# ML-001-R2 — Real-Data Training & Walk-Forward Report

**Date**: August 18, 2026
**Repository state**: builds on commit `c878553` (FE-R2-003 gap-admission fix + Strategy Factory foundation, landed by a concurrent session and independently verified here, not duplicated), through this session's own commits `9eceb47` and this report's commit.
**Headline result**: **NO EDGE FOUND.** The first genuine, real-market, out-of-sample walk-forward evaluation of RF-R2-001/ML-001-R2 in this project's history shows a consistent, distributed, real loss on both EURUSD and GBPUSD. This is reported as a valid scientific outcome, not optimized away, not hidden.

---

## 0. Reconciling with concurrent work

Before any of this session's own work, two commits appeared on this branch that this session did not make (`a68bd05`, `c878553`), resolving the exact gap-semantics blocker previously reported and building Strategy Factory infrastructure (`core/factory/*`). Rather than duplicate or override this, it was independently verified: `build_feature_matrix` was re-run directly against the real EURUSD/GBPUSD CSVs (succeeds, 502/499 gaps admitted and logged, zero silent repairs), and the full test suite was re-run (591/591 passing, confirmed twice more since). All subsequent work in this report builds on that verified foundation.

---

## 1. Leakage / provenance audit (Phase 3, pre-training)

Full detail: `ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md`. Summary: **all checks PASS**.

- Chronological ordering, zero duplicates.
- `build_training_set()` (fail-closed `assert_no_leakage()` internally): clean, 56,999 usable EURUSD rows.
- Future-data-injection check specific to this real dataset: 0 mismatches across 5 features × 28,800 rows.
- Temporal split (60/20/20, strictly chronological): DEVELOPMENT 2012-11-16→2018-06-19 (34,560 bars), VALIDATION →2020-04-29 (11,520 bars), HOLDOUT →2022-03-05 (11,520 bars). Zero overlap between any pair.
- `HoldoutAccessGuard` tested against a deliberate unauthorized-access attempt and correctly rejected it before being relied on.
- Disclosed (non-leakage) finding: 502/57,600 label rows span an admitted gap rather than a clean 1-hour move — statistical heterogeneity, not a violation.
- **Structural guarantee**: every training/walk-forward call in this report is passed `pd.concat([development, validation])` only — PURE_HOLDOUT rows are never present in the object being operated on, not merely runtime-guarded against.

---

## 2. Canonical training (Phase 4)

Two real RF-R2-001 models were trained — the first genuine fits on real market data in this project's history — one per symbol, on the DEVELOPMENT partition only, at the frozen spec hyperparameters (`n_estimators=300, max_depth=6, min_samples_split=50, min_samples_leaf=25, max_features="sqrt", class_weight="balanced", random_state=42`), never tuned.

| Symbol | Model artifact | Checksum | Training rows | Class balance |
|---|---|---|---|---|
| EURUSD | `models/ml_r2/RF-R2-001_EURUSD_canonical.joblib` | `5c4f90a7...` | 33,959 | {0: 17041, 1: 16918} |
| GBPUSD | `models/ml_r2/RF-R2-001_GBPUSD_canonical.joblib` | `0181aa0e...` | (comparable) | (near 50/50) |

**Reproducibility, independently verified** (not assumed from the spec's claim that `n_jobs=1` guarantees it): 3 separate fresh-process retrains of EURUSD, and 2 of GBPUSD, matched their respective saved checksums exactly, byte for byte.

**A genuine, reproducible non-determinism source was found and documented, not swept aside**: in a single Python process, calling `.load()` + `.predict_proba()` on one `RFR2Model` instance measurably changes the checksum of a *different* `RFR2Model` instance subsequently `.train()`ed in that same process (reproduced twice, deterministically — same wrong checksum both times). Predictions from two consecutive clean trains (no intervening load/predict) were bit-identical (`np.array_equal`, `max diff = 0.0`) and matched their feature_importances_ exactly. Root cause not isolated further (candidate: BLAS/thread-pool warm-up state affecting floating-point summation order deep in tree-building, despite `n_jobs=1`) — reported as a real, disclosed sensitivity to prior process activity, not to training inputs or seed. The two artifacts committed here were trained cleanly (no such interference) and are the ones verified reproducible above.

Registered in the Strategy Factory registry (`STRAT-000001`, `TRAINED`), reusing the concurrently-built infrastructure rather than a parallel mechanism.

---

## 3. Walk-forward out-of-sample evaluation (Phase 6/7)

Per spec §9's steady-state protocol: 24-month trailing training window, 1-month test window, monthly step (515 bars/month average, computed empirically from this real dataset's own bar density — forex is open ~5/7 of the week, so 730 nominal hourly bars/month × 5/7 ≈ 521, matching the observed 515 closely). One disclosed simplification: the spec's asymmetric "12-month *first* window, 24-month thereafter" rule was not implemented — every window, including the first, used the full 24-month window (a strictly *more* data-hungry, not less rigorous, choice than the spec's minimum).

**65 windows per symbol, entirely within `DEVELOPMENT ∪ VALIDATION`** (2012-11-16 → 2020-04-29). PURE_HOLDOUT (2020-04-29 → 2022-03-05) was never present in the data object passed to the engine — physically excluded, not merely access-guarded. Each window trained one fresh RF-R2-001 instance on its own trailing 24 months (never touching that window's own test period or anything later), then generated genuine OOS predictions for the following month, then those predictions were run through the **unmodified, canonical `core/ml_r2/backtest_r2.py::run_backtest`** (§10 position sizing / SL / TP / max-hold / exit-priority mechanics — reused, not reimplemented) to produce real trade records.

### Aggregate results (every trade from every window, no cherry-picking)

| Metric | EURUSD | GBPUSD |
|---|---|---|
| Trade count | 1,387 | 1,452 |
| Win rate | 39.37% | 39.39% |
| Gross profit | $144,857.67 | $153,701.26 |
| Gross loss | −$164,838.22 | −$172,290.41 |
| **Net profit** | **−$19,980.55** | **−$18,589.15** |
| **Profit factor** | **0.879** | **0.892** |
| **Expectancy / trade** | **−$14.41** | **−$12.80** |
| Average win | $265.31 | $268.71 |
| Average loss | −$196.00 | −$195.78 |
| Exit reasons | STOP_LOSS 816, TAKE_PROFIT 379, SIGNAL_REVERSAL 129, MAX_HOLD 63 | STOP_LOSS 858, TAKE_PROFIT 403, SIGNAL_REVERSAL 112, MAX_HOLD 79 |

**No cherry-picking, checked explicitly**: 65/65 windows produced at least one trade for both symbols (mean 21.3/window EURUSD, 22.3/window GBPUSD — not a thin sample). Per-window net P&L: **55.4%** of EURUSD windows and **67.7%** of GBPUSD windows were individually net-negative — this is not one bad window dragging down an otherwise-working average. Correlation between window index (time) and window P&L: 0.058 (EURUSD), −0.049 (GBPUSD) — essentially zero; performance is not trending better or worse over the ~5.5-year OOS span, it is consistently unprofitable throughout.

**A separate, mechanical finding, disclosed but not economically material to the verdict above**: because `run_backtest`'s position sizing is 2%-of-*current*-equity and this backtest continues trading past the point where cumulative real losses exceed the $10,000 starting equity (final equity went negative for both symbols), the reported max-drawdown figures exceed −100% and are not economically interpretable past that point — a real broker account would have been stopped by a margin call long before this. This is a robustness/engine-realism observation for a future phase, not a leakage or correctness defect, and does not change the sign or persistence of the result established above (the strategy was already, clearly, unprofitable well before equity turned negative).

---

## 4. Search history — no optimization toward a passing result

Per the instruction that every attempt be recorded and that a failed candidate is scientifically valid:

- **One** strategy candidate exists (`STRAT-000001`, ML-001-R2, the single pre-specified hypothesis from `ML-001-R2-CLEAN-REBUILD-SPEC.md` — not drawn from a search space).
- **One** hyperparameter configuration was ever used — the frozen spec configuration. It was never varied, tuned, or re-run with different settings in search of a better result.
- **130** individual model-training events occurred (65 windows × 2 symbols), each with a distinct 24-month trailing training window (a legitimate, spec-mandated form of "many training attempts," not a hyperparameter search) — every one recorded with its own model checksum, dataset checksum, training period, and code version in `reports/ml_r2_real_data/WALKFORWARD_{EURUSD,GBPUSD}.json`.
- `StrategyRegistry.search_history_summary()`: `total_strategies_tested=1, total_strategies_rejected=1, total_strategies_passed=0, selection_bias_status="UNACCOUNTED"` (correctly *not* claimed as "no bias" — with exactly one candidate, there is nothing to select among, so the question is moot, not resolved-clean).
- The result was **not** used to trigger a second attempt with different parameters. `STRAT-000001` was transitioned directly to `REJECTED` from `TRAINED` (a structurally legal transition — any state in the spine may move to `REJECTED`), with the full walk-forward evidence attached as the reason.

---

## 5. Open item, flagged rather than resolved (per "stop only for a genuine unresolved specification/governance decision")

The Strategy Factory state machine's declared forward spine places `HOLDOUT_TESTED` *before* `OOS_TESTED`/`WFA_TESTED`. This appears to conflict with this project's own, repeatedly-established discipline that PURE_HOLDOUT is opened exactly once, only after every other gate has already been passed. This report does not resolve that conflict — `STRAT-000001` was rejected via the always-legal `TRAINED → REJECTED` path specifically so that no `HOLDOUT_TESTED` claim would need to be made (true or fabricated) to record this real result. Left for explicit resolution: does `HOLDOUT_TESTED` in this state machine mean something other than "PURE_HOLDOUT was accessed" (e.g. a distinct, smaller in-sample check), or should the spine's ordering be corrected?

---

## 6. Tests

```
python3 -m pytest -q   →   591 passed, 0 failed, 0 skipped
```
Unaffected by this session's work (no canonical code modified). **Software test evidence only** — none of these 591 tests execute against the real EURUSD/GBPUSD data or compute an economic metric; the walk-forward/training results above come from direct script execution, recorded in the JSON artifacts cited throughout, not from the test suite.

---

## 7. Final status

```
STRATEGY = ML-001-R2 (STRAT-000001)
REAL_MARKET_DATA        = TRUE
MODEL_ARTIFACT           = TRUE (RF-R2-001, both symbols, checksummed, independently reproduced)
LEAKAGE_AUDIT            = PASS
PURE_HOLDOUT             = NOT ACCESSED (by design; structurally excluded, not just guarded)
OOS_VALIDATION (walk-forward, VALIDATION period) = COMPLETE
  EURUSD: profit_factor=0.879, expectancy=-$14.41/trade, net=-$19,980.55 (1,387 trades, 65/65 windows)
  GBPUSD: profit_factor=0.892, expectancy=-$12.80/trade, net=-$18,589.15 (1,452 trades, 65/65 windows)
EDGE_STATUS = NOT_PROVEN — real evidence now points toward FAIL, not merely INSUFFICIENT_EVIDENCE,
              though this single walk-forward pass (one dataset, one split, no robustness/cost-stress/
              statistical-significance layer yet) is not alone sufficient for a final EVG verdict
CANDIDATE_STATE = REJECTED (STRAT-000001, Strategy Factory registry)
PRODUCTION = BLOCKED
```

No hyperparameter was tuned toward a passing result. No holdout data was accessed. No trade, backtest metric, or model artifact was fabricated. The result is unfavorable and is reported as such.
