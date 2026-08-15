"""Aroon oscillator trend strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import aroon
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class AroonStrategy(BaseStrategy):
    """Follows the Aroon oscillator, which measures time since extremes."""

    name: ClassVar[str] = "Aroon"
    category: ClassVar[str] = "momentum"
    description: ClassVar[str] = "Aroon oscillator trend following"
    default_params: ClassVar[Dict[str, Any]] = {
        "period": 25,
        "threshold": 50,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("period", 10, 60),
        ParameterSpec("threshold", 20, 80),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate positions from the Aroon oscillator."""
        _, _, oscillator = aroon(df["high"], df["low"], int(self.params["period"]))
        threshold = float(self.params["threshold"])

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[oscillator >= threshold] = 1
        raw[oscillator <= -threshold] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")
        position = held.where(oscillator.abs() >= threshold / 2.0, 0).fillna(0).astype("int8")

        confidence = self.scale_confidence(oscillator.abs(), threshold, 100.0)
        return self.build_frame(df, position, confidence)
