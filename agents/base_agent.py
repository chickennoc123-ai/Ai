"""Base class for all AI agents.

An agent owns a periodic work loop plus any number of message subscriptions.
Subclasses implement three methods:

``initialize``
    Acquire resources; return ``False`` to abort startup.
``execute_cycle``
    The periodic unit of work, called every ``interval`` seconds.
``process``
    Handle a message delivered by the bus.

Failures inside a cycle never kill the agent: they are counted, logged with the
agent context and the loop continues, degrading gracefully.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.message_bus import Message, MessageBus, MessageType
from utils.config import Config, get_config
from utils.helpers import correlation_id, utcnow
from utils.logger import BoundLogger, get_logger


class AgentStatus(str, Enum):
    """Runtime status of an agent."""

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class AgentMetrics:
    """Counters describing an agent's activity."""

    cycles: int = 0
    messages_processed: int = 0
    messages_published: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    last_cycle_at: Optional[datetime] = None
    last_error: str = ""
    started_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the metrics."""
        uptime = (utcnow() - self.started_at).total_seconds() if self.started_at else 0.0
        return {
            "cycles": self.cycles,
            "messages_processed": self.messages_processed,
            "messages_published": self.messages_published,
            "errors": self.errors,
            "consecutive_errors": self.consecutive_errors,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_error": self.last_error,
            "uptime_seconds": round(uptime, 1),
        }


class BaseAgent(ABC):
    """Common lifecycle, messaging and health-reporting for every agent."""

    #: Message types the agent subscribes to.
    subscriptions: List[MessageType] = []

    def __init__(
        self,
        name: str,
        config: Optional[Config] = None,
        bus: Optional[MessageBus] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the agent.

        Args:
            name: Agent name, also used as the configuration key
                (``agents.<name>``) and as ``agent_id`` on the bus.
            config: Platform configuration.
            bus: Message bus used for publish/subscribe.
            context: Shared services injected by the orchestrator (data
                manager, broker façades, registries ...).
        """
        self.name = name
        self.config = config or get_config()
        self.bus = bus
        self.context: Dict[str, Any] = context or {}
        self.settings = self.config.section(f"agents.{name}") if f"agents.{name}" in self.config else Config({})
        self.enabled = self.settings.get_bool("enabled", True)
        self.interval = float(self.settings.get_float("interval", 60.0))
        self.logger: BoundLogger = get_logger(f"agent.{name}", agent_id=name)
        self.status = AgentStatus.CREATED
        self.metrics = AgentMetrics()
        self.running = False
        self.tasks: List[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()

    # -- abstract surface ----------------------------------------------------
    @abstractmethod
    async def initialize(self) -> bool:
        """Prepare the agent. Return ``False`` to prevent startup."""

    @abstractmethod
    async def execute_cycle(self) -> None:
        """Perform one unit of periodic work."""

    @abstractmethod
    async def process(self, message: Message) -> Optional[Message]:
        """Handle an incoming message, optionally returning a reply."""

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> bool:
        """Initialise, subscribe and launch the work loop.

        Returns:
            ``True`` when the agent is running.
        """
        if not self.enabled:
            self.logger.info("Agent disabled by configuration")
            self.status = AgentStatus.STOPPED
            return False
        self.status = AgentStatus.STARTING
        try:
            if not await self.initialize():
                self.status = AgentStatus.FAILED
                self.logger.error("Agent initialisation returned False")
                return False
        except Exception as exc:  # noqa: BLE001 - startup must report, not crash the process
            self.status = AgentStatus.FAILED
            self.metrics.last_error = str(exc)
            self.logger.error("Agent initialisation failed", error=str(exc), exc_info=True)
            return False

        if self.bus is not None:
            for message_type in self.subscriptions:
                await self.bus.subscribe(message_type, self._on_message)

        self.running = True
        self._stop_event.clear()
        self.metrics.started_at = utcnow()
        self.status = AgentStatus.RUNNING
        self.tasks.append(asyncio.create_task(self.run(), name=f"agent-{self.name}"))
        self.logger.info("Agent started", interval=self.interval)
        return True

    async def run(self) -> None:
        """Main loop: run a cycle, then wait for the configured interval."""
        while self.running:
            await self._run_cycle()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                return  # stop requested
            except asyncio.TimeoutError:
                continue

    async def _run_cycle(self) -> None:
        """Execute one cycle with error isolation and health tracking."""
        try:
            await self.execute_cycle()
            self.metrics.cycles += 1
            self.metrics.consecutive_errors = 0
            self.metrics.last_cycle_at = utcnow()
            if self.status is AgentStatus.DEGRADED:
                self.status = AgentStatus.RUNNING
                self.logger.info("Agent recovered")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - an agent must survive a bad cycle
            self.metrics.errors += 1
            self.metrics.consecutive_errors += 1
            self.metrics.last_error = str(exc)
            self.logger.error("Agent cycle failed", error=str(exc), exc_info=True)
            if self.metrics.consecutive_errors >= 3:
                self.status = AgentStatus.DEGRADED
            if self.metrics.consecutive_errors >= 10:
                self.status = AgentStatus.FAILED
                self.logger.error("Agent failed after repeated errors, stopping")
                self.running = False

    async def stop(self) -> None:
        """Stop the loop and cancel outstanding tasks."""
        if not self.running and self.status is AgentStatus.STOPPED:
            return
        self.running = False
        self._stop_event.set()
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        await self.shutdown()
        self.status = AgentStatus.STOPPED
        self.logger.info("Agent stopped", cycles=self.metrics.cycles, errors=self.metrics.errors)

    async def shutdown(self) -> None:
        """Release agent specific resources (override when needed)."""

    # -- messaging -----------------------------------------------------------
    async def _on_message(self, message: Message) -> None:
        """Bus callback wrapping :meth:`process` with error isolation."""
        if message.agent_id == self.name:
            return  # never react to our own messages
        if message.target and message.target != self.name:
            return
        try:
            reply = await self.process(message)
            self.metrics.messages_processed += 1
            if reply is not None:
                await self.publish(reply.message_type, reply.payload, reply.correlation_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.metrics.errors += 1
            self.metrics.last_error = str(exc)
            self.logger.error(
                "Message processing failed",
                message_type=message.message_type.value,
                sender=message.agent_id,
                error=str(exc),
            )

    async def publish(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
        correlation: Optional[str] = None,
        target: Optional[str] = None,
    ) -> Optional[Message]:
        """Publish a message on the bus.

        Args:
            message_type: Category of the message.
            payload: JSON-serialisable body.
            correlation: Correlation id tying related messages together.
            target: Optional agent name for point-to-point delivery.

        Returns:
            The published message, or ``None`` when no bus is attached.
        """
        if self.bus is None:
            return None
        message = Message(
            agent_id=self.name,
            message_type=message_type,
            payload=payload,
            correlation_id=correlation or correlation_id(),
            target=target,
        )
        await self.bus.publish(message)
        self.metrics.messages_published += 1
        return message

    # -- helpers -------------------------------------------------------------
    def service(self, key: str, default: Any = None) -> Any:
        """Return a shared service injected by the orchestrator."""
        return self.context.get(key, default)

    def require_service(self, key: str) -> Any:
        """Return a shared service, raising when it is missing.

        Raises:
            KeyError: If the service was not injected.
        """
        if key not in self.context:
            raise KeyError(f"Agent '{self.name}' requires the '{key}' service")
        return self.context[key]

    def health(self) -> Dict[str, Any]:
        """Return a health snapshot for the API and dashboard."""
        return {
            "name": self.name,
            "status": self.status.value,
            "enabled": self.enabled,
            "interval": self.interval,
            "running": self.running,
            "metrics": self.metrics.to_dict(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} name={self.name} status={self.status.value}>"
