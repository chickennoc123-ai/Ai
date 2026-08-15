"""Outbound WebSocket connection manager.

Maintains any number of client connections (market data, news, third-party
feeds), each with its own callback, automatic reconnection with exponential
backoff and per-connection statistics.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Awaitable, Callable, Dict, List, Optional

from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

MessageHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class ManagedConnection:
    """State for one managed WebSocket client connection."""

    def __init__(self, client_id: str, url: str, handler: MessageHandler, subscribe: Optional[Dict[str, Any]] = None) -> None:
        """Initialise the connection record."""
        self.client_id = client_id
        self.url = url
        self.handler = handler
        self.subscribe_payload = subscribe
        self.socket: Any = None
        self.task: Optional[asyncio.Task[None]] = None
        self.connected = False
        self.messages_received = 0
        self.reconnects = 0
        self.last_message_at = None
        self.last_error = ""

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot."""
        return {
            "client_id": self.client_id,
            "url": self.url,
            "connected": self.connected,
            "messages_received": self.messages_received,
            "reconnects": self.reconnects,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "last_error": self.last_error,
        }


class WebSocketManager:
    """Manages outbound WebSocket connections and message distribution."""

    def __init__(
        self,
        reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
        ping_interval: float = 20.0,
    ) -> None:
        """Initialise the manager."""
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval
        self.connections: Dict[str, ManagedConnection] = {}
        self.subscribers: Dict[str, List[MessageHandler]] = {}
        self._running = True

    # -- connections ---------------------------------------------------------
    async def connect(
        self,
        url: str,
        client_id: str,
        callback: MessageHandler,
        subscribe: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Open a managed connection.

        Args:
            url: WebSocket URL.
            client_id: Unique name for the connection.
            callback: Coroutine invoked for each decoded message.
            subscribe: Optional payload sent right after the handshake.

        Returns:
            ``True`` when the connection task was started.
        """
        if client_id in self.connections:
            logger.warning("Connection already registered", client_id=client_id)
            return False
        connection = ManagedConnection(client_id, url, callback, subscribe)
        self.connections[client_id] = connection
        connection.task = asyncio.create_task(self._maintain(connection), name=f"ws-{client_id}")
        logger.info("WebSocket connection registered", client_id=client_id, url=url)
        return True

    async def _maintain(self, connection: ManagedConnection) -> None:
        """Keep one connection alive, reconnecting with backoff."""
        delay = self.reconnect_delay
        while self._running:
            try:
                await self._session(connection)
                delay = self.reconnect_delay
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on anything
                connection.connected = False
                connection.last_error = str(exc)
                connection.reconnects += 1
                sleep_for = delay + random.uniform(0, delay * 0.25)
                logger.warning(
                    "WebSocket disconnected, reconnecting",
                    client_id=connection.client_id,
                    error=str(exc),
                    delay=round(sleep_for, 1),
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, self.max_reconnect_delay)

    async def _session(self, connection: ManagedConnection) -> None:
        """Run a single connection session until it closes."""
        import websockets

        async with websockets.connect(connection.url, ping_interval=self.ping_interval) as socket:
            connection.socket = socket
            connection.connected = True
            logger.info("WebSocket connected", client_id=connection.client_id)
            if connection.subscribe_payload:
                await socket.send(json.dumps(connection.subscribe_payload))
            async for raw in socket:
                if not self._running:
                    break
                connection.messages_received += 1
                connection.last_message_at = utcnow()
                data = self._decode(raw)
                if data is None:
                    continue
                await self._deliver(connection, data)
        connection.connected = False

    @staticmethod
    def _decode(raw: Any) -> Optional[Dict[str, Any]]:
        """Decode a raw frame into a dictionary."""
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _deliver(self, connection: ManagedConnection, data: Dict[str, Any]) -> None:
        """Invoke the connection callback and any topic subscribers."""
        try:
            await connection.handler(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Connection handler failed", client_id=connection.client_id, error=str(exc))
        for handler in list(self.subscribers.get(connection.client_id, [])):
            try:
                await handler(data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Subscriber failed", client_id=connection.client_id, error=str(exc))

    # -- messaging -----------------------------------------------------------
    def subscribe(self, client_id: str, handler: MessageHandler) -> None:
        """Attach an extra handler to an existing connection."""
        self.subscribers.setdefault(client_id, []).append(handler)

    async def send(self, client_id: str, message: Dict[str, Any]) -> bool:
        """Send a message on one connection."""
        connection = self.connections.get(client_id)
        if connection is None or not connection.connected or connection.socket is None:
            return False
        try:
            await connection.socket.send(json.dumps(message))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket send failed", client_id=client_id, error=str(exc))
            return False

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """Send a message on every connected socket, returning the fan-out count."""
        results = await asyncio.gather(
            *(self.send(client_id, message) for client_id in list(self.connections)),
            return_exceptions=True,
        )
        return sum(1 for result in results if result is True)

    # -- lifecycle -----------------------------------------------------------
    async def disconnect(self, client_id: str) -> None:
        """Close and forget one connection."""
        connection = self.connections.pop(client_id, None)
        if connection is None:
            return
        if connection.task is not None:
            connection.task.cancel()
            try:
                await connection.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if connection.socket is not None:
            try:
                await connection.socket.close()
            except Exception:  # noqa: BLE001
                pass
        logger.info("WebSocket connection closed", client_id=client_id)

    async def close_all(self) -> None:
        """Close every managed connection."""
        self._running = False
        for client_id in list(self.connections):
            await self.disconnect(client_id)

    def status(self) -> Dict[str, Any]:
        """Return the status of every managed connection."""
        return {
            "running": self._running,
            "connections": [connection.status() for connection in self.connections.values()],
        }
