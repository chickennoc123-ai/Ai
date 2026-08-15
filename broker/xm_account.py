"""Account information façade."""

from __future__ import annotations

from typing import Any, Dict

from broker.xm_connection import XMConnection
from broker.xm_models import AccountInfo
from utils.logger import get_logger

logger = get_logger(__name__)


class XMAccount:
    """Reads balance, equity, margin and leverage from the broker."""

    def __init__(self, connection: XMConnection) -> None:
        """Bind the façade to a connection."""
        self.connection = connection

    async def get_info(self) -> AccountInfo:
        """Return the full account snapshot."""
        await self.connection.ensure_connected()
        if self.connection.is_simulated:
            return self.connection.simulator.account_info()
        payload: Dict[str, Any] = await self.connection.request("GET", "/account")
        return AccountInfo(
            account_id=str(payload.get("account_id", self.connection.account_id)),
            balance=float(payload.get("balance", 0.0)),
            equity=float(payload.get("equity", 0.0)),
            margin=float(payload.get("margin", 0.0)),
            free_margin=float(payload.get("free_margin", 0.0)),
            margin_level=float(payload.get("margin_level", 0.0)),
            leverage=float(payload.get("leverage", self.connection.leverage)),
            currency=str(payload.get("currency", "USD")),
            server=str(payload.get("server", self.connection.server)),
            demo=bool(payload.get("demo", self.connection.demo)),
            open_positions=int(payload.get("open_positions", 0)),
        )

    async def get_balance(self) -> float:
        """Return the account balance."""
        return (await self.get_info()).balance

    async def get_equity(self) -> float:
        """Return the account equity including floating P&L."""
        return (await self.get_info()).equity

    async def get_margin(self) -> float:
        """Return the margin currently in use."""
        return (await self.get_info()).margin

    async def get_free_margin(self) -> float:
        """Return the margin still available for new positions."""
        return (await self.get_info()).free_margin

    async def get_margin_level(self) -> float:
        """Return the margin level in percent (``equity / margin * 100``)."""
        return (await self.get_info()).margin_level

    async def get_leverage(self) -> float:
        """Return the account leverage."""
        return (await self.get_info()).leverage

    async def summary(self) -> Dict[str, Any]:
        """Return a JSON-friendly account summary."""
        info = await self.get_info()
        payload = info.to_dict()
        payload["mode"] = self.connection.mode
        return payload
