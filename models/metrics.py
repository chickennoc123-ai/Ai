"""Time-series metrics and system event tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base
from utils.helpers import utcnow


class MetricSample(Base):
    """A single named metric observation."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="system", index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    tags: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the metric sample."""
        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "tags": self.tags or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SystemEvent(Base):
    """An audit-log entry describing something the platform did."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", index=True)
    category: Mapped[str] = mapped_column(String(32), default="system", index=True)
    source: Mapped[str] = mapped_column(String(64), default="", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the event."""
        return {
            "id": self.id,
            "level": self.level,
            "category": self.category,
            "source": self.source,
            "message": self.message,
            "payload": self.payload or {},
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
