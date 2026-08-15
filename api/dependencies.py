"""Application state and FastAPI dependency providers.

A single :class:`AppState` object owns every long-lived component (database,
broker connection, agent fleet, services, WebSocket hub).  It is created during
the application lifespan and injected into routers through the ``get_*``
dependency helpers.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from agents.orchestrator import AgentOrchestrator
from broker.xm_account import XMAccount
from broker.xm_connection import XMConnection
from broker.xm_orders import XMOrders
from broker.xm_positions import XMPositions
from core.data_manager import DataManager
from core.decision import DecisionEngine
from core.lifecycle import LifecycleManager
from models.database import Database, get_database
from services.backtest_service import BacktestService
from services.market_data import MarketDataService
from services.notification_service import NotificationService
from services.order_service import OrderService
from services.position_service import PositionService
from services.strategy_service import StrategyService
from services.validation_service import ValidationService
from utils.config import Config, get_config
from utils.helpers import utcnow
from utils.logger import get_logger
from websocket.handler import ConnectionHub
from websocket.xm_stream import XMStreamBridge

logger = get_logger(__name__)


class AppState:
    """Owns every shared component of the API process."""

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialise an empty state; call :meth:`startup` to build it."""
        self.config = config or get_config()
        self.started_at: Optional[datetime] = None
        self.database: Optional[Database] = None
        self.orchestrator: Optional[AgentOrchestrator] = None
        self.hub = ConnectionHub()
        self.bridge: Optional[XMStreamBridge] = None

        self.connection: Optional[XMConnection] = None
        self.account: Optional[XMAccount] = None
        self.orders: Optional[XMOrders] = None
        self.positions: Optional[XMPositions] = None
        self.data_manager: Optional[DataManager] = None
        self.lifecycle: Optional[LifecycleManager] = None
        self.decision: Optional[DecisionEngine] = None

        self.market_service: Optional[MarketDataService] = None
        self.order_service: Optional[OrderService] = None
        self.position_service: Optional[PositionService] = None
        self.strategy_service: Optional[StrategyService] = None
        self.backtest_service: Optional[BacktestService] = None
        self.validation_service: Optional[ValidationService] = None
        self.notifications: Optional[NotificationService] = None

    async def startup(self, start_agents: bool = True) -> None:
        """Build the database, the agent runtime and every service."""
        self.started_at = utcnow()

        try:
            self.database = get_database(self.config)
            self.database.create_all()
        except Exception as exc:  # noqa: BLE001 - the API must boot without a database
            logger.error("Database unavailable, continuing without persistence", error=str(exc))
            self.database = None

        self.orchestrator = AgentOrchestrator(self.config)
        context = await self.orchestrator.setup()

        self.connection = context["connection"]
        self.account = context["account"]
        self.orders = context["orders"]
        self.positions = context["positions"]
        self.data_manager = context["data_manager"]
        self.lifecycle = context["lifecycle"]
        self.decision = context["decision_engine"]

        self.market_service = MarketDataService(self.data_manager, self.config)
        self.order_service = OrderService(self.orders, self.database)
        self.position_service = PositionService(self.positions, self.database)
        self.strategy_service = StrategyService(self.database, self.lifecycle)
        self.backtest_service = BacktestService(self.data_manager, self.config, self.database)
        self.validation_service = ValidationService(self.data_manager, self.config, self.database)
        self.notifications = NotificationService(self.config, self.database)

        self.bridge = XMStreamBridge(
            stream=context["stream"],
            hub=self.hub,
            bus=context["bus"],
            data_manager=self.data_manager,
            market_data=self.market_service,
            publish_interval=self.config.get_float("dashboard.refresh_interval", 1.0),
        )

        if start_agents:
            await self.orchestrator.start()
        else:
            await self.bridge.start()

        logger.info(
            "API state ready",
            agents=start_agents,
            database=bool(self.database),
            mode=self.connection.mode if self.connection else "unknown",
        )

    async def shutdown(self) -> None:
        """Tear every component down in reverse order."""
        if self.bridge is not None:
            await self.bridge.stop()
        if self.orchestrator is not None:
            await self.orchestrator.stop()
        if self.market_service is not None:
            await self.market_service.close()
        if self.database is not None:
            self.database.dispose()
        logger.info("API state shut down")

    def health(self) -> Dict[str, Any]:
        """Return the aggregated health of every subsystem."""
        uptime = (utcnow() - self.started_at).total_seconds() if self.started_at else 0.0
        return {
            "status": "ok",
            "name": self.config.get("system.name", "EA Factory Pro"),
            "version": self.config.get("system.version", "1.0.0"),
            "environment": self.config.get("system.environment", "development"),
            "uptime_seconds": round(uptime, 1),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "database": self.database.health() if self.database else {"connected": False},
            "broker": self.connection.status() if self.connection else {},
            "agents": self.orchestrator.health() if self.orchestrator else {},
            "stream": self.bridge.status() if self.bridge else {},
            "websocket_clients": self.hub.client_count,
        }


_state: Optional[AppState] = None


def set_state(state: Optional[AppState]) -> None:
    """Install the application state singleton."""
    global _state
    _state = state


def get_state() -> AppState:
    """Return the application state.

    Raises:
        HTTPException: If the API is still starting up.
    """
    if _state is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service is starting"
        )
    return _state


# -- component providers -----------------------------------------------------
def get_account(state: AppState = Depends(get_state)) -> XMAccount:
    """Provide the broker account façade."""
    return _require(state.account, "account")


def get_order_service(state: AppState = Depends(get_state)) -> OrderService:
    """Provide the order service."""
    return _require(state.order_service, "order service")


def get_position_service(state: AppState = Depends(get_state)) -> PositionService:
    """Provide the position service."""
    return _require(state.position_service, "position service")


def get_strategy_service(state: AppState = Depends(get_state)) -> StrategyService:
    """Provide the strategy service."""
    return _require(state.strategy_service, "strategy service")


def get_backtest_service(state: AppState = Depends(get_state)) -> BacktestService:
    """Provide the backtest service."""
    return _require(state.backtest_service, "backtest service")


def get_validation_service(state: AppState = Depends(get_state)) -> ValidationService:
    """Provide the validation service."""
    return _require(state.validation_service, "validation service")


def get_market_service(state: AppState = Depends(get_state)) -> MarketDataService:
    """Provide the market data service."""
    return _require(state.market_service, "market data service")


def get_orchestrator(state: AppState = Depends(get_state)) -> AgentOrchestrator:
    """Provide the agent orchestrator."""
    return _require(state.orchestrator, "orchestrator")


def get_hub(state: AppState = Depends(get_state)) -> ConnectionHub:
    """Provide the WebSocket hub."""
    return state.hub


def _require(component: Any, name: str) -> Any:
    """Return ``component`` or raise a 503.

    Raises:
        HTTPException: When the component is not initialised.
    """
    if component is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"The {name} is not available"
        )
    return component


# -- authentication ----------------------------------------------------------
def create_access_token(subject: str, config: Optional[Config] = None) -> Dict[str, Any]:
    """Issue a signed JWT for ``subject``.

    Raises:
        HTTPException: If PyJWT is not installed.
    """
    cfg = config or get_config()
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise HTTPException(status_code=500, detail="PyJWT is not installed") from exc

    minutes = cfg.get_int("api.jwt_expire_minutes", 720)
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expires, "iat": datetime.now(timezone.utc)}
    token = jwt.encode(payload, str(cfg.get("api.jwt_secret", "change-me")), algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": expires.isoformat()}


def verify_credentials(username: str, password: str, config: Optional[Config] = None) -> bool:
    """Check credentials against the configured API user."""
    cfg = config or get_config()
    expected_user = os.environ.get("API_USERNAME", "admin")
    expected_password = os.environ.get("API_PASSWORD", "admin")
    del cfg  # credentials come from the environment only
    return username == expected_user and password == expected_password


async def require_auth(
    authorization: Optional[str] = Header(default=None),
    state: AppState = Depends(get_state),
) -> Optional[str]:
    """Validate the bearer token when authentication is enabled.

    Returns:
        The authenticated subject, or ``None`` when auth is disabled.

    Raises:
        HTTPException: If the token is missing, malformed or expired.
    """
    if not state.config.get_bool("api.auth_enabled", False):
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        import jwt

        payload = jwt.decode(
            token, str(state.config.get("api.jwt_secret", "change-me")), algorithms=["HS256"]
        )
    except Exception as exc:  # noqa: BLE001 - any decode failure is a 401
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    return str(payload.get("sub", ""))
