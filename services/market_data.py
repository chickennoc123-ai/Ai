"""Market data service with optional InfluxDB persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from core.data_manager import DataManager
from core.indicators import compute_indicator_set
from core.utils import get_instrument
from utils.config import Config, get_config
from utils.logger import get_logger
from utils.validators import validate_symbol, validate_timeframe

logger = get_logger(__name__)


class InfluxWriter:
    """Thin, failure-tolerant wrapper around the InfluxDB client.

    Writes are best-effort: when InfluxDB is unavailable the writer disables
    itself and the platform keeps running on in-memory data.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """Create the client if InfluxDB is enabled and reachable."""
        cfg = config or get_config()
        self.enabled = cfg.get_bool("influxdb.enabled", False)
        self.bucket = cfg.get("influxdb.bucket", "market")
        self.org = cfg.get("influxdb.org", "ea-factory")
        self._client: Any = None
        self._write_api: Any = None
        if not self.enabled:
            return
        try:
            from influxdb_client import InfluxDBClient
            from influxdb_client.client.write_api import ASYNCHRONOUS

            self._client = InfluxDBClient(
                url=str(cfg.get("influxdb.url", "http://localhost:8086")),
                token=str(cfg.get("influxdb.token", "")),
                org=self.org,
                timeout=5_000,
            )
            self._write_api = self._client.write_api(write_options=ASYNCHRONOUS)
            logger.info("InfluxDB writer ready", bucket=self.bucket, org=self.org)
        except Exception as exc:  # noqa: BLE001 - optional dependency/service
            logger.warning("InfluxDB unavailable, time-series persistence disabled", error=str(exc))
            self.enabled = False

    def write_quote(self, symbol: str, bid: float, ask: float, timestamp: Optional[datetime] = None) -> None:
        """Persist a single quote."""
        if not self.enabled or self._write_api is None:
            return
        try:
            from influxdb_client import Point

            point = (
                Point("tick")
                .tag("symbol", symbol)
                .field("bid", float(bid))
                .field("ask", float(ask))
                .field("mid", float((bid + ask) / 2.0))
            )
            if timestamp is not None:
                point = point.time(timestamp)
            self._write_api.write(bucket=self.bucket, org=self.org, record=point)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Influx write failed", error=str(exc))

    def write_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Persist a scalar metric."""
        if not self.enabled or self._write_api is None:
            return
        try:
            from influxdb_client import Point

            point = Point("metric").tag("name", name).field("value", float(value))
            for key, tag_value in (tags or {}).items():
                point = point.tag(key, str(tag_value))
            self._write_api.write(bucket=self.bucket, org=self.org, record=point)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Influx metric write failed", error=str(exc))

    def close(self) -> None:
        """Close the client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


class MarketDataService:
    """Serves OHLCV frames, indicator overlays and live quotes."""

    def __init__(
        self,
        data_manager: Optional[DataManager] = None,
        config: Optional[Config] = None,
        influx: Optional[InfluxWriter] = None,
    ) -> None:
        """Initialise the service."""
        self.config = config or get_config()
        self.data_manager = data_manager or DataManager(self.config)
        self.influx = influx if influx is not None else InfluxWriter(self.config)
        self.symbols: List[str] = list(self.config.get("broker.xmtrading.symbols", []))

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "H1",
        bars: int = 500,
        indicators: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        """Return candles, optionally enriched with indicators."""
        symbol = validate_symbol(symbol, self.symbols or None)
        timeframe = validate_timeframe(timeframe)
        frame = await self.data_manager.get_ohlcv(symbol, timeframe, max(bars, 100))
        frame = frame.tail(bars)
        if indicators:
            frame = compute_indicator_set(frame, list(indicators))
        return frame

    async def get_market_payload(
        self,
        symbol: str,
        timeframe: str = "H1",
        bars: int = 300,
        indicators: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Return a JSON-serialisable market snapshot for the API."""
        frame = await self.get_candles(symbol, timeframe, bars, indicators)
        spec = get_instrument(symbol)
        last = frame.iloc[-1]
        previous = frame.iloc[-2] if len(frame) > 1 else last
        change = float(last["close"] - previous["close"])
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "bars": len(frame),
            "digits": spec.digits,
            "last_price": float(last["close"]),
            "change": round(change, spec.digits),
            "change_pct": round(change / previous["close"] * 100.0, 4) if previous["close"] else 0.0,
            "candles": [
                {
                    "timestamp": timestamp.isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                for timestamp, row in frame.iterrows()
            ],
            "indicators": {
                column: [None if pd.isna(value) else float(value) for value in frame[column]]
                for column in frame.columns
                if column not in ("open", "high", "low", "close", "volume")
            },
        }

    async def snapshot(self, timeframe: str = "H1") -> List[Dict[str, Any]]:
        """Return a one-line summary for every tradable symbol."""
        frames = await self.data_manager.get_many(self.symbols, timeframe, 200)
        rows: List[Dict[str, Any]] = []
        for symbol, frame in frames.items():
            spec = get_instrument(symbol)
            close = frame["close"]
            change = float(close.iloc[-1] - close.iloc[-2]) if len(close) > 1 else 0.0
            rows.append(
                {
                    "symbol": symbol,
                    "price": round(float(close.iloc[-1]), spec.digits),
                    "change": round(change, spec.digits),
                    "change_pct": round(change / close.iloc[-2] * 100.0, 3) if len(close) > 1 and close.iloc[-2] else 0.0,
                    "high": round(float(frame["high"].tail(24).max()), spec.digits),
                    "low": round(float(frame["low"].tail(24).min()), spec.digits),
                    "spread_pips": spec.typical_spread_pips,
                }
            )
        return rows

    def record_quote(self, symbol: str, bid: float, ask: float) -> None:
        """Store a live quote in the time-series database and price cache."""
        self.data_manager.update_price(symbol, (bid + ask) / 2.0)
        self.influx.write_quote(symbol, bid, ask)

    async def close(self) -> None:
        """Release resources."""
        await self.data_manager.close()
        self.influx.close()
