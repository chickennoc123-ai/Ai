"""Plotly chart builders shared by the dashboard pages.

The colour system is deliberately small and consistent: one accent per
semantic role (gain, loss, neutral, accent), applied identically across every
chart so the pages read as one product.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

COLORS = {
    "gain": "#26a69a",
    "loss": "#ef5350",
    "accent": "#42a5f5",
    "muted": "#78909c",
    "warning": "#ffa726",
    "grid": "rgba(128,128,128,0.18)",
}

BASE_LAYOUT: Dict[str, Any] = {
    "template": "plotly_dark",
    "margin": {"l": 40, "r": 20, "t": 40, "b": 30},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "hovermode": "x unified",
    "font": {"size": 12},
}


def _apply_layout(figure: go.Figure, title: str = "", height: int = 420) -> go.Figure:
    """Apply the shared layout to a figure."""
    figure.update_layout(**BASE_LAYOUT, title=title, height=height)
    figure.update_xaxes(gridcolor=COLORS["grid"], showspikes=True, spikethickness=1)
    figure.update_yaxes(gridcolor=COLORS["grid"])
    return figure


def candlestick_chart(
    candles: Sequence[Mapping[str, Any]],
    indicators: Optional[Mapping[str, Sequence[Optional[float]]]] = None,
    title: str = "",
    overlay_keys: Sequence[str] = ("sma_fast", "sma_slow", "ema_fast", "ema_slow", "bb_upper", "bb_middle", "bb_lower"),
    subplot_keys: Sequence[str] = ("rsi", "macd", "macd_signal", "adx", "atr"),
) -> go.Figure:
    """Build a candlestick chart with price overlays and an indicator pane.

    Args:
        candles: Sequence of OHLCV dictionaries with an ISO ``timestamp``.
        indicators: Mapping of indicator name to aligned value list.
        title: Chart title.
        overlay_keys: Indicators drawn on the price axis.
        subplot_keys: Indicators drawn in the lower pane.
    """
    frame = pd.DataFrame(list(candles))
    if frame.empty:
        return _apply_layout(go.Figure(), title or "Không có dữ liệu")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])

    available_subplots = [key for key in subplot_keys if indicators and key in indicators]
    rows = 2 if available_subplots else 1
    figure = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28] if rows == 2 else [1.0],
    )

    figure.add_trace(
        go.Candlestick(
            x=frame["timestamp"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="Giá",
            increasing_line_color=COLORS["gain"],
            decreasing_line_color=COLORS["loss"],
        ),
        row=1,
        col=1,
    )

    palette = [COLORS["accent"], COLORS["warning"], COLORS["muted"], "#ab47bc", "#66bb6a"]
    for index, key in enumerate(overlay_keys):
        if not indicators or key not in indicators:
            continue
        figure.add_trace(
            go.Scatter(
                x=frame["timestamp"],
                y=list(indicators[key])[: len(frame)],
                name=key,
                mode="lines",
                line={"width": 1.4, "color": palette[index % len(palette)]},
            ),
            row=1,
            col=1,
        )

    for index, key in enumerate(available_subplots):
        figure.add_trace(
            go.Scatter(
                x=frame["timestamp"],
                y=list(indicators[key])[: len(frame)],
                name=key,
                mode="lines",
                line={"width": 1.4, "color": palette[index % len(palette)]},
            ),
            row=2,
            col=1,
        )
    if "rsi" in available_subplots:
        for level, dash in ((70, "dot"), (30, "dot")):
            figure.add_hline(y=level, line_dash=dash, line_color=COLORS["muted"], row=2, col=1)

    figure.update_layout(xaxis_rangeslider_visible=False)
    return _apply_layout(figure, title, height=560 if rows == 2 else 420)


def equity_curve_chart(
    timestamps: Sequence[Any], values: Sequence[float], title: str = "Đường vốn", benchmark: Optional[Sequence[float]] = None
) -> go.Figure:
    """Plot an equity curve, optionally against a benchmark."""
    figure = go.Figure()
    if not values:
        return _apply_layout(figure, "Chưa có dữ liệu vốn")
    index = pd.to_datetime(pd.Series(list(timestamps))) if timestamps else list(range(len(values)))
    figure.add_trace(
        go.Scatter(
            x=index,
            y=list(values),
            name="Vốn",
            mode="lines",
            line={"color": COLORS["accent"], "width": 2},
            fill="tozeroy",
            fillcolor="rgba(66,165,245,0.10)",
        )
    )
    if benchmark is not None:
        figure.add_trace(
            go.Scatter(
                x=index,
                y=list(benchmark),
                name="Tham chiếu",
                mode="lines",
                line={"color": COLORS["muted"], "width": 1.4, "dash": "dash"},
            )
        )
    return _apply_layout(figure, title)


def drawdown_chart(timestamps: Sequence[Any], values: Sequence[float], title: str = "Sụt giảm vốn") -> go.Figure:
    """Plot the drawdown profile of an equity curve."""
    figure = go.Figure()
    series = pd.Series(list(values), dtype="float64")
    if series.empty:
        return _apply_layout(figure, "Chưa có dữ liệu")
    running_max = series.cummax().replace(0, pd.NA)
    drawdown = ((series - running_max) / running_max * 100.0).fillna(0.0)
    index = pd.to_datetime(pd.Series(list(timestamps))) if timestamps else list(range(len(values)))
    figure.add_trace(
        go.Scatter(
            x=index,
            y=drawdown,
            name="Drawdown %",
            mode="lines",
            line={"color": COLORS["loss"], "width": 1.5},
            fill="tozeroy",
            fillcolor="rgba(239,83,80,0.20)",
        )
    )
    return _apply_layout(figure, title, height=280)


def pnl_distribution_chart(pnls: Sequence[float], title: str = "Phân bố lãi/lỗ") -> go.Figure:
    """Histogram of trade P&L split by sign."""
    figure = go.Figure()
    values = [float(value) for value in pnls]
    if not values:
        return _apply_layout(figure, "Chưa có giao dịch")
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    figure.add_trace(go.Histogram(x=wins, name="Lãi", marker_color=COLORS["gain"], nbinsx=30))
    figure.add_trace(go.Histogram(x=losses, name="Lỗ", marker_color=COLORS["loss"], nbinsx=30))
    figure.update_layout(barmode="overlay")
    figure.update_traces(opacity=0.75)
    return _apply_layout(figure, title, height=320)


def gauge_chart(value: float, title: str, maximum: float = 1.0, threshold: Optional[float] = None) -> go.Figure:
    """Render a single-value gauge, coloured by distance to the threshold."""
    limit = threshold if threshold is not None else maximum * 0.8
    colour = COLORS["gain"] if value < limit * 0.6 else COLORS["warning"] if value < limit else COLORS["loss"]
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(value),
            title={"text": title, "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, maximum]},
                "bar": {"color": colour},
                "steps": [
                    {"range": [0, limit * 0.6], "color": "rgba(38,166,154,0.15)"},
                    {"range": [limit * 0.6, limit], "color": "rgba(255,167,38,0.15)"},
                    {"range": [limit, maximum], "color": "rgba(239,83,80,0.15)"},
                ],
                "threshold": {"line": {"color": COLORS["loss"], "width": 3}, "value": limit},
            },
        )
    )
    figure.update_layout(**BASE_LAYOUT, height=240)
    return figure


def correlation_heatmap(matrix: pd.DataFrame, title: str = "Tương quan") -> go.Figure:
    """Render a correlation matrix as a heat map."""
    if matrix.empty:
        return _apply_layout(go.Figure(), "Chưa đủ dữ liệu")
    figure = go.Figure(
        go.Heatmap(
            z=matrix.to_numpy(),
            x=list(matrix.columns),
            y=list(matrix.index),
            colorscale="RdBu",
            zmid=0,
            zmin=-1,
            zmax=1,
            colorbar={"title": "ρ"},
        )
    )
    return _apply_layout(figure, title, height=380)


def bar_comparison(labels: Sequence[str], values: Sequence[float], title: str, positive_is_good: bool = True) -> go.Figure:
    """Horizontal bar chart used for strategy comparisons."""
    colours = [
        (COLORS["gain"] if (value >= 0) == positive_is_good else COLORS["loss"]) for value in values
    ]
    figure = go.Figure(
        go.Bar(x=list(values), y=list(labels), orientation="h", marker_color=colours)
    )
    return _apply_layout(figure, title, height=max(280, 28 * len(labels) + 90))
