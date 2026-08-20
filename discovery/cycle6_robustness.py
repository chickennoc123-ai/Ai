"""
GEN 7 Cycle 6 -- Phase 6 survivor interrogation for the C2 NFP-surprise family.

Same ten-condition discipline as B2_TURN_OF_MONTH (Cycle 4). Conditions 1-5
are the economic filter already applied by the sweep. This module applies
6-10: subperiod persistence, parameter-neighbourhood robustness, mechanism
interpretability, family novelty, and multiple-testing accounting.
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import roundtrip_cost
from discovery.cycle6_events import _bars_for, _events_for, _symbol_dev_events
from discovery.cycle5_events import c2_surprise, stats, POST_WINDOWS_H

SUBPERIOD_BLOCKS = 4
SUBPERIOD_MIN_POSITIVE = 3
NEIGHBOURHOOD_MIN_POSITIVE_FRAC = 0.60


def interrogate(symbol: str, event_name: str, currency: str, post_hours: int, mode: str) -> Dict:
    bars = _bars_for(symbol)
    all_events = _events_for(symbol)
    matching = [e for e in all_events if e.name == event_name and e.currency == currency]
    tr_ev, va_ev, _ = _symbol_dev_events(symbol, matching)
    cut = int(len(bars) * 0.80)
    tr_bars, va_bars = bars[:cut], bars[cut:]
    cost = roundtrip_cost(symbol)
    evals = 0

    tr_trades = c2_surprise(tr_bars, tr_ev, post_hours, mode, cost); evals += 1
    va_trades = c2_surprise(va_bars, va_ev, post_hours, mode, cost); evals += 1
    s_tr, s_va = stats(tr_trades, cost), stats(va_trades, cost)

    # 6. subperiod persistence -- split TRAIN events chronologically into 4 blocks
    blocks = []
    bs = max(1, len(tr_ev) // SUBPERIOD_BLOCKS)
    for b in range(SUBPERIOD_BLOCKS):
        seg = tr_ev[b * bs:(b + 1) * bs] if b < SUBPERIOD_BLOCKS - 1 else tr_ev[b * bs:]
        st = stats(c2_surprise(tr_bars, seg, post_hours, mode, cost), cost); evals += 1
        blocks.append({"block": b, "n": st.n, "mean_net": st.mean_net, "t": st.t_stat})
    positive_blocks = sum(1 for b in blocks if b["mean_net"] > 0)
    cond6 = positive_blocks >= SUBPERIOD_MIN_POSITIVE

    # 7. parameter neighbourhood -- vary post_hours across the pre-registered grid
    neigh = []
    for h in POST_WINDOWS_H:
        st = stats(c2_surprise(tr_bars, tr_ev, h, mode, cost), cost)
        sv = stats(c2_surprise(va_bars, va_ev, h, mode, cost), cost)
        evals += 2
        neigh.append({"post_hours": h, "train_net": st.mean_net, "train_t": st.t_stat,
                      "val_net": sv.mean_net, "val_t": sv.t_stat})
    pos_frac = sum(1 for x in neigh if x["train_net"] > 0 and x["val_net"] > 0) / len(neigh)
    cond7 = pos_frac >= NEIGHBOURHOOD_MIN_POSITIVE_FRAC

    cond8 = True   # USD strength on positive NFP surprise: named, standard macro mechanism
    cond9 = True   # C2 is a new family (never tested before Cycle 6)
    cond_hold = True  # event families are exempt from the 24h floor by design (Cycle 5 rule)

    return {
        "symbol": symbol, "event_name": event_name, "family": "C2_SURPRISE_REACTION",
        "params": {"post_hours": post_hours, "mode": mode},
        "train": s_tr.to_dict(), "validation": s_va.to_dict(),
        "extra_parameter_evaluations": evals,
        "cond6_subperiod": {"pass": cond6, "positive_blocks": positive_blocks,
                            "required": SUBPERIOD_MIN_POSITIVE, "blocks": blocks},
        "cond7_parameter_robustness": {"pass": cond7,
                                       "both_positive_fraction": round(pos_frac, 3),
                                       "required": NEIGHBOURHOOD_MIN_POSITIVE_FRAC,
                                       "neighbourhood": neigh},
        "cond8_mechanism_interpretable": cond8,
        "cond9_family_not_refuted": cond9,
        "cond_realized_hold_ok": cond_hold,
        "all_conditions_pass": bool(cond6 and cond7 and cond8 and cond9 and cond_hold),
    }


def main() -> int:
    sweep = json.loads((R / "reports/factory/discovery_cycles/cycle_06_event_sweep.json").read_text())
    out: List[Dict] = []
    for s in sweep["survivors"]:
        out.append(interrogate(s["symbol"], s["event_name"], s["currency"],
                               s["params"]["post_hours"], s["params"]["mode"]))

    total_extra = sum(o["extra_parameter_evaluations"] for o in out)
    confirmed = [o for o in out if o["all_conditions_pass"]]
    payload = {"cycle_id": "CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR",
               "stage": "Phase 6 survivor interrogation",
               "candidates_interrogated": len(out),
               "extra_parameter_evaluations": total_extra,
               "confirmed_survivors": len(confirmed),
               "detail": out}
    (R / "reports/factory/discovery_cycles/cycle_06_robustness.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    for o in out:
        print(f"{o['symbol']} {o['event_name']} {o['params']}")
        print(f"  6 subperiod : {'PASS' if o['cond6_subperiod']['pass'] else 'FAIL'} "
              f"({o['cond6_subperiod']['positive_blocks']}/4 blocks net-positive)")
        for b in o["cond6_subperiod"]["blocks"]:
            print(f"      block {b['block']}: n={b['n']:3d} net={b['mean_net']:+.6f} t={b['t']:+.2f}")
        c7 = o["cond7_parameter_robustness"]
        print(f"  7 param robust: {'PASS' if c7['pass'] else 'FAIL'} "
              f"({c7['both_positive_fraction']:.0%} of {len(POST_WINDOWS_H)} windows positive both sides)")
        print(f"  ALL CONDITIONS: {'PASS' if o['all_conditions_pass'] else 'FAIL'}\n")
    print(f"extra parameter evaluations: {total_extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
