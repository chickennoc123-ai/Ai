"""Analysis Agent: reads the market and emits trading signals.

Every cycle the agent refreshes market data for each symbol, computes the
configured indicator set, evaluates all active strategies and combines their
opinions into one confidence-weighted decision per symbol.  It also publishes
a market context (trend, volatility forecast, regime) used by the Risk and Meta
agents.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from agents.base_agent import BaseAgent
from agents.message_bus import Message, MessageType
from core.indicators import adx, atr, compute_indicator_set, ema, realized_volatility, rsi
from core.strategy import Signal, SignalDirection
from core.strategy_registry import create_strategy, load_strategies
from core.utils import get_instrument
from utils.helpers import utcnow


class AnalysisAgent(BaseAgent):
    """Turns market data into signals and market context."""

    subscriptions = [MessageType.META_FEEDBACK, MessageType.COMMAND, MessageType.MARKET_UPDATE]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the analysis agent."""
        super().__init__("analysis", **kwargs)
        self.symbols: List[str] = list(self.config.get("broker.xmtrading.symbols", ["EURUSD"]))
        self.timeframe = str(self.settings.get("timeframe", "H1"))
        self.indicator_names: List[str] = list(
            self.settings.get("indicators", ["rsi", "macd", "bb", "sma", "ema", "atr", "adx"])
        )
        self.active_strategies: List[str] = list(self.config.get("strategies.active", ["RSI", "MACD"]))
        self.min_confidence = self.settings.get_float("min_confidence", 0.45)
        self.history_bars = self.config.get_int("data.history_bars", 5000)
        self.latest_context: Dict[str, Dict[str, Any]] = {}
        self.latest_signals: Dict[str, Dict[str, Any]] = {}
        self._blocked_symbols: set[str] = set()

    # -- lifecycle -----------------------------------------------------------
    async def initialize(self) -> bool:
        """Ensure the strategy registry is loaded."""
        load_strategies()
        self.logger.info(
            "Analysis agent ready",
            symbols=self.symbols,
            strategies=self.active_strategies,
            timeframe=self.timeframe,
        )
        return True

    async def execute_cycle(self) -> None:
        """Analyse every symbol and publish the resulting signals."""
        data_manager = self.require_service("data_manager")
        for symbol in self.symbols:
            try:
                df = await data_manager.get_ohlcv(symbol, self.timeframe, self.history_bars, use_cache=False)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the cycle
                self.logger.warning("Market data unavailable", symbol=symbol, error=str(exc))
                continue

            context = self.analyse_market(symbol, df)
            self.latest_context[symbol] = context
            signal = self.aggregate_signals(symbol, df)
            self.latest_signals[symbol] = signal

            await self.publish(
                MessageType.MARKET_UPDATE,
                {"symbol": symbol, "timeframe": self.timeframe, "context": context},
            )
            if signal["direction"] != 0 and signal["confidence"] >= self.min_confidence:
                if symbol in self._blocked_symbols:
                    self.logger.info("Signal suppressed by risk block", symbol=symbol)
                    continue
                await self.publish(MessageType.SIGNAL, signal)
                self.logger.info(
                    "Signal published",
                    symbol=symbol,
                    direction=signal["direction_label"],
                    confidence=round(signal["confidence"], 3),
                    contributors=len(signal["contributors"]),
                )

    async def process(self, message: Message) -> Optional[Message]:
        """React to risk blocks, meta feedback and manual commands."""
        if message.message_type is MessageType.META_FEEDBACK:
            strategies = message.payload.get("analysis", {}).get("active_strategies")
            if strategies:
                self.active_strategies = list(strategies)
                self.logger.info("Active strategy set updated", strategies=self.active_strategies)
        elif message.message_type is MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "analyse_now":
                await self.execute_cycle()
            elif command == "block_symbol":
                self._blocked_symbols.add(str(message.payload.get("symbol", "")).upper())
            elif command == "unblock_symbol":
                self._blocked_symbols.discard(str(message.payload.get("symbol", "")).upper())
        return None

    # -- analysis ------------------------------------------------------------
    def analyse_market(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Describe the current market state for one symbol.

        Args:
            symbol: Instrument analysed.
            df: OHLCV history.

        Returns:
            Mapping with trend, momentum, volatility and regime information.
        """
        spec = get_instrument(symbol)
        close = df["close"]
        enriched = compute_indicator_set(df, self.indicator_names)
        last = enriched.iloc[-1]

        fast_trend = ema(close, 20)
        slow_trend = ema(close, 100)
        trend_score = float(np.tanh((fast_trend.iloc[-1] - slow_trend.iloc[-1]) / max(close.iloc[-1] * 0.002, 1e-9)))
        adx_values, plus_di, minus_di = adx(df["high"], df["low"], close)
        atr_values = atr(df["high"], df["low"], close)
        volatility = realized_volatility(close, 20, 252 * 24)

        atr_now = float(atr_values.iloc[-1]) if not np.isnan(atr_values.iloc[-1]) else 0.0
        atr_median = float(atr_values.tail(250).median()) if len(atr_values) > 50 else atr_now
        volatility_ratio = atr_now / atr_median if atr_median > 0 else 1.0
        adx_now = float(adx_values.iloc[-1]) if not np.isnan(adx_values.iloc[-1]) else 0.0

        if adx_now >= 25 and abs(trend_score) > 0.3:
            regime = "TRENDING"
        elif volatility_ratio >= 1.4:
            regime = "VOLATILE"
        elif volatility_ratio <= 0.7:
            regime = "QUIET"
        else:
            regime = "RANGING"

        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "price": float(close.iloc[-1]),
            "trend_score": round(trend_score, 4),
            "trend": "UP" if trend_score > 0.15 else "DOWN" if trend_score < -0.15 else "FLAT",
            "regime": regime,
            "adx": round(adx_now, 2),
            "plus_di": round(float(plus_di.iloc[-1]), 2) if not np.isnan(plus_di.iloc[-1]) else 0.0,
            "minus_di": round(float(minus_di.iloc[-1]), 2) if not np.isnan(minus_di.iloc[-1]) else 0.0,
            "rsi": round(float(rsi(close).iloc[-1]), 2),
            "atr": round(atr_now, spec.digits),
            "atr_pips": round(spec.price_to_pips(atr_now), 1),
            "volatility_ratio": round(volatility_ratio, 3),
            "annualised_volatility": round(float(volatility.iloc[-1]), 4) if not np.isnan(volatility.iloc[-1]) else 0.0,
            "volatility_forecast": round(float(atr_values.tail(20).mean()), spec.digits),
            "indicators": {
                key: (round(float(value), 5) if isinstance(value, (int, float, np.floating)) and not np.isnan(value) else None)
                for key, value in last.items()
                if key not in ("open", "high", "low", "close", "volume")
            },
            "timestamp": utcnow().isoformat(),
        }

    def aggregate_signals(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Combine every active strategy into one decision for ``symbol``."""
        contributors: List[Dict[str, Any]] = []
        weighted_vote = 0.0
        total_weight = 0.0
        stops: List[float] = []
        targets: List[float] = []

        for name in self.active_strategies:
            try:
                strategy = create_strategy(name, symbol, self.timeframe)
                signal: Signal = strategy.latest_signal(df)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Strategy evaluation failed", strategy=name, symbol=symbol, error=str(exc))
                continue
            contributors.append(
                {
                    "strategy": name,
                    "strategy_id": strategy.strategy_id,
                    "direction": int(signal.direction),
                    "confidence": round(signal.confidence, 4),
                    "sl": signal.stop_loss,
                    "tp": signal.take_profit,
                }
            )
            if signal.direction == SignalDirection.FLAT:
                continue
            weight = max(signal.confidence, 0.01)
            weighted_vote += int(signal.direction) * weight
            total_weight += weight
            if signal.stop_loss is not None:
                stops.append(signal.stop_loss)
            if signal.take_profit is not None:
                targets.append(signal.take_profit)

        direction = SignalDirection.FLAT
        confidence = 0.0
        if total_weight > 0:
            net = weighted_vote / total_weight
            if abs(net) >= 0.34:  # at least a clear majority of the weight agrees
                direction = SignalDirection.BUY if net > 0 else SignalDirection.SELL
                confidence = min(abs(weighted_vote) / max(len(self.active_strategies), 1), 1.0)

        stop_loss = self._consensus_level(stops, direction, protective=True)
        take_profit = self._consensus_level(targets, direction, protective=False)
        context = self.latest_context.get(symbol, {})

        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "direction": int(direction),
            "direction_label": direction.label,
            "confidence": round(float(confidence), 4),
            "entry_price": float(df["close"].iloc[-1]),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "regime": context.get("regime", "UNKNOWN"),
            "trend": context.get("trend", "FLAT"),
            "atr": context.get("atr", 0.0),
            "contributors": contributors,
            "agreement": round(abs(weighted_vote) / total_weight, 4) if total_weight else 0.0,
            "timestamp": utcnow().isoformat(),
        }

    @staticmethod
    def _consensus_level(levels: List[float], direction: SignalDirection, protective: bool) -> Optional[float]:
        """Pick the most conservative stop or the closest target."""
        if not levels or direction is SignalDirection.FLAT:
            return None
        if protective:
            # Tightest stop = highest for longs, lowest for shorts.
            return float(max(levels)) if direction is SignalDirection.BUY else float(min(levels))
        return float(min(levels)) if direction is SignalDirection.BUY else float(max(levels))

    def report(self) -> Dict[str, Any]:
        """Return the latest analysis state for the API and dashboard."""
        return {
            "timeframe": self.timeframe,
            "symbols": self.symbols,
            "active_strategies": self.active_strategies,
            "blocked_symbols": sorted(self._blocked_symbols),
            "context": self.latest_context,
            "signals": self.latest_signals,
        }
