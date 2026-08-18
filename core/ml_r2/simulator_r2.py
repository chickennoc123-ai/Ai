"""ML-001-R2 deterministic Python<->Pine parity simulator.

This module exists ONLY to support the Python<->Pine parity-testing
project (see ``ML-001-R2-PYTHON-PINE-SIMULATOR-PARITY-REPORT.md``). It
is NOT an economic-validation tool, NOT a production execution path, and
NOT a claim that RF-R2-001 exists or has been trained.

Five layers, kept deliberately separate (per the parity project's
explicit "do not collapse these layers" instruction) so each can be
audited, tested, and Pine-compared independently:

  A. FEATURE ENGINE       -- ``FeatureEngine``            (wraps the
     canonical, unmodified ``core.features.fe_r2_001.build_feature_matrix``)
  B. MODEL OUTPUT          -- ``ModelOutputProvider`` subclasses
  C. SIGNAL DECISION       -- ``SignalDecisionEngine``
  D. POSITION/RISK ENGINE  -- reuses ``core.ml_r2.backtest_r2.run_backtest``
     (already spec-faithful, already tested; not reimplemented here to
     avoid a second, potentially-divergent implementation of the same
     Section 10 mechanics)
  E. EXECUTION ENGINE      -- also ``run_backtest`` (T+1 signal
     execution + same-bar risk-trigger execution are already correctly
     separated inside it; see that module's own docstring)

Layer B is the one place fabrication is explicitly forbidden. There are
exactly two providers:

  - ``NullModelProvider``: represents production reality. RF-R2-001 has
    no trained, persisted artifact anywhere in this repository or its
    git history (verified in
    ``ML-001-R2-PYTHON-PINE-SIMULATOR-FORENSIC-BASELINE.md``). Calling
    it always raises ``ModelArtifactMissingError``.
  - ``FixtureProbabilityProvider``: labeled, at every point it appears
    (class docstring, constant, and every value it returns is sourced
    from caller-supplied data, never computed by any model), as
    ``MODEL_PARITY_TEST_FIXTURE_ONLY``. It is a deterministic parity
    test fixture, not a trading-model claim. No code anywhere may
    interpret its output as RF-R2-001's prediction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from core.features.fe_r2_001 import FEATURE_ORDER, build_feature_matrix
from core.ml_r2.backtest_r2 import BacktestConfig, BacktestResult, Trade, run_backtest
from utils.exceptions import EAFactoryError

MODEL_PARITY_TEST_FIXTURE_ONLY = "MODEL_PARITY_TEST_FIXTURE_ONLY"

#: Canonical trade-event vocabulary (Phase 7 of the parity project).
#: Every Trade produced by the D/E layer is translated into exactly two
#: of these events (one entry, one exit) — nothing else may appear in
#: an event sequence.
EVENT_ENTER_LONG = "ENTER_LONG"
EVENT_ENTER_SHORT = "ENTER_SHORT"
EVENT_EXIT_STOP = "EXIT_STOP"
EVENT_EXIT_TP = "EXIT_TP"
EVENT_EXIT_MAX_HOLD = "EXIT_MAX_HOLD"
EVENT_EXIT_SIGNAL_REVERSAL = "EXIT_SIGNAL_REVERSAL"

_EXIT_REASON_TO_EVENT = {
    "STOP_LOSS": EVENT_EXIT_STOP,
    "TAKE_PROFIT": EVENT_EXIT_TP,
    "MAX_HOLDING_PERIOD": EVENT_EXIT_MAX_HOLD,
    "SIGNAL_REVERSAL": EVENT_EXIT_SIGNAL_REVERSAL,
}

POSITION_FLAT = "FLAT"
POSITION_LONG = "LONG"
POSITION_SHORT = "SHORT"


class SimulatorError(EAFactoryError):
    """Base error for the parity simulator."""


class ModelArtifactMissingError(SimulatorError):
    """Raised by NullModelProvider: there is no trained RF-R2-001 artifact
    to call. This is the correct, honest failure mode — not a bug to be
    silently patched by fabricating a model."""


class FixtureAlignmentError(SimulatorError):
    """Raised when a supplied probability fixture references timestamps
    not present in the OHLCV index, or is misused in a context that
    could be mistaken for a real model call."""


# ============================================================
# LAYER A: FEATURE ENGINE
# ============================================================
class FeatureEngine:
    """Thin, non-modifying wrapper around the canonical FE-R2-002
    pipeline. Never reimplements feature math — that would violate the
    "Python FE-R2-002 remains the source of truth" governance rule.
    """

    @staticmethod
    def compute(ohlcv: pd.DataFrame) -> pd.DataFrame:
        features = build_feature_matrix(ohlcv)
        # feature_valid: True only once every one of the five features
        # (including the longest warmup, volatility_regime at 600 bars)
        # is defined. This is the single flag both the Signal Decision
        # layer and the golden-dataset exports use to mean "safe to act
        # on this bar's features."
        features = features.copy()
        features["feature_valid"] = features[FEATURE_ORDER].notna().all(axis=1)
        return features


# ============================================================
# LAYER B: MODEL OUTPUT
# ============================================================
class ModelOutputProvider(ABC):
    @abstractmethod
    def predict_probability(self, features: pd.DataFrame) -> pd.Series:
        """Return p[t] = P(next bar closes higher), aligned to a subset
        of ``features.index``. Must never be called on a bar where
        ``feature_valid`` is False; callers are responsible for that
        filtering (see ``SignalDecisionEngine``)."""


class NullModelProvider(ModelOutputProvider):
    """Represents production reality: RF-R2-001 has no trained artifact.
    Any attempt to use this provider for anything other than proving
    that the model layer fails closed is itself a misuse of this class.
    """

    def predict_probability(self, features: pd.DataFrame) -> pd.Series:
        raise ModelArtifactMissingError(
            "MODEL_ARTIFACT_MISSING: no trained RF-R2-001 artifact exists in this "
            "repository or its git history. NullModelProvider deliberately fails "
            "closed rather than fabricating a probability."
        )


@dataclass
class FixtureProbabilityProvider(ModelOutputProvider):
    """MODEL_PARITY_TEST_FIXTURE_ONLY.

    Wraps a caller-supplied probability Series verbatim. This class
    computes nothing — it exists solely so the Signal Decision / Position
    Risk / Execution layers can be exercised deterministically for
    Python<->Pine mechanics parity testing, using a probability sequence
    a human (or a golden-dataset generator script) chose explicitly to
    trigger specific scenarios (long entry, short entry, stop-loss,
    take-profit, max-hold, exit-priority conflict, position limit,
    warmup/NaN, threshold boundary).

    THIS IS NOT RF-R2-001's OUTPUT. It has no relationship to any
    trained model, real or hypothetical. No production code path may
    construct or consume this class.
    """

    probabilities: pd.Series
    label: str = MODEL_PARITY_TEST_FIXTURE_ONLY

    def __post_init__(self) -> None:
        if self.label != MODEL_PARITY_TEST_FIXTURE_ONLY:
            raise FixtureAlignmentError(
                "FixtureProbabilityProvider.label must remain "
                "'MODEL_PARITY_TEST_FIXTURE_ONLY' -- it exists precisely so this "
                "class can never be silently repurposed as a real model output."
            )

    def predict_probability(self, features: pd.DataFrame) -> pd.Series:
        unknown = self.probabilities.index.difference(features.index)
        if len(unknown) > 0:
            raise FixtureAlignmentError(
                f"fixture probability index contains {len(unknown)} timestamp(s) "
                "not present in the features index"
            )
        return self.probabilities


# ============================================================
# LAYER C: SIGNAL DECISION
# ============================================================
def decide_signal(p: float, long_threshold: float, short_threshold: float) -> str:
    """Pure, stateless spec Section 10 threshold decision. No position
    context here (position-aware gating -- e.g. "no new entry while a
    position is open" -- is layer D's job, since it requires state)."""
    if pd.isna(p):
        return POSITION_FLAT
    if p > long_threshold:
        return POSITION_LONG
    if p < short_threshold:
        return POSITION_SHORT
    return POSITION_FLAT


class SignalDecisionEngine:
    """Vectorized wrapper around ``decide_signal``, additionally gated by
    ``feature_valid`` -- a signal may only be considered on a bar where
    every canonical feature is defined (spec Section 4 WARMUP_BARS)."""

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self.config = config or BacktestConfig()

    def decide(self, features: pd.DataFrame, probabilities: pd.Series) -> pd.Series:
        out = pd.Series(POSITION_FLAT, index=features.index, name="signal")
        valid_and_supplied = features.index.intersection(probabilities.index)
        for ts in valid_and_supplied:
            if not bool(features.loc[ts, "feature_valid"]):
                continue
            out.loc[ts] = decide_signal(
                probabilities.loc[ts], self.config.long_threshold, self.config.short_threshold
            )
        return out


# ============================================================
# LAYERS D + E: POSITION/RISK ENGINE + EXECUTION ENGINE
# ============================================================
@dataclass
class TradeEvent:
    timestamp: pd.Timestamp
    event: str
    price: float
    direction: Optional[int] = None
    size_lots: Optional[float] = None
    reason: Optional[str] = None


def _translate_trades_to_events(trades: List[Trade]) -> List[TradeEvent]:
    events: List[TradeEvent] = []
    for trade in trades:
        enter_event = EVENT_ENTER_LONG if trade.direction == 1 else EVENT_ENTER_SHORT
        events.append(
            TradeEvent(
                timestamp=trade.entry_time,
                event=enter_event,
                price=trade.entry_price,
                direction=trade.direction,
                size_lots=trade.size_lots,
            )
        )
        if trade.exit_time is not None:
            exit_event = _EXIT_REASON_TO_EVENT.get(trade.exit_reason or "", trade.exit_reason)
            events.append(
                TradeEvent(
                    timestamp=trade.exit_time,
                    event=exit_event,
                    price=trade.exit_price,
                    direction=trade.direction,
                    reason=trade.exit_reason,
                )
            )
    events.sort(key=lambda e: e.timestamp)
    return events


def _position_state_series(index: pd.DatetimeIndex, trades: List[Trade]) -> pd.Series:
    """Position state AS OF the close of each bar (post any same-bar
    entry/exit resolution) -- FLAT / LONG / SHORT."""
    state = pd.Series(POSITION_FLAT, index=index, name="position_state")
    for trade in trades:
        direction_label = POSITION_LONG if trade.direction == 1 else POSITION_SHORT
        end = trade.exit_time if trade.exit_time is not None else index[-1]
        mask = (index >= trade.entry_time) & (index < end) if trade.exit_time is not None else (index >= trade.entry_time)
        state.loc[mask] = direction_label
    return state


# ============================================================
# ORCHESTRATION
# ============================================================
@dataclass
class SimulationResult:
    ohlcv: pd.DataFrame
    features: pd.DataFrame
    probabilities: pd.Series
    signals: pd.Series
    backtest: BacktestResult
    events: List[TradeEvent]
    position_state: pd.Series

    def full_bar_table(self) -> pd.DataFrame:
        """Assembles the Phase 2/3 required per-bar export columns."""
        out = self.ohlcv[["open", "high", "low", "close"]].copy()
        out["volume"] = self.ohlcv["volume"] if "volume" in self.ohlcv.columns else 0.0
        for col in FEATURE_ORDER:
            out[col] = self.features[col]
        out["feature_valid"] = self.features["feature_valid"]
        out["supplied_model_probability"] = self.probabilities.reindex(out.index)
        out["signal"] = self.signals.reindex(out.index).fillna(POSITION_FLAT)
        out["position_state"] = self.position_state

        entry_events = {e.timestamp: e for e in self.events if e.event in (EVENT_ENTER_LONG, EVENT_ENTER_SHORT)}
        exit_events = {e.timestamp: e for e in self.events if e.event not in (EVENT_ENTER_LONG, EVENT_ENTER_SHORT)}
        out["entry"] = out.index.map(lambda ts: entry_events[ts].event if ts in entry_events else "")
        out["exit"] = out.index.map(lambda ts: exit_events[ts].event if ts in exit_events else "")
        out["exit_reason"] = out.index.map(lambda ts: exit_events[ts].reason if ts in exit_events else "")

        size_by_ts = {e.timestamp: e.size_lots for e in self.events if e.event in (EVENT_ENTER_LONG, EVENT_ENTER_SHORT)}
        out["position_size"] = out.index.map(lambda ts: size_by_ts.get(ts, np.nan))

        sl_by_trade: List[tuple] = []
        tp_by_trade: List[tuple] = []
        for trade in self.backtest.trades:
            end = trade.exit_time if trade.exit_time is not None else out.index[-1]
            mask = (out.index >= trade.entry_time) & (out.index <= end)
            sl_by_trade.append((mask, trade.stop_loss_price))
            tp_by_trade.append((mask, trade.take_profit_price))
        out["stop_loss"] = np.nan
        out["take_profit"] = np.nan
        for mask, sl in sl_by_trade:
            out.loc[mask, "stop_loss"] = sl
        for mask, tp in tp_by_trade:
            out.loc[mask, "take_profit"] = tp
        return out


def run_simulation(
    ohlcv: pd.DataFrame,
    model_provider: ModelOutputProvider,
    config: Optional[BacktestConfig] = None,
    initial_equity: float = 10_000.0,
) -> SimulationResult:
    """Runs all five layers, in order, without collapsing them. This is
    the single entry point the golden-dataset generator and the parity
    tests use."""
    cfg = config or BacktestConfig()

    features = FeatureEngine.compute(ohlcv)
    probabilities = model_provider.predict_probability(features)

    signal_engine = SignalDecisionEngine(cfg)
    signals = signal_engine.decide(features, probabilities)

    ohlcv_with_atr = ohlcv.copy()
    ohlcv_with_atr["atr_14"] = features["atr_14"]
    backtest_result = run_backtest(ohlcv_with_atr, probabilities, cfg, initial_equity=initial_equity)

    events = _translate_trades_to_events(backtest_result.trades)
    position_state = _position_state_series(ohlcv.index, backtest_result.trades)

    return SimulationResult(
        ohlcv=ohlcv,
        features=features,
        probabilities=probabilities,
        signals=signals,
        backtest=backtest_result,
        events=events,
        position_state=position_state,
    )
