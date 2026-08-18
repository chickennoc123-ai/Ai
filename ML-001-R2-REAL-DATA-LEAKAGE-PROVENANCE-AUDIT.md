# ML-001-R2 — Real-Data Leakage & Provenance Audit (Phase 3, pre-training)

**Date**: August 18, 2026
**Scope**: `data/csv/EURUSD_H1.csv` (57,600 rows, 2012-11-16 → 2022-03-05), run before any model was trained on real data, per the explicit instruction to audit before training.
**Status**: all checks **PASS**. No leakage found. One non-leakage statistical-heterogeneity finding is disclosed (§4). Training proceeded only after this audit completed cleanly.

This audit builds on, and does not re-litigate, the concurrent FE-R2-003 gap-admission work (`ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md`, `ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md`) already merged onto this branch — its temporal-continuity vocabulary (calendar/market-session/observed-bar continuity) is reused directly rather than re-derived.

---

## 1. Temporal ordering

```
monotonic increasing: True
duplicate timestamps: 0
```
PASS.

## 2. Leakage — canonical, fail-closed check

`core.ml_r2.target_r2.build_training_set()` — which unconditionally runs `assert_no_leakage()` internally before returning — was called directly against the full real series (not bypassed, not mocked):

```
X, y = build_training_set(df)   # 56,999 usable rows
```

Ran to completion with no `LabelConstructionError`. This means the labels are provably reconstructible from `close.shift(-1)` alone — no other information (future or otherwise) contaminated label construction for this real dataset. PASS.

## 3. Future-data-injection check (real-data-specific, not previously run against this file)

Split the real series at its midpoint; computed features on the short half; recomputed features on the full series and re-sliced to the short half's index; compared element-by-element.

```
0 mismatched rows across 5 features × 28,800 rows
```

Confirms no feature at any bar `t` changes when bars after `t` are appended — including specifically through an admitted gap boundary (the split point was not chosen to avoid gaps). PASS — no look-ahead, real-data case.

## 4. Gap-adjacent label/feature heterogeneity — disclosed, not a leakage violation

502 label rows (out of 57,600) have `label[t]` computed across an FE-R2-003-admitted gap rather than a normal 1-hour move (i.e., `close[t+1]` in the row-indexed sense is not `close` one wall-clock hour after `close[t]` — most commonly a weekend or holiday closure). This is **not** leakage: `label[t]` still depends only on `close[t+1]`, never on anything later. It is a genuine **statistical heterogeneity** — a small subset of "1-bar" observations actually span a multi-day real-world gap — consistent with, and an extension of, the feature-level finding already documented in `ML-001-PHASE-1A-TEMPORAL-SEMANTICS-CONTRACT.md` §2 for `momentum_5`/`momentum_20`/`atr_14` gap-adjacency. 502/57,600 = 0.87% of rows. Not remediated here (remediating it — e.g., excluding gap-adjacent rows from training — would itself be a specification decision about what "1-bar" is allowed to mean, out of scope for an audit) but disclosed so it cannot be mistaken for a clean, homogeneous sample.

## 5. Temporal split integrity

```
compute_temporal_split(df)  (60% / 20% / 20%, strictly positional/chronological)

DEVELOPMENT: 2012-11-16 05:00 → 2018-06-19 23:00  (34,560 bars)
VALIDATION:  2018-06-20 00:00 → 2020-04-29 15:00  (11,520 bars)
HOLDOUT:     2020-04-29 16:00 → 2022-03-05 04:00  (11,520 bars)

Overlaps: dev/val = 0, val/holdout = 0, dev/holdout = 0
```
PASS — a clean, non-overlapping, strictly chronological three-way split.

## 6. HoldoutAccessGuard actually protects (verified, not assumed)

```python
guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-REAL-DATA-RUN-1")
guard.validate(DataState.PURE_HOLDOUT, DataAccessAction.SELECTION)
# -> DataStateViolationError: Cannot use PURE_HOLDOUT for SELECTION
#    (allowed_actions=['FINAL_EVALUATION'])
```
The guard was exercised against a deliberately unauthorized access pattern and correctly rejected it, before being trusted for the actual run. `guard.holdout_opened == False` throughout this audit — holdout was never opened.

## 7. Structural guarantee used for all subsequent training/walk-forward work

Rather than rely solely on `HoldoutAccessGuard`'s runtime check, the walk-forward and canonical training runs that follow this audit pass **only** `pd.concat([split.development, split.validation])` to `make_walk_forward_windows`/`generate_oos_predictions` — `split.holdout`'s rows are never present in the DataFrame handed to any training or window-generation call. This is a second, structural (not just procedural) guarantee: even a bug in the runtime guard could not cause holdout rows to be trained on or selected against, because those rows are physically absent from the object being operated on.

---

## Machine-readable summary

`reports/ml_r2_real_data/LEAKAGE_PROVENANCE_AUDIT_EURUSD.json`

```json
{
  "monotonic": true,
  "duplicate_timestamps": 0,
  "build_training_set_rows": 56999,
  "future_injection_check": "PASS",
  "gap_adjacent_label_count": 502,
  "total_label_rows": 57600,
  "development_bars": 34560,
  "validation_bars": 11520,
  "holdout_bars": 11520,
  "split_overlaps": {"dev_val": 0, "val_holdout": 0, "dev_holdout": 0},
  "holdout_guard_rejects_unauthorized_access": true,
  "holdout_ever_opened_this_audit": false
}
```

**Verdict: no leakage detected. Safe to proceed to training, subject to the structural holdout exclusion in §7 being honored by every subsequent script (verified by direct inspection of each script that follows this audit, not merely by convention).**
