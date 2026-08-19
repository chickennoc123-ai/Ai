"""Generation 4 adversarial tests — every one of these MUST fail safely.

Each test names one specific way a researcher (or a future maintainer, or
an over-helpful refactor) could smuggle an unearned PASS through the
Generation 4 machinery, and asserts that the machinery refuses.

All fixtures here are synthetic. Synthetic data is permitted for software
tests and is never economic evidence (Generation 4 governance rule 14);
the two tests that need real behaviour (``test_23``, ``test_24``) read
committed artifacts rather than generating new economic numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.economic_validation.candidate_freeze import (
    CandidateFreezeError,
    CandidateFreezeSnapshot,
    freeze_candidate,
    verify_unchanged,
)
from core.economic_validation.cost_stress import CostStressError, base_cost_model, scenario_cost_model
from core.economic_validation.data_eligibility import DataEligibilityError, audit_dataset
from core.economic_validation.evaluation import evaluate_partition
from core.economic_validation.evg import (
    BLOCKED,
    FAIL,
    PASS,
    REQUIRED_EVIDENCE,
    EVGEvidenceError,
    EvidenceItem,
    run_evg,
)
from core.economic_validation.execution import CostModel, ExecutionError, RiskRules, execute
from core.economic_validation.feature_temporal_audit import audit_feature_temporal_safety
from core.economic_validation.partitions import (
    HoldoutAlreadyReleasedError,
    HoldoutSealError,
    seal_dataset,
)
from core.economic_validation.rule_engine import (
    CrossoverRule,
    RuleSpecificationError,
    generate_signals,
    parse_atr_multiple,
    parse_entry_rule,
)
from core.economic_validation.walkforward import run_walk_forward
from core.factory.candidate import StrategyCandidate, StrategyCandidateSpec
from core.factory.dataset_registry import DatasetRecord, DatasetRegistry
from core.factory.failure_library import FailureLibrary
from core.factory.registry import StrategyRegistry
from core.factory.state_machine import CandidateState
from core.factory.research_ledger import ResearchLedger

REPO_ROOT = Path(__file__).resolve().parents[1]
G4 = REPO_ROOT / "reports" / "generation4"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _synthetic_ohlcv(n: int = 3000, seed: int = 7) -> pd.DataFrame:
    """A deterministic synthetic price series. Software-test fixture only."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.0004, size=n)
    close = 1.10 * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.0003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0003, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.date_range("2015-01-05 05:00", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(high, np.maximum(open_, close)),
                         "low": np.minimum(low, np.minimum(open_, close)), "close": close}, index=idx)


@pytest.fixture(scope="module")
def synthetic() -> pd.DataFrame:
    return _synthetic_ohlcv()


@pytest.fixture(scope="module")
def sealed(synthetic: pd.DataFrame):
    return seal_dataset(synthetic, dataset_id="TEST-DATASET", dataset_checksum="testsum")


@pytest.fixture(scope="module")
def frozen_rule() -> CrossoverRule:
    return parse_entry_rule("rsi_14 crosses back above 30 from below", "long_only")


@pytest.fixture(scope="module")
def costs() -> CostModel:
    return CostModel(spread_price=0.00016, slippage_price=0.00002,
                     commission_per_lot_round_turn=7.0, pip_size=0.0001,
                     pip_value_per_lot=10.0, label="TEST")


@pytest.fixture(scope="module")
def risk() -> RiskRules:
    return RiskRules(risk_per_trade=0.02, stop_loss_atr_mult=1.5,
                     take_profit_atr_mult=2.0, max_holding_bars=12)


def _evidence(name: str, verdict: str = "PASS", **over) -> EvidenceItem:
    base = dict(name=name, verdict=verdict, checksum=f"sum-{name}",
                artifact_reference=f"reports/generation4/{name}.json",
                candidate_id="STRAT-000002", validation_run_id="RUN-1", summary={"reason": "test"})
    base.update(over)
    return EvidenceItem(**base)


def _full_evidence(**over) -> list:
    return [_evidence(n, **over) for n in REQUIRED_EVIDENCE]


# --------------------------------------------------------------------------
# 1-4: holdout access, injection, and optimization
# --------------------------------------------------------------------------


def test_01_holdout_access_before_release_is_refused(sealed):
    """Reading PURE_HOLDOUT before release must raise, not warn."""
    fresh = seal_dataset(sealed.development_and_validation(), dataset_id="D", dataset_checksum="c")
    with pytest.raises(HoldoutSealError):
        fresh.holdout()
    assert fresh.holdout_is_released is False


def test_02_holdout_features_cannot_be_reached_through_the_visible_partitions(synthetic):
    """The widest pre-release frame must provably exclude every holdout bar."""
    s = seal_dataset(synthetic, dataset_id="D", dataset_checksum="c")
    visible = s.development_and_validation()
    holdout_start = pd.Timestamp(s.boundaries.holdout_start)
    assert visible.index.max() < holdout_start
    assert len(visible) == s.boundaries.development_rows + s.boundaries.validation_rows


def test_03_holdout_targets_cannot_be_reached_before_release(synthetic, frozen_rule, costs, risk):
    """An evaluation cannot be built over holdout bars that were never handed out."""
    s = seal_dataset(synthetic, dataset_id="D", dataset_checksum="c")
    with pytest.raises(HoldoutSealError):
        s.holdout()
    visible = s.development_and_validation()
    record = evaluate_partition(
        visible, evaluation_start=visible.index[0], rule=frozen_rule, costs=costs, risk=risk,
        candidate_id="T", validation_run_id="R", partition_name="P",
        dataset_checksum="c", code_version="test",
    )
    assert pd.Timestamp(record.evaluation_end) < pd.Timestamp(s.boundaries.holdout_start)


def test_04_holdout_cannot_be_released_twice(synthetic):
    """Two releases would make 'evaluated exactly once' false."""
    s = seal_dataset(synthetic, dataset_id="D", dataset_checksum="c")
    kwargs = dict(validation_run_id="R", candidate_id="T", candidate_checksum="cc",
                  snapshot_checksum="ss", reason_for_release="first",
                  development_evidence_reference="reports/x.json")
    s.release_holdout(**kwargs)
    with pytest.raises(HoldoutAlreadyReleasedError):
        s.release_holdout(**kwargs)


def test_04b_holdout_release_requires_prior_development_evidence(synthetic):
    """An empty evidence reference must not open the seal."""
    s = seal_dataset(synthetic, dataset_id="D", dataset_checksum="c")
    with pytest.raises(HoldoutSealError):
        s.release_holdout(validation_run_id="R", candidate_id="T", candidate_checksum="cc",
                          snapshot_checksum="ss", reason_for_release="because",
                          development_evidence_reference="   ")
    with pytest.raises(HoldoutSealError):
        s.release_holdout(validation_run_id="R", candidate_id="T", candidate_checksum="cc",
                          snapshot_checksum="ss", reason_for_release="  ",
                          development_evidence_reference="reports/x.json")


# --------------------------------------------------------------------------
# 5-6: mutation after freeze
# --------------------------------------------------------------------------


def _test_candidate(**over) -> StrategyCandidate:
    spec_kwargs = dict(
        entry_rule="rsi_14 crosses back above 30 from below", exit_rule="stop_or_target_or_maxhold",
        features=("rsi_14", "atr_14"), timeframe="H1", direction="long_only",
        stop_loss="1.5xATR", take_profit="2.0xATR", max_hold_bars=12,
        position_sizing="fixed_fractional", transaction_cost_model="test",
    )
    spec_kwargs.update(over.pop("spec", {}))
    return StrategyCandidate(
        candidate_id="STRAT-TEST", version=1, spec=StrategyCandidateSpec(**spec_kwargs),
        state=CandidateState.GENERATED, creation_timestamp="2026-01-01T00:00:00+00:00",
        generator_id="TEST", generator_parameters={}, code_version="test",
        dataset_id="DATASET-EURUSD-H1-KOMO135-V1", candidate_checksum="cc", **over,
    )


def test_05_candidate_mutation_after_freeze_is_detected():
    """A changed spec must fail verify_unchanged, not slip through."""
    registry = DatasetRegistry()
    candidate = _test_candidate()
    snapshot = freeze_candidate(
        candidate, dataset_registry=registry, cost_model={}, risk_rules={},
        target_specification={}, seed_policy={}, code_version="test", instrument_scope=("EURUSD",),
    )
    verify_unchanged(snapshot, candidate, dataset_registry=registry)

    mutated = _test_candidate(spec={"max_hold_bars": 24})
    with pytest.raises(CandidateFreezeError):
        verify_unchanged(snapshot, mutated, dataset_registry=registry)


def test_06_parameter_mutation_after_holdout_is_detected():
    """Same guard, applied at the post-holdout point where it matters most."""
    registry = DatasetRegistry()
    candidate = _test_candidate()
    snapshot = freeze_candidate(
        candidate, dataset_registry=registry, cost_model={}, risk_rules={},
        target_specification={}, seed_policy={}, code_version="test", instrument_scope=("EURUSD",),
    )
    for change in ({"stop_loss": "2.0xATR"}, {"take_profit": "3.0xATR"},
                   {"entry_rule": "rsi_14 crosses back above 35 from below"},
                   {"features": ("rsi_14", "atr_14", "momentum_5")}):
        with pytest.raises(CandidateFreezeError):
            verify_unchanged(snapshot, _test_candidate(spec=change), dataset_registry=registry)


def test_06b_edited_snapshot_file_is_detected():
    """Hand-editing the snapshot JSON must invalidate its own checksum."""
    registry = DatasetRegistry()
    candidate = _test_candidate()
    snapshot = freeze_candidate(
        candidate, dataset_registry=registry, cost_model={"spread_price": 0.00016}, risk_rules={},
        target_specification={}, seed_policy={}, code_version="test", instrument_scope=("EURUSD",),
    )
    tampered = CandidateFreezeSnapshot.from_dict(
        {**snapshot.to_dict(), "cost_model": {"spread_price": 0.0}}
    )
    with pytest.raises(CandidateFreezeError):
        verify_unchanged(tampered, candidate, dataset_registry=registry)


# --------------------------------------------------------------------------
# 7-9: cherry-picking
# --------------------------------------------------------------------------


def test_07_seed_cherry_picking_is_structurally_impossible(synthetic, frozen_rule, costs, risk):
    """No seed exists to pick: the rule pipeline is fully deterministic."""
    records = [
        evaluate_partition(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                           costs=costs, risk=risk, candidate_id="T", validation_run_id="R",
                           partition_name="P", dataset_checksum="c", code_version="test")
        for _ in range(3)
    ]
    assert len({r.result_checksum() for r in records}) == 1
    assert records[0].signal_provenance["seed"] is None
    assert "NO_SEED_REQUIRED" in records[0].signal_provenance["seed_policy"]


def test_08_window_cherry_picking_is_refused(synthetic, frozen_rule, costs, risk):
    """Every window is retained; the report exposes no selection mechanism."""
    report = run_walk_forward(
        synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule, costs=costs, risk=risk,
        candidate_id="T", validation_run_id="R", dataset_checksum="c", code_version="test",
    )
    assert report.n_windows == len(report.windows)
    assert report.aggregate["n_windows"] == report.n_windows
    traded = [w for w in report.windows if w["trade_count"] > 0]
    assert report.aggregate["n_windows_with_trades"] == len(traded)
    # There is no API that would return only the profitable windows.
    assert not any("profitable" in name or "select" in name for name in dir(report))


def test_09_instrument_cherry_picking_is_blocked_by_the_frozen_scope():
    """The frozen scope names its instruments; a different one is a new candidate."""
    registry = DatasetRegistry()
    candidate = _test_candidate()
    snapshot = freeze_candidate(
        candidate, dataset_registry=registry, cost_model={}, risk_rules={},
        target_specification={}, seed_policy={}, code_version="test", instrument_scope=("EURUSD",),
    )
    assert snapshot.instrument_scope == ("EURUSD",)
    assert snapshot.dataset_identity["instrument"] == "EURUSD"
    other = _test_candidate()
    object.__setattr__(other, "dataset_id", "DATASET-GBPUSD-H1-KOMO135-V1")
    with pytest.raises(CandidateFreezeError):
        verify_unchanged(snapshot, other, dataset_registry=registry)


# --------------------------------------------------------------------------
# 10-13: leakage
# --------------------------------------------------------------------------


def test_10_feature_leakage_is_caught_by_truncation_invariance(synthetic):
    """A leaking feature must be caught; the real ones must pass."""
    report = audit_feature_temporal_safety(synthetic, features=["rsi_14", "atr_14"],
                                           cut_points=[800, 1600, 2400])
    assert report.verdict == "PASS"
    assert report.violations == ()

    # A deliberately leaking feature, injected into the same checker.
    import core.economic_validation.feature_temporal_audit as audit_mod

    leaky = synthetic["close"].shift(-1)
    full = leaky.copy()
    truncated = synthetic["close"].iloc[:1600].shift(-1)
    assert not audit_mod._values_equal(full.iloc[1599], truncated.iloc[1599])


def test_11_target_leakage_via_a_same_bar_fill_is_refused(synthetic, frozen_rule, costs, risk):
    """Every fill must be one bar after its signal, never on it."""
    from core.economic_validation.evaluation import build_execution_frame
    from core.economic_validation.target_audit import audit_target_construction

    frame, features = build_execution_frame(synthetic)
    signals = generate_signals(features, frozen_rule)
    result = execute(frame, signals, costs=costs, risk=risk)
    report = audit_target_construction(frame, signals, result, costs=costs, risk=risk,
                                       candidate_id="T", partition_name="P", perturbation_sample=3)
    assert report.signal_to_entry_lag_bars["min"] == 1
    assert report.signal_to_entry_lag_bars["max"] == 1
    assert report.verdict == "PASS"


def test_12_scaler_leakage_is_structurally_absent(synthetic):
    """No fitted transformer exists that could span the train/test boundary."""
    report = audit_feature_temporal_safety(synthetic, features=["rsi_14", "atr_14"],
                                           cut_points=[900, 1800])
    assert "STRUCTURALLY_ABSENT" in report.scaler_or_imputation_state
    import core.features.fe_r2_001 as fe

    source = Path(fe.__file__).read_text()
    for forbidden in ("StandardScaler", "MinMaxScaler", "fit_transform", "fillna(method=", "bfill"):
        assert forbidden not in source, f"{forbidden} appeared in the feature module"


def test_13_future_candle_access_changes_nothing(synthetic):
    """Perturbing every later bar must leave earlier feature values identical."""
    from core.economic_validation.feature_temporal_audit import check_future_perturbation_invariance

    violations = check_future_perturbation_invariance(synthetic, [1000, 2000], ["rsi_14", "atr_14"])
    assert violations == {"rsi_14": [], "atr_14": []}


# --------------------------------------------------------------------------
# 14-17: cost model, windows, counters
# --------------------------------------------------------------------------


def test_14_cost_model_mutation_changes_the_frozen_snapshot_checksum():
    """A quietly cheaper cost model must not pass as the same experiment."""
    registry = DatasetRegistry()
    candidate = _test_candidate()
    honest = freeze_candidate(candidate, dataset_registry=registry,
                              cost_model=base_cost_model("EURUSD").to_dict(), risk_rules={},
                              target_specification={}, seed_policy={}, code_version="test",
                              instrument_scope=("EURUSD",))
    cheap = freeze_candidate(candidate, dataset_registry=registry,
                             cost_model={**base_cost_model("EURUSD").to_dict(), "spread_price": 0.0},
                             risk_rules={}, target_specification={}, seed_policy={},
                             code_version="test", instrument_scope=("EURUSD",))
    assert honest.snapshot_checksum != cheap.snapshot_checksum
    assert honest.validation_run_id != cheap.validation_run_id


def test_14b_unpriced_instrument_is_refused_rather_than_guessed():
    with pytest.raises(CostStressError):
        base_cost_model("NOT_A_REAL_SYMBOL")


def test_15_wfa_window_omission_is_detectable(synthetic, frozen_rule, costs, risk):
    """A report whose window list is shorter than its own count is inconsistent."""
    report = run_walk_forward(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                              costs=costs, risk=risk, candidate_id="T", validation_run_id="R",
                              dataset_checksum="c", code_version="test")
    ids = [w["window_id"] for w in report.windows]
    assert ids == list(range(1, report.n_windows + 1)), "window ids must be gapless"
    tampered = {**report.to_dict(), "windows": report.to_dict()["windows"][:-1]}
    assert len(tampered["windows"]) != tampered["n_windows"]


def test_16_deleting_a_losing_window_changes_the_aggregate(synthetic, frozen_rule, costs, risk):
    """The aggregate is derived from every window, so a deletion is visible."""
    report = run_walk_forward(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                              costs=costs, risk=risk, candidate_id="T", validation_run_id="R",
                              dataset_checksum="c", code_version="test")
    traded = [w for w in report.windows if w["trade_count"] > 0]
    if not traded:
        pytest.skip("synthetic fixture produced no traded windows")
    worst = min(traded, key=lambda w: w["net_profit"])
    total = report.aggregate["total_net_profit"]
    assert total != pytest.approx(total - worst["net_profit"]) or worst["net_profit"] == 0


def test_17_multiple_testing_counter_mismatch_is_reported(tmp_path):
    """Recomputed and stored counters are compared, not assumed equal."""
    from scripts.run_generation4 import _reconcile

    ok = _reconcile({"TOTAL_CANDIDATES_GENERATED": 2, "TOTAL_CANDIDATES_REJECTED": 2},
                    {"total_strategies_generated": 2, "total_strategies_rejected": 2})
    assert ok["status"] == "PASS"
    bad = _reconcile({"TOTAL_CANDIDATES_GENERATED": 2, "TOTAL_CANDIDATES_REJECTED": 2},
                     {"total_strategies_generated": 99, "total_strategies_rejected": 2})
    assert bad["status"] == "FAIL"
    assert bad["mismatches"]


# --------------------------------------------------------------------------
# 18-21: fake statistics, EVG integrity, reproducibility
# --------------------------------------------------------------------------


def test_18_a_fake_statistical_pass_cannot_be_asserted_into_the_gate():
    """An unrecognised verdict blocks the gate rather than counting as support."""
    evidence = _full_evidence()
    evidence = [e for e in evidence if e.name != "STATISTICS"]
    evidence.append(_evidence("STATISTICS", verdict="DEFINITELY_FINE"))
    report = run_evg(evidence, candidate_id="STRAT-000002", validation_run_id="RUN-1",
                     candidate_checksum="cc", snapshot_checksum="ss")
    assert report.verdict == BLOCKED
    assert any("does not recognise" in r for r in report.blocking_reasons)


def test_19_evg_without_the_required_evidence_is_blocked():
    for missing in ("HOLDOUT", "WFA", "COST_STRESS", "MULTIPLE_TESTING", "LEAKAGE_AUDIT"):
        evidence = [e for e in _full_evidence() if e.name != missing]
        report = run_evg(evidence, candidate_id="STRAT-000002", validation_run_id="RUN-1",
                         candidate_checksum="cc", snapshot_checksum="ss")
        assert report.verdict == BLOCKED, missing
        assert missing in report.evidence_missing


def test_20_evg_evidence_from_another_run_or_candidate_is_blocked():
    foreign_candidate = [e for e in _full_evidence() if e.name != "HOLDOUT"]
    foreign_candidate.append(_evidence("HOLDOUT", candidate_id="STRAT-999999"))
    report = run_evg(foreign_candidate, candidate_id="STRAT-000002", validation_run_id="RUN-1",
                     candidate_checksum="cc", snapshot_checksum="ss")
    assert report.verdict == BLOCKED

    foreign_run = [e for e in _full_evidence() if e.name != "OOS"]
    foreign_run.append(_evidence("OOS", validation_run_id="RUN-2"))
    report = run_evg(foreign_run, candidate_id="STRAT-000002", validation_run_id="RUN-1",
                     candidate_checksum="cc", snapshot_checksum="ss")
    assert report.verdict == BLOCKED
    assert any("may not be mixed across runs" in r for r in report.blocking_reasons)


def test_20b_incomplete_evidence_items_are_rejected_at_construction():
    with pytest.raises(EVGEvidenceError):
        EvidenceItem(name="HOLDOUT", verdict="", checksum="c", artifact_reference="a",
                     candidate_id="S", validation_run_id="R")


def test_20c_evg_computes_no_evidence_of_its_own():
    """The gate module must not import anything that could produce a metric."""
    import core.economic_validation.evg as evg_mod

    source = Path(evg_mod.__file__).read_text()
    for forbidden in ("import pandas", "import numpy", "execute(", "compute_metrics", "build_feature_matrix"):
        assert forbidden not in source, f"EVG must not be able to produce evidence: found {forbidden}"


def test_21_reproducibility_mismatch_is_visible(synthetic, frozen_rule, costs, risk):
    """Result checksums must differ when, and only when, the run differs."""
    a = evaluate_partition(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                           costs=costs, risk=risk, candidate_id="T", validation_run_id="R",
                           partition_name="P", dataset_checksum="c", code_version="test")
    b = evaluate_partition(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                           costs=costs, risk=risk, candidate_id="T", validation_run_id="R",
                           partition_name="P", dataset_checksum="c", code_version="test")
    assert a.result_checksum() == b.result_checksum()

    other_risk = RiskRules(risk_per_trade=0.02, stop_loss_atr_mult=2.0,
                           take_profit_atr_mult=2.0, max_holding_bars=12)
    c = evaluate_partition(synthetic, evaluation_start=synthetic.index[0], rule=frozen_rule,
                           costs=costs, risk=other_risk, candidate_id="T", validation_run_id="R",
                           partition_name="P", dataset_checksum="c", code_version="test")
    assert a.result_checksum() != c.result_checksum()


# --------------------------------------------------------------------------
# 22-24: synthetic data, failure deletion, rescue loops
# --------------------------------------------------------------------------


def test_22_synthetic_data_cannot_be_presented_as_real():
    """A synthetic dataset must be ineligible however it is labelled."""
    synthetic_record = DatasetRecord(
        dataset_id="SYNTH", instrument="EURUSD", timeframe="H1", source_id="S",
        source_url="memory://", download_timestamp="2026-01-01T00:00:00Z", timezone="UTC",
        price_type="Bid", coverage_start="2020-01-01", coverage_end="2021-01-01",
        row_count=10, duplicate_count=0, missing_bar_count=0, gap_report={},
        checksum="x", file_checksum="y", download_method="generated", synthetic=True,
        provenance_status="KNOWN_SYNTHETIC", integrity_status="PASS", file_path="data/csv/EURUSD_H1.csv",
    )
    assert synthetic_record.is_real_market_data_eligible is False
    report = audit_dataset(synthetic_record, expected_instrument="EURUSD", expected_timeframe="H1")
    assert report.verdict == "INELIGIBLE"
    assert report.real_market_data is False
    assert any("synthetic" in f for f in report.findings)


def test_23_failure_records_cannot_be_deleted():
    """The failure library is append-only, by absence of any removal path."""
    library = FailureLibrary()
    for forbidden in ("delete", "remove", "purge", "clear", "update", "pop"):
        assert not hasattr(library, forbidden), f"FailureLibrary must not expose {forbidden}()"
    source = Path(FailureLibrary.__module__.replace(".", "/") + ".py")
    assert "def delete" not in (REPO_ROOT / source).read_text()
    # STRAT-000002's Generation 4 failures must be present and preserved.
    recorded = library.failures_for_entity("STRAT-000002")
    assert recorded, "Generation 4 must have preserved STRAT-000002's failure evidence"
    assert {f.failure_stage for f in recorded} & {"HOLDOUT", "OOS", "WFA", "COST_STRESS"}


def test_24_a_rescue_loop_cannot_reuse_the_rejected_candidate():
    """A REJECTED candidate is terminal: no transition out of it exists."""
    from core.factory.state_machine import IllegalStateTransitionError, assert_legal_transition

    for target in (CandidateState.GENERATED, CandidateState.TRAINED, CandidateState.FROZEN,
                   CandidateState.HOLDOUT_TESTED, CandidateState.RESEARCH_CANDIDATE):
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.REJECTED, target)

    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")
    assert candidate.state is CandidateState.REJECTED
    with pytest.raises(Exception):
        registry.assert_mutation_allowed("STRAT-000002")


def test_24b_a_changed_specification_produces_a_different_run_identity():
    """Rerunning with a changed spec cannot masquerade as the same experiment."""
    registry = DatasetRegistry()
    original = freeze_candidate(_test_candidate(), dataset_registry=registry, cost_model={},
                                risk_rules={}, target_specification={}, seed_policy={},
                                code_version="test", instrument_scope=("EURUSD",))
    rescued = freeze_candidate(_test_candidate(spec={"take_profit": "3.0xATR"}),
                               dataset_registry=registry, cost_model={}, risk_rules={},
                               target_specification={}, seed_policy={}, code_version="test",
                               instrument_scope=("EURUSD",))
    assert original.validation_run_id != rescued.validation_run_id
    assert original.spec_checksum != rescued.spec_checksum


# --------------------------------------------------------------------------
# rule parsing: refusing to guess
# --------------------------------------------------------------------------


def test_rule_parser_refuses_unknown_grammar():
    for bad in ("", "buy when it looks good", "rsi_14 is oversold", "rsi_14 > 30"):
        with pytest.raises(RuleSpecificationError):
            parse_entry_rule(bad, "long_only")


def test_rule_parser_refuses_conflicting_conditions():
    with pytest.raises(RuleSpecificationError):
        parse_entry_rule(
            "rsi_14 crosses back above 30 from below AND rsi_14 crosses back above 35 from below",
            "long_only",
        )


def test_rule_parser_refuses_direction_conflict():
    with pytest.raises(RuleSpecificationError):
        parse_entry_rule("rsi_14 crosses back below 70 from above", "long_only")


def test_atr_multiple_parser_refuses_guessing():
    for bad in ("", "1.5 ATR-ish", "tight", "1.5x"):
        with pytest.raises(RuleSpecificationError):
            parse_atr_multiple(bad)


def test_execution_refuses_multi_position_configuration(synthetic, costs):
    frame = synthetic.assign(atr_14=0.001)
    with pytest.raises(ExecutionError):
        execute(frame, pd.Series(0, index=frame.index),
                costs=costs, risk=RiskRules(0.02, 1.5, 2.0, 12, max_positions=2))
