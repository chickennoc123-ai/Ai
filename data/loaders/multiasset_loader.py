"""
Unified data loader for multi-asset H1 bars.

Handles: EURUSD (from dev CSV), GBPUSD/USDCAD/USDCHF/USDJPY/XAUUSD (from uploaded parquet).
All converted to UTC, split 80/20 dev/holdout by symbol, with holdout firewall enforcement.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery._guards import guard_path

@dataclass
class Bar:
    """Single OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class MultiAssetLoader:
    """Load and validate H1 bars across 6 FX/commodity symbols."""

    SYMBOLS = ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]

    # Timezone metadata: HistData EST→UTC offset
    EST_TO_UTC = timedelta(hours=5)

    def __init__(self, data_dir: Path = REPO_ROOT / "data"):
        self.data_dir = Path(data_dir)
        self._cache = {}

    def load_eurusd_dev(self) -> List[Bar]:
        """Load EURUSD from CSV (original source, contains timezone fix)."""
        csv_path = guard_path(self.data_dir / "csv" / "EURUSD_H1.csv")
        df = pd.read_csv(csv_path, parse_dates=[0])
        df.columns = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
        # Already UTC from rebuild in Gen 6
        return self._to_bars(df)

    def load_from_parquet(self, symbol: str, parquet_path: Path) -> List[Bar]:
        """
        Load symbol from uploaded parquet file.
        Handles malformed headers (first row = header values).
        """
        parquet_path = guard_path(parquet_path)

        df = pd.read_parquet(parquet_path)

        # Skip first row (contains header values), use rest as data
        if len(df) > 1:
            df = df.iloc[1:].reset_index(drop=True)

        # Rename to standard columns
        new_cols = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
        df.columns = new_cols

        # Parse datetime
        df['Datetime'] = pd.to_datetime(df['Datetime'], errors='coerce')

        # Convert numeric types
        for col in ['Open', 'High', 'Low', 'Close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0).astype(int)

        # Drop NaN rows
        df = df.dropna(subset=['Datetime', 'Open', 'Close']).reset_index(drop=True)

        # Apply EST→UTC correction (HistData semantic)
        df['Datetime'] = df['Datetime'] + self.EST_TO_UTC

        # Sort and deduplicate
        df = df.sort_values('Datetime').drop_duplicates('Datetime').reset_index(drop=True)

        return self._to_bars(df)

    def _to_bars(self, df: pd.DataFrame) -> List[Bar]:
        """Convert DataFrame to Bar objects."""
        bars = []
        for _, row in df.iterrows():
            bars.append(Bar(
                timestamp=row['Datetime'],
                open=row['Open'],
                high=row['High'],
                low=row['Low'],
                close=row['Close'],
                volume=int(row['Volume'])
            ))
        return bars

    def split_dev_holdout(self, bars: List[Bar], dev_ratio: float = 0.80):
        """
        Split bars 80/20 by timestamp.

        Returns:
            (dev_bars, holdout_bars): Training and sealed evaluation sets
        """
        if not bars:
            return [], []

        split_idx = int(len(bars) * dev_ratio)
        return bars[:split_idx], bars[split_idx:]

    def audit_coverage(self, bars: List[Bar], symbol: str, min_coverage: float = 0.70):
        """
        Audit H1 coverage (expected = continuous hourly).
        Forex: markets may be closed on weekends; commodity: 24h but may have gaps.
        """
        if not bars:
            return {"symbol": symbol, "bars": 0, "coverage": 0.0, "passed": False}

        ts_min, ts_max = bars[0].timestamp, bars[-1].timestamp
        expected_hours = (ts_max - ts_min).total_seconds() / 3600
        actual_bars = len(bars)
        coverage = actual_bars / expected_hours if expected_hours > 0 else 0

        return {
            "symbol": symbol,
            "period": f"{ts_min} to {ts_max}",
            "bars": actual_bars,
            "expected_hours": int(expected_hours),
            "coverage": coverage,
            "passed": coverage >= min_coverage,
        }
