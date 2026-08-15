"""FastAPI application entry point.

Run locally with::

    uvicorn api.main:app --reload --port 8000

The application lifespan builds the whole runtime (broker connection, agent
fleet, services, WebSocket bridge) and tears it down cleanly on shutdown.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Deque, Dict

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from api.dependencies import AppState, create_access_token, get_state, set_state, verify_credentials
from api.routers import account, backtest, market, orders, positions, strategies, system, validation
from api.websocket import handler as websocket_handler
from utils.config import get_config
from utils.exceptions import EAFactoryError
from utils.helpers import correlation_id
from utils.logger import get_logger, set_correlation_id, setup_logging_from_config

config = get_config()
setup_logging_from_config(config)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Build and tear down the application runtime."""
    state = AppState(config)
    set_state(state)
    start_agents = os.environ.get("API_START_AGENTS", "true").lower() not in ("0", "false", "no")
    try:
        await state.startup(start_agents=start_agents)
    except Exception as exc:  # noqa: BLE001 - report but keep serving /health
        logger.error("Startup failed, API running in degraded mode", error=str(exc), exc_info=True)
    application.state.runtime = state
    try:
        yield
    finally:
        await state.shutdown()
        set_state(None)


app = FastAPI(
    title=str(config.get("system.name", "EA Factory Pro")),
    version=str(config.get("system.version", "1.0.0")),
    description=(
        "Unified trading platform for XAUUSD, EURUSD, USDJPY, GBPUSD and AUDUSD: "
        "multi-agent research, validation, execution and risk management."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_list("api.cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimiter:
    """Fixed-window, per-client rate limiter."""

    def __init__(self, limit: int = 240, window: float = 60.0) -> None:
        """Configure the allowance and the window length in seconds."""
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Return ``True`` when the caller is still under the limit."""
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def _parse_rate_limit(value: str) -> tuple[int, float]:
    """Parse a ``"240/minute"`` style rate-limit string."""
    try:
        count, unit = str(value).split("/")
        seconds = {"second": 1.0, "minute": 60.0, "hour": 3600.0}.get(unit.strip().lower(), 60.0)
        return int(count), seconds
    except (ValueError, AttributeError):
        return 240, 60.0


_limit, _window = _parse_rate_limit(str(config.get("api.rate_limit", "240/minute")))
rate_limiter = RateLimiter(_limit, _window)


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Any:
    """Attach a correlation id, apply rate limiting and log the request."""
    identifier = request.headers.get("x-correlation-id") or correlation_id()
    set_correlation_id(identifier)
    client = request.client.host if request.client else "unknown"

    if request.url.path.startswith("/api/") and not rate_limiter.allow(client):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded"},
            headers={"x-correlation-id": identifier},
        )

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except EAFactoryError as exc:
        logger.error("Unhandled platform error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__},
            headers={"x-correlation-id": identifier},
        )
    duration = (time.perf_counter() - started) * 1000
    response.headers["x-correlation-id"] = identifier
    response.headers["x-response-time-ms"] = f"{duration:.1f}"
    if not request.url.path.endswith(("/health", "/metrics")):
        logger.info(
            "HTTP request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration, 1),
        )
    return response


for router in (
    account.router,
    orders.router,
    positions.router,
    strategies.router,
    backtest.router,
    validation.router,
    market.router,
    system.router,
):
    app.include_router(router)
app.include_router(websocket_handler.router)


class TokenRequest(BaseModel):
    """Credentials accepted by the token endpoint."""

    username: str
    password: str


@app.post("/api/v1/auth/token", tags=["auth"], summary="Issue an access token")
async def issue_token(request: TokenRequest) -> Dict[str, Any]:
    """Exchange credentials for a JWT.

    Raises:
        HTTPException: 401 when the credentials are wrong.
    """
    if not verify_credentials(request.username, request.password, config):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return create_access_token(request.username, config)


@app.get("/", tags=["system"], summary="Service banner")
async def root() -> Dict[str, Any]:
    """Return the service banner and the documentation links."""
    return {
        "name": config.get("system.name", "EA Factory Pro"),
        "version": config.get("system.version", "1.0.0"),
        "environment": config.get("system.environment", "development"),
        "docs": "/docs",
        "health": "/health",
        "websocket": "/api/v1/ws",
    }


@app.get("/health", tags=["system"], summary="Liveness and readiness probe")
async def health() -> Dict[str, Any]:
    """Return a health payload; always 200 so the container stays up."""
    try:
        return get_state().health()
    except HTTPException:
        return {"status": "starting"}


@app.get("/metrics", tags=["system"], response_class=PlainTextResponse, summary="Prometheus metrics")
async def prometheus_metrics(state: AppState = Depends(get_state)) -> str:
    """Expose core counters in the Prometheus text exposition format."""
    lines = [
        "# HELP ea_factory_up Whether the platform runtime is initialised.",
        "# TYPE ea_factory_up gauge",
        f"ea_factory_up {1 if state.orchestrator else 0}",
    ]
    try:
        if state.account is not None:
            info = await state.account.get_info()
            lines += [
                "# HELP ea_factory_equity Account equity in account currency.",
                "# TYPE ea_factory_equity gauge",
                f"ea_factory_equity {info.equity:.2f}",
                "# HELP ea_factory_balance Account balance in account currency.",
                "# TYPE ea_factory_balance gauge",
                f"ea_factory_balance {info.balance:.2f}",
                "# HELP ea_factory_open_positions Number of open positions.",
                "# TYPE ea_factory_open_positions gauge",
                f"ea_factory_open_positions {info.open_positions}",
            ]
        if state.orchestrator is not None:
            health_payload = state.orchestrator.health()
            lines += [
                "# HELP ea_factory_agent_cycles Completed agent cycles.",
                "# TYPE ea_factory_agent_cycles counter",
            ]
            for name, agent_health in health_payload.get("agents", {}).items():
                lines.append(
                    f'ea_factory_agent_cycles{{agent="{name}"}} {agent_health["metrics"]["cycles"]}'
                )
            lines += [
                "# HELP ea_factory_agent_errors Agent errors.",
                "# TYPE ea_factory_agent_errors counter",
            ]
            for name, agent_health in health_payload.get("agents", {}).items():
                lines.append(
                    f'ea_factory_agent_errors{{agent="{name}"}} {agent_health["metrics"]["errors"]}'
                )
        lines += [
            "# HELP ea_factory_websocket_clients Connected dashboard clients.",
            "# TYPE ea_factory_websocket_clients gauge",
            f"ea_factory_websocket_clients {state.hub.client_count}",
        ]
    except Exception as exc:  # noqa: BLE001 - metrics must never fail hard
        lines.append(f"# error {exc}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover - manual launch helper
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=str(config.get("api.host", "0.0.0.0")),
        port=config.get_int("api.port", 8000),
        reload=False,
    )
