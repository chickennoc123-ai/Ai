"""Agent orchestrator: builds the shared runtime and supervises the agents.

The orchestrator owns the platform's shared services (broker connection, data
manager, lifecycle, decision engine, price stream) and injects them into every
agent.  It is used both by the FastAPI application and by the standalone
worker process, so the two always run identical wiring.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type

from agents.analysis_agent import AnalysisAgent
from agents.base_agent import AgentStatus, BaseAgent
from agents.execution_agent import ExecutionAgent
from agents.message_bus import Message, MessageBus, MessageType, create_message_bus
from agents.meta_agent import MetaAgent
from agents.research_agent import ResearchAgent
from agents.risk_agent import RiskAgent
from broker.xm_account import XMAccount
from broker.xm_connection import XMConnection
from broker.xm_models import Tick
from broker.xm_orders import XMOrders
from broker.xm_positions import XMPositions
from broker.xm_websocket import XMWebSocket
from core.data_manager import DataManager
from core.decision import DecisionEngine
from core.lifecycle import LifecycleManager
from core.strategy_registry import load_strategies
from utils.config import Config, get_config
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

AGENT_CLASSES: Dict[str, Type[BaseAgent]] = {
    "research": ResearchAgent,
    "analysis": AnalysisAgent,
    "execution": ExecutionAgent,
    "risk": RiskAgent,
    "meta": MetaAgent,
}


class AgentOrchestrator:
    """Creates, starts, monitors and stops the agent fleet."""

    def __init__(self, config: Optional[Config] = None, bus: Optional[MessageBus] = None) -> None:
        """Initialise the orchestrator.

        Args:
            config: Platform configuration.
            bus: Pre-built message bus; one is created on :meth:`setup`
                otherwise.
        """
        self.config = config or get_config()
        self.bus = bus
        self.agents: Dict[str, BaseAgent] = {}
        self.context: Dict[str, Any] = {}
        self.started_at = None
        self.running = False
        self._stream: Optional[XMWebSocket] = None
        self._health_task: Optional[asyncio.Task[None]] = None

    # -- wiring --------------------------------------------------------------
    async def setup(self) -> Dict[str, Any]:
        """Build every shared service and return the injection context."""
        if self.context:
            return self.context

        load_strategies()
        if self.bus is None:
            self.bus = await create_message_bus(self.config)

        connection = XMConnection(config=self.config)
        await connection.connect()

        data_manager = DataManager(self.config)
        lifecycle = LifecycleManager(self.config)
        decision_engine = DecisionEngine(self.config, lifecycle)
        stream = XMWebSocket(
            connection,
            tick_interval=self.config.get_float("data.tick_interval", 1.0),
        )
        stream.subscribe_prices(connection.symbols or data_manager.symbols)
        stream.on_tick(self._on_tick)
        self._stream = stream

        self.context = {
            "config": self.config,
            "bus": self.bus,
            "connection": connection,
            "account": XMAccount(connection),
            "orders": XMOrders(connection),
            "positions": XMPositions(connection),
            "stream": stream,
            "data_manager": data_manager,
            "lifecycle": lifecycle,
            "decision_engine": decision_engine,
            "orchestrator": self,
        }
        logger.info("Runtime context ready", mode=connection.mode, symbols=len(connection.symbols))
        return self.context

    async def _on_tick(self, tick: Tick) -> None:
        """Keep the data manager's live prices in sync with the feed."""
        data_manager: DataManager = self.context["data_manager"]
        data_manager.update_price(tick.symbol, (tick.bid + tick.ask) / 2.0)

    # -- lifecycle -----------------------------------------------------------
    async def start(self, only: Optional[List[str]] = None) -> Dict[str, bool]:
        """Start the price stream and every enabled agent.

        Args:
            only: Restrict startup to these agent names.

        Returns:
            Mapping of agent name to startup success.
        """
        await self.setup()
        assert self.bus is not None

        if self._stream is not None:
            await self._stream.start()

        results: Dict[str, bool] = {}
        for name, agent_class in AGENT_CLASSES.items():
            if only and name not in only:
                continue
            agent = agent_class(config=self.config, bus=self.bus, context=self.context)
            self.agents[name] = agent
            results[name] = await agent.start()

        self.running = any(results.values())
        self.started_at = utcnow()
        if self.running:
            self._health_task = asyncio.create_task(self._health_loop(), name="orchestrator-health")
        logger.info(
            "Agent fleet started",
            started=[name for name, ok in results.items() if ok],
            skipped=[name for name, ok in results.items() if not ok],
        )
        return results

    async def stop(self) -> None:
        """Stop every agent, the stream and the shared connections."""
        self.running = False
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._health_task = None

        await asyncio.gather(*(agent.stop() for agent in self.agents.values()), return_exceptions=True)
        self.agents.clear()

        if self._stream is not None:
            await self._stream.stop()
        connection: Optional[XMConnection] = self.context.get("connection")
        if connection is not None:
            await connection.disconnect()
        data_manager: Optional[DataManager] = self.context.get("data_manager")
        if data_manager is not None:
            await data_manager.close()
        if self.bus is not None:
            await self.bus.close()
        self.context.clear()
        logger.info("Agent fleet stopped")

    async def _health_loop(self) -> None:
        """Periodically log agent health and restart failed agents."""
        interval = self.config.get_float("monitoring.health_check_interval", 30.0)
        while self.running:
            await asyncio.sleep(interval)
            for name, agent in list(self.agents.items()):
                if agent.status is AgentStatus.FAILED:
                    logger.error("Restarting failed agent", agent=name)
                    try:
                        await agent.stop()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed agent did not stop cleanly", agent=name, error=str(exc))
                    restarted = AGENT_CLASSES[name](config=self.config, bus=self.bus, context=self.context)
                    self.agents[name] = restarted
                    await restarted.start()

    # -- control -------------------------------------------------------------
    def agent(self, name: str) -> Optional[BaseAgent]:
        """Return an agent by name."""
        return self.agents.get(name)

    async def send_command(self, command: str, target: Optional[str] = None, **payload: Any) -> None:
        """Broadcast a command message to the fleet."""
        if self.bus is None:
            return
        await self.bus.publish(
            Message(
                agent_id="orchestrator",
                message_type=MessageType.COMMAND,
                payload={"command": command, **payload},
                target=target,
            )
        )
        logger.info("Command dispatched", command=command, target=target or "all")

    async def restart_agent(self, name: str) -> bool:
        """Stop and start a single agent."""
        agent = self.agents.get(name)
        if agent is None:
            return False
        await agent.stop()
        replacement = AGENT_CLASSES[name](config=self.config, bus=self.bus, context=self.context)
        self.agents[name] = replacement
        return await replacement.start()

    # -- reporting -----------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        """Return a health snapshot of the fleet and its transport."""
        uptime = (utcnow() - self.started_at).total_seconds() if self.started_at else 0.0
        connection: Optional[XMConnection] = self.context.get("connection")
        return {
            "running": self.running,
            "uptime_seconds": round(uptime, 1),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "agents": {name: agent.health() for name, agent in self.agents.items()},
            "bus": self.bus.stats() if self.bus else {},
            "broker": connection.status() if connection else {},
            "stream": self._stream.status() if self._stream else {},
        }

    def reports(self) -> Dict[str, Any]:
        """Collect the per-agent reports exposed by the API."""
        payload: Dict[str, Any] = {}
        for name, agent in self.agents.items():
            reporter = getattr(agent, "report", None)
            if callable(reporter):
                try:
                    payload[name] = reporter()
                except Exception as exc:  # noqa: BLE001
                    payload[name] = {"error": str(exc)}
        return payload
