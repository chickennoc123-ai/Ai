"""Tests for the message bus, the agents and the orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from agents.analysis_agent import AnalysisAgent
from agents.base_agent import AgentStatus, BaseAgent
from agents.execution_agent import ExecutionAgent
from agents.message_bus import InMemoryMessageBus, Message, MessageType
from agents.orchestrator import AgentOrchestrator
from agents.research_agent import CodeValidator
from agents.risk_agent import RiskAgent
from broker.xm_account import XMAccount
from broker.xm_connection import XMConnection
from broker.xm_orders import XMOrders
from broker.xm_positions import XMPositions
from core.data_manager import DataManager
from core.decision import DecisionEngine
from core.lifecycle import LifecycleManager
from utils.config import get_config


@pytest.fixture
async def bus() -> Any:
    """Return a connected in-memory bus."""
    transport = InMemoryMessageBus()
    await transport.connect()
    try:
        yield transport
    finally:
        await transport.close()


@pytest.fixture
async def context(connection: XMConnection, bus: InMemoryMessageBus) -> Dict[str, Any]:
    """Return a service context wired to the simulated broker."""
    config = get_config()
    lifecycle = LifecycleManager(config)
    return {
        "config": config,
        "bus": bus,
        "connection": connection,
        "account": XMAccount(connection),
        "orders": XMOrders(connection),
        "positions": XMPositions(connection),
        "data_manager": DataManager(config),
        "lifecycle": lifecycle,
        "decision_engine": DecisionEngine(config, lifecycle),
    }


# -- message bus -------------------------------------------------------------
def test_message_round_trips_through_json() -> None:
    """Messages survive JSON serialisation."""
    original = Message(
        agent_id="analysis",
        message_type=MessageType.SIGNAL,
        payload={"symbol": "XAUUSD", "direction": 1},
        correlation_id="corr-1",
    )
    restored = Message.from_json(original.to_json())
    assert restored.agent_id == "analysis"
    assert restored.message_type is MessageType.SIGNAL
    assert restored.payload["symbol"] == "XAUUSD"
    assert restored.correlation_id == "corr-1"


async def test_bus_delivers_to_subscribers(bus: InMemoryMessageBus) -> None:
    """Every subscriber of a type receives the message."""
    received: List[Message] = []

    async def handler(message: Message) -> None:
        received.append(message)

    await bus.subscribe(MessageType.SIGNAL, handler)
    await bus.publish(Message(agent_id="test", message_type=MessageType.SIGNAL, payload={"a": 1}))
    assert len(received) == 1
    assert bus.stats()["published"] == 1


async def test_bus_isolates_handler_failures(bus: InMemoryMessageBus) -> None:
    """A failing handler does not prevent delivery to the others."""
    delivered: List[str] = []

    async def bad(_: Message) -> None:
        raise RuntimeError("boom")

    async def good(_: Message) -> None:
        delivered.append("ok")

    await bus.subscribe(MessageType.SIGNAL, bad)
    await bus.subscribe(MessageType.SIGNAL, good)
    await bus.publish(Message(agent_id="test", message_type=MessageType.SIGNAL))
    assert delivered == ["ok"]


async def test_bus_history(bus: InMemoryMessageBus) -> None:
    """The bus keeps a bounded, filterable history."""
    await bus.publish(Message(agent_id="a", message_type=MessageType.SIGNAL))
    await bus.publish(Message(agent_id="b", message_type=MessageType.RISK_ALERT))
    assert len(bus.history()) == 2
    assert len(bus.history(MessageType.SIGNAL)) == 1


# -- base agent --------------------------------------------------------------
class _CountingAgent(BaseAgent):
    """Minimal agent used to exercise the base lifecycle."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("analysis", **kwargs)  # reuse an existing config section
        self.interval = 0.05
        self.cycles_run = 0
        self.fail = False

    async def initialize(self) -> bool:
        """Always initialise successfully."""
        return True

    async def execute_cycle(self) -> None:
        """Count cycles, optionally raising to test error isolation."""
        self.cycles_run += 1
        if self.fail:
            raise RuntimeError("cycle failure")

    async def process(self, message: Message) -> None:
        """Ignore inbound messages."""
        return None


async def test_agent_runs_cycles(bus: InMemoryMessageBus) -> None:
    """A started agent runs its cycle repeatedly and stops cleanly."""
    agent = _CountingAgent(bus=bus)
    assert await agent.start()
    await asyncio.sleep(0.2)
    await agent.stop()
    assert agent.cycles_run >= 2
    assert agent.status is AgentStatus.STOPPED


async def test_agent_survives_cycle_errors(bus: InMemoryMessageBus) -> None:
    """Errors are counted and degrade the agent instead of killing it."""
    agent = _CountingAgent(bus=bus)
    agent.fail = True
    await agent.start()
    await asyncio.sleep(0.25)
    status = agent.status
    await agent.stop()
    assert agent.metrics.errors >= 2
    assert status in (AgentStatus.RUNNING, AgentStatus.DEGRADED)


async def test_agent_ignores_its_own_messages(bus: InMemoryMessageBus) -> None:
    """An agent never reacts to a message it published itself."""
    agent = _CountingAgent(bus=bus)
    await agent.start()
    await agent.publish(MessageType.SIGNAL, {"x": 1})
    await asyncio.sleep(0.05)
    await agent.stop()
    assert agent.metrics.messages_processed == 0
    assert agent.metrics.messages_published == 1


# -- analysis agent ----------------------------------------------------------
async def test_analysis_agent_publishes_context(context: Dict[str, Any], bus: InMemoryMessageBus) -> None:
    """The analysis agent produces market context and signal payloads."""
    agent = AnalysisAgent(config=get_config(), bus=bus, context=context)
    agent.symbols = ["EURUSD"]
    agent.active_strategies = ["RSI", "MACD"]
    assert await agent.initialize()
    await agent.execute_cycle()

    report = agent.report()
    assert "EURUSD" in report["context"]
    context_payload = report["context"]["EURUSD"]
    assert context_payload["regime"] in {"TRENDING", "RANGING", "VOLATILE", "QUIET"}
    assert context_payload["trend"] in {"UP", "DOWN", "FLAT"}

    signal = report["signals"]["EURUSD"]
    assert signal["direction"] in (-1, 0, 1)
    assert 0.0 <= signal["confidence"] <= 1.0
    assert signal["contributors"]


# -- execution agent ---------------------------------------------------------
async def test_execution_agent_places_an_order(
    context: Dict[str, Any], bus: InMemoryMessageBus, sample_signal: Dict[str, Any]
) -> None:
    """A valid signal results in a broker order."""
    agent = ExecutionAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    sample_signal["entry_price"] = context["connection"].simulator.quote("XAUUSD").ask

    await agent.handle_signal(sample_signal)
    positions = await context["positions"].get_open_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "XAUUSD"
    assert agent.report()["execution_count"] == 1
    await context["positions"].close_all()


async def test_execution_agent_ignores_a_duplicate_signal(
    context: Dict[str, Any], bus: InMemoryMessageBus, sample_signal: Dict[str, Any]
) -> None:
    """The same signal twice does not double the position."""
    agent = ExecutionAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    sample_signal["entry_price"] = context["connection"].simulator.quote("XAUUSD").ask

    await agent.handle_signal(sample_signal)
    await agent.handle_signal(sample_signal)
    assert len(await context["positions"].get_open_positions()) == 1
    await context["positions"].close_all()


async def test_execution_agent_reverses_on_opposite_signal(
    context: Dict[str, Any], bus: InMemoryMessageBus, sample_signal: Dict[str, Any]
) -> None:
    """An opposite signal flips the position."""
    agent = ExecutionAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    quote = context["connection"].simulator.quote("XAUUSD")
    sample_signal["entry_price"] = quote.ask
    await agent.handle_signal(sample_signal)

    opposite = dict(sample_signal, direction=-1, stop_loss=quote.ask + 6.0, take_profit=quote.ask - 12.0)
    await agent.handle_signal(opposite)

    positions = await context["positions"].get_open_positions()
    assert len(positions) == 1
    assert positions[0].direction == -1
    await context["positions"].close_all()


async def test_execution_agent_halts_on_critical_risk(
    context: Dict[str, Any], bus: InMemoryMessageBus, sample_signal: Dict[str, Any]
) -> None:
    """A critical risk alert stops new orders."""
    agent = ExecutionAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    await agent.process(
        Message(
            agent_id="risk",
            message_type=MessageType.RISK_ALERT,
            payload={"level": "CRITICAL", "action": "HALT", "reason": "test"},
        )
    )
    assert agent.halted

    await agent.handle_signal(sample_signal)
    assert not await context["positions"].get_open_positions()
    assert agent.report()["rejection_count"] == 1


# -- risk agent --------------------------------------------------------------
async def test_risk_agent_computes_metrics(context: Dict[str, Any], bus: InMemoryMessageBus) -> None:
    """The risk agent produces a complete metric set."""
    agent = RiskAgent(config=get_config(), bus=bus, context=context)
    assert await agent.initialize()
    metrics = await agent.compute_metrics()
    for key in ("equity", "drawdown", "var", "cvar", "exposure", "margin_level"):
        assert key in metrics
    assert metrics["equity"] > 0
    assert metrics["drawdown"] >= 0


async def test_risk_agent_flags_a_drawdown_breach(context: Dict[str, Any], bus: InMemoryMessageBus) -> None:
    """A drawdown beyond the kill switch produces a HALT directive."""
    agent = RiskAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    breaches = agent.evaluate_limits(
        {
            "drawdown": 0.30,
            "var": 0.001,
            "exposure": 0.1,
            "exposure_by_symbol": {},
            "margin_level": 5000.0,
        }
    )
    assert breaches
    assert breaches[0]["level"] == "CRITICAL"
    assert breaches[0]["action"] == "HALT"
    assert breaches[0]["close_positions"] is True


async def test_risk_agent_flags_symbol_concentration(context: Dict[str, Any], bus: InMemoryMessageBus) -> None:
    """Per-symbol exposure limits are enforced."""
    agent = RiskAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    breaches = agent.evaluate_limits(
        {
            "drawdown": 0.0,
            "var": 0.001,
            "exposure": 0.2,
            "exposure_by_symbol": {"XAUUSD": 0.9},
            "margin_level": 5000.0,
        }
    )
    assert any(item["limit"] == "max_symbol_exposure" for item in breaches)


async def test_risk_agent_is_quiet_within_limits(context: Dict[str, Any], bus: InMemoryMessageBus) -> None:
    """No alert is raised while every metric is inside its limit."""
    agent = RiskAgent(config=get_config(), bus=bus, context=context)
    await agent.initialize()
    assert not agent.evaluate_limits(
        {
            "drawdown": 0.01,
            "var": 0.001,
            "exposure": 0.05,
            "exposure_by_symbol": {"EURUSD": 0.05},
            "margin_level": 3000.0,
        }
    )


# -- research agent ----------------------------------------------------------
def test_code_validator_accepts_a_valid_module() -> None:
    """A well-formed generated strategy passes validation."""
    code = '''
from strategies.base_strategy import BaseStrategy
from core.strategy_registry import register_strategy
import pandas as pd

@register_strategy
class Generated(BaseStrategy):
    name = "GEN"
    def compute_signals(self, df):
        return self.build_frame(df, pd.Series(0, index=df.index))
'''
    valid, problems = CodeValidator().validate(code)
    assert valid, problems


def test_code_validator_blocks_dangerous_imports() -> None:
    """Filesystem and process access is refused."""
    code = '''
import os
import subprocess
from strategies.base_strategy import BaseStrategy
from core.strategy_registry import register_strategy

@register_strategy
class Bad(BaseStrategy):
    def compute_signals(self, df):
        return df
'''
    valid, problems = CodeValidator().validate(code)
    assert not valid
    assert any("os" in problem or "subprocess" in problem for problem in problems)


def test_code_validator_blocks_eval() -> None:
    """Dynamic evaluation is refused."""
    code = '''
from strategies.base_strategy import BaseStrategy
from core.strategy_registry import register_strategy

@register_strategy
class Bad(BaseStrategy):
    def compute_signals(self, df):
        return eval("df")
'''
    valid, problems = CodeValidator().validate(code)
    assert not valid
    assert any("eval" in problem for problem in problems)


def test_code_validator_rejects_syntax_errors() -> None:
    """Unparsable code is refused before it ever reaches disk."""
    valid, problems = CodeValidator().validate("def broken(:\n  pass")
    assert not valid
    assert "Syntax error" in problems[0]


def test_code_validator_requires_the_registration_decorator() -> None:
    """A module that never registers anything is useless and refused."""
    valid, problems = CodeValidator().validate("import pandas as pd\ndef compute_signals(df):\n    return df\n")
    assert not valid
    assert any("register_strategy" in problem for problem in problems)


# -- orchestrator ------------------------------------------------------------
@pytest.mark.integration
async def test_orchestrator_starts_and_stops() -> None:
    """The orchestrator wires the runtime and shuts it down cleanly."""
    config = get_config().merged(
        {
            "agents": {
                "research": {"enabled": False},
                "analysis": {"enabled": False},
                "meta": {"enabled": False},
                "execution": {"interval": 5},
                "risk": {"interval": 5},
            }
        }
    )
    orchestrator = AgentOrchestrator(config)
    results = await orchestrator.start()
    try:
        assert results["execution"] is True
        assert results["risk"] is True
        assert results["research"] is False  # disabled by configuration

        health = orchestrator.health()
        assert health["running"]
        assert health["broker"]["mode"] == "simulated"
        assert set(health["agents"]) == {"research", "analysis", "execution", "risk", "meta"}

        reports = orchestrator.reports()
        assert "execution" in reports
    finally:
        await orchestrator.stop()
    assert not orchestrator.agents


@pytest.mark.integration
async def test_signal_flows_from_bus_to_broker(sample_signal: Dict[str, Any]) -> None:
    """A signal published on the bus reaches the broker as an order."""
    config = get_config().merged(
        {
            "agents": {
                "research": {"enabled": False},
                "analysis": {"enabled": False},
                "meta": {"enabled": False},
                "risk": {"enabled": False},
                "execution": {"interval": 30},
            }
        }
    )
    orchestrator = AgentOrchestrator(config)
    await orchestrator.start()
    try:
        connection = orchestrator.context["connection"]
        sample_signal["entry_price"] = connection.simulator.quote("XAUUSD").ask
        await orchestrator.bus.publish(
            Message(agent_id="analysis", message_type=MessageType.SIGNAL, payload=sample_signal)
        )
        await asyncio.sleep(0.3)
        positions = await orchestrator.context["positions"].get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "XAUUSD"
    finally:
        await orchestrator.stop()
