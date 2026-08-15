"""Strategy configuration and validation tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base
from utils.helpers import utcnow


class StrategyRecord(Base):
    """A configured strategy instance and its lifecycle state."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), default="generic")
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), default="H1")
    params: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    state_reason: Mapped[str] = mapped_column(String(256), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    generated: Mapped[bool] = mapped_column(Boolean, default=False)
    allocation: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    source_path: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the strategy record."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "category": self.category,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": self.params or {},
            "state": self.state,
            "state_reason": self.state_reason,
            "enabled": self.enabled,
            "generated": self.generated,
            "allocation": self.allocation,
            "metrics": {
                "sharpe": self.sharpe,
                "max_drawdown": self.max_drawdown,
                "win_rate": self.win_rate,
                "trades": self.trades,
            },
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ValidationRecord(Base):
    """A stored validation report."""

    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(128), index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), default="")
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), default="H1")
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    pbo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wfa_efficiency: Mapped[float] = mapped_column(Float, default=0.0)
    calibration_error: Mapped[float] = mapped_column(Float, default=0.0)
    deflated_sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    report: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    @classmethod
    def from_report(cls, payload: Dict[str, Any]) -> "ValidationRecord":
        """Build a record from a :class:`core.validation.ValidationReport` dict."""
        pbo_section = payload.get("pbo") or {}
        return cls(
            strategy_id=str(payload.get("strategy_id", "")),
            strategy_name=str(payload.get("strategy_name", "")),
            symbol=str(payload.get("symbol", "")),
            timeframe=str(payload.get("timeframe", "H1")),
            passed=bool(payload.get("passed", False)),
            score=float(payload.get("score", 0.0)),
            sharpe=float(payload.get("baseline", {}).get("metrics", {}).get("sharpe", 0.0)),
            pbo=float(pbo_section.get("pbo", 0.0)) if pbo_section.get("computed") else None,
            wfa_efficiency=float((payload.get("walk_forward") or {}).get("efficiency", 0.0)),
            calibration_error=float(
                (payload.get("calibration") or {}).get("expected_calibration_error", 0.0)
            ),
            deflated_sharpe=float(payload.get("deflated_sharpe", 0.0)),
            report=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the validation record."""
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "passed": self.passed,
            "score": self.score,
            "sharpe": self.sharpe,
            "pbo": self.pbo,
            "wfa_efficiency": self.wfa_efficiency,
            "calibration_error": self.calibration_error,
            "deflated_sharpe": self.deflated_sharpe,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
