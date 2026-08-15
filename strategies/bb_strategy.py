"""Bollinger Band mean-reversion strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import numpy as np
import pandas as pd

from core.indicators import bollinger_bands
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class BollingerBandsStrategy(BaseStrategy):
    """Fades excursions outside the bands and exits at the moving average.

    Entries require the close to pierce a band; the position is unwound once
    price returns to the basis, which keeps holding periods short.
    """

    name: ClassVar[str] = "Bollinger_Bands"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "Bollinger Band fade with basis exit"
    default_params: ClassVar[Dict[str, Any]] = {
        "period": 20,
        "num_std": 2.0,
        "min_bandwidth": 0.0,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("period", 10, 60),
        ParameterSpec("num_std", 1.0, 3.5, step=0.1, integer=False),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate band-fade positions."""
        close = df["close"]
        upper, middle, lower = bollinger_bands(
            close, int(self.params["period"]), float(self.params["num_std"])
        )
        bandwidth = ((upper - lower) / middle.replace(0.0, np.nan)).fillna(0.0)
        wide_enough = bandwidth >= float(self.params["min_bandwidth"])

        close_values = close.to_numpy()
        upper_values, middle_values, lower_values = upper.to_numpy(), middle.to_numpy(), lower.to_numpy()
        allowed = wide_enough.to_numpy()

        state = np.zeros(len(df), dtype="int8")
        current = 0
        for i in range(len(df)):
            if np.isnan(upper_values[i]) or np.isnan(lower_values[i]):
                state[i] = 0
                continue
            if current == 0:
                if allowed[i] and close_values[i] <= lower_values[i]:
                    current = 1
                elif allowed[i] and close_values[i] >= upper_values[i]:
                    current = -1
            elif current == 1 and close_values[i] >= middle_values[i]:
                current = 0
            elif current == -1 and close_values[i] <= middle_values[i]:
                current = 0
            state[i] = current

        position = pd.Series(state, index=df.index)
        excursion = ((close - middle).abs() / (upper - middle).replace(0.0, np.nan)).fillna(0.0)
        confidence = self.scale_confidence(excursion, 0.5, 1.6)
        return self.build_frame(df, position, confidence)
