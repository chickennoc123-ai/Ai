"""Message bus used for inter-agent communication.

Two implementations share one interface:

:class:`InMemoryMessageBus`
    Zero-dependency asyncio fan-out, used in tests and single-process runs.
:class:`RedisMessageBus`
    Redis Pub/Sub, used when the platform runs as separate containers.

Both deliver :class:`Message` objects serialised as JSON with the fields
``agent_id``, ``message_type``, ``payload`` and ``timestamp``.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Deque, Dict, List, Mapping, Optional

from utils.config import Config, get_config
from utils.exceptions import MessageBusError
from utils.helpers import new_id, utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

Handler = Callable[["Message"], Awaitable[None]]


class MessageType(str, Enum):
    """Message categories exchanged between agents."""

    SIGNAL = "SIGNAL"
    RISK_ALERT = "RISK_ALERT"
    RESEARCH_FINDING = "RESEARCH_FINDING"
    EXECUTION_REPORT = "EXECUTION_REPORT"
    META_FEEDBACK = "META_FEEDBACK"
    MARKET_UPDATE = "MARKET_UPDATE"
    POSITION_UPDATE = "POSITION_UPDATE"
    COMMAND = "COMMAND"
    HEARTBEAT = "HEARTBEAT"


@dataclass
class Message:
    """A single message travelling on the bus."""

    agent_id: str
    message_type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utcnow)
    message_id: str = field(default_factory=lambda: new_id("msg"))
    correlation_id: Optional[str] = None
    target: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the message."""
        return {
            "message_id": self.message_id,
            "agent_id": self.agent_id,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "target": self.target,
        }

    def to_json(self) -> str:
        """Serialise the message to a JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Message":
        """Rebuild a message from its dictionary form."""
        timestamp = payload.get("timestamp")
        return cls(
            agent_id=str(payload.get("agent_id", "unknown")),
            message_type=MessageType(str(payload.get("message_type", "HEARTBEAT"))),
            payload=dict(payload.get("payload") or {}),
            timestamp=datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else utcnow(),
            message_id=str(payload.get("message_id") or new_id("msg")),
            correlation_id=payload.get("correlation_id"),
            target=payload.get("target"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "Message":
        """Rebuild a message from a JSON string.

        Raises:
            MessageBusError: If the payload cannot be decoded.
        """
        try:
            return cls.from_dict(json.loads(raw))
        except (ValueError, KeyError) as exc:
            raise MessageBusError("Malformed message on the bus", error=str(exc)) from exc


class MessageBus(ABC):
    """Publish/subscribe interface shared by all transports."""

    def __init__(self, namespace: str = "eafactory", history_size: int = 500) -> None:
        """Initialise common bookkeeping."""
        self.namespace = namespace
        self._history: Deque[Message] = deque(maxlen=history_size)
        self._published = 0
        self._delivered = 0

    def topic(self, message_type: MessageType | str) -> str:
        """Return the fully qualified channel name for a message type."""
        value = message_type.value if isinstance(message_type, MessageType) else str(message_type)
        return f"{self.namespace}:{value}"

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport."""

    @abstractmethod
    async def close(self) -> None:
        """Release the transport."""

    @abstractmethod
    async def publish(self, message: Message) -> None:
        """Broadcast ``message`` to every subscriber of its type."""

    @abstractmethod
    async def subscribe(self, message_type: MessageType, handler: Handler) -> None:
        """Register ``handler`` for a message type."""

    def history(self, message_type: Optional[MessageType] = None, limit: int = 100) -> List[Message]:
        """Return recently published messages, newest first."""
        items = list(self._history)[::-1]
        if message_type is not None:
            items = [item for item in items if item.message_type is message_type]
        return items[:limit]

    def stats(self) -> Dict[str, Any]:
        """Return bus counters for monitoring."""
        return {
            "transport": type(self).__name__,
            "namespace": self.namespace,
            "published": self._published,
            "delivered": self._delivered,
            "buffered": len(self._history),
        }


class InMemoryMessageBus(MessageBus):
    """Asyncio fan-out bus with no external dependencies."""

    def __init__(self, namespace: str = "eafactory", history_size: int = 500) -> None:
        """Initialise the in-memory subscriber table."""
        super().__init__(namespace, history_size)
        self._subscribers: Dict[MessageType, List[Handler]] = defaultdict(list)
        self._connected = False

    async def connect(self) -> None:
        """Mark the bus as ready (no-op transport)."""
        self._connected = True
        logger.info("In-memory message bus ready", namespace=self.namespace)

    async def close(self) -> None:
        """Drop every subscriber."""
        self._subscribers.clear()
        self._connected = False

    async def publish(self, message: Message) -> None:
        """Deliver a message to all subscribers concurrently."""
        self._history.append(message)
        self._published += 1
        handlers = list(self._subscribers.get(message.message_type, []))
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(message) for handler in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Message handler failed",
                    handler=getattr(handler, "__qualname__", str(handler)),
                    message_type=message.message_type.value,
                    error=str(result),
                )
            else:
                self._delivered += 1

    async def subscribe(self, message_type: MessageType, handler: Handler) -> None:
        """Register a handler for ``message_type``."""
        self._subscribers[message_type].append(handler)
        logger.debug("Subscriber registered", message_type=message_type.value)


class RedisMessageBus(MessageBus):
    """Redis Pub/Sub transport for multi-process deployments."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        namespace: str = "eafactory",
        history_size: int = 500,
    ) -> None:
        """Store connection parameters (the client is created on connect)."""
        super().__init__(namespace, history_size)
        self.host = host
        self.port = port
        self.db = db
        self._redis: Any = None
        self._pubsub: Any = None
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._listener: Optional[asyncio.Task[None]] = None

    async def connect(self) -> None:
        """Open the Redis connection.

        Raises:
            MessageBusError: If Redis is unreachable.
        """
        try:
            import redis.asyncio as redis_asyncio

            self._redis = redis_asyncio.Redis(
                host=self.host, port=self.port, db=self.db, decode_responses=True
            )
            await self._redis.ping()
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            logger.info("Connected to Redis message bus", host=self.host, port=self.port)
        except Exception as exc:  # noqa: BLE001 - surfaced as MessageBusError
            raise MessageBusError("Unable to connect to Redis", host=self.host, error=str(exc)) from exc

    async def close(self) -> None:
        """Close the listener task and the Redis client."""
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._listener = None
        if self._pubsub is not None:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def publish(self, message: Message) -> None:
        """Publish a message on the Redis channel of its type."""
        if self._redis is None:
            raise MessageBusError("Redis bus is not connected")
        self._history.append(message)
        self._published += 1
        await self._redis.publish(self.topic(message.message_type), message.to_json())

    async def subscribe(self, message_type: MessageType, handler: Handler) -> None:
        """Subscribe to a Redis channel and start the listener if needed."""
        if self._pubsub is None:
            raise MessageBusError("Redis bus is not connected")
        channel = self.topic(message_type)
        if channel not in self._handlers:
            await self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)
        if self._listener is None:
            self._listener = asyncio.create_task(self._listen(), name="redis-bus-listener")

    async def _listen(self) -> None:
        """Consume Redis messages and dispatch them to handlers."""
        assert self._pubsub is not None
        while True:
            try:
                raw = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw is None:
                    await asyncio.sleep(0.01)
                    continue
                channel = str(raw.get("channel"))
                message = Message.from_json(raw.get("data"))
                for handler in list(self._handlers.get(channel, [])):
                    try:
                        await handler(message)
                        self._delivered += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Redis handler failed", channel=channel, error=str(exc))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the listener alive
                logger.warning("Redis listener error", error=str(exc))
                await asyncio.sleep(1.0)


async def create_message_bus(config: Optional[Config] = None) -> MessageBus:
    """Create the configured bus, falling back to in-memory when Redis is down.

    Args:
        config: Optional configuration override.

    Returns:
        A connected :class:`MessageBus`.
    """
    cfg = config or get_config()
    namespace = cfg.get("redis.namespace", "eafactory")
    host = cfg.get("redis.host", "localhost")
    port = cfg.get_int("redis.port", 6379)
    db = cfg.get_int("redis.db", 0)

    bus: MessageBus = RedisMessageBus(host=host, port=port, db=db, namespace=namespace)
    try:
        await bus.connect()
        return bus
    except MessageBusError as exc:
        logger.warning(
            "Falling back to the in-memory message bus", reason=str(exc), host=host, port=port
        )
    fallback = InMemoryMessageBus(namespace=namespace)
    await fallback.connect()
    return fallback
