"""
Factory Integration: Connect Idea Machine output to Strategy Factory discovery.

Takes viable hypotheses and:
1. Adds them to discovery queue OR creates new cycle
2. Runs through Factory gates (internal validation, GEN12, GEN14)
3. Tracks survivors and productization
4. Records results in ledger

This module simulates what WOULD happen if we fed ideas to the Factory,
using the Factory's own governance rules (no bypassing, no p-hacking).
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from idea_machine.hypothesis_mapper import DiscoveryHypothesis


@dataclass
class FactoryGateResult:
    """Result of passing through a Factory gate."""
    hypothesis_id: str
    gate_name: str  # "INTERNAL_VALIDATION", "GEN12", "GEN14"
    passed: bool
    reason: str
    survivor_id: Optional[str] = None


@dataclass
class FactoryIdeaJourney:
    """Track one idea through all Factory gates."""
    hypothesis_id: str
    original_idea_id: str
    symbol: str
    family: str
    
    entered_factory_at: str
    gate_results: List[FactoryGateResult]
    
    final_status: str  # "REJECTED", "SURVIVOR", "GEN14_AUTHORIZED", "PRODUCTIZED"
    final_reason: str
    generated_ea_product: Optional[str] = None
    
    def to_dict(self):
        return {
            "hypothesis_id": self.hypothesis_id,
            "original_idea_id": self.original_idea_id,
            "symbol": self.symbol,
            "family": self.family,
            "entered_factory_at": self.entered_factory_at,
            "gate_results": [asdict(g) for g in self.gate_results],
            "final_status": self.final_status,
            "final_reason": self.final_reason,
            "generated_ea_product": self.generated_ea_product,
        }


class FactorySimulator:
    """Simulate passing ideas through Factory gates (for demonstration)."""
    
    def __init__(self, repo_root: Path = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.factory_dir = self.repo_root / "reports" / "factory"
        self.journeys: List[FactoryIdeaJourney] = []
    
    def simulate_idea_through_factory(self, hypothesis: DiscoveryHypothesis) -> FactoryIdeaJourney:
        """
        Simulate passing a hypothesis through Factory gates.
        
        In reality, this would:
        1. Add to discovery queue
        2. Run discovery cycle (parameter sweep + evaluation)
        3. Check INTERNAL_VALIDATION gate (train t >= 2.0, val t >= 1.5, n >= 30)
        4. If survivor, run GEN12 adversarial
        5. If survives GEN12, freeze for GEN13
        6. If authorized by GEN14, package as EA
        
        Here we simulate with realistic assumptions.
        """
        journey = FactoryIdeaJourney(
            hypothesis_id=hypothesis.hyp_id,
            original_idea_id=hypothesis.source_idea_id,
            symbol=hypothesis.symbol,
            family=hypothesis.family,
            entered_factory_at=datetime.utcnow().isoformat(),
            gate_results=[],
            final_status="UNKNOWN",
            final_reason="",
        )
        
        # Gate 1: Internal Validation (on development data only)
        # Assumption: 5% of ideas pass validation (historical rate)
        passes_validation = self._simulate_validation_gate(hypothesis)
        reason1 = "Passed (t_val >= 1.5, n >= 30)" if passes_validation else "Failed validation (underpowered or sign-flipped)"
        gate1 = FactoryGateResult(
            hypothesis_id=hypothesis.hyp_id,
            gate_name="INTERNAL_VALIDATION",
            passed=passes_validation,
            reason=f"Simulated: {reason1}"
        )
        journey.gate_results.append(gate1)
        
        if not passes_validation:
            journey.final_status = "REJECTED"
            journey.final_reason = "Failed internal validation gate"
            self.journeys.append(journey)
            return journey
        
        # Gate 2: GEN12 Adversarial (stress test)
        # Assumption: 80% of internal-validation survivors survive adversarial
        passes_adversarial = self._simulate_adversarial_gate(hypothesis)
        reason2 = "Survived adversarial stress" if passes_adversarial else "Failed: edge disappears under adversarial conditions"
        gate2 = FactoryGateResult(
            hypothesis_id=hypothesis.hyp_id,
            gate_name="GEN12_ADVERSARIAL",
            passed=passes_adversarial,
            reason=f"Simulated: {reason2}"
        )
        journey.gate_results.append(gate2)
        
        if not passes_adversarial:
            journey.final_status = "REJECTED"
            journey.final_reason = "Failed GEN12 adversarial gate"
            self.journeys.append(journey)
            return journey
        
        # Gate 3: GEN14 Holdout Authorization (one-time consumption)
        # Assumption: 20% of GEN12 survivors pass GEN14
        # (Historical: C2_NFP had 4 candidates, ALL failed GEN14)
        passes_holdout = self._simulate_holdout_gate(hypothesis)
        reason3 = "Authorized for deployment" if passes_holdout else "Holdout test failed (edge does not generalize)"
        gate3 = FactoryGateResult(
            hypothesis_id=hypothesis.hyp_id,
            gate_name="GEN14_HOLDOUT",
            passed=passes_holdout,
            reason=f"Simulated: {reason3}"
        )
        journey.gate_results.append(gate3)
        
        if not passes_holdout:
            journey.final_status = "REJECTED"
            journey.final_reason = "Failed GEN14 sealed-holdout evaluation"
            self.journeys.append(journey)
            return journey
        
        # Productization: Create EA
        ea_product = f"EA-{hypothesis.symbol}-{hypothesis.family.split('-')[-1]}"
        journey.final_status = "PRODUCTIZED"
        journey.final_reason = "Authorized for live deployment"
        journey.generated_ea_product = ea_product
        
        self.journeys.append(journey)
        return journey
    
    def _simulate_validation_gate(self, hypothesis: DiscoveryHypothesis) -> bool:
        """
        Simulate internal validation gate.
        
        Based on Factory history:
        - 86 cumulative hypotheses across 10 cycles
        - Only 5 survived discovery (5.8% pass rate)
        """
        import hashlib
        
        # Deterministic: ideas from "known working families" have higher odds
        family_bonus = 0
        if "SURPRISE" in hypothesis.family:
            family_bonus = 0.15  # SC worked, so extensions more likely
        elif "CALENDAR" in hypothesis.family:
            family_bonus = 0.05  # Calendar effects exist but are small
        
        hash_val = int(hashlib.md5(hypothesis.hyp_id.encode()).hexdigest(), 16)
        rand_val = (hash_val % 100) / 100.0
        
        threshold = 0.05 + family_bonus  # Base 5% + bonus
        return rand_val < threshold
    
    def _simulate_adversarial_gate(self, hypothesis: DiscoveryHypothesis) -> bool:
        """
        Simulate GEN12 adversarial gate.
        High survival rate: 80% of validation survivors survive.
        """
        import hashlib
        
        hash_val = int(hashlib.md5(f"{hypothesis.hyp_id}-adv".encode()).hexdigest(), 16)
        rand_val = (hash_val % 100) / 100.0
        return rand_val < 0.80
    
    def _simulate_holdout_gate(self, hypothesis: DiscoveryHypothesis) -> bool:
        """
        Simulate GEN14 sealed-holdout gate.
        Very low pass rate: ~20% (C2_NFP: 0/4 passed).
        """
        import hashlib
        
        hash_val = int(hashlib.md5(f"{hypothesis.hyp_id}-holdout".encode()).hexdigest(), 16)
        rand_val = (hash_val % 100) / 100.0
        return rand_val < 0.20
    
    def report(self) -> Dict:
        """Generate summary report."""
        return {
            "total_ideas_evaluated": len(self.journeys),
            "rejected": sum(1 for j in self.journeys if j.final_status == "REJECTED"),
            "survivors": sum(1 for j in self.journeys if j.final_status == "SURVIVOR"),
            "gen14_authorized": sum(1 for j in self.journeys if j.final_status != "REJECTED"),
            "productized": sum(1 for j in self.journeys if j.generated_ea_product),
            "journeys_by_symbol": self._group_by_symbol(),
        }
    
    def _group_by_symbol(self) -> Dict[str, int]:
        """Count journeys by symbol."""
        by_symbol = {}
        for journey in self.journeys:
            by_symbol[journey.symbol] = by_symbol.get(journey.symbol, 0) + 1
        return by_symbol
