"""Market Universe Expansion Contract — Generation 2, Phase 7.

Ontology and eligibility-checking only — **no dataset is downloaded or
fabricated by this module**. It lets the Factory represent multiple
market universes (FX, METALS, INDICES, COMMODITIES, RATES, VOLATILITY,
CRYPTO) and ask, for any symbol, whether real, eligible data actually
exists for it — never assumed, always checked against
``core.factory.dataset_registry``.
"""

from __future__ import annotations

from typing import Dict, Optional

from core.factory.dataset_registry import DatasetNotFoundError, DatasetRegistry

ASSET_CLASSES = frozenset({"FX", "METALS", "INDICES", "COMMODITIES", "RATES", "VOLATILITY", "CRYPTO"})

#: Pure ontology: symbol -> asset class family. This does NOT assert data
#: exists for any of these -- see `data_eligibility_status` below, which
#: is the only function permitted to make that claim, and only by
#: actually checking the Dataset Registry.
KNOWN_INSTRUMENT_UNIVERSE: Dict[str, str] = {
    "EURUSD": "FX", "GBPUSD": "FX", "USDJPY": "FX", "AUDUSD": "FX",
    "NZDUSD": "FX", "USDCAD": "FX", "USDCHF": "FX",
    "XAUUSD": "METALS", "XAGUSD": "METALS", "COPPER": "METALS",
    "SPX": "INDICES", "NDX": "INDICES", "DAX": "INDICES", "NIKKEI": "INDICES",
    "WTI": "COMMODITIES", "BRENT": "COMMODITIES", "NATURAL_GAS": "COMMODITIES",
    "VIX": "VOLATILITY",
    "BTC": "CRYPTO", "ETH": "CRYPTO",
}

#: RATES has no example instrument in the task's own list -- left as a
#: represented, architecturally-supported asset class with zero known
#: instruments, rather than inventing one.

DATA_ELIGIBILITY_STATUSES = frozenset({"REAL_DATA_VERIFIED", "NO_DATA_REGISTERED", "DATA_REGISTERED_NOT_ELIGIBLE"})


def asset_class_of(symbol: str) -> Optional[str]:
    """Returns the ontology's known asset class for ``symbol``, or
    ``None`` if this symbol is not (yet) part of the represented
    universe -- ``None`` is a valid, honest answer, not an error."""
    return KNOWN_INSTRUMENT_UNIVERSE.get(symbol)


def data_eligibility_status(symbol: str, dataset_registry: DatasetRegistry) -> str:
    """The ONLY function in this module permitted to say a symbol has
    real, verified data -- and only after actually checking the Dataset
    Registry, never from ontology membership alone. Membership in
    ``KNOWN_INSTRUMENT_UNIVERSE`` means "this project knows this
    instrument exists as a concept"; it says nothing about whether any
    data for it has been acquired."""
    matching = dataset_registry.list_by_instrument(symbol)
    if not matching:
        return "NO_DATA_REGISTERED"
    if any(d.is_real_market_data_eligible for d in matching):
        return "REAL_DATA_VERIFIED"
    return "DATA_REGISTERED_NOT_ELIGIBLE"
