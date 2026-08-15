"""Real-time WebSocket endpoint.

Clients connect to ``/api/v1/ws`` and receive quote, signal, position and risk
updates.  Control frames are accepted for subscription management:

.. code-block:: json

    {"action": "subscribe", "topics": ["quotes", "risk"]}
    {"action": "ping"}
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from agents.message_bus import Message, MessageType
from api.dependencies import get_state
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

#: Bus message types mirrored to WebSocket clients, with their topic name.
BRIDGED_TOPICS = {
    MessageType.SIGNAL: "signals",
    MessageType.RISK_ALERT: "risk",
    MessageType.POSITION_UPDATE: "positions",
    MessageType.EXECUTION_REPORT: "executions",
    MessageType.RESEARCH_FINDING: "research",
    MessageType.META_FEEDBACK: "meta",
}

_bridged = False


async def ensure_bus_bridge() -> None:
    """Mirror agent bus messages onto the WebSocket hub (idempotent)."""
    global _bridged
    if _bridged:
        return
    state = get_state()
    if state.orchestrator is None or state.orchestrator.bus is None:
        return

    hub = state.hub

    def make_handler(topic: str):
        """Build a bus handler that forwards to ``topic``."""

        async def handler(message: Message) -> None:
            await hub.broadcast(topic, message.payload)

        return handler

    for message_type, topic in BRIDGED_TOPICS.items():
        await state.orchestrator.bus.subscribe(message_type, make_handler(topic))
    _bridged = True
    logger.info("Bus to WebSocket bridge installed", topics=sorted(BRIDGED_TOPICS.values()))


@router.websocket("/api/v1/ws")
async def websocket_endpoint(
    websocket: WebSocket, topics: Optional[str] = Query(default=None)
) -> None:
    """Serve a real-time client connection."""
    state = get_state()
    requested: List[str] = [item.strip() for item in topics.split(",")] if topics else []
    client = await state.hub.connect(websocket, requested or None)
    await ensure_bus_bridge()

    heartbeat = asyncio.create_task(_heartbeat(state, client))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload: Dict[str, Any] = json.loads(raw)
            except ValueError:
                await state.hub.send(client, {"type": "error", "message": "Invalid JSON"})
                continue
            await state.hub.handle_client_message(client, payload)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - never leak a client error into the server
        logger.debug("WebSocket client error", client_id=client.client_id, error=str(exc))
    finally:
        heartbeat.cancel()
        await state.hub.disconnect(client)


async def _heartbeat(state: Any, client: Any) -> None:
    """Push a periodic account/position snapshot to one client."""
    interval = max(state.config.get_float("dashboard.refresh_interval", 5.0), 1.0)
    while True:
        await asyncio.sleep(interval)
        payload: Dict[str, Any] = {"timestamp": utcnow().isoformat()}
        try:
            if state.account is not None:
                info = await state.account.get_info()
                payload["account"] = {"balance": info.balance, "equity": info.equity, "margin": info.margin}
            if state.position_service is not None:
                payload["positions"] = await state.position_service.portfolio_summary()
        except Exception as exc:  # noqa: BLE001
            payload["error"] = str(exc)
        if not await state.hub.send(client, {"type": "system", "data": payload}):
            return
