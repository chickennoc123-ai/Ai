# ML-001 / STRAT-000001 — Failure Forensic Report

**Date**: August 18, 2026
**Candidate**: `STRAT-000001` (ML-001-R2 / RF-R2-001), state `REJECTED` (see `reports/factory/strategy_registry.json`)
**Purpose of this document**: explain, with evidence, *why* STRAT-000001 failed its walk-forward evaluation — not to optimize, retune, or rescue it. No hyperparameter, feature, target, or cost-model change was made anywhere in the course of producing this analysis. All numbers below are computed directly from the already-committed real-data artifacts (`data/csv/{EURUSD,GBPUSD}_H1.csv`, `models/ml_r2/RF-R2-001_*_canonical.*`, `reports/ml_r2_real_data/WALKFORWARD_{EURUSD,GBPUSD}.json`) plus new, additive read-only analysis scripts whose outputs are saved alongside this report (`FORENSIC_SIGNAL_ANALYSIS.json`, `COST_SENSITIVITY_CANONICAL.json`, `FEATURE_IMPORTANCE_STABILITY_SAMPLE.json`).

**Headline finding**: the model's predicted probabilities carry essentially no information about the sign or magnitude of the next bar's return. This is not a training bug, a mis-specified target, an unstable feature set, or a broken execution engine — every one of those was checked and ruled out below. The evidence is consistent with a single root cause: **the five FE-R2-001 features do not contain an exploitable edge for 1-bar-ahead EURUSD/GBPUSD H1 direction**, at least not one this model class can extract, and transaction costs then convert an already-flat pre-cost result into a small reliable loss.

---

## A. Raw signal quality — pre-cost relationship with future returns

Computed on the canonical model's genuinely out-of-sample VALIDATION-period predictions (`RF-R2-001_{SYMBOL}_canonical`, trained on DEVELOPMENT only; PURE_HOLDOUT never touched):

| Symbol | n | IC (Pearson) | p-value | IC (Spearman) | p-value | Directional accuracy |
|---|---|---|---|---|---|---|
| EURUSD | 11,520 | 0.0146 | 0.117 | 0.0302 | 0.0012 | 51.83% |
| GBPUSD | 11,520 | −0.0021 | 0.826 | 0.0170 | 0.068 | 51.25% |

An Information Coefficient this close to zero — even where the Spearman variant is nominally statistically significant thanks to the large sample (n=11,520), the *effect size* is what matters economically, and 0.014–0.030 is in the range conventionally treated as "no usable signal" in quantitative forecasting (IC > ~0.05–0.10 is the usual minimum bar for a tradeable single-factor signal). Directional accuracy of 51.2–51.8% is barely above the 50% coin-flip baseline and far below what would be needed to overcome realistic transaction costs on a 1-bar-hold strategy.

**Prediction distribution** (both symbols): the model's `P(label=1)` output clusters tightly around 0.50 — std ≈ 0.028–00.030, and **95.6% (EURUSD) / 94.7% (GBPUSD)** of all predictions fall in the "flat zone" [0.45, 0.55]. Only 1.4%/2.2% of bars produce a probability above 0.55. This is itself evidence, independent of the IC calculation: the model rarely expresses confident conviction, consistent with it having found only very weak, noisy structure to fit.

---

## B. Target construction audit

Already performed pre-training, not re-litigated here in depth — see `ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md`. Reaffirmed relevant to this failure:

- Label is `sign(close[t+1] − close[t])`, reconstructed provably from `close.shift(-1)` alone (`build_training_set()`'s internal `assert_no_leakage()` passed on the full real series).
- Class balance is healthy and not a source of the failure: EURUSD training set {0: 17,041, 1: 16,918} — within 0.4% of 50/50. A degenerate or skewed target would show up as a trivial always-predict-majority-class model; this one clearly is not doing that (predictions vary continuously around 0.50, calibration below is honest).
- The one disclosed non-leakage finding — 502/57,600 (0.87%) of EURUSD labels span an admitted real-world gap rather than a clean 1-hour move — is far too small a fraction to explain a systematic, symbol-wide null result; it is an edge-case heterogeneity, not the cause of this outcome.
- Horizon (1 bar / 1 hour) and alignment (features use only `t ≤ current`, label uses `t+1`) were independently verified via the future-injection check (0 mismatches, 5 features × 28,800 rows) — timing/alignment is not the explanation either.

**Conclusion for B**: the target is clean, correctly aligned, and not leaking. It is simply a hard target — 1-hour-ahead FX direction — for these features to predict.

---

## C. Feature predictive behavior

**Canonical-model importances** (`FEATURE_IMPORTANCE_STABILITY_SAMPLE.json`, `FORENSIC_SIGNAL_ANALYSIS.json`):

| Feature | EURUSD | GBPUSD |
|---|---|---|
| `rsi_14` | 0.317 | 0.312 |
| `momentum_5` | 0.264 | 0.260 |
| `momentum_20` | 0.228 | 0.223 |
| `atr_14` | 0.175 | 0.191 |
| `volatility_regime` | 0.016 | 0.015 |

**Stability across WFA folds** — sampled 5 of the 65 walk-forward training windows per symbol (indices 0, 16, 32, 48, 64, spanning the full ~5.5-year DEVELOPMENT/VALIDATION range), retrained fresh RF-R2-001 instances on each window's own trailing-24-month data, and recorded `feature_importances_` directly (not reused from the canonical model — a genuinely independent check):

- `rsi_14`, `momentum_5`, and `momentum_20` are consistently the three dominant features in **every single sampled fold, both symbols, with no exceptions** — never displaced by `atr_14` or `volatility_regime`.
- `volatility_regime`'s importance is stable and consistently small: 1.8%–2.6% across all 10 sampled (fold × symbol) fits — never a leading feature, never zero either.
- Coefficient of variation of each feature's importance across the 5 sampled folds is low (roughly 8–15% relative to its own mean for the dominant features) — this is a **stable** ranking, not one that swings unpredictably fold to fold.

**Interpretation**: this rules out "feature instability" (the model is not randomly latching onto different, incidental features each retrain — the standalone `FEATURE_PROBLEM` category as commonly defined, meaning erratic/inconsistent feature use). What C actually shows is the opposite problem: the model *reliably* extracts the same momentum/RSI structure every time, and that structure is reliably weak (per §A's IC). Stable-but-uninformative is a different failure mode than unstable, and the evidence distinguishes them cleanly here.

---

## D. Prediction quality — calibration, distribution, monotonicity

**Calibration by predicted-probability decile** (VALIDATION-period, canonical model; full table in `FORENSIC_SIGNAL_ANALYSIS.json`):

| Decile (EURUSD) | mean pred. prob | realized freq. label=1 | mean fwd. return |
|---|---|---|---|
| 1 (lowest) | 0.4528 | 0.4705 | −0.000014 |
| 5 | 0.4921 | 0.4809 | −0.000049 |
| 6 | 0.5013 | 0.4948 | +0.000031 |
| 10 (highest) | 0.5428 | 0.5417 | +0.000030 |

(GBPUSD shows the same pattern; full 10-row tables for both symbols in the JSON artifact.)

Two separate, genuinely different properties, deliberately not conflated:

1. **Calibration (is the probability honest about label frequency?) — reasonably good.** Predicted probability and realized `label=1` frequency track each other closely across all 10 deciles for both symbols (e.g. EURUSD decile 10: predicted 0.543 vs. realized 0.542). The model is not miscalibrated or overconfident — `MODEL_MISFIT` in the sense of "the model doesn't even know its own uncertainty" is not supported by this evidence.
2. **Predictive power (does the probability predict economically meaningful forward returns?) — essentially absent.** Mean forward return by decile does **not** move monotonically with predicted probability: only **5 of 9 (EURUSD)** and **5 of 9 (GBPUSD)** consecutive bucket-to-bucket transitions are in the "expected" increasing direction — barely better than the 50% a monotonicity-free relationship would produce by chance. The forward-return magnitudes themselves are tiny (roughly 1–5 × 10⁻⁵, i.e. a few pips) — smaller than typical bid/ask spread, well before any commission/slippage is applied.

**Conclusion for D**: the model outputs an honest probability of an event that itself carries almost no economically exploitable information — calibration is fine, predictive power is not.

---

## E. EURUSD vs. GBPUSD comparison

| Metric | EURUSD | GBPUSD | Same failure? |
|---|---|---|---|
| IC (Spearman) | 0.030 | 0.017 | Yes — both near-zero |
| Directional accuracy | 51.83% | 51.25% | Yes — both barely > 50% |
| % predictions in flat zone | 95.6% | 94.7% | Yes — both dominated by indecision |
| Dominant features | rsi_14, momentum_5, momentum_20 | rsi_14, momentum_5, momentum_20 | Yes — identical ranking |
| WFA profit factor | 0.879 | 0.892 | Yes — both < 1 |
| WFA median fold PF | 0.895 | 0.807 | Yes — both < 1 |
| WFA net-negative windows | 36/65 (55.4%) | 44/65 (67.7%) | Yes — majority negative both |
| Zero-cost profit factor (canonical-model probe) | 1.016 | 1.006 | Yes — both ≈ breakeven, not genuinely profitable |

Every dimension checked shows the **same** failure pattern on both symbols, at similar magnitude. This is a **common** failure (the features/model/target combination does not work for 1-bar EURUSD or GBPUSD H1 direction), not an instrument-specific quirk of one pair. GBPUSD is directionally slightly worse (lower IC, more negative WFA windows), but the gap is small relative to how far both are from a usable result — not evidence of a regime- or instrument-specific explanation for the failure.

---

## F. WFA fold-level behavior

Computed directly from `WALKFORWARD_{EURUSD,GBPUSD}.json`'s 1,387/1,452 trade records, grouped by the 65 walk-forward windows each symbol used:

| Metric | EURUSD (65 folds) | GBPUSD (65 folds) |
|---|---|---|
| Fold profit factor — mean / median / std | 2.913† / **0.895** / 14.34 | 0.981 / **0.807** / 0.620 |
| Fold profit factor — min / max | 0.188 / 116.5† | 0.282 / 3.887 |
| Fold expectancy/trade — mean / median | $2.86 / **−$11.00** | −$11.67 / **−$22.59** |
| Positive-net-P&L folds | 29 / 65 (44.6%) | 21 / 65 (32.3%) |
| Negative-net-P&L folds | 36 / 65 (55.4%) | 44 / 65 (67.7%) |
| Worst single fold (net P&L) | −$2,324.54 | −$2,538.70 |
| Best single fold (net P&L) | +$2,313.77 | +$3,959.43 |
| Correlation(window index, window P&L) | 0.058 | −0.049 |

†EURUSD's fold PF **mean** (2.913) is distorted upward by one or two very-low-trade-count windows with an accidentally lopsided win/loss ratio (max fold PF 116.5); the **median** (0.895) is the representative statistic and is consistent with the aggregate result. This is disclosed explicitly rather than reporting only the flattering mean.

The **median** fold is unprofitable for both symbols, a majority of folds are net-negative, and there is no time trend (correlation with window index ≈ 0 for both) — the failure is not concentrated in one bad period or improving/degrading over the ~5.5-year OOS span. This is a persistent, not episodic, null result.

---

## G. Cost-sensitivity classification

**Scope caveat, disclosed upfront**: the cost-sensitivity probe below re-runs the **canonical model's** VALIDATION-period predictions through `run_backtest()` twice (baseline vs. zero transaction costs) — it is a smaller, single-model sample (229/287 trades) than the full 65-window WFA (1,387/1,452 trades), because the WFA's per-window trade records did not persist entry/exit prices needed to re-simulate a zero-cost pass exactly (see prior session's note on `WALKFORWARD_*.json` schema). It is directionally consistent with, but not numerically identical to, the full WFA result, and is reported as such — not silently presented as if it covered the same trade population.

| Symbol | Cost scenario | Trades | Net profit | Profit factor | Expectancy |
|---|---|---|---|---|---|
| EURUSD | Baseline costs | 229 | −$1,600.53 | 0.940 | −$6.99 |
| EURUSD | Zero costs | 229 | +$442.60 | 1.016 | +$1.93 |
| GBPUSD | Baseline costs | 287 | −$1,548.78 | 0.959 | −$5.40 |
| GBPUSD | Zero costs | 286 | +$260.93 | 1.006 | +$0.91 |

**Classification (this sample only)**: costs matter — removing them flips net P&L from negative to positive — but the zero-cost result is only marginally breakeven (PF 1.006–1.016, expectancy ~$1–2/trade), not a genuinely profitable pre-cost edge that costs merely erode. This maps to the **"approximately breakeven, destroyed by costs"** bucket rather than either "already negative before costs" or "positive before costs, insufficient after" — the pre-cost edge, if it exists at all, is too small to distinguish from noise given the tiny IC and forward-return magnitudes documented in §A/§D. No cost-model parameter was changed to produce this table; it is a direct `dataclasses.replace()` swap between the existing `BacktestConfig` and a zero-cost variant of it, run through the unmodified `run_backtest()`.

---

## Failure classification

Per the required taxonomy — every classification below is tied to a specific piece of evidence above, not asserted on plausibility alone.

### Primary: `NO_PREDICTIVE_SIGNAL`
- IC (Pearson/Spearman) 0.015–0.030, an order of magnitude below the conventional usability threshold (§A).
- Directional accuracy 51.2–51.8%, barely above coin-flip (§A).
- 95%+ of predictions cluster in an indecisive flat zone (§A).
- Calibration-by-decile forward returns are non-monotonic (5/9 transitions correct, ~chance) and tiny in magnitude (§D).
- Identical pattern on both symbols (§E), across all 65 WFA folds with no time trend (§F) — this is not a localized or intermittent signal, it is a globally absent one.

### Secondary, contributing: `COST_SENSITIVITY`
- Zero-cost canonical-model sample is only marginally breakeven (PF 1.006–1.016), not a clean pre-cost edge (§G) — costs are real and matter, but are not, by themselves, the primary explanation, since even removing them entirely does not produce a robust profitable result.

### Explicitly ruled out, with evidence:
- **`MODEL_MISFIT`** — ruled out. Calibration is reasonably accurate (§D); a genuinely misfit model would show predicted probabilities disconnected from realized label frequency, which is not observed.
- **`TARGET_PROBLEM`** — ruled out. Leakage-audited clean, correctly aligned, healthy ~50/50 class balance, gap-adjacent heterogeneity too small (0.87% of rows) to matter (§B).
- **`FEATURE_PROBLEM` (as "unstable/inconsistent feature use")** — ruled out in that specific sense; feature importances are *stable* across folds (§C), not erratic. (A softer, correctly-scoped version of this category — "the feature set itself lacks predictive content for this target" — is subsumed into the primary `NO_PREDICTIVE_SIGNAL` classification rather than treated as a separate cause, since §A/§D's IC/calibration evidence is a more direct measurement of that than feature importance alone.)
- **`EXECUTION_PROBLEM`** — ruled out. `run_backtest()`'s mechanics (position sizing, SL/TP, max-hold, exit priority, cost model) were independently verified correct in prior phases (Pine Script parity work, `ML-001-R2-PYTHON-PINE-PARITY-REPORT.md`) and are reused unmodified here, not reimplemented for this analysis.
- **`REGIME_INSTABILITY`** — ruled out as the primary explanation. Correlation between window index (time) and window P&L is ≈0 for both symbols (§F) — performance is not trending or regime-dependent over the ~5.5-year span, it is consistently (if noisily) unprofitable throughout.
- **`STATISTICAL_INSUFFICIENCY`** — ruled out. Trade-level P&L is large-sample (n=1,387/1,452) and statistically significantly different from zero in the *unfavorable* direction: one-sample t-test EURUSD t=−2.291, p=0.0221; GBPUSD t=−2.067, p=0.0389; bootstrap 95% CI EURUSD (−$25.86, −$1.59), GBPUSD (−$24.96, −$0.94) — both exclude zero. There is more than enough evidence to reach a confident negative conclusion; the problem is not "too little data to tell," it is "enough data to tell, and the answer is no."
- **`INSUFFICIENT_EVIDENCE`** / **`UNKNOWN`** — not applicable; the evidence above is sufficient to support a specific, well-evidenced classification.

**`EDGE_STATUS = NOT_PROVEN`** (in fact, actively disconfirmed by this evidence, not merely "not yet shown") stands as previously reported in `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md`; this document explains the mechanism behind that verdict rather than changing it.

---

## What this document does not do

- Does not modify `core/features/fe_r2_001.py`, `core/ml_r2/*.py`, or any hyperparameter, target definition, or cost model.
- Does not retrain RF-R2-001 toward a better result — every model referenced above is either the already-committed canonical artifact or a fresh fold-sample retrain used purely to measure importance stability, discarded after measurement (not saved as a new candidate artifact, not registered in the Factory).
- Does not access `PURE_HOLDOUT` at any point — every table above is built from DEVELOPMENT/VALIDATION-period data only, consistent with `STRAT-000001`'s own rejection (`TRAINED → REJECTED`, no `HOLDOUT_TESTED` ever recorded).
- Does not propose or begin `STRAT-000002` — see the stop condition addressed in the final status block of this task.
