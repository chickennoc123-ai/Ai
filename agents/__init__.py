"""Multi-agent trading system.

Five specialised agents cooperate over a message bus:

===============  =========================================================
Agent            Responsibility
===============  =========================================================
Research         Discovers and evolves new strategies (LLM + evolutionary)
Analysis         Reads the market and emits trading signals
Execution        Turns signals into broker orders
Risk             Enforces the risk envelope in real time
Meta             Supervises the whole system and tunes it
===============  =========================================================
"""

from agents.base_agent import AgentStatus, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType, create_message_bus
from agents.orchestrator import AgentOrchestrator

__all__ = [
    "AgentOrchestrator",
    "AgentStatus",
    "BaseAgent",
    "Message",
    "MessageBus",
    "MessageType",
    "create_message_bus",
]
