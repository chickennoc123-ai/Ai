#!/usr/bin/env python3
"""
Ingest uploaded multi-asset H1 parquet files.

Loads GBPUSD, USDCAD, USDCHF, USDJPY, XAUUSD, converts to standard CSV format,
audits coverage, and splits dev/holdout 80/20 per symbol.
"""

import sys
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.loaders.multiasset_loader import MultiAssetLoader

# Mapping of uploaded parquet paths
PARQUET_PATHS = {
    "GBPUSD": "/root/.claude/uploads/6c8e1186-ef95-5c82-acb6-24ca4a0ddc65/c2e7b3e2-GBPUSD_H1.parquet",
    "USDCAD": "/root/.claude/uploads/6c8e1186-ef95-5c82-acb6-24ca4a0ddc65/05010a66-USDCAD_H1.parquet",
    "USDCHF": "/root/.claude/uploads/6c8e1186-ef95-5c82-acb6-24ca4a0ddc65/e8e8c4d4-USDCHF_H1.parquet",
    "USDJPY": "/root/.claude/uploads/6c8e1186-ef95-5c82-acb6-24ca4a0ddc65/2049da51-USDJPY_H1.parquet",
    "XAUUSD": "/root/.claude/uploads/6c8e1186-ef95-5c82-acb6-24ca4a0ddc65/93e017c4-XAUUSD_H1.parquet",
}

def ingest():
    """Load, validate, and save all symbols."""
    loader = MultiAssetLoader(REPO_ROOT / "data")

    # Ensure CSV directory exists
    csv_dir = REPO_ROOT / "data" / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    holdout_dir = REPO_ROOT / "data" / "holdout"
    holdout_dir.mkdir(parents=True, exist_ok=True)

    audit_results = []

    print("="*80)
    print("MULTI-ASSET DATA INGESTION & SPLIT")
    print("="*80)

    for symbol, parquet_path in PARQUET_PATHS.items():
        print(f"\n📥 Loading {symbol}...", end=" ")
        try:
            bars = loader.load_from_parquet(symbol, Path(parquet_path))
            print(f"✓ ({len(bars):,} bars)")

            # Audit coverage (XAUUSD: 68% acceptable, FX: 71%+)
            min_cov = 0.68 if symbol == "XAUUSD" else 0.70
            audit = loader.audit_coverage(bars, symbol, min_coverage=min_cov)
            audit_results.append(audit)
            print(f"   Coverage: {audit['coverage']*100:.1f}% ({audit['bars']:,} / {audit['expected_hours']} hours)")

            if not audit['passed']:
                print(f"   ⚠️  WARNING: {audit['coverage']*100:.1f}% < 70% threshold")

            # Split 80/20
            dev_bars, holdout_bars = loader.split_dev_holdout(bars, dev_ratio=0.80)

            # Save to CSV (lowercase column names for observatory compatibility)
            import pandas as pd

            # Dev data
            dev_df = pd.DataFrame([
                {
                    'timestamp': bar.timestamp,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                }
                for bar in dev_bars
            ])
            dev_csv = csv_dir / f"{symbol}_H1.csv"
            dev_df.to_csv(dev_csv, index=False)
            print(f"   → Dev: {dev_csv.name} ({len(dev_df)} bars)")

            # Holdout data
            holdout_df = pd.DataFrame([
                {
                    'timestamp': bar.timestamp,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                }
                for bar in holdout_bars
            ])
            holdout_csv = holdout_dir / f"{symbol}_H1_HOLDOUT_{holdout_df['timestamp'].min().strftime('%Y%m%d')}_{holdout_df['timestamp'].max().strftime('%Y%m%d')}_UTC.csv"
            holdout_df.to_csv(holdout_csv, index=False)
            print(f"   → Holdout: {holdout_csv.name} ({len(holdout_df)} bars)")

        except Exception as e:
            print(f"✗ ERROR: {e}")
            audit_results.append({
                "symbol": symbol,
                "error": str(e),
                "passed": False
            })

    # Summary report
    print("\n" + "="*80)
    print("INGESTION SUMMARY")
    print("="*80)

    passed = [a for a in audit_results if a.get('passed', False)]
    failed = [a for a in audit_results if not a.get('passed', False)]

    print(f"\n✓ Passed: {len(passed)}/{len(audit_results)}")
    for a in passed:
        print(f"  {a['symbol']}: {a['coverage']*100:.1f}% coverage")

    if failed:
        print(f"\n✗ Failed: {len(failed)}/{len(audit_results)}")
        for a in failed:
            if 'error' in a:
                print(f"  {a['symbol']}: {a['error']}")
            else:
                print(f"  {a['symbol']}: {a['coverage']*100:.1f}% coverage < 70%")

    # Save audit to registry
    audit_path = REPO_ROOT / "reports" / "factory" / "multiasset_ingestion_audit.json"
    with open(audit_path, "w") as f:
        json.dump(audit_results, f, indent=2, default=str)
    print(f"\n📄 Audit saved to: {audit_path}")

    return len(failed) == 0

if __name__ == "__main__":
    success = ingest()
    sys.exit(0 if success else 1)
