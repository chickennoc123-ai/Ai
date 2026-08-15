"""Integration tests for the FastAPI application.

The app is exercised in-process through ``httpx.ASGITransport``, with the agent
fleet disabled so the tests stay fast and deterministic.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
import pytest

os.environ.setdefault("API_START_AGENTS", "false")

from api.main import app  # noqa: E402


@pytest.fixture(scope="module")
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client bound to the running application."""
    from asgi_lifespan import LifespanManager  # type: ignore

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as http:
            yield http


pytest.importorskip("asgi_lifespan", reason="asgi-lifespan is required for the API tests")


# -- system ------------------------------------------------------------------
async def test_root_banner(client: httpx.AsyncClient) -> None:
    """The root endpoint advertises the service."""
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["name"]


async def test_health(client: httpx.AsyncClient) -> None:
    """Health reports the broker and database status."""
    payload = (await client.get("/health")).json()
    assert payload["status"] == "ok"
    assert payload["broker"]["mode"] == "simulated"
    assert payload["broker"]["connected"] is True


async def test_status_endpoint(client: httpx.AsyncClient) -> None:
    """The status endpoint mirrors the health payload."""
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
    assert "broker" in response.json()


async def test_prometheus_metrics(client: httpx.AsyncClient) -> None:
    """Prometheus metrics are exposed in the text format."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "ea_factory_equity" in response.text


async def test_correlation_id_header(client: httpx.AsyncClient) -> None:
    """Every response carries a correlation id."""
    response = await client.get("/health")
    assert response.headers.get("x-correlation-id")


# -- account and market ------------------------------------------------------
async def test_account_endpoint(client: httpx.AsyncClient) -> None:
    """The account endpoint returns the simulated balance."""
    payload = (await client.get("/api/v1/account")).json()
    assert payload["balance"] > 0
    assert payload["demo"] is True


async def test_symbols_endpoint(client: httpx.AsyncClient) -> None:
    """All five instruments are exposed with their specifications."""
    payload = (await client.get("/api/v1/market/symbols")).json()
    symbols = {item["symbol"] for item in payload}
    assert symbols == {"XAUUSD", "EURUSD", "USDJPY", "GBPUSD", "AUDUSD"}
    gold = next(item for item in payload if item["symbol"] == "XAUUSD")
    assert gold["contract_size"] == 100.0


async def test_market_candles(client: httpx.AsyncClient) -> None:
    """Candles come back with the requested indicators."""
    response = await client.get("/api/v1/market/XAUUSD", params={"bars": 120, "indicators": "rsi,atr"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["bars"] == 120
    assert len(payload["candles"]) == 120
    assert {"rsi", "atr"} <= set(payload["indicators"])


async def test_market_rejects_an_unknown_symbol(client: httpx.AsyncClient) -> None:
    """An unknown symbol is a 400, not a 500."""
    response = await client.get("/api/v1/market/NOTREAL")
    assert response.status_code == 400


async def test_market_rejects_an_out_of_range_bar_count(client: httpx.AsyncClient) -> None:
    """Query validation rejects an unreasonable bar count."""
    assert (await client.get("/api/v1/market/EURUSD", params={"bars": 1})).status_code == 422


async def test_market_snapshot(client: httpx.AsyncClient) -> None:
    """The snapshot has one row per symbol."""
    payload = (await client.get("/api/v1/market/snapshot")).json()
    assert len(payload) == 5
    assert all("price" in row for row in payload)


# -- trading -----------------------------------------------------------------
async def test_order_lifecycle(client: httpx.AsyncClient) -> None:
    """An order can be placed, listed and its position closed."""
    response = await client.post(
        "/api/v1/orders",
        json={"symbol": "EURUSD", "volume": 0.05, "direction": "BUY", "comment": "pytest"},
    )
    assert response.status_code == 201
    report = response.json()
    assert report["success"] is True
    position_id = report["order"]["position_id"]

    positions = (await client.get("/api/v1/positions")).json()
    assert any(item["position_id"] == position_id for item in positions)

    summary = (await client.get("/api/v1/positions/summary")).json()
    assert summary["open_positions"] >= 1

    closed = await client.post(f"/api/v1/positions/{position_id}/close", json={"reason": "pytest"})
    assert closed.status_code == 200
    assert closed.json()["close_reason"] == "pytest"


async def test_order_validation_error(client: httpx.AsyncClient) -> None:
    """A malformed order is rejected with a 400."""
    response = await client.post(
        "/api/v1/orders", json={"symbol": "NOTREAL", "volume": 0.1, "direction": "BUY"}
    )
    assert response.status_code == 400


async def test_pending_order_can_be_cancelled(client: httpx.AsyncClient) -> None:
    """A pending order is accepted and can be cancelled."""
    quote = (await client.get("/api/v1/market/quotes")).json()
    price = float(quote.get("EURUSD", {}).get("mid") or 1.08) * 0.95
    response = await client.post(
        "/api/v1/orders",
        json={
            "symbol": "EURUSD",
            "volume": 0.05,
            "direction": "BUY",
            "order_type": "LIMIT",
            "price": round(price, 5),
        },
    )
    assert response.status_code == 201
    order_id = response.json()["order"]["order_id"]
    cancelled = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


async def test_unknown_order_is_404(client: httpx.AsyncClient) -> None:
    """Unknown ids produce a 404."""
    assert (await client.get("/api/v1/orders/nope")).status_code == 404
    assert (await client.get("/api/v1/positions/nope")).status_code == 404


# -- strategies --------------------------------------------------------------
async def test_strategy_catalogue(client: httpx.AsyncClient) -> None:
    """The catalogue lists at least ten strategies."""
    payload = (await client.get("/api/v1/strategies")).json()
    assert len(payload["available"]) >= 10
    assert "RSI" in payload["available"]


async def test_strategy_parameters(client: httpx.AsyncClient) -> None:
    """The parameter space of a strategy is exposed."""
    payload = (await client.get("/api/v1/strategies/RSI/parameters")).json()
    assert any(item["name"] == "rsi_period" for item in payload)


async def test_unknown_strategy_parameters_is_404(client: httpx.AsyncClient) -> None:
    """An unknown strategy name is a 404."""
    assert (await client.get("/api/v1/strategies/Nope/parameters")).status_code == 404


async def test_strategy_crud(client: httpx.AsyncClient) -> None:
    """A strategy configuration can be created, updated and deleted."""
    created = await client.post(
        "/api/v1/strategies",
        json={"name": "RSI", "symbol": "GBPUSD", "timeframe": "H4", "params": {"rsi_period": 21}},
    )
    assert created.status_code == 201
    strategy_id = created.json()["strategy_id"]

    duplicate = await client.post(
        "/api/v1/strategies",
        json={"name": "RSI", "symbol": "GBPUSD", "timeframe": "H4", "params": {"rsi_period": 21}},
    )
    assert duplicate.status_code == 400

    updated = await client.put(f"/api/v1/strategies/{strategy_id}", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    paused = await client.post(f"/api/v1/strategies/{strategy_id}/pause")
    assert paused.json()["state"] == "PAUSED"

    deleted = await client.delete(f"/api/v1/strategies/{strategy_id}")
    assert deleted.status_code == 200


# -- research ----------------------------------------------------------------
@pytest.mark.slow
async def test_backtest_endpoint(client: httpx.AsyncClient) -> None:
    """A backtest returns metrics and an equity curve."""
    response = await client.post(
        "/api/v1/backtest/run",
        json={"name": "SMA_Cross", "symbol": "XAUUSD", "timeframe": "H1", "bars": 2000},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["bars"] == 2000
    assert len(payload["equity_curve"]["values"]) == 2000
    assert "sharpe" in payload["metrics"]


async def test_backtest_rejects_unknown_strategy(client: httpx.AsyncClient) -> None:
    """An unknown strategy is a 400."""
    response = await client.post(
        "/api/v1/backtest/run", json={"name": "Nope", "symbol": "XAUUSD", "bars": 1000}
    )
    assert response.status_code == 400


@pytest.mark.slow
async def test_validation_endpoint(client: httpx.AsyncClient) -> None:
    """A quick validation returns a complete verdict."""
    response = await client.post(
        "/api/v1/validation/run",
        json={"name": "RSI", "symbol": "EURUSD", "bars": 2000, "quick": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["passed"], bool)
    assert "walk_forward" in payload
    assert payload["pbo"]["computed"] is False


# -- agents ------------------------------------------------------------------
async def test_agents_endpoint(client: httpx.AsyncClient) -> None:
    """Agent health is reported even when the fleet is disabled."""
    response = await client.get("/api/v1/agents")
    assert response.status_code == 200
    assert "agents" in response.json()


async def test_commands_endpoint(client: httpx.AsyncClient) -> None:
    """Commands are accepted and dispatched on the bus."""
    response = await client.post(
        "/api/v1/commands", json={"command": "risk_check", "target": "risk", "payload": {}}
    )
    assert response.status_code == 200
    assert response.json()["dispatched"] is True


async def test_metrics_endpoint(client: httpx.AsyncClient) -> None:
    """The aggregated metrics payload has the expected sections."""
    payload = (await client.get("/api/v1/metrics")).json()
    for key in ("account", "positions", "risk", "agents", "trading"):
        assert key in payload
