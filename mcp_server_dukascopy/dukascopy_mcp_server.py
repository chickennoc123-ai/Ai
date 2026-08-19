#!/usr/bin/env python3
"""
MCP Server for Dukascopy EURUSD H1 Data Fetching

Provides a fetch_eurusd_h1(start_date, end_date) tool that retrieves
hourly OHLC data from Dukascopy, returning UTC-timestamped CSV with
full provenance metadata.

Designed to run on user's personal machine (unrestricted internet)
and expose data fetch as MCP tool callable from Claude Code.
"""

import json
import hashlib
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import dukascopy_tick
except ImportError:
    dukascopy_tick = None


class DukascopyFetcher:
    """Fetches EURUSD H1 data from Dukascopy and returns as CSV with metadata."""

    INSTRUMENT = "EURUSD"
    TIMEFRAME = "H1"
    TIMEZONE = "UTC"
    PRICE_TYPE = "OHLC"

    def fetch(self, start_date: str, end_date: str) -> dict[str, Any]:
        """
        Fetch EURUSD H1 data from Dukascopy for the given date range.

        Args:
            start_date: ISO-8601 date string (YYYY-MM-DD)
            end_date: ISO-8601 date string (YYYY-MM-DD)

        Returns:
            dict with keys:
                - csv_data: CSV string (timestamp, open, high, low, close)
                - metadata: dict with provenance, checksums, row counts
                - status: "success" or "error"
                - message: human-readable description
        """
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except ValueError as e:
            return {
                "status": "error",
                "message": f"Invalid date format: {e}. Use YYYY-MM-DD.",
                "csv_data": None,
                "metadata": None,
            }

        if start_dt > end_dt:
            return {
                "status": "error",
                "message": f"start_date ({start_date}) must be <= end_date ({end_date})",
                "csv_data": None,
                "metadata": None,
            }

        try:
            # Fetch data from Dukascopy using dukascopy_tick library
            # Returns list of OHLCV candles
            candles = self._fetch_dukascopy_data(start_dt, end_dt)

            if not candles:
                return {
                    "status": "error",
                    "message": f"No data returned from Dukascopy for {start_date} to {end_date}",
                    "csv_data": None,
                    "metadata": None,
                }

            # Convert to CSV format
            csv_data = self._candles_to_csv(candles)

            # Compute checksums
            file_checksum = hashlib.sha256(csv_data.encode("utf-8")).hexdigest()

            # Calculate expected vs actual row count
            expected_rows = self._calculate_expected_rows(start_dt, end_dt)
            actual_rows = len(candles)

            # Build metadata
            metadata = {
                "source": "dukascopy",
                "instrument": self.INSTRUMENT,
                "timeframe": self.TIMEFRAME,
                "timezone": self.TIMEZONE,
                "price_type": self.PRICE_TYPE,
                "start_date": start_date,
                "end_date": end_date,
                "first_timestamp": candles[0]["timestamp"] if candles else None,
                "last_timestamp": candles[-1]["timestamp"] if candles else None,
                "actual_rows": actual_rows,
                "expected_rows": expected_rows,
                "gaps_present": actual_rows < expected_rows,
                "acquisition_timestamp": datetime.now(timezone.utc).isoformat(),
                "checksum": f"sha256:{file_checksum}",
                "file_checksum_algorithm": "SHA256",
                "source_type": "primary",
                "actual_origin_evidence": "Direct download from Dukascopy via dukascopy-tick library",
                "synthetic": False,
                "license": "Dukascopy free tier (research/personal use permitted)",
            }

            return {
                "status": "success",
                "message": f"Fetched {actual_rows} bars from Dukascopy for {self.INSTRUMENT} {self.TIMEFRAME}",
                "csv_data": csv_data,
                "metadata": metadata,
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to fetch data from Dukascopy: {type(e).__name__}: {str(e)}",
                "csv_data": None,
                "metadata": None,
            }

    def _fetch_dukascopy_data(self, start_dt: datetime, end_dt: datetime) -> list[dict]:
        """
        Fetch candles from Dukascopy using dukascopy-tick.

        Returns list of dicts: {"timestamp": ISO-8601, "open": float, "high": float, "low": float, "close": float}
        """
        if not dukascopy_tick:
            raise ImportError("dukascopy-tick not installed. Install with: pip install dukascopy-tick")

        candles = []
        current_dt = start_dt

        while current_dt <= end_dt:
            try:
                # dukascopy_tick.get_candles(instrument, timeframe, year, month, day)
                # Returns list of tuples: (timestamp_ms, open, high, low, close, volume)
                # or list of (datetime, open, high, low, close, volume) depending on version
                daily_candles = dukascopy_tick.get_candles(
                    self.INSTRUMENT,
                    self.TIMEFRAME,
                    current_dt.year,
                    current_dt.month,
                    current_dt.day,
                )

                for candle_data in daily_candles:
                    try:
                        # Handle different return formats
                        if len(candle_data) >= 5:
                            timestamp, open_price, high_price, low_price, close_price = candle_data[:5]

                            # Convert timestamp to ISO-8601 UTC
                            if isinstance(timestamp, datetime):
                                ts_iso = timestamp.replace(tzinfo=timezone.utc).isoformat()
                            elif isinstance(timestamp, (int, float)):
                                # Timestamp in milliseconds since epoch
                                ts_dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                                ts_iso = ts_dt.isoformat()
                            else:
                                # Try to parse as string
                                ts_iso = str(timestamp)

                            # Ensure timezone is included
                            if "+00:00" not in ts_iso and "Z" not in ts_iso:
                                ts_iso += "+00:00"

                            # Only include candles within requested range
                            try:
                                candle_dt = datetime.fromisoformat(ts_iso.replace("+00:00", "").replace("Z", ""))
                            except:
                                continue

                            if start_dt <= candle_dt <= end_dt:
                                candles.append({
                                    "timestamp": ts_iso,
                                    "open": float(open_price),
                                    "high": float(high_price),
                                    "low": float(low_price),
                                    "close": float(close_price),
                                })
                    except (ValueError, IndexError, TypeError):
                        # Skip malformed candle
                        continue

                # Move to next day
                current_dt += timedelta(days=1)

            except Exception as e:
                # Some days may have no data (weekends, holidays)
                # Silently continue to next day
                current_dt += timedelta(days=1)
                continue

        # Sort by timestamp to ensure chronological order
        candles = sorted(candles, key=lambda c: c["timestamp"])

        return candles

    def _candles_to_csv(self, candles: list[dict]) -> str:
        """Convert candle list to CSV format with header."""
        lines = ["timestamp,open,high,low,close"]
        for candle in candles:
            lines.append(
                f"{candle['timestamp']},{candle['open']},{candle['high']},"
                f"{candle['low']},{candle['close']}"
            )
        return "\n".join(lines)

    def _calculate_expected_rows(self, start_dt: datetime, end_dt: datetime) -> int:
        """
        Calculate theoretical number of H1 bars for a date range.

        Assumes 5-day trading weeks (Mon-Fri), no gaps on trading days.
        """
        current = start_dt
        count = 0

        while current <= end_dt:
            # H1 bars: 0-23 = 24 bars per day (if trading)
            # Dukascopy typically has data Mon-Fri (0-4 weekdays)
            if current.weekday() < 5:  # Mon-Fri
                count += 24
            current += timedelta(days=1)

        return count


def main():
    """
    Run MCP server for Dukascopy data fetching.

    This server runs on stdio transport and provides:
    - fetch_eurusd_h1(start_date, end_date): Returns CSV + metadata
    """
    import asyncio

    async def run_server():
        from mcp.server import Server
        from mcp.types import Tool, TextContent

        server = Server("dukascopy-mcp-server")
        fetcher = DukascopyFetcher()

        @server.call_tool
        async def handle_fetch_eurusd_h1(start_date: str, end_date: str):
            """Fetch EURUSD H1 data from Dukascopy."""
            result = fetcher.fetch(start_date, end_date)
            response_text = json.dumps(result, indent=2, default=str)
            return response_text

        # Define tool schema
        tool_schema = Tool(
            name="fetch_eurusd_h1",
            description="Fetch EURUSD hourly (H1) OHLC data from Dukascopy for a date range. Returns CSV data with full provenance metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (e.g., 2022-01-01)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (e.g., 2022-12-31)",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        )

        server.add_tool(tool_schema)

        # Run server with stdio transport
        async with server:
            await server.run()

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
