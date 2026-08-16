"""Commodity Channel Index strategy."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Tuple

import pandas as pd

from core.indicators import cci
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class CCIStrategy(BaseStrategy):
    """Trades CCI excursions beyond +/-100 either as reversal or breakout.

    ``mode='reversion'`` fades the extreme; ``mode='breakout'`` follows it.
    Gold in particular tends to reward the breakout variant.
    """

    name: ClassVar[str] = "CCI"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "CCI extreme handler with selectable reversion/breakout mode"
    default_params: ClassVar[Dict[str, Any]] = {
        "period": 20,
        "threshold": 100,
        "exit_threshold": 0,
        "mode": "reversion",
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("period", 7, 50),
        ParameterSpec("threshold", 60, 220),
    )

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate CCI based positions."""
        values = cci(df["high"], df["low"], df["close"], int(self.params["period"]))
        threshold = float(self.params["threshold"])
        exit_threshold = float(self.params["exit_threshold"])
        breakout = str(self.params.get("mode", "reversion")).lower() == "breakout"

        raw = pd.Series(0, index=df.index, dtype="int8")
        if breakout:
            raw.loc[values >= threshold] = 1
            raw.loc[values <= -threshold] = -1
        else:
            raw.loc[values <= -threshold] = 1
            raw.loc[values >= threshold] = -1

        held = raw.replace(0, pd.NA).ffill().fillna(0).astype("int8")
        exit_long = (held > 0) & (values >= exit_threshold if not breakout else values <= exit_threshold)
        exit_short = (held < 0) & (values <= exit_threshold if not breakout else values >= exit_threshold)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        confidence = self.scale_confidence(values.abs(), threshold, threshold * 2.5)
        return self.build_frame(df, position, confidence)
