"""Input validation helpers shared by the API, agents and broker layers."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from utils.helpers import TIMEFRAME_MINUTES
from utils.exceptions import ConfigurationError, EAFactoryError

SUPPORTED_SYMBOLS = ("XAUUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD")
SUPPORTED_DIRECTIONS = ("BUY", "SELL")
SUPPORTED_ORDER_TYPES = ("MARKET", "LIMIT", "STOP")


class ValidationError(EAFactoryError):
    """Raised when user supplied input fails validation."""


def validate_symbol(symbol: str, allowed: Optional[Iterable[str]] = None) -> str:
    """Normalise and validate a trading symbol.

    Args:
        symbol: Raw symbol string (case insensitive).
        allowed: Optional whitelist, defaults to the platform symbols.

    Returns:
        The upper-cased symbol.

    Raises:
        ValidationError: If the symbol is unknown.
    """
    if not symbol or not isinstance(symbol, str):
        raise ValidationError("Symbol must be a non-empty string", symbol=symbol)
    normalised = symbol.strip().upper()
    whitelist = tuple(allowed) if allowed is not None else SUPPORTED_SYMBOLS
    if normalised not in whitelist:
        raise ValidationError("Unsupported symbol", symbol=normalised, allowed=list(whitelist))
    return normalised


def validate_timeframe(timeframe: str) -> str:
    """Normalise and validate a timeframe label."""
    if not timeframe or not isinstance(timeframe, str):
        raise ValidationError("Timeframe must be a non-empty string", timeframe=timeframe)
    normalised = timeframe.strip().upper()
    if normalised not in TIMEFRAME_MINUTES:
        raise ValidationError(
            "Unsupported timeframe", timeframe=normalised, allowed=sorted(TIMEFRAME_MINUTES)
        )
    return normalised


def validate_direction(direction: str) -> str:
    """Normalise and validate an order direction."""
    if not direction or not isinstance(direction, str):
        raise ValidationError("Direction must be a non-empty string", direction=direction)
    normalised = direction.strip().upper()
    if normalised in {"LONG", "B"}:
        normalised = "BUY"
    if normalised in {"SHORT", "S"}:
        normalised = "SELL"
    if normalised not in SUPPORTED_DIRECTIONS:
        raise ValidationError("Direction must be BUY or SELL", direction=direction)
    return normalised


def validate_order_type(order_type: str) -> str:
    """Normalise and validate an order type."""
    normalised = str(order_type or "").strip().upper()
    if normalised not in SUPPORTED_ORDER_TYPES:
        raise ValidationError(
            "Unsupported order type", order_type=order_type, allowed=list(SUPPORTED_ORDER_TYPES)
        )
    return normalised


def validate_volume(volume: float, min_lot: float = 0.01, max_lot: float = 100.0) -> float:
    """Validate a lot size lies within the tradable range."""
    try:
        value = float(volume)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Volume must be numeric", volume=volume) from exc
    if math.isnan(value) or value <= 0:
        raise ValidationError("Volume must be positive", volume=volume)
    if value < min_lot:
        raise ValidationError("Volume below broker minimum", volume=value, min_lot=min_lot)
    if value > max_lot:
        raise ValidationError("Volume above broker maximum", volume=value, max_lot=max_lot)
    return value


def validate_price(price: Optional[float], field: str = "price", required: bool = True) -> Optional[float]:
    """Validate an optional price field."""
    if price is None:
        if required:
            raise ValidationError(f"{field} is required")
        return None
    try:
        value = float(price)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be numeric", value=price) from exc
    if math.isnan(value) or value <= 0:
        raise ValidationError(f"{field} must be positive", value=price)
    return value


def validate_stop_levels(
    direction: str, entry_price: float, stop_loss: Optional[float], take_profit: Optional[float]
) -> None:
    """Ensure SL/TP sit on the correct side of the entry price.

    Raises:
        ValidationError: If a protective level would trigger immediately.
    """
    side = validate_direction(direction)
    if stop_loss is not None:
        if side == "BUY" and stop_loss >= entry_price:
            raise ValidationError("Stop loss must be below entry for BUY", sl=stop_loss, entry=entry_price)
        if side == "SELL" and stop_loss <= entry_price:
            raise ValidationError("Stop loss must be above entry for SELL", sl=stop_loss, entry=entry_price)
    if take_profit is not None:
        if side == "BUY" and take_profit <= entry_price:
            raise ValidationError("Take profit must be above entry for BUY", tp=take_profit, entry=entry_price)
        if side == "SELL" and take_profit >= entry_price:
            raise ValidationError("Take profit must be below entry for SELL", tp=take_profit, entry=entry_price)


def validate_fraction(value: float, field: str, lower: float = 0.0, upper: float = 1.0) -> float:
    """Validate a fractional configuration value."""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field} must be numeric", value=value) from exc
    if not lower <= result <= upper:
        raise ConfigurationError(f"{field} out of range", value=result, lower=lower, upper=upper)
    return result


def validate_order_request(payload: Dict[str, Any], allowed_symbols: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Validate and normalise a raw order request dictionary.

    Args:
        payload: Mapping with ``symbol``, ``volume``, ``direction`` and optional
            ``order_type``, ``price``, ``sl``, ``tp``.
        allowed_symbols: Optional symbol whitelist.

    Returns:
        A normalised copy of the request.
    """
    order_type = validate_order_type(payload.get("order_type", "MARKET"))
    normalised: Dict[str, Any] = {
        "symbol": validate_symbol(payload.get("symbol", ""), allowed_symbols),
        "volume": validate_volume(payload.get("volume", 0.0)),
        "direction": validate_direction(payload.get("direction", "")),
        "order_type": order_type,
        "price": validate_price(payload.get("price"), "price", required=order_type != "MARKET"),
        "sl": validate_price(payload.get("sl"), "sl", required=False),
        "tp": validate_price(payload.get("tp"), "tp", required=False),
        "comment": str(payload.get("comment", ""))[:64],
        "strategy_id": payload.get("strategy_id"),
    }
    if normalised["price"] is not None:
        validate_stop_levels(
            normalised["direction"], normalised["price"], normalised["sl"], normalised["tp"]
        )
    return normalised
