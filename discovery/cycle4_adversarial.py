"""
GEN 12 for Cycle 4 -- adversarial destruction of the positional survivor.

Six attacks. The candidate must survive ALL of them to reach GEN 13 freeze.
Every attack is deterministic (the bootstrap uses a fixed seed).

    1. COST SHOCK          1.5x / 2x / 3x the frozen round trip
    2. EXECUTION DELAY     entry slips one full day late
    3. PARAMETER SHIFT     +/-1 on window and hold
    4. SUBPERIOD           >= 3 of 4 contiguous blocks net-positive
    5. BOOTSTRAP           1000 resamples, >= 95% with positive mean
    6. SYMBOL SHIFT        same rule on the other five instruments (advisory)
"""

import json
import random
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import load_dev_bars, OBSERVATION_FRACTION
from discovery.cost_model import roundtrip_cost
from discovery.cycle4_economics import (
    to_daily, stats, _materialize, sig_B2_turn_of_month, SYMBOLS,
)

SEED = 20260820
BOOTSTRAP_N = 1000
BOOTSTRAP_MIN_POSITIVE = 0.95


def _dev_days(symbol):
    return to_daily(load_dev_bars(REPO_ROOT / "data/csv" / f"{symbol}_H1.csv"))


def _run(days, window, direction, hold, cost, delay=0):
    sigs = [(i + delay, d) for i, d in sig_B2_turn_of_month(days, tuple(window), direction)]
    sigs = [(i, d) for i, d in sigs if i < len(days)]
    return stats(_materialize(days, sigs, hold, cost), cost)


def destroy(symbol: str, window, direction: int, hold: int) -> Dict:
    days = _dev_days(symbol)
    cost = roundtrip_cost(symbol)
    attacks: Dict[str, Dict] = {}
    evals = 0

    # 1 cost shock -----------------------------------------------------------
    shocks = {}
    for mult in (1.5, 2.0, 3.0):
        s = _run(days, window, direction, hold, cost * mult); evals += 1
        shocks[f"{mult}x"] = {"mean_net": s.mean_net, "t": s.t_stat, "n": s.n}
    attacks["cost_shock"] = {"detail": shocks,
                             "pass": all(v["mean_net"] > 0 for v in shocks.values())}

    # 2 execution delay ------------------------------------------------------
    d1 = _run(days, window, direction, hold, cost, delay=1); evals += 1
    attacks["execution_delay"] = {"detail": {"1_day": {"mean_net": d1.mean_net,
                                                       "t": d1.t_stat, "n": d1.n}},
                                  "pass": d1.mean_net > 0}

    # 3 parameter shift ------------------------------------------------------
    shifts = {}
    for w in ([max(1, window[0] - 1), window[1]], [window[0] + 1, window[1]],
              [window[0], max(1, window[1] - 1)], [window[0], window[1] + 1]):
        for h in (hold - 1, hold + 1):
            if h < 1:
                continue
            s = _run(days, w, direction, h, cost); evals += 1
            shifts[f"w{w}_h{h}"] = {"mean_net": s.mean_net, "t": s.t_stat, "n": s.n}
    pos = sum(1 for v in shifts.values() if v["mean_net"] > 0)
    attacks["parameter_shift"] = {"detail": shifts, "positive": pos,
                                  "total": len(shifts),
                                  "pass": pos >= 0.75 * len(shifts)}

    # 4 subperiod ------------------------------------------------------------
    bs = len(days) // 4
    blocks = []
    for b in range(4):
        seg = days[b * bs:(b + 1) * bs] if b < 3 else days[b * bs:]
        s = _run(seg, window, direction, hold, cost); evals += 1
        blocks.append({"block": b, "n": s.n, "mean_net": s.mean_net, "t": s.t_stat})
    npos = sum(1 for b in blocks if b["mean_net"] > 0)
    attacks["subperiod"] = {"detail": blocks, "positive_blocks": npos,
                            "pass": npos >= 3}

    # 5 bootstrap ------------------------------------------------------------
    trades = _materialize(days, sig_B2_turn_of_month(days, tuple(window), direction),
                          hold, cost)
    nets = [t.net for t in trades]
    rng = random.Random(SEED)
    positive = 0
    for _ in range(BOOTSTRAP_N):
        sample = [nets[rng.randrange(len(nets))] for _ in range(len(nets))]
        if sum(sample) / len(sample) > 0:
            positive += 1
    frac = positive / BOOTSTRAP_N
    attacks["bootstrap"] = {"resamples": BOOTSTRAP_N, "positive_fraction": frac,
                            "required": BOOTSTRAP_MIN_POSITIVE,
                            "pass": frac >= BOOTSTRAP_MIN_POSITIVE}

    # 6 symbol shift (advisory) ---------------------------------------------
    others = {}
    for s_ in SYMBOLS:
        if s_ == symbol:
            continue
        st = _run(_dev_days(s_), window, direction, hold, roundtrip_cost(s_)); evals += 1
        others[s_] = {"mean_net": st.mean_net, "t": st.t_stat, "n": st.n}
    attacks["symbol_shift"] = {"detail": others, "advisory": True,
                               "positive_symbols": sum(1 for v in others.values()
                                                       if v["mean_net"] > 0)}

    binding = [k for k, v in attacks.items() if "pass" in v]
    survived = all(attacks[k]["pass"] for k in binding)
    return {"symbol": symbol, "family": "B2_TURN_OF_MONTH",
            "params": {"window": list(window), "dir": direction, "hold_days": hold},
            "attacks": attacks, "binding_attacks": binding,
            "extra_parameter_evaluations": evals,
            "verdict": "SURVIVED_ADVERSARIAL" if survived else "DESTROYED"}


def main() -> int:
    rb = json.loads((REPO_ROOT /
        "reports/factory/discovery_cycles/cycle_04_robustness.json").read_text())
    out = []
    for c in rb["detail"]:
        if not c["all_conditions_pass"]:
            continue
        out.append(destroy(c["symbol"], c["params"]["window"],
                           c["params"]["dir"], c["params"]["hold_days"]))

    payload = {"cycle_id": "CYCLE-4-ECONOMIC-STRUCTURE", "stage": "GEN 12 adversarial",
               "seed": SEED,
               "extra_parameter_evaluations": sum(o["extra_parameter_evaluations"] for o in out),
               "survived": [o for o in out if o["verdict"] == "SURVIVED_ADVERSARIAL"],
               "detail": out}
    (REPO_ROOT / "reports/factory/discovery_cycles/cycle_04_adversarial.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    for o in out:
        print(f"{o['family']} {o['symbol']} {o['params']}  ->  {o['verdict']}")
        for name in o["binding_attacks"]:
            a = o["attacks"][name]
            print(f"   {name:18s} {'PASS' if a['pass'] else 'FAIL'}")
        cs = o["attacks"]["cost_shock"]["detail"]
        print("     cost shock: " + "  ".join(
            f"{k}: net={v['mean_net']:+.5f} t={v['t']:+.2f}" for k, v in cs.items()))
        d = o["attacks"]["execution_delay"]["detail"]["1_day"]
        print(f"     delay 1d  : net={d['mean_net']:+.5f} t={d['t']:+.2f} n={d['n']}")
        b = o["attacks"]["bootstrap"]
        print(f"     bootstrap : {b['positive_fraction']:.1%} positive (need {b['required']:.0%})")
        ss = o["attacks"]["symbol_shift"]
        print(f"     symbols   : {ss['positive_symbols']}/5 other instruments net-positive (advisory)")
    print(f"\nextra parameter evaluations: {payload['extra_parameter_evaluations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
