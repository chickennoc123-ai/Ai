# ML-001 — Generation 2 Report

**Date**: August 19, 2026
**Task**: "ML-001 — STRATEGY RESEARCH FACTORY — GENERATION 2 — COMPLETE EXECUTION CONTRACT"
**Verdict**: **GENERATION_2 = COMPLETE**, as an infrastructure claim. `STRAT-000001` remains `REJECTED`, no `STRAT-000002` was created in production, `EDGE_STATUS` remains `NOT_PROVEN`.

---

## 0. Baseline verification (Phase 0.A)

On-disk state at task start, independently re-checked rather than trusted from the prior audit's summary: branch `claude/ea-factory-pro-system-bc9jaa`, commit `0b7e649` (the Generation 1 audit commit), clean worktree, **750/750** tests passing (re-run live, not assumed from the audit report's stated figure). `ML-001-GENERATION-1-INDEPENDENT-AUDIT.md` present, verdict `GENERATION_1_CONDITIONALLY_CONFIRMED`, 3 MEDIUM / 8 LOW / 3 INFORMATIONAL findings, 0 CRITICAL/HIGH/BLOCKING.

## 1. Phase 0 — Generation 1 Remediation

### G1-M1 — Production Wiring — **CLOSED**

`core/factory/research_pipeline.py::run_registered_walkforward()` — the one canonical entry point that consumes `DatasetRegistry`/`InstrumentRegistry` and calls the completely unmodified `core.ml_r2.walkforward_r2` functions (`compute_temporal_split`, `make_walk_forward_windows`, `generate_oos_predictions` — confirmed via `git diff` that `core/ml_r2/` has zero changes across this task). `DatasetRegistry.load_verified_dataframe()` (new method) is the only way this function obtains data — it re-checks eligibility and re-computes the on-disk file checksum on every call, so a tampered/synthetic/unverified/missing dataset cannot silently reach the economic pipeline.

**Behavioral proof the wiring is load-bearing, not decorative** (`tests/test_g1_m1_production_wiring.py`, 8 tests): a genuinely tampered file (overwritten after registration) is rejected (`DatasetIntegrityViolationError`); a synthetic-flagged dataset is rejected even with a valid path (`RealMarketDataEligibilityError`); an unregistered dataset id, a missing instrument registration, and a dataset with no recorded path are all rejected. One test runs the wired path against the **real, registered EURUSD dataset** at a deliberately tiny scale (`window_limit=1` of 65 available windows) — proving the wiring works against real data without claiming an economic result.

### G1-M2 — Holdout Access Linkage — **CLOSED**

`core/factory/holdout_access.py::HoldoutAccessEvent` — a required, validated argument to `StrategyRegistry.transition()` when entering `HOLDOUT_TESTED` (`HoldoutAccessEventRequiredError` if absent). The event asserts `candidate_id`, `candidate_version`, `dataset_id`, `dataset_checksum`, `holdout_partition_identity`, `access_timestamp`, `frozen_state_confirmed` (must be `True`), `evidence_reference` — and is cross-checked against the actual candidate being transitioned (`validate_holdout_access_event`, wrong candidate id or version rejected). The event's checksum is recorded in the candidate's own `history`, so the audit trail preserves exactly which event authorized the transition.

**No real holdout data was touched** — every test in `tests/test_g1_m2_holdout_access_linkage.py` (18 tests) uses synthetic fixture identifiers (`_holdout_event()` in `tests/test_factory_registry.py`), per the task's explicit instruction.

### G1-M3 — Vacuous Assertion — **CLOSED**

The original assertion (`tests/test_generation1_foundation_integration.py`) guarded on a dict key `DatasetRecord.to_dict()` can never produce (a `@property`, not a field) — always vacuously true. Replaced with a real assertion on the reconstructed `DatasetRecord` object's actual `is_real_market_data_eligible` property and `assert_real_market_data_eligible()`. **A new adversarial test proves the replacement can genuinely fail**: a deliberately mutated (synthetic-flagged) copy of the same artifact is confirmed to correctly fail both checks (`test_audit_artifact_eligibility_assertion_actually_fails_on_ineligible_data`).

```
G1_MEDIUM_FINDINGS_CLOSED = YES (3/3)
```

## 2. Phases 1-14 — Research Pipeline Modules

| Phase | Module | Status |
|---|---|---|
| 1-2 | `core/factory/research_source_registry.py` | IMPLEMENTED, tested (14 source types, honest UNKNOWN defaults, versioning, dedup) |
| 3 | `core/factory/claim_registry.py` | IMPLEMENTED, tested (status lifecycle, SUPPORTED reachable only via TESTED) |
| 4 | `core/factory/hypothesis.py` (extended) | IMPLEMENTED, tested (additive fields, dual status axes, fabricated-PASS closure — see §6) |
| 5 | `core/factory/hypothesis_formalization.py` | IMPLEMENTED, tested (9 mandatory components, vague-value rejection) |
| 6 | Pipeline wiring (source→claim→hypothesis→formalization→eligible) | IMPLEMENTED, proven end-to-end (`tests/test_generation2_integration.py`) |
| 7 | `core/factory/market_universe_ontology.py` | IMPLEMENTED (ontology only; `REAL_DATA_VERIFIED` requires an actual registry check, never asserted from ontology membership — only EURUSD/GBPUSD currently resolve to it) |
| 8 | `core/factory/feature_catalog.py` | IMPLEMENTED (13 families cataloged; only the 5 real FE-R2-001/003 features are `IMPLEMENTED`, checked directly against `fe_r2_001.FEATURE_ORDER`) |
| 9 | `core/factory/search_space.py` | IMPLEMENTED, tested (immutable, hashed, `combination_count()` verified against the task's own worked example: 216) |
| 10 | `core/factory/candidate_generation_engine.py` | IMPLEMENTED, tested (lineage-aware checksum, quality-gated, no placeholder substitution) |
| 11 | `core/factory/research_ledger.py` | IMPLEMENTED, tested (append-only, no update/delete method exists, tamper-evident checksum) |
| 12 | `core/factory/research_accounting.py` | IMPLEMENTED, tested (pure aggregator, `SELECTION_BIAS_STATUS` never `PASS`) |
| 13 | Deduplication | IMPLEMENTED across Source/Claim/Hypothesis/SearchSpace registries, each `find_duplicate()` exact-match on defining content, never fuzzy |
| 14 | `core/factory/hypothesis_quality_gates.py` | IMPLEMENTED, tested (10 gates, full failure list returned, no silent field-filling) |

## 3. Phase 15-17 — Integration, Adversarial, Reproducibility

**Integration** (`tests/test_generation2_integration.py`): one real, small, synthetic fixture walks `SOURCE → CLAIM → HYPOTHESIS → FORMALIZATION → SEARCH SPACE → CANDIDATE → RESEARCH LEDGER → SEARCH ACCOUNTING → REGISTRY`, and full lineage is reconstructed **backward** from the final candidate to the original source (`candidate.hypothesis_id → hypothesis.source_claim_id → claim.source_id → source.source_id`), with every identity/checksum along the chain independently re-derivable. The fixture candidate is explicitly rejected at the end (`strat_reg.reject(...)`) — never a fabricated PASS — and lives entirely in a `tmp_path` registry; the production `reports/factory/strategy_registry.json` is never opened by this file.

**Adversarial** (`tests/test_generation2_adversarial.py`, 29 tests): all 17 named categories covered — source mutation, duplicate source, duplicate hypothesis, malformed hypothesis, missing target, missing timeframe, missing instrument, feature look-ahead, search-space mutation, frozen candidate mutation, fake PASS state, accounting mismatch, missing provenance, unverified-source-pretending-verified, synthetic-pretending-real, candidate lineage corruption, ledger mutation. Every test is behavioral (constructs the actual violation and confirms the actual exception), not a static source grep — the two grep-style tests attempted during authoring were found to be self-referentially broken (matching their own assertion strings) and were replaced with real behavioral tests or removed, not patched around.

**Reproducibility** (`tests/test_generation2_reproducibility.py`, 10 tests): source/claim/hypothesis/search-space identity checksums are content-based and reproducible across independently-constructed objects; hypothesis checksum reproducibility is confirmed across a **genuine subprocess spawn**, not just same-process repetition; seeded parameter draws (`sample_param_draws`) are deterministic per seed and confirmed to never touch the global `random` module.

## 4. Phase 18 — Documentation

**Created**: `ML-001-GENERATION-2-SPEC.md`, `ML-001-RESEARCH-SOURCE-SPEC.md`, `ML-001-HYPOTHESIS-REGISTRY-SPEC.md`, `ML-001-RESEARCH-LEDGER-SPEC.md`, `ML-001-SEARCH-SPACE-SPEC.md`, `ML-001-GENERATION-2-REPORT.md` (this document).
**Updated**: `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` — one status note added (Generation 2 exists, G1 MEDIUM findings closed), zero prior claims invalidated.

## 5. Phase 19 — Full Test Suite

```
python3 -m pytest --collect-only -q   →   850 tests collected
python3 -m pytest -q                  →   exit code 0, zero failures, zero errors
```

850 = 750 (Generation 1 audit baseline, re-verified) + 100 new (27 closing the three G1 MEDIUM findings + 73 new Generation 2 pipeline/integration/adversarial/reproducibility tests). No existing test was deleted or weakened. Every pre-existing test that referenced `HOLDOUT_TESTED` (5 files, `grep`-confirmed) was updated to supply the now-required `HoldoutAccessEvent` — a genuine behavioral requirement change (G1-M2), not a relaxation.

## 6. Phase 20 — Independent Internal Self-Audit

Performed by re-reading code and re-running behavioral checks live in this task, not by trusting the implementation summary above.

- **A-D. Source/claim/hypothesis/candidate lineage**: re-verified via the actual integration test's backward reconstruction (§3) — passing, not merely asserted.
- **E. Search accounting**: `compute_search_accounting_summary()` re-read in full; confirmed it has no code path producing `"PASS"` for `SELECTION_BIAS_STATUS` — the function's only two possible values are `"UNACCOUNTED"`/`"ACCOUNTING_ONLY"`, both hard-coded, no third branch exists.
- **F. Registry integrity**: every new registry (`ResearchSourceRegistry`, `ClaimRegistry`, `HypothesisRegistry` (extended), `SearchSpaceRegistry`) uses the same atomic-write-then-rename persistence pattern as `core.factory.registry.StrategyRegistry` (verified by direct read of each `_save()` method) — a crash mid-write cannot corrupt any of them.
- **G. Ledger immutability**: `dir(ResearchLedger)` was inspected directly (not just documented) to confirm no `update`/`delete`/`remove` method exists; `LedgerEvent` confirmed frozen via a live `FrozenInstanceError` check.
- **H. Candidate immutability**: the two new fields added to `StrategyCandidate` (`search_space_id`, `candidate_checksum`) do not weaken `_FROZEN_OR_LATER`/`assert_mutation_allowed` — re-verified live that a candidate generated via the new engine is still correctly blocked from mutation at `OOS_TESTED`.
- **I. Temporal safety**: `core/factory/feature_catalog.py` was re-read to confirm `implementation_status()` checks directly against `fe_r2_001.FEATURE_ORDER` (not a hard-coded duplicate list that could drift) — and `git diff` confirms `core/features/fe_r2_001.py` has zero changes across this entire task, so its existing, independently-audited no-lookahead guarantee (`ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` §3) is untouched.
- **J. Provenance**: dataset/instrument eligibility checks re-run live against the real production registries in this task (not merely re-asserted from a prior run).
- **K. Deterministic identity**: hypothesis-checksum reproducibility re-verified via a genuine subprocess spawn in this task's own test suite, not assumed.
- **L. Multiple-testing accounting**: `MultipleTestingAccountingRequiredError` re-confirmed live to still block `MULTIPLE_TESTING_REVIEWED` without prior `set_search_space()`.
- **M. Generation 1 compatibility**: full suite re-run at the end of this task (§5) — 850/850, including every pre-existing Generation 1 test file, unmodified in intent (only the 5 files requiring the new `HoldoutAccessEvent` argument were touched, and only at their `HOLDOUT_TESTED` call sites).
- **N-P. Production wiring / holdout linkage / vacuous-test remediation**: §1 above, each with its own dedicated adversarial proof, re-run in this final pass.
- **Production registry integrity, checked live in this final pass**: `StrategyRegistry().list_all()` against the real `reports/factory/strategy_registry.json` returns exactly `["STRAT-000001"]`, state `REJECTED` — confirmed unchanged by this entire task. `ls reports/factory/` confirms no `research_source_registry.json`/`claim_registry.json`/`hypothesis_registry.json` (beyond the pre-existing, still-empty Generation 1 one)/`search_space_registry.json`/`research_ledger.json` exists in production — every Generation 2 registry created during this task lives only in test `tmp_path` fixtures.
- **Fabricated-PASS gap found and closed during self-audit**: while writing the adversarial tests (§3), direct construction of a `HypothesisRecord` claiming a terminal `formalization_status` (e.g. `SUPPORTED`) with empty `transformation_history` was found to succeed silently — a real fabricated-evidence vulnerability, symmetric to a protection that already existed for `evidence_level` but had not been extended to the new axis. Fixed in `core/factory/hypothesis.py.__post_init__` (mirrors the existing guard exactly) and locked in as a permanent regression test (`tests/test_generation2_adversarial.py::TestMalformedHypothesis::test_fabricated_supported_status_without_history_rejected`). This is reported here explicitly rather than silently folded into the "already correct" implementation summary, per the task's own "do not trust your own implementation summary" instruction.

## 7. Final Status Report

```
GENERATION_2_STATUS          = COMPLETE

G1_MEDIUM_FINDINGS_CLOSED     = YES

SOURCE_REGISTRY               = IMPLEMENTED
CLAIM_REGISTRY                = IMPLEMENTED
HYPOTHESIS_REGISTRY           = IMPLEMENTED (extended, backward-compatible)
FORMALIZATION_ENGINE          = IMPLEMENTED
SEARCH_SPACE                  = IMPLEMENTED (immutable, hashed, versioned)
CANDIDATE_GENERATOR           = IMPLEMENTED
RESEARCH_LEDGER               = IMPLEMENTED (append-only, verified no update/delete path)
SEARCH_ACCOUNTING             = IMPLEMENTED (pure aggregator, SELECTION_BIAS_STATUS never PASS)
LINEAGE                       = VERIFIED (candidate -> hypothesis -> claim -> source, backward-reconstructed)
REPRODUCIBILITY               = VERIFIED (cross-process checksum match; seeded, non-global-state sampling)
ADVERSARIAL_TESTING           = COMPLETE (17/17 named categories, all behavioral)
INTEGRATION                   = COMPLETE (end-to-end, tmp_path-isolated)
DOCUMENTATION                 = COMPLETE (5 new specs + this report + 1 minimal update)

TOTAL_SOURCES                 = 0  (production; test fixtures are isolated, not counted here)
TOTAL_CLAIMS                  = 0
TOTAL_HYPOTHESES              = 0
TOTAL_FORMALIZED_HYPOTHESES   = 0
TOTAL_SEARCH_SPACES           = 0
TOTAL_CANDIDATES_GENERATED    = 1  (STRAT-000001, pre-existing, unchanged by Generation 2)
TOTAL_CANDIDATES_TESTED       = 1
TOTAL_CANDIDATES_REJECTED     = 1
TOTAL_CANDIDATES_SURVIVING    = 0

SELECTION_BIAS_STATUS         = UNACCOUNTED  (production; single pre-existing candidate,
                                 consistent with every prior report -- Generation 2 introduces
                                 no new production candidate to account for)

STRAT-000001_STATUS           = REJECTED
STRAT-000002_STATUS           = NOT_CREATED  (no test fixture in this generation was registered
                                 in, or capable of reaching, the production strategy_registry.json)
EDGE_STATUS                   = NOT_PROVEN

GENERATION_3_STATUS           = NOT_STARTED

TESTS                         = PASS
TEST_COUNT                    = 850 / 850

GIT_STATUS                    = see commit below (clean after commit)
DOCUMENTS_CREATED             = ML-001-GENERATION-2-SPEC.md, ML-001-RESEARCH-SOURCE-SPEC.md,
                                 ML-001-HYPOTHESIS-REGISTRY-SPEC.md, ML-001-RESEARCH-LEDGER-SPEC.md,
                                 ML-001-SEARCH-SPACE-SPEC.md, ML-001-GENERATION-2-REPORT.md
DOCUMENTS_UPDATED             = ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md (minimal status note only)

KNOWN_LIMITATIONS:
  - No real hypothesis has been ingested from any real external source -- every Generation 2
    registry is exercised only by synthetic, clearly-fictional test fixtures.
  - Market universe / feature catalog are ontology/cataloging layers only -- no new real
    instrument data or new real feature was added.
  - Research Ledger does not itself force every registry mutation to be accompanied by an
    entry -- callers must call append() correctly; the integration test demonstrates but
    cannot enforce this pattern on all future callers.
  - No formal multiple-testing statistical correction exists yet -- only the accounting
    infrastructure a future correction would consume.

OPEN_GOVERNANCE_DECISIONS:
  - None encountered that required silent resolution. Every extension made (new fields on
    HypothesisRecord/StrategyCandidate, the new formalization_status axis, the holdout access
    event requirement) was additive/backward-compatible or explicitly required by this task's
    own instructions (G1-M1/M2/M3), not a judgment call about ambiguous existing governance.
```

## 8. What This Task Does Not Do

- Does not create `STRAT-000002` in the production registry.
- Does not ingest any real hypothesis, paper, website, or YouTube video.
- Does not download or fabricate any new market dataset.
- Does not implement any new real feature/indicator beyond the existing five.
- Does not claim an edge, anywhere.
- Does not begin Generation 3.
