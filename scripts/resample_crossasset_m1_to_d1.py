#!/usr/bin/env python3
"""
Resample WTICO_USD (oil), USB10Y_USD (US 10Y), SPX500_USD (S&P500) M1 data
from FutureSharks/financial-data (Oanda) into daily OHLC.

Provenance: cloned from github.com/FutureSharks/financial-data (public,
anonymous git read), Oanda M1 bars, years 2010-2020 (repo's own coverage
stops at 2020; our FX dev windows extend to 2022-2023, so this is a REDUCED
overlap window -- stated here, not discovered later).

Timezone note: Oanda's M1 timestamps use a broker-day convention (first bar
of "day N" begins ~23:00 UTC of day N-1, standard FX/CFD broker rollover, not
strict UTC midnight). This is NOT recalibrated -- daily OHLC computed on
broker-day boundaries is consistent day-to-day and adequate for close-to-close
return analysis; it is not adequate for anything requiring exact UTC-midnight
alignment, which nothing in this cycle's design needs.
"""
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta

CLONE = Path("/home/user/futuresharks/financial-data/pyfinancialdata/data/currencies/oanda")
OUT = Path("data/crossasset/processed")
OUT.mkdir(parents=True, exist_ok=True)

INSTRUMENTS = {
    "WTICO": "WTICO_USD",
    "US10Y": "USB10Y_USD",
    "SPX500": "SPX500_USD",
}
YEARS = range(2010, 2021)


def resample_instrument(name: str, folder: str):
    days = {}
    for year in YEARS:
        ydir = CLONE / folder / str(year)
        if not ydir.exists():
            continue
        for f in sorted(ydir.glob("*.csv")):
            with open(f, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ts = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
                    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                    # broker-day: bars from 23:00 belong to the NEXT calendar date
                    day_key = (ts + timedelta(hours=1)).date()
                    if day_key not in days:
                        days[day_key] = [o, h, l, c, ts, ts, 1]
                    else:
                        d = days[day_key]
                        d[1] = max(d[1], h)
                        d[2] = min(d[2], l)
                        d[3] = c
                        d[5] = ts
                        d[6] += 1
    rows = sorted(days.items())
    out_path = OUT / f"{name}_D1.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "m1_bars"])
        for day, (o, h, l, c, first_ts, last_ts, n) in rows:
            w.writerow([day.isoformat(), o, h, l, c, n])
    return out_path, len(rows), rows[0][0] if rows else None, rows[-1][0] if rows else None


def main():
    print("Resampling M1 -> D1 (this reads ~560MB of local M1 CSVs, no network)")
    for name, folder in INSTRUMENTS.items():
        path, n, start, end = resample_instrument(name, folder)
        print(f"  {name:8s} -> {path.name}: {n} daily bars, {start} .. {end}")


if __name__ == "__main__":
    main()
