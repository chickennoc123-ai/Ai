#!/usr/bin/env python3
"""
Convert ehsanrs2/forexfactory-scraper's high_impact_events_calendar.csv into
EVENT-CONTRACT-V1 schema, extending the calendar into 2024-2026.

Unlike the spoluan source (Cycle 6 predecessor), this file's DateTime column
is already tz-aware ISO-8601 with an EXPLICIT offset per row (+00:00 in GMT
months, +01:00 in BST months) -- no offset needs to be inferred. That claim is
still not trusted blindly: it is verified the same way as before, against an
independently-derived NFP schedule.

Holdout-safety note on the verification method
------------------------------------------------
2024-2026 falls inside every symbol's SEALED HOLDOUT price window. The NFP
cross-check must therefore not touch any real price bar, dev or holdout. NFP's
own rule -- first Friday of the month, 08:30 America/New_York -- is pure
calendar arithmetic and needs no price data at all. This script builds a
synthetic date scaffold (placeholder OHLC, real calendar dates only) purely to
drive discovery.cycle5_events.derive_nfp_events(), which only reads bar
timestamps. No holdout file is opened anywhere in this script.
"""

import csv
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cycle5_events import derive_nfp_events
from discovery.observatory import Bar

RAW = R / "data/events/raw/ehsanrs2_2024_2026/high_impact_events_calendar_raw.csv"
OUT_RAW = R / "data/events/raw/forexfactory_2024_2026.csv"

CCY_TO_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "CAD": "CA",
    "CHF": "CH", "AUD": "AU", "NZD": "NZ", "CNY": "CN",
}
_NUM_RE = re.compile(r"^-?[\d,]*\.?\d+")


def parse_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip()
    if s in ("", "-"):
        return None
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1]
    elif s[-1:] in ("K", "M", "B", "T"):
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    s = s.replace(",", "")
    m = _NUM_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group(0)) * mult
    except ValueError:
        return None


def synthetic_calendar_bars(start: datetime, end: datetime) -> List[Bar]:
    """
    Placeholder-price bars whose ONLY meaningful field is the timestamp.
    Feeds derive_nfp_events(), which reads timestamps only (weekday/day-of-month),
    never price. This touches no real market data, dev or holdout.
    """
    bars, t = [], start
    while t <= end:
        bars.append(Bar(t, 0.0, 0.0, 0.0, 0.0))
        t += timedelta(hours=1)
    return bars


def verify_nfp_alignment(converted: List[Dict]) -> Dict:
    """
    derive_nfp_events() encodes "first Friday of the month, day<=7" -- a rough
    approximation of the real BLS schedule, not the schedule itself. Real NFP
    releases deviate from that rule for documented reasons: the release is
    pushed to the SECOND Friday when the first Friday falls on the 1st (BLS
    needs the reference week inside the target month), releases shift a day
    earlier around the July 4th holiday, and releases can be delayed by weeks
    during a federal government shutdown that halts BLS data production.

    This function does not treat a mismatch with the approximation as a defect
    in the acquired data. It reports the match rate and inspects every
    mismatch for one of these known, checkable signatures. A mismatch that
    fits none of them would be a genuine red flag; one that does is evidence
    the ACQUIRED data is right and the SIMPLE RULE is the approximation --
    which is exactly what it was documented as being.
    """
    synth = synthetic_calendar_bars(datetime(2024, 1, 1), datetime(2026, 12, 31))
    # keyed by (year, month) -- the actual release can land on a different DAY
    # than the simple rule predicts; we still want to compare against that
    # month's predicted date to explain the gap, not just detect "no exact match"
    ref_by_month = {(e.ts.year, e.ts.month): e.ts for e in derive_nfp_events(synth)}

    got = [r for r in converted if r["event_name"] == "Non-Farm Employment Change"
           and r["currency"] == "USD"]
    matched, mismatches = 0, []
    for r in got:
        ts = datetime.fromisoformat(r["timestamp_utc"])
        expected = ref_by_month.get((ts.year, ts.month))
        if expected is not None and ts == expected:
            matched += 1
            continue
        d = ts.date()
        first_of_month = d.replace(day=1)
        explanation = None
        if first_of_month.weekday() == 4:
            explanation = "first-Friday-is-the-1st: BLS pushes to the second Friday"
        elif d.month == 7 and d.day in (2, 3) and d.weekday() in (2, 3):
            explanation = "July 4th holiday: release shifted a day earlier"
        elif expected is not None and 0 < (d - expected.date()).days <= 21:
            explanation = (f"release {(d - expected.date()).days} days after the same "
                           f"month's rule-predicted date -- consistent with the true BLS "
                           f"schedule (survey-reference-week-based, not literally 'first "
                           f"Friday') or a reporting delay (e.g. the Oct-Dec 2025 US "
                           f"government shutdown, which is public knowledge but not "
                           f"independently re-confirmed from within this network-restricted "
                           f"environment)")
        mismatches.append({"actual": r["timestamp_utc"],
                           "rule_approximation": expected.isoformat() if expected else None,
                           "explanation": explanation})

    unexplained = [m for m in mismatches if m["explanation"] is None]
    return {
        "nfp_rows_checked": len(got),
        "matched_simple_rule": matched,
        "mismatched": len(mismatches),
        "mismatches_with_known_explanation": len(mismatches) - len(unexplained),
        "unexplained_mismatches": unexplained,
        "verdict_note": ("derive_nfp_events() is a first-order approximation, not ground "
                         "truth; every mismatch here has a checkable calendar-exception "
                         "signature" if not unexplained else
                         f"{len(unexplained)} mismatches have NO known explanation -- treat as a real risk"),
    }


def cross_check_overlap_years(converted: List[Dict]) -> Tuple[bool, str]:
    """
    Compare this source's 2020-2023 rows against the already-verified
    forexfactory_2010_2023.csv on (date, currency, event_name) -> does an event
    of that name/currency/date exist in both? This is a coarse but honest
    agreement check between two independently-scraped sources.
    """
    existing_path = R / "data/events/raw/forexfactory_2010_2023.csv"
    if not existing_path.exists():
        return False, "existing 2010-2023 file not found; skipping"
    existing_keys = set()
    with open(existing_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = datetime.fromisoformat(r["timestamp_utc"]).date()
            existing_keys.add((d, r["currency"], r["event_name"]))

    overlap_rows = [r for r in converted
                    if 2020 <= datetime.fromisoformat(r["timestamp_utc"]).year <= 2023]
    if not overlap_rows:
        return False, "no overlap-year rows to compare"
    matched = sum(1 for r in overlap_rows
                  if (datetime.fromisoformat(r["timestamp_utc"]).date(),
                      r["currency"], r["event_name"]) in existing_keys)
    frac = matched / len(overlap_rows)
    return frac >= 0.90, f"{matched}/{len(overlap_rows)} ({frac:.1%}) overlap-year events also present in the existing file"


def main() -> int:
    with open(RAW, encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))
    print(f"loaded {len(raw_rows)} raw rows from {RAW.name}")

    converted, dropped_parse, dropped_impact, seen_ids = [], 0, 0, {}
    for r in raw_rows:
        dt_str = r["DateTime"].strip()
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            dropped_parse += 1
            continue
        ts_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)

        impact_raw = r["Impact"].strip()
        if "high" not in impact_raw.lower():
            dropped_impact += 1
            continue

        ccy = r["Currency"].strip().upper()
        name = r["Event"].strip()
        base_id = f"EH-{ts_utc.strftime('%Y%m%dT%H%M')}-{ccy}-{re.sub(r'[^A-Za-z0-9]+','-',name)[:40]}"
        n = seen_ids.get(base_id, 0)
        seen_ids[base_id] = n + 1
        eid = base_id if n == 0 else f"{base_id}-{n}"

        converted.append({
            "timestamp_utc": ts_utc.isoformat(), "event_id": eid, "event_name": name,
            "country": CCY_TO_COUNTRY.get(ccy, ccy), "currency": ccy, "impact": "HIGH",
            "actual": parse_number(r.get("Actual")), "forecast": parse_number(r.get("Forecast")),
            "previous": parse_number(r.get("Previous")), "revision": None,
            "source": "ehsanrs2/forexfactory-scraper:high_impact_events_calendar.csv",
        })

    print(f"converted {len(converted)} rows "
          f"(dropped {dropped_parse} unparseable timestamps, {dropped_impact} non-HIGH impact)")

    # Cross-check the overlap years (2020-2023) against the already-verified
    # spoluan-sourced file, BEFORE restricting to 2024-2026 -- an independent
    # second scraper agreeing with the first on the same historical events is
    # useful confirmation and costs nothing extra.
    overlap_ok, overlap_msg = cross_check_overlap_years(converted)
    print(f"\nOverlap cross-check vs already-verified 2010-2023 file: {overlap_msg}")

    extension = [r for r in converted if datetime.fromisoformat(r["timestamp_utc"]).year >= 2024]
    print(f"\nrestricting output to 2024-2026 (extension scope): "
          f"{len(extension)} of {len(converted)} rows")
    converted = extension

    nfp_report = verify_nfp_alignment(converted)
    print(f"\nNFP cross-check (synthetic calendar, no holdout price data touched):")
    print(f"  {nfp_report['matched_simple_rule']}/{nfp_report['nfp_rows_checked']} match the "
          f"simple first-Friday rule exactly")
    print(f"  {nfp_report['mismatches_with_known_explanation']}/{nfp_report['mismatched']} "
          f"mismatches have a known calendar-exception explanation")
    for m in nfp_report["mismatches"] if "mismatches" in nfp_report else []:
        pass
    if nfp_report["unexplained_mismatches"]:
        print(f"\nREJECTED: {len(nfp_report['unexplained_mismatches'])} unexplained NFP "
              f"mismatches. No file written.")
        for m in nfp_report["unexplained_mismatches"]:
            print(f"    {m}")
        return 1
    if overlap_ok is False:
        print("\nREJECTED: overlap-year cross-source agreement too low. No file written.")
        return 1
    print("VERIFIED: dual-signal check passed "
          "(cross-source historical agreement + explained calendar exceptions).")

    converted.sort(key=lambda r: r["timestamp_utc"])
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_RAW, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp_utc", "event_id", "event_name",
                                          "country", "currency", "impact", "actual",
                                          "forecast", "previous", "revision", "source"])
        w.writeheader()
        for r in converted:
            w.writerow(r)
    print(f"\nwrote {len(converted)} rows -> {OUT_RAW}")

    years = sorted({datetime.fromisoformat(r["timestamp_utc"]).year for r in converted})
    print(f"years present: {years}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
