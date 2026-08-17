# ML-001-R2 IMPLEMENTATION INTEGRITY REMEDIATION REPORT

**Date**: August 17, 2026
**Baseline commit**: `5ef88a1` (ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md)
**Scope**: Remediate ONLY the findings covered by the governing instruction's Phases 2–6 — the spec §7 contradiction (C-1), `assert_no_leakage` wiring (M-1), `RunProvenance` wiring (M-9), feature-schema-file wiring (M-7), and checksum-semantics wording verification (Phase 6). No economic validation, no PURE_HOLDOUT access, no real data, no Pine, no hyperparameter/feature/target/trading-constant changes.

**No STOP condition was triggered.** Spec §7's calendar was sufficiently defined by its own text (the Weekend policy row gives explicit UTC boundaries), so gap detection could be implemented without inventing a new calendar rule. No remediation altered a hyperparameter, feature formula, target definition, or trading/risk constant.

---

## PHASE 1 — FORENSIC BASELINE (independently re-verified, not assumed)

| Item | Value |
|---|---|
| Baseline commit | `5ef88a1f5fe9b58f27d913e3cdea86420c0ef6a8` |
| Baseline `git status` | clean |
| Baseline full repo test count | 395 (collected via `pytest tests/ --co`) |
| Baseline R2 test count | 93 |
| Baseline implementation files | `core/features/fe_r2_001.py`; `core/ml_r2/{model,target,walkforward,backtest,provenance}_r2.py` |
| Baseline governance state | `RESEARCH_ONLY` / `NOT_AUTHORIZED` (from `ML-001-R2-CLEAN-REBUILD-SPEC.md` §14, unchanged by any commit since) |

---

## FINDING-BY-FINDING REMEDIATION

### C-1 — Spec §7 weekday-gap contradiction

**Original finding**: Spec §7 requires weekday gaps >1 bar to be flagged as a data-quality violation; the implementation silently tolerated all gaps, and a passing test (`test_a_gap_in_the_index_does_not_corrupt_downstream_computation`) explicitly locked in the opposite behavior.

**Root cause**: `fe_r2_001.py::_validate_ohlcv` checked for duplicate timestamps and monotonicity but never checked for gaps at all.

**Interpretation applied (no invention)**: Spec §7's Weekend policy row gives an explicit, sufficient calendar: *"FX market closed Fri 22:00 UTC – Sun 22:00 UTC."* No other calendar exception exists anywhere in the spec, so none was invented. "Gap >1 bar" was read literally as "the elapsed time between two consecutive bars exceeds one H1 bar-width" — the most literal, zero-invented-threshold reading (any missing bar at all, not a tolerance-of-N scheme, which the spec text does not support).

**Code changed**: `core/features/fe_r2_001.py` — added `_is_weekend_closure_time(ts)` (a direct, exact implementation of the Fri-22:00–Sun-22:00 UTC boundary) and `_check_weekday_gaps(index)` (enumerates every expected-but-missing H1 timestamp between consecutive bars; raises `FeatureEngineeringError` unless every missing timestamp falls inside the weekend closure). Wired into `_validate_ohlcv`, so it runs on every call to `build_feature_matrix`.

**Tests added/changed**:
- `tests/test_ml_001_r2_data_quality.py` (new, 20 tests): direct unit tests of the calendar predicate (Friday 21:00 vs. 22:00 vs. Sunday 22:00 boundaries), valid continuous data, legitimate full-weekend gaps, single and multiple unexpected weekday gaps, mixed weekend+weekday gaps, and boundary conditions (exactly 1 bar-width vs. 2).
- `tests/test_ml_001_r2_adversarial.py::TestMissingBars` — the old permissive test was replaced with `test_an_arbitrary_weekday_gap_is_now_rejected` (asserts the new, correct behavior) and a new `test_a_genuine_weekend_gap_does_not_corrupt_downstream_computation` (constructs a real Friday-close-to-Sunday-reopen gap and confirms it is still tolerated).

**Independent verification**: Five hand-constructed boundary scenarios were manually traced before any test was written (continuous data, a full legitimate weekend gap, a simple weekday gap, a gap starting 1 hour *before* Friday close, a gap ending 1 hour *after* Sunday reopen) — all five produced the exact expected accept/reject outcome. Re-confirmed by `grep`: `_check_weekday_gaps` is called from `_validate_ohlcv`, which every call to `build_feature_matrix` invokes.

**Status: CLOSED.**

---

### M-1 — `assert_no_leakage` not wired into the real pipeline

**Original finding**: `assert_no_leakage` existed and was unit-tested but had zero call sites outside its own test file.

**Root cause**: No function in the codebase composed `build_feature_matrix` → `compute_label` → `assert_no_leakage` → `align_features_and_labels` as a single, mandatory sequence; each caller (`generate_oos_predictions`) called the pieces separately and had never been told to also call the guard.

**Code changed**: `core/ml_r2/target_r2.py` — added `build_training_set(ohlcv)`, the new single authoritative entry point from raw OHLCV to a trainable `(X, y)`. It unconditionally computes features, computes labels, calls `assert_no_leakage`, and only then aligns — a caller cannot obtain `(X, y)` through this function without the check running. `core/ml_r2/walkforward_r2.py::generate_oos_predictions` was changed to call `build_training_set` for every window's training slice, replacing its previous three separate calls.

**Tests added**: `tests/test_ml_001_r2_leakage_integration.py` (new, 7 tests) proves, per the instruction's own A/B/C/D checklist:
- **A**: clean data proceeds through both `build_training_set` and `generate_oos_predictions`.
- **B**: a label series tampered *after* `compute_label` produces it but *before* `assert_no_leakage` checks it (via a call-count-based `unittest.mock.patch` that leaves `assert_no_leakage`'s own independent recomputation untampered) causes both `build_training_set` and `generate_oos_predictions` to raise `LabelConstructionError` — not silently return a corrupted `(X, y)`.
- **C**: `compute_label`'s legitimate `close.shift(-1)` is confirmed to proceed normally — it is the ground truth `assert_no_leakage` checks against, not a violation of it.
- **D**: `assert_no_leakage` is proven to actually execute — via `unittest.mock.patch(..., wraps=...)` spies — exactly once per call to `build_training_set`, and exactly once *per walk-forward window* (not once total) inside `generate_oos_predictions`.

**Independent verification**: `grep -n "assert_no_leakage" core/ml_r2/target_r2.py core/ml_r2/walkforward_r2.py` shows the function is both defined and *called* (line 119 of `target_r2.py`), not merely referenced in a docstring. A design note worth recording: my first attempt at test B patched `compute_label` globally, which — because `assert_no_leakage` itself calls `compute_label` internally to recompute its ground truth — tampered both sides of the comparison identically and produced a false pass. This was caught by manually reasoning through the call graph before trusting the test, and fixed with a call-count-based side effect that only tampers `build_training_set`'s own first call.

**Status: CLOSED.**

---

### M-9 — `RunProvenance` not wired into the real pipeline

**Original finding**: `RunProvenance` was implemented and unit-tested in isolation but never constructed by `RFR2Model.train()` or `generate_oos_predictions()`.

**Root cause**: No canonical `strategy_id`/`strategy_version` constants existed to source values from (tied to Finding I-5), and no function computed the auxiliary values (`dataset_checksum`, `code_version`, `config_checksum`, `feature_schema_hash`) a complete record requires.

**Code changed**:
- `core/ml_r2/provenance_r2.py` — added `STRATEGY_ID = "ML-001-R2"`, `STRATEGY_VERSION = "1.0.0"` (closing Finding I-5 as a byproduct) and `get_code_version()` (returns the short git commit hash of the code that produced the run, via `git rev-parse --short HEAD`, with a graceful `"unknown"` fallback only if git metadata is genuinely unavailable).
- `core/ml_r2/walkforward_r2.py::generate_oos_predictions` — signature extended with required `dataset_id: str`, `validation_period: tuple`, `holdout_period: tuple` parameters (dataset identity and the overall study's declared split boundaries are caller-level facts this function should not invent). Return type changed from `List[OOSPredictionBatch]` to `Tuple[List[OOSPredictionBatch], List[RunProvenance]]`. For every window, after that window's own model is trained, a `RunProvenance` record is built referencing: that window's own `training_period` (its actual `train_dates`, not a blanket development-period claim), that window's own trained model's `model_checksum`, a `dataset_checksum` computed once from the actual `df` argument, a `feature_schema_hash` computed from the live `get_feature_schema()` output, a `config_checksum` from the live `HYPERPARAMETERS` dict, and `random_seed` read from `HYPERPARAMETERS["random_state"]` — never independently retyped constants.

**Tests added**: `tests/test_ml_001_r2_provenance_integration.py` (new, 16 tests):
- Real runs always produce provenance (one record per window, including a window that yields zero OOS predictions — the model still trained, and that is still provenance-worthy).
- Every field is verified to reference what the run *actually* produced, not independently reconstructed metadata: `dataset_checksum` recomputed and compared bit-for-bit against an out-of-band hash of the same `df`, and shown to change when the data changes; `model_checksum` shown to differ across runs with different training data; `feature_schema_hash`/`config_checksum` recomputed independently and compared; `code_version` compared against a fresh call to `get_code_version()` and confirmed not to be the `"unknown"` fallback (git metadata is available in this repo); `dataset_id` confirmed to be exactly the caller-supplied string, never invented.
- Identical inputs across two calls produce identical `dataset_checksum`/`model_checksum`/`feature_schema_hash`/`config_checksum`.
- One test (`test_zero_usable_test_rows_is_unreachable_given_current_warmup_math`) documents, rather than assumes, a genuine structural property discovered while writing this suite: given `WFAWindow` requires `train_end <= test_start` and `build_training_set` requires >600 usable training rows to avoid raising, the "zero usable test rows" branch in `generate_oos_predictions` is provably unreachable through any window satisfying its own invariants together with successful training — verified by constructing the smallest possible non-degenerate (2-bar) test window directly and confirming it still yields predictions, not zero.

**Independent verification**: `grep -n "RunProvenance(" core/ml_r2/walkforward_r2.py` confirms construction inside the function body, not merely an import. Two genuinely separate Python process invocations (Phase 8, below) reproduced identical `dataset_checksum`, `model_checksum`, and `feature_schema_hash` values.

**Status: CLOSED**, with one explicitly scoped limitation: this closes the *construction* of provenance records by the authoritative pipeline. It does not add automatic, independent *persistence* of those records to a channel the model-artifact files themselves cannot also be used to forge (that remains M-2's territory — see below, correctly not touched per Phase 6).

---

### M-7 — Feature schema JSON never written to disk

**Original finding**: `get_feature_schema()` existed and was correct, but no code path ever called it to produce a file; the required artifact simply did not exist.

**Root cause**: `RFR2Model.save()` only ever wrote `model.joblib` and `metadata.json`.

**Code changed**: `core/ml_r2/model_r2.py::RFR2Model.save()` gained an optional third parameter, `feature_schema_path`. When supplied, it writes `get_feature_schema()`'s live output directly to that path — never a hand-duplicated copy, so it cannot become a second, independently-drifting source of truth. Backward compatible: omitting the parameter reproduces the exact prior behavior (verified by a dedicated regression test).

**Also remediated as part of the same change — M-6 (`ModelMetadata` missing `data_version`)**: spec §6 explicitly names `data_version` as required metadata; it was absent from the dataclass entirely. `ModelMetadata` gained an `Optional[str] = None` `data_version` field, and `RFR2Model.train()` gained an optional `data_version` parameter that flows through to it. `None` is the honest value for any run using synthetic/test data (no real `DATA-R2-001` dataset exists yet); a caller with real data supplies the real value. This was the *field's presence*, not merely a value, that was missing, and it is now present unconditionally.

**Tests added**: `tests/test_ml_001_r2_model.py` gained `TestDataVersionField` (3 tests: defaults to `None`, is recorded when supplied, survives a save/load round trip) and `TestFeatureSchemaArtifactWiring` (4 tests: omitting the path writes nothing, at all — backward compatibility explicitly checked, not assumed; supplying the path writes a real file; the written file is byte-for-byte identical to a fresh call to `get_feature_schema()`; the written `feature_order` matches the actual training `DataFrame`'s columns, not just the schema function in isolation).

**Independent verification**: `grep -n "feature_schema_path\|get_feature_schema" core/ml_r2/model_r2.py` confirms the parameter exists, is used to open a file, and is populated by calling the live function — not a hardcoded dict.

**Status: CLOSED (M-7 and M-6 both).**

---

### Phase 6 — Artifact integrity semantics (checksum ≠ authenticity)

**Instruction**: do not "fix" this unless spec explicitly requires authenticity; only correct wording if it currently overclaims.

**Action taken**: searched the entire codebase and every `ML-001-R2-*.md` document for the words "authenticity"/"authentic". The only occurrences are in `ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md` itself, and they correctly state that authenticity is *not* proven by the checksum mechanism — i.e. the audit report already draws the correct distinction. `ModelIntegrityError`'s class name and docstring ("Raised when a loaded model artifact fails checksum verification") already scope themselves to integrity, never authenticity. **No code or documentation change was made or needed.**

Per the instruction, the checksum mechanism itself was left untouched — no cryptographic signing was introduced, since the spec does not require it. The now-wired `RunProvenance` (M-9) provides the *capability* for an independent verification channel if a future phase chooses to persist provenance records outside the model-artifact directory; this remediation does not itself claim that gap is closed, and Phase 7's `TestDatasetSubstitution.test_coordinated_substitution_of_model_and_metadata_is_not_detected_by_checksum_alone` commits the audit's ad-hoc empirical finding as a permanent, repeatable regression test — the limitation is now *tested and documented*, not silently left as a one-off audit observation.

**Status: VERIFIED, NO CHANGE REQUIRED (M-2 remains open by design — see Findings Remaining below).**

---

## PHASE 7 — ADVERSARIAL TESTING (new committed tests, `tests/test_ml_001_r2_phase7_adversarial.py`, 5 tests)

| # | Scenario | Result |
|---|---|---|
| 1 | Future feature leakage | Covered pre-existing (`TestFutureDataInjection`) — re-verified passing |
| 2 | Target leakage | Covered pre-existing + new B/C/D leakage-integration tests |
| 3 | Weekday data gaps | **New**, `test_ml_001_r2_data_quality.py` — fail-closed (raises) |
| 4 | Weekend/expected gaps | **New**, same file — correctly tolerated |
| 5 | Provenance mismatch | New provenance-integration tests show checksums differ when inputs differ |
| 6 | Model checksum mismatch | Covered pre-existing (`test_load_rejects_tampered_artifact`) |
| 7 | Metadata/model mismatch (substituted model, stale metadata) | **New** — `test_substituted_model_with_stale_metadata_is_rejected`, fail-closed |
| 7b | Metadata/model mismatch (coordinated substitution) | **New** — `test_coordinated_substitution_of_model_and_metadata_is_not_detected_by_checksum_alone`, correctly documents the known, undetected case (Phase 6) |
| 8 | Feature schema mismatch | **New** — `TestFeatureSchemaMismatch`, stale schema detectably differs from live schema |
| 9 | Wrong feature ordering | Covered pre-existing (`TestFeatureReordering`) |
| 10 | Wrong feature version | Covered pre-existing (`test_feature_version_drift_is_observable_in_saved_metadata`) |
| 11 | Wrong model version | **New** — `TestWrongModelVersion`, faithfully recorded not silently corrected |
| 12 | Different random seed | **New** — `TestDifferentRandomSeed`, checksum sensitivity to `random_state` proven via monkeypatch |
| 13 | Dataset substitution | **New**, see #7/#7b above plus provenance `dataset_checksum` sensitivity tests |
| 14 | Training/validation temporal overlap | Covered pre-existing (`TestHoldoutAndValidationAccessViolations`, `TestTemporalSplit`) |

All fail-closed where the spec requires it (#3, #6, #7); #7b and Phase 6 explicitly document the one case that is *not* fail-closed by the current checksum-only mechanism, per the instruction's own guidance not to over-claim.

---

## PHASE 8 — REPRODUCIBILITY REGRESSION

Re-ran the full pre-existing `tests/test_ml_001_r2_reproducibility.py` suite (8 tests: features, labels, model checksum, predictions, trade sequence, equity curve — all still exact) plus the new `TestReproducibilityOfProvenance` (provenance fields identical across two calls) and the schema-content-equality tests (feature schema identical to the live function's output).

**Fresh-process check** (genuinely separate Python interpreter invocations, not same-session repetition): ran the complete remediated pipeline — gap-checked feature computation, leakage-wired `build_training_set`, provenance-wired `generate_oos_predictions`, schema-hash computation — twice, in two separate `python3` process invocations, on identical synthetic data (seed 999):

```
RUN 1                                                            RUN 2
model_checksum:                    2aec2d5c...ec01                2aec2d5c...ec01
provenance[0].model_checksum:      cf78b13e...4618                cf78b13e...4618
provenance[0].dataset_checksum:    de0d2b66...c17879              de0d2b66...c17879
provenance[0].feature_schema_hash: d976bbb4...366bce              d976bbb4...366bce
predictions[:3]:                   [(1,0.5701...),(0,0.4926...),(0,0.4764...)]   identical
```

All values bit-for-bit identical across process boundaries. (`metadata.checksum` and `provenance[0].model_checksum` differ *from each other* within the same run by design — the former trains on the full 2500-bar dataset directly, the latter is the walk-forward window's own separately-trained model on a smaller slice; this is expected, not a reproducibility failure.)

No economic or PURE_HOLDOUT data was used anywhere in this phase.

---

## PHASE 9 — FULL TEST SUITE (exact counts, not approximate)

```
R2 test suite:        148 tests collected, 148 passed, 0 failed   (baseline: 93)
Full repository suite: 450 tests collected, 450 passed, 0 failed   (baseline: 395)
```

Net new tests: 55 (all within `tests/test_ml_001_r2_*.py`; zero pre-existing non-R2 tests were touched). Exit code `0` for both suites, confirmed via `$?` after each run, not inferred from output formatting.

---

## PHASE 10 — FINAL FORENSIC AUDIT: FINDING STATUS

| Finding | Status | Evidence |
|---|---|---|
| C-1 (spec §7 contradiction) | **CLOSED** | `_check_weekday_gaps` wired into `_validate_ohlcv`; 20 new dedicated tests + 2 rewritten adversarial tests |
| M-1 (`assert_no_leakage` unwired) | **CLOSED** | `build_training_set` is the sole authoritative entry point; grep-confirmed call site; 7 integration tests including a mock-verified "actually executes" proof |
| M-9 (`RunProvenance` unwired) | **CLOSED** | Constructed per-window inside `generate_oos_predictions`; grep-confirmed; 16 integration tests verifying every field traces to real artifacts |
| M-7 (feature schema file never written) | **CLOSED** | `RFR2Model.save(..., feature_schema_path=...)`; 4 dedicated tests |
| M-6 (`ModelMetadata` missing `data_version`) | **CLOSED** | Field added, threaded through `train()`, 3 dedicated tests |
| I-5 (no canonical `strategy_id`/`strategy_version` constant) | **CLOSED** (byproduct of M-9) | `STRATEGY_ID`/`STRATEGY_VERSION` now defined once in `provenance_r2.py` |
| M-2 (checksum ≠ authenticity against coordinated tamper) | **NOT_APPLICABLE for code changes; PARTIALLY_CLOSED for documentation/test coverage** | Per Phase 6, deliberately not "fixed" (no spec requirement for authenticity); the limitation is now a committed, repeatable regression test (`test_coordinated_substitution_of_model_and_metadata_is_not_detected_by_checksum_alone`) rather than only a one-off audit observation. The independent-recording *capability* now exists (M-9), but nothing yet automatically persists `RunProvenance` outside the model-artifact directory — that would close the gap fully but was outside this remediation's explicit phases. |
| M-8 (`load()` doesn't check `feature_version` against current constant) | **OPEN** | Not in scope of the governing instruction's Phases 2–6; confirmed unchanged by grep (`feature_version` appears only at field declaration and `train()`-time assignment, never a comparison, in the current `model_r2.py`) |
| M-3 (`generate_oos_predictions` trusts caller-declared data_state without verifying `df` row-range) | **OPEN** | Not in scope; unchanged |
| M-4 (`max_positions_per_symbol` dead config field) | **OPEN** | Not in scope; `backtest_r2.py` was not touched in this remediation |
| M-5 (RSI/ATR not verified against exact reference values) | **OPEN** | Not in scope; no new reference-value test was added |
| L-1, L-2, L-3 (test-quality/dtype/file-layout gaps) | **OPEN** | Not in scope |
| I-1 through I-4 (informational, not defects) | **NOT_APPLICABLE** | No action required, as originally classified |

**7 of 9 audit-report findings this remediation was scoped to address are CLOSED. M-2 is correctly left open by explicit instruction (Phase 6). No finding outside the governing instruction's Phases 2–6 was touched, per the "remediate ONLY" scope — M-3, M-4, M-5, M-8, and the Low-severity findings remain open and are not claimed as fixed.**

---

## FILES MODIFIED

```
core/features/fe_r2_001.py           +60/-0   (weekday-gap check)
core/ml_r2/model_r2.py               +29/-1   (data_version field, schema-file wiring)
core/ml_r2/provenance_r2.py          +29/-0   (STRATEGY_ID/VERSION, get_code_version)
core/ml_r2/target_r2.py              +21/-0   (build_training_set)
core/ml_r2/walkforward_r2.py        +100/-6  (RunProvenance wiring, dataset/config/schema checksums)
tests/test_ml_001_r2_adversarial.py  +37/-14  (gap tests updated for new spec-compliant behavior)
tests/test_ml_001_r2_model.py        +90/-2   (data_version + schema-artifact tests)
tests/test_ml_001_r2_walkforward.py  +14/-6   (updated generate_oos_predictions call signature)
```

**New files**:
```
tests/test_ml_001_r2_data_quality.py           (20 tests)
tests/test_ml_001_r2_leakage_integration.py    (7 tests)
tests/test_ml_001_r2_provenance_integration.py (16 tests)
tests/test_ml_001_r2_phase7_adversarial.py     (5 tests)
```

No governance file, historical report, database record, production runner, or Pine artifact was touched. No hyperparameter, feature formula, target definition, or trading/risk constant was changed — verified by re-diffing every modified file against the baseline commit and confirming every changed line falls into: gap-detection logic, leakage-guard wiring, provenance-record construction, or schema/metadata persistence.

---

## GOVERNANCE IMPACT

This remediation performs no governance transition beyond recording remediation status. Per the governing instruction's Phase 11:

```
IMPLEMENTATION_INTEGRITY = REMEDIATED (partially — 7/9 in-scope findings closed, 1 correctly left open by instruction, 5 out-of-scope findings untouched)
ECONOMIC_VALIDITY        = UNPROVEN
PRODUCTION                = BLOCKED
PINE_CONVERSION           = BLOCKED
ML-001-R2                = RESEARCH_ONLY / UNAUTHORIZED (unchanged)
```

No economic validation was performed. No PURE_HOLDOUT data was accessed — confirmed by `grep -n "FINAL_EVALUATION"` across all changed files: every occurrence is either the guard mechanism's own definition or a test using synthetic fixtures with a test-only `hypothesis_id`. No real market data was used anywhere. No Pine Script was generated. No model was trained for any purpose other than mechanical/integration test verification on synthetic fixtures.
