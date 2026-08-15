"""EA Factory Pro - Streamlit dashboard entry point.

Run with::

    streamlit run dashboard/app.py

The app talks to the FastAPI backend over HTTP; it holds no trading state of
its own, so it can be restarted at any time without affecting the platform.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import streamlit as st

# Allow `streamlit run dashboard/app.py` from the repository root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.api_client import APIClient  # noqa: E402
from dashboard.views import (  # noqa: E402
    market_analysis,
    meta_research,
    overview,
    risk_monitor,
    settings,
    strategy_manager,
)
from utils.config import get_config  # noqa: E402

PAGES: List[Dict[str, Any]] = [
    {"key": "overview", "title": "Tổng quan", "icon": "📊", "render": overview.render},
    {"key": "market", "title": "Phân tích thị trường", "icon": "📈", "render": market_analysis.render},
    {"key": "strategies", "title": "Quản lý chiến lược", "icon": "🧠", "render": strategy_manager.render},
    {"key": "risk", "title": "Giám sát rủi ro", "icon": "🛡️", "render": risk_monitor.render},
    {"key": "meta", "title": "Nghiên cứu & Kiểm định", "icon": "🔬", "render": meta_research.render},
    {"key": "settings", "title": "Cấu hình", "icon": "⚙️", "render": settings.render},
]


@st.cache_resource
def get_client(api_url: str) -> APIClient:
    """Return a cached API client bound to ``api_url``."""
    return APIClient(api_url)


def render_sidebar(client: APIClient, config: Any) -> None:
    """Render the shared sidebar (status, refresh controls, quick actions)."""
    with st.sidebar:
        st.title("EA Factory Pro")
        st.caption(f"Phiên bản {config.get('system.version', '1.0.0')}")

        health = client.health()
        if health:
            broker = health.get("broker", {})
            mode = broker.get("mode", "-")
            st.success(f"🟢 API hoạt động · chế độ **{mode}**")
            if broker.get("demo"):
                st.caption("Tài khoản DEMO — không dùng tiền thật")
            else:
                st.warning("⚠️ TÀI KHOẢN THẬT")
            agents = health.get("agents", {}).get("agents", {})
            running = sum(1 for item in agents.values() if item.get("status") == "RUNNING")
            st.caption(f"Tác nhân đang chạy: {running}/{len(agents) or 0}")
        else:
            st.error("🔴 Mất kết nối API")
            st.caption(client.base_url)

        st.divider()
        auto_refresh = st.checkbox("Tự động làm mới", value=False)
        interval = st.slider("Chu kỳ làm mới (giây)", 2, 60, int(config.get_int("dashboard.refresh_interval", 5)))
        if st.button("🔄 Làm mới ngay", use_container_width=True):
            st.rerun()

        st.divider()
        st.caption("Hành động nhanh")
        if st.button("⛔ Dừng giao dịch", use_container_width=True):
            client.send_command("halt", target="execution", reason="Dừng từ sidebar")
            st.toast("Đã gửi lệnh dừng giao dịch")
        if st.button("▶️ Tiếp tục giao dịch", use_container_width=True):
            client.send_command("resume", target="execution")
            st.toast("Đã gửi lệnh tiếp tục")

        if auto_refresh:
            _schedule_refresh(interval)


def _schedule_refresh(interval: int) -> None:
    """Trigger a rerun after ``interval`` seconds."""
    fragment = getattr(st, "autorefresh", None)
    if callable(fragment):  # pragma: no cover - depends on the Streamlit build
        fragment(interval=interval * 1000, key="auto-refresh")
        return
    import time

    time.sleep(interval)
    st.rerun()


def main() -> None:
    """Configure the page and dispatch to the selected view."""
    config = get_config()
    st.set_page_config(
        page_title=str(config.get("system.name", "EA Factory Pro")),
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    client = get_client(str(config.get("dashboard.api_url", "http://localhost:8000")))
    render_sidebar(client, config)

    navigation = getattr(st, "navigation", None)
    page_factory = getattr(st, "Page", None)
    if callable(navigation) and callable(page_factory):
        # The default page is always served from "/", so declaring a url_path
        # for it would make that path 404.
        pages = [
            page_factory(
                functools.partial(item["render"], client),
                title=item["title"],
                icon=item["icon"],
                default=index == 0,
                **({} if index == 0 else {"url_path": item["key"]}),
            )
            for index, item in enumerate(PAGES)
        ]
        navigation(pages).run()
        return

    # Fallback for Streamlit builds without st.navigation.
    labels = [f"{item['icon']} {item['title']}" for item in PAGES]
    choice = st.sidebar.radio("Điều hướng", labels, index=0)
    selected = PAGES[labels.index(choice)]
    renderer: Callable[[APIClient], None] = selected["render"]
    renderer(client)


main()
