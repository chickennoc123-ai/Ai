"""Tests for the broker layer and the simulated matching engine."""

from __future__ import annotations

import asyncio

import pytest

from broker.simulator import SimulatedBroker
from broker.xm_account import XMAccount
from broker.xm_connection import XMConnection
from broker.xm_models import Order, OrderSide, OrderStatus, OrderType, Quote
from broker.xm_orders import XMOrders
from broker.xm_positions import XMPositions
from broker.xm_websocket import XMWebSocket
from core.utils import get_instrument
from utils.exceptions import (
    InsufficientMarginError,
    OrderNotFoundError,
    OrderRejectedError,
    PositionNotFoundError,
)
from utils.validators import ValidationError


@pytest.fixture
def simulator() -> SimulatedBroker:
    """Return a fresh simulated broker."""
    return SimulatedBroker(balance=10_000.0, leverage=500.0, seed=1)


def test_order_side_parsing() -> None:
    """Order sides accept the usual spellings."""
    assert OrderSide.from_any("buy") is OrderSide.BUY
    assert OrderSide.from_any("SHORT") is OrderSide.SELL
    assert OrderSide.from_any(-1) is OrderSide.SELL
    assert OrderSide.BUY.opposite is OrderSide.SELL
    assert OrderSide.SELL.sign == -1


def test_quote_spread_and_sides(simulator: SimulatedBroker) -> None:
    """Quotes are two-sided with a positive spread."""
    quote: Quote = simulator.quote("XAUUSD")
    assert quote.ask > quote.bid
    assert quote.spread == pytest.approx(get_instrument("XAUUSD").typical_spread_pips * 0.1, rel=1e-6)
    assert quote.price_for(OrderSide.BUY) == quote.ask
    assert quote.price_for(OrderSide.SELL) == quote.bid


def test_initial_account_state(simulator: SimulatedBroker) -> None:
    """A fresh account has no margin and full free margin."""
    info = simulator.account_info()
    assert info.balance == 10_000.0
    assert info.equity == 10_000.0
    assert info.margin == 0
    assert info.free_margin == 10_000.0


async def test_market_order_opens_a_position(simulator: SimulatedBroker) -> None:
    """A market order fills immediately and creates a position."""
    order = Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.10, order_type=OrderType.MARKET)
    report = await simulator.place_order(order)
    assert report.success
    assert report.order.status is OrderStatus.FILLED
    assert report.position is not None
    assert len(simulator.positions()) == 1
    assert simulator.account_info().margin > 0


async def test_position_pnl_moves_with_price(simulator: SimulatedBroker) -> None:
    """A long gold position gains when the price rises."""
    entry = simulator.quote("XAUUSD").ask
    await simulator.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.10))
    simulator.set_price("XAUUSD", entry + 10.0)
    position = simulator.positions()[0]
    # 0.10 lots x 100 oz x ~10 USD, minus the spread paid on entry.
    assert 90 < position.profit < 100


async def test_take_profit_closes_the_position(simulator: SimulatedBroker) -> None:
    """A take-profit level closes the position at that price."""
    quote = simulator.quote("XAUUSD")
    await simulator.place_order(
        Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.10, take_profit=quote.ask + 8.0)
    )
    reports = await simulator.on_price_update("XAUUSD", quote.ask + 9.0)
    assert reports
    assert reports[0].position is not None
    assert reports[0].position.close_reason == "TAKE_PROFIT"
    assert not simulator.positions()
    assert simulator.balance > 10_000.0


async def test_stop_loss_closes_the_position(simulator: SimulatedBroker) -> None:
    """A stop-loss level closes the position at that price."""
    quote = simulator.quote("XAUUSD")
    await simulator.place_order(
        Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.10, stop_loss=quote.ask - 5.0)
    )
    reports = await simulator.on_price_update("XAUUSD", quote.ask - 6.0)
    assert reports[0].position.close_reason == "STOP_LOSS"
    assert simulator.balance < 10_000.0


async def test_pending_limit_order_triggers(simulator: SimulatedBroker) -> None:
    """A buy limit fills once the ask trades down to it."""
    quote = simulator.quote("EURUSD")
    trigger = quote.ask - 0.0020
    report = await simulator.place_order(
        Order(symbol="EURUSD", side=OrderSide.BUY, volume=0.05, order_type=OrderType.LIMIT, price=trigger)
    )
    assert report.order.status is OrderStatus.PENDING
    assert not simulator.positions()

    reports = await simulator.on_price_update("EURUSD", trigger - 0.0005)
    assert reports
    assert len(simulator.positions()) == 1


async def test_pending_order_can_be_cancelled(simulator: SimulatedBroker) -> None:
    """Cancelling a pending order removes it from the book."""
    quote = simulator.quote("EURUSD")
    report = await simulator.place_order(
        Order(symbol="EURUSD", side=OrderSide.BUY, volume=0.05, order_type=OrderType.LIMIT, price=quote.ask - 0.01)
    )
    cancelled = await simulator.cancel_order(report.order.order_id)
    assert cancelled.status is OrderStatus.CANCELLED
    await simulator.on_price_update("EURUSD", quote.ask - 0.02)
    assert not simulator.positions()


async def test_unknown_order_raises(simulator: SimulatedBroker) -> None:
    """Operations on unknown orders raise a typed error."""
    with pytest.raises(OrderNotFoundError):
        await simulator.cancel_order("does-not-exist")


async def test_unknown_position_raises(simulator: SimulatedBroker) -> None:
    """Operations on unknown positions raise a typed error."""
    with pytest.raises(PositionNotFoundError):
        await simulator.close_position("does-not-exist")


async def test_volume_below_minimum_is_rejected(simulator: SimulatedBroker) -> None:
    """A sub-minimum lot size is rejected."""
    with pytest.raises(OrderRejectedError):
        await simulator.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.001))


async def test_insufficient_margin_is_rejected() -> None:
    """An order needing more margin than the account holds is rejected.

    At 1:100, 20 lots of gold require roughly USD 40k of margin against a
    USD 10k account. (The same order is affordable at 1:500, which is why the
    leverage matters here.)
    """
    broker = SimulatedBroker(balance=10_000.0, leverage=100.0, seed=1)
    with pytest.raises(InsufficientMarginError):
        await broker.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=20.0))
    assert not broker.positions()


async def test_margin_scales_with_leverage() -> None:
    """The same position consumes five times less margin at 1:500."""
    low = SimulatedBroker(balance=100_000.0, leverage=100.0, seed=1)
    high = SimulatedBroker(balance=100_000.0, leverage=500.0, seed=1)
    await low.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=1.0))
    await high.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=1.0))
    assert low.account_info().margin == pytest.approx(high.account_info().margin * 5, rel=1e-6)


async def test_close_all_flattens_the_book(simulator: SimulatedBroker) -> None:
    """``close_all`` closes every open position."""
    await simulator.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.05))
    await simulator.place_order(Order(symbol="EURUSD", side=OrderSide.SELL, volume=0.05))
    closed = await simulator.close_all()
    assert len(closed) == 2
    assert not simulator.positions()
    assert len(simulator.history()) == 2


async def test_modify_position_updates_levels(simulator: SimulatedBroker) -> None:
    """Protective levels can be changed after the fill."""
    report = await simulator.place_order(Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.05))
    updated = await simulator.modify_position(report.position.position_id, stop_loss=1900.0, take_profit=2200.0)
    assert updated.stop_loss == 1900.0
    assert updated.take_profit == 2200.0


def test_price_walk_moves_prices(simulator: SimulatedBroker) -> None:
    """The random walk produces ticks for every symbol."""
    before = simulator.quote("EURUSD").mid
    ticks = [simulator.step("EURUSD") for _ in range(200)]
    assert all(len(batch) == 1 for batch in ticks)
    assert simulator.quote("EURUSD").mid != before


async def test_connection_lifecycle() -> None:
    """A simulated connection connects, reports status and disconnects."""
    connection = XMConnection(mode="simulated")
    assert await connection.connect()
    assert connection.is_connected
    assert connection.is_simulated
    status = connection.status()
    assert status["mode"] == "simulated"
    assert status["demo"] is True
    await connection.disconnect()
    assert not connection.is_connected


async def test_account_facade(connection: XMConnection) -> None:
    """The account façade exposes the standard fields."""
    account = XMAccount(connection)
    assert await account.get_balance() > 0
    assert await account.get_equity() > 0
    assert await account.get_leverage() == 500.0
    assert (await account.summary())["mode"] == "simulated"


async def test_orders_facade_round_trip(connection: XMConnection) -> None:
    """The order façade places and lists orders."""
    orders = XMOrders(connection)
    positions = XMPositions(connection)
    quote = connection.simulator.quote("EURUSD")

    report = await orders.place_market_order(
        "EURUSD", 0.05, "BUY", sl=quote.ask - 0.005, tp=quote.ask + 0.010, strategy_id="test"
    )
    assert report.success
    assert len(await orders.get_orders()) == 1

    open_positions = await positions.get_open_positions("EURUSD")
    assert len(open_positions) == 1
    assert open_positions[0].strategy_id == "test"

    closed = await positions.close_position(open_positions[0].position_id, "TEST")
    assert closed.close_reason == "TEST"
    assert not await positions.get_open_positions()


async def test_order_validation_rejects_bad_input(connection: XMConnection) -> None:
    """Unknown symbols and inverted stops are rejected before the broker."""
    orders = XMOrders(connection)
    with pytest.raises(ValidationError):
        await orders.place_market_order("NOTREAL", 0.1, "BUY")
    quote = connection.simulator.quote("EURUSD")
    with pytest.raises(ValidationError):
        # A stop above the entry price for a long would trigger instantly.
        await orders.place_market_order("EURUSD", 0.05, "BUY", sl=quote.ask + 0.01)


async def test_exposure_is_signed(connection: XMConnection) -> None:
    """Exposure nets long and short volume per symbol."""
    orders = XMOrders(connection)
    positions = XMPositions(connection)
    await orders.place_market_order("EURUSD", 0.05, "BUY")
    await orders.place_market_order("XAUUSD", 0.02, "SELL")
    exposure = await positions.exposure()
    assert exposure["EURUSD"] == pytest.approx(0.05)
    assert exposure["XAUUSD"] == pytest.approx(-0.02)
    await positions.close_all()


async def test_websocket_streams_ticks(connection: XMConnection) -> None:
    """The price stream delivers ticks to registered callbacks."""
    stream = XMWebSocket(connection, tick_interval=0.01)
    stream.subscribe_prices(["EURUSD", "XAUUSD"])
    received = []

    async def handler(tick) -> None:
        received.append(tick)

    stream.on_tick(handler)
    await stream.start()
    await asyncio.sleep(0.2)
    await stream.stop()

    assert received
    assert {tick.symbol for tick in received} <= {"EURUSD", "XAUUSD"}
    assert stream.status()["ticks_received"] == len(received)
    assert stream.latest_quote("EURUSD") is not None


def test_simulator_statistics(simulator: SimulatedBroker) -> None:
    """Statistics describe an untouched account correctly."""
    stats = simulator.statistics()
    assert stats["closed_trades"] == 0
    assert stats["balance"] == 10_000.0
    assert stats["return_pct"] == 0.0
