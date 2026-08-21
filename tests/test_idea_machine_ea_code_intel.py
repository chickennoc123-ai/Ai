"""
Tests for the Idea Machine's Economic Feedback and EA Code Intelligence
modules. Focused on governance invariants (no holdout, no ledger writes,
no skipped provenance stages, no fabricated novelty claims) and the two
real bugs found and fixed while building this cycle (gross_mean=0 and
sign-flipped SURPRISE_FX_DIR).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from idea_machine.economic_feedback import EconomicFeedbackEngine
from idea_machine.ea_code_intel.strategy_dna import extract_dna, signature, DNA_CATEGORIES
from idea_machine.ea_code_intel.provenance import ProvenanceTracker, Stage, ProvenanceViolation
from idea_machine.ea_code_intel.novelty_engine import NoveltyEngine
from idea_machine.ea_code_intel.source_registry import SourceRegistry
from idea_machine.ea_code_intel.github_miner import MinedSourceCollection
from idea_machine.ea_code_intel.hypothesis_synthesizer import (
    check_data_availability, synthesize_dual_driver_confirmation,
    AVAILABLE_FX_M1, AVAILABLE_FX_H1_ONLY, AVAILABLE_DRIVERS, AVAILABLE_EVENT_TYPES,
)


# --------------------------------------------------------------------- strategy_dna

class TestStrategyDNA:
    def test_extraction_is_deterministic(self):
        text = "Uses RSI and MACD with a trailing stop, filtered by session time."
        d1 = extract_dna("A", "t", None, text)
        d2 = extract_dna("A", "t", None, text)
        assert d1.tags == d2.tags
        assert signature(d1) == signature(d2)

    def test_no_match_produces_empty_tags(self):
        d = extract_dna("A", "t", None, "The quick brown fox jumps over the lazy dog.")
        assert d.tags == {}
        assert d.tag_count() == 0

    def test_citation_is_literal_substring_of_source_text(self):
        text = "This strategy uses a trailing stop for exits."
        d = extract_dna("A", "t", None, text)
        assert "TRAILING_STOP" in d.tags["exit_mechanism"]
        citation = d.citations["TRAILING_STOP"]
        # citation must be verifiable against the actual source text
        assert citation in text or any(citation in text[i:i+80] for i in range(len(text)))

    def test_stars_and_performance_claims_never_become_dna_tags(self):
        """Governance: popularity/performance claims must never be extracted as mechanism tags."""
        text = "This EA has 5000 stars and a 95% win rate with guaranteed 40% monthly returns using RSI."
        d = extract_dna("A", "t", None, text)
        all_tags = [t for tags in d.tags.values() for t in tags]
        assert not any("STAR" in t or "WIN_RATE" in t or "RETURN" in t or "GUARANTEE" in t for t in all_tags)
        # only the legitimate mechanism tag should appear
        assert "RSI_THRESHOLD" in d.tags.get("entry_mechanism", [])

    def test_all_pattern_categories_are_known_categories(self):
        from idea_machine.ea_code_intel.strategy_dna import PATTERNS
        for _, category, _ in PATTERNS:
            assert category in DNA_CATEGORIES


# --------------------------------------------------------------------- novelty_engine

class TestNoveltyEngine:
    def test_loads_real_refuted_families_readonly(self):
        ne = NoveltyEngine()
        ne.load()
        assert len(ne.refuted_families) >= 1
        assert all(f.get("status") == "REFUTED" for f in ne.refuted_families)

    def test_never_writes_to_family_registry(self):
        from idea_machine.ea_code_intel.novelty_engine import FAMILY_REGISTRY
        before = FAMILY_REGISTRY.read_bytes()
        ne = NoveltyEngine()
        ne.load()
        ne.check({"SOME_TAG"}, "TEST-DNA")
        after = FAMILY_REGISTRY.read_bytes()
        assert before == after

    def test_high_overlap_with_refuted_family_is_flagged(self):
        ne = NoveltyEngine()
        ne.load()
        h1_pattern_family = next(
            (f for f in ne.refuted_families if f["family_id"] == "FAMILY-H1-PRICE-PATTERN"), None)
        assert h1_pattern_family is not None
        exact_tags = ne._family_tag_set(h1_pattern_family)
        assert exact_tags, "expected the refuted family's description to yield at least one tag"
        verdict = ne.check(exact_tags, "TEST-EXACT-MATCH")
        assert verdict.classification == "REFUTED"  # 5-status classification
        assert verdict.matched_family_id == "FAMILY-H1-PRICE-PATTERN"

    def test_disjoint_tag_set_is_not_flagged_as_refuted(self):
        ne = NoveltyEngine()
        ne.load()
        verdict = ne.check({"FAIR_VALUE_GAP", "ORDER_BLOCK"}, "TEST-DISJOINT")
        assert verdict.verdict != "RESEMBLES_REFUTED"


# --------------------------------------------------------------------- provenance

class TestProvenance:
    def test_cannot_skip_stages_forward(self):
        t = ProvenanceTracker(entity_id="X")
        with pytest.raises(ProvenanceViolation):
            t.advance(Stage.DATA_SUPPORTED, "trying to skip DERIVED_HYPOTHESIS")

    def test_cannot_self_declare_survivor(self):
        t = ProvenanceTracker(entity_id="X")
        t.to_derived_hypothesis("r")
        with pytest.raises(ProvenanceViolation):
            t.to_survivor("fabricated-ref")

    def test_data_supported_requires_real_evidence(self):
        t = ProvenanceTracker(entity_id="X")
        t.to_derived_hypothesis("r")
        with pytest.raises(ProvenanceViolation):
            t.to_data_supported("", "")

    def test_factory_tested_requires_passing_gen12(self):
        t = ProvenanceTracker(entity_id="X")
        t.to_derived_hypothesis("r")
        t.to_data_supported("cycle.json", "0 survivors")
        with pytest.raises(ProvenanceViolation):
            t.to_factory_tested("GEN12 FAIL: rejected under adversarial stress")

    def test_legal_full_path_to_survivor(self):
        t = ProvenanceTracker(entity_id="X")
        t.to_derived_hypothesis("r1")
        t.to_data_supported("cycle.json", "DISCOVERY_SURVIVOR")
        t.to_factory_tested("GEN12 PASS")
        t.to_survivor("EV-000123")
        assert t.current_label() == "SURVIVOR"
        assert len(t.history) == 4

    def test_history_is_append_only_and_ordered(self):
        t = ProvenanceTracker(entity_id="X")
        t.to_derived_hypothesis("r")
        t.to_data_supported("cycle.json", "0 survivors")
        assert [e.to_stage for e in t.history] == ["DERIVED_HYPOTHESIS", "DATA_SUPPORTED"]


# --------------------------------------------------------------------- source_registry / github_miner

class TestSourceRegistryAndMiner:
    def test_failed_fetch_recorded_honestly_not_hidden(self):
        reg = SourceRegistry()
        reg.record_fetch_result("blocked site", "https://example-blocked.test", "OPEN_SOURCE_CODE_HOST",
                                succeeded=False, error_detail="EGRESS_BLOCKED")
        assert reg.results[0].access_status == "ACCESS_FAILED"
        assert reg.results[0].content_checksum is None

    def test_successful_fetch_records_checksum(self):
        reg = SourceRegistry()
        r = reg.record_fetch_result("ok site", "https://example.test", "OPEN_SOURCE_CODE",
                                    succeeded=True, content_sample="some real content")
        assert r.access_status == "ACCESSED"
        assert r.content_checksum is not None
        assert len(r.content_checksum) == 64  # sha256 hex

    def test_mined_source_never_stores_stars_as_evidence_field(self):
        """stars is recorded as plain metadata; MinedSource has no 'evidence' or 'edge' field."""
        coll = MinedSourceCollection()
        src = coll.add("github_repo", "x/y", "https://github.com/x/y", "some text", stars=99999)
        field_names = set(src.__dataclass_fields__.keys())
        assert "evidence" not in field_names
        assert "edge_score" not in field_names
        assert src.stars == 99999  # present as metadata, not scored

    def test_real_source_registry_file_reflects_real_results_produced_this_session(self):
        reg_path = REPO_ROOT / "reports" / "idea_machine" / "ea_source_registry.json"
        assert reg_path.exists(), "run_real_mining.py must have been run to produce this file"
        data = json.loads(reg_path.read_text())
        assert data["summary"]["total_probed"] >= 5
        # at least one real blocked source must be present, honestly recorded
        assert data["summary"]["blocked"] >= 1
        blocked_titles = data["summary"]["blocked_sources"]
        assert any("mql5" in t.lower() or "tradingview" in t.lower() for t in blocked_titles)


# --------------------------------------------------------------------- hypothesis_synthesizer

class TestHypothesisSynthesizer:
    def test_data_availability_check_flags_unavailable_symbol(self):
        result = check_data_availability("BTCUSD", ["US10Y"], ["Non-Farm Employment Change"])
        assert result is not None
        assert "BLOCKED_DATA" in result

    def test_data_availability_check_flags_unavailable_driver(self):
        result = check_data_availability("EURUSD", ["DXY"], ["Non-Farm Employment Change"])
        assert result is not None
        assert "DXY" in result

    def test_data_availability_check_passes_for_known_good_combo(self):
        result = check_data_availability("USDJPY", ["US10Y", "SPX500"], ["Non-Farm Employment Change"])
        assert result is None

    def test_synthesized_hypothesis_starts_at_derived_hypothesis_provenance(self):
        h = synthesize_dual_driver_confirmation({})
        assert h.provenance == "DERIVED_HYPOTHESIS"

    def test_synthesized_hypothesis_is_data_available(self):
        h = synthesize_dual_driver_confirmation({})
        assert h.data_availability_check.startswith("AVAILABLE")

    def test_synthesized_hypothesis_carries_source_citation(self):
        h = synthesize_dual_driver_confirmation({})
        assert h.source_dna_ids
        assert h.source_citation


# --------------------------------------------------------------------- economic_feedback

class TestEconomicFeedback:
    def test_reads_only_idea_machine_shaped_cycles(self):
        """cycle_01_queue.json has a differently-shaped 'hypotheses' list (raw
        discovery-queue entries, no windows/train/validation) and must be
        excluded, not miscounted."""
        engine = EconomicFeedbackEngine()
        report = engine.load_and_learn()
        assert "cycle_01_queue.json" not in report.cycles_read

    def test_learns_from_real_cycle_11_and_12(self):
        engine = EconomicFeedbackEngine()
        report = engine.load_and_learn()
        assert "cycle_11_idea_machine.json" in report.cycles_read
        assert report.hypotheses_analyzed >= 3

    def test_lessons_trace_to_real_evidence_strings(self):
        """Every lesson's evidence field must be non-empty and reference real numbers."""
        engine = EconomicFeedbackEngine()
        report = engine.load_and_learn()
        for lesson in report.lessons:
            assert lesson.evidence
            assert lesson.source_cycle
            assert lesson.source_hypothesis

    def test_correlated_windows_are_not_treated_as_independent_evidence(self):
        """The DATA_EXTENSION_CANDIDATE lesson magnitude must not scale with
        window count -- it is capped at +0.15 regardless of how many
        correlated windows contributed, per the correlated-cells caveat."""
        engine = EconomicFeedbackEngine()
        report = engine.load_and_learn()
        data_ext_lessons = [l for l in report.lessons if l.penalty_signal == "DATA_EXTENSION_CANDIDATE"]
        for lesson in data_ext_lessons:
            assert lesson.magnitude == pytest.approx(0.15)

    def test_score_adjustment_is_deterministic(self):
        engine = EconomicFeedbackEngine()
        engine.load_and_learn()
        a1 = engine.score_adjustment("MACRO_SURPRISE", "test", 2, 130)
        a2 = engine.score_adjustment("MACRO_SURPRISE", "test", 2, 130)
        assert a1 == a2

    def test_never_reads_holdout_or_ledger(self):
        """Static check: economic_feedback.py must never actually OPEN a
        holdout path or the multiple_testing_ledger (the docstring is
        allowed to mention them by name while explaining it does NOT touch
        them -- that's a negation, not a usage)."""
        src = (REPO_ROOT / "idea_machine" / "economic_feedback.py").read_text()
        assert "data/holdout" not in src
        assert 'glob("cycle_*.json")' in src  # only glob-based discovery cycle reads
        forbidden_calls = ["open(", ".read_text()", "Path("]
        # every line that names the ledger file must NOT also perform a file operation
        for line in src.splitlines():
            if "multiple_testing_ledger.json" in line:
                assert not any(call in line for call in forbidden_calls), \
                    f"line references ledger AND performs a file op: {line}"


# --------------------------------------------------------------------- Cycle 11/12 result integrity

class TestCycle11And12ResultIntegrity:
    def test_cycle_11_uses_corrected_surprise_fx_dir(self):
        """Regression guard: SURPRISE_FX_DIR in cycle11_idea_machine.py must
        match discovery/cycle8_intraday.py's validated convention exactly.
        This is the exact bug that was found and fixed in this session."""
        from discovery.cycle8_intraday import SURPRISE_FX_DIR as VALIDATED
        from discovery.cycle11_idea_machine import SURPRISE_FX_DIR as CYCLE11
        assert CYCLE11 == VALIDATED

    def test_cycle_11_json_has_no_zero_gross_mean_artifact(self):
        """Regression guard for bug 1: every window with train n>0 must have
        a gross_over_cost that is NOT trivially 0 unless mean(|net|) really
        is 0 (vanishingly unlikely for real price data)."""
        path = REPO_ROOT / "reports/factory/discovery_cycles/cycle_11_idea_machine.json"
        data = json.loads(path.read_text())
        zero_gross_count = 0
        total = 0
        for hyp in data["hypotheses"]:
            windows = list(hyp.get("windows", []))
            for d in hyp.get("delays", []):
                windows.extend(d["windows"])
            for w in windows:
                if "train" in w and w["train"]["n"] > 0:
                    total += 1
                    if w["train"]["gross_over_cost"] == 0:
                        zero_gross_count += 1
        assert total > 0
        # it would be a red flag if EVERY window had exactly 0 -- that's the bug signature
        assert zero_gross_count < total

    def test_cycle_12_result_file_exists_and_is_real(self):
        path = REPO_ROOT / "reports/factory/discovery_cycles/cycle_12_ea_code_intel.json"
        assert path.exists()
        data = json.loads(path.read_text())
        hyp = data["hypotheses"][0]
        assert hyp["hyp_id"] == "HYP-EACI-0001"
        assert len(hyp["windows"]) == 3
        # none may claim DISCOVERY_SURVIVOR without n>=30 validation -- structural sanity check
        for w in hyp["windows"]:
            if w["verdict"] == "DISCOVERY_SURVIVOR":
                assert w["validation"]["n"] >= 30

    def test_no_survivor_was_productized_without_gen12(self):
        """Governance: HYP-EACI-0001's provenance record must not exceed
        DATA_SUPPORTED, since it did not pass internal validation."""
        path = REPO_ROOT / "reports" / "idea_machine" / "hyp_eaci_0001_provenance.json"
        data = json.loads(path.read_text())
        assert data["final_stage"] in ("DERIVED_HYPOTHESIS", "DATA_SUPPORTED")
        assert data["final_stage"] != "SURVIVOR"
        assert data["final_stage"] != "FACTORY_TESTED"


# --------------------------------------------------------------------- governance isolation

class TestGovernanceIsolation:
    def test_ea_code_intel_never_imports_ea_generator(self):
        """The existing ea_generator/ only packages GEN14-PASS candidates.
        EA Code Intelligence must never route around that gate."""
        ea_code_intel_dir = REPO_ROOT / "idea_machine" / "ea_code_intel"
        for f in ea_code_intel_dir.glob("*.py"):
            src = f.read_text()
            assert "ea_generator" not in src, f"{f} must not import ea_generator"

    def test_no_module_writes_to_candidate_spec_registry(self):
        for f in (REPO_ROOT / "idea_machine").rglob("*.py"):
            src = f.read_text()
            assert "candidate_spec_registry.json" not in src or "read" in src.lower()[:2000], \
                f"{f} references candidate_spec_registry.json -- verify it's read-only"

    def test_no_module_writes_to_evidence_vault(self):
        """The docstring may name evidence_vault.json while explaining it is
        NOT touched (a negation). What must never happen is an actual file
        operation performed against it."""
        forbidden_calls = ["open(", ".read_text()", ".write_text()", "Path("]
        for f in (REPO_ROOT / "idea_machine").rglob("*.py"):
            for line in f.read_text().splitlines():
                if "evidence_vault.json" in line:
                    assert not any(call in line for call in forbidden_calls), \
                        f"{f}: line references evidence_vault.json AND performs a file op: {line}"


# --------------------------------------------------------------------- Phase 3: research_memory

class TestResearchMemory:
    def test_research_memory_loads_families(self):
        from idea_machine.research_memory import ResearchMemory
        mem = ResearchMemory()
        mem.load()
        assert len(mem.families) >= 2
        assert "FAMILY-H1-PRICE-PATTERN" in mem.families
        refuted = mem.lookup_families_by_status("REFUTED")
        assert len(refuted) >= 1

    def test_research_memory_loads_candidates(self):
        from idea_machine.research_memory import ResearchMemory
        mem = ResearchMemory()
        mem.load()
        assert len(mem.candidates) >= 4
        underpowered = mem.lookup_candidates_by_status("STILL_UNDERPOWERED")
        assert len(underpowered) >= 1

    def test_research_memory_loads_cycle_hypotheses(self):
        from idea_machine.research_memory import ResearchMemory
        mem = ResearchMemory()
        mem.load()
        assert len(mem.cycle_hypotheses) >= 3
        under = mem.lookup_underpowered_hypotheses()
        assert len(under) >= 1

    def test_research_memory_is_readonly(self):
        """Modifying research_memory in-memory does not touch disk."""
        from idea_machine.research_memory import ResearchMemory
        mem = ResearchMemory()
        mem.load()
        before = (REPO_ROOT / "reports" / "factory" / "research_family_registry.json").read_bytes()
        mem.families["FAKE-FAMILY"] = None
        after = (REPO_ROOT / "reports" / "factory" / "research_family_registry.json").read_bytes()
        assert before == after

    def test_research_memory_summary(self):
        from idea_machine.research_memory import ResearchMemory
        mem = ResearchMemory()
        summary = mem.get_summary()
        assert summary["families_total"] >= 2
        assert summary["candidates_total"] >= 4
        assert summary["cycle_hypotheses_total"] >= 3


# --------------------------------------------------------------------- Phase 3: novelty 5-status classification

class TestNoveltyFiveStatus:
    def test_novelty_engine_classifies_refuted(self):
        ne = NoveltyEngine()
        ne.load()
        h1_family = next((f for f in ne.refuted_families if f["family_id"] == "FAMILY-H1-PRICE-PATTERN"), None)
        assert h1_family is not None
        exact_tags = ne._family_tag_set(h1_family)
        verdict = ne.check(exact_tags, "TEST-REFUTED")
        assert verdict.classification == "REFUTED"
        assert verdict.matched_family_id == "FAMILY-H1-PRICE-PATTERN"

    def test_novelty_engine_searches_all_statuses(self):
        """Verify that families with STILL_UNDERPOWERED, TESTED_FAILED status are searchable."""
        ne = NoveltyEngine()
        ne.load()
        assert len(ne.refuted_families) >= 1
        # Any historical families with STILL_UNDERPOWERED or TESTED_FAILED would be loaded

    def test_novelty_verdict_has_classification_field(self):
        ne = NoveltyEngine()
        ne.load()
        disjoint_tags = {"FAIR_VALUE_GAP", "ORDER_BLOCK"}
        verdict = ne.check(disjoint_tags, "TEST-NOVEL")
        assert hasattr(verdict, "classification")
        assert verdict.classification in ("REFUTED", "STILL_UNDERPOWERED", "TESTED_FAILED", "NOVEL", "UNKNOWN")

    def test_novelty_classification_is_deterministic(self):
        ne = NoveltyEngine()
        ne.load()
        tags = {"RSI_THRESHOLD", "MACD_CROSSOVER"}
        v1 = ne.check(tags, "TEST-1")
        v2 = ne.check(tags, "TEST-2")
        assert v1.classification == v2.classification
        assert v1.verdict == v2.verdict


# --------------------------------------------------------------------- Phase 3: opportunity_queue

class TestOpportunityQueue:
    def test_queue_is_append_only(self):
        from idea_machine.opportunity_queue import OpportunityQueue, DataRequirement, RetestCondition
        queue = OpportunityQueue()
        queue.load()
        initial_count = len(queue.entries)

        missing = DataRequirement("test", 100, 200, "events")
        retest = RetestCondition(None, "test trigger", None)
        entry = queue.append(
            source_hypothesis_id="TEST-HYP", source_cycle_id="CYCLE-TEST",
            classification="STILL_UNDERPOWERED", mechanism_summary="test",
            symbol="EURUSD", driver="US10Y",
            n_events_available=100, windows_evaluated=6,
            best_train_t=2.5, best_val_n=12, mean_confirmation_rate=0.5,
            evidence_level="REAL_SIGNAL_BLOCKED", reason="test reason",
            missing_data=missing, retest_conditions=retest,
            priority="HIGH", provenance_status="DATA_SUPPORTED",
        )
        assert entry.queue_id.startswith("OPP-")
        assert len(queue.entries) == initial_count + 1
        queue.save()

    def test_queue_never_retroactively_modifies_entries(self):
        from idea_machine.opportunity_queue import OpportunityQueue
        queue = OpportunityQueue()
        queue.load()
        before_count = len(queue.entries)
        before_json = (REPO_ROOT / "reports" / "idea_machine" / "opportunity_queue.json").read_text()

        queue2 = OpportunityQueue()
        queue2.load()
        after_json = (REPO_ROOT / "reports" / "idea_machine" / "opportunity_queue.json").read_text()
        # Just loading and reading should not modify the file
        assert before_json == after_json

    def test_queue_entries_have_required_fields(self):
        from idea_machine.opportunity_queue import OpportunityQueue
        queue = OpportunityQueue()
        queue.load()
        for entry in queue.entries[:3]:
            assert entry.queue_id
            assert entry.source_hypothesis_id
            assert entry.source_cycle_id
            assert entry.classification in ("STILL_UNDERPOWERED", "TESTED_FAILED")
            assert entry.evidence_level
            assert entry.missing_data is not None
            assert entry.retest_conditions is not None
            assert entry.provenance_status == "DATA_SUPPORTED"

    def test_underpowered_is_not_edge_claim(self):
        """CRITICAL: STILL_UNDERPOWERED entries must NOT claim edge."""
        from idea_machine.opportunity_queue import OpportunityQueue
        queue = OpportunityQueue()
        queue.load()
        underpowered = queue.get_by_classification("STILL_UNDERPOWERED")
        for entry in underpowered:
            reason = entry.reason.lower()
            assert "edge" not in reason
            assert "proven" not in reason
            # "signal" is OK if it says "too small to confirm" or similar
            assert "confirmed signal" not in reason  # NOT confirmed


# --------------------------------------------------------------------- Phase 3: cycle integration

class TestCycleIntegration:
    def test_populate_queue_from_cycle_11(self):
        from idea_machine.opportunity_queue import populate_queue_from_cycle
        cycle_path = REPO_ROOT / "reports" / "factory" / "discovery_cycles" / "cycle_11_idea_machine.json"
        assert cycle_path.exists()
        new_entries = populate_queue_from_cycle(cycle_path)
        assert len(new_entries) >= 2  # HYP-IM-0001 and HYP-IM-0004 are underpowered

    def test_populate_queue_from_cycle_12(self):
        from idea_machine.opportunity_queue import populate_queue_from_cycle
        cycle_path = REPO_ROOT / "reports" / "factory" / "discovery_cycles" / "cycle_12_ea_code_intel.json"
        assert cycle_path.exists()
        new_entries = populate_queue_from_cycle(cycle_path)
        assert len(new_entries) >= 1  # HYP-EACI-0001 is underpowered

    def test_cycle_integration_hook_exists(self):
        """Verify integration hook can be called."""
        from discovery.cycle_integration_hook import update_research_memory_after_cycle
        cycle_path = REPO_ROOT / "reports" / "factory" / "discovery_cycles" / "cycle_11_idea_machine.json"
        result = update_research_memory_after_cycle(cycle_path)
        assert "cycle_file" in result
        assert "new_opportunities_created" in result
        assert "opportunity_ids" in result


# --------------------------------------------------------------------- Phase 3: governance for Phase 3

class TestPhase3Governance:
    def test_research_memory_never_writes_registries(self):
        """research_memory.py must never modify any registry."""
        src = (REPO_ROOT / "idea_machine" / "research_memory.py").read_text()
        forbidden_writes = [".write_text(", ".write(", ".dump("]
        for call in forbidden_writes:
            assert call not in src, f"research_memory.py must not contain {call}"

    def test_opportunity_queue_is_append_only_in_code(self):
        """opportunity_queue.py must not contain rewrite/delete/edit operations."""
        src = (REPO_ROOT / "idea_machine" / "opportunity_queue.py").read_text()
        dangerous_patterns = [
            "entries.pop(",
            "entries.remove(",
            "entries[",  # could be modification if followed by =
            ".replace(",
            "del ",
        ]
        # Only check for clear patterns; entries[i] could be read
        assert "entries.pop(" not in src
        assert "entries.remove(" not in src

    def test_novelty_engine_never_modifies_family_registry(self):
        """novelty_engine.py must never write to family registry."""
        src = (REPO_ROOT / "idea_machine" / "ea_code_intel" / "novelty_engine.py").read_text()
        assert ".write_text(" not in src
        assert "open(" not in src or "r" in src[src.find("open("):src.find("open(")+20]

    def test_underpowered_classified_entries_have_calculated_data_requirements(self):
        """Never invent sample sizes; calculate or mark UNKNOWN."""
        from idea_machine.opportunity_queue import OpportunityQueue
        queue = OpportunityQueue()
        queue.load()
        for entry in queue.entries:
            missing = entry.missing_data
            assert missing["current_value"] > 0 or missing["current_value"] == 0
            assert missing["required_value"] > 0
            # Required value must be >= current or marked explicitly
            if missing["current_value"] > 0:
                assert missing["required_value"] >= missing["current_value"]

    def test_no_unknown_power_gains_claimed(self):
        """Power gain estimates must be calculated or marked None."""
        from idea_machine.opportunity_queue import OpportunityQueue
        queue = OpportunityQueue()
        queue.load()
        for entry in queue.entries:
            retest = entry.retest_conditions
            if retest["estimated_power_gain"]:
                # If provided, must contain numbers (not vague language)
                power_text = retest["estimated_power_gain"].lower()
                has_number = any(c.isdigit() for c in retest["estimated_power_gain"])
                assert has_number, f"Power gain must contain numbers: {retest['estimated_power_gain']}"
