#!/usr/bin/env python3
"""
ML-001 GENERATION 6 CLOSURE: Holdout Rebuild (EST->UTC), Re-Audit, Gate, Seal.

Root cause being corrected
--------------------------
HistData.com M1 timestamps are EST (GMT-5, fixed, no DST). The original
aggregation (histdata_m1_to_h1_aggregator.py) labeled those timestamps as UTC
("+00:00"), which made ordinary forex weekends (Fri 17:00 -> Sun 17:00 EST)
look like trading-hour gaps. That misclassification produced the earlier
"68.9% coverage / 877 trading-hour gaps" rejection. Measured against the real
forex trading week the dataset covers ~96.5% of trading hours.

A second defect corrected here: the earlier audits claimed "no overlap with
DEVELOPMENT" but the aggregated file starts 2022-01-02 while DEVELOPMENT ends
2022-03-05 -- a ~2-month overlap. The sealed holdout is therefore TRIMMED to
start strictly after DEVELOPMENT (>= 2022-03-06 00:00 UTC).

What this script does (in order)
--------------------------------
 1. Rebuild H1 candles from the owner-supplied HistData M1 CSVs with the
    correct timezone semantics (EST + 5h = UTC).
 2. Write the full rebuilt series (lineage artifact) and the TRIMMED holdout
    artifact (2022-03-06 -> end).
 3. Independent audit of the trimmed artifact: OHLC integrity, monotonicity,
    coverage vs. true trading hours, hour-level gap classification
    (WEEKEND handled by construction; HOLIDAY / MARKET_EDGE / RESIDUAL).
 4. Explicit economic-compatibility gate with fixed thresholds.
 5. OGD-4 acquisition gates (core.factory.holdout_acquisition).
 6. Seal via EvidenceVault (persistent), evaluation NOT authorized.
 7. Emit machine-readable results for the report layer.

Determinism: no randomness anywhere; same inputs -> same outputs/checksums.
"""

import csv
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.factory.holdout_acquisition import (  # noqa: E402
    CandidateArtifact,
    SourceAccessStatus,
    SourceCandidate,
    check_independence,
    decide_primary_holdout_eligibility,
    evaluate_source_candidate,
    validate_artifact_integrity,
)
from core.factory.evidence_vault import EvidenceVault  # noqa: E402

# ---------------------------------------------------------------------------
# Constants (all governance-fixed, none tunable at runtime)
# ---------------------------------------------------------------------------

M1_DIR = Path("/tmp")
M1_GLOB = "DAT_MS_EURUSD_M1_*.csv"

# HistData timestamps are EST = UTC-5 fixed (no DST). UTC = stamp + 5h.
EST_TO_UTC = timedelta(hours=5)

# Prior research periods (naive UTC) -- the holdout must not touch these.
DEVELOPMENT_START = datetime(2012, 11, 16, 0, 0, 0)
DEVELOPMENT_END = datetime(2022, 3, 5, 23, 59, 59)
PURE_HOLDOUT_START = datetime(2021, 1, 1, 0, 0, 0)
PURE_HOLDOUT_END = datetime(2021, 12, 31, 23, 59, 59)

# Trimmed holdout must start strictly after DEVELOPMENT_END. Additionally,
# the owner-supplied 2023 M1 file is SOURCE_DEGRADED: ~830 whole trading hours
# (~13% of 2023) are absent from the file itself (alternating-hour holes on
# many weekdays), while 2022/2024/2025/2026 are essentially complete (0-5
# residual missing hours each). 2023 is therefore EXCLUDED from the primary
# holdout on evidence, and the primary window is the contiguous clean span
# 2024-01-01 -> end. The clean 2022-03-06..2022-12-31 segment is preserved
# (unsealed, unexposed) as SECONDARY data; 2023 is quarantined.
HOLDOUT_MIN_START = datetime(2024, 1, 1, 0, 0, 0)
SECONDARY_SEGMENT = (datetime(2022, 3, 6, 0, 0, 0), datetime(2022, 12, 31, 23, 0, 0))
QUARANTINED_YEAR = 2023

OUT_DIR = REPO_ROOT / "data" / "holdout"
FULL_CSV = OUT_DIR / "EURUSD_H1_2022-2026_UTC_FULL.csv"
HOLDOUT_CSV = OUT_DIR / "EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv"
SECONDARY_CSV = OUT_DIR / "EURUSD_H1_SECONDARY_20220306_20221231_UTC.csv"
RESULT_JSON = REPO_ROOT / "reports" / "factory" / "g6_holdout_seal_result.json"

DATASET_ID = "DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"

# Economic gate thresholds (fixed, pre-registered here before measurement).
MIN_COVERAGE_VS_TRADING_HOURS = 0.95   # >= 95% of true trading hours present
MAX_RESIDUAL_GAP_SHARE = 0.01          # unexplained missing hours <= 1%

# Known FX holiday dates (New York calendar; market closed or near-closed).
def _holiday_dates() -> set:
    days = set()
    for year in range(2022, 2027):
        for month, dom in [(12, 24), (12, 25), (12, 26), (12, 31), (1, 1), (1, 2)]:
            days.add(date(year, month, dom))
    # Good Friday + Easter Sunday/Monday (FX liquidity holidays)
    for gf in [date(2022, 4, 15), date(2023, 4, 7), date(2024, 3, 29),
               date(2025, 4, 18), date(2026, 4, 3)]:
        days.add(gf)
        days.add(gf + timedelta(days=1))
        days.add(gf + timedelta(days=2))
        days.add(gf + timedelta(days=3))
    return days

HOLIDAYS = _holiday_dates()


# ---------------------------------------------------------------------------
# Step 1: rebuild H1 from M1 with correct EST->UTC semantics
# ---------------------------------------------------------------------------

def rebuild_h1_utc() -> dict:
    """Aggregate owner-supplied M1 (EST) into H1 keyed by true-UTC hour."""
    files = sorted(M1_DIR.glob(M1_GLOB))
    if not files:
        raise SystemExit(f"FILE_NOT_AVAILABLE: no {M1_GLOB} under {M1_DIR}")

    m1_checksums = {}
    candles = {}  # naive UTC datetime (top of hour) -> dict(o,h,l,c,count)
    rows_processed = 0
    rows_skipped = 0

    for path in files:
        m1_checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 7 or row[0] != "EURUSD":
                    rows_skipped += 1
                    continue
                ts_str = row[1]
                try:
                    est = datetime(int(ts_str[0:4]), int(ts_str[4:6]), int(ts_str[6:8]),
                                   int(ts_str[8:10]), int(ts_str[10:12]))
                    o, h, l, c = (float(row[2]), float(row[3]),
                                  float(row[4]), float(row[5]))
                except (ValueError, IndexError):
                    rows_skipped += 1
                    continue
                if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
                    rows_skipped += 1
                    continue
                utc = est + EST_TO_UTC
                hour = utc.replace(minute=0)
                bar = candles.get(hour)
                if bar is None:
                    candles[hour] = {"open": o, "high": h, "low": l, "close": c}
                else:
                    bar["high"] = max(bar["high"], h)
                    bar["low"] = min(bar["low"], l)
                    bar["close"] = c
                rows_processed += 1

    return {
        "candles": candles,
        "m1_files": [p.name for p in files],
        "m1_checksums": m1_checksums,
        "rows_processed": rows_processed,
        "rows_skipped": rows_skipped,
    }


def write_csv(candles: dict, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,open,high,low,close"]
    for ts in sorted(candles):
        b = candles[ts]
        iso = ts.replace(tzinfo=timezone.utc).isoformat()
        lines.append(f"{iso},{b['open']},{b['high']},{b['low']},{b['close']}")
    payload = "\n".join(lines) + "\n"
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Step 3: audit -- coverage vs. true trading hours + gap classification
# ---------------------------------------------------------------------------

def in_weekend(ts: datetime) -> bool:
    """Fixed-EST weekend in UTC coordinates: Fri 22:00 -> Sun 22:00 UTC."""
    wd, hr = ts.weekday(), ts.hour
    if wd == 5:                      # Saturday: always closed
        return True
    if wd == 4 and hr >= 22:         # Friday from 22:00 UTC
        return True
    if wd == 6 and hr < 22:          # Sunday before 22:00 UTC
        return True
    return False


def near_weekend_boundary(ts: datetime, hours: int = 3) -> bool:
    for k in range(-hours, hours + 1):
        t = ts + timedelta(hours=k)
        if in_weekend(t) != in_weekend(ts):
            return True
    return False


def audit_holdout(candles: dict) -> dict:
    stamps = sorted(candles)
    first, last = stamps[0], stamps[-1]
    present = set(stamps)

    expected = []
    t = first
    while t <= last:
        if not in_weekend(t):
            expected.append(t)
        t += timedelta(hours=1)

    missing = [t for t in expected if t not in present]
    holiday_h = [t for t in missing if t.date() in HOLIDAYS]
    rest = [t for t in missing if t.date() not in HOLIDAYS]
    edge_h = [t for t in rest if near_weekend_boundary(t)]
    residual_h = [t for t in rest if not near_weekend_boundary(t)]

    ohlc_errors = sum(
        1 for b in candles.values()
        if not (b["high"] >= max(b["open"], b["close"]) and
                b["low"] <= min(b["open"], b["close"]) and
                b["high"] >= b["low"] and min(b.values()) > 0)
    )

    coverage = len(present & set(expected)) / len(expected)
    residual_share = len(residual_h) / len(expected)

    return {
        "first_bar_utc": first.isoformat(),
        "last_bar_utc": last.isoformat(),
        "bars": len(stamps),
        "expected_trading_hours": len(expected),
        "missing_trading_hours": len(missing),
        "missing_holiday_hours": len(holiday_h),
        "missing_market_edge_hours": len(edge_h),
        "missing_residual_hours": len(residual_h),
        "residual_examples": [t.isoformat() for t in residual_h[:20]],
        "coverage_vs_trading_hours": round(coverage, 4),
        "residual_gap_share": round(residual_share, 5),
        "ohlc_errors": ohlc_errors,
        "economic_gate": {
            "min_coverage_required": MIN_COVERAGE_VS_TRADING_HOURS,
            "max_residual_share": MAX_RESIDUAL_GAP_SHARE,
            "coverage_pass": coverage >= MIN_COVERAGE_VS_TRADING_HOURS,
            "residual_pass": residual_share <= MAX_RESIDUAL_GAP_SHARE,
            "verdict": ("PASS" if (coverage >= MIN_COVERAGE_VS_TRADING_HOURS and
                                    residual_share <= MAX_RESIDUAL_GAP_SHARE)
                        else "FAIL"),
        },
    }


# ---------------------------------------------------------------------------
# Steps 5-6: OGD-4 gates + Evidence Vault seal
# ---------------------------------------------------------------------------

def run_gates_and_seal(candles: dict, holdout_bytes: bytes,
                       rebuild_meta: dict, audit: dict) -> dict:
    stamps = sorted(candles)
    rows = [{"timestamp": ts, "open": candles[ts]["open"], "high": candles[ts]["high"],
             "low": candles[ts]["low"], "close": candles[ts]["close"]} for ts in stamps]

    evidence = (
        "Owner-supplied HistData.com ZIP archives "
        "(HISTDATA_COM_MS_EURUSD_M1{2022,2023,2024,2025,202601}) downloaded by the owner from "
        "https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/eurusd ; "
        "M1 CSV SHA-256 inventory: "
        + "; ".join(f"{k}={v[:16]}..." for k, v in sorted(rebuild_meta["m1_checksums"].items()))
        + " ; deterministic EST(+5h)->UTC H1 aggregation via "
          "scripts/ml_001_g6_holdout_rebuild_and_seal.py (this file, git-tracked); "
          "rebuilt-artifact checksum reproducible from the same inputs."
    )

    source = SourceCandidate(
        source_id="SRC-HISTDATA-OWNER-SUPPLIED",
        source_name="HistData.com M1 (owner-supplied archives)",
        source_url="https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/eurusd",
        source_type="user_provided",
        publisher="HistData.com",
        claimed_origin="HistData.com generic M1 bid quotes (EST GMT-5, no DST)",
        actual_origin_evidence=evidence,
        access_status=SourceAccessStatus.AVAILABLE,
        network_status="N/A (owner-supplied files; no network fetch)",
        license_status="HistData free historical data terms",
        download_method="owner manual download + upload to session",
        download_timestamp=datetime(2026, 8, 19, 16, 17, 0),
        notes="Timezone semantics corrected: EST->UTC (+5h). Trimmed to start "
              "after DEVELOPMENT_END to restore LEVEL_3 temporal independence.",
    )
    source = evaluate_source_candidate(source)

    artifact = CandidateArtifact(
        data_bytes=holdout_bytes,
        claimed_instrument="EURUSD",
        claimed_timeframe="H1",
        claimed_timezone="UTC",
        claimed_price_type="OHLC(bid)",
        claimed_source="HistData.com M1 aggregated to H1 (EST->UTC corrected)",
        synthetic_flag=False,
        coverage_start=stamps[0],
        coverage_end=stamps[-1],
        rows=rows,
    )

    validation = validate_artifact_integrity(artifact)
    independence = check_independence(
        artifact,
        known_research_periods=[
            (DEVELOPMENT_START, DEVELOPMENT_END),
            (PURE_HOLDOUT_START, PURE_HOLDOUT_END),
        ],
    )
    decision = decide_primary_holdout_eligibility(artifact, source, validation, independence)

    result = {
        "source": source.to_dict(),
        "validation": {
            "passed": validation.passed,
            "row_count": validation.row_count,
            "ohlc_violations": validation.ohlc_violations,
            "duplicates": validation.duplicate_timestamp_count,
            "monotonic": validation.monotonic,
            "file_checksum": validation.file_checksum,
            "failure_reasons": validation.failure_reasons,
        },
        "independence": {
            "temporal_overlap": independence.temporal_overlap,
            "research_exposure": independence.research_exposure,
            "passed": independence.passed,
            "reasons": independence.reasons,
        },
        "decision": decision.decision,
        "decision_reasons": decision.reasons,
    }

    if decision.decision != "ELIGIBLE" or audit["economic_gate"]["verdict"] != "PASS":
        result["sealed"] = False
        result["seal_refusal_reason"] = "gates not fully passed; refusing to seal"
        return result

    vault = EvidenceVault()
    if DATASET_ID in vault.datasets:
        raise SystemExit(f"dataset_id {DATASET_ID} already in vault; refusing to overwrite")

    vault.register_dataset_unsealed(
        dataset_id=DATASET_ID,
        instrument="EURUSD",
        timeframe="H1",
        source="HistData.com M1 (owner-supplied) -> deterministic EST->UTC H1 aggregation",
        source_url=source.source_url,
        coverage_start=stamps[0],
        coverage_end=stamps[-1],
        row_count=len(rows),
        timezone="UTC",
        price_type="OHLC(bid)",
        download_timestamp=datetime(2026, 8, 19, 16, 17, 0),
        download_method="owner manual download + upload; rebuild via scripts/ml_001_g6_holdout_rebuild_and_seal.py",
        source_verified=True,
    )
    seal_hash = vault.seal_dataset(
        dataset_id=DATASET_ID,
        data_bytes=holdout_bytes,
        research_exposure="UNEXPOSED",
        independence_level="LEVEL_3",
    )

    result["sealed"] = True
    result["dataset_id"] = DATASET_ID
    result["seal_hash"] = seal_hash
    result["vault_path"] = str(vault.path)
    return result


def fresh_process_verify(holdout_csv: Path) -> dict:
    """Re-open the persisted vault in a brand-new interpreter and verify."""
    code = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})
from core.factory.evidence_vault import EvidenceVault
vault = EvidenceVault()
data = open({str(holdout_csv)!r}, 'rb').read()
ok = vault.verify_seal({DATASET_ID!r}, data)
meta = vault.datasets[{DATASET_ID!r}]
print('VERIFY_OK' if ok else 'VERIFY_FAIL')
print('STATUS', meta.seal_status.value)
tampered = vault.verify_seal({DATASET_ID!r}, data + b'x')
print('TAMPER_DETECTED' if not tampered else 'TAMPER_MISSED')
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, cwd=str(REPO_ROOT))
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip().splitlines(),
        "stderr": proc.stderr.strip()[-500:] if proc.stderr else "",
        "passed": ("VERIFY_OK" in proc.stdout and "TAMPER_DETECTED" in proc.stdout
                   and proc.returncode == 0),
    }


def main() -> int:
    print("=" * 78)
    print("G6 CLOSURE: REBUILD (EST->UTC) -> TRIM -> AUDIT -> GATES -> SEAL")
    print("=" * 78)

    print("\n[1] Rebuilding H1 from owner-supplied M1 with EST->UTC (+5h)...")
    rebuild = rebuild_h1_utc()
    candles_full = rebuild["candles"]
    print(f"    M1 rows processed: {rebuild['rows_processed']:,} "
          f"(skipped: {rebuild['rows_skipped']})")
    print(f"    H1 bars (full):    {len(candles_full):,}")

    full_checksum = write_csv(candles_full, FULL_CSV)
    print(f"    Full artifact:     {FULL_CSV.name}  sha256={full_checksum[:16]}...")

    print("\n[2] Trimming: primary >= 2024-01-01 UTC; 2023 quarantined (SOURCE_DEGRADED);")
    print("    2022-03-06..2022-12-31 preserved as SECONDARY; pre-2022-03-06 dropped")
    print("    (DEVELOPMENT overlap).")
    candles_holdout = {ts: b for ts, b in candles_full.items() if ts >= HOLDOUT_MIN_START}
    candles_secondary = {ts: b for ts, b in candles_full.items()
                         if SECONDARY_SEGMENT[0] <= ts <= SECONDARY_SEGMENT[1]}
    dev_overlap_bars = sum(1 for ts in candles_full if ts < SECONDARY_SEGMENT[0])
    quarantined_bars = sum(1 for ts in candles_full if ts.year == QUARANTINED_YEAR)
    holdout_checksum = write_csv(candles_holdout, HOLDOUT_CSV)
    secondary_checksum = write_csv(candles_secondary, SECONDARY_CSV)
    holdout_bytes = HOLDOUT_CSV.read_bytes()
    print(f"    DEVELOPMENT-overlap bars dropped (2022-01-02..2022-03-05): {dev_overlap_bars}")
    print(f"    2023 bars quarantined (source-degraded): {quarantined_bars}")
    print(f"    Secondary bars (2022-03-06..2022-12-31): {len(candles_secondary):,}"
          f"  sha256={secondary_checksum[:16]}...")
    print(f"    PRIMARY holdout bars: {len(candles_holdout):,}")
    print(f"    PRIMARY artifact: {HOLDOUT_CSV.name}  sha256={holdout_checksum[:16]}...")

    print("\n[3] Auditing trimmed artifact (coverage vs true trading hours)...")
    audit = audit_holdout(candles_holdout)
    for k in ("first_bar_utc", "last_bar_utc", "bars", "expected_trading_hours",
              "missing_trading_hours", "missing_holiday_hours",
              "missing_market_edge_hours", "missing_residual_hours",
              "coverage_vs_trading_hours", "residual_gap_share", "ohlc_errors"):
        print(f"    {k}: {audit[k]}")
    print(f"    ECONOMIC GATE: {audit['economic_gate']['verdict']}")

    print("\n[4] Running OGD-4 acquisition gates + sealing...")
    gates = run_gates_and_seal(candles_holdout, holdout_bytes, rebuild, audit)
    print(f"    Source eligibility: {gates['source']['eligibility_status']}")
    print(f"    Integrity passed:   {gates['validation']['passed']}")
    print(f"    Independence:       overlap={gates['independence']['temporal_overlap']} "
          f"exposure={gates['independence']['research_exposure']}")
    print(f"    DECISION:           {gates['decision']}")
    if gates.get("sealed"):
        print(f"    SEALED: {gates['dataset_id']}")
        print(f"    Seal hash: {gates['seal_hash'][:32]}...")

    fresh = {"passed": False, "skipped": True}
    if gates.get("sealed"):
        print("\n[5] Fresh-process seal verification (new interpreter)...")
        fresh = fresh_process_verify(HOLDOUT_CSV)
        for line in fresh["stdout"]:
            print(f"    {line}")
        print(f"    Fresh-process verification: {'PASS' if fresh['passed'] else 'FAIL'}")

    result = {
        "generated_at": "2026-08-19",
        "script": "scripts/ml_001_g6_holdout_rebuild_and_seal.py",
        "timezone_correction": "HistData EST (GMT-5, no DST) -> UTC via +5h",
        "m1_files": rebuild["m1_files"],
        "m1_checksums": rebuild["m1_checksums"],
        "m1_rows_processed": rebuild["rows_processed"],
        "full_artifact": {"path": str(FULL_CSV.relative_to(REPO_ROOT)),
                          "bars": len(candles_full), "sha256": full_checksum},
        "holdout_artifact": {"path": str(HOLDOUT_CSV.relative_to(REPO_ROOT)),
                             "bars": len(candles_holdout), "sha256": holdout_checksum,
                             "development_overlap_bars_removed": dev_overlap_bars},
        "secondary_artifact": {"path": str(SECONDARY_CSV.relative_to(REPO_ROOT)),
                               "bars": len(candles_secondary),
                               "sha256": secondary_checksum,
                               "status": "PRESERVED_UNSEALED_UNEXPOSED"},
        "quarantined_2023": {
            "bars": quarantined_bars,
            "status": "SOURCE_DEGRADED_EXCLUDED",
            "evidence": "owner-supplied 2023 M1 file has ~830 whole trading "
                        "hours absent (~13% of 2023) with alternating-hour "
                        "holes; 2022/2024/2025/2026 files show 0-5 residual "
                        "missing hours each",
        },
        "audit": audit,
        "gates": gates,
        "fresh_process_verification": fresh,
        "evaluation_authorized": False,
        "prior_misclassification": {
            "old_verdict": "REJECT (68.9% coverage, 877 trading-hour gaps)",
            "root_cause": "EST timestamps mislabeled as UTC; forex weekends "
                          "misclassified as trading-hour gaps",
            "second_defect": "2022-01-02..2022-03-05 overlap with DEVELOPMENT "
                             "was reported as PASS by a phase that had errored",
        },
    }
    RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\n[6] Machine-readable result: {RESULT_JSON.relative_to(REPO_ROOT)}")

    ok = (gates["decision"] == "ELIGIBLE" and gates.get("sealed") and fresh["passed"])
    print("\n" + "=" * 78)
    print("RESULT:", "SEALED + VERIFIED" if ok else "NOT SEALED (see reasons above)")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
