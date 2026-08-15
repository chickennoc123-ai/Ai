"""Dashboard overview page: portfolio, positions and market snapshot."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.charts import equity_curve_chart, pnl_distribution_chart
from dashboard.components.metrics import (
    format_currency,
    kpi_row,
    positions_frame,
    status_badge,
    trades_frame,
)


def render(client: APIClient) -> None:
    """Render the overview page."""
    st.title("📊 Tổng quan hệ thống")

    account: Dict[str, Any] = client.account()
    summary: Dict[str, Any] = client.position_summary()
    metrics: Dict[str, Any] = client.metrics()

    if not account:
        st.warning("Chưa lấy được thông tin tài khoản từ API.")
        return

    balance = float(account.get("balance", 0.0))
    equity = float(account.get("equity", 0.0))
    floating = float(summary.get("floating_pnl", 0.0))
    currency = str(account.get("currency", "USD"))

    kpi_row(
        [
            {"label": "Số dư", "value": format_currency(balance, currency)},
            {
                "label": "Vốn thực (Equity)",
                "value": format_currency(equity, currency),
                "delta": f"{equity - balance:+,.2f}",
            },
            {"label": "Lãi/lỗ đang mở", "value": format_currency(floating, currency)},
            {"label": "Ký quỹ đã dùng", "value": format_currency(account.get("margin", 0.0), currency)},
            {"label": "Ký quỹ khả dụng", "value": format_currency(account.get("free_margin", 0.0), currency)},
        ]
    )

    trading = metrics.get("trading", {})
    agents = metrics.get("agents", {})
    running_agents = sum(1 for item in agents.values() if item.get("status") == "RUNNING")
    kpi_row(
        [
            {"label": "Vị thế đang mở", "value": summary.get("open_positions", 0)},
            {"label": "Lệnh đã khớp", "value": trading.get("executions", 0)},
            {"label": "Lệnh bị từ chối", "value": trading.get("rejections", 0)},
            {"label": "Tác nhân hoạt động", "value": f"{running_agents}/{len(agents) or 5}"},
            {
                "label": "Trạng thái thực thi",
                "value": "TẠM DỪNG" if trading.get("halted") else "BÌNH THƯỜNG",
            },
        ]
    )

    st.divider()
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Đường vốn (từ lịch sử lệnh đã đóng)")
        history: List[Dict[str, Any]] = client.position_history(days=90)
        if history:
            ordered = sorted(history, key=lambda item: str(item.get("closed_at") or ""))
            initial = balance - sum(float(item.get("net_profit", 0.0)) for item in ordered)
            curve, timestamps, running = [], [], initial
            for item in ordered:
                running += float(item.get("net_profit", 0.0))
                curve.append(running)
                timestamps.append(item.get("closed_at"))
            st.plotly_chart(
                equity_curve_chart(timestamps, curve, "Vốn tích luỹ theo lệnh đã đóng"),
                use_container_width=True,
            )
        else:
            st.info("Chưa có lệnh nào được đóng. Đường vốn sẽ xuất hiện sau giao dịch đầu tiên.")

    with right:
        st.subheader("Thị trường")
        snapshot = client.snapshot()
        if snapshot:
            frame = pd.DataFrame(snapshot).rename(
                columns={
                    "symbol": "Cặp",
                    "price": "Giá",
                    "change": "Thay đổi",
                    "change_pct": "% Thay đổi",
                    "spread_pips": "Spread (pip)",
                }
            )
            st.dataframe(
                frame[["Cặp", "Giá", "Thay đổi", "% Thay đổi", "Spread (pip)"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Chưa có dữ liệu thị trường.")

        st.subheader("Tình trạng tác nhân")
        for name, item in agents.items():
            st.write(
                f"{status_badge(item.get('status', 'UNKNOWN'))} **{name}** · "
                f"{item.get('cycles', 0)} chu kỳ · {item.get('errors', 0)} lỗi"
            )

    st.divider()
    st.subheader("Vị thế đang mở")
    positions = client.positions()
    frame = positions_frame(positions)
    if frame.empty:
        st.info("Không có vị thế nào đang mở.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)
        selected = st.selectbox(
            "Chọn vị thế để đóng",
            options=[item["position_id"] for item in positions],
            format_func=lambda value: next(
                (f"{item['symbol']} {item['side']} {item['volume']}" for item in positions if item["position_id"] == value),
                value,
            ),
        )
        close_one, close_all = st.columns(2)
        if close_one.button("Đóng vị thế đã chọn", use_container_width=True):
            client.close_position(selected)
            st.rerun()
        if close_all.button("⚠️ Đóng tất cả vị thế", type="primary", use_container_width=True):
            client.close_all()
            st.rerun()

    st.divider()
    st.subheader("Lệnh đã đóng gần đây")
    history = client.position_history(days=30)
    closed = trades_frame(history[:25])
    if closed.empty:
        st.info("Chưa có lịch sử giao dịch.")
    else:
        st.dataframe(closed, use_container_width=True, hide_index=True)
        st.plotly_chart(
            pnl_distribution_chart([float(item.get("net_profit", 0.0)) for item in history]),
            use_container_width=True,
        )
