"""Generation 3, Phase 26 — end-to-end verification of the REAL research
intake that now lives in the production registries.

Read-only: these tests verify the committed production state; they never
mutate it. Every check here re-derives its answer from the files (reverse
lineage walk, checksum recomputation) rather than trusting any report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.factory.claim_registry import ClaimRegistry
from core.factory.hypothesis import HypothesisRegistry
from core.factory.novelty_engine import FamilyRegistry
from core.factory.registry import StrategyRegistry
from core.factory.research_accounting import compute_search_accounting_summary
from core.factory.research_ledger import ResearchLedger
from core.factory.research_source_registry import ResearchSourceRegistry
from core.factory.search_space import SearchSpaceRegistry
from core.factory.source_snapshot import SourceSnapshotStore
from core.factory.state_machine import CandidateState

REPO_ROOT = Path(__file__).resolve().parent.parent
FACTORY = REPO_ROOT / "reports" / "factory"


def _production_available() -> bool:
    return (FACTORY / "research_source_registry.json").exists() and (FACTORY / "strategy_registry.json").exists()


pytestmark = pytest.mark.skipif(not _production_available(), reason="production Generation 3 registries not present")


def _registries():
    return (
        ResearchSourceRegistry(path=FACTORY / "research_source_registry.json"),
        ClaimRegistry(path=FACTORY / "claim_registry.json"),
        HypothesisRegistry(path=FACTORY / "hypothesis_registry.json"),
        SearchSpaceRegistry(path=FACTORY / "search_space_registry.json"),
        StrategyRegistry(path=FACTORY / "strategy_registry.json"),
    )


class TestRealSourceProvenance:
    def test_the_real_external_source_is_checksummed_and_snapshot_verified(self) -> None:
        src_reg, *_ = _registries()
        s = src_reg.get("SRC2-000001")
        assert s.access_status == "ACCESSED"
        assert s.verification_status == "PROVISIONALLY_VERIFIED"
        assert s.license_status == "PERMISSIVE"
        # the stored snapshot's bytes must still hash to the recorded checksum
        snapshot_id = s.artifact_reference.split(":", 1)[1]
        store = SourceSnapshotStore(directory=FACTORY / "source_snapshots")
        content = store.read_verified(snapshot_id)
        assert hashlib.sha256(content).hexdigest() == s.content_checksum
        # and the snapshot really contains the claim text we extracted
        assert b"RSI above 70 is overbought and RSI below 30 is oversold" in content

    def test_access_failed_sources_are_recorded_honestly_not_substituted(self) -> None:
        src_reg, *_ = _registries()
        failed = [s for s in src_reg.list_all() if s.access_status == "ACCESS_FAILED"]
        assert len(failed) >= 2  # arxiv + ssrn host attempts
        for s in failed:
            assert s.verification_status == "ACCESS_FAILED"
            assert s.content_checksum in ("UNKNOWN", "")  # never pretends content was reached
            assert "no specific paper was identified or reviewed" in s.title.lower() or "unreachable" in s.title.lower()

    def test_internal_source_checksum_matches_the_committed_file(self) -> None:
        src_reg, *_ = _registries()
        internal = [s for s in src_reg.list_all() if s.source_type == "INTERNAL_RESEARCH_REPORT"]
        assert len(internal) == 1
        expected = hashlib.sha256((REPO_ROOT / "ML-001-STRAT-000001-FAILURE-FORENSIC-REPORT.md").read_bytes()).hexdigest()
        assert internal[0].content_checksum == expected


class TestRealClaimDiscipline:
    def test_verbatim_claim_text_exists_in_the_source_snapshot(self) -> None:
        """The no-strengthening check, end to end: the extracted claim
        text must appear verbatim inside the stored source snapshot."""
        src_reg, claim_reg, *_ = _registries()
        c = claim_reg.get("CLAIM-000001")
        s = src_reg.get(c.source_id)
        store = SourceSnapshotStore(directory=FACTORY / "source_snapshots")
        content = store.read_verified(s.artifact_reference.split(":", 1)[1]).decode("utf-8", errors="replace")
        assert c.claim_text in content
        assert c.epistemic_status == "SOURCE_CLAIM"
        assert c.claim_classification == "MARKET_LORE"

    def test_fact_established_claim_carries_evidence(self) -> None:
        _, claim_reg, *_ = _registries()
        facts = [c for c in claim_reg.list_all() if c.epistemic_status == "FACT_ESTABLISHED"]
        assert len(facts) == 1
        assert "FORENSIC-REPORT" in facts[0].evidence_reference


class TestRealHypothesisLineage:
    def test_all_three_origins_are_present_and_none_is_supported(self) -> None:
        hyp_reg = HypothesisRegistry(path=FACTORY / "hypothesis_registry.json")
        origins = {h.origin_type for h in hyp_reg.list_all()}
        assert origins == {"PUBLIC_STRATEGY_DERIVED", "CROSS_SOURCE_SYNTHESIS", "AI_DERIVED"}
        assert all(h.formalization_status != "SUPPORTED" for h in hyp_reg.list_all())

    def test_synthesis_hypothesis_preserves_both_parents(self) -> None:
        hyp_reg = HypothesisRegistry(path=FACTORY / "hypothesis_registry.json")
        synth = [h for h in hyp_reg.list_all() if h.origin_type == "CROSS_SOURCE_SYNTHESIS"][0]
        assert len(synth.parent_claim_ids) == 2 and len(synth.parent_source_ids) == 2

    def test_ai_hypothesis_carries_full_separated_provenance(self) -> None:
        hyp_reg = HypothesisRegistry(path=FACTORY / "hypothesis_registry.json")
        ai = [h for h in hyp_reg.list_all() if h.origin_type == "AI_DERIVED"][0]
        for key in ("generation_model", "generation_timestamp", "prompt_identity", "input_source_ids", "input_claim_ids"):
            assert key in ai.ai_provenance
        # the prompt identity is a real checksum of the recorded prompt text
        assert ai.ai_provenance["prompt_identity"] == hashlib.sha256(
            ai.ai_provenance["prompt_text"].encode()
        ).hexdigest()


class TestFirstRealCandidate:
    def test_full_reverse_lineage_from_candidate_to_source(self) -> None:
        src_reg, claim_reg, hyp_reg, ss_reg, strat_reg = _registries()
        c = strat_reg.get("STRAT-000002")
        # Updated for Generation 4 (documented contract change, not a
        # weakening). This originally asserted GENERATED, encoding the
        # Generation 3 end-state where the candidate had been created but
        # never evaluated. Generation 4 evaluated it and rejected it. The
        # point the assertion was protecting -- that this candidate is not
        # an edge claim -- is now stronger, not weaker, and is asserted
        # directly: it is terminally REJECTED and never reached any state
        # that would constitute a passing verdict.
        assert c.state == CandidateState.REJECTED
        states = [h["state"] for h in c.history]
        assert "RESEARCH_CANDIDATE" not in states
        assert "PAPER_VALIDATION" not in states
        assert "LIVE_CANDIDATE" not in states
        h = hyp_reg.get(c.hypothesis_id)
        claim = claim_reg.get(h.source_claim_id)
        source = src_reg.get(claim.source_id)
        assert source.source_id == "SRC2-000001"
        space = ss_reg.get(c.search_space_id)
        assert space.combination_count() == 8
        assert c.candidate_checksum  # generation-time identity recorded
        assert "STRAT-000002" in h.candidate_ids  # forward link too

    def test_strat_000001_remains_rejected_and_untouched(self) -> None:
        *_, strat_reg = _registries()
        assert strat_reg.get("STRAT-000001").state == CandidateState.REJECTED

    def test_candidate_is_counted_in_multiple_testing_accounting(self) -> None:
        src_reg, claim_reg, hyp_reg, ss_reg, strat_reg = _registries()
        summary = compute_search_accounting_summary(
            source_registry=src_reg, claim_registry=claim_reg, hypothesis_registry=hyp_reg,
            search_space_registry=ss_reg, strategy_registry=strat_reg,
        )
        assert summary["TOTAL_SOURCES"] == 4
        assert summary["TOTAL_CLAIMS"] == 3
        assert summary["TOTAL_HYPOTHESES"] == 3
        assert summary["TOTAL_FORMALIZED_HYPOTHESES"] == 3
        assert summary["TOTAL_CANDIDATES_GENERATED"] == 2
        assert summary["SELECTION_BIAS_STATUS"] != "PASS"


class TestLedgerAndSafetyState:
    def test_ledger_records_the_full_research_trail(self) -> None:
        ledger = ResearchLedger(path=FACTORY / "research_ledger.json")
        by_type = {}
        for e in ledger.all_events():
            by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        assert by_type["SOURCE_INGESTED"] == 4
        assert by_type["CLAIM_CREATED"] == 3
        assert by_type["HYPOTHESIS_CREATED"] == 3
        assert by_type["HYPOTHESIS_FORMALIZED"] == 3
        assert by_type["SEARCH_SPACE_CREATED"] == 1
        assert by_type["CANDIDATE_GENERATED"] == 1
        # the candidate event explicitly disclaims validation
        candidate_events = ledger.events_for_subject("STRAT-000002")
        assert any("NOT" in e.reason and "validated" in e.reason.lower() for e in candidate_events)

    def test_kill_switch_exists_and_is_not_tripped(self) -> None:
        from core.factory.research_budget import ResearchKillSwitch

        ks = ResearchKillSwitch(path=FACTORY / "research_kill_switch.json")
        ks.assert_not_tripped()

    def test_holdout_was_never_touched_by_research_discovery(self) -> None:
        """Retargeted for Generation 4, and deliberately not deleted.

        The original assertion was "no candidate has ever entered
        HOLDOUT_TESTED". Generation 4 legitimately entered it for
        STRAT-000002, after the full pre-holdout evidence chain and after
        the candidate was FROZEN. Deleting the test would lose the
        property it was protecting, so it is retargeted to the property
        that still holds and still matters: *research discovery* never
        touched PURE_HOLDOUT, and any holdout access that does exist is a
        Generation 4 economic-validation access on a frozen candidate,
        never a discovery-time one.
        """
        *_, strat_reg = _registries()
        for c in strat_reg.list_all():
            states = [h["state"] for h in c.history]
            if "HOLDOUT_TESTED" not in states:
                continue
            assert c.candidate_id == "STRAT-000002", (
                "only the Generation 4 candidate may have touched PURE_HOLDOUT"
            )
            # It must have been frozen first, and the transition must carry
            # a real evidence reference rather than a bare reason string.
            assert states.index("FROZEN") < states.index("HOLDOUT_TESTED")
            entry = next(h for h in c.history if h["state"] == "HOLDOUT_TESTED")
            assert entry.get("evidence_reference"), "holdout access must reference its evidence"
            # And exactly once: a second access would break "evaluated once".
            assert states.count("HOLDOUT_TESTED") == 1

        # The Generation 3 audit artifact is a frozen record of Generation
        # 3's own end-state and must still say zero -- if this ever became
        # non-zero, a discovery-phase holdout access would have been
        # back-dated into Generation 3's record.
        audit = json.loads((FACTORY / "GENERATION3_RESEARCH_AUDIT.json").read_text())
        assert audit["holdout_access_events"] == 0

    def test_failure_library_records_the_access_failures(self) -> None:
        from core.factory.failure_library import FailureLibrary

        lib = FailureLibrary(path=FACTORY / "failure_library.json")
        access_failures = [f for f in lib.all_failures() if f.failure_category == "SOURCE_ACCESS_FAILED"]
        assert len(access_failures) >= 2  # arxiv + ssrn -- failure is information, preserved


class TestChecksumReproducibility:
    def test_hypothesis_checksums_in_audit_artifact_recompute_identically(self) -> None:
        hyp_reg = HypothesisRegistry(path=FACTORY / "hypothesis_registry.json")
        audit = json.loads((FACTORY / "GENERATION3_RESEARCH_AUDIT.json").read_text())
        for hid, info in audit["hypotheses"].items():
            assert hyp_reg.get(hid).checksum() == info["checksum"]

    def test_search_space_checksum_recomputes_identically(self) -> None:
        ss_reg = SearchSpaceRegistry(path=FACTORY / "search_space_registry.json")
        audit = json.loads((FACTORY / "GENERATION3_RESEARCH_AUDIT.json").read_text())
        space = ss_reg.get(audit["search_space"]["id"])
        assert space.checksum() == audit["search_space"]["checksum"]
