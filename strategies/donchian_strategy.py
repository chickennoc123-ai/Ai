"""Donchian channel breakout (turtle style) strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import donchian_channel
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class DonchianStrategy(BaseStrategy):
    """Turtle-style breakout: enter on an N-bar extreme, exit on an M-bar one."""

    name: ClassVar[str] = "Donchian"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "Donchian channel breakout with shorter exit channel"
    default_params: ClassVar[Dict[str, Any]] = {
        "entry_period": 20,
        "exit_period": 10,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("entry_period", 10, 100),
        ParameterSpec("exit_period", 3, 50),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate breakout positions with channel-based exits."""
        high, low, close = df["high"], df["low"], df["close"]
        entry_period = int(self.params["entry_period"])
        exit_period = max(int(self.params["exit_period"]), 2)

        entry_upper, _, entry_lower = donchian_channel(high, low, entry_period)
        exit_upper, _, exit_lower = donchian_channel(high, low, exit_period)
        entry_upper, entry_lower = entry_upper.shift(1), entry_lower.shift(1)
        exit_upper, exit_lower = exit_upper.shift(1), exit_lower.shift(1)

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw.loc[close >= entry_upper] = 1
        raw.loc[close <= entry_lower] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")

        exit_long = (held > 0) & (close <= exit_lower)
        exit_short = (held < 0) & (close >= exit_upper)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        channel_width = (entry_upper - entry_lower).replace(0.0, pd.NA)
        breakout_size = (close - (entry_upper + entry_lower) / 2.0).abs() / channel_width
        confidence = self.scale_confidence(breakout_size, 0.4, 1.2)
        return self.build_frame(df, position, confidence)
