"""Strategy endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import AppState, get_state, get_strategy_service, require_auth
from services.strategy_service import StrategyService
from utils.exceptions import StrategyError

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"], dependencies=[Depends(require_auth)])


class StrategyCreate(BaseModel):
    """Payload accepted when configuring a strategy instance."""

    name: str = Field(..., examples=["RSI"])
    symbol: str = Field(..., examples=["XAUUSD"])
    timeframe: str = Field(default="H1", examples=["H1"])
    params: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class StrategyUpdate(BaseModel):
    """Payload accepted when updating a configured strategy."""

    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    allocation: Optional[float] = None


@router.get("", summary="List configured strategies")
async def list_strategies(service: StrategyService = Depends(get_strategy_service)) -> Dict[str, Any]:
    """Return the strategy catalogue and every configured instance."""
    return {
        "available": service.names(),
        "catalogue": service.catalogue(),
        "configured": service.list_configured(),
    }


@router.get("/catalogue", summary="Strategy catalogue")
async def catalogue(service: StrategyService = Depends(get_strategy_service)) -> List[Dict[str, Any]]:
    """Return metadata for every registered strategy class."""
    return service.catalogue()


@router.get("/lifecycle", summary="Lifecycle snapshot")
async def lifecycle(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Return the lifecycle state of every tracked strategy."""
    if state.lifecycle is None:
        return {"counts": {}, "total": 0, "strategies": {}}
    return state.lifecycle.snapshot()


@router.get("/{name}/parameters", summary="Parameter search space")
async def parameters(name: str, service: StrategyService = Depends(get_strategy_service)) -> List[Dict[str, Any]]:
    """Return the tunable parameters of a strategy.

    Raises:
        HTTPException: 404 when the strategy name is unknown.
    """
    try:
        return service.parameter_space(name)
    except StrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", status_code=201, summary="Configure a strategy")
async def create_strategy_endpoint(
    request: StrategyCreate, service: StrategyService = Depends(get_strategy_service)
) -> Dict[str, Any]:
    """Persist a new strategy configuration.

    Raises:
        HTTPException: 400 when the strategy is unknown or already configured.
    """
    try:
        return service.create(request.name, request.symbol, request.timeframe, request.params, request.enabled)
    except StrategyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{strategy_id}", summary="Update a configured strategy")
async def update_strategy(
    strategy_id: str, request: StrategyUpdate, service: StrategyService = Depends(get_strategy_service)
) -> Dict[str, Any]:
    """Update parameters, allocation or the enabled flag."""
    updates = {key: value for key, value in request.model_dump().items() if value is not None}
    try:
        return service.update(strategy_id, updates)
    except StrategyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{strategy_id}", summary="Delete a configured strategy")
async def delete_strategy(
    strategy_id: str, service: StrategyService = Depends(get_strategy_service)
) -> Dict[str, bool]:
    """Remove a configured strategy.

    Raises:
        HTTPException: 404 when nothing was deleted.
    """
    if not service.delete(strategy_id):
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"deleted": True}


@router.post("/{strategy_id}/pause", summary="Pause a strategy")
async def pause_strategy(strategy_id: str, state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Move a strategy to the PAUSED lifecycle state."""
    if state.lifecycle is None:
        raise HTTPException(status_code=503, detail="Lifecycle manager unavailable")
    state.lifecycle.pause(strategy_id, "Paused via API")
    return state.lifecycle.get_strategy_status(strategy_id)


@router.post("/{strategy_id}/resume", summary="Resume a strategy")
async def resume_strategy(strategy_id: str, state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Move a paused strategy back to DEGRADED (probation)."""
    if state.lifecycle is None:
        raise HTTPException(status_code=503, detail="Lifecycle manager unavailable")
    state.lifecycle.resume(strategy_id, "Resumed via API")
    return state.lifecycle.get_strategy_status(strategy_id)
