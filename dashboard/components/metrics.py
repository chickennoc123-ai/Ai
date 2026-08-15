"""Metric widgets shared by the dashboard pages."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

STATE_COLORS = {
    "ACTIVE": "🟢",
    "DEGRADED": "🟡",
    "PAUSED": "🟠",
    "RETIRED": "⚫",
    "RUNNING": "🟢",
    "STOPPED": "⚫",
    "FAILED": "🔴",
    "CREATED": "⚪",
    "STARTING": "🔵",
    "CRITICAL": "🔴",
    "WARNING": "🟡",
    "INFO": "🔵",
}

METRIC_LABELS_VI = {
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "calmar": "Calmar",
    "max_drawdown": "Sụt giảm tối đa",
    "win_rate": "Tỷ lệ thắng",
    "profit_factor": "Hệ số lợi nhuận",
    "trades": "Số lệnh",
    "total_return": "Lợi nhuận tổng",
    "net_profit": "Lãi ròng",
    "expectancy": "Kỳ vọng/lệnh",
    "volatility": "Biến động",
    "exposure": "Thời gian nắm giữ",
}


def status_badge(state: str) -> str:
    """Return an emoji-prefixed status label."""
    return f"{STATE_COLORS.get(str(state).upper(), '⚪')} {state}"


def kpi_row(items: Sequence[Dict[str, Any]], columns: Optional[int] = None) -> None:
    """Render a row of Streamlit metrics.

    Args:
        items: Dicts with ``label``, ``value`` and optional ``delta``/``help``.
        columns: Number of columns; defaults to ``len(items)``.
    """
    if not items:
        return
    layout = st.columns(columns or len(items))
    for column, item in zip(layout, items):
        column.metric(
            label=str(item.get("label", "")),
            value=item.get("value", "-"),
            delta=item.get("delta"),
            help=item.get("help"),
        )


def metrics_table(metrics: Mapping[str, Any], keys: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Return a two-column table of translated metric labels and values."""
    selected = keys or list(METRIC_LABELS_VI)
    rows: List[Dict[str, Any]] = []
    for key in selected:
        if key not in metrics:
            continue
        value = metrics[key]
        if isinstance(value, float):
            if key in ("win_rate", "max_drawdown", "total_return", "exposure"):
                rendered = f"{value:.2%}"
            else:
                rendered = f"{value:,.3f}"
        else:
            rendered = str(value)
        rows.append({"Chỉ số": METRIC_LABELS_VI.get(key, key), "Giá trị": rendered})
    return pd.DataFrame(rows)


def render_alert_list(alerts: Sequence[Mapping[str, Any]], limit: int = 10) -> None:
    """Render risk alerts with severity-appropriate styling."""
    if not alerts:
        st.success("Không có cảnh báo rủi ro nào.")
        return
    for alert in list(alerts)[-limit:][::-1]:
        level = str(alert.get("level", "INFO")).upper()
        reason = alert.get("reason", "")
        timestamp = str(alert.get("timestamp", ""))[:19].replace("T", " ")
        text = f"**{status_badge(level)}** · {timestamp} · {reason}"
        if level == "CRITICAL":
            st.error(text)
        elif level == "WARNING":
            st.warning(text)
        else:
            st.info(text)


def format_currency(value: Any, currency: str = "USD") -> str:
    """Format a number as an account-currency amount."""
    try:
        return f"{float(value):,.2f} {currency}"
    except (TypeError, ValueError):
        return "-"


def format_percent(value: Any, digits: int = 2) -> str:
    """Format a fraction as a percentage."""
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def positions_frame(positions: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Return a Vietnamese-labelled table of open positions."""
    if not positions:
        return pd.DataFrame()
    frame = pd.DataFrame(list(positions))
    columns = {
        "symbol": "Cặp",
        "side": "Hướng",
        "volume": "Khối lượng",
        "open_price": "Giá mở",
        "current_price": "Giá hiện tại",
        "sl": "Cắt lỗ",
        "tp": "Chốt lời",
        "net_profit": "Lãi/Lỗ",
        "opened_at": "Thời gian mở",
    }
    available = [key for key in columns if key in frame.columns]
    renamed = frame[available].rename(columns=columns)
    if "Thời gian mở" in renamed:
        renamed["Thời gian mở"] = renamed["Thời gian mở"].astype(str).str[:19].str.replace("T", " ")
    return renamed


def trades_frame(trades: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Return a Vietnamese-labelled table of closed trades."""
    if not trades:
        return pd.DataFrame()
    frame = pd.DataFrame(list(trades))
    columns = {
        "symbol": "Cặp",
        "side": "Hướng",
        "volume": "Khối lượng",
        "open_price": "Giá mở",
        "close_price": "Giá đóng",
        "net_profit": "Lãi/Lỗ",
        "close_reason": "Lý do đóng",
        "closed_at": "Thời gian đóng",
    }
    available = [key for key in columns if key in frame.columns]
    renamed = frame[available].rename(columns=columns)
    if "Thời gian đóng" in renamed:
        renamed["Thời gian đóng"] = renamed["Thời gian đóng"].astype(str).str[:19].str.replace("T", " ")
    return renamed


def connection_banner(online: bool, api_url: str, error: str = "") -> None:
    """Show a persistent banner describing API connectivity."""
    if online:
        st.caption(f"🟢 Đã kết nối API · {api_url}")
    else:
        st.error(
            f"🔴 Không kết nối được API tại {api_url}. "
            f"Hãy chạy `docker-compose up -d` hoặc `uvicorn api.main:app`. {error}"
        )
