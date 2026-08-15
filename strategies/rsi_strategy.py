"""RSI mean-reversion strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import numpy as np
import pandas as pd

from core.indicators import rsi, sma
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class RSIStrategy(BaseStrategy):
    """Buys oversold dips and sells overbought spikes, exiting at the midline.

    A long position is opened when RSI drops below ``oversold`` and closed once
    RSI recovers above ``exit_level``.  Shorts mirror the logic.  An optional
    trend filter blocks counter-trend entries.
    """

    name: ClassVar[str] = "RSI"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "RSI mean reversion with midline exit and optional trend filter"
    default_params: ClassVar[Dict[str, Any]] = {
        "rsi_period": 14,
        "oversold": 30,
        "overbought": 70,
        "exit_level": 50,
        "trend_filter": 200,
        "use_trend_filter": False,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("rsi_period", 5, 30),
        ParameterSpec("oversold", 15, 40),
        ParameterSpec("overbought", 60, 85),
        ParameterSpec("exit_level", 45, 55),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate mean-reversion positions from the RSI oscillator."""
        close = df["close"]
        period = int(self.params["rsi_period"])
        oversold = float(self.params["oversold"])
        overbought = float(self.params["overbought"])
        exit_level = float(self.params["exit_level"])

        rsi_values = rsi(close, period)
        state = np.zeros(len(df), dtype="int8")
        values = rsi_values.to_numpy()

        trend_ok_long = np.ones(len(df), dtype=bool)
        trend_ok_short = np.ones(len(df), dtype=bool)
        if self.params.get("use_trend_filter"):
            trend = sma(close, int(self.params["trend_filter"]))
            trend_ok_long = (close >= trend).fillna(False).to_numpy()
            trend_ok_short = (close <= trend).fillna(False).to_numpy()

        current = 0
        for i in range(len(values)):
            value = values[i]
            if np.isnan(value):
                state[i] = 0
                continue
            if current == 0:
                if value <= oversold and trend_ok_long[i]:
                    current = 1
                elif value >= overbought and trend_ok_short[i]:
                    current = -1
            elif current == 1 and value >= exit_level:
                current = 0
            elif current == -1 and value <= exit_level:
                current = 0
            state[i] = current

        position = pd.Series(state, index=df.index)
        distance = (rsi_values - exit_level).abs()
        confidence = self.scale_confidence(distance, 0.0, 35.0)
        return self.build_frame(df, position, confidence)
