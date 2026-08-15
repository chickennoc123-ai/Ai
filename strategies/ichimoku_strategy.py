"""Ichimoku Kinko Hyo trend strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import ichimoku
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class IchimokuStrategy(BaseStrategy):
    """Trades in the direction of the cloud with a Tenkan/Kijun trigger.

    Longs require price above both leading spans and Tenkan above Kijun;
    shorts require the mirrored configuration.
    """

    name: ClassVar[str] = "Ichimoku"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "Ichimoku cloud breakout with Tenkan/Kijun confirmation"
    default_params: ClassVar[Dict[str, Any]] = {
        "conversion": 9,
        "base": 26,
        "span_b": 52,
        "displacement": 26,
        "require_cloud": True,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("conversion", 5, 20),
        ParameterSpec("base", 15, 60),
        ParameterSpec("span_b", 30, 120),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate cloud-aligned trend positions."""
        components = ichimoku(
            df["high"],
            df["low"],
            df["close"],
            int(self.params["conversion"]),
            int(self.params["base"]),
            int(self.params["span_b"]),
            int(self.params["displacement"]),
        )
        close = df["close"]
        tenkan, kijun = components["tenkan"], components["kijun"]
        span_a, span_b = components["senkou_a"], components["senkou_b"]
        cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
        cloud_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)

        long_state = tenkan > kijun
        short_state = tenkan < kijun
        if self.params.get("require_cloud", True):
            long_state &= close > cloud_top
            short_state &= close < cloud_bottom

        position = pd.Series(0, index=df.index, dtype="int8")
        position[long_state.fillna(False)] = 1
        position[short_state.fillna(False)] = -1

        thickness = (cloud_top - cloud_bottom).abs()
        distance = (close - (cloud_top + cloud_bottom) / 2.0).abs()
        confidence = self.scale_confidence(distance / thickness.replace(0.0, pd.NA), 0.0, 3.0)
        return self.build_frame(df, position, confidence)
