"""Position endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_position_service, require_auth
from services.position_service import PositionService
from utils.exceptions import BrokerError, PositionNotFoundError

router = APIRouter(prefix="/api/v1/positions", tags=["positions"], dependencies=[Depends(require_auth)])


class PositionUpdate(BaseModel):
    """Payload accepted when modifying protective levels."""

    sl: Optional[float] = None
    tp: Optional[float] = None


class CloseRequest(BaseModel):
    """Payload accepted when closing positions."""

    reason: str = "MANUAL"
    symbol: Optional[str] = None


@router.get("", summary="List open positions")
async def list_positions(
    symbol: Optional[str] = None, service: PositionService = Depends(get_position_service)
) -> List[Dict[str, Any]]:
    """Return the currently open positions."""
    try:
        return await service.list_open(symbol)
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/summary", summary="Portfolio exposure summary")
async def summary(service: PositionService = Depends(get_position_service)) -> Dict[str, Any]:
    """Return aggregated exposure and floating P&L."""
    return await service.portfolio_summary()


@router.get("/history", summary="Closed position history")
async def history(
    symbol: Optional[str] = None, days: int = 30, service: PositionService = Depends(get_position_service)
) -> List[Dict[str, Any]]:
    """Return closed positions from the last ``days`` days."""
    return await service.history(symbol, min(days, 365))


@router.get("/{position_id}", summary="Get one position")
async def get_position(
    position_id: str, service: PositionService = Depends(get_position_service)
) -> Dict[str, Any]:
    """Return a single open position.

    Raises:
        HTTPException: 404 when the position does not exist.
    """
    try:
        return await service.get(position_id)
    except PositionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/close-all", summary="Close every open position")
async def close_all(
    request: CloseRequest, service: PositionService = Depends(get_position_service)
) -> List[Dict[str, Any]]:
    """Close all open positions, optionally filtered by symbol."""
    return await service.close_all(request.symbol, request.reason)


@router.post("/{position_id}/close", summary="Close one position")
async def close_position(
    position_id: str, request: CloseRequest, service: PositionService = Depends(get_position_service)
) -> Dict[str, Any]:
    """Close a single position."""
    try:
        return await service.close(position_id, request.reason)
    except PositionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{position_id}", summary="Modify protective levels")
async def modify_position(
    position_id: str, request: PositionUpdate, service: PositionService = Depends(get_position_service)
) -> Dict[str, Any]:
    """Update the stop-loss and take-profit of a position."""
    try:
        return await service.modify(position_id, request.sl, request.tp)
    except PositionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
