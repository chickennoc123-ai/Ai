"""Tests for core.factory.hypothesis — the external-source intake ledger.

Nothing here ingests a real external hypothesis (per the task's explicit
"do not ingest new external strategies yet" instruction) -- these tests
exercise the module's own discipline using synthetic, clearly-fictional
source references only.
"""

from __future__ import annotations

import pytest

from core.factory.hypothesis import (
    DuplicateHypothesisError,
    HypothesisNotFoundError,
    HypothesisRegistry,
    HypothesisSpecError,
)


class TestCaptureNeverClaimsEvidence:
    def test_new_hypothesis_starts_at_unvalidated_claim(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(
            source_type="YOUTUBE",
            source_reference="https://example.invalid/some-video",
            original_claim="Buy when RSI crosses 30 from below on H1.",
        )
        assert h.evidence_level == "UNVALIDATED_CLAIM"
        assert h.candidate_ids == ()
        assert h.formalized_trading_rule is None

    def test_unknown_source_type_rejected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            reg.register(
                source_type="TIKTOK",  # not in SOURCE_TYPES
                source_reference="https://example.invalid/x",
                original_claim="claim",
            )

    def test_direct_construction_cannot_claim_tested_evidence_out_of_the_gate(self) -> None:
        from core.factory.hypothesis import HypothesisRecord

        with pytest.raises(HypothesisSpecError):
            HypothesisRecord(
                hypothesis_id="HYP-999999",
                source_type="BOOK",
                source_reference="Some Book, p.42",
                original_claim="claim",
                date_captured="2026-01-01T00:00:00+00:00",
                evidence_level="CANDIDATE_HOLDOUT_PASSED",  # nothing behind this claim
            )

    def test_empty_original_claim_rejected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="WEBSITE", source_reference="https://example.invalid/x", original_claim="")


class TestOriginalClaimRemainsDistinguishableFromEvidence:
    def test_formalize_does_not_alter_original_claim(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(
            source_type="ACADEMIC_PAPER",
            source_reference="Fictional (2026), Journal of Examples",
            original_claim="momentum persists for 3-5 days after an earnings surprise",
        )
        reg.formalize(
            h.hypothesis_id,
            formalized_trading_rule="long if 3-day return > 2 std dev, hold 4 days",
        )
        reloaded = reg.get(h.hypothesis_id)
        assert reloaded.original_claim == "momentum persists for 3-5 days after an earnings surprise"
        assert reloaded.formalized_trading_rule == "long if 3-day return > 2 std dev, hold 4 days"
        assert reloaded.evidence_level == "FORMALIZED_UNTESTED"

    def test_transformation_history_is_append_only(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="Book X, ch.3", original_claim="claim")
        n0 = len(h.transformation_history)
        reg.formalize(h.hypothesis_id, formalized_trading_rule="rule")
        reg.link_candidate(h.hypothesis_id, "STRAT-999999")
        reg.update_evidence_level(h.hypothesis_id, "CANDIDATE_TESTED_NO_EDGE", reason="failed WFA")
        final = reg.get(h.hypothesis_id)
        assert len(final.transformation_history) == n0 + 3
        # every prior entry preserved, none overwritten
        events = [e["event"] for e in final.transformation_history]
        assert events == ["captured", "formalized", "candidate_linked", "evidence_level_changed"]


class TestCandidateLinkage:
    def test_link_candidate_advances_evidence_level_and_is_idempotent(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="https://example.invalid/x", original_claim="claim")
        reg.link_candidate(h.hypothesis_id, "STRAT-000042")
        reg.link_candidate(h.hypothesis_id, "STRAT-000042")  # duplicate, must not double-add
        reloaded = reg.get(h.hypothesis_id)
        assert reloaded.candidate_ids == ("STRAT-000042",)
        assert reloaded.evidence_level == "CANDIDATE_GENERATED"

    def test_update_evidence_level_rejects_unknown_level(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="WEBSITE", source_reference="https://example.invalid/x", original_claim="claim")
        with pytest.raises(HypothesisSpecError):
            reg.update_evidence_level(h.hypothesis_id, "DEFINITELY_PROFITABLE", reason="nope")


class TestRegistryIdentityAndPersistence:
    def test_ids_are_monotonic(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        a = reg.register(source_type="BOOK", source_reference="r1", original_claim="c1")
        b = reg.register(source_type="BOOK", source_reference="r2", original_claim="c2")
        assert a.hypothesis_id == "HYP-000001"
        assert b.hypothesis_id == "HYP-000002"

    def test_duplicate_id_rejected(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="r1", original_claim="c1")
        with pytest.raises(DuplicateHypothesisError):
            reg.register(
                source_type="BOOK", source_reference="r2", original_claim="c2", hypothesis_id=h.hypothesis_id
            )

    def test_unknown_id_raises(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisNotFoundError):
            reg.get("HYP-999999")

    def test_survives_reload(self, tmp_path) -> None:
        path = tmp_path / "hyp.json"
        reg = HypothesisRegistry(path=path)
        h = reg.register(source_type="YOUTUBE", source_reference="r", original_claim="c")
        reg.link_candidate(h.hypothesis_id, "STRAT-000001")

        reloaded = HypothesisRegistry(path=path)
        record = reloaded.get(h.hypothesis_id)
        assert record.candidate_ids == ("STRAT-000001",)
        assert record.evidence_level == "CANDIDATE_GENERATED"

    def test_summary_counts_by_evidence_level(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        reg.register(source_type="BOOK", source_reference="r1", original_claim="c1")
        h2 = reg.register(source_type="BOOK", source_reference="r2", original_claim="c2")
        reg.formalize(h2.hypothesis_id, formalized_trading_rule="rule")
        summary = reg.summary()
        assert summary["total_hypotheses_ingested"] == 2
        assert summary["by_evidence_level"]["UNVALIDATED_CLAIM"] == 1
        assert summary["by_evidence_level"]["FORMALIZED_UNTESTED"] == 1


class TestProductionHypothesisIngestionDiscipline:
    """Updated for Generation 3 (documented contract change, not a
    weakening): the original test asserted the production hypothesis
    registry did NOT exist, encoding Generation 2's explicit "zero real
    hypotheses ingested" stop condition. Generation 3's execution contract
    explicitly authorized a small, controlled REAL research seed set, so
    the registry now legitimately exists. The replacement invariants are
    stronger than the old existence check: every production hypothesis
    must carry full source lineage, and none may claim SUPPORTED (no
    hypothesis has any test evidence yet)."""

    def test_every_production_hypothesis_has_full_lineage_and_none_is_supported(self) -> None:
        from core.factory.hypothesis import DEFAULT_HYPOTHESIS_REGISTRY_PATH, HypothesisRegistry

        if not DEFAULT_HYPOTHESIS_REGISTRY_PATH.exists():
            pytest.skip("production hypothesis registry not present in this checkout")
        reg = HypothesisRegistry(path=DEFAULT_HYPOTHESIS_REGISTRY_PATH)
        population = reg.list_all()
        assert population, "registry file exists but is empty -- inconsistent state"
        for h in population:
            assert h.source_reference.strip()
            assert h.original_claim.strip()
            assert h.origin_type != "UNSPECIFIED"
            assert h.formalization_status != "SUPPORTED"  # nothing has test evidence yet
            if h.origin_type == "AI_DERIVED":
                assert h.ai_provenance  # AI hypotheses carry their provenance
            if h.origin_type == "CROSS_SOURCE_SYNTHESIS":
                assert len(h.parent_claim_ids) + len(h.parent_source_ids) >= 2
