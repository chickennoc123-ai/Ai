# ML-001 Strategy Factory — Canonical Specification

**Status**: CANONICAL — this document is the authoritative source for every "roadmap Section N" reference in `core/factory/*`. It supersedes the informal, uncommitted "roadmap Sections 6/16/19/20" previously cited in code docstrings (see `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` §2 for how that gap was discovered — no such document was ever found in this repository).
**Date**: August 18, 2026
**Scope**: the Strategy Factory (`core/factory/*`) — candidate lifecycle, state machine, evidence requirements, holdout policy, versioning, rejection semantics, multiple-testing/search-space accounting, EVG prerequisites, paper/live promotion, and multi-symbol/multi-feature/multi-hypothesis expansion readiness. Does not define any specific strategy's trading rules — `ML-001-R2-CLEAN-REBUILD-SPEC.md` remains authoritative for ML-001-R2's own entry/exit/feature/target/cost logic; this document governs the *process* every candidate (ML-001-R2 or any future one) must pass through.

Every section number below is stable — code and other documents cite it, and citations are only ever added to, never renumbered, once this document ships (a section may gain sub-numbered clarifications, e.g. §4.1, without disturbing existing citations elsewhere).

---

## §1. Purpose & Scope

The Strategy Factory exists to let this project generate, test, and (rarely) accept trading strategy candidates at scale without secretly inflating the odds of a false positive. Its two obligations, in order of priority:

1. **Never let a candidate reach production on fabricated, cherry-picked, or holdout-contaminated evidence.**
2. **Make the true cost of search — how many hypotheses, symbols, features, and parameter combinations were tried — impossible to hide**, even from the researchers running it.

Everything else in this document exists in service of those two obligations.

---

## §2. Candidate Lifecycle & State Machine

Implemented in `core/factory/state_machine.py` (`CandidateState`, `_FORWARD_SPINE`) and `core/factory/candidate.py` (`StrategyCandidate`, `StrategyCandidateSpec`).

A candidate is a `(candidate_id, version)` pair with an immutable `StrategyCandidateSpec` (entry rule, exit rule, features, timeframe, direction, stop-loss, take-profit, max-hold, position sizing, transaction-cost model — every field required, `CandidateSpecError` on omission) and a `state` that advances along one linear spine:

```
GENERATED → DATA_VALIDATED → TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED
→ COST_TESTED → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED → FROZEN
→ HOLDOUT_TESTED → EVG_REVIEW → RESEARCH_CANDIDATE → PAPER_VALIDATION → LIVE_CANDIDATE → RETIRED
```

Every state except `LIVE_CANDIDATE` may additionally transition to `REJECTED` or `FAILED` (both terminal) — a candidate can fail at any gate, and doing so is a normal, expected, scientifically valid outcome (`STRAT-000001`'s `TRAINED → REJECTED` is the working example). `LIVE_CANDIDATE`'s only forward motion is `RETIRED`. Illegal transitions (skipping a gate, going backward, or acting on a terminal state) raise `IllegalStateTransitionError` and leave the candidate's state and history untouched.

`_ALLOWED_TRANSITIONS` is derived mechanically from `_FORWARD_SPINE`'s order — there is no separate hand-maintained transition table to drift out of sync with the declared spine.

---

## §3. Evidence Requirements Per Gate

| Gate | What must be true to enter it |
|---|---|
| `DATA_VALIDATED` | Leakage/provenance audit passed on real data for every declared instrument (§12). |
| `TRAINED` | Model fit on `DEVELOPMENT` only, frozen hyperparameters recorded, reproducibility checked. |
| `OOS_TESTED` | Out-of-sample predictions generated on `VALIDATION`, never `PURE_HOLDOUT`. |
| `WFA_TESTED` | Full walk-forward evaluation (rolling windows, fresh model per window) on `VALIDATION`. |
| `ROBUSTNESS_TESTED` | Sensitivity to reasonable parameter/data perturbations checked. |
| `COST_TESTED` | Cost-sensitivity classified (baseline vs. stressed/zero cost) without changing the cost model to force a result. |
| `STATISTICALLY_VALIDATED` | Trade-level significance (e.g. bootstrap CI, t-test) computed and reported honestly, including unfavorable results. |
| `MULTIPLE_TESTING_REVIEWED` | `StrategyRegistry.set_search_space()` has been called for this registry — enforced in code (`MultipleTestingAccountingRequiredError`), not just documented (§7). |
| `FROZEN` | Spec is now finalized for holdout; already immutable since `OOS_TESTED` (§5), this is the explicit "about to touch holdout" declaration. |
| `HOLDOUT_TESTED` | `PURE_HOLDOUT` accessed exactly once, for `FINAL_EVALUATION` only (§4). |
| `EVG_REVIEW` | Reachable only from `HOLDOUT_TESTED` — no path exists that reaches EVG review without holdout having actually occurred (§9). |

A candidate may be rejected at any of these gates without ever reaching a later one — most candidates are expected to end at `REJECTED`, not at `LIVE_CANDIDATE`.

---

## §4. Holdout Policy

**`PURE_HOLDOUT` is the final sealed historical evaluation.** Every reusable-data gate — OOS, walk-forward, robustness, cost stress, statistics, and multiple-testing accounting — completes *before* the state machine allows entry into `HOLDOUT_TESTED`, never after. This is a change from this project's earlier, ambiguous state machine (which placed `HOLDOUT_TESTED` immediately after training) — formalized here, per explicit product-owner direction, superseding that ambiguity (full history and the option analysis that preceded this decision: `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md`).

Rules, all mechanically enforced (not merely documented):

1. A candidate may be rejected at any earlier stage without ever touching `PURE_HOLDOUT` (`X → REJECTED`/`FAILED` legal from every non-terminal, pre-`LIVE_CANDIDATE` state — §2).
2. `PURE_HOLDOUT` is opened **exactly once** per candidate version (`core.provenance_enforcement.ProvenanceEnforcer` tracks `holdout_accessed`; the only permitted action against `DataState.PURE_HOLDOUT` is `FINAL_EVALUATION` — `TRAINING`/`SELECTION` raise `DataStateViolationError`).
3. Once a candidate accesses `PURE_HOLDOUT` (enters `HOLDOUT_TESTED`), that candidate **version** is permanently frozen with respect to that holdout. Its spec has in fact been immutable since `OOS_TESTED` already (§5) — `HOLDOUT_TESTED` adds no new mutability rule, it is simply the point past which mutability was never available to begin with.
4. **Never**: `candidate v1 → holdout → modify v1 → retest same holdout`. There is no code path in `core/factory/registry.py` that mutates a registered candidate's `spec` in place — `StrategyCandidateSpec` is a frozen dataclass, and `StrategyRegistry.assert_mutation_allowed()` additionally blocks swapping in a new spec object from `OOS_TESTED` onward.
5. **Instead**: `candidate v1 → holdout → PASS/FAIL` (terminal for that version), and any modified hypothesis becomes `candidate v2` via `StrategyRegistry.derive_new_version()` — a brand-new `candidate_id`, linked via `parent_candidate_id`, never a mutation of `v1`'s own record.

---

## §5. Versioning & Immutability

`StrategyCandidateSpec` is `@dataclass(frozen=True)` — in-place field mutation raises `dataclasses.FrozenInstanceError` unconditionally, regardless of registry state. On top of that, `StrategyRegistry._FROZEN_OR_LATER` (currently: `OOS_TESTED` and every state after it) blocks a caller from swapping in a *different* spec object onto an already-registered candidate — `assert_mutation_allowed()` raises `FrozenCandidateMutationError`.

**"STRAT-001 v1 → FAILED; STRAT-001 v2 → NEW CANDIDATE. Never mutate v1 into v2."** The only sanctioned path from an existing candidate to a modified one is `StrategyRegistry.derive_new_version(parent_candidate_id, new_spec, ...)`, which mints a fresh `candidate_id`, sets `parent_candidate_id` on the child, and leaves the parent's own record — including its full `history` — completely untouched.

---

## §6. Rejection Semantics

`REJECTED` and `FAILED` are terminal states (`TERMINAL_STATES`, `is_terminal()`): zero outgoing transitions are ever legal from them, enforced by the state machine (`IllegalStateTransitionError` on any attempt) and locked in as a regression test (`tests/test_factory_holdout_governance.py::TestRejectedCandidateImmutability`).

**The rejected population is part of the scientific record**, not a set of records to prune. `StrategyRegistry.rejected_population()` returns every `REJECTED`/`FAILED` candidate, each with its full, append-only `history` (state, timestamp, reason, evidence reference for every transition, including the rejection itself) preserved exactly as originally written. `StrategyRegistry.reject()` is a convenience wrapper that records `failed_phase` and `reason` structurally, not just as free text buried in a log.

---

## §7. Multiple-Testing & Search-Space Accounting

**Core principle**: more data, more symbols, more indicators, and more external hypotheses are not automatically more edge — they increase the search space, and therefore potentially increase overfitting risk, selection bias, and multiple-testing burden. The architecture's job is to make this visible, not to hide it.

`StrategyRegistry.search_history_summary()` (backed by `_search_history`, persisted in `reports/factory/strategy_registry.json`) tracks:

```
total_strategies_generated     ) "TOTAL_CANDIDATES_GENERATED" in task vocabulary --
total_strategies_tested        )  "strategy" and "candidate" are the same concept in
total_strategies_rejected      )  this codebase; these are not duplicated under a
total_strategies_failed        )  second name, only documented here as synonyms.
total_strategies_surviving     )
total_strategies_passed        )
total_hypotheses_ingested        -- count of HypothesisRecords ever registered in
                                     core.factory.hypothesis.HypothesisRegistry that
                                     were intended to feed this Strategy Registry
                                     (incremented via record_hypothesis_ingested();
                                     the two registries are independent files -- see §10)
feature_search_space             -- explicit dict, set via set_search_space()
parameter_search_space           -- explicit dict
symbol_search_space              -- explicit dict
timeframe_search_space           -- explicit dict
model_search_space               -- explicit dict
search_space, search_method,
parameter_search_count,
model_search_count,
selection_criteria               -- pre-existing summary-level fields, unchanged
selection_bias_status            -- starts "UNACCOUNTED"; must be explicitly set,
                                     never silently defaulted to "PASS"
```

`set_search_space()` must be called — recording at minimum `search_method`, `parameter_search_count`, `model_search_count`, `selection_criteria`, and optionally each of the five explicit `*_search_space` dicts — **before** a candidate may enter `MULTIPLE_TESTING_REVIEWED` (`core.factory.registry.MultipleTestingAccountingRequiredError` otherwise). This makes the accounting a precondition of the gate named after it, not a label applied after the fact with nothing behind it.

**Related-candidate traceability**: a candidate derived from another via `derive_new_version()` carries `parent_candidate_id`, so a family of variants sharing one origin remains linkable and cannot silently present as N independent, statistically-unrelated data points merely because each has a different `candidate_id`. A candidate originating from an ingested external hypothesis additionally carries `hypothesis_id` (§10), extending traceability back past the Factory's own candidate-to-candidate lineage to the original source claim.

---

## §8. Search-History Accounting Fields — canonical reference

The full, current field list for `search_history_summary()` is defined in code at `core.factory.registry._empty_search_history()` and is not duplicated verbatim here to avoid the two falling out of sync — §7 above lists every field name and its purpose; that function is the single source of truth for defaults and persistence shape. Loading an older registry file merges its contents onto current defaults (`StrategyRegistry._load()`), so a field added after a given registry was first written still appears, correctly defaulted, without a migration step.

---

## §9. EVG Prerequisites

`EVG_REVIEW` is reachable from exactly one state: `HOLDOUT_TESTED`. No other state in the spine may transition directly into `EVG_REVIEW` — this is enforced structurally by the linear `_FORWARD_SPINE` (skipping straight to `EVG_REVIEW` from any earlier gate raises `IllegalStateTransitionError`) and locked in as a regression test (`tests/test_factory_holdout_governance.py::TestEVGOnlyAfterRequiredEvidence`). An EVG reviewer reading a candidate's `history` can therefore trust, without cross-referencing anything else, that every earlier gate — OOS, WFA, robustness, cost, statistics, multiple-testing accounting, freeze, and holdout — genuinely occurred in that order before the review record was created.

---

## §10. Hypothesis Sources — Intake Discipline

Full contract: `ML-001-HYPOTHESIS-SOURCE-CONTRACT.md`. Summary: `core.factory.hypothesis.HypothesisRecord`/`HypothesisRegistry` provide a place to capture a trading idea from any external source (user research, academic paper, book, website, public strategy description, YouTube, other documented source) — but a captured claim can never assert more than `UNVALIDATED_CLAIM` at capture time; only real testing through the Strategy Registry (§2-§9) can advance a hypothesis's `evidence_level` toward anything resembling validated. The `HypothesisRegistry` is a **separate file and separate class** from `StrategyRegistry` specifically so that source provenance and tested economic evidence are never persisted in the same record, making it structurally harder to accidentally conflate "someone claimed this" with "this was shown to work."

---

## §11. Paper-Forward Promotion & Live-Promotion Rules

`EVG_REVIEW → RESEARCH_CANDIDATE` is the only path into paper/live consideration — a candidate that has not passed the full gate sequence in §2-§9, including a genuine holdout evaluation, cannot reach `RESEARCH_CANDIDATE` by construction. From there: `RESEARCH_CANDIDATE → PAPER_VALIDATION → LIVE_CANDIDATE`, each a single forward step, no skipping. `PAPER_VALIDATION` may also transition directly to `RETIRED` (a paper run abandoned without ever reaching live, still with its full history preserved — not deleted). `LIVE_CANDIDATE`'s only forward motion is `RETIRED` — a live or paper candidate that stops being used must be explicitly retired, never silently dropped, preserving the audit trail. No candidate in this project has yet reached `EVG_REVIEW`; §2-§9 are process guarantees for whenever one does, not a description of anything that has happened yet.

---

## §12. Multi-Symbol / Multi-Feature / Multi-Hypothesis Expansion Readiness

**This document authorizes the *architecture* for expansion, not any actual expansion.** No new symbol, indicator, or ingested hypothesis is added by this specification or by the code changes that accompany it.

**Instruments as explicit provenance metadata** (`core.factory.candidate.DatasetProvenanceRecord`, `StrategyCandidate.instrument_universe`): a candidate's `instrument_universe` is a tuple of per-instrument records — never a bare symbol string — each carrying `symbol`, `timeframe`, `dataset_id`, `dataset_checksum`, `source`, `coverage_start`/`coverage_end`, `timezone`, `cost_model_reference`, and free-form `symbol_specific_assumptions` (e.g. pip value, session hours, spread regime). **A strategy tested on EURUSD is never automatically assumed valid on GBPUSD, USDJPY, AUDUSD, USDCAD, XAUUSD, XAGUSD, or any other instrument** — each instrument in a candidate's universe requires its own dataset provenance, and by extension (§3) its own leakage audit, training, OOS/WFA evaluation, and holdout access before any claim can be made about it specifically. `STRAT-000001`'s real per-symbol provenance (EURUSD and GBPUSD, evaluated and rejected independently, per `ML-001-STRAT-000001-FAILURE-FORENSIC-REPORT.md` §E) is the existing precedent this structure generalizes, not a new requirement invented for this document.

**Features** (existing, unmodified: `core/features/fe_r2_001.py`'s `FEATURE_ORDER`, versioned feature schema hash): every feature already carries a deterministic definition, timestamp semantics (`t ≤ current` only, independently verified via the future-injection check in every leakage audit performed so far), a version (`FE-R2-001`/`FE-R2-003`), and provenance. A candidate's `spec.features` tuple plus its training run's recorded `feature_schema_hash` (already present in `RunProvenance`, `core/ml_r2/walkforward_r2.py`) together let the Factory answer, for any candidate, exactly which features were available to it — this document does not add new features (price/return, volatility, momentum, trend, mean-reversion, volume/order-flow, technical indicators, regime features), only confirms the existing mechanism generalizes to them when they are added.

**External hypotheses**: see §10. No hypothesis has been ingested.

**Making search space visible, not more edge**: expanding along any of these axes (§7) increases `symbol_search_space`, `feature_search_space`, and `total_hypotheses_ingested` — each an explicit, queryable field, not an implicit multiplier hidden inside a bigger candidate count. A future audit asking "how many symbol × feature × hypothesis combinations were tried before this one candidate reached `RESEARCH_CANDIDATE`" must be answerable directly from `search_history_summary()`, without needing to reconstruct it from scratch.
