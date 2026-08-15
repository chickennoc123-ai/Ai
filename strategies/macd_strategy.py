"""MACD trend-following strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import numpy as np
import pandas as pd

from core.indicators import ema, macd
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class MACDStrategy(BaseStrategy):
    """Follows MACD/signal crossovers with an optional histogram threshold.

    The position is long while the MACD line sits above its signal line (and
    the histogram exceeds ``min_histogram``), short in the mirrored case.
    """

    name: ClassVar[str] = "MACD"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "MACD crossover trend following with histogram confirmation"
    default_params: ClassVar[Dict[str, Any]] = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "min_histogram": 0.0,
        "trend_ema": 100,
        "use_trend_filter": True,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("fast", 5, 20),
        ParameterSpec("slow", 21, 60),
        ParameterSpec("signal", 4, 15),
        ParameterSpec("trend_ema", 50, 250),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate positions from MACD crossovers."""
        close = df["close"]
        fast = int(self.params["fast"])
        slow = max(int(self.params["slow"]), fast + 1)
        macd_line, signal_line, histogram = macd(close, fast, slow, int(self.params["signal"]))

        threshold = float(self.params["min_histogram"]) * close.rolling(50, min_periods=10).std().fillna(0.0)
        long_state = (macd_line > signal_line) & (histogram >= threshold)
        short_state = (macd_line < signal_line) & (-histogram >= threshold)

        if self.params.get("use_trend_filter"):
            trend = ema(close, int(self.params["trend_ema"]))
            long_state &= close >= trend
            short_state &= close <= trend

        position = pd.Series(0, index=df.index, dtype="int8")
        position[long_state.fillna(False)] = 1
        position[short_state.fillna(False)] = -1

        scale = histogram.abs().rolling(100, min_periods=20).quantile(0.9).replace(0.0, np.nan)
        confidence = self.scale_confidence((histogram.abs() / scale).fillna(0.5), 0.0, 1.5)
        return self.build_frame(df, position, confidence)
