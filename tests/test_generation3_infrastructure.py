"""Generation 3 infrastructure unit tests: source intake statuses,
snapshots, claim epistemic discipline, hypothesis origins/AI provenance,
novelty/families, strategy DNA, prioritization/information gain,
pre-flight, failure library, cache, budgets, kill switch, diversity.
"""

from __future__ import annotations

import dataclasses

import pytest
from utils.helpers import utcnow

from core.factory.claim_registry import ClaimRecord, ClaimSpecError
from core.factory.failure_library import FailureLibrary, FailureLibraryError
from core.factory.hypothesis import HypothesisRecord, HypothesisRegistry, HypothesisSpecError
from core.factory.novelty_engine import (
    FamilyRegistry,
    is_exact_duplicate,
    is_near_duplicate,
    is_same_mechanism,
    mechanism_signature,
    text_signature,
    token_jaccard,
)
from core.factory.preflight import run_preflight
from core.factory.research_budget import (
    BudgetTracker,
    KillSwitchTrippedError,
    ResearchBudget,
    ResearchBudgetExceededError,
    ResearchKillSwitch,
)
from core.factory.research_cache import ResearchCacheError, ResearchCache, cache_key
from core.factory.research_diversity import compute_diversity_report
from core.factory.research_prioritization import (
    PrioritizationError,
    PriorityDimensions,
    ResearchKnowledge,
    expected_information_value,
    novelty_from_knowledge,
    score_priority,
)
from core.factory.research_source_registry import SourceRecord, SourceSpecError
from core.factory.source_snapshot import SnapshotError, SourceSnapshotStore
from core.factory.strategy_dna import StrategyDNA, component_matches, similarity


def _source(**overrides):
    base = dict(source_id="SRC2-G3-001", source_type="YOUTUBE", title="fixture", retrieval_timestamp=utcnow().isoformat())
    base.update(overrides)
    return SourceRecord(**base)


def _ai_provenance(**overrides):
    base = dict(
        generation_model="fixture-model-identity-withheld",
        generation_timestamp=utcnow().isoformat(),
        prompt_identity="deadbeef" * 8,
        input_source_ids=["SRC2-G3-001"],
        input_claim_ids=["CLAIM-000001"],
    )
    base.update(overrides)
    return base


class TestSourceAccessStatus:
    def test_access_failed_is_a_first_class_recordable_state(self) -> None:
        s = _source(access_status="ACCESS_FAILED", verification_status="ACCESS_FAILED")
        assert s.access_status == "ACCESS_FAILED"

    def test_access_failed_source_cannot_claim_a_content_checksum(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(access_status="ACCESS_FAILED", content_checksum="deadbeef" * 8)

    def test_unknown_access_status_rejected(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(access_status="PROBABLY_FINE")

    def test_generation3_verification_statuses_accepted(self) -> None:
        for status in ("VERIFIED", "PROVISIONALLY_VERIFIED", "ACCESS_FAILED", "REJECTED"):
            _source(verification_status=status)


class TestSourceSnapshotStore:
    def test_snapshot_is_content_addressed_and_reproducible(self, tmp_path) -> None:
        store = SourceSnapshotStore(directory=tmp_path / "snaps")
        r1 = store.store(b"real research bytes", source_id="S", representation="EXCERPT",
                         license_basis="PERMITTED_EXCERPT")
        r2 = store.store(b"real research bytes", source_id="S", representation="EXCERPT",
                         license_basis="PERMITTED_EXCERPT")
        assert r1.snapshot_id == r2.snapshot_id  # identical content -> identical identity
        r3 = store.store(b"materially different bytes", source_id="S", representation="EXCERPT",
                         license_basis="PERMITTED_EXCERPT")
        assert r3.snapshot_id != r1.snapshot_id

    def test_storage_without_a_stated_legal_basis_is_refused(self, tmp_path) -> None:
        store = SourceSnapshotStore(directory=tmp_path / "snaps")
        with pytest.raises(SnapshotError):
            store.store(b"content", source_id="S", representation="FULL_TEXT", license_basis="NO_BASIS_STATED")

    def test_altered_blob_is_detected_on_read(self, tmp_path) -> None:
        store = SourceSnapshotStore(directory=tmp_path / "snaps")
        record = store.store(b"original", source_id="S", representation="EXCERPT",
                             license_basis="PERMITTED_EXCERPT")
        blob = tmp_path / "snaps" / f"{record.snapshot_id}.bin"
        blob.write_bytes(b"tampered")
        with pytest.raises(SnapshotError):
            store.read_verified(record.snapshot_id)

    def test_verified_read_returns_original_bytes(self, tmp_path) -> None:
        store = SourceSnapshotStore(directory=tmp_path / "snaps")
        record = store.store(b"original", source_id="S", representation="EXCERPT",
                             license_basis="PERMITTED_EXCERPT")
        assert store.read_verified(record.snapshot_id) == b"original"


class TestClaimEpistemicDiscipline:
    def test_fact_established_requires_evidence_reference(self) -> None:
        with pytest.raises(ClaimSpecError):
            ClaimRecord(
                claim_id="C1", source_id="S1", claim_text="X is true", claim_type="PREDICTIVE_SIGNAL",
                creation_timestamp=utcnow().isoformat(), epistemic_status="FACT_ESTABLISHED",
            )

    def test_fact_established_with_evidence_constructs(self) -> None:
        c = ClaimRecord(
            claim_id="C1", source_id="S1", claim_text="X was tested", claim_type="PREDICTIVE_SIGNAL",
            creation_timestamp=utcnow().isoformat(), epistemic_status="FACT_ESTABLISHED",
            evidence_reference="SOME-REPORT.md",
        )
        assert c.epistemic_status == "FACT_ESTABLISHED"

    def test_default_epistemic_status_is_source_claim(self) -> None:
        c = ClaimRecord(claim_id="C1", source_id="S1", claim_text="X", claim_type="OTHER",
                        creation_timestamp=utcnow().isoformat())
        assert c.epistemic_status == "SOURCE_CLAIM"

    def test_unknown_classification_rejected(self) -> None:
        with pytest.raises(ClaimSpecError):
            ClaimRecord(claim_id="C1", source_id="S1", claim_text="X", claim_type="OTHER",
                        creation_timestamp=utcnow().isoformat(), claim_classification="GOSPEL")


class TestHypothesisOriginsAndAIProvenance:
    def test_cross_source_synthesis_requires_two_or_more_parents(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="BOOK", source_reference="R", original_claim="C",
                         origin_type="CROSS_SOURCE_SYNTHESIS", parent_claim_ids=("CLAIM-1",))
        h = reg.register(source_type="BOOK", source_reference="R", original_claim="C",
                          origin_type="CROSS_SOURCE_SYNTHESIS",
                          parent_claim_ids=("CLAIM-1", "CLAIM-2"))
        assert h.parent_claim_ids == ("CLAIM-1", "CLAIM-2")

    def test_ai_derived_requires_full_provenance_keys(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="AI_GENERATED_HYPOTHESIS", source_reference="R", original_claim="C",
                         origin_type="AI_DERIVED", ai_provenance={"generation_model": "x"})
        h = reg.register(source_type="AI_GENERATED_HYPOTHESIS", source_reference="R", original_claim="C",
                          origin_type="AI_DERIVED", ai_provenance=_ai_provenance())
        assert h.origin_type == "AI_DERIVED"

    def test_non_ai_hypothesis_cannot_carry_ai_provenance(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="BOOK", source_reference="R", original_claim="C",
                         origin_type="HUMAN_DERIVED", ai_provenance=_ai_provenance())

    def test_supported_requires_a_linked_candidate_for_any_origin(self, tmp_path) -> None:
        """The independent-evidence-path guard: AI plausibility (or any
        origin's confidence) can never reach SUPPORTED without a real
        linked candidate."""
        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="AI_GENERATED_HYPOTHESIS", source_reference="R", original_claim="C",
                          origin_type="AI_DERIVED", ai_provenance=_ai_provenance())
        reg.formalize(h.hypothesis_id, formalized_trading_rule="rule")
        reg.transition_formalization_status(h.hypothesis_id, "FORMALIZED", reason="x")
        reg.transition_formalization_status(h.hypothesis_id, "ELIGIBLE", reason="x")
        reg.transition_formalization_status(h.hypothesis_id, "TESTED", reason="x")
        with pytest.raises(HypothesisSpecError):
            reg.transition_formalization_status(h.hypothesis_id, "SUPPORTED", reason="AI is confident")
        reg.link_candidate(h.hypothesis_id, "STRAT-999999")
        reg.transition_formalization_status(h.hypothesis_id, "SUPPORTED", reason="candidate evidence exists")

    def test_lineage_round_trips_through_persistence(self, tmp_path) -> None:
        path = tmp_path / "hyp.json"
        reg = HypothesisRegistry(path=path)
        reg.register(source_type="BOOK", source_reference="R", original_claim="C",
                     origin_type="CROSS_SOURCE_SYNTHESIS",
                     parent_source_ids=("S1", "S2"), parent_claim_ids=("C1", "C2"))
        reloaded = HypothesisRegistry(path=path)
        h = reloaded.list_all()[0]
        assert h.parent_source_ids == ("S1", "S2")
        assert h.parent_claim_ids == ("C1", "C2")


class TestNoveltyEngine:
    def test_exact_duplicate_ignores_case_and_punctuation(self) -> None:
        assert is_exact_duplicate("RSI-14 works!", "rsi 14 works")

    def test_parameter_variants_share_a_mechanism(self) -> None:
        variants = ["RSI 10 oversold reverts", "RSI 14 oversold reverts", "RSI 20 oversold reverts",
                    "RSI 30 oversold reverts"]
        signatures = {mechanism_signature(v) for v in variants}
        assert len(signatures) == 1  # one family

    def test_different_mechanisms_stay_distinct(self) -> None:
        assert not is_same_mechanism("RSI 14 oversold reverts", "MACD crossover continues")

    def test_near_duplicate_detects_rewording(self) -> None:
        a = "momentum tends to persist in trending markets over time"
        b = "in trending markets momentum tends to persist over time"
        assert is_near_duplicate(a, b, threshold=0.8)
        assert not is_near_duplicate(a, "volatility clusters around macro events", threshold=0.8)

    def test_family_registry_preserves_members_append_only(self, tmp_path) -> None:
        reg = FamilyRegistry(path=tmp_path / "fam.json")
        sig = mechanism_signature("rsi N oversold reverts")
        f1 = reg.assign(family_kind="HYPOTHESIS_FAMILY", family_signature=sig, member_id="HYP-1", description="rsi")
        f2 = reg.assign(family_kind="HYPOTHESIS_FAMILY", family_signature=sig, member_id="HYP-2", description="rsi")
        assert f1.family_id == f2.family_id
        assert reg.member_count(f1.family_id) == 2
        # idempotent re-assign does not duplicate
        reg.assign(family_kind="HYPOTHESIS_FAMILY", family_signature=sig, member_id="HYP-2", description="rsi")
        assert reg.member_count(f1.family_id) == 2

    def test_family_registry_survives_reload(self, tmp_path) -> None:
        path = tmp_path / "fam.json"
        reg = FamilyRegistry(path=path)
        sig = mechanism_signature("x")
        f = reg.assign(family_kind="STRATEGY_FAMILY", family_signature=sig, member_id="STRAT-X", description="d")
        reloaded = FamilyRegistry(path=path)
        assert reloaded.member_count(f.family_id) == 1


class TestStrategyDNA:
    def _dna(self, **overrides) -> StrategyDNA:
        base = dict(
            market="EURUSD", timeframe="H1", features=("rsi_14", "atr_14"),
            feature_parameters="rsi_period=14", entry="rsi crosses above 30", exit="stop or target",
            regime="any", risk="sl=1.5xATR sizing=fixed", holding_period="12", cost_model="realistic",
        )
        base.update(overrides)
        return StrategyDNA(**base)

    def test_fingerprint_changes_with_any_component(self) -> None:
        a = self._dna()
        b = self._dna(entry="macd crossover")
        assert a.fingerprint() != b.fingerprint()

    def test_family_fingerprint_ignores_parameter_numbers(self) -> None:
        a = self._dna(feature_parameters="rsi_period=10", holding_period="12")
        b = self._dna(feature_parameters="rsi_period=20", holding_period="24")
        assert a.fingerprint() != b.fingerprint()
        assert a.family_fingerprint() == b.family_fingerprint()

    def test_similarity_is_decomposable(self) -> None:
        a = self._dna()
        b = self._dna(entry="macd crossover", exit="trailing stop")
        matches = component_matches(a, b)
        assert matches["market"] is True and matches["entry"] is False and matches["exit"] is False
        assert similarity(a, b) == sum(matches.values()) / len(matches)

    def test_no_auto_rejection_api_exists(self) -> None:
        import core.factory.strategy_dna as mod

        assert not any("reject" in name.lower() for name in dir(mod))


class TestPrioritizationAndInformationGain:
    def test_priority_score_is_decomposable_mean(self) -> None:
        dims = PriorityDimensions(novelty=1.0, data_availability=1.0)
        score = score_priority(dims)
        assert score.total == sum(score.dimensions.values()) / len(score.dimensions)
        assert "NOT economic edge probability" in score.to_dict()["meaning"]

    def test_dimensions_outside_unit_interval_rejected(self) -> None:
        with pytest.raises(PrioritizationError):
            PriorityDimensions(novelty=1.5)

    def test_novelty_decays_with_prior_family_testing(self) -> None:
        fresh = novelty_from_knowledge(ResearchKnowledge())
        tested_100 = novelty_from_knowledge(ResearchKnowledge(family_prior_test_count=100))
        assert fresh == 1.0 and tested_100 < 0.02

    def test_information_value_prioritizes_novel_cheap_testable_work(self) -> None:
        # the task's own example: A = cheap, low novelty, tested 100x; B = moderate cost, novel
        a = expected_information_value(
            novelty=novelty_from_knowledge(ResearchKnowledge(family_prior_test_count=100)),
            testability=0.9, computational_cost_efficiency=0.9,
        )
        b = expected_information_value(novelty=1.0, testability=0.8, computational_cost_efficiency=0.5)
        assert b > a

    def test_research_knowledge_structurally_cannot_carry_performance_metrics(self) -> None:
        """The Phase 16 firewall: the feedback dataclass has ONLY count
        fields -- there is no field a holdout return could be smuggled
        through, and non-integer values are rejected."""
        field_names = {f.name for f in dataclasses.fields(ResearchKnowledge)}
        assert field_names == {"family_prior_test_count", "family_prior_failure_count", "family_member_count"}
        with pytest.raises(PrioritizationError):
            ResearchKnowledge(family_prior_test_count=0.35)  # type: ignore[arg-type]


class TestFailureLibrary:
    def test_record_and_count_by_family(self, tmp_path) -> None:
        lib = FailureLibrary(path=tmp_path / "fail.json")
        lib.record(entity_id="HYP-1", failure_stage="PREFLIGHT", failure_category="INSUFFICIENT_HISTORY",
                   failure_reason="too few rows", related_family="FAMILY-000001")
        lib.record(entity_id="HYP-2", failure_stage="WFA", failure_category="NO_SIGNAL",
                   failure_reason="flat IC", related_family="FAMILY-000001")
        assert lib.count_by_family("FAMILY-000001") == 2
        assert lib.count_by_category()["NO_SIGNAL"] == 1

    def test_unknown_category_rejected(self, tmp_path) -> None:
        lib = FailureLibrary(path=tmp_path / "fail.json")
        with pytest.raises(FailureLibraryError):
            lib.record(entity_id="X", failure_stage="WFA", failure_category="BAD_LUCK", failure_reason="r")

    def test_no_delete_method_exists(self) -> None:
        methods = [m for m in dir(FailureLibrary) if not m.startswith("_")]
        assert not any("delete" in m.lower() or "remove" in m.lower() for m in methods)

    def test_records_survive_reload(self, tmp_path) -> None:
        path = tmp_path / "fail.json"
        lib = FailureLibrary(path=path)
        lib.record(entity_id="X", failure_stage="INTAKE", failure_category="SOURCE_ACCESS_FAILED", failure_reason="r")
        assert len(FailureLibrary(path=path).all_failures()) == 1


class TestResearchCache:
    def _deps(self, **overrides):
        base = dict(dataset_checksum="d", feature_version="FE-R2-003", hypothesis_checksum="h",
                    search_space_checksum="s", code_version="c", cost_model="realistic", random_seed=42)
        base.update(overrides)
        return base

    def test_missing_required_dependency_rejected(self) -> None:
        deps = self._deps()
        del deps["dataset_checksum"]
        with pytest.raises(ResearchCacheError):
            cache_key(**deps)

    def test_any_dependency_change_invalidates(self, tmp_path) -> None:
        cache = ResearchCache(path=tmp_path / "cache.json")
        key = cache_key(**self._deps())
        cache.put(key, {"result": "computed-under-original-deps"})
        assert cache.get(key) == {"result": "computed-under-original-deps"}
        for changed in (self._deps(dataset_checksum="d2"), self._deps(random_seed=43),
                        self._deps(code_version="c2"), self._deps(cost_model="zero")):
            assert cache.get(cache_key(**changed)) is None  # guaranteed miss

    def test_extra_declared_dependencies_also_affect_the_key(self) -> None:
        assert cache_key(**self._deps(), extra_dep="a") != cache_key(**self._deps(), extra_dep="b")


class TestBudgetsAndKillSwitch:
    def _budget(self, **overrides):
        base = dict(max_sources=2, max_hypotheses=2, max_candidates=2, max_search_space_size=100,
                    max_candidates_per_family=1)
        base.update(overrides)
        return ResearchBudget(**base)

    def test_budget_exhaustion_stops_generation(self) -> None:
        tracker = BudgetTracker(self._budget())
        tracker.charge("hypotheses")
        tracker.charge("hypotheses")
        with pytest.raises(ResearchBudgetExceededError):
            tracker.charge("hypotheses")
        assert tracker.usage()["hypotheses"] == 2  # never overshoots

    def test_per_family_candidate_budget(self) -> None:
        tracker = BudgetTracker(self._budget())
        tracker.charge("candidates", family_id="FAMILY-1")
        with pytest.raises(ResearchBudgetExceededError):
            tracker.charge("candidates", family_id="FAMILY-1")  # family cap = 1

    def test_search_space_size_budget(self) -> None:
        tracker = BudgetTracker(self._budget(max_search_space_size=10))
        tracker.check_search_space(10)
        with pytest.raises(ResearchBudgetExceededError):
            tracker.check_search_space(11)

    def test_unbounded_budget_is_not_representable(self) -> None:
        from core.factory.research_budget import ResearchBudgetError

        with pytest.raises(ResearchBudgetError):
            self._budget(max_candidates=-1)

    def test_kill_switch_trips_persistently_and_blocks_generation(self, tmp_path) -> None:
        path = tmp_path / "ks.json"
        ks = ResearchKillSwitch(path=path)
        ks.assert_not_tripped()
        with pytest.raises(KillSwitchTrippedError):
            ks.check_metric("CANDIDATE_EXPLOSION", metric=1_000_001, threshold=1_000_000,
                            reason="candidate generation runaway")
        # persistence: a NEW instance loading the same state stays tripped
        with pytest.raises(KillSwitchTrippedError):
            ResearchKillSwitch(path=path).assert_not_tripped()

    def test_kill_switch_has_no_reset_api(self) -> None:
        methods = [m for m in dir(ResearchKillSwitch) if not m.startswith("_")]
        assert "reset" not in methods and "clear" not in methods

    def test_corrupted_kill_switch_state_fails_closed(self, tmp_path) -> None:
        path = tmp_path / "ks.json"
        path.write_text("{not json")
        with pytest.raises(KillSwitchTrippedError):
            ResearchKillSwitch(path=path).assert_not_tripped()


class TestDiversityReport:
    def test_diversity_counts_and_concentration(self, tmp_path) -> None:
        from core.factory.research_source_registry import ResearchSourceRegistry

        src = ResearchSourceRegistry(path=tmp_path / "src.json")
        for i, st in enumerate(["YOUTUBE", "YOUTUBE", "YOUTUBE", "ACADEMIC_PAPER"]):
            src.register(_source(source_id=f"SRC2-D{i:03d}", source_type=st))
        report = compute_diversity_report(source_registry=src, concentration_flag_threshold=0.7)
        assert report["by_source_type"] == {"YOUTUBE": 3, "ACADEMIC_PAPER": 1}
        assert "CONCENTRATION:source_type_max_share" in report["concentration_flags"]
        assert "not itself optimized" in report["meaning"]
