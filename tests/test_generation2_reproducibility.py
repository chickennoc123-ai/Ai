"""Generation 2, Phase 17 — reproducibility.

The same source + claim + hypothesis + search space must produce
deterministic identities. Where generation uses randomness, the seed
must be explicit, recorded, and the resulting artifact identity
reproducible -- and must never touch uncontrolled/global randomness.
"""

from __future__ import annotations

import random

from utils.helpers import utcnow

from core.factory.candidate_generation_engine import (
    compute_candidate_checksum,
    generate_candidate_spec_from_draw,
    sample_param_draws,
)
from core.factory.claim_registry import ClaimRecord
from core.factory.hypothesis import HypothesisRecord
from core.factory.hypothesis_formalization import FormalizationSpec, formalize_hypothesis
from core.factory.hypothesis import HypothesisRegistry
from core.factory.research_source_registry import SourceRecord
from core.factory.search_space import SearchSpace


def _search_space(**overrides):
    base = dict(
        search_space_id="SEARCHSPACE-REPRO", symbols=("EURUSD", "GBPUSD"), timeframes=("H1",),
        features=("rsi_14",), feature_parameters={"rsi_period": [10, 14, 20]},
        entry_conditions=("e1", "e2"), exit_conditions=("x1", "x2"),
        stop_loss_options=("1.5xATR", "2xATR"), take_profit_options=("2xATR", "3xATR"),
        holding_periods=(4, 8, 12), regimes=("any",), position_sizing_options=("fixed",),
        cost_model="realistic", creation_timestamp=utcnow().isoformat(),
    )
    base.update(overrides)
    return SearchSpace(**base)


class TestSourceClaimIdentityReproducibility:
    def test_source_identity_checksum_is_reproducible(self) -> None:
        s1 = SourceRecord(source_id="A", source_type="BOOK", title="T", retrieval_timestamp=utcnow().isoformat())
        s2 = SourceRecord(source_id="B", source_type="BOOK", title="T", retrieval_timestamp=utcnow().isoformat())
        # different ids/timestamps, same defining content -> same identity checksum
        assert s1.identity_checksum() == s2.identity_checksum()

    def test_claim_identity_checksum_is_reproducible(self) -> None:
        c1 = ClaimRecord(claim_id="A", source_id="S", claim_text="T", claim_type="PREDICTIVE_SIGNAL",
                          creation_timestamp=utcnow().isoformat())
        c2 = ClaimRecord(claim_id="B", source_id="S", claim_text="T", claim_type="PREDICTIVE_SIGNAL",
                          creation_timestamp=utcnow().isoformat())
        assert c1.identity_checksum() == c2.identity_checksum()


class TestHypothesisChecksumReproducibility:
    def test_identical_formalization_content_produces_identical_checksum(self, tmp_path) -> None:
        reg1 = HypothesisRegistry(path=tmp_path / "hyp1.json")
        reg2 = HypothesisRegistry(path=tmp_path / "hyp2.json")
        h1 = reg1.register(source_type="BOOK", source_reference="R", original_claim="C")
        h2 = reg2.register(source_type="BOOK", source_reference="R", original_claim="C")
        spec = FormalizationSpec(
            inputs=("rsi_14",), condition="cond", signal="sig", target="target", horizon_bars=12,
            direction="positive", regime="any", instrument_scope="EURUSD", cost_assumptions="realistic",
            falsification_rule="rule",
        )
        h1 = formalize_hypothesis(reg1, h1.hypothesis_id, spec, reason="x")
        h2 = formalize_hypothesis(reg2, h2.hypothesis_id, spec, reason="x")
        assert h1.checksum() == h2.checksum()

    def test_checksum_recomputed_in_a_fresh_process_matches(self, tmp_path) -> None:
        """Genuine cross-process check (not just same-process idempotency)."""
        import subprocess
        import sys

        reg = HypothesisRegistry(path=tmp_path / "hyp.json")
        h = reg.register(source_type="BOOK", source_reference="R", original_claim="C")
        spec = FormalizationSpec(
            inputs=("rsi_14",), condition="cond", signal="sig", target="target", horizon_bars=12,
            direction="positive", regime="any", instrument_scope="EURUSD", cost_assumptions="realistic",
            falsification_rule="rule",
        )
        h = formalize_hypothesis(reg, h.hypothesis_id, spec, reason="x")
        in_process_checksum = h.checksum()

        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from core.factory.hypothesis import HypothesisRegistry\n"
            "reg = HypothesisRegistry(path=%r)\n"
            "print(reg.get(%r).checksum())\n"
        ) % (str(__import__("pathlib").Path(__file__).resolve().parent.parent), str(tmp_path / "hyp.json"), h.hypothesis_id)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        fresh_process_checksum = result.stdout.strip()
        assert fresh_process_checksum == in_process_checksum


class TestSearchSpaceChecksumReproducibility:
    def test_identical_content_different_id_same_checksum(self) -> None:
        s1 = _search_space(search_space_id="A")
        s2 = _search_space(search_space_id="B")
        assert s1.checksum() == s2.checksum()

    def test_combination_count_is_reproducible(self) -> None:
        s1 = _search_space()
        s2 = _search_space()
        assert s1.combination_count() == s2.combination_count()


class TestSeededParameterDrawReproducibility:
    def test_same_seed_produces_identical_draws(self) -> None:
        space = _search_space()
        draws_a = sample_param_draws(space, seed=42, count=10)
        draws_b = sample_param_draws(space, seed=42, count=10)
        assert draws_a == draws_b

    def test_different_seed_can_produce_different_draws(self) -> None:
        space = _search_space()
        draws_a = sample_param_draws(space, seed=1, count=20)
        draws_b = sample_param_draws(space, seed=2, count=20)
        assert draws_a != draws_b

    def test_sampling_never_touches_global_random_state(self) -> None:
        """Mirrors core.factory.generator's existing, already-tested
        discipline: this module must not call bare random.choice/
        random.seed on the shared global random module."""
        random.seed(12345)
        state_before = random.getstate()
        space = _search_space()
        sample_param_draws(space, seed=99, count=15)
        assert random.getstate() == state_before

    def test_candidate_checksum_is_reproducible_for_a_fixed_draw(self) -> None:
        space = _search_space()
        draws = sample_param_draws(space, seed=7, count=1)
        draw = draws[0]

        h = HypothesisRecord(
            hypothesis_id="HYP-REPRO", source_type="BOOK", source_reference="R", original_claim="C",
            date_captured=utcnow().isoformat(), feature_dependencies=("rsi_14",),
            expected_direction="positive", formalization_status="FORMALIZED",
            evidence_level="FORMALIZED_UNTESTED",
            transformation_history=[{"timestamp": utcnow().isoformat(), "event": "formalized", "detail": "x"}],
        )
        spec_a = generate_candidate_spec_from_draw(h, space, draw, symbol="EURUSD", timeframe="H1")
        spec_b = generate_candidate_spec_from_draw(h, space, draw, symbol="EURUSD", timeframe="H1")
        assert spec_a.spec_checksum() == spec_b.spec_checksum()

        checksum_a = compute_candidate_checksum(spec_a, h.hypothesis_id, space.search_space_id)
        checksum_b = compute_candidate_checksum(spec_b, h.hypothesis_id, space.search_space_id)
        assert checksum_a == checksum_b
