"""
Idea Machine cycle runner: Orchestrate end-to-end discovery cycle.

Flow:
1. Generate ideas from seeded patterns + internet search
2. Filter by data availability (mark BLOCKED_DATA if needed)
3. Rank by viability
4. Convert to discovery hypotheses
5. Add to discovery queue or new cycle
6. Run discovery evaluation
7. Track survivors and products
8. Record results for next iteration
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict

from idea_machine.searcher import IdeaMachine, StrategyIdea
from idea_machine.hypothesis_mapper import HypothesisMapper, DiscoveryHypothesis


@dataclass
class CycleMetrics:
    """Track metrics through the idea → product pipeline."""
    cycle_id: str
    started_at: str
    
    # Stage 1: Idea generation
    ideas_generated: int
    ideas_from_internet: int
    ideas_from_seeding: int
    
    # Stage 2: Pre-Factory filtering
    ideas_viable_data: int
    ideas_blocked_data: int
    blocked_reasons: Dict[str, int]
    
    # Stage 3: Ranking
    ideas_ranked: int
    top_tier_ideas: int  # Score >= 50
    
    # Stage 4: Hypothesis conversion
    hypotheses_created: int
    hypotheses_with_params: int
    
    # Stage 5: Factory discovery
    hypotheses_evaluated: int
    evaluations_passed_train: int
    evaluations_passed_validation: int
    
    # Stage 6: Survivors
    discovery_survivors: int
    gen12_survivors: int
    gen14_authorized: int
    
    # Stage 7: Productization
    ea_products_created: int
    
    # Bottlenecks
    bottlenecks: List[str]
    errors: List[str]
    
    def summary(self) -> str:
        return f"""
Idea Machine Cycle {self.cycle_id}
============================
Started: {self.started_at}

Stage 1: Idea Generation
  Total ideas: {self.ideas_generated}
  From seeding: {self.ideas_from_seeding}
  From internet: {self.ideas_from_internet}

Stage 2: Data Filtering
  Viable: {self.ideas_viable_data}
  Blocked: {self.ideas_blocked_data}
  Blocking reasons: {self.blocked_reasons}

Stage 3: Ranking
  Ideas ranked: {self.ideas_ranked}
  Top tier (score >= 50): {self.top_tier_ideas}

Stage 4: Hypothesis Conversion
  Hypotheses created: {self.hypotheses_created}
  With parameter sweeps: {self.hypotheses_with_params}

Stage 5: Factory Discovery
  Evaluated: {self.hypotheses_evaluated}
  Passed train gate: {self.evaluations_passed_train}
  Passed validation gate: {self.evaluations_passed_validation}

Stage 6: Survivors
  Discovery survivors: {self.discovery_survivors}
  GEN12 survivors: {self.gen12_survivors}
  GEN14 authorized: {self.gen14_authorized}

Stage 7: Productization
  EA products created: {self.ea_products_created}

Bottlenecks:
{chr(10).join('  - ' + b for b in self.bottlenecks)}

Errors:
{chr(10).join('  - ' + e for e in self.errors)}
"""


class IdeaMachineCycleRunner:
    """Run a complete idea → discovery → product cycle."""
    
    def __init__(self, repo_root: Path = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.ideas_dir = self.repo_root / "reports" / "idea_machine"
        self.ideas_dir.mkdir(parents=True, exist_ok=True)
        
        self.cycle_id = f"CYCLE-IM-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        self.metrics = CycleMetrics(
            cycle_id=self.cycle_id,
            started_at=datetime.utcnow().isoformat(),
            ideas_generated=0,
            ideas_from_internet=0,
            ideas_from_seeding=0,
            ideas_viable_data=0,
            ideas_blocked_data=0,
            blocked_reasons={},
            ideas_ranked=0,
            top_tier_ideas=0,
            hypotheses_created=0,
            hypotheses_with_params=0,
            hypotheses_evaluated=0,
            evaluations_passed_train=0,
            evaluations_passed_validation=0,
            discovery_survivors=0,
            gen12_survivors=0,
            gen14_authorized=0,
            ea_products_created=0,
            bottlenecks=[],
            errors=[],
        )
        
        self.machine = IdeaMachine()
        self.mapper = HypothesisMapper()
    
    def run(self) -> CycleMetrics:
        """Execute the full cycle."""
        try:
            # Stage 1: Generate ideas
            self._stage_generate_ideas()
            
            # Stage 2: Filter by data availability
            self._stage_filter_by_data()
            
            # Stage 3: Rank ideas
            self._stage_rank_ideas()
            
            # Stage 4: Convert to hypotheses
            self._stage_convert_to_hypotheses()
            
            # Stage 5-7: Would integrate with actual Factory in full implementation
            # For now, report what would happen
            self._stage_report_findings()
            
        except Exception as e:
            self.metrics.errors.append(str(e))
        
        return self.metrics
    
    def _stage_generate_ideas(self):
        """Stage 1: Generate ideas from seeded patterns."""
        try:
            seeded_ideas = self.machine.generate_seeded_ideas()
            self.metrics.ideas_from_seeding = len(seeded_ideas)
            self.metrics.ideas_generated = len(seeded_ideas)
        except Exception as e:
            self.metrics.errors.append(f"Idea generation failed: {e}")
    
    def _stage_filter_by_data(self):
        """Stage 2: Filter ideas by data availability."""
        try:
            viable, blocked = self.machine.filter_by_data_availability(self.machine.ideas)
            
            self.metrics.ideas_viable_data = len(viable)
            self.metrics.ideas_blocked_data = len(blocked)
            
            # Count blocking reasons
            for idea in blocked:
                reason = idea.rejection_reason or "unknown"
                self.metrics.blocked_reasons[reason] = self.metrics.blocked_reasons.get(reason, 0) + 1
            
            # Flag as bottleneck if >50% blocked
            if self.metrics.ideas_generated > 0:
                block_rate = self.metrics.ideas_blocked_data / self.metrics.ideas_generated
                if block_rate > 0.5:
                    self.metrics.bottlenecks.append(
                        f"Data availability: {block_rate*100:.1f}% of ideas blocked (need exotic data)"
                    )
        except Exception as e:
            self.metrics.errors.append(f"Data filtering failed: {e}")
    
    def _stage_rank_ideas(self):
        """Stage 3: Rank viable ideas by viability score."""
        try:
            viable_ideas = [i for i in self.machine.ideas if i.status == "GENERATED"]
            ranked = self.machine.rank_ideas(viable_ideas)
            
            self.metrics.ideas_ranked = len(ranked)
            self.metrics.top_tier_ideas = sum(1 for _, score in ranked if score >= 50)
            
            # Report top 5
            print("\nTop ideas by viability:")
            for i, (idea, score) in enumerate(ranked[:5]):
                print(f"  {i+1}. {idea.idea_id}: {idea.mechanism[:60]}... (score={score:.1f})")
                idea.status = "IN_DISCOVERY"  # Mark for next stage
        except Exception as e:
            self.metrics.errors.append(f"Ranking failed: {e}")
    
    def _stage_convert_to_hypotheses(self):
        """Stage 4: Convert ideas to discovery hypotheses."""
        try:
            hypotheses = self.mapper.map_batch(self.machine.ideas)
            self.metrics.hypotheses_created = len(hypotheses)
            self.metrics.hypotheses_with_params = len([h for h in hypotheses 
                                                       if h.parameters_to_sweep])
            
            # Save hypotheses
            hyp_file = self.ideas_dir / f"{self.cycle_id}_hypotheses.json"
            with open(hyp_file, 'w') as f:
                json.dump([h.to_dict() for h in hypotheses], f, indent=2, default=str)
            
            print(f"\nSaved {len(hypotheses)} hypotheses to {hyp_file}")
        except Exception as e:
            self.metrics.errors.append(f"Hypothesis conversion failed: {e}")
    
    def _stage_report_findings(self):
        """Stage 5-7: Report findings and recommendations."""
        try:
            # Check for data blockers
            if self.metrics.ideas_blocked_data > 0:
                self.metrics.bottlenecks.append(
                    f"Missing data sources: {list(self.metrics.blocked_reasons.keys())}"
                )
            
            # Check for low idea quality
            if self.metrics.top_tier_ideas == 0:
                self.metrics.bottlenecks.append(
                    "No top-tier ideas generated (all score < 50). Need better idea sources."
                )
            
            # Estimate Factory throughput
            if self.metrics.hypotheses_created > 0:
                print(f"\nEstimated Factory impact:")
                print(f"  Created {self.metrics.hypotheses_created} new hypotheses")
                print(f"  Parameter space: {sum(self._estimate_param_combinations(self.machine.ideas))}")
        except Exception as e:
            self.metrics.errors.append(f"Reporting failed: {e}")
    
    def _estimate_param_combinations(self, ideas: List[StrategyIdea]) -> List[int]:
        """Estimate parameter sweep size for each idea."""
        counts = []
        for idea in ideas:
            if idea.status in ["GENERATED", "IN_DISCOVERY"]:
                h = self.mapper.map_idea_to_hypothesis(idea)
                if h:
                    combinations = 1
                    for param_list in h.parameters_to_sweep.values():
                        combinations *= len(param_list)
                    counts.append(combinations)
        return counts
    
    def save_cycle_report(self):
        """Save cycle metrics and ideas to disk."""
        # Save metrics
        metrics_file = self.ideas_dir / f"{self.cycle_id}_metrics.json"
        with open(metrics_file, 'w') as f:
            json.dump(asdict(self.metrics), f, indent=2, default=str)
        
        # Save ideas
        ideas_file = self.ideas_dir / f"{self.cycle_id}_ideas.json"
        with open(ideas_file, 'w') as f:
            json.dump(self.machine.to_json(), f, indent=2)
        
        # Save summary
        summary_file = self.ideas_dir / f"{self.cycle_id}_summary.txt"
        with open(summary_file, 'w') as f:
            f.write(self.metrics.summary())
        
        print(f"\nCycle report saved to {self.ideas_dir}/{self.cycle_id}_*")
        return metrics_file, ideas_file, summary_file


if __name__ == "__main__":
    runner = IdeaMachineCycleRunner()
    metrics = runner.run()
    runner.save_cycle_report()
    print(metrics.summary())
