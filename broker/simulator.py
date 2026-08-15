"""Local matching engine used by the simulated broker mode.

The simulator implements the parts of a retail FX/CFD venue that matter for a
trading platform: two-sided quotes with a spread, market and pending orders,
protective levels, margin accounting, swaps and a position history.  It runs
entirely in-process, which makes the whole system testable and demo-able
without broker credentials.
"""

from __future__ import annotations

import asyncio
import random
from typing import Dict, List, Optional

from broker.xm_models import (
    AccountInfo,
    ExecutionReport,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionStatus,
    Quote,
    Tick,
)
from core.utils import (
    REFERENCE_PRICES,
    get_instrument,
    position_pnl,
    required_margin,
)
from utils.exceptions import (
    InsufficientMarginError,
    OrderNotFoundError,
    OrderRejectedError,
    PositionNotFoundError,
)
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class SimulatedBroker:
    """In-process matching engine with realistic account mechanics."""

    def __init__(
        self,
        account_id: str = "DEMO-1000001",
        balance: float = 10_000.0,
        leverage: float = 500.0,
        symbols: Optional[List[str]] = None,
        server: str = "XMGlobal-Demo",
        seed: Optional[int] = None,
        slippage_pips: float = 0.2,
    ) -> None:
        """Initialise the simulated account.

        Args:
            account_id: Identifier reported by the account endpoint.
            balance: Starting balance in account currency.
            leverage: Account leverage (e.g. ``500`` for 1:500).
            symbols: Tradable symbols; defaults to the platform universe.
            server: Server name reported to clients.
            seed: RNG seed; ``None`` produces a different path per process.
            slippage_pips: Average execution slippage applied to market orders.
        """
        self.account_id = account_id
        self.server = server
        self.initial_balance = balance
        self.balance = balance
        self.leverage = leverage
        self.symbols = [symbol.upper() for symbol in (symbols or list(REFERENCE_PRICES))]
        self.slippage_pips = slippage_pips

        self._random = random.Random(seed)
        self._prices: Dict[str, float] = {
            symbol: REFERENCE_PRICES.get(symbol, 1.0) for symbol in self.symbols
        }
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._history: List[Position] = []
        self._last_swap_day: Optional[int] = None
        self._lock = asyncio.Lock()

    # -- pricing -------------------------------------------------------------
    def quote(self, symbol: str) -> Quote:
        """Return the current two-sided quote for ``symbol``."""
        key = symbol.upper()
        spec = get_instrument(key)
        mid = self._prices.get(key, REFERENCE_PRICES.get(key, 1.0))
        half_spread = spec.typical_spread_pips * spec.pip_size / 2.0
        return Quote(
            symbol=key,
            bid=spec.normalize_price(mid - half_spread),
            ask=spec.normalize_price(mid + half_spread),
        )

    def quotes(self) -> Dict[str, Quote]:
        """Return quotes for every tradable symbol."""
        return {symbol: self.quote(symbol) for symbol in self.symbols}

    def set_price(self, symbol: str, price: float) -> None:
        """Force the mid price of a symbol (used when replaying real data)."""
        self._prices[symbol.upper()] = float(price)

    def step(self, symbol: Optional[str] = None) -> List[Tick]:
        """Advance the random walk one step and return the resulting ticks.

        Args:
            symbol: Restrict the update to a single symbol when provided.

        Returns:
            The list of generated ticks.
        """
        targets = [symbol.upper()] if symbol else list(self.symbols)
        ticks: List[Tick] = []
        for key in targets:
            spec = get_instrument(key)
            # Per-tick volatility scaled from the instrument's annual figure.
            step_volatility = spec.annual_volatility / (252 * 24 * 60 * 60) ** 0.5
            drift = self._random.gauss(0.0, 1.0) * step_volatility
            price = self._prices.get(key, REFERENCE_PRICES.get(key, 1.0)) * (1.0 + drift)
            self._prices[key] = price
            quote = self.quote(key)
            ticks.append(Tick(symbol=key, bid=quote.bid, ask=quote.ask, volume=1.0))
        return ticks

    # -- account -------------------------------------------------------------
    def account_info(self) -> AccountInfo:
        """Return the current account snapshot."""
        self._revalue_positions()
        margin = sum(position.margin for position in self._positions.values())
        floating = sum(position.net_profit for position in self._positions.values())
        equity = self.balance + floating
        return AccountInfo(
            account_id=self.account_id,
            balance=self.balance,
            equity=equity,
            margin=margin,
            free_margin=equity - margin,
            margin_level=(equity / margin * 100.0) if margin > 0 else 0.0,
            leverage=self.leverage,
            server=self.server,
            demo=True,
            open_positions=len(self._positions),
        )

    def _revalue_positions(self) -> None:
        """Mark every open position to the current market."""
        for position in self._positions.values():
            spec = get_instrument(position.symbol)
            quote = self.quote(position.symbol)
            # Long positions are closed at the bid, shorts at the ask.
            price = quote.bid if position.side is OrderSide.BUY else quote.ask
            position.current_price = price
            position.profit = position_pnl(
                spec, position.direction, position.open_price, price, position.volume
            )

    def _apply_swaps(self) -> None:
        """Charge daily swap once per UTC day for every open position."""
        today = utcnow().timetuple().tm_yday
        if self._last_swap_day is None:
            self._last_swap_day = today
            return
        if today == self._last_swap_day:
            return
        self._last_swap_day = today
        for position in self._positions.values():
            spec = get_instrument(position.symbol)
            rate = spec.swap_long if position.side is OrderSide.BUY else spec.swap_short
            position.swap += rate * position.volume

    # -- orders --------------------------------------------------------------
    async def place_order(self, order: Order) -> ExecutionReport:
        """Validate and route an order to the matching engine."""
        async with self._lock:
            return self._place_order_locked(order)

    def _place_order_locked(self, order: Order) -> ExecutionReport:
        """Order handling assuming the engine lock is held."""
        symbol = order.symbol.upper()
        if symbol not in self.symbols:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "Symbol not tradable"
            raise OrderRejectedError("Symbol not tradable", reason=order.rejection_reason, symbol=symbol)

        spec = get_instrument(symbol)
        volume = spec.normalize_volume(order.volume)
        if volume <= 0:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = f"Volume below broker minimum ({spec.min_lot})"
            raise OrderRejectedError("Invalid volume", reason=order.rejection_reason, volume=order.volume)
        order.volume = volume

        self._orders[order.order_id] = order
        if order.order_type is OrderType.MARKET:
            return self._fill_market_order(order)

        if order.price is None:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "Pending orders require a price"
            raise OrderRejectedError("Missing price", reason=order.rejection_reason)
        order.status = OrderStatus.PENDING
        order.updated_at = utcnow()
        logger.info(
            "Pending order accepted",
            order_id=order.order_id,
            symbol=symbol,
            side=order.side.value,
            price=order.price,
        )
        return ExecutionReport(order=order, success=True, message="Pending order accepted")

    def _fill_market_order(self, order: Order) -> ExecutionReport:
        """Fill a market order immediately at the current quote plus slippage."""
        spec = get_instrument(order.symbol)
        quote = self.quote(order.symbol)
        reference = quote.price_for(order.side)
        slippage = self._random.uniform(0.0, self.slippage_pips) * spec.pip_size * order.side.sign
        fill_price = spec.normalize_price(reference + slippage)

        margin = required_margin(spec, fill_price, order.volume, self.leverage)
        account = self.account_info()
        if margin > account.free_margin:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "Insufficient free margin"
            logger.warning(
                "Order rejected for margin",
                order_id=order.order_id,
                required=round(margin, 2),
                free_margin=round(account.free_margin, 2),
            )
            raise InsufficientMarginError(
                "Insufficient free margin",
                reason=order.rejection_reason,
                required=round(margin, 2),
                available=round(account.free_margin, 2),
            )

        commission = spec.commission_per_lot * order.volume / 2.0
        position = Position(
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            open_price=fill_price,
            current_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            margin=margin,
            commission=commission,
            strategy_id=order.strategy_id,
            comment=order.comment,
        )
        self._positions[position.position_id] = position

        order.status = OrderStatus.FILLED
        order.filled_volume = order.volume
        order.filled_price = fill_price
        order.position_id = position.position_id
        order.updated_at = utcnow()

        logger.info(
            "Market order filled",
            order_id=order.order_id,
            position_id=position.position_id,
            symbol=order.symbol,
            side=order.side.value,
            volume=order.volume,
            price=fill_price,
        )
        return ExecutionReport(
            order=order,
            position=position,
            success=True,
            message="Filled",
            slippage=abs(fill_price - reference),
        )

    async def modify_order(
        self,
        order_id: str,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Order:
        """Modify a resting pending order."""
        async with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise OrderNotFoundError("Order not found", order_id=order_id)
            if order.status is not OrderStatus.PENDING:
                raise OrderRejectedError("Only pending orders can be modified", order_id=order_id)
            if price is not None:
                order.price = price
            if stop_loss is not None:
                order.stop_loss = stop_loss
            if take_profit is not None:
                order.take_profit = take_profit
            order.updated_at = utcnow()
            return order

    async def cancel_order(self, order_id: str) -> Order:
        """Cancel a resting pending order."""
        async with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise OrderNotFoundError("Order not found", order_id=order_id)
            if order.status is not OrderStatus.PENDING:
                raise OrderRejectedError("Only pending orders can be cancelled", order_id=order_id)
            order.status = OrderStatus.CANCELLED
            order.updated_at = utcnow()
            logger.info("Order cancelled", order_id=order_id)
            return order

    def orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """Return orders, optionally filtered by status."""
        values = list(self._orders.values())
        if status is not None:
            values = [order for order in values if order.status is status]
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def get_order(self, order_id: str) -> Order:
        """Return a single order.

        Raises:
            OrderNotFoundError: If the id is unknown.
        """
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError("Order not found", order_id=order_id)
        return order

    # -- positions -----------------------------------------------------------
    def positions(self) -> List[Position]:
        """Return the currently open positions."""
        self._revalue_positions()
        return sorted(self._positions.values(), key=lambda item: item.opened_at)

    def get_position(self, position_id: str) -> Position:
        """Return a single open position.

        Raises:
            PositionNotFoundError: If the id is unknown.
        """
        self._revalue_positions()
        position = self._positions.get(position_id)
        if position is None:
            raise PositionNotFoundError("Position not found", position_id=position_id)
        return position

    def history(self, symbol: Optional[str] = None, limit: int = 200) -> List[Position]:
        """Return closed positions, newest first."""
        items = self._history
        if symbol:
            key = symbol.upper()
            items = [position for position in items if position.symbol == key]
        return sorted(items, key=lambda item: item.closed_at or item.opened_at, reverse=True)[:limit]

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Position:
        """Close an open position at the current market price."""
        async with self._lock:
            return self._close_position_locked(position_id, reason)

    def _close_position_locked(self, position_id: str, reason: str, price: Optional[float] = None) -> Position:
        """Close a position assuming the engine lock is held."""
        position = self._positions.get(position_id)
        if position is None:
            raise PositionNotFoundError("Position not found", position_id=position_id)

        spec = get_instrument(position.symbol)
        quote = self.quote(position.symbol)
        close_price = price if price is not None else (
            quote.bid if position.side is OrderSide.BUY else quote.ask
        )
        close_price = spec.normalize_price(close_price)
        position.profit = position_pnl(
            spec, position.direction, position.open_price, close_price, position.volume
        )
        position.commission += spec.commission_per_lot * position.volume / 2.0
        position.close_price = close_price
        position.current_price = close_price
        position.closed_at = utcnow()
        position.status = PositionStatus.CLOSED
        position.close_reason = reason

        self.balance += position.net_profit
        del self._positions[position_id]
        self._history.append(position)
        logger.info(
            "Position closed",
            position_id=position_id,
            symbol=position.symbol,
            reason=reason,
            profit=round(position.net_profit, 2),
            balance=round(self.balance, 2),
        )
        return position

    async def close_all(self, symbol: Optional[str] = None, reason: str = "CLOSE_ALL") -> List[Position]:
        """Close every open position, optionally filtered by symbol."""
        async with self._lock:
            targets = [
                position.position_id
                for position in self._positions.values()
                if symbol is None or position.symbol == symbol.upper()
            ]
            return [self._close_position_locked(position_id, reason) for position_id in targets]

    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Position:
        """Update the protective levels of an open position."""
        async with self._lock:
            position = self._positions.get(position_id)
            if position is None:
                raise PositionNotFoundError("Position not found", position_id=position_id)
            if stop_loss is not None:
                position.stop_loss = stop_loss
            if take_profit is not None:
                position.take_profit = take_profit
            return position

    # -- market events -------------------------------------------------------
    async def on_price_update(self, symbol: str, price: Optional[float] = None) -> List[ExecutionReport]:
        """Process a price change: trigger pendings, stops and margin calls.

        Args:
            symbol: Symbol whose price changed.
            price: New mid price; the internal random walk is used when omitted.

        Returns:
            Execution reports for every automatic action taken.
        """
        async with self._lock:
            key = symbol.upper()
            if price is not None:
                self._prices[key] = float(price)
            self._apply_swaps()
            self._revalue_positions()
            reports: List[ExecutionReport] = []
            reports.extend(self._trigger_pending_orders(key))
            reports.extend(self._trigger_protective_levels(key))
            self._check_margin_call()
            return reports

    def _trigger_pending_orders(self, symbol: str) -> List[ExecutionReport]:
        """Fill pending orders whose trigger price has been reached."""
        quote = self.quote(symbol)
        reports: List[ExecutionReport] = []
        for order in list(self._orders.values()):
            if order.status is not OrderStatus.PENDING or order.symbol != symbol or order.price is None:
                continue
            price = quote.price_for(order.side)
            triggered = False
            if order.order_type is OrderType.LIMIT:
                triggered = price <= order.price if order.side is OrderSide.BUY else price >= order.price
            elif order.order_type is OrderType.STOP:
                triggered = price >= order.price if order.side is OrderSide.BUY else price <= order.price
            if not triggered:
                continue
            market_order = Order(
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                order_type=OrderType.MARKET,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                order_id=order.order_id,
                strategy_id=order.strategy_id,
                comment=order.comment or "pending-triggered",
            )
            try:
                report = self._fill_market_order(market_order)
                self._orders[order.order_id] = market_order
                reports.append(report)
            except OrderRejectedError as exc:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = str(exc)
                logger.warning("Pending order rejected on trigger", order_id=order.order_id, error=str(exc))
        return reports

    def _trigger_protective_levels(self, symbol: str) -> List[ExecutionReport]:
        """Close positions whose stop-loss or take-profit has been touched."""
        quote = self.quote(symbol)
        reports: List[ExecutionReport] = []
        for position in list(self._positions.values()):
            if position.symbol != symbol:
                continue
            price = quote.bid if position.side is OrderSide.BUY else quote.ask
            reason = ""
            if position.stop_loss is not None:
                if position.side is OrderSide.BUY and price <= position.stop_loss:
                    reason = "STOP_LOSS"
                elif position.side is OrderSide.SELL and price >= position.stop_loss:
                    reason = "STOP_LOSS"
            if not reason and position.take_profit is not None:
                if position.side is OrderSide.BUY and price >= position.take_profit:
                    reason = "TAKE_PROFIT"
                elif position.side is OrderSide.SELL and price <= position.take_profit:
                    reason = "TAKE_PROFIT"
            if not reason:
                continue
            level = position.stop_loss if reason == "STOP_LOSS" else position.take_profit
            closed = self._close_position_locked(position.position_id, reason, price=level)
            reports.append(
                ExecutionReport(
                    order=Order(
                        symbol=closed.symbol,
                        side=closed.side.opposite,
                        volume=closed.volume,
                        order_type=OrderType.MARKET,
                        status=OrderStatus.FILLED,
                        filled_price=closed.close_price,
                        filled_volume=closed.volume,
                        position_id=closed.position_id,
                        strategy_id=closed.strategy_id,
                        comment=reason,
                    ),
                    position=closed,
                    success=True,
                    message=f"Position closed by {reason}",
                )
            )
        return reports

    def _check_margin_call(self) -> None:
        """Force-close the worst position when the margin level collapses."""
        account = self.account_info()
        if account.margin <= 0 or account.margin_level >= 50.0:
            return
        worst = min(self._positions.values(), key=lambda item: item.net_profit, default=None)
        if worst is None:
            return
        logger.warning(
            "Margin call - closing worst position",
            margin_level=round(account.margin_level, 2),
            position_id=worst.position_id,
        )
        self._close_position_locked(worst.position_id, "MARGIN_CALL")

    # -- diagnostics ---------------------------------------------------------
    def statistics(self) -> Dict[str, float]:
        """Return simple account statistics for dashboards and tests."""
        closed = self._history
        wins = [position for position in closed if position.net_profit > 0]
        return {
            "closed_trades": len(closed),
            "open_positions": len(self._positions),
            "win_rate": len(wins) / len(closed) if closed else 0.0,
            "realized_pnl": sum(position.net_profit for position in closed),
            "balance": self.balance,
            "return_pct": (self.balance / self.initial_balance - 1.0) if self.initial_balance else 0.0,
        }

    def reset(self) -> None:
        """Reset the engine to its initial state (used by tests)."""
        self.balance = self.initial_balance
        self._orders.clear()
        self._positions.clear()
        self._history.clear()
        self._prices = {symbol: REFERENCE_PRICES.get(symbol, 1.0) for symbol in self.symbols}
