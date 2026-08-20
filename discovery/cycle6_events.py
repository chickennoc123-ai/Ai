"""
GEN 7 CYCLE 6 -- event-driven discovery on the real acquired calendar.

Cycle 5 ran C1/C3/C4 on a DERIVED NFP-only schedule (no real calendar was
available) and found 0 survivors -- FAIL-000034: calendar timing alone
carries no directional information. C2 (surprise reaction) could not run at
all.

Cycle 6 material acquisition (this session, prior turn) delivered a real,
dual-signal-verified ForexFactory calendar for 2010-2023, with actual and
forecast populated for the majority of numeric releases. This module re-runs
C1/C3/C4 on the REAL calendar (not the NFP approximation) and runs C2 for the
first time.

Firewall note: the 2024-2026 extension acquired in the same prior turn is
NEVER read here. Every symbol's development window ends before 2024, so
load_events(dev_end=...) excludes it structurally -- this was verified
directly (byte-identical events_dev.csv) when the extension was merged, and
is re-asserted by a test in this module's test file.

Pre-registered event-type -> symbol mapping (fixed before any evaluation ran)
-------------------------------------------------------------------------------
Each event type is tested only against the symbol(s) where a direct economic
mechanism exists -- a rate decision trades its own currency pair, US releases
trade every pair with USD exposure (including gold). No event type is tested
against an unrelated pair (e.g. BOJ Policy Statement against EURUSD) --
mixing in economically ungrounded combinations was the exact temptation this
project's "mechanism interpretable" gate exists to block.

    USD (NFP, CPI y/y, Federal Funds Rate, FOMC Statement)
        -> EURUSD, GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD
    GBP (Official Bank Rate)      -> GBPUSD only
    EUR (Main Refinancing Rate)   -> EURUSD only
    JPY (Monetary Policy Statement) -> USDJPY only

C2 (surprise reaction) is only attempted where actual+forecast coverage is
real: FOMC Statement and JPY Monetary Policy Statement carry no numeric
actual/forecast (they are prose statements, not data prints) and are
structurally excluded from C2, not silently zero-filled.

Every (event_type, symbol, family) combination is power-pre-checked -- n>=30
in BOTH train and validation windows -- BEFORE any evaluation runs. Counting
costs nothing; evaluating a structurally underpowered combination costs a
parameter evaluation and raises the Bonferroni bar for every future
candidate, for a result that was knowable in advance.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars, OBSERVATION_FRACTION
from discovery.cost_model import roundtrip_cost, cost_table, COST_MODEL_ID
from discovery.event_calendar import MacroEvent, load_events
from discovery.cycle5_events import (
    c1_pre_event, c2_surprise, c3_volatility, c4_sequence, stats, gate,
    MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST,
    PRE_WINDOWS_H, POST_WINDOWS_H,
)

CALENDAR_2010_2023 = R / "data/events/raw/forexfactory_2010_2023.csv"

# Pre-registered mapping: (event_name, currency) -> [symbols], allow_c2
EVENT_MAP: List[Tuple[str, str, List[str], bool]] = [
    ("Non-Farm Employment Change", "USD",
     ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"], True),
    ("CPI y/y", "USD",
     ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"], True),
    ("Federal Funds Rate", "USD",
     ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"], True),
    ("FOMC Statement", "USD",
     ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"], False),
    ("Official Bank Rate", "GBP", ["GBPUSD"], True),
    ("Main Refinancing Rate", "EUR", ["EURUSD"], True),
    ("Monetary Policy Statement", "JPY", ["USDJPY"], False),
]


_BARS_CACHE: Dict[str, list] = {}
_EVENTS_CACHE: Dict[str, List[MacroEvent]] = {}


def _bars_for(symbol: str) -> list:
    if symbol not in _BARS_CACHE:
        _BARS_CACHE[symbol] = load_dev_bars(R / "data/csv" / f"{symbol}_H1.csv")
    return _BARS_CACHE[symbol]


def _events_for(symbol: str) -> List[MacroEvent]:
    """Events filtered to this symbol's own dev_end -- cached per symbol since
    the same (symbol, dev_end) pair is reused across every event type."""
    if symbol not in _EVENTS_CACHE:
        dev_end = _bars_for(symbol)[-1].ts
        _EVENTS_CACHE[symbol] = load_events(CALENDAR_2010_2023, dev_end=dev_end)
    return _EVENTS_CACHE[symbol]


def _symbol_dev_events(symbol: str, all_events: List[MacroEvent]) -> Tuple[List[MacroEvent], List[MacroEvent], object]:
    """Split an already dev_end-filtered event list into train/validation by
    this symbol's own 80% observation cut."""
    bars = _bars_for(symbol)
    cut_ts = bars[int(len(bars) * OBSERVATION_FRACTION)].ts
    tr = [e for e in all_events if e.ts < cut_ts]
    va = [e for e in all_events if e.ts >= cut_ts]
    return tr, va, bars


def power_precheck(symbol: str, event_name: str, currency: str) -> Dict:
    """Zero-cost check: does this (event, symbol) combo have any chance of
    clearing n>=30 in both windows? Declared before evaluation, not after."""
    all_events = _events_for(symbol)
    matching = [e for e in all_events if e.name == event_name and e.currency == currency]
    tr, va, _ = _symbol_dev_events(symbol, matching)
    ok = len(tr) >= MIN_TRADES and len(va) >= MIN_TRADES
    return {"symbol": symbol, "event_name": event_name, "currency": currency,
            "train_events": len(tr), "validation_events": len(va),
            "feasible": ok}


def evaluate_combo(symbol: str, event_name: str, currency: str, allow_c2: bool) -> List[Dict]:
    bars = _bars_for(symbol)
    all_events = _events_for(symbol)
    matching = [e for e in all_events if e.name == event_name and e.currency == currency]
    tr_ev, va_ev, _ = _symbol_dev_events(symbol, matching)
    cut = int(len(bars) * OBSERVATION_FRACTION)
    tr_bars, va_bars = bars[:cut], bars[cut:]
    cost = roundtrip_cost(symbol)

    results = []

    def emit(family, params, fn):
        tr = stats(fn(tr_bars, tr_ev), cost)
        va = stats(fn(va_bars, va_ev), cost)
        v, reason = gate(tr, va)
        results.append({"family": family, "event_name": event_name, "currency": currency,
                        "symbol": symbol, "params": params,
                        "train": tr.to_dict(), "validation": va.to_dict(),
                        "verdict": v, "verdict_reason": reason})

    for pre in PRE_WINDOWS_H:
        for d in (1, -1):
            emit("C1_PRE_EVENT_POSITIONING", {"pre_hours": pre, "dir": d},
                 lambda b, e, pre=pre, d=d: c1_pre_event(b, e, pre, d, cost))
    for post in POST_WINDOWS_H:
        for mode in ("CONTINUATION", "REVERSION"):
            emit("C3_VOLATILITY_EXPANSION", {"post_hours": post, "mode": mode},
                 lambda b, e, post=post, mode=mode: c3_volatility(b, e, post, mode, cost))
    for post in POST_WINDOWS_H:
        for mode in ("STREAK", "ALTERNATION"):
            emit("C4_EVENT_SEQUENCE", {"post_hours": post, "mode": mode},
                 lambda b, e, post=post, mode=mode: c4_sequence(b, e, post, mode, cost))
    if allow_c2:
        for post in POST_WINDOWS_H:
            for mode in ("FOLLOW", "FADE"):
                emit("C2_SURPRISE_REACTION", {"post_hours": post, "mode": mode},
                     lambda b, e, post=post, mode=mode: c2_surprise(b, e, post, mode, cost))
    return results


def main() -> int:
    precheck_rows, feasible_combos = [], []
    for event_name, currency, symbols, allow_c2 in EVENT_MAP:
        for symbol in symbols:
            p = power_precheck(symbol, event_name, currency)
            precheck_rows.append(p)
            if p["feasible"]:
                feasible_combos.append((symbol, event_name, currency, allow_c2))

    print(f"Power pre-check: {len(feasible_combos)}/{len(precheck_rows)} "
          f"(event, symbol) combos clear n>=30 in both windows (0-cost check)")
    skipped = [p for p in precheck_rows if not p["feasible"]]
    for p in skipped:
        print(f"  SKIPPED {p['currency']} {p['event_name']} / {p['symbol']}: "
              f"train={p['train_events']} val={p['validation_events']}")

    all_results: List[Dict] = []
    for symbol, event_name, currency, allow_c2 in feasible_combos:
        all_results.extend(evaluate_combo(symbol, event_name, currency, allow_c2))

    survivors = [r for r in all_results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    by_family: Dict[str, Dict[str, int]] = {}
    for r in all_results:
        by_family.setdefault(r["family"], {})
        by_family[r["family"]][r["verdict"]] = by_family[r["family"]].get(r["verdict"], 0) + 1

    payload = {
        "cycle_id": "CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR",
        "calendar_source": str(CALENDAR_2010_2023),
        "note": ("2024-2026 extension deliberately NOT used here -- every symbol's dev "
                 "window ends before 2024, so it is structurally excluded by "
                 "load_events(dev_end=...), not manually filtered out."),
        "pre_registered_event_map": [
            {"event_name": n, "currency": c, "symbols": s, "c2_allowed": a2}
            for n, c, s, a2 in EVENT_MAP
        ],
        "power_precheck": precheck_rows,
        "combos_evaluated": len(feasible_combos),
        "combos_skipped_underpowered": len(skipped),
        "cost_model_id": COST_MODEL_ID, "cost_table": cost_table(),
        "economic_filter": {"min_trades": MIN_TRADES, "train_min_t": TRAIN_MIN_T,
                            "val_min_t": VAL_MIN_T, "min_gross_over_cost": MIN_GROSS_OVER_COST},
        "parameter_evaluations": len(all_results),
        "survivor_count": len(survivors), "survivors": survivors,
        "family_breakdown": by_family,
        "results": all_results,
    }
    out = R / "reports/factory/discovery_cycles/cycle_06_event_sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nCYCLE 6: {len(all_results)} parameter evaluations, {len(survivors)} DISCOVERY_SURVIVOR")
    for fam in sorted(by_family):
        row = by_family[fam]
        print(f"  {fam:28s} " + "  ".join(f"{k}={v}" for k, v in sorted(row.items())))
    for s in survivors:
        print(f"  SURVIVOR {s['family']} {s['currency']} {s['event_name']} / {s['symbol']} "
              f"{s['params']} train t={s['train']['t_stat']} val t={s['validation']['t_stat']} "
              f"g/c={s['train']['gross_over_cost']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
