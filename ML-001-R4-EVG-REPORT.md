# ML-001-R4 — Economic Validation Gate Report

**Phase:** Generation 4, Phase 23
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/EVG_REPORT.json`
**Candidate checksum:** `f38087385217026c…`
**Freeze snapshot checksum:** `6b1c63d014d4a7be…`

## **EVG_VERDICT = FAIL**

---

## 1. What the gate is allowed to do

The EVG consumes evidence. It computes nothing.

`core/economic_validation/evg.py` imports neither pandas nor numpy nor any
evaluation, execution, or metric function.
`test_20c_evg_computes_no_evidence_of_its_own` asserts this by reading the
module's own source and failing if `import pandas`, `import numpy`,
`execute(`, `compute_metrics` or `build_feature_matrix` appears in it.

The reason is not tidiness. A gate that can compute a metric can
manufacture the evidence it is supposed to be checking, and a gate that
can manufacture evidence is not a gate.

Each `EvidenceItem` carries the producing module's **own** verdict and the
producing module's **own** report checksum. The gate stores both and
recomputes neither.

---

## 2. Evidence chain — complete

| # | Evidence | Verdict | Artifact |
|---|---|---|---|
| 1 | `REAL_DATA` | PASS | `DATA_ELIGIBILITY.json` |
| 2 | `DATA_INTEGRITY` | ELIGIBLE | `DATA_ELIGIBILITY.json` |
| 3 | `LEAKAGE_AUDIT` | PASS | `FEATURE_TEMPORAL_AUDIT.json` |
| 4 | `TARGET_AUDIT` | PASS | `TARGET_LEAKAGE_AUDIT.json` |
| 5 | `CANDIDATE_FREEZE` | PASS | `CANDIDATE_FREEZE_SNAPSHOT.json` |
| 6 | `TRAINING` | PASS | `EVALUATION_DEVELOPMENT.json` |
| 7 | `DEVELOPMENT_EVALUATION` | **FAIL** | `EVALUATION_DEVELOPMENT.json` |
| 8 | `HOLDOUT` | **FAIL** | `EVALUATION_PURE_HOLDOUT.json` |
| 9 | `OOS` | **FAIL** | `EVALUATION_OOS.json` |
| 10 | `WFA` | **FAIL** | `WALK_FORWARD.json` |
| 11 | `ROBUSTNESS` | **FAIL** | `ROBUSTNESS.json` |
| 12 | `COST_STRESS` | **FAIL** | `COST_STRESS.json` |
| 13 | `STATISTICS` | **FAIL** | `STATISTICAL_VALIDATION.json` |
| 14 | `MULTIPLE_TESTING` | **NOT_SUPPORTED** | `MULTIPLE_TESTING.json` |

Evidence missing: **none**. Blocking reasons: **none**.

Every item was checked to belong to candidate `STRAT-000002` and to
validation run `G4RUN-STRAT-000002-6b1c63d014d4a7be`; evidence from a
different candidate or a different run blocks the gate rather than being
silently accepted (`test_20`).

---

## 3. Refuting observations, verbatim

1. **DEVELOPMENT_EVALUATION** — profit factor 0.6727 < 1 on 488 trades;
   net −8,273.63
2. **HOLDOUT** — profit factor 0.6534 < 1 on 142 trades; net −3,948.86
3. **OOS** — profit factor 0.7927 < 1 on 157 trades; net −3,050.02
4. **WFA** — 90 windows, positive fraction 0.3556, total net −18,557.81,
   DISTRIBUTED
5. **ROBUSTNESS** — viable region: NONE; 0 of 360 grid points have PF > 1
6. **COST_STRESS** — NOT_COST_DEPENDENT: the strategy is unprofitable even
   with all execution costs removed
7. **STATISTICS** — block-bootstrap 95% CI for per-trade expectancy is
   [−19.4201, −7.1071] — entirely below zero
8. **MULTIPLE_TESTING** — observed annualised Sharpe −1.3807; a correction
   can only reduce confidence in a positive result

## 4. Supporting observations

`REAL_DATA`, `DATA_INTEGRITY`, `LEAKAGE_AUDIT`, `TARGET_AUDIT`,
`CANDIDATE_FREEZE`, `TRAINING` — all PASS.

These are process gates, not economic ones. Their passing is what makes
the eight refutations *interpretable*: the negative result is not an
artifact of bad data, a leaking feature, a contaminated target, a mutated
specification, or a non-deterministic run. The pipeline is clean and the
strategy loses money.

---

## 5. Why FAIL and not INSUFFICIENT

The gate distinguishes these deliberately, and the distinction is the one
that matters most in practice:

* **INSUFFICIENT** — the complete chain is present, nothing refutes the
  candidate, but the evidence is too thin to support a conclusion.
* **FAIL** — the complete chain is present and at least one gate produced
  a *refuting* observation.

Eight gates produced refuting observations. Sample sizes are adequate (646
trades on reusable data, 142 on holdout — both above the 100-trade
threshold). Confidence intervals exclude break-even rather than straddling
it.

Verdict basis, verbatim from the artifact:

> 8 gate(s) produced refuting evidence against the frozen candidate. The
> complete chain was present, so this is a conclusion, not a gap.

---

## 6. Scope of the verdict

`EVG_VERDICT = FAIL` means: **under the frozen specification, on real
EURUSD H1 data from 2012-11-16 to 2022-03-05, with a complete and audited
evidence chain, `STRAT-000002` shows no evidence of economic edge and
positive evidence of negative expectancy.**

It does not mean RSI is useless, that mean reversion does not exist in FX,
or that no related strategy could work. It is a verdict on one frozen
candidate, on one instrument, on one timeframe, over one historical
period.
