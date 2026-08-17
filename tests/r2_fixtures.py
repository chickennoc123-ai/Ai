"""Shared synthetic-data helpers for ML-001-R2 implementation tests.

IMPORTANT: the OHLCV series generated here is a deterministic synthetic
random walk used ONLY to exercise code mechanics (feature math, label
alignment, model schema, backtest bookkeeping, provenance plumbing). It
is explicitly NOT real market data and MUST NOT be used, cited, or
mistaken for economic validation of ML-001-R2 — see
ML-001-R2-CLEAN-REBUILD-SPEC.md Section 6/17 (real data is a separate,
not-yet-completed procurement step) and the implementation-phase
governance boundary (no economic validation in this phase).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_ohlcv(n_bars: int, seed: int = 0, start: str = "2020-01-03", base_price: float = 1.10) -> pd.DataFrame:
    """Deterministic synthetic H1 OHLCV frame for mechanical testing only."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start=start, periods=n_bars, freq="h", tz="UTC")

    log_returns = rng.normal(loc=0.0, scale=0.0006, size=n_bars)
    close = base_price * np.exp(np.cumsum(log_returns))

    open_ = np.empty(n_bars)
    open_[0] = base_price
    open_[1:] = close[:-1]

    intrabar_range = np.abs(rng.normal(loc=0.0004, scale=0.0002, size=n_bars))
    high = np.maximum(open_, close) + intrabar_range
    low = np.minimum(open_, close) - intrabar_range
    volume = rng.integers(low=100, high=1000, size=n_bars).astype(float)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
