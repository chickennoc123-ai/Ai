"""
GEN 12: ADVERSARIAL EDGE DESTRUCTION.

The Factory stops looking for edge here and starts trying to KILL it.

A candidate arrives with a claimed edge. This module's job is to find any
alternative explanation for that edge other than "the market has this
structure". Every attack below is a falsification attempt; a candidate is
only allowed forward if it survives ALL of them.

Attacks implemented:
  1. COST_SHOCK          -- 1.5x / 2x / 3x the frozen roundtrip cost
  2. EXECUTION_DELAY     -- signal acted on 1 and 2 bars late
  3. PARAMETER_PERTURB   -- every integer parameter +/-1 and +/-2
  4. SUBPERIOD           -- split train into 4 contiguous blocks; edge must
                            not live in only one of them
  5. BOOTSTRAP           -- 1000 seeded resamples of the trade sequence;
                            requires >=95% of resamples net-positive
  6. SYMBOL_SHIFT        -- same rule on GBPUSD H1 (a different instrument);
                            a rule that works ONLY on EURUSD is suspect but
                            not automatically dead -- reported, not auto-fatal
  7. REGIME_SHIFT        -- edge must not be confined to a single vol tercile

Every random draw is seeded (SEED constant). Same candidate -> same verdict.
"""

import json
import math
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

from discovery.observatory import Bar, load_dev_bars, OBSERVATION_FRACTION
from discovery.evaluation import (
    ROUNDTRIP_COST, Trade, _stats, _rets, _rolling_vol,
    exec_streak_fade, exec_weekend_gap_fade, exec_hour_drift, exec_breakout,
)

SEED = 20260819
BOOTSTRAP_N = 1000
BOOTSTRAP_MIN_POSITIVE_FRACTION = 0.95
SUBPERIOD_BLOCKS = 4
SUBPERIOD_MIN_POSITIVE_BLOCKS = 3     # at least 3 of 4 blocks net-positive
DEFAULT_OUT = Path("reports/factory/adversarial_results.json")
GBPUSD_CSV = Path("data/csv/GBPUSD_H1.csv")


@dataclass
class AttackResult:
    attack: str
    survived: bool
    detail: Dict = field(default_factory=dict)
    fatal: bool = True          # if False, a failure is reported but not disqualifying

    def to_dict(self) -> Dict:
        return asdict(self)


def _bootstrap(trades: List[Trade], n: int = BOOTSTRAP_N) -> Dict:
    if len(trades) < 10:
        return {"positive_fraction": 0.0, "resamples": 0, "insufficient_trades": True}
    rng = random.Random(SEED)
    nets = [t.net for t in trades]
    k = len(nets)
    positive = 0
    means = []
    for _ in range(n):
        sample = [nets[rng.randrange(k)] for _ in range(k)]
        m = sum(sample) / k
        means.append(m)
        if m > 0:
            positive += 1
    means.sort()
    return {
        "positive_fraction": round(positive / n, 4),
        "resamples": n,
        "mean_of_means": round(sum(means) / n, 7),
        "ci_2.5": round(means[int(0.025 * n)], 7),
        "ci_97.5": round(means[int(0.975 * n)], 7),
    }


class AdversarialDestroyer:
    """
    executor(bars, **kwargs) -> List[Trade]
    kwargs the executor must accept: cost, delay (both already supported by
    every executor in discovery.evaluation).
    """

    def __init__(self, candidate_id: str, executor: Callable[..., List[Trade]],
                 bars: List[Bar], int_params: Optional[Dict[str, int]] = None,
                 param_rebuild: Optional[Callable[[Dict[str, int]], Callable]] = None):
        self.candidate_id = candidate_id
        self.executor = executor
        self.bars = bars
        self.int_params = int_params or {}
        self.param_rebuild = param_rebuild
        self.results: List[AttackResult] = []
        self.baseline = _stats(executor(bars))

    # ------------------------------------------------------------------
    def attack_cost_shock(self) -> None:
        detail = {}
        survived = True
        for mult in (1.5, 2.0, 3.0):
            s = _stats(self.executor(self.bars, cost=ROUNDTRIP_COST * mult))
            detail[f"{mult}x"] = {"mean_net": s.mean_net, "t_stat": s.t_stat, "n": s.n}
            if mult <= 2.0 and s.mean_net <= 0:
                survived = False
        detail["rule"] = "must stay net-positive at 2x the frozen roundtrip cost"
        self.results.append(AttackResult("COST_SHOCK", survived, detail))

    def attack_execution_delay(self) -> None:
        detail = {}
        survived = True
        for d in (1, 2):
            s = _stats(self.executor(self.bars, delay=d))
            detail[f"delay_{d}_bars"] = {"mean_net": s.mean_net, "t_stat": s.t_stat, "n": s.n}
            if d == 1 and s.mean_net <= 0:
                survived = False
        detail["rule"] = "must stay net-positive with a 1-bar execution delay"
        self.results.append(AttackResult("EXECUTION_DELAY", survived, detail))

    def attack_parameter_perturbation(self) -> None:
        if not self.int_params or not self.param_rebuild:
            self.results.append(AttackResult(
                "PARAMETER_PERTURB", True,
                {"skipped": "no integer parameters declared"}, fatal=False))
            return
        detail, survived = {}, True
        for name, base in self.int_params.items():
            for delta in (-2, -1, 1, 2):
                v = base + delta
                if v < 1:
                    continue
                params = dict(self.int_params)
                params[name] = v
                try:
                    s = _stats(self.param_rebuild(params)(self.bars))
                except Exception as exc:                       # noqa: BLE001
                    detail[f"{name}={v}"] = {"error": str(exc)[:80]}
                    continue
                detail[f"{name}={v}"] = {"mean_net": s.mean_net, "t_stat": s.t_stat, "n": s.n}
                if abs(delta) == 1 and s.mean_net <= 0:
                    survived = False
        detail["rule"] = "must stay net-positive at every +/-1 parameter neighbour"
        self.results.append(AttackResult("PARAMETER_PERTURB", survived, detail))

    def attack_subperiod(self) -> None:
        size = len(self.bars) // SUBPERIOD_BLOCKS
        blocks, positive = {}, 0
        for i in range(SUBPERIOD_BLOCKS):
            seg = self.bars[i * size:(i + 1) * size]
            s = _stats(self.executor(seg))
            blocks[f"block_{i+1}"] = {
                "start": seg[0].ts.isoformat(), "end": seg[-1].ts.isoformat(),
                "n": s.n, "mean_net": s.mean_net, "t_stat": s.t_stat}
            if s.mean_net > 0:
                positive += 1
        survived = positive >= SUBPERIOD_MIN_POSITIVE_BLOCKS
        blocks["positive_blocks"] = positive
        blocks["rule"] = f"at least {SUBPERIOD_MIN_POSITIVE_BLOCKS}/{SUBPERIOD_BLOCKS} blocks net-positive"
        self.results.append(AttackResult("SUBPERIOD", survived, blocks))

    def attack_bootstrap(self) -> None:
        b = _bootstrap(self.executor(self.bars))
        survived = b.get("positive_fraction", 0) >= BOOTSTRAP_MIN_POSITIVE_FRACTION
        b["rule"] = f"seeded bootstrap: >={BOOTSTRAP_MIN_POSITIVE_FRACTION:.0%} of {BOOTSTRAP_N} resamples net-positive"
        b["seed"] = SEED
        self.results.append(AttackResult("BOOTSTRAP", survived, b))

    def attack_symbol_shift(self) -> None:
        if not GBPUSD_CSV.exists():
            self.results.append(AttackResult(
                "SYMBOL_SHIFT", True, {"skipped": "GBPUSD_H1.csv not available"}, fatal=False))
            return
        try:
            other = load_dev_bars(GBPUSD_CSV)
            s = _stats(self.executor(other))
            detail = {"instrument": "GBPUSD_H1", "n": s.n, "mean_net": s.mean_net,
                      "t_stat": s.t_stat,
                      "rule": "reported, not disqualifying: a EURUSD-only edge is suspect "
                              "but may be genuinely instrument-specific"}
            survived = s.mean_net > 0
        except Exception as exc:                                # noqa: BLE001
            detail, survived = {"error": str(exc)[:120]}, True
        self.results.append(AttackResult("SYMBOL_SHIFT", survived, detail, fatal=False))

    def attack_regime_shift(self) -> None:
        trades = self.executor(self.bars)
        rets = _rets(self.bars)
        vols = _rolling_vol(rets)
        vals = sorted(v for v in vols if v is not None)
        if not vals or not trades:
            self.results.append(AttackResult("REGIME_SHIFT", False,
                                             {"reason": "no trades or no vol series"}))
            return
        lo, hi = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        ts_to_vol = {self.bars[i + 1].ts.isoformat(): vols[i]
                     for i in range(len(vols)) if vols[i] is not None}
        cells: Dict[str, List[Trade]] = {"LOW": [], "MID": [], "HIGH": []}
        for t in trades:
            v = ts_to_vol.get(t.ts)
            if v is None:
                continue
            cells["LOW" if v <= lo else ("HIGH" if v >= hi else "MID")].append(t)
        detail, positive = {}, 0
        for reg, ts_ in cells.items():
            s = _stats(ts_)
            detail[reg] = {"n": s.n, "mean_net": s.mean_net, "t_stat": s.t_stat}
            if s.n >= 30 and s.mean_net > 0:
                positive += 1
        detail["regimes_net_positive"] = positive
        detail["rule"] = "edge must be net-positive in at least 2 of 3 volatility terciles"
        self.results.append(AttackResult("REGIME_SHIFT", positive >= 2, detail))

    # ------------------------------------------------------------------
    def run_all(self) -> Dict:
        self.attack_cost_shock()
        self.attack_execution_delay()
        self.attack_parameter_perturbation()
        self.attack_subperiod()
        self.attack_bootstrap()
        self.attack_symbol_shift()
        self.attack_regime_shift()
        fatal_failures = [r.attack for r in self.results if not r.survived and r.fatal]
        advisory = [r.attack for r in self.results if not r.survived and not r.fatal]
        return {
            "candidate_id": self.candidate_id,
            "baseline": self.baseline.to_dict(),
            "seed": SEED,
            "attacks": [r.to_dict() for r in self.results],
            "fatal_failures": fatal_failures,
            "advisory_failures": advisory,
            "verdict": "SURVIVED_ADVERSARIAL" if not fatal_failures else "DESTROYED",
        }


def destroy(candidate_id: str, executor: Callable[..., List[Trade]],
            bars: Optional[List[Bar]] = None, **kw) -> Dict:
    if bars is None:
        all_bars = load_dev_bars()
        bars = all_bars[:int(len(all_bars) * OBSERVATION_FRACTION)]
    return AdversarialDestroyer(candidate_id, executor, bars, **kw).run_all()
