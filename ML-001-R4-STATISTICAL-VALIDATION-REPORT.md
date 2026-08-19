# ML-001-R4 — Statistical Validation Report

**Phase:** Generation 4, Phase 18
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifacts:** `reports/generation4/STATISTICAL_VALIDATION.json`,
`reports/generation4/STATISTICAL_VALIDATION_HOLDOUT.json`
**Verdict:** `STATISTICAL_STATUS = FAIL`

---

## 1. Methodology

| Parameter | Value | Chosen |
|---|---|---|
| Primary method | **moving-block bootstrap** | before any interval was computed |
| Secondary method | IID bootstrap | reported only for contrast — see §1.2 |
| Block size | **20 trades** | before any interval was computed; not varied afterward |
| Iterations | 10,000 (2,000 for drawdown/Sharpe resamples) | fixed |
| Seed | 20260819 | fixed constant, never selected by result |
| Confidence | 95%, percentile method | fixed |
| Primary sample | DEVELOPMENT + VALIDATION, 646 trades | — |

### 1.1 Why a block bootstrap

Trading returns are serially dependent, and consecutive trades sample
adjacent market regimes. An IID trade-level bootstrap destroys that
structure and reports intervals narrower than the data supports.

A 20-trade block spans roughly one market month at this trade frequency,
which is the scale at which regime persistence shows up in the P&L
sequence.

### 1.2 The IID result is shown to expose its own error

Both are reported side by side so the reader can see how much the
independence assumption would have flattered the analysis:

| Statistic | Block 95% CI | IID 95% CI | IID width vs block |
|---|---|---|---|
| Expectancy / trade | [−19.42, −7.11] | [−20.42, −6.71] | ~11% wider |
| Profit factor | [0.591, 0.809] | [0.562, 0.831] | ~24% wider |
| Net profit | [−12,545, −4,591] | [−13,193, −4,333] | ~11% wider |

Here the IID intervals happen to be slightly *wider*, not narrower — the
block structure captures the run-of-losses persistence in a way that makes
the mean more stable across resamples. Reported as observed; the point of
showing both is that the choice is visible rather than assumed.

### 1.3 Deliberately not computed

* **A p-value against a "no edge" null.** With a candidate drawn from a
  search space the project can enumerate, a single-candidate p-value would
  ignore the search that produced the candidate. Significance is treated
  in `ML-001-R4-MULTIPLE-TESTING-REPORT.md`, where it belongs.
* **A parametric probability of ruin.** That would require a
  distributional assumption the data does not support (kurtosis ≈ 51).
  Ruin is estimated by resampling the actual trade sequence, which makes
  it a statement about the observed sample and nothing more.

---

## 2. Sample sufficiency

| Sample | Trades | Assessment |
|---|---|---|
| DEVELOPMENT + VALIDATION | **646** | **SUFFICIENT** (≥ 100) |
| PURE_HOLDOUT | **142** | **SUFFICIENT** (≥ 100) |

Sufficiency is reported explicitly because an interval computed from too
few trades is precise-looking noise, and adding decimals to it does not
help.

---

## 3. Primary intervals — DEVELOPMENT + VALIDATION (646 trades)

| Statistic | Point estimate | Block bootstrap 95% CI | Straddles the null? |
|---|---|---|---|
| **Expectancy per trade** | **−13.574** | **[−19.420, −7.107]** | **No** (null = 0) |
| **Profit factor** | **0.6856** | **[0.5906, 0.8090]** | **No** (null = 1) |
| **Net profit** | **−8,768.91** | **[−12,545.40, −4,591.21]** | **No** (null = 0) |

**All three intervals lie entirely on the losing side of their null.** The
upper bound of the profit-factor interval is 0.809 — the resampling does
not reach break-even in any plausible world consistent with this data.

This is what distinguishes `FAIL` from `INSUFFICIENT`. The evidence does
not merely fail to support an edge; it excludes one at 95% confidence.

### 3.1 Sharpe uncertainty

| | Value |
|---|---|
| Observed annualised Sharpe | **−1.3807** |
| Block bootstrap 95% CI | **[−2.0823, −0.6722]** |
| Analytic standard error (IID normal reference) | 0.5143 |
| Return observations | 46,079 |

The interval is entirely negative.

### 3.2 Drawdown distribution

Block bootstrap over the trade-P&L sequence:

| | Value |
|---|---|
| Observed max drawdown | 9,059.37 |
| Resampled median | 8,609.89 |
| Resampled 95th percentile | 12,060.90 |
| Resampled 99th percentile | 13,520.98 |
| Worst resample | 17,378.91 |

The observed drawdown is close to the resampled median — the realised path
was ordinary for this strategy, not unlucky.

### 3.3 Probability of ruin

Fraction of resampled trade sequences whose peak-to-trough drawdown
exceeds a given fraction of the 10,000 starting equity:

| Threshold | Probability |
|---|---|
| > 20% of starting equity | **1.000** |
| > 30% | **0.999** |
| > 50% | **0.983** |

**Caveat, carried in the artifact itself:** this describes resamples of
the *observed* trade sequence. It is not a forward-looking probability and
must not be read as one. What it does establish is that the observed
drawdown was not a tail event — essentially every reordering of these
trades ruins the account.

---

## 4. PURE_HOLDOUT, evaluated separately (142 trades)

| Statistic | Point estimate | Block bootstrap 95% CI | Straddles the null? |
|---|---|---|---|
| Expectancy per trade | −27.809 | [−45.223, −6.002] | No |
| Profit factor | 0.6534 | [0.4959, **0.9124**] | No |
| Net profit | −3,948.86 | [−6,421.69, −852.28] | No |
| Annualised Sharpe | −1.4021 | [−2.7627, **+0.0528**] | **Yes** |

Two honest observations about the smaller sample:

1. The expectancy, profit-factor and net-profit intervals all remain
   entirely on the losing side.
2. The **Sharpe** interval marginally crosses zero (upper bound +0.053).
   With 142 trades the Sharpe estimate alone would be too noisy to reject
   an edge on its own. It is reported that way rather than rounded into a
   cleaner story.

The holdout verdict does not rest on the holdout Sharpe. It rests on the
expectancy and profit-factor intervals, which do not cross, and on
consistency with two other partitions.

---

## 5. Verdict

`STATISTICAL_STATUS = FAIL`.

The 95% block-bootstrap confidence interval for per-trade expectancy on
646 trades is **[−19.42, −7.11]** — entirely below zero. Combined with a
profit-factor interval whose upper bound is 0.809 and an entirely negative
Sharpe interval, the statistical evidence refutes an edge rather than
merely failing to find one.
