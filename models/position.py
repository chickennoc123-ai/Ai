"""Position history table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base
from utils.helpers import utcnow


class PositionRecord(Base):
    """A persisted position, mirroring :class:`broker.xm_models.Position`."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    open_price: Mapped[float] = mapped_column(Float, default=0.0)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    close_reason: Mapped[str] = mapped_column(String(32), default="")
    comment: Mapped[str] = mapped_column(String(128), default="")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def from_position(cls, position: Any) -> "PositionRecord":
        """Build a record from a broker position object."""
        return cls(
            position_id=position.position_id,
            symbol=position.symbol,
            side=position.side.value,
            volume=position.volume,
            open_price=position.open_price,
            close_price=position.close_price,
            current_price=position.current_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            status=position.status.value,
            profit=position.profit,
            swap=position.swap,
            commission=position.commission,
            margin=position.margin,
            strategy_id=position.strategy_id,
            close_reason=position.close_reason,
            comment=position.comment,
            opened_at=position.opened_at,
            closed_at=position.closed_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the position record."""
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "open_price": self.open_price,
            "close_price": self.close_price,
            "current_price": self.current_price,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "status": self.status,
            "profit": self.profit,
            "swap": self.swap,
            "commission": self.commission,
            "net_profit": self.profit + self.swap - self.commission,
            "margin": self.margin,
            "strategy_id": self.strategy_id,
            "close_reason": self.close_reason,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }
