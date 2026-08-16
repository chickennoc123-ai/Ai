"""Z-score mean reversion strategy with a trend guard."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import ema, zscore
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class ZScoreReversionStrategy(BaseStrategy):
    """Fades statistically extreme deviations from a rolling mean.

    A long-term EMA slope guard prevents fading a strong trend, the classic
    failure mode of naive z-score reversion on FX.
    """

    name: ClassVar[str] = "ZScore_Reversion"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "Rolling z-score reversion with EMA slope guard"
    default_params: ClassVar[Dict[str, Any]] = {
        "lookback": 40,
        "entry_z": 2.0,
        "exit_z": 0.4,
        "trend_ema": 200,
        "max_trend_slope": 0.0015,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("lookback", 10, 120),
        ParameterSpec("entry_z", 1.0, 3.5, step=0.1, integer=False),
        ParameterSpec("exit_z", 0.0, 1.5, step=0.1, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate reversion positions from the rolling z-score."""
        close = df["close"]
        scores = zscore(close, int(self.params["lookback"]))
        entry = float(self.params["entry_z"])
        exit_level = float(self.params["exit_z"])

        trend = ema(close, int(self.params["trend_ema"]))
        slope = (trend / trend.shift(20) - 1.0).abs().fillna(0.0)
        calm = slope <= float(self.params["max_trend_slope"]) * 20

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw.loc[(scores <= -entry) & calm] = 1
        raw.loc[(scores >= entry) & calm] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")
        position = held.where(scores.abs() > exit_level, 0).astype("int8")

        confidence = self.scale_confidence(scores.abs(), entry, entry * 2.0)
        return self.build_frame(df, position, confidence)
