# ML-001 Strategy Research Factory — Generation 1 Canonical Specification

**Status**: CANONICAL for Generation 1 (Foundation), superseded as the top-level document by `ML-001-GENERATION-2-SPEC.md` for anything Generation 2 added (research pipeline: source/claim/hypothesis/search-space/candidate-generation/ledger/accounting) — this document remains the authoritative source for Generation 1's own scope (Data Factory, Market Universe, Feature Factory) and is not restated or invalidated by Generation 2. This is the top-level specification for the Strategy Research Factory as a whole at the time it was written; it does not restate the candidate-lifecycle detail already canonical in `ML-001-STRATEGY-FACTORY-SPEC.md` §1-§12, it incorporates that document by reference and adds the Generation 1 scope this task introduced: Data Factory, Market Universe, Feature Factory, and generation boundaries.
**Date**: August 18, 2026 (Generation 1); Generation 2 status noted August 19, 2026 — see `ML-001-GENERATION-2-REPORT.md`.

**Generation 1's three MEDIUM audit findings** (`ML-001-GENERATION-1-INDEPENDENT-AUDIT.md` §11: production wiring not complete, holdout access linkage weak, one vacuous test assertion) **are now CLOSED** — see `ML-001-GENERATION-2-SPEC.md` §6 for what changed and where. No claim in this document about Generation 1's own scope was invalidated by that remediation; the fixes are additive (`core/factory/research_pipeline.py`, `core/factory/holdout_access.py`, both new files) plus one corrected test assertion.

---

## §1. Mission

Build a rigorous, reproducible research foundation capable of supporting large-scale strategy research **without**: data fabrication, synthetic-data substitution presented as real, temporal leakage, holdout contamination, undocumented search, hidden selection bias, candidate mutation, provenance loss, silent governance relaxation, or fabricated PASS states. Finding a winning strategy is explicitly **not** this generation's objective — `STRAT-000001` remains `REJECTED`, `STRAT-000002` remains `NOT_CREATED`, and Generation 1 succeeds or fails independent of either fact.

## §2. Scope — Generation 1 vs. later generations

**Generation 1 (this specification's scope)**:

| Phase | Subsystem | Canonical spec |
|---|---|---|
| 0 | Governance foundation | `ML-001-STRATEGY-FACTORY-SPEC.md` §1-§12, `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` |
| 1 | Data Factory | `ML-001-DATA-FACTORY-SPEC.md` |
| 2 | Market Universe | `ML-001-MARKET-UNIVERSE-SPEC.md` |
| 3 | Feature Factory | `ML-001-FEATURE-FACTORY-SPEC.md` |
| 4 | Foundation integration | this document §7, `reports/factory/GENERATION1_FOUNDATION_AUDIT.json` |

**Generation 2 and later — explicitly out of scope here, not implemented, not started**: hypothesis ingestion at scale (`ML-001-HYPOTHESIS-SOURCE-CONTRACT.md` defines the *contract*, Generation 1 does not use it), YouTube/internet strategy ingestion, candidate generation at scale, `STRAT-000002` or any new candidate, automated strategy discovery, new economic strategy experiments, paper trading, live trading, production promotion. Generation 1 builds the foundation these would run on; it does not run any of them.

## §3. Terminology

- **Candidate**: one `StrategyCandidate` in the Factory registry (`core/factory/registry.py`) — a specific, immutable trading-rule specification moving through the lifecycle in `ML-001-STRATEGY-FACTORY-SPEC.md` §2.
- **Dataset**: one catalogued, checksummed market-data file (`core.factory.dataset_registry.DatasetRecord`) — distinct from a **data source** (`core.factory.data_source_registry.DataSourceRecord`, *where* data can come from) and from a **partition** (`core.dataset_provenance.DatasetProvenance`, a DEVELOPMENT/VALIDATION/PURE_HOLDOUT *slice* of a dataset governed at runtime).
- **Instrument**: one tradeable symbol (`core.factory.instrument_registry.InstrumentRecord`) with its own asset class, venue, and cost-model reference — never assumed interchangeable with another instrument merely because both are FX pairs.
- **Feature contract**: one feature's complete, queryable definition (`core.factory.feature_registry.FeatureContract`) — wraps, never replaces, `core.features.fe_r2_001.get_feature_schema()`.
- **Research scope**: `SINGLE_INSTRUMENT` / `INSTRUMENT_FAMILY` / `MULTI_INSTRUMENT`, declared on a candidate spec *before* evaluation (`ML-001-MARKET-UNIVERSE-SPEC.md` §4).
- **Generation**: a bounded phase of this project's own development, not a Factory runtime concept — Generation 1 is foundation; Generation 2 (not started) is hypothesis research/candidate generation.

## §4. Candidate Lifecycle & State Machine

Fully specified in `ML-001-STRATEGY-FACTORY-SPEC.md` §2-§9 — not restated here. Summary for orientation: `GENERATED → DATA_VALIDATED → TRAINED → OOS_TESTED → WFA_TESTED → ROBUSTNESS_TESTED → COST_TESTED → STATISTICALLY_VALIDATED → MULTIPLE_TESTING_REVIEWED → FROZEN → HOLDOUT_TESTED → EVG_REVIEW → RESEARCH_CANDIDATE → PAPER_VALIDATION → LIVE_CANDIDATE`, terminal `REJECTED`/`FAILED`/`RETIRED` reachable from most states.

## §5. Version Semantics & Rejection Semantics

Fully specified in `ML-001-STRATEGY-FACTORY-SPEC.md` §5-§6 — not restated here.

## §6. Dataset, Feature, and Holdout Semantics (Generation 1 additions)

- **Dataset semantics**: `ML-001-DATA-FACTORY-SPEC.md` §3-§4 — every dataset has a stable `dataset_id`, a `provenance_status` that is never inferred (`UNVERIFIED` by default), and an `is_real_market_data_eligible` gate that a script must pass explicitly before treating a dataset as `REAL_MARKET_DATA = TRUE` evidence.
- **Feature semantics**: `ML-001-FEATURE-FACTORY-SPEC.md` §2-§4 — every feature has a versioned contract, a warmup requirement, and contributes to a reproducible `feature_schema_identity`.
- **Holdout semantics**: `ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md` (resolved) + `ML-001-STRATEGY-FACTORY-SPEC.md` §4 — `PURE_HOLDOUT` is the final gate, opened exactly once, never used for selection.
- **Evidence semantics**: a claim ("real data", "no leakage", "passed") requires an artifact that can be independently re-derived (a checksum, a re-run test, a re-computed schema identity) — never a bare assertion. Every Generation 1 subsystem built in this task follows this: dataset eligibility, feature schema identity, and instrument/dataset linkage are all functions that can be re-run and re-checked, not narrative claims.

## §7. Provenance Requirements

A downstream artifact (a trained model, an evaluation result, an audit report) must be traceable, without ambiguity, back through: **candidate scope → feature schema → dataset → source → checksum**. `reports/factory/GENERATION1_FOUNDATION_AUDIT.json` (§4/Phase 4, `tests/test_generation1_foundation_integration.py`) is the concrete, re-runnable proof this chain holds for the real EURUSD dataset as of this document.

## §8. Search Accounting & Multiple-Testing Accounting

Fully specified in `ML-001-SEARCH-SPACE-AND-MULTIPLE-TESTING-CONTRACT.md` and `ML-001-STRATEGY-FACTORY-SPEC.md` §7-§8 — extended by this generation's `symbol_search_space`/`timeframe_search_space`/`feature_search_space` fields (already present in `StrategyRegistry._empty_search_history()`, populated by `set_search_space()`), which Generation 2 will use once it actually begins expanding along those axes. Generation 1 populates zero of them beyond what already existed for `STRAT-000001`.

## §9. Audit Requirements

Every Generation 1 subsystem must be independently re-checkable, not merely asserted:

- Dataset file checksums recomputed from disk, not trusted from a prior manifest (`DatasetRegistry.verify_file_checksum`).
- Feature schema identity recomputed and compared across fresh processes (`tests/test_generation1_foundation_integration.py::TestReproducibilityAcrossFreshProcesses`).
- Adversarial attempts (wrong symbol, wrong timeframe, altered dataset, synthetic-flag mismatch, missing provenance, duplicate data, future-leaking feature, invalid gap handling, frozen-candidate mutation, holdout misuse) must be rejected, not silently accepted (`tests/test_generation1_foundation_integration.py::TestAdversarialAudit`).

## §10. Future Generation Boundaries

Generation 1 delivers infrastructure; it does not use it to make a new economic claim. The explicit stop condition (repeated from the task's own instruction, not invented here): **do not create `STRAT-000002`**, do not ingest a hypothesis, do not add a new symbol's real data, do not add a new feature beyond the existing five, do not begin paper or live promotion. `ML-001-GENERATION-1-FOUNDATION-REPORT.md` records the final gate status and is the last artifact this task produces — Generation 2 begins, per the task's own words, "only after Generation 1 has been independently reviewed," which this document does not attempt to substitute for.
