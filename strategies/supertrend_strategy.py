"""SuperTrend following strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import supertrend
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class SuperTrendStrategy(BaseStrategy):
    """Holds the direction indicated by the SuperTrend line.

    The SuperTrend line itself is used as the protective stop, which keeps the
    risk aligned with the signal that generated the trade.
    """

    name: ClassVar[str] = "SuperTrend"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "SuperTrend direction following with line-based stop"
    default_params: ClassVar[Dict[str, Any]] = {
        "period": 10,
        "multiplier": 3.0,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("period", 5, 30),
        ParameterSpec("multiplier", 1.0, 6.0, step=0.25, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate SuperTrend positions using the line as the stop."""
        line, direction = supertrend(
            df["high"], df["low"], df["close"], int(self.params["period"]), float(self.params["multiplier"])
        )
        position = direction.fillna(0).astype("int8")
        position[line.isna()] = 0

        atr_values = self.atr_series(df)
        stop = line.where(position != 0)
        target = (df["close"] + position * float(self.params["tp_atr"]) * atr_values).where(position != 0)

        distance = (df["close"] - line).abs() / atr_values.replace(0.0, pd.NA)
        confidence = self.scale_confidence(distance, 0.0, 4.0)
        return self.build_frame(df, position, confidence, sl=stop, tp=target)
