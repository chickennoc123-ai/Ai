# ML-001 — Hypothesis Source Contract

**Status**: infrastructure specification. No hypothesis has been ingested under this contract — `core/factory/hypothesis.py` exists and is tested (`tests/test_factory_hypothesis.py`), but `reports/factory/hypothesis_registry.json` does not exist in this repository as of this document.
**Date**: August 18, 2026
**Referenced by**: `ML-001-STRATEGY-FACTORY-SPEC.md` §10, `core/factory/hypothesis.py`.

---

## §1. Purpose

A trading idea can come from anywhere — user research, an academic paper, a book, a website, a public strategy description, a YouTube video, or some other documented source. This project wants a disciplined place to *capture* such ideas so they are not lost or reconstructed from memory later, without ever letting the act of capturing one be mistaken for evidence that it works. This contract defines that boundary precisely.

---

## §2. Source Types

`core.factory.hypothesis.SOURCE_TYPES` — a closed set; `HypothesisSpecError` on anything else:

```
USER_RESEARCH
ACADEMIC_PAPER
BOOK
WEBSITE
PUBLIC_STRATEGY_DESCRIPTION
YOUTUBE
OTHER_DOCUMENTED_SOURCE
```

`OTHER_DOCUMENTED_SOURCE` exists for a legitimate source type not anticipated here — it does not mean "undocumented." `source_reference` is required for every hypothesis regardless of type (a citation, URL, or other retrievable pointer to where the claim actually came from).

---

## §3. HypothesisRecord Fields

`core.factory.hypothesis.HypothesisRecord`:

| Field | Meaning |
|---|---|
| `hypothesis_id` | Immutable identifier, `HYP-000001`-style, allocated by `HypothesisRegistry`. |
| `source_type` | One of §2. |
| `source_reference` | Where the claim came from — required, never empty. |
| `original_claim` | The source's own claim, captured as close to verbatim as practical. **Never rewritten after capture** — this is the one field this contract treats as load-bearing: whatever the source actually said must remain checkable against what this project later did with it. |
| `date_captured` | Set automatically at registration time (UTC ISO8601). |
| `assumptions` | Tuple of strings — any preconditions the claim depends on (e.g. "assumes retail spread, not institutional"), captured alongside the claim rather than left implicit. |
| `formalized_trading_rule` | `None` until `HypothesisRegistry.formalize()` attaches a concrete, testable rule. May differ substantially from `original_claim` in wording — that is expected and fine, since translating a source's prose into an executable rule always involves judgment calls; what matters is that both are on record, distinguishable. |
| `evidence_level` | See §5. |
| `transformation_history` | Append-only list of every event this hypothesis has gone through (captured, formalized, candidate linked, evidence level changed) — never overwritten, never pruned. |
| `candidate_ids` | Tuple of `StrategyRegistry` candidate IDs generated from this hypothesis — see §6. |

---

## §4. Formalization Process

`HypothesisRegistry.formalize(hypothesis_id, formalized_trading_rule=..., reason=...)` attaches a concrete rule and — only if the hypothesis is still at `UNVALIDATED_CLAIM` — advances `evidence_level` to `FORMALIZED_UNTESTED`. This step is explicitly a **translation**, not a validation: turning "buy when RSI crosses 30 from below" into a fully specified `StrategyCandidateSpec` (exact indicator parameters, exact entry/exit timing, exact position sizing) requires choices the original source did not make, and those choices must be visible in `formalized_trading_rule`'s text, not silently absorbed into a candidate spec with no record of where the specific numbers came from.

---

## §5. Evidence Level Discipline — source claims are never evidence

`core.factory.hypothesis.EVIDENCE_LEVELS`, ordered weakest to strongest:

```
UNVALIDATED_CLAIM              -- captured, nothing more
FORMALIZED_UNTESTED            -- a concrete rule exists, no candidate registered yet
CANDIDATE_GENERATED            -- a StrategyCandidate exists in the Factory registry
CANDIDATE_TESTED_NO_EDGE       -- tested, evidence says no edge (STRAT-000001's outcome)
CANDIDATE_TESTED_EDGE_NOT_PROVEN -- tested, inconclusive/insufficient evidence
CANDIDATE_HOLDOUT_PASSED       -- the linked candidate passed PURE_HOLDOUT + EVG
```

**A hypothesis may never be captured already claiming a tested-level outcome** (`CANDIDATE_GENERATED` and everything below it in the list above are rejected by `HypothesisRecord.__post_init__` unless `transformation_history` already shows real prior activity — i.e., these levels are only reachable by actually going through §4/§6, never assigned at construction time with nothing behind them). Every level past `UNVALIDATED_CLAIM` can only be reached through `HypothesisRegistry.formalize()`/`link_candidate()`/`update_evidence_level()`, each of which appends to `transformation_history` rather than silently overwriting — so a hypothesis's evidence level always has a visible, checkable trail explaining how it got there, and can never be a bare assertion.

**The source's own claim (`original_claim`) is never treated as evidence of an edge**, at any evidence level. "The video says this works" is not, and can never become, a substitute for "a `StrategyCandidate` was registered, ran through §3-§9 of `ML-001-STRATEGY-FACTORY-SPEC.md`, and produced a specific, checkable result." `evidence_level` measures how far a hypothesis has progressed through the real testing pipeline — it does not, and structurally cannot, measure how credible or popular the original source is.

---

## §6. Candidate Linkage & Traceability

`HypothesisRegistry.link_candidate(hypothesis_id, candidate_id)` records that a real `StrategyRegistry` candidate was generated from this hypothesis — idempotent (linking the same candidate twice does not duplicate the record), and advances `evidence_level` to at least `CANDIDATE_GENERATED`. A hypothesis may produce more than one candidate over time (e.g. re-formalized after an initial rejection); `candidate_ids` accumulates all of them, so the full lineage from source claim to every candidate it ever produced remains queryable in one place — this is the hypothesis-level analogue of `StrategyCandidate.parent_candidate_id` (`ML-001-STRATEGY-FACTORY-SPEC.md` §7), extending traceability one hop further back, past the Factory's own candidate lineage to the original external claim.

`StrategyCandidate.hypothesis_id` (optional, defaults to `None`) is the reverse pointer — set when a candidate is registered from a formalized hypothesis, left `None` for candidates generated directly from a pre-specified hypothesis document (e.g. `ML-001-R2-CLEAN-REBUILD-SPEC.md`, which is not itself a `HypothesisRecord` and was never captured as an external source claim).

---

## §7. What This Contract Does Not Authorize

- Does not authorize automatic scraping or ingestion of internet/YouTube strategies. Every `HypothesisRecord` must be explicitly, individually created by a human or an explicitly-invoked process — there is no crawler, no batch importer, and none is implied by this document.
- Does not authorize treating a captured hypothesis's `original_claim` as a basis for any trading, sizing, or risk decision, at any evidence level.
- Does not authorize skipping any gate in `ML-001-STRATEGY-FACTORY-SPEC.md` §2-§9 for a candidate merely because it originated from a "credible-sounding" source — every candidate, regardless of `hypothesis_id`, goes through the identical pipeline.
- Does not itself ingest anything. As of this document, `HypothesisRegistry`/`HypothesisRecord` are tested, working infrastructure with zero real records in it.
