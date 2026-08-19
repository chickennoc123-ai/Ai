# ML-001 — Governance Closure (post-Generation 4)

**Date**: August 19, 2026
**Scope**: closes the two open governance decisions Generation 4 recorded rather than resolved (`ML-001-GENERATION-4-REPORT.md` §12), plus one epistemic-chain gap that Generation 4 did not record at all and that this closure found.
**Status**: `OPEN_GOVERNANCE_DECISIONS = 0`.

---

## 0. Baseline verified, not assumed

Per this project's standing discipline, the reported baseline was re-derived on disk before any change: branch `claude/ea-factory-pro-system-bc9jaa`, commit `2d1cc4d`, clean worktree, **998 tests collected and passing**, `STRAT-000001 = REJECTED`, `STRAT-000002 = REJECTED` (full spine walked: `GENERATED → DATA_VALIDATED → TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED → COST_TESTED → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED → FROZEN → HOLDOUT_TESTED → EVG_REVIEW → REJECTED`), EVG verdict `FAIL`. The user-supplied summary matched the repository on every checkable point.

---

## 1. OGD-1 — Holdout ordering — **CLOSED**

**The conflict.** Generation 4's execution contract numbered `PURE_HOLDOUT` at its Phases 11–12; the committed state machine places `HOLDOUT_TESTED` after every reusable-data gate *and* after `FROZEN`. The G4 run deferred to the committed governance and flagged the divergence rather than picking silently — the correct call.

**Resolution: the committed state machine is the single authority.** It already encodes the holdout-last policy formally adopted in `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` §0 (Option C), which was itself an explicitly authorized product-owner decision. A phase-numbering convention inside one generation's execution contract is a description of intended work order, not a governance instrument, and cannot override it. **No code change was required** — the state machine already enforced the right thing; what was missing was a durable statement that it *is* the authority.

**What changed:** nothing in `core/factory/state_machine.py`. Four assertions now pin the authority permanently (`tests/test_generation5_governance_closure.py::TestOGD1HoldoutOrderingIsSettled`): `HOLDOUT_TESTED` is reachable from exactly `["FROZEN"]`; every earlier gate is *proven* unable to jump to it; `EVG_REVIEW` is reachable from exactly `["HOLDOUT_TESTED"]`; and the real `STRAT-000002` history is checked to have followed that order. A future generation cannot now execute a different order and describe it as a reconciliation without a test failing.

## 2. OGD-2 — `total_strategies_surviving` naming — **CLOSED**

**The problem.** A monotonic *ever-reached-this-gate* counter carrying a name that reads as a *current-state* count. After G4 the registry honestly reported `surviving = 1` while **zero** candidates actually survived — both numbers correct for their own definition, the name the only thing wrong. G4 deferred the fix because renaming a Generation-1 registry field mid-generation would itself have been a silent governance change; governance closure is the phase authorized to make it.

**Resolution: renamed to `total_strategies_ever_statistically_validated`**, which says what the number is. Semantics and value are unchanged — it still increments once on first entry to `STATISTICALLY_VALIDATED` and is still never decremented. For a current-state answer, `core.factory.research_accounting`'s `TOTAL_CANDIDATES_SURVIVING` remains the correct field; it is derived from live state and correctly reports `0`.

**Migration, and why it was necessary.** A naive rename would have been *data-destroying*: `StrategyRegistry._load()` merges stored history onto defaults, so a pre-rename file's real count would have been dropped and the new key silently defaulted to `0`. `_load()` now carries the legacy key's value forward and retires the stale name, so exactly one name for the number survives. If both keys are somehow present the already-migrated key wins (the legacy one is by definition the older writer's value).

The production registry was migrated and persisted, with candidate states and every counter asserted identical before and after — a schema write, not a data change. Four tests pin the rename, the no-data-loss migration, the both-keys case, and monotonicity-under-rejection.

## 3. Epistemic-chain gap — found during closure, **CLOSED**

Not in G4's open-items list; found by walking the lineage rather than reading the report.

Generation 4 terminally rejected the *candidate* and recorded six candidate-level failure entries — but never propagated the verdict **up** the lineage chain. `HYP-000001` was still `ELIGIBLE` / `CANDIDATE_GENERATED` and `CLAIM-000001` still `FORMALIZED`, even though the hypothesis's own **pre-registered** falsification condition had been met outright:

> *"conditional expectancy ≤ 0 after realistic costs on out-of-sample walk-forward, OR confidence interval straddles economically irrelevant values, OR effect absent OOS"*

Observed: OOS expectancy **−19.4269**/trade, holdout expectancy **−27.8089**/trade with a 95% block-bootstrap CI of **[−45.22, −6.00]** (does not straddle zero), WFA net **−18,557.81** over 90 windows. The first disjunct is satisfied on its own terms.

Left uncorrected, the Factory would have carried a hypothesis marked *eligible for research* whose refuting evidence was already committed — the precise condition under which duplicated research happens.

**Closed by** advancing `HYP-000001` through the legal path `ELIGIBLE → TESTED → REFUTED` (evidence level `CANDIDATE_TESTED_NO_EDGE`) and `CLAIM-000001` through `FORMALIZED → TESTED → REFUTED`, each with the evidence reference recorded, plus `HYPOTHESIS_REJECTED` / `CLAIM_STATUS_CHANGED` ledger events. Detail: `ML-001-GENERATION-4-POST-MORTEM.md` §5.

**Scope discipline on the claim.** `CLAIM-000001` is the source's verbatim RSI 70/30 lore. Marking it `REFUTED` records *our* verification status of the **tested operationalisation** — EURUSD H1, 12-bar horizon, frozen cost model — not a universal refutation. The source stated no instrument, timeframe, horizon or cost model, so other operationalisations remain untested; the claim text itself is unchanged and unchangeable (frozen dataclass).

---

## 4. Closure status

```
OGD-1 (holdout ordering)        = CLOSED (authority affirmed + pinned by test; no code change)
OGD-2 (counter naming)          = CLOSED (renamed, migrated without data loss, tested)
EPISTEMIC-CHAIN GAP             = CLOSED (hypothesis + claim REFUTED on pre-registered terms)

STRAT-000001                    = REJECTED (terminal, unchanged)
STRAT-000002                    = REJECTED (terminal; holdout consumed exactly once, ever)
EDGE_STATUS                     = NO_EDGE_FOUND
SELECTION_BIAS_STATUS           = STATISTICAL_CORRECTION_APPLIED_LOW_POWER
                                   (honest: with 2 trials the correction is near-uninformative,
                                    as G4's own MULTIPLE_TESTING.json states)
OPEN_GOVERNANCE_DECISIONS       = 0
```

## 5. What this closure deliberately did **not** do

- Did not alter any Generation 4 economic result, artifact, or checksum.
- Did not revive, re-test, or re-parameterise either rejected candidate — both are terminal, and the state machine proves no path out.
- Did not re-open `PURE_HOLDOUT`; it has been consumed exactly once in the Factory's entire history, asserted by test.
- Did not upgrade `SELECTION_BIAS_STATUS`, weaken any gate, or delete any failure record.
