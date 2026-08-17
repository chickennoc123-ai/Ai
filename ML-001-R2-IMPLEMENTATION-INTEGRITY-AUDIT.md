# ML-001-R2 IMPLEMENTATION INTEGRITY AUDIT

**Date**: August 17, 2026
**Role**: Independent senior quantitative-system auditor (read-only)
**Subject commit**: `90a6cf6` — confirmed via `git diff 90a6cf6 --stat` (empty) that the working tree audited is byte-identical to this commit
**Method**: Fresh line-by-line source re-read (not reliance on the implementation's own report), manual boundary reasoning, and three genuinely separate Python process invocations to empirically test the checksum/reproducibility claims (scripts and artifacts written to `/tmp` and the session scratchpad, never to the repository; all cleaned up, `git status` confirmed clean before and after)

---

## 1. EXECUTIVE SUMMARY

The ML-001-R2 implementation's core mathematical and safety claims hold up under independent re-verification: **no feature leakage was found** (proven, not assumed, via direct inspection of every `shift()` call and an explicit causality re-derivation), **the target/feature separation is clean**, **all nine model hyperparameters match the spec exactly**, and **the bit-for-bit determinism claim is empirically confirmed across three separate process invocations**, including a from-scratch retrain in a fresh interpreter reproducing an identical SHA-256 checksum.

However, this audit also found **one direct contradiction of an explicit spec requirement** (§7's weekday-gap data-quality policy is not implemented, and a passing test locks in the opposite behavior) and **eight Medium-severity gaps**, most centering on one theme: several safety/provenance mechanisms are *built and unit-tested in isolation* but **not wired into the actual pipeline call paths** — `assert_no_leakage`, `RunProvenance`, and a feature-schema-file generator all exist as working, tested code that nothing in the real training/walk-forward path ever calls. None of these rise to the audit's own defined Critical/High categories (no proven leakage, no formula error, no hyperparameter mismatch, no walk-forward contamination, no timing error, no false provenance claim, no false reproducibility claim) — each is a **capability gap or missing automatic enforcement**, not an active defect that produces wrong output today.

**Verdict: `IMPLEMENTATION_INTEGRITY_CONDITIONAL`.**

---

## 2. SPECIFICATION COVERAGE MATRIX

| Spec § | Requirement | File → Function | Test | Status |
|---|---|---|---|---|
| §2 | `model_version = RF-R2-001` | `model_r2.py::MODEL_VERSION` | `test_model.py` | **EXACT** |
| §2 | `feature_version = FE-R2-001` | `fe_r2_001.py::FEATURE_VERSION` | `test_features.py` | **EXACT** |
| §2 | `strategy_id`, `strategy_version` as canonical values | *(no constant defined anywhere in `core/`)* | only used ad hoc in `provenance_r2.py` tests | **PARTIAL** — no single source-of-truth constant exists; risk of divergent hardcoded copies |
| §2 | `data_version`, `research_version` | correctly deferred (no real data yet) | — | N/A, not a gap |
| §3 | Old rejected values (`0.001` threshold, `n_estimators:100`, 7.2% allocation) absent from code | confirmed absent in `target_r2.py`, `model_r2.py`, `backtest_r2.py` | — | **EXACT** |
| §4 | `momentum_5`/`momentum_20` formula | `fe_r2_001.py::compute_momentum` | `test_momentum_5_formula_is_exact` (hand-computed) | **EXACT** |
| §4 | `rsi_14`/`atr_14` formula | `fe_r2_001.py::compute_rsi_14/compute_atr_14` → `core/indicators.py` | warmup-boundary tests only, no independent numeric reference check | **EXACT** per spec's own "reference implementation" clause (see Finding I-1 on a spec-internal wording inconsistency) |
| §4 | `volatility_regime` formula/boundaries | `fe_r2_001.py::compute_volatility_regime` | class-membership + causality tests; **no explicit boundary-equality test** | **EXACT** on manual inspection (`<`/`>` strict, inclusive-normal default verified by reading the code); boundary case untested |
| §4 | Warmup bars `{5,20,100,100,600}` | `fe_r2_001.py::WARMUP_BARS` | `test_warmup_boundaries_are_exact` | **EXACT** |
| §4 | Fixed feature ordering, single canonical module | `fe_r2_001.py::FEATURE_ORDER`; imported identically by `model_r2.py`, `walkforward_r2.py` | grep-confirmed no second implementation exists | **EXACT** |
| §5 | Binary label formula, undefined-not-zero final bar | `target_r2.py::compute_label` | `TestLabelCorrectness` (7 tests incl. boundary) | **EXACT** |
| §5 | Feature/label leakage separation | features never use negative `shift`; labels always do | manual re-derivation (§4 below) | **PROVEN_ABSENT** |
| §5 | Leakage guard callable | `target_r2.py::assert_no_leakage` | tested directly, but **zero call sites in production code** (`align_features_and_labels`, `RFR2Model.train`, `generate_oos_predictions` never call it) | **PARTIAL** — implemented but not wired (Finding M-1) |
| §6 | All 9 `RandomForestClassifier` hyperparameters | `model_r2.py::HYPERPARAMETERS` | `TestHyperparameterSpecification` (asserts every value) | **EXACT** |
| §6 | `random_state=42`, bit-for-bit determinism | same | `TestModelDeterminism` + independent 3-process empirical test (§6 below) | **EXACT, empirically proven** |
| §6 | Model artifact (`.joblib`) | `RFR2Model.save()` | `TestModelPersistence` | **EXACT** |
| §6 | Metadata JSON: algorithm, hyperparameters, sklearn version, training timestamp, **feature_version, data_version** | `ModelMetadata` dataclass | — | **PARTIAL** — `data_version` field is explicitly named in spec §6 point 2 and is **absent** from `ModelMetadata` entirely (Finding M-6) |
| §6 | Training manifest (date range, row count, class balance) | present, but merged into the *same* metadata.json rather than a separate file per §16's naming convention | — | **PARTIAL** (content complete, file-layout convention not followed — spec marks §16 "proposed," so low severity) |
| §6 | Feature schema JSON artifact | `fe_r2_001.py::get_feature_schema()` exists and is correct, but **no code path ever writes it to disk** | `test_get_feature_schema_matches_module_constants` only calls it in-memory | **MISSING** as an artifact (Finding M-7) |
| §6 | SHA-256 checksum in manifest | `ModelMetadata.checksum` | `test_train_produces_complete_metadata` | **EXACT** |
| §7 | Data schema/timezone/provenance | correctly out of scope (no real data acquisition yet) | — | N/A |
| §7 | **Weekday gaps >1 bar = data-quality violation requiring investigation** | `fe_r2_001.py::_validate_ohlcv` has **no such check** — only checks duplicates and monotonicity | `test_a_gap_in_the_index_does_not_corrupt_downstream_computation` **explicitly asserts gaps are silently tolerated** | **CONTRADICTED** (Finding C-1) |
| §7 | Slippage 0.2 pip deterministic buffer | `backtest_r2.py::BacktestConfig.slippage_price = 0.00002` | `TestStopLossTriggers` etc. use it | **EXACT** |
| §8 | Chronological 60/20/20 split, no random split | `walkforward_r2.py::compute_temporal_split` | `TestTemporalSplit` (5 tests) | **EXACT** |
| §8 | `ProvenanceEnforcer` reuse for boundary enforcement | reused unmodified | `TestHoldoutAccessGuard` | **EXACT** |
| §8 | PURE_HOLDOUT opened exactly once | `walkforward_r2.py::HoldoutAccessGuard` | `test_holdout_second_access_blocked` | **EXACT** |
| §8 | Split boundaries hashed and frozen into a manifest | **no hashing/manifest-writing code exists anywhere** | — | **MISSING** |
| §9 | Fresh model per walk-forward window (no online updates) | `walkforward_r2.py::generate_oos_predictions` — `model = RFR2Model()` inside the window loop | `test_oos_predictions_are_registered_with_full_provenance` | **EXACT** |
| §9 | Every OOS prediction tagged with model/feature version | `OOSPredictionBatch` fields set on every batch | same test | **EXACT** |
| §9 | No lookahead in walk-forward predictions | window `test_dates` strictly after `train_dates[1]` | `test_oos_predictions_use_only_past_training_data` | **PROVEN_ABSENT** |
| §9 | `WFAPredictionEngine` reuse | window generation reused verbatim; `generate_predictions` **deliberately not reused** (documented lookback incompatibility) | — | **EXACT** — deviation is disclosed, not silent |
| §10 | LONG/SHORT/FLAT thresholds `0.55`/`0.45` | `backtest_r2.py::BacktestConfig` | `TestSignalReversal`, entry tests | **EXACT** |
| §10 | Position sizing formula | `_position_size` | `TestPositionSizing` | **EXACT** |
| §10 | Max 1 position per symbol | enforced structurally (`open_trade: Optional[Trade]`, never a list) | `TestNoEntryWhilePositionOpen` (weak — see Finding L-1) | **EXACT behavior**, but... |
| §10 | ...via a configurable `max_positions_per_symbol` | field declared, **never read anywhere in `run_backtest`** | — | **PARTIAL** — dead config surface (Finding M-4) |
| §10 | SL `1.5×ATR`, TP `2.5×ATR` | `run_backtest` | `TestStopLossTriggers`, `TestTakeProfitTriggers` (both hand-verify exact price) | **EXACT** |
| §10 | Max holding 24 bars, forced flat | `run_backtest` | `TestMaxHoldingPeriod` | **EXACT** |
| §10 | Exit priority SL > TP > MAX_HOLD > REVERSAL | `if/elif` chain in that literal order | all four backtest scenario classes together | **EXACT** |
| §10 | Reversal exits next bar's open, not same bar | `pending_exit` deferred-execution pattern | `test_reversal_closes_at_next_bar_open_not_same_bar` | **EXACT** |
| §11 | Portfolio risk thresholds deferred to Phase 12 | correctly not invented | — | **EXACT** (compliance = not doing it yet) |
| §12 | FEATURE_PARITY | single module, grep-confirmed no duplicate implementation | — | **EXACT** |
| §12 | SIGNAL_PARITY | `run_backtest` takes probabilities as an **external input**, not computed via a single named "inference function"; no production/paper-trading runner exists yet to compare against | — | **PARTIAL** — underlying capability supports parity, but no dedicated enforced abstraction, and the second required call site doesn't exist yet |
| §12 | TIMING_PARITY | backtest-side next-bar-open execution is exact and tested; "genuine event-driven bar-close handler" for live use does not exist (correctly out of scope) | — | **PARTIAL** (backtest half EXACT, production half correctly deferred) |
| §13 | No Pine Script generated | confirmed, `find -iname "*.pine"` returns nothing | — | **EXACT** |
| §14 | All 10 governance gates NOT_STARTED | no governance file modified (`git show --stat 90a6cf6` confirms) | — | **EXACT** |
| §15 | Bit-for-bit reproducible model artifact | — | independently re-verified, §6 below | **EXACT, empirically proven** |
| §15 | Manifests committed alongside code, never orphaned | no manifest has ever been produced or committed (nothing to commit yet — correctly consistent with RESEARCH_ONLY status, but see §16 gap above) | — | N/A for now, mechanism incomplete (ties to M-6/M-7) |

---

## 3. FEATURE AUDIT

Independent manual trace of every feature, focused on the audit's explicit leakage requirement:

| Feature | Lookback | Source price | Warmup | NaN handling | Ordering | Dtype | Numerical stability |
|---|---|---|---|---|---|---|---|
| `momentum_5` | 5 (`close.shift(5)`) | close | 5 bars, exact | forced NaN via `_apply_warmup` | index 0 | float64 | `inf`/`-inf` explicitly caught and converted to NaN (division-by-near-zero guard) |
| `momentum_20` | 20 | close | 20 bars | same | index 1 | float64 | same |
| `rsi_14` | 14 (ewm) | close | 100-bar burn-in enforced independently of the 14-bar `min_periods` | same | index 2 | float64 | delegates to `core/indicators.py`, which already guards the zero-avg-loss divide-by-zero case |
| `atr_14` | 14 (ewm on True Range) | high/low/close | 100-bar burn-in | same | index 3 | float64 | same delegation |
| `volatility_regime` | 500-bar rolling percentile on top of `atr_14` | derived | 600 bars (500+100) | same | index 4 | float64 (not literal int — see Finding I-2) | quantile computation is a standard pandas rolling op, no observed instability |

**Manual boundary reasoning — `feature(t)` cannot access `price(t+1)`:**

I traced every `.shift(...)` call in `fe_r2_001.py` by hand:
- `compute_momentum`: `close.shift(lookback)` with `lookback > 0` — pandas positive shift pulls **past** values forward to align with the current index (`close.shift(5).iloc[t] == close.iloc[t-5]`), confirmed by direct reasoning about pandas semantics, not assumption.
- `compute_rsi_14`/`compute_atr_14`: delegate to `core/indicators.py`, which uses only `.diff()`, `.ewm(...)`, and `close.shift(1)` inside `true_range` (also a positive/backward shift) — no negative shift anywhere.
- `compute_volatility_regime`: `.rolling(window=500, ...)` — pandas rolling windows are right-aligned by default (window `[t-499, t]`), confirmed causal.
- **Zero occurrences of `.shift(-N)` or any other future-indexing pattern exist anywhere in `fe_r2_001.py`.** (Grep-verified as part of this audit; matches the earlier read of the full file.)

Compare against `target_r2.py::compute_label`, which uses `close.shift(-1)` — the **only** negative shift in the entire feature/target codebase, confined exclusively to the label module, never imported into `fe_r2_001.py` or vice versa.

**FEATURE_LEAKAGE = PROVEN_ABSENT.** This is not "not found on inspection" — it is a positive, exhaustive claim backed by a complete enumeration of every shift/rolling operation in the feature pipeline.

---

## 4. TARGET AUDIT

- **Horizon**: exactly 1 bar (`close.shift(-1)`), matches spec §5 exactly.
- **Threshold**: none, strict `>`/`<=` comparison, matches spec's explicit rejection of the old `0.001` threshold.
- **Future price usage confined to labels**: confirmed above — `target_r2.py` is the only module in the codebase that reads a future bar.
- **Label timestamp**: `label[t]` is stored at index `t` but its docstring and this audit both confirm it represents information *available only at* `t+1` — this is a **naming/storage convention worth flagging as a real footgun**: nothing in the type system prevents a future caller from reading `labels.loc[t]` and treating it as available at `t`. The only defense is `align_features_and_labels`'s masking (which drops the correct rows) and `assert_no_leakage` (which is not wired in — Finding M-1). This is a design-level observation, not a proven defect, since every current call site (`align_features_and_labels`, `generate_oos_predictions`) handles the alignment correctly.
- **Neutral class**: correctly absent — `<=` maps ties to class 0, per spec.
- **Alignment with feature timestamp**: `align_features_and_labels` requires `features.index.equals(labels.index)` before masking — verified exact index equality, not just same length.

No leakage found. No target-alignment defect found.

---

## 5. MODEL AUDIT

- **Algorithm**: `sklearn.ensemble.RandomForestClassifier`, confirmed by import statement, not merely by name.
- **Hyperparameters**: all nine spec values present and matched exactly (`n_estimators=300, max_depth=6, min_samples_split=50, min_samples_leaf=25, max_features="sqrt", class_weight="balanced", criterion="gini", bootstrap=True, random_state=42`). Verified both by direct code read and by re-running `TestHyperparameterSpecification`.
- **Undisclosed addition**: `n_jobs=1` is added via a separate `_DETERMINISM_SETTINGS` dict, clearly documented as non-strategic. Confirmed this does not silently become an unlisted "10th hyperparameter" — it is kept structurally and textually separate from `HYPERPARAMETERS`.
- **Feature order enforcement**: `_validate_feature_schema` checks `list(X.columns) == list(FEATURE_ORDER)` on every `train`/`predict`/`predict_proba` call — verified exact name-and-order match, not just set membership (a reordered-but-same-set input is correctly rejected; confirmed via `TestFeatureReordering`).
- **Target schema**: `y.isna().any()` checked; length-match checked; empty-dataset checked.
- **Dtype validation**: **not explicitly checked** — `_validate_feature_schema` validates column names/order and NaN-freedom, but not dtype (Finding L-2, Low severity — sklearn would raise its own, less-clear error on genuinely bad input; no silent-corruption path was found).
- **`predict_proba` class-index lookup**: `list(self._model.classes_).index(1)` was independently sanity-checked (`[0.0, 1.0].index(1) == 1` in Python, since `1 == 1.0`) — confirmed correct, not a latent bug.

Serialization safety is covered in detail in §6 (Checksum Forensics) below, since it warranted its own empirical investigation.

---

## 6. CHECKSUM FORENSICS

This required its own empirical investigation, run as three genuinely separate Python process invocations (each `python3 <script>` a fresh interpreter, artifacts passed via files on disk — not in-memory objects shared across "runs" within one pytest session).

**Process 1** (train + save): trained `RF-R2-001` on synthetic data (seed 999, 800 bars), saved artifact + metadata, recorded `metadata.checksum` and independently re-hashed the on-disk file:
```
metadata.checksum      = 761fda53f7276589dc9b1d40c8d6c502c27696b279aa690733fb56690fe01a22
sha256(model.joblib)   = 761fda53f7276589dc9b1d40c8d6c502c27696b279aa690733fb56690fe01a22
match: True
```

**Process 2** (fresh interpreter, load + verify): loaded that artifact, confirmed checksum persisted across the process boundary, and confirmed `predict_proba` output was bit-identical to Process 1's saved predictions:
```
cross-process checksum match: True
predictions identical after cross-process load: True
```
Then ran a single-byte tamper test on the artifact file: `RFR2Model.load()` correctly raised `ModelIntegrityError` — **modified model file detection: PROVEN**.

**Process 3** (fresh interpreter, from-scratch retrain, same seed-999 data — no loading involved at all): reproduced the identical checksum:
```
761fda53f7276589dc9b1d40c8d6c502c27696b279aa690733fb56690fe01a22
```
This is the strongest evidence in the audit: **training determinism holds across process boundaries**, not merely within one Python session.

**Coordinated-tamper experiment** (the critical distinction the audit asked for): I trained a second, genuinely different model on different synthetic data (seed 12345), then simulated an attacker who replaces **both** `model.joblib` and `metadata.json` consistently (i.e., recomputes the checksum for the substituted model and writes that correct-for-the-substitute value into the metadata). Result:
```
loaded checksum matches substituted (attacker) checksum: True
load() succeeded WITHOUT raising ModelIntegrityError
```

**This is the key finding.** The checksum mechanism proves **artifact_identity is internally self-consistent with its co-located metadata** — i.e., "this `model.joblib` is the exact bytes this `metadata.json` was written for." It does **not** prove **artifact authenticity against the actual research run that supposedly produced it**, because both files live in the same trust domain and can be replaced together by anyone with write access to both. Detecting a coordinated replacement requires the checksum to be recorded in an **independent** channel the same actor cannot also rewrite — which is exactly what `RunProvenance` (`provenance_r2.py`) is designed for, but as confirmed in §2 above and §9 below, `RunProvenance` is never actually constructed by `RFR2Model.train()`/`save()` or committed anywhere. The capability to close this gap exists in the codebase; it is simply not wired up yet.

**Detection matrix**:

| Threat | Detected? |
|---|---|
| Modified model file (bytes altered, metadata unchanged) | ✅ **YES** — proven via single-byte tamper test |
| Replaced model file with metadata left pointing at the old checksum | ✅ **YES** (same mechanism) |
| Coordinated replacement of both model file and metadata (checksum recomputed to match) | ❌ **NO** — proven via the substitution experiment above |
| Changed feature schema (same names, different formula, i.e. `FE-R2-002` swapped in silently) | ❌ **NO** — `load()` never compares `metadata.feature_version` to the currently-imported `FEATURE_VERSION` constant (grep-confirmed: `feature_version` appears in `model_r2.py` only at field declaration and at `train()`-time assignment, never in a comparison) |
| Changed training data (different dataset, same nominal row count/date range) | ⚠️ **PARTIALLY** — `training_rows`/`class_balance`/date range are recorded and could reveal gross differences, but there is no dataset checksum bound into `ModelMetadata` (that field only exists, unconnected, in `RunProvenance`) |

---

## 7. WALK-FORWARD AUDIT

**Explicit timeline example** (constructed for this audit, not copied from the implementation's own report):

Given a call `generate_oos_predictions(df, windows, hypothesis_id="X", training_data_state=DEVELOPMENT, test_data_state=VALIDATION)` and one window `W` with `train_start=0, train_end=1200, test_start=1200, test_end=1500`:

| Quantity | Value | How determined |
|---|---|---|
| Training data | `df.iloc[0:1200]` | `window.train_start:train_end`, strictly before `test_start` — structurally guaranteed non-overlapping by `WFAWindow.__post_init__` (reused, unmodified validation) |
| Feature data for training | computed only from `df.iloc[0:1200]` | `build_feature_matrix(train_df)` — no access to rows ≥1200 |
| Model version | fresh `RFR2Model()` instance, trained once for this window only | `model = RFR2Model()` created *inside* the per-window loop — confirmed no reuse/carry-over across windows |
| Feature data for a prediction at row 1250 | `df.iloc[600:1500]` extended-then-trimmed (600 = `MAX_WARMUP_BARS`), features computed over that range, **then rows before 1200 discarded** before being handed to the model | `extended_start = max(0, 1200-600) = 600`; `test_features = extended_features.loc[df.index[1200]:]` |
| Prediction timestamp | `df.index[1250]` (bar close) | `usable_features.index` |
| Execution timestamp | not computed here — that is `backtest_r2.py`'s job (next bar open), correctly out of scope for the walk-forward layer | — |
| Accessible data at prediction time | everything in `df.iloc[0:1251]` (train + warmup-extended test history up to and including bar 1250) | by construction of the extended-slice logic |

I manually verified `1200 < 1250` (test bar strictly after training window end) and that the model consuming bar 1250's features was fit exclusively on `df.iloc[0:1200]` — **no future training, no model contamination, confirmed for this concrete example**, not merely asserted in the abstract.

**A real gap, found independently, not previously disclosed in the implementation report**: `generate_oos_predictions`'s `ProvenanceEnforcer` check validates the **caller-declared** `training_data_state`/`test_data_state` labels against the allowed-action matrix (e.g., rejects `training_data_state=VALIDATION`) — but it does **not** structurally verify that the `df` argument's actual row range is consistent with those declared labels. Nothing stops a caller from passing a `df` that secretly spans into `PURE_HOLDOUT`-period rows while still declaring `test_data_state=VALIDATION`; the function has no way to detect this because it only sees row positions, not calendar-boundary metadata. Within a **single call**, train/test non-overlap is structurally guaranteed (tested); the risk is entirely at the **caller-discipline** layer, one level up. This is a defense-in-depth gap, not a proven contamination — every existing test correctly scopes its `df` — but it is worth flagging precisely because "walk-forward contamination" is exactly the failure mode the spec's Section 8 provenance requirements exist to prevent, and this particular avenue is not closed.

---

## 8. BACKTEST AUDIT

Checked against the audit's named risk categories:

| Category | Finding |
|---|---|
| **LOOKAHEAD** | None found. Entries and signal-reversal exits are scheduled at bar `t`'s close and executed at bar `t+1`'s open via the `pending_entry`/`pending_exit` deferred-execution pattern — traced through the loop by hand, confirmed no code path reads `ohlcv.iloc[i+1]` before iteration `i+1`. |
| **SURVIVORSHIP BIAS** | Not applicable at this layer — `run_backtest` operates on whatever OHLCV frame it is given; survivorship bias would be a property of the (not-yet-acquired) dataset, not this mechanics module. |
| **INTRA-BAR ASSUMPTION** | **Present, and spec-mandated, not a hidden implementation choice.** A bar's OHLC alone cannot reveal whether the high or the low occurred first within the bar. The code resolves this by always checking `STOP_LOSS` before `TAKE_PROFIT` on the same bar — this is exactly spec §10's literal priority ordering ("Stop loss > Take profit"), so the implementation is compliant, but the *reason* this ordering doubles as an intrabar-sequencing tie-break is not explicitly called out in the module docstring (documentation gap, not a behavioral one). |
| **DOUBLE EXECUTION** | None found. Manually traced the `pending_entry`/`pending_exit` state machine: a pending action can only be set when the corresponding state variable is `None`, and is always consumed (set back to `None`) at the top of the very next iteration before the scheduling block for that same kind of action runs again. No path found where a signal could be scheduled twice or lost. |
| **SIGNAL REUSE** | None found. Each bar's probability value is read at most twice in the same iteration (once for reversal-check on an open position, once for new-entry scheduling) but these are mutually exclusive (`open_trade is not None` vs. `open_trade is None and pending_entry is None`), so no probability value drives two independent actions. |
| **POSITION STATE CORRUPTION** | None found — `open_trade` is a scalar `Optional[Trade]`, not a list, so the "max 1 position" invariant is structurally unbreakable by construction. **However**, `BacktestConfig.max_positions_per_symbol` (declared, default `1`) is **never read anywhere in `run_backtest`'s logic** — grep-confirmed zero references outside its own field declaration. The correct behavior is achieved *incidentally* by the data structure choice, not by honoring this config value. Changing `max_positions_per_symbol` to any other number would have **zero effect**. This is a real, testable-and-testably-absent gap (Finding M-4). |

**Cost model**: commission, slippage, and (implicitly, via the entry-price offset) spread-like costs are all applied on every trade — confirmed no code path skips cost application. Cost figures themselves are correctly flagged (in both spec and code comments) as placeholders pending broker selection, not presented as final.

---

## 9. PROVENANCE AUDIT

`RunProvenance` (`provenance_r2.py`) is well-designed and its own tests are thorough (completeness rejection tested field-by-field). But tracing its actual **usage**:

```
grep -rn "RunProvenance(" core/ tests/  →  zero matches outside provenance_r2.py's own test file
```

**No code anywhere in `RFR2Model.train()`, `RFR2Model.save()`, or `generate_oos_predictions()` ever constructs a `RunProvenance` record.** The class exists, is correct, and is unit-tested — but it is not yet an operative part of any real pipeline run. A researcher training a model today via `RFR2Model.train()` gets a `ModelMetadata` record (missing `data_version` per Finding M-6) but **no `RunProvenance` record is produced automatically, and none is rejected for incompleteness, because none is ever created.**

Field-by-field status if/when it *is* wired up:
- `strategy_id`, `strategy_version`: no canonical constant exists to source these from (Finding, §2 table)
- `model_version`, `feature_version`: available from `ModelMetadata`, would need to be threaded through
- `dataset_id`, `dataset_checksum`: **no code anywhere computes a dataset checksum** (confirmed by re-checking `walkforward_r2.py` — zero references to "checksum" or "dataset_id")
- `code_version`: no code captures a git commit hash or similar anywhere
- `model_checksum`: available from `ModelMetadata.checksum`
- `random_seed`: available from `HYPERPARAMETERS["random_state"]`

**Conclusion**: the provenance *mechanism* (the dataclass, its completeness check) is sound and correctly designed to "reject a result without complete provenance." The provenance *pipeline* (something that actually populates one on every real run) does not exist yet. This is the same theme as Finding M-1 (`assert_no_leakage`) and Finding M-7 (feature schema file) — well-built, tested components that are not yet load-bearing.

---

## 10. REPRODUCIBILITY AUDIT

The instruction asks me to distinguish several claims. Based on the empirical work in §6:

| Claim | Evidence | Verdict |
|---|---|---|
| **A. Deterministic execution, same process** | `TestModelDeterminism` (two `RFR2Model` instances trained in-process on identical data) | **PROVEN** |
| **B. Reproducible artifact, separate process** | Process 2 loaded Process 1's saved artifact and reproduced identical predictions and checksum | **PROVEN** |
| **C. Reproducible training, separate Python invocation** | Process 3 retrained from scratch (no loading at all) and reproduced Process 1's exact checksum | **PROVEN — this is the strongest of the three, since it rules out any artifact-caching explanation** |
| **D. Freshly loaded model artifact behaves identically to the in-memory original** | Process 2's `predict_proba` comparison | **PROVEN** |

**Distinguishing the three concepts the audit asked for:**
- **Deterministic execution** (same code + same data + same config → same output, verified in-process): **PROVEN**.
- **Reproducible artifact** (the serialized bytes and their behavior survive save/load and process boundaries intact): **PROVEN**.
- **Reproducible research result** (in the sense of a *stable, economically meaningful* finding): **NOT ESTABLISHED, AND NOT CLAIMED** — the implementation report never asserts this, and this audit finds no basis to assert it either. All reproducibility evidence, old and new, is confined to deterministic *mechanics* on synthetic fixtures.

**The strongest supported claim, stated precisely**: *Given identical code, identical (including synthetic-fixture) data, and a fixed execution configuration (`n_jobs=1`, this exact scikit-learn/joblib/Python version), `RF-R2-001` training and inference are bit-for-bit deterministic, and this determinism survives serialization and process boundaries.* This does **not** extend, and was never tested to extend, across different `n_jobs` settings, different library versions, or different hardware/platforms — those would need their own verification before being claimed (Finding I-3, informational, not a defect since no such claim was made).

No false reproducibility claim was found. If anything, the implementation report's Section 12 claim was slightly *under*-stated relative to what this audit was able to independently prove (it demonstrated same-process RUN A/RUN B equality; it did not itself attempt the cross-process retrain that Process 3 above performed).

---

## 11. TEST QUALITY AUDIT

93 tests reviewed. Most exercise genuine implementation correctness, boundary conditions, and adversarial scenarios, not merely "does it run." Specific findings:

**Genuinely strong**:
- `test_momentum_5_formula_is_exact`, `TestStopLossTriggers`/`TestTakeProfitTriggers` (hand-computed expected prices, not tautological), `test_holdout_second_access_blocked`, the full `TestEndToEndReproducibility` suite, and the leakage-guard mismatch tests all independently recompute an expected value and compare — these would fail if the implementation were subtly wrong.

**Weak or could pass despite a real defect**:
- `TestNoEntryWhilePositionOpen::test_single_open_position_enforced` — contains dead code (`open_trades_at_any_time = 1` is assigned and never used; `+ ([] if True else [])` is a no-op). Its core assertion (`len(entries) <= 1`) is close to tautological given `open_trade` is already structurally a scalar — this test would likely still pass even under a plausible mutation (e.g., a bug that scheduled a *second* `pending_entry` while one was already pending, only to have it silently overwritten) because it only checks the *final* entry count, not the intermediate state transitions. (Finding L-1.)
- `test_feature_version_drift_is_observable_in_saved_metadata` — proves the drift is *externally checkable* by comparing two strings, which is true but weaker than its name might suggest to a reader skimming the test suite; it does **not** prove any enforcement exists in `load()`/`predict()` (confirmed in §5/§9 — none does). A reader could reasonably (and incorrectly) conclude from the test's presence that mismatch protection is automatic. (Ties to §5/§9 findings.)
- RSI/ATR correctness (both in this suite and the pre-existing `test_indicators.py`) is verified only via **properties** (bounded `[0,100]`, high on a monotonic-up series, low on a monotonic-down series, ATR positive) — **never against an exact hand-computed or externally-sourced reference value**. A formula bug that preserved these properties (e.g., an off-by-one in the smoothing constant, or `alpha=1/13` instead of `1/14`) could plausibly pass every existing test in the repository. (Finding M-5.)
- `test_volatility_regime_is_ordinal_zero_one_two` checks the *value set*, and a separate causality test checks *no future leakage*, but no test constructs an ATR series with a value **exactly equal to** the 33rd/67th percentile to confirm the inclusive-normal boundary semantics — verified correct only by my own manual code reading in §2/§3, not by a dedicated test.

**Categories covered vs. not covered** (per the audit's own checklist):

| Category | Covered? |
|---|---|
| Implementation correctness | Yes, mostly strong |
| Edge cases (warmup, boundary bars, empty data) | Yes |
| Adversarial cases (shuffled/duplicate timestamps, reordering, tamper) | Yes, 16 dedicated tests |
| Leakage | Yes, both direct and adversarial |
| Temporal integrity | Yes |
| Serialization | Yes, including the round-trip that surfaced the real checksum bug during implementation |
| Provenance | Only for the standalone `RunProvenance` dataclass — **no test exists (because no code exists) for provenance being produced by an actual training run**, which is consistent with Finding M-1/§9 above rather than a separate gap |

---

## 12. SYNTHETIC DATA BOUNDARY

Confirmed, independently:
- `tests/r2_fixtures.py::make_synthetic_ohlcv` is the only data-generation function referenced anywhere in the 93 R2 tests (grep-confirmed no other data source).
- No file in the repository claims a Sharpe ratio, profit factor, drawdown, or any other economic metric attributable to ML-001-R2 — confirmed by re-reading the implementation report and every test file; the only performance-shaped numbers that appear (`equity_curve`, `final_equity`) exist solely inside mechanics-verification tests using 3-4 bar hand-constructed fixtures explicitly labeled as such.
- **PURE_HOLDOUT was never accessed against real (or even synthetic-as-if-real) data.** Every `FINAL_EVALUATION`/`PURE_HOLDOUT` reference in the codebase is either (a) the guard mechanism's own definition, or (b) a test using `HoldoutAccessGuard` with a synthetic fixture and a test-only `hypothesis_id`.

**This boundary held throughout the implementation and holds under this independent audit.**

---

## 13. GOVERNANCE BOUNDARY

Independently re-verified, not merely re-stated from the implementation report:
- `git show --stat 90a6cf6` — no governance, validation-result, decision-engine, or risk-governance file appears in the diff.
- `find /home/user/Ai -iname "*.pine"` — zero results.
- No broker/connectivity code was added (confirmed by the file list in the commit: only `core/features/`, `core/ml_r2/`, `tests/`, and `requirements.txt`).
- No authorization, allocation, or EVG-pass state was created anywhere — no such state-holding structure was even touched.

```
RESEARCH_ONLY        — confirmed, no code claims otherwise
NOT_VALIDATED         — confirmed, no economic metric computed on real/synthetic-as-real data
NOT_AUTHORIZED        — confirmed
PRODUCTION_BLOCKED    — confirmed, no broker code exists
PINE_BLOCKED          — confirmed, no Pine artifact exists
```

---

## 14. FINDINGS BY SEVERITY

**CRITICAL**: none.

**HIGH**: none. (See discussion below — several candidates were considered and downgraded to Medium because, on the audit's own stated examples for this tier — proven leakage, formula error, hyperparameter mismatch, proven contamination, timing error, a *false* provenance claim, a *false* reproducibility claim — none of my findings are active, proven defects that produce wrong output today; they are capability/wiring gaps in code that is otherwise correct.)

**MEDIUM** (8):
1. **M-1**: `assert_no_leakage` is implemented and tested but never called from any production code path (`align_features_and_labels`, `RFR2Model.train`, `generate_oos_predictions`).
2. **M-2**: The model checksum mechanism proves artifact↔metadata self-consistency, not authenticity against a coordinated replacement of both files — empirically demonstrated in §6. Mitigation (independent provenance recording) exists in the codebase but is unwired (ties to M-9/Provenance §9).
3. **M-3**: `generate_oos_predictions` trusts the caller's declared `training_data_state`/`test_data_state` without structurally verifying the actual `df` row-range matches — a caller error could pass holdout-period rows under a `VALIDATION` label undetected.
4. **M-4**: `BacktestConfig.max_positions_per_symbol` is declared but never read anywhere in `run_backtest` — dead, misleading configuration surface.
5. **M-5**: RSI/ATR numeric correctness is verified only via properties (bounded, directionally correct) everywhere in the repository, old and new — never against an exact reference value. A subtle formula bug could pass all existing tests.
6. **M-6**: `ModelMetadata` is missing the `data_version` field, which spec §6 explicitly names as a required metadata component.
7. **M-7**: The Feature Schema JSON artifact required by spec §6/§16 has no code path that ever writes it to disk — `get_feature_schema()` exists but is only exercised in-memory in one test.
8. **M-8**: `RFR2Model.load()` never compares the loaded artifact's `feature_version` against the currently-imported `FE-R2-001` module's `FEATURE_VERSION` constant — a stale/mismatched model would load and predict without any error.
9. **M-9**: `RunProvenance` is fully implemented and tested in isolation but never constructed by any real training/walk-forward code path (§9).

**CONTRADICTED** (1, tracked separately since it's a distinct classification from Medium-severity gaps, though I assess its severity as Medium):
- **C-1**: Spec §7 explicitly requires weekday gaps >1 bar to be treated as a data-quality violation requiring investigation. `fe_r2_001.py::_validate_ohlcv` implements no such check, and `tests/test_ml_001_r2_adversarial.py::test_a_gap_in_the_index_does_not_corrupt_downstream_computation` explicitly asserts and locks in the opposite (permissive) behavior. This was not disclosed as a deviation anywhere in the implementation report.

**LOW** (3):
1. **L-1**: `TestNoEntryWhilePositionOpen` contains dead/vestigial code and is a structurally weak test relative to what it claims to verify.
2. **L-2**: `_validate_feature_schema` does not explicitly validate column dtype, relying on sklearn to raise a less-specific downstream error.
3. **L-3**: Training-manifest content is merged into `metadata.json` rather than split into the two separate files §16's naming convention proposes (spec marks this "proposed," so low severity).

**INFORMATIONAL** (5):
1. **I-1**: Spec §4's own prose description of Wilder RSI seeding ("simple mean of the first 14 gains/losses") and its "reference implementation" pointer (`core/indicators.py`'s `ewm(adjust=False)` recursion) are two different, only asymptotically-converging formulations — a spec-internal wording inconsistency, not a code defect, since the code correctly follows the authoritative reference-implementation clause.
2. **I-2**: `volatility_regime` is stored as `float64`, not a literal integer dtype, because pandas cannot represent NaN in a standard integer column — the *values* are integral, the *column type* is not.
3. **I-3**: The reproducibility claim is scoped to a fixed execution configuration (`n_jobs=1`, this exact dependency stack) — proven exact within that scope across three separate process invocations; not tested (and not claimed) beyond it.
4. **I-4**: The intrabar SL-before-TP priority resolves an inherent OHLC-bar sequencing ambiguity and is spec-mandated, correctly implemented — named here per the audit's own checklist, not a defect.
5. **I-5**: No canonical `strategy_id`/`strategy_version` constant exists anywhere in the codebase (unlike `model_version`/`feature_version`), risking future divergent hardcoded copies.

---

## 15. REQUIRED REMEDIATION

(Documented per the audit's instructions — **not implemented in this audit**.)

Before this implementation should be considered a hardened base for the next phase:
1. Wire `assert_no_leakage` into `align_features_and_labels` or `RFR2Model.train` as an automatic check, not an opt-in.
2. Wire `RunProvenance` construction into `RFR2Model.train()`/`generate_oos_predictions()` so every real run automatically produces a complete, rejected-if-incomplete provenance record — and commit that record independently of the model artifact, so it can serve as the external check the coordinated-tamper gap (M-2) needs.
3. Add `data_version` to `ModelMetadata`; wire `get_feature_schema()` to actually write the schema JSON artifact.
4. Add a `feature_version` equality check to `RFR2Model.load()`.
5. Add a dataset-checksum computation step to the walk-forward/training pipeline.
6. Either implement the weekday-gap data-quality check per spec §7, or formally amend the spec to mark it out of scope for this phase — but do not leave the contradiction undisclosed.
7. Either wire `max_positions_per_symbol` into `run_backtest`'s entry-scheduling guard, or remove the field to stop implying a control that doesn't exist.
8. Add at least one exact-reference-value test for `rsi_14`/`atr_14` (e.g., against a hand-computed or TA-Lib-cross-checked series) and one explicit boundary-equality test for `volatility_regime`.
9. Clean up `TestNoEntryWhilePositionOpen`'s dead code and strengthen its assertion (e.g., assert on `pending_entry`/`open_trade` state at each bar, not just the final trade count).

None of these block continued research-phase work; all should be resolved before any governance gate in spec §14 is attempted.

---

## 16. FINAL VERDICT

### **IMPLEMENTATION_INTEGRITY_CONDITIONAL**

Rationale: every property this audit could test directly and adversarially — feature leakage absence, target/label correctness, hyperparameter fidelity, walk-forward non-contamination within a single call, backtest execution timing and no-double-execution, and bit-for-bit determinism across three separate process invocations — held up exactly, with no approximation accepted. No Critical or High defect (per the audit's own defined examples) was found. But nine Medium-severity gaps and one direct spec contradiction were found, concentrated on a single real theme: several safety and provenance mechanisms are built and tested correctly in isolation but not yet wired into the pipeline that would make them load-bearing on a real run. This is a fundamentally sound implementation with concrete, well-scoped gaps that require resolution — the definition of `CONDITIONAL`, not `PASS` (gaps exist and are non-trivial) and not `FAIL` (no proven Critical/High defect exists).

---

## MANDATORY FINAL STATEMENT

**This audit does NOT establish economic validity.**

**ML-001-R2 remains unauthorized for production unless and until fresh economic validation and governance gates are independently passed.**

---

**AUDIT COMPLETE — NO SOURCE CODE MODIFIED — NO TESTS MODIFIED — NO SPECIFICATION MODIFIED — NO ECONOMIC MODEL TRAINED — NO ECONOMIC BACKTEST RUN — PURE_HOLDOUT NOT OPENED — NO AUTHORIZATION GRANTED — NO PINE GENERATED — NO GOVERNANCE STATE CHANGED**

*Method: fresh independent source re-read; manual leakage boundary re-derivation; three separate Python process invocations for empirical checksum/reproducibility/tamper testing (all temporary artifacts created outside the repository and removed before this report was written; `git status` and `git diff 90a6cf6` confirmed clean throughout).*
