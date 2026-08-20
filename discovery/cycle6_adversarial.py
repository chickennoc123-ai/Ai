"""
GEN 12 for Cycle 6 -- adversarial destruction of the C2 NFP-surprise survivors.

Five binding attacks, same standard as Cycle 4:
    1. COST SHOCK       1.5x / 2x / 3x the frozen round trip
    2. EXECUTION DELAY  entry slips 1 bar (1h) after the release bar --
                        can't act on the surprise before the release bar
                        itself closes, so delay is measured in bars, not days
    3. PARAMETER SHIFT  post_hours neighbours from the pre-registered grid
    4. SUBPERIOD        >= 3 of 4 contiguous (event-order) blocks net-positive
    5. BOOTSTRAP        1000 resamples, >= 95% with positive mean

Plus one advisory check specific to this family:
    6. CROSS-INSTRUMENT SIGN CONSISTENCY -- does the SAME underlying mechanism
       (long USD on a stronger-than-forecast NFP print) show the correct SIGN
       on every USD pair, once quote-currency direction is corrected, even on
       instruments that did not individually clear the survivor bar? This is
       the direct test of whether these are one discovery or four coincidences.
"""
import json
import random
import sys
from pathlib import Path
from typing import Dict, List

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import roundtrip_cost
from discovery.cycle6_events import _bars_for, _events_for, _symbol_dev_events
from discovery.cycle5_events import c2_surprise, stats, POST_WINDOWS_H

SEED = 20260820
BOOTSTRAP_N = 1000
BOOTSTRAP_MIN_POSITIVE = 0.95

# USD-base pairs: +1 = long USD. USD-quote pairs: +1 = long the OTHER currency,
# so a "long USD" bet is -1. XAUUSD is USD-quote with an inverse macro link:
# gold falls when USD strengthens, so a "long USD" bet is also -1 (short gold).
USD_DIRECTION_SIGN = {
    "EURUSD": -1, "GBPUSD": -1,               # USD is the quote currency
    "USDCAD": +1, "USDCHF": +1, "USDJPY": +1,  # USD is the base currency
    "XAUUSD": -1,                              # inverse macro link, not quote convention
}
ALL_SYMBOLS = list(USD_DIRECTION_SIGN)


def _run(symbol: str, event_name: str, currency: str, post_hours: int, mode: str,
        cost_mult: float = 1.0, delay_bars: int = 0) -> "EStats":
    bars = _bars_for(symbol)
    all_events = _events_for(symbol)
    matching = [e for e in all_events if e.name == event_name and e.currency == currency]
    tr_ev, _va_ev, _ = _symbol_dev_events(symbol, matching)
    cut = int(len(bars) * 0.80)
    tr_bars = bars[:cut]
    cost = roundtrip_cost(symbol) * cost_mult
    if delay_bars:
        from datetime import timedelta
        matching = [type(e)(ts=e.ts + timedelta(hours=delay_bars), event_id=e.event_id,
                            name=e.name, country=e.country, currency=e.currency,
                            impact=e.impact, actual=e.actual, forecast=e.forecast,
                            previous=e.previous, revision=e.revision, source=e.source)
                    for e in tr_ev]
        tr_ev = matching
    return stats(c2_surprise(tr_bars, tr_ev, post_hours, mode, cost), cost)


def destroy(symbol: str, event_name: str, currency: str, post_hours: int, mode: str) -> Dict:
    bars = _bars_for(symbol)
    all_events = _events_for(symbol)
    matching = [e for e in all_events if e.name == event_name and e.currency == currency]
    tr_ev, _va_ev, _ = _symbol_dev_events(symbol, matching)
    cut = int(len(bars) * 0.80)
    tr_bars = bars[:cut]
    cost = roundtrip_cost(symbol)
    attacks: Dict[str, Dict] = {}
    evals = 0

    # 1 cost shock
    shocks = {}
    for mult in (1.5, 2.0, 3.0):
        s = _run(symbol, event_name, currency, post_hours, mode, cost_mult=mult); evals += 1
        shocks[f"{mult}x"] = {"mean_net": s.mean_net, "t": s.t_stat, "n": s.n}
    attacks["cost_shock"] = {"detail": shocks,
                             "pass": all(v["mean_net"] > 0 for v in shocks.values())}

    # 2 execution delay -- 1 bar after the release bar closes
    d1 = _run(symbol, event_name, currency, post_hours, mode, delay_bars=1); evals += 1
    attacks["execution_delay"] = {"detail": {"1_bar": {"mean_net": d1.mean_net,
                                                       "t": d1.t_stat, "n": d1.n}},
                                  "pass": d1.mean_net > 0}

    # 3 parameter shift -- neighbouring post_hours from the pre-registered grid
    shifts = {}
    for h in POST_WINDOWS_H:
        if h == post_hours:
            continue
        s = _run(symbol, event_name, currency, h, mode); evals += 1
        shifts[f"h{h}"] = {"mean_net": s.mean_net, "t": s.t_stat, "n": s.n}
    pos = sum(1 for v in shifts.values() if v["mean_net"] > 0)
    attacks["parameter_shift"] = {"detail": shifts, "positive": pos, "total": len(shifts),
                                  "pass": pos >= 0.75 * len(shifts)}

    # 4 subperiod -- 4 contiguous blocks by event order
    blocks = []
    bs = max(1, len(tr_ev) // 4)
    for b in range(4):
        seg = tr_ev[b * bs:(b + 1) * bs] if b < 3 else tr_ev[b * bs:]
        s = stats(c2_surprise(tr_bars, seg, post_hours, mode, cost), cost); evals += 1
        blocks.append({"block": b, "n": s.n, "mean_net": s.mean_net, "t": s.t_stat})
    npos = sum(1 for b in blocks if b["mean_net"] > 0)
    attacks["subperiod"] = {"detail": blocks, "positive_blocks": npos, "pass": npos >= 3}

    # 5 bootstrap
    trades = c2_surprise(tr_bars, tr_ev, post_hours, mode, cost)
    nets = [t.net for t in trades]
    rng = random.Random(SEED)
    positive = 0
    for _ in range(BOOTSTRAP_N):
        sample = [nets[rng.randrange(len(nets))] for _ in range(len(nets))]
        if sum(sample) / len(sample) > 0:
            positive += 1
    frac = positive / BOOTSTRAP_N
    attacks["bootstrap"] = {"resamples": BOOTSTRAP_N, "positive_fraction": frac,
                            "required": BOOTSTRAP_MIN_POSITIVE, "pass": frac >= BOOTSTRAP_MIN_POSITIVE}

    binding = [k for k in attacks]
    survived = all(attacks[k]["pass"] for k in binding)
    return {"symbol": symbol, "event_name": event_name, "family": "C2_SURPRISE_REACTION",
            "params": {"post_hours": post_hours, "mode": mode},
            "attacks": attacks, "binding_attacks": binding,
            "extra_parameter_evaluations": evals,
            "verdict": "SURVIVED_ADVERSARIAL" if survived else "DESTROYED"}


def cross_instrument_sign_check(event_name: str, currency: str, post_hours: int) -> Dict:
    """
    Advisory attack 6: apply the SAME single mechanism (direction determined
    by USD_DIRECTION_SIGN, not by per-symbol FOLLOW/FADE labels) to every USD
    pair, including ones that never individually cleared the survivor bar, and
    check the sign is consistent everywhere.
    """
    out = {}
    for symbol in ALL_SYMBOLS:
        sign = USD_DIRECTION_SIGN[symbol]
        mode = "FOLLOW" if sign == 1 else "FADE"
        s = _run(symbol, event_name, currency, post_hours, mode)
        out[symbol] = {"mean_net": s.mean_net, "t": s.t_stat, "n": s.n,
                       "mode_implied_by_usd_direction": mode}
    positive = sum(1 for v in out.values() if v["mean_net"] > 0)
    return {"per_symbol": out, "positive_symbols": positive, "total_symbols": len(out),
            "advisory": True,
            "reading": (f"{positive}/{len(out)} instruments show the USD-strength-consistent "
                       f"sign, using ONE mechanism direction applied uniformly, not four "
                       f"independently-chosen FOLLOW/FADE labels")}


def main() -> int:
    rb = json.loads((R / "reports/factory/discovery_cycles/cycle_06_robustness.json").read_text())
    out = []
    for c in rb["detail"]:
        if not c["all_conditions_pass"]:
            continue
        out.append(destroy(c["symbol"], c["event_name"], "USD",
                           c["params"]["post_hours"], c["params"]["mode"]))

    cross = cross_instrument_sign_check("Non-Farm Employment Change", "USD", 4)

    payload = {"cycle_id": "CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR", "stage": "GEN 12 adversarial",
               "seed": SEED,
               "extra_parameter_evaluations": sum(o["extra_parameter_evaluations"] for o in out),
               "survived": [o for o in out if o["verdict"] == "SURVIVED_ADVERSARIAL"],
               "detail": out,
               "cross_instrument_sign_check": cross}
    (R / "reports/factory/discovery_cycles/cycle_06_adversarial.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    for o in out:
        print(f"{o['symbol']} {o['event_name']} {o['params']}  ->  {o['verdict']}")
        for name in o["binding_attacks"]:
            a = o["attacks"][name]
            print(f"   {name:18s} {'PASS' if a['pass'] else 'FAIL'}")
        cs = o["attacks"]["cost_shock"]["detail"]
        print("     cost shock: " + "  ".join(
            f"{k}: net={v['mean_net']:+.5f} t={v['t']:+.2f}" for k, v in cs.items()))
        d = o["attacks"]["execution_delay"]["detail"]["1_bar"]
        print(f"     delay 1bar: net={d['mean_net']:+.5f} t={d['t']:+.2f} n={d['n']}")
        b = o["attacks"]["bootstrap"]
        print(f"     bootstrap : {b['positive_fraction']:.1%} positive (need {b['required']:.0%})")
    print(f"\ncross-instrument sign check (advisory): {cross['reading']}")
    for sym, v in cross["per_symbol"].items():
        print(f"    {sym:7s} mode={v['mode_implied_by_usd_direction']:7s} "
              f"n={v['n']:4d} net={v['mean_net']:+.6f} t={v['t']:+.2f}")
    print(f"\nextra parameter evaluations: {payload['extra_parameter_evaluations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
