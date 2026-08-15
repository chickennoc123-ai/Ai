"""Risk monitor page: limits, VaR/CVaR, drawdown and alerts."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.charts import bar_comparison, drawdown_chart, equity_curve_chart, gauge_chart
from dashboard.components.metrics import format_percent, kpi_row, render_alert_list


def render(client: APIClient) -> None:
    """Render the risk monitor page."""
    st.title("🛡️ Giám sát rủi ro")

    reports = client.agent_reports()
    risk: Dict[str, Any] = reports.get("risk", {}) or {}
    metrics: Dict[str, Any] = risk.get("metrics", {}) or {}
    limits: Dict[str, Any] = risk.get("limits", {}) or {}

    if not metrics:
        st.warning("Risk Agent chưa công bố số liệu. Hãy đảm bảo worker/API đang chạy.")
        return

    halted = bool(risk.get("halted"))
    if halted:
        st.error("🚨 Hệ thống đang TẠM DỪNG giao dịch do vi phạm giới hạn rủi ro.")
    else:
        st.success("✅ Mọi giới hạn rủi ro đang trong ngưỡng cho phép.")

    kpi_row(
        [
            {"label": "Vốn thực", "value": f"{metrics.get('equity', 0):,.2f}"},
            {"label": "Đỉnh vốn", "value": f"{metrics.get('peak_equity', 0):,.2f}"},
            {"label": "Sụt giảm hiện tại", "value": format_percent(metrics.get("drawdown", 0))},
            {"label": "Lãi/lỗ đang mở", "value": f"{metrics.get('floating_pnl', 0):,.2f}"},
            {"label": "Mức ký quỹ", "value": f"{metrics.get('margin_level', 0):,.0f}%"},
        ]
    )

    st.divider()
    gauges = st.columns(3)
    gauges[0].plotly_chart(
        gauge_chart(
            float(metrics.get("drawdown", 0.0)),
            "Sụt giảm / Giới hạn",
            maximum=max(float(limits.get("kill_switch_drawdown", 0.25)), 0.3),
            threshold=float(limits.get("max_drawdown", 0.15)),
        ),
        use_container_width=True,
    )
    gauges[1].plotly_chart(
        gauge_chart(
            float(metrics.get("var", 0.0)),
            "VaR 1 ngày",
            maximum=max(float(limits.get("max_var", 0.02)) * 2, 0.04),
            threshold=float(limits.get("max_var", 0.02)),
        ),
        use_container_width=True,
    )
    gauges[2].plotly_chart(
        gauge_chart(
            float(metrics.get("exposure", 0.0)),
            "Tổng mức tiếp xúc",
            maximum=max(float(limits.get("max_exposure", 0.5)) * 2, 1.0),
            threshold=float(limits.get("max_exposure", 0.5)),
        ),
        use_container_width=True,
    )

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Diễn biến vốn theo thời gian thực")
        history: List[Dict[str, Any]] = risk.get("equity_history", [])
        if history:
            timestamps = [item["timestamp"] for item in history]
            values = [item["equity"] for item in history]
            st.plotly_chart(equity_curve_chart(timestamps, values, "Vốn thực"), use_container_width=True)
            st.plotly_chart(drawdown_chart(timestamps, values), use_container_width=True)
        else:
            st.info("Chưa có đủ mẫu vốn.")

    with right:
        st.subheader("Chỉ số rủi ro chi tiết")
        rows = [
            ("VaR lịch sử", format_percent(metrics.get("historical_var", 0))),
            ("VaR Monte-Carlo", format_percent(metrics.get("monte_carlo_var", 0))),
            ("CVaR (tổn thất kỳ vọng)", format_percent(metrics.get("cvar", 0))),
            ("Tổng notional", f"{metrics.get('gross_notional', 0):,.0f}"),
            ("Số vị thế mở", metrics.get("open_positions", 0)),
            ("Số mẫu vốn", metrics.get("samples", 0)),
        ]
        st.dataframe(
            pd.DataFrame(rows, columns=["Chỉ số", "Giá trị"]),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Giới hạn cấu hình")
        st.dataframe(
            pd.DataFrame(
                [{"Giới hạn": key, "Ngưỡng": value} for key, value in limits.items()]
            ),
            use_container_width=True,
            hide_index=True,
        )

    exposure = metrics.get("exposure_by_symbol", {})
    if exposure:
        st.subheader("Mức tiếp xúc theo cặp")
        st.plotly_chart(
            bar_comparison(
                list(exposure.keys()),
                list(exposure.values()),
                "Tỷ lệ notional / vốn",
                positive_is_good=False,
            ),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Lịch sử cảnh báo")
    render_alert_list(risk.get("alerts", []), limit=15)

    st.divider()
    st.subheader("Điều khiển khẩn cấp")
    controls = st.columns(3)
    if controls[0].button("⛔ Tạm dừng giao dịch", use_container_width=True):
        client.send_command("halt", target="execution", reason="Tạm dừng từ bảng điều khiển")
        st.rerun()
    if controls[1].button("▶️ Tiếp tục giao dịch", use_container_width=True):
        client.send_command("resume", target="execution")
        st.rerun()
    if controls[2].button("🔴 Đóng toàn bộ vị thế", type="primary", use_container_width=True):
        client.close_all("DASHBOARD_EMERGENCY")
        st.rerun()
