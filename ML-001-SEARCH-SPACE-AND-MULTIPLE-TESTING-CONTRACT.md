# ML-001 — Search-Space & Multiple-Testing Contract

**Status**: infrastructure specification. No new symbol, feature, or hypothesis has been added under this contract — it documents the accounting mechanism now in place (`core/factory/registry.py`, `core/factory/hypothesis.py`) and the discipline required when the Factory does eventually scale.
**Date**: August 18, 2026
**Referenced by**: `ML-001-STRATEGY-FACTORY-SPEC.md` §7-§8, §12.

---

## §1. The principle this contract exists to enforce

> More data, more symbols, more indicators, and more external hypotheses are **not automatically more edge**. They increase the **search space**, and therefore potentially increase **overfitting risk**, **selection bias**, and **multiple-testing burden**. The architecture must make this visible rather than hiding it.

Every mechanism below exists to make that visible — none of them make the Factory produce better strategies; they make it **honest about how hard it looked** before producing whichever one it did.

---

## §2. Counters — what "how many were tried" actually means

`StrategyRegistry.search_history_summary()` (`reports/factory/strategy_registry.json`):

```
total_strategies_generated   -- every candidate ever registered, pass or fail
total_strategies_tested      -- reached DATA_VALIDATED (leakage-audited, real data)
total_strategies_rejected    -- terminal REJECTED
total_strategies_failed      -- terminal FAILED (distinct from REJECTED: a
                                 process/technical failure vs. a substantive
                                 evidence-based rejection — see registry.py docstrings
                                 for exactly which terminal each caller should use)
total_strategies_surviving   -- reached STATISTICALLY_VALIDATED
total_strategies_passed      -- reached RESEARCH_CANDIDATE (i.e. passed EVG)
```

`HypothesisRegistry.summary()` (`reports/factory/hypothesis_registry.json`, a **separate** file — §5):

```
total_hypotheses_ingested    -- every HypothesisRecord ever registered
by_evidence_level             -- breakdown, e.g. {"UNVALIDATED_CLAIM": 4,
                                  "CANDIDATE_TESTED_NO_EDGE": 1}
```

**Current real values, as of this document** (both directly queryable, not asserted from memory):

```
total_hypotheses_ingested  = 0   (HypothesisRegistry has never been used)
total_strategies_generated = 1   (STRAT-000001)
total_strategies_tested    = 1
total_strategies_rejected  = 1
total_strategies_passed    = 0
```

Both counters are asserted directly against the on-disk production files by `tests/test_factory_holdout_governance.py::TestMultipleTestingAccountingIsHonest` and `tests/test_factory_hypothesis.py::TestNoHypothesesActuallyIngestedInProduction`, so this table cannot silently drift from reality without a test failing.

---

## §3. Search-space dimensions — what "how hard did it look" actually means

A count of candidates alone can understate risk (100 candidates that are all trivial variations of one idea is a smaller true search space than 10 candidates each testing a genuinely different hypothesis). `StrategyRegistry.set_search_space()` therefore records five explicit, separately-inspectable dimensions in addition to the summary counters:

```
feature_search_space     -- which feature sets/combinations were considered
parameter_search_space   -- which hyperparameter/rule-parameter grids were considered
symbol_search_space      -- which instruments were considered
timeframe_search_space   -- which timeframes were considered
model_search_space       -- which model classes/architectures were considered
```

Each defaults to `{}` (not populated) until a caller explicitly declares it — an empty dict is a true statement ("this dimension was never varied"), not a placeholder. `core.factory.generator.SEARCH_SPACE` is the one real, currently-populated example in this repository: a 5×6×4 grid over `stop_loss_atr_multiple`/`take_profit_atr_multiple`/`max_hold_bars` for the single ML-001-R2 hypothesis — recorded verbatim into `generator_parameters` on every generated candidate, so the grid a candidate was drawn from is never reconstructed after the fact from the candidate's own chosen values.

**Entering `MULTIPLE_TESTING_REVIEWED` requires `set_search_space()` to have been called at all** (`MultipleTestingAccountingRequiredError` otherwise, `ML-001-STRATEGY-FACTORY-SPEC.md` §7) — this does not by itself require every one of the five dimensions to be populated (a candidate testing one fixed feature set on one fixed symbol legitimately has empty `feature_search_space`/`symbol_search_space`), only that the accounting mechanism was actually engaged, not skipped.

---

## §4. A different ID is not statistical independence

`StrategyCandidate.parent_candidate_id` (set by `derive_new_version()`) and `HypothesisRecord.candidate_ids` (set by `link_candidate()`) together mean a family of related candidates — variants of the same underlying idea, whether derived candidate-to-candidate or hypothesis-to-candidate — remains traceable as a family, not as N independent data points. A future EVG review or statistical-significance calculation that needs to know "how many genuinely independent hypotheses does this candidate's apparent success need to be corrected against" must be able to walk `parent_candidate_id` back to the family's root and `hypothesis_id` back to the originating claim, rather than treating every `STRAT-NNNNNN` as if it arose from an unrelated, independent search.

This contract does not itself implement a multiple-testing *correction* (e.g. Bonferroni, false-discovery-rate control) — `selection_bias_status` exists precisely to record, per §2, whether one has been applied (`"MULTIPLE_TESTING_CORRECTED"`) or explicitly not (`"DISCLOSED_NO_CORRECTION_APPLIED"`), starting from `"UNACCOUNTED"` and never silently defaulted to `"PASS"`. With `total_strategies_tested = 1`, there is currently nothing to correct for — `STRAT-000001` is the entire population, and `selection_bias_status` correctly remains `"UNACCOUNTED"` rather than being marked passing.

---

## §5. Why hypothesis-intake and strategy-testing accounting are separate files

`reports/factory/strategy_registry.json` and `reports/factory/hypothesis_registry.json` (the latter not yet created) are deliberately independent JSON files, not a single combined store. A hypothesis can be captured and never produce a candidate (abandoned as impractical after formalization, for instance); a candidate can exist without a `hypothesis_id` at all (directly specified, like `STRAT-000001`, from `ML-001-R2-CLEAN-REBUILD-SPEC.md` rather than an ingested external claim). Merging the two stores would force every hypothesis to pretend it produced a candidate, or every candidate to pretend it came from a formally captured hypothesis, neither of which is true today and neither of which should be forced to become true merely for storage convenience.

---

## §6. What this contract does not do

- Does not add a new symbol, feature, indicator, or model class to any search space.
- Does not ingest a hypothesis or populate `hypothesis_search_space`/`total_hypotheses_ingested` beyond its current real value of 0.
- Does not implement a formal multiple-testing correction procedure — only the accounting infrastructure that a future correction would consume.
- Does not change `STRAT-000001`'s recorded counters or history — every figure in §2 was read from the existing, already-committed registry, not recomputed or adjusted for this document.
