"""Stochastic oscillator reversal strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import stochastic
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class StochasticStrategy(BaseStrategy):
    """Trades %K/%D crossovers taken from oversold or overbought territory."""

    name: ClassVar[str] = "Stochastic"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "Stochastic %K/%D crossover from extreme zones"
    default_params: ClassVar[Dict[str, Any]] = {
        "k_period": 14,
        "d_period": 3,
        "smooth": 3,
        "oversold": 20,
        "overbought": 80,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("k_period", 5, 30),
        ParameterSpec("d_period", 2, 10),
        ParameterSpec("oversold", 10, 35),
        ParameterSpec("overbought", 65, 90),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate oscillator reversal positions."""
        percent_k, percent_d = stochastic(
            df["high"],
            df["low"],
            df["close"],
            int(self.params["k_period"]),
            int(self.params["d_period"]),
            int(self.params["smooth"]),
        )
        oversold = float(self.params["oversold"])
        overbought = float(self.params["overbought"])

        long_trigger = self.crossover(percent_k, percent_d) & (percent_k <= oversold + 15)
        short_trigger = self.crossunder(percent_k, percent_d) & (percent_k >= overbought - 15)

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[long_trigger.fillna(False)] = 1
        raw[short_trigger.fillna(False)] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")

        # Exit when the oscillator reaches the opposite extreme.
        exit_long = (held > 0) & (percent_k >= overbought)
        exit_short = (held < 0) & (percent_k <= oversold)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        confidence = self.scale_confidence((percent_k - 50).abs(), 0.0, 40.0)
        return self.build_frame(df, position, confidence)
