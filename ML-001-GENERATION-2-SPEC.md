# ML-001 Strategy Research Factory — Generation 2 Canonical Specification

**Status**: CANONICAL for Generation 2. Incorporates Generation 1 (`ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md`, `ML-001-STRATEGY-FACTORY-SPEC.md`) by reference; does not restate or invalidate it.
**Date**: August 19, 2026

---

## §1. Mission

Build the machinery that can systematically generate, trace, classify, count, and eventually test hypotheses without losing provenance or research history. **Generation 2 is not a strategy-performance phase.** No edge is claimed by anything built here. `STRAT-000001` remains `REJECTED`; `STRAT-000002` is not created as a real, production-registered candidate by this generation's own work — see §10.

## §2. Scope

```
RESEARCH MATERIAL → SOURCE REGISTRY → CLAIM EXTRACTION → HYPOTHESIS REGISTRY
→ HYPOTHESIS FORMALIZATION → SEARCH SPACE → CANDIDATE GENERATION
→ RESEARCH LEDGER → MULTIPLE-TESTING ACCOUNTING → CANDIDATE REGISTRY
```

Every arrow above is real, executable code (§3), not documentation alone — proven end-to-end in `tests/test_generation2_integration.py`.

## §3. Module Map

| Pipeline stage | Module | Canonical spec |
|---|---|---|
| Source | `core/factory/research_source_registry.py` | `ML-001-RESEARCH-SOURCE-SPEC.md` §1-§3 |
| Claim | `core/factory/claim_registry.py` | `ML-001-RESEARCH-SOURCE-SPEC.md` §4 |
| Hypothesis | `core/factory/hypothesis.py` (extended) | `ML-001-HYPOTHESIS-REGISTRY-SPEC.md` §1-§3 |
| Formalization | `core/factory/hypothesis_formalization.py` | `ML-001-HYPOTHESIS-REGISTRY-SPEC.md` §4 |
| Quality gates | `core/factory/hypothesis_quality_gates.py` | `ML-001-HYPOTHESIS-REGISTRY-SPEC.md` §5 |
| Market universe expansion | `core/factory/market_universe_ontology.py` | this document §7 |
| Feature catalog | `core/factory/feature_catalog.py` | this document §8 |
| Search space | `core/factory/search_space.py` | `ML-001-SEARCH-SPACE-SPEC.md` §1-§3 |
| Candidate generation | `core/factory/candidate_generation_engine.py` | `ML-001-SEARCH-SPACE-SPEC.md` §4 |
| Research ledger | `core/factory/research_ledger.py` | `ML-001-RESEARCH-LEDGER-SPEC.md` |
| Search accounting | `core/factory/research_accounting.py` | `ML-001-SEARCH-SPACE-SPEC.md` §5 |
| Production wiring (closes G1-M1) | `core/factory/research_pipeline.py` | this document §6 |
| Holdout access linkage (closes G1-M2) | `core/factory/holdout_access.py` | this document §6 |

## §4. Terminology — the non-negotiable distinctions

```
SOURCE ≠ CLAIM ≠ HYPOTHESIS ≠ CANDIDATE ≠ BACKTEST RESULT ≠ OOS RESULT ≠ EDGE
```

- A **source** (`SourceRecord`) is raw research material. Never evidence.
- A **claim** (`ClaimRecord`) is one extracted assertion from a source. Its `verification_status` may reach `SUPPORTED` only after real testing — never merely because the source said so (enforced: `ClaimRegistry`'s status graph makes `SUPPORTED` reachable only from `TESTED`, never directly).
- A **hypothesis** (`HypothesisRecord`) is a formalized, falsifiable proposition. Its `formalization_status` may reach `SUPPORTED` only via the same discipline, and even then means "not refuted by the linked candidate's real evidence," never "proven edge."
- A **candidate** (`StrategyCandidate`) is a concrete, registered trading-rule specification with full lineage back to its hypothesis and search space. Generating one is not testing one.
- A **backtest/OOS result** is real evidence produced by `core/ml_r2/*` against a registered, eligible dataset (§6). Generation 2 does not produce one — no candidate created by this generation's own tests is trained or evaluated economically.
- **Edge** is a claim this project makes only after a candidate survives the full lifecycle in `ML-001-STRATEGY-FACTORY-SPEC.md` §2-§9, including `PURE_HOLDOUT` and EVG review. Nothing in Generation 2 asserts it.

## §5. Search-Space Expansion ≠ More Edge

```
MORE DATA ≠ MORE EDGE      MORE SOURCES ≠ MORE EDGE
MORE FEATURES ≠ MORE EDGE  MORE STRATEGIES ≠ MORE EDGE
```

More search increases multiple testing, selection bias, and false-discovery risk. `core/factory/research_accounting.py::compute_search_accounting_summary()` is the concrete mechanism that keeps this visible: `SELECTION_BIAS_STATUS` is `UNACCOUNTED` or `ACCOUNTING_ONLY` — never silently `PASS` (`research_accounting.py` has no code path that produces `PASS`; that value would have to come from a future, separate, explicitly-authorized statistical-validation layer).

## §6. Generation 1 Remediation (Phase 0)

Three MEDIUM findings from `ML-001-GENERATION-1-INDEPENDENT-AUDIT.md` §11, closed in this generation with real, tested code (not documentation-only fixes):

- **G1-M1 (production wiring)**: `core/factory/research_pipeline.py::run_registered_walkforward()` is now the one canonical entry point that wires `DatasetRegistry`/`InstrumentRegistry` into `core/ml_r2/walkforward_r2.py` (imported and used completely unmodified). A tampered dataset, an unregistered dataset, a synthetic-flagged dataset, or a missing instrument registration all provably fail before any economic computation occurs (`tests/test_g1_m1_production_wiring.py`, 8 tests, including one against the real registered EURUSD dataset at a deliberately tiny scale — never claimed as an economic result).
- **G1-M2 (holdout access linkage)**: `core/factory/holdout_access.py::HoldoutAccessEvent` is now a required, validated argument to `StrategyRegistry.transition()` when entering `HOLDOUT_TESTED` — a bare `reason` string is no longer sufficient (`HoldoutAccessEventRequiredError` otherwise). No real holdout data is touched anywhere in Generation 2's own tests (`tests/test_g1_m2_holdout_access_linkage.py`, 18 tests, entirely synthetic fixtures).
- **G1-M3 (vacuous assertion)**: the vacuous assertion in `tests/test_generation1_foundation_integration.py` (guarding on a dict key a dataclass property can never produce) is replaced with a real assertion on the reconstructed `DatasetRecord` object, plus a new adversarial test proving the replacement can actually fail.

## §7. Market Universe Expansion (Phase 7)

`core/factory/market_universe_ontology.py`: `ASSET_CLASSES` (FX, METALS, INDICES, COMMODITIES, RATES, VOLATILITY, CRYPTO) and `KNOWN_INSTRUMENT_UNIVERSE` (the task's own example symbol list, mapped to asset class — pure ontology, zero datasets downloaded). `data_eligibility_status(symbol, dataset_registry)` is the **only** function permitted to claim `REAL_DATA_VERIFIED`, and only after checking the real Dataset Registry — ontology membership alone never implies data exists. As of this document, only `EURUSD`/`GBPUSD` resolve to `REAL_DATA_VERIFIED`; every other symbol in the ontology resolves to `NO_DATA_REGISTERED`.

## §8. Feature Catalog Expansion (Phase 8)

`core/factory/feature_catalog.py`: `FEATURE_FAMILIES` (13 families per the task's list) and `KNOWN_FEATURE_CATALOG` (named indicator concepts, e.g. `RSI`, `MACD`, `ADX`, `BOLLINGER_BANDS`, mapped to family). `implementation_status(name)` distinguishes `IMPLEMENTED` (checked directly against `fe_r2_001.FEATURE_ORDER` — only the five real FE-R2-001/003 features) from `CATALOGED_NOT_IMPLEMENTED` (a recognized concept, no working formula) from `UNKNOWN`. No new indicator was implemented.

## §9. Absolute Stop Conditions (honored, not merely stated)

No governance ambiguity was silently resolved during this generation. Every design choice that could plausibly have altered an existing governance contract's meaning is documented in `ML-001-GENERATION-2-REPORT.md` §"Open Decisions" rather than resolved unilaterally where a real ambiguity existed; where no genuine ambiguity existed (e.g. how to extend an already-empty, zero-real-records Gen1 module additively), the extension proceeded without treating routine additive engineering as a governance question.

## §10. Generation 3 Boundary

Not started. No hypothesis was ingested from a real external source (every `SourceRecord`/`ClaimRecord`/`HypothesisRecord` created during this generation's own test suite is a clearly-fictional fixture, in an isolated `tmp_path` registry, never the production `reports/factory/*.json` files). No `STRAT-000002` exists in the production `reports/factory/strategy_registry.json` — confirmed in `ML-001-GENERATION-2-REPORT.md`'s final audit. No paper or live promotion logic was touched.
