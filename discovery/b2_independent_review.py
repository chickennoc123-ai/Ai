"""
B2_TURN_OF_MONTH -- independent review before any holdout decision.

DIAGNOSTIC ONLY. Nothing in this file can promote the candidate. If a
conditioned variant looks better than the base rule, that variant is NOT
adopted -- selecting it after seeing the result is precisely the fitting this
project exists to avoid. The only questions asked here are:

    Q1  Is this a GOLD effect or a USD effect?
        (a USD-flow story predicts it appears in the USD pairs too)
    Q2  Is it stable through time, or carried by a few years?
    Q3  Does an exogenous prior (USD strength / risk sentiment, both measured
        from OTHER instruments) explain when it works?
    Q4  Is genuinely independent gold data available for a second test?

Every probe is counted into the multiple-testing ledger.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import load_dev_bars, OBSERVATION_FRACTION
from discovery.cost_model import roundtrip_cost
from discovery.cycle4_economics import (
    to_daily, stats, _materialize, sig_B2_turn_of_month, SYMBOLS,
)

WINDOW, DIRECTION, HOLD = (1, 1), 1, 2


def _days(sym):
    return to_daily(load_dev_bars(REPO_ROOT / "data/csv" / f"{sym}_H1.csv"))


def q1_gold_or_usd() -> Dict:
    """Same rule, every instrument. A USD-flow story predicts consistency."""
    out = {}
    for s in SYMBOLS:
        d = _days(s)
        c = roundtrip_cost(s)
        st = stats(_materialize(d, sig_B2_turn_of_month(d, WINDOW, DIRECTION), HOLD, c), c)
        out[s] = {"n": st.n, "mean_net": st.mean_net, "t": st.t_stat,
                  "gross_over_cost": st.gross_over_cost}
    pos = [s for s, v in out.items() if v["mean_net"] > 0]
    sig = [s for s, v in out.items() if v["t"] >= 2.0]
    return {"per_symbol": out, "net_positive": pos, "significant": sig,
            "evaluations": len(SYMBOLS),
            "reading": ("gold-specific: the effect does not generalise to the USD pairs"
                        if len(sig) <= 1 else
                        "possibly a USD-flow effect: it appears in multiple pairs")}


def q2_year_stability(symbol="XAUUSD") -> Dict:
    d = _days(symbol)
    c = roundtrip_cost(symbol)
    trades = _materialize(d, sig_B2_turn_of_month(d, WINDOW, DIRECTION), HOLD, c)
    by_year = defaultdict(list)
    for t in trades:
        by_year[t.entry[:4]].append(t)
    rows = {y: {"n": len(v), "mean_net": round(sum(x.net for x in v) / len(v), 8),
                "total": round(sum(x.net for x in v), 6)}
            for y, v in sorted(by_year.items())}
    pos = sum(1 for v in rows.values() if v["mean_net"] > 0)
    best = max(rows.items(), key=lambda kv: kv[1]["total"])
    total_all = sum(v["total"] for v in rows.values())
    return {"per_year": rows, "years": len(rows), "positive_years": pos,
            "evaluations": len(rows),
            "best_year": best[0],
            "best_year_share_of_total": round(best[1]["total"] / total_all, 3)
            if total_all else None,
            "reading": ("broadly stable" if pos >= 0.7 * len(rows)
                        else "carried by a minority of years")}


def q3_exogenous_prior(symbol="XAUUSD") -> Dict:
    """
    Split months by a prior measured from OTHER instruments only:
      USD strength  = mean log return of USDCAD/USDCHF/USDJPY over the month
      risk sentiment= USDCHF return (CHF bid = risk-off)
    Diagnostic split, not a candidate variant.
    """
    d = _days(symbol)
    c = roundtrip_cost(symbol)
    others = {s: _days(s) for s in ("USDCAD", "USDCHF", "USDJPY")}
    by_date = {s: {x.date: i for i, x in enumerate(v)} for s, v in others.items()}

    trades = _materialize(d, sig_B2_turn_of_month(d, WINDOW, DIRECTION), HOLD, c)
    import math
    strong, weak = [], []
    riskoff, riskon = [], []
    for t in trades:
        from datetime import datetime
        entry = datetime.fromisoformat(t.entry)
        usd_moves, chf = [], None
        for s, series in others.items():
            i = by_date[s].get(entry)
            if i is None or i < 21:
                continue
            m = math.log(series[i].close / series[i - 21].close)
            usd_moves.append(m)
            if s == "USDCHF":
                chf = m
        if not usd_moves:
            continue
        (strong if sum(usd_moves) / len(usd_moves) > 0 else weak).append(t)
        if chf is not None:
            (riskoff if chf > 0 else riskon).append(t)

    def blk(ts):
        st = stats(ts, c) if ts else None
        return {"n": st.n, "mean_net": st.mean_net, "t": st.t_stat} if st else {"n": 0}

    return {"usd_strong_prior_month": blk(strong), "usd_weak_prior_month": blk(weak),
            "risk_off_prior_month": blk(riskoff), "risk_on_prior_month": blk(riskon),
            "evaluations": 4,
            "note": ("DIAGNOSTIC ONLY -- the conditioned variants are not adopted as "
                     "the candidate; selecting the better split after seeing it would "
                     "be fitting.")}


def q4_independent_data() -> Dict:
    holdout = sorted((REPO_ROOT / "data/holdout").glob("XAUUSD_H1_HOLDOUT_*.csv"))
    return {
        "independent_gold_series_available": False,
        "reason": ("The only XAUUSD data in the project is one vendor series, already "
                   "split into development (used above) and a reserved holdout. There "
                   "is no second, independent gold series to test against, so option "
                   "(b) cannot be completed without new data acquisition."),
        "reserved_holdout_present_but_untouched": [p.name for p in holdout],
        "what_would_satisfy_it": [
            "a second vendor's XAUUSD H1/D1 series covering 2010-2023",
            "gold futures (GC) settlement data, which is a different instrument "
            "with different month-end mechanics -- a genuine independent test",
            "a longer XAUUSD history predating 2009 from any source",
        ],
        "evaluations": 0,
    }


def main() -> int:
    r = {"candidate": "B2_TURN_OF_MONTH XAUUSD long, window=[1,1], hold=2d",
         "q1_gold_or_usd": q1_gold_or_usd(),
         "q2_year_stability": q2_year_stability(),
         "q3_exogenous_prior": q3_exogenous_prior(),
         "q4_independent_data": q4_independent_data()}
    r["total_evaluations"] = sum(v.get("evaluations", 0) for k, v in r.items()
                                 if isinstance(v, dict))
    out = REPO_ROOT / "reports/factory/discovery_cycles/b2_independent_review.json"
    out.write_text(json.dumps(r, indent=2), encoding="utf-8")

    print("B2_TURN_OF_MONTH -- INDEPENDENT REVIEW (diagnostic)")
    q1 = r["q1_gold_or_usd"]
    print(f"\nQ1 gold or USD?  net-positive: {q1['net_positive']}  significant: {q1['significant']}")
    for s, v in q1["per_symbol"].items():
        print(f"    {s:7s} n={v['n']:4d} net={v['mean_net']:+.6f} t={v['t']:+.2f} g/c={v['gross_over_cost']}")
    print(f"    -> {q1['reading']}")
    q2 = r["q2_year_stability"]
    print(f"\nQ2 stability: {q2['positive_years']}/{q2['years']} years net-positive; "
          f"best year {q2['best_year']} = {q2['best_year_share_of_total']:.0%} of all profit")
    print(f"    -> {q2['reading']}")
    q3 = r["q3_exogenous_prior"]
    print("\nQ3 exogenous prior (diagnostic only):")
    for k in ("usd_strong_prior_month", "usd_weak_prior_month",
              "risk_off_prior_month", "risk_on_prior_month"):
        v = q3[k]
        print(f"    {k:26s} n={v['n']:4d} net={v.get('mean_net',0):+.6f} t={v.get('t',0):+.2f}")
    print(f"\nQ4 independent gold data available: {r['q4_independent_data']['independent_gold_series_available']}")
    print(f"\ntotal extra parameter evaluations: {r['total_evaluations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
