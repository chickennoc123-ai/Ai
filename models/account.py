"""Account snapshot table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base
from utils.helpers import utcnow


class AccountSnapshot(Base):
    """Point-in-time picture of the trading account."""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)
    free_margin: Mapped[float] = mapped_column(Float, default=0.0)
    margin_level: Mapped[float] = mapped_column(Float, default=0.0)
    leverage: Mapped[float] = mapped_column(Float, default=500.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    server: Mapped[str] = mapped_column(String(64), default="")
    demo: Mapped[bool] = mapped_column(Boolean, default=True)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the snapshot."""
        return {
            "id": self.id,
            "account_id": self.account_id,
            "balance": self.balance,
            "equity": self.equity,
            "margin": self.margin,
            "free_margin": self.free_margin,
            "margin_level": self.margin_level,
            "leverage": self.leverage,
            "currency": self.currency,
            "server": self.server,
            "demo": self.demo,
            "open_positions": self.open_positions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
