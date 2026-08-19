"""
GEN 7: DISCOVERY ENGINE.

Market evidence -> search operators -> hypotheses. Never the reverse.

Every emitted hypothesis answers, explicitly:
  1. what was discovered           (from GEN 8 observation)
  2. why it is interesting         (mechanism + effect + significance)
  3. what evidence generated it    (observation ids)
  4. which operator produced it    (operator name)
  5. what information gain justifies testing it (priority score inputs)

Filters, in order, all mechanical:
  A. evidence filter    -- only SIGNIFICANT observations may seed hypotheses
  B. refuted-family     -- reuses core.factory.novelty_engine primitives
                           against reports/factory/research_family_registry.json
  C. batch novelty      -- near-duplicates within the batch are collapsed
  D. economic sanity    -- expected gross effect per trade is annotated against
                           the frozen cost assumption; hopeless ones are marked
                           ECONOMICALLY_DOUBTFUL (kept, deprioritized) or dropped
                           if effect < 0.25x cost
  E. budget             -- top MAX_HYPOTHESES_PER_CYCLE by priority

No randomness. Same observation registry -> byte-identical queue.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from core.factory.novelty_engine import (
    is_near_duplicate,
    is_same_mechanism,
    mechanism_signature,
    token_jaccard,
)

DEFAULT_OBSERVATIONS = Path("reports/factory/market_observations.json")
DEFAULT_FAMILY_REGISTRY = Path("reports/factory/research_family_registry.json")
DEFAULT_QUEUE = Path("reports/factory/discovery_queue.json")

MAX_HYPOTHESES_PER_CYCLE = 20

# Frozen cost assumption carried from GEN 4/5 (ML-001-R2 spec section 7):
# median spread + slippage for EURUSD H1, in price terms.
ASSUMED_ROUNDTRIP_COST = 0.00011  # 1.1 pips
MIN_EFFECT_VS_COST = 0.25         # below this, not worth a test slot


@dataclass
class DiscoveredHypothesis:
    hyp_id: str
    operator: str
    what_was_discovered: str
    why_interesting: str
    evidence_obs_ids: List[str]
    mechanism: str
    testable_prediction: str
    proposed_test: Dict
    expected_gross_effect: float       # per-trade, price terms (abs)
    effect_vs_cost: float              # expected_gross_effect / cost
    economic_flag: str                 # "VIABLE" | "ECONOMICALLY_DOUBTFUL"
    priority: float
    family_signature: str
    information_gain_inputs: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


def _hyp_id(mechanism: str) -> str:
    return "DISC-" + hashlib.sha256(mechanism.encode("utf-8")).hexdigest()[:10].upper()


def load_observations(path: Path = DEFAULT_OBSERVATIONS) -> Dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_refuted_descriptions(path: Path = DEFAULT_FAMILY_REGISTRY) -> List[str]:
    """Descriptions of every known research family (refuted or tested)."""
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fams = data.get("families", {})
    return [rec.get("description", "") for rec in fams.values() if rec.get("description")]


class DiscoveryEngine:
    def __init__(self,
                 observations_payload: Dict,
                 refuted_descriptions: Optional[List[str]] = None):
        self.payload = observations_payload
        self.obs = {o["obs_id"]: o for o in observations_payload["observations"]}
        self.significant = {k: o for k, o in self.obs.items() if o["significant"]}
        self.refuted = refuted_descriptions or []
        self.candidates: List[DiscoveredHypothesis] = []
        self.rejections: List[Dict] = []

    # ------------------------------------------------------------------
    def _emit(self, operator: str, obs_ids: List[str], mechanism: str,
              what: str, why: str, prediction: str, test: Dict,
              gross_effect: float) -> None:
        evc = gross_effect / ASSUMED_ROUNDTRIP_COST if ASSUMED_ROUNDTRIP_COST else 0.0
        if evc < MIN_EFFECT_VS_COST:
            self.rejections.append({"mechanism": mechanism, "reason":
                                    f"economic pre-filter: effect/cost {evc:.2f} < {MIN_EFFECT_VS_COST}"})
            return
        flag = "VIABLE" if evc >= 1.0 else "ECONOMICALLY_DOUBTFUL"
        min_t = min(abs(self.obs[i]["t_stat"]) for i in obs_ids)
        min_n = min(self.obs[i]["sample_size"] for i in obs_ids)
        complexity = 1.0 + 0.5 * (len(obs_ids) - 1)
        priority = (min_t * min(evc, 3.0)) / complexity
        self.candidates.append(DiscoveredHypothesis(
            hyp_id=_hyp_id(mechanism),
            operator=operator,
            what_was_discovered=what,
            why_interesting=why,
            evidence_obs_ids=obs_ids,
            mechanism=mechanism,
            testable_prediction=prediction,
            proposed_test=test,
            expected_gross_effect=round(gross_effect, 7),
            effect_vs_cost=round(evc, 3),
            economic_flag=flag,
            priority=round(priority, 3),
            family_signature=mechanism_signature(mechanism),
            information_gain_inputs={"min_t": min_t, "min_n": min_n,
                                     "complexity": complexity},
        ))

    # ------------------------------------------------------------------
    # Operators
    # ------------------------------------------------------------------

    def op_streak_reversal(self) -> None:
        """OP-THRESHOLD on trend-persistence observations."""
        for k in (2, 3, 4):
            oid = f"OBS-TRENDPERSIST-K{k}"
            o = self.significant.get(oid)
            if not o or o["effect_size"] >= 0:
                continue
            edge_pp = abs(o["effect_size"])           # probability-points edge
            mean_abs_ret = 0.00085                    # H1 EURUSD, from dev data
            gross = 2 * edge_pp * mean_abs_ret        # directional expectancy proxy
            self._emit(
                "OP-STREAK-REVERSAL", [oid],
                mechanism=(f"after {k} consecutive same-direction H1 bars, the next bar "
                           f"reverses more often than chance (fade the streak, 1-bar horizon)"),
                what=f"P(continuation | {k}-bar streak) = {0.5 + o['effect_size']:.3f}, "
                     f"t={o['t_stat']}",
                why="exhaustion/anti-persistence after consecutive moves; distinct from "
                    "oscillator-level mean reversion (no indicator threshold involved)",
                prediction=f"fading {k}-bar streaks yields positive gross expectancy at 1-bar horizon "
                           f"on unseen dev-internal validation data",
                test={"entry": f"at close of {k}-th consecutive up(down) bar, enter short(long)",
                      "exit": "next bar close", "horizon_bars": 1,
                      "direction": "counter-streak"},
                gross_effect=gross,
            )

    def op_weekend_gap_fade(self) -> None:
        o = self.significant.get("OBS-WKND-GAPFILL")
        if not o:
            return
        p_fill = 0.5 + o["effect_size"]
        median_gap = 0.00051  # from observation details (median weekend gap)
        gross = (2 * p_fill - 1) * median_gap
        self._emit(
            "OP-EVENT-SEQUENCE", ["OBS-WKND-GAPFILL"],
            mechanism="weekend opening gaps revert toward Friday close within 24 H1 bars "
                      "(fade the gap at Sunday open, target = Friday close)",
            what=f"P(gap fill within 24 bars) = {p_fill:.3f} over {o['sample_size']} weekends",
            why="positioning unwind after illiquid weekend open; event-based, "
                "~52 trades/year, well-defined target and time stop",
            prediction="fading weekend gaps with target=Friday-close and 24-bar time stop "
                       "yields positive expectancy net of spread on validation data",
            test={"entry": "Sunday open bar close, direction opposing the gap",
                  "exit": "Friday close touched OR 24 bars elapsed",
                  "horizon_bars": 24, "event": "weekend_gap"},
            gross_effect=gross,
        )

    def op_compression_persistence(self) -> None:
        o = self.significant.get("OBS-NR7-EXPAND")
        if not o or o["effect_size"] >= 0:
            return
        # Negative effect: compression persists. This is a FILTER hypothesis,
        # not a directional trade: quiet hours predict quiet hours.
        self._emit(
            "OP-STATE-FILTER", ["OBS-NR7-EXPAND", "OBS-VOLCLUST-L1"],
            mechanism="range compression persists into the next hour "
                      "(narrowest-range-of-7 predicts below-median next-bar range); "
                      "use as a NO-TRADE filter for breakout-style entries",
            what=f"next-bar range after NR7 = {1 + o['effect_size']:.3f}x recent median, "
                 f"t={o['t_stat']}",
            why="volatility clustering implies compression is a state, not a trigger; "
                "breakout entries during compression should underperform",
            prediction="a breakout rule filtered by 'not in NR7 state' outperforms the same "
                       "rule unfiltered, net of costs, on validation data",
            test={"type": "filter_ablation", "state": "NR7",
                  "applies_to": "breakout entries", "horizon_bars": 1},
            gross_effect=abs(o["effect_size"]) * 0.00085,
        )

    def op_session_conditioning(self) -> None:
        """Cross directional anomalies with session-volatility structure."""
        streak = self.significant.get("OBS-TRENDPERSIST-K2")
        ny = self.significant.get("OBS-SESSVOL-NY_LATE")
        if streak and ny:
            gross = 2 * abs(streak["effect_size"]) * 0.00085 * (1 + ny["effect_size"])
            self._emit(
                "OP-SESSION-CONDITION", ["OBS-TRENDPERSIST-K2", "OBS-SESSVOL-NY_LATE"],
                mechanism="fade 2-bar streaks ONLY during the high-volatility late-NY window "
                          "(17-21 UTC) where per-bar range is 1.38x average",
                what="streak reversal edge (t=-8.96) x highest-vol session (1.384x range)",
                why="same probability edge applied where bar magnitude is largest -> "
                    "gross effect scales with session range while cost is constant",
                prediction="streak-fade restricted to 17-21 UTC has higher net expectancy "
                           "per trade than the unconditioned version",
                test={"entry": "counter-streak after 2 consecutive bars, hour in 17-21 UTC",
                      "exit": "next bar close", "horizon_bars": 1},
                gross_effect=gross,
            )
        asia_hours = [self.significant.get("OBS-HOUR-04"), self.significant.get("OBS-HOUR-06")]
        if all(asia_hours):
            h4, h6 = asia_hours
            gross = (abs(h4["effect_size"]) + abs(h6["effect_size"])) / 2
            self._emit(
                "OP-SESSION-CONDITION", ["OBS-HOUR-04", "OBS-HOUR-06"],
                mechanism="systematic directional drift in specific Asia hours "
                          "(04 UTC negative t=-6.98, 06 UTC positive t=+4.49): "
                          "time-of-day flow pattern, trade the hour with the sign",
                what="hour-of-day return anomalies with |t|>4.4 in the observation window",
                why="persistent intraday flow (fixing/rebalancing) can create "
                    "clock-driven drift; cheap to test, high refutation value",
                prediction="an hour-conditioned position (short 04 UTC / long 06 UTC bar) "
                           "retains sign on validation data",
                test={"entry": "at hour open (04 short, 06 long)", "exit": "hour close",
                      "horizon_bars": 1},
                gross_effect=gross,
            )

    def op_regime_recombination(self) -> None:
        """Conjunction of vol-clustering regime with the streak edge."""
        streak = self.significant.get("OBS-TRENDPERSIST-K3")
        volc = self.significant.get("OBS-VOLCLUST-L1")
        if streak and volc:
            gross = 2 * abs(streak["effect_size"]) * 0.00085 * 1.3
            self._emit(
                "OP-RECOMBINE", ["OBS-TRENDPERSIST-K3", "OBS-VOLCLUST-L1"],
                mechanism="fade 3-bar streaks conditioned on ELEVATED realized volatility "
                          "(50-bar vol above its median): streak exhaustion should be "
                          "stronger when moves are large enough to exhaust",
                what="streak reversal (t=-7.35) recombined with volatility persistence (t=+53)",
                why="conditioning the probability edge on a persistent state variable "
                    "concentrates trades where gross effect exceeds cost",
                prediction="vol-conditioned streak fade beats unconditioned fade net of costs",
                test={"entry": "counter-streak after 3 bars AND vol50 > median",
                      "exit": "next bar close", "horizon_bars": 1},
                gross_effect=gross,
            )

    def op_cost_amortization(self) -> None:
        """
        CYCLE-2 operator, failure-informed (not curve-fitting): cycle-1
        evaluation showed every 1-bar-horizon hypothesis had positive GROSS
        expectancy but died to the fixed 1.1-pip roundtrip cost
        (streak fade gross ~0.19 pips/trade; gap fade ~0.89 pips/trade).
        The mechanical response is to amortize the fixed cost over a longer
        holding period / larger target -- a new, testable structure, generated
        BEFORE looking at internal-validation data (cycle-1 failures were all
        at the TRAIN gate; validation remains unconsumed for these families).
        """
        streak3 = self.significant.get("OBS-TRENDPERSIST-K3")
        if streak3:
            for horizon in (4, 8):
                gross = 2 * abs(streak3["effect_size"]) * 0.00085 * math.sqrt(horizon)
                self._emit(
                    "OP-COST-AMORTIZED", ["OBS-TRENDPERSIST-K3"],
                    mechanism=(f"fade 3-bar streaks and hold {horizon} bars: amortize the "
                               f"fixed roundtrip cost over a {horizon}-hour reversion swing"),
                    what=f"streak anti-persistence (t={streak3['t_stat']}) re-tested at "
                         f"{horizon}-bar horizon after 1-bar horizon proved cost-dominated",
                    why="cycle-1 failure analysis: gross edge positive but < cost at "
                        "1-bar horizon; if reversion persists beyond one bar, expectancy "
                        "scales with horizon while cost stays fixed",
                    prediction=f"{horizon}-bar streak fade clears cost on train AND "
                               f"internal validation",
                    test={"type": "streak_fade", "k": 3, "horizon_bars": horizon},
                    gross_effect=gross,
                )
        gap = self.significant.get("OBS-WKND-GAPFILL")
        if gap:
            for min_gap_pips, hold in ((8, 24), (8, 48)):
                gross = 0.0004 * (0.5 + gap["effect_size"])
                self._emit(
                    "OP-COST-AMORTIZED", ["OBS-WKND-GAPFILL"],
                    mechanism=(f"fade only weekend gaps larger than {min_gap_pips} pips "
                               f"toward Friday close with a {hold}-bar time stop: "
                               f"condition on target size exceeding cost several times over"),
                    what=f"gap-fill tendency (t={gap['t_stat']}) conditioned on gap size "
                         f"after unconditioned version proved cost-marginal",
                    why="cycle-1 failure analysis: median gap 5.1 pips vs 1.1-pip cost "
                        "left ~0 net; large gaps carry proportionally larger targets "
                        "for the same fixed cost",
                    prediction=f"large-gap fade (>{min_gap_pips} pips, {hold}-bar stop) "
                               f"has positive net expectancy on train AND validation",
                    test={"type": "gap_fade", "horizon_bars": hold,
                          "min_gap": min_gap_pips / 10000.0},
                    gross_effect=gross,
                )

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def filter_refuted_families(self) -> None:
        kept: List[DiscoveredHypothesis] = []
        for h in self.candidates:
            blocked = None
            for desc in self.refuted:
                if (is_near_duplicate(h.mechanism, desc)
                        or is_same_mechanism(h.mechanism, desc)
                        or token_jaccard(h.mechanism, desc) >= 0.5):
                    blocked = desc
                    break
            if blocked:
                self.rejections.append({
                    "hyp_id": h.hyp_id, "mechanism": h.mechanism,
                    "reason": f"refuted-family firewall: too similar to known family "
                              f"({blocked[:80]}...)"})
            else:
                kept.append(h)
        self.candidates = kept

    def filter_batch_novelty(self) -> None:
        kept: List[DiscoveredHypothesis] = []
        for h in sorted(self.candidates, key=lambda x: -x.priority):
            dup = any(is_near_duplicate(h.mechanism, k.mechanism) for k in kept)
            if dup:
                self.rejections.append({"hyp_id": h.hyp_id,
                                        "reason": "near-duplicate within batch"})
            else:
                kept.append(h)
        self.candidates = kept

    def apply_budget(self) -> None:
        ordered = sorted(self.candidates, key=lambda x: (-x.priority, x.hyp_id))
        for h in ordered[MAX_HYPOTHESES_PER_CYCLE:]:
            self.rejections.append({"hyp_id": h.hyp_id, "reason": "over budget"})
        self.candidates = ordered[:MAX_HYPOTHESES_PER_CYCLE]

    # ------------------------------------------------------------------
    def run(self) -> List[DiscoveredHypothesis]:
        self.op_streak_reversal()
        self.op_weekend_gap_fade()
        self.op_compression_persistence()
        self.op_session_conditioning()
        self.op_regime_recombination()
        self.op_cost_amortization()
        self.filter_refuted_families()
        self.filter_batch_novelty()
        self.apply_budget()
        return self.candidates

    def save(self, path: Path = DEFAULT_QUEUE) -> Dict:
        payload = {
            "generated_by": "discovery/engine.py (GEN 7)",
            "observation_registry_window": self.payload.get("observation_window"),
            "budget": MAX_HYPOTHESES_PER_CYCLE,
            "assumed_roundtrip_cost": ASSUMED_ROUNDTRIP_COST,
            "queue_size": len(self.candidates),
            "hypotheses": [h.to_dict() for h in self.candidates],
            "rejections": self.rejections,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def main() -> int:
    payload = load_observations()
    engine = DiscoveryEngine(payload, load_refuted_descriptions())
    queue = engine.run()
    engine.save()
    print(f"GEN 7 DISCOVERY: {len(queue)} hypotheses in queue "
          f"({len(engine.rejections)} rejected by filters)")
    for h in queue:
        print(f"  {h.hyp_id}  prio={h.priority:7.2f}  [{h.economic_flag}] "
              f"{h.operator:22s} {h.mechanism[:75]}")
    if engine.rejections:
        print("Rejections:")
        for r in engine.rejections:
            print(f"  - {r.get('hyp_id','(pre-id)')}: {r['reason'][:100]}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
