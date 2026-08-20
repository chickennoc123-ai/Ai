"""
GEN 7 CYCLE 4 -- economic-structure discovery.

FAIL-000029 eliminated the H1 intrabar price-pattern search space: every
pattern found is smaller than the round-trip cost on every instrument tested.
Cycle 4 therefore changes the ECONOMICS, not the sample. Nothing here holds a
position for less than one calendar day, and no family is an H1 price model.

Families (all NEW; none is a parameter variant of a refuted family):

  A1 POSITIONAL_STREAK      D1 k-day run, faded or followed, held 5-10 days
  A2 POSITIONAL_BREAKOUT    D1 20-day range break, continuation or reversal
  B1 DAY_OF_WEEK            weekday close -> next close, both directions
  B2 TURN_OF_MONTH          month-boundary window, both directions
  B3 QUARTER_TURN           quarter-boundary drift, held 5-10 days
  C1 NFP_CALENDAR_PROXY     first Friday of month (NFP release day), faded or
                            followed. Calendar-derived: no external event feed
                            is used, so FOMC/CPI are OUT OF SCOPE this cycle.
  E1 CROSS_ASSET_CONVERGENCE  z-scored spread between two instruments, traded
                            back toward its mean, held 3-5 days, TWO legs of
                            cost charged.

The grid below is PRE-REGISTERED: it is fixed before any evaluation runs and
is not extended after seeing results. Cost is the frozen per-symbol relative
round trip. Determinism: no randomness anywhere.
"""

import json
import math
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar, load_dev_bars, OBSERVATION_FRACTION
from discovery.cost_model import roundtrip_cost, cost_table, COST_MODEL_ID

SYMBOLS = ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]

# ---- pre-registered economic filter (Cycle 4; stricter than Cycles 1-3) ----
MIN_TRADES = 30
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_GROSS_OVER_COST = 2.0     # NEW in Cycle 4: must cover cost twice over
MIN_HOLDING_HOURS = 24        # structural guard against H1 price models

# ---- pre-registered parameter grid ----
GRID = {
    "A1": {"k": [2, 3], "mode": ["FADE", "FOLLOW"], "hold": [5, 10]},
    "A2": {"lookback": [20], "mode": ["CONT", "REV"], "hold": [5, 10]},
    "B1": {"weekday": [0, 1, 2, 3, 4], "dir": [1, -1]},
    "B2": {"window": [(1, 1), (2, 3)], "dir": [1, -1]},
    "B3": {"dir": [1, -1], "hold": [5, 10]},
    "C1": {"mode": ["FADE", "FOLLOW"], "hold": [1, 3, 5]},
    "E1": {"lookback": [60], "threshold": [2.0], "hold": [3, 5]},
}
CROSS_PAIRS = [("XAUUSD", "USDCHF"), ("EURUSD", "GBPUSD"), ("USDCHF", "EURUSD"),
               ("USDJPY", "USDCHF"), ("USDCAD", "XAUUSD")]


# ---------------------------------------------------------------- structures

@dataclass
class DayBar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    bars: int
    last_ts: datetime          # timestamp of the final H1 bar in this day


@dataclass
class PosTrade:
    entry: str
    direction: int
    gross: float
    net: float
    hold_days: int
    realized_hours: float      # measured from real bar timestamps, not assumed


@dataclass
class Stats:
    n: int
    gross_mean: float
    mean_net: float
    t_stat: float
    profit_factor: float
    win_rate: float
    gross_over_cost: float
    median_hold_hours: float

    def to_dict(self) -> Dict:
        return asdict(self)


def stats(trades: List[PosTrade], cost: float) -> Stats:
    if not trades:
        return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    nets = [t.net for t in trades]
    grosses = [abs(t.gross) for t in trades]
    n = len(nets)
    mean = sum(nets) / n
    if n > 1:
        var = sum((x - mean) ** 2 for x in nets) / (n - 1)
        t = mean / math.sqrt(var / n) if var > 0 else 0.0
    else:
        t = 0.0
    gains = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    gm = sum(grosses) / n
    hrs = sorted(t_.realized_hours for t_ in trades)
    med = hrs[n // 2]
    return Stats(n, round(gm, 8), round(mean, 8), round(t, 3), round(pf, 3),
                 round(sum(1 for x in nets if x > 0) / n, 4),
                 round(gm / cost, 3) if cost else 0.0, round(med, 1))


# ------------------------------------------------------------- resampling

def to_daily(bars: List[Bar]) -> List[DayBar]:
    """UTC calendar-day OHLC from H1 bars. Deterministic, no gaps invented."""
    out: List[DayBar] = []
    cur_key = None
    o = h = l = c = None
    cnt = 0
    last = None
    for b in bars:
        key = b.ts.date()
        if key != cur_key:
            if cur_key is not None:
                out.append(DayBar(datetime(cur_key.year, cur_key.month, cur_key.day),
                                  o, h, l, c, cnt, last))
            cur_key, o, h, l, c, cnt = key, b.open, b.high, b.low, b.close, 1
        else:
            h, l, c, cnt = max(h, b.high), min(l, b.low), b.close, cnt + 1
        last = b.ts
    if cur_key is not None:
        out.append(DayBar(datetime(cur_key.year, cur_key.month, cur_key.day),
                          o, h, l, c, cnt, last))
    return out


# ------------------------------------------------------------ trade builder

def _materialize(days: List[DayBar], entries: List[Tuple[int, int]],
                 hold: int, cost: float) -> List[PosTrade]:
    """
    entries: (index_of_signal_day, direction). Positions are NON-OVERLAPPING:
    once a trade opens, later signals are ignored until it closes. Exactly one
    round-trip cost is charged per trade regardless of holding length -- that
    amortization is the entire economic premise of this cycle.
    """
    trades: List[PosTrade] = []
    busy_until = -1
    for i, direction in entries:
        if i <= busy_until:
            continue
        j = i + hold
        if j >= len(days):
            break
        gross = direction * math.log(days[j].close / days[i].close)
        realized = (days[j].last_ts - days[i].last_ts).total_seconds() / 3600.0
        trades.append(PosTrade(days[i].date.isoformat(), direction,
                               round(gross, 8), round(gross - cost, 8), hold,
                               round(realized, 2)))
        busy_until = j
    return trades


# --------------------------------------------------------------- families

def sig_A1_streak(days: List[DayBar], k: int, mode: str) -> List[Tuple[int, int]]:
    out, run_dir, run_len = [], 0, 0
    for i in range(1, len(days)):
        d = 1 if days[i].close > days[i - 1].close else (-1 if days[i].close < days[i - 1].close else 0)
        if d == run_dir and d != 0:
            run_len += 1
        else:
            run_dir, run_len = d, (1 if d else 0)
        if run_len >= k and d != 0:
            out.append((i, -d if mode == "FADE" else d))
    return out


def sig_A2_breakout(days: List[DayBar], lookback: int, mode: str) -> List[Tuple[int, int]]:
    out = []
    for i in range(lookback, len(days)):
        hi = max(d.high for d in days[i - lookback:i])
        lo = min(d.low for d in days[i - lookback:i])
        d = 1 if days[i].close > hi else (-1 if days[i].close < lo else 0)
        if d:
            out.append((i, d if mode == "CONT" else -d))
    return out


def sig_B1_weekday(days: List[DayBar], weekday: int, direction: int) -> List[Tuple[int, int]]:
    return [(i, direction) for i in range(len(days)) if days[i].date.weekday() == weekday]


def sig_B2_turn_of_month(days: List[DayBar], window: Tuple[int, int],
                         direction: int) -> List[Tuple[int, int]]:
    """Enter `pre` trading days before month end; the caller holds pre+post days."""
    pre, _post = window
    out = []
    for i in range(len(days) - 1):
        if days[i + 1].date.month != days[i].date.month:      # last day of month
            j = i - pre + 1
            if j >= 0:
                out.append((j, direction))
    return out


def sig_B3_quarter(days: List[DayBar], direction: int) -> List[Tuple[int, int]]:
    out = []
    for i in range(1, len(days)):
        m, pm = days[i].date.month, days[i - 1].date.month
        if m != pm and m in (1, 4, 7, 10):
            out.append((i, direction))
    return out


def sig_C1_nfp(days: List[DayBar], mode: str) -> List[Tuple[int, int]]:
    """First Friday of each month -- the NFP release day (calendar-derived)."""
    seen = set()
    out = []
    for i in range(1, len(days)):
        d = days[i].date
        if d.weekday() == 4 and d.day <= 7 and (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            move = 1 if days[i].close > days[i - 1].close else -1
            out.append((i, -move if mode == "FADE" else move))
    return out


def sig_E1_convergence(a: List[DayBar], b: List[DayBar], lookback: int,
                       threshold: float) -> List[Tuple[int, int]]:
    """
    z-score of (log a - log b) over `lookback` days. z above +threshold means A
    is rich relative to B: short A (and long B) expecting convergence.
    """
    out = []
    for i in range(lookback, len(a)):
        spread = [math.log(a[j].close) - math.log(b[j].close) for j in range(i - lookback, i)]
        m = sum(spread) / lookback
        var = sum((x - m) ** 2 for x in spread) / (lookback - 1)
        sd = math.sqrt(var)
        if sd == 0:
            continue
        z = ((math.log(a[i].close) - math.log(b[i].close)) - m) / sd
        if z >= threshold:
            out.append((i, -1))
        elif z <= -threshold:
            out.append((i, 1))
    return out


def to_weekly(days: List[DayBar]) -> List[DayBar]:
    """
    ISO-week resample from DayBar list. No new data source required -- this
    is a pure resampling of the H1 data already in data/csv/.
    """
    out: List[DayBar] = []
    cur_key = None
    o = h = l = c = None
    cnt = 0
    last = None
    week_start = None
    for d in days:
        key = d.date.isocalendar()[:2]   # (iso_year, iso_week)
        if key != cur_key:
            if cur_key is not None:
                out.append(DayBar(week_start, o, h, l, c, cnt, last))
            cur_key, week_start = key, d.date
            o, h, l, c, cnt = d.open, d.high, d.low, d.close, d.bars
        else:
            h, l, c = max(h, d.high), min(l, d.low), d.close
            cnt += d.bars
        last = d.last_ts
    if cur_key is not None:
        out.append(DayBar(week_start, o, h, l, c, cnt, last))
    return out


# ----------------------------------------------------------------- sweep

def _gate(tr: Stats, va: Stats) -> Tuple[str, str]:
    """Pre-registered Cycle 4 economic filter. Never relaxed."""
    if tr.n and tr.median_hold_hours < MIN_HOLDING_HOURS:
        return "SUB_DAILY_REFUTED_FAMILY", (
            f"median realized hold {tr.median_hold_hours}h < {MIN_HOLDING_HOURS}h; "
            f"this is an H1-scale trade, which FAIL-000029 refuted")
    if tr.n < MIN_TRADES:
        return "TRAIN_UNDERPOWERED", f"train n={tr.n} < {MIN_TRADES}"
    if tr.gross_over_cost < MIN_GROSS_OVER_COST:
        return "COST_DOMINATED", (f"gross/cost={tr.gross_over_cost} < {MIN_GROSS_OVER_COST}")
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


def _evaluate(family: str, params: Dict, symbol: str, hold: int,
              tr_days: List[DayBar], va_days: List[DayBar],
              sig_fn, cost: float, min_hold_hours: int) -> Dict:
    tr = stats(_materialize(tr_days, sig_fn(tr_days), hold, cost), cost)
    va = stats(_materialize(va_days, sig_fn(va_days), hold, cost), cost)
    verdict, reason = _gate(tr, va)
    return {"family": family, "symbol": symbol, "params": {**params, "hold_days": hold},
            "declared_holding_hours": min_hold_hours,
            "measured_median_hold_hours": tr.median_hold_hours,
            "train": tr.to_dict(), "validation": va.to_dict(),
            "verdict": verdict, "verdict_reason": reason}


def sweep_symbol(symbol: str) -> Tuple[List[Dict], List[DayBar]]:
    bars = load_dev_bars(REPO_ROOT / "data/csv" / f"{symbol}_H1.csv")
    days = to_daily(bars)
    cut = int(len(days) * OBSERVATION_FRACTION)
    tr_d, va_d = days[:cut], days[cut:]
    cost = roundtrip_cost(symbol)
    res: List[Dict] = []

    g = GRID["A1"]
    for k in g["k"]:
        for mode in g["mode"]:
            for hold in g["hold"]:
                res.append(_evaluate("A1_POSITIONAL_STREAK", {"k": k, "mode": mode},
                                     symbol, hold, tr_d, va_d,
                                     lambda d, k=k, mode=mode: sig_A1_streak(d, k, mode),
                                     cost, hold * 24))
    g = GRID["A2"]
    for lb in g["lookback"]:
        for mode in g["mode"]:
            for hold in g["hold"]:
                res.append(_evaluate("A2_POSITIONAL_BREAKOUT", {"lookback": lb, "mode": mode},
                                     symbol, hold, tr_d, va_d,
                                     lambda d, lb=lb, mode=mode: sig_A2_breakout(d, lb, mode),
                                     cost, hold * 24))
    g = GRID["B1"]
    for wd in g["weekday"]:
        for dr in g["dir"]:
            res.append(_evaluate("B1_DAY_OF_WEEK", {"weekday": wd, "dir": dr},
                                 symbol, 1, tr_d, va_d,
                                 lambda d, wd=wd, dr=dr: sig_B1_weekday(d, wd, dr),
                                 cost, 24))
    g = GRID["B2"]
    for win in g["window"]:
        for dr in g["dir"]:
            hold = win[0] + win[1]
            res.append(_evaluate("B2_TURN_OF_MONTH", {"window": list(win), "dir": dr},
                                 symbol, hold, tr_d, va_d,
                                 lambda d, win=win, dr=dr: sig_B2_turn_of_month(d, win, dr),
                                 cost, hold * 24))
    g = GRID["B3"]
    for dr in g["dir"]:
        for hold in g["hold"]:
            res.append(_evaluate("B3_QUARTER_TURN", {"dir": dr}, symbol, hold, tr_d, va_d,
                                 lambda d, dr=dr: sig_B3_quarter(d, dr), cost, hold * 24))
    g = GRID["C1"]
    for mode in g["mode"]:
        for hold in g["hold"]:
            res.append(_evaluate("C1_NFP_CALENDAR_PROXY", {"mode": mode}, symbol, hold,
                                 tr_d, va_d, lambda d, mode=mode: sig_C1_nfp(d, mode),
                                 cost, hold * 24))
    return res, days


def sweep_cross_asset(daily: Dict[str, List[DayBar]]) -> List[Dict]:
    """E1: two-legged convergence trades. BOTH legs are charged round-trip cost."""
    out: List[Dict] = []
    g = GRID["E1"]
    for a_sym, b_sym in CROSS_PAIRS:
        da, db = daily[a_sym], daily[b_sym]
        common = sorted(set(x.date for x in da) & set(x.date for x in db))
        idx = {d: i for i, d in enumerate(common)}
        A = [x for x in da if x.date in idx]
        B = [x for x in db if x.date in idx]
        n = min(len(A), len(B))
        A, B = A[:n], B[:n]
        cut = int(n * OBSERVATION_FRACTION)
        cost = roundtrip_cost(a_sym) + roundtrip_cost(b_sym)   # two legs
        for lb in g["lookback"]:
            for thr in g["threshold"]:
                # signals use a trailing window only, so they are computed once
                # on the aligned series and then split by index.
                sigs = sig_E1_convergence(A, B, lb, thr)
                tr_sigs = [(i, d) for i, d in sigs if i < cut]
                va_sigs = [(i - cut, d) for i, d in sigs if i >= cut]
                for hold in g["hold"]:
                    tr = stats(_materialize(A[:cut], tr_sigs, hold, cost), cost)
                    va = stats(_materialize(A[cut:], va_sigs, hold, cost), cost)
                    verdict, reason = _gate(tr, va)
                    out.append({"family": "E1_CROSS_ASSET_CONVERGENCE",
                                "symbol": f"{a_sym}/{b_sym}",
                                "params": {"lookback": lb, "threshold": thr,
                                           "hold_days": hold, "legs": 2},
                                "declared_holding_hours": hold * 24,
                                "measured_median_hold_hours": tr.median_hold_hours,
                                "train": tr.to_dict(), "validation": va.to_dict(),
                                "verdict": verdict, "verdict_reason": reason})
    return out


def main() -> int:
    daily: Dict[str, List[DayBar]] = {}
    results: List[Dict] = []
    for s in SYMBOLS:
        r, d = sweep_symbol(s)
        results.extend(r)
        daily[s] = d
    results.extend(sweep_cross_asset(daily))

    survivors = [r for r in results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    by_verdict: Dict[str, int] = {}
    by_family: Dict[str, Dict[str, int]] = {}
    for r in results:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
        f = by_family.setdefault(r["family"], {})
        f[r["verdict"]] = f.get(r["verdict"], 0) + 1

    payload = {
        "cycle_id": "CYCLE-4-ECONOMIC-STRUCTURE",
        "stage": "GEN 7 discovery + GEN 9-11 internal evaluation (development data only)",
        "refuted_space_avoided": "FAMILY-H1-PRICE-PATTERN (FAIL-000029)",
        "cost_model_id": COST_MODEL_ID,
        "cost_table": cost_table(),
        "economic_filter": {"min_trades": MIN_TRADES, "train_min_t": TRAIN_MIN_T,
                            "val_min_t": VAL_MIN_T,
                            "min_gross_over_cost": MIN_GROSS_OVER_COST,
                            "min_holding_hours": MIN_HOLDING_HOURS},
        "preregistered_grid": {k: {kk: (vv if not isinstance(vv[0], tuple) else
                                        [list(x) for x in vv])
                                   for kk, vv in v.items()} for k, v in GRID.items()},
        "cross_pairs": [list(p) for p in CROSS_PAIRS],
        "parameter_evaluations": len(results),
        "survivor_count": len(survivors),
        "survivors": survivors,
        "verdict_distribution": by_verdict,
        "family_breakdown": by_family,
        "results": results,
    }
    out = REPO_ROOT / "reports/factory/discovery_cycles/cycle_04_economic_sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"CYCLE 4: {len(results)} parameter evaluations, "
          f"{len(survivors)} DISCOVERY_SURVIVOR")
    for fam in sorted(by_family):
        row = by_family[fam]
        print(f"  {fam:28s} " + "  ".join(f"{k}={v}" for k, v in sorted(row.items())))
    print("  verdicts: " + "  ".join(f"{k}={v}" for k, v in sorted(by_verdict.items())))
    for s in survivors:
        print(f"  SURVIVOR {s['family']} {s['symbol']} {s['params']} "
              f"train t={s['train']['t_stat']} val t={s['validation']['t_stat']} "
              f"g/c={s['train']['gross_over_cost']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
