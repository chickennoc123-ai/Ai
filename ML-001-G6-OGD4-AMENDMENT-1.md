# ML-001 OGD-4 AMENDMENT 1: PRIMARY HOLDOUT IDENTITY + SEAL

**Date**: 2026-08-19
**Authorized by**: Owner (explicit selection: "Tái audit HistData rồi seal")
**Status**: EXECUTED — sealed and fresh-process verified

---

## 1. What changed and why

### 1.1 The prior HistData rejection was based on a measurement error

The earlier verdict (ML-001-G6-HISTDATA-FINAL-ELIGIBILITY.md: "REJECT — 68.9%
coverage, 877 trading-hour gaps") was wrong. Root cause: **HistData timestamps
are EST (GMT-5, fixed, no DST), and the aggregation mislabeled them as UTC.**
Ordinary forex weekends (Fri 17:00 → Sun 17:00 EST) were therefore
misclassified as trading-hour gaps. Measured against the true 24/5 forex week,
the supplied data covers ~96.5% of trading hours.

### 1.2 A second defect: unverified temporal-independence claim

Prior audit reports claimed "no overlap with DEVELOPMENT" — but the aggregated
file started 2022-01-02 while DEVELOPMENT ends 2022-03-05 (the audit phase that
should have caught this had crashed, and the report was written as PASS
anyway). The overlap is real and is removed by trimming.

### 1.3 2023 source file is degraded

The owner-supplied 2023 M1 file has ~830 whole trading hours absent (~13% of
2023, alternating-hour holes on many weekdays; 322,638 rows vs ~372,000 for
other years). Bars that exist are well-formed (99.2% built from ≥50 minutes),
but the missing hours materially break evaluation continuity. 2022, 2024,
2025, 2026 have 0–5 residual missing hours each.

**Decision**: 2023 is excluded from the primary holdout (SOURCE_DEGRADED).

## 2. Amended holdout identity

| Field | Previous (OGD-4) | Amended (this document) |
|---|---|---|
| Source | Dukascopy Bank SA (bytes never acquired) | HistData.com M1, owner-supplied, EST→UTC corrected, deterministic H1 aggregation |
| Instrument / TF / TZ | EURUSD / H1 / UTC | unchanged |
| Period | 2022–2026 (intended) | **2024-01-01 → 2026-01-30** (contiguous, clean) |
| Independence | LEVEL_3 (unseen time period) | LEVEL_3 confirmed: no overlap with DEVELOPMENT (…2022-03-05) or PURE_HOLDOUT (2021) |

Dukascopy remains a welcome future cross-check (LEVEL_5 source independence)
but is no longer the blocker.

## 3. Sealed artifact

```
DATASET_ID   = DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130
FILE         = data/holdout/EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv
BARS         = 12,972      (2024-01-01T22:00Z → 2026-01-30T21:00Z)
SHA256       = ccc056b26afafbc8...  (full value in reports/factory/g6_holdout_seal_result.json)
COVERAGE     = 99.3% of true trading hours
RESIDUAL     = 5 unexplained missing hours (0.04%)  [gate limit: 1%]
OHLC ERRORS  = 0
GATES        = source ELIGIBLE / integrity PASS / independence NONE+ZERO / decision ELIGIBLE
SEAL         = EvidenceVault (reports/factory/evidence_vault.json), fresh-process verified,
               tamper-detection confirmed
EVALUATION   = NOT_AUTHORIZED (one-time authorization required before any consumption)
```

Pre-registered economic gate (fixed before measurement): coverage ≥ 95% of
trading hours AND residual unexplained missingness ≤ 1%. Result: PASS
(99.3% / 0.04%).

## 4. Preserved segments (not sealed, not exposed)

- `data/holdout/EURUSD_H1_SECONDARY_20220306_20221231_UTC.csv` — 5,159 clean
  bars; reserved for possible future confirmatory/robustness use. Firewalled
  from research until governance says otherwise.
- 2023 — quarantined (SOURCE_DEGRADED). Not for evaluation. The owner may
  re-download the 2023 archive from HistData if a repaired file becomes
  available; it would need its own audit.
- 2022-01-02 → 2022-03-05 — discarded from evaluation use (DEVELOPMENT overlap).

## 5. Firewall rules now in force

1. The sealed holdout is invisible to hypothesis/candidate generation (GEN 7–11).
2. One-time evaluation requires `authorize_evaluation()` with a frozen
   candidate spec checksum; consumption is terminal.
3. Any byte change breaks the seal (verified).
4. No research code may read `data/holdout/` — enforcement is procedural plus
   seal verification at evaluation time.

## 6. Reproduction

```
python3 scripts/ml_001_g6_holdout_rebuild_and_seal.py   # deterministic
python3 -m pytest tests/test_g6_holdout_seal.py -q      # 21 tests
```
