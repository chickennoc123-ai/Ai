"""Market data acquisition, caching and resampling.

The :class:`DataManager` is the single entry point used by strategies, agents
and the API to obtain OHLCV frames.  It supports three providers out of the
box:

``simulated``
    A deterministic, reproducible synthetic market with volatility clustering.
    This is the default so the whole platform runs without credentials.
``csv``
    Reads ``<symbol>_<timeframe>.csv`` files from a directory.
``alphavantage``
    Fetches real FX/metal history over HTTPS when an API key is configured.

Frames returned by this module always share the same schema: a
``DatetimeIndex`` named ``timestamp`` (UTC) and the columns
``open``, ``high``, ``low``, ``close``, ``volume``.
"""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import numpy as np
import pandas as pd

from core.utils import REFERENCE_PRICES, get_instrument
from utils.config import Config, get_config
from utils.exceptions import DataError
from utils.helpers import (
    TIMEFRAME_PANDAS_RULE,
    async_retry,
    timeframe_to_minutes,
    utcnow,
)
from utils.logger import get_logger
from utils.validators import validate_symbol, validate_timeframe

logger = get_logger(__name__)

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
MAX_SIMULATED_BARS = 30_000


def _floor_to_timeframe(moment: datetime, timeframe: str) -> datetime:
    """Round ``moment`` down to the last completed bar boundary."""
    minutes = timeframe_to_minutes(timeframe)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed = int((moment - epoch).total_seconds() // 60)
    return epoch + timedelta(minutes=elapsed - (elapsed % minutes))


def _seed_for(symbol: str, timeframe: str, base_seed: int) -> int:
    """Derive a stable RNG seed from symbol/timeframe."""
    digest = hashlib.sha256(f"{symbol}:{timeframe}:{base_seed}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def ensure_ohlcv(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """Validate and normalise an OHLCV frame.

    Args:
        df: Candidate frame.
        symbol: Symbol used for error context.

    Returns:
        A sorted frame with the canonical schema.

    Raises:
        DataError: When required columns are missing or the frame is empty.
    """
    if df is None or df.empty:
        raise DataError("Empty market data frame", symbol=symbol)
    frame = df.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.set_index("timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    frame.index.name = "timestamp"
    missing = [column for column in ("open", "high", "low", "close") if column not in frame.columns]
    if missing:
        raise DataError("Market data missing columns", symbol=symbol, missing=missing)
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    frame = frame[list(OHLCV_COLUMNS)].astype("float64")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    if frame.empty:
        raise DataError("Market data frame empty after cleaning", symbol=symbol)
    return frame


class MarketDataProvider(ABC):
    """Interface implemented by every historical data source."""

    name: str = "provider"

    @abstractmethod
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, bars: int, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Return the last ``bars`` candles for ``symbol`` at ``timeframe``."""

    async def close(self) -> None:
        """Release provider resources (no-op by default)."""


class SimulatedProvider(MarketDataProvider):
    """Deterministic synthetic market generator.

    The generator combines a slow stochastic drift, a GARCH-like volatility
    process and occasional jumps so that trend-following and mean-reversion
    strategies both find realistic behaviour.  Output is reproducible for a
    given ``(symbol, timeframe, seed)`` triple.
    """

    name = "simulated"

    def __init__(self, seed: int = 20240101) -> None:
        self.seed = int(seed)

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, bars: int, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Generate synthetic candles ending at the last closed bar."""
        return await asyncio.to_thread(self.generate, symbol, timeframe, bars, end)

    def generate(
        self, symbol: str, timeframe: str, bars: int, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Synchronously generate synthetic candles."""
        symbol = validate_symbol(symbol)
        timeframe = validate_timeframe(timeframe)
        count = int(min(max(bars, 50), MAX_SIMULATED_BARS))
        spec = get_instrument(symbol)
        rng = np.random.default_rng(_seed_for(symbol, timeframe, self.seed))

        minutes = timeframe_to_minutes(timeframe)
        last_close_time = _floor_to_timeframe(end or utcnow(), timeframe)
        index = pd.date_range(end=last_close_time, periods=count, freq=f"{minutes}min", tz="UTC")

        bars_per_year = 252 * 24 * 60 / minutes
        base_vol = spec.annual_volatility / np.sqrt(bars_per_year)

        # GARCH(1,1)-like volatility with mean reversion to base_vol.
        omega, alpha, beta = 0.05, 0.08, 0.87
        variance = np.empty(count)
        shocks = rng.standard_normal(count)
        variance[0] = base_vol**2
        for i in range(1, count):
            variance[i] = base_vol**2 * omega + alpha * (base_vol * shocks[i - 1]) ** 2 + beta * variance[i - 1]
        volatility = np.sqrt(variance)

        # Alternating trending / mean-reverting regimes. Trending regimes get a
        # small persistent drift, ranging regimes an Ornstein-Uhlenbeck pull
        # towards the level where the regime started.
        regime_length = max(count // 14, 40)
        regime_count = count // regime_length + 1
        is_trending = rng.random(regime_count) < 0.5
        regime_drift = np.where(is_trending, rng.normal(0.0, base_vol * 0.06, regime_count), 0.0)
        regime_theta = np.where(is_trending, 0.0, rng.uniform(0.004, 0.02, regime_count))
        drift = np.repeat(regime_drift, regime_length)[:count]
        theta = np.repeat(regime_theta, regime_length)[:count]
        regime_id = np.repeat(np.arange(regime_count), regime_length)[:count]

        # Rare jumps (news shocks).
        jumps = rng.binomial(1, 2.5 / max(count, 1), count) * rng.normal(0, base_vol * 8, count)

        log_price = np.empty(count)
        log_price[0] = 0.0
        regime_anchor = 0.0
        for i in range(1, count):
            if regime_id[i] != regime_id[i - 1]:
                regime_anchor = log_price[i - 1]
            pull = theta[i] * (regime_anchor - log_price[i - 1])
            log_price[i] = log_price[i - 1] + drift[i] + pull + volatility[i] * shocks[i] + jumps[i]

        log_returns = np.diff(log_price, prepend=log_price[0])
        anchor = REFERENCE_PRICES.get(symbol, 1.0)
        closes = anchor * np.exp(log_price - log_price[-1])  # end at the reference price

        opens = np.empty(count)
        opens[0] = closes[0] * float(np.exp(-log_returns[0]))
        opens[1:] = closes[:-1]

        # Intrabar range from a Brownian-bridge style approximation.
        wick = np.abs(rng.normal(0.0, 1.0, count)) * volatility * 0.9
        highs = np.maximum(opens, closes) * (1.0 + wick)
        lows = np.minimum(opens, closes) * (1.0 - wick)
        volumes = np.abs(rng.normal(1_000, 260, count)) * (1.0 + 6.0 * volatility / max(base_vol, 1e-9) * 0.1)

        frame = pd.DataFrame(
            {
                "open": np.round(opens, spec.digits),
                "high": np.round(highs, spec.digits),
                "low": np.round(lows, spec.digits),
                "close": np.round(closes, spec.digits),
                "volume": np.round(volumes, 2),
            },
            index=index,
        )
        frame.index.name = "timestamp"
        # Guarantee OHLC consistency after rounding.
        frame["high"] = frame[["open", "high", "close"]].max(axis=1)
        frame["low"] = frame[["open", "low", "close"]].min(axis=1)
        return frame


class CSVProvider(MarketDataProvider):
    """Loads candles from ``<directory>/<SYMBOL>_<TIMEFRAME>.csv`` files."""

    name = "csv"

    def __init__(self, directory: str = "data/csv") -> None:
        self.directory = Path(directory)

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, bars: int, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Read candles from disk, optionally truncating at ``end``."""
        path = self.directory / f"{symbol.upper()}_{timeframe.upper()}.csv"
        if not path.exists():
            raise DataError("CSV file not found", path=str(path), symbol=symbol)
        frame = await asyncio.to_thread(pd.read_csv, path)
        frame = ensure_ohlcv(frame, symbol)
        if end is not None:
            frame = frame[frame.index <= pd.Timestamp(end, tz="UTC")]
        return frame.tail(bars)


class AlphaVantageProvider(MarketDataProvider):
    """Fetches FX/metal candles from the Alpha Vantage REST API."""

    name = "alphavantage"

    _INTERVALS = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "60min"}

    def __init__(self, api_key: str, base_url: str = "https://www.alphavantage.co/query") -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._session: Any = None

    async def _get_session(self) -> Any:
        """Lazily create the shared aiohttp session."""
        if self._session is None:
            import aiohttp  # imported lazily so the dependency stays optional

            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    @async_retry(attempts=3, delay=2.0, exceptions=(DataError, OSError))
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, bars: int, end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Fetch candles from Alpha Vantage and normalise them."""
        if not self.api_key:
            raise DataError("Alpha Vantage API key is not configured", symbol=symbol)
        timeframe = validate_timeframe(timeframe)
        base, quote = symbol[:3].upper(), symbol[3:].upper()
        params: Dict[str, str] = {"from_symbol": base, "to_symbol": quote, "apikey": self.api_key, "outputsize": "full"}
        if timeframe in self._INTERVALS:
            params["function"] = "FX_INTRADAY"
            params["interval"] = self._INTERVALS[timeframe]
        elif timeframe == "D1":
            params["function"] = "FX_DAILY"
        elif timeframe == "W1":
            params["function"] = "FX_WEEKLY"
        else:
            params["function"] = "FX_MONTHLY"

        session = await self._get_session()
        async with session.get(self.base_url, params=params) as response:
            if response.status != 200:
                raise DataError("Alpha Vantage request failed", status=response.status, symbol=symbol)
            payload = await response.json()

        series_key = next((key for key in payload if "Time Series" in key), None)
        if series_key is None:
            raise DataError("Unexpected Alpha Vantage payload", symbol=symbol, keys=list(payload)[:4])
        records = payload[series_key]
        frame = pd.DataFrame.from_dict(records, orient="index")
        frame.columns = [column.split(". ")[-1] for column in frame.columns]
        frame = frame.rename(columns={"1a. open": "open"})
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame["volume"] = 0.0
        return ensure_ohlcv(frame, symbol).tail(bars)

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None


class DataManager:
    """Fetches, caches and resamples market data for the whole platform."""

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialise the manager and its provider pool."""
        self.config = config or get_config()
        self.cache_dir = Path(self.config.get("data.cache_dir", "data/cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_provider = str(self.config.get("data.default_provider", "simulated"))
        self.default_bars = self.config.get_int("data.history_bars", 5000)
        self.symbols: List[str] = list(self.config.get("broker.xmtrading.symbols", list(REFERENCE_PRICES)))
        self._providers: Dict[str, MarketDataProvider] = {}
        self._memory_cache: Dict[str, pd.DataFrame] = {}
        self._latest_prices: Dict[str, float] = dict(REFERENCE_PRICES)
        self._lock = asyncio.Lock()

    # -- providers -----------------------------------------------------------
    def provider(self, name: Optional[str] = None) -> MarketDataProvider:
        """Return (and memoise) a provider instance by name."""
        key = (name or self.default_provider).lower()
        if key not in self._providers:
            self._providers[key] = self._build_provider(key)
        return self._providers[key]

    def _build_provider(self, name: str) -> MarketDataProvider:
        """Instantiate a provider from configuration."""
        if name == "csv":
            return CSVProvider(self.config.get("data.providers.csv.directory", "data/csv"))
        if name == "alphavantage":
            return AlphaVantageProvider(
                self.config.get("data.providers.alphavantage.api_key", ""),
                self.config.get("data.providers.alphavantage.base_url", "https://www.alphavantage.co/query"),
            )
        if name != "simulated":
            logger.warning("Unknown data provider, falling back to simulated", provider=name)
        return SimulatedProvider(self.config.get_int("data.providers.simulated.seed", 20240101))

    # -- fetching ------------------------------------------------------------
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "H1",
        bars: Optional[int] = None,
        provider: Optional[str] = None,
        use_cache: bool = True,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Return candles for ``symbol``.

        Args:
            symbol: Instrument symbol.
            timeframe: Bar timeframe label.
            bars: Number of bars requested (defaults to ``data.history_bars``).
            provider: Override the configured provider.
            use_cache: Serve from the in-memory cache when possible.
            end: Optional right boundary for the series.

        Returns:
            A canonical OHLCV frame.

        Raises:
            DataError: If every provider fails.
        """
        symbol = validate_symbol(symbol, self.symbols or None)
        timeframe = validate_timeframe(timeframe)
        count = int(bars or self.default_bars)
        cache_key = f"{symbol}:{timeframe}:{count}:{provider or self.default_provider}"

        if use_cache and cache_key in self._memory_cache:
            return self._memory_cache[cache_key].copy()

        async with self._lock:
            if use_cache and cache_key in self._memory_cache:
                return self._memory_cache[cache_key].copy()
            source = self.provider(provider)
            try:
                frame = await source.fetch_ohlcv(symbol, timeframe, count, end)
                frame = ensure_ohlcv(frame, symbol)
            except Exception as exc:
                logger.warning(
                    "Primary data provider failed, using simulated fallback",
                    symbol=symbol,
                    timeframe=timeframe,
                    provider=source.name,
                    error=str(exc),
                )
                fallback = self.provider("simulated")
                frame = ensure_ohlcv(await fallback.fetch_ohlcv(symbol, timeframe, count, end), symbol)
            self._memory_cache[cache_key] = frame
            self._latest_prices[symbol] = float(frame["close"].iloc[-1])
            return frame.copy()

    async def get_many(
        self,
        symbols: Optional[Iterable[str]] = None,
        timeframe: str = "H1",
        bars: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch several symbols concurrently."""
        targets = list(symbols or self.symbols)
        results = await asyncio.gather(
            *(self.get_ohlcv(symbol, timeframe, bars, provider) for symbol in targets),
            return_exceptions=True,
        )
        output: Dict[str, pd.DataFrame] = {}
        for symbol, result in zip(targets, results):
            if isinstance(result, Exception):
                logger.error("Failed to load symbol", symbol=symbol, error=str(result))
                continue
            output[symbol] = result
        return output

    # -- transformation ------------------------------------------------------
    @staticmethod
    def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Aggregate candles to a higher timeframe."""
        rule = TIMEFRAME_PANDAS_RULE.get(validate_timeframe(timeframe))
        if rule is None:
            raise DataError("Unsupported resample timeframe", timeframe=timeframe)
        resampled = df.resample(rule, label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        return resampled.dropna(subset=["open", "high", "low", "close"])

    @staticmethod
    def slice_period(df: pd.DataFrame, start: Optional[datetime], end: Optional[datetime]) -> pd.DataFrame:
        """Return the sub-frame between ``start`` and ``end`` (inclusive)."""
        frame = df
        if start is not None:
            frame = frame[frame.index >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            frame = frame[frame.index <= pd.Timestamp(end, tz="UTC")]
        return frame

    # -- live data -----------------------------------------------------------
    def update_price(self, symbol: str, price: float) -> None:
        """Record the latest traded price for a symbol."""
        self._latest_prices[symbol.upper()] = float(price)

    def latest_price(self, symbol: str) -> float:
        """Return the most recent known price for ``symbol``."""
        return float(self._latest_prices.get(symbol.upper(), REFERENCE_PRICES.get(symbol.upper(), 0.0)))

    def latest_prices(self) -> Dict[str, float]:
        """Return a snapshot of all known prices."""
        return dict(self._latest_prices)

    def append_bar(self, symbol: str, timeframe: str, bar: Mapping[str, float]) -> None:
        """Append a freshly closed bar to every cached series of the symbol."""
        prefix = f"{symbol.upper()}:{timeframe.upper()}:"
        timestamp = pd.Timestamp(bar.get("timestamp", utcnow()), tz="UTC")
        row = pd.DataFrame(
            [{column: float(bar.get(column, 0.0)) for column in OHLCV_COLUMNS}], index=[timestamp]
        )
        for key, frame in list(self._memory_cache.items()):
            if key.startswith(prefix):
                updated = pd.concat([frame, row])
                updated = updated[~updated.index.duplicated(keep="last")].sort_index()
                self._memory_cache[key] = updated.tail(len(frame))

    # -- persistence ---------------------------------------------------------
    def cache_path(self, symbol: str, timeframe: str) -> Path:
        """Return the on-disk cache path for a series."""
        return self.cache_dir / f"{symbol.upper()}_{timeframe.upper()}.parquet"

    def save_cache(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Path]:
        """Persist a frame to the parquet cache (CSV fallback)."""
        path = self.cache_path(symbol, timeframe)
        try:
            df.to_parquet(path)
            return path
        except Exception as exc:  # pragma: no cover - pyarrow missing
            logger.warning("Parquet cache failed, using CSV", error=str(exc))
            csv_path = path.with_suffix(".csv")
            df.to_csv(csv_path)
            return csv_path

    def load_cache(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Load a previously cached frame if present."""
        path = self.cache_path(symbol, timeframe)
        try:
            if path.exists():
                return ensure_ohlcv(pd.read_parquet(path), symbol)
            csv_path = path.with_suffix(".csv")
            if csv_path.exists():
                return ensure_ohlcv(pd.read_csv(csv_path, index_col=0), symbol)
        except Exception as exc:  # pragma: no cover - corrupted cache
            logger.warning("Unable to read cache", symbol=symbol, error=str(exc))
        return None

    def clear_cache(self) -> None:
        """Drop the in-memory cache."""
        self._memory_cache.clear()

    async def close(self) -> None:
        """Release all provider resources."""
        for source in self._providers.values():
            await source.close()
        self._providers.clear()
