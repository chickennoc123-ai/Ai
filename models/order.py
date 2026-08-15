"""Order history table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base
from utils.helpers import utcnow


class OrderRecord(Base):
    """A persisted order, mirroring :class:`broker.xm_models.Order`."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16), default="MARKET")
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    filled_volume: Mapped[float] = mapped_column(Float, default=0.0)
    filled_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    comment: Mapped[str] = mapped_column(String(128), default="")
    rejection_reason: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @classmethod
    def from_order(cls, order: Any) -> "OrderRecord":
        """Build a record from a broker order object."""
        return cls(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.value,
            order_type=order.order_type.value,
            volume=order.volume,
            price=order.price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=order.status.value,
            filled_volume=order.filled_volume,
            filled_price=order.filled_price,
            position_id=order.position_id,
            strategy_id=order.strategy_id,
            comment=order.comment,
            rejection_reason=order.rejection_reason,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the order record."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "volume": self.volume,
            "price": self.price,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "status": self.status,
            "filled_volume": self.filled_volume,
            "filled_price": self.filled_price,
            "position_id": self.position_id,
            "strategy_id": self.strategy_id,
            "comment": self.comment,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
