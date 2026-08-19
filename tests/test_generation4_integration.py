"""Generation 4 integration — the committed evidence must be real and consistent.

These tests read the artifacts under ``reports/generation4/`` that the
Generation 4 run actually produced and check that they hang together:
that the evidence chain is complete, that every artifact belongs to the
same frozen candidate and the same validation run, that the EVG's verdict
follows from the evidence it was given, and — the one that matters most —
that the PURE_HOLDOUT result reproduces byte-for-byte from the committed
data and the committed specification.

A reproducibility test that re-derives the number from source is worth
more than any number of assertions about the number, so that is what the
central test here does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from core.economic_validation.candidate_freeze import CandidateFreezeSnapshot, verify_unchanged
from core.economic_validation.cost_stress import base_cost_model
from core.economic_validation.data_eligibility import audit_dataset, load_raw_ohlcv
from core.economic_validation.evaluation import evaluate_partition
from core.economic_validation.evg import REQUIRED_EVIDENCE
from core.economic_validation.execution import RiskRules
from core.economic_validation.rule_engine import parse_atr_multiple, parse_entry_rule
from core.factory.dataset_registry import DatasetRegistry
from core.factory.registry import StrategyRegistry
from core.factory.research_ledger import ResearchLedger
from core.factory.state_machine import CandidateState

REPO_ROOT = Path(__file__).resolve().parents[1]
G4 = REPO_ROOT / "reports" / "generation4"

ARTIFACTS = [
    "CANDIDATE_FREEZE_SNAPSHOT.json",
    "DATA_ELIGIBILITY.json",
    "PARTITION_BOUNDARIES.json",
    "FEATURE_TEMPORAL_AUDIT.json",
    "PARSED_RULE.json",
    "EVALUATION_DEVELOPMENT.json",
    "TARGET_LEAKAGE_AUDIT.json",
    "EVALUATION_OOS.json",
    "WALK_FORWARD.json",
    "ROBUSTNESS.json",
    "COST_STRESS.json",
    "EVALUATION_REUSABLE_COMBINED.json",
    "STATISTICAL_VALIDATION.json",
    "MULTIPLE_TESTING.json",
    "SEARCH_ACCOUNTING.json",
    "HOLDOUT_RELEASE_RECORD.json",
    "EVALUATION_PURE_HOLDOUT.json",
    "STATISTICAL_VALIDATION_HOLDOUT.json",
    "EVG_REPORT.json",
    "SEARCH_ACCOUNTING_RECONCILIATION.json",
    "GENERATION4_SUMMARY.json",
]


def _load(name: str):
    return json.loads((G4 / name).read_text())


@pytest.fixture(scope="module")
def summary():
    return _load("GENERATION4_SUMMARY.json")


@pytest.fixture(scope="module")
def snapshot():
    return CandidateFreezeSnapshot.read(G4 / "CANDIDATE_FREEZE_SNAPSHOT.json")


def test_every_generation4_artifact_was_produced():
    missing = [name for name in ARTIFACTS if not (G4 / name).exists()]
    assert missing == [], f"Generation 4 artifacts missing: {missing}"


def test_freeze_snapshot_is_internally_consistent(snapshot):
    assert snapshot.snapshot_checksum == snapshot.content_checksum()
    assert snapshot.validation_run_id.endswith(snapshot.snapshot_checksum[:16])
    assert snapshot.model_specification == "NONE_DETERMINISTIC_RULE"
    assert snapshot.hyperparameters == {}
    assert snapshot.instrument_scope == ("EURUSD",)


def test_frozen_candidate_was_never_mutated(snapshot):
    """The registry's candidate must still match the freeze snapshot exactly."""
    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")
    verify_unchanged(snapshot, candidate, dataset_registry=DatasetRegistry())
    assert candidate.version == snapshot.candidate_version == 1


def test_every_artifact_belongs_to_one_candidate_and_one_run(summary):
    run_id = summary["validation_run_id"]
    for name in ("EVALUATION_DEVELOPMENT.json", "EVALUATION_OOS.json", "EVALUATION_PURE_HOLDOUT.json",
                 "WALK_FORWARD.json", "ROBUSTNESS.json", "COST_STRESS.json",
                 "STATISTICAL_VALIDATION.json", "MULTIPLE_TESTING.json", "EVG_REPORT.json"):
        artifact = _load(name)
        assert artifact["candidate_id"] == "STRAT-000002", name
        assert artifact["validation_run_id"] == run_id, name


def test_data_eligibility_reproduces_from_the_committed_bytes():
    committed = _load("DATA_ELIGIBILITY.json")
    registry = DatasetRegistry()
    fresh = audit_dataset(registry.get(committed["dataset_id"]),
                          expected_instrument="EURUSD", expected_timeframe="H1")
    assert fresh.verdict == committed["verdict"] == "ELIGIBLE"
    assert fresh.report_checksum() == _report_checksum_of(committed)
    assert fresh.real_market_data is True
    assert fresh.gap_classification["unexplained_gaps"] == 0


def _report_checksum_of(committed: dict) -> str:
    """Recompute a committed report's own checksum from its stored fields."""
    import hashlib

    d = dict(committed)
    d.pop("audit_timestamp", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def test_partitions_are_chronological_and_non_overlapping():
    b = _load("PARTITION_BOUNDARIES.json")
    train_end = pd.Timestamp(b["train_end"])
    val_start, val_end = pd.Timestamp(b["validation_start"]), pd.Timestamp(b["validation_end"])
    holdout_start = pd.Timestamp(b["holdout_start"])
    assert train_end < val_start < val_end < holdout_start
    assert b["development_fraction"] == 0.6 and b["validation_fraction"] == 0.2
    assert b["development_rows"] + b["validation_rows"] + b["holdout_rows"] == 57_600


def test_holdout_was_released_only_after_the_development_evidence_existed():
    release = _load("HOLDOUT_RELEASE_RECORD.json")
    assert release["candidate_id"] == "STRAT-000002"
    assert release["development_evidence_reference"].strip()
    assert release["reason_for_release"].strip()
    boundaries = _load("PARTITION_BOUNDARIES.json")
    assert release["holdout_start"] == boundaries["holdout_start"]
    assert release["holdout_rows"] == boundaries["holdout_rows"]


def test_pure_holdout_result_reproduces_from_source():
    """The headline holdout number must be re-derivable, not merely stored."""
    committed = _load("EVALUATION_PURE_HOLDOUT.json")
    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")

    full = load_raw_ohlcv(REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv")
    rule = parse_entry_rule(candidate.spec.entry_rule, candidate.spec.direction)
    risk = RiskRules(
        risk_per_trade=0.02,
        stop_loss_atr_mult=parse_atr_multiple(candidate.spec.stop_loss),
        take_profit_atr_mult=parse_atr_multiple(candidate.spec.take_profit),
        max_holding_bars=int(candidate.spec.max_hold_bars),
    )
    record = evaluate_partition(
        full,
        evaluation_start=pd.Timestamp(committed["evaluation_start"]),
        rule=rule,
        costs=base_cost_model("EURUSD"),
        risk=risk,
        candidate_id=committed["candidate_id"],
        validation_run_id=committed["validation_run_id"],
        partition_name="PURE_HOLDOUT",
        dataset_checksum=committed["signal_provenance"]["dataset_checksum"],
        code_version=committed["signal_provenance"]["code_version"],
    )
    assert record.result_checksum() == _stored_result_checksum(committed)
    assert record.metrics["net_profit"] == pytest.approx(committed["metrics"]["net_profit"], rel=1e-12)
    assert record.metrics["trade_count"] == committed["metrics"]["trade_count"]


def _stored_result_checksum(committed: dict) -> str:
    import hashlib

    d = dict(committed)
    d.pop("evaluation_timestamp", None)
    prov = dict(d.get("signal_provenance") or {})
    prov.pop("timestamp", None)
    d["signal_provenance"] = prov
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def test_walk_forward_retained_every_window():
    wfa = _load("WALK_FORWARD.json")
    assert len(wfa["windows"]) == wfa["n_windows"]
    assert [w["window_id"] for w in wfa["windows"]] == list(range(1, wfa["n_windows"] + 1))
    total = sum(w["net_profit"] for w in wfa["windows"])
    assert total == pytest.approx(wfa["aggregate"]["total_net_profit"], rel=1e-9)
    # Windows must be contiguous and non-overlapping in time.
    ends = [pd.Timestamp(w["test_end"]) for w in wfa["windows"]]
    starts = [pd.Timestamp(w["test_start"]) for w in wfa["windows"]]
    assert all(ends[i] < starts[i + 1] for i in range(len(ends) - 1))


def test_robustness_reports_the_whole_surface_and_names_no_best_point():
    rob = _load("ROBUSTNESS.json")
    grid = rob["grid"]
    expected = (len(grid["rsi_threshold"]) * len(grid["stop_loss_atr_mult"])
                * len(grid["take_profit_atr_mult"]) * len(grid["max_holding_bars"])
                * len(grid["entry_delay_bars"]))
    assert len(rob["points"]) == expected == rob["surface_summary"]["n_points"]
    assert rob["pre_registered"] is False
    assert "NOT PRE-REGISTERED" in rob["declaration"]
    assert "best" not in rob["surface_summary"]
    assert sum(1 for p in rob["points"] if p["is_frozen_point"]) == 1


def test_cost_stress_includes_a_zero_cost_diagnostic_and_labels_it_as_such():
    cost = _load("COST_STRESS.json")
    labels = [s["label"] for s in cost["scenarios"]]
    for required in ("ZERO_COST", "BASE", "REALISTIC_SPREAD", "1X_SLIPPAGE", "2X_SLIPPAGE", "3X_SLIPPAGE"):
        assert required in labels, required
    zero = next(s for s in cost["scenarios"] if s["label"] == "ZERO_COST")
    assert zero["total_costs_paid"] == 0.0
    assert "Never economic evidence" in zero["note"]
    assert cost["assumptions"]["confirmed_against_broker_feed"] is False


def test_statistics_use_a_serial_dependence_aware_method():
    stats = _load("STATISTICAL_VALIDATION.json")
    methods = {i["method"] for i in stats["intervals"]}
    assert "BLOCK_BOOTSTRAP" in methods
    assert stats["methodology"]["primary_method"] == "moving-block bootstrap"
    assert stats["methodology"]["deterministic"] is True


def test_multiple_testing_keeps_the_three_statuses_separate():
    mt = _load("MULTIPLE_TESTING.json")
    assert mt["accounting_status"] == "ACCOUNTING_COMPLETE"
    assert mt["statistical_correction_status"] == "STATISTICAL_CORRECTION_COMPLETE"
    assert mt["economic_edge_status"] != "ECONOMIC_EDGE_SUPPORTED"
    assert "NEARLY_UNINFORMATIVE" in mt["correction_meaningfulness"]
    assert mt["effective_trials"] == mt["total_candidates"]


def test_evg_consumed_the_complete_chain_and_its_verdict_follows(summary):
    evg = _load("EVG_REPORT.json")
    assert set(evg["evidence_present"]) == set(REQUIRED_EVIDENCE)
    assert evg["evidence_missing"] == []
    assert evg["blocking_reasons"] == []
    assert evg["verdict"] == "FAIL"
    assert evg["refuting_observations"], "a FAIL must name what refuted the candidate"
    assert evg["snapshot_checksum"] == summary["snapshot_checksum"]


def test_candidate_reached_rejected_through_the_full_committed_spine():
    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")
    assert candidate.state is CandidateState.REJECTED
    states = [h["state"] for h in candidate.history]
    for required in ("DATA_VALIDATED", "TRAINED", "OOS_TESTED", "WFA_TESTED", "ROBUSTNESS_TESTED",
                     "COST_TESTED", "STATISTICALLY_VALIDATED", "MULTIPLE_TESTING_REVIEWED",
                     "FROZEN", "HOLDOUT_TESTED", "EVG_REVIEW", "REJECTED"):
        assert required in states, required
    assert states.index("FROZEN") < states.index("HOLDOUT_TESTED")
    assert states.index("MULTIPLE_TESTING_REVIEWED") < states.index("FROZEN")


def test_the_ledger_recorded_the_generation4_events():
    ledger = ResearchLedger()
    events = {e.event_type for e in ledger.events_for_subject("STRAT-000002")}
    for required in ("HOLDOUT_EVALUATED", "EVG_VERDICT", "CANDIDATE_REJECTED", "CANDIDATE_CLASSIFIED"):
        assert required in events, required


def test_search_accounting_reconciles():
    rec = _load("SEARCH_ACCOUNTING_RECONCILIATION.json")
    assert rec["status"] == "PASS"
    assert rec["mismatches"] == []
    # Any counter that legitimately differs must be enumerated, not omitted.
    for divergence in rec["definitional_divergences"]:
        assert divergence["reason"].strip()
        assert divergence["recomputed"] != divergence["stored"]


def test_no_synthetic_data_entered_the_economic_evidence():
    eligibility = _load("DATA_ELIGIBILITY.json")
    assert eligibility["declared_synthetic"] is False
    assert eligibility["real_market_data"] is True
    snapshot = _load("CANDIDATE_FREEZE_SNAPSHOT.json")
    assert snapshot["dataset_identity"]["synthetic"] is False
    assert snapshot["dataset_identity"]["provenance_status"] in ("VERIFIED", "VERIFIED_WITH_QUALIFICATION")


def test_generation6_has_not_started():
    """No Generation 6 *execution* may exist.

    Governance note (contract change, documented not silent): this test
    was originally named ``test_generation5_has_not_started`` and asserted
    that NO Generation 5 execution existed at all. That became the wrong
    boundary the moment the product owner issued the full Generation 5
    execution contract ("INSTRUMENTATION, RESEARCH MEMORY & CONTROLLED
    DISCOVERY") -- Generation 5 code, tests, and
    ``reports/generation5/`` artifacts are now the AUTHORIZED, IN-PROGRESS
    deliverable of that contract, not evidence of an unauthorized jump
    ahead. The boundary this project must keep enforcing is the one the
    contract itself states explicitly: Generation 5 may complete, but
    Generation 6 may not begin.

    The assertions below are the Generation-6 analogue of the original
    Generation-5 guard, plus budget-bounded (not frozen-at-zero) checks on
    the candidate/hypothesis population, since Generation 5's own
    execution contract explicitly permits a small number of new
    hypotheses/candidates under ``core.factory.generation5_budget``.
    """
    # no Generation 6 run artifacts or implementation code
    assert not (REPO_ROOT / "reports" / "generation6").exists()
    assert not list((REPO_ROOT / "core" / "factory").glob("*generation6*"))
    assert not list((REPO_ROOT / "scripts").glob("*generation6*"))
    assert not list((REPO_ROOT / "scripts").glob("*run_generation6*"))

    # STRAT-000001 and STRAT-000002 remain terminal and are never
    # resurrected, regardless of how many new candidates Generation 5 adds.
    registry = StrategyRegistry()
    ids = {c.candidate_id for c in registry.list_all()}
    assert {"STRAT-000001", "STRAT-000002"} <= ids
    original = [c for c in registry.list_all() if c.candidate_id in ("STRAT-000001", "STRAT-000002")]
    assert all(c.state == CandidateState.REJECTED for c in original)

    # the candidate/hypothesis population may grow, but only within
    # Generation 5's own declared, immutable budget -- never silently.
    from core.factory.generation5_budget import GenerationFiveBudgetStore
    from core.factory.hypothesis import HypothesisRegistry

    hypothesis_registry = HypothesisRegistry(path=REPO_ROOT / "reports" / "factory" / "hypothesis_registry.json")
    original_hyp_ids = {"HYP-000001", "HYP-000002", "HYP-000003"}
    new_hyp_ids = {h.hypothesis_id for h in hypothesis_registry.list_all()} - original_hyp_ids
    new_candidate_ids = ids - {"STRAT-000001", "STRAT-000002"}

    if new_hyp_ids or new_candidate_ids:
        store = GenerationFiveBudgetStore()
        assert store.declared, "new hypotheses/candidates exist but no Generation 5 budget was ever declared"
        budget = store.usage_summary()["budget"]
        assert len(new_hyp_ids) <= budget["max_new_hypotheses"]
        assert len(new_candidate_ids) <= budget["max_new_candidates"]

    # no Generation 6 document exists at all yet.
    assert not list(REPO_ROOT.glob("ML-001-GENERATION-6-*.md"))
