"""Order management façade."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from broker.xm_connection import XMConnection
from broker.xm_models import (
    ExecutionReport,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from core.utils import get_instrument
from utils.exceptions import OrderRejectedError
from utils.logger import get_logger
from utils.validators import validate_stop_levels, validate_symbol, validate_volume

logger = get_logger(__name__)


class XMOrders:
    """Places, modifies and cancels orders."""

    def __init__(self, connection: XMConnection) -> None:
        """Bind the façade to a connection."""
        self.connection = connection

    # -- placement -----------------------------------------------------------
    async def place_market_order(
        self,
        symbol: str,
        volume: float,
        direction: str,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        strategy_id: Optional[str] = None,
        comment: str = "",
    ) -> ExecutionReport:
        """Place a market order.

        Args:
            symbol: Instrument symbol.
            volume: Size in lots.
            direction: ``"BUY"`` or ``"SELL"``.
            sl: Optional stop-loss price.
            tp: Optional take-profit price.
            strategy_id: Originating strategy, stored for attribution.
            comment: Free-form order comment.

        Returns:
            The :class:`ExecutionReport` describing the fill.
        """
        return await self._submit(
            symbol=symbol,
            volume=volume,
            direction=direction,
            order_type=OrderType.MARKET,
            price=None,
            sl=sl,
            tp=tp,
            strategy_id=strategy_id,
            comment=comment,
        )

    async def place_limit_order(
        self,
        symbol: str,
        volume: float,
        direction: str,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        strategy_id: Optional[str] = None,
        comment: str = "",
    ) -> ExecutionReport:
        """Place a pending limit order at ``price``."""
        return await self._submit(
            symbol=symbol,
            volume=volume,
            direction=direction,
            order_type=OrderType.LIMIT,
            price=price,
            sl=sl,
            tp=tp,
            strategy_id=strategy_id,
            comment=comment,
        )

    async def place_stop_order(
        self,
        symbol: str,
        volume: float,
        direction: str,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        strategy_id: Optional[str] = None,
        comment: str = "",
    ) -> ExecutionReport:
        """Place a pending stop order at ``price``."""
        return await self._submit(
            symbol=symbol,
            volume=volume,
            direction=direction,
            order_type=OrderType.STOP,
            price=price,
            sl=sl,
            tp=tp,
            strategy_id=strategy_id,
            comment=comment,
        )

    async def _submit(
        self,
        symbol: str,
        volume: float,
        direction: str,
        order_type: OrderType,
        price: Optional[float],
        sl: Optional[float],
        tp: Optional[float],
        strategy_id: Optional[str],
        comment: str,
    ) -> ExecutionReport:
        """Validate and dispatch an order to the active transport."""
        normalised_symbol = validate_symbol(symbol, self.connection.symbols or None)
        spec = get_instrument(normalised_symbol)
        side = OrderSide.from_any(direction)
        validate_volume(volume, spec.min_lot, spec.max_lot)

        reference_price = price
        if reference_price is None and self.connection.is_simulated:
            reference_price = self.connection.simulator.quote(normalised_symbol).price_for(side)
        if reference_price is not None and (sl is not None or tp is not None):
            validate_stop_levels(side.value, reference_price, sl, tp)

        order = Order(
            symbol=normalised_symbol,
            side=side,
            volume=spec.normalize_volume(volume),
            order_type=order_type,
            price=spec.normalize_price(price) if price is not None else None,
            stop_loss=spec.normalize_price(sl) if sl is not None else None,
            take_profit=spec.normalize_price(tp) if tp is not None else None,
            strategy_id=strategy_id,
            comment=comment,
        )

        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.place_order(order)

        payload = await self.connection.request("POST", "/orders", json_body=order.to_dict())
        return self._report_from_payload(order, payload)

    @staticmethod
    def _report_from_payload(order: Order, payload: Dict[str, Any]) -> ExecutionReport:
        """Convert a REST response into an :class:`ExecutionReport`."""
        status = str(payload.get("status", "FILLED")).upper()
        try:
            order.status = OrderStatus(status)
        except ValueError:
            order.status = OrderStatus.PENDING
        order.order_id = str(payload.get("order_id", order.order_id))
        order.filled_price = payload.get("filled_price")
        order.filled_volume = float(payload.get("filled_volume", 0.0))
        order.position_id = payload.get("position_id")
        if order.status is OrderStatus.REJECTED:
            reason = str(payload.get("reason", "Broker rejected the order"))
            order.rejection_reason = reason
            raise OrderRejectedError("Order rejected by broker", reason=reason, order_id=order.order_id)
        return ExecutionReport(order=order, success=True, message=str(payload.get("message", "")))

    # -- maintenance ---------------------------------------------------------
    async def modify_order(
        self,
        order_id: str,
        new_price: Optional[float] = None,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> Order:
        """Modify a resting pending order."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.modify_order(order_id, new_price, new_sl, new_tp)
        payload = await self.connection.request(
            "PUT", f"/orders/{order_id}", json_body={"price": new_price, "sl": new_sl, "tp": new_tp}
        )
        return Order.from_dict(payload)

    async def cancel_order(self, order_id: str) -> Order:
        """Cancel a resting pending order."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.cancel_order(order_id)
        payload = await self.connection.request("DELETE", f"/orders/{order_id}")
        return Order.from_dict(payload)

    async def get_orders(self, status: Optional[str] = None) -> List[Order]:
        """List orders, optionally filtered by status."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            filter_status = OrderStatus(status.upper()) if status else None
            return self.connection.simulator.orders(filter_status)
        payload = await self.connection.request("GET", "/orders", params={"status": status} if status else None)
        return [Order.from_dict(item) for item in payload or []]

    async def get_order(self, order_id: str) -> Order:
        """Return a single order."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return self.connection.simulator.get_order(order_id)
        return Order.from_dict(await self.connection.request("GET", f"/orders/{order_id}"))
