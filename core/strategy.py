"""Strategy contracts shared by the backtester, the agents and the API.

A strategy is a pure function of an OHLCV frame: given bars it must produce a
``signal`` column in ``{-1, 0, 1}`` plus optional ``confidence``, ``sl`` and
``tp`` columns.  Signals are always interpreted as *decisions taken at the
close of the bar*, so the execution layer fills them on the following bar.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from core.indicators import atr
from core.utils import InstrumentSpec, get_instrument
from utils.exceptions import StrategyError
from utils.helpers import utcnow

REQUIRED_COLUMNS: Tuple[str, ...] = ("open", "high", "low", "close")
SIGNAL_COLUMNS: Tuple[str, ...] = ("signal", "confidence", "sl", "tp")


class SignalDirection(IntEnum):
    """Direction of a trading signal."""

    SELL = -1
    FLAT = 0
    BUY = 1

    @classmethod
    def from_any(cls, value: Any) -> "SignalDirection":
        """Coerce ints/strings such as ``"BUY"`` or ``-1`` into a direction."""
        if isinstance(value, SignalDirection):
            return value
        if isinstance(value, str):
            text = value.strip().upper()
            if text in {"BUY", "LONG"}:
                return cls.BUY
            if text in {"SELL", "SHORT"}:
                return cls.SELL
            return cls.FLAT
        try:
            numeric = int(np.sign(float(value)))
        except (TypeError, ValueError):
            return cls.FLAT
        return cls(numeric)

    @property
    def label(self) -> str:
        """Return ``"BUY"``, ``"SELL"`` or ``"FLAT"``."""
        return {1: "BUY", -1: "SELL", 0: "FLAT"}[int(self)]


@dataclass
class Signal:
    """A single actionable trading decision emitted by a strategy."""

    symbol: str
    timeframe: str
    direction: SignalDirection
    timestamp: datetime = field(default_factory=utcnow)
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strength: float = 1.0
    confidence: float = 0.5
    strategy_id: str = ""
    strategy_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        """``True`` when the signal asks for a position change."""
        return self.direction != SignalDirection.FLAT

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable representation used on the message bus."""
        payload = asdict(self)
        payload["direction"] = int(self.direction)
        payload["direction_label"] = self.direction.label
        payload["timestamp"] = self.timestamp.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Signal":
        """Rebuild a signal from its dictionary representation."""
        data = dict(payload)
        data.pop("direction_label", None)
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            data["timestamp"] = datetime.fromisoformat(timestamp)
        data["direction"] = SignalDirection.from_any(data.get("direction", 0))
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass(frozen=True)
class ParameterSpec:
    """Search space definition for a tunable strategy parameter."""

    name: str
    low: float
    high: float
    step: float = 1.0
    integer: bool = True

    def clip(self, value: float) -> float:
        """Clamp ``value`` into the declared range, honouring integrality."""
        bounded = min(max(float(value), self.low), self.high)
        if self.integer:
            return int(round(bounded))
        return round(bounded, 6)

    def sample(self, rng: np.random.Generator) -> float:
        """Draw a uniform random value from the search space."""
        if self.integer:
            return int(rng.integers(int(self.low), int(self.high) + 1))
        return float(round(rng.uniform(self.low, self.high), 6))


@dataclass
class StrategyMetadata:
    """Descriptive information exposed to the dashboard and the registry."""

    name: str
    category: str
    description: str
    parameters: Dict[str, Any]
    symbols: List[str] = field(default_factory=list)
    timeframes: List[str] = field(default_factory=list)
    author: str = "EA Factory Pro"
    generated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dictionary."""
        return asdict(self)


class Strategy(ABC):
    """Abstract base contract every trading strategy implements."""

    name: ClassVar[str] = "Strategy"
    category: ClassVar[str] = "generic"
    description: ClassVar[str] = ""
    default_params: ClassVar[Dict[str, Any]] = {}
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = ()
    generated: ClassVar[bool] = False

    def __init__(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        params: Optional[Mapping[str, Any]] = None,
        strategy_id: Optional[str] = None,
    ) -> None:
        """Initialise the strategy.

        Args:
            symbol: Instrument the strategy trades.
            timeframe: Bar timeframe the strategy expects.
            params: Overrides merged on top of :attr:`default_params`.
            strategy_id: Stable identifier; derived from the config when absent.
        """
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.params: Dict[str, Any] = {**self.default_params, **dict(params or {})}
        self._validate_params()
        self.strategy_id = strategy_id or self.fingerprint()

    # -- identity ------------------------------------------------------------
    def fingerprint(self) -> str:
        """Deterministic id derived from name, symbol, timeframe and params."""
        payload = json.dumps(
            {"n": self.name, "s": self.symbol, "t": self.timeframe, "p": self.params},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
        return f"{self.name}-{self.symbol}-{self.timeframe}-{digest}"

    @property
    def instrument(self) -> InstrumentSpec:
        """Contract specification of the traded instrument."""
        return get_instrument(self.symbol)

    @property
    def warmup(self) -> int:
        """Number of bars required before signals become valid."""
        numeric = [int(value) for value in self.params.values() if isinstance(value, (int, float)) and 1 < float(value) < 500]
        return int(max(numeric, default=20)) * 2 + 5

    def metadata(self) -> StrategyMetadata:
        """Return descriptive metadata for UIs and persistence."""
        return StrategyMetadata(
            name=self.name,
            category=self.category,
            description=self.description or self.__doc__ or "",
            parameters=dict(self.params),
            symbols=[self.symbol],
            timeframes=[self.timeframe],
            generated=self.generated,
        )

    # -- parameters ----------------------------------------------------------
    def _validate_params(self) -> None:
        """Clip parameters into their declared search space."""
        for spec in self.param_space:
            if spec.name in self.params:
                self.params[spec.name] = spec.clip(self.params[spec.name])

    def with_params(self, **overrides: Any) -> "Strategy":
        """Return a copy of the strategy with ``overrides`` applied."""
        return type(self)(self.symbol, self.timeframe, {**self.params, **overrides})

    def for_symbol(self, symbol: str, timeframe: Optional[str] = None) -> "Strategy":
        """Return a copy of the strategy bound to another instrument."""
        return type(self)(symbol, timeframe or self.timeframe, dict(self.params))

    # -- signal generation ---------------------------------------------------
    @abstractmethod
    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute raw signals for an OHLCV frame.

        Args:
            df: Frame indexed by timestamp with OHLCV columns.

        Returns:
            A frame (aligned to ``df.index``) containing at least a ``signal``
            column with values in ``{-1, 0, 1}``.
        """

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate the input, compute signals and normalise the output.

        Returns:
            Frame with ``signal``, ``confidence``, ``sl`` and ``tp`` columns.

        Raises:
            StrategyError: If the input frame is unusable or the strategy
                returns a malformed result.
        """
        self.validate_frame(df)
        try:
            raw = self.compute_signals(df)
        except StrategyError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise StrategyError(
                "Strategy failed during signal computation",
                strategy=self.name,
                symbol=self.symbol,
                error=str(exc),
            ) from exc
        return self._normalise(df, raw)

    def _normalise(self, df: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
        """Coerce a raw strategy output into the canonical signal frame."""
        if not isinstance(raw, pd.DataFrame) or "signal" not in raw:
            raise StrategyError("Strategy must return a frame with a 'signal' column", strategy=self.name)
        out = pd.DataFrame(index=df.index)
        signal = pd.to_numeric(raw["signal"], errors="coerce").reindex(df.index).fillna(0.0)
        out["signal"] = np.sign(signal).astype("int8")
        confidence = raw["confidence"] if "confidence" in raw else pd.Series(0.5, index=df.index)
        out["confidence"] = pd.to_numeric(confidence, errors="coerce").reindex(df.index).fillna(0.5).clip(0.0, 1.0)
        for column in ("sl", "tp"):
            values = raw[column] if column in raw else pd.Series(np.nan, index=df.index)
            out[column] = pd.to_numeric(values, errors="coerce").reindex(df.index)
        warmup = min(self.warmup, max(len(out) - 1, 0))
        if warmup:
            out.iloc[:warmup, out.columns.get_loc("signal")] = 0
        return out

    def latest_signal(self, df: pd.DataFrame) -> Signal:
        """Return the most recent signal as a :class:`Signal` object."""
        frame = self.generate_signals(df)
        if frame.empty:
            return Signal(
                symbol=self.symbol,
                timeframe=self.timeframe,
                direction=SignalDirection.FLAT,
                strategy_id=self.strategy_id,
                strategy_name=self.name,
            )
        row = frame.iloc[-1]
        bar = df.iloc[-1]
        timestamp = df.index[-1]
        stop_loss = float(row["sl"]) if pd.notna(row["sl"]) else None
        take_profit = float(row["tp"]) if pd.notna(row["tp"]) else None
        return Signal(
            symbol=self.symbol,
            timeframe=self.timeframe,
            direction=SignalDirection.from_any(row["signal"]),
            timestamp=timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else utcnow(),
            entry_price=float(bar["close"]),
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=float(row["confidence"]),
            strength=abs(float(row["signal"])),
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            metadata={"params": dict(self.params)},
        )

    # -- helpers available to subclasses -------------------------------------
    def validate_frame(self, df: pd.DataFrame) -> None:
        """Ensure the input frame has the required columns and length."""
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            raise StrategyError("Empty market data frame", strategy=self.name, symbol=self.symbol)
        missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
        if missing:
            raise StrategyError("Missing OHLC columns", strategy=self.name, missing=missing)
        if len(df) < 10:
            raise StrategyError("Not enough bars to evaluate strategy", strategy=self.name, bars=len(df))

    def atr_levels(
        self,
        df: pd.DataFrame,
        signal: pd.Series,
        atr_period: int = 14,
        sl_multiple: float = 2.0,
        tp_multiple: float = 3.0,
    ) -> Tuple[pd.Series, pd.Series]:
        """Derive ATR based stop-loss / take-profit levels for a signal series.

        Args:
            df: OHLCV frame.
            signal: Series of ``{-1, 0, 1}`` decisions aligned to ``df``.
            atr_period: ATR lookback.
            sl_multiple: Stop distance in ATR multiples.
            tp_multiple: Target distance in ATR multiples.

        Returns:
            Tuple of ``(stop_loss, take_profit)`` price series.
        """
        atr_values = atr(df["high"], df["low"], df["close"], atr_period)
        close = df["close"]
        long_mask = signal > 0
        short_mask = signal < 0
        stop = pd.Series(np.nan, index=df.index)
        target = pd.Series(np.nan, index=df.index)
        stop[long_mask] = close[long_mask] - sl_multiple * atr_values[long_mask]
        stop[short_mask] = close[short_mask] + sl_multiple * atr_values[short_mask]
        target[long_mask] = close[long_mask] + tp_multiple * atr_values[long_mask]
        target[short_mask] = close[short_mask] - tp_multiple * atr_values[short_mask]
        return stop, target

    @staticmethod
    def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
        """Boolean series that is ``True`` on the bar ``fast`` crosses above ``slow``."""
        return (fast > slow) & (fast.shift(1) <= slow.shift(1))

    @staticmethod
    def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
        """Boolean series that is ``True`` on the bar ``fast`` crosses below ``slow``."""
        return (fast < slow) & (fast.shift(1) >= slow.shift(1))

    @staticmethod
    def hold(signal: pd.Series) -> pd.Series:
        """Forward-fill entry signals into a continuous position series."""
        return signal.replace(0, np.nan).ffill().fillna(0).astype("int8")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{self.name} {self.symbol}/{self.timeframe} {self.params}>"
