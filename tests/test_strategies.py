"""Tests for the strategy library and registry."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.strategy import Signal, SignalDirection
from core.strategy_registry import (
    available_strategies,
    create_strategy,
    describe_strategies,
    get_strategy_class,
)
from utils.exceptions import StrategyError

EXPECTED_STRATEGIES = {
    "RSI",
    "MACD",
    "SMA_Cross",
    "Bollinger_Bands",
    "Ichimoku",
    "ADX_Trend",
    "Momentum",
    "Volatility_Breakout",
    "Stochastic",
    "CCI",
    "Keltner",
    "Donchian",
    "Aroon",
    "SuperTrend",
    "ZScore_Reversion",
    "Session_Breakout",
    "Ensemble",
}


def test_registry_contains_the_bundled_strategies() -> None:
    """Every bundled strategy is registered."""
    registered = set(available_strategies())
    missing = EXPECTED_STRATEGIES - registered
    assert not missing, f"Missing strategies: {sorted(missing)}"


def test_registry_has_at_least_ten_strategies() -> None:
    """The platform ships more than the ten required strategies."""
    assert len(available_strategies()) >= 10


def test_unknown_strategy_raises() -> None:
    """Requesting an unknown strategy is an error."""
    with pytest.raises(StrategyError):
        create_strategy("DoesNotExist", "EURUSD", "H1")


def test_describe_strategies_returns_metadata() -> None:
    """Metadata is available for every strategy."""
    described = describe_strategies()
    assert len(described) == len(available_strategies())
    assert all(item.name and item.category for item in described)


@pytest.mark.parametrize("name", sorted(EXPECTED_STRATEGIES))
def test_strategy_produces_valid_signal_frame(name: str, ohlcv: pd.DataFrame) -> None:
    """Every strategy returns a well-formed signal frame."""
    strategy = create_strategy(name, "EURUSD", "H1")
    frame = strategy.generate_signals(ohlcv)

    assert list(frame.columns) == ["signal", "confidence", "sl", "tp"]
    assert frame.index.equals(ohlcv.index)
    assert set(frame["signal"].unique()).issubset({-1, 0, 1})
    assert frame["confidence"].between(0.0, 1.0).all()


@pytest.mark.parametrize("name", sorted(EXPECTED_STRATEGIES))
def test_strategy_respects_warmup(name: str, ohlcv: pd.DataFrame) -> None:
    """No strategy trades before its warmup period elapses."""
    strategy = create_strategy(name, "EURUSD", "H1")
    frame = strategy.generate_signals(ohlcv)
    warmup = min(strategy.warmup, len(frame) - 1)
    assert (frame["signal"].iloc[:warmup] == 0).all()


@pytest.mark.parametrize("name", ["RSI", "MACD", "SMA_Cross", "Bollinger_Bands"])
def test_strategy_generates_some_activity(name: str, ohlcv: pd.DataFrame) -> None:
    """The core strategies actually take positions on real data."""
    frame = create_strategy(name, "EURUSD", "H1").generate_signals(ohlcv)
    assert int((frame["signal"] != 0).sum()) > 0


def test_stops_sit_on_the_correct_side(ohlcv: pd.DataFrame) -> None:
    """Long stops are below price and long targets above it."""
    frame = create_strategy("RSI", "EURUSD", "H1").generate_signals(ohlcv)
    joined = frame.join(ohlcv["close"]).dropna(subset=["sl", "tp"])
    longs = joined[joined["signal"] > 0]
    shorts = joined[joined["signal"] < 0]
    if not longs.empty:
        assert (longs["sl"] < longs["close"]).all()
        assert (longs["tp"] > longs["close"]).all()
    if not shorts.empty:
        assert (shorts["sl"] > shorts["close"]).all()
        assert (shorts["tp"] < shorts["close"]).all()


def test_latest_signal_shape(ohlcv: pd.DataFrame) -> None:
    """``latest_signal`` returns a populated :class:`Signal`."""
    signal = create_strategy("MACD", "EURUSD", "H1").latest_signal(ohlcv)
    assert isinstance(signal, Signal)
    assert signal.symbol == "EURUSD"
    assert isinstance(signal.direction, SignalDirection)
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.entry_price > 0


def test_signal_round_trips_through_dict(ohlcv: pd.DataFrame) -> None:
    """Signals survive serialisation for the message bus."""
    original = create_strategy("RSI", "XAUUSD", "H1").latest_signal(ohlcv)
    restored = Signal.from_dict(original.to_dict())
    assert restored.symbol == original.symbol
    assert restored.direction == original.direction
    assert restored.confidence == pytest.approx(original.confidence)


def test_parameters_are_clipped_to_the_search_space() -> None:
    """Out-of-range parameters are clamped, not accepted blindly."""
    strategy = create_strategy("RSI", "EURUSD", "H1", {"rsi_period": 9999})
    spec = next(item for item in strategy.param_space if item.name == "rsi_period")
    assert strategy.params["rsi_period"] == spec.high


def test_with_params_does_not_mutate_the_original() -> None:
    """``with_params`` returns a copy."""
    original = create_strategy("RSI", "EURUSD", "H1")
    modified = original.with_params(rsi_period=7)
    assert original.params["rsi_period"] != 7
    assert modified.params["rsi_period"] == 7


def test_strategy_id_is_deterministic() -> None:
    """The same configuration always yields the same identifier."""
    first = create_strategy("RSI", "EURUSD", "H1", {"rsi_period": 14})
    second = create_strategy("RSI", "EURUSD", "H1", {"rsi_period": 14})
    third = create_strategy("RSI", "EURUSD", "H1", {"rsi_period": 21})
    assert first.strategy_id == second.strategy_id
    assert first.strategy_id != third.strategy_id


def test_for_symbol_rebinds_the_instrument() -> None:
    """A strategy can be moved to another instrument."""
    strategy = create_strategy("RSI", "EURUSD", "H1").for_symbol("XAUUSD")
    assert strategy.symbol == "XAUUSD"
    assert strategy.instrument.contract_size == 100.0


def test_empty_frame_raises(ohlcv: pd.DataFrame) -> None:
    """An empty frame is rejected with a clear error."""
    with pytest.raises(StrategyError):
        create_strategy("RSI", "EURUSD", "H1").generate_signals(pd.DataFrame())


def test_missing_columns_raise() -> None:
    """A frame without OHLC columns is rejected."""
    frame = pd.DataFrame({"price": np.arange(100, dtype="float64")})
    with pytest.raises(StrategyError):
        create_strategy("RSI", "EURUSD", "H1").generate_signals(frame)


def test_ensemble_combines_members(ohlcv: pd.DataFrame) -> None:
    """The ensemble strategy runs its members and votes."""
    strategy = create_strategy("Ensemble", "EURUSD", "H1", {"members": ["RSI", "MACD"], "min_votes": 1})
    frame = strategy.generate_signals(ohlcv)
    assert set(frame["signal"].unique()).issubset({-1, 0, 1})


def test_ensemble_never_recurses() -> None:
    """The ensemble refuses to include itself as a member."""
    strategy = create_strategy("Ensemble", "EURUSD", "H1", {"members": ["Ensemble", "RSI"]})
    members = strategy._members()  # noqa: SLF001 - deliberate white-box check
    assert all(member.name != "Ensemble" for member in members)


def test_strategy_class_lookup_is_case_insensitive() -> None:
    """Strategy lookup ignores case."""
    assert get_strategy_class("rsi") is get_strategy_class("RSI")
