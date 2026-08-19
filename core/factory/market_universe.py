"""
Generation 6, Phase 6-7: Market Universe Expansion & Cross-Market Independence

Audit of available instruments and classification of cross-market independence.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Set, Dict, Any
from datetime import datetime


class MarketRelationship(Enum):
    """Classification of market relationships."""
    SAME_MARKET = "same_market"  # Exact same instrument
    RELATED_MARKET = "related_market"  # Same currency pair but different timeframe
    CORRELATED_MARKET = "correlated_market"  # Strong historical correlation
    DISTINCT_MARKET = "distinct_market"  # Different base markets (stocks/crypto)
    CROSS_CURRENCY = "cross_currency"  # Crosses that share one leg
    UNKNOWN = "unknown"


class DataAvailability(Enum):
    """Data quality and availability assessment."""
    AVAILABLE = "available"
    LIMITED = "limited"
    ACCESS_FAILED = "access_failed"
    UNKNOWN = "unknown"


@dataclass
class InstrumentProfile:
    """Detailed profile of an instrument."""
    symbol: str
    name: str
    asset_class: str  # forex, stocks, crypto, commodities, etc.
    timezone: str
    market_hours: str  # e.g., "24/5" for forex, "09:30-16:00" for stocks
    base_currency: Optional[str] = None  # for forex
    quote_currency: Optional[str] = None  # for forex
    exchange: Optional[str] = None  # for non-forex

    # Data availability
    data_availability: DataAvailability = DataAvailability.UNKNOWN
    available_timeframes: Set[str] = field(default_factory=set)  # H1, M15, D1, etc.
    earliest_data: Optional[datetime] = None
    latest_data: Optional[datetime] = None
    data_source: Optional[str] = None  # e.g., "dukascopy", "broker_api", etc.

    # Research exposure
    research_exposed: bool = False
    exposure_description: str = ""

    # Market structure
    typical_spread_pips: Optional[float] = None
    typical_volume: Optional[str] = None
    liquidity_profile: str = "unknown"  # high, medium, low, unknown

    # Eligibility
    research_eligible: bool = False
    eligibility_reason: str = ""

    # Feature compatibility
    compatible_features: Set[str] = field(default_factory=set)
    incompatible_features: Set[str] = field(default_factory=set)

    # Audit
    assessed_at: datetime = field(default_factory=datetime.utcnow)
    assessed_by: str = "market_universe_audit"


@dataclass
class CrossMarketClassification:
    """Classification of relationship between two instruments."""
    instrument_a: str
    instrument_b: str
    relationship: MarketRelationship
    correlation_estimate: Optional[float] = None  # historical correlation if known
    reasoning: List[str] = field(default_factory=list)
    independence_strength: str = "unknown"  # strong, moderate, weak, unknown

    def is_independent(self) -> bool:
        """True if markets are sufficiently independent."""
        return self.relationship in {
            MarketRelationship.DISTINCT_MARKET,
            MarketRelationship.UNKNOWN,  # Conservative: unknown = not independent
        }


class MarketUniverseAuditor:
    """Audit available instruments and their relationships."""

    def __init__(self):
        self.instruments: Dict[str, InstrumentProfile] = {}
        self.cross_market_classifications: Dict[tuple, CrossMarketClassification] = {}

    def register_instrument(self, profile: InstrumentProfile) -> None:
        """Register an instrument for audit."""
        self.instruments[profile.symbol] = profile

    def classify_cross_market_relationship(self,
                                          symbol_a: str,
                                          symbol_b: str,
                                          correlation: Optional[float] = None) -> CrossMarketClassification:
        """
        Classify the relationship between two instruments.

        A different symbol does NOT automatically mean independent evidence.
        """
        if symbol_a == symbol_b:
            relationship = MarketRelationship.SAME_MARKET
            reasoning = ["Exact same instrument"]
        elif self._extract_base_currency(symbol_a) == self._extract_base_currency(symbol_b):
            # Same base currency
            relationship = MarketRelationship.CROSS_CURRENCY
            reasoning = [f"Share base currency ({self._extract_base_currency(symbol_a)})"]
        else:
            # Different base instruments
            a_profile = self.instruments.get(symbol_a)
            b_profile = self.instruments.get(symbol_b)

            if a_profile and b_profile:
                if a_profile.asset_class == b_profile.asset_class:
                    if a_profile.asset_class == "forex":
                        relationship = MarketRelationship.DISTINCT_MARKET
                        reasoning = ["Different forex pairs, unrelated bases"]
                    else:
                        relationship = MarketRelationship.DISTINCT_MARKET
                        reasoning = ["Different instruments, same asset class"]
                else:
                    relationship = MarketRelationship.DISTINCT_MARKET
                    reasoning = ["Different asset classes"]
            else:
                relationship = MarketRelationship.UNKNOWN
                reasoning = ["Instrument profile incomplete"]

            # If correlation is known and high, may be correlated despite seeming distinct
            if correlation and correlation > 0.7:
                relationship = MarketRelationship.CORRELATED_MARKET
                reasoning.append(f"Historical correlation {correlation:.2f} suggests relationship")

        independence_strength = "unknown"
        if relationship == MarketRelationship.DISTINCT_MARKET:
            independence_strength = "strong"
        elif relationship in {MarketRelationship.UNKNOWN, MarketRelationship.CORRELATED_MARKET}:
            independence_strength = "weak"
        elif relationship == MarketRelationship.RELATED_MARKET:
            independence_strength = "moderate"

        classification = CrossMarketClassification(
            instrument_a=symbol_a,
            instrument_b=symbol_b,
            relationship=relationship,
            correlation_estimate=correlation,
            reasoning=reasoning,
            independence_strength=independence_strength,
        )

        self.cross_market_classifications[(symbol_a, symbol_b)] = classification
        return classification

    def get_eligible_instruments(self) -> List[str]:
        """Return list of instruments eligible for research."""
        return [
            symbol for symbol, profile in self.instruments.items()
            if profile.research_eligible
        ]

    def _extract_base_currency(self, symbol: str) -> Optional[str]:
        """Extract base currency from symbol (e.g., 'EUR' from 'EURUSD')."""
        # For symbols with slash like 'EUR/USD', split on /
        if '/' in symbol:
            return symbol.split('/')[0]
        # For forex symbols like 'EURUSD', first 3 chars are usually base
        if len(symbol) == 6 and symbol.isupper():
            return symbol[:3]
        return None

    def get_correlated_instruments(self, symbol: str, min_correlation: float = 0.5) -> List[str]:
        """Get instruments with known correlation above threshold."""
        correlated = []
        for (a, b), classification in self.cross_market_classifications.items():
            if a == symbol and classification.correlation_estimate and classification.correlation_estimate > min_correlation:
                correlated.append(b)
            elif b == symbol and classification.correlation_estimate and classification.correlation_estimate > min_correlation:
                correlated.append(a)
        return correlated

    def audit_summary(self) -> Dict[str, Any]:
        """Summary of market universe audit."""
        available = sum(
            1 for p in self.instruments.values()
            if p.data_availability == DataAvailability.AVAILABLE
        )
        research_eligible = sum(
            1 for p in self.instruments.values()
            if p.research_eligible
        )

        return {
            "total_instruments": len(self.instruments),
            "available_data": available,
            "research_eligible": research_eligible,
            "eligible_symbols": self.get_eligible_instruments(),
            "asset_classes": set(p.asset_class for p in self.instruments.values()),
            "cross_market_classifications": len(self.cross_market_classifications),
        }
