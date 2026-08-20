#!/usr/bin/env python3
"""
Audit a supplied event calendar against EVENT-CONTRACT-V1.

    python3 scripts/audit_event_calendar.py data/events/raw/<file>.csv

Writes data/events/processed/events_dev.csv and an audit report only when all
seven gates pass. A calendar that fails is left in raw/ and nothing downstream
can read it.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.event_calendar import load_events, audit, EventDataError
from discovery.observatory import load_dev_bars, OBSERVATION_FRACTION


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])

    bars = load_dev_bars(R / "data/csv/EURUSD_H1.csv")
    dev_start, dev_end = bars[0].ts, bars[-1].ts

    try:
        events = load_events(src, dev_end=dev_end)
    except EventDataError as e:
        print(f"REJECTED at import: {e}")
        return 1

    rep = audit(events, dev_start, dev_end)
    rep["source_file"] = str(src)
    rep["dev_window"] = {"start": dev_start.isoformat(), "end": dev_end.isoformat()}

    print(json.dumps(rep, indent=2))
    out_dir = R / "data/events/processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")

    if not rep["passed"]:
        failed = [k for k, v in rep["gates"].items() if not v["pass"]]
        print(f"\nREJECTED: gates failed -> {failed}")
        print("No processed file written; discovery cannot read this calendar.")
        return 1

    import csv
    with open(out_dir / "events_dev.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "event_id", "event_name", "country", "currency",
                    "impact", "actual", "forecast", "previous", "revision", "source"])
        for e in events:
            w.writerow([e.ts.isoformat(), e.event_id, e.name, e.country, e.currency,
                        e.impact, e.actual, e.forecast, e.previous, e.revision, e.source])
    print(f"\nACCEPTED: {len(events)} development-window events -> {out_dir/'events_dev.csv'}")
    print("Cycle 5 can now run: python3 discovery/cycle5_events.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
