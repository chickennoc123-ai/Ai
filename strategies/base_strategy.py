"""Convenience base class shared by all bundled strategies.

It adds ATR based risk levels, confidence shaping and a helper that turns a
desired-position series into the canonical signal frame expected by the
backtester.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from core.indicators import atr as atr_indicator
from core.strategy import ParameterSpec, Strategy


class BaseStrategy(Strategy):
    """Base implementation with shared risk-management plumbing.

    Subclasses implement :meth:`compute_signals` and typically finish with a
    call to :meth:`build_frame`.
    """

    name: ClassVar[str] = "BaseStrategy"
    category: ClassVar[str] = "generic"
    default_params: ClassVar[Dict[str, Any]] = {
        "atr_period": 14,
        "sl_atr": 2.0,
        "tp_atr": 3.0,
        "use_atr_stops": True,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("atr_period", 7, 30, integer=True),
        ParameterSpec("sl_atr", 1.0, 4.0, step=0.5, integer=False),
        ParameterSpec("tp_atr", 1.5, 6.0, step=0.5, integer=False),
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Merge parent default parameters and search spaces into subclasses."""
        super().__init_subclass__(**kwargs)
        merged: Dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            params = base.__dict__.get("default_params")
            if isinstance(params, dict):
                merged.update(params)
        cls.default_params = merged

        seen: Dict[str, ParameterSpec] = {}
        for base in reversed(cls.__mro__):
            space = base.__dict__.get("param_space")
            if space:
                for spec in space:
                    seen[spec.name] = spec
        cls.param_space = tuple(seen.values())

    # -- helpers -------------------------------------------------------------
    def atr_series(self, df: pd.DataFrame) -> pd.Series:
        """ATR series using the strategy's configured period."""
        period = int(self.params.get("atr_period", 14))
        values = atr_indicator(df["high"], df["low"], df["close"], period)
        return values.bfill().fillna(df["close"] * 0.002)

    def build_frame(
        self,
        df: pd.DataFrame,
        position: pd.Series,
        confidence: Optional[pd.Series] = None,
        sl: Optional[pd.Series] = None,
        tp: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """Assemble the canonical signal frame.

        Args:
            df: Source OHLCV frame.
            position: Desired position per bar in ``{-1, 0, 1}``.
            confidence: Optional per-bar confidence in ``[0, 1]``.
            sl: Optional explicit stop-loss prices.
            tp: Optional explicit take-profit prices.

        Returns:
            Frame with ``signal``, ``confidence``, ``sl`` and ``tp`` columns.
        """
        signal = pd.Series(position, index=df.index).fillna(0.0)
        signal = np.sign(signal).astype("int8")

        if confidence is None:
            confidence = pd.Series(0.55, index=df.index)
        confidence = pd.Series(confidence, index=df.index).astype("float64").clip(0.0, 1.0).fillna(0.5)

        if (sl is None or tp is None) and self.params.get("use_atr_stops", True):
            atr_values = self.atr_series(df)
            sl_multiple = float(self.params.get("sl_atr", 2.0))
            tp_multiple = float(self.params.get("tp_atr", 3.0))
            close = df["close"]
            derived_sl = close - signal * sl_multiple * atr_values
            derived_tp = close + signal * tp_multiple * atr_values
            derived_sl = derived_sl.where(signal != 0)
            derived_tp = derived_tp.where(signal != 0)
            sl = derived_sl if sl is None else sl
            tp = derived_tp if tp is None else tp

        frame = pd.DataFrame(
            {
                "signal": signal,
                "confidence": confidence,
                "sl": pd.Series(sl, index=df.index) if sl is not None else np.nan,
                "tp": pd.Series(tp, index=df.index) if tp is not None else np.nan,
            },
            index=df.index,
        )
        return frame

    @staticmethod
    def scale_confidence(value: pd.Series, low: float, high: float) -> pd.Series:
        """Map ``value`` from ``[low, high]`` onto a ``[0.35, 0.95]`` confidence."""
        span = max(high - low, 1e-9)
        normalised = ((value - low) / span).clip(0.0, 1.0).fillna(0.5)
        return 0.35 + 0.60 * normalised
