#!/usr/bin/env python3
"""
Audit the two independently-sourced gold series against each other and
against our own HistData-derived XAUUSD series, on the CLOSE price only
(the one field all three define comparably). This never runs discovery --
it only establishes whether the data is trustworthy enough to run Q4 of the
B2_TURN_OF_MONTH review on.

Sources:
  A. GC futures (CME continuous, via Investing.com scrape), 2008-10-28..2018-11-28
     github.com/Arghyadeep/Gold-and-Silver-Price-Prediction...
  B. XAUUSD D1 (provenance undisclosed), 2012-11-14..2022-03-04
     github.com/ejtraderLabs/historical-data
  C. our own dev XAUUSD H1 (HistData), resampled to daily, for comparison only
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from discovery.observatory import load_dev_bars
from discovery.cycle4_economics import to_daily

RAW = R / "data/independent_gold/raw"
OUT = R / "data/independent_gold/processed"
OUT.mkdir(parents=True, exist_ok=True)


def load_gc_futures():
    rows = []
    with open(RAW / "GC_futures_investingcom_2008_2018.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["Date"], "%b %d, %Y").date()
            price = float(r["Price"].replace(",", ""))
            rows.append((d, price))
    rows.sort()
    return rows


def load_ejtrader():
    rows = []
    with open(RAW / "XAUUSD_ejtraderlabs_d1.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["Date"], "%Y-%m-%d").date()
            close = float(r["close"]) / 100.0     # verified scale below
            rows.append((d, close))
    rows.sort()
    return rows


def load_ours():
    bars = load_dev_bars(R / "data/csv/XAUUSD_H1.csv")
    days = to_daily(bars)
    return sorted((d.date.date(), d.close) for d in days)


def gaps(dates, label):
    """Business-day gap audit: flag runs of >3 consecutive missing calendar days."""
    out = []
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i - 1]).days
        if delta > 4:      # allow normal weekends/holidays, flag longer
            out.append({"from": str(dates[i - 1]), "to": str(dates[i]), "days": delta})
    return out


def cross_check(a, label_a, b, label_b, tolerance=0.02):
    """Compare close prices on overlapping dates. tolerance = 2% (spot vs futures basis)."""
    da = dict(a)
    db = dict(b)
    common = sorted(set(da) & set(db))
    if not common:
        return {"overlap_days": 0}
    diffs = []
    for d in common:
        pa, pb = da[d], db[d]
        if pa and pb:
            diffs.append(abs(pa - pb) / pa)
    diffs.sort()
    n = len(diffs)
    within_tol = sum(1 for x in diffs if x <= tolerance)
    return {
        "overlap_days": n,
        "first_overlap": str(common[0]), "last_overlap": str(common[-1]),
        "median_relative_diff": round(diffs[n // 2], 5) if n else None,
        "max_relative_diff": round(diffs[-1], 5) if n else None,
        "fraction_within_2pct": round(within_tol / n, 4) if n else None,
        f"sample_{label_a}_vs_{label_b}": [
            {"date": str(common[i]), label_a: round(da[common[i]], 2),
             label_b: round(db[common[i]], 2)}
            for i in range(0, n, max(1, n // 5))
        ][:6],
    }


def main() -> int:
    gc = load_gc_futures()
    ej = load_ejtrader()
    ours = load_ours()

    # sanity check on the ejtrader /100 scale assumption before trusting anything
    ej_first = ej[0][1]
    if not (300 < ej_first < 5000):
        print(f"REJECTED: ejtraderLabs scale assumption failed sanity "
              f"(first close after /100 = {ej_first}, expected a plausible gold price)")
        return 1

    report = {
        "source_A_gc_futures": {
            "provenance": "CME GC continuous futures, Investing.com export, "
                          "github.com/Arghyadeep/Gold-and-Silver-Price-Prediction...",
            "provenance_confidence": "MEDIUM -- disclosed original vendor (Investing.com) "
                                     "and disclosed instrument (CME futures, not spot); "
                                     "student-project repo, no independent QA",
            "rows": len(gc), "start": str(gc[0][0]), "end": str(gc[-1][0]),
            "gaps_over_4_days": gaps([d for d, _ in gc], "gc"),
        },
        "source_B_ejtraderlabs": {
            "provenance": "XAUUSD D1, github.com/ejtraderLabs/historical-data",
            "provenance_confidence": "LOW -- original broker/vendor NOT disclosed in the "
                                     "repo; usable only as a weak secondary cross-check, "
                                     "not as a strong independent confirmation",
            "rows": len(ej), "start": str(ej[0][0]), "end": str(ej[-1][0]),
            "gaps_over_4_days": gaps([d for d, _ in ej], "ej"),
            "scale_correction_applied": "divided raw values by 100 (verified by sanity range)",
        },
        "our_series_daily_resample": {
            "rows": len(ours), "start": str(ours[0][0]), "end": str(ours[-1][0]),
        },
        "cross_check_gc_vs_ours": cross_check(gc, "gc_futures", ours, "our_histdata"),
        "cross_check_ej_vs_ours": cross_check(ej, "ejtrader", ours, "our_histdata"),
        "cross_check_gc_vs_ej": cross_check(gc, "gc_futures", ej, "ejtrader"),
    }

    combined_start = max(gc[0][0], ours[0][0])
    combined_end = min(gc[-1][0], ej[-1][0], ours[-1][0])
    report["usable_independent_overlap_with_our_dev_window"] = {
        "gc_futures_overlap": [str(max(gc[0][0], ours[0][0])), str(min(gc[-1][0], ours[-1][0]))],
        "ejtrader_overlap": [str(max(ej[0][0], ours[0][0])), str(min(ej[-1][0], ours[-1][0]))],
        "note": ("Neither source covers our full dev window (2009-12..2023-06). "
                 "GC futures ends 2018-11 (misses 2019-2023, including the 2020 COVID "
                 "year that supplies 26% of B2's measured profit). ejtraderLabs ends "
                 "2022-03 and DOES cover 2020, but its provenance is undisclosed."),
    }

    (OUT / "audit_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))

    # write merged usable series for later diagnostic use (NOT run here)
    with open(OUT / "gc_futures_daily.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "close"])
        for d, p in gc: w.writerow([d, p])
    with open(OUT / "ejtrader_xauusd_daily.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "close"])
        for d, p in ej: w.writerow([d, p])
    print(f"\nwrote processed series to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
