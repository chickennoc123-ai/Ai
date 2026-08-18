"""Deterministic candidate generation for the Strategy Factory.

Per roadmap Section 7: no ``random.choice``/``random.uniform`` bare calls
in the economic path. Any stochastic search must be seeded, with the seed
and search space recorded, so the Factory can always answer "why was this
strategy tested" and "how many alternatives were tested before this one
was selected."

This generator produces ``StrategyCandidateSpec`` variants of the single
real strategy hypothesis currently in this repository (ML-001-R2, per
``ML-001-R2-CLEAN-REBUILD-SPEC.md``) by sampling from an explicit,
declared parameter grid — it does not invent new entry/exit logic (there
is no second strategy hypothesis in this project to draw from), only
parameter variants of the one that exists. A future generator that
searches over entry/exit logic itself would be a separate, new
``generator_id``, not a silent extension of this one.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from core.factory.candidate import StrategyCandidateSpec

GENERATOR_ID = "GEN-R2-PARAM-GRID-001"

#: The declared, explicit search space this generator draws from. Recorded
#: verbatim into every generated candidate's ``generator_parameters`` and
#: into the registry's ``search_history.search_space`` — nothing here is
#: hidden from the multiple-testing accounting.
SEARCH_SPACE: Dict[str, List[Any]] = {
    "stop_loss_atr_multiple": [1.0, 1.5, 2.0, 2.5, 3.0],
    "take_profit_atr_multiple": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    "max_hold_bars": [12, 24, 48, 96],
}

_BASE_ENTRY_RULE = (
    "RF-R2-001.predict_proba(FE-R2-003 feature vector) crosses the "
    "spec Section 9 decision threshold — see ML-001-R2-CLEAN-REBUILD-SPEC.md"
)
_BASE_EXIT_RULE = "First of: stop-loss, take-profit, or max_hold_bars elapsed (spec Section 9)"


def generate_candidate_spec(rng: random.Random) -> Dict[str, Any]:
    """Draw one parameter combination from ``SEARCH_SPACE`` using ``rng``.

    Callers MUST construct ``rng`` themselves with an explicit, recorded
    seed (``random.Random(seed)``) — this function never touches the
    global ``random`` module, so two callers with the same seed always
    produce the same sequence of draws regardless of what else in the
    process has called ``random`` in the meantime.
    """
    return {
        "stop_loss_atr_multiple": rng.choice(SEARCH_SPACE["stop_loss_atr_multiple"]),
        "take_profit_atr_multiple": rng.choice(SEARCH_SPACE["take_profit_atr_multiple"]),
        "max_hold_bars": rng.choice(SEARCH_SPACE["max_hold_bars"]),
    }


def build_spec(params: Dict[str, Any]) -> StrategyCandidateSpec:
    """Turn a drawn parameter dict into a complete, immutable candidate spec."""
    return StrategyCandidateSpec(
        entry_rule=_BASE_ENTRY_RULE,
        exit_rule=_BASE_EXIT_RULE,
        features=("momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"),
        timeframe="H1",
        direction="long_and_short",
        stop_loss=f"{params['stop_loss_atr_multiple']}x ATR_14",
        take_profit=f"{params['take_profit_atr_multiple']}x ATR_14",
        max_hold_bars=int(params["max_hold_bars"]),
        position_sizing="fixed_fractional (spec Section 11, RiskGovernanceConfig)",
        transaction_cost_model="realistic median spread + 0.2 pip slippage buffer (spec Section 7)",
    )


def generate_candidates(seed: int, count: int) -> List[Dict[str, Any]]:
    """Generate ``count`` (spec, params) pairs deterministically from ``seed``.

    Duplicate parameter draws are possible (the grid is finite and small)
    and are NOT filtered out silently — a caller registering these with
    the Strategy Factory will naturally see duplicate spec_checksum()
    values if the RNG repeats a combination, which is itself useful
    evidence for the search-history record, not a bug to hide.
    """
    rng = random.Random(seed)
    results = []
    for _ in range(count):
        params = generate_candidate_spec(rng)
        spec = build_spec(params)
        results.append({"spec": spec, "generator_parameters": params, "seed": seed, "generator_id": GENERATOR_ID})
    return results
