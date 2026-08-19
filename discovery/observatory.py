"""
GEN 8: MARKET OBSERVATORY.

Answers "what is the market actually doing?" with measured evidence, so that
GEN 7 generates hypotheses FROM observations instead of from AI imagination.

Rules enforced here:
- DEV data only (holdout firewall via discovery._guards).
- Observations are computed on the OBSERVATION WINDOW (first 80% of dev bars);
  the last 20% is reserved for GEN 9 train-only verification and is not
  touched by the observatory.
- Significance threshold is PRE-REGISTERED: |t| >= 3.5 (conservative Bonferroni
  allowance for the ~60 statistics this module computes; 0.05/60 -> z ~ 3.2).
- Every observation records its sample size, effect size, t-statistic, and
  exactly which window produced it. No randomness anywhere.
"""

import csv
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from discovery._guards import guard_path

DEFAULT_DEV_CSV = Path("data/csv/EURUSD_H1.csv")
DEFAULT_REGISTRY = Path("reports/factory/market_observations.json")

OBSERVATION_FRACTION = 0.80          # first 80% of dev bars
SIGNIFICANCE_T = 3.5                 # pre-registered; never tuned post hoc


@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class MarketObservation:
    obs_id: str
    family: str                       # e.g. "AUTOCORRELATION", "SESSION"
    description: str                  # human-readable, feeds novelty engine
    mechanism_hint: str               # candidate economic mechanism
    effect_size: float
    t_stat: float
    sample_size: int
    significant: bool
    details: Dict = field(default_factory=dict)
    window_start: str = ""
    window_end: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def load_dev_bars(csv_path: Path = DEFAULT_DEV_CSV) -> List[Bar]:
    path = guard_path(csv_path)
    bars: List[Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
            bars.append(Bar(ts, float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"])))
    if not bars:
        raise ValueError(f"no bars loaded from {path}")
    return bars


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _tstat_mean(xs: List[float]) -> float:
    s = _std(xs)
    if s == 0 or len(xs) < 2:
        return 0.0
    return _mean(xs) / (s / math.sqrt(len(xs)))


def _autocorr(xs: List[float], lag: int) -> float:
    n = len(xs) - lag
    if n < 30:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs)
    if var == 0:
        return 0.0
    cov = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n))
    return cov / var


class MarketObservatory:
    """Computes the observation registry from the observation window."""

    def __init__(self, bars: List[Bar]):
        cut = int(len(bars) * OBSERVATION_FRACTION)
        self.window = bars[:cut]
        self.window_start = self.window[0].ts.isoformat()
        self.window_end = self.window[-1].ts.isoformat()
        self.reserved_bars = len(bars) - cut
        closes = [b.close for b in self.window]
        self.rets = [math.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]
        self.observations: List[MarketObservation] = []

    # ------------------------------------------------------------------
    def _add(self, obs_id: str, family: str, description: str,
             mechanism_hint: str, effect: float, t: float, n: int,
             details: Optional[Dict] = None) -> None:
        self.observations.append(MarketObservation(
            obs_id=obs_id, family=family, description=description,
            mechanism_hint=mechanism_hint, effect_size=round(effect, 6),
            t_stat=round(t, 3), sample_size=n,
            significant=abs(t) >= SIGNIFICANCE_T,
            details=details or {},
            window_start=self.window_start, window_end=self.window_end,
        ))

    # ------------------------------------------------------------------
    def obs_return_autocorrelation(self) -> None:
        for lag in (1, 2, 3, 6, 12, 24):
            r = _autocorr(self.rets, lag)
            n = len(self.rets) - lag
            t = r * math.sqrt(n)
            self._add(
                f"OBS-AC-RET-L{lag}", "AUTOCORRELATION",
                f"lag-{lag} autocorrelation of H1 log returns = {r:.4f}",
                ("negative serial correlation (short-horizon mean reversion in returns)"
                 if r < 0 else
                 "positive serial correlation (short-horizon continuation in returns)"),
                r, t, n, {"lag": lag},
            )

    def obs_vol_clustering(self) -> None:
        abs_rets = [abs(r) for r in self.rets]
        for lag in (1, 24):
            r = _autocorr(abs_rets, lag)
            n = len(abs_rets) - lag
            t = r * math.sqrt(n)
            self._add(
                f"OBS-VOLCLUST-L{lag}", "VOLATILITY",
                f"lag-{lag} autocorrelation of |returns| = {r:.4f} (volatility clustering)",
                "volatility is persistent: high-vol hours cluster; regime conditioning is meaningful",
                r, t, n, {"lag": lag},
            )

    def obs_trend_persistence(self) -> None:
        ups = [1 if r > 0 else 0 for r in self.rets if r != 0]
        base_p = _mean([float(u) for u in ups])
        for k in (2, 3, 4):
            after: List[float] = []
            run = 0
            for i, r in enumerate(self.rets[:-1]):
                run = run + 1 if r > 0 else 0
                if run >= k:
                    after.append(1.0 if self.rets[i + 1] > 0 else 0.0)
            if len(after) < 50:
                continue
            p = _mean(after)
            se = math.sqrt(base_p * (1 - base_p) / len(after))
            t = (p - base_p) / se if se > 0 else 0.0
            self._add(
                f"OBS-TRENDPERSIST-K{k}", "TREND",
                f"P(up | {k} consecutive up bars) = {p:.4f} vs unconditional {base_p:.4f}",
                ("streaks continue (short-horizon herding)" if p > base_p
                 else "streaks reverse (exhaustion after consecutive moves)"),
                p - base_p, t, len(after), {"k": k, "base_p": round(base_p, 4)},
            )

    def obs_mean_reversion_after_shock(self) -> None:
        win = 20
        for z_thr in (2.0, 3.0):
            signed_next: List[float] = []
            for i in range(win, len(self.rets) - 1):
                sd = _std(self.rets[i - win:i])
                if sd == 0:
                    continue
                z = self.rets[i] / sd
                if abs(z) >= z_thr:
                    # positive value = reversal (next return opposes the shock)
                    signed_next.append(-math.copysign(1.0, z) * self.rets[i + 1])
            if len(signed_next) < 50:
                continue
            t = _tstat_mean(signed_next)
            self._add(
                f"OBS-MRSHOCK-Z{int(z_thr)}", "MEAN_REVERSION",
                f"mean next-bar return OPPOSING a |z|>={z_thr} shock = "
                f"{_mean(signed_next):.6f} ({len(signed_next)} events)",
                "liquidity-provision snapback after outsized single-bar moves",
                _mean(signed_next), t, len(signed_next), {"z_threshold": z_thr, "vol_window": win},
            )

    def obs_momentum_continuation(self) -> None:
        win, horizon = 20, 4
        for z_thr in (2.0,):
            cont: List[float] = []
            for i in range(win, len(self.rets) - horizon):
                sd = _std(self.rets[i - win:i])
                if sd == 0:
                    continue
                z = self.rets[i] / sd
                if abs(z) >= z_thr:
                    fwd = sum(self.rets[i + 1:i + 1 + horizon])
                    cont.append(math.copysign(1.0, z) * fwd)  # + = continuation
            if len(cont) < 50:
                continue
            t = _tstat_mean(cont)
            self._add(
                f"OBS-MOMCONT-Z{int(z_thr)}-H{horizon}", "MOMENTUM",
                f"mean {horizon}-bar continuation after |z|>={z_thr} bar = {_mean(cont):.6f}",
                "information diffusion: large moves keep drifting" if _mean(cont) > 0
                else "large moves overshoot and revert over the next hours",
                _mean(cont), t, len(cont), {"z_threshold": z_thr, "horizon": horizon},
            )

    def obs_hour_of_day(self) -> None:
        by_hour: Dict[int, List[float]] = {h: [] for h in range(24)}
        rng_by_hour: Dict[int, List[float]] = {h: [] for h in range(24)}
        for i in range(1, len(self.window)):
            b = self.window[i]
            by_hour[b.ts.hour].append(self.rets[i - 1])
            rng_by_hour[b.ts.hour].append((b.high - b.low) / b.close)
        all_rng = [x for xs in rng_by_hour.values() for x in xs]
        mean_rng = _mean(all_rng)
        for h in range(24):
            xs = by_hour[h]
            if len(xs) < 100:
                continue
            t = _tstat_mean(xs)
            ratio = _mean(rng_by_hour[h]) / mean_rng if mean_rng else 1.0
            # only record hours with a return anomaly or an extreme range ratio
            if abs(t) >= 2.0 or ratio > 1.5 or ratio < 0.6:
                self._add(
                    f"OBS-HOUR-{h:02d}", "SESSION",
                    f"hour {h:02d} UTC: mean ret t={t:.2f}, range ratio {ratio:.2f}x",
                    "session-specific liquidity/participation structure",
                    _mean(xs), t, len(xs), {"hour_utc": h, "range_ratio": round(ratio, 3)},
                )

    def obs_session_volatility(self) -> None:
        sessions = {"ASIA": range(0, 7), "LONDON": range(7, 13),
                    "NY_OVERLAP": range(13, 17), "NY_LATE": range(17, 22)}
        rng_all: List[float] = []
        per: Dict[str, List[float]] = {s: [] for s in sessions}
        for b in self.window:
            r = (b.high - b.low) / b.close
            rng_all.append(r)
            for s, hours in sessions.items():
                if b.ts.hour in hours:
                    per[s].append(r)
        base = _mean(rng_all)
        for s, xs in per.items():
            if len(xs) < 200 or base == 0:
                continue
            ratio = _mean(xs) / base
            diffs = [x - base for x in xs]
            t = _tstat_mean(diffs)
            self._add(
                f"OBS-SESSVOL-{s}", "SESSION",
                f"{s} true-range ratio vs all hours = {ratio:.3f}x",
                "volatility concentrates where the active sessions are",
                ratio - 1.0, t, len(xs), {"session": s},
            )

    def obs_range_compression_expansion(self) -> None:
        lookback = 7
        ratios: List[float] = []
        for i in range(lookback, len(self.window) - 1):
            recent = [(b.high - b.low) for b in self.window[i - lookback:i + 1]]
            cur = self.window[i].high - self.window[i].low
            if cur == min(recent) and cur > 0:
                nxt = self.window[i + 1].high - self.window[i + 1].low
                med = sorted(recent)[len(recent) // 2]
                if med > 0:
                    ratios.append(nxt / med)
        if len(ratios) >= 50:
            diffs = [x - 1.0 for x in ratios]
            t = _tstat_mean(diffs)
            self._add(
                "OBS-NR7-EXPAND", "RANGE",
                f"after a {lookback}-bar narrowest-range hour, next-bar range = "
                f"{_mean(ratios):.3f}x the recent median",
                "compression precedes expansion (volatility cycle)",
                _mean(ratios) - 1.0, t, len(ratios), {"lookback": lookback},
            )

    def obs_weekend_gap(self) -> None:
        fills: List[float] = []
        gaps: List[float] = []
        for i in range(1, len(self.window)):
            prev, cur = self.window[i - 1], self.window[i]
            if (cur.ts - prev.ts).total_seconds() >= 40 * 3600:  # weekend jump
                gap = cur.open - prev.close
                if gap == 0:
                    continue
                gaps.append(abs(gap) / prev.close)
                filled = 0.0
                for j in range(i, min(i + 24, len(self.window))):
                    b = self.window[j]
                    if (gap > 0 and b.low <= prev.close) or (gap < 0 and b.high >= prev.close):
                        filled = 1.0
                        break
                fills.append(filled)
        if len(fills) >= 30:
            p = _mean(fills)
            se = math.sqrt(p * (1 - p) / len(fills)) or 1e-9
            t = (p - 0.5) / se
            self._add(
                "OBS-WKND-GAPFILL", "GAP",
                f"P(weekend gap fills within 24 bars) = {p:.3f} over {len(fills)} weekends, "
                f"median gap {sorted(gaps)[len(gaps)//2]*1e4:.1f} pips-e4",
                "weekend gaps revert to Friday close (positioning unwind)",
                p - 0.5, t, len(fills), {},
            )

    def obs_conditional_by_vol_regime(self) -> None:
        win = 50
        vols: List[float] = []
        for i in range(win, len(self.rets)):
            vols.append(_std(self.rets[i - win:i]))
        if len(vols) < 300:
            return
        s = sorted(vols)
        lo_thr, hi_thr = s[len(s) // 3], s[2 * len(s) // 3]
        regimes: Dict[str, List[int]] = {"LOW": [], "MID": [], "HIGH": []}
        for k, v in enumerate(vols):
            i = k + win  # index into self.rets
            reg = "LOW" if v <= lo_thr else ("HIGH" if v >= hi_thr else "MID")
            regimes[reg].append(i)
        for reg in ("LOW", "HIGH"):
            idxs = [i for i in regimes[reg] if i + 1 < len(self.rets)]
            if len(idxs) < 200:
                continue
            sub = [self.rets[i] for i in idxs]
            r1 = _autocorr_indexed(self.rets, idxs)
            t = r1 * math.sqrt(len(idxs))
            self._add(
                f"OBS-VOLREG-{reg}-AC1", "REGIME",
                f"{reg}-vol regime: conditional lag-1 return autocorrelation = {r1:.4f}",
                f"serial dependence differs by volatility regime ({reg})",
                r1, t, len(idxs), {"regime": reg, "vol_window": win,
                                   "mean_abs_ret": round(_mean([abs(x) for x in sub]), 6)},
            )

    def obs_tail_behavior(self) -> None:
        n = len(self.rets)
        m, sd = _mean(self.rets), _std(self.rets)
        if sd == 0:
            return
        kurt = sum(((x - m) / sd) ** 4 for x in self.rets) / n - 3.0
        neg_tail = sum(1 for x in self.rets if (x - m) / sd < -3)
        pos_tail = sum(1 for x in self.rets if (x - m) / sd > 3)
        asym = (neg_tail - pos_tail) / max(neg_tail + pos_tail, 1)
        self._add(
            "OBS-TAILS", "TAILS",
            f"excess kurtosis {kurt:.1f}; 3-sigma tails: {neg_tail} down vs {pos_tail} up "
            f"(asymmetry {asym:+.2f})",
            "fat tails imply stop placement/expectancy dominated by rare bars",
            kurt, kurt / max(math.sqrt(24.0 / n), 1e-9) if n else 0.0, n,
            {"neg_tail_3sig": neg_tail, "pos_tail_3sig": pos_tail},
        )

    # ------------------------------------------------------------------
    def run_all(self) -> List[MarketObservation]:
        self.obs_return_autocorrelation()
        self.obs_vol_clustering()
        self.obs_trend_persistence()
        self.obs_mean_reversion_after_shock()
        self.obs_momentum_continuation()
        self.obs_hour_of_day()
        self.obs_session_volatility()
        self.obs_range_compression_expansion()
        self.obs_weekend_gap()
        self.obs_conditional_by_vol_regime()
        self.obs_tail_behavior()
        return self.observations

    def save(self, path: Path = DEFAULT_REGISTRY) -> Dict:
        payload = {
            "generated_by": "discovery/observatory.py (GEN 8)",
            "data_source": str(DEFAULT_DEV_CSV),
            "observation_window": {"start": self.window_start, "end": self.window_end,
                                    "bars": len(self.window)},
            "reserved_internal_validation_bars": self.reserved_bars,
            "significance_threshold_t": SIGNIFICANCE_T,
            "observation_count": len(self.observations),
            "significant_count": sum(1 for o in self.observations if o.significant),
            "observations": [o.to_dict() for o in self.observations],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def _autocorr_indexed(rets: List[float], idxs: List[int]) -> float:
    pairs = [(rets[i], rets[i + 1]) for i in idxs if i + 1 < len(rets)]
    if len(pairs) < 30:
        return 0.0
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = _mean(xs), _mean(ys)
    sx, sy = _std(xs), _std(ys)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in pairs) / (len(pairs) - 1)
    return cov / (sx * sy)


def main() -> int:
    bars = load_dev_bars()
    obs = MarketObservatory(bars)
    obs.run_all()
    payload = obs.save()
    print(f"GEN 8 OBSERVATORY: {payload['observation_count']} observations "
          f"({payload['significant_count']} significant at |t|>={SIGNIFICANCE_T}) "
          f"on {payload['observation_window']['bars']} bars "
          f"[{payload['observation_window']['start']} .. {payload['observation_window']['end']}]")
    for o in obs.observations:
        flag = "**" if o.significant else "  "
        print(f" {flag} {o.obs_id:26s} t={o.t_stat:+8.2f} n={o.sample_size:6d}  {o.description[:80]}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
