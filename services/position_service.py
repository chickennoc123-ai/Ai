"""Position service: exposure, closing and trade persistence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from broker.xm_models import Position
from broker.xm_positions import XMPositions
from core.utils import get_instrument, notional_value
from models.database import Database, session_scope
from models.position import PositionRecord
from models.trade import TradeRecord
from utils.helpers import new_id
from utils.logger import get_logger

logger = get_logger(__name__)


class PositionService:
    """Reads positions from the broker and persists closed ones as trades."""

    def __init__(self, positions: XMPositions, database: Optional[Database] = None) -> None:
        """Bind the service to a broker façade and an optional database."""
        self.positions = positions
        self.database = database

    async def list_open(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return open positions as dictionaries."""
        return [position.to_dict() for position in await self.positions.get_open_positions(symbol)]

    async def get(self, position_id: str) -> Dict[str, Any]:
        """Return a single open position."""
        return (await self.positions.get_position_details(position_id)).to_dict()

    async def history(self, symbol: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
        """Return closed positions from the broker."""
        return [
            position.to_dict() for position in await self.positions.get_position_history(symbol, days)
        ]

    async def close(self, position_id: str, reason: str = "MANUAL") -> Dict[str, Any]:
        """Close a position and persist the resulting trade."""
        position = await self.positions.close_position(position_id, reason)
        self._persist(position)
        return position.to_dict()

    async def close_all(self, symbol: Optional[str] = None, reason: str = "CLOSE_ALL") -> List[Dict[str, Any]]:
        """Close every open position."""
        closed = await self.positions.close_all(symbol, reason)
        for position in closed:
            self._persist(position)
        return [position.to_dict() for position in closed]

    async def modify(
        self, position_id: str, sl: Optional[float] = None, tp: Optional[float] = None
    ) -> Dict[str, Any]:
        """Update the protective levels of a position."""
        return (await self.positions.modify_position(position_id, sl, tp)).to_dict()

    async def portfolio_summary(self) -> Dict[str, Any]:
        """Return aggregated exposure and P&L across open positions."""
        positions = await self.positions.get_open_positions()
        gross = 0.0
        by_symbol: Dict[str, Dict[str, float]] = {}
        for position in positions:
            spec = get_instrument(position.symbol)
            notional = notional_value(spec, position.current_price or position.open_price, position.volume)
            gross += notional
            bucket = by_symbol.setdefault(
                position.symbol, {"volume": 0.0, "notional": 0.0, "profit": 0.0, "positions": 0}
            )
            bucket["volume"] += position.direction * position.volume
            bucket["notional"] += notional
            bucket["profit"] += position.net_profit
            bucket["positions"] += 1
        return {
            "open_positions": len(positions),
            "gross_notional": round(gross, 2),
            "floating_pnl": round(sum(position.net_profit for position in positions), 2),
            "by_symbol": {
                key: {name: round(value, 4) for name, value in bucket.items()}
                for key, bucket in by_symbol.items()
            },
        }

    def _persist(self, position: Position) -> None:
        """Store the closed position and the derived trade record."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                existing = (
                    session.query(PositionRecord)
                    .filter(PositionRecord.position_id == position.position_id)
                    .one_or_none()
                )
                if existing is None:
                    session.add(PositionRecord.from_position(position))
                else:
                    existing.status = position.status.value
                    existing.close_price = position.close_price
                    existing.closed_at = position.closed_at
                    existing.profit = position.profit
                    existing.swap = position.swap
                    existing.commission = position.commission
                    existing.close_reason = position.close_reason
                if not position.is_open:
                    session.add(
                        TradeRecord(
                            trade_id=new_id("trd"),
                            strategy_id=position.strategy_id,
                            strategy_name=(position.strategy_id or "").split("-")[0],
                            symbol=position.symbol,
                            direction=position.direction,
                            volume=position.volume,
                            entry_price=position.open_price,
                            exit_price=position.close_price or position.current_price,
                            gross_pnl=position.profit,
                            commission=position.commission,
                            pnl=position.net_profit,
                            exit_reason=position.close_reason,
                            source="live",
                            entry_time=position.opened_at,
                            exit_time=position.closed_at or position.opened_at,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - persistence must not break trading
            logger.warning("Unable to persist position", position_id=position.position_id, error=str(exc))
