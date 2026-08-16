"""Rate-of-change momentum strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import roc, sma
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class MomentumStrategy(BaseStrategy):
    """Buys strength and sells weakness measured by rate of change.

    The entry threshold adapts to recent dispersion of the ROC series, so the
    same parameters behave sensibly on gold and on FX majors.
    """

    name: ClassVar[str] = "Momentum"
    category: ClassVar[str] = "momentum"
    description: ClassVar[str] = "Adaptive rate-of-change momentum with smoothing"
    default_params: ClassVar[Dict[str, Any]] = {
        "roc_period": 12,
        "smooth_period": 3,
        "entry_z": 0.8,
        "exit_z": 0.1,
        "lookback": 100,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("roc_period", 3, 40),
        ParameterSpec("smooth_period", 1, 10),
        ParameterSpec("entry_z", 0.2, 2.5, step=0.1, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate momentum positions from a normalised ROC."""
        close = df["close"]
        momentum_raw = roc(close, int(self.params["roc_period"]))
        smoothed = sma(momentum_raw, int(self.params["smooth_period"]))
        lookback = int(self.params["lookback"])
        dispersion = smoothed.rolling(lookback, min_periods=max(lookback // 4, 10)).std(ddof=0)
        normalised = (smoothed / dispersion.replace(0.0, pd.NA)).fillna(0.0)

        entry = float(self.params["entry_z"])
        exit_level = float(self.params["exit_z"])
        raw = pd.Series(0, index=df.index, dtype="int8")
        raw.loc[normalised >= entry] = 1
        raw.loc[normalised <= -entry] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")
        flat = normalised.abs() < exit_level
        position = held.where(~flat, 0).astype("int8")

        confidence = self.scale_confidence(normalised.abs(), entry, entry * 3.0)
        return self.build_frame(df, position, confidence)
