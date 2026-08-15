"""XMTrading broker integration.

The package exposes a small, broker-agnostic surface:

* :class:`XMConnection` - session management and transport (simulated or REST).
* :class:`XMAccount` - balance, equity, margin and leverage.
* :class:`XMOrders` - order placement, modification and cancellation.
* :class:`XMPositions` - open positions and position history.
* :class:`XMWebSocket` - streaming quotes.

``mode: simulated`` (the default) runs a complete local matching engine so the
platform is fully functional without credentials; ``mode: rest`` talks to an
XM-compatible REST/WebSocket gateway.
"""

from broker.xm_account import XMAccount
from broker.xm_connection import XMConnection
from broker.xm_models import (
    AccountInfo,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Tick,
)
from broker.xm_orders import XMOrders
from broker.xm_positions import XMPositions
from broker.xm_websocket import XMWebSocket

__all__ = [
    "AccountInfo",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "Quote",
    "Tick",
    "XMAccount",
    "XMConnection",
    "XMOrders",
    "XMPositions",
    "XMWebSocket",
]
