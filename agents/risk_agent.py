"""Risk Agent: real-time portfolio risk monitoring.

The agent samples the account on every cycle, maintains an equity history and
evaluates four families of limits:

* **Drawdown** - peak-to-trough on the tracked equity curve.
* **Value at Risk / CVaR** - historical simulation over the return history plus
  a Monte-Carlo cross-check on the current exposure.
* **Exposure** - gross notional over equity, and per-symbol concentration.
* **Margin** - margin level and free margin buffer.

Breaches are published as ``RISK_ALERT`` messages; a breach of the kill-switch
drawdown asks the Execution Agent to halt and flatten.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from agents.base_agent import BaseAgent
from agents.message_bus import Message, MessageType
from core.utils import (
    conditional_value_at_risk,
    get_instrument,
    max_drawdown,
    notional_value,
    value_at_risk,
)
from utils.helpers import utcnow

import pandas as pd


class RiskAgent(BaseAgent):
    """Monitors the live risk envelope and raises alerts."""

    subscriptions = [MessageType.POSITION_UPDATE, MessageType.EXECUTION_REPORT, MessageType.COMMAND]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the risk agent."""
        super().__init__("risk", **kwargs)
        self.max_drawdown_limit = self.settings.get_float("max_drawdown", 0.15)
        self.kill_switch_drawdown = self.settings.get_float("kill_switch_drawdown", 0.25)
        self.max_var = self.settings.get_float("max_var", 0.02)
        self.max_exposure = self.settings.get_float("max_exposure", 0.5)
        self.max_symbol_exposure = self.settings.get_float("max_symbol_exposure", 0.2)
        self.var_confidence = self.settings.get_float("var_confidence", 0.99)
        self.monte_carlo_paths = self.settings.get_int("monte_carlo_paths", 5000)
        self.equity_history: Deque[Tuple[str, float]] = deque(maxlen=5000)
        self.alerts: List[Dict[str, Any]] = []
        self.latest_metrics: Dict[str, Any] = {}
        self.peak_equity = 0.0
        self.halted = False

    # -- lifecycle -----------------------------------------------------------
    async def initialize(self) -> bool:
        """Seed the equity history from the current account state."""
        account = self.require_service("account")
        info = await account.get_info()
        self.peak_equity = info.equity
        self.equity_history.append((utcnow().isoformat(), info.equity))
        self.logger.info(
            "Risk agent ready",
            equity=round(info.equity, 2),
            max_drawdown=self.max_drawdown_limit,
            kill_switch=self.kill_switch_drawdown,
        )
        return True

    async def execute_cycle(self) -> None:
        """Recompute every risk metric and publish alerts on breaches."""
        metrics = await self.compute_metrics()
        self.latest_metrics = metrics
        breaches = self.evaluate_limits(metrics)

        for breach in breaches:
            await self._raise_alert(breach, metrics)

        if not breaches and self.halted and metrics["drawdown"] < self.max_drawdown_limit * 0.5:
            self.halted = False
            await self.publish(
                MessageType.RISK_ALERT,
                {
                    "level": "INFO",
                    "action": "RESUME",
                    "reason": "Drawdown recovered below half the limit",
                    "metrics": metrics,
                },
            )
            self.logger.info("Risk halt lifted", drawdown=round(metrics["drawdown"], 4))

    async def process(self, message: Message) -> Optional[Message]:
        """React to position updates and manual commands."""
        if message.message_type is MessageType.POSITION_UPDATE:
            # A position change is a good moment for an off-cycle check.
            self.latest_metrics = await self.compute_metrics()
        elif message.message_type is MessageType.COMMAND:
            command = str(message.payload.get("command", ""))
            if command == "risk_check":
                await self.execute_cycle()
            elif command == "reset_peak":
                account = self.require_service("account")
                self.peak_equity = (await account.get_info()).equity
        return None

    # -- metrics -------------------------------------------------------------
    async def compute_metrics(self) -> Dict[str, Any]:
        """Compute the full set of live risk metrics."""
        account_api = self.require_service("account")
        positions_api = self.require_service("positions")

        account = await account_api.get_info()
        positions = await positions_api.get_open_positions()

        self.equity_history.append((utcnow().isoformat(), account.equity))
        self.peak_equity = max(self.peak_equity, account.equity)
        equity_values = [value for _, value in self.equity_history]

        drawdown = (self.peak_equity - account.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        returns = pd.Series(equity_values, dtype="float64").pct_change().dropna()

        gross_notional = 0.0
        exposure_by_symbol: Dict[str, float] = {}
        for position in positions:
            spec = get_instrument(position.symbol)
            notional = notional_value(spec, position.current_price or position.open_price, position.volume)
            gross_notional += notional
            exposure_by_symbol[position.symbol] = exposure_by_symbol.get(position.symbol, 0.0) + notional

        equity = max(account.equity, 1e-9)
        historical_var = value_at_risk(returns, self.var_confidence)
        historical_cvar = conditional_value_at_risk(returns, self.var_confidence)
        monte_carlo_var = self._monte_carlo_var(positions, equity)

        return {
            "timestamp": utcnow().isoformat(),
            "balance": round(account.balance, 2),
            "equity": round(account.equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown": round(drawdown, 4),
            "max_drawdown_observed": round(max_drawdown(equity_values), 4),
            "margin": round(account.margin, 2),
            "free_margin": round(account.free_margin, 2),
            "margin_level": round(account.margin_level, 2),
            "open_positions": len(positions),
            "gross_notional": round(gross_notional, 2),
            "exposure": round(gross_notional / equity, 4),
            "exposure_by_symbol": {
                key: round(value / equity, 4) for key, value in exposure_by_symbol.items()
            },
            "var": round(max(historical_var, monte_carlo_var), 5),
            "historical_var": round(historical_var, 5),
            "monte_carlo_var": round(monte_carlo_var, 5),
            "cvar": round(historical_cvar, 5),
            "floating_pnl": round(sum(position.net_profit for position in positions), 2),
            "samples": len(equity_values),
        }

    def _monte_carlo_var(self, positions: List[Any], equity: float) -> float:
        """Estimate one-day VaR of the open book by Monte-Carlo simulation."""
        if not positions or equity <= 0:
            return 0.0
        rng = np.random.default_rng(1234)
        daily_pnl = np.zeros(self.monte_carlo_paths)
        for position in positions:
            spec = get_instrument(position.symbol)
            price = position.current_price or position.open_price
            daily_volatility = spec.annual_volatility / np.sqrt(252)
            shocks = rng.normal(0.0, daily_volatility, self.monte_carlo_paths)
            notional = notional_value(spec, price, position.volume)
            daily_pnl += position.direction * notional * shocks
        quantile = float(np.percentile(daily_pnl, (1 - self.var_confidence) * 100))
        return abs(min(quantile, 0.0)) / equity

    # -- limits --------------------------------------------------------------
    def evaluate_limits(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return the list of limit breaches implied by ``metrics``."""
        breaches: List[Dict[str, Any]] = []

        if metrics["drawdown"] >= self.kill_switch_drawdown:
            breaches.append(
                {
                    "level": "CRITICAL",
                    "action": "HALT",
                    "close_positions": True,
                    "limit": "kill_switch_drawdown",
                    "value": metrics["drawdown"],
                    "threshold": self.kill_switch_drawdown,
                    "reason": f"Drawdown {metrics['drawdown']:.2%} hit the kill switch",
                }
            )
        elif metrics["drawdown"] >= self.max_drawdown_limit:
            breaches.append(
                {
                    "level": "CRITICAL",
                    "action": "HALT",
                    "close_positions": False,
                    "limit": "max_drawdown",
                    "value": metrics["drawdown"],
                    "threshold": self.max_drawdown_limit,
                    "reason": f"Drawdown {metrics['drawdown']:.2%} exceeds the limit",
                }
            )
        elif metrics["drawdown"] >= self.max_drawdown_limit * 0.75:
            breaches.append(
                {
                    "level": "WARNING",
                    "action": "MONITOR",
                    "limit": "max_drawdown",
                    "value": metrics["drawdown"],
                    "threshold": self.max_drawdown_limit,
                    "reason": f"Drawdown {metrics['drawdown']:.2%} approaching the limit",
                }
            )

        if metrics["var"] > self.max_var:
            breaches.append(
                {
                    "level": "WARNING",
                    "action": "REDUCE",
                    "limit": "max_var",
                    "value": metrics["var"],
                    "threshold": self.max_var,
                    "reason": f"VaR {metrics['var']:.2%} exceeds the limit",
                }
            )

        if metrics["exposure"] > self.max_exposure:
            breaches.append(
                {
                    "level": "WARNING",
                    "action": "REDUCE",
                    "limit": "max_exposure",
                    "value": metrics["exposure"],
                    "threshold": self.max_exposure,
                    "reason": f"Gross exposure {metrics['exposure']:.2f}x exceeds the limit",
                }
            )

        for symbol, exposure in metrics["exposure_by_symbol"].items():
            if exposure > self.max_symbol_exposure:
                breaches.append(
                    {
                        "level": "WARNING",
                        "action": "CLOSE_SYMBOL",
                        "symbol": symbol,
                        "limit": "max_symbol_exposure",
                        "value": exposure,
                        "threshold": self.max_symbol_exposure,
                        "reason": f"{symbol} exposure {exposure:.2f}x exceeds the per-symbol limit",
                    }
                )

        if 0 < metrics["margin_level"] < 150.0:
            breaches.append(
                {
                    "level": "CRITICAL",
                    "action": "REDUCE",
                    "limit": "margin_level",
                    "value": metrics["margin_level"],
                    "threshold": 150.0,
                    "reason": f"Margin level {metrics['margin_level']:.0f}% is close to a stop-out",
                }
            )
        return breaches

    async def _raise_alert(self, breach: Dict[str, Any], metrics: Dict[str, Any]) -> None:
        """Publish a risk alert and remember it."""
        alert = {**breach, "metrics": metrics, "timestamp": utcnow().isoformat()}
        self.alerts.append(alert)
        self.alerts = self.alerts[-200:]
        if breach.get("action") == "HALT":
            self.halted = True
        await self.publish(MessageType.RISK_ALERT, alert)
        log = self.logger.error if breach["level"] == "CRITICAL" else self.logger.warning
        log(
            "Risk limit breached",
            limit=breach["limit"],
            value=breach["value"],
            threshold=breach["threshold"],
            action=breach.get("action"),
        )

    # -- reporting -----------------------------------------------------------
    def report(self) -> Dict[str, Any]:
        """Return the risk state for the API and dashboard."""
        return {
            "metrics": self.latest_metrics,
            "halted": self.halted,
            "limits": {
                "max_drawdown": self.max_drawdown_limit,
                "kill_switch_drawdown": self.kill_switch_drawdown,
                "max_var": self.max_var,
                "max_exposure": self.max_exposure,
                "max_symbol_exposure": self.max_symbol_exposure,
            },
            "alerts": self.alerts[-50:],
            "equity_history": [
                {"timestamp": timestamp, "equity": round(value, 2)}
                for timestamp, value in list(self.equity_history)[-500:]
            ],
        }
