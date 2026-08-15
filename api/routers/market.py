"""Market data endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import AppState, get_market_service, get_state, require_auth
from core.utils import INSTRUMENTS
from services.market_data import MarketDataService
from utils.exceptions import DataError
from utils.validators import ValidationError

router = APIRouter(prefix="/api/v1/market", tags=["market"], dependencies=[Depends(require_auth)])


@router.get("/symbols", summary="Tradable instruments")
async def symbols() -> List[Dict[str, Any]]:
    """Return the contract specification of every supported instrument."""
    return [
        {
            "symbol": spec.symbol,
            "digits": spec.digits,
            "pip_size": spec.pip_size,
            "contract_size": spec.contract_size,
            "min_lot": spec.min_lot,
            "max_lot": spec.max_lot,
            "lot_step": spec.lot_step,
            "typical_spread_pips": spec.typical_spread_pips,
            "category": spec.category,
            "quote_currency": spec.quote_currency,
        }
        for spec in INSTRUMENTS.values()
    ]


@router.get("/snapshot", summary="All-symbol snapshot")
async def snapshot(
    timeframe: str = "H1", service: MarketDataService = Depends(get_market_service)
) -> List[Dict[str, Any]]:
    """Return a one-line summary for every tradable symbol."""
    return await service.snapshot(timeframe)


@router.get("/quotes", summary="Latest streamed quotes")
async def quotes(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Return the most recent quote of every streamed symbol."""
    if state.orchestrator is None or state.data_manager is None:
        return {}
    stream = state.orchestrator.context.get("stream")
    if stream is not None:
        latest = stream.latest_quotes()
        if latest:
            return {symbol: quote.to_dict() for symbol, quote in latest.items()}
    return {symbol: {"symbol": symbol, "mid": price} for symbol, price in state.data_manager.latest_prices().items()}


@router.get("/{symbol}", summary="Candles and indicators")
async def market_data(
    symbol: str,
    timeframe: str = "H1",
    bars: int = Query(default=300, ge=10, le=5000),
    indicators: Optional[str] = Query(default=None, description="Comma separated indicator keys"),
    service: MarketDataService = Depends(get_market_service),
) -> Dict[str, Any]:
    """Return OHLCV candles with optional indicator overlays.

    Raises:
        HTTPException: 400 for unknown symbols or timeframes.
    """
    indicator_list = [item.strip() for item in indicators.split(",")] if indicators else None
    try:
        return await service.get_market_payload(symbol, timeframe, bars, indicator_list)
    except (ValidationError, DataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
