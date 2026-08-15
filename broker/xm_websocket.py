"""Streaming quotes from XMTrading.

In ``simulated`` mode ticks are produced by the local matching engine at a
configurable cadence; in ``rest`` mode the class opens a WebSocket to the
gateway, subscribes to the requested symbols and reconnects with exponential
backoff when the socket drops.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from broker.xm_connection import XMConnection
from broker.xm_models import Quote, Tick
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

TickCallback = Callable[[Tick], Awaitable[None]]
QuoteCallback = Callable[[Quote], Awaitable[None]]


class XMWebSocket:
    """Maintains the market data subscription for a set of symbols."""

    def __init__(
        self,
        connection: XMConnection,
        tick_interval: float = 1.0,
        reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
    ) -> None:
        """Initialise the stream.

        Args:
            connection: Broker connection providing the transport.
            tick_interval: Seconds between synthetic ticks in simulated mode.
            reconnect_delay: Initial backoff after a disconnection.
            max_reconnect_delay: Upper bound of the backoff.
        """
        self.connection = connection
        self.tick_interval = tick_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._symbols: List[str] = []
        self._tick_callbacks: List[TickCallback] = []
        self._quote_callbacks: List[QuoteCallback] = []
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._latest: Dict[str, Quote] = {}
        self._ticks_received = 0
        self._last_tick_at = None

    # -- subscription --------------------------------------------------------
    def subscribe_prices(self, symbols: Iterable[str]) -> None:
        """Register the symbols to stream."""
        self._symbols = [str(symbol).upper() for symbol in symbols]
        logger.info("Subscribed to price stream", symbols=self._symbols)

    def on_tick(self, callback: TickCallback) -> None:
        """Register an async callback invoked for every tick."""
        self._tick_callbacks.append(callback)

    def on_price_update(self, callback: QuoteCallback) -> None:
        """Register an async callback invoked for every quote update."""
        self._quote_callbacks.append(callback)

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        """Start streaming in the background."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="xm-websocket")
        logger.info("Price stream started", mode=self.connection.mode, symbols=len(self._symbols))

    async def stop(self) -> None:
        """Stop streaming and wait for the background task to finish."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown must not raise
                pass
            self._task = None
        logger.info("Price stream stopped", ticks_received=self._ticks_received)

    async def _run(self) -> None:
        """Dispatch to the simulated or real transport, with reconnection."""
        delay = self.reconnect_delay
        while self._running:
            try:
                if self.connection.is_simulated:
                    await self._run_simulated()
                else:
                    await self._run_websocket()
                delay = self.reconnect_delay
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the stream must survive anything
                logger.warning("Price stream error, reconnecting", error=str(exc), delay=round(delay, 1))
                await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
                delay = min(delay * 2, self.max_reconnect_delay)

    async def _run_simulated(self) -> None:
        """Generate ticks locally from the simulated broker."""
        simulator = self.connection.simulator
        while self._running:
            for tick in simulator.step():
                if self._symbols and tick.symbol not in self._symbols:
                    continue
                await simulator.on_price_update(tick.symbol)
                await self._dispatch(tick)
            await asyncio.sleep(self.tick_interval)

    async def _run_websocket(self) -> None:
        """Consume the real WebSocket feed."""
        import websockets

        url = self.connection.ws_url
        headers = {"Authorization": header} if (header := self.connection.headers.get("Authorization")) else {}
        async with websockets.connect(url, additional_headers=headers, ping_interval=20) as socket:
            await socket.send(json.dumps({"action": "subscribe", "symbols": self._symbols}))
            logger.info("WebSocket connected", url=url, symbols=len(self._symbols))
            async for message in socket:
                if not self._running:
                    break
                tick = self._parse(message)
                if tick is not None:
                    await self._dispatch(tick)

    @staticmethod
    def _parse(message: Any) -> Optional[Tick]:
        """Parse a raw WebSocket frame into a :class:`Tick`."""
        try:
            payload = json.loads(message) if isinstance(message, (str, bytes)) else dict(message)
        except (ValueError, TypeError):
            logger.debug("Discarding unparsable frame")
            return None
        symbol = payload.get("symbol") or payload.get("s")
        bid, ask = payload.get("bid", payload.get("b")), payload.get("ask", payload.get("a"))
        if not symbol or bid is None or ask is None:
            return None
        return Tick(
            symbol=str(symbol).upper(),
            bid=float(bid),
            ask=float(ask),
            volume=float(payload.get("volume", 0.0) or 0.0),
        )

    async def _dispatch(self, tick: Tick) -> None:
        """Fan a tick out to every registered callback."""
        self._ticks_received += 1
        self._last_tick_at = utcnow()
        quote = tick.to_quote()
        self._latest[tick.symbol] = quote
        for callback in list(self._tick_callbacks):
            try:
                await callback(tick)
            except Exception as exc:  # noqa: BLE001 - one bad subscriber must not stop the feed
                logger.warning("Tick callback failed", error=str(exc))
        for callback in list(self._quote_callbacks):
            try:
                await callback(quote)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Quote callback failed", error=str(exc))

    # -- accessors -----------------------------------------------------------
    def latest_quote(self, symbol: str) -> Optional[Quote]:
        """Return the most recent quote for ``symbol``."""
        return self._latest.get(symbol.upper())

    def latest_quotes(self) -> Dict[str, Quote]:
        """Return the most recent quote of every streamed symbol."""
        return dict(self._latest)

    def status(self) -> Dict[str, Any]:
        """Return stream diagnostics."""
        return {
            "running": self._running,
            "mode": self.connection.mode,
            "symbols": self._symbols,
            "ticks_received": self._ticks_received,
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "subscribers": len(self._tick_callbacks) + len(self._quote_callbacks),
        }
