# ML-001 — Research Intake Specification (Generation 3, Phases 1-3)

**Status**: IMPLEMENTED and exercised against REAL material.
**Code**: `core/factory/research_source_registry.py` (extended additively), `core/factory/source_snapshot.py`
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3.

---

## §1. Source Categories

`SOURCE_TYPES` now includes all fourteen Generation 2 types plus `MACRO_RESEARCH`, `ALTERNATIVE_DATA_RESEARCH`, and `INTERNAL_RESEARCH_REPORT` (additive — no historical record invalidated; the set is a `frozenset` consulted only at construction time, so future types extend it without migration). Ingestion behavior legitimately differs by class: a fetched open-source README gets a full snapshot; an unreachable academic host gets an honest `ACCESS_FAILED` record with no content claim; an internal committed report gets an `OWN_WORK` snapshot.

## §2. Provenance Fields

`SourceRecord` carries: `source_id`, `source_version`, `source_type`, `title`, `author` (creator), `publisher`, `source_url`, `retrieval_timestamp`, `publication_timestamp`, `content_checksum`, `artifact_reference` (snapshot pointer), `license_status`, `access_status`, `provenance_status`, `verification_status`, `notes`, `supersedes_source_id`. Every unestablished field is the literal `"UNKNOWN"` — never fabricated.

## §3. Status Discipline

- `verification_status` distinguishes `VERIFIED` / `PROVISIONALLY_VERIFIED` / `UNVERIFIED` / `ACCESS_FAILED` / `REJECTED` (plus the two Generation 2 values, retained). Never silently upgraded — the only strengthening path is an explicit re-registration/new-version stating its evidence.
- `access_status` (`NOT_ATTEMPTED`/`ACCESSED`/`ACCESS_FAILED`) is a separate axis from verification. **Code-enforced coherence**: an `ACCESS_FAILED` source cannot carry a `content_checksum` — a source whose content was never reached cannot claim its content was checksummed (`SourceSpecError`).
- Inaccessible source ⇒ record the failure (`SRC2-000002`/`SRC2-000003` in production are real examples: the arxiv.org and papers.ssrn.com hosts are blocked by environment network policy; their records state explicitly that *no specific paper was identified or reviewed*, so they cannot be mistaken for citations, and the failure is also in the Failure Library as `SOURCE_ACCESS_FAILED`). No substitute source is ever presented as the failed one (rule 13; adversarial test `Test19SourceSubstitution`).

## §4. Snapshots (Phase 3 + content addressing, Phase 17)

`SourceSnapshotStore`: content-addressed (`snapshot_id` = SHA-256 of the stored bytes), append-only (no delete/overwrite API), tamper-evident on read (`read_verified` refuses bytes that no longer hash to their own id — proven with a bit-flip adversarial test). **Storage requires an affirmative `license_basis`** from a closed set (`PERMISSIVE_LICENSE`/`PUBLIC_DOMAIN`/`OWN_WORK`/`PERMITTED_EXCERPT`/`METADATA_ONLY`) — content with no stated legal basis is refused, and where full content cannot legally be retained, metadata + permitted excerpt + provenance is the sanctioned fallback, honestly labeled as such (`representation` field).

Production snapshots: the je-suis-tm/quant-trading README (31,556 bytes, Apache-2.0 verified by fetching the repository's own LICENSE file at retrieval time) and this project's own forensic report (`OWN_WORK`). Both re-verified by checksum in `tests/test_generation3_production_research.py`.

## §5. What Intake Never Does

Never crawls; never fabricates metadata; never upgrades UNKNOWN; never claims a blocked source was reviewed; never overwrites a source version (`new_version()` mints a new id with `supersedes_source_id`, the original untouched).
