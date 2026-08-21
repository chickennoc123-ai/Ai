"""
Hypothesis mapper: Convert StrategyIdea objects into testable discovery hypotheses.

Maps ideas to:
1. Known discovery families (extend existing cycles)
2. New discovery families (novel mechanism types)
3. Parameter sets to sweep over

Output format matches the discovery_queue.json hypothesis schema.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import json
from datetime import datetime

from idea_machine.searcher import StrategyIdea


@dataclass
class DiscoveryHypothesis:
    """Testable hypothesis ready for the discovery pipeline."""
    hyp_id: str
    family: str  # E.g., "MACRO_SURPRISE_EXTENDED", "CALENDAR_REGIONAL"
    symbol: str
    operator: str  # What operation to apply
    mechanism: str  # Plain text mechanism
    testable_prediction: str
    parameters_to_sweep: Dict[str, List]
    min_trades: int
    estimated_gross_effect: Optional[float]
    source_idea_id: str
    created_at: str
    
    def to_dict(self):
        return {
            "hyp_id": self.hyp_id,
            "family": self.family,
            "symbol": self.symbol,
            "operator": self.operator,
            "mechanism": self.mechanism,
            "testable_prediction": self.testable_prediction,
            "parameters_to_sweep": self.parameters_to_sweep,
            "min_trades": self.min_trades,
            "estimated_gross_effect": self.estimated_gross_effect,
            "source_idea_id": self.source_idea_id,
            "created_at": self.created_at,
        }


class HypothesisMapper:
    """Convert strategy ideas to discovery hypotheses."""
    
    def __init__(self):
        self.hypothesis_counter = 1
        self.family_counter = {}
    
    def map_idea_to_hypothesis(self, idea: StrategyIdea) -> Optional[DiscoveryHypothesis]:
        """Convert a single idea to a testable hypothesis."""
        
        if idea.status == "BLOCKED_DATA":
            return None  # Cannot test this idea yet
        
        # Map idea category to discovery family
        family_name = self._determine_family(idea)
        
        # Create hypothesis ID
        hyp_id = f"HYP-IM-{self.hypothesis_counter:04d}"
        self.hypothesis_counter += 1
        
        # Determine what parameters to sweep
        parameters = self._get_parameters_to_sweep(idea)
        
        hypothesis = DiscoveryHypothesis(
            hyp_id=hyp_id,
            family=family_name,
            symbol=idea.symbol,
            operator=self._get_operator(idea),
            mechanism=idea.mechanism,
            testable_prediction=f"{idea.mechanism} implies positive net expectancy on validation data",
            parameters_to_sweep=parameters,
            min_trades=30,
            estimated_gross_effect=None,  # Will be computed by discovery engine
            source_idea_id=idea.idea_id,
            created_at=datetime.utcnow().isoformat()
        )
        
        return hypothesis
    
    def _determine_family(self, idea: StrategyIdea) -> str:
        """Map idea category to discovery family."""
        family_map = {
            "MACRO_SURPRISE": "MACRO_SURPRISE_EXTENDED",
            "CALENDAR": "CALENDAR_REGIONAL",
            "MICROSTRUCTURE": "MICROSTRUCTURE_INTRADAY",
            "REGIME": "REGIME_CONDITIONAL",
            "CROSS_ASSET": "CROSS_ASSET_CONFIRMATION",
        }
        
        base_family = family_map.get(idea.category, "UNKNOWN_FAMILY")
        
        # Add symbol specificity
        return f"{base_family}-{idea.symbol}"
    
    def _get_operator(self, idea: StrategyIdea) -> str:
        """Determine the discovery operator type."""
        op_map = {
            "MACRO_SURPRISE": "OP-CROSS-ASSET-CONFIRM",
            "CALENDAR": "OP-CALENDAR-ANOMALY",
            "MICROSTRUCTURE": "OP-SPREAD-FADE",
            "REGIME": "OP-REGIME-FILTER",
            "CROSS_ASSET": "OP-YIELD-DIFFERENTIAL",
        }
        return op_map.get(idea.category, "OP-UNKNOWN")
    
    def _get_parameters_to_sweep(self, idea: StrategyIdea) -> Dict[str, List]:
        """Determine parameter space to sweep."""
        
        params = {
            "entry_delay_sec": [0, 30, 60, 120],  # Response latency
            "exit_window_min": [5, 15, 30, 60, 240],  # Hold period
        }
        
        # Add category-specific parameters
        if idea.category == "MACRO_SURPRISE":
            params["impulse_window_min"] = [5, 10, 15]  # Cross-asset confirmation window
            params["min_move_pips"] = [5, 10, 20]  # Min driver move to confirm
        elif idea.category == "CALENDAR":
            params["pre_window_h"] = [4, 8, 24]  # Hours before event
            params["post_window_h"] = [4, 8, 24]  # Hours after event
        elif idea.category == "REGIME":
            params["lookback_bars"] = [20, 50, 100]  # Regime detection window
            params["threshold_std"] = [1.0, 1.5, 2.0]  # Std dev thresholds
        elif idea.category == "CROSS_ASSET":
            params["correlation_lookback"] = [20, 50, 100]
            params["corr_threshold"] = [0.3, 0.5, 0.7]
        
        return params
    
    def map_batch(self, ideas: List[StrategyIdea]) -> List[DiscoveryHypothesis]:
        """Convert all viable ideas to hypotheses."""
        hypotheses = []
        for idea in ideas:
            if idea.status in ["GENERATED", "IN_DISCOVERY"]:
                h = self.map_idea_to_hypothesis(idea)
                if h:
                    hypotheses.append(h)
        return hypotheses
