"""ATR volatility breakout strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class VolatilityBreakoutStrategy(BaseStrategy):
    """Enters when price breaks a volatility band around the prior close.

    The band is ``k * ATR`` wide around the previous session close, a robust
    formulation that adapts automatically across XAUUSD and the FX majors.
    """

    name: ClassVar[str] = "Volatility_Breakout"
    category: ClassVar[str] = "volatility"
    description: ClassVar[str] = "ATR band breakout with trailing regime exit"
    default_params: ClassVar[Dict[str, Any]] = {
        "breakout_atr": 1.0,
        "exit_bars": 12,
        "min_atr_pct": 0.0002,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("breakout_atr", 0.3, 3.0, step=0.1, integer=False),
        ParameterSpec("exit_bars", 3, 60),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate breakout positions."""
        close = df["close"]
        atr_values = self.atr_series(df)
        reference = close.shift(1)
        width = float(self.params["breakout_atr"]) * atr_values.shift(1)
        upper = reference + width
        lower = reference - width

        liquid = (atr_values / close).fillna(0.0) >= float(self.params["min_atr_pct"])
        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[(close > upper) & liquid] = 1
        raw[(close < lower) & liquid] = -1

        exit_bars = int(self.params["exit_bars"])
        held = raw.replace(0, pd.NA).ffill(limit=exit_bars).fillna(0).astype("int8")

        excursion = ((close - reference).abs() / width.replace(0.0, pd.NA)).fillna(0.0)
        confidence = self.scale_confidence(excursion, 1.0, 3.0)
        return self.build_frame(df, held, confidence)
