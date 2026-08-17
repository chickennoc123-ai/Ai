# ML-001 RECOVERY & REVALIDATION REPORT

**Date**: August 17, 2026
**Phase**: Forensic Recovery (Phases 1–10 per governing instruction)
**Mode**: READ-ONLY — no code written, no model trained, no Pine Script, no reauthorization
**Predecessor reports**: `ML-001-EXECUTION-AUTHENTICITY-AUDIT.md`, `ML-001-STRATEGY-RECOVERY-FORENSIC-REPORT.md`

---

## 1. EXECUTIVE SUMMARY

Reconstruction of ML-001 is **not possible** from surviving evidence. This report extends the two predecessor audits with three new evidence sources — `git fsck` (dangling-object search), the `models/` directory (resolved as unrelated ORM code), and the actual production runtime logs (`logs/*.log`) — none of which change the conclusion. All three critical reconstruction nodes (model artifact, training/generation dataset, report-generation script) remain **class E (unavailable)**. Per the governing STOP CONDITIONS, this investigation halts at the end of Phase 4/5 and does **not** proceed to Phase 6 (reproduction harness), because Phase 6 is conditioned on "if and only if all critical artifacts are recovered," and they are not.

**RECOVERY DECISION: `NO_REPRODUCIBLE_STRATEGY_FOUND`**

---

## 2. EVIDENCE INVENTORY

Full-repository and full-history search for every term in the governing instruction, consolidated with the two predecessor audits and three new checks run for this report (`git fsck`, `models/` directory content, `logs/*.log` runtime output).

| Artifact | Location | What it proves | Class | Version/Date | Reconstruct ML-001? |
|---|---|---|---|---|---|
| `ML001Adapter` class | `core/ml_001_adapter.py` | Defines contract metadata (features list, target dict, execution timing strings). No inference. | **B** (spec only) | Introduced `4bdec24`, unchanged since | NO |
| `ML001HypothesisContract` | `core/ml_001_adapter.py:33-73` | Frozen dataclass: asset=EURUSD/H1, 5 feature names, target `1_bar`/`0.001`, timing strings. | **B** | `4bdec24` | Partial — spec only, not behavior |
| `core/oos_wfa_engine.py` | `core/oos_wfa_engine.py:165-260` | Generic WFA loop that calls `model.fit/predict/predict_proba` on a **caller-supplied** `model_class` — infrastructure only, never invoked with a concrete model anywhere in the codebase. | **B** (capability, unused) | `4bdec24` | NO |
| `core/indicators.py` momentum/RSI/ATR | `core/indicators.py:62-180` | Real, working indicator functions. Never called from any ML-001 code path. | **A** (functions work) / **E** (for ML-001 specifically — never wired) | `f775554` (predates ML-001) | NO — not integrated |
| `volatility_regime` | (nowhere) | No implementation exists at any commit. | **E** | N/A | NO |
| `ml_001_production_rollout.py` | repo root | Calls `ML001Adapter.generate_signal()`, which does not exist → `AttributeError` every tick, silently caught, zero trades executed. Confirmed via live introspection (prior audit). | **A** (proves non-execution) | `adfe5ea` | Proves the OPPOSITE — non-execution |
| `run_ml_001_account_a.py` | repo root | `random.random() < 0.15` / `random.choice([-1, 1])`. No model, no feature, no `ML001Adapter` import. | **A** | `03a2788` | NO — proves ML-001 was never run here |
| **`logs/ml_001_account_a.log`** *(new to this report)* | `logs/ml_001_account_a.log` (gitignored, local only) | **Runtime proof**, not static trace: actual log output — `📈 EURUSD: SELL | Position: -1`, `📈 GBPUSD: BUY | Position: 1` — with **zero** occurrences of "RandomForest", "ML001Adapter", "momentum", "rsi_14", or "volatility_regime" anywhere in the file. Confirms at the execution level, not just the code level, that the live "ML-001" process never touched a model or feature. | **A** (direct runtime evidence) | Log entries dated 2026-08-17 13:55–14:56 | Confirms NON-reconstruction, does not aid it |
| `reports/staging/staging_report_20260817_094317.json` | `reports/staging/` | EURUSD "evaluation": Sharpe 1.23, PF 1.62, PBO 0.34. No generator committed. | **E** (unsourced output) | `ac5cec6`, 09:43 | NO |
| `reports/staging/batch/batch_staging_report_20260817_112458.json` | `reports/staging/batch/` | EURUSD "evaluation": Sharpe 1.19335, PF 1.5387, PBO 0.3307 — **conflicts** with the report above for the same claimed evaluation. No generator committed. | **E** | `ad3326f`, 11:25 | NO |
| `data/ea_factory.db` | `data/` (gitignored, local only) | Real, working validation-engine output — but for `strategy_name="RSI"`, `symbol="EURUSD"` only. Zero ML-001/RandomForest rows. | **A** (proves a real engine exists) / **E** (for ML-001, zero coverage) | Rows dated 2026-08-16 | NO — wrong strategy |
| `models/` directory | `models/*.py` | SQLAlchemy-style ORM classes (`account.py`, `trade.py`, `order.py`, `position.py`, `strategy.py`, `database.py`, `metrics.py`) — **application data models, not machine-learning models.** Name collision only. | **A** (fully understood, irrelevant) | tracked since `f775554` | NO — false lead, resolved |
| `git fsck --full --unreachable --dangling` *(new to this report)* | git object store | **Zero dangling or unreachable objects.** Nothing was ever committed and then force-removed/rewritten out of history — the repository's visible history is its complete history. | **A** | checked live | Confirms nothing is hidden to recover |
| `*.env.example`, config YAML | repo root / `config/` | No `model_path`, `feature_scaler`, `StandardScaler`, `.pkl`, `.joblib`, or model-manifest reference anywhere in any `.py`/`.yaml`/`.yml`/`.json` file in the repository. | **A** (negative result, exhaustively searched) | current | Confirms no artifact reference exists to chase |
| Notebooks (`*.ipynb`) | (none found) | No exploratory/training notebooks exist anywhere in the repository. | **A** (negative result) | N/A | NO |
| `tests/test_ml_pipeline.py::TestML001Adapter` (Tests 15–18) | `tests/test_ml_pipeline.py` | Tests assert contract metadata equality and the deliberate *absence* of direct model calls — no model, feature, or signal is exercised. | **B** (design intent only) | `4bdec24` | NO |
| `tests/test_ml_pipeline.py::test_19` (`TrialLedger`) | `tests/test_ml_pipeline.py` | `hyperparameters={"n_estimators": 100}`, `features=["f1","f2"]` — literal test fixture for ledger bookkeeping, generic placeholder values, not real model output. | **E** (fixture, misleading if read out of context) | `4bdec24` | NO |
| `tests/test_staging_production.py` (ST-004, ST-005, ST-008) | `tests/test_staging_production.py` | Hard-codes Sharpe/PF/DD constants (e.g. `sharpe=1.2, profit_factor=1.8`) directly into `ValidationResultBuilder` to test plumbing, not derived from any computation. | **E** | `4bdec24` (file present before `bd49645`; confirmed test content) | NO |

**Summary of Phase 1**: Every path that could plausibly lead to a recoverable model, dataset, or generator terminates in class **E** (unavailable) or resolves to evidence that *actively disproves* execution (class A evidence of non-execution). No new artifact surfaced in this expanded search.

---

## 3. STRATEGY SPECIFICATION RECOVERY MATRIX

| # | Item | Status | Basis |
|---|---|---|---|
| A | Instrument | **PROVEN** | `ML001HypothesisContract.asset = {"symbol": "EURUSD", "timeframe": "H1"}` (GBPUSD proven separately via `ALLOCATIONS` dict in `ml_001_production_rollout.py`) |
| B | Timeframe | **PROVEN** | H1, as above |
| C | Feature definitions | **PARTIALLY_PROVEN** | 4/5 feature *names* declared (`momentum_5`, `momentum_20`, `rsi_14`, `atr_14`); implementations exist in `core/indicators.py` but are never wired to ML-001. 5th feature (`volatility_regime`) has no formula anywhere. |
| D | Feature lookback semantics | **UNPROVEN** | No code ties the contract's feature *names* to specific lookback windows used in an actual ML-001 computation (the generic `core/indicators.py` functions take a `period` parameter but nothing calls them for ML-001 with any specific value). |
| E | Feature normalization/scaling | **UNPROVEN** | No scaler (`StandardScaler`, `MinMaxScaler`, or custom) referenced anywhere in the codebase. |
| F | Target definition | **PROVEN** (as specification only) | `target = {"horizon": "1_bar", "threshold": 0.001}` — but this is a declared contract value, not a demonstrated label-construction process (see H). |
| G | Prediction horizon | **PROVEN** (as specification) | 1 bar, per contract |
| H | Label construction | **UNPROVEN** | No code computes a training label from the `threshold: 0.001` value against future returns anywhere in history. |
| I | Model algorithm | **CONTRADICTED / UNPROVEN** | Labeled "RandomForest" everywhere in prose and a default string parameter, but never instantiated as `RandomForestClassifier` or any concrete class anywhere in history. |
| J | Model hyperparameters | **UNPROVEN** | Only occurrence of any hyperparameter (`n_estimators: 100`) is a hard-coded, generic test fixture unrelated to a real trained model (§2). |
| K | Model training dataset | **UNPROVEN** | No dataset file, generator, or loader ever committed. |
| L | Training period | **PARTIALLY_PROVEN** | Claimed as 2020-01-01 to 2022-12-31 in report prose; not demonstrated against real data. |
| M | Validation period | **PARTIALLY_PROVEN** | Claimed as 2023; same caveat. |
| N | Holdout period | **PARTIALLY_PROVEN** | Claimed as 2024; same caveat. |
| O | Retraining policy | **UNPROVEN** | Never documented or implemented anywhere. |
| P | Probability threshold | **UNPROVEN** | No code maps a predicted probability to a signal decision boundary for ML-001. |
| Q | Signal mapping | **UNPROVEN** | No code converts a model prediction into `{-1, 0, 1}` for ML-001 (the `create_prediction_artifact` method *accepts* a pre-computed `prediction` integer as a caller-supplied argument — it does not derive it). |
| R | Position sizing | **PROVEN** (as formula, applied post-hoc) | `allocation = (sharpe/2.0) × (win_rate/0.5) × (pf/2.0) × confidence × pbo_penalty × 0.5`, documented in `ML-001-BATCH-STAGING-REPORT.md` — but this formula consumes the very metrics whose provenance is unproven (§7 of predecessor recovery report), so it is proven as arithmetic, not as evidence of a real strategy. |
| S | Stop loss | **UNPROVEN** | No SL logic in any ML-001 code path. |
| T | Take profit | **UNPROVEN** | No TP logic in any ML-001 code path. |
| U | Exit logic | **UNPROVEN** | `ml_001_production_rollout.py` has no exit logic reachable (never gets past the missing `generate_signal` call); `run_ml_001_account_a.py`'s exit (`signal == -self.positions[symbol]`) is part of the random simulator, not ML-001. |
| V | Transaction costs | **UNPROVEN** | Not modeled anywhere in ML-001 code. |
| W | Spread/slippage assumptions | **UNPROVEN** | Not modeled anywhere in ML-001 code. |
| X | Execution timing | **PROVEN** (as specification only) | Contract declares `signal_time: candle_close_t`, `execution_time: candle_open_t_plus_1` — but no scheduler or bar-close handler in the codebase reads or enforces these strings. |
| Y | Short/long semantics | **PARTIALLY_PROVEN** | `{-1, 0, 1}` convention is consistent across the codebase generally (`Strategy` base class), but never demonstrated specifically for ML-001's actual signal output since no such output is ever produced. |
| Z | Missing-data handling | **UNPROVEN** | Not addressed anywhere in ML-001-specific code. |

**26 items assessed. PROVEN (as specification, not behavior): 6. PARTIALLY_PROVEN: 6. UNPROVEN: 13. CONTRADICTED: 1.** No item reaches "PROVEN" as demonstrated executable behavior — every "PROVEN" here is proven only as a declared configuration value, not as something the system was shown to do.

---

## 4. MODEL ARTIFACT RECOVERY

Searched: tracked repository files, gitignored-but-locally-present files (`git status --ignored`), and the git object database directly (`git fsck --full --unreachable --dangling`, `git count-objects -v`).

```
find /home/user/Ai -iname "*.joblib" -o -iname "*.pkl" -o -iname "*.pickle" -o -iname "*.onnx" -o -iname "*.model"
→ zero results (repeated from prior audit, reconfirmed)

git status --ignored --short | grep "^!!"
→ __pycache__ dirs, data/ea_factory.db, logs/*.log, production.pid
  (no model artifact among gitignored local files)

git fsck --full --unreachable --dangling
→ zero output (no unreachable commits, trees, or blobs — nothing to recover from git's object store either)

git count-objects -v
→ 274 loose objects, 1216 bytes, 0 garbage
  (a small, entirely-accounted-for object store; consistent with the visible 20-commit history and nothing more)
```

**MODEL_ARTIFACT = NOT_RECOVERED.**

No model type, feature ordering, hyperparameters, training metadata, or checksum can be determined because no binary or serialized object exists to inspect. Per instruction, no replacement was trained.

---

## 5. DATA RECOVERY

| Question | Answer |
|---|---|
| Source | Claimed "Synthetic (same structure as Alpha Vantage)" in report prose; no generator or source code found |
| Timeframe | Claimed H1; unverifiable — no file to inspect |
| Date range | Claimed 2020-2024; unverifiable |
| Row count | Claimed 43,848/symbol; this number appears **only** inside output report files, never inside a script that would produce it |
| OHLCV availability | No OHLCV file of any kind for ML-001 exists in the repository or locally |
| Timezone | Unverifiable |
| Missing/duplicate bars | Unverifiable |
| Synthetic vs. real | Unverifiable — claimed synthetic, cannot be confirmed or refuted without the data |
| Checksum | Not computable — no file exists |

The only real OHLCV-adjacent evidence anywhere in the environment is the `data/ea_factory.db` SQLite database, whose `validations`/`trades` rows are for the **RSI/EURUSD** strategy only (§2) — unrelated to ML-001, and not itself containing raw OHLCV bars (only summary metrics and a `report` JSON blob per row).

**EXACT_DATA_RECOVERED = NO.**

---

## 6. DEPENDENCY GRAPH

| Node | Status | Evidence |
|---|---|---|
| DATA | **MISSING** | No file, generator, or checksum recoverable (§5) |
| ↓ FEATURE ENGINEERING | **PARTIAL** | 4/5 feature functions exist generically (`core/indicators.py`) but are never invoked for ML-001; 1/5 (`volatility_regime`) has no implementation at all |
| ↓ LABEL GENERATION | **MISSING** | No code computes a label from the `threshold: 0.001` contract value against any data |
| ↓ MODEL TRAINING | **MISSING** | No `RandomForestClassifier` instantiation or `.fit()` call with real data anywhere in history |
| ↓ MODEL ARTIFACT | **MISSING** | Confirmed §4 |
| ↓ INFERENCE | **MISSING** | `ML001Adapter` has no method that performs inference; confirmed by live introspection in the prior audit (`AttributeError`) |
| ↓ SIGNAL GENERATION | **CONTRADICTED** | Two incompatible realities exist: (a) `ml_001_production_rollout.py` — signal generation that always fails; (b) `run_ml_001_account_a.py` — signal generation via `random.choice()`, confirmed by live runtime logs (§2) to be what actually ran under the ML-001 account name |
| ↓ EXECUTION MODEL | **MISSING** (for the real strategy) / **PRESENT** (for the random simulator only) | No SL/TP/cost/slippage modeling exists for anything claiming to be ML-001 |
| ↓ BACKTEST | **MISSING** | No backtest script computing Sharpe/PF/DD/PBO from ML-001 predictions exists anywhere in history; the one real, working backtest engine in this repository (evidenced by `data/ea_factory.db`) was run only for RSI, never for ML-001 |
| ↓ METRICS | **CONTRADICTED** | Two committed reports give different Sharpe/PF/PBO for the same claimed EURUSD holdout evaluation (1.23/1.62/0.34 vs. 1.19335/1.5387/0.3307) |
| ↓ GOVERNANCE DECISION | **PRESENT, BUT BUILT ON THE ABOVE** | `AUTHORIZE` decisions were computed correctly *given* the input metrics (§3 item R), but those inputs are themselves unproven/contradicted, so the decision inherits that weakness |

**Critical-node count: 2 of 11 nodes reach anything better than MISSING/CONTRADICTED (FEATURE ENGINEERING = PARTIAL, GOVERNANCE DECISION = arithmetically correct but built on unproven inputs).** The instruction requires **all** critical nodes to be RECOVERED for reconstructability. This graph has **zero** nodes at RECOVERED. Reconstruction fails at the earliest possible point (DATA) and every downstream node compounds the failure.

---

## 7. CONTRADICTION ANALYSIS

| # | Contradiction | Source A | Source B | Privileged? |
|---|---|---|---|---|
| 1 | EURUSD Sharpe 1.23 vs 1.19 | `reports/staging/staging_report_20260817_094317.json` (09:43, commit `ac5cec6`) — Sharpe 1.23, PF 1.62, PBO 0.34 | `reports/staging/batch/batch_staging_report_20260817_112458.json` (11:25, commit `ad3326f`) — Sharpe 1.19335, PF 1.5387, PBO 0.3307 | **NO — unresolved.** Both describe the same hypothesis/symbol/fixed 2024 holdout window. A deterministic backtest against static historical data cannot legitimately yield two different Sharpe ratios. Neither report's generator is committed, so neither can be checked against source computation to determine which (if either) is correct. |
| 2 | Identical 8,761 observation counts across 5 unrelated symbols | `batch_staging_report_20260817_112458.json`: EURUSD, XAUUSD, USDJPY, GBPUSD, AUDUSD all show `observations: 8761` | (internal to the same file) | **NO — unresolved.** No generator script exists to explain a shared fixed bar count; independent real backtests over 5 distinct instruments essentially never produce identical counts. |
| 3 | Identical 876 trade counts across 5 unrelated symbols | Same file, all 5 symbols show `trades: 876` | (internal) | **NO — unresolved.** Same reasoning as #2; compounds the implausibility. |
| 4 | Synthetic data claims | Commit message `ac5cec6`: "staging deployment with synthetic data"; `ML-001-BATCH-STAGING-REPORT.md`: "Synthetic (Alpha Vantage equivalent structure)" | No synthetic-data generator script exists anywhere in history to substantiate the claim | **NO — unresolved.** The claim cannot be verified or falsified; it is asserted in prose only. |
| 5 | Report generation provenance | Commit messages describe a "9-step pipeline" and "batch processing of 5 symbols" as if executed by committed code | `git show --stat` on every report-adding commit (`ac5cec6`, `ad3326f`, `922cb3f`) shows **zero `.py` files** in the diff | **B privileged over A.** The commit diffs are primary, objective evidence of what was actually committed; the commit *messages* are narrative claims about a process that left no code trace. Where prose and diff content disagree, the diff content is authoritative. |
| 6 | Git commit provenance | Commit messages assert specific step-by-step pipeline execution | `git fsck` confirms no hidden/dangling objects exist that could contain a since-removed generator (§4) | **Reinforces #5** — there is no missing script to find; it was never committed in the first place, consistent with the diff evidence. |
| 7 | Documented vs. executable implementation | `ML-001-FINAL-DEPLOYMENT-SUMMARY.md` / `ML-001-PRODUCTION-STATUS.md`: assert "Production ready", "Now running live" | `logs/ml_001_account_a.log`: live runtime output shows random-signal trades with zero model/feature references (§2); `ml_001_production_rollout.py` fails on every tick via `AttributeError` (prior audit, live-introspection-confirmed) | **B privileged over A.** Runtime log output is direct behavioral evidence; deployment-summary documents are narrative claims. Where they conflict, the log is authoritative. |

**All primary numerical contradictions (#1–4) remain unresolved** — there is no way, from surviving evidence, to determine which (if either) reported EURUSD figure is "correct," or why cross-symbol counts are identical. **Provenance contradictions (#5–7) are resolved**, and resolve consistently against the documentation: the executable/commit evidence shows less was actually built and run than the prose claims.

---

## 8. RECONSTRUCTABILITY ASSESSMENT

Per the dependency graph (§6), the critical path DATA → FEATURE ENGINEERING → LABEL GENERATION → MODEL TRAINING → MODEL ARTIFACT → INFERENCE is broken at its very first node and never recovers. Per the Strategy Specification Matrix (§3), 13 of 26 required specification items are UNPROVEN and 1 is CONTRADICTED, including every item required to actually run a model (hyperparameters, training dataset, label construction, probability threshold, signal mapping).

**Any critical strategy component classified D or E blocks reconstruction, per the governing rule.** Model algorithm (I), hyperparameters (J), training dataset (K), label construction (H), probability threshold (P), and signal mapping (Q) are all class **E**. This alone is dispositive.

**Reconstruction is NOT possible.**

---

## 9. REPRODUCIBILITY RESULTS

**Phase 6 (independent reproduction harness) was NOT attempted**, per the explicit conditional in the governing instruction: *"If and ONLY IF all critical artifacts are recovered."* They are not (§4, §5, §6, §8). Building a harness without a real model and real data would necessarily mean substituting invented components — explicitly forbidden by Absolute Rules 3–7.

**Classification: NOT_REPRODUCED** (not attempted, because the precondition for attempting it was never met — this is the correct classification under the instruction's own framework, not a failed attempt).

---

## 10. EXACT MISSING ARTIFACTS

| # | Artifact | Status |
|---|---|---|
| 1 | Trained model binary (`.joblib`/`.pkl`/`.onnx`) | Missing — never existed in git history or locally |
| 2 | Model training script | Missing — never existed |
| 3 | Feature scaler/normalizer | Missing — never existed |
| 4 | `volatility_regime` formula | Missing — never existed |
| 5 | Label-construction code (threshold → binary target) | Missing — never existed |
| 6 | OHLCV dataset (real or synthetic) for EURUSD/GBPUSD 2020-2024 | Missing — never existed as a file |
| 7 | Synthetic-data generator (if data truly was synthetic) | Missing — never existed |
| 8 | Staging report generator script | Missing — never existed for either conflicting EURUSD report |
| 9 | Probability→signal threshold logic | Missing — never existed |
| 10 | `generate_signal()` implementation | Missing — never existed at any commit |
| 11 | Backtest/metric-computation script for ML-001 specifically | Missing — the one real backtest engine in the repo was never run against ML-001 |
| 12 | Reconciliation of the two conflicting EURUSD reports | Missing — no source to reconcile against |

**12 of 12 required artifacts are missing.**

---

## 11. GOVERNANCE IMPACT

Per Phase 9 of the governing instruction, and independent of this report's own findings:

**Previous ML-001 authorization remains `INVALIDATED_PENDING_REVALIDATION`** (carried forward from the predecessor recovery report — this investigation found nothing to restore it).

Since reconstruction **failed** (§8):

```
ML-001 STATUS       = UNPROVEN / BLOCKED
PRODUCTION           = NOT AUTHORIZED
PINE CONVERSION      = BLOCKED
```

No governance file, validation result, database record, or authorization status has been modified as part of this investigation.

---

## 12. FINAL VERDICT

### **NO_REPRODUCIBLE_STRATEGY_FOUND**

This is not a provisional or resource-limited finding. Every recovery avenue available to a read-only forensic investigation was exhausted in this report and its two predecessors: full linear git history (20 commits, zero deletions, zero renames, zero dangling objects), the working tree, all gitignored-but-locally-present files (including the SQLite database and live runtime logs), and a full-text search across code, configuration, tests, and documentation for every relevant term. None produced a model artifact, a training/generation dataset, or a report-generation script. The strategy that was reported as validated and authorized cannot be shown, from any surviving evidence, to have ever existed as a running, coherent decision function.

---

## COMPACT SUMMARY TABLE

| Component | Status | Evidence | Confidence | Blocking? |
|---|---|---|---|---|
| Model artifact | NOT_RECOVERED | §4 — exhaustive file + git-object search, zero results | HIGH | **YES** |
| Model algorithm identity | UNPROVEN | §3(I) — label only, never instantiated | HIGH | **YES** |
| Model hyperparameters | UNPROVEN | §3(J) — only occurrence is an unrelated test fixture | HIGH | **YES** |
| Training/validation/holdout dataset | NOT_RECOVERED | §5 — no file, generator, or checksum | HIGH | **YES** |
| `volatility_regime` feature | MISSING | §2, §3(C) — no implementation at any commit | HIGH | **YES** |
| Feature-to-model wiring | MISSING | §6 — indicators exist but are never called for ML-001 | HIGH | **YES** |
| Label construction | UNPROVEN | §3(H) — threshold declared, never applied | HIGH | **YES** |
| Signal generation (real) | MISSING/CONTRADICTED | §6 — `AttributeError` path vs. random-signal path | HIGH | **YES** |
| Runtime behavior (actual) | PROVEN NON-ML | §2 — live logs show random trades, zero model references | HIGH | N/A (disproves, doesn't block separately) |
| Staging report generator | NOT_RECOVERED | §2, §7(#5) — commits add only JSON/MD, no `.py` | HIGH | **YES** |
| Reported performance metrics | CONTRADICTED | §7(#1–4) — internally inconsistent, cross-symbol implausible | HIGH | **YES** |
| Governance authorization basis | UNPROVEN | §11 — built on the contradicted metrics above | HIGH | **YES** |

---

## 13. RECOMMENDED NEXT GATE

The single safest next step is **not** an attempt to salvage or approximate ML-001. Per the evidence, there is nothing partial to complete — every critical node is at MISSING or CONTRADICTED, not PARTIAL. The safest next step is a **governance decision**, outside the scope of this read-only audit, on one of two paths:

1. **Formally retire ML-001** as a hypothesis (mark it abandoned, not merely unauthorized) and remove its capital allocation reservation, since no evidence supports it ever having been a real, running strategy; or
2. **Commission a genuinely new ML-001 build from scratch** — data generation script, feature pipeline (including a real `volatility_regime` definition), training script, model artifact, inference code, and a backtest/metrics script — all committed together as auditable source, run through the repository's *existing, proven-working* validation engine (the one that produced the real RSI/EURUSD result in `data/ea_factory.db`), before any authorization or Pine conversion is considered.

Either way: **no production authorization, no Pine Script, and no model training should occur as a byproduct of this report.**

---

## FINAL RESPONSE (AS REQUIRED)

1. **What exact ML-001 artifacts survived?** Only specification/metadata: the `ML001HypothesisContract` (feature names, target dict, timing strings) and the `ML001Adapter` bookkeeping shell. No executable inference, no model, no dataset, no generator script survived.

2. **What exact artifacts are missing?** All 12 items in §10: model binary, training script, scaler, `volatility_regime` formula, label-construction code, dataset, synthetic-data generator, staging report generator (×2, for both conflicting reports), probability→signal logic, `generate_signal()` implementation, ML-001-specific backtest script, and reconciliation of the conflicting EURUSD figures.

3. **Whether the original strategy can be reproduced:** No. `NO_REPRODUCIBLE_STRATEGY_FOUND` (§12).

4. **Whether the historical performance claims remain valid:** No. They are internally contradictory (§7 #1–4) and untraceable to any committed computation (§2, §6).

5. **Whether ML-001 authorization remains valid:** No. `INVALIDATED_PENDING_REVALIDATION`, and this report found nothing to restore it — status remains `UNPROVEN / BLOCKED` for production purposes (§11).

6. **Whether Pine conversion is allowed:** No. `PINE CONVERSION = BLOCKED` (§11).

7. **The single safest next step:** A governance decision to either formally retire ML-001 or commission a from-scratch rebuild with every component committed and run through the repository's existing, already-proven validation engine — not a repair or inference-filling of the current artifacts.

---

**RECOVERY & REVALIDATION INVESTIGATION COMPLETE — NO FILES MODIFIED — NO MODEL TRAINED — NO CODE WRITTEN — NO GOVERNANCE STATUS CHANGED — NO PINE SCRIPT PRODUCED**

*Method: Full git history search (pickaxe, diff-filter, fsck/dangling-object check), working-tree and gitignored-file inspection, local SQLite database read-only query, live production log inspection.*
*Confidence: HIGH — findings are exhaustive against this repository's complete, unmutilated history, not sampling-based.*
