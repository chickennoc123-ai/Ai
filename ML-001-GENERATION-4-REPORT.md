# ML-001 Generation 4 — Candidate Economic Validation Report

**Candidate:** `STRAT-000002`
**Validation run:** `G4RUN-STRAT-000002-6b1c63d014d4a7be`
**Code version:** `23fb460`
**Status:** **COMPLETE**
**Outcome:** **NO EDGE FOUND — candidate REJECTED**

---

## Executive summary

`STRAT-000002` — the first candidate this Factory ever produced from a
real external source with complete lineage — was frozen, audited, and
evaluated across the full Generation 4 evidence chain. It does not work.

The evidence is unusually clean, in the sense that matters: every process
gate passed, so the negative result cannot be blamed on the pipeline.

| Partition | Trades | Profit factor | Net | Gross before costs |
|---|---|---|---|---|
| DEVELOPMENT | 488 | 0.6727 | −8,273.63 | −3,024.22 |
| OOS (VALIDATION) | 157 | 0.7927 | −3,050.02 | +1,149.41 |
| **PURE_HOLDOUT** | **142** | **0.6534** | **−3,948.86** | **−1,069.79** |

Three findings carry the verdict:

1. **It loses money before costs.** At ZERO_COST on the combined reusable
   partitions, profit factor is 0.8855 and net is −4,628.77. This is not a
   cost-sensitivity failure; there is no signal to be eaten.
2. **Nothing in the parameter neighbourhood works.** 0 of 360 grid points
   reach profit factor 1. The best point in the entire surface is 0.8611.
   The failure belongs to the rule family, not the chosen parameters.
3. **The 95% confidence interval excludes break-even.** Block-bootstrap
   expectancy over 646 trades: **[−19.42, −7.11]**. The evidence refutes
   an edge rather than failing to find one.

The Factory did its job. Rejecting a false edge *is* the job.

---

## 1. The candidate, and one structural fact about it

`STRAT-000002` is a deterministic rule with **no model, no
hyperparameters, and zero parameters fitted from data**:

> Enter long when `rsi_14` crosses back above 30 from below. Exit at
> `1.5×ATR` stop, `2.0×ATR` target, or 12 bars — whichever comes first.
> EURUSD H1, fixed-fractional 2% risk.

Lineage: `STRAT-000002 → HYP-000001 → CLAIM-000001 → SRC2-000001`
(je-suis-tm/quant-trading README, Apache-2.0, content-checksummed
snapshot). The source itself hedges — *"The effectiveness of any
divergence strategy on RSI is rather debatable"* — and that hedge is
recorded in the claim registry. This generation is, in a sense, the
empirical test of that hedge.

Three phases were shaped by the no-model fact, and in each case the
alternative would have meant inventing something the specification did not
contain:

| Contract phase | As executed | Why |
|---|---|---|
| 8 — Model training | Deterministic signal generation (`RULE-R4-001`), provenance recorded in training-record shape | The frozen spec names no model; inventing one would be a post-freeze specification change |
| 14 — Walk-forward | Rolling windows with structurally empty training fields | Nothing is fitted, so every window is out-of-sample by construction; the protocol measures time-stability instead |
| 22/27 — Seed cherry-picking | Structurally impossible | No stochastic element exists to seed |

---

## 2. Governance conflict, resolved and disclosed

The Generation 4 contract numbers PURE_HOLDOUT release/evaluation as
Phases 11–12, before OOS (13) and WFA (14). This project's committed
governance — `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` and the
`_FORWARD_SPINE` in `core/factory/state_machine.py` — places
`HOLDOUT_TESTED` **after** every reusable-data gate and after `FROZEN`.

**The committed governance was followed.** Reordering the state machine to
match the contract's numbering would have been a silent governance change
for procedural convenience — exactly what governance principle 1 forbids.
Every artifact the contract asks for was produced; only the execution
order follows the committed spine.

Executed order:

```
DATA_VALIDATED → TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED
→ COST_TESTED → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED
→ FROZEN → HOLDOUT_TESTED → EVG_REVIEW → REJECTED
```

Recorded as open governance decision **OGD-1** below.

---

## 3. Evidence chain

### 3.1 Process gates — all PASS

| Gate | Result | Key evidence |
|---|---|---|
| Real market data | PASS | recomputed file checksum matches registry; `synthetic = false` |
| Data integrity | **ELIGIBLE** | 0 duplicates, 0 OHLC violations, 0 NaN, 0 bars in the closed window, **0 unexplained gaps** (502/502 explained by market closure) |
| Feature temporal safety | **PASS** | truncation invariance, future-perturbation invariance, next-bar leakage — all pass on real data at 12 cut points |
| Target leakage | **PASS** | signal→entry lag exactly 1 bar for every trade; post-exit and post-signal perturbation invariance verified on 25 sampled real trades |
| Candidate freeze | PASS | `verify_unchanged` passes against the committed registry today |
| Signal generation | PASS | deterministic; identical checksums across three in-process runs and across fresh processes |

### 3.2 Economic gates — all FAIL

| Gate | Result | Headline |
|---|---|---|
| Development | FAIL | PF 0.6727, 488 trades |
| OOS | FAIL | PF 0.7927, 157 trades |
| **PURE_HOLDOUT** | **FAIL** | **PF 0.6534, 142 trades** |
| Walk-forward | FAIL | 32/90 windows positive; total −18,557.81; DISTRIBUTED |
| Robustness | FAIL | 0/360 grid points PF > 1; viable region NONE |
| Cost stress | FAIL | **NOT_COST_DEPENDENT** — loses at zero cost |
| Statistics | FAIL | expectancy 95% CI [−19.42, −7.11] |
| Multiple testing | NOT_SUPPORTED | annualised Sharpe −1.3807 |

---

## 4. The three findings, in detail

### 4.1 It loses before costs

| Scenario | Net | PF | Gross before costs |
|---|---|---|---|
| ZERO_COST | −4,628.77 | 0.8855 | −4,628.77 |
| BASE | −8,768.91 | 0.6856 | −2,772.46 |
| STRESSED | −9,739.43 | 0.5434 | −2,028.02 |

The only partition with a positive gross figure is VALIDATION: **+7.32 per
trade against 26.75 of cost per trade** — about a quarter of what would be
needed. On DEVELOPMENT and PURE_HOLDOUT the gross figure is negative
outright.

This distinction determines what happens next. `ZERO_COST_DEPENDENT` would
say *the edge exists but is too small to trade*, pointing toward a
cheaper venue or a longer horizon. `NOT_COST_DEPENDENT` says *there is no
edge*, and points nowhere within this family.

### 4.2 The neighbourhood is uniformly dead

360 points: **0** with PF > 1, **0** net positive. Best PF in the entire
surface: 0.8611. The frozen point sits at the **43.6th percentile** of its
own neighbourhood — neither a lucky pick nor an unlucky one, which is
exactly what a parameter draw made before seeing results should look like.

Three marginal patterns, each cutting against the strategy's own premise:

* Loosening the oversold threshold from 25 → 35 monotonically **improves**
  profit factor (0.639 → 0.738). The rule's premise is that deeper
  oversold conditions are *stronger* signals; the data says the opposite.
* Wider stops with wider targets monotonically improve — the signature of
  a random entry under fixed-fractional sizing, where tight stops are
  taken out by ordinary noise.
* Delaying entry by one bar makes it slightly **better** (0.682 → 0.722).
  A genuine short-horizon mean-reversion signal would degrade with delay.

### 4.3 The failure is distributed across the whole history

| | Value |
|---|---|
| Positive windows | 32 / 90 (35.6%) |
| Largest single window's share of absolute P&L | 5.09% |
| Top-5 windows' share | 18.26% |
| Correlation of window P&L with time | +0.027 |
| Total excluding the worst window | −16,625.08 |

**All nine calendar years are net negative** (2012 partial through 2020
partial), spanning trending and range-bound regimes, the 2015 CHF de-peg,
the Brexit period and the opening of the 2020 shock. There is no regime in
which this rule works, and no time trend — it is not a decayed edge that
once worked.

---

## 5. What was NOT done, deliberately

| Not done | Why |
|---|---|
| Evaluated GBPUSD | Frozen `research_scope` is `SINGLE_INSTRUMENT`/EURUSD. Data is present and eligible; using it would be a post-freeze scope change. This *cost* information — and that is precisely why the boundary is only meaningful if it holds when crossing it would be interesting. |
| Widened the robustness grid after seeing 0/360 | Opportunistic search-space expansion — the rescue loop Phase 25 forbids. |
| Adjusted cost assumptions after seeing the result | Every figure traces to a pre-existing repository constant. |
| Created `STRAT-000003` | Generation 4 ends at the verdict. A new candidate requires a new research event with its own legitimate reason. |
| Modified anything after freeze | `verify_unchanged` was called before every consuming phase and passes against the committed registry today. |
| Reordered the state machine to match the contract | Would have been a silent governance change (§2). |

---

## 6. Cross-instrument (Phase 21)

`STRAT-000002` declares `research_scope = SINGLE_INSTRUMENT` with
`instrument_scope = ("EURUSD",)`. Phase 21 applies only "if STRAT-000002
is specified for multiple instruments". It is not.

`DATASET-GBPUSD-H1-KOMO135-V1` was audited (Phase 2) and is **ELIGIBLE**,
but was not evaluated for this candidate. `verify_unchanged` raises if the
candidate's `dataset_id` changes, and
`test_09_instrument_cherry_picking_is_blocked_by_the_frozen_scope` asserts
it.

No aggregate hides a component failure here, because there is exactly one
component and it is reported directly.

---

## 7. Failure library (Phase 22)

Six categorised records preserved for `STRAT-000002`, none deleted:

| ID | Stage | Category |
|---|---|---|
| `FAIL-000003` | TRAINING | `NEGATIVE_EXPECTANCY` |
| `FAIL-000004` | OOS | `NEGATIVE_EXPECTANCY` |
| `FAIL-000005` | HOLDOUT | `NEGATIVE_EXPECTANCY` |
| `FAIL-000006` | WFA | `WFA_FAILURE` |
| `FAIL-000007` | ROBUSTNESS | `PARAMETER_FRAGILITY` |
| `FAIL-000008` | MULTIPLE_TESTING | `STATISTICAL_FAILURE` |

All tagged to `FAMILY-000004` (RSI oversold mean-reversion, EURUSD H1),
features `rsi_14`/`atr_14`, search space `SEARCHSPACE-000001`. The library
carries **no performance-metric field** by design, so holdout numbers
cannot flow back into research targeting through this channel — only
family-level failure *counts* can.

`FailureLibrary` exposes no delete, remove, purge, clear, update or pop
method; `test_23` asserts this.

---

## 8. Research accounting (Phase 26)

Recomputed independently from the registries and compared against the
stored counters:

| Counter | Recomputed | Stored | Match |
|---|---|---|---|
| Candidates generated | 2 | 2 | ✔ |
| Candidates tested | 2 | 2 | ✔ |
| Candidates rejected | 2 | 2 | ✔ |
| Candidates failed | 0 | 0 | ✔ |
| Candidates passed | 0 | 0 | ✔ |

`SEARCH_ACCOUNTING_STATUS = PASS`. Mismatches: none.

### 8.1 One documented divergence, reported not hidden

`total_strategies_surviving` = **1** (stored) versus
`TOTAL_CANDIDATES_SURVIVING` = **0** (recomputed).

These fields do not mean the same thing. The registry's counter is
**monotonic** — incremented on first entry to `STATISTICALLY_VALIDATED`,
never decremented — so it counts candidates that *ever reached* that gate.
The recomputed figure is derived from **current** state.
`STRAT-000002` passed the statistics gate and was subsequently rejected,
so it is counted by the first and not the second.

Both numbers are correct for their own definition; the field **name** is
what misleads. Enumerated in
`reports/generation4/SEARCH_ACCOUNTING_RECONCILIATION.json` under
`definitional_divergences` with both values and the reason — never
silently dropped from the comparison — and pinned in both directions by
`test_production_registry_counters_match_the_real_population`. Raised as
**OGD-2** rather than fixed here: renaming a Generation-1 registry field
during Generation 4 would itself be a silent governance change.

---

## 9. Reproducibility (Phase 28)

Two complete pipeline executions in fresh processes produced **identical
checksums for every one of the ten result artifacts**.

| Artifact | Result checksum |
|---|---|
| Development | `8deda1033eb1b261…` |
| OOS | `6e07592315f4b3bf…` |
| **PURE_HOLDOUT** | **`febe48ac8b5ffb9f…`** |
| Reusable combined | `404e92fb8d5d55a1…` |
| Walk-forward | `1e46d5ecceaba1f0…` |
| Robustness | `1399bb7eb6de9370…` |
| Cost stress | `b9015ed0446e76cf…` |
| Statistics | `14c72fc1865cdf5a…` |
| Multiple testing | `3f17e2ac6633f109…` |
| EVG | `9b949694da3592c5…` |

One real defect was found and fixed during this phase: three audit report
checksums initially included `audit_timestamp`, so they differed between
runs. A checksum with a wall clock inside it cannot be reproducibility
evidence. The timestamps are now excluded from those checksums (the
timestamp is still recorded in the artifact, just not hashed).

`test_pure_holdout_result_reproduces_from_source` re-derives the headline
holdout number from the committed CSV and the committed specification in a
fresh process and requires the result checksum to match exactly. The
number is re-derivable, not merely stored.

---

## 10. Performance optimization (Phase 29)

Runtime fell from **>10 minutes to 3m11s** through one change: the feature
matrix is computed once and sliced for all 90 walk-forward windows, 360
robustness points and 8 cost scenarios, instead of being rebuilt each time.

**This is safe only because Phase 3 proved it is.** Slicing a globally
computed feature matrix would be leakage for any non-causal feature — row
`t` of a global computation could carry information from after `t`. It is
identical to recomputing here for exactly one reason: the truncation-
invariance audit empirically established `f(data[0..T])[t] ==
f(data[0..t])[t]` on this data for these features.

That dependency is load-bearing, so it is enforced rather than remembered:
`assert_causal_slicing_verified(feature_audit.verdict)` raises unless
Phase 3 returned PASS, and the runner calls it before constructing the
cache. Every result checksum was verified identical before and after — the
optimization is provably result-preserving, which is Phase 29's actual
requirement.

---

## 11. Adversarial testing (Phase 27)

35 adversarial tests, all failing safely. Coverage of the contract's 24
required scenarios:

| # | Scenario | Test | Mechanism |
|---|---|---|---|
| 1 | Holdout access before release | `test_01` | `HoldoutSealError` |
| 2 | Holdout feature injection | `test_02` | visible frames sliced before holdout attached |
| 3 | Holdout target injection | `test_03` | evaluation cannot extend past the seal |
| 4 | Holdout used for optimization | `test_04`, `test_04b` | one-shot release; requires prior development evidence |
| 5 | Candidate mutation after freeze | `test_05` | `verify_unchanged` |
| 6 | Parameter mutation after holdout | `test_06`, `test_06b` | spec + snapshot-file tamper detection |
| 7 | Seed cherry-picking | `test_07` | structurally impossible; identical checksums |
| 8 | Window cherry-picking | `test_08` | all windows retained; no selection API |
| 9 | Instrument cherry-picking | `test_09` | frozen scope; dataset change raises |
| 10 | Feature leakage | `test_10` | truncation invariance |
| 11 | Target leakage | `test_11` | signal→entry lag exactly 1 |
| 12 | Scaler leakage | `test_12` | structurally absent; source grepped |
| 13 | Future candle access | `test_13` | perturbation invariance |
| 14 | Cost-model mutation | `test_14`, `test_14b` | changes snapshot checksum; unpriced symbol refused |
| 15 | WFA window omission | `test_15` | gapless window ids |
| 16 | Losing-window deletion | `test_16` | aggregate derived from every window |
| 17 | Counter mismatch | `test_17` | reconciliation returns FAIL |
| 18 | Fake statistical PASS | `test_18` | unrecognised verdict → BLOCKED |
| 19 | EVG without evidence | `test_19` | BLOCKED per missing item |
| 20 | EVG evidence mutation | `test_20`, `test_20b`, `test_20c` | cross-run/candidate rejected; gate cannot compute |
| 21 | Reproducibility mismatch | `test_21` | checksums differ iff run differs |
| 22 | Synthetic presented as real | `test_22` | INELIGIBLE regardless of labelling |
| 23 | Failure deletion | `test_23` | no removal path exists |
| 24 | Rescue-loop attempt | `test_24`, `test_24b` | REJECTED is terminal; changed spec → different run id |

Plus rule-parser tests asserting the engine **refuses to guess** an
unrecognised rule grammar rather than falling through to a default
interpretation.

---

## 12. Open governance decisions

**OGD-1 — Holdout ordering.** The Generation 4 contract places
PURE_HOLDOUT at Phases 11–12; the committed state machine places it after
every reusable-data gate and after `FROZEN`. Resolved *for this run* in
favour of the committed governance. A future generation should reconcile
the two deliberately rather than letting each execution pick.

**OGD-2 — `total_strategies_surviving` naming.** A monotonic
ever-reached-this-gate counter carrying a name that reads as a current-
state count. Both interpretations are now pinned by test; the field should
be renamed (e.g. `total_strategies_ever_statistically_validated`) in a
generation authorised to change Generation-1 registry schemas.

**OGD-3 — Cost figures unconfirmed.**
`ML-001-R2-CLEAN-REBUILD-SPEC.md` §17 Open Item #2 remains open. Spread,
slippage and commission are plausible retail figures, not measured ones.
Immaterial to this verdict (the strategy loses at zero cost), but it would
be material to any future candidate that survives to a marginal result.

**OGD-4 — Dataset timezone qualification.**
`provenance_status = VERIFIED_WITH_QUALIFICATION`; the UTC-5-no-DST source
convention is assumed, not confirmed. Immaterial here (no rule in
`STRAT-000002` depends on session or hour-of-day), but material to any
future session-conditional candidate.

**OGD-5 — Holdout spent on a pre-refuted candidate.** The holdout was
opened to satisfy completion criterion 10 on a candidate already refuted
on reusable data, departing from the `STRAT-000001` precedent. Future
generations should state a standing policy rather than deciding case by
case.

**OGD-6 — Hypothesis horizon vs realised horizon.** `HYP-000001` states a
12-bar forward return; the frozen candidate realises it as `max_hold=12`
with earlier stop/target exit, so ~2/3 of trades realise a shorter
horizon. Recorded, not corrected — changing the exit rule mid-validation
would be a post-hoc rule change. A future candidate could test the
unconditional horizon as its own experiment.

---

## 13. Known limitations

1. Single instrument, single timeframe, single 9-year period.
2. Cost figures unconfirmed against a real broker feed (OGD-3).
3. Swap/financing not modelled — results are **optimistic**, not
   pessimistic, in this respect.
4. Robustness grid not pre-registered (fully disclosed;
   `pre_registered = false`).
5. Multiple-testing correction has near-zero power at 2 trials.
6. Dataset timezone convention is an assumption (OGD-4).
7. Bar-level intrabar path is not modelled: when both stop and target fall
   inside one bar's range, `STOP_LOSS` takes priority — the conservative
   choice, and identical to the audited `BACKTEST-R2-001` convention.
8. Holdout Sharpe interval marginally crosses zero at 142 trades
   ([−2.763, +0.053]); the holdout verdict rests on the expectancy and
   profit-factor intervals, which do not.

---

## 14. Completion criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Candidate frozen | ✔ | `CANDIDATE_FREEZE_SNAPSHOT.json` |
| 2 | Provenance captured | ✔ | 5 checksums + `validation_run_id` |
| 3 | Dataset eligibility audited | ✔ | `DATA_ELIGIBILITY.json` — ELIGIBLE |
| 4 | Feature temporal safety audited | ✔ | `FEATURE_TEMPORAL_AUDIT.json` — PASS |
| 5 | Target leakage audited | ✔ | `TARGET_LEAKAGE_AUDIT.json` — PASS |
| 6 | Training provenance captured | ✔ | `SignalGenerationProvenance` (no model to train) |
| 7 | Model reproducibility verified | ✔ | identical checksums, fresh processes |
| 8 | Development evaluation completed | ✔ | `EVALUATION_DEVELOPMENT.json` |
| 9 | Holdout sealed until authorized release | ✔ | structural seal + `test_01`–`test_04b` |
| 10 | Holdout evaluated under frozen candidate | ✔ | `EVALUATION_PURE_HOLDOUT.json` |
| 11 | OOS completed | ✔ | `EVALUATION_OOS.json` |
| 12 | WFA completed | ✔ | 90 windows |
| 13 | All WFA windows preserved | ✔ | gapless ids; sum equals aggregate |
| 14 | Robustness completed | ✔ | 360 points |
| 15 | Cost/slippage stress completed | ✔ | 8 scenarios |
| 16 | Statistical validation completed | ✔ | block bootstrap, 10,000 iterations |
| 17 | Multiple-testing accounting completed | ✔ | DSR = 9.26 × 10⁻⁶ |
| 18 | Selection-bias audit completed | ✔ | `ML-001-R4-SELECTION-BIAS-AUDIT.md` |
| 19 | EVG consumed the complete chain | ✔ | 14/14 evidence items |
| 20 | Failure evidence preserved | ✔ | 6 records |
| 21 | Accounting independently recomputed | ✔ | PASS, divergence enumerated |
| 22 | No rescue loop | ✔ | REJECTED terminal; `test_24` |
| 23 | No mutation after freeze | ✔ | `verify_unchanged` passes today |
| 24 | No synthetic economic evidence | ✔ | `synthetic = false`; `test_22` |
| 25 | No holdout leakage | ✔ | structural seal; no pre-release access |
| 26 | Adversarial tests pass | ✔ | 35 tests |
| 27 | Fresh-process reproducibility | ✔ | all 10 checksums identical |
| 28 | Existing tests still pass | ✔ | 998 / 998 |
| 29 | Generation 5 not started | ✔ | `test_generation5_has_not_started` |

---

## 15. Final classification

`STRAT-000002` = **REJECTED** (terminal).

Not `EDGE_CANDIDATE`. Not `EVG_PASS`. Not `RESEARCH_CANDIDATE`. Certainly
not `PROVEN_EDGE` — no such state exists, and Generation 4 is historical
economic validation, not forward-market proof.

**`EDGE_STATUS = NO_EDGE_FOUND`.**

Both candidates this Factory has ever produced are now rejected. That is
not a failure of the Factory; it is the Factory working. Most trading
hypotheses are false, and a research pipeline whose value lies in
rejecting them cheaply and provably has to actually reject them. The
alternative — a pipeline that finds an edge in the first RSI rule it
tests — would be the alarming outcome.

**Generation 5 has NOT started.**

---

## Appendix A — Independent code-trace audit (Phase 30)

Performed by tracing the implementation, not by reading the generated
reports. Each row is a check that could have failed and did not.

| # | Question | Method | Result |
|---|---|---|---|
| 1 | Can anything outside `partitions.py` reach the sealed holdout rows? | grep for the name-mangled attribute across `core/` and `scripts/` | **No** — only `partitions.py` references it |
| 2 | Does the runner touch the holdout before releasing it? | line-order inspection of `run_generation4.py` | **No** — `release_holdout` at line 449, `sealed.holdout()` at 469; the only earlier accessors are `development()` and `development_and_validation()` |
| 3 | Can the EVG compute evidence? | its complete import list | **No** — imports only `hashlib`, `json`, `dataclasses`, `typing`, and two project exception/time helpers. No pandas, no numpy, no evaluation function |
| 4 | Is there any imputation or fill in the evidence path? | grep `fillna`/`ffill`/`bfill`/`interpolate` | **One**, benign: `signals.shift(delay).fillna(0)` in the robustness timing perturbation — shifts signals *forward* in time and zero-fills the leading gap. No price or feature series is ever filled |
| 5 | Is there any backward shift in the evidence path? | grep `shift(-` | **One**, unused: `close.shift(-1)` in `core/ml_r2/target_r2.py`, the ML label builder. Confirmed by grep that no Generation 4 module or the runner imports `target_r2`, `build_training_set`, or `compute_label` — the label path is not reachable from this candidate's evidence |
| 6 | Was frozen STRAT-000001 evidence modified? | `git diff` over `core/ml_r2/` and `core/features/` | **No changes at all** |
| 7 | Were the modifications to shared code additive? | `git diff` filtered to removed lines in `registry.py` and `research_ledger.py` | **Zero removed lines** — one new method, twelve new ledger event types |
| 8 | Does the frozen candidate still match its snapshot? | `verify_unchanged` against the committed registry | **Passes** (`test_frozen_candidate_was_never_mutated`) |
| 9 | Do the walk-forward windows account for the aggregate? | sum window net profits, compare to reported total | **Matches** to 1e-9 (`test_walk_forward_retained_every_window`) |
| 10 | Does EXEC-R4-001 diverge from the audited engine? | trade-for-trade parity against `run_backtest` at matched settings | **No divergence** — entry/exit times, reasons, prices, sizes and P&L all equal |

### Files changed outside the new Generation 4 package

| File | Change | Nature |
|---|---|---|
| `core/factory/registry.py` | `set_selection_bias_status()` added | Additive; requires a justification argument |
| `core/factory/research_ledger.py` | 12 Generation 4 event types added | Additive; no existing type renamed or repurposed |
| `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` | Generation 4 status notes | Additive; no Generation 1 claim altered |
| `reports/factory/*.json` | registry/ledger/failure-library state | Written by the run itself |
| `tests/test_factory_holdout_governance.py` | population expectations retargeted | Documented in the test's own docstring; invariant tightened, not relaxed |
| `tests/test_generation3_production_research.py` | two point-in-time assertions retargeted | Documented in-place; the holdout test now asserts a *stronger* property than before |

### Note on the two retargeted tests

Both asserted Generation 3's end-state — that `STRAT-000002` was still
`GENERATED` and that no candidate had ever entered `HOLDOUT_TESTED`.
Generation 4's entire purpose was to change exactly those facts.

Neither was deleted. `test_holdout_was_never_touched_by_research_discovery`
now asserts more than it did: that any holdout access belongs to
`STRAT-000002` alone, that `FROZEN` preceded it, that it carries a real
evidence reference, that it happened exactly once, and that Generation 3's
own frozen audit artifact still records zero accesses (so a
discovery-phase access could not be back-dated into it).
`test_production_registry_counters_match_the_real_population` now derives
every expected count from the population instead of writing literals, and
additionally pins the `total_strategies_surviving` divergence in both
directions.

---

## Appendix B — Test inventory

| Suite | Tests | Purpose |
|---|---|---|
| `tests/test_generation4_adversarial.py` | 35 | The 24 contract-required attack scenarios plus rule-parser refusal tests |
| `tests/test_generation4_integration.py` | 19 | Committed-artifact consistency and source-level reproducibility |
| `tests/test_generation4_execution_parity.py` | 4 | EXEC-R4-001 ≡ BACKTEST-R2-001 at matched settings; cost legs actually charged |
| **New in Generation 4** | **58** | — |
| **Full suite** | **998 passed** | up from 940 at the Generation 3 baseline |
