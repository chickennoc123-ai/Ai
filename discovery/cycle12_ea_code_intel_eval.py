"""
GEN 7 CYCLE 12 -- EA Code Intelligence: real Factory evaluation of
HYP-EACI-0001 (DUAL_DRIVER_CONFIRMATION), the one hypothesis synthesized by
idea_machine/ea_code_intel/ from real mined source material that (a) uses
only data this project has, (b) is structurally distinct from every
previously tried mechanism (checked by novelty_engine.py and by hand
against the 6 frozen SC_SURPRISE_CONFIRMATION candidates and Cycle 11's
HYP-IM-0001).

Methodology discipline (learned from Cycle 11's two bugs): SURPRISE_FX_DIR
and the PAIRINGS base_dir convention are imported directly from
discovery/cycle8_intraday.py, never redefined -- and the train/validation
split uses the SAME chronological event-index method as
evaluate_pairing(), not an ad hoc trade-index split.
"""
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import roundtrip_cost
from discovery.event_calendar import load_events
from discovery.cycle8_intraday import (
    fx_series, driver_series, stats, gate, SURPRISE_FX_DIR,
    ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN,
)


def _entry_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(seconds=ENTRY_DELAY_SEC)

def _impulse_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(minutes=IMPULSE_WINDOW_MIN)

def _exit_ts(event_ts: datetime, window_min: int) -> datetime:
    return event_ts + timedelta(minutes=window_min)

def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


# base_dir for (USDJPY, SPX500): +1, copied verbatim from Cycle 8's own
# validated PAIRINGS list ("SPX up -> risk-on, JPY funding-currency sold -> long USDJPY").
BASE_DIR_SPX500_USDJPY = +1

# base_dir for (USDJPY, US10Y): -1, STATED here explicitly (not present in
# Cycle 8's PAIRINGS list, which only paired US10Y with EURUSD/GBPUSD).
# Economic reasoning, stated BEFORE running this evaluation: US10Y in this
# dataset is a bond PRICE series, so price-up means yield-down. Cycle 8's own
# reasoning for EURUSD/GBPUSD was "yield down -> USD carry less attractive ->
# long EUR/GBP" (i.e. USD sold). Applying the same carry logic to USDJPY:
# yield down -> USD sold -> USDJPY DOWN. So US10Y price up (yield down) ->
# USDJPY down -> base_dir = -1.
BASE_DIR_US10Y_USDJPY = -1


def trade_dual_driver(event, fx, spx, us10y, symbol: str, window_min: int, cost: float) -> Optional[float]:
    """DUAL_DRIVER_CONFIRMATION: trade only if BOTH SPX500 and US10Y confirm the surprise direction."""
    if event.surprise is None or event.surprise == 0:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)

    spx0, spx1 = spx.price_at_or_after(t_entry), spx.price_at_or_after(t_imp)
    y0, y1 = us10y.price_at_or_after(t_entry), us10y.price_at_or_after(t_imp)
    f0 = fx.price_at_or_after(t_entry)
    f2 = fx.price_at_or_after(t_exit)
    if None in (spx0, spx1, y0, y1, f0, f2) or spx0 <= 0 or y0 <= 0 or f0 <= 0:
        return None

    expected_from_spx = BASE_DIR_SPX500_USDJPY * _sign(math.log(spx1 / spx0))
    expected_from_y = BASE_DIR_US10Y_USDJPY * _sign(math.log(y1 / y0))
    implied_from_surprise = SURPRISE_FX_DIR[symbol] * _sign(event.surprise)

    if expected_from_spx == 0 or expected_from_y == 0:
        return None
    if not (expected_from_spx == expected_from_y == implied_from_surprise):
        return None  # both drivers must agree with EACH OTHER and with the surprise

    gross = implied_from_surprise * math.log(f2 / f0)
    return gross - cost


def run():
    print("=" * 80)
    print("GEN 7 CYCLE 12: EA Code Intelligence -- HYP-EACI-0001 Factory Evaluation")
    print("=" * 80)

    symbol = "USDJPY"
    event_path = R / "data/events/raw/forexfactory_2010_2023.csv"
    dev_end = datetime(2020, 4, 29, 23, 59, 59)

    all_events = load_events(event_path, dev_end=dev_end)
    nfp_events = sorted([e for e in all_events if e.name == "Non-Farm Employment Change" and e.currency == "USD"],
                        key=lambda e: e.ts)

    fx = fx_series(symbol)
    spx = driver_series("SPX500")
    us10y = driver_series("US10Y")
    cost = roundtrip_cost(symbol)

    print(f"Symbol: {symbol} (H1) | Drivers: SPX500 (M1), US10Y (M1)")
    print(f"Events: {len(nfp_events)} NFP releases in dev period")
    print(f"Cost: {cost:.6f} per round-trip")
    print(f"Mechanism: BOTH drivers must confirm surprise direction (dual confirmation)")

    n_events = len(nfp_events)
    cut = int(n_events * 0.80)
    cutoff_ts = nfp_events[cut].ts if cut < n_events else nfp_events[-1].ts

    windows = [60, 120, 240]  # USDJPY is H1-only; sub-hourly windows aren't meaningful
    results = []
    for w in windows:
        nets = []
        for e in nfp_events:
            r = trade_dual_driver(e, fx, spx, us10y, symbol, w, cost)
            if r is not None:
                nets.append((e.ts, r))

        tr_nets, va_nets = [], []
        for ts, r in nets:
            (tr_nets if ts < cutoff_ts else va_nets).append(r)

        gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
        tr_s = stats(tr_nets, gm + cost, cost)
        va_s = stats(va_nets, 0.0, cost)
        v, reason = gate(tr_s, va_s)

        n_confirmed = len(nets)
        conf_rate = n_confirmed / n_events if n_events else 0.0
        status = "PASS" if v == "DISCOVERY_SURVIVOR" else "FAIL"
        print(f"  Window {w:3d}m: confirmed={n_confirmed:3d}/{n_events} ({conf_rate:.1%})  "
              f"train n={tr_s.n:2d} t={tr_s.t_stat:6.2f}  val n={va_s.n:2d} t={va_s.t_stat:6.2f}  "
              f"{status} ({v}: {reason})")

        results.append({
            "window_min": w, "n_confirmed": n_confirmed, "n_events_available": n_events,
            "confirmation_rate": round(conf_rate, 4),
            "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "reason": reason,
        })

    survivors = [r for r in results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    print(f"\nSurvivors: {len(survivors)}/{len(windows)}")
    return results, survivors


if __name__ == "__main__":
    import json
    results, survivors = run()
    out = {
        "cycle_id": "CYCLE-12-EA-CODE-INTEL",
        "generated_at": datetime.utcnow().isoformat(),
        "hypotheses": [{
            "hyp_id": "HYP-EACI-0001",
            "source_idea_id": "EA-CODE-INTEL-MINED",
            "category": "CROSS_ASSET_DUAL_CONFIRMATION",
            "symbol": "USDJPY", "driver": "US10Y+SPX500",
            "n_events_available": results[0]["n_events_available"] if results else 0,
            "windows": results,
        }],
    }
    out_path = R / "reports/factory/discovery_cycles/cycle_12_ea_code_intel.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {out_path}")
