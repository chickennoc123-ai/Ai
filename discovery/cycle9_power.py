"""
GEN 7 CYCLE 9 -- power expansion for SC_SURPRISE_CONFIRMATION only.

See CYCLE9-PREREGISTRATION.md for the frozen design, written before this
module ran. This file changes exactly one thing relative to Cycle 8: the
event pool passed into trade_sc(). Every other piece -- mechanism logic,
symbols, windows, cost model, execution delay, gates -- is imported
unmodified from discovery.cycle8_intraday, not reimplemented, so there is no
possibility of a silent behavioral drift between the two cycles.

DC/DR/RI are not re-run. Only SC is in scope, per the task's explicit
instruction to re-test the pre-existing mechanism, not invent a new search.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars
from discovery.event_calendar import load_events, MacroEvent
from discovery.cycle8_intraday import (
    trade_sc, fx_series, driver_series, stats, gate, PAIRINGS,
    FX_M1_SYMBOLS, WINDOWS_MIN_FULL, WINDOWS_MIN_H1ONLY,
    roundtrip_cost, M1_YEAR_RANGE, ENTRY_DELAY_SEC,
)

FROZEN_EVENT_TYPES = {"Non-Farm Employment Change", "CPI y/y",
                      "ADP Non-Farm Employment Change"}
MIN_TRADES = 30


def frozen_event_pool(dev_end: datetime) -> List[MacroEvent]:
    """386-event pool per CYCLE9-PREREGISTRATION.md section 1. Same holdout
    firewall as every prior cycle: load_events(dev_end=...) drops anything
    at or after dev_end before this function ever sees it."""
    all_ev = load_events(R / "data/events/raw/forexfactory_2010_2023.csv", dev_end=dev_end)
    ev = [e for e in all_ev if e.currency == "USD" and e.impact == "HIGH"
          and e.name in FROZEN_EVENT_TYPES]
    return [e for e in ev if M1_YEAR_RANGE.start <= e.ts.year <= M1_YEAR_RANGE.stop - 1]


def evaluate_sc_pairing(symbol: str, driver_name: str, base_dir: int,
                        events: List[MacroEvent], fx, driver) -> List[Dict]:
    cost = roundtrip_cost(symbol)
    windows = WINDOWS_MIN_FULL if symbol in FX_M1_SYMBOLS else WINDOWS_MIN_H1ONLY
    n_events = len(events)
    cut = int(n_events * 0.80)
    cutoff_ts = events[cut].ts if cut < n_events else events[-1].ts

    results = []
    for w in windows:
        nets = []
        for e in events:
            r = trade_sc(e, fx, driver, symbol, base_dir, w, cost)
            if r is not None:
                nets.append((e.ts, r))
        tr_nets = [r for ts, r in nets if ts < cutoff_ts]
        va_nets = [r for ts, r in nets if ts >= cutoff_ts]
        gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
        tr_s = stats(tr_nets, gm + cost, cost)
        va_s = stats(va_nets, 0.0, cost)
        v, reason = gate(tr_s, va_s)
        results.append({
            "mechanism": "SC_SURPRISE_CONFIRMATION", "symbol": symbol, "driver": driver_name,
            "window_min": w, "entry_delay_sec": ENTRY_DELAY_SEC,
            "events_available": n_events, "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "verdict_reason": reason,
        })
    return results


def main() -> int:
    bars = load_dev_bars(R / "data/csv/EURUSD_H1.csv")
    dev_end = bars[-1].ts
    events = frozen_event_pool(dev_end)
    print(f"frozen event pool: {len(events)} events (NFP+CPI+ADP, 2010-{M1_YEAR_RANGE.stop-1}), "
          f"expected 386 per pre-registration")

    all_results = []
    for symbol, driver_name, base_dir, mechanism_note in PAIRINGS:
        fx = fx_series(symbol)
        driver = driver_series(driver_name)
        all_results.extend(evaluate_sc_pairing(symbol, driver_name, base_dir, events, fx, driver))

    survivors = [r for r in all_results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    still_underpowered = [r for r in all_results if r["verdict"] == "VALIDATION_UNDERPOWERED"]
    train_failed = [r for r in all_results
                    if r["verdict"] in ("TRAIN_UNDERPOWERED", "TRAIN_NEGATIVE",
                                        "TRAIN_INSIGNIFICANT", "COST_DOMINATED")]
    val_failed = [r for r in all_results if r["verdict"] == "VALIDATION_NEGATIVE"
                 or r["verdict"] == "VALIDATION_INSIGNIFICANT"]

    if survivors:
        outcome = "SURVIVORS_FOUND"
    elif still_underpowered:
        outcome = "STILL_UNDERPOWERED"
    else:
        outcome = "REFUTED"

    payload = {
        "cycle_id": "CYCLE-09-SC-POWER-EXPANSION",
        "preregistration": "CYCLE9-PREREGISTRATION.md",
        "event_pool_size": len(events),
        "event_types": sorted(FROZEN_EVENT_TYPES),
        "parameter_evaluations": len(all_results),
        "outcome": outcome,
        "survivor_count": len(survivors), "survivors": survivors,
        "still_underpowered_count": len(still_underpowered),
        "still_underpowered": still_underpowered,
        "train_failed_count": len(train_failed),
        "validation_failed_count": len(val_failed),
        "results": all_results,
    }
    out = R / "reports/factory/discovery_cycles/cycle_09_sc_power.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(f"\nCYCLE 9: {len(all_results)} evaluations, outcome={outcome}")
    print(f"  survivors={len(survivors)}  still_underpowered={len(still_underpowered)}  "
         f"train_failed={len(train_failed)}  validation_failed={len(val_failed)}")
    for r in sorted(all_results, key=lambda x: -x["train"]["t_stat"])[:10]:
        print(f"  {r['symbol']}/{r['driver']:6s} w={r['window_min']:3d}m  "
             f"train(n={r['train']['n']:3d},t={r['train']['t_stat']:+.2f})  "
             f"val(n={r['validation']['n']:3d},t={r['validation']['t_stat']:+.2f})  {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
