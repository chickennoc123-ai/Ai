# ML-001 — Research Prioritization Specification (Generation 3, Phases 12-14, 16, 19-21)

**Status**: IMPLEMENTED and exercised against REAL material.
**Code**: `core/factory/research_prioritization.py`, `core/factory/preflight.py`, `core/factory/research_budget.py`, `core/factory/research_diversity.py`
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3, §6-§7.

---

## §1. Priority Score (Phase 12)

Eight named dimensions, each in [0, 1]: `mechanism_plausibility`, `data_availability`, `testability`, `novelty`, `expected_information_gain`, `computational_cost_efficiency`, `lineage_quality`, `research_diversity_contribution`. The total is the unweighted mean of the dimensions — the decomposition IS the score, so every ranking is explainable dimension-by-dimension. `PriorityScore.to_dict()` carries the sentence "research scheduling priority — NOT economic edge probability" in its own payload; **no dimension named or resembling expected profitability exists**, and the score is a scheduling aid only.

## §2. Expected Information Value (Phase 13)

`expected_information_value(novelty, testability, computational_cost_efficiency)` — a transparent mean of three [0, 1] inputs. Verified against the contract's own worked example: a novel, moderately-costed hypothesis B outranks a cheap, 100-times-tested hypothesis A (test `test_information_value_prioritizes_novel_cheap_testable_work`). A research-efficiency mechanism, not a profit predictor.

## §3. Novelty from Knowledge

`novelty_from_knowledge(k) = 1 / (1 + prior_tests + prior_failures)` — deterministic, monotone, no hidden tunables. An untested family scores 1.0; a 100-times-tested family scores < 0.02.

## §4. The Feedback Firewall (Phase 16)

`ResearchKnowledge` is the ONLY sanctioned shape for historical feedback: exactly three fields (`family_prior_test_count`, `family_prior_failure_count`, `family_member_count`), all non-negative integers, enforced at construction (a float is rejected; an unknown keyword like `holdout_return` is a `TypeError`). **"This family has been tested extensively" can flow in; "this family lost money on holdout, so alter parameters" structurally cannot** — there is no field to carry it. Adding one would be an explicit governance change (documented here as requiring authorization), not a refactor. Production usage: `HYP-000001`'s priority used `family_prior_test_count=1` (the STRAT-000001 campaign as a COUNT), and `HYP-000002`'s synthesis used the internal parent solely as horizon-coverage knowledge — both recorded in the ledger with that distinction stated.

## §5. Pre-flight (Phase 14)

`run_preflight()` — nine named cheap checks before any expensive evaluation: `DATA_AVAILABLE`, `FEATURE_AVAILABLE`, `TEMPORAL_SAFE`, `TARGET_DEFINED`, `MINIMUM_HISTORY` (≥ 5,000 usable rows), `COST_MODEL_AVAILABLE`, `SEARCH_SPACE_VALID` (incl. explicit size budget), `HYPOTHESIS_ELIGIBLE` (full Generation 2 quality gates, reused not reimplemented), `DUPLICATE_STATUS` (exact statement duplicates fail; family co-membership — a parameter variant — deliberately does not). Failures return as an exact named list AND are recorded to the Failure Library with mapped categories: early rejection contributes information, it never discards it. Production: `HYP-000001` passed pre-flight before `STRAT-000002` was generated.

## §6. Budgets & Kill Switch (Phases 20-21)

`ResearchBudget` (five required positive-integer caps: sources, hypotheses, candidates, search-space size, candidates-per-family; an unlimited budget is unrepresentable) + `BudgetTracker` (check-then-increment: the exceeding charge raises and is never applied, so recorded usage never overshoots). `ResearchKillSwitch`: persistent trip-once state for `CANDIDATE_EXPLOSION`/`SEARCH_SPACE_EXPLOSION`/`DUPLICATE_EXPLOSION`/`RESOURCE_EXHAUSTION`/`LEDGER_FAILURE`/`PROVENANCE_FAILURE`/`ACCOUNTING_MISMATCH`; fails closed on a corrupted state file; **no programmatic reset API exists** (clearing a safety stop is a manual, visible act on the state file); a trip blocks only NEW generation — every already-recorded registry entry is preserved (tested). Production ingestion ran under `ResearchBudget(10, 10, 2, 1000, 2)`, and the production kill switch exists un-tripped at `reports/factory/research_kill_switch.json`.

## §7. Diversity (Phase 19)

`compute_diversity_report()` — read-only counts by source type/market/timeframe/origin/feature family/hypothesis family plus max-share concentration flags (suppressed for trivially small populations). Diversity is measured to DETECT concentration and single-ecosystem over-reliance; the report's own payload states it is not itself optimized.
