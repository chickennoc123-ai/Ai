# ML-001-R2 FINAL ECONOMIC VALIDATION REPORT

**Date**: August 18, 2026
**Repository state**: commit `6526146`, branch `claude/ea-factory-pro-system-bc9jaa`, clean tree at start.
**Scope**: ML-001-R2 only (per `STRATEGY_REALITY_RECONSTRUCTION_REPORT.md`, AGLE is platform infrastructure, not a strategy, and is out of scope; the original ML-001 is a frozen, unimplemented specification and is out of scope until implemented).
**Verdict, stated up front so it is not lost in the detail below**: `ECONOMIC VALIDATION BLOCKED`. Two independent, hard-stop conditions both apply — no trained model artifact exists, and no real market data exists. Neither was manufactured to close this report. Everything below documents *why*, in the depth the governing instruction requires, without pretending an evidence chain exists where one does not.

---

## PHASE 0 — THE EXISTING R2 SYSTEM (re-read this session, not assumed)

Re-read directly from `ML-001-R2-CLEAN-REBUILD-SPEC.md` and the corresponding implementation files:

| Parameter | Value | Source |
|---|---|---|
| `strategy_id` | `ML-001-R2` | spec line 28 |
| `feature_version` | `FE-R2-002` (bumped from `FE-R2-001` per the M-5 seeded-Wilder RSI/ATR correction) | spec line 31, `core/features/fe_r2_001.py` |
| `model_version` | `RF-R2-001` | spec line 30 |
| `data_version` | `DATA-R2-001` — explicitly marked "checksum to be appended once real data is acquired" | spec line 32 |
| Feature set | `momentum_5`, `momentum_20`, `rsi_14`, `atr_14`, `volatility_regime`, fixed order | `core/features/fe_r2_001.py::FEATURE_ORDER` |
| Target definition | 1-bar-forward binary classification | `core/ml_r2/target_r2.py::compute_label()` |
| Prediction horizon | 1 H1 bar | spec §5 |
| Signal threshold | `p > 0.55` LONG, `p < 0.45` SHORT, else FLAT (strict inequalities) | spec §10, `core/ml_r2/backtest_r2.py::BacktestConfig` |
| Model type | `RandomForestClassifier`, `n_estimators=300`, `max_depth=6`, `min_samples_split=50`, `min_samples_leaf=25`, `max_features="sqrt"`, `class_weight="balanced"`, `random_state=42` | spec §6, `core/ml_r2/model_r2.py::HYPERPARAMETERS` |
| Position sizing | `size = (equity × 0.02) / (SL_distance_pips × pip_value)` | spec §10 |
| Stop loss | `1.5 × atr_14[entry]` | spec §10 |
| Take profit | `2.5 × atr_14[entry]` | spec §10 |
| Max hold | 24 H1 bars | spec §10 |
| Exit priority | SL > TP > MaxHold > SignalReversal | spec §10 |
| T+1 semantics | Signal computed at bar-close `t`; execution at bar-open `t+1` | spec §9/§12 (TIMING_PARITY) |
| Transaction cost | Placeholder deterministic constant, pending broker selection (spec §17 Open Item #2) — modeled explicitly, never omitted | spec §10, `core/ml_r2/backtest_r2.py::BacktestConfig` (`commission_per_lot_round_turn=7.0`, `slippage_price=0.00002`) |

All of the above was independently re-read from the spec and code this session (not carried over from an earlier session summary without verification). `core/features/fe_r2_001.py`'s hash (`1d8ce135...ffd3dd`) is unchanged from every prior check this project has made — Python FE-R2-002 remains untouched, consistent with the governing instruction's prohibition on altering canonical formulas.

Relevant prior reports re-confirmed as consistent, not re-litigated: `ML-001-M5-FULL-REMEDIATION-REPORT.md` (seeded-Wilder correction), `ML-001-R2-FINAL-INTEGRITY-CLOSURE-AUDIT.md`, `ML-001-R2-PYTHON-PINE-SIMULATOR-PARITY-REPORT.md` (Pine parity — explicitly out of scope for this economic-validation report per the governing instruction's Phase 13, cited only for completeness), `ML-001-R2-ECONOMIC-VALIDATION-REPORT.md` (the prior attempt, which reached the identical `INSUFFICIENT_EVIDENCE` conclusion for the data-availability reason re-confirmed independently below).

---

## PHASE 1 — MODEL ARTIFACT FORENSICS (re-run fresh this session)

```
$ find / -xdev \( -iname "*.pkl" -o -iname "*.joblib" -o -iname "*.model" -o -iname "*.bin" -o -iname "*.pickle" -o -iname "*.onnx" \) 2>/dev/null | grep -v /proc/ | grep -viE "dist-packages|site-packages|node_modules"
```
Result: only three files, all `/tmp/pytest-of-root/pytest-*/test_export_does_not_fabricate0/not_a_real_model.joblib` — these are artifacts of *this session's own test run* of `tests/test_ml_001_r2_simulator.py::TestModelExporterFailsClosed::test_export_does_not_fabricate_pine_code`, which writes the literal bytes `b"not a real trained artifact"` to a `tmp_path` fixture specifically to prove `export_model_to_pine()` does not fabricate Pine code even when a *file* exists at the expected path. This is not a model artifact; it is a negative-test fixture, and its own name says so. Every other `.bin` match is an unrelated system binary (LibreOffice, Go toolchain test data, `valgrind`, a Chromium V8 snapshot).

```
$ git log --all --diff-filter=A --name-only | grep -iE '\.pkl$|\.joblib$|\.onnx$|\.pickle$|\.model$'
```
Result: empty. No artifact-shaped file has ever been added at any commit, on any branch, in this repository's history.

```
$ git ls-files | grep -iE '\.pkl$|\.joblib$|\.onnx$|\.pickle$|\.model$|\.bin$'
```
Result: empty. Nothing of the kind is currently tracked.

**`MODEL_ARTIFACT_EXISTS = NO`.**

Per the governing instruction: **model-dependent economic validation stops here.** No replacement model is trained. `core/ml_r2/model_r2.py::RFR2Model` is a real, instantiable, unit-tested class — it can be trained in a Python process — but "the class can train a model" is not "a trained model exists." No `.train()` call that produced a persisted artifact has ever been committed or found on disk in this environment.

---

## PHASE 2 — TRAINING PIPELINE FORENSICS

The pipeline components exist as real, independently tested code, but have never been chained together into a single "run me end-to-end against real data" script — no `train_r2.py` or equivalent CLI entrypoint was found anywhere in the repository (`find . -iname "*train*r2*"` → empty). This is a structural gap, not a correctness defect: each stage below is individually real and tested; nothing verifies the *composed* pipeline against real data, because no real data has ever been available to compose it against.

```
raw market data              → NONE AVAILABLE (Phase 3)
    ↓
deterministic preprocessing   → core/features/fe_r2_001.py::_check_weekday_gaps,
                                 _validate_ohlcv — real, tested
    ↓
canonical FE-R2-002 features  → core/features/fe_r2_001.py::build_feature_matrix —
                                 real, tested, hash-verified unchanged
    ↓
target generation             → core/ml_r2/target_r2.py::compute_label,
                                 build_training_set, assert_no_leakage — real, tested
    ↓
train/validation split         → core/ml_r2/walkforward_r2.py::compute_temporal_split,
                                  TemporalSplit — real, tested
    ↓
model training                  → core/ml_r2/model_r2.py::RFR2Model.train() — real,
                                   tested (against synthetic fixtures only, per every
                                   test file's own explicit non-economic disclaimer)
    ↓
model artifact                   → RFR2Model.save()/.load() with byte-exact checksum
                                    verification on load (ModelIntegrityError raised on
                                    mismatch) — real, tested mechanism; NO ARTIFACT HAS
                                    EVER BEEN PRODUCED THROUGH IT AND PERSISTED
```

Leakage/provenance checks specifically requested by this phase, verified by direct code read (not re-executed against real data, since none exists):
- **Future leakage**: `core/ml_r2/target_r2.py::assert_no_leakage()` exists and is exercised by `tests/test_ml_001_r2_adversarial.py` against synthetic fixtures.
- **Temporal split**: `walkforward_r2.py::compute_temporal_split`/`TemporalSplit` — chronological, not random, by construction (read directly).
- **Feature-fit isolation**: FE-R2-002's features (momentum/RSI/ATR/volatility_regime) are all causal/trailing by formula — no fitting step exists to leak (unlike a scaler), consistent with `ML-001-RECOVERY-REVALIDATION-REPORT.md`'s finding that no scaler exists anywhere in this codebase (that finding was about the *original* ML-001; independently re-confirmed here that FE-R2-002 likewise has no scaler/fit-on-data step).
- **Target leakage**: `compute_label()` is 1-bar-forward by construction; `assert_no_leakage()` specifically checks for this.
- **Deterministic seed**: `HYPERPARAMETERS["random_state"] = 42`, `_DETERMINISM_SETTINGS = {"n_jobs": 1}` (explicit, documented as a reproducibility-only setting, not a strategy hyperparameter).
- **Artifact provenance**: `core/ml_r2/model_r2.py::ModelMetadata` (frozen dataclass: `model_version`, `feature_version`, `hyperparameters`, `sklearn_version`, `python_version`, `training_timestamp`, `checksum`, ...) and `core/ml_r2/provenance_r2.py::RunProvenance`/`get_code_version()` are real, tested, and would attach genuine provenance to a real training run — again, no such run has ever occurred and been persisted.

**Conclusion**: the pipeline is *structurally* reproducible — every stage is real, tested, deterministic code with no missing component *as code*. It has never been *exercised* end-to-end, because Phase 1's blocker (no artifact) is a direct consequence of Phase 3's blocker (no data to train on) — there was never real data to run this pipeline against in the first place.

(See `ML-001-R2-TRAINING-PROVENANCE.md` for the itemized component-by-component detail behind this summary.)

---

## PHASE 3 — MARKET DATA REQUIREMENT (re-run fresh this session)

```
$ find data/ -type f
data/ea_factory.db
```
`data/csv/` and `data/cache/` contain zero files (not even the `.gitkeep` placeholders were populated with real content — confirmed empty).

```
$ ls -la .env
ls: cannot access '.env': No such file or directory

$ grep -i "API_KEY\|VENDOR\|DATA" .env.example
DATABASE_URL=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
ALPHAVANTAGE_API_KEY=
```
No `.env` file exists in this environment; the one market-data vendor field in the template (`ALPHAVANTAGE_API_KEY`) is an empty placeholder, never populated.

```
$ sqlite3 data/ea_factory.db "SELECT name FROM sqlite_master WHERE type='table'"
account_snapshots, metrics, system_events, orders, positions, strategies, validations, trades
```
No raw OHLCV table exists in the local database. (The `validations`/`trades` tables hold the RSI-EURUSD-H1 backtest *results*, not raw price bars — and that backtest's own underlying data source, per `core/data_manager.py`, is the honestly-labeled `SimulatedDataSource` (`name = "simulated"`), not a real vendor feed, per this repository's own code — this is documented here as a data-provenance fact, not reused as economic evidence for ML-001-R2, per the governing prohibition.)

**Dataset inventory table** (per the phase's required format):

| Field | Value |
|---|---|
| Vendor/source | None configured |
| Symbol | N/A |
| Timeframe | N/A |
| Timezone | N/A |
| Start / End | N/A |
| OHLCV availability | None |
| Completeness | N/A |
| Checksum | N/A |
| Provenance | N/A |
| License status | N/A |

**`REAL_MARKET_DATA = NO`.**

The Pine parity fixtures (`ML-001-R2-PINE-PARITY-FIXTURE.csv`, `ML-001-R2-GOLDEN-OHLCV-FIXTURE.csv`) are explicitly engineered synthetic data for implementation/mechanics parity testing, as labeled in every one of their own header comments and the reports that produced them. Per the governing instruction, they are **not used anywhere in this report as economic evidence** — they are cited only to note that they exist and are correctly scoped as non-economic.

---

## PHASE 4 — CANONICAL R2 ECONOMIC PIPELINE

**Not built.** The governing condition is explicit: *"If and only if BOTH real market data exists AND model artifact exists."* Neither condition holds (Phases 1 and 3). Constructing this pipeline now, with placeholder or synthetic inputs, would violate the prohibition on using synthetic data as economic evidence and on fabricating a model. Not attempted.

---

## PHASE 5 — STRICT DATA SPLITS

**Not created.** There is no dataset to split. `core/ml_r2/walkforward_r2.py::compute_temporal_split` and `HoldoutAccessGuard` (real, tested, one-time-access-enforcing infrastructure) stand ready to define TRAIN/VALIDATION/PURE_HOLDOUT the moment a real dataset exists — re-confirmed this session, not modified. No `HoldoutAccessGuard` has ever been invoked against real data in this repository's history (nothing to invoke it against).

---

## PHASE 6 — BASELINE ECONOMIC TEST

**Not run.** There is no model to produce a probability and no real data to run a backtest against. Fabricating trade_count/win_rate/expectancy/Sharpe/etc. from synthetic or placeholder inputs and presenting them here would be exactly the "manufactured result" the governing instruction prohibits. Not attempted.

---

## PHASE 7 — OUT-OF-SAMPLE VALIDATION

**Blocked.** Per the phase's own explicit rule: *"If OOS is not available: `ECONOMIC_VALIDATION = BLOCKED`."* OOS evidence requires a trained model evaluated on data it did not see — both the model and the data are absent. `OOS_VALIDATION = BLOCKED`.

---

## PHASE 8 — WALK-FORWARD VALIDATION

**Not run**, for the same reason as Phase 6/7. `core/ml_r2/walkforward_r2.py::generate_oos_predictions`/`make_walk_forward_windows` are real, tested (against synthetic fixtures, explicitly labeled non-economic in their own test file docstrings) generic infrastructure — re-confirmed unmodified this session — but have never been run against real data.

---

## PHASE 9 — ROBUSTNESS (parameter sensitivity)

**Not tested against real data.** A form of mechanical robustness *was* already established this session's prior work — `tests/test_ml_001_r2_simulator.py`'s golden-dataset regression tests exercise the position/risk mechanics (entry threshold boundaries at exactly 0.55/0.45, SL/TP/max-hold/exit-priority/position-limit) against engineered synthetic scenarios and confirm the mechanics behave exactly as specified. That is **mechanical/implementation robustness**, already reported in `ML-001-R2-PYTHON-PINE-SIMULATOR-PARITY-REPORT.md`, and is explicitly *not* the same thing as **economic parameter robustness** (i.e., "does the edge survive if SL/TP/threshold are perturbed on real market data") — which requires a real edge to perturb in the first place. `ROBUSTNESS (economic) = NOT TESTED`.

---

## PHASE 10 — COST ROBUSTNESS

**Not evaluated.** No economic result exists to stress-test against cost scenarios. `core/ml_r2/backtest_r2.py::BacktestConfig`'s cost fields (`commission_per_lot_round_turn=7.0`, `slippage_price=0.00002`, `pip_value_per_lot=10.0`) remain the documented placeholders from spec §17 Open Item #2, pending final broker selection — unchanged this session, not finalized, not evaluated for sensitivity.

---

## PHASE 11 — STATISTICAL EVIDENCE

**Not produced.** No confidence interval, bootstrap, permutation test, Monte Carlo robustness check, Sharpe-uncertainty estimate, or multiple-testing correction is computed in this report, because there is no trade series to compute any of them from. No p-value or confidence interval is manufactured to fill this section.

---

## PHASE 12 — EVG

`core/evidence_aggregator.py::AggregatedEvidence.is_authorizable()` (read directly this session, unmodified) requires, at minimum: `verdict == VALIDATED`, `sharpe >= 1.0`, `profit_factor >= 1.5`, `max_drawdown <= 0.15`, `pbo_score <= 0.5`, cost-stress pass, `oos_observations >= 50`.

**No `AggregatedEvidence` object is constructed for ML-001-R2 in this report** — there are no real inputs to construct one from (Phases 6–11 all blocked/not-run). Passing placeholder or synthetic values through the EVG to obtain a verdict would produce a verdict about the placeholders, not about ML-001-R2, and is exactly what the governing instruction prohibits ("Do not modify EVG semantics... If EVG blocks: remain BLOCKED"). The correct, honest state is that **the EVG gate was never reached** — not `FAIL` in the EVG's own vocabulary (which would imply real evidence was evaluated and found wanting), but **`INSUFFICIENT`**, the same classification this project's audits have consistently used for "the gate was never reached" versus "the gate was reached and failed."

`EVG = INSUFFICIENT` (gate not reached; not modified; no evidence assembled to pass through it).

---

## PHASE 13 — HUMAN / TRADINGVIEW

Out of scope for this report by explicit instruction. `ML-001-R2-PYTHON-PINE-SIMULATOR-PARITY-REPORT.md` and `ML-001-R2-TRADINGVIEW-MANUAL-TEST-GUIDE.md` cover Pine parity separately and are not used here as a substitute for real data, a model artifact, OOS evidence, robustness evidence, or economic validation — consistent with that report's own explicit disclaimer ("does NOT constitute economic validation").

---

## PHASE 14 — FINAL DECISION

Per the governing instruction: *"Only use `PASS — EDGE PROVEN` if the complete evidence chain is actually present. Otherwise explicitly identify the blocker."*

The complete evidence chain is not present. Two independent, hard blockers apply simultaneously:

1. **`MODEL_ARTIFACT_EXISTS = NO`** — no trained RF-R2-001 artifact exists anywhere in this repository, its git history, or this environment's filesystem (re-verified fresh this session).
2. **`REAL_MARKET_DATA = NO`** — no licensed market-data vendor is configured, no `.env` populated, no OHLCV data present locally in any form (re-verified fresh this session).

Per the **IMPORTANT STOP RULE**, both conditions independently trigger the same outcome: do not manufacture a result.

**Verdict: `ECONOMIC VALIDATION BLOCKED`.**

**Exact next dependency** (the single next actionable step, in order): acquire a real, licensed EURUSD/GBPUSD H1 market-data source (spec §17 Open Item #1 — this has been an open procurement item since the specification phase and remains unresolved). Everything downstream of that (temporal split, training, OOS, walk-forward, robustness, EVG) is already implemented, tested, and ready to run the moment real data exists — this is a data-acquisition blocker, not an implementation gap.

---

## DELIVERABLES PRODUCED

- `ML-001-R2-FINAL-ECONOMIC-VALIDATION-REPORT.md` (this file)
- `ML-001-R2-TRAINING-PROVENANCE.md` (Phase 2 detail — the training pipeline's component-by-component structural forensics)

**Not produced, and why**: `ML-001-R2-OOS-RESULTS.md`, `ML-001-R2-WALK-FORWARD-RESULTS.md`, `ML-001-R2-ROBUSTNESS-RESULTS.md` — each of these would require Phases 6–11 to have actually run against real data. None did. Creating stub or placeholder versions of these files would misrepresent that evidence exists where it does not; they are deliberately not created, per the same "do not manufacture a result" rule applied throughout this report.

---

## TESTS RUN

```
python3 -m pytest -q                                              → 533 passed, 0 failed, 0 skipped
python3 -m pytest -q tests/test_ml_001_r2_*.py tests/test_pine_parity.py tests/test_ml_001_r2_simulator.py
                                                                    → 231 passed, 0 failed, 0 skipped
```
No code was changed this session; these counts confirm the repository's existing test suite (including every R2 mechanics/feature/parity/simulator test) is unaffected by this audit and remains fully green. **These test results are mechanical-correctness evidence, not economic evidence** — no test in either run trains a model on real data, evaluates OOS performance, or computes an economic metric from anything other than engineered synthetic fixtures explicitly labeled as such in their own docstrings.

---

## FINAL STATUS

```
STRATEGY = ML-001-R2

MODEL_ARTIFACT     = NO
REAL_MARKET_DATA   = NO
PURE_HOLDOUT       = NO (never opened; nothing to open — HoldoutAccessGuard exists, untriggered)
OOS_VALIDATION     = BLOCKED
ROBUSTNESS         = NOT TESTED (economic); mechanical/implementation robustness only, reported separately
EVG                = INSUFFICIENT (gate never reached; not modified)

ECONOMIC_VALIDITY  = INSUFFICIENT_EVIDENCE
EDGE               = NOT_PROVEN

PRODUCTION = BLOCKED
```

No backtest profit, Sharpe, win rate, or equity curve is claimed anywhere in this report. No edge is claimed because a backtest looked profitable — no backtest was run. The blocker is data and model acquisition, not implementation quality: everything downstream of those two missing inputs is already built, tested, and waiting.
