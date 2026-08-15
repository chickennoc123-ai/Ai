"""Backtest endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_backtest_service, require_auth
from services.backtest_service import BacktestService
from utils.exceptions import DataError, StrategyError

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"], dependencies=[Depends(require_auth)])


class BacktestRequest(BaseModel):
    """Payload accepted when running a backtest."""

    name: str = Field(..., examples=["RSI"])
    symbol: str = Field(..., examples=["XAUUSD"])
    timeframe: str = Field(default="H1")
    bars: Optional[int] = Field(default=None, ge=200, le=30_000)
    params: Dict[str, Any] = Field(default_factory=dict)
    commission: Optional[float] = None
    slippage: Optional[float] = None
    initial_capital: Optional[float] = None
    risk_per_trade: Optional[float] = None
    persist: bool = False


class MatrixRequest(BaseModel):
    """Payload accepted when running a strategy/symbol matrix."""

    names: List[str]
    symbols: List[str]
    timeframe: str = "H1"
    bars: Optional[int] = None


class PortfolioRequest(MatrixRequest):
    """Payload accepted when running a portfolio backtest."""

    weights: Optional[Dict[str, float]] = None


@router.post("/run", summary="Run a backtest")
async def run_backtest(
    request: BacktestRequest, service: BacktestService = Depends(get_backtest_service)
) -> Dict[str, Any]:
    """Backtest one strategy on one symbol.

    Raises:
        HTTPException: 400 for unknown strategies or unusable data.
    """
    overrides = {
        key: value
        for key, value in {
            "commission": request.commission,
            "slippage": request.slippage,
            "initial_capital": request.initial_capital,
            "risk_per_trade": request.risk_per_trade,
        }.items()
        if value is not None
    }
    try:
        return await service.run(
            request.name,
            request.symbol,
            request.timeframe,
            request.bars,
            request.params,
            overrides or None,
            request.persist,
        )
    except (StrategyError, DataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/matrix", summary="Backtest a strategy/symbol matrix")
async def run_matrix(
    request: MatrixRequest, service: BacktestService = Depends(get_backtest_service)
) -> List[Dict[str, Any]]:
    """Backtest every combination and return a ranked summary."""
    return await service.run_matrix(request.names, request.symbols, request.timeframe, request.bars)


@router.post("/portfolio", summary="Backtest a portfolio")
async def run_portfolio(
    request: PortfolioRequest, service: BacktestService = Depends(get_backtest_service)
) -> Dict[str, Any]:
    """Backtest several strategies together and return the blended curve."""
    return await service.run_portfolio(
        request.names, request.symbols, request.timeframe, request.bars, request.weights
    )


@router.get("/results", summary="Cached result ids")
async def cached_results(service: BacktestService = Depends(get_backtest_service)) -> List[str]:
    """Return the ids of cached backtest results."""
    return service.cached_results()


@router.get("/{strategy_id}", summary="Fetch a cached result")
async def get_result(
    strategy_id: str, service: BacktestService = Depends(get_backtest_service)
) -> Dict[str, Any]:
    """Return a cached backtest result including the equity curve.

    Raises:
        HTTPException: 404 when the result is not cached.
    """
    result = service.get_result(strategy_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No cached result for this strategy id")
    return result
