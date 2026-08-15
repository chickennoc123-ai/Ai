"""Classic dual moving-average crossover strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import atr, ema, sma
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class SMACrossStrategy(BaseStrategy):
    """Long while the fast average is above the slow average, short otherwise.

    A volatility filter suppresses signals when the moving averages are closer
    than ``min_separation_atr`` ATRs, which removes most whipsaws in ranges.
    """

    name: ClassVar[str] = "SMA_Cross"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "Dual moving average crossover with ATR separation filter"
    default_params: ClassVar[Dict[str, Any]] = {
        "fast_period": 20,
        "slow_period": 50,
        "use_ema": False,
        "min_separation_atr": 0.25,
        "long_only": False,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("fast_period", 5, 60),
        ParameterSpec("slow_period", 20, 250),
        ParameterSpec("min_separation_atr", 0.0, 1.5, step=0.05, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate crossover positions."""
        close = df["close"]
        fast_period = int(self.params["fast_period"])
        slow_period = max(int(self.params["slow_period"]), fast_period + 1)
        average = ema if self.params.get("use_ema") else sma
        fast = average(close, fast_period)
        slow = average(close, slow_period)

        separation = (fast - slow).abs()
        atr_values = atr(df["high"], df["low"], df["close"], int(self.params["atr_period"]))
        threshold = float(self.params["min_separation_atr"]) * atr_values
        confirmed = separation >= threshold

        position = pd.Series(0, index=df.index, dtype="int8")
        position[(fast > slow) & confirmed] = 1
        if not self.params.get("long_only"):
            position[(fast < slow) & confirmed] = -1

        confidence = self.scale_confidence(separation / atr_values.replace(0.0, pd.NA), 0.0, 3.0)
        return self.build_frame(df, position, confidence)
