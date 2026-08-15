"""Market analysis page: live charts, indicators and agent market context."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.charts import candlestick_chart, correlation_heatmap
from dashboard.components.metrics import kpi_row

TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"]
INDICATOR_CHOICES = ["rsi", "macd", "bb", "sma", "ema", "atr", "adx", "stoch", "cci"]


def render(client: APIClient) -> None:
    """Render the market analysis page."""
    st.title("📈 Phân tích thị trường")

    symbols = [item["symbol"] for item in client.symbols()] or [
        "XAUUSD",
        "EURUSD",
        "USDJPY",
        "GBPUSD",
        "AUDUSD",
    ]

    controls = st.columns([2, 1, 1, 3])
    symbol = controls[0].selectbox("Cặp giao dịch", symbols, index=0)
    timeframe = controls[1].selectbox("Khung thời gian", TIMEFRAMES, index=3)
    bars = controls[2].number_input("Số nến", min_value=50, max_value=2000, value=300, step=50)
    indicators = controls[3].multiselect(
        "Chỉ báo", INDICATOR_CHOICES, default=["rsi", "bb", "atr"]
    )

    payload: Dict[str, Any] = client.market(symbol, timeframe, int(bars), ",".join(indicators))
    if not payload:
        st.error("Không tải được dữ liệu thị trường từ API.")
        return

    last_price = payload.get("last_price", 0.0)
    change = payload.get("change", 0.0)
    change_pct = payload.get("change_pct", 0.0)
    kpi_row(
        [
            {"label": "Giá hiện tại", "value": f"{last_price:,.5f}".rstrip("0").rstrip(".")},
            {"label": "Thay đổi", "value": f"{change:+,.5f}".rstrip("0").rstrip("."), "delta": f"{change_pct:+.3f}%"},
            {"label": "Số nến", "value": payload.get("bars", 0)},
            {"label": "Khung", "value": payload.get("timeframe", timeframe)},
        ]
    )

    st.plotly_chart(
        candlestick_chart(
            payload.get("candles", []),
            payload.get("indicators", {}),
            title=f"{symbol} · {timeframe}",
        ),
        use_container_width=True,
    )

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("Bối cảnh thị trường (Analysis Agent)")
        reports = client.agent_reports()
        context = (reports.get("analysis", {}) or {}).get("context", {}).get(symbol, {})
        if context:
            st.write(
                f"**Xu hướng:** {context.get('trend', '-')} · "
                f"**Chế độ thị trường:** {context.get('regime', '-')}"
            )
            kpi_row(
                [
                    {"label": "ADX", "value": context.get("adx", "-")},
                    {"label": "RSI", "value": context.get("rsi", "-")},
                    {"label": "ATR (pip)", "value": context.get("atr_pips", "-")},
                    {"label": "Tỷ lệ biến động", "value": context.get("volatility_ratio", "-")},
                ]
            )
        else:
            st.info("Analysis Agent chưa công bố bối cảnh cho cặp này.")

        st.subheader("Tín hiệu gần nhất")
        signal = (reports.get("analysis", {}) or {}).get("signals", {}).get(symbol, {})
        if signal:
            direction = signal.get("direction_label", "FLAT")
            icon = {"BUY": "🟢", "SELL": "🔴"}.get(direction, "⚪")
            st.write(
                f"{icon} **{direction}** · độ tin cậy {float(signal.get('confidence', 0)):.0%} · "
                f"đồng thuận {float(signal.get('agreement', 0)):.0%}"
            )
            contributors = signal.get("contributors", [])
            if contributors:
                frame = pd.DataFrame(contributors)[["strategy", "direction", "confidence"]].rename(
                    columns={"strategy": "Chiến lược", "direction": "Hướng", "confidence": "Độ tin cậy"}
                )
                st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có tín hiệu nào được tạo.")

    with right:
        st.subheader("Tương quan giữa các cặp")
        closes: Dict[str, List[float]] = {}
        for item in symbols:
            data = client.market(item, timeframe, 200)
            candles = data.get("candles", [])
            if candles:
                closes[item] = [float(candle["close"]) for candle in candles]
        if len(closes) >= 2:
            length = min(len(values) for values in closes.values())
            frame = pd.DataFrame({key: values[-length:] for key, values in closes.items()}).pct_change().dropna()
            st.plotly_chart(correlation_heatmap(frame.corr()), use_container_width=True)
        else:
            st.info("Cần ít nhất hai cặp có dữ liệu để tính tương quan.")

        st.subheader("Bảng giá")
        snapshot = client.snapshot(timeframe)
        if snapshot:
            frame = pd.DataFrame(snapshot).rename(
                columns={
                    "symbol": "Cặp",
                    "price": "Giá",
                    "change_pct": "% Thay đổi",
                    "high": "Đỉnh",
                    "low": "Đáy",
                }
            )
            st.dataframe(
                frame[["Cặp", "Giá", "% Thay đổi", "Đỉnh", "Đáy"]],
                use_container_width=True,
                hide_index=True,
            )
