"""Strategy lifecycle management.

Every deployed strategy moves through four states:

``ACTIVE``
    Trading with its full allocation.
``DEGRADED``
    Underperforming; allocation is cut but the strategy keeps trading so it can
    prove itself again.
``PAUSED``
    Signals are ignored, positions are closed. The strategy is monitored on
    paper only.
``RETIRED``
    Permanently switched off.

Transitions use hysteresis (a recovery threshold above the degradation
threshold) and a minimum dwell time, which prevents a strategy from
oscillating between states on noise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from core.utils import PerformanceMetrics
from utils.config import Config, get_config
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class LifecycleState(str, Enum):
    """Possible lifecycle states of a strategy."""

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"

    @property
    def tradable(self) -> bool:
        """``True`` when the state still allows new positions."""
        return self in (LifecycleState.ACTIVE, LifecycleState.DEGRADED)

    @property
    def allocation_multiplier(self) -> float:
        """Fraction of the nominal allocation granted in this state."""
        return {
            LifecycleState.ACTIVE: 1.0,
            LifecycleState.DEGRADED: 0.4,
            LifecycleState.PAUSED: 0.0,
            LifecycleState.RETIRED: 0.0,
        }[self]


@dataclass
class LifecycleTransition:
    """A recorded state change."""

    strategy_id: str
    from_state: str
    to_state: str
    reason: str
    timestamp: datetime = field(default_factory=utcnow)
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the transition."""
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


@dataclass
class StrategyLifecycle:
    """Lifecycle bookkeeping for a single strategy."""

    strategy_id: str
    state: LifecycleState = LifecycleState.ACTIVE
    since: datetime = field(default_factory=utcnow)
    reason: str = "Initial registration"
    last_evaluated: Optional[datetime] = None
    evaluations: int = 0
    consecutive_bad: int = 0
    consecutive_good: int = 0
    best_sharpe: float = 0.0
    history: List[LifecycleTransition] = field(default_factory=list)

    @property
    def days_in_state(self) -> float:
        """Number of days spent in the current state."""
        return (utcnow() - self.since).total_seconds() / 86400.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the lifecycle record."""
        return {
            "strategy_id": self.strategy_id,
            "state": self.state.value,
            "since": self.since.isoformat(),
            "reason": self.reason,
            "days_in_state": round(self.days_in_state, 2),
            "evaluations": self.evaluations,
            "consecutive_bad": self.consecutive_bad,
            "consecutive_good": self.consecutive_good,
            "best_sharpe": round(self.best_sharpe, 3),
            "allocation_multiplier": self.state.allocation_multiplier,
            "history": [item.to_dict() for item in self.history[-20:]],
        }


class LifecycleManager:
    """Applies the lifecycle policy to a population of strategies."""

    STATES = [state.value for state in LifecycleState]

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialise thresholds from configuration."""
        cfg = config or get_config()
        self.degraded_sharpe = cfg.get_float("lifecycle.degraded_sharpe", 0.5)
        self.paused_sharpe = cfg.get_float("lifecycle.paused_sharpe", 0.0)
        self.recovery_sharpe = cfg.get_float("lifecycle.recovery_sharpe", 0.75)
        self.retire_after_days = cfg.get_float("lifecycle.retire_after_days", 90)
        self.min_trades = cfg.get_int("lifecycle.evaluation_window_trades", 30)
        self.min_dwell_days = cfg.get_float("lifecycle.min_dwell_days", 1.0)
        self._records: Dict[str, StrategyLifecycle] = {}

    # -- registration --------------------------------------------------------
    def register(
        self, strategy_id: str, state: LifecycleState = LifecycleState.ACTIVE, reason: str = "Registered"
    ) -> StrategyLifecycle:
        """Register a strategy, returning the existing record when present."""
        if strategy_id not in self._records:
            self._records[strategy_id] = StrategyLifecycle(strategy_id=strategy_id, state=state, reason=reason)
            logger.info("Strategy registered in lifecycle", strategy_id=strategy_id, state=state.value)
        return self._records[strategy_id]

    def get(self, strategy_id: str) -> StrategyLifecycle:
        """Return (creating if needed) the lifecycle record of a strategy."""
        return self.register(strategy_id)

    def get_strategy_status(self, strategy_id: str) -> Dict[str, Any]:
        """Return the current state and reason of a strategy."""
        return self.get(strategy_id).to_dict()

    def all_states(self) -> Dict[str, Dict[str, Any]]:
        """Return every lifecycle record."""
        return {key: record.to_dict() for key, record in self._records.items()}

    def tradable_strategies(self) -> List[str]:
        """Return the ids of strategies allowed to open new positions."""
        return [key for key, record in self._records.items() if record.state.tradable]

    # -- transitions ---------------------------------------------------------
    def update_state(
        self,
        strategy_id: str,
        metrics: PerformanceMetrics | Mapping[str, float],
        force: Optional[LifecycleState] = None,
        reason: str = "",
    ) -> LifecycleState:
        """Evaluate a strategy and apply the resulting state transition.

        Args:
            strategy_id: Identifier of the strategy.
            metrics: Recent performance metrics (rolling window preferred).
            force: Bypass the policy and move to this state.
            reason: Human readable justification, required when forcing.

        Returns:
            The state after evaluation.
        """
        record = self.get(strategy_id)
        payload = metrics.to_dict() if isinstance(metrics, PerformanceMetrics) else dict(metrics)
        sharpe = float(payload.get("sharpe", 0.0))
        trades = int(payload.get("trades", 0))
        max_dd = float(payload.get("max_drawdown", 0.0))

        record.evaluations += 1
        record.last_evaluated = utcnow()
        record.best_sharpe = max(record.best_sharpe, sharpe)

        if force is not None:
            self._transition(record, force, reason or f"Manual override to {force.value}", payload)
            return record.state

        if record.state is LifecycleState.RETIRED:
            return record.state

        if trades < self.min_trades and record.state is LifecycleState.ACTIVE:
            # Not enough evidence yet - keep the strategy where it is.
            return record.state

        if sharpe >= self.recovery_sharpe:
            record.consecutive_good += 1
            record.consecutive_bad = 0
        elif sharpe < self.degraded_sharpe:
            record.consecutive_bad += 1
            record.consecutive_good = 0

        target = record.state
        transition_reason = ""

        if record.state is LifecycleState.ACTIVE:
            if sharpe < self.paused_sharpe:
                target = LifecycleState.PAUSED
                transition_reason = f"Sharpe {sharpe:.2f} below pause threshold {self.paused_sharpe:.2f}"
            elif sharpe < self.degraded_sharpe:
                target = LifecycleState.DEGRADED
                transition_reason = f"Sharpe {sharpe:.2f} below degrade threshold {self.degraded_sharpe:.2f}"
        elif record.state is LifecycleState.DEGRADED:
            if sharpe < self.paused_sharpe:
                target = LifecycleState.PAUSED
                transition_reason = f"Sharpe {sharpe:.2f} below pause threshold {self.paused_sharpe:.2f}"
            elif sharpe >= self.recovery_sharpe and record.consecutive_good >= 2:
                target = LifecycleState.ACTIVE
                transition_reason = f"Recovered with Sharpe {sharpe:.2f}"
        elif record.state is LifecycleState.PAUSED:
            if sharpe >= self.recovery_sharpe and record.consecutive_good >= 2:
                target = LifecycleState.DEGRADED
                transition_reason = f"Paper performance recovered (Sharpe {sharpe:.2f})"
            elif record.days_in_state >= self.retire_after_days:
                target = LifecycleState.RETIRED
                transition_reason = (
                    f"No recovery after {record.days_in_state:.0f} days paused"
                )

        if max_dd >= 0.5 and record.state.tradable:
            target = LifecycleState.PAUSED
            transition_reason = f"Drawdown {max_dd:.1%} breached the 50% hard limit"

        if target is not record.state and record.days_in_state >= self.min_dwell_days:
            self._transition(record, target, transition_reason, payload)
        elif target is not record.state:
            logger.debug(
                "Transition suppressed by dwell time",
                strategy_id=strategy_id,
                target=target.value,
                days_in_state=round(record.days_in_state, 2),
            )
        return record.state

    def _transition(
        self,
        record: StrategyLifecycle,
        target: LifecycleState,
        reason: str,
        metrics: Mapping[str, float],
    ) -> None:
        """Record and log a state change."""
        if target is record.state:
            return
        transition = LifecycleTransition(
            strategy_id=record.strategy_id,
            from_state=record.state.value,
            to_state=target.value,
            reason=reason,
            metrics={
                key: round(float(metrics.get(key, 0.0)), 4)
                for key in ("sharpe", "max_drawdown", "win_rate", "trades")
            },
        )
        record.history.append(transition)
        record.state = target
        record.since = utcnow()
        record.reason = reason
        record.consecutive_bad = 0
        record.consecutive_good = 0
        logger.info(
            "Lifecycle transition",
            strategy_id=record.strategy_id,
            from_state=transition.from_state,
            to_state=transition.to_state,
            reason=reason,
        )

    # -- manual controls -----------------------------------------------------
    def pause(self, strategy_id: str, reason: str = "Manual pause") -> LifecycleState:
        """Pause a strategy immediately."""
        record = self.get(strategy_id)
        self._transition(record, LifecycleState.PAUSED, reason, {})
        return record.state

    def resume(self, strategy_id: str, reason: str = "Manual resume") -> LifecycleState:
        """Move a paused strategy back to DEGRADED for a probation period."""
        record = self.get(strategy_id)
        if record.state is LifecycleState.RETIRED:
            logger.warning("Cannot resume a retired strategy", strategy_id=strategy_id)
            return record.state
        self._transition(record, LifecycleState.DEGRADED, reason, {})
        return record.state

    def retire(self, strategy_id: str, reason: str = "Manual retirement") -> LifecycleState:
        """Retire a strategy permanently."""
        record = self.get(strategy_id)
        self._transition(record, LifecycleState.RETIRED, reason, {})
        return record.state

    def allocation_multiplier(self, strategy_id: str) -> float:
        """Return the allocation multiplier implied by the current state."""
        return self.get(strategy_id).state.allocation_multiplier

    def snapshot(self) -> Dict[str, Any]:
        """Return a summary suitable for the dashboard."""
        counts: Dict[str, int] = {state.value: 0 for state in LifecycleState}
        for record in self._records.values():
            counts[record.state.value] += 1
        return {
            "counts": counts,
            "total": len(self._records),
            "strategies": self.all_states(),
        }

    def load_snapshot(self, payload: Mapping[str, Any]) -> None:
        """Restore lifecycle records from a serialised snapshot."""
        for strategy_id, data in (payload.get("strategies") or {}).items():
            record = self.register(strategy_id)
            try:
                record.state = LifecycleState(str(data.get("state", "ACTIVE")))
                record.reason = str(data.get("reason", ""))
                record.since = datetime.fromisoformat(data["since"]) if data.get("since") else utcnow()
                record.evaluations = int(data.get("evaluations", 0))
            except (ValueError, KeyError) as exc:  # pragma: no cover - defensive
                logger.warning("Skipping malformed lifecycle record", strategy_id=strategy_id, error=str(exc))
