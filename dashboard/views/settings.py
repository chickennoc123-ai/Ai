"""Settings page: system status, agent control and manual trading."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.metrics import kpi_row, status_badge


def render(client: APIClient) -> None:
    """Render the settings page."""
    st.title("⚙️ Cấu hình & Điều khiển")

    health: Dict[str, Any] = client.health()
    if not health:
        st.error("Không kết nối được API.")
        return

    system_tab, agents_tab, trading_tab, bus_tab = st.tabs(
        ["Hệ thống", "Tác nhân AI", "Giao dịch thủ công", "Luồng thông điệp"]
    )

    with system_tab:
        kpi_row(
            [
                {"label": "Phiên bản", "value": health.get("version", "-")},
                {"label": "Môi trường", "value": health.get("environment", "-")},
                {"label": "Thời gian chạy", "value": f"{health.get('uptime_seconds', 0):,.0f}s"},
                {"label": "Client WebSocket", "value": health.get("websocket_clients", 0)},
            ]
        )

        broker = health.get("broker", {})
        st.subheader("Kết nối sàn XMTrading")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Thuộc tính": "Chế độ", "Giá trị": broker.get("mode", "-")},
                    {"Thuộc tính": "Đã kết nối", "Giá trị": "✅" if broker.get("connected") else "❌"},
                    {"Thuộc tính": "Tài khoản", "Giá trị": broker.get("account_id", "-")},
                    {"Thuộc tính": "Máy chủ", "Giá trị": broker.get("server", "-")},
                    {"Thuộc tính": "Demo", "Giá trị": "✅" if broker.get("demo") else "❌ TÀI KHOẢN THẬT"},
                    {"Thuộc tính": "Đòn bẩy", "Giá trị": f"1:{int(broker.get('leverage', 0))}"},
                    {"Thuộc tính": "Cặp giao dịch", "Giá trị": ", ".join(broker.get("symbols", []))},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        if broker.get("mode") == "simulated":
            st.info(
                "Đang chạy ở chế độ **mô phỏng**: toàn bộ lệnh được khớp bởi engine nội bộ, "
                "không có tiền thật. Đặt `XM_MODE=rest` trong `.env` để kết nối cổng giao dịch thật."
            )

        database = health.get("database", {})
        stream = health.get("stream", {})
        st.subheader("Hạ tầng")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Thành phần": "Cơ sở dữ liệu", "Trạng thái": "🟢 " + str(database.get("dialect", "-")) if database.get("connected") else "🔴 mất kết nối"},
                    {"Thành phần": "Số bảng", "Trạng thái": database.get("tables", 0)},
                    {"Thành phần": "Tick đã nhận", "Trạng thái": stream.get("ticks_processed", 0)},
                    {"Thành phần": "Bản tin đã phát", "Trạng thái": stream.get("updates_published", 0)},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    with agents_tab:
        agents: Dict[str, Any] = client.agents().get("agents", {})
        if not agents:
            st.info("Không có tác nhân nào đang chạy.")
        else:
            frame = pd.DataFrame(
                [
                    {
                        "Tác nhân": name,
                        "Trạng thái": status_badge(item.get("status", "")),
                        "Chu kỳ (giây)": item.get("interval"),
                        "Số chu kỳ": item["metrics"]["cycles"],
                        "Tin đã xử lý": item["metrics"]["messages_processed"],
                        "Tin đã phát": item["metrics"]["messages_published"],
                        "Lỗi": item["metrics"]["errors"],
                        "Lỗi gần nhất": (item["metrics"].get("last_error") or "")[:60],
                    }
                    for name, item in agents.items()
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)

            columns = st.columns(3)
            target = columns[0].selectbox("Chọn tác nhân", list(agents))
            if columns[1].button("🔄 Khởi động lại", use_container_width=True):
                client.post(f"/api/v1/agents/{target}/restart")
                st.rerun()
            command = columns[2].text_input("Lệnh tuỳ chỉnh", value="")
            if command and st.button("Gửi lệnh"):
                client.send_command(command, target=target)
                st.success(f"Đã gửi lệnh '{command}' tới {target}.")

    with trading_tab:
        st.warning(
            "Đặt lệnh thủ công bỏ qua tín hiệu của các tác nhân nhưng vẫn chịu kiểm soát "
            "rủi ro và ký quỹ của sàn."
        )
        symbols = [item["symbol"] for item in client.symbols()] or ["XAUUSD"]
        with st.form("manual_order"):
            columns = st.columns(4)
            symbol = columns[0].selectbox("Cặp", symbols)
            direction = columns[1].selectbox("Hướng", ["BUY", "SELL"])
            volume = columns[2].number_input("Khối lượng (lot)", 0.01, 20.0, 0.01, 0.01)
            order_type = columns[3].selectbox("Loại lệnh", ["MARKET", "LIMIT", "STOP"])
            price_columns = st.columns(3)
            price = price_columns[0].number_input("Giá (chỉ cho LIMIT/STOP)", 0.0, 100000.0, 0.0)
            stop_loss = price_columns[1].number_input("Cắt lỗ", 0.0, 100000.0, 0.0)
            take_profit = price_columns[2].number_input("Chốt lời", 0.0, 100000.0, 0.0)
            submitted = st.form_submit_button("Gửi lệnh", type="primary")
        if submitted:
            payload: Dict[str, Any] = {
                "symbol": symbol,
                "direction": direction,
                "volume": float(volume),
                "order_type": order_type,
                "comment": "dashboard",
            }
            if order_type != "MARKET":
                payload["price"] = float(price)
            if stop_loss > 0:
                payload["sl"] = float(stop_loss)
            if take_profit > 0:
                payload["tp"] = float(take_profit)
            result = client.place_order(payload)
            if result:
                st.success(f"Lệnh đã gửi: {result.get('message', 'OK')}")
            else:
                st.error(f"Lệnh thất bại: {client.last_error}")

        st.subheader("Lệnh hiện tại")
        orders: List[Dict[str, Any]] = client.orders()
        if orders:
            frame = pd.DataFrame(orders)[
                ["order_id", "symbol", "side", "volume", "order_type", "status", "filled_price"]
            ].rename(
                columns={
                    "order_id": "Mã lệnh",
                    "symbol": "Cặp",
                    "side": "Hướng",
                    "volume": "Khối lượng",
                    "order_type": "Loại",
                    "status": "Trạng thái",
                    "filled_price": "Giá khớp",
                }
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có lệnh nào.")

    with bus_tab:
        st.subheader("Thông điệp gần đây giữa các tác nhân")
        messages = client.messages(limit=60)
        if messages:
            frame = pd.DataFrame(
                [
                    {
                        "Thời gian": str(item.get("timestamp", ""))[11:19],
                        "Tác nhân": item.get("agent_id"),
                        "Loại": item.get("message_type"),
                        "Nội dung": str(item.get("payload"))[:120],
                    }
                    for item in messages
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có thông điệp nào trên bus.")
