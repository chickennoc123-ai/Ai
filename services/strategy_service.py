"""Strategy service: registry access and persisted strategy configurations."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from core.lifecycle import LifecycleManager, LifecycleState
from core.strategy_registry import (
    available_strategies,
    create_strategy,
    describe_strategies,
    get_strategy_class,
    load_strategies,
)
from models.database import Database, session_scope
from models.strategy import StrategyRecord
from utils.exceptions import StrategyError
from utils.logger import get_logger

logger = get_logger(__name__)


class StrategyService:
    """Exposes the strategy catalogue and manages configured instances."""

    def __init__(
        self,
        database: Optional[Database] = None,
        lifecycle: Optional[LifecycleManager] = None,
    ) -> None:
        """Initialise the service."""
        self.database = database
        self.lifecycle = lifecycle
        load_strategies()

    # -- catalogue -----------------------------------------------------------
    def catalogue(self) -> List[Dict[str, Any]]:
        """Return metadata for every registered strategy class."""
        return [metadata.to_dict() for metadata in describe_strategies()]

    def names(self) -> List[str]:
        """Return the registered strategy names."""
        return available_strategies()

    def parameter_space(self, name: str) -> List[Dict[str, Any]]:
        """Return the tunable parameter space of a strategy."""
        cls = get_strategy_class(name)
        return [
            {
                "name": spec.name,
                "low": spec.low,
                "high": spec.high,
                "step": spec.step,
                "integer": spec.integer,
                "default": cls.default_params.get(spec.name),
            }
            for spec in cls.param_space
        ]

    # -- configured instances ------------------------------------------------
    def list_configured(self) -> List[Dict[str, Any]]:
        """Return the strategy instances stored in the database."""
        if self.database is None:
            return []
        with session_scope(self.database) as session:
            records = session.query(StrategyRecord).order_by(StrategyRecord.name).all()
            payload = [record.to_dict() for record in records]
        if self.lifecycle is not None:
            for item in payload:
                item["lifecycle"] = self.lifecycle.get_strategy_status(item["strategy_id"])
        return payload

    def create(
        self,
        name: str,
        symbol: str,
        timeframe: str = "H1",
        params: Optional[Mapping[str, Any]] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Persist a new strategy configuration.

        Raises:
            StrategyError: If the strategy name is unknown or already
                configured for this symbol and timeframe.
        """
        strategy = create_strategy(name, symbol, timeframe, params)
        metadata = strategy.metadata()
        if self.database is None:
            return {"strategy_id": strategy.strategy_id, **metadata.to_dict(), "persisted": False}

        with session_scope(self.database) as session:
            existing = (
                session.query(StrategyRecord)
                .filter(StrategyRecord.strategy_id == strategy.strategy_id)
                .one_or_none()
            )
            if existing is not None:
                raise StrategyError(
                    "Strategy already configured",
                    strategy_id=strategy.strategy_id,
                    name=name,
                    symbol=symbol,
                )
            record = StrategyRecord(
                strategy_id=strategy.strategy_id,
                name=strategy.name,
                category=strategy.category,
                symbol=strategy.symbol,
                timeframe=strategy.timeframe,
                params=dict(strategy.params),
                enabled=enabled,
                generated=strategy.generated,
                description=metadata.description,
            )
            session.add(record)
            session.flush()
            payload = record.to_dict()
        if self.lifecycle is not None:
            self.lifecycle.register(strategy.strategy_id, LifecycleState.ACTIVE, "Created via API")
        logger.info("Strategy configured", strategy_id=strategy.strategy_id, name=name, symbol=symbol)
        return payload

    def update(self, strategy_id: str, updates: Mapping[str, Any]) -> Dict[str, Any]:
        """Update a stored strategy configuration.

        Raises:
            StrategyError: If the id is unknown.
        """
        if self.database is None:
            raise StrategyError("No database configured", strategy_id=strategy_id)
        with session_scope(self.database) as session:
            record = (
                session.query(StrategyRecord)
                .filter(StrategyRecord.strategy_id == strategy_id)
                .one_or_none()
            )
            if record is None:
                raise StrategyError("Strategy not found", strategy_id=strategy_id)
            if "params" in updates and isinstance(updates["params"], Mapping):
                merged = dict(record.params or {})
                merged.update(updates["params"])
                # Re-instantiate so parameters are clipped to the search space.
                record.params = dict(create_strategy(record.name, record.symbol, record.timeframe, merged).params)
            for field in ("enabled", "allocation", "state", "state_reason"):
                if field in updates:
                    setattr(record, field, updates[field])
            payload = record.to_dict()
        logger.info("Strategy updated", strategy_id=strategy_id, fields=sorted(updates))
        return payload

    def delete(self, strategy_id: str) -> bool:
        """Remove a stored strategy configuration."""
        if self.database is None:
            return False
        with session_scope(self.database) as session:
            deleted = (
                session.query(StrategyRecord).filter(StrategyRecord.strategy_id == strategy_id).delete()
            )
        if deleted and self.lifecycle is not None:
            self.lifecycle.retire(strategy_id, "Deleted via API")
        logger.info("Strategy deleted", strategy_id=strategy_id, deleted=bool(deleted))
        return bool(deleted)

    def record_performance(self, strategy_id: str, metrics: Mapping[str, Any]) -> None:
        """Store the latest performance metrics on the strategy row."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                record = (
                    session.query(StrategyRecord)
                    .filter(StrategyRecord.strategy_id == strategy_id)
                    .one_or_none()
                )
                if record is None:
                    return
                record.sharpe = float(metrics.get("sharpe", 0.0))
                record.max_drawdown = float(metrics.get("max_drawdown", 0.0))
                record.win_rate = float(metrics.get("win_rate", 0.0))
                record.trades = int(metrics.get("trades", 0))
                if self.lifecycle is not None:
                    status = self.lifecycle.get_strategy_status(strategy_id)
                    record.state = status["state"]
                    record.state_reason = status["reason"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to record strategy performance", strategy_id=strategy_id, error=str(exc))
