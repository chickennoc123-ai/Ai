"""
GEN 9-11 OPERATIONAL CORE: hypothesis evaluation with internal validation.

Executes the proposed_test spec of every queued GEN 7 hypothesis:

  TRAIN               = observation window (first 80% of dev bars)
  INTERNAL VALIDATION = reserved last 20% of dev bars (2020-04..2022-03),
                        untouched by GEN 8 and GEN 7

Frozen semantics (not tunable at runtime):
  - H1 close-to-close execution; entry at signal-bar close
  - roundtrip cost 1.1 pips subtracted from every trade
  - early rejection: TRAIN needs net>0 and t>=2.0; VALIDATION needs net>0,
    t>=1.5 and n>=30 -- thresholds pre-registered here
  - GEN 11: survivors get a regime breakdown (vol terciles + session blocks,
    minimum 100 trades per cell to claim anything)

The sealed holdout is NEVER touched here (loader guard).
Determinism: no randomness anywhere.
"""

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from discovery.observatory import Bar, load_dev_bars, OBSERVATION_FRACTION

DEFAULT_QUEUE = Path("reports/factory/discovery_queue.json")
DEFAULT_OUT = Path("reports/factory/hypothesis_evaluation.json")

ROUNDTRIP_COST = 0.00011      # 1.1 pips, frozen (GEN 4/5 cost model)
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
VAL_MIN_TRADES = 30


@dataclass
class Trade:
    ts: str
    direction: int            # +1 long, -1 short
    gross: float              # price-relative return, signed by direction
    net: float
    bars_held: int
    hour: int
    vol_regime: str = ""


@dataclass
class EvalStats:
    n: int
    mean_net: float
    t_stat: float
    profit_factor: float
    win_rate: float
    total_net: float

    def to_dict(self) -> Dict:
        return asdict(self)


def _stats(trades: List[Trade]) -> EvalStats:
    if not trades:
        return EvalStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    nets = [t.net for t in trades]
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
    wr = sum(1 for x in nets if x > 0) / n
    return EvalStats(n, round(mean, 7), round(t, 3), round(pf, 3),
                     round(wr, 4), round(sum(nets), 6))


def _rets(bars: List[Bar]) -> List[float]:
    return [math.log(bars[i + 1].close / bars[i].close) for i in range(len(bars) - 1)]


def _rolling_vol(rets: List[float], win: int = 50) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(rets)
    for i in range(win, len(rets)):
        seg = rets[i - win:i]
        m = sum(seg) / win
        out[i] = math.sqrt(sum((x - m) ** 2 for x in seg) / (win - 1))
    return out


# ---------------------------------------------------------------------------
# Executors: one per proposed_test family. Each returns a list of Trades.
# ---------------------------------------------------------------------------

def exec_streak_fade(bars: List[Bar], k: int,
                     hours: Optional[range] = None,
                     vol_above_median: bool = False,
                     cost: float = ROUNDTRIP_COST,
                     delay: int = 0,
                     horizon: int = 1) -> List[Trade]:
    rets = _rets(bars)
    vols = _rolling_vol(rets) if vol_above_median else None
    med = None
    if vol_above_median:
        vals = sorted(v for v in vols if v is not None)
        med = vals[len(vals) // 2] if vals else None
    trades: List[Trade] = []
    run_dir, run_len = 0, 0
    for i in range(len(rets) - 1 - delay):
        r = rets[i]
        d = 1 if r > 0 else (-1 if r < 0 else 0)
        if d == run_dir and d != 0:
            run_len += 1
        else:
            run_dir, run_len = d, (1 if d != 0 else 0)
        if run_len >= k and d != 0:
            sig_bar = bars[i + 1]                       # bar whose close is entry
            if hours is not None and sig_bar.ts.hour not in hours:
                continue
            if vol_above_median and (med is None or vols[i] is None or vols[i] <= med):
                continue
            entry_idx = i + 1 + delay
            if entry_idx + horizon >= len(bars):
                continue
            direction = -d                              # fade the streak
            gross = direction * math.log(bars[entry_idx + horizon].close
                                         / bars[entry_idx].close)
            trades.append(Trade(bars[entry_idx].ts.isoformat(), direction,
                                round(gross, 7), round(gross - cost, 7), horizon,
                                bars[entry_idx].ts.hour))
            run_dir, run_len = 0, 0                     # one trade per streak
    return trades


def exec_weekend_gap_fade(bars: List[Bar], max_hold: int = 24,
                          cost: float = ROUNDTRIP_COST,
                          delay: int = 0,
                          min_gap: float = 0.0) -> List[Trade]:
    trades: List[Trade] = []
    for i in range(1, len(bars) - 1):
        prev, cur = bars[i - 1], bars[i]
        if (cur.ts - prev.ts).total_seconds() < 40 * 3600:
            continue
        gap = cur.open - prev.close
        if gap == 0 or abs(gap) / prev.close < min_gap:
            continue
        entry_idx = i + delay
        if entry_idx + 1 >= len(bars):
            continue
        direction = -1 if gap > 0 else 1                # fade toward Friday close
        entry_px = bars[entry_idx].close
        target = prev.close
        exit_px, held = None, 0
        for j in range(entry_idx + 1, min(entry_idx + 1 + max_hold, len(bars))):
            held = j - entry_idx
            b = bars[j]
            if (direction < 0 and b.low <= target) or (direction > 0 and b.high >= target):
                exit_px = target
                break
            exit_px = b.close
        if exit_px is None:
            continue
        gross = direction * (exit_px - entry_px) / entry_px
        trades.append(Trade(bars[entry_idx].ts.isoformat(), direction,
                            round(gross, 7), round(gross - cost, 7), held,
                            bars[entry_idx].ts.hour))
    return trades


def exec_hour_drift(bars: List[Bar], short_hour: int = 4, long_hour: int = 6,
                    cost: float = ROUNDTRIP_COST, delay: int = 0) -> List[Trade]:
    trades: List[Trade] = []
    for i in range(len(bars) - 1 - delay):
        h = bars[i + 1].ts.hour if i + 1 < len(bars) else None
        # trade the bar itself: enter at its open ~= previous close
        b_idx = i + delay
        if b_idx + 1 >= len(bars):
            continue
        nb = bars[b_idx + 1]
        if nb.ts.hour == short_hour:
            gross = -math.log(nb.close / bars[b_idx].close)
            trades.append(Trade(nb.ts.isoformat(), -1, round(gross, 7),
                                round(gross - cost, 7), 1, nb.ts.hour))
        elif nb.ts.hour == long_hour:
            gross = math.log(nb.close / bars[b_idx].close)
            trades.append(Trade(nb.ts.isoformat(), 1, round(gross, 7),
                                round(gross - cost, 7), 1, nb.ts.hour))
    return trades


def exec_breakout(bars: List[Bar], lookback: int = 4, nr7_filter: bool = False,
                  cost: float = ROUNDTRIP_COST, delay: int = 0) -> List[Trade]:
    """Base breakout rule used by the NR7 filter-ablation hypothesis."""
    trades: List[Trade] = []
    for i in range(max(lookback, 7), len(bars) - 1 - delay):
        hh = max(b.high for b in bars[i - lookback:i])
        ll = min(b.low for b in bars[i - lookback:i])
        cur = bars[i]
        direction = 0
        if cur.close > hh:
            direction = 1
        elif cur.close < ll:
            direction = -1
        if direction == 0:
            continue
        if nr7_filter:
            recent = [(b.high - b.low) for b in bars[i - 7:i + 1]]
            if (cur.high - cur.low) == min(recent):     # in compression: skip
                continue
        entry_idx = i + delay
        if entry_idx + 1 >= len(bars):
            continue
        gross = direction * math.log(bars[entry_idx + 1].close / bars[entry_idx].close)
        trades.append(Trade(bars[entry_idx].ts.isoformat(), direction,
                            round(gross, 7), round(gross - cost, 7), 1,
                            bars[entry_idx].ts.hour))
    return trades


# ---------------------------------------------------------------------------
# Hypothesis -> executor dispatch
# ---------------------------------------------------------------------------

def build_executor(h: Dict) -> Optional[Callable[..., List[Trade]]]:
    mech = h["mechanism"].lower()
    test = h.get("proposed_test", {})
    # Typed specs (cycle 2+): parameters live in the spec, not in prose.
    if test.get("type") == "streak_fade":
        k = test["k"]
        horizon = test.get("horizon_bars", 1)
        hours = range(*test["hours"]) if test.get("hours") else None
        vam = bool(test.get("vol_above_median", False))
        return lambda bars, **kw: exec_streak_fade(bars, k, hours=hours,
                                                   vol_above_median=vam,
                                                   horizon=horizon, **kw)
    if test.get("type") == "gap_fade":
        return lambda bars, **kw: exec_weekend_gap_fade(
            bars, test.get("horizon_bars", 24),
            min_gap=test.get("min_gap", 0.0), **kw)
    if h["operator"] == "OP-STREAK-REVERSAL":
        k = 2 if "2 consecutive" in mech else (3 if "3 consecutive" in mech else 4)
        return lambda bars, **kw: exec_streak_fade(bars, k, **kw)
    if h["operator"] == "OP-SESSION-CONDITION" and "17-21" in mech:
        return lambda bars, **kw: exec_streak_fade(bars, 2, hours=range(17, 22), **kw)
    if h["operator"] == "OP-SESSION-CONDITION" and "asia" in mech:
        return lambda bars, **kw: exec_hour_drift(bars, 4, 6, **kw)
    if h["operator"] == "OP-RECOMBINE" and "3-bar streaks" in mech:
        return lambda bars, **kw: exec_streak_fade(bars, 3, vol_above_median=True, **kw)
    if h["operator"] == "OP-EVENT-SEQUENCE":
        return lambda bars, **kw: exec_weekend_gap_fade(bars, test.get("horizon_bars", 24), **kw)
    if h["operator"] == "OP-STATE-FILTER":
        return None  # handled specially as an ablation pair
    return None


# ---------------------------------------------------------------------------
# GEN 11: regime breakdown
# ---------------------------------------------------------------------------

def regime_breakdown(trades: List[Trade], bars: List[Bar]) -> Dict:
    rets = _rets(bars)
    vols = _rolling_vol(rets)
    vals = sorted(v for v in vols if v is not None)
    if not vals:
        return {}
    lo, hi = vals[len(vals) // 3], vals[2 * len(vals) // 3]
    ts_to_vol = {bars[i + 1].ts.isoformat(): vols[i] for i in range(len(vols)) if vols[i] is not None}

    cells: Dict[str, List[Trade]] = {}
    for t in trades:
        v = ts_to_vol.get(t.ts)
        reg = "UNKNOWN" if v is None else ("LOW" if v <= lo else ("HIGH" if v >= hi else "MID"))
        sess = ("ASIA" if t.hour < 7 else ("LONDON" if t.hour < 13 else
                ("NY_OVERLAP" if t.hour < 17 else "NY_LATE")))
        for key in (f"VOL_{reg}", f"SESS_{sess}"):
            cells.setdefault(key, []).append(t)
    out = {}
    for key, ts_ in sorted(cells.items()):
        s = _stats(ts_)
        out[key] = {**s.to_dict(),
                    "sufficient_sample": s.n >= 100,
                    "claim_allowed": s.n >= 100}
    return out


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate_queue(queue_path: Path = DEFAULT_QUEUE,
                   out_path: Path = DEFAULT_OUT) -> Dict:
    bars = load_dev_bars()
    cut = int(len(bars) * OBSERVATION_FRACTION)
    train, val = bars[:cut], bars[cut:]

    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    results = []
    for h in queue["hypotheses"]:
        entry: Dict = {"hyp_id": h["hyp_id"], "operator": h["operator"],
                       "mechanism": h["mechanism"]}
        if h["operator"] == "OP-STATE-FILTER":
            # ablation: breakout with vs without NR7 no-trade filter
            tr_base = exec_breakout(train, nr7_filter=False)
            tr_filt = exec_breakout(train, nr7_filter=True)
            va_base = exec_breakout(val, nr7_filter=False)
            va_filt = exec_breakout(val, nr7_filter=True)
            entry["train"] = {"base": _stats(tr_base).to_dict(),
                              "filtered": _stats(tr_filt).to_dict()}
            entry["validation"] = {"base": _stats(va_base).to_dict(),
                                   "filtered": _stats(va_filt).to_dict()}
            st_f, sv_f = _stats(tr_filt), _stats(va_filt)
            train_improve = (st_f.mean_net - _stats(tr_base).mean_net)
            val_improve = (sv_f.mean_net - _stats(va_base).mean_net)
            entry["train_filter_improvement"] = round(train_improve, 7)
            entry["validation_filter_improvement"] = round(val_improve, 7)
            # The filtered variant must clear the SAME pre-registered bar as every
            # other hypothesis. A filter that merely shrinks a loss is not an edge.
            tradable = (st_f.n >= VAL_MIN_TRADES and st_f.mean_net > 0
                        and st_f.t_stat >= TRAIN_MIN_T
                        and sv_f.n >= VAL_MIN_TRADES and sv_f.mean_net > 0
                        and sv_f.t_stat >= VAL_MIN_T)
            entry["filtered_variant_tradable"] = tradable
            entry["verdict"] = ("SURVIVES_INTERNAL"
                                if (train_improve > 0 and val_improve > 0 and tradable)
                                else "REFUTED_INTERNAL")
            results.append(entry)
            continue

        executor = build_executor(h)
        if executor is None:
            entry["verdict"] = "NO_EXECUTOR"
            results.append(entry)
            continue

        tr = executor(train)
        ts = _stats(tr)
        entry["train"] = ts.to_dict()
        if ts.n < VAL_MIN_TRADES or ts.mean_net <= 0 or ts.t_stat < TRAIN_MIN_T:
            entry["verdict"] = "TRAIN_FAIL"
            entry["verdict_reason"] = (f"train: n={ts.n}, mean_net={ts.mean_net}, "
                                       f"t={ts.t_stat} (need n>={VAL_MIN_TRADES}, "
                                       f"net>0, t>={TRAIN_MIN_T})")
            results.append(entry)
            continue

        va = executor(val)
        vs = _stats(va)
        entry["validation"] = vs.to_dict()
        if vs.n < VAL_MIN_TRADES or vs.mean_net <= 0 or vs.t_stat < VAL_MIN_T:
            entry["verdict"] = "VALIDATION_FAIL"
            entry["verdict_reason"] = (f"validation: n={vs.n}, mean_net={vs.mean_net}, "
                                       f"t={vs.t_stat} (need n>={VAL_MIN_TRADES}, "
                                       f"net>0, t>={VAL_MIN_T})")
        else:
            entry["verdict"] = "SURVIVES_INTERNAL"
            entry["regime_breakdown_train"] = regime_breakdown(tr, train)
            entry["regime_breakdown_validation"] = regime_breakdown(va, val)
        results.append(entry)

    n_tested = len([r for r in results if r["verdict"] != "NO_EXECUTOR"])
    payload = {
        "generated_by": "discovery/evaluation.py (GEN 9-11 core)",
        "train_window": {"start": train[0].ts.isoformat(), "end": train[-1].ts.isoformat(),
                          "bars": len(train)},
        "validation_window": {"start": val[0].ts.isoformat(), "end": val[-1].ts.isoformat(),
                               "bars": len(val)},
        "cost_model": {"roundtrip": ROUNDTRIP_COST},
        "gates": {"train_min_t": TRAIN_MIN_T, "val_min_t": VAL_MIN_T,
                  "min_trades": VAL_MIN_TRADES},
        "multiple_testing": {
            "hypotheses_tested_this_cycle": n_tested,
            "note": "internal-validation t-thresholds are screening gates only; "
                    "no edge claim is made at this stage. Any candidate advancing "
                    "to the sealed holdout gets exactly one shot (GEN 13) and "
                    "carries this cycle's test count into the final qualification "
                    "correction (GEN 14).",
        },
        "results": results,
        "survivors": [r["hyp_id"] for r in results if r["verdict"] == "SURVIVES_INTERNAL"],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    payload = evaluate_queue()
    print(f"GEN 9-11 EVALUATION: {len(payload['results'])} hypotheses, "
          f"{len(payload['survivors'])} survive internal validation")
    for r in payload["results"]:
        line = f"  {r['hyp_id']}  {r['verdict']:18s}"
        if "train" in r and "mean_net" in r.get("train", {}):
            line += (f" train(n={r['train']['n']}, net={r['train']['mean_net']:+.6f}, "
                     f"t={r['train']['t_stat']:+.2f})")
        if "validation" in r and "mean_net" in r.get("validation", {}):
            line += (f" val(n={r['validation']['n']}, net={r['validation']['mean_net']:+.6f}, "
                     f"t={r['validation']['t_stat']:+.2f})")
        print(line)
        if r.get("verdict_reason"):
            print(f"      reason: {r['verdict_reason']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
