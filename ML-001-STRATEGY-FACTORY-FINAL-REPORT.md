# ML-001 Strategy Factory — Final Status Report

**Date**: August 18, 2026
**Scope**: consolidates the outcome of `STRAT-000001` (ML-001-R2 / RF-R2-001) — the first, and to date only, candidate ever registered in the Strategy Factory — across data acquisition, leakage audit, training, walk-forward evaluation, failure forensics, non-determinism investigation, and governance review. This document does not introduce new evidence; it indexes and summarizes what the artifacts below already establish, distinguishing three separate questions that must not be conflated: whether the **Factory infrastructure works**, whether **ML-001-R2 has a proven edge**, and whether **any candidate is validated for forward/live deployment**.

This report was reconstructed after an interrupted write (a prior turn was cut off by a server error before this file was created). No economic pipeline step, model training run, or walk-forward run was re-executed to produce it — every figure below is read directly from already-committed or already-produced artifacts, cross-checked against the on-disk `reports/factory/strategy_registry.json` and a fresh (test-only, non-economic) `pytest` run.

---

## 1. Three separate statuses — do not conflate

```
FACTORY_ENGINEERING_STATUS   = WORKING
EDGE_STATUS                  = NOT_PROVEN  (actively disconfirmed by real evidence, not merely "untested")
FORWARD_VALIDATION_STATUS    = NOT_STARTED (no candidate has ever reached HOLDOUT_TESTED, EVG_REVIEW, or beyond)
```

- **`FACTORY_ENGINEERING_STATUS = WORKING`**: the candidate lifecycle (`core/factory/*`), the leakage-audited real-data pipeline, the walk-forward engine, the registry's immutable history/search-accounting, and the rejection path all executed correctly, on real data, end to end. This is an infrastructure claim, not an economic one.
- **`EDGE_STATUS = NOT_PROVEN`**: the one hypothesis this Factory has actually tested (`STRAT-000001`) failed its walk-forward evaluation with statistically significant negative expectancy on both symbols. A working Factory that correctly rejects a bad candidate is Factory success, not strategy success — these must be reported separately, and this report does not describe `STRAT-000001` as, or on a path toward, a proven edge.
- **`FORWARD_VALIDATION_STATUS = NOT_STARTED`**: `PURE_HOLDOUT` was never opened for `STRAT-000001` (by design — see §4), and no candidate has reached `EVG_REVIEW`, `RESEARCH_CANDIDATE`, `PAPER_VALIDATION`, or `LIVE_CANDIDATE`. There is nothing currently in, or approaching, any forward-facing validation stage.

---

## 2. STRAT-000001 — final disposition

Per `reports/factory/strategy_registry.json` (verified directly, not summarized from memory):

```
candidate_id: STRAT-000001
state:        REJECTED
history:      GENERATED → DATA_VALIDATED → TRAINED → REJECTED
              (HOLDOUT_TESTED never appears in the history — holdout was never opened)
```

This is the terminal, immutable record — per `core/factory/registry.py`, a `REJECTED` candidate's spec and history cannot be further mutated, and no transition out of `REJECTED` is legal (`core/factory/state_machine.py`; verified as a hard invariant by `tests/test_factory_holdout_governance.py::TestRejectedCandidateImmutability`, added this task).

---

## 3. Data and training — real, provenance-verified, not synthetic

| Item | Value |
|---|---|
| `REAL_MARKET_DATA` | TRUE |
| `DATA_PROVENANCE` | VERIFIED — independently confirmed via the 2016 Brexit GBPUSD flash-crash event (an externally falsifiable historical fact, not merely a source's own claim), documented at acquisition time |
| `DATA_INTEGRITY` | PASS — `ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md`: monotonic timestamps, 0 duplicates, 0 future-injection mismatches (5 features × 28,800 rows), clean chronological 60/20/20 split with zero cross-partition overlap |
| Symbols / timeframe | EURUSD, GBPUSD, H1 |
| Model | RF-R2-001 (frozen spec hyperparameters, `random_state=42`, never tuned) |
| Training rows (EURUSD) | 33,959 (DEVELOPMENT partition only), class balance {0: 17,041, 1: 16,918} |
| Model reproducibility | Independently re-verified: 3 fresh-process EURUSD retrains, 2 GBPUSD retrains, matched saved checksums byte-for-byte (under the "clean process" condition — see §6 for the documented exception) |

---

## 4. Walk-forward evaluation — the economic result

Per `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md` and the underlying `reports/ml_r2_real_data/WALKFORWARD_{EURUSD,GBPUSD}.json` (1,387 + 1,452 real trade records):

| | EURUSD | GBPUSD |
|---|---|---|
| Trades | 1,387 | 1,452 |
| Profit factor | 0.879 | 0.892 |
| Expectancy/trade | −$14.41 | −$12.80 |
| Net P&L | −$19,980.55 | −$18,589.15 |
| Net-negative windows | 36/65 (55.4%) | 44/65 (67.7%) |

**Protocol**: 65 windows per symbol, 24-month trailing training, 1-month test, monthly step, spanning ~5.5 years, entirely within `DEVELOPMENT ∪ VALIDATION`. `PURE_HOLDOUT` was **structurally excluded** — never present in the DataFrame object passed to the walk-forward engine, not merely access-guarded — and was never opened for this candidate (§2). One frozen hyperparameter configuration was used throughout; 130 individual training events (65 windows × 2 symbols) were each recorded with their own model checksum, dataset checksum, and training period in the WFA JSON artifacts — no hyperparameter search, no retry-toward-a-better-result.

**Statistical significance** (computed this task, from the same trade records, not previously reported at this level of formality): one-sample t-test on trade-level P&L — EURUSD t=−2.291, p=0.0221; GBPUSD t=−2.067, p=0.0389; bootstrap 95% CI EURUSD (−$25.86, −$1.59), GBPUSD (−$24.96, −$0.94) — both exclude zero on the unfavorable side. This rules out "too little data to conclude anything" as an explanation; the sample is large enough to support a confident negative conclusion.

---

## 5. Why it failed — forensic summary

Full detail: `ML-001-STRAT-000001-FAILURE-FORENSIC-REPORT.md`. Headline finding, evidence-backed:

- **Primary classification: `NO_PREDICTIVE_SIGNAL`** — Information Coefficient 0.015–0.030 (both symbols, both Pearson/Spearman variants), directional accuracy 51.2–51.8% (barely above coin-flip), 95%+ of predictions cluster in an indecisive [0.45, 0.55] zone, calibration-by-decile forward returns are non-monotonic (5/9 transitions correct — chance level) and tiny in magnitude (~1–5×10⁻⁵), identical pattern on both symbols, no time trend across the 65 WFA folds (correlation with window index ≈ 0 for both).
- **Secondary, contributing: `COST_SENSITIVITY`** — a canonical-model zero-cost probe (smaller sample, 229/287 trades, disclosed as non-identical in scope to the full WFA) shows only marginal breakeven (PF 1.006–1.016) even with costs fully removed — costs matter, but do not by themselves explain the failure, since there is no clean pre-cost edge to erode.
- **Explicitly ruled out with evidence**: `MODEL_MISFIT` (calibration is honest), `TARGET_PROBLEM` (leakage-audited clean, healthy class balance), `FEATURE_PROBLEM` in the "unstable feature use" sense (feature importances are stable across sampled WFA folds — `rsi_14`/`momentum_5`/`momentum_20` dominate consistently, `volatility_regime` consistently near-zero), `EXECUTION_PROBLEM` (backtest mechanics independently verified via prior Pine Script parity work, reused unmodified), `REGIME_INSTABILITY` (no time trend), `STATISTICAL_INSUFFICIENCY` (large-sample, statistically significant negative result), `INSUFFICIENT_EVIDENCE`/`UNKNOWN` (not applicable — evidence is sufficient for a specific classification).

---

## 6. Non-determinism artifact — characterized, isolated, not silently omitted

A real, reproducible artifact was found during training: an unrelated `joblib.load()` of a `RandomForestClassifier` earlier in the same Python process measurably changes the `checksum` (raw serialized-byte hash) of a subsequently-trained, otherwise-identical `RFR2Model`. Full investigation: `ML-001-NONDETERMINISM-AUDIT.md`. Key facts, none of which are omitted or softened:

- **Model behavior is unaffected** — `predict_proba()`, `feature_importances_`, and individual tree structure are bit-identical regardless of this artifact, verified repeatedly.
- **Only the serialized byte representation varies** — root mechanism traced to serialization/deserialization byte layout; not fully decomposed to one single named cause (candidate contributor: process-global numeric/threading state — not conclusively proven, reported honestly as inconclusive rather than asserted).
- **The actual WFA run that produced §4's results never triggers this artifact** — `generate_oos_predictions()` trains a fresh model per window without any interleaved `.load()` calls — and even if it had, §4's economic results would be unaffected since predictions are proven unaffected.
- **Fix implemented**: `structural_fingerprint`, an additive, backward-compatible, content-based hash on `ModelMetadata`, immune to this artifact, with 5 dedicated regression tests (`tests/test_ml_r2_nondeterminism.py`, all passing). The original `checksum` field is preserved unchanged for its original purpose (on-disk corruption detection).

```
NONDETERMINISM_STATUS = ISOLATED
```

---

## 7. Holdout / WFA state-machine governance — unresolved, honestly flagged

`core/factory/state_machine.py`'s declared forward spine places `HOLDOUT_TESTED` *before* `OOS_TESTED`/`WFA_TESTED`, in apparent tension with this project's own repeatedly-established discipline that `PURE_HOLDOUT` is opened exactly once, only after every other gate has passed. Full analysis: `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md`, presenting three options (A: holdout last; B: holdout first, the current/status-quo ordering; C: holdout last plus explicit renaming/documentation to remove the ambiguity) scored across leakage risk, selection risk, early-rejection ability, WFA compatibility, immutable-version compatibility, multiple-testing compatibility, EVG consequences, and registry consequences.

**No document in this repository was found that grants authority to resolve this unilaterally** — the "roadmap Sections 6/16/19/20" cited in `core/factory/*` docstrings do not exist as a committed file anywhere in this repository. Accordingly:

```
SPECIFICATION_DECISION_REQUIRED = TRUE
state_machine.py MODIFIED = FALSE
```

This did **not** block `STRAT-000001`'s rejection: the always-legal `TRAINED → REJECTED` transition was used specifically so no `HOLDOUT_TESTED` claim (true or fabricated) would ever need to be made, and that path remains legal under all three options in the governance document.

---

## 8. Multiple-testing / search-history accounting — verified honest, not inflated

Directly from `reports/factory/strategy_registry.json`'s `search_history` block (re-read this task, not assumed):

```
total_strategies_generated = 1
total_strategies_tested    = 1
total_strategies_rejected  = 1
total_strategies_failed    = 0
total_strategies_surviving = 0
total_strategies_passed    = 0
selection_bias_status      = "UNACCOUNTED"   (never set to PASS — correctly not claimed,
                                               since with exactly one candidate ever tested
                                               there is no selection among alternatives to
                                               correct for; PASS would misrepresent a formal
                                               multiple-testing correction that was never done)
```

`tests/test_factory_holdout_governance.py::TestMultipleTestingAccountingIsHonest` (added this task) asserts these exact values directly against the production registry file, and asserts `selection_bias_status != "PASS"`, so this claim is now a regression-tested invariant, not just a one-time observation.

---

## 9. Tests

```
python3 -m pytest --collect-only -q   →   615 tests collected
python3 -m pytest -q                  →   exit code 0, zero failures, zero errors
```

615 = the pre-existing 591 (baseline, unaffected by this task — no canonical economic logic was modified) + 5 new non-determinism regression tests (`tests/test_ml_r2_nondeterminism.py`) + 19 new governance/immutability tests (`tests/test_factory_holdout_governance.py`, covering rejected-candidate immutability, illegal-transition rejection, frozen-spec-requires-new-version, final-holdout one-time-access semantics, and the multiple-testing counters above). No existing test was weakened, skipped, or deleted to reach this count.

**Software test evidence only** — as previously disclosed, none of these 615 tests execute against real EURUSD/GBPUSD data or compute an economic metric; §4's walk-forward/training results come from the JSON artifacts cited throughout, produced by direct script execution outside the test suite.

---

## 10. Final status block

```
STRAT-000001               = REJECTED
EDGE_STATUS                 = NOT_PROVEN
FACTORY_ENGINEERING_STATUS  = WORKING
FORWARD_VALIDATION_STATUS   = NOT_STARTED
PRODUCTION_STATUS           = BLOCKED
HOLDOUT_POLICY               = SPECIFICATION_DECISION_REQUIRED (see §7;
                                interim operating rule: treat HOLDOUT_TESTED as the
                                last gate before EVG_REVIEW in practice, regardless of
                                the state machine's current declared order)
NONDETERMINISM_STATUS       = ISOLATED (see §6; behaviorally proven safe, fix implemented)
TOTAL_STRATEGIES_TESTED     = 1
TOTAL_STRATEGIES_REJECTED   = 1
TOTAL_STRATEGIES_PASSED     = 0
TESTS_PASSING                = 615 / 615
KNOWN_BLOCKERS:
  - No proven edge exists for ML-001-R2 on real EURUSD/GBPUSD H1 data (§4-5).
  - Holdout/WFA state-machine ordering is unresolved pending a specification decision (§7).
  - The "roadmap Sections 6/16/19/20" cited in core/factory/* docstrings do not exist as a
    committed document in this repository — a broader documentation gap beyond just §7's
    specific question.
DECISIONS_REQUIRED:
  - Resolve the HOLDOUT_TESTED/WFA_TESTED ordering (Option A, B, or C, or a variant) —
    by whoever holds authority over the Strategy Factory roadmap; not resolved here.
  - Decide whether to attempt a new strategy hypothesis (STRAT-000002) with a materially
    different feature set/model class, or conclude 1-bar H1 direction is not viable for
    this instrument pair with tree-based models on these five features. NOT decided,
    NOT started, and explicitly out of scope for this task's stop condition.
```

---

## 11. What this report does not do

- Does not create or begin `STRAT-000002`, or any new-strategy generation work.
- Does not modify `core/factory/state_machine.py`, `core/ml_r2/*` economic logic, cost model, target definition, or hyperparameters.
- Does not access `PURE_HOLDOUT`.
- Does not upgrade `EDGE_STATUS`, `PRODUCTION_STATUS`, or `FORWARD_VALIDATION_STATUS` beyond what §1–§8's evidence supports.
- Does not re-run the Strategy Factory, retrain any model, or re-run walk-forward evaluation — every figure above is read from already-produced artifacts.
