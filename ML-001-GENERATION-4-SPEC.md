# ML-001 Generation 4 — Candidate Economic Validation Specification

**Status:** EXECUTED
**Candidate under validation:** `STRAT-000002`
**Validation run id:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Code version at execution:** `23fb460`
**Supersedes nothing.** Extends Generations 1–3; no earlier governance was
modified, relaxed, or reinterpreted to reach any Generation 4 result.

---

## 1. What Generation 4 is for

Generations 1–3 built the machinery to *produce* a research candidate with
verifiable lineage. Generation 4 exists to answer one question about the
first such candidate:

> Does `STRAT-000002` contain evidence of a real economic edge?

The question is deliberately not "can `STRAT-000002` be made to pass". A
factory whose gates can be argued past is not a factory; it is a
rationalisation engine with a build step. The success criterion for
Generation 4 is that the answer produced is *correct*, not that it is
favourable.

**Permitted outcomes:** `PASS`, `FAIL`, `INSUFFICIENT`, `BLOCKED`,
`INCONCLUSIVE`. A negative outcome is a successful research result.

---

## 2. What the candidate actually is

This matters more than it might appear, because most of this project's
prior machinery was built for a machine-learning candidate and
`STRAT-000002` is not one.

| Field | Value |
|---|---|
| `candidate_id` | `STRAT-000002` |
| `hypothesis_id` | `HYP-000001` |
| `claim_id` | `CLAIM-000001` |
| `source_id` | `SRC2-000001` (je-suis-tm/quant-trading README, Apache-2.0) |
| `search_space_id` | `SEARCHSPACE-000001` (8 parameter combinations) |
| Entry | `rsi_14` crosses back above 30 from below |
| Exit | stop-loss `1.5×ATR`, take-profit `2.0×ATR`, or 12 bars elapsed |
| Direction | long only |
| Features | `rsi_14`, `atr_14` (FE-R2-003) |
| Timeframe | H1 |
| Instrument scope | `SINGLE_INSTRUMENT` — EURUSD |
| Position sizing | fixed fractional, 2% risk per trade |
| **Model** | **none** |
| **Hyperparameters** | **none** |
| **Free parameters fitted from data** | **none** |

`STRAT-000002` is a deterministic rule with zero fitted parameters. Three
consequences follow, and each is reflected in how the corresponding phase
was executed rather than papered over:

1. **There is no model to train.** Contract Phase 8 says "train RF-R2-001
   *or the exact model specified by STRAT-000002*". The frozen
   specification names no model. Inventing one would have been a
   post-freeze specification change. Phase 8 was therefore executed as
   deterministic signal generation (`RULE-R4-001`), with provenance
   recorded in the same shape a training run would produce so downstream
   evidence consumers need no special case.

2. **There is no seed to cherry-pick.** Signal generation and execution
   are pure functions of the price series and the frozen thresholds. Seed
   cherry-picking is not defended against here; it is structurally
   impossible, and the adversarial suite asserts that rather than assuming
   it.

3. **Walk-forward measures stability, not parameter survival.** A
   walk-forward protocol normally tests whether parameters fitted on a
   training window survive on the next test window. With nothing fitted,
   every window is out-of-sample by construction. The protocol was still
   run — because time-stability is a real and separate question — but the
   training-window fields are recorded as structurally empty rather than
   filled with a fitting step that did not occur.

---

## 3. Governance conflict, and how it was resolved

The Generation 4 contract numbers `PURE_HOLDOUT` release and evaluation as
Phases 11–12, *before* OOS (13) and walk-forward (14).

This project's already-committed governance says the opposite.
`ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` and the `_FORWARD_SPINE` in
`core/factory/state_machine.py` both place `HOLDOUT_TESTED` **after**
every reusable-data gate and after `FROZEN`:

```
TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED → COST_TESTED
        → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED
        → FROZEN → HOLDOUT_TESTED → EVG_REVIEW
```

**Resolution: the committed governance wins.** Reordering the state
machine to match the contract's numbering would have been a silent
governance change to obtain a procedural convenience — precisely what
governance principle 1 forbids. Every artifact the contract asks for was
still produced; only the *order of execution* follows the committed spine.
This is recorded as an open governance decision in
`ML-001-GENERATION-4-REPORT.md` §Open Governance Decisions for a future
generation to reconcile deliberately.

---

## 4. Module map

Every module below produces evidence. Exactly one module consumes it.

| Phase | Module | Produces |
|---|---|---|
| 1 | `core/economic_validation/candidate_freeze.py` | `CandidateFreezeSnapshot` |
| 2 | `core/economic_validation/data_eligibility.py` | `DataEligibilityReport` |
| 3 | `core/economic_validation/feature_temporal_audit.py` | `FeatureTemporalAuditReport` |
| 4 | `core/economic_validation/target_audit.py` | `TargetLeakageAuditReport` |
| 5–6 | `core/economic_validation/partitions.py` | `PartitionBoundaries`, `SealedDataset`, `HoldoutReleaseRecord` |
| 8 | `core/economic_validation/rule_engine.py` | signals + `SignalGenerationProvenance` |
| 8 | `core/economic_validation/execution.py` | `ExecutionResult` (EXEC-R4-001) |
| 10, 12 | `core/economic_validation/metrics.py` | `PerformanceMetrics` |
| 10–13 | `core/economic_validation/evaluation.py` | `EvaluationRecord` |
| 14–15 | `core/economic_validation/walkforward.py` | `WalkForwardReport` |
| 16 | `core/economic_validation/robustness.py` | `RobustnessReport` |
| 17 | `core/economic_validation/cost_stress.py` | `CostStressReport` |
| 18 | `core/economic_validation/statistics.py` | `StatisticalValidationReport` |
| 19–20 | `core/economic_validation/multiple_testing.py` | `MultipleTestingReport` |
| 23 | `core/economic_validation/evg.py` | `EVGReport` — **consumes only** |
| — | `scripts/run_generation4.py` | orchestration, ledger, registry transitions |

`evg.py` is the one module with a structural prohibition: it imports
neither pandas nor numpy nor any evaluation function, and
`test_20c_evg_computes_no_evidence_of_its_own` asserts this by reading the
module's own source. A gate that can compute a metric can manufacture the
evidence it is supposed to be checking.

---

## 5. Design decisions that are load-bearing

### 5.1 The freeze snapshot is derived, never supplied

`freeze_candidate` reads the registry record, hashes the dataset bytes on
disk, and reads the live feature schema. A caller cannot hand it a
checksum; it can only ask what the checksum *is*. That is what makes
`verify_unchanged` meaningful — it recomputes from the same live sources
and compares. `verify_unchanged` is called before every phase that
consumes the frozen candidate, so a mutation *between* phases is caught,
not merely a mutation before the first one.

### 5.2 The validation run id is content-derived

`validation_run_id = G4RUN-{candidate_id}-{content_checksum[:16]}`.

A wall-clock or random run id would make two identical re-runs look like
two different experiments — the ambiguity a rescue loop hides inside.
Deriving it from content means an identical rerun is *visibly* identical,
and any changed input produces a visibly different run.

### 5.3 The holdout seal is structural

`SealedDataset` holds the holdout rows in a name-mangled private attribute
and returns them from exactly one method, which raises until
`release_holdout` is called. More importantly, `development()`,
`validation()` and `development_and_validation()` return frames sliced
*before* the holdout was ever attached — so a caller who concatenates
everything they can reach still cannot reconstruct the holdout.

The threat model is not a malicious caller (anyone who can edit the file
can defeat anything in it) but an ordinary one reaching for `.holdout` out
of habit while assembling a training set.

### 5.4 Leakage is tested, not asserted

Phase 3 does not document that features are causal; it tests it three
ways on the real series:

* **truncation invariance** — `f(data[0..T])[t] == f(data[0..t])[t]`
* **future perturbation invariance** — shock every bar after `t`, require
  `f[t]` bit-identical
* **same-timestamp leakage** — alter only bar `t+1`, require `f[t]`
  unchanged

Together these catch centred windows, `shift(-n)`, backward fills,
whole-sample normalisation, whole-sample quantiles and scaler fitting,
without needing to know which of them an author might have used.

### 5.5 Cost is charged on both legs

`core/ml_r2/backtest_r2.py` applies slippage on entry only. A cost model
that charges one side of a round turn systematically flatters every
strategy it evaluates. EXEC-R4-001 charges spread on entry, slippage on
entry *and* exit, and commission per round turn.

`backtest_r2.py` was **not modified** — it is frozen evidence for
STRAT-000001. Instead, `tests/test_generation4_execution_parity.py` pins
EXEC-R4-001 against `run_backtest` under matched settings (zero spread,
exit slippage off) and requires trade-for-trade, price-for-price,
P&L-for-P&L equality. The extension is therefore demonstrably an
*addition* to the audited semantics, not a divergence from them.

### 5.6 The three multiple-testing statuses are kept apart

```
ACCOUNTING_COMPLETE               we know how many things were tried
STATISTICAL_CORRECTION_COMPLETE   a correction was computed and applied
ECONOMIC_EDGE_SUPPORTED           the corrected evidence supports an edge
```

Conflating these is the specific failure Phase 19 exists to prevent. In
this project's current state the first two are true and the third is
false, and the `MultipleTestingReport` records all three separately.

---

## 6. Pre-registered constants

Declared in code before any corresponding result was computed:

| Constant | Value | Source |
|---|---|---|
| Partition fractions | 60 / 20 / 20 | `core/ml_r2/walkforward_r2.py`, committed 2026-08-18 |
| Minimum usable bars | 30,000 | derived from the partition governance |
| WFA window | 1 calendar month, contiguous, non-overlapping | this spec |
| Bootstrap block size | 20 trades | this spec |
| Bootstrap iterations | 10,000 | this spec |
| Bootstrap seed | 20260819 | this spec |
| Robustness grid | 5 × 3 × 4 × 3 × 2 = 360 points | `robustness.py` — **not pre-registered**, see §7 |
| Cost scenarios | 8 rungs | `cost_stress.py` |
| EURUSD spread | 1.6 pips | `core/utils.py` `INSTRUMENTS`, pre-existing |
| Slippage | 0.2 pip | `ML-001-R2-CLEAN-REBUILD-SPEC.md` §7 |
| Commission | 7.00 / lot round turn | `core/ml_r2/backtest_r2.py` |

---

## 7. What is NOT claimed

* **The robustness grid was not pre-registered.** No robustness protocol
  existed before Generation 4. The grid is a new research decision made
  during this generation and is recorded as one. Its results describe the
  shape of the parameter surface; they are not an unbiased confirmation of
  anything.
* **The cost figures are plausible, not measured.** None has been
  confirmed against a real broker feed for this dataset's period.
  `ML-001-R2-CLEAN-REBUILD-SPEC.md` §17 Open Item #2 remains open.
* **Swap/financing is not modelled.** Most trades close within 12 H1 bars
  without crossing a rollover; those that do would incur an additional
  cost. The results are therefore optimistic in this respect, not
  pessimistic.
* **The dataset's timezone convention is a documented assumption.**
  `provenance_status = VERIFIED_WITH_QUALIFICATION`, not `VERIFIED`.
* **No `PROVEN_EDGE` state exists.** Generation 4 is historical economic
  validation, not forward-market proof.

---

## 8. Completion criteria

See `ML-001-GENERATION-4-REPORT.md` §Completion Criteria for the
point-by-point evidence mapping. Generation 5 has **not** started.
