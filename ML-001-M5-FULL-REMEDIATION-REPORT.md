# ML-001-R2 — M-5 FULL REMEDIATION REPORT

**Date**: August 17, 2026
**Baseline commit**: `5a97d77`
**Scope**: Fully resolve M-5 end-to-end — spec → implementation → tests → feature parity → model artifacts → provenance → reproducibility. No economic validation, no PURE_HOLDOUT, no Pine, no production authorization.

---

## 1. ORIGINAL AMBIGUITY

Spec §4 defined `rsi_14`/`atr_14`'s smoothing step in prose (an explicit seeded-Wilder recurrence) while simultaneously asserting this was *"equivalent to `ewm(alpha=1/14, adjust=False)`"* and pointing to `core/indicators.py` as the "reference implementation" to reuse directly. These two things are not the same algorithm. The prior audit (`ML-001-R2-FINAL-INTEGRITY-CLOSURE-AUDIT.md`) quantified the divergence and correctly refused to resolve it by guessing, reporting `M-5 = BLOCKED_BY_SPEC_AMBIGUITY`.

---

## 2. MATHEMATICAL COMPARISON

| | Option A: seeded Wilder | Option B: `ewm(alpha=1/14, adjust=False)` |
|---|---|---|
| Initialization | Explicit: simple mean of the first 14 values | Implicit: `y[0] = x[0]`, geometric decay from index 0 |
| Explicit deterministic spec | Yes — closed-form seed | No — depends on library internals |
| Reproducibility by hand | Yes | Requires understanding pandas' `adjust=False` semantics |
| Hidden library initialization | None | Yes |
| Transparent implementation | Yes (explicit loop/recurrence) | No (opaque library call) |
| **Pine parity** | **Matches TradingView's native `ta.rsi()`/`ta.atr()`**, which use RMA — Wilder's classic seeded moving average, the *same* algorithm as Option A | **Does not match Pine's native functions** — would create a permanent, unclosable parity gap ahead of the spec §13 Pine-conversion target |
| Auditable numerical behavior | Yes | Only via library documentation |

Empirical divergence (from the prior audit, reproduced here): up to 31% relative difference at the point RSI first becomes defined; still ~2×10⁻⁴ relative at the spec's own declared 100-bar burn-in threshold. Never exactly zero at any finite bar.

---

## 3. CANONICAL FORMULA SELECTED

**Option A — explicit seeded Wilder smoothing.**

## 4. WHY IT WAS SELECTED

Concrete, decisive evidence, not merely following the option listed first:
1. **Pine parity is the deciding factor.** TradingView's `ta.rsi()`/`ta.atr()` are documented to use RMA (Wilder's classic seeded moving average) — mathematically Option A, not Option B. Spec §13 names Pine conversion as this strategy's eventual target and §12 names FEATURE_PARITY as a formal invariant; choosing Option B today would guarantee a permanent, structural parity failure the day Pine conversion is attempted, for no benefit now.
2. Every other evaluation criterion (explicit specification, no hidden library semantics, transparent implementation, hand-auditability) favors Option A independently of the Pine consideration.
3. Option A can be implemented with zero dependency on any library's internal recursion semantics — a plain, explicit, loop-based recurrence, auditable line by line.

---

## 5. SPECIFICATION CHANGES

`ML-001-R2-CLEAN-REBUILD-SPEC.md` §4 (`rsi_14`, `atr_14`) rewritten:
- Removed the false "equivalent to `ewm(...)`" claim, with an explicit **AMENDED** note explaining what was wrong and citing this report.
- Both sections now specify, step by step: source, initialization/seed, recurrence, division-by-zero behavior (RSI only), first valid value, warmup, NaN handling, precision, and minimum data requirement — sufficient for an independent engineer to reproduce the formula without reading any source code.
- Both sections now carry an explicit **CANONICAL_NUMERICAL_ORACLE** subsection naming the exact function that is authoritative.
- A **namespacing note** added, documenting that `core/indicators.py::rsi`/`atr` are explicitly *not* the ML-001-R2 oracle and remain unmodified for unrelated strategies (RSI strategy, MACD ATR-based stops).
- §2's Identity table `feature_version` updated from `FE-R2-001` to `FE-R2-002`, with the immutability rule's own text extended to state that any `FE-R2-001`-tagged artifact used the since-corrected formula and must not be treated as `FE-R2-002`-compatible.

---

## 6. IMPLEMENTATION CHANGES

`core/features/fe_r2_001.py`:
- Removed the `from core.indicators import atr as wilder_atr` / `rsi as wilder_rsi` delegation entirely, replaced with an explicit code comment documenting why (`core/indicators.py` intentionally not touched — shared by unrelated strategies).
- Added `_seeded_wilder_smooth(values, period)` — the CANONICAL_NUMERICAL_ORACLE: an explicit, loop-based, non-vectorized recurrence implementing exactly the spec's Steps 3–4 (seed = simple mean of the first `period` values from the first non-NaN entry; then the Wilder recurrence). Raises `WilderSmoothingError` (a new, dedicated exception) on any internal NaN gap, rather than silently propagating or masking one.
- `compute_rsi_14`: rewritten to compute `delta`/`gain`/`loss` explicitly and call `_seeded_wilder_smooth`, preserving the existing (unambiguous, unrelated-to-M-5) division-by-zero convention: `RSI=100` when `avg_loss=0, avg_gain>0`; `RSI=50` when both are zero (flat market).
- `compute_atr_14`: rewritten to reuse `core/indicators.py::true_range` directly (no ambiguity in that function — a stateless per-bar maximum) and apply `_seeded_wilder_smooth` to its output.
- `get_feature_schema()`'s `definitions` dict updated to describe the new formula in the same precise, step-by-step terms.
- `FEATURE_VERSION` bumped from `"FE-R2-001"` to `"FE-R2-002"`, per the spec's own immutability rule (this is a genuine change to computed feature values, not a no-op).

No hyperparameters, target definition, trading/risk constants, or `momentum_5`/`momentum_20`/`volatility_regime` formulas were touched — `compute_momentum` and `compute_volatility_regime` were never implicated in the M-5 ambiguity.

**`core/indicators.py` was not modified** — confirmed via `git diff --stat HEAD -- core/indicators.py` returning empty. Other strategies (`strategies/base_strategy.py`, `core/strategy.py`) continue importing `core.indicators.atr` unchanged.

---

## 7. TESTS ADDED/MODIFIED

**New files**:
- `tests/test_ml_001_r2_numerical_oracle.py` (20 tests) — a worked textbook RSI example (hand-derived `RSI[14]=70.46413502109705`, cross-checked against the implementation to `1e-9`); an *independent* from-scratch reimplementation of the seeded-Wilder recurrence (never calling `_seeded_wilder_smooth`), compared against the implementation across monotonic-up, monotonic-down, flat, alternating, and 200-bar random-walk series for both RSI and ATR; warmup/initialization boundary tests; NaN-handling tests (including a disclosed, pre-existing limitation of the reused `true_range` function — see §16 below); explicit numerical tolerance policy and bit-for-bit determinism check.
- `tests/test_ml_001_r2_feature_parity_fixture.py` (6 tests) — a single fixed, deterministic 700-bar synthetic OHLC series with independently-computed expected values (via dedicated from-scratch reimplementations, not the production functions) for all five features at multiple bars, committed as a permanent regression oracle.

**Modified**:
- `tests/test_ml_001_r2_features.py`, `tests/test_ml_001_r2_walkforward.py` — updated the two hardcoded `"FE-R2-001"` assertions to `"FE-R2-002"`.
- `tests/test_ml_001_r2_adversarial.py`, `tests/test_ml_001_r2_phase7_adversarial.py` — the two tests that used `"FE-R2-002"` as a *simulated wrong* version string now use `"FE-R2-999-SIMULATED-FUTURE-VERSION"`, since `FE-R2-002` is now the real current value (both tests' *logic* is unchanged — this is a fixture-value fix required by the version bump, not a weakening).
- `tests/test_ml_001_r2_adversarial.py::TestFutureDataInjection` — added a test specifically targeting the new `_seeded_wilder_smooth` recurrence for no-lookahead behavior (in addition to the pre-existing generic all-five-features test, which also still passes unchanged).

No test was deleted or weakened. No test's assertion was loosened to accommodate the new formula — every test that changed either fixed a now-colliding placeholder string or added coverage.

---

## 8. NUMERICAL ORACLE RESULTS

| Check | Result |
|---|---|
| Textbook 15-bar RSI example | Hand-derived `70.46413502109705` == implementation, exact |
| Fresh independent hand-derivation (this report, different data) | RSI: hand `80.3030303030303` vs. implementation `80.30303030303033` (float64 rounding only) — **match**; ATR: hand `0.7714285714285671` vs. implementation `0.7714285714285671` — **exact bit match** |
| Independent reimplementation vs. production, 200-bar random walk (RSI) | Exact match at all 186 defined positions, tolerance `1e-9` |
| Independent reimplementation vs. production, 200-bar random walk (ATR) | Exact match at all 187 defined positions, tolerance `1e-9` |
| Monotonic/flat/alternating regime tests | All exact matches against independent reimplementation |
| Canonical 700-bar fixture, all 5 features at 5+ points each | All exact matches against independent, from-scratch oracles |

---

## 9. LEAKAGE RESULTS

- `TestFutureDataInjection::test_features_up_to_t_are_unaffected_by_bars_after_t` (pre-existing, generic across all 5 features) — still passes unchanged with the new formula.
- New, `_seeded_wilder_smooth`-specific test added: appending 200 future bars leaves `rsi_14`/`atr_14` at every prior timestamp bit-for-bit identical.
- `target_r2.py`'s `close.shift(-1)` remains the only future-looking operation anywhere in the feature/target codebase — confirmed unchanged (feature module modifications did not touch `target_r2.py`).
- `assert_no_leakage` remains wired into the authoritative path (`build_training_set`, called from `generate_oos_predictions` for every walk-forward window) — confirmed by re-running the full `test_ml_001_r2_leakage_integration.py` suite (7 tests, including the mock-spy proof that it actually executes), all passing unchanged.

---

## 10. ARTIFACT INVALIDATION DECISION

**Searched the entire repository and full git history** for any persisted model artifact: `find ... -iname "*.joblib"`, `git log --all --diff-filter=A --name-only | grep joblib`, and a check for `models_ml/`/`reports/ml_001_r2/` directories — all returned empty. **No trained model artifact has ever been committed or persisted anywhere.** Every model produced by any prior test run existed only transiently (in-memory or inside a `tempfile.TemporaryDirectory()` context) and was discarded when that process ended.

**Decision**: `OLD MODEL ARTIFACTS = INVALIDATED` is the structurally correct policy and is now automatically enforced — `RFR2Model.load()`'s M-8 check rejects any artifact whose recorded `feature_version` is not `FE-R2-002`. In practice there is nothing to mark or move, since nothing was ever persisted to invalidate. This is disclosed explicitly rather than silently assumed away: **the invalidation guarantee is preventive/structural, not an active remediation of real files.**

---

## 11. RETRAINING RESULTS

A synthetic verification run (explicitly not economic validation) was executed end-to-end on 3,500 synthetic bars (`tests/r2_fixtures.py::make_synthetic_ohlcv`, seed `20260817`):

```
feature_version:  FE-R2-002
model_version:    RF-R2-001
hyperparameters:  {bootstrap: true, class_weight: balanced, criterion: gini, max_depth: 6,
                    max_features: sqrt, min_samples_leaf: 25, min_samples_split: 50,
                    n_estimators: 300, random_state: 42}
feature_order:    [momentum_5, momentum_20, rsi_14, atr_14, volatility_regime]

dataset_checksum:     64444698d20250dfbee346988760df50d4e96fea51e62b0f587aa8972099a082
feature_schema_hash:  10f07b3eca3c835a0ce09772777d4159e3ef549803e38fc68d0654faf84b80f1
model checksum (full-df model):  fcea94283a450c004a332abdd174980b49c9e0dfd03e27833cae695cb280700b
training_rows:  2,899   class_balance: {0.0: 1416, 1.0: 1483}

Save -> load (through the M-8 feature_version/feature_order checks) -> predict:
  identical predictions confirmed, checksum round-trips exactly.

Walk-forward: 7 windows, 7 OOS batches, 7 complete RunProvenance records
  (each independently .validate_complete()'d), 2,100 total OOS predictions.
```

No `PURE_HOLDOUT` data was accessed. No economic metric (Sharpe, PF, drawdown, win rate) was computed or claimed.

---

## 12. REPRODUCIBILITY RESULTS

The complete verification script above was run twice, as two genuinely separate `python3` process invocations. Full text-diff of both runs' output: **zero differences** — every value (dataset checksum, feature schema hash, full-df model checksum, all 7 per-window model checksums, all 7 training periods, class balance, save/load round-trip checksum) was bit-for-bit identical across the process boundary.

---

## 13. FULL TEST COUNTS

```
R2 test suite:          186 tests collected, 186 passed, 0 failed   (before this phase: 159)
Full repository suite:  488 tests collected, 488 passed, 0 failed   (before this phase: 461)
```

Net new tests: 27 (`test_ml_001_r2_numerical_oracle.py` ×20, `test_ml_001_r2_feature_parity_fixture.py` ×6, plus one new lookahead-specific adversarial test). Exit code `0` for both suites, confirmed via `$?`. No test skipped. No assertion weakened. No test deleted for conflicting with the old implementation — the two tests whose fixture values collided with the new real `FEATURE_VERSION` had that fixture value changed to a clearly-synthetic placeholder, not their logic altered.

---

## 14. INDEPENDENT AUDIT RESULTS (A–H)

| Item | Result |
|---|---|
| A. Specification formula | Re-read fresh; confirmed internally consistent (no remaining false-equivalence claim), matches implementation line-for-line |
| B. Implementation formula | Re-read `fe_r2_001.py` fresh; confirmed `_seeded_wilder_smooth`'s seed-then-recurrence logic matches spec Steps 3–4 exactly |
| C. Numerical oracle | Two independent by-hand derivations performed *for this report specifically* (not reused from earlier test-writing) — both match the implementation exactly (§8) |
| D. Feature pipeline | `build_feature_matrix` → `compute_rsi_14`/`compute_atr_14` wiring confirmed via the canonical 700-bar fixture test, all 5 features cross-checked simultaneously at bar 650 |
| E. Model training | Confirmed via the Phase 9/10 verification runs — trains successfully, schema-validated, checksummed |
| F. Artifact metadata | Confirmed `ModelMetadata.feature_version == "FE-R2-002"` is recorded and that `RFR2Model.load()` rejects any other value (pre-existing M-8 enforcement, re-verified still functions with the new version string) |
| G. Provenance | Confirmed all 7 `RunProvenance` records from the verification run pass `.validate_complete()` and reference the actual dataset/model/schema checksums produced by that run, not placeholder values |
| H. Reproducibility | Confirmed bit-for-bit identical across two separate process invocations (§12) |

---

## 15. REMAINING FINDINGS

All prior open items unaffected by this phase, restated for completeness:
- **M-2**: checksum mechanism still cannot detect a coordinated model+metadata substitution (unchanged, disclosed, not in scope of M-5).
- **M-3**: data-state trust boundary remains a documented residual limitation per spec §8's declaration-gated design (unchanged).
- **L-3**: file-layout convention for the separate training-manifest file remains open, deprioritized (unchanged).
- **New, disclosed limitation surfaced during this remediation**: `core/indicators.py::true_range`'s `.max(axis=1)` call defaults to `skipna=True`, so a NaN in only one of `high[t]`/`low[t]` (not both) is silently absorbed into a plausible-but-incorrect True Range value rather than propagating as NaN. This is pre-existing behavior of code this remediation deliberately did not modify (shared with unrelated strategies), documented and tested (`test_single_column_nan_is_silently_absorbed_by_true_range`) rather than silently left undiscovered.

None of these block the M-5 verdict below, and none were introduced by this remediation.

---

## 16. GOVERNANCE STATE

```
ML-001-R2         = RESEARCH_ONLY / NOT_AUTHORIZED   (unchanged)
ECONOMIC_VALIDITY = UNPROVEN                          (unchanged — no economic validation performed)
PRODUCTION        = BLOCKED                           (unchanged)
PINE_CONVERSION   = BLOCKED                           (unchanged)
```

No PURE_HOLDOUT data was accessed. No real/economic market data was used anywhere in this phase — the verification run used the same synthetic fixture generator as every prior test. No Pine Script was generated. No production authorization occurred. Improved technical/numerical integrity is not evidence of profitability and is not claimed as such. No old ML-001 performance numbers were reused. No Sharpe/PF/PBO validity is claimed.

---

## MANDATORY FINAL STATE

# M-5 = **CLOSED**

All eight closure conditions are met:
1. Exactly one canonical RSI definition exists (`_seeded_wilder_smooth` via `compute_rsi_14`) — the old `core.indicators.rsi` delegation was removed, not merely deprecated.
2. Exactly one canonical ATR definition exists (`_seeded_wilder_smooth` via `compute_atr_14`).
3. Spec and implementation agree — verified line-by-line, §14 item A/B.
4. The independent numerical oracle agrees — two fresh hand derivations plus 20 dedicated reimplementation-based tests plus a 6-test canonical fixture, all exact.
5. The feature pipeline uses the canonical implementation exclusively — confirmed via `build_feature_matrix`.
6. Leakage checks pass — confirmed, including a new formula-specific test.
7. Affected artifacts were correctly assessed — none existed to invalidate; the version bump (`FE-R2-001` → `FE-R2-002`) provides forward-looking, automatically-enforced protection via the pre-existing M-8 check.
8. Fresh-process reproducibility passes — bit-for-bit identical across two separate process invocations.
9. The full test suite passes — 186/186 R2, 488/488 repository-wide, zero regressions.

---

**GOVERNANCE UNCHANGED**: `RESEARCH_ONLY / NOT_AUTHORIZED`. `ECONOMIC_VALIDITY = UNPROVEN`. `PRODUCTION = BLOCKED`. `PINE_CONVERSION = BLOCKED`. This report closes a technical-integrity finding; it does not authorize, and should not be read as authorizing, any economic or production gate.
