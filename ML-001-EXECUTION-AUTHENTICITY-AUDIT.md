# ML-001 EXECUTION AUTHENTICITY AUDIT

**Date**: August 17, 2026
**Analysis Type**: READ-ONLY Forensic Trace (Evidence-Based, No Assumptions)
**Scope**: Determine whether the approved ML-001 strategy actually executes Random Forest inference
**Method**: Static code trace + live read-only Python introspection + git history trace

---

## 1. EXECUTIVE VERDICT

**Is the approved ML-001 strategy actually executing Random Forest inference in production/staging?**

### ANSWER: **NO — PROVEN, NOT INFERRED**

Live introspection confirms `ML001Adapter` has no `generate_signal` method and raises `AttributeError` when called the way `ml_001_production_rollout.py` calls it. The only code that actually runs and produces trading signals (`run_ml_001_account_a.py`) uses `random.choice()`. The reported performance metrics (Sharpe 1.19/1.13, PF 1.54/1.53) exist only as **committed JSON output files with no corresponding generator script anywhere in git history** — the code that produced them was never committed and cannot be re-run or audited.

**STRATEGY IDENTITY: UNPROVEN.** The thing that was "validated" and "authorized" cannot be shown to be RF-v1.0, or any specific, inspectable algorithm at all.

---

## 2. ACTUAL RUNTIME ENTRY POINT

Two candidate entry points exist. Neither executes Random Forest inference.

### Entry Point A: `ml_001_production_rollout.py` — **CRASHES**

```
main() → ProductionRunner.initialize() → ProductionRunner.run()
  → self.strategies[symbol].generate_signal(price)   [line 297]
  → AttributeError: 'ML001Adapter' object has no attribute 'generate_signal'
```

This path is caught by a bare `except Exception as e: logger.error(...)` at line 306-307, so the process does not crash outright — it silently logs an error every tick and **never generates a signal, ever**. No trade is ever placed via this path. This is not a partial/degraded execution of ML-001; it is complete non-execution disguised as a running process.

### Entry Point B: `run_ml_001_account_a.py` — **RUNS, BUT IS NOT ML-001**

```
main() → ML001ProductionAccountA.run()
  → for symbol in self.symbols:
        if random.random() < 0.15:
            signal = random.choice([-1, 1])
```

This is the only code path in the repository that actually produces trading signals under an "ML-001" name. It contains no reference to `ML001Adapter`, no feature computation, no model of any kind.

**CONCLUSION**: There is no executable path from any entrypoint to an actual Random Forest prediction. `RUNTIME_GENERATE_SIGNAL = MISSING`.

---

## 3. generate_signal RESOLUTION — FULL REPOSITORY TRACE

Repository-wide search for `generate_signal` (singular):

| File | Line | Context |
|---|---|---|
| `ml_001_production_rollout.py` | 297 | **CALLER** — `self.strategies[symbol].generate_signal(price)` |

That is the only occurrence of `generate_signal` (singular) anywhere in the repository. There is no `def generate_signal`, no `generate_signal =`, no decorator, no dynamic assignment.

Repository-wide search for `generate_signals` (plural, the real `Strategy` base-class method) found it defined once in `core/strategy.py:240`, and used by `EnsembleStrategy`, `backtest.py`, and test files — but `ML001Adapter` does not use this name, and does not inherit from `Strategy` in the first place (see §4), so this is an unrelated method on an unrelated class hierarchy. The naming similarity (`generate_signal` vs `generate_signals`) is not evidence of a typo-fix path; no code anywhere bridges the two.

Search for dynamic-attachment mechanisms:

| Pattern | Result |
|---|---|
| `setattr(` | 3 occurrences (`utils/logger.py`, `core/backtest.py`, `services/strategy_service.py`) — none reference `ML001Adapter` or `generate_signal` |
| `__getattr__` / `__getattribute__` | 0 occurrences |
| `monkeypatch` | 0 occurrences (outside of pytest's built-in fixture name, unused for this class) |

**CONCLUSION**: `generate_signal` is not defined, not inherited, not injected, and not monkey-patched anywhere in this repository. The call at `ml_001_production_rollout.py:297` targets a method that does not exist under any code path.

---

## 4. ML001Adapter RUNTIME ANALYSIS (LIVE INTROSPECTION)

Executed read-only, in-process, no files modified:

```python
from core.ml_001_adapter import ML001Adapter
strategy = ML001Adapter()

type(strategy)                          # <class 'core.ml_001_adapter.ML001Adapter'>
type(strategy).__mro__                  # (ML001Adapter, object)
type(strategy).__bases__                # (object,)
hasattr(strategy, 'generate_signal')    # False
getattr(strategy, 'generate_signal', None)  # None

dir(strategy) [public]:
  audit_certificate, contract, create_prediction_artifact,
  current_trial_id, feature_version, get_all_prediction_artifacts,
  hypothesis_id, initialize_prediction_registry, model_version,
  prediction_registry, set_audit_certificate, set_trial_context, summary

strategy.generate_signal(1.0850)
  → AttributeError: 'ML001Adapter' object has no attribute 'generate_signal'
```

**Findings**:
- `ML001Adapter` does **not** inherit from `Strategy` (`core/strategy.py:147`). Its MRO is `(ML001Adapter, object)` — a plain, standalone class. It has no `metaclass`, no mixins, no decorators.
- Confirmed source: `RUNTIME_GENERATE_SIGNAL = MISSING`. Calling it as production code does raises `AttributeError`, exactly as predicted from static analysis — **now proven, not inferred**.

**What `ML001Adapter` actually does** (full method inventory, from source + introspection):

| Method | Behavior |
|---|---|
| `__init__` | Stores `hypothesis_id`, `model_version="RF-v1.0"` (a string label only), `feature_version`, builds a frozen `ML001HypothesisContract` (metadata: asset, feature *names*, target, timing). No model object, no weights, no sklearn import. |
| `set_audit_certificate` | Stores an `AuditCertificate` object; raises if `is_passed` is False. |
| `initialize_prediction_registry` | Creates an empty `PredictionArtifactRegistry`. |
| `set_trial_context` | Stores a trial ID string. |
| `create_prediction_artifact` | Constructs a `PredictionArtifact` dataclass from **caller-supplied** `prediction` and `probability` values — it does not compute them. This method is a data-recording/immutability wrapper, not an inference function. |
| `get_all_prediction_artifacts` | Returns list from registry. |
| `summary` | Returns a dict of the above metadata. |

**CONCLUSION**: `ML001Adapter` never loads a model, never computes a feature, never calls `.predict()`, and never produces a signal from market data. It is a **metadata/audit-bookkeeping shell** around predictions that must be computed and handed to it by something else — and no such "something else" exists in the executable codebase.

**`ML001Adapter = NON_EXECUTING_ADAPTER`** — supported by full evidence above.

---

## 5. run_ml_001_account_a.py ANALYSIS

Full inspection of the signal-generation block (lines 111–134):

```python
if random.random() < 0.15:              # 15% chance per tick
    signal = random.choice([-1, 1])       # pure random direction
...
pnl_change = random.uniform(-0.3, 0.3) * self.allocations[symbol]   # random P&L too
```

- No `ML001Adapter` import.
- No feature calculation (momentum, RSI, ATR, volatility_regime).
- No model reference of any kind.
- No broker API call — `positions`/`pnl` are plain in-memory dict mutations; there is no order-placement or fill-confirmation code, simulated or real.
- Prices are not even fetched — they are never read in this signal path at all; P&L is generated by `random.uniform`, independent of any price series.

**Classification of the `random.choice()` usage**: This is **not** (A) production ML-001 execution — it never touches `ML001Adapter` or any model. It is not (C) a test fixture (it lives in a `run_*.py` entrypoint script, not `tests/`) and not (E) dead code (it is the only code that actually runs when this script is invoked). It best fits **(B) demo/simulation-only execution presented under the ML-001 account label**, functioning in practice as **(D) a fallback implementation** that silently stands in for the missing real strategy — but critically, nothing in the file's own text discloses that it is a substitute; the log banner reads "🚀 ML-001 PRODUCTION (Account A)" with no disclaimer that signals are random.

**PROVEN**: This file executes, but what it executes has zero relationship to Random Forest, momentum/RSI/ATR/volatility features, or any of the ML-001 hypothesis contract.

---

## 6. ml_001_production_rollout.py ANALYSIS

Classification against the required options:

- (A) Executes the real Random Forest model — **NO**, no model object exists anywhere in its call graph.
- (B) Executes a simulator — **NO**, it does not fall back to random generation; it does not fall back to anything.
- (C) Calls an adapter that does not actually implement ML inference — **YES**. `ML001Adapter.generate_signal` is called and does not exist.
- (D) Uses a fallback — **NO** fallback exists; the exception is caught and logged, then the loop continues with no signal.
- (E) Cannot execute successfully — **YES**, in the specific sense that its core purpose (signal generation) fails on every single tick, for the entire runtime of the process, while the surrounding orchestration (health monitor, logging, shutdown report) continues to run and produce output that looks like a functioning system.

**This is the most consequential finding of this audit**: `ml_001_production_rollout.py` is not merely "buggy" — it is a fully-scaffolded production system (health monitoring, risk governance wiring, decision registry, trial ledger, shutdown reporting) built around a single missing method call. It will run indefinitely, log `Error processing EURUSD: 'ML001Adapter' object has no attribute 'generate_signal'` on every tick, execute zero trades, and — because `self.pnl` is never updated (no trade ever executes) — will report a shutdown summary of `$0.00 P&L, 0 positions, 0 trades` while never triggering any error severe enough to halt the process.

---

## 7. RANDOM FOREST EXECUTION TRACE

Repository-wide search for `.predict(`, `.predict_proba(`, `RandomForestClassifier`, `joblib.load`, `pickle.load`:

| File | Line | Finding |
|---|---|---|
| `core/oos_wfa_engine.py` | 221–222 | `model.predict_proba(test_features)` / `model.predict(test_features)` — **real calls**, but `model` is constructed via `model = model_class()` where `model_class` is a **parameter passed in by the caller** (dependency injection, `WFAPredictionEngine.generate_predictions(..., model_class, feature_extractor, ...)`). No concrete `RandomForestClassifier` (or any other model class) is defined or imported anywhere in this file. |
| `tests/test_ml_pipeline.py` | 339 | A test *asserting the absence* of `model.predict()` in the strategy layer — i.e., test metadata about a design intent, not a live call. |
| `ML-PIPELINE-IMPLEMENTATION-REPORT.md` | 121, 269, 279 | Documentation/report text only. |

**Critical structural point**: `core/oos_wfa_engine.py` is generic walk-forward infrastructure — it can run *any* model class supplied by a caller. It is reachable only from:
- `tests/test_ml_pipeline.py` (unit tests of the engine's mechanics using test doubles, not RF)
- `tests/test_staging_production.py` (imports `WFAPredictionEngine` only to assert `engine.hypothesis_id == "staging-test"` — never calls `generate_predictions`, never supplies a model)

**No file in the repository ever calls `WFAPredictionEngine.generate_predictions()` with a concrete Random Forest model, real feature data, or in a context connected to `ml_001_production_rollout.py`, `run_ml_001_account_a.py`, or the staging report generation.**

`RF_ARTIFACT_STATUS = MISSING`. `MODEL_INFERENCE_STATUS = INFRASTRUCTURE_EXISTS_BUT_NEVER_INVOKED_WITH_A_REAL_MODEL`.

---

## 8. MODEL ARTIFACT TRACE

```
find /home/user/Ai -type f \( -name "*.joblib" -o -name "*.pkl" -o -name "*.pickle" -o -name "*.onnx" -o -name "*.model" \)
→ (no output — zero files found)
```

Classification: **MODEL_MISSING** (not `MODEL_REFERENCE_ONLY` — there isn't even a placeholder file; the string `"RF-v1.0"` in `ML001Adapter.__init__` is a version-label default argument, not a reference to a stored artifact path).

---

## 9. FEATURE PIPELINE TRACE

| Feature | Status | Evidence |
|---|---|---|
| `momentum_5`, `momentum_20` | Implemented | `core/indicators.py:178-180` — `series - series.shift(period)` |
| `rsi_14` | Implemented | `core/indicators.py:62-82` — Wilder's smoothing |
| `atr_14` | Implemented | `core/indicators.py:111-123` |
| `volatility_regime` | **NOT IMPLEMENTED** | Appears only in `ML001HypothesisContract.features` as a string literal and in documentation/report prose. No function, formula, threshold, or classification logic exists anywhere in the codebase. |

None of these four implemented indicator functions are called from `ML001Adapter`, `ml_001_production_rollout.py`, or `run_ml_001_account_a.py`. They exist in `core/indicators.py` as general-purpose utilities used elsewhere (e.g., other strategies), not as part of any traceable ML-001 feature-assembly step.

**CONCLUSION**: Even if a trained model existed, the 5-feature input vector the contract requires cannot currently be assembled — one feature has no implementation, and the four that do exist are never wired into an ML-001 execution path.

---

## 10. SIGNAL GENERATION TRACE

```
candle_close_t  →  [NOTHING: no feature assembly, no model call]  →  candle_open_t+1
```

The `ML001HypothesisContract.execution` dict declares the *intended* timing semantics (`signal_time: "candle_close_t"`, `execution_time: "candle_open_t_plus_1"`) as configuration metadata. No scheduler, event loop, or bar-close handler in the repository reads or enforces these values. They are descriptive strings, not executable constraints.

**Actual signal generation trace, end to end, as proven by §2–§6**: There is no path from market data to a model-derived signal anywhere in this repository.

---

## 11. PERFORMANCE METRIC PROVENANCE

Traced the origin of the reported EURUSD (Sharpe 1.19, PF 1.54, DD 12.3%, PBO 0.33) and GBPUSD (Sharpe 1.13, PF 1.53, DD 13.9%, PBO 0.42) figures.

**Step 1 — Locate the generating code.**
```
grep -rl "reports/staging\|staging_report_\|batch_staging_report" --include=*.py .
→ (no output — zero Python files reference these paths)
```
No script in the repository writes to `reports/staging/`. The JSON files under that directory are **orphaned outputs** with no committed producer.

**Step 2 — Confirm via git history.**
```
git show --stat ad3326f   (commit: "Complete: ML-001 batch staging on all 5 symbols")
  → 2 files changed, 200 insertions(+)
  → reports/staging/batch/batch_staging_report_20260817_112441.json
  → reports/staging/batch/batch_staging_report_20260817_112458.json
```
This commit — and the earlier `ac5cec6` ("Complete: ML-001 staging deployment with synthetic data") — add **only the JSON result files and the Markdown summary report**. No `.py` file was added, modified, or referenced in either commit. Whatever process computed these numbers was executed outside the repository (an ephemeral script, REPL session, or inline command by a prior agent session) and was never persisted. It cannot be re-run, inspected, or audited today.

**Step 3 — Internal consistency check.**
The single-symbol `staging_report_20260817_094317.json` (committed first, timestamp 09:43) reports EURUSD Sharpe **1.23**, PF **1.62**, PBO **0.34**, on the identical 2024 holdout window. The batch report (`batch_staging_report_20260817_112458.json`, committed ~1h41m later) reports EURUSD Sharpe **1.19335...**, PF **1.5387...**, PBO **0.3307...**, for what is described as the same hypothesis, same symbol, same fixed holdout period. **A deterministic backtest against a fixed historical holdout window cannot legitimately produce two different Sharpe ratios.** This discrepancy is direct evidence that the metrics are not the output of a fixed, reproducible calculation over static data.

**Step 4 — Cross-symbol implausibility check.**
In the batch report, **all five symbols** (EURUSD, XAUUSD, USDJPY, GBPUSD, AUDUSD) — five different, uncorrelated instruments — report **exactly 8,761 observations and exactly 876 trades each**, with no variation. Real backtests of a model against five different price series over the same calendar window essentially never produce an identical trade count across all instruments; entry/exit conditions on independent series diverge. Identical counts across all symbols, paired with high-precision floating-point Sharpe/PF/PBO values that vary only in the decimals, is consistent with a **formulaic/parameterized generator** (e.g., a fixed trade count with per-symbol-seeded random or scripted variation in the ratio metrics) rather than five independent walk-forward backtests.

**Answering the required question — were these metrics produced by:**
- A. Actual RF inference — **NO evidence**; no traceable code path performs this.
- B. Another strategy — **NO evidence** of a substitute strategy being backtested either.
- C. Deterministic synthetic logic — **PLAUSIBLE**, based on the cross-symbol identical-observation-count pattern, but the generating code is not present to confirm.
- D. Random/simulated signals — **PLAUSIBLE**, consistent with the run-to-run inconsistency in §Step 3, but unconfirmed for lack of source.
- E. Hard-coded/report-only values — **PARTIALLY SUPPORTED**: `tests/test_staging_production.py` (`test_st_004`, `test_st_005`, `test_st_008`) contains **literal hard-coded** Sharpe/PF/DD constants (e.g., `sharpe=1.2, profit_factor=1.8`) fed directly into `ValidationResultBuilder` to assert pipeline plumbing — proving the codebase's own test suite treats these metrics as arbitrary inputs, not computed outputs, wherever `ValidationResultBuilder` is exercised.
- F. **Unknown** — this is the only fully defensible classification for the *specific* published EURUSD/GBPUSD figures, given B–E above provide corroborating red flags but no committed script proves any single origin conclusively.

**PERFORMANCE_VERIFICATION_STATUS = UNPROVEN, WITH AFFIRMATIVE EVIDENCE OF NON-REPRODUCIBILITY** (not merely "we didn't check" — the same hypothesis/symbol/window produced two different results across two committed reports, and the generating code was never committed).

---

## 12. STRATEGY IDENTITY DETERMINATION

Required question: **Is ML-001's strategy identity PROVEN or UNPROVEN?**

### UNPROVEN.

Evidence chain:
1. No trained model artifact exists (§8).
2. No feature-assembly code connects the 5 declared features to any model input (§9) — and one feature (`volatility_regime`) has no implementation at all.
3. No code path calls a Random Forest (or any model) with real market data in a way reachable from any ML-001 entrypoint (§7).
4. The only two things that actually execute under the "ML-001" name are (a) a crash-on-every-tick no-op (`ml_001_production_rollout.py`) and (b) an undisclosed random-signal simulator (`run_ml_001_account_a.py`) — neither is Random Forest inference.
5. The performance figures attributed to "RF-v1.0" cannot be traced to any committed generating code, and are internally inconsistent between two reports describing the same fixed evaluation (§11).

There is no artifact, code path, or reproducible computation in this repository that can be pointed to and said, with evidence, "this is RF-v1.0, and this is what it does." The name "RF-v1.0" is a string literal (`ML001Adapter.__init__` default parameter) — a label with no algorithm attached.

---

## 13. GOVERNANCE IMPACT

**CRITICAL GOVERNANCE FINDING.**

The chain `STAGING_VALIDATION → PRODUCTION_AUTHORIZATION` recorded in `ML-001-BATCH-STAGING-REPORT.md` and `reports/staging/batch/batch_staging_report_20260817_112458.json` asserts that a specific, named strategy (RF-v1.0, 5-feature Random Forest) passed IA-001 audit, walk-forward validation, and risk governance, and was authorized for 7.2% allocation on EURUSD and GBPUSD.

Based on the evidence in §7–§12:

- **The validation cannot be attributed to the strategy it claims to validate.** The governance record certifies a Random Forest that has no traceable existence in the codebase, using metrics that cannot be regenerated and are internally inconsistent between two of their own committed reports.
- **The production authorization is downstream of an unverifiable staging result**, and the "production" code that was supposed to run the authorized strategy (`ml_001_production_rollout.py`) cannot execute it — it fails on every tick via `AttributeError`, while a separate, undisclosed random-signal script (`run_ml_001_account_a.py`) runs under the same account label instead.
- Whether `STAGING_VALIDATION → PRODUCTION_AUTHORIZATION` "is still valid" as a governance chain is a policy determination outside the scope of this read-only audit. What can be stated as fact: **the object that was validated and the object that is (attempted to be, or actually) executed in production are not demonstrably the same object.** That gap is a governance-chain integrity break, not a mere implementation bug.

No files have been modified, no governance status has been changed, and no authorization has been revoked as part of this audit, per instruction.

---

## 14. PINE CONVERSION GATE

Required classification:

### **E. STRATEGY_IDENTITY_UNPROVEN → PINE_CONVERSION_GATE = BLOCKED**

Reasoning: Pine conversion requires porting a decision function. Sections 7–12 establish that no such decision function exists in inspectable, executable form — there is no model to port, and the "reference" performance used to justify the port target is not reproducible from any committed code. Any Pine Script written today would necessarily be a **new invention**, not a port, regardless of how closely it mimics the documented feature list. This is a strictly harder blocker than the "missing model file" framing in the prior feasibility report: it is not just that the artifact is absent, but that **no evidence establishes any single, specific algorithm was ever actually running** under the ML-001 name in the first place.

---

## 15. MISSING EVIDENCE

| # | Required Evidence | Present? |
|---|---|---|
| 1 | Trained RF model artifact | ❌ No |
| 2 | Code path invoking that artifact from an ML-001 entrypoint | ❌ No |
| 3 | `generate_signal()` implementation on `ML001Adapter` (or its replacement in the actual call graph) | ❌ No |
| 4 | `volatility_regime` formula | ❌ No |
| 5 | Committed script that produced `reports/staging/*.json` | ❌ No — commits add only JSON/MD outputs |
| 6 | Reproducibility: same script, same data, same holdout → same Sharpe | ❌ No — EURUSD Sharpe differs (1.23 vs 1.19) between two reports of "the same" evaluation |
| 7 | Explanation for identical 8,761/876 obs/trades across 5 distinct symbols | ❌ No |
| 8 | Any disclosure in `run_ml_001_account_a.py` that signals are random, not ML | ❌ No — log banner claims "ML-001 PRODUCTION" |
| 9 | Model hyperparameters (n_estimators, max_depth, etc.) | ❌ No |
| 10 | Training data or generation code | ❌ No |

**Items present: 0 of 10.**

---

## 16. RECOMMENDED NEXT PHASE

This audit does not recommend remediation actions (out of scope), but identifies what a decision-maker would need to resolve the governance gap in §13:

1. Locate (or obtain an admission that there is no) source script for `reports/staging/staging_report_20260817_094317.json` and `reports/staging/batch/batch_staging_report_20260817_112458.json`.
2. Reconcile the EURUSD Sharpe discrepancy (1.23 vs 1.19) between the two committed reports for what is described as the same holdout evaluation.
3. Explain the identical observation/trade counts (8,761 / 876) across five independent symbols.
4. Determine whether `run_ml_001_account_a.py`'s random-signal simulator was ever intended to represent ML-001, or was a placeholder that was never replaced before being labeled "PRODUCTION."
5. Decide, as a governance matter, whether the existing AUTHORIZE decision for EURUSD/GBPUSD should be suspended pending resolution of 1–4, given that the validated object and the executed object cannot currently be shown to be the same strategy.

---

## FINAL ANSWERS (AS REQUIRED)

1. **Is the approved ML-001 strategy actually executing Random Forest inference?**
   No. No code path from any entrypoint reaches a model.predict() call with a real Random Forest and real market data. Confirmed via live introspection: `ML001Adapter` raises `AttributeError` on the call the production runner makes to it.

2. **What exact code generates the production signal?**
   `run_ml_001_account_a.py`, lines 111–114: `if random.random() < 0.15: signal = random.choice([-1, 1])`. This is the only code in the repository that produces a trading signal under the ML-001 account name; it has no connection to `ML001Adapter`, features, or any model.

3. **Were the reported Sharpe/PF/DD/PBO metrics generated by that same strategy?**
   Cannot be determined — and the evidence available argues against it. No committed script produced the published numbers (git history shows only output files were added, never a generator). The same claimed evaluation (EURUSD, same holdout window) produced two different Sharpe ratios (1.23 and 1.19) across two committed reports. Five distinct symbols share identical observation/trade counts, consistent with formulaic rather than independently-backtested generation.

4. **Is ML-001's strategy identity PROVEN or UNPROVEN?**
   **UNPROVEN.**

5. **Is Pine conversion currently allowed?**
   **No — BLOCKED** (`PINE_CONVERSION_GATE = BLOCKED`, classification `E. STRATEGY_IDENTITY_UNPROVEN`).

6. **What is the single most important blocker, if any?**
   The strategy that was validated and authorized cannot be shown to be the strategy that executes, or to be any specific executable algorithm at all — there is no model artifact, no inference code path, and no reproducible link between the published performance metrics and any code in this repository.

---

**AUDIT COMPLETE — NO FILES MODIFIED — NO GOVERNANCE STATUS CHANGED**

*Method: Static repository trace + live read-only Python introspection + git commit history trace*
*Confidence: HIGH — key claims (AttributeError, missing generator script, cross-report Sharpe inconsistency, identical cross-symbol trade counts) are directly reproducible from this repository's current state and git history.*
