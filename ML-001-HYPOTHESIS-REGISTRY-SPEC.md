# ML-001 — Hypothesis Registry Specification (Generation 2, Phase 4-5, 14)

**Status**: IMPLEMENTED and tested. Extends the Generation 1 `core/factory/hypothesis.py` (`ML-001-HYPOTHESIS-SOURCE-CONTRACT.md`) additively — every Generation 1 field/behavior is unchanged; Generation 2 adds fields and a second status axis.
**Code**: `core/factory/hypothesis.py`, `core/factory/hypothesis_formalization.py`, `core/factory/hypothesis_quality_gates.py`
**Referenced by**: `ML-001-GENERATION-2-SPEC.md` §3-§4.

---

## §1. Why Extended, Not Replaced

Generation 1's `HypothesisRecord`/`HypothesisRegistry` (`ML-001-HYPOTHESIS-SOURCE-CONTRACT.md`) had zero real records in production, so there was no migration risk — every new field below is additive with a safe default, and every Generation 1 test still passes unmodified. This avoids the two-competing-implementations problem a from-scratch rewrite would have created.

## §2. New Fields (additive)

`hypothesis_version`, `source_claim_id` (links to `core.factory.claim_registry.ClaimRecord`), `economic_mechanism`, `instrument_scope`, `timeframe_scope`, `feature_dependencies`, `target_definition`, `expected_direction`, `holding_period`, `regime_conditions`, `falsification_conditions`, `cost_assumptions` — all default to `"UNKNOWN"` (or empty tuple for `feature_dependencies`). `checksum()` hashes the content that defines what the hypothesis *claims* (statement, mechanism, scope, target, direction, falsification, version) — distinct from lifecycle bookkeeping, so it changes only when the hypothesis's substance changes.

## §3. Two Independent Status Axes

- **`evidence_level`** (Generation 1, unchanged): tracks progression toward real `StrategyRegistry` test evidence — `UNVALIDATED_CLAIM → FORMALIZED_UNTESTED → CANDIDATE_GENERATED → CANDIDATE_TESTED_NO_EDGE / CANDIDATE_TESTED_EDGE_NOT_PROVEN → CANDIDATE_HOLDOUT_PASSED`.
- **`formalization_status`** (Generation 2, new): tracks research-quality readiness — `DRAFT → FORMALIZED → ELIGIBLE → TESTED → {SUPPORTED, REFUTED}`, with `REJECTED`/`SUPERSEDED` reachable from any non-terminal status. Enforced by `HypothesisRegistry.transition_formalization_status()`, mirroring `core.factory.state_machine`'s linear-spine discipline.

**`SUPPORTED` must never be read as PROVEN EDGE.** It means only "the linked candidate's real test evidence did not refute this hypothesis" — nothing stronger. This is stated in code (module docstring, field docstring) and enforced structurally: reaching `SUPPORTED` requires walking through `TESTED` first, which itself requires `ELIGIBLE`, which requires passing every quality gate in §5 — there is no shortcut.

**Fabricated-PASS closure (found and fixed during this generation's own adversarial testing, §6 of `ML-001-GENERATION-2-REPORT.md`)**: direct construction of a `HypothesisRecord` claiming a terminal `formalization_status` (`SUPPORTED`/`REFUTED`/`REJECTED`/`SUPERSEDED`) with empty `transformation_history` now raises `HypothesisSpecError` — symmetric to the pre-existing Generation 1 protection on `evidence_level`. Verified: `tests/test_generation2_adversarial.py::TestMalformedHypothesis::test_fabricated_supported_status_without_history_rejected`.

## §4. Formalization Engine

`core/factory/hypothesis_formalization.py::FormalizationSpec` — the nine mandatory, explicit components (per the task's own worked example):

```
INPUTS · CONDITION · SIGNAL · TARGET · HORIZON · DIRECTION · REGIME · COST ASSUMPTIONS · FALSIFICATION RULE
```

plus `instrument_scope` (required so gate 4 in §5 can be satisfied at formalization time, not left for later). Every field is checked against a closed list of "vague" values (`""`, `"unknown"`, `"tbd"`, `"n/a"`, `"none"`, `"?"`, `"..."`) — a spec that technically fills a field with a non-answer is rejected exactly as if it were empty. `formalize_hypothesis()` applies the spec, advances **both** status axes (`evidence_level` and `formalization_status`), and refuses to re-formalize an already-`FORMALIZED` hypothesis in place (`FormalizationSpecError`) — a materially different formalization must be a new hypothesis version (§7 of `ML-001-GENERATION-2-SPEC.md`... see `ML-001-STRATEGY-FACTORY-SPEC.md` §5's versioning discipline, applied here by analogy).

Worked example (identical to the task's own, verified as a passing test — `tests/test_generation2_integration.py`):

```
Source claim: "RSI 14 crossing above 30 tends to precede short-term upward moves."
Condition:     rsi_14 < 30
Signal:        rsi_14 crosses above 30
Target:        future_return over 12 bars
Direction:     positive
Falsification: conditional expectancy <= 0 after realistic costs OR effect disappears out-of-sample
```

## §5. Hypothesis Quality Gates

`core/factory/hypothesis_quality_gates.py::evaluate_hypothesis_quality_gates()` checks, per the task's numbered list: (1) falsifiable, (2) target defined, (3) time horizon defined, (4) instrument scope defined, (5) feature dependencies known, (6) temporal availability known (every declared feature dependency must resolve to at least `CATALOGED_NOT_IMPLEMENTED` in `core.factory.feature_catalog` — an unrecognized name fails this gate), (7) cost assumptions explicit, (8) falsification conditions exist (same field as gate 1, not double-penalized), (9) source lineage exists, (10) search space explicit (checked only when a `SearchSpace` is supplied — candidate generation itself always requires one, enforced separately). Returns the **full list** of failed gates, never just the first — a caller building a `REJECT`/`HOLD`/`NEEDS_FORMALIZATION` classifier can act on the complete picture. `assert_hypothesis_eligible_for_candidate_generation()` is the fail-closed wrapper `core.factory.candidate_generation_engine` actually calls before generating anything.

No missing field is ever silently filled — every gate failure is a named, listed reason, not a default value substituted in.

## §6. What This Contract Does Not Do

- Does not ingest a real hypothesis from a real source.
- Does not implement a statistical test of whether any hypothesis is actually predictive — `TESTED`/`SUPPORTED`/`REFUTED` on the `formalization_status` axis require real `StrategyRegistry` evidence that this generation does not produce.
