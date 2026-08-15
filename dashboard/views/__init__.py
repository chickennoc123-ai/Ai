"""Dashboard views. Each module exposes ``render(client)``.

The package is called ``views`` rather than ``pages`` on purpose: Streamlit
treats a ``pages/`` directory sitting next to the entry point as its own
file-based navigation and serves those modules directly, bypassing
``dashboard/app.py`` (which would render blank screens, since the modules only
define functions). Routing is owned by ``st.navigation`` in ``app.py``.
"""

from dashboard.views import (
    market_analysis,
    meta_research,
    overview,
    risk_monitor,
    settings,
    strategy_manager,
)

__all__ = [
    "market_analysis",
    "meta_research",
    "overview",
    "risk_monitor",
    "settings",
    "strategy_manager",
]
