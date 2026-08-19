"""Unit tests for the Generation 2 research-pipeline registries:
ResearchSourceRegistry, ClaimRegistry, HypothesisFormalization,
HypothesisQualityGates, SearchSpaceRegistry, ResearchLedger.
"""

from __future__ import annotations

import pytest

from core.factory.claim_registry import (
    ClaimNotFoundError,
    ClaimRecord,
    ClaimRegistry,
    ClaimSpecError,
    IllegalClaimStatusTransitionError,
    assert_legal_claim_transition,
)
from core.factory.hypothesis import HypothesisRegistry
from core.factory.hypothesis_formalization import FormalizationSpec, FormalizationSpecError, formalize_hypothesis
from core.factory.hypothesis_quality_gates import (
    HypothesisNotEligibleError,
    assert_hypothesis_eligible_for_candidate_generation,
    evaluate_hypothesis_quality_gates,
)
from core.factory.research_ledger import LedgerEvent, LedgerEventError, ResearchLedger
from core.factory.research_source_registry import (
    DuplicateSourceError,
    SOURCE_TYPES,
    SourceNotFoundError,
    SourceRecord,
    SourceSpecError,
    ResearchSourceRegistry,
)
from core.factory.search_space import (
    DuplicateSearchSpaceError,
    FrozenSearchSpaceMutationError,
    SearchSpace,
    SearchSpaceRegistry,
    SearchSpaceSpecError,
)
from utils.helpers import utcnow


def _source(**overrides):
    base = dict(source_id="SRC2-000099", source_type="YOUTUBE", title="A video", retrieval_timestamp=utcnow().isoformat())
    base.update(overrides)
    return SourceRecord(**base)


def _formalization_spec(**overrides):
    base = dict(
        inputs=("rsi_14",), condition="rsi_14 < 30", signal="rsi_14 crosses above 30",
        target="future_return over 12 bars", horizon_bars=12, direction="positive", regime="any",
        instrument_scope="EURUSD", cost_assumptions="realistic", falsification_rule="expectancy <= 0 after costs",
    )
    base.update(overrides)
    return FormalizationSpec(**base)


def _search_space(**overrides):
    base = dict(
        search_space_id="SEARCHSPACE-TEST", symbols=("EURUSD",), timeframes=("H1",), features=("rsi_14",),
        feature_parameters={}, entry_conditions=("e",), exit_conditions=("x",), stop_loss_options=("s",),
        take_profit_options=("t",), holding_periods=(12,), regimes=("any",), position_sizing_options=("fixed",),
        cost_model="realistic", creation_timestamp=utcnow().isoformat(),
    )
    base.update(overrides)
    return SearchSpace(**base)


class TestResearchSourceRegistry:
    def test_register_and_reload(self, tmp_path) -> None:
        path = tmp_path / "sources.json"
        reg = ResearchSourceRegistry(path=path)
        reg.register(_source())
        reloaded = ResearchSourceRegistry(path=path)
        assert reloaded.get("SRC2-000099").title == "A video"

    def test_unknown_source_type_rejected(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(source_type="TIKTOK")

    def test_all_original_source_types_remain_supported(self) -> None:
        """Updated for Generation 3 (documented contract change, not a
        weakening): this test originally asserted len(SOURCE_TYPES) == 14,
        which encoded the Generation 2 snapshot of the set. Generation 3's
        execution contract explicitly requires the architecture to admit
        future source types without invalidating historical records, so
        the fixed-count assertion is replaced by the invariant that
        actually matters: every original Generation 2 type remains
        present (nothing was removed or renamed), and every member of the
        set constructs a valid record."""
        original_gen2_types = {
            "ACADEMIC_PAPER", "WORKING_PAPER", "BOOK", "TEXTBOOK", "RESEARCH_REPORT",
            "WEBSITE", "YOUTUBE", "PUBLIC_STRATEGY", "OPEN_SOURCE_CODE", "HUMAN_HYPOTHESIS",
            "AI_GENERATED_HYPOTHESIS", "MARKET_OBSERVATION", "MACRO_DATA_SOURCE",
            "ALTERNATIVE_DATA_SOURCE",
        }
        assert original_gen2_types.issubset(SOURCE_TYPES)
        for st in SOURCE_TYPES:
            _source(source_id=f"SRC2-{hash(st) % 100000:06d}", source_type=st)

    def test_unspecified_fields_default_to_unknown(self) -> None:
        s = _source()
        assert s.author == "UNKNOWN"
        assert s.license_status == "UNKNOWN"

    def test_duplicate_detection_by_identity_checksum(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        reg.register(_source())
        dup_candidate = _source(source_id="SRC2-000100")  # same type/title/author/url/publisher
        found = reg.find_duplicate(dup_candidate)
        assert found is not None
        assert found.source_id == "SRC2-000099"

    def test_different_title_is_not_a_duplicate(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        reg.register(_source())
        distinct = _source(source_id="SRC2-000100", title="A completely different video")
        assert reg.find_duplicate(distinct) is None

    def test_new_version_preserves_previous_record_untouched(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        reg.register(_source())
        new = reg.new_version("SRC2-000099", title="A video (updated)")
        assert new.source_id != "SRC2-000099"
        assert new.supersedes_source_id == "SRC2-000099"
        assert new.source_version == 2
        assert reg.get("SRC2-000099").title == "A video"  # untouched


class TestClaimRegistry:
    def test_lifecycle_transitions(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "claims.json")
        cid = reg.allocate_claim_id()
        reg.register(ClaimRecord(
            claim_id=cid, source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        ))
        assert reg.get(cid).verification_status == "UNEXTRACTED"
        reg.transition_status(cid, "EXTRACTED", reason="ok")
        reg.transition_status(cid, "FORMALIZATION_PENDING", reason="ok")
        assert reg.get(cid).verification_status == "FORMALIZATION_PENDING"

    def test_cannot_skip_to_supported(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "claims.json")
        cid = reg.allocate_claim_id()
        reg.register(ClaimRecord(
            claim_id=cid, source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        ))
        with pytest.raises(IllegalClaimStatusTransitionError):
            reg.transition_status(cid, "SUPPORTED", reason="not so fast")

    def test_supported_is_not_settable_merely_because_source_says_so(self, tmp_path) -> None:
        """The task's explicit rule: a claim is never SUPPORTED merely
        because the source asserted it -- it must walk the full status
        chain (implicitly requiring real downstream testing to justify
        TESTED before SUPPORTED is even reachable). SUPPORTED is legal
        ONLY as a direct successor of TESTED, never of any earlier
        status -- checked directly against the real transition function,
        for every non-TESTED status."""
        for status in ("UNEXTRACTED", "EXTRACTED", "FORMALIZATION_PENDING", "FORMALIZED"):
            with pytest.raises(IllegalClaimStatusTransitionError):
                assert_legal_claim_transition(status, "SUPPORTED")
        assert_legal_claim_transition("TESTED", "SUPPORTED")  # must not raise -- the one legal path

    def test_terminal_status_has_no_further_transitions(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "claims.json")
        cid = reg.allocate_claim_id()
        reg.register(ClaimRecord(
            claim_id=cid, source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        ))
        reg.transition_status(cid, "EXTRACTED", reason="ok")
        reg.transition_status(cid, "SUPERSEDED", reason="ok")
        with pytest.raises(IllegalClaimStatusTransitionError):
            reg.transition_status(cid, "FORMALIZATION_PENDING", reason="illegal")

    def test_history_is_append_only(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "claims.json")
        cid = reg.allocate_claim_id()
        reg.register(ClaimRecord(
            claim_id=cid, source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        ))
        reg.transition_status(cid, "EXTRACTED", reason="ok")
        assert [h["status"] for h in reg.history(cid)] == ["UNEXTRACTED", "EXTRACTED"]

    def test_duplicate_claim_detection(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "claims.json")
        cid1 = reg.allocate_claim_id()
        record = ClaimRecord(
            claim_id=cid1, source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        )
        reg.register(record)
        candidate = ClaimRecord(
            claim_id="CLAIM-999999", source_id="SRC2-000099", claim_text="RSI works", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(),
        )
        assert reg.find_duplicate(candidate) is not None


class TestHypothesisFormalizationEngine:
    def test_vague_field_rejected(self) -> None:
        with pytest.raises(FormalizationSpecError):
            _formalization_spec(condition="unknown")

    def test_zero_or_negative_horizon_rejected(self) -> None:
        with pytest.raises(FormalizationSpecError):
            _formalization_spec(horizon_bars=0)

    def test_empty_inputs_rejected(self) -> None:
        with pytest.raises(FormalizationSpecError):
            _formalization_spec(inputs=())

    def test_formalize_advances_both_status_axes(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X", original_claim="claim")
        updated = formalize_hypothesis(reg, h.hypothesis_id, _formalization_spec(), reason="test")
        assert updated.formalization_status == "FORMALIZED"
        assert updated.evidence_level == "FORMALIZED_UNTESTED"
        assert updated.instrument_scope == "EURUSD"
        assert updated.cost_assumptions == "realistic"

    def test_cannot_reformalize_already_formalized_hypothesis(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X", original_claim="claim")
        formalize_hypothesis(reg, h.hypothesis_id, _formalization_spec(), reason="test")
        with pytest.raises(FormalizationSpecError):
            formalize_hypothesis(reg, h.hypothesis_id, _formalization_spec(), reason="second attempt")


class TestHypothesisQualityGates:
    def test_draft_hypothesis_fails_all_gates(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X", original_claim="claim")
        failed = evaluate_hypothesis_quality_gates(h)
        assert len(failed) > 0
        with pytest.raises(HypothesisNotEligibleError):
            assert_hypothesis_eligible_for_candidate_generation(h)

    def test_fully_formalized_hypothesis_passes(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X", original_claim="claim")
        h = formalize_hypothesis(reg, h.hypothesis_id, _formalization_spec(), reason="test")
        assert evaluate_hypothesis_quality_gates(h) == []
        assert_hypothesis_eligible_for_candidate_generation(h)  # must not raise

    def test_unrecognized_feature_dependency_fails_gate(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X", original_claim="claim")
        h = formalize_hypothesis(
            reg, h.hypothesis_id, _formalization_spec(inputs=("totally_made_up_indicator",)), reason="test"
        )
        failed = evaluate_hypothesis_quality_gates(h)
        assert any("TEMPORAL_AVAILABILITY_KNOWN" in f for f in failed)


class TestSearchSpaceRegistry:
    def test_register_and_reload(self, tmp_path) -> None:
        path = tmp_path / "ss.json"
        reg = SearchSpaceRegistry(path=path)
        reg.register(_search_space())
        reloaded = SearchSpaceRegistry(path=path)
        assert reloaded.get("SEARCHSPACE-TEST").symbols == ("EURUSD",)

    def test_combination_count(self) -> None:
        space = _search_space(
            stop_loss_options=("a", "b"), take_profit_options=("c", "d", "e"),
            holding_periods=(4, 8),
        )
        # 1 symbol * 1 tf * 1 entry * 1 exit * 2 SL * 3 TP * 2 holding * 1 regime * 1 sizing = 12
        assert space.combination_count() == 12

    def test_mutation_under_same_id_rejected(self, tmp_path) -> None:
        reg = SearchSpaceRegistry(path=tmp_path / "ss.json")
        reg.register(_search_space())
        mutated = _search_space(cost_model="DIFFERENT")
        with pytest.raises(FrozenSearchSpaceMutationError):
            reg.register(mutated)

    def test_identical_reregistration_raises_duplicate_not_mutation(self, tmp_path) -> None:
        reg = SearchSpaceRegistry(path=tmp_path / "ss.json")
        reg.register(_search_space())
        with pytest.raises(DuplicateSearchSpaceError):
            reg.register(_search_space())

    def test_incomplete_search_space_rejected(self) -> None:
        with pytest.raises(SearchSpaceSpecError):
            _search_space(symbols=())

    def test_find_duplicate_by_content(self, tmp_path) -> None:
        reg = SearchSpaceRegistry(path=tmp_path / "ss.json")
        reg.register(_search_space())
        candidate = _search_space(search_space_id="SEARCHSPACE-OTHER")
        found = reg.find_duplicate(candidate)
        assert found is not None
        assert found.search_space_id == "SEARCHSPACE-TEST"


class TestResearchLedger:
    def test_append_and_reload(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        ledger = ResearchLedger(path=path)
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-000001", reason="test")
        reloaded = ResearchLedger(path=path)
        assert len(reloaded.all_events()) == 1

    def test_unknown_event_type_rejected(self, tmp_path) -> None:
        ledger = ResearchLedger(path=tmp_path / "ledger.json")
        with pytest.raises(LedgerEventError):
            ledger.append("SOMETHING_MADE_UP", subject_id="X", reason="test")

    def test_events_are_append_only_never_removed(self, tmp_path) -> None:
        ledger = ResearchLedger(path=tmp_path / "ledger.json")
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-000001", reason="a")
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-000001", reason="b")
        assert len(ledger.all_events()) == 2
        assert [e.reason for e in ledger.all_events()] == ["a", "b"]

    def test_ledger_has_no_delete_or_update_method(self) -> None:
        methods = [m for m in dir(ResearchLedger) if not m.startswith("_")]
        assert not any("delete" in m.lower() or "remove" in m.lower() for m in methods)
        assert not any(m in ("update", "edit", "rewrite") for m in methods)

    def test_events_for_subject_filters_correctly(self, tmp_path) -> None:
        ledger = ResearchLedger(path=tmp_path / "ledger.json")
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-000001", reason="a")
        ledger.append("CLAIM_CREATED", subject_id="CLAIM-000001", reason="b")
        assert len(ledger.events_for_subject("SRC2-000001")) == 1

    def test_ledger_checksum_changes_when_a_new_event_is_appended(self, tmp_path) -> None:
        ledger = ResearchLedger(path=tmp_path / "ledger.json")
        before = ledger.ledger_checksum()
        ledger.append("SOURCE_INGESTED", subject_id="SRC2-000001", reason="a")
        after = ledger.ledger_checksum()
        assert before != after
