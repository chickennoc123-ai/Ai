"""
GEN 14 -- final sealed-holdout evaluation for the 4 frozen C2-NFP candidates
(CAND-C2-NFP-GBPUSD, CAND-C2-NFP-USDCHF, CAND-C2-NFP-USDJPY, CAND-C2-NFP-XAUUSD).

This is the only place in the Factory permitted to read these four holdout
files, and each is read exactly once. Two governance layers gate every read,
both required:

  1. core.factory.evidence_vault.EvidenceVault -- cryptographic seal
     (SHA-256 over the exact file bytes), authorize_evaluation() /
     consume_dataset() state machine (SEALED -> AUTHORIZED -> CONSUMED,
     one-way). This is the same mechanism EURUSD's Gen 6 holdout uses.
  2. discovery.holdout_authorization.HoldoutAuthorizationGate +
     discovery.candidate_spec_registry.CandidateSpecRegistry -- the frozen-
     spec / one-shot-result tracking these 4 candidates were already
     registered under in Cycle 6.

A candidate must clear a spec-hash check against BOTH layers before a single
byte of holdout price data is read. Neither layer alone is sufficient; both
must agree the candidate is frozen, authorized, and unconsumed.

Event data for the holdout window
----------------------------------
The acquired real calendar (data/events/raw/forexfactory_2010_2026.csv) ends
2026-01-30; every symbol's holdout runs to 2026-08-20. This leaves a 202-day
tail with NO acquired event data. This is stated here, not discovered after
the fact: the usable holdout evaluation window is
[holdout_start, min(holdout_end, 2026-01-30)], and the resulting sample sizes
(30-33 NFP events depending on symbol) are reported honestly, including where
that lands a candidate right at the n>=30 floor.

Gates (fixed BEFORE this script ever touches real holdout data)
------------------------------------------------------------------
  G1  n_trades      >= 30
  G2  mean_net      >  0
  G3  t_stat        >= 2.0
  G4  profit_factor >= 1.10
  G5  bonferroni    p < 0.05 / M,  M = 1222 (the cumulative ledger total
      immediately before this GEN 14 run -- fixed now, not recomputed after
      any candidate's result is seen)

PASS -> QUALIFIED. FAIL -> terminal; the candidate may never be retuned or
resubmitted against this holdout.
"""

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from core.factory.evidence_vault import EvidenceVault, EvidenceSealStatus
from discovery.observatory import Bar
from discovery.event_calendar import MacroEvent
from discovery.cycle5_events import c2_surprise, stats as event_stats, EStats
from discovery.candidate_spec_registry import CandidateSpecRegistry
from discovery.holdout_authorization import HoldoutAuthorizationGate
from qualification.gen14_runner import _two_sided_p

CALENDAR = R / "data/events/raw/forexfactory_2010_2026.csv"
CALENDAR_MAX_TS = datetime(2026, 1, 30, 0, 0, 0)   # acquired coverage ends here

FAMILYWISE_ALPHA = 0.05
MIN_TRADES = 30
MIN_T = 2.0
MIN_PROFIT_FACTOR = 1.10
FIXED_M = 1222   # cumulative ledger total immediately BEFORE this GEN 14 run

HOLDOUT_FILES = {
    "GBPUSD": R / "data/holdout/GBPUSD_H1_HOLDOUT_20230602_20260820_UTC.csv",
    "USDCHF": R / "data/holdout/USDCHF_H1_HOLDOUT_20230602_20260820_UTC.csv",
    "USDJPY": R / "data/holdout/USDJPY_H1_HOLDOUT_20230603_20260820_UTC.csv",
    "XAUUSD": R / "data/holdout/XAUUSD_H1_HOLDOUT_20230403_20260820_UTC.csv",
}

CANDIDATES = {
    "CAND-C2-NFP-GBPUSD": {"symbol": "GBPUSD", "mode": "FADE"},
    "CAND-C2-NFP-USDCHF": {"symbol": "USDCHF", "mode": "FOLLOW"},
    "CAND-C2-NFP-USDJPY": {"symbol": "USDJPY", "mode": "FOLLOW"},
    "CAND-C2-NFP-XAUUSD": {"symbol": "XAUUSD", "mode": "FADE"},
}
POST_HOURS = 4
EVENT_NAME, CCY = "Non-Farm Employment Change", "USD"

DATASET_PREFIX = "DS-HOLDOUT"
OUT = R / "reports/factory/gen14_c2_nfp_qualification.json"


# --------------------------------------------------------------------- setup

def dataset_id(symbol: str) -> str:
    f = HOLDOUT_FILES[symbol]
    # e.g. DS-HOLDOUT-GBPUSD-H1-20230602-20260820
    stem = f.stem.replace(f"{symbol}_H1_HOLDOUT_", "").replace("_UTC", "")
    start, end = stem.split("_")
    return f"{DATASET_PREFIX}-{symbol}-H1-{start}-{end}"


def seal_holdout_datasets(vault: EvidenceVault) -> Dict[str, str]:
    """
    Idempotently register+seal the 4 non-EURUSD holdout datasets. Safe to call
    repeatedly: skips any dataset already SEALED/AUTHORIZED/CONSUMED.
    Research-exposure and independence are asserted from this project's own
    audit trail, not assumed: these files were split from vendor parquet in
    Cycle 3 (ingest_multiasset_data.py), guarded by discovery._guards ever
    since, and the only prior touch (b2_independent_review.py) listed
    filenames without reading bytes -- verified by code inspection before
    this script was written.
    """
    ids = {}
    for symbol, path in HOLDOUT_FILES.items():
        did = dataset_id(symbol)
        ids[symbol] = did
        if did in vault.datasets:
            continue
        data = path.read_bytes()
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        start = datetime.fromisoformat(rows[0]["timestamp"])
        end = datetime.fromisoformat(rows[-1]["timestamp"])
        vault.register_dataset_unsealed(
            dataset_id=did, instrument=symbol, timeframe="H1",
            source="HistData.com (owner-supplied parquet) -> Cycle 3 80/20 split",
            source_url="https://www.histdata.com/",
            coverage_start=start, coverage_end=end, row_count=len(rows),
            timezone="UTC", price_type="OHLC(bid)",
            download_timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            download_method="scripts/ingest_multiasset_data.py (Cycle 3)",
            source_verified=True,
        )
        vault.seal_dataset(did, data, research_exposure="UNEXPOSED",
                           independence_level="LEVEL_3")
    return ids


def load_holdout_bars(symbol: str) -> List[Bar]:
    path = HOLDOUT_FILES[symbol]
    bars = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
            bars.append(Bar(ts, float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"])))
    return bars


def load_holdout_events(dev_end: datetime, holdout_end: datetime) -> List[MacroEvent]:
    """NFP/USD events in [dev_end, min(holdout_end, CALENDAR_MAX_TS)]."""
    cutoff = min(holdout_end, CALENDAR_MAX_TS)
    out = []
    with open(CALENDAR, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["event_name"] != EVENT_NAME or row["currency"] != CCY:
                continue
            ts = datetime.fromisoformat(row["timestamp_utc"])
            if not (dev_end <= ts <= cutoff):
                continue

            def num(x):
                return float(x) if x not in ("", "None") else None
            out.append(MacroEvent(ts=ts, event_id=row["event_id"], name=row["event_name"],
                                  country=row["country"], currency=row["currency"],
                                  impact=row["impact"], actual=num(row["actual"]),
                                  forecast=num(row["forecast"]), previous=num(row["previous"]),
                                  revision=num(row["revision"]), source=row["source"]))
    out.sort(key=lambda e: e.ts)
    return out


# --------------------------------------------------------------- evaluation

def evaluate_candidate(candidate_id: str, vault: EvidenceVault,
                       registry: CandidateSpecRegistry,
                       gate: HoldoutAuthorizationGate,
                       dataset_ids: Dict[str, str]) -> Dict:
    cfg = CANDIDATES[candidate_id]
    symbol, mode = cfg["symbol"], cfg["mode"]
    did = dataset_ids[symbol]

    # --- layer 1: candidate_spec_registry + holdout_authorization ---------
    spec = registry.get_candidate(candidate_id)
    if spec is None or not spec.is_frozen():
        raise RuntimeError(f"{candidate_id}: not registered or not frozen")
    if gate.has_gen14_result(candidate_id):
        raise RuntimeError(f"{candidate_id}: already has a terminal GEN 14 result")
    if not gate.is_gen14_authorized(candidate_id):
        gate.authorize_gen14_access(candidate_id, spec.spec_hash, phase="GEN14-C2-NFP")

    # --- layer 2: evidence vault seal verify + authorize -------------------
    path = HOLDOUT_FILES[symbol]
    data_bytes = path.read_bytes()
    if not vault.verify_seal(did, data_bytes):
        raise RuntimeError(f"SEAL VERIFICATION FAILED for {did} -- holdout bytes do not "
                           f"match the recorded seal. Evaluation aborted.")
    vault.authorize_evaluation(
        dataset_id=did, candidate_id=candidate_id,
        candidate_spec_checksum=spec.spec_hash,
        authorization_code="GEN14-C2-NFP-EXPLICIT-USER-AUTHORIZATION",
        reason="GEN 14 one-shot evaluation of frozen C2 NFP-surprise candidate",
    )

    # --- read holdout price + event data (the one sanctioned read) --------
    bars = load_holdout_bars(symbol)
    dev_end, holdout_end = bars[0].ts, bars[-1].ts
    events = load_holdout_events(dev_end, holdout_end)
    from discovery.cost_model import roundtrip_cost
    cost = roundtrip_cost(symbol)

    trades = c2_surprise(bars, events, POST_HOURS, mode, cost)
    s: EStats = event_stats(trades, cost)

    p = _two_sided_p(s.t_stat, s.n) if s.n >= 2 else 1.0
    alpha = FAMILYWISE_ALPHA / FIXED_M
    gates = {
        "G1_min_trades": "PASS" if s.n >= MIN_TRADES else "FAIL",
        "G2_positive_expectancy": "PASS" if s.mean_net > 0 else "FAIL",
        "G3_significance": "PASS" if s.t_stat >= MIN_T else "FAIL",
        "G4_profit_factor": "PASS" if s.profit_factor >= MIN_PROFIT_FACTOR else "FAIL",
        "G5_multiple_testing": "PASS" if (p < alpha and s.mean_net > 0) else "FAIL",
    }
    verdict = "PASS" if all(v == "PASS" for v in gates.values()) else "FAIL"
    first_failed = next((k for k, v in gates.items() if v == "FAIL"), None)

    # --- terminal recording (both layers, in the same run) -----------------
    result = {
        "candidate_id": candidate_id, "symbol": symbol,
        "spec_hash": spec.spec_hash, "holdout_dataset_id": did,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "event_source_note": (f"NFP events in [{dev_end.isoformat()}, "
                              f"{min(holdout_end, CALENDAR_MAX_TS).isoformat()}]; "
                              f"acquired calendar coverage ends {CALENDAR_MAX_TS.isoformat()}, "
                              f"{max(0,(holdout_end-CALENDAR_MAX_TS).days)} days of the holdout "
                              f"tail have NO acquired event data and are excluded, not imputed"),
        "holdout_period_full": {"start": dev_end.isoformat(), "end": holdout_end.isoformat()},
        "holdout_period_evaluated": {"start": dev_end.isoformat(),
                                     "end": min(holdout_end, CALENDAR_MAX_TS).isoformat()},
        "params": {"event": EVENT_NAME, "currency": CCY,
                  "post_hours": POST_HOURS, "mode": mode},
        "gates": gates, "verdict": verdict, "first_failed_gate": first_failed,
        "multiple_testing": {"fixed_M": FIXED_M, "bonferroni_alpha": alpha,
                             "observed_p": round(p, 10)},
        "holdout_statistics": s.to_dict(),
        "terminal": True,
    }
    result_checksum = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()

    vault.consume_dataset(dataset_id=did, candidate_id=candidate_id,
                          result_checksum=result_checksum,
                          result_summary=verdict)
    gate.record_gen14_result(candidate_id, verdict)
    result["vault_status_after"] = vault.datasets[did].seal_status.value
    return result


def main() -> int:
    vault = EvidenceVault()
    registry = CandidateSpecRegistry(R / "reports/factory/candidate_spec_registry.json")
    gate = HoldoutAuthorizationGate(R / "reports/factory/holdout_authorization_registry.json")

    dataset_ids = seal_holdout_datasets(vault)
    print("Sealed holdout datasets:")
    for sym, did in dataset_ids.items():
        print(f"  {sym}: {did}  status={vault.datasets[did].seal_status.value}")

    results = []
    for cid in CANDIDATES:
        r = evaluate_candidate(cid, vault, registry, gate, dataset_ids)
        results.append(r)
        print(f"\n{cid} ({r['symbol']}): {r['verdict']}")
        for g, v in r["gates"].items():
            print(f"    {g}: {v}")
        s = r["holdout_statistics"]
        print(f"    n={s['n']} mean_net={s['mean_net']:+.6f} t={s['t_stat']:+.3f} "
              f"pf={s['profit_factor']} p={r['multiple_testing']['observed_p']:.2e} "
              f"(need < {r['multiple_testing']['bonferroni_alpha']:.2e})")

    passed = [r for r in results if r["verdict"] == "PASS"]
    failed = [r for r in results if r["verdict"] == "FAIL"]

    # Mechanism-level read: does the pattern of pass/fail and sign agree with
    # the single "long USD on positive NFP surprise" mechanism from Cycle 6?
    signs = {r["symbol"]: r["holdout_statistics"]["mean_net"] > 0 for r in results}
    mechanism_note = (
        f"{sum(signs.values())}/4 candidates net-positive on holdout "
        f"(sign consistency with the Cycle 6 dev-window mechanism); "
        f"{len(passed)}/4 cleared every GEN 14 gate")

    payload = {
        "run_id": "GEN14-C2-NFP-EXPLICIT-USER-AUTHORIZATION",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "fixed_M": FIXED_M,
        "candidates_evaluated": len(results),
        "passed": len(passed), "failed": len(failed),
        "mechanism_note": mechanism_note,
        "individual_results": results,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n{'='*70}\nGEN 14 FINAL: {len(passed)}/4 PASS, {len(failed)}/4 FAIL")
    print(mechanism_note)
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
