# ML-001-R2 CLEAN REBUILD SPECIFICATION

**Date**: August 17, 2026
**Phase**: SPECIFICATION ONLY — no implementation, no training, no backtest, no Pine, no production changes
**Status of this document**: RESEARCH_ONLY / NOT AUTHORIZED
**Relationship to old ML-001**: **NONE.** This is a new strategy built from zero evidentiary standing. It inherits *names and concepts* from old ML-001 documentation as design inputs only — never as proof that anything worked before.

---

## 1. WHY OLD ML-001 WAS INVALIDATED

Per `ML-001-EXECUTION-AUTHENTICITY-AUDIT.md`, `ML-001-STRATEGY-RECOVERY-FORENSIC-REPORT.md`, and `ML-001-RECOVERY-REVALIDATION-REPORT.md` (verdict: `NO_REPRODUCIBLE_STRATEGY_FOUND`):

- `ML001Adapter` never had a `generate_signal()` method at any point in its history; the production runner's call to it raises `AttributeError` on every tick (proven via live introspection).
- The only code that ever executed under the "ML-001" name used `random.choice([-1, 1])`, confirmed by live runtime logs with zero references to any model or feature.
- No trained model artifact, training script, feature-to-model wiring, or dataset ever existed in git history (full history searched: 20 commits, zero deletions, zero renames, zero dangling git objects).
- No script that generated the published Sharpe/PF/PBO figures was ever committed; the two committed reports for the "same" EURUSD holdout evaluation disagree with each other (1.23 vs 1.19 Sharpe).
- `volatility_regime` had no implementation, ever, at any commit.

**Every historical ML-001 performance claim is therefore inadmissible as evidence for this rebuild.** Nothing below relies on it.

---

## 2. NEW STRATEGY IDENTITY

| Field | Value |
|---|---|
| `strategy_id` | `ML-001-R2` |
| `strategy_version` | `1.0.0` |
| `model_version` | `RF-R2-001` |
| `feature_version` | `FE-R2-001` |
| `data_version` | `DATA-R2-001` *(checksum to be appended once real data is acquired — see §6 Open Item)* |
| `research_version` | `RESEARCH-R2-001` |

**Immutability rule**: any change to feature formulas, model hyperparameters, target definition, or trading rules requires a new version suffix (e.g., `FE-R2-002`, `RF-R2-002`). No silent in-place edits to a version once it has produced any recorded prediction or evaluation.

`ML-001` (unversioned) and `ML-001 v1.0` are retired identifiers and MUST NOT be reused. `ML-001-R2` never inherits the old identity's authorization state — it starts at `RESEARCH_ONLY`.

---

## 3. DESIGN INPUTS INHERITED FROM OLD RESEARCH

| Concept | Classification | Note |
|---|---|---|
| EURUSD | DESIGN_INPUT_ONLY | Reasonable instrument choice; carries no evidentiary weight from old reports |
| GBPUSD | DESIGN_INPUT_ONLY | Same |
| H1 timeframe | DESIGN_INPUT_ONLY | Same |
| `momentum_5` (name) | DESIGN_INPUT_ONLY | Formula redefined from scratch in §4 — never actually wired to old ML-001, so nothing is "reused," only the name and lookback concept |
| `momentum_20` (name) | DESIGN_INPUT_ONLY | Same |
| `rsi_14` (name) | DESIGN_INPUT_ONLY | Same |
| `atr_14` (name) | DESIGN_INPUT_ONLY | Same |
| `volatility_regime` (name) | DESIGN_INPUT_ONLY — **zero historical substance** | Unlike the four features above, this name was never backed by *any* formula at any point in history. It is 100% new construction wearing an old label. Flagged distinctly so it is never mistaken for a recovered definition. |
| Random Forest (as candidate algorithm) | DESIGN_INPUT_ONLY | Reasonable forward-looking candidate; never proven to have executed historically. Formally specified fresh in §5. |
| 1-bar prediction horizon | DESIGN_INPUT_ONLY | Concept retained; label mechanics redefined in §4 |
| Candle-close signal / next-bar execution timing | DESIGN_INPUT_ONLY | Previously only a declared string in a contract dataclass, never enforced by any scheduler or event handler. In R2 this becomes an actually-built, actually-enforced invariant (§10). |

**Classification key applied**: none of the above reach `PROVEN_HISTORICAL_EXECUTION` — nothing in old ML-001 was ever proven to execute. None are `REJECTED` as *concepts* (they are all reasonable starting points). None are `AMBIGUOUS`.

### Explicitly REJECTED historical numeric claims (not carried forward under any circumstance)

| Old value | Status |
|---|---|
| Target threshold `0.001` | REJECTED — arbitrary, unproven, never applied by any code |
| `n_estimators: 100` | REJECTED — sourced from an unrelated `TrialLedger` test fixture, not a trained model |
| 7.2% capital allocation (EURUSD/GBPUSD) | REJECTED — computed from unproven/contradicted metrics |
| Sharpe 1.19/1.23 (EURUSD), 1.13 (GBPUSD), PF, DD, PBO figures | REJECTED — internally contradictory, no traceable generator |
| "43,848 bars," "8,761 observations," "876 trades" | REJECTED — appear only in unsourced output files, not derivable from any committed data or code |

---

## 4. EXACT FEATURE DEFINITIONS (`FE-R2-001`)

Canonical implementation: a single new module (to be created only at implementation time, not now) that research, backtest, production inference, and the Pine exporter (§11) all import identically. No feature may be reimplemented a second time anywhere in the system.

Fixed feature vector order (index 0–4):

### [0] `momentum_5`
- **Formula**: `momentum_5[t] = (close[t] - close[t-5]) / close[t-5]`
- **Lookback**: 5 completed H1 bars
- **Price field**: `close`
- **Warmup**: 5 bars (undefined/NaN before bar index 5 of the series)
- **NaN handling**: rows containing NaN in any feature are excluded from training and labeling; in production/live inference, no signal is emitted until warmup is satisfied for all 5 features
- **Normalization/scaling**: none additional — already a unitless percentage return, appropriate for a tree-based model
- **Timestamp semantics**: computed using the completed bar at time `t` (bar close), never a forming/incomplete bar

### [1] `momentum_20`
- Identical specification to `momentum_5` with lookback 20: `momentum_20[t] = (close[t] - close[t-20]) / close[t-20]`
- Warmup: 20 bars

### [2] `rsi_14`
- **Formula**: Wilder's RSI. `avg_gain`/`avg_loss` seeded as the simple mean of the first 14 gains/losses, then propagated via Wilder smoothing `avg[t] = (avg[t-1] × 13 + value[t]) / 14` (equivalent to `ewm(alpha=1/14, adjust=False)`); `RS = avg_gain / avg_loss`; `RSI = 100 − 100 / (1 + RS)`
- **Lookback**: 14-period smoothing constant
- **Price field**: `close`
- **Warmup**: minimum 14 bars for a defined value; **100-bar burn-in required** before a value is used for training or live inference, to dilute Wilder seed-dependency (standard practice — the seed average biases early values)
- **NaN handling**: as above
- **Normalization/scaling**: none — native `[0, 100]` range is acceptable for a tree model
- **Reference implementation**: functionally equivalent to `core/indicators.py` lines 62–82 (existing, tested, working code in this repository) — reuse that implementation directly rather than re-deriving it, subject to a fresh unit test confirming output matches this specification exactly

### [3] `atr_14`
- **Formula**: `TR[t] = max(high[t]-low[t], |high[t]-close[t-1]|, |low[t]-close[t-1]|)`; `ATR = ` Wilder-smoothed `TR` over 14 periods (same smoothing method as RSI)
- **Warmup**: 14 bars minimum defined, 100-bar burn-in required before use (same rationale as `rsi_14`)
- **Reference implementation**: functionally equivalent to `core/indicators.py` lines 111–123

### [4] `volatility_regime` — **NEWLY DEFINED, NO HISTORICAL PRECEDENT**
- **Formula**: ordinal 3-class regime label derived from `atr_14`'s position in its own trailing distribution:
  - `p33`, `p67` = 33rd and 67th percentile of `atr_14` over the trailing 500 bars (causal — computed using only bars up to and including `t`, expanding until 500 bars are available, then a fixed rolling window)
  - `volatility_regime[t] = 0` (LOW) if `atr_14[t] < p33`
  - `volatility_regime[t] = 1` (NORMAL) if `p33 ≤ atr_14[t] ≤ p67`
  - `volatility_regime[t] = 2` (HIGH) if `atr_14[t] > p67`
- **Lookback**: 500-bar trailing percentile window, computed on top of `atr_14` (which itself requires its own 100-bar burn-in)
- **Warmup**: 500 + 100 = 600 bars before the first valid value
- **Encoding**: single ordinal integer feature `{0, 1, 2}` (not one-hot) — chosen for simplicity; tree-based splits handle ordinal thresholds natively. This is an explicit new design decision, documented here so it is never mistaken for a recovered historical definition.
- **NaN handling / normalization**: as above; no further scaling (already a bounded ordinal)

### Vector assembly
`feature_vector[t] = [momentum_5[t], momentum_20[t], rsi_14[t], atr_14[t], volatility_regime[t]]`, fixed order, versioned as `FE-R2-001`. Any reordering or addition/removal of features requires a new `feature_version`.

---

## 5. EXACT TARGET DEFINITION

**Label**: strict binary, no neutral/deadband class, for full determinism and to avoid inheriting an arbitrary threshold from old (rejected) `0.001`.

```
label[t] = 1  if close[t+1] > close[t]
label[t] = 0  if close[t+1] <= close[t]
```

- **Direction**: predicts probability of next-bar close being strictly higher than current close ("up" vs. "not up")
- **Horizon**: exactly 1 bar (H1)
- **Threshold**: none — direct comparison, no epsilon. (A deadband/threshold variant is noted as an open research question in §17, not adopted for v1.0.0.)
- **Neutral outcomes**: none by construction — `close[t+1] == close[t]` maps to class 0 by the `<=` in the formula, defined explicitly to avoid an undefined third case
- **Timestamp alignment**: `label[t]` requires `close[t+1]`, which is only known after bar `t+1` closes. It is information-available at `t+1`, not at `t`. Enforced identically to the existing `IA-001` information-audit pattern: any code path that can see `label[t]` before `t+1` closes is a leakage violation and must raise, not silently proceed.

---

## 6. MODEL SPECIFICATION (`RF-R2-001`)

Fully specified — no unspecified defaults:

```python
sklearn.ensemble.RandomForestClassifier(
    n_estimators=300,
    max_depth=6,
    min_samples_split=50,
    min_samples_leaf=25,
    max_features="sqrt",
    class_weight="balanced",
    criterion="gini",
    bootstrap=True,
    random_state=42,
)
```

- **Probability interpretation**: `predict_proba(features)[:, 1]` = estimated probability of `label = 1` (next bar closes higher). Signal thresholds applied to this probability are defined in §9.
- **Determinism**: fixed `random_state=42`; training on identical data + identical scikit-learn version must reproduce an identical model bit-for-bit (verified by artifact checksum, not merely "similar" metrics).
- **Required training outputs** (all committed together, none optional):
  1. Model artifact (`.joblib`)
  2. Model metadata JSON (algorithm, hyperparameters, `sklearn` version, training timestamp, `feature_version`, `data_version`)
  3. Training manifest (exact date range of training data, row count, class balance)
  4. Feature schema JSON (the §4 specification, machine-readable)
  5. SHA256 checksum of the model artifact, recorded in the manifest

**Note on these hyperparameters**: this is the *initial candidate specification* for `RF-R2-001` v1.0.0. Nothing here is tuned yet — hyperparameter search, if performed, happens only inside the DEVELOPMENT period during the governance walk-forward phase (§8/§12) and must produce a new `model_version` if changed, never a silent edit to `RF-R2-001`.

---

## 7. DATA SPECIFICATION

| Field | Value |
|---|---|
| Symbols | EURUSD, GBPUSD |
| Timeframe | H1 |
| Source | **OPEN — see §17.** Must be a real, licensed market-data vendor. The old synthetic dataset is explicitly forbidden as a substitute. |
| Timezone | UTC — all timestamps normalized before any feature computation |
| OHLCV schema | `timestamp (UTC, ISO8601), open, high, low, close, volume` (tick volume if true traded volume is unavailable for FX — flagged as such in the manifest, not silently presented as real volume) |
| Missing-bar policy | Weekday gaps >1 bar during normal trading hours are treated as a **data-quality violation** requiring investigation — never silently forward-filled or interpolated |
| Duplicate policy | Duplicate timestamps rejected; first occurrence kept, conflict logged |
| Weekend policy | FX market closed Fri 22:00 UTC – Sun 22:00 UTC; this window is excluded from continuity checks, not treated as missing data |
| Spread assumption | Realistic historical median spread per pair, applied as a cost in backtest — exact figures pending real broker/vendor data (§17) |
| Slippage assumption | Fixed conservative buffer of 0.2 pip applied to every simulated fill (deterministic, may be revised via version bump) |
| Provenance | Every dataset used must record vendor name, license reference, download timestamp, and SHA256 checksum in the `DATA-R2-001` manifest before any feature computation begins |

---

## 8. TEMPORAL VALIDATION PROTOCOL

Structure preserved from the (architecturally sound, if never actually enforced) old design, but boundaries are defined **relative to whatever real data is actually acquired**, not pre-assumed as 2020–2024:

- **DEVELOPMENT**: first 60% of the acquired history, chronologically
- **VALIDATION**: next 20%, chronologically, immediately following DEVELOPMENT
- **PURE_HOLDOUT**: final 20%, chronologically last

**Requirements** (all mandatory, all must be mechanically enforced, not merely documented):
1. No leakage — reuse the existing `core/provenance_enforcement.py` `ProvenanceEnforcer` (proven, working governance code already in this repository) to gate every data access by declared state (DEVELOPMENT/VALIDATION/PURE_HOLDOUT)
2. No random train/test split — strictly chronological only
3. No access to PURE_HOLDOUT data during model selection, hyperparameter search, or feature iteration, for any reason
4. PURE_HOLDOUT is opened **exactly once**, after the model, features, and hyperparameters are fully frozen
5. Once set, the exact split boundaries (dates, row indices) are computed, hashed, and frozen into the `DATA-R2-001` manifest — immutable thereafter

---

## 9. WALK-FORWARD PROTOCOL

- **Initial training window**: trailing 12 months of DEVELOPMENT data
- **Retraining frequency**: monthly, rolling forward on a 24-month trailing training window, evaluated one month forward at a time — only within the VALIDATION period, generating genuinely out-of-sample predictions
- **Feature availability**: features at time `t` computed using only bars with timestamp `≤ t`
- **Prediction timestamp**: computed at H1 bar close (`t`)
- **Execution timestamp**: next bar open (`t+1`) — see §10 for the enforced invariant
- **Model replacement semantics**: each walk-forward window trains a fresh model instance on its own trailing window (no incremental/online updates); every OOS prediction is tagged with the exact `model_version` + window index that produced it
- **Reference implementation**: `core/oos_wfa_engine.py`'s `WFAPredictionEngine` — this is real, working, generic infrastructure already in the repository. It has never been wired to a concrete model class; for R2 it is wired, for the first time, to `RF-R2-001` and `FE-R2-001`. This reuse is legitimate because the engine's *mechanics* (window generation, no-lookahead enforcement, immutable `OOSPredictionBatch` records) are independently proven — it was only ever missing a real model to run.

Every OOS prediction produced under this protocol must be demonstrably out-of-sample: its `test_data_state` provenance tag, checked by `ProvenanceEnforcer`, must show it was generated using a model trained strictly on data preceding the prediction's window.

---

## 10. TRADING RULES

Let `p = predict_proba(feature_vector[t])[1]` (model's probability estimate that the next bar closes higher).

| Rule | Specification |
|---|---|
| **LONG condition** | `p > 0.55` AND no existing open position in this symbol |
| **SHORT condition** | `p < 0.45` AND no existing open position in this symbol |
| **FLAT condition** | `0.45 ≤ p ≤ 0.55` — no new entry |
| **Position sizing** | Fixed-fractional, risk-based: `size = (account_equity × 0.02) / (stop_loss_distance_pips × pip_value)` — i.e., risk exactly 2% of equity per trade, sized from the stop-loss distance below. This replaces the old, unproven 7.2%-of-capital figure entirely. |
| **Maximum positions** | 1 open position per symbol at a time; no pyramiding/scaling-in for v1.0.0 |
| **Stop loss** | `1.5 × atr_14[entry]` from entry price, fixed at entry time, not trailed in v1.0.0 |
| **Take profit** | `2.5 × atr_14[entry]` from entry price (fixed R:R ≈ 1:1.67) |
| **Signal reversal** | If the opposite-direction condition fires while a position is open, close the current position at the next bar open; do not re-enter within the same signal cycle (avoids same-bar whipsaw); a new entry is only evaluated on the following bar's signal |
| **Maximum holding period** | 24 H1 bars (1 trading day); force-flat at next bar open if reached, regardless of P&L |
| **Exit priority when multiple conditions trigger simultaneously** | Stop loss > Take profit > Max holding period > Signal reversal (evaluated in this fixed order each bar) |
| **Transaction cost** | Commission per lot per round turn — placeholder deterministic constant pending final broker selection (§17); modeled explicitly in backtest, never omitted |
| **Spread / slippage** | Per §7 |

All numeric constants above (`0.55`/`0.45` thresholds, `1.5`/`2.5` ATR multiples, `24`-bar max hold, `2%` risk) are **new, explicit R2 v1.0.0 design decisions** — not inherited from old ML-001, which never had trading rules of any kind (its production code never got past the missing `generate_signal()` call). Any change to these constants requires a `strategy_version` bump.

---

## 11. RISK RULES

Portfolio-level, layered on top of §10's per-trade rules:

- Maximum total allocation across `ML-001-R2` positions: capped at a conservative fraction of account equity, to be finalized during Phase 12 risk-governance review (reuse existing, working `core/risk_governance.py` `RiskGovernanceConfig` — proven infrastructure, config values TBD per-account, not hardcoded here)
- Maximum concurrent positions across both symbols: 2 (one per symbol, per §10)
- Daily loss limit and max-drawdown circuit breaker: reuse existing `RiskGovernanceConfig`/`HealthMonitor` pattern from old infrastructure (the *mechanism* is sound and reusable even though it was never reached at runtime due to the missing `generate_signal()` bug) — thresholds to be set during Phase 12, not invented here as arbitrary numbers
- No martingale, no position-size scaling on losses, no averaging down — explicitly disallowed

---

## 12. RESEARCH / PRODUCTION PARITY

Three formal invariants, each requiring a real enforcement mechanism (not documentation-only, as the old contract's timing strings were):

### FEATURE_PARITY
`Python research feature calculation == backtest feature calculation == production inference feature calculation`
Enforced by: a single canonical feature module, imported identically by all three call sites, with a shared `FE-R2-001` schema hash checked at each entry point. No second implementation is permitted to exist anywhere, including in a future Pine exporter (§13) — Pine code must be *generated from*, not independently reimplement, this canonical definition.

### SIGNAL_PARITY
`Research inference == production inference`
Enforced by: one shared inference function (load model → compute `predict_proba` → apply §10 thresholds) used identically by the backtest engine and the live/paper-trading runner. Two separate implementations (as existed for old ML-001's crashed production path vs. its random-signal simulator) is the exact failure mode this invariant exists to prevent.

### TIMING_PARITY
`Signal computed at candle close T → execution at candle open T+1, with no lookahead`
Enforced by: a genuine event-driven bar-close handler — not a `sleep(1)` polling loop (the pattern used by both broken old runners). The handler must reject any feature or signal computation that references a bar not yet closed.

---

## 13. PINE COMPATIBILITY ARCHITECTURE

**No Pine Script is written in this phase.** This section defines the architecture only, per the mandatory stop gate.

**Constraint acknowledged**: Pine v6 cannot load a serialized scikit-learn artifact; there is no native Pine equivalent to a `RandomForestClassifier`.

**Chosen approach: B — exported tree-structure translation.**

- Rationale for rejecting the alternatives:
  - **(A) Pine-native deterministic model representation** — no native RF equivalent exists in Pine; not applicable without effectively becoming (B) or (C).
  - **(C) Replace Random Forest with a Pine-compatible model** — explicitly forbidden by this spec's governing rule ("Do not silently replace the model"); would change the strategy's decision function and identity, requiring a new `model_version` and full revalidation, defeating the purpose of parity.
- **(B)** is selected: an automated, auditable exporter script translates the *trained* `RF-R2-001` artifact's tree structure into generated Pine nested-conditional code, deterministically, tree-by-tree. The exporter is not written now — only its architectural role is fixed here.

**Known downstream constraint this creates on §6**: `n_estimators=300` at `max_depth=6` may exceed Pine's script-size budget once exported. Two resolutions are available and neither is decided here (deferred to implementation-time engineering, not a specification gap):
  (a) cap the *exported* model to a smaller `n_estimators` (e.g., ≤150) as a documented, versioned deviation between the research model and the deployed Pine model, with the size-reduced variant re-validated on its own before deployment, or
  (b) accept that Pine deployment is not pursued if no size-feasible reduction preserves acceptable fidelity to the full model's decision boundary — in which case `ML-001-R2` would remain Python/production-only, not a specification failure.

**Pine conversion remains BLOCKED** until `ML-001-R2` passes every gate in §14, independent of this architecture being defined.

---

## 14. GOVERNANCE GATES

`ML-001-R2` starts at `RESEARCH_ONLY` and must pass, in order, before any production authorization is possible:

| # | Gate | Status |
|---|---|---|
| 1 | Data audit (provenance, checksum, continuity per §7) | NOT_STARTED |
| 2 | Feature leakage audit (IA-001-style, applied to `FE-R2-001`) | NOT_STARTED |
| 3 | Model audit (artifact determinism, checksum, hyperparameter record) | NOT_STARTED |
| 4 | Walk-forward validation (§9) | NOT_STARTED |
| 5 | Pure holdout evaluation (opened exactly once, §8) | NOT_STARTED |
| 6 | Economic validation gate (Sharpe/PF/DD/PBO thresholds — to be met by a real, reproducible computation, not asserted) | NOT_STARTED |
| 7 | Evidence aggregation (`AggregatedEvidence`, existing reusable infrastructure) | NOT_STARTED |
| 8 | Decision governance (`DecisionEngine` AUTHORIZE/REJECT/HOLD/OBSERVE) | NOT_STARTED |
| 9 | Paper trading | NOT_STARTED |
| 10 | Production readiness review | NOT_STARTED |

**No production authorization occurs during, or as a byproduct of, this specification phase.**

---

## 15. REPRODUCIBILITY REQUIREMENTS

- Model artifact must be bit-for-bit reproducible from (data checksum + `FE-R2-001` code + `RF-R2-001` hyperparameters + `random_state`)
- Every OOS prediction batch must carry immutable provenance (window, model version, feature version, training/test data state) — reuse `OOSPredictionBatch`
- Every validation report must be produced by a **committed, auditable script** — the single most important process fix relative to old ML-001, where no such script was ever committed for any published metric
- Running the full pipeline twice on identical inputs must produce identical outputs — this must be demonstrated, not assumed, before any gate in §14 is considered passed
- All manifests (data, feature schema, model metadata, training) are committed to version control alongside the code that produced them — never as orphaned output files with no traceable generator (the exact failure mode identified in the old ML-001 recovery reports)

---

## 16. ARTIFACT MANIFEST (required, once implementation begins)

| Artifact | Path convention (proposed) |
|---|---|
| Data manifest | `data/ml_001_r2/DATA-R2-001_manifest.json` |
| Feature schema | `core/features/FE-R2-001_schema.json` |
| Feature implementation | `core/features/fe_r2_001.py` (single canonical module, §4/§12) |
| Model artifact | `models_ml/RF-R2-001/model.joblib` |
| Model metadata | `models_ml/RF-R2-001/metadata.json` |
| Training manifest | `models_ml/RF-R2-001/training_manifest.json` |
| OOS prediction batches | `reports/ml_001_r2/oos_predictions/` |
| Validation report + generator script (committed together) | `reports/ml_001_r2/validation/` + `scripts/ml_001_r2/generate_validation_report.py` |

None of these paths or files exist yet. This table is a naming convention for implementation phase, not a claim that implementation has occurred.

---

## 17. OPEN QUESTIONS

| # | Question | Blocks spec completeness? |
|---|---|---|
| 1 | Real market-data vendor/source for EURUSD & GBPUSD H1 (licensing, API access) | No — the data *protocol* (§7) is fully specified; vendor selection is a procurement action item, not a design ambiguity |
| 2 | Exact spread/commission figures (depends on final broker/vendor choice) | No — modeled with a documented placeholder constant until a broker is selected; must be finalized before any backtest is run |
| 3 | Whether a deadband/threshold variant of the target (§5) should be researched as an alternative to the strict binary label | No — v1.0.0 uses the strict binary label; deadband is a future `label_version` research question, not a blocker |
| 4 | Pine export size/fidelity trade-off (§13) | No — Pine conversion is already blocked pending full validation regardless of this question's resolution |
| 5 | Final portfolio-level risk thresholds (§11) | No — mechanism is reused from existing, proven `RiskGovernanceConfig`; specific numeric thresholds are a Phase-12 governance decision, not a strategy-design ambiguity |

**None of the open questions leave any required trading rule, feature formula, target definition, or model specification non-deterministic.** Each is either a procurement/business action item or an explicitly deferred future-research variant.

---

## 18. EXPLICIT NON-GOALS

- This document does not authorize training, backtesting, paper trading, or production deployment of anything.
- This document does not restore, reference as evidence, or extend any credibility to old ML-001's authorization, performance claims, or "production ready" status.
- This document does not produce Pine Script.
- This document does not modify any existing production code, historical report, or database record.
- This document is not itself a validation — `ML-001-R2` earns every governance gate in §14 from zero, exactly like any brand-new hypothesis would.

---

## FINAL DECISION

### **READY_FOR_IMPLEMENTATION**

Justification: every feature formula, the target definition, the model specification, the temporal/walk-forward protocol, all trading rules, and all parity invariants are fully deterministic and require no unresolved design choice to begin implementation (§4–§10, §12). The five items in §17 are external procurement or explicitly-deferred research questions, not gaps in the specification itself — none of them prevent writing the canonical feature module, the label-construction code, the model-training script, or the trading-rule engine exactly as specified. Implementation may begin with data-vendor selection as its first concrete action item; no code, model, or Pine artifact may be produced beyond that point without passing the governance gates in §14, and production authorization remains explicitly out of scope until then.

---

**SPECIFICATION PHASE COMPLETE — NO IMPLEMENTATION, NO TRAINING, NO BACKTEST, NO PINE SCRIPT, NO PRODUCTION CHANGES**
