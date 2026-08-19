"""
GEN 7 CYCLE 2: horizon-expansion discovery across structurally distinct
families (Phases 2-8 of the Cycle-2 directive).

Research question: does the same/related market structure become
economically tradable when holding horizon is extended so fixed transaction
cost is a smaller fraction of expected movement?

Design:
  - Signal generators are horizon-independent: each returns a list of
    (entry_index, direction) events computed once per structural parameter
    set.
  - A generic materializer turns (events, horizon) -> List[Trade] using the
    SAME fixed roundtrip cost regardless of horizon (cost is per round-trip,
    not per bar -- extending the hold does not multiply cost).
  - Every (family, structural_params, horizon) combination is one entry in
    the multiple-testing ledger, pass or fail.

Families (see module docstring per function for the specific mechanism):
  A. STREAK_REVERSAL_MULTIBAR      -- multi-bar streak exhaustion, vol-gated
  B. GAP_MAGNITUDE_STRUCTURE       -- weekend gap fade vs continuation, by size
  C. VOLATILITY_TRANSITION         -- compression breakout; shock momentum/reversal
  D. BREAKOUT_STRUCTURE            -- N-bar range breakout, continuation vs reversal
  E. MULTITIMEFRAME_TREND_FILTER   -- D1-trend-aligned vs counter-trend streak fade

HORIZONS swept (bars): 2, 4, 8, 12, 24, 48, 72, 120, 240
"""

import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from discovery.observatory import Bar, load_dev_bars, OBSERVATION_FRACTION
from discovery.evaluation import ROUNDTRIP_COST, Trade, _rets, _rolling_vol

HORIZONS = (2, 4, 8, 12, 24, 48, 72, 120, 240)

TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_TRADES = 30


# ---------------------------------------------------------------------------
# Generic materializer + full stats (extends evaluation._stats with the
# additional metrics Phase 2 requires: volatility, sharpe, sortino, drawdown,
# cost efficiency, turnover)
# ---------------------------------------------------------------------------

@dataclass
class FullStats:
    n: int
    gross_expectancy: float
    mean_net: float
    net_std: float
    t_stat: float
    profit_factor: float
    win_rate: float
    cost: float
    cost_efficiency: float          # |gross_expectancy| / cost
    turnover: float                 # n / bars_in_window
    sharpe: float                   # mean_net / net_std (per-trade, non-annualized)
    sortino: float
    max_drawdown: float

    def to_dict(self) -> Dict:
        return asdict(self)


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def full_stats(trades: List[Trade], bars_in_window: int,
               cost: float = ROUNDTRIP_COST) -> FullStats:
    if not trades:
        return FullStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, cost, 0.0, 0.0, 0.0, 0.0, 0.0)
    gross = [t.gross for t in trades]
    nets = [t.net for t in trades]
    n = len(nets)
    mean_gross = sum(gross) / n
    mean_net = sum(nets) / n
    sd = _std(nets)
    t_stat = mean_net / (sd / math.sqrt(n)) if sd > 0 and n > 1 else 0.0
    gains = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    wr = sum(1 for x in nets if x > 0) / n
    cost_eff = abs(mean_gross) / cost if cost > 0 else 0.0
    turnover = n / bars_in_window if bars_in_window else 0.0
    sharpe = mean_net / sd if sd > 0 else 0.0
    downside = [x for x in nets if x < 0]
    down_sd = _std(downside) if len(downside) >= 2 else (abs(downside[0]) if downside else 0.0)
    sortino = mean_net / down_sd if down_sd > 0 else (999.0 if mean_net > 0 else 0.0)
    # equity curve in entry-time order (already ordered by construction)
    equity, peak, mdd = 0.0, 0.0, 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return FullStats(n, round(mean_gross, 7), round(mean_net, 7), round(sd, 7),
                     round(t_stat, 3), round(pf, 3), round(wr, 4), cost,
                     round(cost_eff, 3), round(turnover, 5), round(sharpe, 4),
                     round(sortino, 4), round(mdd, 6))


def materialize(events: List[Tuple[int, int]], bars: List[Bar], horizon: int,
                cost: float = ROUNDTRIP_COST) -> List[Trade]:
    """events: list of (entry_idx, direction). Non-overlapping: an event
    inside another trade's holding window is skipped (positional
    accumulation semantics -- one cost per swing, not one per signal)."""
    trades: List[Trade] = []
    blocked_until = -1
    for idx, direction in events:
        if idx <= blocked_until:
            continue
        if idx + horizon >= len(bars):
            continue
        gross = direction * math.log(bars[idx + horizon].close / bars[idx].close)
        trades.append(Trade(bars[idx].ts.isoformat(), direction, round(gross, 7),
                            round(gross - cost, 7), horizon, bars[idx].ts.hour))
        blocked_until = idx + horizon
    return trades


# ---------------------------------------------------------------------------
# FAMILY A: STREAK_REVERSAL_MULTIBAR
# ---------------------------------------------------------------------------

def signals_streak_reversal(bars: List[Bar], k: int, vol_gated: bool = False) -> List[Tuple[int, int]]:
    rets = _rets(bars)
    vols = _rolling_vol(rets) if vol_gated else None
    med = None
    if vol_gated:
        vals = sorted(v for v in vols if v is not None)
        med = vals[len(vals) // 2] if vals else None
    events = []
    run_dir, run_len = 0, 0
    for i, r in enumerate(rets):
        d = 1 if r > 0 else (-1 if r < 0 else 0)
        run_len = run_len + 1 if (d == run_dir and d != 0) else (1 if d != 0 else 0)
        run_dir = d
        if run_len >= k and d != 0:
            if vol_gated and (med is None or vols[i] is None or vols[i] <= med):
                continue
            entry_idx = i + 1
            if entry_idx < len(bars):
                events.append((entry_idx, -d))
            run_dir, run_len = 0, 0
    return events


# ---------------------------------------------------------------------------
# FAMILY B: GAP_MAGNITUDE_STRUCTURE
# ---------------------------------------------------------------------------

def signals_gap_structure(bars: List[Bar], min_pips: float, max_pips: Optional[float],
                          mode: str) -> List[Tuple[int, int]]:
    """mode: 'FADE' (toward Friday close) or 'CONTINUATION' (with the gap)."""
    events = []
    for i in range(1, len(bars) - 1):
        prev, cur = bars[i - 1], bars[i]
        if (cur.ts - prev.ts).total_seconds() < 40 * 3600:
            continue
        gap = cur.open - prev.close
        gap_pips = abs(gap) / prev.close * 1e4
        if gap == 0 or gap_pips < min_pips:
            continue
        if max_pips is not None and gap_pips >= max_pips:
            continue
        direction = (-1 if gap > 0 else 1) if mode == "FADE" else (1 if gap > 0 else -1)
        events.append((i, direction))
    return events


# ---------------------------------------------------------------------------
# FAMILY C: VOLATILITY_TRANSITION
# ---------------------------------------------------------------------------

def signals_compression_breakout(bars: List[Bar], lookback: int = 7) -> List[Tuple[int, int]]:
    events = []
    for i in range(lookback, len(bars) - 1):
        recent = [(b.high - b.low) for b in bars[i - lookback:i + 1]]
        cur = bars[i]
        if (cur.high - cur.low) == min(recent) and (cur.high - cur.low) > 0:
            nxt = bars[i + 1]
            direction = 1 if nxt.close > cur.close else (-1 if nxt.close < cur.close else 0)
            if direction != 0:
                events.append((i + 1, direction))
    return events


def signals_shock(bars: List[Bar], z_thr: float, mode: str, vol_win: int = 20) -> List[Tuple[int, int]]:
    """mode: 'MOMENTUM' (with the shock) or 'REVERSAL' (against it)."""
    rets = _rets(bars)
    events = []
    for i in range(vol_win, len(rets)):
        sd = _std(rets[i - vol_win:i])
        if sd == 0:
            continue
        z = rets[i] / sd
        if abs(z) >= z_thr:
            entry_idx = i + 1
            if entry_idx < len(bars):
                sign = 1 if z > 0 else -1
                direction = sign if mode == "MOMENTUM" else -sign
                events.append((entry_idx, direction))
    return events


# ---------------------------------------------------------------------------
# FAMILY D: BREAKOUT_STRUCTURE
# ---------------------------------------------------------------------------

def signals_breakout(bars: List[Bar], lookback: int, mode: str) -> List[Tuple[int, int]]:
    """mode: 'CONTINUATION' or 'REVERSAL' of the breakout direction."""
    events = []
    for i in range(lookback, len(bars) - 1):
        hh = max(b.high for b in bars[i - lookback:i])
        ll = min(b.low for b in bars[i - lookback:i])
        cur = bars[i]
        raw_dir = 0
        if cur.close > hh:
            raw_dir = 1
        elif cur.close < ll:
            raw_dir = -1
        if raw_dir == 0:
            continue
        direction = raw_dir if mode == "CONTINUATION" else -raw_dir
        events.append((i, direction))
    return events


# ---------------------------------------------------------------------------
# FAMILY E: MULTITIMEFRAME_TREND_FILTER
# ---------------------------------------------------------------------------

def _d1_trend_direction(bars: List[Bar], i: int, d1_bars: int = 24) -> int:
    if i < d1_bars:
        return 0
    seg = bars[i - d1_bars:i]
    return 1 if seg[-1].close > seg[0].close else (-1 if seg[-1].close < seg[0].close else 0)


def signals_mtf_streak(bars: List[Bar], k: int, align: str) -> List[Tuple[int, int]]:
    """align: 'WITH_TREND' (fade direction agrees with D1 trend) or
    'AGAINST_TREND' (counter-trend fade)."""
    base = signals_streak_reversal(bars, k, vol_gated=False)
    events = []
    for idx, direction in base:
        trend = _d1_trend_direction(bars, idx)
        if trend == 0:
            continue
        agrees = (direction == trend)
        if (align == "WITH_TREND" and agrees) or (align == "AGAINST_TREND" and not agrees):
            events.append((idx, direction))
    return events


# ---------------------------------------------------------------------------
# Registry of (family, structural params, signal function)
# ---------------------------------------------------------------------------

def build_family_registry() -> List[Dict]:
    reg = []
    for k in (2, 3, 4, 6):
        reg.append({"family": "STREAK_REVERSAL_MULTIBAR", "params": {"k": k, "vol_gated": False},
                   "fn": lambda bars, k=k: signals_streak_reversal(bars, k, False)})
        reg.append({"family": "STREAK_REVERSAL_MULTIBAR", "params": {"k": k, "vol_gated": True},
                   "fn": lambda bars, k=k: signals_streak_reversal(bars, k, True)})
    for mode in ("FADE", "CONTINUATION"):
        for lo, hi, label in ((3, 8, "SMALL"), (8, 15, "MEDIUM"), (15, None, "LARGE")):
            reg.append({"family": "GAP_MAGNITUDE_STRUCTURE",
                       "params": {"mode": mode, "bucket": label, "min_pips": lo, "max_pips": hi},
                       "fn": lambda bars, lo=lo, hi=hi, mode=mode: signals_gap_structure(bars, lo, hi, mode)})
    reg.append({"family": "VOLATILITY_TRANSITION", "params": {"mechanism": "COMPRESSION_BREAKOUT", "lookback": 7},
               "fn": lambda bars: signals_compression_breakout(bars, 7)})
    for z in (2.0, 3.0):
        for mode in ("MOMENTUM", "REVERSAL"):
            reg.append({"family": "VOLATILITY_TRANSITION",
                       "params": {"mechanism": "SHOCK", "z_threshold": z, "mode": mode},
                       "fn": lambda bars, z=z, mode=mode: signals_shock(bars, z, mode)})
    for lb in (10, 20, 40):
        for mode in ("CONTINUATION", "REVERSAL"):
            reg.append({"family": "BREAKOUT_STRUCTURE", "params": {"lookback": lb, "mode": mode},
                       "fn": lambda bars, lb=lb, mode=mode: signals_breakout(bars, lb, mode)})
    for align in ("WITH_TREND", "AGAINST_TREND"):
        reg.append({"family": "MULTITIMEFRAME_TREND_FILTER", "params": {"k": 3, "align": align},
                   "fn": lambda bars, align=align: signals_mtf_streak(bars, 3, align)})
    return reg


# ---------------------------------------------------------------------------
# Sweep runner
# ---------------------------------------------------------------------------

def run_sweep(train: List[Bar], val: List[Bar]) -> List[Dict]:
    registry = build_family_registry()
    results = []
    for entry in registry:
        family, params, fn = entry["family"], entry["params"], entry["fn"]
        train_events = fn(train)
        val_events = fn(val)
        for horizon in HORIZONS:
            train_trades = materialize(train_events, train, horizon)
            train_stats = full_stats(train_trades, len(train))
            row = {
                "family": family, "params": dict(params, horizon=horizon),
                "train": train_stats.to_dict(),
            }
            row["gate"] = _classify_train(train_stats)
            if row["gate"] == "PASS_TRAIN":
                val_trades = materialize(val_events, val, horizon)
                val_stats = full_stats(val_trades, len(val))
                row["validation"] = val_stats.to_dict()
                row["gate"] = _classify_val(val_stats)
            results.append(row)
    return results


def _classify_train(s: FullStats) -> str:
    if s.n < MIN_TRADES:
        return "KILLED_INSUFFICIENT_SAMPLE"
    if s.mean_net <= 0:
        if s.gross_expectancy > 0:
            return "ECONOMICALLY_UNTRADABLE"
        return "KILLED_NEGATIVE_EXPECTANCY"
    if s.cost_efficiency < 1.0:
        return "KILLED_COST_DOMINATED"
    if s.t_stat < TRAIN_MIN_T:
        return "KILLED_UNDERPOWERED"
    return "PASS_TRAIN"


def _classify_val(s: FullStats) -> str:
    if s.n < MIN_TRADES:
        return "VAL_INSUFFICIENT_SAMPLE"
    if s.mean_net <= 0:
        return "VAL_FAIL_NEGATIVE"
    if s.t_stat < VAL_MIN_T:
        return "VAL_FAIL_UNDERPOWERED"
    return "PASS_TRAIN_AND_VAL"


def main() -> int:
    bars = load_dev_bars()
    cut = int(len(bars) * OBSERVATION_FRACTION)
    train, val = bars[:cut], bars[cut:]
    results = run_sweep(train, val)
    passed = [r for r in results if r["gate"] == "PASS_TRAIN_AND_VAL"]
    print(f"CYCLE 2 SWEEP: {len(results)} (family,params,horizon) evaluations, "
          f"{len(passed)} pass train+validation")
    for r in passed:
        print(f"  {r['family']} {r['params']}  "
              f"train_net={r['train']['mean_net']:+.6f} val_net={r['validation']['mean_net']:+.6f}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
