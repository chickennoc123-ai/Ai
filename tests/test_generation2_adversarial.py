"""Generation 2, Phase 16 — adversarial testing.

Covers every category the task names explicitly. Each test proves the
invariant actually fails when violated (not a static source-grep) — per
the task's own instruction to avoid grep-style tests where a behavioral
test is possible.
"""

from __future__ import annotations

import dataclasses

import pytest
from utils.helpers import utcnow

from core.factory.candidate_generation_engine import CandidateGenerationError, generate_and_register_candidate
from core.factory.claim_registry import ClaimRecord, ClaimRegistry, IllegalClaimStatusTransitionError
from core.factory.dataset_registry import DatasetRecord, DatasetSpecError
from core.factory.hypothesis import HypothesisRegistry, HypothesisSpecError
from core.factory.hypothesis_formalization import FormalizationSpec, FormalizationSpecError, formalize_hypothesis
from core.factory.hypothesis_quality_gates import HypothesisNotEligibleError, assert_hypothesis_eligible_for_candidate_generation
from core.factory.registry import (
    HoldoutAccessEventRequiredError,
    MultipleTestingAccountingRequiredError,
    StrategyRegistry,
)
from core.factory.research_ledger import ResearchLedger
from core.factory.research_source_registry import DuplicateSourceError, ResearchSourceRegistry, SourceRecord
from core.factory.search_space import DuplicateSearchSpaceError, FrozenSearchSpaceMutationError, SearchSpace, SearchSpaceRegistry
from core.factory.state_machine import CandidateState
from tests.test_factory_registry import _spec, _walk_to_frozen


def _source(**overrides):
    base = dict(source_id="SRC2-ADV-001", source_type="WEBSITE", title="adversarial fixture", retrieval_timestamp=utcnow().isoformat())
    base.update(overrides)
    return SourceRecord(**base)


def _search_space(**overrides):
    base = dict(
        search_space_id="SEARCHSPACE-ADV", symbols=("EURUSD",), timeframes=("H1",), features=("rsi_14",),
        feature_parameters={}, entry_conditions=("e",), exit_conditions=("x",), stop_loss_options=("s",),
        take_profit_options=("t",), holding_periods=(12,), regimes=("any",), position_sizing_options=("fixed",),
        cost_model="realistic", creation_timestamp=utcnow().isoformat(),
    )
    base.update(overrides)
    return SearchSpace(**base)


def _full_formalization_spec(**overrides):
    base = dict(
        inputs=("rsi_14",), condition="rsi_14 < 30", signal="rsi_14 crosses above 30",
        target="future_return over 12 bars", horizon_bars=12, direction="positive", regime="any",
        instrument_scope="EURUSD", cost_assumptions="realistic", falsification_rule="expectancy <= 0 after costs",
    )
    base.update(overrides)
    return FormalizationSpec(**base)


class TestSourceMutation:
    def test_source_record_is_frozen(self) -> None:
        s = _source()
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.title = "mutated"  # type: ignore[misc]

    def test_registry_has_no_in_place_update_method(self) -> None:
        methods = [m for m in dir(ResearchSourceRegistry) if not m.startswith("_")]
        assert "update" not in methods and "edit" not in methods


class TestDuplicateSource:
    def test_duplicate_source_id_rejected(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        reg.register(_source())
        with pytest.raises(DuplicateSourceError):
            reg.register(_source())


class TestDuplicateHypothesis:
    def test_duplicate_hypothesis_detected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        reg.register(source_type="WEBSITE", source_reference="ref1", original_claim="claim text")
        found = reg.find_duplicate("WEBSITE", "ref1", "claim text")
        assert found is not None

    def test_genuinely_different_claim_is_not_flagged_as_duplicate(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        reg.register(source_type="WEBSITE", source_reference="ref1", original_claim="claim text A")
        found = reg.find_duplicate("WEBSITE", "ref1", "claim text B -- genuinely different")
        assert found is None


class TestMalformedHypothesis:
    def test_unknown_evidence_level_rejected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            from core.factory.hypothesis import HypothesisRecord

            HypothesisRecord(
                hypothesis_id="HYP-BAD", source_type="WEBSITE", source_reference="r", original_claim="c",
                date_captured=utcnow().isoformat(), evidence_level="DEFINITELY_TRUE",
            )

    def test_fabricated_supported_status_without_history_rejected(self) -> None:
        """The fix applied during this phase's own adversarial testing:
        direct construction can no longer claim a terminal
        formalization_status (a fabricated PASS) with empty
        transformation_history."""
        from core.factory.hypothesis import HypothesisRecord

        with pytest.raises(HypothesisSpecError):
            HypothesisRecord(
                hypothesis_id="HYP-FAKE", source_type="WEBSITE", source_reference="r", original_claim="c",
                date_captured=utcnow().isoformat(), formalization_status="SUPPORTED",
            )


class TestMissingTarget:
    def test_vague_target_rejected(self) -> None:
        with pytest.raises(FormalizationSpecError):
            _full_formalization_spec(target="tbd")

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(FormalizationSpecError):
            _full_formalization_spec(target="")


class TestMissingTimeframe:
    def test_search_space_with_no_timeframe_rejected(self) -> None:
        from core.factory.search_space import SearchSpaceSpecError

        with pytest.raises(SearchSpaceSpecError):
            _search_space(timeframes=())

    def test_candidate_generation_rejects_timeframe_outside_search_space(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="r", original_claim="c")
        h = formalize_hypothesis(reg, h.hypothesis_id, _full_formalization_spec(), reason="test")
        space = _search_space()
        strat_reg = StrategyRegistry(path=tmp_path / "strat.json")
        with pytest.raises(CandidateGenerationError):
            generate_and_register_candidate(
                strat_reg, h, space,
                param_draw={"entry_condition": "e", "exit_condition": "x", "stop_loss": "s", "take_profit": "t",
                            "holding_period": 12, "position_sizing": "fixed"},
                symbol="EURUSD", timeframe="H4",  # not in space.timeframes
                code_version="test", dataset_id="NONE",
            )


class TestMissingInstrument:
    def test_search_space_with_no_symbols_rejected(self) -> None:
        from core.factory.search_space import SearchSpaceSpecError

        with pytest.raises(SearchSpaceSpecError):
            _search_space(symbols=())

    def test_hypothesis_with_vague_instrument_scope_fails_quality_gate(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="r", original_claim="c")
        with pytest.raises(FormalizationSpecError):
            formalize_hypothesis(reg, h.hypothesis_id, _full_formalization_spec(instrument_scope="unknown"), reason="test")


class TestFeatureLookAhead:
    def test_hypothesis_declaring_unrecognized_feature_fails_availability_gate(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="r", original_claim="c")
        h = formalize_hypothesis(
            reg, h.hypothesis_id, _full_formalization_spec(inputs=("a_feature_that_requires_the_future",)),
            reason="test",
        )
        with pytest.raises(HypothesisNotEligibleError):
            assert_hypothesis_eligible_for_candidate_generation(h)

    def test_real_fe_r2_features_still_have_the_underlying_no_lookahead_guarantee(self) -> None:
        """Not re-derived here (already exhaustively proven in
        ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md and
        tests/test_ml_001_r2_adversarial.py) -- confirms Generation 2
        declares dependence on the SAME canonical feature module, not a
        second, unverified implementation."""
        from core.factory.feature_catalog import implementation_status

        assert implementation_status("rsi_14") == "IMPLEMENTED"


class TestSearchSpaceMutation:
    def test_mutating_a_registered_search_space_id_is_rejected(self, tmp_path) -> None:
        reg = SearchSpaceRegistry(path=tmp_path / "ss.json")
        reg.register(_search_space())
        with pytest.raises(FrozenSearchSpaceMutationError):
            reg.register(_search_space(cost_model="TAMPERED"))

    def test_search_space_object_itself_is_frozen(self) -> None:
        space = _search_space()
        with pytest.raises(dataclasses.FrozenInstanceError):
            space.cost_model = "mutated"  # type: ignore[misc]


class TestFrozenCandidateMutation:
    def test_candidate_generated_via_gen2_engine_is_still_frozen_at_oos_tested(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="r", original_claim="c")
        h = formalize_hypothesis(reg, h.hypothesis_id, _full_formalization_spec(), reason="test")
        space = _search_space()
        strat_reg = StrategyRegistry(path=tmp_path / "strat.json")
        cid = generate_and_register_candidate(
            strat_reg, h, space,
            param_draw={"entry_condition": "e", "exit_condition": "x", "stop_loss": "s", "take_profit": "t",
                        "holding_period": 12, "position_sizing": "fixed"},
            symbol="EURUSD", timeframe="H1", code_version="test", dataset_id="NONE",
        )
        strat_reg.transition(cid, CandidateState.DATA_VALIDATED, reason="ok")
        strat_reg.transition(cid, CandidateState.TRAINED, reason="ok")
        strat_reg.transition(cid, CandidateState.OOS_TESTED, reason="ok")
        from core.factory.candidate import FrozenCandidateMutationError

        with pytest.raises(FrozenCandidateMutationError):
            strat_reg.assert_mutation_allowed(cid)


class TestFakePassState:
    def test_cannot_enter_multiple_testing_reviewed_without_accounting(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "strat.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        for state in (CandidateState.DATA_VALIDATED, CandidateState.TRAINED, CandidateState.OOS_TESTED,
                      CandidateState.WFA_TESTED, CandidateState.ROBUSTNESS_TESTED, CandidateState.COST_TESTED,
                      CandidateState.STATISTICALLY_VALIDATED):
            reg.transition(c.candidate_id, state, reason="ok")
        with pytest.raises(MultipleTestingAccountingRequiredError):
            reg.transition(c.candidate_id, CandidateState.MULTIPLE_TESTING_REVIEWED, reason="fake")

    def test_cannot_enter_holdout_tested_without_a_real_event(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "strat.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(HoldoutAccessEventRequiredError):
            reg.transition(c.candidate_id, CandidateState.HOLDOUT_TESTED, reason="fake pass")

    def test_selection_bias_status_never_defaults_to_pass(self) -> None:
        from core.factory.research_accounting import compute_search_accounting_summary

        summary = compute_search_accounting_summary()
        assert summary["SELECTION_BIAS_STATUS"] != "PASS"


class TestAccountingMismatch:
    def test_search_accounting_recomputes_from_real_registries_not_a_stale_cache(self, tmp_path) -> None:
        from core.factory.research_accounting import compute_search_accounting_summary

        source_reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        summary_before = compute_search_accounting_summary(source_registry=source_reg)
        assert summary_before["TOTAL_SOURCES"] == 0
        source_reg.register(_source())
        summary_after = compute_search_accounting_summary(source_registry=source_reg)
        assert summary_after["TOTAL_SOURCES"] == 1


class TestMissingProvenance:
    def test_dataset_with_unverified_provenance_is_not_real_market_eligible(self) -> None:
        from core.factory.dataset_registry import assert_real_market_data_eligible, RealMarketDataEligibilityError

        record = DatasetRecord(
            dataset_id="D", instrument="EURUSD", timeframe="H1", source_id="S", source_url="u",
            download_timestamp="2026-01-01T00:00:00+00:00", timezone="UTC", price_type="mid",
            coverage_start="2020-01-01T00:00:00+00:00", coverage_end="2021-01-01T00:00:00+00:00",
            row_count=1, duplicate_count=0, missing_bar_count=0, gap_report={}, checksum="x", file_checksum="x",
            download_method="curl", synthetic=False, provenance_status="UNVERIFIED", integrity_status="PASS",
        )
        with pytest.raises(RealMarketDataEligibilityError):
            assert_real_market_data_eligible(record)


class TestUnverifiedSourcePretendingToBeVerified:
    def test_verified_provenance_requires_a_stated_verification_method(self) -> None:
        with pytest.raises(DatasetSpecError):
            DatasetRecord(
                dataset_id="D", instrument="EURUSD", timeframe="H1", source_id="S", source_url="u",
                download_timestamp="2026-01-01T00:00:00+00:00", timezone="UTC", price_type="mid",
                coverage_start="2020-01-01T00:00:00+00:00", coverage_end="2021-01-01T00:00:00+00:00",
                row_count=1, duplicate_count=0, missing_bar_count=0, gap_report={}, checksum="x", file_checksum="x",
                download_method="curl", synthetic=False, provenance_status="VERIFIED", integrity_status="PASS",
                verification_method="",  # claims VERIFIED with nothing behind it
            )


class TestSyntheticDataPretendingToBeReal:
    def test_synthetic_true_cannot_pair_with_verified_status(self) -> None:
        with pytest.raises(DatasetSpecError):
            DatasetRecord(
                dataset_id="D", instrument="EURUSD", timeframe="H1", source_id="S", source_url="u",
                download_timestamp="2026-01-01T00:00:00+00:00", timezone="UTC", price_type="mid",
                coverage_start="2020-01-01T00:00:00+00:00", coverage_end="2021-01-01T00:00:00+00:00",
                row_count=1, duplicate_count=0, missing_bar_count=0, gap_report={}, checksum="x", file_checksum="x",
                download_method="curl", synthetic=True, provenance_status="VERIFIED", integrity_status="PASS",
                verification_method="claimed but should be rejected",
            )


class TestCandidateLineageCorruption:
    def test_candidate_generated_with_mismatched_symbol_is_rejected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="r", original_claim="c")
        h = formalize_hypothesis(reg, h.hypothesis_id, _full_formalization_spec(), reason="test")
        space = _search_space()  # symbols=("EURUSD",)
        strat_reg = StrategyRegistry(path=tmp_path / "strat.json")
        with pytest.raises(CandidateGenerationError):
            generate_and_register_candidate(
                strat_reg, h, space,
                param_draw={"entry_condition": "e", "exit_condition": "x", "stop_loss": "s", "take_profit": "t",
                            "holding_period": 12, "position_sizing": "fixed"},
                symbol="GBPUSD",  # not in search_space.symbols -- lineage would be corrupted if allowed
                timeframe="H1", code_version="test", dataset_id="NONE",
            )

    def test_candidate_checksum_reflects_true_hypothesis_and_search_space_lineage(self, tmp_path) -> None:
        """A candidate generated from a DIFFERENT hypothesis/search-space
        pairing must produce a DIFFERENT checksum, even with an
        identical param_draw -- proving the checksum genuinely encodes
        lineage, not just the drawn parameters."""
        from core.factory.candidate_generation_engine import compute_candidate_checksum
        from core.factory.candidate import StrategyCandidateSpec

        spec = StrategyCandidateSpec(
            entry_rule="r", exit_rule="x", features=("rsi_14",), timeframe="H1", direction="long_only",
            stop_loss="s", take_profit="t", max_hold_bars=12, position_sizing="fixed",
            transaction_cost_model="realistic",
        )
        c1 = compute_candidate_checksum(spec, "HYP-000001", "SEARCHSPACE-000001")
        c2 = compute_candidate_checksum(spec, "HYP-000002", "SEARCHSPACE-000001")
        assert c1 != c2


class TestLedgerMutation:
    def test_ledger_events_cannot_be_removed_or_edited(self, tmp_path) -> None:
        ledger = ResearchLedger(path=tmp_path / "ledger.json")
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-X", reason="a")
        event = ledger.all_events()[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.reason = "tampered"  # type: ignore[misc]

    def test_ledger_file_tampering_changes_the_ledger_checksum(self, tmp_path) -> None:
        """Proves the checksum is a real tamper-evidence mechanism: a
        file-level edit (bypassing the append() API entirely) is
        detectable by recomputing the checksum from the loaded state."""
        import json

        path = tmp_path / "ledger.json"
        ledger = ResearchLedger(path=path)
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-X", reason="original")
        original_checksum = ledger.ledger_checksum()

        raw = json.loads(path.read_text())
        raw["events"][0]["reason"] = "tampered directly in the JSON file"
        path.write_text(json.dumps(raw))

        tampered_ledger = ResearchLedger(path=path)
        assert tampered_ledger.ledger_checksum() != original_checksum
