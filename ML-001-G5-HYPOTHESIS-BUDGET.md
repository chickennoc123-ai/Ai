# ML-001 — Generation 5, Phase 2: Hypothesis/Candidate Budget

**Date**: August 19, 2026
**Status**: `HYPOTHESIS_BUDGET_STATUS = DECLARED_NOT_SPENT`

---

## 1. Why a new dataclass, not an extension of Generation 3's `ResearchBudget`

`core.factory.research_budget.ResearchBudget` is a frozen dataclass with five required, no-default positive-integer fields, consumed by existing Generation 3 tests. Adding the two Generation-5-specific fields (`max_research_retries`, `max_research_branches`) would either break every existing caller or require a default — and a defaulted budget limit is exactly the "silent generous default" this project's `-1`-is-not-representable budget philosophy forbids. `core.factory.generation5_budget.GenerationFiveBudget` is therefore a new, self-contained dataclass, declared once and persisted (`reports/factory/generation5_budget.json`).

## 2. Declared budget

Declared **before** any Generation 5 hypothesis or candidate was generated, via `GenerationFiveBudgetStore.declare()`:

| Field | Value |
|---|---|
| `max_new_hypotheses` | 3 |
| `max_new_candidates` | 1 |
| `max_candidates_per_family` | 1 |
| `max_search_space_size_per_hypothesis` | 50 |
| `max_research_retries` | 2 |
| `max_research_branches` | 3 |

**Justification (recorded verbatim in the store):** Generation 5's mission is instrumentation, research memory, and controlled discovery — not volume search. Prior generations tested 2 candidates total; this budget permits at most 1 more. `max_candidates_per_family = 1` forecloses re-testing minor variants of a refuted family (Non-Negotiable Principle 10). `max_search_space_size_per_hypothesis = 50` forecloses a brute-force grid (design doc's own warning against generating 500 RSI variants).

## 3. Immutability

`GenerationFiveBudgetStore.declare()` refuses a second declaration unless `allow_redeclare=True` is passed with its own justification — pinned by `tests/test_generation5_adversarial.py::test_budget_redeclare_without_governance_flag_is_refused`. No redeclaration occurred this generation.

## 4. Usage

```
{"declared": true, "usage": {"new_hypotheses": 0, "new_candidates": 0}, "family_candidate_usage": {}, "exhausted": {}}
```

**Zero spent.** See `ML-001-G5-GENERATION-5-REPORT.md` §"Candidate generation decision" for why: Phase 12 found `HYP-000003` has undocumented (`SILENT_HORIZON_DRIFT`) horizon reuse, Phase 3-4 found `HYP-000002` is a close variant of the already-refuted `HYP-000001` family, and Phase 22's holdout-independence question (where would a new candidate's independent evaluation data come from, given `PURE_HOLDOUT` has been consumed exactly once in this Factory's history) has no answer this session can supply without inventing one. Recorded as `OPEN_GOVERNANCE_DECISION` OGD-3, not resolved silently. Budget headroom remaining is available to a future generation once these are addressed.
