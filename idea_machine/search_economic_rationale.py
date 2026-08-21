"""Established economic direction (base_dir) for every real symbol/driver pairing
this project has actually reasoned through, across Cycles 8, 13, and 14.

This table is the honesty boundary for the live autonomous search cycle: a
proposal whose (instrument, driver) pair is NOT in this table is skipped
with an explicit note rather than evaluated with an invented or default
direction. Economic reasoning is not free to manufacture on demand -- every
entry here was stated, with its channel, in the cycle that first used it.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

#: (instrument, driver) -> (base_dir, rationale, established_in)
BASE_DIR_TABLE: Dict[Tuple[str, str], Tuple[int, str, str]] = {
    ("EURUSD", "US10Y"): (+1, "US10Y price up (yield down) -> USD carry less attractive -> long EURUSD", "Cycle 8"),
    ("EURUSD", "DE10YB"): (+1, "German 10y Bund yield up -> Eurozone carry more attractive on its own curve -> EURUSD rises", "Cycle 13"),
    ("GBPUSD", "US10Y"): (+1, "US10Y price up (yield down) -> USD carry less attractive -> long GBPUSD", "Cycle 8"),
    ("GBPUSD", "UK10YB"): (+1, "UK 10y yield up -> GBP carry more attractive on its own curve -> GBPUSD rises", "Cycle 13"),
    ("GBPUSD", "US2000"): (-1, "Russell 2000 up -> pure US domestic growth signal -> USD strengthens broadly -> GBPUSD falls", "Cycle 14 (second pass)"),
    ("XAUUSD", "SPX500"): (-1, "SPX up -> risk-on -> gold sold -> short XAUUSD on SPX up", "Cycle 8"),
    ("XAUUSD", "WTICO"): (+1, "Oil up -> inflation co-movement -> long XAUUSD", "Cycle 8"),
    ("XAUUSD", "USB02Y"): (-1, "US 2y yield up -> short-term real yields rise -> opportunity cost of holding non-yielding gold rises -> XAUUSD falls", "Cycle 13"),
    ("USDJPY", "SPX500"): (+1, "SPX up -> risk-on, JPY funding-currency sold -> long USDJPY", "Cycle 8"),
    ("USDJPY", "USB02Y"): (+1, "US 2y yield up -> USD carry more attractive vs near-zero JPY -> USDJPY rises", "Cycle 13"),
    ("USDJPY", "JP225"): (+1, "Nikkei up -> foreign equity inflows funded by JPY selling -> USDJPY up", "Cycle 14 (first pass)"),
    ("USDJPY", "UK100"): (+1, "FTSE up -> global risk-on -> JPY funding-currency sold -> USDJPY up", "Cycle 14 (first pass)"),
    ("USDJPY", "AU200"): (+1, "ASX up -> global risk-on -> JPY funding-currency sold -> USDJPY up", "Cycle 14 (first pass)"),
    ("USDJPY", "US2000"): (+1, "Russell 2000 up -> US domestic growth strength -> USDJPY up", "Cycle 14 (first pass)"),
    ("USDJPY", "NATGAS"): (+1, "Nat gas up -> Japan (net energy importer) terms-of-trade worsen -> JPY weakens -> USDJPY up", "Cycle 14 (first pass)"),
    ("USDCHF", "SPX500"): (+1, "SPX up -> risk-on, CHF safe-haven sold -> long USDCHF", "Cycle 8"),
    ("USDCAD", "WTICO"): (-1, "WTI crude up -> Canada terms-of-trade improve -> CAD strengthens -> USDCAD falls", "Cycle 13"),
    # Cycle 15 (adaptive search, live demonstration): direct extensions of
    # ALREADY-established risk-sentiment channels (XAUUSD/SPX500 and
    # USDCHF/SPX500, both Cycle 8), substituting a different regional equity
    # index as the observable proxy for the same underlying global
    # risk-on/risk-off factor -- not a new, unreasoned mechanism.
    ("USDCHF", "JP225"): (+1, "Nikkei up -> global risk-on (same channel as USDCHF/SPX500, Cycle 8) -> CHF safe-haven sold -> USDCHF up", "Cycle 15"),
    ("XAUUSD", "UK100"): (-1, "FTSE up -> global risk-on (same channel as XAUUSD/SPX500, Cycle 8) -> gold sold -> XAUUSD falls", "Cycle 15"),
    ("GBPUSD", "UK100"): (+1, "FTSE up -> global risk-on backdrop supports higher-beta GBP relative to safe-haven flows -> GBPUSD rises", "Cycle 15"),
}


def lookup(instrument: str, driver: Optional[str]) -> Optional[Tuple[int, str, str]]:
    if not driver:
        return None
    return BASE_DIR_TABLE.get((instrument, driver))
