"""
Real Factory Integration: Connect Idea Machine to actual Strategy Factory gates.

CRITICAL: This uses the REAL gate() function from discovery/cycle8_intraday.py,
not simulation. Every hypothesis is evaluated against actual train/validation data
and real gate thresholds (train t >= 2.0, val t >= 1.5, n >= 30).

For every eligible hypothesis:
1. Create formal pre-registered hypothesis
2. Prepare train/validation split
3. Run through real Factory gates
4. Track survivors
5. Productize if authorized

This module NEVER invents statistics or bypasses gates.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

# Import the REAL gate function from Factory
from discovery.cycle8_intraday import gate, Stats


@dataclass
class GateEvaluation:
    """Result of passing through a Factory gate."""
    hypothesis_id: str
    symbol: str
    driver: Optional[str]
    gate_name: str  # "INTERNAL_VALIDATION", "DISCOVERY_SURVIVOR", "GEN12_ADVERSARIAL", "GEN14_HOLDOUT"

    train_n: int
    train_t: float
    val_n: int
    val_t: float

    verdict: str  # from real gate() function
    reason: str   # from real gate() function
    passed: bool


@dataclass
class FactoryHypothesisJourney:
    """Track a real hypothesis through actual Factory gates."""
    hypothesis_id: str
    source_idea_id: str
    symbol: str
    driver: Optional[str]

    pre_registered_at: str
    gate_evaluations: List[GateEvaluation]

    final_status: str  # "REJECTED", "DISCOVERY_SURVIVOR", "GEN14_AUTHORIZED", "PRODUCTIZED"
    final_reason: str
    generated_ea_product: Optional[str] = None

    def to_dict(self):
        return {
            "hypothesis_id": self.hypothesis_id,
            "source_idea_id": self.source_idea_id,
            "symbol": self.symbol,
            "driver": self.driver,
            "pre_registered_at": self.pre_registered_at,
            "gate_evaluations": [asdict(g) for g in self.gate_evaluations],
            "final_status": self.final_status,
            "final_reason": self.final_reason,
            "generated_ea_product": self.generated_ea_product,
        }


class RealFactoryIntegrator:
    """
    Integrate real hypotheses into actual Factory gates.

    This uses the REAL gate() function and REAL train/validation data,
    never simulation.
    """

    def __init__(self, repo_root: Path = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.factory_dir = self.repo_root / "reports" / "factory"
        self.journeys: List[FactoryHypothesisJourney] = []

    def pre_register_hypothesis(self, hyp_id: str, source_idea_id: str, symbol: str,
                               driver: Optional[str] = None) -> FactoryHypothesisJourney:
        """
        Pre-register a hypothesis for Factory evaluation.

        Pre-registration:
        - Records the hypothesis ID, source, symbol, driver
        - Timestamp marks when it entered the Factory
        - Guarantees the evaluation will be recorded (no silent skips)
        """
        journey = FactoryHypothesisJourney(
            hypothesis_id=hyp_id,
            source_idea_id=source_idea_id,
            symbol=symbol,
            driver=driver,
            pre_registered_at=datetime.utcnow().isoformat(),
            gate_evaluations=[],
            final_status="UNKNOWN",
            final_reason="",
        )
        self.journeys.append(journey)
        return journey

    def evaluate_with_real_gates(self, journey: FactoryHypothesisJourney,
                                 train_stats: Stats, val_stats: Stats) -> bool:
        """
        Evaluate hypothesis using REAL gate() function from cycle8_intraday.py.

        Args:
            journey: Pre-registered hypothesis journey to update
            train_stats: Real training statistics (n, mean_net, t_stat, gross_over_cost)
            val_stats: Real validation statistics

        Returns:
            True if passed INTERNAL_VALIDATION gate, False otherwise

        CRITICAL: This uses the real gate() function, never invents verdicts.
        """
        # Run through the REAL gate function
        verdict, reason = gate(train_stats, val_stats)

        # Record the evaluation
        eval_result = GateEvaluation(
            hypothesis_id=journey.hypothesis_id,
            symbol=journey.symbol,
            driver=journey.driver,
            gate_name="INTERNAL_VALIDATION",
            train_n=train_stats.n,
            train_t=train_stats.t_stat,
            val_n=val_stats.n,
            val_t=val_stats.t_stat,
            verdict=verdict,
            reason=reason,
            passed=(verdict == "DISCOVERY_SURVIVOR")
        )
        journey.gate_evaluations.append(eval_result)

        # Set journey status based on gate result
        if verdict == "DISCOVERY_SURVIVOR":
            journey.final_status = "DISCOVERY_SURVIVOR"
            journey.final_reason = "Passed INTERNAL_VALIDATION gate"
            return True
        else:
            journey.final_status = "REJECTED"
            journey.final_reason = f"Failed INTERNAL_VALIDATION: {reason}"
            return False

    def get_journeys_by_status(self, status: str) -> List[FactoryHypothesisJourney]:
        """Get all journeys with a specific final status."""
        return [j for j in self.journeys if j.final_status == status]

    def save_journeys(self, output_path: Path = None):
        """Save all hypothesis journeys to disk.

        Atomic (temp file + os.replace), matching
        idea_machine.core.store.AppendOnlyStore's write discipline -- a
        crash mid-write leaves the previous file intact rather than
        truncated. This method still fully OVERWRITES its target with only
        this integrator instance's in-memory journeys; it is not a merge, so
        callers running repeated cycles against the same output_path should
        expect the file to reflect only the most recent run's journeys, not
        an accumulation. Duplicate-evaluation protection across runs is the
        job of production.evaluation_ledger.EvaluationLedger, consulted
        BEFORE a hypothesis is ever submitted here.
        """
        import os
        import tempfile

        if output_path is None:
            output_path = self.factory_dir / "hypothesis_journeys.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "saved_at": datetime.utcnow().isoformat(),
            "total_journeys": len(self.journeys),
            "journeys": [j.to_dict() for j in self.journeys]
        }
        fd, tmp = tempfile.mkstemp(dir=str(output_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, output_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get_summary(self) -> Dict:
        """Summary of all hypothesis journeys."""
        return {
            "total_hypotheses": len(self.journeys),
            "rejected": len(self.get_journeys_by_status("REJECTED")),
            "discovery_survivors": len(self.get_journeys_by_status("DISCOVERY_SURVIVOR")),
            "gen14_authorized": len(self.get_journeys_by_status("GEN14_AUTHORIZED")),
            "productized": len(self.get_journeys_by_status("PRODUCTIZED")),
        }
