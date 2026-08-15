"""Domain models shared by the broker layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from utils.helpers import new_id, utcnow


class OrderSide(str, Enum):
    """Direction of an order or position."""

    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """``1`` for BUY, ``-1`` for SELL."""
        return 1 if self is OrderSide.BUY else -1

    @classmethod
    def from_any(cls, value: Any) -> "OrderSide":
        """Coerce strings or signed numbers into an :class:`OrderSide`."""
        if isinstance(value, OrderSide):
            return value
        if isinstance(value, (int, float)):
            return cls.BUY if value >= 0 else cls.SELL
        text = str(value).strip().upper()
        if text in {"BUY", "LONG", "B", "1"}:
            return cls.BUY
        if text in {"SELL", "SHORT", "S", "-1"}:
            return cls.SELL
        raise ValueError(f"Unknown order side: {value}")

    @property
    def opposite(self) -> "OrderSide":
        """Return the opposite side."""
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    """Lifecycle of an order."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    """Lifecycle of a position."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Quote:
    """Top-of-book quote for a symbol."""

    symbol: str
    bid: float
    ask: float
    timestamp: datetime = field(default_factory=utcnow)

    @property
    def mid(self) -> float:
        """Mid price."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        """Absolute spread in price units."""
        return self.ask - self.bid

    def price_for(self, side: OrderSide) -> float:
        """Return the executable price for ``side``."""
        return self.ask if side is OrderSide.BUY else self.bid

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the quote."""
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": round(self.mid, 6),
            "spread": round(self.spread, 6),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Tick:
    """A single market tick."""

    symbol: str
    bid: float
    ask: float
    volume: float = 0.0
    timestamp: datetime = field(default_factory=utcnow)

    def to_quote(self) -> Quote:
        """Convert the tick into a :class:`Quote`."""
        return Quote(self.symbol, self.bid, self.ask, self.timestamp)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the tick."""
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


@dataclass
class Order:
    """An order resting at, or executed by, the broker."""

    symbol: str
    side: OrderSide
    volume: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    order_id: str = field(default_factory=lambda: new_id("ord"))
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: float = 0.0
    filled_price: Optional[float] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    position_id: Optional[str] = None
    strategy_id: Optional[str] = None
    comment: str = ""
    rejection_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the order."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "volume": self.volume,
            "order_type": self.order_type.value,
            "price": self.price,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "status": self.status.value,
            "filled_volume": self.filled_volume,
            "filled_price": self.filled_price,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "position_id": self.position_id,
            "strategy_id": self.strategy_id,
            "comment": self.comment,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Order":
        """Rebuild an order from a broker payload."""
        return cls(
            symbol=str(payload["symbol"]).upper(),
            side=OrderSide.from_any(payload.get("side") or payload.get("direction")),
            volume=float(payload.get("volume", 0.0)),
            order_type=OrderType(str(payload.get("order_type", "MARKET")).upper()),
            price=payload.get("price"),
            stop_loss=payload.get("sl", payload.get("stop_loss")),
            take_profit=payload.get("tp", payload.get("take_profit")),
            order_id=str(payload.get("order_id") or new_id("ord")),
            status=OrderStatus(str(payload.get("status", "PENDING")).upper()),
            filled_volume=float(payload.get("filled_volume", 0.0)),
            filled_price=payload.get("filled_price"),
            position_id=payload.get("position_id"),
            strategy_id=payload.get("strategy_id"),
            comment=str(payload.get("comment", "")),
        )


@dataclass
class Position:
    """An open or closed position."""

    symbol: str
    side: OrderSide
    volume: float
    open_price: float
    position_id: str = field(default_factory=lambda: new_id("pos"))
    current_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = field(default_factory=utcnow)
    closed_at: Optional[datetime] = None
    close_price: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    profit: float = 0.0
    swap: float = 0.0
    commission: float = 0.0
    margin: float = 0.0
    strategy_id: Optional[str] = None
    comment: str = ""
    close_reason: str = ""

    @property
    def direction(self) -> int:
        """``1`` for long, ``-1`` for short."""
        return self.side.sign

    @property
    def net_profit(self) -> float:
        """Profit net of swap and commission."""
        return self.profit + self.swap - self.commission

    @property
    def is_open(self) -> bool:
        """``True`` while the position is live."""
        return self.status is PositionStatus.OPEN

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the position."""
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "direction": self.direction,
            "volume": self.volume,
            "open_price": self.open_price,
            "current_price": self.current_price,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "close_price": self.close_price,
            "status": self.status.value,
            "profit": round(self.profit, 2),
            "swap": round(self.swap, 2),
            "commission": round(self.commission, 2),
            "net_profit": round(self.net_profit, 2),
            "margin": round(self.margin, 2),
            "strategy_id": self.strategy_id,
            "comment": self.comment,
            "close_reason": self.close_reason,
        }


@dataclass
class AccountInfo:
    """Snapshot of the trading account."""

    account_id: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    leverage: float
    currency: str = "USD"
    server: str = ""
    demo: bool = True
    open_positions: int = 0
    timestamp: datetime = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the account snapshot."""
        return {
            "account_id": self.account_id,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "margin": round(self.margin, 2),
            "free_margin": round(self.free_margin, 2),
            "margin_level": round(self.margin_level, 2),
            "leverage": self.leverage,
            "currency": self.currency,
            "server": self.server,
            "demo": self.demo,
            "open_positions": self.open_positions,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ExecutionReport:
    """Outcome of an execution request, published on the message bus."""

    order: Order
    position: Optional[Position] = None
    success: bool = True
    message: str = ""
    slippage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the execution report."""
        return {
            "success": self.success,
            "message": self.message,
            "slippage": round(self.slippage, 6),
            "order": self.order.to_dict(),
            "position": self.position.to_dict() if self.position else None,
        }
