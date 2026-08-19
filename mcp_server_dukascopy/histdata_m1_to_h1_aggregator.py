#!/usr/bin/env python3
"""
HistData M1 → H1 Aggregator

Converts HistData minute-level (M1) EURUSD data to hourly (H1) candles.
Aggregates 60 minute bars into single hourly OHLC candles, handles gaps,
and outputs ISO-8601 UTC CSV compatible with holdout_acquisition.py.

Input: HistData CSV files (format: SYMBOL,YYYYMMDDHHmm,O,H,L,C,V)
Output: CSV (timestamp, open, high, low, close) with UTC timezone
"""

import csv
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional


class HistDataM1Aggregator:
    """Aggregates HistData M1 data to H1 candles."""

    def __init__(self):
        self.hourly_candles = {}  # {timestamp_iso: {o, h, l, c}}
        self.gaps = []
        self.gaps_total = 0
        self.rows_processed = 0
        self.rows_skipped = 0

    def parse_histdata_timestamp(self, ts_str: str) -> datetime:
        """
        Parse HistData timestamp format: YYYYMMDDHHmm

        Returns UTC datetime at the top of the minute.
        """
        try:
            # Format: YYYYMMDDHHmm
            if len(ts_str) != 12:
                raise ValueError(f"Invalid timestamp length: {ts_str}")

            year = int(ts_str[0:4])
            month = int(ts_str[4:6])
            day = int(ts_str[6:8])
            hour = int(ts_str[8:10])
            minute = int(ts_str[10:12])

            # Create UTC datetime
            dt = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
            return dt

        except (ValueError, IndexError) as e:
            raise ValueError(f"Could not parse timestamp '{ts_str}': {e}")

    def timestamp_to_iso(self, dt: datetime) -> str:
        """Convert datetime to ISO-8601 UTC with timezone."""
        return dt.isoformat()

    def aggregate_hourly(self, timestamp: datetime, open_p: float, high_p: float,
                        low_p: float, close_p: float):
        """
        Add minute bar to hourly aggregation.

        Aggregates 60 minute bars (00-59 minutes) into one H1 candle.
        """
        # Get the top-of-hour for this minute bar
        hour_key = timestamp.replace(minute=0, second=0, microsecond=0)
        hour_iso = self.timestamp_to_iso(hour_key)

        if hour_iso not in self.hourly_candles:
            # First minute of the hour
            self.hourly_candles[hour_iso] = {
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "count": 1,
            }
        else:
            # Subsequent minutes in the hour
            candle = self.hourly_candles[hour_iso]
            candle["high"] = max(candle["high"], high_p)
            candle["low"] = min(candle["low"], low_p)
            candle["close"] = close_p
            candle["count"] += 1

    def load_histdata_file(self, filepath: str) -> int:
        """
        Load HistData M1 CSV file and aggregate to H1.

        Format: SYMBOL,YYYYMMDDHHmm,open,high,low,close,volume

        Returns: number of rows processed
        """
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                try:
                    if len(row) < 7:
                        self.rows_skipped += 1
                        continue

                    symbol, timestamp_str, open_str, high_str, low_str, close_str, vol_str = row[:7]

                    # Validate
                    if symbol != "EURUSD":
                        self.rows_skipped += 1
                        continue

                    # Parse timestamp and prices
                    timestamp = self.parse_histdata_timestamp(timestamp_str)
                    open_p = float(open_str)
                    high_p = float(high_str)
                    low_p = float(low_str)
                    close_p = float(close_str)

                    # Validate prices
                    if any(p <= 0 for p in [open_p, high_p, low_p, close_p]):
                        self.rows_skipped += 1
                        continue

                    if not (high_p >= max(open_p, close_p)):
                        self.rows_skipped += 1
                        continue

                    if not (low_p <= min(open_p, close_p)):
                        self.rows_skipped += 1
                        continue

                    # Aggregate to hourly
                    self.aggregate_hourly(timestamp, open_p, high_p, low_p, close_p)
                    self.rows_processed += 1
                    count += 1

                except (ValueError, IndexError) as e:
                    self.rows_skipped += 1
                    continue

        return count

    def load_all_files(self, file_list: list[str]) -> int:
        """Load and aggregate multiple HistData files."""
        total = 0
        for filepath in sorted(file_list):
            print(f"  Loading {Path(filepath).name}...", end=" ", flush=True)
            count = self.load_histdata_file(filepath)
            total += count
            print(f"({count} rows)")
        return total

    def detect_gaps(self) -> None:
        """Detect missing hours (gaps in hourly data)."""
        sorted_timestamps = sorted(self.hourly_candles.keys())

        for i in range(len(sorted_timestamps) - 1):
            current_ts = datetime.fromisoformat(sorted_timestamps[i])
            next_ts = datetime.fromisoformat(sorted_timestamps[i + 1])

            expected_next = current_ts + timedelta(hours=1)

            # Check if next hour is trading hour (Mon-Fri 0-23 UTC)
            # Note: EURUSD trades 24/5, but we expect gaps on weekends
            while expected_next <= next_ts:
                if expected_next not in [datetime.fromisoformat(ts) for ts in sorted_timestamps]:
                    # This hour is missing
                    if expected_next.weekday() < 5:  # Trading day
                        gap_hours = (next_ts - expected_next).total_seconds() / 3600
                        self.gaps.append({
                            "from": self.timestamp_to_iso(expected_next),
                            "to": self.timestamp_to_iso(next_ts),
                            "hours": gap_hours,
                        })
                        self.gaps_total += gap_hours

                expected_next += timedelta(hours=1)

    def validate_hourly_candles(self) -> tuple[int, int]:
        """Validate OHLC relationships in hourly candles."""
        valid = 0
        invalid = 0

        for timestamp_iso, candle in self.hourly_candles.items():
            o = candle["open"]
            h = candle["high"]
            l = candle["low"]
            c = candle["close"]

            # Check OHLC relationships
            if (h >= max(o, c) and l <= min(o, c) and h >= l and
                all(p > 0 for p in [o, h, l, c])):
                valid += 1
            else:
                invalid += 1
                print(f"  Invalid candle at {timestamp_iso}: O={o} H={h} L={l} C={c}")

        return valid, invalid

    def to_csv(self) -> str:
        """Export hourly candles as CSV with ISO-8601 UTC timestamps."""
        lines = ["timestamp,open,high,low,close"]

        for timestamp_iso in sorted(self.hourly_candles.keys()):
            candle = self.hourly_candles[timestamp_iso]
            lines.append(
                f"{timestamp_iso},{candle['open']},{candle['high']},"
                f"{candle['low']},{candle['close']}"
            )

        return "\n".join(lines)

    def save_csv(self, filepath: str) -> str:
        """Save hourly candles to CSV file. Returns checksum."""
        csv_content = self.to_csv()

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(csv_content)

        checksum = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()
        return checksum

    def get_stats(self) -> dict:
        """Get aggregation statistics."""
        sorted_ts = sorted(self.hourly_candles.keys())

        return {
            "total_hourly_candles": len(self.hourly_candles),
            "rows_processed": self.rows_processed,
            "rows_skipped": self.rows_skipped,
            "first_timestamp": sorted_ts[0] if sorted_ts else None,
            "last_timestamp": sorted_ts[-1] if sorted_ts else None,
            "gaps_detected": len(self.gaps),
            "gaps_total_hours": self.gaps_total,
            "file_size_mb": 0,  # Will be set after saving
        }


def main():
    """Main execution: aggregate all HistData M1 files to H1."""
    print("=" * 70)
    print("HISTDATA M1 → H1 AGGREGATOR")
    print("=" * 70)

    # Find input files
    print("\n[1/5] Finding HistData M1 files...")
    input_dir = Path("/tmp")
    m1_files = list(input_dir.glob("DAT_MS_EURUSD_M1_*.csv"))

    if not m1_files:
        print("❌ No HistData M1 files found in /tmp/")
        return 1

    print(f"✓ Found {len(m1_files)} files:")
    for f in sorted(m1_files):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"    {f.name} ({size_mb:.1f} MB)")

    # Aggregate
    print("\n[2/5] Aggregating M1 to H1 candles...")
    aggregator = HistDataM1Aggregator()
    total_rows = aggregator.load_all_files([str(f) for f in sorted(m1_files)])
    print(f"✓ Processed {total_rows:,} minute bars")

    # Validate
    print("\n[3/5] Validating hourly candles...")
    valid, invalid = aggregator.validate_hourly_candles()
    print(f"✓ Valid: {valid}, Invalid: {invalid}")

    if invalid > 0:
        print(f"⚠ {invalid} invalid candles detected")

    # Detect gaps
    print("\n[4/5] Detecting data gaps...")
    aggregator.detect_gaps()
    print(f"✓ Detected {len(aggregator.gaps)} gaps ({aggregator.gaps_total:.1f} hours total)")

    if aggregator.gaps:
        print(f"  First 5 gaps:")
        for gap in aggregator.gaps[:5]:
            print(f"    {gap['from']} to {gap['to']} ({gap['hours']:.1f} hours)")

    # Save
    print("\n[5/5] Saving H1 CSV...")
    output_file = "/tmp/EURUSD_H1_2022-2026.csv"
    checksum = aggregator.save_csv(output_file)

    output_size_mb = Path(output_file).stat().st_size / (1024 * 1024)

    print(f"✓ Saved: {output_file}")
    print(f"✓ File size: {output_size_mb:.2f} MB")
    print(f"✓ Checksum (SHA256): {checksum}")

    # Display statistics
    stats = aggregator.get_stats()
    stats["file_size_mb"] = output_size_mb

    print("\n" + "=" * 70)
    print("AGGREGATION COMPLETE")
    print("=" * 70)

    print(f"\n📊 Statistics:")
    print(f"  Hourly candles: {stats['total_hourly_candles']:,}")
    print(f"  Period: {stats['first_timestamp']} to {stats['last_timestamp']}")
    print(f"  Minute bars processed: {stats['rows_processed']:,}")
    print(f"  Minute bars skipped: {stats['rows_skipped']:,}")
    print(f"  Data gaps (trading hours): {stats['gaps_detected']}")
    print(f"  Gap duration: {stats['gaps_total_hours']:.1f} hours")

    print(f"\n📄 Output:")
    print(f"  File: {output_file}")
    print(f"  Size: {stats['file_size_mb']:.2f} MB")
    print(f"  Format: CSV (timestamp, open, high, low, close)")
    print(f"  Timestamps: ISO-8601 UTC (+00:00)")

    print(f"\n🔒 Checksums:")
    print(f"  SHA256: {checksum}")

    print(f"\n💾 Next Steps:")
    print(f"  1. Download {output_file}")
    print(f"  2. Upload to Claude Code environment")
    print(f"  3. Run through holdout_acquisition.py validation gates")
    print(f"  4. Seal via EvidenceVault")
    print(f"  5. Begin Generation 7 research")

    print("\n" + "=" * 70)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
