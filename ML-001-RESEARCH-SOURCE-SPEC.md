# ML-001 — Research Source & Claim Specification (Generation 2, Phase 1-3)

**Status**: IMPLEMENTED and tested. Zero real sources/claims exist in production — every registry in this document's test suite uses an isolated `tmp_path`.
**Code**: `core/factory/research_source_registry.py`, `core/factory/claim_registry.py`
**Referenced by**: `ML-001-GENERATION-2-SPEC.md` §3.

---

## §1. Purpose

The entry point of the research pipeline. **A source is never evidence of an edge**, regardless of type or wording — this contract exists to make that boundary structural, not a matter of discipline alone.

## §2. Source Types (14, per the task's own list)

`core.factory.research_source_registry.SOURCE_TYPES`: `ACADEMIC_PAPER`, `WORKING_PAPER`, `BOOK`, `TEXTBOOK`, `RESEARCH_REPORT`, `WEBSITE`, `YOUTUBE`, `PUBLIC_STRATEGY`, `OPEN_SOURCE_CODE`, `HUMAN_HYPOTHESIS`, `AI_GENERATED_HYPOTHESIS`, `MARKET_OBSERVATION`, `MACRO_DATA_SOURCE`, `ALTERNATIVE_DATA_SOURCE`. A `frozenset`, not a hard-coded schema migration — extending it does not invalidate any existing `SourceRecord`.

## §3. Source Record & Registry

`SourceRecord`: `source_id`, `source_type`, `title`, `retrieval_timestamp`, `source_version` (defaults 1), `author`/`publisher`/`source_url`/`content_checksum`/`publication_timestamp`/`license_status` (each defaults to the literal string `"UNKNOWN"` — never guessed, never silently upgraded), `provenance_status` (defaults `UNVERIFIED`), `verification_status` (defaults `UNVERIFIED`), `notes`, `supersedes_source_id`.

**Ingestion contract** (Phase 2): `ResearchSourceRegistry.register()` never overwrites an existing `source_id` (`DuplicateSourceError`); `.new_version(previous_source_id, **overrides)` is the only sanctioned way to record materially changed content — it mints a new id, sets `supersedes_source_id`, and leaves the previous record completely untouched (verified: `tests/test_generation2_research_registries.py::test_new_version_preserves_previous_record_untouched`). `SourceRecord` is a frozen dataclass — no in-place mutation is possible at all, and `ResearchSourceRegistry` deliberately has no `update`/`edit` method.

**Deduplication** (Phase 13): `find_duplicate()` matches on `identity_checksum()` — a hash of `(source_type, title, author, source_url, publisher)`, deliberately excluding volatile fields (`retrieval_timestamp`, `source_id`, `notes`). A source with a genuinely different title is never flagged as a duplicate merely because it shares a URL or author — verified with an adversarial "different title, not a duplicate" test.

**Per source-type discipline** (Phase 2): for web/YouTube/public-strategy sources, the source itself is not evidence of an edge — it is research material. For papers, the paper is not evidence the strategy works — it contains claims that may become hypotheses. This is enforced structurally: there is no field on `SourceRecord`, and no method on `ResearchSourceRegistry`, that can assert an economic result — that capability exists only on `core.factory.registry.StrategyCandidate`, reached only after the full pipeline in `ML-001-GENERATION-2-SPEC.md` §4.

## §4. Claim Record & Registry

`core.factory.claim_registry.ClaimRecord`: `claim_id`, `source_id`, `claim_text`, `claim_type` (one of `PREDICTIVE_SIGNAL`/`REGIME_DEPENDENCE`/`RISK_PREMIUM`/`MICROSTRUCTURE_EFFECT`/`SEASONALITY`/`CROSS_ASSET_RELATIONSHIP`/`EVENT_DRIVEN`/`OTHER`), `creation_timestamp`, `claim_version`, `mechanism`/`instrument_scope`/`timeframe_scope`/`direction` (default `UNKNOWN`), `supporting_context`, `verification_status`.

**Status lifecycle**: `UNEXTRACTED → EXTRACTED → FORMALIZATION_PENDING → FORMALIZED → TESTED → {SUPPORTED, REFUTED}`, with `SUPERSEDED` reachable from any non-terminal status. Enforced by `assert_legal_claim_transition()`, mirroring `core.factory.state_machine`'s discipline — a claim cannot skip `FORMALIZED` and jump straight to `TESTED`, and **`SUPPORTED` is reachable only as the direct successor of `TESTED`, never from any earlier status** (verified explicitly, both the negative case for every earlier status and the one legal path: `tests/test_generation2_research_registries.py::TestClaimRegistry`). This is the concrete mechanism behind "do not label a claim SUPPORTED merely because the source says it" — there is no code path that reaches `SUPPORTED` without first passing through `TESTED`, and nothing in this module can make a claim `TESTED` — only real downstream evidence, outside this module's scope entirely, could ever justify that transition being invoked.

`ClaimRecord` is frozen; status is tracked out-of-band in `ClaimRegistry._history` (append-only, `history(claim_id)` returns the full, ordered trail) — `get()` always returns a freshly-reconstructed record reflecting the latest status, never a stale cached object.

**Deduplication**: `find_duplicate()` matches on `(source_id, claim_text, claim_type)` — exact match only. A paraphrased or reworded claim from the same source is deliberately **not** flagged as a duplicate, since paraphrase can change meaning and incorrectly merging genuinely different claims would corrupt the research record.

## §5. What This Contract Does Not Do

- Does not ingest any real source. Every `SourceRecord`/`ClaimRecord` in this project's test suite is a clearly-fictional fixture.
- Does not scrape or automatically pull content from the internet/YouTube — every registration is an explicit, individual call.
- Does not itself compute or assert any economic result.
