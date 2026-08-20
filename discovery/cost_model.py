"""
Pre-registered per-symbol transaction cost model (FROZEN).

Cycle 1 and Cycle 2 ran on EURUSD alone, where the frozen assumption was
1.1 pips per round trip in PRICE terms (0.00011). Every executor in this
package measures gross performance as a LOG RETURN, so once the factory
trades instruments quoted on different scales (USDJPY ~150, XAUUSD ~3000)
an absolute price cost is meaningless and must be expressed in RELATIVE
terms instead.

This module fixes that translation once, before any Cycle 3 evaluation is
run, and freezes it. Values are deliberately conservative (retail-realistic
spread + slippage, not institutional best-case). Raising a cost is always
permitted; LOWERING any value in this table after a candidate has been
evaluated against it is a governance violation -- it would be loosening a
pre-registered gate to manufacture an edge.

EURUSD is pinned so Cycle 3 stays comparable with Cycles 1-2:
    1.1 pips / 1.10 quote  ==  1.0e-4 relative  ==  the frozen assumption.
"""

from typing import Dict

# relative (log-return equivalent) round-trip cost per symbol
ROUNDTRIP_COST_RELATIVE: Dict[str, float] = {
    "EURUSD": 1.00e-4,   # 1.1 pips @ ~1.10   (pinned to Cycles 1-2)
    "GBPUSD": 1.20e-4,   # 1.5 pips @ ~1.30
    "USDCAD": 1.40e-4,   # 1.9 pips @ ~1.35
    "USDCHF": 1.90e-4,   # 1.7 pips @ ~0.90
    "USDJPY": 1.00e-4,   # 1.4 pips @ ~145
    "XAUUSD": 2.00e-4,   # ~$0.55 @ ~$2750 (gold spread widens intraday)
}

# Frozen provenance string written into every evaluation artifact.
COST_MODEL_ID = "COST-REL-V1-FROZEN-20260820"


def roundtrip_cost(symbol: str) -> float:
    """Relative round-trip cost for one symbol. Unknown symbol is an error."""
    try:
        return ROUNDTRIP_COST_RELATIVE[symbol]
    except KeyError:
        raise KeyError(
            f"no pre-registered cost for {symbol!r}; a cost must be registered "
            f"and frozen BEFORE that symbol is evaluated, never after"
        )


def cost_table() -> Dict[str, float]:
    """Copy of the frozen table, for embedding in reports."""
    return dict(ROUNDTRIP_COST_RELATIVE)
