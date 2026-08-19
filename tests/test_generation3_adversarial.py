"""Generation 3, Phase 25 — adversarial testing, all 20 named categories.

Every test is behavioral: it constructs the actual violation and asserts
the actual exception/detection. Categories already behaviorally covered
in tests/test_generation3_infrastructure.py are cross-referenced there
and covered here with a DIFFERENT attack variant, not duplicated.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from utils.helpers import utcnow

from core.factory.claim_registry import ClaimRecord, ClaimRegistry, ClaimSpecError
from core.factory.dataset_registry import DatasetRecord, DatasetSpecError
from core.factory.failure_library import FailureLibrary
from core.factory.hypothesis import HypothesisRegistry, HypothesisSpecError
from core.factory.hypothesis_formalization import FormalizationSpec, formalize_hypothesis
from core.factory.novelty_engine import FamilyRegistry, mechanism_signature, text_signature
from core.factory.preflight import run_preflight
from core.factory.research_budget import (
    BudgetTracker, KillSwitchTrippedError, ResearchBudget, ResearchBudgetExceededError, ResearchKillSwitch,
)
from core.factory.research_cache import ResearchCache, cache_key
from core.factory.research_ledger import ResearchLedger
from core.factory.research_source_registry import ResearchSourceRegistry, SourceRecord, SourceSpecError
from core.factory.search_space import FrozenSearchSpaceMutationError, SearchSpace, SearchSpaceRegistry
from core.factory.source_snapshot import SnapshotError, SourceSnapshotStore
from core.factory.strategy_dna import StrategyDNA
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError, ProvenanceEnforcer


def _source(**overrides):
    base = dict(source_id="SRC2-ADV3", source_type="YOUTUBE", title="adv fixture",
                retrieval_timestamp=utcnow().isoformat())
    base.update(overrides)
    return SourceRecord(**base)


def _search_space(**overrides):
    base = dict(
        search_space_id="SS-ADV3", symbols=("EURUSD",), timeframes=("H1",), features=("rsi_14",),
        feature_parameters={}, entry_conditions=("e",), exit_conditions=("x",), stop_loss_options=("s",),
        take_profit_options=("t",), holding_periods=(12,), regimes=("any",), position_sizing_options=("f",),
        cost_model="realistic", creation_timestamp=utcnow().isoformat(),
    )
    base.update(overrides)
    return SearchSpace(**base)


def _spec(**overrides):
    base = dict(
        inputs=("rsi_14",), condition="rsi_14 < 30", signal="cross above 30", target="ret over 12 bars",
        horizon_bars=12, direction="positive", regime="any", instrument_scope="EURUSD",
        cost_assumptions="realistic", falsification_rule="expectancy <= 0 after costs",
    )
    base.update(overrides)
    return FormalizationSpec(**base)


class Test01FakeSourceVerification:
    def test_access_failed_source_cannot_claim_reviewed_content(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(access_status="ACCESS_FAILED", content_checksum="a" * 64)

    def test_unknown_invented_verification_status_rejected(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(verification_status="TOTALLY_LEGIT")


class Test02MissingProvenance:
    def test_source_without_title_or_retrieval_time_rejected(self) -> None:
        with pytest.raises(SourceSpecError):
            _source(title="")
        with pytest.raises(SourceSpecError):
            _source(retrieval_timestamp="")


class Test03AlteredSourceSnapshot:
    def test_bitflipped_snapshot_blob_detected(self, tmp_path) -> None:
        store = SourceSnapshotStore(directory=tmp_path / "s")
        record = store.store(b"the original research text", source_id="S", representation="EXCERPT",
                             license_basis="PERMITTED_EXCERPT")
        blob = tmp_path / "s" / f"{record.snapshot_id}.bin"
        raw = bytearray(blob.read_bytes())
        raw[0] ^= 0xFF  # single bit-level alteration
        blob.write_bytes(bytes(raw))
        with pytest.raises(SnapshotError):
            store.read_verified(record.snapshot_id)


class Test04ClaimSourceMismatch:
    def test_fact_established_claim_without_evidence_rejected(self) -> None:
        with pytest.raises(ClaimSpecError):
            ClaimRecord(claim_id="C", source_id="S", claim_text="X", claim_type="OTHER",
                        creation_timestamp=utcnow().isoformat(), epistemic_status="FACT_ESTABLISHED")


class Test05ClaimStrengthening:
    def test_claim_records_are_frozen_text_cannot_be_rewritten(self) -> None:
        c = ClaimRecord(claim_id="C", source_id="S", claim_text="RSI might work sometimes",
                        claim_type="OTHER", creation_timestamp=utcnow().isoformat())
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.claim_text = "RSI definitely works"  # type: ignore[misc]

    def test_registry_status_transition_cannot_alter_claim_text(self, tmp_path) -> None:
        reg = ClaimRegistry(path=tmp_path / "c.json")
        cid = reg.allocate_claim_id()
        original = "It is commonly believed that RSI below 30 is oversold."
        reg.register(ClaimRecord(claim_id=cid, source_id="S", claim_text=original, claim_type="OTHER",
                                  creation_timestamp=utcnow().isoformat()))
        reg.transition_status(cid, "EXTRACTED", reason="ok")
        assert reg.get(cid).claim_text == original  # byte-identical after lifecycle changes


class Test06UnsupportedHypothesis:
    def test_supported_unreachable_without_linked_candidate(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "h.json")
        h = reg.register(source_type="BOOK", source_reference="R", original_claim="C",
                          origin_type="HUMAN_DERIVED")
        formalize_hypothesis(reg, h.hypothesis_id, _spec(), reason="x")
        reg.transition_formalization_status(h.hypothesis_id, "ELIGIBLE", reason="x")
        reg.transition_formalization_status(h.hypothesis_id, "TESTED", reason="x")
        with pytest.raises(HypothesisSpecError):
            reg.transition_formalization_status(h.hypothesis_id, "SUPPORTED", reason="popularity")


class Test07AIHypothesisPretendingVerified:
    def test_ai_hypothesis_cannot_be_constructed_as_verified_human_work(self, tmp_path) -> None:
        reg = HypothesisRegistry(path=tmp_path / "h.json")
        # attack: strip AI provenance and claim HUMAN_DERIVED while carrying AI provenance leftovers
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="HUMAN_HYPOTHESIS", source_reference="R", original_claim="C",
                         origin_type="HUMAN_DERIVED",
                         ai_provenance={"generation_model": "hidden"})
        # attack: AI_DERIVED with fabricated-empty provenance
        with pytest.raises(HypothesisSpecError):
            reg.register(source_type="AI_GENERATED_HYPOTHESIS", source_reference="R", original_claim="C",
                         origin_type="AI_DERIVED", ai_provenance={})


class Test08DuplicateHypothesis:
    def test_exact_duplicate_fails_preflight(self, tmp_path) -> None:
        from core.factory.dataset_registry import DatasetRegistry

        hyp_reg = HypothesisRegistry(path=tmp_path / "h.json")
        fam = FamilyRegistry(path=tmp_path / "f.json")
        statement = "RSI 14 oversold reverts within 12 bars"
        h1 = hyp_reg.register(source_type="BOOK", source_reference="R", original_claim=statement)
        h2 = hyp_reg.register(source_type="BOOK", source_reference="R2", original_claim=statement)
        for h in (h1, h2):
            formalize_hypothesis(hyp_reg, h.hypothesis_id, _spec(), reason="x")
            fam.assign(family_kind="HYPOTHESIS_FAMILY",
                       family_signature=mechanism_signature(hyp_reg.get(h.hypothesis_id).original_claim),
                       member_id=h.hypothesis_id, description="d")
        statements = {h.hypothesis_id: h.original_claim for h in hyp_reg.list_all()}
        ds_reg = DatasetRegistry(path=tmp_path / "ds.json")  # empty -> data failures too, but we check DUPLICATE
        failures = run_preflight(hyp_reg.get(h2.hypothesis_id), _search_space(),
                                 dataset_registry=ds_reg, family_registry=fam,
                                 known_statements=statements)
        assert any(f.startswith("DUPLICATE_STATUS") for f in failures)


class Test09FamilyDuplication:
    def test_parameter_variants_collapse_into_one_family_not_independent_research(self, tmp_path) -> None:
        fam = FamilyRegistry(path=tmp_path / "f.json")
        for i, statement in enumerate(["RSI 10 oversold reverts", "RSI 14 oversold reverts",
                                        "RSI 20 oversold reverts", "RSI 30 oversold reverts"]):
            fam.assign(family_kind="HYPOTHESIS_FAMILY", family_signature=mechanism_signature(statement),
                       member_id=f"HYP-{i}", description="rsi variants")
        families = [f for f in fam.list_all() if f.family_kind == "HYPOTHESIS_FAMILY"]
        assert len(families) == 1 and len(families[0].members) == 4


class Test10SearchSpaceExplosion:
    def test_oversized_search_space_blocked_by_budget(self) -> None:
        tracker = BudgetTracker(ResearchBudget(max_sources=1, max_hypotheses=1, max_candidates=1,
                                                max_search_space_size=100, max_candidates_per_family=1))
        big = _search_space(holding_periods=tuple(range(1, 20)), stop_loss_options=tuple(f"{i}x" for i in range(1, 10)))
        with pytest.raises(ResearchBudgetExceededError):
            tracker.check_search_space(big.combination_count())


class Test11CandidateExplosion:
    def test_runaway_candidate_generation_stops_at_budget(self) -> None:
        tracker = BudgetTracker(ResearchBudget(max_sources=1, max_hypotheses=1, max_candidates=3,
                                                max_search_space_size=100, max_candidates_per_family=10))
        for _ in range(3):
            tracker.charge("candidates")
        with pytest.raises(ResearchBudgetExceededError):
            tracker.charge("candidates")
        assert tracker.usage()["candidates"] == 3  # evidence preserved, no overshoot


class Test12CacheInvalidation:
    def test_stale_hit_impossible_when_code_version_changes(self, tmp_path) -> None:
        cache = ResearchCache(path=tmp_path / "cache.json")
        deps = dict(dataset_checksum="d", feature_version="FE-R2-003", hypothesis_checksum="h",
                    search_space_checksum="s", code_version="v1", cost_model="realistic", random_seed=1)
        cache.put(cache_key(**deps), {"result": "old"})
        assert cache.get(cache_key(**{**deps, "code_version": "v2"})) is None


class Test13FingerprintCollisionHandling:
    def test_distinct_strategies_produce_distinct_fingerprints_and_family_split_is_conservative(self) -> None:
        a = StrategyDNA(market="EURUSD", timeframe="H1", features=("rsi_14",), feature_parameters="p=14",
                        entry="rsi cross above 30", exit="stop", regime="any", risk="sl=1.5xATR",
                        holding_period="12", cost_model="realistic")
        b = StrategyDNA(market="XAUUSD", timeframe="H1", features=("rsi_14",), feature_parameters="p=14",
                        entry="rsi cross above 30", exit="stop", regime="any", risk="sl=1.5xATR",
                        holding_period="12", cost_model="realistic")
        assert a.fingerprint() != b.fingerprint()
        assert a.family_fingerprint() != b.family_fingerprint()  # market differs -> not one family


class Test14MissingLedgerEvent:
    def test_ledger_checksum_exposes_a_silently_removed_event(self, tmp_path) -> None:
        path = tmp_path / "ledger.json"
        ledger = ResearchLedger(path=path)
        ledger.append("SOURCE_INGESTED", subject_id="S1", reason="a")
        ledger.append("CLAIM_CREATED", subject_id="C1", reason="b")
        full_checksum = ledger.ledger_checksum()
        raw = json.loads(path.read_text())
        raw["events"] = raw["events"][:1]  # attacker deletes an event at the file level
        path.write_text(json.dumps(raw))
        assert ResearchLedger(path=path).ledger_checksum() != full_checksum


class Test15ResearchBudgetExhaustion:
    def test_source_budget_stops_intake_without_losing_prior_records(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "s.json")
        tracker = BudgetTracker(ResearchBudget(max_sources=2, max_hypotheses=1, max_candidates=1,
                                                max_search_space_size=10, max_candidates_per_family=1))
        for i in range(2):
            tracker.charge("sources")
            reg.register(_source(source_id=f"SRC2-B{i}"))
        with pytest.raises(ResearchBudgetExceededError):
            tracker.charge("sources")
        assert len(reg.list_all()) == 2  # already-recorded evidence preserved


class Test16KillSwitch:
    def test_duplicate_explosion_trips_and_blocks_but_preserves_registries(self, tmp_path) -> None:
        ks = ResearchKillSwitch(path=tmp_path / "ks.json")
        reg = ResearchSourceRegistry(path=tmp_path / "s.json")
        reg.register(_source(source_id="SRC2-K1"))
        with pytest.raises(KillSwitchTrippedError):
            ks.check_metric("DUPLICATE_EXPLOSION", metric=500, threshold=100, reason="dup ratio runaway")
        with pytest.raises(KillSwitchTrippedError):
            ks.assert_not_tripped()
        assert len(reg.list_all()) == 1  # nothing deleted by the safety stop


class Test17HoldoutLeakageAttempt:
    def test_holdout_cannot_be_read_for_research_discovery(self) -> None:
        enforcer = ProvenanceEnforcer(hypothesis_id="GEN3-DISCOVERY")
        for action in (DataAccessAction.TRAINING, DataAccessAction.SELECTION):
            with pytest.raises(DataStateViolationError):
                enforcer.validate_access(DataState.PURE_HOLDOUT, action)

    def test_research_knowledge_has_no_channel_for_holdout_performance(self) -> None:
        from core.factory.research_prioritization import ResearchKnowledge

        with pytest.raises(TypeError):
            ResearchKnowledge(holdout_return=0.35)  # type: ignore[call-arg]


class Test18ResultInformedHypothesisMutation:
    def test_formalized_hypothesis_cannot_be_reformalized_in_place(self, tmp_path) -> None:
        """The 'saw a result, quietly re-tuned the hypothesis' attack:
        re-formalization of an already-FORMALIZED hypothesis is refused;
        a materially different formalization must be a new hypothesis."""
        from core.factory.hypothesis_formalization import FormalizationSpecError

        reg = HypothesisRegistry(path=tmp_path / "h.json")
        h = reg.register(source_type="BOOK", source_reference="R", original_claim="C")
        formalize_hypothesis(reg, h.hypothesis_id, _spec(horizon_bars=12), reason="x")
        with pytest.raises(FormalizationSpecError):
            formalize_hypothesis(reg, h.hypothesis_id, _spec(horizon_bars=24), reason="revise after results")


class Test19SourceSubstitution:
    def test_new_version_never_masquerades_as_the_original(self, tmp_path) -> None:
        reg = ResearchSourceRegistry(path=tmp_path / "s.json")
        reg.register(_source(source_id="SRC2-SUB1", title="Original talk"))
        replacement = reg.new_version("SRC2-SUB1", title="Different talk found later")
        assert replacement.source_id != "SRC2-SUB1"
        assert replacement.supersedes_source_id == "SRC2-SUB1"
        assert reg.get("SRC2-SUB1").title == "Original talk"  # the original is never rewritten

    def test_registering_a_different_source_under_an_existing_id_is_refused(self, tmp_path) -> None:
        from core.factory.research_source_registry import DuplicateSourceError

        reg = ResearchSourceRegistry(path=tmp_path / "s.json")
        reg.register(_source(source_id="SRC2-SUB2", title="A"))
        with pytest.raises(DuplicateSourceError):
            reg.register(_source(source_id="SRC2-SUB2", title="B pretending to be A"))


class Test20FabricatedPassState:
    def test_synthetic_dataset_cannot_carry_verified_real_provenance(self) -> None:
        with pytest.raises(DatasetSpecError):
            DatasetRecord(
                dataset_id="D", instrument="EURUSD", timeframe="H1", source_id="S", source_url="u",
                download_timestamp="2026-01-01T00:00:00+00:00", timezone="UTC", price_type="mid",
                coverage_start="2020-01-01T00:00:00+00:00", coverage_end="2021-01-01T00:00:00+00:00",
                row_count=1, duplicate_count=0, missing_bar_count=0, gap_report={}, checksum="x",
                file_checksum="x", download_method="curl", synthetic=True, provenance_status="VERIFIED",
                integrity_status="PASS", verification_method="fabricated",
            )

    def test_hypothesis_cannot_be_born_supported(self) -> None:
        from core.factory.hypothesis import HypothesisRecord

        with pytest.raises(HypothesisSpecError):
            HypothesisRecord(
                hypothesis_id="HYP-FAKE", source_type="BOOK", source_reference="R", original_claim="C",
                date_captured=utcnow().isoformat(), formalization_status="SUPPORTED",
            )

    def test_search_space_mutation_under_frozen_id_rejected(self, tmp_path) -> None:
        reg = SearchSpaceRegistry(path=tmp_path / "ss.json")
        reg.register(_search_space())
        with pytest.raises(FrozenSearchSpaceMutationError):
            reg.register(_search_space(cost_model="zero -- rewritten to look better"))
