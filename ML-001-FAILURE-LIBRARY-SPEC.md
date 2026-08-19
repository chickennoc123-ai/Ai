# ML-001 — Failure Library Specification (Generation 3, Phase 15)

**Status**: IMPLEMENTED, with REAL production records.
**Code**: `core/factory/failure_library.py`; production store `reports/factory/failure_library.json`
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3, `ML-001-RESEARCH-PRIORITIZATION-SPEC.md` §4-§5.

---

## §1. Purpose

Failure is information. Every rejected source/claim/hypothesis/candidate may record a durable, categorized entry; the library is append-only (no delete/remove/update method exists — verified by test against the class's actual method list), and nothing recorded is ever discarded.

## §2. Record Fields

`FailureRecord`: `failure_id`, `entity_id`, `failure_stage` (16 stages, `INTAKE` through `GOVERNANCE`), `failure_category`, `failure_reason`, `timestamp`, `evidence_reference`, `related_family`, `related_features`, `related_market`, `related_search_space`.

## §3. Standard Categories

`INVALID_DATA`, `INSUFFICIENT_HISTORY`, `LEAKAGE`, `TEMPORAL_INVALIDITY`, `NO_SIGNAL`, `NEGATIVE_EXPECTANCY`, `COST_SENSITIVITY`, `PARAMETER_FRAGILITY`, `OOS_DECAY`, `WFA_FAILURE`, `STATISTICAL_FAILURE`, `DUPLICATE`, `GOVERNANCE_FAILURE`, `PROVENANCE_FAILURE`, `SEARCH_SPACE_INVALID`, plus Generation 3 intake categories `SOURCE_ACCESS_FAILED` and `FORMALIZATION_INCOMPLETE`. Unknown categories are rejected (closed set — a new category is an explicit contract extension, not a free-text drift).

## §4. Feedback Role — deliberately narrow

The library's sanctioned contribution to future research is `count_by_family()` / `count_by_category()` — **counts only**, consumed via `ResearchKnowledge` (`ML-001-RESEARCH-PRIORITIZATION-SPEC.md` §4). `FailureRecord` carries no performance-metric field of any kind: the category `NEGATIVE_EXPECTANCY` records *that* a candidate failed for that reason (with an `evidence_reference` pointing at the full report for human audit), never the number itself in a machine-consumable feedback path.

## §5. Production Records

Two real entries exist as of this document: `SOURCE_ACCESS_FAILED` at stage `INTAKE` for the arxiv.org and papers.ssrn.com host-attempt sources — the environment's network-policy blocks, preserved as research information rather than silently dropped.
