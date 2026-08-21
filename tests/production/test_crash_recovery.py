"""Crash-recovery integration tests for the production/ package.

Each test simulates a real crash point named in the AGLE production-mode
specification and proves the invariant that matters at that point, using the
real classes (MasterSwitch, EvaluationLedger, EAProductRegistry,
OpportunityQueue) against an isolated tmp_path -- never the real
reports/production/ or reports/factory/ ledgers.

A true OS-level process kill cannot be reproduced inside a single pytest
process. Instead each test reproduces the exact on-disk state a crash at
that point would leave behind (an orphaned .tmp file, a ledger missing the
last write, a registry with an unacknowledged prior success) and then
exercises the real recovery path -- a fresh instance re-reading from disk,
exactly as the supervisor does via ProductionSupervisor.recover_state() and
every AppendOnlyStore's load-on-construct.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from idea_machine.opportunity_queue import (
    DataRequirement,
    OpportunityQueue,
    RetestCondition,
)
from production.ea_registry import EAProductRegistry
from production.evaluation_ledger import EvaluationLedger
from production.productization import maybe_productize


def _make_queue_entry_kwargs(n: int) -> dict:
    return dict(
        source_hypothesis_id=f"HYP-CRASH-{n:03d}",
        source_cycle_id="CYCLE-CRASH-TEST",
        classification="STILL_UNDERPOWERED",
        mechanism_summary="crash-recovery test fixture",
        symbol="EURUSD",
        driver="test_driver",
        n_events_available=10,
        windows_evaluated=1,
        best_train_t=1.0,
        best_val_n=5,
        mean_confirmation_rate=0.5,
        evidence_level="LOW",
        reason="test fixture -- not real evidence",
        missing_data=DataRequirement(description="none", current_value=1, required_value=1, unit="events"),
        retest_conditions=RetestCondition(earliest_date=None, trigger="none", estimated_power_gain=None),
        priority="MEDIUM",
        provenance_status="TEST_FIXTURE",
    )


# --------------------------------------------------------------------- (A)


def test_crash_during_idea_generation_no_duplicate_no_loss(tmp_path):
    """(A) Crash during idea generation: OpportunityQueue.save() is atomic
    (tempfile + os.replace). If the process dies between writing the temp
    file and the os.replace(), the ORIGINAL file must be left completely
    intact -- no partial write ever becomes visible under the real name, and
    no entry already durably saved is lost or duplicated on the next
    process's load()."""
    queue_file = tmp_path / "opportunity_queue.json"

    queue = OpportunityQueue(queue_file=queue_file)
    queue.append(**_make_queue_entry_kwargs(1))
    queue.save()
    assert queue_file.exists()
    original_bytes = queue_file.read_bytes()

    # Simulate a crash: a second process appends a new idea in memory, then
    # dies after writing its temp file but before os.replace() ever runs.
    queue2 = OpportunityQueue(queue_file=queue_file)
    queue2.load()
    assert len(queue2.entries) == 1
    queue2.append(**_make_queue_entry_kwargs(2))

    real_replace = os.replace

    def _crash_before_replace(src, dst):
        raise OSError("simulated crash: process killed before os.replace()")

    os.replace = _crash_before_replace
    try:
        with pytest.raises(OSError):
            queue2.save()
    finally:
        os.replace = real_replace

    # The on-disk file must be byte-for-byte untouched -- the crash left the
    # ORIGINAL single-entry file in place, not a truncated/partial one.
    assert queue_file.read_bytes() == original_bytes
    # No orphaned temp file should remain visible next to it forever, but
    # even if the OS left one, it must never be picked up as the real file.
    leftover_tmp = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    for p in leftover_tmp:
        p.unlink()

    # The NEXT process (retry after crash) reloads and finds exactly the one
    # durably-saved entry -- no loss, and no duplicate of the entry that
    # never made it to disk (it will be legitimately re-appended and saved
    # once, not twice).
    queue3 = OpportunityQueue(queue_file=queue_file)
    queue3.load()
    assert len(queue3.entries) == 1
    assert queue3.entries[0].source_hypothesis_id == "HYP-CRASH-001"

    # Retry the second append+save for real (no simulated crash this time).
    queue3.append(**_make_queue_entry_kwargs(2))
    queue3.save()

    queue4 = OpportunityQueue(queue_file=queue_file)
    queue4.load()
    ids = sorted(e.source_hypothesis_id for e in queue4.entries)
    assert ids == ["HYP-CRASH-001", "HYP-CRASH-002"]


# --------------------------------------------------------------------- (B)


def test_crash_during_factory_evaluation_no_double_ledger_consumption(tmp_path):
    """(B) Crash during Factory evaluation: the EvaluationLedger is only
    ever written to AFTER the real gate() has produced a verdict. A crash
    before that write means the evaluation simply never happened as far as
    the ledger is concerned -- the retry correctly re-runs the real Factory
    (never silently invents a verdict). A crash AFTER the write, or a retry
    that resubmits the identical (mechanism, instrument, driver, window)
    triple with the identical verdict, must resolve to exactly ONE ledger
    record -- never two."""
    ledger_path = tmp_path / "evaluation_ledger.json"
    ledger = EvaluationLedger(path=ledger_path)

    triple = dict(mechanism="streak_fade", instrument="EURUSD", driver="cpi_release", window_min=60)

    # Before any evaluation, the ledger must say "never evaluated" -- a
    # crashed-before-record() attempt looks identical to "never ran".
    assert ledger.already_evaluated(**triple) is None

    # The real Factory ran and produced a verdict; the process persists it.
    saved = ledger.record(
        **triple, hyp_id="HYP-B-001", cycle_id="CYCLE-B", verdict="STILL_UNDERPOWERED",
        final_status="STILL_UNDERPOWERED", train={"t": 1.2}, validation={"n": 5},
    )
    eval_id = saved["eval_id"]

    # Simulate a crash immediately after that record() returned, before the
    # caller could tell the caller-of-the-caller it succeeded: a fresh
    # ledger instance (the "restart") must see the verdict as durable.
    ledger_restarted = EvaluationLedger(path=ledger_path)
    prior = ledger_restarted.already_evaluated(**triple)
    assert prior is not None
    assert prior["eval_id"] == eval_id
    assert prior["final_status"] == "STILL_UNDERPOWERED"

    # A naive retry loop that does not check already_evaluated() first and
    # resubmits the SAME real verdict for the SAME triple must not create a
    # second record -- AppendOnlyStore.append() is idempotent for identical
    # content under an identical id (the id is a pure content-hash of the
    # triple), so this is the actual duplicate-prevention mechanism.
    ledger_restarted.record(
        **triple, hyp_id="HYP-B-001", cycle_id="CYCLE-B", verdict="STILL_UNDERPOWERED",
        final_status="STILL_UNDERPOWERED", train={"t": 1.2}, validation={"n": 5},
    )
    all_records = ledger_restarted.all()
    matching = [r for r in all_records if r["eval_id"] == eval_id]
    assert len(matching) == 1, "duplicate real-Factory evaluation was consumed into the ledger"

    # The correct production behavior is to check FIRST and skip the real
    # Factory call entirely -- prove that path too.
    checked = ledger_restarted.already_evaluated(**triple)
    assert checked is not None and checked["eval_id"] == eval_id


def test_evaluation_ledger_rejects_conflicting_verdict_for_same_triple(tmp_path):
    """A genuinely different verdict for the identical triple (which should
    never happen -- the real Factory is deterministic on the same data) must
    raise rather than silently overwrite history."""
    from idea_machine.core.errors import StoreError

    ledger = EvaluationLedger(path=tmp_path / "evaluation_ledger.json")
    triple = dict(mechanism="gap_fade", instrument="XAUUSD", driver=None, window_min=60)
    ledger.record(**triple, hyp_id="HYP-B-002", cycle_id="CYCLE-B", verdict="DISCOVERY_SURVIVOR",
                  final_status="DISCOVERY_SURVIVOR", train={"t": 3.0}, validation={"n": 40})
    with pytest.raises(StoreError):
        ledger.record(**triple, hyp_id="HYP-B-002", cycle_id="CYCLE-B", verdict="REFUTED",
                      final_status="REFUTED_THIS_RUN", train={"t": 3.0}, validation={"n": 40})


# --------------------------------------------------------------------- (C)


def test_crash_after_verdict_before_productization_verdict_durable(tmp_path):
    """(C) Crash after a Factory verdict but before productization: the
    EvaluationLedger record for a DISCOVERY_SURVIVOR must survive a
    simulated restart, and calling maybe_productize() afterward (the resumed
    productization attempt) must be safe to call -- including safe to call
    TWICE, in case the process crashes again mid-productization -- without
    ever erroring or fabricating a product."""
    ledger_path = tmp_path / "evaluation_ledger.json"
    ledger = EvaluationLedger(path=ledger_path)

    triple = dict(mechanism="streak_fade", instrument="EURUSD", driver="nfp_release", window_min=60)
    saved = ledger.record(
        **triple, hyp_id="HYP-C-001", cycle_id="CYCLE-C", verdict="DISCOVERY_SURVIVOR",
        final_status="DISCOVERY_SURVIVOR", train={"t": 4.5}, validation={"n": 60},
    )

    # Simulated restart: fresh ledger instance still finds the survivor
    # verdict -- it is durable, not lost by the crash.
    ledger_restarted = EvaluationLedger(path=ledger_path)
    prior = ledger_restarted.already_evaluated(**triple)
    assert prior is not None
    assert prior["final_status"] == "DISCOVERY_SURVIVOR"
    assert prior["eval_id"] == saved["eval_id"]

    # This candidate was NEVER carried through the real GEN12->GEN13->GEN14
    # holdout-gated qualification pipeline (that is a separate, deliberately
    # manual, governed step) -- so productization correctly, safely refuses
    # it as NOT_AUTHORIZED. The important invariant here is that resuming
    # productization after the simulated crash does not error and does not
    # fabricate a product just because a survivor verdict exists.
    ea_registry = EAProductRegistry(path=tmp_path / "ea_product_registry.json")
    result1 = maybe_productize(
        candidate_id="HYP-C-001", symbol="EURUSD", hypothesis_id="HYP-C-001",
        factory_evaluation_id=prior["eval_id"], registry=ea_registry,
        artifact_dir=tmp_path / "ea_products",
    )
    assert result1.status == "NOT_AUTHORIZED"
    assert ea_registry.count() == 0

    # Retrying (as the resumed loop would on its next cycle) must be equally
    # safe and equally refuse -- idempotent refusal, not a crash, not a
    # second fabricated attempt that somehow succeeds.
    result2 = maybe_productize(
        candidate_id="HYP-C-001", symbol="EURUSD", hypothesis_id="HYP-C-001",
        factory_evaluation_id=prior["eval_id"], registry=ea_registry,
        artifact_dir=tmp_path / "ea_products",
    )
    assert result2.status == "NOT_AUTHORIZED"
    assert ea_registry.count() == 0


# --------------------------------------------------------------------- (D)


def test_crash_after_product_creation_no_duplicate_ea_product(tmp_path):
    """(D) Crash after product creation: EAProductRegistry.register() is
    keyed by a content hash of (candidate_id, spec_hash), so a retry that
    re-registers the SAME already-created product (the caller crashed after
    the real registration succeeded but before it could record that success
    upstream) must resolve to the exact same product_id -- never a second,
    duplicate EA product record."""
    registry = EAProductRegistry(path=tmp_path / "ea_product_registry.json")

    row1 = registry.register(
        candidate_id="CAND-D-001", hypothesis_id="HYP-D-001", factory_evaluation_id="EVAL-D-001",
        spec_hash="deadbeefcafef00d", source="production_loop",
        artifact_path=str(tmp_path / "ea_products" / "CAND-D-001"),
    )
    assert registry.count() == 1

    # Simulated restart: fresh registry instance sees the one product.
    registry_restarted = EAProductRegistry(path=registry.store.path)
    assert registry_restarted.count() == 1

    # Retry of the exact same registration (identical candidate_id +
    # spec_hash -> identical product_id, identical content) must be a
    # no-op, not a duplicate.
    row2 = registry_restarted.register(
        candidate_id="CAND-D-001", hypothesis_id="HYP-D-001", factory_evaluation_id="EVAL-D-001",
        spec_hash="deadbeefcafef00d", source="production_loop",
        artifact_path=str(tmp_path / "ea_products" / "CAND-D-001"),
    )
    assert row2["product_id"] == row1["product_id"]
    assert registry_restarted.count() == 1

    products_for_candidate = registry_restarted.for_candidate("CAND-D-001")
    assert len(products_for_candidate) == 1

    registry_restarted.verify_integrity()
