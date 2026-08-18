# STRATEGY REALITY RECONSTRUCTION REPORT
## ML-001 + AGLE — Forensic Repair Investigation (No Economic Claims)

**Date**: August 18, 2026
**Repository state**: commit `935633c`, branch `claude/ea-factory-pro-system-bc9jaa`, clean tree at start.
**Mode**: READ-ONLY. No code, EVG semantics, strategy, or artifact was modified, trained, or fabricated by this report.
**Predecessor**: `FINAL_TWO_STRATEGY_ECONOMIC_VALIDATION_REPORT.md` (verdict: both FAIL, edge not proven — unchanged, not re-litigated here).

---

## 0. WHAT THIS REPORT ADDS

The prior audit established *that* both live paths are random-number generators. This report establishes *why* — by tracing, file by file, exactly which pieces of a real trading pipeline exist, which are missing, and which exist-but-are-disconnected, for both ML-001 and AGLE. One material correction to the prior audit's framing is made here: **AGLE is not a second trading-signal strategy in the same sense as ML-001** — it is the EA Factory Pro platform's own Docker-orchestrated service stack (API/worker/dashboard/redis/postgres/influxdb), which never successfully started in any environment this repository's history shows evidence of, and silently fell back to an undisclosed `random.choice` simulator every time it was invoked. This does not change the FAIL verdict; it changes what "AGLE" *is*, which matters for repair planning (Phase 8).

---

## 1. PHASE 1 — COMPLETE RANDOM/MOCK INVENTORY

Full repository grep, tracked files, for `random.random`, `random.choice`, `random.uniform`, `np.random`/`numpy.random`, plus textual markers (`fake`/`simulated`/`demo`/`placeholder`/`mock`/`synthetic`/`stub`/`TODO`/`FIXME` near "strategy"/"signal"/"P&L"):

| File | Line(s) | What it does | Classification |
|---|---|---|---|
| `run_ml_001_account_a.py` | 113–114, 132 | `random.random()<0.15` → `random.choice([-1,1])` signal; `pnl_change = random.uniform(-0.3,0.3)*allocation` | **PRODUCTION PATH** (live entrypoint, "ML-001 PRODUCTION (Account A)" banner) — undisclosed fallback |
| `run_agle_account_b.py` | 97–100 | `random.random()<0.1` → `random.choice([-1,1])`, comment: `# Simulate market analysis and signal generation` | **PRODUCTION PATH** (live entrypoint, "AGLE 24/7 (Account B)" banner) — undisclosed fallback |
| `run_separate_accounts_orchestrator.py` | 86–102 (ML-001 side), 173–176 (AGLE side) | Both accounts, same pattern; comments `# Simulate trading`, `# Simulate P&L`, `# Simulate monitoring` | **PRODUCTION PATH** variant — self-documented as simulation in comments, not in the user-facing log banners |
| `run_production_full.py` | 67 (docstring), 91–92, 157–160, 176–179 | Class docstring: `"""Simulates AGLE when Docker unavailable."""`; both accounts use the same random pattern | **DISCLOSED FALLBACK IN CODE COMMENT, NOT IN OPERATOR-FACING OUTPUT** — see Phase 3 |
| `ml_001_agle_production_orchestrator.py` | 267 (`np.random.choice([-1,0,1], p=[0.3,0.4,0.3])`), 92–147 (`AGLEManager.activate_24_7`) | A **fourth**, independent random-signal implementation for ML-001, inline in the orchestrator's own "PRODUCTION" class; separately, `AGLEManager` tries to launch the real Docker stack and fails closed with an explanatory log message if Docker is unavailable (does **not** silently fall back to random itself — the fallback happens in the *calling* script, see Phase 3) | **PRODUCTION PATH** (ML-001 side) / **REAL BUT NEVER-SUCCESSFULLY-INVOKED ATTEMPT** (AGLE Docker side) |
| `ml_001_production_rollout.py` | 338 (`_get_price`, docstring `"""Get current price (simulated)."""`, hardcoded `EURUSD: 1.0850, GBPUSD: 1.3050` + `np.random.normal(0,0.00005)` noise), 362–364 (`simulated_return = signal * np.random.normal(0.0001, 0.00005)`) | Price is **not fetched from any market data source at all** — it is a hardcoded constant plus Gaussian noise; P&L is `signal × N(0.0001, 0.00005)`, i.e. drawn from a distribution with a small **positive mean in the signal's own direction**, independent of the (also fake) price | **PRODUCTION PATH**, and the single most misleading artifact found in this inventory — see Phase 6 |
| `agents/risk_agent.py` | 166 (`np.random.default_rng(1234)`) | Monte-Carlo VaR estimation over an already-open real position book (`positions[i].net_profit`, `spec.annual_volatility`) | **LEGITIMATE** — standard risk-engine technique, not signal/P&L fabrication |
| `agents/research_agent.py` | 301 (`np.random.default_rng(97)`) | Mutation/selection RNG for a genetic-algorithm strategy-research loop (`mutation_rate`, `population`, `hall_of_fame`), backed by the real `core.backtest.BacktestEngine`/`core.validation.ValidationSuite` | **LEGITIMATE, REAL, BUT NEVER PRODUCED ML-001 OR AGLE** — see Phase 8 |
| `core/data_manager.py` | 145 (`np.random.default_rng(_seed_for(...))`) | `class` explicitly named/labeled `name = "simulated"` — a disclosed, GARCH-like synthetic OHLCV generator used as a fallback data source | **LEGITIMATE AND DISCLOSED** — the class identifies itself as simulated; the harm in this repository is never using this label truthfully in the ML-001/AGLE production banners, not this generator's existence |
| `core/validation.py` | 169, 243, 324, 455 (`np.random.default_rng(7/11/23/31)`) | Monte-Carlo parameter sampling, walk-forward fold generation, bootstrap/robustness testing — inside the **real, working** validation engine that produced the genuine RSI Sharpe=−2.41 result (`data/ea_factory.db`) | **LEGITIMATE** — this is what correct statistical-robustness randomness looks like |
| `core/strategy.py` | 122 (`Strategy.sample(rng)`) | Parameter-space sampling interface for the real `Strategy` base class | **LEGITIMATE** |
| `broker/simulator.py` | 223 (`self._random.uniform(0.0, slippage_pips)`) | Slippage modeling inside a broker execution **simulator** (paper-trading), applied to real order objects with real sides/prices | **LEGITIMATE** — standard, disclosed simulator component |
| `broker/xm_websocket.py` | 108; `websocket/manager.py` | 111; `utils/helpers.py` | 151, 192 | Reconnect-backoff jitter | **LEGITIMATE**, unrelated to trading logic |

**No occurrence** of the literal terms "fake P&L", "demo P&L", "placeholder signal", "mock signal", "synthetic signal", "stub strategy", or a `TODO`/`FIXME` attached to strategy logic was found — the repository does not self-flag these sections as incomplete work; they are dressed as finished, "PRODUCTION"-banner code.

**Summary**: of 6 files containing a strategy-adjacent `random` call, all 6 (`run_ml_001_account_a.py`, `run_agle_account_b.py`, `run_separate_accounts_orchestrator.py`, `run_production_full.py`, `ml_001_agle_production_orchestrator.py`, `ml_001_production_rollout.py`) are live/production entrypoints, not test fixtures or clearly-marked demos. Every other `random`/`np.random` occurrence in the repository (9 files) is legitimate, disclosed infrastructure (risk VaR, genetic search, synthetic-data fallback, statistical robustness testing, execution-simulator slippage, network-retry jitter).

---

## 2. PHASE 2 — ML-001 RECONSTRUCTION: "WHERE IS THE REAL STRATEGY?"

Two, formally distinct things share the "ML-001" name in this repository. Neither is what runs live.

### 2a. The original ML-001 (the one actually deployed under the "ML-001" account label)

```
raw market data        → MISSING   (never fetched anywhere in the live path)
    ↓
FE-R2-002 / features    → MISSING   (feature NAMES declared in ML001HypothesisContract
                                      match ML-001-R2's names exactly — momentum_5,
                                      momentum_20, rsi_14, atr_14, volatility_regime —
                                      but no FORMULA is implemented for any of them
                                      under the ML-001 contract; core/indicators.py has
                                      real momentum/RSI/ATR functions but they are never
                                      called from any ML-001 code path)
    ↓
model artifact           → MODEL_ARTIFACT = NONE   (no .joblib/.pkl ever committed;
                                                      confirmed independently in this
                                                      audit and three prior forensic
                                                      reports)
    ↓
probability               → MISSING   (nothing computes one)
    ↓
threshold/decision rule    → SPEC_EXISTS_IMPLEMENTATION_MISSING
                              (ML-001-R2's spec §10 thresholds, 0.55/0.45, exist for
                              the DIFFERENT ML-001-R2 entity; the original ML-001
                              contract has no threshold field at all)
    ↓
position sizing            → MISSING
    ↓
SL/TP/max-hold/exit priority → MISSING
    ↓
execution                  → IMPLEMENTATION_EXISTS_NOT_WIRED, in the worst sense:
                              `ml_001_production_rollout.py` calls
                              `ML001Adapter.generate_signal()`, a method that has
                              never existed on that class at any commit (confirmed
                              by `ML-001-STRATEGY-RECOVERY-FORENSIC-REPORT.md`,
                              re-verified this audit via `grep -n "generate_signal"
                              core/ml_001_adapter.py` → zero matches) — this path
                              raises AttributeError on every tick and places zero
                              trades. The code that DOES place "trades" under the
                              ML-001 label is a completely separate, disconnected
                              script (`run_ml_001_account_a.py`) using
                              `random.choice`.
```

**`ML-001HypothesisContract`** (`core/ml_001_adapter.py:33-73`, read directly this audit) is real, frozen, validated dataclass — asset `EURUSD/H1`, 5 feature names, target `{"horizon": "1_bar", "threshold": 0.001}`, execution timing strings `"candle_close_t"`/`"candle_open_t_plus_1"`. This is a genuine specification. **Nothing behind it is implemented.** `ML001Adapter` itself (the class using this contract) has no `generate_signal`, no feature computation, no model load — it is "metadata/audit shell" (per the prior forensic report's own accurate phrase, independently re-confirmed here).

`ML001_REAL_STRATEGY_STATUS (original) = SPEC_EXISTS_IMPLEMENTATION_MISSING`

### 2b. ML-001-R2 (the "clean rebuild" — a different strategy_id, not what's deployed)

```
raw market data        → BLOCKED   (no licensed vendor configured anywhere in this
                                     environment; ML-001-R2-ECONOMIC-VALIDATION-REPORT.md)
    ↓
FE-R2-002 features       → REAL, IMPLEMENTED, TESTED
                            (core/features/fe_r2_001.py: momentum_5, momentum_20,
                            rsi_14, atr_14, volatility_regime — exact seeded-Wilder
                            formulas, 100/600-bar warmup, hash-verified unchanged
                            this session: 1d8ce135...ffd3dd)
    ↓
model artifact            → MODEL_ARTIFACT = NONE
                             (core/ml_r2/model_r2.py::RFR2Model is a real, instantiable,
                             trainable class with explicit hyperparameters — but no
                             TRAINED, PERSISTED artifact has ever existed; "the class
                             exists" ≠ "the model exists")
    ↓
probability                 → MISSING (nothing to compute it; NullModelProvider in
                                        core/ml_r2/simulator_r2.py fails closed by design)
    ↓
threshold/decision rule      → REAL, IMPLEMENTED, TESTED
                                (core/ml_r2/backtest_r2.py: p>0.55 LONG / p<0.45 SHORT,
                                spec §10, unit-tested)
    ↓
position sizing               → REAL, IMPLEMENTED, TESTED (same file, 2%-risk formula)
    ↓
SL/TP/max-hold/exit priority   → REAL, IMPLEMENTED, TESTED (1.5×/2.5× ATR, 24-bar,
                                  SL>TP>MaxHold>Reversal priority — regression-tested
                                  against a golden dataset, this session)
    ↓
execution                      → REAL MECHANICS EXIST, IMPLEMENTATION_EXISTS_NOT_WIRED
                                  to any broker account; never touches
                                  run_ml_001_account_a.py or any live entrypoint
```

**This is the single most important structural fact in this report**: a substantially real, tested, spec-faithful implementation of "an ML-001-shaped strategy" *exists in this repository* — but it is a **different strategy identity** (`strategy_id=ML-001-R2`, `feature_version=FE-R2-002`) from the one running live under the "ML-001" account label, and it has never been connected to `run_ml_001_account_a.py`, `run_production_full.py`, `ml_001_production_rollout.py`, or any broker account (confirmed by `grep -l "ml_r2\|fe_r2_001" run_*.py ml_001*.py` → zero matches). The live "ML-001" and the tested "ML-001-R2" are not the same code, do not share a strategy_id, and were never meant to be — but neither is what a reasonable reader of `ML-001-FINAL-DEPLOYMENT-SUMMARY.md` would expect "ML-001 in production" to mean.

`ML-001-R2_REAL_STRATEGY_STATUS = IMPLEMENTATION_EXISTS_NOT_WIRED (to any broker execution path); MODEL_ARTIFACT = NONE; ECONOMIC_VALIDATION = BLOCKED (no real data)`

---

## 3. PHASE 3 — AGLE RECONSTRUCTION: "WHERE IS THE REAL STRATEGY?"

**Correction to the prior audit's framing**: AGLE is not a second ML strategy parallel to ML-001. Every artifact that defines what AGLE is meant to be describes it as **the full EA Factory Pro platform running as a 24/7 monitored service stack**, not a distinct signal-generation algorithm:

- `docker-compose.yml` (real file, read this audit): defines `postgres`, `redis`, `influxdb`, `api`, `worker`, `dashboard` services, backed by real `Dockerfile.postgres`/`Dockerfile.redis`/`Dockerfile.influxdb`/`Dockerfile.api`/`Dockerfile.worker`/`Dockerfile.dashboard`.
- `ml_001_agle_production_orchestrator.py::AGLEManager.activate_24_7()`: attempts `docker --version`, then `docker-compose up -d`, then verifies and sets `--restart unless-stopped` on exactly those six services. If Docker is unavailable, it logs a clear, honest failure: *"Docker not available... AGLE 24/7 requires Docker to be installed and running... Current environment: Remote Claude Code session (no Docker)"* and **returns `False` without inventing a fallback**. This one component behaves correctly — it fails closed, disclosed, no fabrication.
- `run_production_full.py`'s `AGLE_Simulator` class docstring: `"""Simulates AGLE when Docker unavailable."""` — an explicit, in-code acknowledgment that this class is a stand-in, not the real thing.

**What the platform behind AGLE actually contains, if it had started**: `core/strategy_registry.py` (real strategy factory/registry, backed by the 14 real strategies in `strategies/*.py` plus the Research Agent's `ai_generated` package), `core/backtest.py::BacktestEngine` and `core/validation.py::ValidationSuite` (the real, working validation engine that produced the genuine RSI Sharpe=−2.41 result), `core/decision_engine.py`, `core/evidence_aggregator.py` (the real EVG), `services/strategy_service.py` (CRUD for strategy configuration, API/dashboard-facing). All of these are real, implemented, and at least partially tested. **None of them is a specific "AGLE trading strategy"** — there is no `AGLEStrategy` class, no AGLE feature set, no AGLE model anywhere in the repository (`grep -rn "class AGLE" --include=*.py` returns only the four orchestrator/simulator wrapper classes listed in Section 1, none of which contain trading logic).

**What actually ran under the "AGLE 24/7 (Account B)" banner**: every attempt to activate the real Docker stack in this repository's traceable history either was never invoked or failed closed (no Docker available); the scripts that *did* run and place "trades" (`run_agle_account_b.py`, and the AGLE side of `run_separate_accounts_orchestrator.py`/`run_production_full.py`) are 100% `random.choice([-1,1])`, with **zero connection** to `core.strategy_registry`, `core.backtest`, `core.validation`, `core.decision_engine`, or `core.evidence_aggregator` — the very components that would make "AGLE" real. The "AI Analysis: enabled" line logged by `run_agle_account_b.py` corresponds to no analysis code anywhere between reading that config value and calling `random.random()`.

```
data source           → the real platform has one (core/data_manager.py + broker
                         adapters); the live AGLE path never calls it
    ↓
features                → exist for the 14 strategies/ implementations and for
                           FE-R2-002; AGLE itself defines none of its own
    ↓
model/learning component → NONE defined anywhere under the AGLE name specifically;
                            agents/research_agent.py is a real genetic-algorithm
                            strategy-research loop but has never produced an
                            AGLE-named or ML-001-named strategy (strategies/ai_generated/
                            contains only its own bootstrap __init__.py, confirmed by
                            git history: only the founding commit ever touched that
                            directory)
    ↓
signal generation         → random.choice([-1,1]) in the live path; NONE in the
                             (never-started) real platform path
    ↓
risk engine                → agents/risk_agent.py is real (Monte-Carlo VaR); never
                              invoked by the live AGLE path
    ↓
execution engine            → broker/simulator.py is real; never invoked by the live
                               AGLE path, which manipulates an in-memory dict
                               (self.positions) directly
    ↓
reconciliation                → NONE
    ↓
evidence generation             → NONE (no AggregatedEvidence ever constructed for AGLE)
    ↓
EVG                             → NEVER INVOKED
    ↓
governance authority             → NEVER INVOKED
```

`AGLE_REAL_STRATEGY_STATUS = SPEC_EXISTS_AT_INFRASTRUCTURE_LEVEL_ONLY (docker-compose.yml, six real services) — NO TRADING-STRATEGY-LEVEL SPECIFICATION EXISTS FOR "AGLE" AS A SIGNAL-GENERATING ALGORITHM; the platform it is meant to orchestrate contains real strategy/validation/governance infrastructure, but "AGLE" itself was never more than a deployment/monitoring label`

---

## 4. PHASE 4 — LIVE PATH CALL GRAPHS

### ML-001 (the account actually running, per `SEPARATE_ACCOUNTS_DEPLOYMENT_SUMMARY.md`)

```
run_ml_001_account_a.py [REAL file, live entrypoint]
  └─ load_broker_config()                          [REAL — reads config/ml_001_broker.yaml]
  └─ ML001AccountA.run()                            [REAL function, RANDOM behavior]
       └─ random.random() < 0.15                    [RANDOM]
       └─ random.choice([-1, 1])                    [RANDOM]
       └─ pnl_change = random.uniform(-0.3, 0.3)     [RANDOM]
       └─ core.ml_001_adapter.ML001Adapter           [UNREACHABLE — never imported by this file]
       └─ core.evidence_aggregator / decision_engine  [UNREACHABLE — never imported]
       └─ broker.simulator / any real execution path  [UNREACHABLE — never imported]

(separately, unreachable from the above)
ml_001_production_rollout.py [REAL file, NOT the one actually invoked per the account docs]
  └─ ProductionSystem._get_price()                   [STUB — hardcoded price + Gaussian noise]
  └─ ProductionSystem._execute_trade()                [STUB — P&L = signal × N(0.0001,0.00005)]
  └─ self.strategies[symbol].generate_signal(price)    [MISSING METHOD — AttributeError every tick]
       └─ core.ml_001_adapter.ML001Adapter              [REAL class, but has no generate_signal — MISSING]
```

### AGLE (the account actually running, per the same document)

```
run_agle_account_b.py [REAL file, live entrypoint]
  └─ load_broker_config()                          [REAL — reads config/agle_broker.yaml]
  └─ AGLE24AccountB.run()                            [REAL function, RANDOM behavior]
       └─ random.random() < 0.1                      [RANDOM]
       └─ random.choice([-1, 1])                      [RANDOM]
       └─ (no price fetch, no feature, no model, no EVG call anywhere in this function)

(the "real" path, never successfully reached in this repository's traceable history)
ml_001_agle_production_orchestrator.py
  └─ AGLEManager.activate_24_7()                      [REAL logic]
       └─ subprocess: docker --version                 [FAILS in this environment — "no Docker"]
       └─ → returns False, logs honest failure           [CORRECT, DISCLOSED FAIL-CLOSED]
       └─ (docker-compose up -d: api/worker/dashboard/
            redis/postgres/influxdb)                     [UNREACHABLE in this environment]
            └─ [inside worker, if it ran] core.strategy_registry → strategies/*.py
                 or core.ml_r2.* → core.decision_engine → core.evidence_aggregator
                 → broker execution                        [NEVER TRACED — never started;
                                                              see Phase 7 for what this
                                                              audit can and cannot say about it]
```

Every node marked `RANDOM` or `MISSING`/`STUB`/`UNREACHABLE` above was independently re-verified this audit via direct file read or `grep`, not assumed from either predecessor report.

---

## 5. PHASE 5 — SPECIFICATION VS IMPLEMENTATION MATRIX

| Component | Spec | Implementation | Status |
|---|---|---|---|
| ML-001 (original) asset/timeframe | `ML001HypothesisContract`: EURUSD/H1 | Matches — but nothing downstream uses it | MATCH (spec-only) |
| ML-001 (original) features | 5 named features | `core/indicators.py` has real momentum/RSI/ATR functions; `volatility_regime` has no formula anywhere under this contract; none are wired to `ML001Adapter` | PARTIAL / MISSING |
| ML-001 (original) model | "RandomForest" (prose/default string only) | Never instantiated as `RandomForestClassifier` or any concrete class, at any commit | MISSING |
| ML-001 (original) live signal | (none specified) | `random.choice([-1,1])`, undisclosed | RANDOM/MOCK |
| ML-001-R2 features | FE-R2-002, spec §4 | `core/features/fe_r2_001.py` — exact match, tested | MATCH |
| ML-001-R2 model | RF-R2-001, spec §6 hyperparameters | `RFR2Model` class matches hyperparameters exactly; no trained artifact | PARTIAL (class matches, artifact MISSING) |
| ML-001-R2 trading rules | spec §10 | `core/ml_r2/backtest_r2.py` — exact match, tested | MATCH |
| ML-001-R2 live wiring | (implicitly: eventually production) | Never connected to any broker account or live entrypoint | MISSING (by design at this stage — not a defect, a gate) |
| AGLE infrastructure | `docker-compose.yml`, 6 services | Files are real; never successfully started in this repository's traceable environment history | MATCH (definition) / UNKNOWN (runtime — never observed running) |
| AGLE trading strategy | (none — no spec exists) | `random.choice([-1,1])`, undisclosed, labeled "AI Analysis: enabled" | RANDOM/MOCK, CONTRADICTORY (label vs. content) |
| EVG (evidence_aggregator + decision_engine) | Documented thresholds (`DECISION-STAGING-PRODUCTION-REPORT.md`) | Real, implemented, tested (`tests/test_decision_integration.py`) | MATCH (as infrastructure) / NEVER INVOKED (for ML-001 or AGLE) |

---

## 6. PHASE 6 — ECONOMIC ARTIFACT PROVENANCE AUDIT

| Artifact | Generator | Source data | Reproducible? | Verdict |
|---|---|---|---|---|
| `reports/staging/staging_report_20260817_094317.json` (Sharpe 1.23) | Added in commit `428db6f`, whose own diff shows only a 2-line unrelated `core/evidence_aggregator.py` docstring/trial-count fix — no report-generation code in the diff | Commit message claims "43,848 EURUSD H1 bars (2020-2024)... synthetic data (same OHLCV structure) due to Alpha Vantage API 403 limit" — no synthetic-data-generation script committed alongside it either | NO | **NON-REPRODUCIBLE ECONOMIC CLAIM** |
| `reports/staging/batch/batch_staging_report_20260817_112458.json` (Sharpe 1.19335, EURUSD) | Commit `ad3326f`, zero `.py` files in the diff | Same claimed dataset; contradicts the figure above for the same nominal evaluation; all 5 symbols report identically 8,761 observations / 876 trades (statistically implausible for independent series, per `ML-001-STRATEGY-RECOVERY-FORENSIC-REPORT.md`, independently re-checked this audit's predecessor) | NO | **NON-REPRODUCIBLE ECONOMIC CLAIM** |
| `tests/test_staging_production.py::test_st_004_holdout_evaluation_works` (`sharpe=1.2, profit_factor=1.8`) | Literal Python constants typed directly into a `ValidationResultBuilder` call | None — test fixture, not derived from any computation | YES (as a test, trivially — but it reproduces a hardcoded number, not a strategy result) | **TEST FIXTURE, NOT AN ECONOMIC CLAIM** — was never offered as one, but is worth naming explicitly since its numbers superficially resemble the (non-reproducible) staging JSON figures |
| RSI-EURUSD-H1 validation (Sharpe −2.41, PF 0.60, PBO 1.0) | `core/validation.py::ValidationSuite` (real, re-queried live from `data/ea_factory.db` this audit and the predecessor audit) | Real backtest mechanics (`core/backtest.py::BacktestEngine`) over whatever OHLCV `core/data_manager.py` supplied at the time (provenance of *that specific* underlying price series was not re-traced in this report — flagged as an open item, not asserted either way) | Partially — the engine is real and re-runnable; the exact historical run that produced this row was not re-executed this audit | **GENUINE COMPUTED RESULT, but not one of the two audited strategies, and its own underlying data provenance is not fully re-verified here** |

None of the non-reproducible figures above (1.23, 1.19335, 1.2, 1.8) is used anywhere in this report, or the predecessor report, as evidence for anything. They are documented here only as provenance findings.

---

## 7. PHASE 7 — GOVERNANCE PATH / BYPASS ANALYSIS

**ML-001 (live path)**: `run_ml_001_account_a.py` reaches a simulated "broker fill" (an in-memory `self.positions[symbol] += signal` and `self.pnl` update) with **zero** intermediate calls to `core.evidence_aggregator`, `core.decision_engine`, or any risk-governance check beyond the account's own static config (`config/ml_001_broker.yaml` risk limits, which bound position count and daily loss but do not gate whether a trade should be *placed* in the first place). **GOVERNANCE BYPASS: CONFIRMED**, for the live path.

**AGLE (live path)**: identical structure — `run_agle_account_b.py` reaches its in-memory position dict with zero EVG calls. **GOVERNANCE BYPASS: CONFIRMED**, for the live path.

**AGLE (the never-started "real" Docker path)**: this audit cannot confirm or deny whether the `worker` container, had it started, would route strategy decisions through `core.decision_engine`/`core.evidence_aggregator` before reaching a broker — no evidence of that container ever running exists in this repository's logs, and its actual entrypoint/startup command was not traced to completion in this report (open item, Section 9). It is neither cleared nor confirmed as a bypass; it is **UNTRACED**, and should not be assumed safe merely because it never ran.

**Important scope note**: none of the four production entrypoints inspected place a **real broker order** — all "fills" are in-memory dictionary updates, not calls to `broker/xm_websocket.py`, `broker/simulator.py`, or any live trading API. So while GOVERNANCE BYPASS is confirmed for the *decision* path (no EVG gate), no evidence was found that a real, external broker order was ever transmitted for either strategy — the risk realized so far is "an ungoverned decision was logged as if it were a trade," not (as far as this repository's artifacts show) "real capital moved."

---

## 8. PHASE 8 — REQUIRED REPAIR PLAN (not implemented here)

**A. Existing real components that can be wired (no new implementation needed):**
- `core/features/fe_r2_001.py`, `core/ml_r2/backtest_r2.py`, `core/ml_r2/simulator_r2.py` — a complete, tested position/risk/execution mechanics layer for ML-001-R2, ready to accept a real probability the moment one exists.
- `core/evidence_aggregator.py` + `core/decision_engine.py` — real EVG, ready to accept a real `AggregatedEvidence` for either strategy.
- `core/backtest.py` + `core/validation.py` + `core/strategy_registry.py` + `strategies/*.py` — a real, working, general-purpose strategy validation engine, already proven functional (RSI result), currently only ever pointed at RSI/EURUSD/H1.
- `agents/risk_agent.py` (Monte-Carlo VaR) and `broker/simulator.py` (execution simulator with slippage) — real, usable risk/execution components.
- `docker-compose.yml` + Dockerfiles — real platform definition, if a Docker-capable deployment target is used instead of this remote session.

**B. Missing components that must be implemented:**
- A trained, checksummed RF-R2-001 model artifact (requires real EURUSD/GBPUSD H1 data — currently blocked, per `ML-001-R2-ECONOMIC-VALIDATION-REPORT.md`).
- A `volatility_regime` formula under the *original* ML-001 contract (or, more honestly, a decision to retire the original `ML001HypothesisContract`/`ML001Adapter` shell in favor of ML-001-R2's already-complete feature spec, rather than maintaining two parallel, differently-complete "ML-001" definitions).
- An actual AGLE trading-strategy specification, if AGLE is meant to be more than a deployment/monitoring label for the whole platform — currently none exists to implement against.
- A single, disclosed, code-level "DEMO MODE" flag and matching operator-facing log banner for any random/simulated fallback, so a script never claims "PRODUCTION" while running a coin flip.

**C. Artifacts that must be regenerated (with a committed, re-runnable generator):**
- Any Sharpe/PF/DD/PBO figure intended to represent ML-001 or AGLE — the two existing staging JSONs are non-reproducible and must not be reused, only regenerated from scratch by real code once B is addressed.

**D. Tests that must be added:**
- A test asserting `run_ml_001_account_a.py`/`run_agle_account_b.py` (or their eventual real replacements) actually call `core.evidence_aggregator`/`core.decision_engine` before any position-changing action — this audit found no such test exists for any of the five entrypoints (`grep -rl` against `tests/` returned nothing).
- A test asserting no live entrypoint script contains `random.random`/`random.choice`/`np.random.choice` in a signal-generation role (a simple, cheap regression guard against this exact class of defect recurring).

**E. Economic validation that must happen after repair (not now):**
- Once a real model/strategy exists, wired end-to-end, with real market data and no EVG bypass — a full re-run of the economic-validation process this repository already has infrastructure for (`AggregatedEvidence.is_authorizable()`, walk-forward, holdout) is required before any `PASS`/`EDGE PROVEN` verdict can be considered. Nothing in this report shortens that path.

---

## 9. HARD STOP CONDITIONS — APPLIED

- Neither strategy has a real signal-generation implementation in its live path → **ECONOMIC VALIDATION STOPPED** for both, confirmed.
- ML-001-R2's model artifact is required and missing → **MODEL VALIDATION STOPPED** for ML-001-R2 specifically.
- Market data provenance is missing for economic validation purposes (no licensed vendor; the one real backtest result, RSI, has unre-traced upstream data provenance) → **ECONOMIC VALIDATION STOPPED**.
- P&L for both live strategies is drawn from `random.uniform`/`np.random.normal`, not derived from real execution or a deterministic market simulator → **ECONOMIC VALIDATION STOPPED**, independently of the above.
- Governance can be bypassed on the confirmed live paths for both strategies → **PRODUCTION MARKED BLOCKED**.

**Open item, explicitly not resolved by this report**: whether the AGLE Docker `worker` service, if actually started on a Docker-capable host, would itself bypass governance. This report does not clear it — it is untraced, not safe-by-default.

---

## 10. WHAT CAN AND CANNOT CURRENTLY BE ECONOMICALLY VALIDATED

**Cannot be validated**: ML-001 (original) — no real feature computation, no model, no live signal beyond a coin flip. AGLE — no trading-strategy specification exists to validate in the first place; only a monitoring/deployment label exists. ML-001-R2 — the *mechanics* are validated (tested end-to-end this session, Python-side, with a golden dataset), but the *strategy itself* cannot be economically validated without (a) a trained model artifact and (b) real market data, both currently absent.

**Can currently be validated, if someone chooses to run it**: any of the 14 strategies in `strategies/*.py` through the real `core.backtest`/`core.validation` engine — this is the one path in the repository that is fully real, fully wired, and has already produced at least one genuine (if failing) result.

---

## FINAL STATUS

```
ML-001_REAL_STRATEGY_STATUS  = SPEC_EXISTS_IMPLEMENTATION_MISSING (original ML-001 contract);
                                a separate, differently-identified implementation
                                (ML-001-R2) IMPLEMENTATION_EXISTS_NOT_WIRED to any
                                broker account or the "ML-001" live path
AGLE_REAL_STRATEGY_STATUS    = NO_STRATEGY_SPECIFICATION_EXISTS; AGLE is an
                                infrastructure/deployment label (docker-compose
                                service stack) with no defined trading logic of
                                its own; the live path is an undisclosed random
                                fallback

ML-001_EDGE_STATUS = NOT_PROVEN
AGLE_EDGE_STATUS   = NOT_PROVEN

ECONOMIC_VALIDATION = BLOCKED_PENDING_REAL_STRATEGY

PRODUCTION = BLOCKED
```

No PASS claim is made. No edge claim is made. No optimization was performed. No market data, model artifact, or economic result was fabricated.

---

## REGRESSION STATUS (not economic evidence)

`python3 -m pytest -q` (full repository suite, run after this audit's investigation, no code changed): **533 passed, 0 failed, 0 skipped.** This confirms the repository's existing test suite is unaffected by this report's (read-only) investigation. It says nothing about ML-001's or AGLE's economic validity — no test in this suite exercises either strategy's live entrypoint (`grep -rl` against `tests/` for all five entrypoint files returned zero matches, confirmed this audit).
