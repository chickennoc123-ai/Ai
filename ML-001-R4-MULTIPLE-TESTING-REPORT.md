# ML-001-R4 — Multiple Testing Report

**Phase:** Generation 4, Phase 19
**Run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Artifact:** `reports/generation4/MULTIPLE_TESTING.json`
**Verdict:** `MULTIPLE_TESTING_STATUS = COMPLETE`, economic edge
**`NOT_SUPPORTED`**

---

## 1. Three statuses, kept apart

Conflating these is the specific failure this phase exists to prevent, so
they are separate fields in the artifact and separate rows here:

| Status | Value | Meaning |
|---|---|---|
| `ACCOUNTING_STATUS` | **ACCOUNTING_COMPLETE** | We know how many things were tried. |
| `STATISTICAL_CORRECTION_STATUS` | **STATISTICAL_CORRECTION_COMPLETE** | A correction was computed and applied. |
| `ECONOMIC_EDGE_STATUS` | **NOT_SUPPORTED** | The corrected evidence does not support an edge. |

The first two being true says nothing about the third. In this project's
current state the first two are true and the third is false.

---

## 2. Trial accounting, read from the ledgers

| Counter | Value | Source |
|---|---|---|
| `TOTAL_SOURCES` | 4 | `research_source_registry.json` |
| `TOTAL_CLAIMS` | 3 | `claim_registry.json` |
| `TOTAL_HYPOTHESES` | 3 | `hypothesis_registry.json` |
| `TOTAL_SEARCH_SPACES` | 1 | `search_space_registry.json` |
| `TOTAL_STRATEGY_FAMILIES` | 4 | `research_family_registry.json` |
| `TOTAL_CANDIDATES_GENERATED` | **2** | `strategy_registry.json` |
| `TOTAL_CANDIDATES_TESTED` | 2 | recomputed from state |
| `TOTAL_CANDIDATES_REJECTED` | 2 | recomputed from state |
| `SEARCH_SPACE_SIZE` (enumerable) | 8 | `SEARCHSPACE-000001` |
| **Effective trials for deflation** | **2** | — |

### 2.1 Why `effective_trials = 2` and not 8

The enumerable search space has 8 parameter combinations, but only 2
candidates were ever *evaluated*. The un-drawn combinations were never
tested and are not trials.

Using 8 would have been more conservative — a larger benchmark, a harsher
test — and it would also have been fiction. The accounting reports what
happened, not the most defensive-sounding number available.

### 2.2 Why the rejected candidate counts

`effective_trials` counts every candidate the Factory has put through
economic evaluation, including `STRAT-000001` (rejected in Generation 3).
Counting only survivors is precisely the self-deception this phase exists
to prevent: it is how "we tried one thing and it worked" gets written
after trying twenty.

---

## 3. Deflated Sharpe Ratio

Bailey & López de Prado (2014). All Sharpe quantities below are
**per-observation** (per H1 bar), not annualised — mixing the two units is
the most common way this statistic is computed wrongly.

| Quantity | Value |
|---|---|
| Observed Sharpe (per observation) | **−0.017479** |
| Observed Sharpe (annualised, ×√6240) | **−1.3807** |
| Return observations | 46,079 |
| Skewness | −0.4905 |
| Kurtosis | 50.65 |
| Expected max Sharpe from 2 skill-free trials | +0.002422 |
| **Deflated Sharpe probability** | **9.26 × 10⁻⁶** |

The deflated Sharpe probability is the probability that the observed
Sharpe exceeds what a skill-free search over 2 trials would be expected to
reach. At 0.0000093 it is about as far from the conventional 0.95
threshold as the statistic can go.

The benchmark itself is tiny (+0.0024 per bar) because two trials produce
almost no selection advantage. The observed Sharpe is not merely below the
benchmark; it is negative.

---

## 4. The correction's power, stated before it can be misread

`CORRECTION_MEANINGFULNESS = NEARLY_UNINFORMATIVE`

Verbatim from the artifact:

> Only 2 candidate(s) have ever been evaluated by this Factory. A
> deflation over 2 trials shifts the benchmark by a negligible amount, so
> a candidate that passes it has NOT thereby been shown to survive
> multiple-testing scrutiny — there was barely any multiplicity to correct
> for. The correction is reported for completeness and for the audit trail
> it establishes for future generations, not because it discriminates.

This is the part most likely to be misquoted later, so it is worth being
blunt: **had `STRAT-000002` passed this correction, that would have meant
almost nothing.** A deflation over 2 trials is arithmetically valid and
epistemically nearly empty. The threshold for meaningful discrimination is
set at 20 trials in `multiple_testing.py`; this Factory has 2.

The correction becomes informative only when the Factory has accumulated a
real search population. Its value today is the audit trail, not the
number.

---

## 5. Why the correction is moot for this candidate

The observed annualised Sharpe is **−1.3807**.

A multiple-testing correction can only *reduce* confidence in a positive
result. It has nothing to correct in a negative one. `STRAT-000002` is
refuted before multiplicity is even considered, and the deflated
probability of 9.26 × 10⁻⁶ simply restates the fact that a strongly
negative Sharpe is not evidence of skill.

Put plainly: this phase did not reject the candidate. Development, OOS,
walk-forward, robustness, cost stress and the confidence intervals did.
This phase confirms there is nothing left for a correction to take away.

---

## 6. Effect on `SELECTION_BIAS_STATUS`

Moved from `ACCOUNTING_ONLY` (Generation 3) to
**`STATISTICAL_CORRECTION_APPLIED_LOW_POWER`**, with the justification
recorded in the registry's own search-history event log —
`StrategyRegistry.set_selection_bias_status` refuses to change the status
without one.

The `LOW_POWER` suffix is load-bearing, not stylistic:
`test_selection_bias_status_is_not_silently_marked_pass` requires any
status beginning `STATISTICAL_CORRECTION_APPLIED` to carry it, so a future
reader cannot mistake "corrected" for "shown to be unbiased".

See `ML-001-R4-SELECTION-BIAS-AUDIT.md` for the full decision timeline.
