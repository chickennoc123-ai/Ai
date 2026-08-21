"""
Economic Feedback: learn from real Strategy Factory results to improve
idea ranking BEFORE spending Factory evaluation budget.

READ-ONLY with respect to the Factory. This module never touches:
  - discovery/ (research code)
  - reports/factory/multiple_testing_ledger.json (ledger)
  - reports/factory/candidate_spec_registry.json (frozen specs)
  - reports/factory/evidence_vault.json (holdout consumption record)
  - discovery/cost_model.py (cost model)
  - any holdout data

It reads reports/factory/discovery_cycles/cycle_*.json (real, already-run
Factory evaluations) and derives deterministic priors that adjust the
IdeaMachine viability score. The adjustment is diagnostic, not predictive
magic: it encodes lessons the Factory has already taught us, e.g. "ideas
whose mechanism requires >2 simultaneous confirmations tend to starve
themselves of trades" -- a fact visible in Cycle 11's own numbers, not an
opinion.

The goal is NOT to make ideas pass the Factory. It is to avoid re-spending
evaluation budget on ideas that share the exact economic signature of
recent failures (cost-dominated, data-starved) when a cheaper diagnostic
could have predicted that outcome from the idea's own description.
"""

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CYCLES_DIR = REPO_ROOT / "reports" / "factory" / "discovery_cycles"


@dataclass
class EconomicLesson:
    """One deterministic, evidence-backed lesson extracted from a real Factory cycle."""
    lesson_id: str
    source_cycle: str
    source_hypothesis: str
    finding: str
    evidence: str
    penalty_signal: str   # what idea-level trait this should penalize/reward
    magnitude: float      # -1.0 (strong penalty) .. +1.0 (strong reward)


@dataclass
class FeedbackReport:
    """Full economic feedback derived from all available real Factory cycles."""
    cycles_read: List[str]
    hypotheses_analyzed: int
    lessons: List[EconomicLesson]
    aggregate_stats: Dict[str, float]


class EconomicFeedbackEngine:
    """
    Reads real discovery-cycle JSON output and derives scoring adjustments.

    Design choice: deterministic rules over historical aggregates, not a
    trained model. This is auditable -- every adjustment traces to a
    specific number in a specific cycle file -- and matches the project's
    existing "no unexplained magic" discipline.
    """

    def __init__(self, cycles_dir: Path = CYCLES_DIR):
        self.cycles_dir = cycles_dir
        self.lessons: List[EconomicLesson] = []
        self.cycles_read: List[str] = []
        self._hyp_count = 0

    def load_and_learn(self) -> FeedbackReport:
        """Read all cycle_*.json files that carry per-hypothesis Factory results."""
        self.lessons = []
        self.cycles_read = []
        self._hyp_count = 0

        for f in sorted(self.cycles_dir.glob("cycle_*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            hyps = data.get("hypotheses")
            if not hyps or not isinstance(hyps, list):
                continue
            # Schema check: idea-machine-shaped hypotheses carry hyp_id + either
            # windows or delays with per-window train/validation Stats. A raw
            # discovery-queue entry (e.g. cycle_01_queue.json) has a "hyp_id"
            # too but no evaluated windows -- require at least one entry with
            # a "windows" or "delays" key to accept the file.
            if not any(("windows" in h) or ("delays" in h) for h in hyps):
                continue
            self.cycles_read.append(f.name)
            self._learn_from_cycle(f.name, data)

        return FeedbackReport(
            cycles_read=self.cycles_read,
            hypotheses_analyzed=self._hyp_count,
            lessons=self.lessons,
            aggregate_stats=self._aggregate_stats(),
        )

    def _learn_from_cycle(self, cycle_name: str, data: Dict):
        for hyp in data.get("hypotheses", []):
            hyp_id = hyp.get("hyp_id", "UNKNOWN")
            n_available = hyp.get("n_events_available", 0)

            # Flatten windows (direct or nested under delays)
            all_windows = list(hyp.get("windows", []))
            for delay_entry in hyp.get("delays", []):
                all_windows.extend(delay_entry.get("windows", []))

            evaluated = [w for w in all_windows if "train" in w]
            if not evaluated:
                continue  # not a gate-evaluated hypothesis in this schema (e.g. a raw discovery-queue entry); skip, don't guess
            self._hyp_count += 1

            no_train_edge = [w for w in evaluated
                            if w.get("verdict") in ("TRAIN_NEGATIVE", "TRAIN_INSIGNIFICANT")]
            underpowered = [w for w in evaluated if w.get("verdict") == "VALIDATION_UNDERPOWERED"]

            # Lesson 1: mechanism shows no real train-side edge (majority of windows).
            # This is the strongest, most useful negative signal: it means the
            # MECHANISM is likely wrong, not merely data-starved -- future ideas
            # that resemble this one's structure should be penalized harder than
            # ideas that are merely data-blocked.
            if len(no_train_edge) >= len(evaluated) * 0.5:
                sign_flips = sum(
                    1 for w in evaluated
                    if w.get("train", {}).get("mean_net", 0) * w.get("validation", {}).get("mean_net", 0) < 0
                )
                self.lessons.append(EconomicLesson(
                    lesson_id=f"LESSON-{hyp_id}-NOEDGE",
                    source_cycle=cycle_name,
                    source_hypothesis=hyp_id,
                    finding=(f"{len(no_train_edge)}/{len(evaluated)} windows show no train-side edge "
                            f"(negative or insignificant mean_net); {sign_flips} train/val sign flips"),
                    evidence=f"n_events_available={n_available}",
                    penalty_signal="NO_TRAIN_SIDE_EDGE",
                    magnitude=-0.7,
                ))

            # Lesson 2: real positive train signal, blocked purely by validation n.
            # This is a DIFFERENT and much less severe situation than lesson 1:
            # the mechanism may be right, just data-starved. Confirmation rate
            # (n_trades / n_events_available) is the direct, measurable cause.
            real_signal_blocked = [
                w for w in underpowered
                if w.get("train", {}).get("t_stat", 0) >= 1.5
            ]
            if real_signal_blocked:
                conf_rates = [w.get("confirmation_rate", 0.0) for w in real_signal_blocked]
                avg_conf = sum(conf_rates) / len(conf_rates) if conf_rates else 0.0
                # Caveat: windows drawn from the same event pool with overlapping
                # window/delay definitions are correlated, not independent draws.
                # >1 window here is NOT >1x the evidence -- report it as one
                # underlying pattern observed through several correlated lenses,
                # not as N independent confirmations (see CYCLE11 report's own
                # explicit caution about this exact overstatement risk).
                correlated_note = (
                    f" (drawn from {n_available} shared events across overlapping windows/delays -- "
                    f"correlated, not independent evidence; treat as ~1 underlying observation, not "
                    f"{len(real_signal_blocked)}x)" if len(real_signal_blocked) > 1 else ""
                )
                self.lessons.append(EconomicLesson(
                    lesson_id=f"LESSON-{hyp_id}-DATABLOCKED",
                    source_cycle=cycle_name,
                    source_hypothesis=hyp_id,
                    finding=(f"{len(real_signal_blocked)} window(s) show train t>=1.5 but fail on "
                            f"validation n<30 (avg confirmation_rate={avg_conf:.3f} of "
                            f"{n_available} available events){correlated_note}"),
                    evidence=json.dumps([{"window": w["window_min"], "train_t": w["train"]["t_stat"],
                                         "val_n": w["validation"]["n"]} for w in real_signal_blocked]),
                    penalty_signal="DATA_EXTENSION_CANDIDATE",
                    magnitude=+0.15,  # mild reward, NOT scaled up by window count -- see caveat above
                ))

            # Lesson 3: confirmation rate as a general predictor of validation power.
            # Any hypothesis whose filter (cross-asset confirm, impulse confirm,
            # etc.) keeps confirmation_rate below ~40% of available events is at
            # structural risk of validation-underpower even with a real train edge,
            # simply from the 80/20 split arithmetic (need val n>=30 => train+val
            # needs >=150 raw confirmed trades at an 80/20 split).
            conf_rates_all = [w.get("confirmation_rate") for w in evaluated if w.get("confirmation_rate") is not None]
            if conf_rates_all:
                avg_conf_all = sum(conf_rates_all) / len(conf_rates_all)
                if avg_conf_all < 0.40 and underpowered:
                    self.lessons.append(EconomicLesson(
                        lesson_id=f"LESSON-{hyp_id}-LOWCONF",
                        source_cycle=cycle_name,
                        source_hypothesis=hyp_id,
                        finding=(f"avg confirmation_rate={avg_conf_all:.3f} across {len(evaluated)} windows; "
                                f"{len(underpowered)} window(s) validation-underpowered as a direct "
                                f"consequence of low confirmation rate on {n_available} raw events"),
                        evidence=f"need >=150 raw confirmed events at 80/20 split to clear val n>=30; "
                                f"got ~{avg_conf_all * n_available:.0f}",
                        penalty_signal="LOW_CONFIRMATION_RATE",
                        magnitude=-0.35,
                    ))

    def _aggregate_stats(self) -> Dict[str, float]:
        if not self.lessons:
            return {}
        by_signal: Dict[str, List[float]] = {}
        for l in self.lessons:
            by_signal.setdefault(l.penalty_signal, []).append(l.magnitude)
        return {sig: round(sum(vals) / len(vals), 3) for sig, vals in by_signal.items()}

    def score_adjustment(self, category: str, mechanism_text: str,
                         n_conditions: int, estimated_events: Optional[int]) -> Dict:
        """
        Compute a deterministic adjustment (-1.0..+1.0 scale, then mapped to
        points) for a NEW idea, using lessons learned from real Factory runs.

        n_conditions: count of simultaneous confirmation requirements the
                     idea's mechanism implies (e.g. cross-asset confirm +
                     impulse check = 2). Caller supplies this from the
                     idea's own description -- not inferred by magic.
        estimated_events: idea's own estimated_trade_count field (raw event
                     count BEFORE any confirmation filter reduces it).
        """
        adjustment = 0.0
        reasons = []

        # Rule 1: multi-condition mechanisms have, in the one real cycle run so
        # far, shown NO real train-side edge more often than they've shown a
        # real-but-blocked signal (2 of 3 vs 1 of 3). This is thin evidence
        # (n=3 hypotheses) -- the penalty is intentionally small and explicitly
        # framed as a weak prior, not a strong rule.
        no_edge_lessons = [l for l in self.lessons if l.penalty_signal == "NO_TRAIN_SIDE_EDGE"]
        if no_edge_lessons and n_conditions >= 2:
            base_rate = len(no_edge_lessons) / max(1, self._hyp_count)
            penalty = -0.15 * min(1.0, base_rate * 3)  # thin-evidence dampening
            adjustment += penalty
            reasons.append(f"{len(no_edge_lessons)}/{self._hyp_count} analyzed hypotheses with "
                          f"multi-condition mechanisms showed no train-side edge at all "
                          f"(weak prior, n is small: {penalty:+.2f})")

        # Rule 2: mechanisms whose confirmation filter is likely to push raw
        # event count below ~150 (the threshold Cycle 11 showed is needed for
        # val n>=30 at an 80/20 split, given typical ~35-45% confirmation
        # rates) risk validation-underpower even with a real edge.
        low_conf_lessons = [l for l in self.lessons if l.penalty_signal == "LOW_CONFIRMATION_RATE"]
        if low_conf_lessons and estimated_events is not None and estimated_events < 150:
            severity = min(1.0, (150 - estimated_events) / 150)
            avg_penalty = sum(l.magnitude for l in low_conf_lessons) / len(low_conf_lessons)
            scaled = avg_penalty * severity
            adjustment += scaled
            reasons.append(f"estimated {estimated_events} raw events, below the ~150 needed "
                          f"post-filter for validation n>=30 at typical confirmation rates "
                          f"({scaled:+.2f})")

        # Rule 3: reward ideas that resemble the one genuinely promising pattern
        # found so far (real train signal, blocked only by data) IF the caller's
        # estimated_events is large enough that the same mechanism might clear
        # n>=30 with more history -- this is intentionally a small, capped reward,
        # not an invitation to retest the exact same hypothesis (that would be
        # p-hacking against the same event pool).
        data_ext_lessons = [l for l in self.lessons if l.penalty_signal == "DATA_EXTENSION_CANDIDATE"]
        if data_ext_lessons and estimated_events is not None and estimated_events >= 150:
            adjustment += 0.1
            reasons.append(f"{len(data_ext_lessons)} prior hypothesis(es) showed real train signal "
                          f"blocked only by data volume; this idea's estimated {estimated_events} "
                          f"events clears the threshold that blocked them (+0.10)")

        return {
            "category": category,
            "n_conditions": n_conditions,
            "estimated_events": estimated_events,
            "raw_adjustment": round(adjustment, 3),
            "score_delta_points": round(adjustment * 25, 1),  # map to same 0-100 scale as viability score
            "reasons": reasons,
        }

    def save_report(self, report: FeedbackReport, out_path: Optional[Path] = None) -> Path:
        out_path = out_path or (REPO_ROOT / "reports" / "idea_machine" / "economic_feedback_report.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cycles_read": report.cycles_read,
            "hypotheses_analyzed": report.hypotheses_analyzed,
            "lessons": [asdict(l) for l in report.lessons],
            "aggregate_stats": report.aggregate_stats,
        }
        out_path.write_text(json.dumps(payload, indent=2))
        return out_path


if __name__ == "__main__":
    engine = EconomicFeedbackEngine()
    report = engine.load_and_learn()
    print(f"Cycles read: {report.cycles_read}")
    print(f"Hypotheses analyzed: {report.hypotheses_analyzed}")
    print(f"Lessons extracted: {len(report.lessons)}")
    for l in report.lessons:
        print(f"  [{l.lesson_id}] {l.finding} (magnitude={l.magnitude:+.2f})")
    print(f"\nAggregate stats: {report.aggregate_stats}")

    path = engine.save_report(report)
    print(f"\nSaved: {path}")

    # Demo: score a hypothetical new idea like HYP-IM-0001's pattern
    print("\n--- Example adjustment (2-condition macro-surprise idea, ~130 events) ---")
    adj = engine.score_adjustment("MACRO_SURPRISE", "cross-asset confirm + impulse check", 2, 130)
    print(json.dumps(adj, indent=2))
