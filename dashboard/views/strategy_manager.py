"""Strategy manager page: catalogue, configuration, backtest and lifecycle."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.charts import bar_comparison, drawdown_chart, equity_curve_chart
from dashboard.components.metrics import kpi_row, metrics_table, status_badge

TIMEFRAMES = ["M15", "M30", "H1", "H4", "D1"]


def render(client: APIClient) -> None:
    """Render the strategy manager page."""
    st.title("🧠 Quản lý chiến lược")

    payload: Dict[str, Any] = client.strategies()
    available: List[str] = payload.get("available", [])
    catalogue: List[Dict[str, Any]] = payload.get("catalogue", [])
    configured: List[Dict[str, Any]] = payload.get("configured", [])
    symbols = [item["symbol"] for item in client.symbols()] or ["XAUUSD", "EURUSD"]

    if not available:
        st.error("Không tải được danh mục chiến lược từ API.")
        return

    catalogue_tab, configure_tab, backtest_tab, lifecycle_tab = st.tabs(
        ["Danh mục", "Cấu hình", "Kiểm thử", "Vòng đời"]
    )

    with catalogue_tab:
        st.subheader(f"{len(catalogue)} chiến lược khả dụng")
        frame = pd.DataFrame(
            [
                {
                    "Tên": item["name"],
                    "Nhóm": item["category"],
                    "Mô tả": item["description"][:110],
                    "AI tạo": "✅" if item.get("generated") else "",
                    "Tham số": len(item.get("parameters", {})),
                }
                for item in catalogue
            ]
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)

        selected = st.selectbox("Xem tham số của chiến lược", available)
        space = client.get(f"/api/v1/strategies/{selected}/parameters", [])
        if space:
            st.dataframe(
                pd.DataFrame(space).rename(
                    columns={
                        "name": "Tham số",
                        "low": "Nhỏ nhất",
                        "high": "Lớn nhất",
                        "step": "Bước",
                        "integer": "Số nguyên",
                        "default": "Mặc định",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Chiến lược này không khai báo không gian tham số tối ưu.")

    with configure_tab:
        st.subheader("Thêm cấu hình chiến lược")
        with st.form("create_strategy"):
            columns = st.columns(3)
            name = columns[0].selectbox("Chiến lược", available)
            symbol = columns[1].selectbox("Cặp", symbols)
            timeframe = columns[2].selectbox("Khung", TIMEFRAMES, index=2)
            params_text = st.text_input(
                "Tham số ghi đè (JSON)", value="{}", help='Ví dụ: {"rsi_period": 21}'
            )
            submitted = st.form_submit_button("Tạo cấu hình", type="primary")
        if submitted:
            import json

            try:
                params = json.loads(params_text or "{}")
            except ValueError:
                st.error("Tham số phải là JSON hợp lệ.")
            else:
                result = client.post(
                    "/api/v1/strategies",
                    {"name": name, "symbol": symbol, "timeframe": timeframe, "params": params},
                )
                if result:
                    st.success(f"Đã tạo {result.get('strategy_id')}")
                    st.rerun()
                else:
                    st.error(f"Không tạo được: {client.last_error}")

        st.subheader("Chiến lược đã cấu hình")
        if not configured:
            st.info("Chưa có chiến lược nào được cấu hình.")
        else:
            frame = pd.DataFrame(
                [
                    {
                        "ID": item["strategy_id"],
                        "Tên": item["name"],
                        "Cặp": item["symbol"],
                        "Khung": item["timeframe"],
                        "Trạng thái": status_badge(item.get("state", "ACTIVE")),
                        "Phân bổ": f"{float(item.get('allocation', 0)):.1%}",
                        "Sharpe": round(float(item.get("metrics", {}).get("sharpe", 0)), 3),
                        "Bật": "✅" if item.get("enabled") else "⛔",
                    }
                    for item in configured
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
            target = st.selectbox("Chọn chiến lược", [item["strategy_id"] for item in configured])
            actions = st.columns(3)
            if actions[0].button("Tạm dừng", use_container_width=True):
                client.post(f"/api/v1/strategies/{target}/pause")
                st.rerun()
            if actions[1].button("Kích hoạt lại", use_container_width=True):
                client.post(f"/api/v1/strategies/{target}/resume")
                st.rerun()
            if actions[2].button("Xoá", type="secondary", use_container_width=True):
                client.delete(f"/api/v1/strategies/{target}")
                st.rerun()

    with backtest_tab:
        st.subheader("Chạy kiểm thử lịch sử")
        with st.form("run_backtest"):
            columns = st.columns(4)
            name = columns[0].selectbox("Chiến lược", available, key="bt_name")
            symbol = columns[1].selectbox("Cặp", symbols, key="bt_symbol")
            timeframe = columns[2].selectbox("Khung", TIMEFRAMES, index=2, key="bt_tf")
            bars = columns[3].number_input("Số nến", 500, 20000, 5000, 500)
            cost_columns = st.columns(3)
            capital = cost_columns[0].number_input("Vốn ban đầu", 1000.0, 1_000_000.0, 10_000.0, 1000.0)
            commission = cost_columns[1].number_input("Phí (tỷ lệ notional)", 0.0, 0.001, 0.00007, 0.00001, format="%.5f")
            risk = cost_columns[2].number_input("Rủi ro mỗi lệnh", 0.001, 0.05, 0.01, 0.001, format="%.3f")
            run = st.form_submit_button("Chạy kiểm thử", type="primary")

        if run:
            with st.spinner("Đang chạy kiểm thử..."):
                result = client.run_backtest(
                    {
                        "name": name,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "bars": int(bars),
                        "initial_capital": float(capital),
                        "commission": float(commission),
                        "risk_per_trade": float(risk),
                    }
                )
            if not result:
                st.error(f"Kiểm thử thất bại: {client.last_error}")
            else:
                st.session_state["last_backtest"] = result

        result = st.session_state.get("last_backtest")
        if result:
            metrics = result.get("metrics", {})
            kpi_row(
                [
                    {"label": "Sharpe", "value": f"{metrics.get('sharpe', 0):.2f}"},
                    {"label": "Lãi ròng", "value": f"{metrics.get('net_profit', 0):,.2f}"},
                    {"label": "Sụt giảm tối đa", "value": f"{metrics.get('max_drawdown', 0):.2%}"},
                    {"label": "Tỷ lệ thắng", "value": f"{metrics.get('win_rate', 0):.1%}"},
                    {"label": "Số lệnh", "value": metrics.get("trades", 0)},
                ]
            )
            curve = result.get("equity_curve", {})
            st.plotly_chart(
                equity_curve_chart(curve.get("timestamps", []), curve.get("values", [])),
                use_container_width=True,
            )
            st.plotly_chart(
                drawdown_chart(curve.get("timestamps", []), curve.get("values", [])),
                use_container_width=True,
            )
            st.dataframe(metrics_table(metrics), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("So sánh nhiều chiến lược")
        compare = st.multiselect("Chọn chiến lược để so sánh", available, default=available[:4])
        compare_symbols = st.multiselect("Cặp", symbols, default=symbols[:2])
        if st.button("Chạy so sánh") and compare and compare_symbols:
            with st.spinner("Đang chạy ma trận kiểm thử..."):
                rows = client.post(
                    "/api/v1/backtest/matrix",
                    {"names": compare, "symbols": compare_symbols, "timeframe": "H1", "bars": 4000},
                    [],
                )
            if rows:
                frame = pd.DataFrame(rows)
                st.dataframe(frame, use_container_width=True, hide_index=True)
                st.plotly_chart(
                    bar_comparison(
                        [f"{row['strategy']} · {row['symbol']}" for row in rows],
                        [row["sharpe"] for row in rows],
                        "Sharpe theo chiến lược",
                    ),
                    use_container_width=True,
                )

    with lifecycle_tab:
        st.subheader("Vòng đời chiến lược")
        snapshot = client.lifecycle()
        counts = snapshot.get("counts", {})
        kpi_row(
            [
                {"label": "ACTIVE", "value": counts.get("ACTIVE", 0)},
                {"label": "DEGRADED", "value": counts.get("DEGRADED", 0)},
                {"label": "PAUSED", "value": counts.get("PAUSED", 0)},
                {"label": "RETIRED", "value": counts.get("RETIRED", 0)},
            ]
        )
        strategies = snapshot.get("strategies", {})
        if strategies:
            frame = pd.DataFrame(
                [
                    {
                        "Chiến lược": key,
                        "Trạng thái": status_badge(item.get("state", "")),
                        "Số ngày": item.get("days_in_state", 0),
                        "Hệ số phân bổ": item.get("allocation_multiplier", 0),
                        "Lý do": item.get("reason", ""),
                    }
                    for key, item in strategies.items()
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có chiến lược nào được theo dõi vòng đời.")
