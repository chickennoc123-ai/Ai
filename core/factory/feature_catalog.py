"""Feature Catalog — Generation 2, Phase 8.

Distinct from ``core.factory.feature_registry`` (which wraps *actually
implemented* features with a real formula, currently the five FE-R2-001/
FE-R2-003 features): this module catalogs feature *concepts* — named
indicators the Factory knows about, organized by family — without
implementing them. Per the task's explicit instruction ("do not blindly
implement hundreds of indicators"), cataloging a name is not the same as
having a working, provenance-backed implementation; ``implementation_
status()`` is the honest boundary between the two.
"""

from __future__ import annotations

from typing import Dict

from core.features.fe_r2_001 import FEATURE_ORDER

FEATURE_FAMILIES = frozenset(
    {
        "PRICE", "MOMENTUM", "TREND", "VOLATILITY", "MEAN_REVERSION", "VOLUME",
        "RANGE", "REGIME", "CROSS_ASSET", "MACRO", "POSITIONING", "EVENT", "MICROSTRUCTURE",
    }
)

#: name -> family. Cataloged, not implemented (see implementation_status).
#: The five names actually implemented in fe_r2_001.py use their real
#: identifiers; every other entry is a concept only.
KNOWN_FEATURE_CATALOG: Dict[str, str] = {
    "momentum_5": "MOMENTUM",
    "momentum_20": "MOMENTUM",
    "rsi_14": "MOMENTUM",
    "atr_14": "VOLATILITY",
    "volatility_regime": "REGIME",
    "RSI": "MOMENTUM",
    "MACD": "MOMENTUM",
    "ATR": "VOLATILITY",
    "ADX": "TREND",
    "EMA": "TREND",
    "SMA": "TREND",
    "BOLLINGER_BANDS": "VOLATILITY",
    "REALIZED_VOLATILITY": "VOLATILITY",
    "RANGE": "RANGE",
    "DRAWDOWN": "REGIME",
    "TREND_STRENGTH": "TREND",
    "ROLLING_CORRELATIONS": "CROSS_ASSET",
    "MEAN_REVERSION_ZSCORE": "MEAN_REVERSION",
    "VOLUME_PROFILE": "VOLUME",
    "MACRO_SURPRISE_INDEX": "MACRO",
    "COT_POSITIONING": "POSITIONING",
    "EVENT_PROXIMITY": "EVENT",
    "BID_ASK_IMBALANCE": "MICROSTRUCTURE",
}

_IMPLEMENTED_NAMES = frozenset(FEATURE_ORDER)


def implementation_status(name: str) -> str:
    """``IMPLEMENTED`` only for the real, working FE-R2-001/003 features
    (checked against ``fe_r2_001.FEATURE_ORDER`` directly, not a hard-coded
    duplicate list, so this can never silently drift from the actual
    pipeline). ``CATALOGED_NOT_IMPLEMENTED`` for a recognized concept with
    no working formula. ``UNKNOWN`` for a name not in the catalog at all."""
    if name in _IMPLEMENTED_NAMES:
        return "IMPLEMENTED"
    if name in KNOWN_FEATURE_CATALOG:
        return "CATALOGED_NOT_IMPLEMENTED"
    return "UNKNOWN"


def family_of(name: str) -> str:
    return KNOWN_FEATURE_CATALOG.get(name, "UNKNOWN")
