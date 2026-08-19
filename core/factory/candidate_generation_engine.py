"""Candidate Generation Engine — Generation 2, Phase 10.

Generates a ``StrategyCandidateSpec``/registers a ``StrategyCandidate``
from a FORMALIZED hypothesis and an explicit, already-registered
``SearchSpace`` — never from a vague or un-formalized hypothesis (Phase
14's quality gates are checked here, not bypassed), and never from an
implicit, unrecorded search.

Distinct from ``core.factory.generator`` (the Generation-1/ML-001-R2-
specific parameter-grid generator for the ONE pre-specified hypothesis) —
this module is deliberately more general: it consumes any FORMALIZED
``HypothesisRecord`` plus any registered ``SearchSpace``, and produces a
full lineage chain (hypothesis -> search space -> candidate) recorded on
the ``StrategyCandidate`` itself.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.factory.candidate import StrategyCandidateSpec
from core.factory.hypothesis import HypothesisRecord
from core.factory.hypothesis_quality_gates import assert_hypothesis_eligible_for_candidate_generation
from core.factory.registry import StrategyRegistry
from core.factory.search_space import SearchSpace
from utils.exceptions import EAFactoryError


class CandidateGenerationError(EAFactoryError):
    """Raised when candidate generation is attempted from an ineligible
    hypothesis/search-space combination, or with an incomplete parameter
    draw."""


def compute_candidate_checksum(spec: StrategyCandidateSpec, hypothesis_id: str, search_space_id: str) -> str:
    """Generation-time identity: spec content + exactly which hypothesis
    and search space produced it. Distinct from ``spec.spec_checksum()``
    (spec content alone) -- this additionally proves lineage, so two
    candidates with byte-identical trading rules but drawn from different
    hypotheses/search spaces are still distinguishable."""
    data = {"spec_checksum": spec.spec_checksum(), "hypothesis_id": hypothesis_id, "search_space_id": search_space_id}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def generate_candidate_spec_from_draw(
    hypothesis: HypothesisRecord,
    search_space: SearchSpace,
    param_draw: Dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
) -> StrategyCandidateSpec:
    """Build one concrete ``StrategyCandidateSpec`` from a hypothesis and
    one specific parameter combination drawn from ``search_space``.
    ``param_draw`` must supply exactly the keys the caller intends to use
    from ``search_space.entry_conditions``/``exit_conditions``/
    ``stop_loss_options``/``take_profit_options``/``holding_periods``/
    ``position_sizing_options`` (validated: every drawn value must
    actually be a member of the corresponding search-space list, so a
    candidate can never silently claim to have been drawn from a space it
    wasn't)."""
    required_keys = (
        "entry_condition", "exit_condition", "stop_loss", "take_profit", "holding_period", "position_sizing",
    )
    missing = [k for k in required_keys if k not in param_draw]
    if missing:
        raise CandidateGenerationError("param_draw is incomplete", missing_keys=missing)

    checks = (
        ("entry_condition", search_space.entry_conditions),
        ("exit_condition", search_space.exit_conditions),
        ("stop_loss", search_space.stop_loss_options),
        ("take_profit", search_space.take_profit_options),
        ("holding_period", search_space.holding_periods),
        ("position_sizing", search_space.position_sizing_options),
    )
    for key, allowed in checks:
        if param_draw[key] not in allowed:
            raise CandidateGenerationError(
                f"param_draw['{key}'] is not a member of the declared search space",
                key=key, value=param_draw[key], allowed=list(allowed),
            )
    if symbol not in search_space.symbols:
        raise CandidateGenerationError("symbol is not a member of the declared search space", symbol=symbol)
    if timeframe not in search_space.timeframes:
        raise CandidateGenerationError("timeframe is not a member of the declared search space", timeframe=timeframe)

    direction_map = {"positive": "long_only", "negative": "short_only"}
    direction = direction_map.get(hypothesis.expected_direction, "long_and_short")

    return StrategyCandidateSpec(
        entry_rule=f"{hypothesis.economic_mechanism} :: {param_draw['entry_condition']}",
        exit_rule=str(param_draw["exit_condition"]),
        features=tuple(hypothesis.feature_dependencies) or tuple(search_space.features),
        timeframe=timeframe,
        direction=direction,
        stop_loss=str(param_draw["stop_loss"]),
        take_profit=str(param_draw["take_profit"]),
        max_hold_bars=int(param_draw["holding_period"]),
        position_sizing=str(param_draw["position_sizing"]),
        transaction_cost_model=search_space.cost_model,
        research_scope="SINGLE_INSTRUMENT",
    )


def generate_and_register_candidate(
    registry: StrategyRegistry,
    hypothesis: HypothesisRecord,
    search_space: SearchSpace,
    param_draw: Dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    code_version: str,
    dataset_id: str,
) -> str:
    """The one sanctioned way to turn a formalized hypothesis + a
    registered search space into a real, registered ``StrategyCandidate``
    with full lineage. Raises (via ``assert_hypothesis_eligible_for_
    candidate_generation``) if the hypothesis has not actually cleared
    Phase 14's quality gates -- generation from a vague/incomplete
    hypothesis is refused, not silently attempted with placeholder
    values. Returns the new candidate's id."""
    assert_hypothesis_eligible_for_candidate_generation(hypothesis)

    spec = generate_candidate_spec_from_draw(hypothesis, search_space, param_draw, symbol=symbol, timeframe=timeframe)
    checksum = compute_candidate_checksum(spec, hypothesis.hypothesis_id, search_space.search_space_id)

    candidate = registry.register(
        spec,
        generator_id="GEN2-CANDIDATE-GENERATION-ENGINE",
        generator_parameters={"param_draw": param_draw, "symbol": symbol, "timeframe": timeframe},
        code_version=code_version,
        dataset_id=dataset_id,
        hypothesis_id=hypothesis.hypothesis_id,
        search_space_id=search_space.search_space_id,
        candidate_checksum=checksum,
    )
    return candidate.candidate_id


def sample_param_draws(search_space: SearchSpace, *, seed: int, count: int) -> List[Dict[str, Any]]:
    """Generation 2, Phase 17 (reproducibility): draw ``count`` parameter
    combinations from ``search_space`` using an explicitly-seeded RNG.
    Callers MUST supply ``seed`` themselves (no default, no silent
    fallback to an unseeded ``random.choice``) and MUST record it
    alongside whatever candidates get generated from the draws (e.g. in
    ``StrategyCandidateSpec``'s ``generator_parameters``, already the
    established Generation 1 pattern in ``core.factory.generator``).

    This function never touches the global ``random`` module -- two
    callers using the same seed always produce the same sequence of
    draws regardless of what else in the process has called ``random``
    in the meantime (mirrors ``core.factory.generator.generate_candidate_
    spec``'s existing, already-tested discipline)."""
    rng = random.Random(seed)
    draws: List[Dict[str, Any]] = []
    for _ in range(count):
        draws.append(
            {
                "entry_condition": rng.choice(search_space.entry_conditions),
                "exit_condition": rng.choice(search_space.exit_conditions),
                "stop_loss": rng.choice(search_space.stop_loss_options),
                "take_profit": rng.choice(search_space.take_profit_options),
                "holding_period": rng.choice(search_space.holding_periods),
                "position_sizing": rng.choice(search_space.position_sizing_options),
            }
        )
    return draws
