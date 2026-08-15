"""Server-side WebSocket hub for dashboard and API clients.

Clients connect to ``/api/v1/ws``, optionally subscribe to a set of topics
(``quotes``, ``signals``, ``positions``, ``risk``, ``all``) and receive JSON
frames pushed by the platform.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set

from utils.helpers import new_id, utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TOPICS = {"quotes", "signals", "positions", "risk", "system"}


class ClientConnection:
    """A single connected browser/API client."""

    def __init__(self, websocket: Any, client_id: str) -> None:
        """Wrap a Starlette/FastAPI WebSocket."""
        self.websocket = websocket
        self.client_id = client_id
        self.topics: Set[str] = set(DEFAULT_TOPICS)
        self.connected_at = utcnow()
        self.messages_sent = 0

    def wants(self, topic: str) -> bool:
        """``True`` when the client subscribed to ``topic``."""
        return "all" in self.topics or topic in self.topics

    def status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot."""
        return {
            "client_id": self.client_id,
            "topics": sorted(self.topics),
            "connected_at": self.connected_at.isoformat(),
            "messages_sent": self.messages_sent,
        }


class ConnectionHub:
    """Tracks connected clients and broadcasts topic-filtered messages."""

    def __init__(self) -> None:
        """Initialise the hub."""
        self._clients: Dict[str, ClientConnection] = {}
        self._lock = asyncio.Lock()
        self.messages_broadcast = 0

    async def connect(self, websocket: Any, topics: Optional[List[str]] = None) -> ClientConnection:
        """Accept a client connection and register it."""
        await websocket.accept()
        client = ClientConnection(websocket, new_id("ws"))
        if topics:
            client.topics = {topic.strip().lower() for topic in topics if topic.strip()}
        async with self._lock:
            self._clients[client.client_id] = client
        logger.info("Dashboard client connected", client_id=client.client_id, clients=len(self._clients))
        await self.send(client, {"type": "welcome", "client_id": client.client_id, "topics": sorted(client.topics)})
        return client

    async def disconnect(self, client: ClientConnection) -> None:
        """Forget a client."""
        async with self._lock:
            self._clients.pop(client.client_id, None)
        logger.info("Dashboard client disconnected", client_id=client.client_id, clients=len(self._clients))

    async def send(self, client: ClientConnection, payload: Dict[str, Any]) -> bool:
        """Send one payload to one client."""
        try:
            await client.websocket.send_json(payload)
            client.messages_sent += 1
            return True
        except Exception as exc:  # noqa: BLE001 - a dead client is not an error
            logger.debug("Client send failed", client_id=client.client_id, error=str(exc))
            return False

    async def broadcast(self, topic: str, payload: Dict[str, Any]) -> int:
        """Broadcast a payload to every client subscribed to ``topic``.

        Returns:
            The number of clients that received the message.
        """
        async with self._lock:
            targets = [client for client in self._clients.values() if client.wants(topic)]
        if not targets:
            return 0
        message = {"type": topic, "timestamp": utcnow().isoformat(), "data": payload}
        results = await asyncio.gather(*(self.send(client, message) for client in targets))
        delivered = sum(1 for result in results if result)
        self.messages_broadcast += delivered

        stale = [client for client, ok in zip(targets, results) if not ok]
        for client in stale:
            await self.disconnect(client)
        return delivered

    async def handle_client_message(self, client: ClientConnection, message: Dict[str, Any]) -> None:
        """Process an inbound control frame from a client."""
        action = str(message.get("action", "")).lower()
        if action == "subscribe":
            topics = message.get("topics") or []
            client.topics.update(str(topic).lower() for topic in topics)
            await self.send(client, {"type": "subscribed", "topics": sorted(client.topics)})
        elif action == "unsubscribe":
            for topic in message.get("topics") or []:
                client.topics.discard(str(topic).lower())
            await self.send(client, {"type": "unsubscribed", "topics": sorted(client.topics)})
        elif action == "ping":
            await self.send(client, {"type": "pong", "timestamp": utcnow().isoformat()})

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)

    def status(self) -> Dict[str, Any]:
        """Return hub statistics."""
        return {
            "clients": self.client_count,
            "messages_broadcast": self.messages_broadcast,
            "connections": [client.status() for client in self._clients.values()],
        }
