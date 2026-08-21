"""
Idea Machine searcher: Internet research for novel strategy ideas.

Strategy idea categories:
  - MACRO_SURPRISE: Event-driven (surprise reactions, positioning)
  - MICROSTRUCTURE: Order flow, spreads, patterns
  - TECHNICAL: Price patterns, momentum, mean reversion
  - CALENDAR: Anomalies (day/week/month effects)
  - REGIME: Regime detection, switching, filtering
  - CROSS_ASSET: Multi-leg relationships
  - DATA_DEPENDENT: Ideas that need specific data availability

Each idea carries:
  - source: Where it came from (paper, forum, observation)
  - category: Type of idea
  - mechanism: Plain-language description
  - viability_signal: Why it might work
  - data_requirement: What data is needed
  - estimated_samples: How many trades are likely
"""

from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime
import json


@dataclass
class IdeaSource:
    """Where an idea came from."""
    source_type: str  # "paper", "forum", "observation", "synthesis"
    citation: str  # Author/URL/internal reference
    date_discovered: str  # ISO format
    reliability_rank: int  # 1-10, higher = more vetted


@dataclass
class StrategyIdea:
    """A novel strategy idea to be tested."""
    idea_id: str
    category: str  # MACRO_SURPRISE, MICROSTRUCTURE, etc.
    symbol: str  # FX pair or asset
    mechanism: str  # Plain-language description
    viability_signal: str  # Why it might work
    data_requirement: str  # Data needed
    estimated_trade_count: Optional[int]  # How many trades expected?
    source: IdeaSource
    prerequisites: List[str]  # ["need_macro_calendar", "need_m1_prices", etc.]
    created_at: str
    status: str  # "GENERATED", "BLOCKED_DATA", "IN_DISCOVERY", "REJECTED", "SURVIVOR"
    rejection_reason: Optional[str]


class IdeaMachine:
    """Search and synthesize strategy ideas from multiple sources."""
    
    def __init__(self):
        self.ideas: List[StrategyIdea] = []
        self.search_results = []
        
    def generate_seeded_ideas(self) -> List[StrategyIdea]:
        """Generate initial ideas from known patterns and recent research."""
        ideas = []
        
        # Seeded ideas from known categories not yet explored in Factory
        idea_seeds = [
            {
                "category": "MACRO_SURPRISE",
                "symbol": "NZDJPY",
                "mechanism": "Cross-asset surprise confirmation between NZDJPY and ASX200 on employment data",
                "viability_signal": "SC worked on USDJPY/SPX500; NZD employment surprise similar macro event",
                "data_requirement": "NZD employment calendar + NZDJPY M1 + ASX200 M1 price",
                "estimated_trade_count": 15,  # NZ employment ~monthly
                "prerequisites": ["need_nzd_employment_calendar", "need_asx200_m1"]
            },
            {
                "category": "CALENDAR",
                "symbol": "EURUSD",
                "mechanism": "Tuesday-after-NFP mean reversion in Euro (historically softest revert after US data)",
                "viability_signal": "NFP is Thu; Tue is end of normalization window. EUR often reverting at that point.",
                "data_requirement": "Daily EURUSD bars, NFP calendar",
                "estimated_trade_count": 52,  # Weekly
                "prerequisites": ["need_daily_bars"]
            },
            {
                "category": "MICROSTRUCTURE",
                "symbol": "XAUUSD",
                "mechanism": "Bid-ask bounce post-news on gold (flight-to-safety wideness followed by normalization)",
                "viability_signal": "Spread widens on risk events, closes quickly. Fade the initial width.",
                "data_requirement": "XAUUSD tick/M1 data with bid-ask history",
                "estimated_trade_count": None,  # Unknown, data not available
                "prerequisites": ["need_tick_bid_ask"]
            },
            {
                "category": "REGIME",
                "symbol": "GBPUSD",
                "mechanism": "Session-conditioned entry bias: UK-session opens show +t on BOE days, other days flat",
                "viability_signal": "European central bank decisions drive intra-session session behavior",
                "data_requirement": "GBPUSD H1 bars, BOE decision calendar",
                "estimated_trade_count": 60,  # ~Monthly + press conferences
                "prerequisites": ["need_boe_calendar", "need_h1_bars"]
            },
            {
                "category": "CROSS_ASSET",
                "symbol": "USDJPY",
                "mechanism": "Yield-curve inversion detector: DXY vs Jap 10Y correlation shift predicts USD direction",
                "viability_signal": "Macro FX drivers are yield differentials; inversion signals regime change",
                "data_requirement": "DXY daily, Japan 10Y daily, USDJPY daily",
                "estimated_trade_count": 20,  # Regime changes ~quarterly
                "prerequisites": ["need_dxy", "need_japan10y"]
            },
        ]
        
        for i, seed in enumerate(idea_seeds):
            idea_id = f"IDEA-{i+1:03d}-{seed['category'][:4]}"
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
                    citation="Idea Machine: Extension of known successful families",
                    date_discovered=datetime.utcnow().isoformat(),
                    reliability_rank=6
                ),
                prerequisites=seed["prerequisites"],
                created_at=datetime.utcnow().isoformat(),
                status="GENERATED",
                rejection_reason=None
            ))
        
        self.ideas.extend(ideas)
        return ideas
    
    def filter_by_data_availability(self, ideas: List[StrategyIdea]) -> tuple[List[StrategyIdea], List[StrategyIdea]]:
        """
        Split ideas into:
        - viable: all data prerequisites can be satisfied
        - blocked_data: missing required data
        """
        viable = []
        blocked = []
        
        # Data we know we have
        available_data = {
            "daily_bars": True,
            "h1_bars": True,
            "m1_bars": True,
            "nfp_calendar": True,
            "macro_events": True,
            "fx_symbols": ["EURUSD", "GBPUSD", "USDCHF", "USDJPY", "XAUUSD"],
            "index_symbols": ["SPX500", "WTICO"],
            "us10y": True,
        }
        
        for idea in ideas:
            # Check prerequisites
            missing = []
            for prereq in idea.prerequisites:
                if prereq == "need_nzd_employment_calendar":
                    missing.append(prereq)
                elif prereq == "need_asx200_m1":
                    missing.append(prereq)
                elif prereq == "need_tick_bid_ask":
                    missing.append(prereq)
                elif prereq == "need_boe_calendar":
                    missing.append(prereq)
                elif prereq == "need_dxy":
                    missing.append(prereq)
                elif prereq == "need_japan10y":
                    missing.append(prereq)
                elif prereq == "need_daily_bars":
                    pass  # We have this
                elif prereq == "need_h1_bars":
                    pass  # We have this
                elif prereq == "need_m1_bars":
                    pass  # We have this
            
            if missing:
                idea.status = "BLOCKED_DATA"
                idea.rejection_reason = f"Missing data: {', '.join(missing)}"
                blocked.append(idea)
            else:
                viable.append(idea)
        
        return viable, blocked
    
    def estimate_viability(self, idea: StrategyIdea) -> float:
        """
        Score idea viability 0-100.
        Factors:
        - Source reliability (known reliable sources score higher)
        - Data availability
        - Estimated trade count vs min 30
        - Similarity to known working patterns
        """
        score = 0.0
        
        # Source reliability: 0-20 points
        score += idea.source.reliability_rank * 2
        
        # Trade count vs. minimum 30: 0-30 points
        if idea.estimated_trade_count:
            if idea.estimated_trade_count >= 30:
                score += 30
            else:
                score += (idea.estimated_trade_count / 30.0) * 30
        else:
            score += 0  # No trade estimate = risky
        
        # Category fit with existing successful mechanisms: 0-30 points
        if idea.category == "MACRO_SURPRISE":
            score += 25  # SC_SURPRISE_CONFIRMATION worked
        elif idea.category == "CALENDAR":
            score += 20  # Calendar effects are reliable but small
        elif idea.category == "CROSS_ASSET":
            score += 25  # SC used cross-asset confirmation
        elif idea.category == "REGIME":
            score += 15  # Regime detection is hard
        elif idea.category == "MICROSTRUCTURE":
            score += 10  # Microstructure is data-hungry and noisy
        
        # Novelty penalty: -20 points if same symbol/category as known FAILs
        known_fails = [
            ("EURUSD", "CALENDAR"),
            ("USDJPY", "CALENDAR"),
        ]
        for sym, cat in known_fails:
            if idea.symbol == sym and idea.category == cat:
                score -= 10
        
        return max(0.0, min(100.0, score))

    def rank_ideas(self, ideas: List[StrategyIdea]) -> List[tuple[StrategyIdea, float]]:
        """Rank ideas by viability, return sorted list."""
        ranked = [(idea, self.estimate_viability(idea)) for idea in ideas]
        return sorted(ranked, key=lambda x: x[1], reverse=True)
    
    def to_json(self) -> str:
        """Serialize all ideas to JSON."""
        return json.dumps([asdict(idea) for idea in self.ideas], indent=2, default=str)
    
    def summary(self) -> dict:
        """Summary statistics on all ideas."""
        total = len(self.ideas)
        by_status = {}
        for idea in self.ideas:
            by_status[idea.status] = by_status.get(idea.status, 0) + 1
        
        return {
            "total_ideas": total,
            "by_status": by_status,
            "by_category": {cat: sum(1 for i in self.ideas if i.category == cat) 
                          for cat in set(i.category for i in self.ideas)},
        }
