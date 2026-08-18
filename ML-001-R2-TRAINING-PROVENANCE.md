# ML-001-R2 Training Pipeline Provenance & Reproducibility Forensics

**Date**: August 18, 2026
**Companion to**: `ML-001-R2-FINAL-ECONOMIC-VALIDATION-REPORT.md`, Phase 2.
**Purpose**: assess whether the *code* implementing ML-001-R2's training pipeline is structurally reproducible — independent of the fact that it has never been run against real data (no real data exists; see the companion report's Phase 3).

This is a **code forensics** document, not a training run record. No model was trained to produce this document.

---

## 1. Pipeline stage inventory

| Stage | File / function | Status | Test coverage |
|---|---|---|---|
| Raw OHLCV validation | `core/features/fe_r2_001.py::_validate_ohlcv`, `_check_weekday_gaps` | REAL | `tests/test_ml_001_r2_data_quality.py` |
| Canonical features | `core/features/fe_r2_001.py::build_feature_matrix` | REAL, hash-verified unchanged this session (`1d8ce135daaafedd8c085b243f41beeb1b8aafb165f7169d3722dc6e99ffd3dd`) | `tests/test_ml_001_r2_features.py`, `tests/test_ml_001_r2_numerical_oracle.py`, `tests/test_ml_001_r2_feature_parity_fixture.py` |
| Target/label construction | `core/ml_r2/target_r2.py::compute_label`, `build_training_set`, `assert_no_leakage` | REAL | `tests/test_ml_001_r2_target.py` |
| Temporal split | `core/ml_r2/walkforward_r2.py::compute_temporal_split`, `TemporalSplit` | REAL | `tests/test_ml_001_r2_walkforward.py` |
| Holdout access control | `core/ml_r2/walkforward_r2.py::HoldoutAccessGuard` | REAL, one-time-access enforcement mechanism | `tests/test_ml_001_r2_walkforward.py`, `tests/test_ml_001_r2_provenance_integration.py` |
| Walk-forward OOS generation | `core/ml_r2/walkforward_r2.py::generate_oos_predictions`, `make_walk_forward_windows` | REAL | `tests/test_ml_001_r2_walkforward.py` |
| Model class | `core/ml_r2/model_r2.py::RFR2Model` | REAL, instantiable, trainable | `tests/test_ml_001_r2_model.py` |
| Model persistence + integrity | `RFR2Model.save()`/`.load()`, byte-exact checksum verification, `ModelIntegrityError` on mismatch | REAL | `tests/test_ml_001_r2_model.py`, `tests/test_ml_001_r2_phase7_adversarial.py` |
| Provenance recording | `core/ml_r2/provenance_r2.py::RunProvenance`, `get_code_version` | REAL | `tests/test_ml_001_r2_provenance.py`, `tests/test_ml_001_r2_provenance_integration.py` |
| Position/risk/execution mechanics | `core/ml_r2/backtest_r2.py::run_backtest` | REAL, spec-faithful | `tests/test_ml_001_r2_backtest.py`, `tests/test_ml_001_r2_simulator.py` |
| End-to-end orchestration script | — | **MISSING** | — |

**Every individual stage is real code with real tests.** No stage is a stub, TODO, or placeholder function. The one missing piece is a top-level script that calls these stages in sequence against a real dataset (`find . -iname "*train*r2*"` returns nothing) — this is a thin orchestration gap, not a missing capability; someone would write perhaps 30–60 lines wiring the existing functions together once real data exists.

---

## 2. Leakage / integrity checks, verified by direct code read

- **No future leakage**: `assert_no_leakage()` exists in `target_r2.py` and is exercised by `tests/test_ml_001_r2_adversarial.py::TestFutureDataInjection` (confirms features up to bar `t` are unaffected by bars appended after `t`, including specifically for the seeded-Wilder RSI/ATR recurrence — a targeted test added during the M-5 remediation phase).
- **No overlapping train/test contamination**: `compute_temporal_split` produces non-overlapping `TemporalSplit` windows by construction (chronological slicing, not random sampling).
- **No feature-fit leakage**: FE-R2-002's five features are all causal/trailing transformations of price (momentum ratios, seeded-Wilder RSI/ATR, a trailing percentile for volatility_regime) — none involves fitting a transformer (e.g., a `StandardScaler`) to any window of data, so there is no "fit on future data" failure mode to guard against in the first place. Confirmed by direct read of `build_feature_matrix` — no `sklearn.preprocessing` import exists in `fe_r2_001.py`.
- **No target leakage**: `compute_label()` is strictly 1-bar-forward; `assert_no_leakage()` specifically checks that no label depends on information at or before its own feature timestamp.
- **No model-selection-on-test-data leakage**: `HoldoutAccessGuard` (in `walkforward_r2.py`) is designed to enforce PURE_HOLDOUT's one-time-access semantics — read directly this session, unmodified — but has never been invoked against a real dataset, since none exists. This mechanism is a *control*, not evidence of a violation; it has simply never been exercised for real.
- **Deterministic seeding**: `HYPERPARAMETERS["random_state"] = 42` (the model's own randomness); `_DETERMINISM_SETTINGS = {"n_jobs": 1}`, explicitly documented in `model_r2.py`'s own module docstring as "purely for run-to-run determinism... not one of the strategy hyperparameters."
- **Artifact provenance fields**: `ModelMetadata` (frozen dataclass) captures `model_version`, `feature_version`, `feature_order`, `hyperparameters`, `sklearn_version`, `python_version`, `training_timestamp`, `training_start`/`training_end`, `training_rows`, `class_balance`, `checksum`. All fields are populated by `RFR2Model.train()` at training time — this has been exercised in tests against synthetic fixtures (confirming the mechanism works), never against real data (because none exists).

---

## 3. What "reproducible" means here, precisely

This document does **not** claim the training pipeline has been reproduced — it has never run against real data, so there is nothing yet to reproduce. It claims the narrower, verifiable thing: every stage of the intended pipeline exists as real, unit-tested, deterministic code, with no gap that would prevent a future run from being reproducible once real data is acquired. The distinction matters because "the code is ready" and "a result has been produced and verified" are different claims, and only the first is being made here.

---

## 4. Explicit non-claims

- This document does not claim RF-R2-001 has ever been trained.
- This document does not claim any economic performance figure for ML-001-R2.
- This document does not claim the pipeline has been run end-to-end, even once, against any dataset (synthetic or real).
- This document does not substitute for `ML-001-R2-OOS-RESULTS.md`, `ML-001-R2-WALK-FORWARD-RESULTS.md`, or `ML-001-R2-ROBUSTNESS-RESULTS.md` — those were not created, because their preconditions were never met (see the companion report).
