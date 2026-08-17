# ML-001-R2 IMPLEMENTATION REPORT

**Date**: August 17, 2026
**Phase**: IMPLEMENTATION ONLY — per `ML-001-R2-CLEAN-REBUILD-SPEC.md`
**Governance transition this phase performs**: `IMPLEMENTATION_NOT_STARTED` → `IMPLEMENTATION_COMPLETE`
**This phase does NOT**: validate economically, open PURE_HOLDOUT, authorize production, deploy, connect to a broker, or generate Pine Script.

---

## 1. IMPLEMENTATION MATRIX

| Requirement (spec section) | Module | Function/Class | Test file | Invariant enforced |
|---|---|---|---|---|
| Feature formulas (§4) | `core/features/fe_r2_001.py` | `build_feature_matrix`, `compute_momentum`, `compute_volatility_regime` | `tests/test_ml_001_r2_features.py` | Exact formula, lookback, warmup, NaN handling, fixed ordering |
| Feature schema (§4, §12) | `core/features/fe_r2_001.py` | `get_feature_schema`, `FEATURE_ORDER`, `FEATURE_VERSION` | `tests/test_ml_001_r2_features.py` | FEATURE_PARITY — single canonical implementation |
| Target/label (§5) | `core/ml_r2/target_r2.py` | `compute_label`, `align_features_and_labels` | `tests/test_ml_001_r2_target.py` | Strict binary label, undefined final bar not silently 0 |
| Leakage guard (§5, §12) | `core/ml_r2/target_r2.py` | `assert_no_leakage` | `tests/test_ml_001_r2_target.py`, `tests/test_ml_001_r2_adversarial.py` | Label independently recomputable and verifiable |
| Model spec (§6) | `core/ml_r2/model_r2.py` | `RFR2Model`, `HYPERPARAMETERS` | `tests/test_ml_001_r2_model.py` | No unspecified sklearn defaults; strict schema validation |
| Model artifact/checksum (§6, §15) | `core/ml_r2/model_r2.py` | `RFR2Model.save/load`, `_serialize_model`, `_checksum_bytes` | `tests/test_ml_001_r2_model.py` | Deterministic checksum, tamper detection |
| Temporal split (§7, §8) | `core/ml_r2/walkforward_r2.py` | `compute_temporal_split`, `TemporalSplit` | `tests/test_ml_001_r2_walkforward.py` | Chronological, non-overlapping, no random split |
| Holdout boundary (§8) | `core/ml_r2/walkforward_r2.py` | `HoldoutAccessGuard` | `tests/test_ml_001_r2_walkforward.py`, `tests/test_ml_001_r2_adversarial.py` | PURE_HOLDOUT opened at most once |
| Walk-forward OOS (§9) | `core/ml_r2/walkforward_r2.py` | `generate_oos_predictions`, `make_walk_forward_windows` | `tests/test_ml_001_r2_walkforward.py` | No lookahead; every prediction provenance-tagged |
| Trading rules (§10) | `core/ml_r2/backtest_r2.py` | `run_backtest`, `BacktestConfig` | `tests/test_ml_001_r2_backtest.py` | Deterministic entry/exit/sizing/SL/TP/max-hold/reversal priority |
| Provenance manifest (§15) | `core/ml_r2/provenance_r2.py` | `RunProvenance.validate_complete` | `tests/test_ml_001_r2_provenance.py` | Incomplete provenance is rejected, not silently accepted |
| Reproducibility (§15, Phase 9) | (cross-cutting) | full-pipeline run comparison | `tests/test_ml_001_r2_reproducibility.py` | RUN A == RUN B at every stage |
| Adversarial defenses (Phase 8) | (cross-cutting) | — | `tests/test_ml_001_r2_adversarial.py` | See §11 below |

---

## 2. FILES CREATED / MODIFIED

**Created:**
```
core/features/__init__.py
core/features/fe_r2_001.py
core/ml_r2/__init__.py
core/ml_r2/target_r2.py
core/ml_r2/model_r2.py
core/ml_r2/walkforward_r2.py
core/ml_r2/backtest_r2.py
core/ml_r2/provenance_r2.py
tests/r2_fixtures.py
tests/test_ml_001_r2_features.py
tests/test_ml_001_r2_target.py
tests/test_ml_001_r2_model.py
tests/test_ml_001_r2_walkforward.py
tests/test_ml_001_r2_backtest.py
tests/test_ml_001_r2_provenance.py
tests/test_ml_001_r2_adversarial.py
tests/test_ml_001_r2_reproducibility.py
ML-001-R2-IMPLEMENTATION-REPORT.md
```

**Modified:**
```
requirements.txt   — added scikit-learn>=1.4,<2.0 and joblib>=1.3,<2.0 (RF-R2-001 dependency, spec §6)
```

**Not modified** (per Absolute Rules / Governance Boundary): any old ML-001 file, any existing report, any governance/validation-result file, any production runner, any database record, any Pine Script.

---

## 3. SPECIFICATION-TO-CODE MAPPING

Every numeric constant in the implementation traces to a named spec section, not to old ML-001:

| Constant | Value | Source |
|---|---|---|
| `FEATURE_ORDER` | `[momentum_5, momentum_20, rsi_14, atr_14, volatility_regime]` | Spec §4 |
| `WARMUP_BARS` | `{5, 20, 100, 100, 600}` | Spec §4 |
| `HYPERPARAMETERS` | `n_estimators=300, max_depth=6, min_samples_split=50, min_samples_leaf=25, max_features="sqrt", class_weight="balanced", criterion="gini", bootstrap=True, random_state=42` | Spec §6 |
| Temporal split fractions | `60% / 20% / 20%` | Spec §8 |
| `long_threshold` / `short_threshold` | `0.55 / 0.45` | Spec §10 |
| `risk_per_trade` | `0.02` | Spec §10 |
| `stop_loss_atr_mult` / `take_profit_atr_mult` | `1.5 / 2.5` | Spec §10 |
| `max_holding_bars` | `24` | Spec §10 |
| `slippage_price` | `0.00002` (0.2 pip) | Spec §7 |

No value above was copied from any old ML-001 report, config, or test fixture.

---

## 4. FEATURE IMPLEMENTATION

`core/features/fe_r2_001.py` computes all five FE-R2-001 features from a validated OHLCV frame:

- `momentum_5`/`momentum_20`: percentage return over the lookback, per spec formula
- `rsi_14`/`atr_14`: delegate to the existing, already-tested `core/indicators.py` Wilder implementations (spec §4's stated reference implementation) rather than re-deriving Wilder smoothing
- `volatility_regime`: new construction — trailing 500-bar causal percentile of `atr_14`, encoded ordinally `{0,1,2}`
- Warmup masking is applied per-feature (`_apply_warmup`), independent of the underlying rolling/ewm computation's own `min_periods`
- Input validation rejects missing columns, non-datetime index, duplicate timestamps, and non-monotonic timestamps before any feature is computed

`get_feature_schema()` produces the machine-readable schema referenced by the provenance manifest (§15 of the spec, `feature_schema_hash` field).

---

## 5. TARGET IMPLEMENTATION

`core/ml_r2/target_r2.py::compute_label` implements the strict binary label exactly as specified: `1` if `close[t+1] > close[t]`, `0` if `close[t+1] <= close[t]`, and — critically — **NaN, not 0**, when `close[t+1]` does not exist (the final bar of any series). This distinction is deliberately tested (`test_last_bar_is_undefined_not_zero`) because collapsing "unknown" into "class 0" would be a subtle leakage-adjacent bug: it would let a model implicitly learn from an artificially inflated negative-class rate at series boundaries.

`align_features_and_labels` drops both feature-warmup rows and the final undefined-label row, and asserts the resulting (X, y) pair stays chronologically ordered. `assert_no_leakage` independently recomputes labels from the raw close series and verifies exact agreement, catching both wrong-value and wrong-definedness leakage bugs (both are exercised in `tests/test_ml_001_r2_target.py::TestLeakageGuard`).

---

## 6. MODEL IMPLEMENTATION

`core/ml_r2/model_r2.py::RFR2Model` wraps `sklearn.ensemble.RandomForestClassifier` with every hyperparameter from spec §6 explicit (`HYPERPARAMETERS` dict) plus `n_jobs=1`, added separately and documented as a determinism-only setting (not a strategy hyperparameter — it affects only whether parallel tree-building floating-point summation order is reproducible, not what the model predicts).

`train()`/`predict()`/`predict_proba()` all validate the input DataFrame's columns against `FEATURE_ORDER` exactly (name and order) and reject NaNs, per spec's "strict schema validation" requirement.

**Checksum design note** (a real implementation-time finding, not a hypothetical): an initial version computed the artifact checksum by re-pickling the model object at each verification point, including after `joblib.load()`. This failed a round-trip test — `joblib.dump(loaded_model)` does not reliably reproduce byte-identical output to the original `joblib.dump(original_model)`, even though the reconstructed model's predictions are unaffected (internal numpy array layout/strides can differ across a dump→load→re-dump cycle). The fix: the checksum is computed exactly once, at `train()` time, over the serialized bytes; `save()` writes those exact bytes to disk (never re-serializes); `load()` hashes the raw bytes read from disk directly (never re-pickles the reconstructed object) before deserializing. This is now covered by `tests/test_ml_001_r2_model.py::TestModelPersistence` and the reproducibility suite.

---

## 7. WALK-FORWARD IMPLEMENTATION

`core/ml_r2/walkforward_r2.py`:

- `compute_temporal_split`: strict chronological 60/20/20 DEVELOPMENT/VALIDATION/PURE_HOLDOUT split, positional only, never random
- `HoldoutAccessGuard`: wraps the existing `ProvenanceEnforcer` with mutable open/closed state so "PURE_HOLDOUT accessed at most once" holds across an entire research run, not just a single call
- `make_walk_forward_windows`: thin, documented reuse of `WFAPredictionEngine.generate_windows` — pure window-boundary arithmetic, safe to reuse unmodified because it does no feature computation
- `generate_oos_predictions`: **new code**, not a reuse of `WFAPredictionEngine.generate_predictions`. That existing method calls `feature_extractor(df.iloc[test_start:test_end])` on a bare slice with no preceding context — incompatible with any feature requiring lookback (all five FE-R2-001 features do; `volatility_regime` needs up to 600 bars). `generate_oos_predictions` extends each test window backward by `MAX_WARMUP_BARS` before computing features, then trims output back to the window's declared boundaries. This is a **documented, deliberate deviation** from reusing the existing method verbatim — not a silent patch to shared code, and the existing method itself was left untouched.

Every OOS prediction batch is a `core.oos_wfa_engine.OOSPredictionBatch` — the same immutable, existing dataclass old ML-001's infrastructure defined but never actually populated with a real model. For R2, it is genuinely populated.

---

## 8. BACKTEST IMPLEMENTATION

`core/ml_r2/backtest_r2.py::run_backtest` implements spec §10's trading rules as a single-pass, deterministic state machine:

- Entries and signal-reversal exits are treated as *signals*: computed from `p` at bar close, executed at the next bar's open (TIMING_PARITY)
- Stop-loss, take-profit, and max-holding-period are treated as *risk triggers*: evaluated against the current bar's intrabar high/low/close as soon as they occur, same bar — documented explicitly in the module docstring as the reason this is not a TIMING_PARITY violation
- Exit priority `STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD > SIGNAL_REVERSAL` is enforced by evaluation order within a single `if/elif` chain, not by any implicit ordering assumption
- Position sizing follows the exact §10 formula: `size = (equity × 0.02) / (stop_loss_distance_pips × pip_value_per_lot)`

**Explicitly out of scope / not run**: this module has never been executed against real market data, and no output from it has been used to compute or claim any economic metric. All six test classes in `tests/test_ml_001_r2_backtest.py` use tiny, hand-constructed 3-4 bar fixtures chosen specifically to force each individual mechanic (stop-loss hit, take-profit hit, max-hold, reversal) in isolation — this validates the *code is correct*, not that the *strategy is good*.

---

## 9. RISK IMPLEMENTATION

Per-trade risk (position sizing, stop-loss/take-profit distance) is implemented in `backtest_r2.py` per §10.

Portfolio-level risk (§11 — max total allocation, daily loss limits, drawdown circuit breaker) is **explicitly deferred**, per the spec's own §11 language: *"thresholds to be set during Phase 12, not invented here as arbitrary numbers."* No portfolio-level risk thresholds were invented in this implementation phase; wiring to the existing, reusable `core/risk_governance.py::RiskGovernanceConfig` is a Phase-12 governance action, not an implementation-phase one.

---

## 10. PROVENANCE IMPLEMENTATION

`core/ml_r2/provenance_r2.py::RunProvenance` is a frozen dataclass carrying all fifteen fields required by the implementation-phase instruction (Phase 7): `strategy_id`, `strategy_version`, `model_version`, `feature_version`, `dataset_id`, `dataset_checksum`, `code_version`, `config_checksum`, `training_period`, `validation_period`, `holdout_period`, `feature_schema_hash`, `model_checksum`, `random_seed`, `execution_assumptions`.

`validate_complete()` raises `ProvenanceIncompleteError` on any missing/empty field — the literal implementation of "a result without complete provenance must be rejected." This is the direct process fix for the single largest failure identified in the ML-001 forensic reports: every historical performance figure existed only as an orphaned output file with no committed generator or provenance trail. `to_manifest_dict()`/`to_json()` refuse to serialize an incomplete record (they call `validate_complete()` first).

---

## 11. TEST RESULTS

```
core/features/fe_r2_001.py, core/ml_r2/*.py — 93 tests, 93 passed, 0 failed
Full repository test suite (including all pre-existing tests) — 395 tests, 395 passed, 0 failed
```

Breakdown by required category (Phase 8 of the implementation instruction):

| Category | File | Tests | Result |
|---|---|---|---|
| A. Feature correctness | `test_ml_001_r2_features.py` | 15 | PASS |
| B. Target correctness | `test_ml_001_r2_target.py` | 12 | PASS |
| C. Model schema | `test_ml_001_r2_model.py` | 12 | PASS |
| D. Model determinism | `test_ml_001_r2_model.py` (`TestModelDeterminism`) | 2 | PASS |
| E. Temporal boundaries | `test_ml_001_r2_walkforward.py` (`TestTemporalSplit`) | 5 | PASS |
| F. Leakage prevention | `test_ml_001_r2_target.py`, `test_ml_001_r2_adversarial.py` | 6 | PASS |
| G. Walk-forward OOS behavior | `test_ml_001_r2_walkforward.py` (`TestWalkForwardOOSGeneration`) | 5 | PASS |
| H. Execution timing | `test_ml_001_r2_backtest.py` | 8 | PASS |
| I. Risk limits | `test_ml_001_r2_backtest.py` (SL/TP/sizing) | (included above) | PASS |
| J. Artifact provenance | `test_ml_001_r2_provenance.py` | 6 | PASS |
| K. Reproducibility | `test_ml_001_r2_reproducibility.py` | 7 | PASS |
| L. Holdout access prevention | `test_ml_001_r2_walkforward.py`, `test_ml_001_r2_adversarial.py` | 8 | PASS |
| Adversarial (future data, shuffled/duplicate timestamps, missing bars, feature reordering, model mismatch, dataset mismatch, holdout/validation misuse) | `test_ml_001_r2_adversarial.py` | 16 | PASS |

No test was skipped, xfailed, or weakened to make it pass.

---

## 12. REPRODUCIBILITY RESULTS

Per Phase 9 (RUN A vs. RUN B on identical synthetic inputs), `tests/test_ml_001_r2_reproducibility.py` verifies, end to end (features → labels → training → predictions → backtest):

| Property | Result |
|---|---|
| Identical features | ✅ EXACT (`pd.testing.assert_frame_equal`) |
| Identical labels | ✅ EXACT |
| Identical model checksum | ✅ EXACT |
| Identical predictions | ✅ EXACT (`np.testing.assert_array_equal`) |
| Identical trade sequence | ✅ EXACT (entry/exit price, time, reason, PnL, per trade) |
| Identical equity curve | ✅ EXACT (`pd.testing.assert_series_equal`) |

**No non-determinism was observed or explained away.** The one real non-determinism issue found during implementation (model checksum drift across a save/load round trip, §6) was root-caused and fixed at the source — the fix is what the passing test now verifies, not a tolerance loosened to accommodate it.

---

## 13. KNOWN LIMITATIONS

1. **No real market data.** All tests use deterministic synthetic fixtures (`tests/r2_fixtures.py`), explicitly documented as mechanical-testing-only. Real EURUSD/GBPUSD data acquisition remains an open procurement item (spec §17, item 1) — not started in this phase.
2. **`RF-R2-001` has never been trained on real data.** Every trained model produced during this phase exists only inside a test process and is discarded when the test ends. No model artifact has been persisted for actual research use.
3. **No walk-forward run has been executed against real data.** `generate_oos_predictions` is exercised only against synthetic fixtures in tests.
4. **Cost model is a documented placeholder.** `commission_per_lot_round_turn`, `pip_value_per_lot`, and the spread assumption are explicit stand-ins pending broker selection (spec §17, item 2); the position-sizing/PnL formulas correctly *apply* whatever values are configured, but the specific dollar figures are not final.
5. **Pine export architecture is not implemented.** Per the mandatory stop gate, only the specification's architectural decision (tree-export translation, spec §13) exists; no exporter code was written, and none should be until after validation passes.
6. **Portfolio-level risk thresholds are not wired.** Per-trade risk is fully implemented; account-level allocation caps and circuit breakers are deferred to Phase 12 governance review, per the spec's own instruction not to invent them here.
7. **`generate_oos_predictions` is new code**, not a reuse of the existing generic `WFAPredictionEngine.generate_predictions` (§7 above) — a deliberate, documented architectural deviation required because the generic method has no lookback support, not a defect introduced by this implementation.

None of these limitations were papered over, defaulted silently, or hidden — each is either an explicit open item already listed in the R2 specification (§17) or a documented engineering decision made during implementation and covered by a passing test.

---

## 14. GOVERNANCE STATUS

```
ML-001-R2 STATUS       = RESEARCH_ONLY  (unchanged)
VALIDATION STATUS       = NOT_VALIDATED  (unchanged — no economic validation performed)
AUTHORIZATION           = NOT_AUTHORIZED  (unchanged)
PRODUCTION              = BLOCKED  (unchanged — no broker connectivity, no live/paper execution)
PINE CONVERSION         = BLOCKED  (unchanged — no Pine code generated)
PURE_HOLDOUT             = NOT OPENED  (verified — no call to FINAL_EVALUATION against real data occurred anywhere in this phase)
```

**Governance transition performed by this report**: `IMPLEMENTATION_NOT_STARTED` → `IMPLEMENTATION_COMPLETE`. Nothing beyond that transition was calculated, declared, or authorized — no economic validation, no capital allocation, no PASS/VALIDATED verdict, no EVG result, no broker deployment.

---

## FINAL RESPONSE

### **IMPLEMENTATION_COMPLETE**

- **Tests passed**: 93/93 new ML-001-R2 tests; 395/395 across the full repository (zero regressions to pre-existing test suites)
- **Files changed**: 8 new source modules, 9 new test files, 1 modified dependency file (`requirements.txt`); zero old ML-001, governance, report, or production files touched
- **Specification coverage**: every requirement in `ML-001-R2-CLEAN-REBUILD-SPEC.md` Sections 4-12 that is implementable in this phase has been implemented and mapped in §1/§3 above; §11 (portfolio risk thresholds) and §13 (Pine exporter) are correctly deferred per the spec's own instructions, not gaps
- **Reproducibility status**: EXACT — RUN A and RUN B produce identical features, labels, model checksum, predictions, trade sequence, and equity curve
- **Unresolved implementation gaps**: none that block `IMPLEMENTATION_COMPLETE`; the real gaps (real data acquisition, broker/cost finalization, Pine exporter, portfolio risk thresholds) are pre-existing open items from the specification itself, not implementation defects
- **Production remains BLOCKED**: confirmed — no broker connectivity, no live or paper execution code was written or run
- **Pine remains BLOCKED**: confirmed — no Pine Script was generated; only the architectural decision from the specification phase is on record

---

**IMPLEMENTATION PHASE COMPLETE — NO ECONOMIC VALIDATION PERFORMED — PURE_HOLDOUT NOT OPENED — NO PRODUCTION AUTHORIZATION — NO PINE SCRIPT GENERATED**
