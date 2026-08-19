# ML-001 Strategy Research Factory — Generation 3 Canonical Specification

**Status**: CANONICAL for Generation 3 (Real Research Intake + Hypothesis Factory). Incorporates Generations 1-2 (`ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md`, `ML-001-GENERATION-2-SPEC.md`) by reference; nothing in them is weakened or restated.
**Date**: August 19, 2026

---

## §1. Mission

Make the Factory capable of consuming REAL research material and transforming it into traceable, falsifiable, prioritized research hypotheses — and, where a real hypothesis legitimately qualifies, executable strategy candidates. **Nothing in Generation 3 claims an economic edge**: generation, sourcing, popularity, publication, AI plausibility, and source profitability are all explicitly non-evidence. The Factory optimizes TRUTH DISCOVERY, not profit discovery, and becomes MORE conservative as the search space grows (every expansion feeds the multiple-testing accounting, never bypasses it).

## §2. Pipeline

```
REAL RESEARCH MATERIAL → SOURCE REGISTRY → SOURCE SNAPSHOT/PROVENANCE → CLAIM EXTRACTION
→ CLAIM VALIDATION/CLASSIFICATION → HYPOTHESIS FORMALIZATION → NOVELTY/DUPLICATION
→ QUALITY GATE → PRIORITIZATION → SEARCH SPACE → CANDIDATE GENERATION
→ RESEARCH LEDGER → MULTIPLE-TEST ACCOUNTING
```

Every arrow is executable code, proven end-to-end against REAL material (`tests/test_generation3_production_research.py` verifies the committed production state, reverse lineage, and checksums — read-only).

## §3. Module Map

| Concern | Module | Detail spec |
|---|---|---|
| Real source intake / access statuses | `core/factory/research_source_registry.py` (extended) | `ML-001-RESEARCH-INTAKE-SPEC.md` |
| Content-addressed snapshots | `core/factory/source_snapshot.py` | `ML-001-RESEARCH-INTAKE-SPEC.md` §4 |
| Claim extraction/classification/epistemic status | `core/factory/claim_registry.py` (extended) | `ML-001-CLAIM-EXTRACTION-SPEC.md` |
| Hypothesis origins / synthesis / AI provenance | `core/factory/hypothesis.py` (extended) | `ML-001-HYPOTHESIS-GENERATION-SPEC.md` |
| Novelty / duplication / families | `core/factory/novelty_engine.py` | `ML-001-HYPOTHESIS-GENERATION-SPEC.md` §5 |
| Strategy DNA / fingerprint | `core/factory/strategy_dna.py` | `ML-001-HYPOTHESIS-GENERATION-SPEC.md` §6 |
| Prioritization / information gain / feedback firewall | `core/factory/research_prioritization.py` | `ML-001-RESEARCH-PRIORITIZATION-SPEC.md` |
| Pre-flight early rejection | `core/factory/preflight.py` | `ML-001-RESEARCH-PRIORITIZATION-SPEC.md` §5 |
| Failure library | `core/factory/failure_library.py` | `ML-001-FAILURE-LIBRARY-SPEC.md` |
| Governed cache | `core/factory/research_cache.py` | `ML-001-RESEARCH-CACHE-SPEC.md` |
| Budgets + kill switch | `core/factory/research_budget.py` | `ML-001-RESEARCH-PRIORITIZATION-SPEC.md` §6 |
| Diversity metrics | `core/factory/research_diversity.py` | `ML-001-RESEARCH-PRIORITIZATION-SPEC.md` §7 |

## §4. Epistemic Chain (the load-bearing distinctions)

`SOURCE_SAYS_X` ≠ `FACT_ESTABLISHED_X` ≠ `HYPOTHESIS_X` — three distinct `epistemic_status` values on every claim, code-enforced (`FACT_ESTABLISHED` requires non-empty evidence at construction; `SOURCE_CLAIM` is the default and the only state a bare extraction can occupy). A claim's `SUPPORTED` verification status is reachable only through `TESTED` (Generation 2 discipline, unchanged); a hypothesis's `SUPPORTED` additionally requires a linked real candidate (new, Generation 3 — the independent-evidence-path guard, which is what makes `AI_GENERATED → SUPPORTED` on plausibility structurally impossible for every origin, not just AI).

## §5. Real Intake Performed (Phase 22-24 outcome)

Four production sources (one real fetched external source, checksummed and snapshot-preserved under its verified Apache-2.0 license; two honest `ACCESS_FAILED` host-attempt records — network policy blocks arxiv.org and papers.ssrn.com, and per rule 13 no substitute was presented as those sources; one internal committed forensic report, checksum-verified). Three verbatim/summarized claims, three formalized hypotheses across three origins (`PUBLIC_STRATEGY_DERIVED`, `CROSS_SOURCE_SYNTHESIS` with both parents preserved, `AI_DERIVED` with full separated provenance), one declared 8-combination search space, and one production candidate — `STRAT-000002`, state `GENERATED`, full reverse lineage to `SRC2-000001`, **not validated, not an edge claim**. Full detail: `ML-001-GENERATION-3-REPORT.md`; machine-readable: `reports/factory/GENERATION3_RESEARCH_AUDIT.json`.

## §6. Phase 16 Feedback Firewall

Historical research outcomes may inform novelty/priority/compute/duplication-avoidance ONLY as **counts** (`ResearchKnowledge` has exactly three integer count fields and rejects anything else — there is no field through which a holdout/OOS performance number can flow into research targeting). The one production synthesis hypothesis (`HYP-000002`) uses the internal parent strictly as *coverage* knowledge ("the 1-bar horizon is already-tested territory"), never as performance-informed parameter tuning — the distinction is recorded in its ledger entry.

## §7. Safety

`ResearchBudget`/`BudgetTracker` (per-run caps on sources/hypotheses/candidates/search-space size/candidates-per-family; unbounded budgets are unrepresentable) and `ResearchKillSwitch` (persistent, trip-once, fails closed on corrupted state, no programmatic reset API, preserves all recorded evidence). Production kill-switch state: `reports/factory/research_kill_switch.json`, not tripped.

## §8. Generation 4 Boundary

Not started. `STRAT-000002` has received no data validation, training, or evaluation of any kind; no economic number of any sort was produced in Generation 3. `EDGE_STATUS` remains `NOT_PROVEN`; `SELECTION_BIAS_STATUS` remains honest (`ACCOUNTING_ONLY`/`UNACCOUNTED`, never `PASS`).
