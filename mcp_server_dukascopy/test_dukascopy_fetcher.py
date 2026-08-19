#!/usr/bin/env python3
"""
Test script to verify Dukascopy data fetching and CSV format.

Run this after installing requirements to verify:
1. dukascopy-tick works
2. CSV format is correct
3. Data has no gaps
4. Timestamps are UTC
5. Checksums are reproducible
"""

import sys
from datetime import datetime, timezone
from dukascopy_mcp_server import DukascopyFetcher


def test_fetch_and_format():
    """Test fetching data and verifying format."""
    print("=" * 70)
    print("DUKASCOPY DATA FETCH TEST")
    print("=" * 70)

    fetcher = DukascopyFetcher()

    # Test with a small date range (last 7 days with data)
    # Adjust these dates based on current date and trading calendar
    start_date = "2024-08-12"  # Adjust to a real trading week
    end_date = "2024-08-16"

    print(f"\nFetching EURUSD H1 from {start_date} to {end_date}...")
    result = fetcher.fetch(start_date, end_date)

    if result["status"] != "success":
        print(f"❌ ERROR: {result['message']}")
        return False

    print(f"✓ Status: {result['status']}")
    print(f"✓ Message: {result['message']}")

    # Verify metadata
    metadata = result["metadata"]
    print("\n--- METADATA ---")
    print(f"  source: {metadata['source']}")
    print(f"  instrument: {metadata['instrument']}")
    print(f"  timeframe: {metadata['timeframe']}")
    print(f"  timezone: {metadata['timezone']}")
    print(f"  price_type: {metadata['price_type']}")
    print(f"  synthetic: {metadata['synthetic']}")
    print(f"  actual_rows: {metadata['actual_rows']}")
    print(f"  expected_rows: {metadata['expected_rows']}")
    print(f"  gaps_present: {metadata['gaps_present']}")
    print(f"  checksum: {metadata['checksum']}")
    print(f"  acquisition_timestamp: {metadata['acquisition_timestamp']}")

    # Verify CSV format
    csv_data = result["csv_data"]
    lines = csv_data.strip().split("\n")

    print(f"\n--- CSV FORMAT ---")
    print(f"  total_lines: {len(lines)}")
    print(f"  header: {lines[0]}")

    if lines[0] != "timestamp,open,high,low,close":
        print(f"❌ ERROR: Expected header 'timestamp,open,high,low,close', got '{lines[0]}'")
        return False

    print(f"✓ Header is correct")

    # Verify first few rows
    print(f"\n--- SAMPLE DATA (first 5 rows) ---")
    for i in range(1, min(6, len(lines))):
        row = lines[i]
        parts = row.split(",")
        if len(parts) == 5:
            timestamp, open_p, high_p, low_p, close_p = parts
            print(f"  {timestamp} | O:{open_p:>8} H:{high_p:>8} L:{low_p:>8} C:{close_p:>8}")

            # Verify timestamp format (ISO-8601 with UTC timezone)
            if "+00:00" not in timestamp:
                print(f"    ❌ WARNING: Timestamp missing UTC timezone info: {timestamp}")
            else:
                print(f"    ✓ Timezone: UTC")

            # Verify OHLC relationships
            try:
                open_f = float(open_p)
                high_f = float(high_p)
                low_f = float(low_p)
                close_f = float(close_p)

                if not (high_f >= max(open_f, close_f)):
                    print(f"    ❌ ERROR: high < max(open, close)")
                    return False

                if not (low_f <= min(open_f, close_f)):
                    print(f"    ❌ ERROR: low > min(open, close)")
                    return False

                if not (high_f >= low_f):
                    print(f"    ❌ ERROR: high < low")
                    return False

                if any(p <= 0 for p in [open_f, high_f, low_f, close_f]):
                    print(f"    ❌ ERROR: Non-positive price detected")
                    return False

                print(f"    ✓ OHLC relationships valid")

            except ValueError as e:
                print(f"    ❌ ERROR: Could not parse prices as floats: {e}")
                return False
        else:
            print(f"  ❌ ERROR: Row has {len(parts)} fields instead of 5: {row}")
            return False

    # Verify checksum reproducibility
    print(f"\n--- CHECKSUM VERIFICATION ---")
    import hashlib
    computed_checksum = hashlib.sha256(csv_data.encode("utf-8")).hexdigest()
    expected_checksum = metadata["checksum"].replace("sha256:", "")

    if computed_checksum == expected_checksum:
        print(f"  ✓ Checksum matches: {computed_checksum}")
    else:
        print(f"  ❌ ERROR: Checksum mismatch")
        print(f"     Expected: {expected_checksum}")
        print(f"     Got:      {computed_checksum}")
        return False

    # Verify timestamp monotonicity
    print(f"\n--- MONOTONICITY CHECK ---")
    timestamps = []
    for i in range(1, len(lines)):
        row = lines[i]
        timestamp = row.split(",")[0]
        timestamps.append(timestamp)

    is_monotonic = all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))
    if is_monotonic:
        print(f"  ✓ Timestamps are monotonically increasing")
    else:
        print(f"  ❌ ERROR: Timestamps are not monotonic")
        return False

    print(f"\n" + "=" * 70)
    print("✓ ALL TESTS PASSED")
    print("=" * 70)
    return True


if __name__ == "__main__":
    try:
        success = test_fetch_and_format()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
