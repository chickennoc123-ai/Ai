# ML-001 — Generation 5, Phases 3-4 & 11-12: Research Memory

**Date**: August 19, 2026
**Status**: `RESEARCH_MEMORY_STATUS = OPERATIONAL`, `LINEAGE_STATUS = TRAVERSABLE`, `HORIZON_CONSISTENCY_STATUS = AUDITED`

---

## 1. Refuted-family memory (Phase 3) + similarity classification (Phase 4)

`core.factory.refuted_family_memory` answers "has this hypothesis family already been tested and refuted?" two ways:

**Exact family membership** (`compute_family_refutation_status`, using the existing `core.factory.novelty_engine.FamilyRegistry`): a family is `REFUTED_UNDER_SPECIFIC_OPERATIONALISATION` if ≥1 member is `REFUTED`, and `REFUTED_UNIVERSALLY` **only** if the family_id appears in a governance allowlist this module has no code path to populate itself (empty today — no family in this Factory is universally refuted; every refutation states an instrument/horizon/cost-model scope).

**Cross-hypothesis similarity** (`assess_similarity_against_registry`, `classify_similarity`): deterministic, threshold-based (`CLOSE_VARIANT ≥ 0.60` Jaccard, `RELATED_FAMILY ≥ 0.30`, `DISTANT_ANALOG ≥ 0.01`, else `NOVEL`; `EXACT_DUPLICATE` via exact text-signature match) — declared before any similarity was computed, never an unevidenced AI assertion of "novel."

**A real gap this module found and closed**: `HYP-000001` and `HYP-000002` land in *different* formal families (`FAMILY-000001` vs `FAMILY-000002`) under exact number-stripped mechanism-signature hashing, because `HYP-000001`'s text carries one extra parenthetical aside ("(source's oversold threshold)"). Token-Jaccard similarity between them is 0.667 — `CLOSE_VARIANT`. Cross-hypothesis similarity, not exact family-signature membership alone, is therefore the authoritative refuted-family check going forward:

```
HYP-000002 vs HYP-000001: CLOSE_VARIANT (jaccard=0.667) -- HYP-000001 is REFUTED
HYP-000003 vs HYP-000001: RELATED_FAMILY (jaccard=0.444) -- HYP-000001 is REFUTED
```

## 2. Lineage graph (Phase 11)

`core.factory.lineage_graph.trace_hypothesis_lineage` returns, for any hypothesis, its parent sources, parent claims, produced candidates (with current state), every linked failure record, and — if refuted — the falsification conditions and operationalisation (instrument/horizon/cost model) the refutation applies to. Missing references degrade to an explicit `{"error": "not found"}` entry rather than raising, so a broken reference is visible, not a crash. Full output: `reports/generation5/LINEAGE_GRAPH.json`.

```
HYP-000001: refuted=True, 10 linked failure records, 1 candidate (STRAT-000002, REJECTED)
HYP-000002: refuted=False, 0 linked failures, 0 candidates
HYP-000003: refuted=False, 0 linked failures, 0 candidates
```

## 3. Horizon consistency audit (Phase 12)

`core.factory.horizon_consistency.audit_hypothesis_horizon` classifies each hypothesis's horizon relative to its source claim as `CONSISTENT`, `EXPLICIT_MECHANISTIC_TRANSFORMATION` (the hypothesis's own record states the horizon is this project's testable framing, not the source's), or `SILENT_HORIZON_DRIFT` (a horizon appears with no recorded justification anywhere).

```
HYP-000001: EXPLICIT_MECHANISTIC_TRANSFORMATION -- "this project's testable framing, not the source's words" is stated verbatim in the formalized rule
HYP-000002: EXPLICIT_MECHANISTIC_TRANSFORMATION -- registered explicitly as a 24-bar horizon synthesis, distinct from the 1-bar-tested / 12-bar-formalized territory
HYP-000003: SILENT_HORIZON_DRIFT -- reuses HYP-000001's 12-bar horizon with no recorded reason
```

**Finding, disclosed not silently fixed**: `HYP-000003`'s transformation_history explains its *mechanism* (regime-conditional continuation, distinct from its parents' reversion mechanism) but never explains *why 12 bars*. This is real, minor, and does not retroactively change `HYP-000003`'s `FORMALIZED` status — it is recorded here as a gap that should be closed (an explicit horizon-choice rationale added to the hypothesis record) before `HYP-000003` is ever formalized into a candidate.

## 4. Non-negotiable boundary respected

None of this module's computations feed a performance metric back into prioritization — `refutation_scope` and `similarity_class` are structural/textual classifications, not derived from any holdout/OOS number, preserving the Phase 16 feedback firewall `core.factory.research_prioritization.ResearchKnowledge` already enforces.
