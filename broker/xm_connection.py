"""XMTrading connection handling.

Two transports are supported:

``simulated``
    All requests are served by :class:`broker.simulator.SimulatedBroker`.
    No network access and no credentials are required, which is the default
    for development, CI and demos.
``rest``
    Requests are issued against an XM-compatible REST gateway using bearer
    authentication.  XM does not publish a public REST trading API; point
    ``broker.xmtrading.rest_url`` at your own MT5 bridge (for example a
    ``MetaTrader5``-backed FastAPI service) that implements the endpoints
    documented in :mod:`README`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping, Optional

from broker.simulator import SimulatedBroker
from utils.config import Config, get_config
from utils.exceptions import AuthenticationError, BrokerConnectionError
from utils.helpers import async_retry, utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class XMConnection:
    """Manages the session with the XM trading backend."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        demo: bool = True,
        mode: Optional[str] = None,
        config: Optional[Config] = None,
    ) -> None:
        """Initialise the connection.

        Args:
            account_id: XM account number.
            password: Account password (never logged).
            server: Broker server name, e.g. ``XMGlobal-Demo``.
            demo: Whether the account is a demo account.
            mode: ``simulated`` or ``rest``; read from config when omitted.
            config: Optional configuration override.
        """
        self.config = config or get_config()
        section = self.config.section("broker.xmtrading")
        self.account_id = account_id or str(section.get("account_id", "DEMO-1000001"))
        self._password = password if password is not None else str(section.get("password", ""))
        self.server = server or str(section.get("server", "XMGlobal-Demo"))
        self.demo = bool(section.get_bool("demo", demo))
        self.mode = (mode or str(section.get("mode", "simulated"))).lower()
        self.rest_url = str(section.get("rest_url", "https://demo.xm.com/api"))
        self.ws_url = str(section.get("ws_url", "wss://demo.xm.com/ws"))
        self.timeout = section.get_int("request_timeout", 15)
        self.max_retries = section.get_int("max_retries", 4)
        self.symbols = [str(symbol).upper() for symbol in section.get_list("symbols")]
        self.leverage = section.get_float("leverage", 500.0)

        self._session: Any = None
        self._token: Optional[str] = None
        self._connected = False
        self._connected_at = None
        self._simulator: Optional[SimulatedBroker] = None
        self._lock = asyncio.Lock()

        if self.mode == "simulated":
            self._simulator = SimulatedBroker(
                account_id=self.account_id,
                balance=section.get_float("initial_balance", 10_000.0),
                leverage=self.leverage,
                symbols=self.symbols or None,
                server=self.server,
            )

    # -- properties ----------------------------------------------------------
    @property
    def is_simulated(self) -> bool:
        """``True`` when the local matching engine is in use."""
        return self.mode == "simulated"

    @property
    def is_connected(self) -> bool:
        """``True`` once :meth:`connect` succeeded."""
        return self._connected

    @property
    def simulator(self) -> SimulatedBroker:
        """Return the simulated broker.

        Raises:
            BrokerConnectionError: When running in REST mode.
        """
        if self._simulator is None:
            raise BrokerConnectionError("Simulator is not available in REST mode", mode=self.mode)
        return self._simulator

    # -- lifecycle -----------------------------------------------------------
    async def connect(self) -> bool:
        """Establish the broker session.

        Returns:
            ``True`` when the session is usable.

        Raises:
            AuthenticationError: If the gateway rejects the credentials.
            BrokerConnectionError: If the gateway is unreachable.
        """
        async with self._lock:
            if self._connected:
                return True
            if self.is_simulated:
                self._connected = True
                self._connected_at = utcnow()
                logger.info(
                    "Connected to simulated XM backend",
                    account_id=self.account_id,
                    server=self.server,
                    symbols=len(self.symbols),
                )
                return True
            await self._connect_rest()
            return self._connected

    @async_retry(attempts=3, delay=2.0, exceptions=(BrokerConnectionError, OSError))
    async def _connect_rest(self) -> None:
        """Authenticate against the REST gateway."""
        import aiohttp  # imported lazily so simulated mode has no hard dependency

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        payload = {"account_id": self.account_id, "password": self._password, "server": self.server}
        try:
            async with self._session.post(f"{self.rest_url}/auth/login", json=payload) as response:
                if response.status in (401, 403):
                    raise AuthenticationError("XM rejected the credentials", account_id=self.account_id)
                if response.status != 200:
                    raise BrokerConnectionError(
                        "XM authentication failed", status=response.status, url=self.rest_url
                    )
                data = await response.json()
        except aiohttp.ClientError as exc:
            raise BrokerConnectionError("Unable to reach XM gateway", url=self.rest_url, error=str(exc)) from exc

        self._token = str(data.get("token") or data.get("access_token") or "")
        if not self._token:
            raise AuthenticationError("XM did not return a session token", account_id=self.account_id)
        self._connected = True
        self._connected_at = utcnow()
        logger.info("Connected to XM REST gateway", account_id=self.account_id, server=self.server)

    async def disconnect(self) -> None:
        """Close the broker session and release resources."""
        async with self._lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = None
            self._token = None
            self._connected = False
            logger.info("Disconnected from XM", account_id=self.account_id, mode=self.mode)

    async def ensure_connected(self) -> None:
        """Connect on demand, raising when the session cannot be established."""
        if not self._connected:
            await self.connect()

    # -- transport -----------------------------------------------------------
    @property
    def headers(self) -> Dict[str, str]:
        """Authorisation headers for REST calls."""
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @async_retry(attempts=3, delay=1.0, exceptions=(BrokerConnectionError, OSError))
    async def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Perform an authenticated REST call.

        Args:
            method: HTTP verb.
            path: Path relative to the gateway root, e.g. ``"/orders"``.
            json_body: Optional JSON payload.
            params: Optional query parameters.

        Returns:
            The decoded JSON response.

        Raises:
            BrokerConnectionError: On transport or protocol failures.
        """
        if self.is_simulated:
            raise BrokerConnectionError("REST requests are not available in simulated mode", path=path)
        await self.ensure_connected()
        import aiohttp

        url = f"{self.rest_url}{path}"
        try:
            async with self._session.request(
                method.upper(), url, json=json_body, params=params, headers=self.headers
            ) as response:
                if response.status == 401:
                    self._connected = False
                    raise BrokerConnectionError("XM session expired", path=path)
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise BrokerConnectionError(
                        "XM request failed", status=response.status, path=path, body=str(body)[:200]
                    )
                return body
        except aiohttp.ClientError as exc:
            raise BrokerConnectionError("XM transport error", path=path, error=str(exc)) from exc

    # -- diagnostics ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Return a connection summary for the API and dashboard."""
        return {
            "mode": self.mode,
            "connected": self._connected,
            "account_id": self.account_id,
            "server": self.server,
            "demo": self.demo,
            "leverage": self.leverage,
            "symbols": self.symbols,
            "rest_url": self.rest_url if not self.is_simulated else None,
            "connected_at": self._connected_at.isoformat() if self._connected_at else None,
        }

    async def ping(self) -> bool:
        """Check that the backend is responsive."""
        if self.is_simulated:
            return self._connected
        try:
            await self.request("GET", "/health")
            return True
        except Exception as exc:
            logger.warning("XM ping failed", error=str(exc))
            return False
