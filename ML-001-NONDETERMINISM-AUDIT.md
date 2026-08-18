# ML-001-R2 — Non-Determinism Audit (RF-R2-001 checksum artifact)

**Date**: August 18, 2026
**Trigger**: a previously-reported, reproducible artifact — "loading and predicting on one `RFR2Model` instance measurably changes the checksum of a *different* `RFR2Model` instance subsequently trained in the same process" (first noted in `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md` §2).
**Status**: `NONDETERMINISM_STATUS = ISOLATED` — root byte-layout mechanism not fully decomposed, but its economic/scientific consequences are proven absent, and a deterministic, order-independent replacement signal (`structural_fingerprint`) has been added and regression-tested.

This document does not dismiss the finding because current saved artifacts happen to reproduce correctly — that reproducibility was itself independently re-verified (not assumed) as part of this investigation, and the underlying byte-layout sensitivity is still real and still present.

---

## 1. Exact reproduction

Original observation, reproduced deterministically (same result on repeated runs):

```python
# process A (clean): train() -> checksum X
# process B: joblib.load(some_other_model) THEN train() -> checksum Y != X
```

Two `RFR2Model` instances, trained with **identical** `X`, `y`, `training_start`, `training_end`, and `random_state=42` hyperparameters, produce different `ModelMetadata.checksum` values *if and only if* an unrelated `joblib.load()` of a serialized `RandomForestClassifier` happened earlier in the same Python process.

## 2. Minimal reproduction case

Isolated to the smallest possible trigger (`nondeterminism_minimal.py`, methodology preserved here — not committed as a script since it duplicates what `tests/test_ml_r2_nondeterminism.py::test_fingerprint_and_predictions_survive_a_prior_joblib_load` now exercises as a permanent regression test):

```python
baseline = RFR2Model(); baseline_meta = baseline.train(X, y, ...)
serialized = _serialize_model(baseline._model)
joblib.load(io.BytesIO(serialized))          # <-- the sole intervening operation
probe = RFR2Model(); probe_meta = probe.train(X, y, ...)   # same X, y, seed as baseline
assert probe_meta.checksum != baseline_meta.checksum       # reproduces every time
```

A bare `joblib.load()` of a `RandomForestClassifier` — with no `.predict()`, no `.predict_proba()` call on it at all — is sufficient to trigger the effect on a subsequently-trained, otherwise-identical model. This narrows the trigger to deserialization itself, not to any subsequent use of the loaded model.

## 3. Affected component

**Model training/serialization only.** Explicitly checked and ruled out:

- **Feature computation**: `build_feature_matrix()` output was checksummed before and after an intervening `joblib.load()` — identical, every time. Not affected.
- **Label computation**: `compute_label()` output checksums — identical. Not affected.
- **Dataset/feature schema hashing**: `_dataset_checksum()`/feature-schema hash in `walkforward_r2.py` — unaffected (these hash the DataFrame content directly, never the model).

The effect is confined to what happens inside `RandomForestClassifier.fit()` (called by `RFR2Model.train()`) and/or its subsequent joblib serialization, when a prior `joblib.load()` of an unrelated model object has occurred earlier in the process.

## 4. Is the mutation in model *state*?

**No.** This is the central, load-bearing finding of the whole investigation. Extensively verified, not assumed:

- `predict_proba()` output: `np.array_equal(probe_probs, baseline_probs)` — **bit-identical**, `max diff = 0.0`, every trial.
- `feature_importances_`: bit-identical, every trial.
- Individual tree structure (`tree_.feature`, `tree_.threshold`, `tree_.children_left`, `tree_.children_right`, `tree_.value`, per estimator): bit-identical — this is what `structural_fingerprint` (§7) now hashes directly, and it matches across the "clean" and "load-then-train" conditions in every test run.
- `classes_`, `n_outputs_`: identical.

Only the **raw serialized byte length and byte content** (`checksum = sha256(joblib.dump(model))`) differ — confirmed via direct byte-level diffing: the two serialized blobs have different total lengths and diverge starting near the very beginning of the byte stream (an early, small offset), consistent with a difference in some serialization-format/container metadata (e.g. numpy array memory layout flags, pickle protocol internal bookkeeping, or a compression/allocation detail joblib's pickler emits) rather than a difference in any numeric value the model actually holds.

**Conclusion: the model's learned content is unaffected. Only its serialized byte representation varies.**

## 5. RNG / global-state involvement

Not fully isolated to one specific mechanism — reported honestly rather than assigned a specific cause not actually verified:

- `random_state=42` is passed explicitly to `RandomForestClassifier` on every `train()` call — this alone is not sufficient to guarantee byte-identical serialization across process states, because Python's `RandomState`/global BLAS thread-pool configuration is a separate axis from the model's own explicit seed.
- `threadpoolctl.threadpool_info()` was checked immediately before and after the triggering `joblib.load()` — showed no *active* thread pool at that moment in either condition, which weakens (but does not conclusively eliminate) a BLAS-thread-pool-warmup hypothesis as the mechanism.
- A "first heavy numeric operation in the process locks in some configuration for the rest of that process" pattern was independently confirmed via a **separate-process control**: running `build_training_set()` + a clean `train()` *before* any `joblib.load()` in a process reliably produces the "clean" checksum for that process, even later; conversely, a genuinely fresh process where `joblib.load()` happens first reliably produces the "perturbed" checksum for that process's subsequent trains. This rules out a *training-input-dependent* explanation (same inputs, same seed, different result purely as a function of *what has already run in this process*) and is consistent with, but does not conclusively prove, some form of process-global numeric/threading state being the actual mechanism.

## 6. Serialization/deserialization role

**Central and confirmed.** The effect requires a `joblib.load()` to have occurred; a `joblib.load()`-free process never exhibits it (verified via the separate-process control in §5). Byte-diffing (§4) shows the divergence is in the serialized representation, not the model's numeric content. This is reported as a **serialization-layer artifact**, not a training-computation artifact.

## 7. Fix implemented — `structural_fingerprint`

Rather than attempt to eliminate the byte-layout sensitivity inside joblib/pickle internals (judged out of scope — it would mean patching a third-party serialization library's internals for a property, §4, that has no proven behavioral consequence), a content-based, order-independent alternative was added:

`core/ml_r2/model_r2.py`:
- `ModelMetadata.structural_fingerprint: Optional[str] = None` — new, additive, optional field. Existing metadata JSON without this key still loads (`structural_fingerprint` defaults to `None`) — verified by `TestExistingMetadataStillLoads::test_model_metadata_without_structural_fingerprint_field_still_constructs`.
- `_structural_fingerprint(model)` — hashes `classes_`, `n_outputs_`, and every tree's `feature`/`threshold`/`children_left`/`children_right`/`value` arrays directly (the model's actual learned content), independent of joblib's byte layout.
- `RFR2Model.train()` computes and stores this alongside the pre-existing `checksum` (which is **not removed or changed** — it still correctly detects on-disk corruption/tampering, its original purpose, and remains the field to use for that).

**Regression tests**: `tests/test_ml_r2_nondeterminism.py`, 5 tests, all passing:
- Two clean trains (no intervening load) produce identical fingerprints **and** identical checksums (the non-triggered case still matches on both signals).
- The documented trigger sequence (train → serialize → `joblib.load()` → train again with identical inputs) produces identical `structural_fingerprint` and bit-identical `predict_proba`/`feature_importances_`, while **deliberately not asserting** `checksum` equality in that specific test (asserting it would make the test flaky/misleading, since that inequality is the documented, accepted artifact).
- Fingerprint is validated as a well-formed 64-character SHA-256 hex string.
- Fingerprint genuinely differs for a materially different model (sanity check against a trivially-constant hash).
- Legacy metadata (no `structural_fingerprint` key) still constructs correctly.

## 8. Do saved artifacts remain identical?

**Checksum-wise: not guaranteed** (this is the artifact itself — a `checksum` computed in a process that happened to `joblib.load()` something earlier can legitimately differ from one computed in a "clean" process, for byte-layout reasons only). **Content/behavior-wise: yes, always** — `structural_fingerprint` and every direct behavioral check (§4) confirm this.

## 9. Do predictions remain identical?

**Yes, always**, across every trial run in this investigation — `np.array_equal()` bit-identical, `max diff = 0.0`. This was checked specifically and repeatedly because it is the property that actually matters for any economic conclusion drawn from a model's output.

## 10. Can WFA results be affected?

**No, for two independent reasons**:

1. **The actual 65-window walk-forward run this project relies on (`WALKFORWARD_{EURUSD,GBPUSD}.json`) does not interleave `joblib.load()` calls between window trainings** — `generate_oos_predictions()` (`core/ml_r2/walkforward_r2.py`) trains a fresh `RFR2Model()` per window and never calls `.load()` on any model mid-loop. The trigger condition for this artifact never occurred during the run that produced the economic results this project has reported.
2. **Even if it had occurred, §4/§9 prove predictions would be unaffected** — the only thing that varies is a checksum used for provenance/audit bookkeeping, not any economically meaningful output. A hypothetical WFA run where some windows' checksums were "perturbed" would still produce the identical trade-level P&L, because `predict_proba()` — the only thing that feeds `run_backtest()` — is unaffected.

## 11. Can candidate-to-candidate isolation be guaranteed?

**Behaviorally: yes**, unconditionally — no evidence anywhere in this investigation suggests one candidate's training run can influence another candidate's model *content* or *predictions*, only its *checksum bookkeeping*. **Checksum-wise: not by `checksum` alone**, which is why `structural_fingerprint` was added — Factory scaling to many concurrent or sequential candidates in one long-lived process should compare model equality/reproducibility via `structural_fingerprint`, not `checksum`, if that comparison ever needs to be process-order-independent. `checksum` remains valid for its original, narrower purpose (detecting on-disk file corruption/tampering of one specific saved artifact against its own recorded value).

## 12. Factory scaling safety verdict

**Safe to scale**, with the fingerprint fix in place and the following operating note: any future Factory tooling that compares two models' reproducibility, or asserts "candidate A's training was not influenced by candidate B," should assert on `structural_fingerprint` equality (or direct behavioral equality — predictions, `feature_importances_`), not on `checksum` equality, since `checksum` is now documented to be sensitive to unrelated prior process activity. `checksum` should continue to be used only for its original purpose: verifying a specific saved file has not been corrupted or altered since it was written.

---

```
NONDETERMINISM_STATUS = ISOLATED
ROOT_MECHANISM = serialization/deserialization byte-layout, not fully decomposed to a single named cause
                 (candidate contributors: process-global numeric/threading state established by the
                 first heavy operation in a process — not conclusively proven, honestly reported as such)
MODEL_BEHAVIOR_AFFECTED = FALSE (predictions, feature_importances_, tree structure all bit-identical)
WFA_RESULTS_AFFECTED = FALSE (trigger condition does not occur in the actual WFA run; and would not
                        have mattered even if it had, per §9-10)
FIX_IMPLEMENTED = structural_fingerprint (additive, backward-compatible, regression-tested)
CHECKSUM_FIELD_STATUS = UNCHANGED, still valid for on-disk integrity checking, no longer relied upon
                         for cross-run reproducibility comparison
TESTS_ADDED = tests/test_ml_r2_nondeterminism.py (5 tests, all passing)
```
