# ML-001-R4 — PURE_HOLDOUT Report

**Phase:** Generation 4, Phases 11–12
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifacts:** `reports/generation4/HOLDOUT_RELEASE_RECORD.json`,
`reports/generation4/EVALUATION_PURE_HOLDOUT.json`,
`reports/generation4/STATISTICAL_VALIDATION_HOLDOUT.json`
**Evaluations performed:** exactly **one**

---

## 1. Release

| Field | Value |
|---|---|
| Candidate | `STRAT-000002` v1 |
| Candidate checksum | `f38087385217026c…` |
| Freeze snapshot checksum | `6b1c63d014d4a7be…` |
| Dataset | `DATASET-EURUSD-H1-KOMO135-V1` |
| Holdout frame checksum | recorded in the release record |
| Holdout period | **2020-04-29 16:00 → 2022-03-05 04:00 UTC** |
| Holdout bars | 11,520 |
| Candidate state at release | `FROZEN` |

### 1.1 Reason for release, verbatim

> The complete pre-holdout evidence chain is closed (data eligibility,
> feature temporal safety, target-leakage audit, development evaluation,
> OOS, walk-forward, robustness, cost stress, statistics, multiple-testing
> accounting) and the candidate has entered FROZEN. Generation 4
> completion criterion 10 requires PURE_HOLDOUT to be evaluated under the
> frozen specification. Disclosure: the candidate is already refuted on
> reusable data; the holdout is opened to complete the required evidence,
> not in the expectation that it will change the verdict, and no
> modification of any kind is permitted after this point.

### 1.2 A judgement call, stated plainly

`STRAT-000001` was rejected in Generation 3 **without** ever opening the
holdout, on the reasoning that a one-shot resource should not be spent on
a candidate already refuted on reusable data. By that precedent,
`STRAT-000002` did not need the holdout either: it was already refuted on
DEVELOPMENT and OOS before the seal was touched.

The holdout was opened anyway, for two reasons:

1. Generation 4 completion criterion 10 requires it explicitly.
2. Opening it after `FROZEN` cannot bias anything. No modification is
   permitted afterward, and the candidate's terminal state was already
   determined by evidence gathered before the seal was broken.

What it costs: this 22-month window is now spent for this candidate
family. It should be recorded that the cost was paid to satisfy a
completion criterion, not because the evidence needed it.

---

## 2. Seal integrity before release

| Property | Mechanism | Result |
|---|---|---|
| Holdout unreadable before release | `SealedDataset.holdout()` raises `HoldoutSealError` | enforced |
| Holdout unreachable via other accessors | `development()`, `validation()`, `development_and_validation()` are sliced before the holdout is attached | enforced |
| Release is one-shot | second `release_holdout` raises `HoldoutAlreadyReleasedError` | enforced |
| Release requires prior development evidence | empty `development_evidence_reference` raises | enforced |
| No pre-release access occurred | `holdout_was_accessed_before_release()` → `False` | verified |
| Registry gate | `HOLDOUT_TESTED` requires a validated `HoldoutAccessEvent` | enforced |
| Ordering | `FROZEN` precedes `HOLDOUT_TESTED` in candidate history | verified |

Adversarial coverage: `test_01`–`test_04b` in
`tests/test_generation4_adversarial.py`.

---

## 3. Results — the single evaluation

Frozen specification, base cost model, 10,000 starting equity.

| Metric | Value |
|---|---|
| **Trade count** | **142** |
| Profitable trades | 58 |
| Losing trades | 84 |
| Breakeven trades | 0 |
| Gross profit | 7,443.91 |
| Gross loss | 11,392.77 |
| **Net profit** | **−3,948.86** |
| **Profit factor** | **0.6534** |
| **Win rate** | **40.85%** |
| **Expectancy per trade** | **−27.81** |
| Average trade | −27.81 |
| Average win | +128.34 |
| Average loss | −135.63 |
| Largest win | +240.56 |
| Largest loss | −205.91 |
| **Sharpe (annualised)** | **−1.4021** |
| Sortino | −0.6417 |
| **Max drawdown** | **4,341.35 (43.41%)** |
| Max drawdown duration | 11,418 bars |
| Recovery factor | −0.9096 |
| Longest losing streak | 8 |
| Longest winning streak | 7 |
| Turnover | 106.63 lots |
| Exposure | 9.49% of bars |
| Total costs paid | 2,879.08 |
| **Gross P&L before costs** | **−1,069.79** |

### 3.1 Exit reasons

| Reason | Count | Share |
|---|---|---|
| `STOP_LOSS` | 67 | 47.2% |
| `MAX_HOLDING_PERIOD` | 43 | 30.3% |
| `TAKE_PROFIT` | 32 | 22.5% |

### 3.2 Per-bar return distribution

| | Value |
|---|---|
| n | 11,519 |
| mean | −4.119 × 10⁻⁵ |
| std | 2.321 × 10⁻³ |
| skew | +0.258 |
| kurtosis | 51.95 |
| min | −0.02509 |
| max | +0.04044 |

The very high kurtosis is expected and not a defect: equity is flat on the
~90% of bars with no open position, so the return series is a spike
distribution rather than a continuous one.

---

## 4. What the number means

The holdout does not merely fail to support an edge; it **refutes** one,
and it refutes it in the same direction and at a similar magnitude as
every earlier partition:

| Partition | Trades | Profit factor | Net |
|---|---|---|---|
| DEVELOPMENT | 488 | 0.6727 | −8,273.63 |
| OOS (VALIDATION) | 157 | 0.7927 | −3,050.02 |
| **PURE_HOLDOUT** | **142** | **0.6534** | **−3,948.86** |

The holdout is not an outlier confirming an otherwise-working strategy,
nor a disappointment after a promising development result. It is the third
consistent observation of the same thing.

The most informative line in the table above is `gross_pnl_before_costs =
−1,069.79`. **The strategy loses money on the holdout before a single
unit of execution cost is applied.** Costs then roughly quadruple the
loss. This is not a cost-sensitivity failure — it is the absence of a
signal.

---

## 5. Statistical treatment of the holdout alone

`reports/generation4/STATISTICAL_VALIDATION_HOLDOUT.json` carries
block-bootstrap intervals for the holdout's 142 trades on their own
(sufficiency: SUFFICIENT, above the 100-trade threshold, though the
interval is correspondingly wider than the 646-trade reusable one).

The primary statistical result for the verdict is computed on the reusable
partitions, not on the holdout — using the holdout for the headline
interval would give the sealed partition a second job it was not sealed
for. See `ML-001-R4-STATISTICAL-VALIDATION-REPORT.md`.

---

## 6. Post-release discipline

After the release timestamp, **nothing** about the candidate changed:

* no parameter, feature, threshold, cost assumption, or window was altered;
* `verify_unchanged` was called against the freeze snapshot immediately
  before release and passes against the committed registry today
  (`test_frozen_candidate_was_never_mutated`);
* the candidate moved `HOLDOUT_TESTED → EVG_REVIEW → REJECTED` and
  `REJECTED` is terminal — the state machine permits no transition out of
  it, asserted in `test_24_a_rescue_loop_cannot_reuse_the_rejected_candidate`.

---

## 7. Reproducibility

`tests/test_generation4_integration.py::test_pure_holdout_result_reproduces_from_source`
re-derives this evaluation from the committed CSV and the committed
candidate specification in a fresh process and requires the result
checksum to match `febe48ac8b5ffb9f…` exactly. The headline number is
re-derivable, not merely stored.
