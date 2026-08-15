"""Execution Agent: turns signals into broker orders.

Responsibilities:

* Enforce the execution envelope (max positions, one position per symbol,
  duplicate-signal suppression, risk halt).
* Size positions through the :class:`core.decision.DecisionEngine`.
* Route the order using the configured algorithm: ``immediate``, ``twap``
  (time sliced), ``vwap`` (volume weighted slices) or ``iceberg`` (hidden
  size).
* Publish an execution report for every attempt, successful or not.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from agents.message_bus import Message, MessageType
from broker.xm_models import ExecutionReport, OrderSide
from core.decision import DecisionEngine
from core.utils import get_instrument
from utils.exceptions import BrokerError, OrderRejectedError
from utils.helpers import utcnow
from utils.validators import ValidationError


class ExecutionAgent(BaseAgent):
    """Executes signals subject to the risk and position limits."""

    subscriptions = [MessageType.SIGNAL, MessageType.RISK_ALERT, MessageType.COMMAND]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the execution agent."""
        super().__init__("execution", **kwargs)
        self.max_positions = self.settings.get_int("max_positions", 5)
        self.algo = str(self.settings.get("algo", "immediate")).lower()
        self.twap_slices = self.settings.get_int("twap_slices", 4)
        self.twap_interval = self.settings.get_float("twap_interval", 5.0)
        self.max_slippage_pips = self.settings.get_float("max_slippage_pips", 3.0)
        self.risk_per_trade = self.config.get_float("backtest.risk_per_trade", 0.01)
        self.halted = False
        self.halt_reason = ""
        self.executions: List[Dict[str, Any]] = []
        self.rejections: List[Dict[str, Any]] = []
        self._decision: Optional[DecisionEngine] = None
        self._pending: set[str] = set()

    # -- lifecycle -----------------------------------------------------------
    async def initialize(self) -> bool:
        """Verify the broker connection and prepare the sizing engine."""
        connection = self.require_service("connection")
        await connection.ensure_connected()
        self._decision = self.service("decision_engine") or DecisionEngine(self.config)
        self.logger.info(
            "Execution agent ready",
            algo=self.algo,
            max_positions=self.max_positions,
            mode=connection.mode,
        )
        return True

    async def execute_cycle(self) -> None:
        """Reconcile local state with the broker and publish a position update."""
        positions_api = self.require_service("positions")
        try:
            positions = await positions_api.get_open_positions()
        except BrokerError as exc:
            self.logger.warning("Unable to read positions", error=str(exc))
            return
        await self.publish(
            MessageType.POSITION_UPDATE,
            {
                "count": len(positions),
                "positions": [position.to_dict() for position in positions],
                "halted": self.halted,
                "timestamp": utcnow().isoformat(),
            },
        )

    async def process(self, message: Message) -> Optional[Message]:
        """Handle signals, risk alerts and manual commands."""
        if message.message_type is MessageType.SIGNAL:
            await self.handle_signal(message.payload, message.correlation_id)
        elif message.message_type is MessageType.RISK_ALERT:
            await self._handle_risk_alert(message.payload)
        elif message.message_type is MessageType.COMMAND:
            await self._handle_command(message.payload)
        return None

    # -- signal handling -----------------------------------------------------
    async def handle_signal(self, payload: Dict[str, Any], correlation: Optional[str] = None) -> Optional[ExecutionReport]:
        """Validate, size and execute one signal.

        Args:
            payload: Signal dictionary produced by the Analysis Agent.
            correlation: Correlation id linking the signal to its report.

        Returns:
            The :class:`ExecutionReport` when an order was sent.
        """
        symbol = str(payload.get("symbol", "")).upper()
        direction = int(payload.get("direction", 0))
        if not symbol or direction == 0:
            return None

        if self.halted:
            await self._reject(symbol, "Execution halted by risk agent", payload, correlation)
            return None
        if symbol in self._pending:
            self.logger.debug("Signal ignored, execution already in flight", symbol=symbol)
            return None

        positions_api = self.require_service("positions")
        orders_api = self.require_service("orders")
        account_api = self.require_service("account")

        positions = await positions_api.get_open_positions()
        existing = [position for position in positions if position.symbol == symbol]
        if existing:
            current = existing[0]
            if current.direction == direction:
                self.logger.debug("Signal matches the open position, nothing to do", symbol=symbol)
                return None
            self.logger.info("Reversing position on opposite signal", symbol=symbol)
            await positions_api.close_position(current.position_id, "SIGNAL_REVERSAL")
            positions = [position for position in positions if position.position_id != current.position_id]

        if len(positions) >= self.max_positions:
            await self._reject(symbol, f"Position limit reached ({self.max_positions})", payload, correlation)
            return None

        account = await account_api.get_info()
        spec = get_instrument(symbol)
        entry_price = float(payload.get("entry_price") or 0.0)
        if entry_price <= 0:
            entry_price = self.service("data_manager").latest_price(symbol) if self.service("data_manager") else 0.0
        stop_loss = payload.get("stop_loss")
        take_profit = payload.get("take_profit")
        if stop_loss is None:
            atr_value = float(payload.get("atr") or entry_price * 0.002)
            stop_loss = entry_price - direction * 2.0 * atr_value
        if take_profit is None:
            atr_value = float(payload.get("atr") or entry_price * 0.002)
            take_profit = entry_price + direction * 3.0 * atr_value

        assert self._decision is not None
        confidence = float(payload.get("confidence", 0.5))
        sizing = self._decision.get_position_sizing(
            symbol=symbol,
            allocation_capital=account.equity,
            entry_price=entry_price,
            stop_price=float(stop_loss),
            # Scale risk with confidence: a 0.5 confidence signal takes half size.
            risk_per_trade=self.risk_per_trade * min(max(confidence, 0.2), 1.0),
            equity=account.equity,
        )
        if sizing.volume < spec.min_lot:
            await self._reject(symbol, "Computed volume below the broker minimum", payload, correlation)
            return None

        self._pending.add(symbol)
        try:
            report = await self._route_order(
                orders_api,
                symbol=symbol,
                volume=sizing.volume,
                side=OrderSide.BUY if direction > 0 else OrderSide.SELL,
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
                strategy_id=str(payload.get("strategy_id") or "analysis-consensus"),
            )
        except (OrderRejectedError, BrokerError, ValidationError) as exc:
            await self._reject(symbol, str(exc), payload, correlation)
            return None
        finally:
            self._pending.discard(symbol)

        record = {
            "symbol": symbol,
            "direction": direction,
            "volume": sizing.volume,
            "algo": self.algo,
            "price": report.order.filled_price,
            "slippage": report.slippage,
            "confidence": confidence,
            "timestamp": utcnow().isoformat(),
        }
        self.executions.append(record)
        self.executions = self.executions[-500:]
        await self.publish(
            MessageType.EXECUTION_REPORT,
            {"success": True, "execution": record, "report": report.to_dict()},
            correlation,
        )
        self.logger.info(
            "Order executed",
            symbol=symbol,
            side=report.order.side.value,
            volume=sizing.volume,
            price=report.order.filled_price,
            algo=self.algo,
        )
        return report

    async def _route_order(
        self,
        orders_api: Any,
        symbol: str,
        volume: float,
        side: OrderSide,
        stop_loss: float,
        take_profit: float,
        strategy_id: str,
    ) -> ExecutionReport:
        """Send the order using the configured execution algorithm."""
        spec = get_instrument(symbol)
        if self.algo in ("twap", "vwap") and volume >= spec.min_lot * self.twap_slices:
            return await self._sliced_execution(
                orders_api, symbol, volume, side, stop_loss, take_profit, strategy_id
            )
        if self.algo == "iceberg" and volume >= spec.min_lot * 2:
            visible = spec.normalize_volume(volume / 2.0)
            first = await orders_api.place_market_order(
                symbol, visible, side.value, stop_loss, take_profit, strategy_id, "iceberg-visible"
            )
            remainder = spec.normalize_volume(volume - visible)
            if remainder >= spec.min_lot:
                await orders_api.place_market_order(
                    symbol, remainder, side.value, stop_loss, take_profit, strategy_id, "iceberg-hidden"
                )
            return first
        return await orders_api.place_market_order(
            symbol, volume, side.value, stop_loss, take_profit, strategy_id, f"{self.algo}-execution"
        )

    async def _sliced_execution(
        self,
        orders_api: Any,
        symbol: str,
        volume: float,
        side: OrderSide,
        stop_loss: float,
        take_profit: float,
        strategy_id: str,
    ) -> ExecutionReport:
        """Execute the order in equal time slices (TWAP/VWAP approximation)."""
        spec = get_instrument(symbol)
        slice_volume = spec.normalize_volume(volume / self.twap_slices)
        remaining = volume
        first_report: Optional[ExecutionReport] = None
        for index in range(self.twap_slices):
            if remaining < spec.min_lot:
                break
            current = min(slice_volume, remaining) if index < self.twap_slices - 1 else spec.normalize_volume(remaining)
            if current < spec.min_lot:
                break
            report = await orders_api.place_market_order(
                symbol, current, side.value, stop_loss, take_profit, strategy_id, f"{self.algo}-slice-{index + 1}"
            )
            first_report = first_report or report
            remaining = spec.normalize_volume(remaining - current)
            if remaining >= spec.min_lot and index < self.twap_slices - 1:
                await asyncio.sleep(self.twap_interval)
        if first_report is None:
            raise OrderRejectedError("Sliced execution produced no fills", symbol=symbol)
        return first_report

    # -- risk and commands ---------------------------------------------------
    async def _handle_risk_alert(self, payload: Dict[str, Any]) -> None:
        """Apply a risk directive from the Risk Agent."""
        action = str(payload.get("action", "")).upper()
        level = str(payload.get("level", "INFO")).upper()
        if action == "HALT" or level == "CRITICAL":
            self.halted = True
            self.halt_reason = str(payload.get("reason", "Risk limit breached"))
            self.logger.warning("Execution halted", reason=self.halt_reason)
            if payload.get("close_positions"):
                await self.close_all("RISK_HALT")
        elif action == "RESUME":
            self.halted = False
            self.halt_reason = ""
            self.logger.info("Execution resumed")
        elif action == "CLOSE_SYMBOL":
            symbol = str(payload.get("symbol", "")).upper()
            if symbol:
                positions_api = self.require_service("positions")
                for position in await positions_api.get_open_positions(symbol):
                    await positions_api.close_position(position.position_id, "RISK_CLOSE")

    async def _handle_command(self, payload: Dict[str, Any]) -> None:
        """Handle a manual command from the API or dashboard."""
        command = str(payload.get("command", ""))
        if command == "close_all":
            await self.close_all(str(payload.get("reason", "MANUAL")))
        elif command == "halt":
            self.halted = True
            self.halt_reason = str(payload.get("reason", "Manual halt"))
        elif command == "resume":
            self.halted = False
            self.halt_reason = ""
        elif command == "set_algo":
            self.algo = str(payload.get("algo", self.algo)).lower()

    async def close_all(self, reason: str = "MANUAL") -> List[Dict[str, Any]]:
        """Close every open position and report the outcome."""
        positions_api = self.require_service("positions")
        closed = await positions_api.close_all(reason=reason)
        payload = [position.to_dict() for position in closed]
        await self.publish(
            MessageType.EXECUTION_REPORT,
            {"success": True, "action": "close_all", "reason": reason, "closed": payload},
        )
        self.logger.info("All positions closed", count=len(closed), reason=reason)
        return payload

    async def _reject(
        self, symbol: str, reason: str, payload: Dict[str, Any], correlation: Optional[str]
    ) -> None:
        """Record and publish a rejected signal."""
        record = {"symbol": symbol, "reason": reason, "timestamp": utcnow().isoformat()}
        self.rejections.append(record)
        self.rejections = self.rejections[-200:]
        self.logger.warning("Signal rejected", symbol=symbol, reason=reason)
        await self.publish(
            MessageType.EXECUTION_REPORT,
            {"success": False, "rejection": record, "signal": payload},
            correlation,
        )

    def report(self) -> Dict[str, Any]:
        """Return the execution state for the API and dashboard."""
        return {
            "algo": self.algo,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "max_positions": self.max_positions,
            "executions": self.executions[-50:],
            "rejections": self.rejections[-50:],
            "execution_count": len(self.executions),
            "rejection_count": len(self.rejections),
        }
