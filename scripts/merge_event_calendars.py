#!/usr/bin/env python3
"""
Merge forexfactory_2010_2023.csv (unchanged, read-only) with
forexfactory_2024_2026.csv (new) into a superset file. Neither input file is
modified -- this only ever writes a NEW combined file.
"""
import csv
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
OLD = R / "data/events/raw/forexfactory_2010_2023.csv"
NEW = R / "data/events/raw/forexfactory_2024_2026.csv"
OUT = R / "data/events/raw/forexfactory_2010_2026.csv"


def main() -> int:
    old_rows = list(csv.DictReader(open(OLD, encoding="utf-8")))
    new_rows = list(csv.DictReader(open(NEW, encoding="utf-8")))
    print(f"existing (2010-2023, untouched): {len(old_rows)} rows")
    print(f"extension (2024-2026, new):      {len(new_rows)} rows")

    old_ids = {r["event_id"] for r in old_rows}
    new_ids = {r["event_id"] for r in new_rows}
    collisions = old_ids & new_ids
    if collisions:
        print(f"REJECTED: {len(collisions)} event_id collisions between old and new: "
              f"{list(collisions)[:5]}")
        return 1

    combined = old_rows + new_rows
    combined.sort(key=lambda r: r["timestamp_utc"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp_utc", "event_id", "event_name",
                                          "country", "currency", "impact", "actual",
                                          "forecast", "previous", "revision", "source"])
        w.writeheader()
        for r in combined:
            w.writerow(r)

    print(f"\nwrote {len(combined)} rows -> {OUT}")
    print(f"OLD file untouched: {OLD}")
    print(f"NEW file untouched: {NEW}")

    years = sorted({r["timestamp_utc"][:4] for r in combined})
    print(f"years present in merged file: {years}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
