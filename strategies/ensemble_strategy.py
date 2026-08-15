"""Voting ensemble that blends several bundled strategies."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Tuple

import pandas as pd

from core.strategy import ParameterSpec, Strategy
from core.strategy_registry import create_strategy, register_strategy
from strategies.base_strategy import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


@register_strategy
class EnsembleStrategy(BaseStrategy):
    """Aggregates member strategies into a single position by majority vote.

    A position is taken only when the net vote exceeds ``min_votes``, which
    materially reduces turnover compared with any individual member.
    """

    name: ClassVar[str] = "Ensemble"
    category: ClassVar[str] = "ensemble"
    description: ClassVar[str] = "Confidence weighted vote across several member strategies"
    default_params: ClassVar[Dict[str, Any]] = {
        "members": ["MACD", "ADX_Trend", "SuperTrend", "RSI"],
        "min_votes": 2,
        "weight_by_confidence": True,
    }
    param_space: ClassVar[Tuple[ParameterSpec, ...]] = (
        ParameterSpec("min_votes", 1, 4),
    )

    def _members(self) -> List[Strategy]:
        """Instantiate the configured member strategies."""
        members: List[Strategy] = []
        for name in self.params.get("members", []):
            if str(name).upper() == self.name.upper():
                continue  # never recurse into itself
            try:
                members.append(create_strategy(str(name), self.symbol, self.timeframe))
            except Exception as exc:
                logger.warning("Ensemble member unavailable", member=name, error=str(exc))
        return members

    @property
    def warmup(self) -> int:
        """Warmup is the maximum warmup across members."""
        members = self._members()
        return max((member.warmup for member in members), default=40)

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Combine member votes into a single position series."""
        members = self._members()
        if not members:
            return self.build_frame(df, pd.Series(0, index=df.index))

        votes = pd.Series(0.0, index=df.index)
        confidences = pd.Series(0.0, index=df.index)
        weight_by_confidence = bool(self.params.get("weight_by_confidence", True))

        for member in members:
            try:
                frame = member.generate_signals(df)
            except Exception as exc:
                logger.warning("Ensemble member failed", member=member.name, error=str(exc))
                continue
            weight = frame["confidence"] if weight_by_confidence else pd.Series(1.0, index=df.index)
            votes = votes.add(frame["signal"] * weight, fill_value=0.0)
            confidences = confidences.add(frame["confidence"].abs(), fill_value=0.0)

        min_votes = float(self.params.get("min_votes", 2))
        threshold = min_votes * (0.5 if weight_by_confidence else 1.0)
        position = pd.Series(0, index=df.index, dtype="int8")
        position[votes >= threshold] = 1
        position[votes <= -threshold] = -1

        agreement = (votes.abs() / max(len(members), 1)).clip(0.0, 1.0)
        confidence = self.scale_confidence(agreement, 0.2, 1.0)
        return self.build_frame(df, position, confidence)
