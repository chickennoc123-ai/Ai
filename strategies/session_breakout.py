"""Trading-session range breakout, tuned for XAUUSD and the FX majors."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import numpy as np
import pandas as pd

from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class SessionBreakoutStrategy(BaseStrategy):
    """Breaks out of the Asian range during the London/New York overlap.

    The Asian session (00:00-07:00 UTC) range is measured each day; a close
    outside that range during the active window opens a position that is held
    until the end of the trading day.
    """

    name: ClassVar[str] = "Session_Breakout"
    category: ClassVar[str] = "volatility"
    description: ClassVar[str] = "Asian range breakout traded during the London/NY session"
    default_params: ClassVar[Dict[str, Any]] = {
        "range_start_hour": 0,
        "range_end_hour": 7,
        "trade_end_hour": 20,
        "buffer_atr": 0.15,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("range_end_hour", 4, 10),
        ParameterSpec("trade_end_hour", 14, 23),
        ParameterSpec("buffer_atr", 0.0, 1.0, step=0.05, integer=False),
    )

    @property
    def warmup(self) -> int:
        """Session logic only needs the ATR warmup."""
        return int(self.params.get("atr_period", 14)) * 2 + 5

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate session breakout positions."""
        index = df.index
        hours = index.hour
        days = index.normalize()

        range_start = int(self.params["range_start_hour"])
        range_end = int(self.params["range_end_hour"])
        trade_end = int(self.params["trade_end_hour"])

        in_range_window = (hours >= range_start) & (hours < range_end)
        frame = pd.DataFrame(
            {"high": df["high"], "low": df["low"], "close": df["close"], "day": days},
            index=index,
        )
        masked_high = frame["high"].where(in_range_window)
        masked_low = frame["low"].where(in_range_window)
        range_high = masked_high.groupby(frame["day"]).transform("max")
        range_low = masked_low.groupby(frame["day"]).transform("min")

        atr_values = self.atr_series(df)
        buffer_width = float(self.params["buffer_atr"]) * atr_values
        tradable = (hours >= range_end) & (hours < trade_end)

        close = frame["close"]
        raw = pd.Series(0, index=index, dtype="int8")
        raw.loc[tradable & (close > range_high + buffer_width)] = 1
        raw.loc[tradable & (close < range_low - buffer_width)] = -1

        # Hold within the trading day only, flat overnight.
        held = raw.replace(0, np.nan).groupby(frame["day"]).ffill().fillna(0.0)
        position = pd.Series(held.to_numpy(), index=index).where(tradable, 0).astype("int8")

        span = (range_high - range_low).replace(0.0, np.nan)
        excursion = (close - (range_high + range_low) / 2.0).abs() / span
        confidence = self.scale_confidence(excursion.fillna(0.0), 0.5, 2.0)
        return self.build_frame(df, position, confidence)
