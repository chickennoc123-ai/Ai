"""Validation service: runs the validation suite and stores the reports."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional

from core.data_manager import DataManager
from core.strategy_registry import create_strategy
from core.validation import ValidationReport, ValidationSuite
from models.database import Database, session_scope
from models.strategy import ValidationRecord
from utils.config import Config, get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class ValidationService:
    """Runs walk-forward, PBO, calibration and robustness checks on demand."""

    def __init__(
        self,
        data_manager: Optional[DataManager] = None,
        config: Optional[Config] = None,
        database: Optional[Database] = None,
    ) -> None:
        """Initialise the service."""
        self.config = config or get_config()
        self.data_manager = data_manager or DataManager(self.config)
        self.database = database
        self.suite = ValidationSuite(self.config)
        self._reports: Dict[str, Dict[str, Any]] = {}

    async def validate(
        self,
        name: str,
        symbol: str,
        timeframe: str = "H1",
        bars: Optional[int] = None,
        params: Optional[Mapping[str, Any]] = None,
        quick: bool = False,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Validate one strategy and return the full report.

        Args:
            name: Registered strategy name.
            symbol: Instrument.
            timeframe: Bar timeframe.
            bars: History length.
            params: Parameter overrides.
            quick: Skip PBO and robustness (fast screening mode).
            persist: Store the report in the database.

        Returns:
            The serialised :class:`core.validation.ValidationReport`.
        """
        frame = await self.data_manager.get_ohlcv(
            symbol, timeframe, bars or self.config.get_int("data.history_bars", 5000)
        )
        strategy = create_strategy(name, symbol, timeframe, params)
        report: ValidationReport = await asyncio.to_thread(self.suite.run, strategy, frame, quick)
        payload = report.to_dict()
        self._reports[report.strategy_id] = payload
        if persist:
            self._persist(payload)
        return payload

    async def validate_many(
        self, names: List[str], symbols: List[str], timeframe: str = "H1", quick: bool = True
    ) -> List[Dict[str, Any]]:
        """Validate several strategies and return a ranked summary."""
        summaries: List[Dict[str, Any]] = []
        for name in names:
            for symbol in symbols:
                try:
                    report = await self.validate(name, symbol, timeframe, quick=quick)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Validation failed", strategy=name, symbol=symbol, error=str(exc))
                    continue
                summaries.append(
                    {
                        "strategy": name,
                        "symbol": symbol,
                        "passed": report["passed"],
                        "score": round(report["score"], 4),
                        "sharpe": round(report["baseline"]["metrics"]["sharpe"], 3),
                        "pbo": report["pbo"]["pbo"] if report["pbo"]["computed"] else None,
                        "wfa_efficiency": round(report["walk_forward"]["efficiency"], 3),
                        "reasons": report["reasons"],
                    }
                )
        summaries.sort(key=lambda item: item["score"], reverse=True)
        return summaries

    def get_report(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return a cached validation report."""
        return self._reports.get(strategy_id)

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return persisted validation records, newest first."""
        if self.database is None:
            return []
        with session_scope(self.database) as session:
            records = (
                session.query(ValidationRecord)
                .order_by(ValidationRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [record.to_dict() for record in records]

    def _persist(self, payload: Dict[str, Any]) -> None:
        """Store a validation report."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                session.add(ValidationRecord.from_report(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to persist validation report", error=str(exc))
