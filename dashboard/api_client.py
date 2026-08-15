"""HTTP client used by the dashboard to talk to the FastAPI backend.

Every call degrades gracefully: on failure the client returns a fallback value
and records the error so pages can show a banner instead of a traceback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from utils.config import Config, get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class APIClient:
    """Thin, failure-tolerant wrapper around the platform REST API."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0, config: Optional[Config] = None) -> None:
        """Initialise the client.

        Args:
            base_url: API root; read from ``dashboard.api_url`` when omitted.
            timeout: Per-request timeout in seconds.
            config: Optional configuration override.
        """
        cfg = config or get_config()
        self.base_url = (base_url or str(cfg.get("dashboard.api_url", "http://localhost:8000"))).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.last_error: str = ""
        self.token: Optional[str] = None

    # -- transport -----------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        """Return the request headers, including auth when a token is set."""
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, default: Any = None, **kwargs: Any) -> Any:
        """Perform a request and return the decoded body or ``default``."""
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method, url, timeout=kwargs.pop("timeout", self.timeout), headers=self._headers(), **kwargs
            )
            if response.status_code >= 400:
                self.last_error = f"{response.status_code} {response.text[:200]}"
                logger.warning("API error", path=path, status=response.status_code)
                return default
            self.last_error = ""
            return response.json()
        except requests.RequestException as exc:
            self.last_error = str(exc)
            logger.warning("API unreachable", path=path, error=str(exc))
            return default

    def get(self, path: str, default: Any = None, **params: Any) -> Any:
        """GET a resource."""
        return self.request("GET", path, default, params=params or None)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None, default: Any = None) -> Any:
        """POST a JSON body."""
        return self.request("POST", path, default, json=payload or {})

    def put(self, path: str, payload: Optional[Dict[str, Any]] = None, default: Any = None) -> Any:
        """PUT a JSON body."""
        return self.request("PUT", path, default, json=payload or {})

    def delete(self, path: str, default: Any = None) -> Any:
        """DELETE a resource."""
        return self.request("DELETE", path, default)

    # -- typed helpers -------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        """Return the platform health payload."""
        return self.get("/health", {}) or {}

    def is_online(self) -> bool:
        """``True`` when the API answered the last health probe."""
        return bool(self.health())

    def account(self) -> Dict[str, Any]:
        """Return the account snapshot."""
        return self.get("/api/v1/account", {}) or {}

    def positions(self) -> List[Dict[str, Any]]:
        """Return open positions."""
        return self.get("/api/v1/positions", []) or []

    def position_summary(self) -> Dict[str, Any]:
        """Return the aggregated exposure summary."""
        return self.get("/api/v1/positions/summary", {}) or {}

    def position_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Return closed positions."""
        return self.get("/api/v1/positions/history", [], days=days) or []

    def close_position(self, position_id: str, reason: str = "DASHBOARD") -> Dict[str, Any]:
        """Close one position."""
        return self.post(f"/api/v1/positions/{position_id}/close", {"reason": reason}, {}) or {}

    def close_all(self, reason: str = "DASHBOARD") -> List[Dict[str, Any]]:
        """Close every open position."""
        return self.post("/api/v1/positions/close-all", {"reason": reason}, []) or []

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order."""
        return self.post("/api/v1/orders", payload, {}) or {}

    def orders(self) -> List[Dict[str, Any]]:
        """List broker orders."""
        return self.get("/api/v1/orders", []) or []

    def market(self, symbol: str, timeframe: str = "H1", bars: int = 300, indicators: str = "") -> Dict[str, Any]:
        """Return candles and indicator overlays for a symbol."""
        params: Dict[str, Any] = {"timeframe": timeframe, "bars": bars}
        if indicators:
            params["indicators"] = indicators
        return self.get(f"/api/v1/market/{symbol}", {}, **params) or {}

    def snapshot(self, timeframe: str = "H1") -> List[Dict[str, Any]]:
        """Return a summary row per symbol."""
        return self.get("/api/v1/market/snapshot", [], timeframe=timeframe) or []

    def symbols(self) -> List[Dict[str, Any]]:
        """Return instrument specifications."""
        return self.get("/api/v1/market/symbols", []) or []

    def strategies(self) -> Dict[str, Any]:
        """Return the strategy catalogue and configured instances."""
        return self.get("/api/v1/strategies", {}) or {}

    def lifecycle(self) -> Dict[str, Any]:
        """Return the lifecycle snapshot."""
        return self.get("/api/v1/strategies/lifecycle", {}) or {}

    def run_backtest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run a backtest."""
        return self.post("/api/v1/backtest/run", payload, {}) or {}

    def run_validation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run a validation pass."""
        return self.post("/api/v1/validation/run", payload, {}) or {}

    def validation_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return stored validation reports."""
        return self.get("/api/v1/validation/history", [], limit=limit) or []

    def agents(self) -> Dict[str, Any]:
        """Return agent health."""
        return self.get("/api/v1/agents", {}) or {}

    def agent_reports(self) -> Dict[str, Any]:
        """Return per-agent detailed reports."""
        return self.get("/api/v1/agents/reports", {}) or {}

    def metrics(self) -> Dict[str, Any]:
        """Return the aggregated metric payload."""
        return self.get("/api/v1/metrics", {}) or {}

    def messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent bus messages."""
        return self.get("/api/v1/messages", [], limit=limit) or []

    def send_command(self, command: str, target: Optional[str] = None, **payload: Any) -> Dict[str, Any]:
        """Broadcast a command to the agent fleet."""
        return self.post("/api/v1/commands", {"command": command, "target": target, "payload": payload}, {}) or {}
