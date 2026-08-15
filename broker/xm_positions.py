"""Position management façade."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from broker.xm_connection import XMConnection
from broker.xm_models import OrderSide, Position, PositionStatus
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class XMPositions:
    """Reads and manages open and historical positions."""

    def __init__(self, connection: XMConnection) -> None:
        """Bind the façade to a connection."""
        self.connection = connection

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return the currently open positions, optionally filtered."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            positions = self.connection.simulator.positions()
        else:
            payload = await self.connection.request("GET", "/positions")
            positions = [self._from_payload(item) for item in payload or []]
        if symbol:
            key = symbol.upper()
            positions = [position for position in positions if position.symbol == key]
        return positions

    async def get_position_details(self, position_id: str) -> Position:
        """Return a single open position."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return self.connection.simulator.get_position(position_id)
        return self._from_payload(await self.connection.request("GET", f"/positions/{position_id}"))

    async def get_position_history(self, symbol: Optional[str] = None, days: int = 30) -> List[Position]:
        """Return closed positions from the last ``days`` days."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            cutoff = utcnow() - timedelta(days=days)
            return [
                position
                for position in self.connection.simulator.history(symbol)
                if position.closed_at is None or position.closed_at >= cutoff
            ]
        payload = await self.connection.request(
            "GET", "/positions/history", params={"symbol": symbol, "days": days}
        )
        return [self._from_payload(item) for item in payload or []]

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Position:
        """Close a single open position."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.close_position(position_id, reason)
        payload = await self.connection.request(
            "POST", f"/positions/{position_id}/close", json_body={"reason": reason}
        )
        return self._from_payload(payload)

    async def close_all(self, symbol: Optional[str] = None, reason: str = "CLOSE_ALL") -> List[Position]:
        """Close every open position, optionally restricted to one symbol."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.close_all(symbol, reason)
        payload = await self.connection.request(
            "POST", "/positions/close-all", json_body={"symbol": symbol, "reason": reason}
        )
        return [self._from_payload(item) for item in payload or []]

    async def modify_position(
        self, position_id: str, sl: Optional[float] = None, tp: Optional[float] = None
    ) -> Position:
        """Update the protective levels of an open position."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return await self.connection.simulator.modify_position(position_id, sl, tp)
        payload = await self.connection.request(
            "PUT", f"/positions/{position_id}", json_body={"sl": sl, "tp": tp}
        )
        return self._from_payload(payload)

    async def exposure(self) -> Dict[str, float]:
        """Return net signed lot exposure per symbol."""
        positions = await self.get_open_positions()
        exposure: Dict[str, float] = {}
        for position in positions:
            exposure[position.symbol] = exposure.get(position.symbol, 0.0) + position.direction * position.volume
        return exposure

    @staticmethod
    def _from_payload(payload: Dict[str, Any]) -> Position:
        """Build a :class:`Position` from a REST payload."""
        return Position(
            symbol=str(payload["symbol"]).upper(),
            side=OrderSide.from_any(payload.get("side") or payload.get("direction")),
            volume=float(payload.get("volume", 0.0)),
            open_price=float(payload.get("open_price", 0.0)),
            position_id=str(payload.get("position_id", "")),
            current_price=float(payload.get("current_price", 0.0)),
            stop_loss=payload.get("sl", payload.get("stop_loss")),
            take_profit=payload.get("tp", payload.get("take_profit")),
            close_price=payload.get("close_price"),
            status=PositionStatus(str(payload.get("status", "OPEN")).upper()),
            profit=float(payload.get("profit", 0.0)),
            swap=float(payload.get("swap", 0.0)),
            commission=float(payload.get("commission", 0.0)),
            margin=float(payload.get("margin", 0.0)),
            strategy_id=payload.get("strategy_id"),
            comment=str(payload.get("comment", "")),
        )
