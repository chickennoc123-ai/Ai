"""Order endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_order_service, require_auth
from services.order_service import OrderService
from utils.exceptions import BrokerError, OrderNotFoundError, OrderRejectedError
from utils.validators import ValidationError

router = APIRouter(prefix="/api/v1/orders", tags=["orders"], dependencies=[Depends(require_auth)])


class OrderRequest(BaseModel):
    """Payload accepted when placing an order."""

    symbol: str = Field(..., examples=["XAUUSD"])
    volume: float = Field(..., gt=0, examples=[0.10])
    direction: str = Field(..., examples=["BUY"])
    order_type: str = Field(default="MARKET", examples=["MARKET", "LIMIT", "STOP"])
    price: Optional[float] = Field(default=None, description="Required for LIMIT/STOP orders")
    sl: Optional[float] = Field(default=None, description="Stop-loss price")
    tp: Optional[float] = Field(default=None, description="Take-profit price")
    strategy_id: Optional[str] = None
    comment: str = ""


class OrderUpdate(BaseModel):
    """Payload accepted when modifying a pending order."""

    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None


@router.get("", summary="List orders")
async def list_orders(
    status_filter: Optional[str] = None, service: OrderService = Depends(get_order_service)
) -> List[Dict[str, Any]]:
    """List broker orders, optionally filtered by status."""
    try:
        return await service.list_orders(status_filter)
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/history", summary="Persisted order history")
async def order_history(limit: int = 100, service: OrderService = Depends(get_order_service)) -> List[Dict[str, Any]]:
    """Return persisted orders, newest first."""
    return service.history(min(limit, 1000))


@router.get("/{order_id}", summary="Get one order")
async def get_order(order_id: str, service: OrderService = Depends(get_order_service)) -> Dict[str, Any]:
    """Return a single order.

    Raises:
        HTTPException: 404 when the order does not exist.
    """
    try:
        return await service.get(order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", status_code=201, summary="Place an order")
async def place_order(
    request: OrderRequest, service: OrderService = Depends(get_order_service)
) -> Dict[str, Any]:
    """Place a market, limit or stop order.

    Raises:
        HTTPException: 400 on validation errors, 409 when the broker rejects
            the order, 502 on transport failures.
    """
    try:
        return await service.place(request.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OrderRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/{order_id}", summary="Modify a pending order")
async def modify_order(
    order_id: str, request: OrderUpdate, service: OrderService = Depends(get_order_service)
) -> Dict[str, Any]:
    """Modify the price or protective levels of a pending order."""
    try:
        return await service.modify(order_id, request.price, request.sl, request.tp)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrderRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{order_id}", summary="Cancel a pending order")
async def cancel_order(order_id: str, service: OrderService = Depends(get_order_service)) -> Dict[str, Any]:
    """Cancel a pending order."""
    try:
        return await service.cancel(order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrderRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
