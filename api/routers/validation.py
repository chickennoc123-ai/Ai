"""Validation endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_validation_service, require_auth
from services.validation_service import ValidationService
from utils.exceptions import DataError, StrategyError, ValidationFailure

router = APIRouter(prefix="/api/v1/validation", tags=["validation"], dependencies=[Depends(require_auth)])


class ValidationRequest(BaseModel):
    """Payload accepted when validating a strategy."""

    name: str = Field(..., examples=["MACD"])
    symbol: str = Field(..., examples=["EURUSD"])
    timeframe: str = "H1"
    bars: Optional[int] = Field(default=None, ge=500, le=30_000)
    params: Dict[str, Any] = Field(default_factory=dict)
    quick: bool = False


class BatchValidationRequest(BaseModel):
    """Payload accepted when validating several strategies."""

    names: List[str]
    symbols: List[str]
    timeframe: str = "H1"
    quick: bool = True


@router.post("/run", summary="Validate a strategy")
async def run_validation(
    request: ValidationRequest, service: ValidationService = Depends(get_validation_service)
) -> Dict[str, Any]:
    """Run walk-forward, PBO, calibration and robustness on one strategy.

    Raises:
        HTTPException: 400 for unknown strategies or unusable data.
    """
    try:
        return await service.validate(
            request.name, request.symbol, request.timeframe, request.bars, request.params, request.quick
        )
    except (StrategyError, DataError, ValidationFailure) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch", summary="Validate several strategies")
async def run_batch(
    request: BatchValidationRequest, service: ValidationService = Depends(get_validation_service)
) -> List[Dict[str, Any]]:
    """Validate every combination and return a ranked summary."""
    return await service.validate_many(request.names, request.symbols, request.timeframe, request.quick)


@router.get("/history", summary="Stored validation reports")
async def history(limit: int = 50, service: ValidationService = Depends(get_validation_service)) -> List[Dict[str, Any]]:
    """Return persisted validation records, newest first."""
    return service.history(min(limit, 500))


@router.get("/{strategy_id}", summary="Fetch a cached report")
async def get_report(
    strategy_id: str, service: ValidationService = Depends(get_validation_service)
) -> Dict[str, Any]:
    """Return a cached validation report.

    Raises:
        HTTPException: 404 when the report is not cached.
    """
    report = service.get_report(strategy_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No cached validation for this strategy id")
    return report
