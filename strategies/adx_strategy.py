"""ADX directional trend strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import adx
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class ADXTrendStrategy(BaseStrategy):
    """Takes directional trades only when ADX confirms a trending regime.

    While ADX stays below ``adx_threshold`` the strategy remains flat, which
    keeps it out of the choppy conditions that damage DI crossover systems.
    """

    name: ClassVar[str] = "ADX_Trend"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "DI crossover filtered by ADX trend strength"
    default_params: ClassVar[Dict[str, Any]] = {
        "adx_period": 14,
        "adx_threshold": 25,
        "exit_threshold": 18,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("adx_period", 7, 30),
        ParameterSpec("adx_threshold", 15, 40),
        ParameterSpec("exit_threshold", 10, 25),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate ADX-gated directional positions."""
        period = int(self.params["adx_period"])
        threshold = float(self.params["adx_threshold"])
        exit_threshold = float(self.params["exit_threshold"])
        adx_values, plus_di, minus_di = adx(df["high"], df["low"], df["close"], period)

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[(plus_di > minus_di) & (adx_values >= threshold)] = 1
        raw[(minus_di > plus_di) & (adx_values >= threshold)] = -1
        # Hold the position until ADX collapses below the exit threshold.
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")
        position = held.where(adx_values >= exit_threshold, 0).fillna(0).astype("int8")

        confidence = self.scale_confidence(adx_values, threshold, 55.0)
        return self.build_frame(df, position, confidence)
