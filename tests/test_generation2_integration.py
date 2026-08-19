"""Generation 2, Phase 15 — end-to-end integration proof.

SOURCE -> CLAIM -> HYPOTHESIS -> FORMALIZATION -> SEARCH SPACE ->
CANDIDATE -> RESEARCH LEDGER -> SEARCH ACCOUNTING -> REGISTRY

Uses a SMALL, controlled, entirely synthetic fixture. This does NOT claim
economic edge -- no real market data is touched, no candidate produced
here is registered in the production strategy_registry.json (every
registry in this file uses tmp_path), and per the task's explicit rule
25, this fixture-generated candidate is a TEST candidate only: it is
never treated as, or capable of becoming, STRAT-000002. The real
production registry (containing STRAT-000001) is never opened by this
file.
"""

from __future__ import annotations

from utils.helpers import utcnow

from core.factory.candidate_generation_engine import generate_and_register_candidate
from core.factory.claim_registry import ClaimRecord, ClaimRegistry
from core.factory.hypothesis import HypothesisRegistry
from core.factory.hypothesis_formalization import FormalizationSpec, formalize_hypothesis
from core.factory.hypothesis_quality_gates import assert_hypothesis_eligible_for_candidate_generation
from core.factory.registry import StrategyRegistry
from core.factory.research_accounting import compute_search_accounting_summary
from core.factory.research_ledger import ResearchLedger
from core.factory.research_source_registry import ResearchSourceRegistry, SourceRecord
from core.factory.search_space import SearchSpace, SearchSpaceRegistry
from core.factory.state_machine import CandidateState


class TestGeneration2EndToEndPipeline:
    def test_source_to_registry_full_pipeline(self, tmp_path) -> None:
        source_reg = ResearchSourceRegistry(path=tmp_path / "sources.json")
        claim_reg = ClaimRegistry(path=tmp_path / "claims.json")
        hyp_reg = HypothesisRegistry(path=tmp_path / "hypotheses.json")
        ss_reg = SearchSpaceRegistry(path=tmp_path / "search_spaces.json")
        strat_reg = StrategyRegistry(path=tmp_path / "strategy_registry.json")
        ledger = ResearchLedger(path=tmp_path / "ledger.json")

        # 1. SOURCE
        source_id = source_reg.allocate_source_id()
        source = source_reg.register(
            SourceRecord(
                source_id=source_id, source_type="YOUTUBE",
                title="Fictional test video: RSI mean reversion (Generation 2 integration fixture, not a real source)",
                retrieval_timestamp=utcnow().isoformat(),
            )
        )
        ledger.append("SOURCE_INGESTED", subject_id=source.source_id, reason="integration test fixture")

        # 2. CLAIM
        claim_id = claim_reg.allocate_claim_id()
        claim = claim_reg.register(
            ClaimRecord(
                claim_id=claim_id, source_id=source.source_id,
                claim_text="RSI 14 crossing above 30 from below tends to precede short-term upward moves.",
                claim_type="PREDICTIVE_SIGNAL", creation_timestamp=utcnow().isoformat(),
            )
        )
        ledger.append("CLAIM_CREATED", subject_id=claim.claim_id, reason="extracted from fixture source",
                       source_id=source.source_id)
        claim_reg.transition_status(claim.claim_id, "EXTRACTED", reason="extracted")

        # 3. HYPOTHESIS
        hyp = hyp_reg.register(
            source_type="YOUTUBE", source_reference=source.source_id, original_claim=claim.claim_text,
        )
        hyp.source_claim_id = claim.claim_id
        ledger.append("HYPOTHESIS_CREATED", subject_id=hyp.hypothesis_id, reason="from claim",
                       source_id=source.source_id)

        # 4. FORMALIZATION
        spec = FormalizationSpec(
            inputs=("rsi_14",), condition="rsi_14 < 30", signal="rsi_14 crosses above 30",
            target="future_return over 12 bars", horizon_bars=12, direction="positive", regime="any",
            instrument_scope="EURUSD", cost_assumptions="realistic spread + slippage",
            falsification_rule="conditional expectancy <= 0 after realistic costs OR effect disappears out-of-sample",
        )
        hyp = formalize_hypothesis(hyp_reg, hyp.hypothesis_id, spec, reason="integration test formalization")
        assert_hypothesis_eligible_for_candidate_generation(hyp)
        ledger.append("HYPOTHESIS_FORMALIZED", subject_id=hyp.hypothesis_id, reason="quality gates passed",
                       feature_ids=hyp.feature_dependencies)

        # 5. SEARCH SPACE
        search_space_id = ss_reg.allocate_search_space_id()
        search_space = ss_reg.register(
            SearchSpace(
                search_space_id=search_space_id, symbols=("EURUSD",), timeframes=("H1",), features=("rsi_14",),
                feature_parameters={"rsi_threshold": [25, 30, 35]},
                entry_conditions=("rsi_cross_30",), exit_conditions=("stop_or_target_or_maxhold",),
                stop_loss_options=("1.5xATR", "2xATR"), take_profit_options=("2xATR", "3xATR"),
                holding_periods=(8, 12, 24), regimes=("any",), position_sizing_options=("fixed_fractional",),
                cost_model="realistic median spread + 0.2 pip slippage",
                creation_timestamp=utcnow().isoformat(), generation_method="SEEDED_GRID", generation_seed=42,
            )
        )
        ledger.append("SEARCH_SPACE_CREATED", subject_id=search_space.search_space_id,
                       reason=f"{search_space.combination_count()} combinations declared")

        # 6. CANDIDATE
        candidate_id = generate_and_register_candidate(
            strat_reg, hyp, search_space,
            param_draw={"entry_condition": "rsi_cross_30", "exit_condition": "stop_or_target_or_maxhold",
                        "stop_loss": "1.5xATR", "take_profit": "2xATR", "holding_period": 12,
                        "position_sizing": "fixed_fractional"},
            symbol="EURUSD", timeframe="H1", code_version="gen2-integration-test",
            dataset_id="NONE-TEST-FIXTURE",
        )
        candidate = strat_reg.get(candidate_id)
        ledger.append(
            "CANDIDATE_GENERATED", subject_id=candidate.candidate_id, reason="generated from formalized hypothesis",
            search_space_id=search_space.search_space_id, feature_ids=hyp.feature_dependencies,
        )

        # 7. RESEARCH LEDGER -- already populated above; verify full trail
        subject_events = {e.subject_id: e for e in ledger.all_events()}
        assert source.source_id in subject_events
        assert claim.claim_id in subject_events
        assert hyp.hypothesis_id in subject_events
        assert search_space.search_space_id in subject_events
        assert candidate.candidate_id in subject_events

        # 8. SEARCH ACCOUNTING
        summary = compute_search_accounting_summary(
            source_registry=source_reg, claim_registry=claim_reg, hypothesis_registry=hyp_reg,
            search_space_registry=ss_reg, strategy_registry=strat_reg,
        )
        assert summary["TOTAL_SOURCES"] == 1
        assert summary["TOTAL_CLAIMS"] == 1
        assert summary["TOTAL_HYPOTHESES"] == 1
        assert summary["TOTAL_FORMALIZED_HYPOTHESES"] == 1
        assert summary["TOTAL_SEARCH_SPACES"] == 1
        assert summary["TOTAL_CANDIDATES_GENERATED"] == 1
        assert summary["SELECTION_BIAS_STATUS"] in ("UNACCOUNTED", "ACCOUNTING_ONLY")
        assert summary["SELECTION_BIAS_STATUS"] != "PASS"

        # 9. REGISTRY -- the candidate is real, registered, and legally REJECTED
        # -- never a fabricated PASS. This is a TEST candidate in an
        # isolated tmp_path registry; it does NOT touch, and cannot become,
        # the real production strategy_registry.json or STRAT-000002.
        strat_reg.transition(candidate.candidate_id, CandidateState.DATA_VALIDATED, reason="test fixture, no real data")
        strat_reg.reject(candidate.candidate_id, reason="Generation 2 integration proof only -- not a real economic test",
                          failed_phase="INTEGRATION_TEST")
        ledger.append("CANDIDATE_REJECTED", subject_id=candidate.candidate_id,
                       reason="integration test fixture, not a real economic result")

        # ==== LINEAGE RECONSTRUCTION: candidate -> hypothesis -> claim -> source ====
        final_candidate = strat_reg.get(candidate_id)
        assert final_candidate.hypothesis_id == hyp.hypothesis_id
        assert final_candidate.search_space_id == search_space.search_space_id

        reconstructed_hypothesis = hyp_reg.get(final_candidate.hypothesis_id)
        assert reconstructed_hypothesis.source_claim_id == claim.claim_id
        assert reconstructed_hypothesis.source_reference == source.source_id

        reconstructed_claim = claim_reg.get(reconstructed_hypothesis.source_claim_id)
        assert reconstructed_claim.source_id == source.source_id

        reconstructed_source = source_reg.get(reconstructed_claim.source_id)
        assert reconstructed_source.source_id == source_id

        # every identity/checksum along the chain is independently verifiable
        assert final_candidate.candidate_checksum  # non-empty, was computed at generation time
        assert reconstructed_hypothesis.checksum()  # recomputable
        assert search_space.checksum()  # recomputable
        assert reconstructed_source.identity_checksum()  # recomputable
        assert reconstructed_claim.identity_checksum()  # recomputable

