"""Generic helpers: time handling, retries, ids and numeric guards."""

from __future__ import annotations

import asyncio
import functools
import math
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Iterator, List, Optional, Sequence, Tuple, Type, TypeVar

from utils.logger import get_logger

T = TypeVar("T")

logger = get_logger(__name__)

#: Bar duration for every supported timeframe.
TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
    "MN1": 43200,
}

#: Pandas resample rule per timeframe.
TIMEFRAME_PANDAS_RULE: dict[str, str] = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
    "W1": "1W",
    "MN1": "1MS",
}


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def isoformat(moment: Optional[datetime] = None) -> str:
    """Return an ISO-8601 string for ``moment`` (defaults to now)."""
    return (moment or utcnow()).isoformat()


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """Convert a timeframe label such as ``"H4"`` into a :class:`timedelta`."""
    minutes = TIMEFRAME_MINUTES.get(timeframe.upper())
    if minutes is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return timedelta(minutes=minutes)


def timeframe_to_minutes(timeframe: str) -> int:
    """Return the number of minutes covered by one bar of ``timeframe``."""
    minutes = TIMEFRAME_MINUTES.get(timeframe.upper())
    if minutes is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return minutes


def bars_per_year(timeframe: str) -> float:
    """Approximate number of bars in a trading year for annualisation.

    Forex trades roughly 24h x 5 days, i.e. 252 trading days per year.
    """
    minutes = timeframe_to_minutes(timeframe)
    minutes_per_year = 252 * 24 * 60
    return max(minutes_per_year / minutes, 1.0)


def new_id(prefix: str = "") -> str:
    """Return a short unique identifier, optionally prefixed."""
    token = uuid.uuid4().hex[:12]
    return f"{prefix}-{token}" if prefix else token


def correlation_id() -> str:
    """Return a fresh correlation id for cross-component tracing."""
    return new_id("corr")


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert ``value`` to float, returning ``default`` on failure or NaN."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp ``value`` into the inclusive ``[lower, upper]`` range."""
    return max(lower, min(upper, value))


def round_to_step(value: float, step: float) -> float:
    """Round ``value`` down to the nearest multiple of ``step``."""
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def chunked(items: Sequence[T], size: int) -> Iterator[List[T]]:
    """Yield consecutive chunks of at most ``size`` elements."""
    if size <= 0:
        raise ValueError("size must be positive")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def percentage(value: float, total: float) -> float:
    """Return ``value / total`` guarding against division by zero."""
    return value / total if total else 0.0


def retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    jitter: float = 0.1,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator adding exponential backoff retries to a sync function."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            wait = delay
            last_error: Optional[BaseException] = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203 - retry semantics
                    last_error = exc
                    if attempt == attempts:
                        break
                    sleep_for = wait + random.uniform(0, jitter * wait)
                    logger.warning(
                        "Call failed, retrying",
                        function=func.__name__,
                        attempt=attempt,
                        sleep=round(sleep_for, 2),
                        error=str(exc),
                    )
                    time.sleep(sleep_for)
                    wait *= backoff
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


def async_retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    jitter: float = 0.1,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator adding exponential backoff retries to a coroutine function."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            wait = delay
            last_error: Optional[BaseException] = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except exceptions as exc:  # noqa: PERF203 - retry semantics
                    last_error = exc
                    if attempt == attempts:
                        break
                    sleep_for = wait + random.uniform(0, jitter * wait)
                    logger.warning(
                        "Async call failed, retrying",
                        function=func.__name__,
                        attempt=attempt,
                        sleep=round(sleep_for, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(sleep_for)
                    wait *= backoff
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


async def gather_with_limit(limit: int, *coros: Awaitable[T]) -> List[T]:
    """Run awaitables with bounded concurrency preserving input order."""
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _run(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(_run(coro) for coro in coros)))


def truncate(text: str, length: int = 240) -> str:
    """Shorten ``text`` for logging purposes."""
    return text if len(text) <= length else f"{text[: length - 3]}..."


def flatten(nested: Iterable[Iterable[T]]) -> List[T]:
    """Flatten one level of nesting."""
    return [item for group in nested for item in group]
