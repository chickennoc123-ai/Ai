# ML-001 — Research Ledger Specification (Generation 2, Phase 11 — CORE REQUIREMENT)

**Status**: IMPLEMENTED and tested.
**Code**: `core/factory/research_ledger.py`
**Referenced by**: `ML-001-GENERATION-2-SPEC.md` §3.

---

## §1. Purpose

A durable, append-only record of every meaningful research event across the pipeline — the mechanism that lets a future audit ask "what happened, when, why, and using what" without reconstructing the answer from scattered registry diffs.

## §2. Event Types

`core.factory.research_ledger.EVENT_TYPES`: `SOURCE_INGESTED`, `SOURCE_NEW_VERSION`, `CLAIM_CREATED`, `CLAIM_STATUS_CHANGED`, `HYPOTHESIS_CREATED`, `HYPOTHESIS_FORMALIZED`, `HYPOTHESIS_REJECTED`, `HYPOTHESIS_STATUS_CHANGED`, `SEARCH_SPACE_CREATED`, `CANDIDATE_GENERATED`, `CANDIDATE_REJECTED`, `CANDIDATE_FROZEN`, `EVALUATION_REQUESTED`, `EVALUATION_BLOCKED`, `DUPLICATE_DETECTED` — a closed set (`LedgerEventError` on anything else), extendable by adding to the `frozenset` without invalidating any existing entry.

## §3. Event Fields

`LedgerEvent`: `event_id` (auto-allocated, monotonic, `LEDGER-NNNNNNNN`), `event_type`, `timestamp`, `subject_id` (the primary entity — source/claim/hypothesis/candidate id), `reason`, plus optional `source_id`/`dataset_id`/`feature_ids`/`search_space_id`/`result`/`artifact_reference`. Together these answer WHO/WHAT (`subject_id` + event type), WHEN (`timestamp`), WHY (`reason`), FROM_WHICH_SOURCE (`source_id`), USING_WHICH_DATA (`dataset_id`), USING_WHICH_FEATURES (`feature_ids`), USING_WHICH_SEARCH_SPACE (`search_space_id`), RESULT (`result`), ARTIFACT (`artifact_reference`) directly from one entry, cross-referenceable against every other registry via the same ids they use.

## §4. Append-Only, Structurally

`LedgerEvent` is a frozen dataclass — a retrieved event cannot be mutated (`dataclasses.FrozenInstanceError`, verified). `ResearchLedger` has exactly one write method, `append()` — there is deliberately no `update`/`edit`/`delete`/`remove` method anywhere in the class (verified: `tests/test_generation2_research_registries.py::test_ledger_has_no_delete_or_update_method` inspects the class's actual method list, not a promise). Calling `append()` twice with identical arguments correctly creates two distinct events — two real occurrences are two real events, never silently deduplicated into one.

`ledger_checksum()` hashes the full ordered event sequence. A direct file-level edit to the underlying JSON (bypassing `append()` entirely) is detectable: recomputing the checksum after such an edit produces a different value than before, proven adversarially (`tests/test_generation2_adversarial.py::TestLedgerMutation::test_ledger_file_tampering_changes_the_ledger_checksum`) — this is tamper-evidence, not tamper-prevention (a sufficiently determined actor with file access could edit the checksum's own recorded value too, if one were separately stored; this module does not claim cryptographic security, only that an edit is not silently invisible to a checksum recomputed from the file's own current content).

## §5. What This Contract Does Not Do

- Does not itself enforce that every registry mutation is accompanied by a ledger entry — callers (the integration pipeline, future scripts) are responsible for calling `append()` at the right points; `tests/test_generation2_integration.py` demonstrates the intended usage pattern end-to-end but this module cannot force every future caller to follow it.
- Does not provide cryptographic tamper-*prevention*, only tamper-*evidence* via checksum recomputation (§4).
