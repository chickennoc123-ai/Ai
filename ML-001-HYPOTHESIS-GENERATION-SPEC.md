# ML-001 — Hypothesis Generation Specification (Generation 3, Phases 6-11)

**Status**: IMPLEMENTED and exercised against REAL material.
**Code**: `core/factory/hypothesis.py` (extended), `core/factory/novelty_engine.py`, `core/factory/strategy_dna.py`
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3-§4.

---

## §1. Hypothesis Fields

All Generation 2 fields plus (additive): `origin_type`, `parent_source_ids`, `parent_claim_ids`, `ai_provenance`. A hypothesis remains falsifiable-by-construction: formalization (`FormalizationSpec`, unchanged from Generation 2 plus `instrument_scope`) requires condition/signal/target/horizon/direction/regime/instrument/costs/falsification, rejects vague values, and is testable without knowing the eventual result (production example: `HYP-000001`'s falsification rule was fixed before any evaluation exists).

## §2. Origins (Phase 7)

`ORIGIN_TYPES`: `PAPER_DERIVED`, `WEB_DERIVED`, `YOUTUBE_DERIVED`, `PUBLIC_STRATEGY_DERIVED`, `HUMAN_DERIVED`, `AI_DERIVED`, `MARKET_OBSERVATION_DERIVED`, `CROSS_SOURCE_SYNTHESIS` (+ `UNSPECIFIED` for pre-Generation-3 records only). **`CROSS_SOURCE_SYNTHESIS` requires ≥ 2 recorded parents at construction** — synthesis lineage preserves ALL parents, never collapses (production `HYP-000002` records parent sources `SRC2-000001` + `SRC2-000004` and parent claims `CLAIM-000001` + `CLAIM-000003`).

## §3. AI Hypotheses (Phase 8)

`AI_DERIVED` is first-class but carries **stronger** provenance separation, enforced both directions: an AI hypothesis missing any of `generation_model`/`generation_timestamp`/`prompt_identity`/`input_source_ids`/`input_claim_ids` is rejected; a non-AI hypothesis carrying `ai_provenance` is rejected (an AI hypothesis can never blend in as human work, and vice versa). Production `HYP-000003` records the prompt text plus its SHA-256 as `prompt_identity` (re-verified by test), the input source/claim ids, and a generation-model field whose model identifier is withheld in committed artifacts per repository policy, with the generating session identified by the introducing commit's session trailer — an explicit, documented redaction, not missing provenance.

**AI plausibility is not evidence**: `AI_GENERATED → SUPPORTED` without an independent evidence path is structurally impossible — `transition_formalization_status(…, "SUPPORTED")` raises for ANY origin unless at least one real candidate is linked (`HypothesisSpecError`; adversarial tests `Test06`/`Test07`).

## §4. Falsifiability & Quality (Phases 6, 9)

Unchanged Generation 2 quality gates (10 gates, full failure list, no auto-fill) remain the eligibility barrier; `ELIGIBLE` is granted only after they pass (production: `HYP-000001` is `ELIGIBLE`; `HYP-000002`/`HYP-000003` deliberately remain `FORMALIZED` — no candidate was generated from them).

## §5. Novelty / Duplication / Families (Phase 10)

`core/factory/novelty_engine.py` — all deterministic and explainable:

- `text_signature` (normalized-text SHA-256): exact duplicates, wording-insensitive.
- `token_jaccard` / `is_near_duplicate(threshold)`: same hypothesis, different wording; threshold is an explicit argument, never hidden.
- `mechanism_signature` (numbers → `N` before hashing): same mechanism with parameter variation — RSI 10/14/20/30 provably collapse to ONE signature (tested), so parameter variants are never counted as independent research.
- `FamilyRegistry` (`HYPOTHESIS_FAMILY`/`STRATEGY_FAMILY`/`RESEARCH_CLUSTER`): durable, members append-only and preserved permanently — the raw material for false-discovery analysis.

**Known limitation (disclosed, not hidden)**: mechanism signatures are wording-sensitive across differently-phrased mechanism strings — production `HYP-000001`/`HYP-000002` landed in separate families because their mechanism texts differ by a parenthetical, though they are conceptually one family. The error direction is over-splitting (never over-merging), so recorded family sizes are lower bounds on true relatedness; multiple-testing consumers must treat them as such. A future canonicalization pass may merge families, which the append-only member model supports without rewriting history.

## §6. Strategy DNA (Phase 11)

`StrategyDNA` over ten components (market/timeframe/features/feature-parameters/entry/exit/regime/risk/holding/costs): `fingerprint()` (exact), `family_fingerprint()` (parameter-stripped), `similarity()`/`component_matches()` (decomposable fraction — every score explainable per component). **No auto-rejection API exists** (tested: no method with "reject" in the module) — DNA feeds clustering, novelty, accounting, and compute prioritization only, exactly as the contract requires; automatic rejection would need an explicit future governance rule.
