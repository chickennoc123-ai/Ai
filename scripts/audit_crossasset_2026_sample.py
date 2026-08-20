#!/usr/bin/env python3
"""
Audit the SPX500/USOIL 2026-02..2026-07 M1 samples acquired in Cycle 10.

Read-only integrity audit. Does NOT run any SC evaluation, does NOT touch
holdout price data, does NOT touch the multiple-testing ledger.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parent.parent
RAW = R / "data/crossasset/raw_2026_sample"
OUT = R / "reports/factory/discovery_cycles/cycle_10_crossasset_2026_audit.json"

FX_HOLDOUT_START = {
    "EURUSD": datetime(2024, 1, 1), "GBPUSD": datetime(2023, 6, 2),
    "USDCAD": datetime(2023, 6, 3), "USDCHF": datetime(2023, 6, 2),
    "USDJPY": datetime(2023, 6, 3), "XAUUSD": datetime(2023, 4, 3),
}
FX_HOLDOUT_END = {
    "EURUSD": datetime(2026, 1, 30), "GBPUSD": datetime(2026, 8, 20),
    "USDCAD": datetime(2026, 8, 20), "USDCHF": datetime(2026, 8, 20),
    "USDJPY": datetime(2026, 8, 20), "XAUUSD": datetime(2026, 8, 20),
}


def audit_file(name: str, path: Path) -> dict:
    rows = list(csv.DictReader(open(path)))
    ts = [datetime.fromisoformat(r["datetime"]).replace(tzinfo=None) for r in rows]
    closes = [float(r["close"]) for r in rows]

    bad_ohlc = sum(1 for r in rows if not (
        float(r["low"]) <= float(r["open"]) <= float(r["high"]) and
        float(r["low"]) <= float(r["close"]) <= float(r["high"])))
    gaps = [(ts[i - 1], ts[i], (ts[i] - ts[i - 1]).total_seconds() / 3600)
           for i in range(1, len(ts)) if (ts[i] - ts[i - 1]).total_seconds() > 3600]
    long_gaps = [g for g in gaps if g[2] > 24]

    overlapping_holdouts = [sym for sym, start in FX_HOLDOUT_START.items()
                            if ts[0] < FX_HOLDOUT_END[sym] and ts[-1] > start]

    return {
        "rows": len(rows), "span_start": str(ts[0]), "span_end": str(ts[-1]),
        "price_range": [min(closes), max(closes)],
        "bad_ohlc_rows": bad_ohlc,
        "gaps_over_1h": len(gaps), "gaps_over_24h": len(long_gaps),
        "sample_gaps_over_24h": [{"from": str(g[0]), "to": str(g[1]), "hours": round(g[2], 1)}
                                 for g in long_gaps[:10]],
        "overlaps_fx_holdout_for": overlapping_holdouts,
    }


def main() -> int:
    report = {
        "cycle_id": "CYCLE-10-CROSSASSET-DATA-ACQUISITION",
        "no_experiments_run": True,
        "no_holdout_price_touched": True,
        "no_sc_mechanism_modified": True,
        "no_ledger_change": True,
        "sources_found": {
            "SPX500": {
                "vendor": "getdata.finance (via GitHub sample repo getdata-finance/"
                         "spx500-1m-ohlcv-index-historical-data)",
                "acquisition_method": "anonymous git clone (raw.githubusercontent.com-"
                                      "equivalent path; git proxy allows public repo reads "
                                      "even though the vendor's own site is blocked)",
                "github_sample_window": "2026-02-01 .. 2026-07-31 (rolling 6-month evaluation "
                                        "sample, refreshed weekly; NOT the full archive)",
                "full_archive_claimed": "2008-08-19 .. 2026-07-30, 5,782,916 1m rows, "
                                        "~389.53MB, 11 timeframes",
                "full_archive_access": "BLOCKED -- requires purchase/download from "
                                       "getdata.finance directly; that host returns "
                                       "connection code 000 (policy denial) from this "
                                       "environment, same as every other direct financial "
                                       "data host tried across Cycles 4-10",
            },
            "USOIL": {
                "vendor": "getdata.finance (via GitHub sample repo getdata-finance/"
                         "usoil-1m-ohlcv-commodities-historical-data)",
                "note": "identical pattern to SPX500 -- 6-month rolling sample on GitHub, "
                       "full archive (2008-09-10..2026-07-30, 5,948,540 rows) paywalled "
                       "and blocked",
                "instrument_note": "'USOIL' is the standard CFD-market name for WTI crude "
                                   "(distinct from 'UKOIL'/Brent, also offered by this "
                                   "vendor); treated as the WTI proxy requested",
            },
            "US10Y": {
                "vendor": None,
                "status": "NOT FOUND",
                "search_performed": [
                    "direct network probes: stooq, dukascopy, yahoo finance, investing.com, "
                    "nasdaq data link -- all connection code 000 (blocked)",
                    "WebSearch for github M1/intraday US10Y/treasury sources",
                    "getdata-finance org: checked naming convention against 8 plausible "
                    "repo-name variants (us10y-1m-*, ust10y-1m-*, tnx-1m-*, etc) -- all 404",
                    "getdata-finance org repository search filtered by '10y' and 'bond' -- "
                    "zero matches out of the org's 307 repositories",
                ],
                "conclusion": "No free, network-accessible M1 US10Y source was found "
                             "extending past FutureSharks/financial-data's 2020-05 cutoff.",
            },
        },
        "audit": {},
    }

    for name, fname in [("SPX500", "SPX500_1m_20260201_20260731.csv"),
                        ("USOIL", "USOIL_1m_20260201_20260731.csv")]:
        report["audit"][name] = audit_file(name, RAW / fname)

    # the actual question this cycle exists to answer
    report["power_bottleneck_resolved"] = False
    report["reason"] = (
        "Two real, integrity-audited samples were acquired (SPX500, USOIL), but neither "
        "closes the gap this project actually needs. The event calendar "
        "(data/events/raw/forexfactory_2010_2023.csv) only extends to 2023 -- there is no "
        "verified NFP/CPI/ADP event data for 2024 onward. The acquired samples cover "
        "2026-02..2026-07, which is AFTER the event calendar ends, not inside the "
        "2020-06..2023-12 window the SC mechanism's event pool actually spans. A temporal "
        "gap of roughly 5.5 years (2020-06 to 2026-02) remains completely uncovered for "
        "SPX500/USOIL, and no source at all was found for US10Y at any date past 2020-05."
    )
    report["additional_governance_note"] = (
        "The acquired 2026-02..2026-07 window overlaps the SEALED holdout period for "
        "GBPUSD, USDCAD, USDCHF, USDJPY, and XAUUSD (each extends through 2026-08-20) -- "
        "only EURUSD's sealed window (ending 2026-01-30) sits just before it. Any future "
        "use of this cross-asset sample paired with those five FX legs would require the "
        "same GEN 14 authorization gate as touching their price holdout directly, not casual "
        "use as ordinary development data. This is noted for future cycles, not acted on now."
    )

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
