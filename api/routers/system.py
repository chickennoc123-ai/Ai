"""System, agent and metrics endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.orchestrator import AgentOrchestrator
from api.dependencies import AppState, get_orchestrator, get_state, require_auth
from core.utils import PerformanceMetrics, compute_metrics

router = APIRouter(prefix="/api/v1", tags=["system"], dependencies=[Depends(require_auth)])


class CommandRequest(BaseModel):
    """Payload accepted when broadcasting a command to the agents."""

    command: str
    target: Optional[str] = None
    payload: Dict[str, Any] = {}


@router.get("/status", summary="System status")
async def status(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Return the aggregated health of every subsystem."""
    return state.health()


@router.get("/agents", summary="Agent health")
async def agents(orchestrator: AgentOrchestrator = Depends(get_orchestrator)) -> Dict[str, Any]:
    """Return the health of every agent."""
    return orchestrator.health()


@router.get("/agents/reports", summary="Agent reports")
async def agent_reports(orchestrator: AgentOrchestrator = Depends(get_orchestrator)) -> Dict[str, Any]:
    """Return the detailed report published by each agent."""
    return orchestrator.reports()


@router.post("/agents/{name}/restart", summary="Restart an agent")
async def restart_agent(
    name: str, orchestrator: AgentOrchestrator = Depends(get_orchestrator)
) -> Dict[str, Any]:
    """Restart a single agent.

    Raises:
        HTTPException: 404 when the agent is unknown.
    """
    if orchestrator.agent(name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    started = await orchestrator.restart_agent(name)
    return {"agent": name, "restarted": started}


@router.post("/commands", summary="Broadcast a command")
async def send_command(
    request: CommandRequest, orchestrator: AgentOrchestrator = Depends(get_orchestrator)
) -> Dict[str, Any]:
    """Publish a command message on the agent bus."""
    await orchestrator.send_command(request.command, request.target, **request.payload)
    return {"dispatched": True, "command": request.command, "target": request.target}


@router.get("/messages", summary="Recent bus messages")
async def messages(
    limit: int = 50, orchestrator: AgentOrchestrator = Depends(get_orchestrator)
) -> List[Dict[str, Any]]:
    """Return recent messages seen on the agent bus."""
    if orchestrator.bus is None:
        return []
    return [message.to_dict() for message in orchestrator.bus.history(limit=min(limit, 500))]


@router.get("/metrics", summary="Platform metrics")
async def metrics(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Return trading, risk and agent metrics in one payload."""
    payload: Dict[str, Any] = {"account": {}, "positions": {}, "risk": {}, "agents": {}, "trading": {}}

    if state.account is not None:
        try:
            payload["account"] = (await state.account.get_info()).to_dict()
        except Exception as exc:  # noqa: BLE001 - metrics must never fail hard
            payload["account"] = {"error": str(exc)}

    if state.position_service is not None:
        payload["positions"] = await state.position_service.portfolio_summary()

    if state.orchestrator is not None:
        reports = state.orchestrator.reports()
        payload["risk"] = reports.get("risk", {}).get("metrics", {})
        payload["agents"] = {
            name: {
                "status": health["status"],
                "cycles": health["metrics"]["cycles"],
                "errors": health["metrics"]["errors"],
            }
            for name, health in state.orchestrator.health().get("agents", {}).items()
        }
        execution = reports.get("execution", {})
        payload["trading"] = {
            "executions": execution.get("execution_count", 0),
            "rejections": execution.get("rejection_count", 0),
            "halted": execution.get("halted", False),
        }

    if state.connection is not None and state.connection.is_simulated:
        payload["simulator"] = state.connection.simulator.statistics()
    return payload


@router.get("/metrics/performance", summary="Realised performance")
async def performance(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Compute realised performance metrics from the closed-trade history."""
    if state.position_service is None:
        return {"trades": 0}
    history = await state.position_service.history(days=365)
    if not history:
        return PerformanceMetrics().to_dict()

    initial = state.config.get_float("backtest.initial_capital", 10_000.0)
    equity = [initial]
    pnls: List[float] = []
    for position in sorted(history, key=lambda item: item.get("closed_at") or ""):
        pnl = float(position.get("net_profit", 0.0))
        pnls.append(pnl)
        equity.append(equity[-1] + pnl)
    return compute_metrics(equity, pnls, periods_per_year=252, initial_capital=initial).to_dict()


@router.get("/events", summary="Audit log")
async def events(limit: int = 100, state: AppState = Depends(get_state)) -> List[Dict[str, Any]]:
    """Return recent audit-log entries."""
    if state.database is None:
        return []
    from models.database import session_scope
    from models.metrics import SystemEvent

    with session_scope(state.database) as session:
        records = (
            session.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(min(limit, 1000)).all()
        )
        return [record.to_dict() for record in records]


@router.get("/notifications", summary="Recent notifications")
async def notifications(limit: int = 50, state: AppState = Depends(get_state)) -> List[Dict[str, Any]]:
    """Return recent notifications."""
    if state.notifications is None:
        return []
    return state.notifications.recent(limit)
