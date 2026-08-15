"""Order service: broker execution plus persistence and audit."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from broker.xm_models import Order
from broker.xm_orders import XMOrders
from models.database import Database, session_scope
from models.metrics import SystemEvent
from models.order import OrderRecord
from utils.logger import get_logger
from utils.validators import validate_order_request

logger = get_logger(__name__)


class OrderService:
    """Places orders through the broker and records them in the database."""

    def __init__(self, orders: XMOrders, database: Optional[Database] = None) -> None:
        """Bind the service to a broker façade and an optional database."""
        self.orders = orders
        self.database = database

    async def place(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and place an order.

        Args:
            payload: Raw order request (symbol, volume, direction, ...).

        Returns:
            The serialised execution report.
        """
        request = validate_order_request(payload, self.orders.connection.symbols or None)
        order_type = request["order_type"]
        common = {
            "symbol": request["symbol"],
            "volume": request["volume"],
            "direction": request["direction"],
            "sl": request["sl"],
            "tp": request["tp"],
            "strategy_id": request["strategy_id"],
            "comment": request["comment"] or "api",
        }
        if order_type == "MARKET":
            report = await self.orders.place_market_order(**common)
        elif order_type == "LIMIT":
            report = await self.orders.place_limit_order(price=request["price"], **common)
        else:
            report = await self.orders.place_stop_order(price=request["price"], **common)

        self._persist(report.order, "order_placed")
        return report.to_dict()

    async def modify(
        self,
        order_id: str,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Modify a pending order."""
        order = await self.orders.modify_order(order_id, price, sl, tp)
        self._persist(order, "order_modified")
        return order.to_dict()

    async def cancel(self, order_id: str) -> Dict[str, Any]:
        """Cancel a pending order."""
        order = await self.orders.cancel_order(order_id)
        self._persist(order, "order_cancelled")
        return order.to_dict()

    async def list_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List broker orders."""
        return [order.to_dict() for order in await self.orders.get_orders(status)]

    async def get(self, order_id: str) -> Dict[str, Any]:
        """Return a single order."""
        return (await self.orders.get_order(order_id)).to_dict()

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return persisted orders, newest first."""
        if self.database is None:
            return []
        with session_scope(self.database) as session:
            records = (
                session.query(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(limit).all()
            )
            return [record.to_dict() for record in records]

    def _persist(self, order: Order, event: str) -> None:
        """Upsert the order and write an audit event."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                existing = (
                    session.query(OrderRecord).filter(OrderRecord.order_id == order.order_id).one_or_none()
                )
                if existing is None:
                    session.add(OrderRecord.from_order(order))
                else:
                    existing.status = order.status.value
                    existing.filled_price = order.filled_price
                    existing.filled_volume = order.filled_volume
                    existing.price = order.price
                    existing.stop_loss = order.stop_loss
                    existing.take_profit = order.take_profit
                    existing.position_id = order.position_id
                    existing.rejection_reason = order.rejection_reason
                session.add(
                    SystemEvent(
                        level="INFO",
                        category="trading",
                        source="order_service",
                        message=event,
                        payload=order.to_dict(),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - persistence must not break trading
            logger.warning("Unable to persist order", order_id=order.order_id, error=str(exc))
