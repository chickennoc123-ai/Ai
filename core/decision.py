"""Capital allocation and position sizing.

The decision engine converts validation evidence into risk capital:

1. A **fractional Kelly** stake is computed from the win rate and payoff ratio.
2. It is **haircut for uncertainty** using the PBO, the walk-forward efficiency
   and the number of trades observed (a small sample is heavily discounted).
3. Allocations are **de-correlated**: strategies whose returns move together
   share a single risk budget.
4. Hard caps from ``config.yaml`` are applied last.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from core.lifecycle import LifecycleManager
from core.utils import (
    InstrumentSpec,
    PerformanceMetrics,
    get_instrument,
    lots_for_risk,
    required_margin,
)
from utils.config import Config, get_config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AllocationDecision:
    """Capital allocation granted to a single strategy."""

    strategy_id: str
    strategy_name: str
    symbol: str
    raw_kelly: float
    penalised_kelly: float
    correlation_penalty: float
    lifecycle_multiplier: float
    allocation: float
    capital: float
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the decision."""
        return asdict(self)


@dataclass
class SizingDecision:
    """Concrete order size derived from an allocation."""

    symbol: str
    volume: float
    risk_amount: float
    stop_distance: float
    margin_required: float
    capped_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the sizing decision."""
        return asdict(self)


class DecisionEngine:
    """Turns validated strategies into capital allocations and lot sizes."""

    def __init__(self, config: Optional[Config] = None, lifecycle: Optional[LifecycleManager] = None) -> None:
        """Initialise the engine from configuration."""
        self.config = config or get_config()
        self.lifecycle = lifecycle
        self.kelly_fraction = self.config.get_float("decision.kelly_fraction", 0.25)
        self.uncertainty_penalty = self.config.get_float("decision.uncertainty_penalty", 0.5)
        self.max_correlation = self.config.get_float("decision.max_correlation", 0.7)
        self.min_allocation = self.config.get_float("decision.min_allocation", 0.01)
        self.max_allocation = self.config.get_float("decision.max_allocation", 0.2)
        self.max_total = self.config.get_float("strategies.max_total_allocation", 1.0)
        self.leverage = self.config.get_float("broker.xmtrading.leverage", 500.0)

    # -- Kelly ---------------------------------------------------------------
    @staticmethod
    def kelly_criterion(win_rate: float, payoff_ratio: float) -> float:
        """Return the full Kelly stake for a binary bet.

        Args:
            win_rate: Probability of a winning trade in ``[0, 1]``.
            payoff_ratio: Average win divided by average loss.

        Returns:
            The Kelly fraction, floored at ``0`` when the edge is negative.
        """
        if payoff_ratio <= 0 or not 0.0 < win_rate < 1.0:
            return 0.0
        kelly = win_rate - (1.0 - win_rate) / payoff_ratio
        return float(max(kelly, 0.0))

    def uncertainty_haircut(
        self,
        trades: int,
        pbo: float = 0.5,
        wfa_efficiency: float = 0.0,
        validation_score: float = 0.5,
    ) -> float:
        """Return a multiplier in ``[0, 1]`` reflecting confidence in the edge.

        Args:
            trades: Number of trades observed.
            pbo: Probability of backtest overfitting.
            wfa_efficiency: Out-of-sample over in-sample Sharpe ratio.
            validation_score: Composite validation score.
        """
        # Sample size: 100 trades gives ~0.9, 30 trades ~0.72, 10 trades ~0.5.
        sample_factor = trades / (trades + 12.0) if trades > 0 else 0.0
        pbo_factor = max(0.0, 1.0 - 2.0 * max(pbo - 0.25, 0.0))
        wfa_factor = min(max(wfa_efficiency, 0.0), 1.0) ** 0.5
        score_factor = min(max(validation_score, 0.0), 1.0)
        blended = sample_factor * (0.4 * pbo_factor + 0.3 * wfa_factor + 0.3 * score_factor)
        return float(min(max(blended, 0.0), 1.0)) ** self.uncertainty_penalty

    def calculate_allocation(
        self,
        strategy_id: str,
        strategy_name: str,
        symbol: str,
        metrics: PerformanceMetrics | Mapping[str, float],
        validation: Optional[Mapping[str, Any]] = None,
        total_capital: float = 10_000.0,
    ) -> AllocationDecision:
        """Compute the capital allocation for one strategy.

        Args:
            strategy_id: Strategy identifier.
            strategy_name: Human readable name.
            symbol: Traded instrument.
            metrics: Performance metrics of the strategy.
            validation: Optional validation report dictionary.
            total_capital: Account capital available for allocation.

        Returns:
            An :class:`AllocationDecision`.
        """
        payload = metrics.to_dict() if isinstance(metrics, PerformanceMetrics) else dict(metrics)
        win_rate = float(payload.get("win_rate", 0.0))
        payoff = float(payload.get("payoff_ratio", 0.0))
        trades = int(payload.get("trades", 0))
        reasons: List[str] = []

        raw_kelly = self.kelly_criterion(win_rate, payoff)
        if raw_kelly <= 0:
            reasons.append("No positive Kelly edge")

        report = dict(validation or {})
        pbo_section = report.get("pbo")
        # An uncomputed PBO is "unknown", not "certainly overfit": treat it as
        # the neutral 0.5 so a quick validation pass does not zero every stake.
        if isinstance(pbo_section, Mapping) and pbo_section.get("computed"):
            pbo = float(pbo_section.get("pbo", 0.5))
        else:
            pbo = 0.5
        wfa = (
            float((report.get("walk_forward") or {}).get("efficiency", 0.0))
            if isinstance(report.get("walk_forward"), Mapping)
            else 0.0
        )
        score = float(report.get("score", 0.5))

        haircut = self.uncertainty_haircut(trades, pbo, wfa, score)
        penalised = raw_kelly * self.kelly_fraction * haircut
        if haircut < 0.4:
            reasons.append(f"Heavy uncertainty haircut ({haircut:.2f})")

        lifecycle_multiplier = 1.0
        if self.lifecycle is not None:
            lifecycle_multiplier = self.lifecycle.allocation_multiplier(strategy_id)
            if lifecycle_multiplier < 1.0:
                reasons.append(f"Lifecycle state limits allocation to {lifecycle_multiplier:.0%}")

        allocation = penalised * lifecycle_multiplier
        if allocation > self.max_allocation:
            allocation = self.max_allocation
            reasons.append(f"Capped at max allocation {self.max_allocation:.0%}")
        if allocation < self.min_allocation:
            if allocation > 0:
                reasons.append(f"Below minimum allocation {self.min_allocation:.0%}")
            allocation = 0.0

        # Report capital from the rounded allocation so the two always agree.
        rounded_allocation = round(allocation, 4)
        return AllocationDecision(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            symbol=symbol,
            raw_kelly=round(raw_kelly, 4),
            penalised_kelly=round(penalised, 4),
            correlation_penalty=1.0,
            lifecycle_multiplier=lifecycle_multiplier,
            allocation=rounded_allocation,
            capital=round(rounded_allocation * total_capital, 2),
            reasons=reasons,
        )

    # -- portfolio construction ---------------------------------------------
    def allocate_portfolio(
        self,
        candidates: Sequence[Mapping[str, Any]],
        total_capital: float = 10_000.0,
        returns: Optional[Mapping[str, Sequence[float]]] = None,
    ) -> List[AllocationDecision]:
        """Allocate capital across several strategies with correlation control.

        Args:
            candidates: Sequence of mappings with ``strategy_id``,
                ``strategy_name``, ``symbol``, ``metrics`` and optional
                ``validation``.
            total_capital: Capital to distribute.
            returns: Optional per-strategy return series used to build the
                correlation matrix.

        Returns:
            A list of :class:`AllocationDecision`, largest allocation first.
        """
        decisions: List[AllocationDecision] = []
        for candidate in candidates:
            decisions.append(
                self.calculate_allocation(
                    strategy_id=str(candidate.get("strategy_id", "")),
                    strategy_name=str(candidate.get("strategy_name", "")),
                    symbol=str(candidate.get("symbol", "")),
                    metrics=candidate.get("metrics", {}),
                    validation=candidate.get("validation"),
                    total_capital=total_capital,
                )
            )

        if returns:
            self._apply_correlation_penalty(decisions, returns)
        self._normalise(decisions, total_capital)
        decisions.sort(key=lambda item: item.allocation, reverse=True)
        logger.info(
            "Portfolio allocation computed",
            strategies=len(decisions),
            deployed=sum(1 for item in decisions if item.allocation > 0),
            gross_allocation=round(sum(item.allocation for item in decisions), 4),
        )
        return decisions

    def _apply_correlation_penalty(
        self, decisions: List[AllocationDecision], returns: Mapping[str, Sequence[float]]
    ) -> None:
        """Shrink allocations of strategies that duplicate each other's risk."""
        frame = pd.DataFrame(
            {key: pd.Series(list(values), dtype="float64") for key, values in returns.items()}
        )
        if frame.shape[1] < 2:
            return
        correlation = frame.corr().fillna(0.0)
        for decision in decisions:
            if decision.strategy_id not in correlation.columns or decision.allocation <= 0:
                continue
            peers = correlation[decision.strategy_id].drop(labels=[decision.strategy_id], errors="ignore")
            crowded = peers[peers.abs() >= self.max_correlation]
            if crowded.empty:
                continue
            penalty = 1.0 / (1.0 + float(crowded.abs().sum()))
            decision.correlation_penalty = round(penalty, 4)
            decision.allocation = round(decision.allocation * penalty, 4)
            # `_normalise` recomputes `capital` from the final allocation.
            decision.reasons.append(
                f"Correlated with {len(crowded)} strategy(ies), allocation scaled by {penalty:.2f}"
            )

    def _normalise(self, decisions: List[AllocationDecision], total_capital: float) -> None:
        """Scale allocations so the gross exposure respects the global cap."""
        gross = sum(decision.allocation for decision in decisions)
        if gross > self.max_total and gross > 0:
            scale = self.max_total / gross
            for decision in decisions:
                decision.allocation = round(decision.allocation * scale, 4)
                decision.reasons.append(f"Scaled by {scale:.2f} to respect the total allocation cap")
        for decision in decisions:
            decision.capital = round(decision.allocation * total_capital, 2)

    # -- position sizing -----------------------------------------------------
    def get_position_sizing(
        self,
        symbol: str,
        allocation_capital: float,
        entry_price: float,
        stop_price: Optional[float],
        risk_per_trade: Optional[float] = None,
        equity: Optional[float] = None,
    ) -> SizingDecision:
        """Convert an allocation into a broker-ready lot size.

        Args:
            symbol: Instrument to trade.
            allocation_capital: Capital assigned to the strategy.
            entry_price: Intended entry price.
            stop_price: Protective stop; a 1% default distance is used when
                omitted.
            risk_per_trade: Fraction of the allocation risked on this trade.
            equity: Account equity, used for the margin check.

        Returns:
            A :class:`SizingDecision` with the normalised volume.
        """
        spec: InstrumentSpec = get_instrument(symbol)
        risk_fraction = risk_per_trade if risk_per_trade is not None else self.config.get_float(
            "backtest.risk_per_trade", 0.01
        )
        stop_distance = abs(entry_price - stop_price) if stop_price else entry_price * 0.01
        if stop_distance <= 0:
            stop_distance = entry_price * 0.01

        volume = lots_for_risk(spec, allocation_capital, risk_fraction, stop_distance, entry_price)
        capped_by = ""

        available_equity = equity if equity is not None else allocation_capital
        margin = required_margin(spec, entry_price, max(volume, spec.min_lot), self.leverage)
        if volume > 0 and margin > available_equity * 0.5:
            affordable = spec.normalize_volume(
                volume * (available_equity * 0.5) / max(margin, 1e-9)
            )
            if affordable < volume:
                volume = affordable
                capped_by = "margin"
        if volume > spec.max_lot:
            volume = spec.max_lot
            capped_by = "max_lot"

        return SizingDecision(
            symbol=spec.symbol,
            volume=round(volume, 2),
            risk_amount=round(allocation_capital * risk_fraction, 2),
            stop_distance=round(stop_distance, spec.digits),
            margin_required=round(required_margin(spec, entry_price, volume, self.leverage), 2),
            capped_by=capped_by,
        )

    # -- risk budgeting ------------------------------------------------------
    @staticmethod
    def risk_parity_weights(returns: Mapping[str, Sequence[float]]) -> Dict[str, float]:
        """Return inverse-volatility weights for a set of return series."""
        volatilities: Dict[str, float] = {}
        for key, values in returns.items():
            series = pd.Series(list(values), dtype="float64")
            volatility = float(series.std(ddof=1)) if len(series) > 1 else 0.0
            volatilities[key] = volatility if volatility > 1e-12 else math.inf
        inverse = {key: 1.0 / value for key, value in volatilities.items()}
        total = sum(value for value in inverse.values() if np.isfinite(value))
        if total <= 0:
            equal = 1.0 / max(len(returns), 1)
            return {key: equal for key in returns}
        return {key: (value / total if np.isfinite(value) else 0.0) for key, value in inverse.items()}
