"""
Idea Machine v2: Ideas constrained to available data sources.

After the first cycle, we know:
- We have M1 FX prices (EURUSD, GBPUSD, USDCHF, USDJPY, XAUUSD)
- We have NFP calendar (scheduled US employment events)
- We have daily bars
- We DON'T have: exotic calendars, tick data, alternative indices

Strategy: Mine ideas from what worked in past cycles + novel extensions.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import json

from idea_machine.searcher import IdeaSource, StrategyIdea


class IdeaMachineV2:
    """Generate ideas from known working patterns + safe extensions."""
    
    def __init__(self):
        self.ideas: List[StrategyIdea] = []
    
    def generate_data_constrained_ideas(self) -> List[StrategyIdea]:
        """Generate ideas using ONLY available data."""
        ideas = []
        
        idea_seeds = [
            # Based on SC_SURPRISE_CONFIRMATION success
            {
                "category": "MACRO_SURPRISE",
                "symbol": "GBPUSD",
                "driver": "US10Y",
                "mechanism": "GBP confirmation via US10Y move post-NFP (SC works on GBPUSD/US10Y 5m already)",
                "viability_signal": "SC_SURPRISE_CONFIRMATION found GBPUSD/US10Y works. Add EURUSD/US10Y validation check for robustness.",
                "data_requirement": "GBPUSD M1 + US10Y M1 + NFP calendar (all available)",
                "estimated_trade_count": 60,  # 60 NFP events/year
                "prerequisites": ["have_gbpusd_m1", "have_us10y_m1", "have_nfp_calendar"]
            },
            # Based on B2 month-end effect
            {
                "category": "CALENDAR",
                "symbol": "XAUUSD",
                "mechanism": "Month-end rebalancing: gold + risk-off positioning at month transitions",
                "viability_signal": "Cycle 4 found XAUUSD month-end long survives GEN12 (48h hold). Extend window testing.",
                "data_requirement": "XAUUSD daily bars",
                "estimated_trade_count": 12,  # 12 month-ends/year
                "prerequisites": ["have_xauusd_daily"]
            },
            # Novel: Session-specific patterns on known working pair
            {
                "category": "REGIME",
                "symbol": "EURUSD",
                "mechanism": "European session entry bias: EURUSD opens show different t-stat on US data days vs quiet days",
                "viability_signal": "Session conditioning works for other assets. EURUSD/NFP timing overlap is natural.",
                "data_requirement": "EURUSD hourly bars + NFP calendar",
                "estimated_trade_count": 60,
                "prerequisites": ["have_eurusd_hourly", "have_nfp_calendar"]
            },
            # Novel: Cost recovery angle
            {
                "category": "MICROSTRUCTURE",
                "symbol": "EURUSD",
                "mechanism": "Post-event entry delay realization: wait 5min post-news, then entry if impulse confirms direction (cost amortization)",
                "viability_signal": "SC uses 60s delay. Formalize this as cost-recovery: longer delay = higher prob confirmation = lower total cost",
                "data_requirement": "EURUSD M1 + NFP calendar",
                "estimated_trade_count": 60,
                "prerequisites": ["have_eurusd_m1", "have_nfp_calendar"]
            },
            # Horizon extension of known working idea
            {
                "category": "TECHNICAL",
                "symbol": "XAUUSD",
                "mechanism": "Month-end long horizon extension: test 96h, 120h, 240h windows (not just 48h)",
                "viability_signal": "If 48h works, longer holds might amortize cost further. Test horizons Cycle 2 didn't sweep.",
                "data_requirement": "XAUUSD daily bars",
                "estimated_trade_count": 12,
                "prerequisites": ["have_xauusd_daily"]
            },
        ]
        
        for i, seed in enumerate(idea_seeds):
            idea_id = f"IDEA-V2-{i+1:03d}-{seed['category'][:4]}"
            ideas.append(StrategyIdea(
                idea_id=idea_id,
                category=seed["category"],
                symbol=seed["symbol"],
                mechanism=seed["mechanism"],
                viability_signal=seed["viability_signal"],
                data_requirement=seed["data_requirement"],
                estimated_trade_count=seed["estimated_trade_count"],
                source=IdeaSource(
                    source_type="synthesis",
                    citation="Idea Machine V2: Extensions of known survivors",
                    date_discovered=datetime.utcnow().isoformat(),
                    reliability_rank=8  # Higher reliability (based on working families)
                ),
                prerequisites=seed["prerequisites"],
                created_at=datetime.utcnow().isoformat(),
                status="GENERATED",
                rejection_reason=None
            ))
        
        self.ideas.extend(ideas)
        return ideas
    
    def filter_by_available_data(self, ideas: List[StrategyIdea]) -> tuple[List[StrategyIdea], List[StrategyIdea]]:
        """Filter to only ideas we can test with available data."""
        
        available = {
            "have_gbpusd_m1": True,
            "have_eurusd_m1": True,
            "have_eurusd_hourly": True,
            "have_xauusd_daily": True,
            "have_us10y_m1": True,
            "have_nfp_calendar": True,
        }
        
        viable = []
        blocked = []
        
        for idea in ideas:
            missing = [p for p in idea.prerequisites if not available.get(p, False)]
            
            if missing:
                idea.status = "BLOCKED_DATA"
                idea.rejection_reason = f"Data unavailable: {', '.join(missing)}"
                blocked.append(idea)
            else:
                viable.append(idea)
        
        return viable, blocked

    def rank_ideas(self, ideas):
        """Rank ideas by viability score (0-100)."""
        ranked = [(idea, self._estimate_viability(idea)) for idea in ideas]
        return sorted(ranked, key=lambda x: x[1], reverse=True)
    
    def _estimate_viability(self, idea: StrategyIdea) -> float:
        """Score idea viability 0-100."""
        score = 0.0
        
        # Source reliability: 0-30 points
        score += idea.source.reliability_rank * 3
        
        # Trade count vs minimum 30: 0-30 points
        if idea.estimated_trade_count:
            if idea.estimated_trade_count >= 30:
                score += 30
            else:
                score += (idea.estimated_trade_count / 30.0) * 30
        else:
            score += 10
        
        # Category fit: 0-20 points
        if idea.category == "MACRO_SURPRISE":
            score += 20
        elif idea.category == "CALENDAR":
            score += 15
        elif idea.category in ["MICROSTRUCTURE", "REGIME"]:
            score += 10
        else:
            score += 5
        
        return max(0.0, min(100.0, score))
