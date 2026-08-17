# ML-001-R2 FINAL INTEGRITY CLOSURE AUDIT

**Date**: August 17, 2026
**Baseline commit**: `e9d8b59` (independently re-verified: clean `git status`, 148 R2 tests / 450 repo tests, both passing)
**Scope**: Resolve or formally disposition M-3, M-4, M-5, M-8, L-1, L-2, L-3 — priority order M-5 → M-8 → M-3 → M-4 → L-1/L-2/L-3. No economic validation, no PURE_HOLDOUT access, no Pine, no production authorization, no change to strategy economics.

---

## 1. BASELINE

| Item | Value |
|---|---|
| Commit at start | `e9d8b59fb416766e4ddd91ecf9acd60bb234c9d0` |
| `git status` at start | clean |
| R2 test count at start | 148 (independently collected via `pytest tests/test_ml_001_r2_*.py --co`) |
| Full repo test count at start | 450 |

---

## 2. M-5 DISPOSITION — RSI/ATR REFERENCE SEMANTICS

### Finding: **BLOCKED_BY_SPEC_AMBIGUITY**

**Step 1 — locate the authoritative specification.** Spec §4 defines `rsi_14`/`atr_14` in prose:

> "avg_gain/avg_loss **seeded as the simple mean of the first 14 gains/losses**, then propagated via Wilder smoothing `avg[t] = (avg[t-1] × 13 + value[t]) / 14` (**equivalent to** `ewm(alpha=1/14, adjust=False)`)"

and separately:

> "Reference implementation: functionally equivalent to `core/indicators.py` lines 62–82 ... reuse that implementation directly"

**Step 2 — search the repository.** `core/indicators.py::rsi`/`atr` implement `series.ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()` — pandas' unseeded exponential recursion (effectively `y[0]=x[0]`, then geometric decay from the very first data point), **not** the classic Wilder method the prose describes (an explicit flat arithmetic-mean seed over the first 14 values, only *then* switching to recursive smoothing). No other RSI/ATR implementation, fixture, or documented expected value exists anywhere in the repository.

**Step 3 — does the spec uniquely determine the implementation?** No. The spec asserts, in its own text, that these two procedures are "equivalent." **This assertion is mathematically false**, verified empirically (not by inspection alone):

```
Synthetic close-price series, n=150 bars (seed=1):
t=14   seeded_avg_gain=0.19732628   ewm_avg_gain=0.13579288   diff=6.153e-02  (31% relative)
t=20   seeded_avg_gain=0.14712402   ewm_avg_gain=0.10767803   diff=3.945e-02
t=50   seeded_avg_gain=0.21228484   ewm_avg_gain=0.20801451   diff=4.270e-03
t=99   seeded_avg_gain=0.15493679   ewm_avg_gain=0.15482370   diff=1.131e-04
t=100  seeded_avg_gain=0.14386988   ewm_avg_gain=0.14376487   diff=1.050e-04  (spec's own declared burn-in bar)
t=149  seeded_avg_gain=0.20212842   ewm_avg_gain=0.20212564   diff=2.781e-06
```

Both are legitimate, well-defined, deterministic procedures. They converge asymptotically (the difference decays geometrically at rate `(13/14)^t`, matching both formulas sharing the same recursive tail) but are **never exactly equal at any finite t**, including at the spec's own explicitly-declared 100-bar burn-in threshold — the divergence there (1.05×10⁻⁴) is six orders of magnitude smaller than at t=14, but not zero, for a spec that elsewhere demands artifact-checksum-level exactness ("verified by artifact checksum, not merely similar metrics") and this audit chain's own repeated "no approximately equivalent" standard.

**Conclusion**: the specification names two different, precisely-defined candidate formulas and incorrectly claims they are the same thing. It does not say which one governs when they diverge. Per the governing instruction's explicit rule ("If the specification does not uniquely define the semantics: STOP PHASE 1... Do NOT invent a formula") and Critical Principle #3 ("Never use an external indicator implementation as the oracle unless the specification explicitly identifies it as authoritative"), **no reference fixture was constructed, and no formula choice was made.** Picking either candidate and writing "independent" hand-calculated fixtures around it would not be independent verification — it would be encoding my own resolution of an ambiguity the spec itself does not resolve, then testing the implementation against my own choice.

**M-5 = BLOCKED_BY_SPEC_AMBIGUITY.** No code was changed for this finding. This is not a refusal to do the work — it is the correct output of doing the work rigorously: the ambiguity is real, quantified, and was not assumed away.

**What would unblock it**: a spec revision that either (a) removes the "seeded as simple mean" language and states unambiguously that `ewm(alpha=1/period, adjust=False)` (ties to `core/indicators.py`'s existing, reused implementation) is authoritative, or (b) removes the "reference implementation" pointer and requires the classic seeded-Wilder algorithm to be implemented fresh (a small, well-defined change, not invented here). Either resolution is then independently testable with hand-calculated fixtures exactly as Phase 7 describes.

---

## 3. M-8 DISPOSITION — FEATURE VERSION ENFORCEMENT

### Finding: **CLOSED**

**Spec basis** (not invented): §12, FEATURE_PARITY — *"Enforced by: a single canonical feature module ... with a shared FE-R2-001 schema hash checked at each entry point."* Model loading is exactly such an entry point. This is an existing, textual spec requirement that was simply unimplemented, not a new invariant introduced now.

**Scope discipline**: the same section says nothing about rejecting a different-but-valid `model_version` or `strategy_version` at load time — only the *feature* schema is named. No check was added for those, avoiding invented compatibility behavior beyond what §12 actually specifies.

**Code changed**: `core/ml_r2/model_r2.py::RFR2Model.load()` — after successfully parsing metadata and verifying the artifact checksum, compares `metadata.feature_version` against the live `FEATURE_VERSION` constant and `metadata.feature_order` against the live `FEATURE_ORDER` constant, raising `ModelIntegrityError` on any mismatch, fail-closed, with no override. Malformed JSON and missing required metadata fields are also now caught explicitly and re-raised as `ModelIntegrityError` rather than leaking a raw `json.JSONDecodeError`/`TypeError`.

**Tests added** (`tests/test_ml_001_r2_model.py::TestFeatureVersionEnforcementAtLoad`, the full A–E matrix):
- **A** — correct `feature_version` → load succeeds.
- **B** — wrong `feature_version` → `ModelIntegrityError`.
- **C** — missing `feature_version` field → `ModelIntegrityError` (via the wrapped dataclass-construction `TypeError`, since it is a required field with no default).
- **D** — malformed JSON → `ModelIntegrityError` (via the wrapped `JSONDecodeError`).
- **E** — `feature_order` mismatch (reordered, same names) → `ModelIntegrityError`.

The pre-existing test that had asserted the *old* (permissive) behavior — `test_feature_version_drift_is_observable_in_saved_metadata` — was renamed and rewritten to assert the new, correct fail-closed behavior (`test_feature_version_drift_is_rejected_at_load_time`), not deleted or weakened.

**Independent verification**: `grep -n "feature_version != FEATURE_VERSION\|feature_order) != list(FEATURE_ORDER)" core/ml_r2/model_r2.py` confirms both comparisons exist in the function body. Confirmed via fresh-process reproducibility run (§9) that a correctly-versioned save/load round trip still succeeds and produces identical predictions.

---

## 4. M-3 DISPOSITION — DATA-STATE TRUST BOUNDARY

### Finding: **NOT_APPLICABLE (documented residual limitation)**

**Traced the full flow**: raw `df` → `generate_oos_predictions(df, windows, ..., training_data_state=X, test_data_state=Y)` → `ProvenanceEnforcer.validate_access(X, TRAINING)` / `validate_access(Y, SELECTION|FINAL_EVALUATION)` → per-window `build_training_set` (features/labels/leakage-check) → `RFR2Model.train()` → `RunProvenance` construction.

**Direct answers to Phase 3's five questions**:
1. *Can a caller falsely label data as TRAINING?* Yes, mechanically — nothing inspects `df`'s actual date range against the declared state.
2. *Can PURE_HOLDOUT data accidentally enter training?* Only if a caller both mislabels the state **and** passes holdout-period rows in `df` — a compound caller error, not something the current code path reaches on its own (every existing call site correctly scopes its own `df`).
3. *Is data state cryptographically/procedurally bound to actual temporal ranges?* No.
4. *Does provenance independently verify the declaration?* No — `RunProvenance.dataset_checksum` proves *which* dataset was used, but not that the dataset's actual content matches the declared `training_data_state`/`test_data_state`.
5. *Does the specification require protection against caller mislabeling?* **No.** Spec §8, requirement 1, states the enforcement mechanism explicitly: *"reuse the existing `core/provenance_enforcement.py` `ProvenanceEnforcer` ... to gate every data access by **declared state**."* This is declaration-based gating by the spec's own design — not a request for structural or cryptographic verification of the declaration against the underlying data. `ProvenanceEnforcer` is described elsewhere in the spec as "proven, working governance code" to be reused as-is, not extended.

**Disposition**: since spec text itself specifies the *declaration-gated* mechanism as sufficient, and does not ask for independent verification of the declaration against actual data content, this is a **theoretical trust issue outside the current threat model**, not an unimplemented requirement. Per the governing instruction ("If this is only a theoretical trust issue outside the current threat model/spec: document it as an explicit residual limitation. Do NOT introduce a new security architecture without a specification requirement"), **no code was changed.** This is recorded here as a residual limitation for any future spec revision to explicitly address, not silently dropped.

---

## 5. M-4 DISPOSITION — DEAD `max_positions_per_symbol`

### Finding: **CLOSED — classified (B) REQUIRED BUT UNWIRED**

**Spec basis**: §10's Trading Rules table lists *"Maximum positions: 1 open position per symbol at a time; no pyramiding/scaling-in for v1.0.0"* in the same normative table, and under the same "any change requires a `strategy_version` bump" rule, as every other constant `BacktestConfig` field (`long_threshold`, `stop_loss_atr_mult`, etc.) — all of which **are** actively read and enforced by `run_backtest`. `max_positions_per_symbol` was the one exception: declared, defaulted to the spec-correct value of `1`, but never read.

This is not (C) obsolete configuration (spec still names the constant) and not (D) deliberately deferred (unlike the portfolio-level risk thresholds in §11, which spec explicitly defers to "Phase 12... not invented here" — §10's per-trade rules carry no such deferral language).

**Code changed**: `core/ml_r2/backtest_r2.py::run_backtest` now validates `config.max_positions_per_symbol == 1` at entry, raising `BacktestConfigError` otherwise. This does **not** change behavior for the default/only-currently-valid configuration (`1`) — every existing passing test is unaffected. It makes a previously-silent misconfiguration (e.g. someone setting `max_positions_per_symbol=2`, wrongly believing this engine would then support two concurrent positions) fail loudly instead of being silently ignored — this is "wiring the field into the risk path," not inventing multi-position trading logic the spec never defines for v1.0.0.

**Tests added**: `tests/test_ml_001_r2_backtest.py::TestMaxPositionsPerSymbolEnforcement` — default value of `1` accepted; `2` and `0` both rejected with `BacktestConfigError`.

**Independent verification**: `grep -n "max_positions_per_symbol" core/ml_r2/backtest_r2.py` confirms the field is now read, compared, and used to raise — not merely declared. Full backtest and reproducibility suites re-run and confirmed unaffected by the change (§9).

---

## 6. L-1 / L-2 / L-3 DISPOSITION

### L-1 — dead code / weak test in `TestNoEntryWhilePositionOpen`: **CLOSED**

Could it hide a real defect? Yes — its old assertion (`len(entries) <= 1` over a 3-bar window where at most one entry was ever mechanically reachable) was close to tautological and would not have caught, e.g., a regression to a list-based position store that opened a second concurrent trade. Removed the dead code (`open_trades_at_any_time = 1` unused variable; `+ ([] if True else [])` no-op) and replaced the single weak test with two:
- A forced-close scenario asserting the exact single trade's `entry_time`/`entry_price`/`exit_reason`, under a continuous 10-bar strong long signal.
- A held-open scenario that **independently recomputes** the expected single-position unrealized P&L bar-by-bar from first principles (not by calling any of the implementation's own helper functions) and compares it exactly against `result.equity_curve` — a genuinely independent oracle that would catch a doubled/compounded-position bug (the equity would be roughly 2× the correct value).

### L-2 — no explicit dtype validation: **CLOSED**

Priority-1 item per Phase 5 ("dtype mismatch" listed first). `_validate_feature_schema` now explicitly checks every feature column is numeric (`pd.api.types.is_numeric_dtype`), raising `ModelSchemaError` naming the offending column(s) — previously this relied on sklearn to fail downstream with a less specific error. Verified it does **not** reject legitimate non-float numeric dtypes (`int64`), only genuinely non-numeric ones (tested via a `str`-cast column).

### L-3 — training-manifest content merged into `metadata.json` rather than split per §16: **OPEN, correctly deprioritized**

Not a dtype mismatch, not a feature-ordering issue, not a test-oracle-independence gap, and not missing edge-case coverage — it doesn't fit any of Phase 5's four stated priorities. It is a file-layout/organizational convention, and spec §16 itself labels the two-file convention "proposed," not mandatory. Fixing it would not improve verification of anything; it was left open, not silently dropped — recorded here explicitly as out of this phase's priorities.

---

## 7. INDEPENDENT NUMERICAL VERIFICATION

Per M-5's disposition, no RSI/ATR reference-fixture verification was performed, since doing so would require resolving an ambiguity the spec itself does not resolve. The numerical divergence evidence in Section 2 above **is** the independent numerical verification for this phase — it independently computed both candidate formulas from first principles (no library call for either), compared them against each other and against `core/indicators.py`'s actual behavior, and quantified the divergence at multiple points including the spec's own declared burn-in threshold. This satisfies Phase 7's spirit (construct independent reference calculations, not implementation-echoing tests) while correctly declining to manufacture a false sense of "verified" for a value that isn't yet uniquely defined.

---

## 8. ADVERSARIAL TESTING (Phase 6 checklist)

| # | Scenario | Status |
|---|---|---|
| 1 | Wrong feature version | **New** — M-8 test B |
| 2 | Wrong model version | Pre-existing (`TestWrongModelVersion`) |
| 3 | Wrong schema | **New** — M-8 test E (`feature_order` mismatch) |
| 4 | Reordered features | Pre-existing (`TestFeatureReordering`) |
| 5 | Altered RSI values | **Not independently testable — M-5 blocked.** Weaker, pre-existing property tests remain in place (`tests/test_indicators.py`: bounded `[0,100]`, high on monotonic-up, low on monotonic-down) — these confirm RSI responds to input changes in the expected direction, but cannot confirm exact values against an undefined oracle |
| 6 | Altered ATR values | Same as #5 (`test_atr_is_positive`) |
| 7 | Insufficient warmup | Pre-existing (`TestFeatureCorrectness`, `TestBoundaryConditions`) |
| 8 | NaN contamination | Pre-existing (`ModelSchemaError` NaN checks) |
| 9 | Temporal overlap | Pre-existing (`TestTemporalSplit`, `WFAWindow` validation) |
| 10 | Caller-declared wrong data state | Pre-existing (`TestHoldoutAndValidationAccessViolations`) |
| 11 | Dataset substitution | Pre-existing (`TestDatasetSubstitution`) |
| 12 | Coordinated artifact substitution | Pre-existing (`test_coordinated_substitution_...`, documents the known M-2 limitation) |
| 13 | Random-seed change | Pre-existing (`TestDifferentRandomSeed`) |
| 14 | Weekday gap | Pre-existing (C-1 remediation, `TestUnexpectedWeekdayGaps`) |
| 15 | Unexpected market-calendar gap | Pre-existing, same suite, boundary conditions |

All required invariants fail closed. #5/#6 are the only scenarios not resolvable to exact-value testing, and that is a direct, disclosed consequence of M-5 remaining blocked — not an oversight.

---

## 9. REPRODUCIBILITY

Two genuinely separate `python3` process invocations of the complete pipeline (features → `build_training_set` → train → save → **load (now exercising the new M-8 checks)** → predict → walk-forward → provenance → backtest), on identical synthetic data:

```
                                    RUN 1                              RUN 2
rsi_14[100:103]:                   [36.7347..., 41.3335..., 38.5559...]   identical
atr_14[100:103]:                   [0.0014431..., 0.0014061..., 0.0014378...]  identical
model.metadata.checksum:           94f3ceca...ccc82c2                  identical
loaded.metadata.checksum:          94f3ceca...ccc82c2                  identical (round-trips through new M-8 checks)
provenance[0].dataset_checksum:    0b463778...e39de215d                identical
provenance[0].feature_schema_hash: d976bbb4...366bce                  identical
backtest trades / final_equity:    190 / 40006.14540339329             identical
first 3 OOS predictions:           [(0,0.3538...),(1,0.6448...),(1,0.5249...)]  identical
```

All values bit-for-bit identical across process boundaries, including RSI/ATR raw values (whatever their currently-implemented formula is — determinism is confirmed independent of, and does not resolve, the M-5 ambiguity) and the newly-added M-8 load-time checks (a correctly-versioned artifact still round-trips cleanly). No economic or PURE_HOLDOUT data was used.

---

## 10. FULL TEST SUITE (exact counts)

```
R2 test suite:         159 tests collected, 159 passed, 0 failed   (start of this phase: 148)
Full repository suite: 461 tests collected, 461 passed, 0 failed   (start of this phase: 450)
```

Net new tests this phase: 11 (`TestFeatureVersionEnforcementAtLoad` ×5, `TestMaxPositionsPerSymbolEnforcement` ×3, `TestFeatureDtypeValidation` ×2, plus L-1's rewritten `TestNoEntryWhilePositionOpen` net +1). Exit code `0` for both suites.

---

## 11. FINDING STATUS TABLE

| Finding | Classification | Evidence |
|---|---|---|
| M-3 | **NOT_APPLICABLE** (documented residual limitation) | Spec §8 specifies declaration-gated enforcement as the mechanism; no independent-verification requirement exists in spec text |
| M-4 | **CLOSED** | `run_backtest` now validates and enforces `max_positions_per_symbol == 1`; 3 new tests |
| M-5 | **BLOCKED_BY_SPEC_AMBIGUITY** | Spec's prose formula and its cited reference implementation are empirically, numerically different (diff quantified at 7 points, including the spec's own burn-in threshold); no formula invented |
| M-8 | **CLOSED** | `load()` now fails closed on `feature_version`/`feature_order` mismatch, malformed JSON, and missing fields; full A–E test matrix |
| L-1 | **CLOSED** | Dead code removed; replaced with a genuinely independent equity-curve oracle |
| L-2 | **CLOSED** | Explicit numeric-dtype validation added, tested against both a rejection and an acceptance case |
| L-3 | **OPEN, deprioritized** | Does not fit any of Phase 5's four stated priorities; spec itself marks the convention "proposed" |

---

## 12. REMAINING LIMITATIONS

- **M-5 remains unresolved** and blocks any claim of exact RSI/ATR numerical correctness until the spec itself is amended to name a single authoritative formula.
- **M-2** (from the prior remediation round) remains open by design — the checksum mechanism still cannot detect a coordinated model+metadata substitution; `RunProvenance` provides the capability for independent recording but nothing yet automatically persists it outside the model-artifact directory.
- **M-3** is a disclosed, spec-consistent design choice (declaration-based provenance gating), not a defect — but it does mean a sufficiently careless caller could mislabel data state without detection. This is now explicitly documented rather than silently present.
- **L-3** remains open — a file-layout convention, not a verification gap.
- Adversarial scenarios #5/#6 (altered RSI/ATR values) cannot be verified to exact values while M-5 is blocked; only weaker directional/boundedness properties are confirmed.

---

## 13. GOVERNANCE STATE

```
ML-001-R2         = RESEARCH_ONLY / NOT_AUTHORIZED   (unchanged)
ECONOMIC_VALIDITY = UNPROVEN                          (unchanged — no economic validation performed)
PRODUCTION        = BLOCKED                           (unchanged)
PINE_CONVERSION   = BLOCKED                           (unchanged)
```

No PURE_HOLDOUT data was accessed. No real/economic market data was used anywhere in this phase. No Pine Script was generated. No production authorization occurred. No strategy economics (hyperparameters, feature formulas, target definition, or trading/risk constants) were changed — every code change in this phase is either a fail-closed validation check or a test-quality improvement.

---

## EXACT COMMIT HASH

This report describes work committed at: **(recorded in the commit that includes this file — see repository history immediately following commit `e9d8b59`)**
