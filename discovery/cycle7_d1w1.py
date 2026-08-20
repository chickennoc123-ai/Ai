"""
GEN 7 CYCLE 7 -- Phase 3: D1/W1 positional structures.

Two families, both structurally DIFFERENT from the refuted Cycle 4 families
(FAIL-000031: undirected D1 streak-reversal and 20-day breakout persistence,
5-10 day holds) -- not parameter variants of them:

  D1_WEEKDAY   A day-of-week effect, redone with a bug fix. Cycle 4's
               B1_DAY_OF_WEEK never got a fair test: "enter Friday close,
               hold 1 day" landed on a spillover stub day (HistData's Friday
               NY close crosses into Saturday UTC, producing a 2-3 bar
               "day"), so every result was killed by the realized-hold guard
               before the economic question was ever asked. This version
               filters DayBars to real trading days (>=12 H1 bars) BEFORE
               indexing, so "next trading day" is genuinely ~24h later.

  W1_BREAKOUT  Weekly N-week high/low breakout, continuation or reversal,
               held 1-2 weeks. Different timeframe (W1, not D1) and
               different lookback (12/26 weeks, not A2's 20 days) from the
               refuted family.

Both use the frozen per-symbol cost model. FAIL-000029 (H1 price patterns)
is not rescued: nothing here operates below a genuine 24h realized hold,
verified the same way Cycle 4 verified it -- from measured bar timestamps,
never a declared parameter.
"""
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars, OBSERVATION_FRACTION
from discovery.cycle4_economics import to_daily, to_weekly, DayBar, stats as d_stats, _materialize
from discovery.cost_model import roundtrip_cost

MIN_TRADES = 30
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_GROSS_OVER_COST = 2.0
MIN_TRADING_DAY_BARS = 12   # filters the Friday->Saturday spillover stub

SYMBOLS = ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]


def gate(tr, va) -> Tuple[str, str]:
    if tr.n < MIN_TRADES:
        return "TRAIN_UNDERPOWERED", f"train n={tr.n} < {MIN_TRADES}"
    if tr.gross_over_cost < MIN_GROSS_OVER_COST:
        return "COST_DOMINATED", f"gross/cost={tr.gross_over_cost} < {MIN_GROSS_OVER_COST}"
    if tr.mean_net <= 0:
        return "TRAIN_NEGATIVE", f"train mean_net={tr.mean_net} <= 0"
    if tr.t_stat < TRAIN_MIN_T:
        return "TRAIN_INSIGNIFICANT", f"train t={tr.t_stat} < {TRAIN_MIN_T}"
    if va.n < MIN_TRADES:
        return "VALIDATION_UNDERPOWERED", f"validation n={va.n} < {MIN_TRADES}"
    if va.mean_net <= 0:
        return "VALIDATION_NEGATIVE", f"validation mean_net={va.mean_net} <= 0"
    if va.t_stat < VAL_MIN_T:
        return "VALIDATION_INSIGNIFICANT", f"validation t={va.t_stat} < {VAL_MIN_T}"
    return "DISCOVERY_SURVIVOR", ""


def real_trading_days(bars) -> List[DayBar]:
    days = to_daily(bars)
    return [d for d in days if d.bars >= MIN_TRADING_DAY_BARS]


# --------------------------------------------------------------- D1 weekday

def sig_weekday_fixed(days: List[DayBar], weekday: int, direction: int) -> List[Tuple[int, int]]:
    """Signal on trading-day index i, exit at trading-day index i+hold --
    both genuine trading days, no calendar-boundary stub possible."""
    return [(i, direction) for i, d in enumerate(days) if d.date.weekday() == weekday]


def sweep_d1_weekday(symbol: str) -> List[Dict]:
    bars = load_dev_bars(R / "data/csv" / f"{symbol}_H1.csv")
    days = real_trading_days(bars)
    cut = int(len(days) * OBSERVATION_FRACTION)
    tr_days, va_days = days[:cut], days[cut:]
    cost = roundtrip_cost(symbol)
    out = []
    for wd in range(5):          # Mon=0..Fri=4
        for direction in (1, -1):
            for hold in (1, 2):
                tr = d_stats(_materialize(tr_days, sig_weekday_fixed(tr_days, wd, direction),
                                          hold, cost), cost)
                va = d_stats(_materialize(va_days, sig_weekday_fixed(va_days, wd, direction),
                                          hold, cost), cost)
                v, reason = gate(tr, va)
                out.append({"family": "D1_WEEKDAY_FIXED", "symbol": symbol,
                            "params": {"weekday": wd, "dir": direction, "hold_days": hold},
                            "train": tr.to_dict(), "validation": va.to_dict(),
                            "verdict": v, "verdict_reason": reason})
    return out


# --------------------------------------------------------------- W1 breakout

def sig_weekly_breakout(weeks: List[DayBar], lookback: int, mode: str) -> List[Tuple[int, int]]:
    out = []
    for i in range(lookback, len(weeks)):
        hi = max(w.high for w in weeks[i - lookback:i])
        lo = min(w.low for w in weeks[i - lookback:i])
        d = 1 if weeks[i].close > hi else (-1 if weeks[i].close < lo else 0)
        if d:
            out.append((i, d if mode == "CONTINUATION" else -d))
    return out


def sweep_w1_breakout(symbol: str) -> List[Dict]:
    bars = load_dev_bars(R / "data/csv" / f"{symbol}_H1.csv")
    days = to_daily(bars)
    weeks = to_weekly(days)
    cut = int(len(weeks) * OBSERVATION_FRACTION)
    tr_w, va_w = weeks[:cut], weeks[cut:]
    cost = roundtrip_cost(symbol)
    out = []
    for lookback in (12, 26):
        for mode in ("CONTINUATION", "REVERSAL"):
            for hold in (1, 2):
                tr = d_stats(_materialize(tr_w, sig_weekly_breakout(tr_w, lookback, mode),
                                          hold, cost), cost)
                va = d_stats(_materialize(va_w, sig_weekly_breakout(va_w, lookback, mode),
                                          hold, cost), cost)
                v, reason = gate(tr, va)
                out.append({"family": "W1_BREAKOUT", "symbol": symbol,
                            "params": {"lookback_weeks": lookback, "mode": mode, "hold_weeks": hold},
                            "train": tr.to_dict(), "validation": va.to_dict(),
                            "verdict": v, "verdict_reason": reason})
    return out


def main() -> int:
    all_results = []
    for sym in SYMBOLS:
        all_results.extend(sweep_d1_weekday(sym))
        all_results.extend(sweep_w1_breakout(sym))

    survivors = [r for r in all_results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    by_family = {}
    for r in all_results:
        by_family.setdefault(r["family"], {})
        by_family[r["family"]][r["verdict"]] = by_family[r["family"]].get(r["verdict"], 0) + 1

    payload = {
        "cycle_id": "CYCLE-07-D1-W1", "stage": "Phase 3 D1/W1 positional",
        "bug_fix_note": ("D1_WEEKDAY_FIXED filters DayBars to >=12 H1 bars before indexing, "
                         "removing the Friday->Saturday spillover stub that killed every "
                         "Cycle 4 B1_DAY_OF_WEEK result via SUB_DAILY_REFUTED_FAMILY before "
                         "the economic question was ever tested."),
        "not_a_rescue_of_fail_29_or_31": ("Every trade here holds >=1 genuine trading day, "
                                          "measured directly from real bar timestamps. Neither "
                                          "family is a parameter variant of the refuted "
                                          "A1_POSITIONAL_STREAK/A2_POSITIONAL_BREAKOUT "
                                          "mechanism (FAIL-000031): D1_WEEKDAY conditions on "
                                          "calendar weekday, not price-streak state; "
                                          "W1_BREAKOUT operates on weekly bars with 12/26-week "
                                          "lookbacks, not A2's 20-day D1 lookback."),
        "parameter_evaluations": len(all_results),
        "survivor_count": len(survivors), "survivors": survivors,
        "family_breakdown": by_family,
        "results": all_results,
    }
    out = R / "reports/factory/discovery_cycles/cycle_07_d1w1.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"CYCLE 7 PHASE 3: {len(all_results)} evaluations, {len(survivors)} DISCOVERY_SURVIVOR")
    for fam in sorted(by_family):
        print(f"  {fam:20s} " + "  ".join(f"{k}={v}" for k, v in sorted(by_family[fam].items())))
    for s in survivors:
        print(f"  SURVIVOR {s['family']} {s['symbol']} {s['params']} "
              f"train t={s['train']['t_stat']} val t={s['validation']['t_stat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
