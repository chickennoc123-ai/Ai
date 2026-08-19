"""Generation 5, Phases 25-26 — Adversarial tests for the modules this
generation added (research access policy, budget, refuted-family memory,
instrumentation, failure library enrichment, lineage graph), plus a
reproducibility check on the instrumentation replay.

Scoped to what Generation 5 actually built. Categories from the execution
contract's 30-item adversarial list that don't apply to this generation's
delivered scope (e.g. no new candidate was generated, so "rejected
candidate resurrection via a new candidate" has no surface to test beyond
what Generation 4's own adversarial tests already cover) are not
fabricated here.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from core.economic_validation.cost_stress import base_cost_model
from core.economic_validation.data_eligibility import load_raw_ohlcv
from core.economic_validation.evaluation import build_execution_frame
from core.economic_validation.execution import RiskRules
from core.economic_validation.instrumented_execution import execute_instrumented
from core.economic_validation.rule_engine import generate_signals, parse_atr_multiple, parse_entry_rule
from core.factory.failure_library import FailureLibrary, FailureLibraryError
from core.factory.generation5_budget import (
    GenerationFiveBudget, GenerationFiveBudgetError, GenerationFiveBudgetExceededError, GenerationFiveBudgetStore,
)
from core.factory.hypothesis import HypothesisRegistry
from core.factory.lineage_graph import trace_hypothesis_lineage
from core.factory.novelty_engine import FamilyRegistry
from core.factory.refuted_family_memory import (
    UNIVERSAL_REFUTATION_ALLOWLIST, assess_similarity_against_registry, compute_family_refutation_status,
)
from core.factory.registry import StrategyRegistry
from core.factory.research_access_policy import AccessPolicyError, assert_access_failed_not_treated_as_reviewed
from core.factory.research_source_registry import SourceRecord
from core.factory.claim_registry import ClaimRegistry
from core.factory.research_source_registry import ResearchSourceRegistry


# --- 1. refuted-family bypass -------------------------------------------------

def test_close_variant_of_refuted_hypothesis_is_flagged_not_hidden():
    hyp = HypothesisRegistry()
    h2 = hyp.get("HYP-000002")
    assessment = assess_similarity_against_registry(h2.economic_mechanism, hypothesis_registry=hyp, exclude_hypothesis_id="HYP-000002")
    assert "HYP-000001" in assessment.related_refuted_hypotheses


def test_family_refutation_scope_never_silently_upgrades_to_universal():
    fam = FamilyRegistry()
    hyp = HypothesisRegistry()
    record = compute_family_refutation_status("FAMILY-000001", family_registry=fam, hypothesis_registry=hyp)
    assert record.refutation_scope != "REFUTED_UNIVERSALLY"
    assert record.refutation_scope == "REFUTED_UNDER_SPECIFIC_OPERATIONALISATION"
    assert "FAMILY-000001" not in UNIVERSAL_REFUTATION_ALLOWLIST


# --- 2. budget bypass ----------------------------------------------------------

def test_budget_charge_raises_once_exhausted_and_does_not_overshoot(tmp_path):
    store = GenerationFiveBudgetStore(path=tmp_path / "budget.json")
    store.declare(
        GenerationFiveBudget(max_new_hypotheses=1, max_new_candidates=1, max_candidates_per_family=1,
                              max_search_space_size_per_hypothesis=10, max_research_retries=1, max_research_branches=1),
        justification="adversarial test",
    )
    store.charge_hypothesis()
    with pytest.raises(GenerationFiveBudgetExceededError):
        store.charge_hypothesis()
    assert store.usage_summary()["usage"]["new_hypotheses"] == 1  # never overshoots


def test_budget_per_family_candidate_cap_blocks_variant_explosion(tmp_path):
    store = GenerationFiveBudgetStore(path=tmp_path / "budget2.json")
    store.declare(
        GenerationFiveBudget(max_new_hypotheses=10, max_new_candidates=10, max_candidates_per_family=1,
                              max_search_space_size_per_hypothesis=10, max_research_retries=1, max_research_branches=1),
        justification="adversarial test",
    )
    store.charge_candidate(family_id="FAMILY-X")
    with pytest.raises(GenerationFiveBudgetExceededError):
        store.charge_candidate(family_id="FAMILY-X")


def test_budget_redeclare_without_governance_flag_is_refused(tmp_path):
    store = GenerationFiveBudgetStore(path=tmp_path / "budget3.json")
    budget = GenerationFiveBudget(max_new_hypotheses=1, max_new_candidates=1, max_candidates_per_family=1,
                                   max_search_space_size_per_hypothesis=10, max_research_retries=1, max_research_branches=1)
    store.declare(budget, justification="first")
    with pytest.raises(GenerationFiveBudgetError):
        store.declare(budget, justification="silent increase attempt")


def test_budget_limits_must_be_positive_integers():
    with pytest.raises(Exception):
        GenerationFiveBudget(max_new_hypotheses=0, max_new_candidates=1, max_candidates_per_family=1,
                              max_search_space_size_per_hypothesis=10, max_research_retries=1, max_research_branches=1)


# --- 3. source access / provenance downgrade ------------------------------------

def test_access_failed_source_cannot_be_constructed_with_a_checksum():
    """SourceRecord's own __post_init__ enforces this -- verifying the
    guard exists BEFORE relying on the Phase-1 wrapper assertion."""
    with pytest.raises(Exception):
        SourceRecord(
            source_id="SRC2-TEST", source_type="ACADEMIC_PAPER", title="t",
            retrieval_timestamp="2026-01-01T00:00:00+00:00",
            access_status="ACCESS_FAILED", content_checksum="deadbeef",
        )


def test_access_failed_verification_status_mismatch_is_caught():
    record = SourceRecord(
        source_id="SRC2-TEST2", source_type="ACADEMIC_PAPER", title="t",
        retrieval_timestamp="2026-01-01T00:00:00+00:00",
        access_status="ACCESS_FAILED", verification_status="VERIFIED",  # inconsistent on purpose
    )
    with pytest.raises(AccessPolicyError):
        assert_access_failed_not_treated_as_reviewed(record)


def test_production_sources_all_pass_the_access_failed_guard():
    src = ResearchSourceRegistry()
    for s in src.list_all():
        assert_access_failed_not_treated_as_reviewed(s)  # must not raise


# --- 4. lineage break --------------------------------------------------------

def test_lineage_trace_handles_missing_references_without_crashing():
    hyp = HypothesisRegistry()
    claims = ClaimRegistry()
    src = ResearchSourceRegistry()
    strat = StrategyRegistry()
    lib = FailureLibrary()
    trace = trace_hypothesis_lineage(
        "HYP-000001", hypothesis_registry=hyp, claim_registry=claims, source_registry=src,
        strategy_registry=strat, failure_library=lib,
    )
    assert trace.refutation_basis["refuted"] is True
    assert trace.candidates and trace.candidates[0]["candidate_id"] == "STRAT-000002"


# --- 5. append-only discipline (no delete/update surface) ----------------------

def test_failure_library_has_no_mutation_or_delete_method():
    forbidden = {"delete", "remove", "update", "edit", "rewrite", "clear"}
    assert not (forbidden & set(dir(FailureLibrary)))


def test_failure_library_rejects_unknown_reusability_level():
    lib = FailureLibrary(path=Path("/tmp") / "does_not_exist_failure_lib.json")
    with pytest.raises(FailureLibraryError):
        lib.record(entity_id="X", failure_stage="HOLDOUT", failure_category="NO_SIGNAL",
                   failure_reason="test", reusability="NOT_A_REAL_LEVEL")


# --- 6. holdout reuse prevention (instrumentation script's own discipline) -----

def test_holdout_mfe_mae_report_declares_not_computed_not_fabricated():
    import json
    path = REPO_ROOT / "reports" / "generation5" / "MFE_MAE_PURE_HOLDOUT.json"
    assert path.exists(), "run scripts/run_generation5_instrumentation.py first"
    d = json.loads(path.read_text())
    assert d["verdict"] == "NOT_COMPUTED"
    assert d["mfe_r_distribution"] is None and d["mae_r_distribution"] is None
    assert "second access" in d["reason"] or "holdout" in d["reason"].lower()


# --- 7. reproducibility --------------------------------------------------------

def test_instrumented_replay_is_reproducible_across_fresh_calls():
    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")
    full = load_raw_ohlcv(REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv")
    rule = parse_entry_rule(candidate.spec.entry_rule, candidate.spec.direction)
    risk = RiskRules(risk_per_trade=0.02, stop_loss_atr_mult=parse_atr_multiple(candidate.spec.stop_loss),
                      take_profit_atr_mult=parse_atr_multiple(candidate.spec.take_profit),
                      max_holding_bars=int(candidate.spec.max_hold_bars))
    costs = base_cost_model("EURUSD")
    exec_frame, features = build_execution_frame(full)
    signals = generate_signals(features, rule)
    window = exec_frame.loc["2022-01-01":"2022-12-31"]
    sig_window = signals.loc[signals.index.isin(window.index)]

    run1 = execute_instrumented(window, sig_window, costs=costs, risk=risk, candidate_id="STRAT-000002",
                                 instrument="EURUSD", signal_feature_series=features["rsi_14"],
                                 signal_feature_name="rsi_14", rule_version="RULE-R4-001", initial_equity=10_000.0)
    run2 = execute_instrumented(window, sig_window, costs=costs, risk=risk, candidate_id="STRAT-000002",
                                 instrument="EURUSD", signal_feature_series=features["rsi_14"],
                                 signal_feature_name="rsi_14", rule_version="RULE-R4-001", initial_equity=10_000.0)
    assert [t.to_dict() for t in run1] == [t.to_dict() for t in run2]
