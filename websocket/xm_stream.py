"""Bridge between the XM price stream and the rest of the platform.

The bridge subscribes to :class:`broker.xm_websocket.XMWebSocket` and fans each
tick out to:

* the :class:`core.data_manager.DataManager` live price cache,
* the time-series store (InfluxDB) through the market data service,
* the agent message bus (throttled ``MARKET_UPDATE`` messages),
* every dashboard client attached to the :class:`websocket.handler.ConnectionHub`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agents.message_bus import Message, MessageBus, MessageType
from broker.xm_models import Tick
from broker.xm_websocket import XMWebSocket
from core.data_manager import DataManager
from services.market_data import MarketDataService
from utils.helpers import utcnow
from utils.logger import get_logger
from websocket.handler import ConnectionHub

logger = get_logger(__name__)


class XMStreamBridge:
    """Distributes broker ticks to consumers, with per-symbol throttling."""

    def __init__(
        self,
        stream: XMWebSocket,
        hub: Optional[ConnectionHub] = None,
        bus: Optional[MessageBus] = None,
        data_manager: Optional[DataManager] = None,
        market_data: Optional[MarketDataService] = None,
        publish_interval: float = 1.0,
    ) -> None:
        """Initialise the bridge.

        Args:
            stream: Broker price stream.
            hub: Dashboard connection hub.
            bus: Agent message bus.
            data_manager: Live price cache.
            market_data: Service used for time-series persistence.
            publish_interval: Minimum seconds between two published updates of
                the same symbol.
        """
        self.stream = stream
        self.hub = hub
        self.bus = bus
        self.data_manager = data_manager
        self.market_data = market_data
        self.publish_interval = publish_interval
        self._last_published: Dict[str, float] = {}
        self.ticks_processed = 0
        self.updates_published = 0

    async def start(self) -> None:
        """Register the tick handler and start the stream."""
        self.stream.on_tick(self.on_tick)
        await self.stream.start()
        logger.info("XM stream bridge started", publish_interval=self.publish_interval)

    async def stop(self) -> None:
        """Stop the underlying stream."""
        await self.stream.stop()
        logger.info(
            "XM stream bridge stopped",
            ticks=self.ticks_processed,
            published=self.updates_published,
        )

    async def on_tick(self, tick: Tick) -> None:
        """Handle a single tick from the broker."""
        self.ticks_processed += 1
        mid = (tick.bid + tick.ask) / 2.0

        if self.data_manager is not None:
            self.data_manager.update_price(tick.symbol, mid)
        if self.market_data is not None:
            self.market_data.record_quote(tick.symbol, tick.bid, tick.ask)

        now = tick.timestamp.timestamp()
        last = self._last_published.get(tick.symbol, 0.0)
        if now - last < self.publish_interval:
            return
        self._last_published[tick.symbol] = now
        self.updates_published += 1

        payload: Dict[str, Any] = {
            "symbol": tick.symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "mid": round(mid, 6),
            "spread": round(tick.ask - tick.bid, 6),
            "timestamp": tick.timestamp.isoformat(),
        }
        if self.hub is not None:
            await self.hub.broadcast("quotes", payload)
        if self.bus is not None:
            await self.bus.publish(
                Message(agent_id="market-stream", message_type=MessageType.MARKET_UPDATE, payload=payload)
            )

    def status(self) -> Dict[str, Any]:
        """Return bridge statistics."""
        return {
            "ticks_processed": self.ticks_processed,
            "updates_published": self.updates_published,
            "publish_interval": self.publish_interval,
            "stream": self.stream.status(),
            "clients": self.hub.client_count if self.hub else 0,
            "checked_at": utcnow().isoformat(),
        }
