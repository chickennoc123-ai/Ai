"""Keltner Channel trend-continuation strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import keltner_channel
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class KeltnerStrategy(BaseStrategy):
    """Buys closes above the upper Keltner band, sells below the lower band.

    The basis EMA acts as the trailing exit, producing a classic
    volatility-normalised trend continuation system.
    """

    name: ClassVar[str] = "Keltner"
    category: ClassVar[str] = "volatility"
    description: ClassVar[str] = "Keltner Channel breakout with EMA basis exit"
    default_params: ClassVar[Dict[str, Any]] = {
        "period": 20,
        "multiplier": 2.0,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("period", 10, 60),
        ParameterSpec("multiplier", 1.0, 4.0, step=0.1, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate Keltner breakout positions."""
        close = df["close"]
        upper, basis, lower = keltner_channel(
            df["high"], df["low"], close, int(self.params["period"]), float(self.params["multiplier"])
        )
        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[close > upper] = 1
        raw[close < lower] = -1
        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")

        exit_long = (held > 0) & (close < basis)
        exit_short = (held < 0) & (close > basis)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        width = (upper - basis).replace(0.0, pd.NA)
        confidence = self.scale_confidence((close - basis).abs() / width, 0.5, 2.5)
        return self.build_frame(df, position, confidence)
