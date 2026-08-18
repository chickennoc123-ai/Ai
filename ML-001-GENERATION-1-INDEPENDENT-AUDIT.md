# ML-001 — Generation 1 Independent Audit

**Date**: August 18, 2026
**Auditor stance**: independent, observational. No implementation, governance, specification, or test file was modified in the course of this audit. Every claim below was checked directly against on-disk code, tests, artifacts, or git history at the time of this audit — nothing is carried over from the prior completion report without independent re-verification.
**Audited claim**: `GENERATION_1_STATUS = COMPLETE`, commit `9da97fe`, `750/750` tests, clean worktree.

---

## 1. Executive Verdict

**`GENERATION_1_CONDITIONALLY_CONFIRMED`**

The governance, Data Factory, Market Universe, and Feature Factory subsystems are genuinely implemented (not merely documented), independently re-verified to behave as claimed on every point this audit could re-check, and covered by real (not merely cosmetic) tests. No CRITICAL or HIGH finding was identified. No fabricated PASS state, no leakage into the real economic evidence, no modification of frozen/canonical economic files, and no inflation of the `STRAT-000001`/`EDGE_STATUS` facts was found anywhere.

However, three MEDIUM findings are real, material, and not disclosed with full clarity in the prior completion report: (1) the new Data/Market/Feature Factory registries are **not wired into the production `core/ml_r2/*` pipeline** that actually produced `STRAT-000001`'s evidence — they exist as correct, tested, standalone infrastructure, not yet an enforced gate; (2) a candidate's `HOLDOUT_TESTED` state-machine label is **pure bookkeeping**, not programmatically tied to a verified `PURE_HOLDOUT` data-access event; (3) one integration test contains a **vacuous assertion** that always passes regardless of the underlying data. None of these invalidate what was actually built — the foundation itself is sound — but they mean "COMPLETE" should be read as "the described infrastructure exists, is correct, and is tested," not as "the production pipeline is now gated by this infrastructure."

---

## 2. Repository Baseline

```
git rev-parse HEAD          -> 9da97fe322bdc5227a06fc2603d59b7b48b6facd
git status --short          -> (empty; clean)
python3 -m pytest -q        -> exit code 0, 0 failures
python3 -m pytest --collect-only -q | sum -> 750 tests collected
```

All four figures independently reproduced in this audit session, not copied from the prior report.

---

## 3. Governance Audit

### A. Candidate state machine — code-traced, not doc-trusted

Read directly: `core/factory/state_machine.py` (full file). The `_FORWARD_SPINE` list, in order:

```
GENERATED, DATA_VALIDATED, TRAINED, OOS_TESTED, WFA_TESTED, ROBUSTNESS_TESTED,
COST_TESTED, STATISTICALLY_VALIDATED, MULTIPLE_TESTING_REVIEWED, FROZEN,
HOLDOUT_TESTED, EVG_REVIEW, RESEARCH_CANDIDATE, PAPER_VALIDATION, LIVE_CANDIDATE
```

`_ALLOWED_TRANSITIONS` is mechanically derived from this list (no separate hand-maintained transition table to drift). Independently queried in this audit session:

```python
>>> [s.value for s,nexts in _ALLOWED_TRANSITIONS.items() if CandidateState.HOLDOUT_TESTED in nexts]
['FROZEN']
>>> [s.value for s,nexts in _ALLOWED_TRANSITIONS.items() if CandidateState.EVG_REVIEW in nexts]
['HOLDOUT_TESTED']
```

**PASS** — `HOLDOUT_TESTED` is reachable from exactly `FROZEN`; `EVG_REVIEW` is reachable from exactly `HOLDOUT_TESTED`. No other path exists.

**Rejection from intermediate states** — every non-`LIVE_CANDIDATE` state in the spine gets `REJECTED`/`FAILED` added to its allowed-next set by the same loop (`state_machine.py` lines ~80-86). Verified directly: `assert_legal_transition(CandidateState.TRAINED, CandidateState.REJECTED)` succeeds without walking any other state. **PASS**.

**A candidate is not forced through PURE_HOLDOUT before rejection** — confirmed both structurally (the above) and empirically: `STRAT-000001`'s real, on-disk history (`reports/factory/strategy_registry.json`, re-read live in this audit) is exactly `GENERATED → DATA_VALIDATED → TRAINED → REJECTED`. `HOLDOUT_TESTED` never appears. **PASS, with real production evidence, not just a synthetic test.**

Tests: `tests/test_factory_state_machine.py` (24 tests, includes `test_full_forward_spine_is_legal`, `test_holdout_is_the_last_gate_before_evg`), `tests/test_generation1_phase0_audit.py` (18 tests, each named directly after this task's own §0.2 transition list — `test_trained_to_rejected`, `test_oos_to_rejected`, ... `test_multiple_testing_to_freeze`, `test_freeze_to_holdout`, `test_holdout_to_pass_or_fail`, etc.), all independently re-run in this audit and confirmed passing.

### B. Holdout-last semantics — traced in code, not merely documented

Confirmed by direct code read (§A above) and by the `_FORWARD_SPINE` comment block, which itself states the exact ordering the task specifies. The implementation genuinely matches: `TRAIN → OOS → WFA → ROBUSTNESS → COST → STATISTICS → MULTIPLE_TESTING → FREEZE → PURE_HOLDOUT → EVG`. **PASS.**

### C. Holdout contamination

- **Can holdout data enter training?** Not through any Generation-1-introduced code path — none of the new registries touch training data at all. The actual training/WFA pipeline (`core/ml_r2/walkforward_r2.py::generate_oos_predictions`) never includes holdout rows in the DataFrame passed to it in the one real run this project has performed (`pd.concat([split.development, split.validation])`, confirmed in `ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` §7, not re-litigated here since Generation 1 did not touch this file). **PASS, by inheritance from prior work, not by anything new in Generation 1.**
- **Can holdout data enter feature fitting?** Same answer — `core/features/fe_r2_001.py` was not modified by Generation 1 (confirmed: `git diff c1affc6 9da97fe -- core/features/` produces no output).
- **Can holdout results influence optimization?** `core.provenance_enforcement.ProvenanceEnforcer.validate_access(PURE_HOLDOUT, SELECTION)` raises `DataStateViolationError` — re-verified directly in this audit: `enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.SELECTION)` raises as expected. **PASS.**
- **Can holdout results mutate a frozen candidate?** No — `StrategyCandidateSpec` is a frozen dataclass; `StrategyRegistry.assert_mutation_allowed()` raises `FrozenCandidateMutationError` for any state in `_FROZEN_OR_LATER` (which includes `HOLDOUT_TESTED`). Re-verified live via `tests/test_factory_holdout_governance.py::TestFinalHoldoutSemantics::test_holdout_tested_candidate_is_also_mutation_blocked`. **PASS.**
- **Can holdout accidentally be accessed before freeze?** Structurally no — `HOLDOUT_TESTED` is reachable only from `FROZEN` (§A). **PASS at the state-machine level.**

**Finding G1 (MEDIUM, NON_BLOCKING)**: the state-machine's `HOLDOUT_TESTED` label and the runtime `ProvenanceEnforcer`/`ProvenanceGuard` data-access guard are **two independent modules with no code-level cross-enforcement**. Confirmed by grep: `core/factory/registry.py` and `core/factory/state_machine.py` contain zero references to `provenance_enforcement`, `dataset_provenance`, `ProvenanceEnforcer`, or `ProvenanceGuard`. `StrategyRegistry.transition(candidate_id, CandidateState.HOLDOUT_TESTED, reason="...")` will succeed on a bare string `reason`, with no verification that a real, provenance-guarded `PURE_HOLDOUT` access actually occurred for this candidate. In this project's one real case (`STRAT-000001`), this was never exploited — `HOLDOUT_TESTED` was never entered at all, precisely to avoid needing to make this claim. But the *mechanism* that would prevent a future candidate from having its registry state say `HOLDOUT_TESTED` without a corresponding real, verified holdout access does not exist in code — it is a human/process discipline, not a structural guarantee. This is worth remediating before Generation 2 registers a candidate that actually reaches this state.

### D. Candidate immutability

- **Specification** — `StrategyCandidateSpec` is `@dataclass(frozen=True)`; direct field mutation raises `dataclasses.FrozenInstanceError` (`tests/test_factory_holdout_governance.py::TestRejectedCandidateImmutability::test_strategycandidatespec_is_a_frozen_dataclass`, re-run, passes).
- **Parameters** — parameters are part of the same frozen spec (`stop_loss`, `take_profit`, `max_hold_bars`, etc.) — same guarantee.
- **Feature schema** — `spec.features: tuple` is part of the same frozen spec — same guarantee. No separate feature-schema field exists to independently mutate.
- **Model identity** — **Finding G2 (LOW, NON_BLOCKING, classified UNVERIFIED rather than PASS per this audit's own instruction)**: `StrategyCandidate`/`StrategyCandidateSpec` (`core/factory/candidate.py`, both classes read in full) contain **no field at all** representing a trained model's identity (checksum, `structural_fingerprint`, or model version). Model provenance lives entirely in a separate, structurally unlinked system (`core.ml_r2.model_r2.ModelMetadata`, `core.ml_r2.provenance_r2.RunProvenance`), which the Factory registry never references. The task's item D asks to verify a frozen candidate's model identity cannot be mutated — there is currently nothing on the candidate object to protect, so this specific sub-claim cannot be marked PASS; it is **UNVERIFIED / not applicable to the current architecture**, disclosed honestly rather than silently passed.
- **Swap-in-place blocked** — `StrategyRegistry.assert_mutation_allowed()` blocks a caller from replacing `candidate.spec` with a different object once `_FROZEN_OR_LATER` (starts at `OOS_TESTED`) is reached. Re-verified: `tests/test_factory_registry.py::TestLifecycleAndImmutability::test_mutation_already_blocked_at_oos_tested_before_frozen`, passes.

### E. Version semantics

`StrategyRegistry.derive_new_version()` (`core/factory/registry.py` lines 329-356, read in full): mints a brand-new `candidate_id` via `register()`, sets `parent_candidate_id`, and **never** mutates the parent's stored record. Re-verified live: `tests/test_generation1_phase0_audit.py::test_any_modified_post_holdout_candidate_becomes_a_new_version` constructs exactly the `v1 → freeze → holdout → reject → derive v2` sequence the task specifies, confirms `v2.candidate_id != v1.candidate_id`, `v2.parent_candidate_id == v1.candidate_id`, `v1`'s own state remains `REJECTED`, and a direct attempt to re-transition `v1` to `HOLDOUT_TESTED` again raises `IllegalStateTransitionError`. **PASS**, exact pattern confirmed, both directions (the disallowed `v1 → holdout → modify v1 → retest` and the required `v1 → holdout → PASS/FAIL, modify → v2`).

**Finding G3 (LOW, INFORMATIONAL)**: `derive_new_version()`'s signature does not accept `hypothesis_id` or `instrument_universe`, so a derived `v2` candidate silently loses its parent's hypothesis lineage and per-instrument provenance unless a caller reconstructs them manually (which the current signature does not even allow). Not exercised by any real candidate to date; a completeness gap in an otherwise-correct mechanism.

### F. Multiple-testing accounting

Read `StrategyRegistry.transition()` and `_empty_search_history()` in full. Independently recomputed against the real production registry in this audit (not trusted from the prior report):

```
stored total_strategies_generated: 1   recomputed from list_all():        1
stored total_strategies_rejected:  1   recomputed (state == REJECTED):    1
```

Both match exactly. **PASS for the current real population.**

**Finding G4 (LOW, INFORMATIONAL)**: counters are incrementally maintained (`+= 1` on specific transitions inside `transition()`/`register()`), not recomputed/reconciled from the actual candidate population on every read. `_load()` accepts a hand-edited registry JSON file's `search_history` block without cross-checking it against the `candidates` block for internal consistency. No structural reconciliation test exists as a standing regression guard. Currently consistent in practice (verified above) but not structurally guaranteed against a future manual edit or a bug in a not-yet-written code path.

**Finding G5 (LOW, INFORMATIONAL)**: `total_strategies_tested` increments on reaching `CandidateState.DATA_VALIDATED`, earlier than a literal reading of "tested" might suggest (before OOS/WFA/robustness/statistics actually run). Accurate for `STRAT-000001` (which really was economically tested before rejection), but the counter's name is broader than its trigger condition.

**`MultipleTestingAccountingRequiredError`** (new in Generation 1's governance work): `transition()` raises this if `MULTIPLE_TESTING_REVIEWED` is attempted before `set_search_space()` has been called. Re-verified live: `tests/test_factory_holdout_governance.py::TestMultipleTestingGateEnforcement::test_cannot_enter_multiple_testing_reviewed_without_search_space_declared`, passes, and confirms the candidate's state is unchanged after the failed attempt. **PASS — this is a genuine, enforced gate, not a documentation-only claim.**

### G. Stale specification references

```
grep -rn "roadmap" --include="*.py" .          -> zero matches
grep -rn "Section [0-9]\+/\|Sections [0-9]" --include="*.py" .  -> 8 matches, ALL pointing at
    ML-001-R2-CLEAN-REBUILD-SPEC.md (a real, existing document), never at the old
    unfindable "Factory roadmap"
```

Cross-checked every referenced section number (2, 6, 7, 11, 16, 17) against `ML-001-R2-CLEAN-REBUILD-SPEC.md`'s actual `## N.` headings — **all exist**. `.md` files still mentioning "roadmap" (`ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md`, `ML-001-STRATEGY-FACTORY-SPEC.md`, two others) do so only to **document the historical fact that no such file was ever found** — not as live, active citations. **PASS — no stale reference remains in active governance logic.**

---

## 4. Data Factory Audit

### A-B. Registries exist and are actually used

`core/factory/data_source_registry.py` (171 lines, read in full), `core/factory/dataset_registry.py` (254 lines, read in full) — both real classes, both backed by real JSON persistence (`reports/factory/data_source_registry.json`, `reports/factory/dataset_registry.json`, both present on disk, both re-parsed successfully in this audit).

**Finding D1 (MEDIUM, NON_BLOCKING)**: "actually used" needs qualification. `grep -rln "dataset_registry\|instrument_registry\|feature_registry" --include="*.py" . | grep -v tests | grep -v core/factory/` returns **zero results**. These registries are used by (a) their own module code, (b) the dedicated test files, and (c) the standalone Phase-4 integration script whose output is `reports/factory/GENERATION1_FOUNDATION_AUDIT.json`. They are **not imported anywhere in `core/ml_r2/*`**, the actual pipeline that trained `RF-R2-001` and produced `STRAT-000001`'s real walk-forward evidence. This matches Phase 4's own explicit instruction ("infrastructure proof only... do not train a new model"), so it is not a violation of what was asked — but it means the registries currently function as a parallel, self-consistent, tested system, not yet an enforced gate on the real economic pipeline.

### C. Dataset identity is deterministic

`dataset_id` values (`DATASET-EURUSD-H1-KOMO135-V1`, `DATASET-GBPUSD-H1-KOMO135-V1`) are caller-assigned strings, not derived from content — deterministic in the sense that the same call always produces the same registration, and `DatasetRegistry.register()` raises `DuplicateDatasetError` on a second attempt with the same id (re-verified: `tests/test_data_factory.py::TestDataSourceRegistryPersistence::test_duplicate_source_id_rejected`, analogous dataset-level test not present but the underlying `register()` logic is identical to the analogous, tested `StrategyRegistry.register()` pattern — read directly, confirmed present at `dataset_registry.py` line ~215). **PASS.**

### D-E. Provenance persisted, checksums from real artifacts

Live-reparsed `reports/factory/dataset_registry.json` in this audit: both records contain `checksum` (raw source file SHA-256), `file_checksum` (normalized on-disk file SHA-256), `row_count`, `duplicate_count`, `missing_bar_count`, `gap_report`, `verification_method` — all present, all non-empty. **Checksums independently recomputed from the actual files on disk in this audit session** (not trusted from the registry or from any prior report):

```
EURUSD: sha256(data/csv/EURUSD_H1.csv) == registered file_checksum  -> True
GBPUSD: sha256(data/csv/GBPUSD_H1.csv) == registered file_checksum  -> True
```

**PASS, independently re-derived, not copied.**

### F-H. Provenance discipline — enforced in code

Read `DatasetRecord.__post_init__` in full (`core/factory/dataset_registry.py` lines ~118-147):

- `synthetic=True` requires `provenance_status="KNOWN_SYNTHETIC"` and vice versa — raises `DatasetSpecError` on any other combination. Re-verified live: constructing `synthetic=True, provenance_status="VERIFIED"` raises immediately.
- `provenance_status in (VERIFIED, VERIFIED_WITH_QUALIFICATION)` requires a non-empty `verification_method` — raises otherwise. Re-verified live.
- `license_status`/`provenance_confidence` on `DataSourceRecord` default to `"UNKNOWN"`/`"UNVERIFIED"` — confirmed both in the class defaults (`data_source_registry.py`) and in the live production registry entry (`SRC-KOMO135-FOREX-HISTORICAL-DATA`'s `license_status` is genuinely `"UNKNOWN"` on disk, not upgraded).
- `is_real_market_data_eligible` (a property, recomputed every access, never cached/stored) requires `synthetic=False AND provenance_status in (VERIFIED, VERIFIED_WITH_QUALIFICATION) AND integrity_status == "PASS"`, all three. Re-verified: flipping any one of the three to a disqualifying value in a scratch object flips the property to `False`.

**PASS — SYNTHETIC cannot silently become FALSE, REAL_MARKET_DATA eligibility cannot be asserted without satisfying all three conditions, and UNKNOWN/UNVERIFIED is never silently upgraded anywhere in this code.**

### I. No silent resampling/timezone conversion/gap filling/price transformation in the production data path

Traced the actual call path: `data/csv/EURUSD_H1.csv` is read via `pd.read_csv(..., parse_dates=True)` directly in every real training/WFA script this project has run (confirmed by the scripts referenced in `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md`) — no resampling, no additional timezone conversion beyond the one-time, disclosed acquisition-time shift (`DATASET_VALIDATION_REPORT.md` §2), no gap-filling (gaps are **admitted**, i.e. accepted as real closures, never filled with interpolated/forward-filled values — confirmed via `_check_weekday_gaps_v3`'s implementation, which only ever raises or admits, never fills).

**Finding D2 (LOW, INFORMATIONAL)**: a **separate, older module**, `core/data_manager.py`, does perform silent `tz_localize("UTC")`, silent duplicate-dropping (`~frame.index.duplicated(keep="last")`, no error raised), and resampling (`DataManager.resample()`). Confirmed via direct grep and read. **Confirmed NOT imported anywhere in `core/ml_r2/*` or `core/factory/*`** (`grep -rln "data_manager\|CSVProvider\|DataManager" core/ml_r2/*.py core/factory/*.py` returns zero results) — so it is outside the ML-001-R2/Generation-1 real-data path's scope, used only by other, unrelated strategies. Flagged for completeness since the audit's own definition of "silent" behavior technically matches it, even though it does not affect the audited path.

### J. Missing candles/gaps represented explicitly

`gap_report` field on `DatasetRecord` contains `admitted_gap_count` (502 for EURUSD, 500 for GBPUSD, matching `data/csv/GAP_ADMISSION_MANIFEST.json`'s `admitted_gap_count` exactly — cross-checked live), `usable_rows_after_warmup`, and a pointer to the full per-gap manifest. **PASS.**

### K-L. FE-R2-003/FE-R2-002 preserved

```
git diff c1affc6 9da97fe -- core/features/   -> (empty; zero changes to this file across
                                                 the entire Generation-1-labeled work)
```

`_check_weekday_gaps` (FE-R2-002, original) and `_check_weekday_gaps_v3` (FE-R2-003, additive) both confirmed present as distinct function objects (`tests/test_feature_factory.py::TestExistingGapPolicyPreserved`, re-run live, passes, including a direct re-test that the *original* function still rejects an arbitrary mid-week gap exactly as before). **PASS, and independently confirmed via git diff that Generation 1 touched this file zero times — not merely "claims to preserve it," provably never modified it.**

### M. Dataset validation — call path traced, not just function names

Read `_validate_ohlcv` in full (`core/features/fe_r2_001.py` lines 295-311) and confirmed it is called by `build_feature_matrix()` (line 474, `gap_admission_log = _validate_ohlcv(ohlcv)`) — the actual entry point every real feature-generation call uses. `_validate_ohlcv` checks: required columns present, `DatetimeIndex` type, duplicate timestamps (`df.index.has_duplicates`), strict monotonicity, then delegates to `_check_weekday_gaps_v3` for gap/timezone-window admission.

**Finding D3 (LOW, INFORMATIONAL)**: `_validate_ohlcv` — the **standing, repeatable** gate invoked on every `build_feature_matrix()` call — does **not** re-check OHLC consistency (high ≥ low, high ≥ open/close, etc.), positive prices, or abnormal single-bar moves. Those specific checks (`ohlc_high_violations`, `ohlc_low_violations`, `non_positive_prices`, `bars_with_gt5pct_move`) were performed **once**, by a separate, one-off acquisition/normalization script, and are recorded as historical findings in `data/csv/PROVENANCE_MANIFEST.json` — not re-verified by the reusable pipeline gate itself. A different, corrupted dataset fed through `build_feature_matrix()` directly would not be rejected on OHLC-consistency or positive-price grounds by this path alone (though `DatasetRegistry.integrity_status` is a separate field a caller could set to reflect such a check, if one were performed and recorded — it is not automatically derived).

---

## 5. Market Universe Audit

### A-B. Instrument and timeframe registries

`core/factory/instrument_registry.py` (183 lines, read in full). `InstrumentRegistry` backed by real JSON persistence (`reports/factory/instrument_registry.json`, re-parsed live, contains exactly `INSTR-EURUSD`, `INSTR-GBPUSD` — no fabricated third instrument). `SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")` is a fixed tuple, `is_supported_timeframe()`/`assert_supported_timeframe()` check membership only. **PASS — this is real code, not just an enum name with no behavior; `assert_supported_timeframe("W1")` genuinely raises `UnsupportedTimeframeError` (re-verified live).**

### C. Instrument/dataset compatibility

`assert_dataset_matches_instrument(dataset_symbol, dataset_timeframe, instrument)` (`instrument_registry.py`, read in full) raises `InstrumentSpecError` on a symbol mismatch. Re-verified live: constructing an instrument with `symbol="EURUSD"` and calling this function with `dataset_symbol="GBPUSD"` raises immediately. **PASS.**

### D. Explicit symbol identity through the chain

Traced: `DatasetRecord.instrument` → `InstrumentRecord.symbol` (checked via §C) → `StrategyCandidateSpec` has no direct symbol field (candidates are symbol-agnostic specs; symbol association happens via `dataset_id`/`instrument_universe`) → `DatasetProvenanceRecord.symbol` (part of `StrategyCandidate.instrument_universe`, `core/factory/candidate.py`) → training/evaluation artifacts (`RunProvenance.dataset_id`, `core/ml_r2/provenance_r2.py`, pre-existing, unrelated to Generation 1's new registries).

**Finding M1 (MEDIUM, NON_BLOCKING, same root cause as D1)**: this chain is **provable as architecture** (each link's type/field exists and is tested) but is **not automatically enforced end-to-end** by any single call path in production, because — as established in §4.A — the new registries are not wired into `core/ml_r2/*`. The chain exists as disconnected, individually-correct pieces, not yet as one enforced pipeline for real training runs.

### E-F. No silent substitution, no implicit cross-instrument validity

`assert_dataset_matches_instrument`'s adversarial rejection re-verified live (§C). `research_scope` defaults to `"SINGLE_INSTRUMENT"` on every candidate spec (`core/factory/candidate.py`, confirmed via direct field read) — never inferred as broader after the fact. **PASS.**

### G. Research scope

`RESEARCH_SCOPES = frozenset({"SINGLE_INSTRUMENT", "INSTRUMENT_FAMILY", "MULTI_INSTRUMENT"})` (`instrument_registry.py`) — confirmed enforced at `StrategyCandidateSpec.__post_init__` (raises `CandidateSpecError` on an unrecognized value, re-verified live with `research_scope="ALL_INSTRUMENTS_AT_ONCE"`). **PASS.**

### H. Cost-model references, no fabrication

`InstrumentRecord.cost_model_reference` for both real instruments points at `ML-001-R2-CLEAN-REBUILD-SPEC.md sec 7`, a real, existing, already-used cost model (`core/ml_r2/backtest_r2.py::BacktestConfig`) — not a newly-invented figure. Default is `"UNKNOWN"` when unestablished (class default, confirmed in source). **PASS.**

### I. Unknown metadata remains unknown

Live-reparsed production registry: `INSTR-EURUSD.venue_provider == "UNKNOWN"`, `.tick_size == "UNKNOWN"` — both genuinely unestablished facts, correctly not guessed. **PASS.**

---

## 6. Feature Factory Audit (high-importance, per task instruction)

### A-C. Feature contract, versioning, schema identity

`core/factory/feature_registry.py` (169 lines, read in full). `build_feature_contracts()` calls `fe_r2_001.get_feature_schema()` directly — confirmed by source read, this is a **wrapper, not a parallel reimplementation**; `tests/test_feature_factory.py::test_contract_definition_is_taken_verbatim_from_pipeline_schema` re-verified live, passes. `feature_schema_identity()` (SHA-256 of an ordered feature-id tuple) independently re-verified in this audit session, in two genuinely separate `python3` process invocations:

```
run A: f6e2473d9cf5055707f59c14ef741cecc79d62ba5e637313668e8ee8ba21739f
run B: f6e2473d9cf5055707f59c14ef741cecc79d62ba5e637313668e8ee8ba21739f
```

Identical, and identical to the value stored in `reports/factory/GENERATION1_FOUNDATION_AUDIT.json`. **PASS — genuinely reproducible, independently re-derived, not copied from any report.**

### D-H. Temporal semantics, lookback/warmup, rolling-window, shift, normalization

- **`feature(t)` uses only `t ≤ now`**: this is `fe_r2_001.py`'s own pre-existing, already-verified guarantee (future-injection check, `ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` §3, 0 mismatches across 5 features × 28,800 real rows) — Generation 1 did not modify this file (confirmed §4.K-L), so this guarantee is unchanged, and re-confirmed by `tests/test_ml_001_r2_adversarial.py`'s pre-existing tests, still passing.
- **Warmup boundary**: `tests/test_feature_factory.py::test_warmup_boundary_is_exactly_enforced_not_approximate` checks every feature's `NaN` boundary against `WARMUP_BARS[feature]` bar-by-bar on synthetic data. Re-run live, passes.
- **Rolling-window/shift semantics**: **Finding F1 (LOW, NON_BLOCKING)**: `test_no_feature_implementation_uses_a_centered_rolling_window` and `test_no_feature_implementation_calls_a_global_fit_scaler` (`tests/test_feature_factory.py`) are **static source-string greps** (`assert "center=True" not in source`), not behavioral/injection tests. They correctly describe the current implementation's absence of these patterns, but would not catch a disguised violation (a renamed import, a boolean passed via an intermediate variable, `center=(1==1)`). This is a real limitation of the adversarial coverage's depth, though the task itself instructs "do not attempt to prove arbitrary user code is mathematically leakage-free... make temporal semantics explicit and testable" — under that framing, this is an acceptable, disclosed limitation rather than a defect, but it should not be over-read as a strong guarantee against a determined future violation.
- **Target separation**: `test_no_feature_is_literally_derived_from_the_forward_label` computes real Pearson correlation between each feature and the forward label on synthetic data, asserts `|corr| < 0.9` for all five. Re-run live, passes (this is a genuine behavioral test, not a grep).
- **Normalization/scaling**: confirmed (via the same static grep, same limitation as above) that no `StandardScaler`/`MinMaxScaler`/`.fit_transform(` exists in `fe_r2_001.py` — and independently confirmed by direct read of the module that no scaling logic of any kind is present (the five features are used directly by a tree-based model, which does not require scaling) — this specific claim is also independently supported by inspection, not just the grep test.

### I-K. Leakage adversarial tests, cross-split contamination, FE-R2-003 integration

`tests/test_feature_factory.py` (19 tests) + pre-existing `tests/test_ml_001_r2_adversarial.py`/`tests/test_ml_001_r2_leakage_integration.py` (23 + 7 tests, unmodified, still passing) collectively cover: future shift, shuffled timestamps, duplicate timestamps, arbitrary gap rejection, feature-version drift, dataset-checksum sensitivity, and holdout/validation access blocking (cross-split contamination, via `ProvenanceEnforcer`). **PASS, broad and largely genuine coverage**, with the one disclosed static-grep limitation (F1).

### L. Existing FE-R2-003 integration

Confirmed: `feature_registry.py` reads `FEATURE_VERSION`, `FEATURE_ORDER`, `WARMUP_BARS`, `get_feature_schema()` directly from `fe_r2_001.py` — no independent redefinition. **PASS.**

### M. Reproducibility of feature output

Re-verified live in this audit (§6.A-C) across two separate process invocations — byte-identical schema identity. The committed test suite's own `TestReproducibilityAcrossFreshProcesses` tests, however, call `canonical_schema_identity()` twice **within the same test process**, not via a genuine subprocess spawn — the truly cross-process proof was performed via a standalone script (not part of the committed, automated test suite) in the original Generation 1 task, and independently re-confirmed by this audit just now via two separate shell invocations. **Finding F2 (LOW, INFORMATIONAL)**: the cross-process reproducibility claim is TRUE (re-confirmed live) but is not encoded as a permanent, automated regression test — only as same-process idempotency in the committed suite, plus a one-time manual/scratch verification.

### N. Feature provenance answers "what exact implementation generated this column?"

`FeatureContract.formula_reference == "core/features/fe_r2_001.py (canonical, single implementation)"` for every feature — confirmed via direct read, this is accurate (no second feature implementation exists anywhere in the repository; confirmed via `grep -rln "def compute_momentum\|def compute_rsi_14\|def compute_atr_14" --include="*.py" .` returning only `fe_r2_001.py`). **PASS.**

---

## 7. Integration Audit

Traced the actual, executable path (not documentation): `core/factory/dataset_registry.DatasetRegistry.get()` → `assert_real_market_data_eligible()` → `core/factory/instrument_registry.InstrumentRegistry.get_by_symbol()` → `assert_dataset_matches_instrument()` → `core/factory/feature_registry.build_feature_contracts()`/`canonical_schema_identity()` → `core/features/fe_r2_001.build_feature_matrix()` → provenance-trace dict → `reports/factory/GENERATION1_FOUNDATION_AUDIT.json`.

Re-executed the equivalent of this chain live in this audit (not merely re-reading the artifact):

```
DATASET-EURUSD-H1-KOMO135-V1 eligible: True (independently re-checked)
file checksum matches on-disk file: True (independently recomputed)
feature schema identity: f6e2473d9cf5055707f59c14ef741cecc79d62ba5e637313668e8ee8ba21739f
  (matches artifact, matches two fresh-process re-derivations)
usable_rows_after_warmup: 57000 / total_rows: 57600 (matches artifact)
```

**Symbol/timeframe cannot silently change**: `assert_dataset_matches_instrument` and `assert_supported_timeframe` are both called in this chain and both independently re-verified to reject a mismatch (§4-5). **PASS.**

**Feature schema identity remains intact through the pipeline**: confirmed identical between the standalone integration run, the committed artifact, and two fresh re-derivations in this audit. **PASS.**

**Reproducibility in a fresh process**: **CONFIRMED, BENIGN** — re-verified live via two genuinely separate `python3` process invocations in this audit, byte-identical output. No nondeterminism was found anywhere in this specific path (distinct from, and not affected by, the previously-documented and separately-mitigated `RandomForestClassifier`/joblib checksum artifact from the prior forensic task — this path trains no model at all, so that artifact's trigger condition, `joblib.load()`, never occurs here).

**Overall integration verdict**: the described end-to-end path **is genuinely executable code**, not documentation — re-run and re-verified independently in this audit. The one qualification (already raised as Finding D1/M1) is that this path is a **standalone proof**, not (yet) the path any real training/evaluation script actually calls.

---

## 8. Test-Quality Audit

`grep -c "def test_"` re-counted live for each Generation-1-specific file: `test_data_factory.py` 23, `test_market_universe.py` 20, `test_feature_factory.py` 19, `test_generation1_foundation_integration.py` 14, `test_generation1_phase0_audit.py` 18 — **sum 94, exactly matching the prior report's claim.**

**Composition** (assessed by reading every test in these five files):
- Roughly 25-30% are simple constructor/default-value/persistence-round-trip tests (e.g. "unspecified fields default to UNKNOWN," "duplicate id raises"). Legitimate but shallow individually.
- The majority (roughly 60-65%) are genuine behavioral tests: provenance-discipline combination checks, checksum-tamper detection using a real tampered file, cross-symbol/cross-timeframe rejection, correlation-based target-separation checks, warmup-boundary bar-by-bar checks, multiple-testing gate enforcement with a state-unchanged-after-failure assertion.
- A real adversarial test suite exists and is exercised (`tests/test_generation1_foundation_integration.py::TestAdversarialAudit`, 10 tests): wrong symbol, wrong timeframe, altered/tampered dataset (using an actual file write + checksum re-check, not a mock), synthetic-flag contradiction, missing provenance, duplicate/shuffled real-shaped data, invalid gap handling, frozen-candidate mutation, holdout misuse. All independently re-run in this audit and confirmed to genuinely raise the expected exception.

**Finding T1 (MEDIUM, NON_BLOCKING)** — a genuine defect found by direct code tracing in this audit, not present in the prior completion report: `tests/test_generation1_foundation_integration.py::TestEndToEndFoundationPath::test_audit_artifact_exists_and_is_internally_consistent` contains the line

```python
assert audit["dataset_record"]["is_real_market_data_eligible"] is True if "is_real_market_data_eligible" in audit["dataset_record"] else True
```

`is_real_market_data_eligible` is a `@property` on `DatasetRecord`, not a dataclass field, so `dataclasses.asdict()` (used by `DatasetRecord.to_dict()`) **never serializes it** — confirmed live in this audit: `"is_real_market_data_eligible" in audit["dataset_record"]` evaluates to `False` against the real artifact. The guarded conditional therefore always falls through to the `else True` branch, and **this specific assertion can never fail, regardless of the actual data** — it is vacuous. The underlying property IS correctly and meaningfully tested elsewhere in the same file (`test_real_eurusd_dataset_flows_through_the_full_foundation_path` calls `assert_real_market_data_eligible()` directly, which is a real, non-vacuous check), so this is a **test-quality defect in one specific assertion**, not a production defect and not evidence the underlying eligibility logic is wrong.

**Finding T2 (LOW, INFORMATIONAL)**: `test_synthetic_flag_mismatch_is_rejected_at_construction` uses `pytest.raises(Exception)` with a comment noting the intended type (`DatasetSpecError`) rather than asserting the specific exception class — would also silently pass if an unrelated exception (e.g. a `TypeError` from an accidental signature mismatch) were raised instead. Low-severity imprecision, not a false-positive risk in current behavior (verified: it does raise `DatasetSpecError` specifically).

**"Can tests pass while the production path is broken?"** — **Yes, confirmed.** Because of Finding D1 (registries not imported by `core/ml_r2/*`), all 94 new tests could pass in full even if `core/ml_r2/walkforward_r2.py` were deleted entirely, and the reverse also holds (the pre-existing 656 `ml_r2`/other tests do not depend on `core/factory/dataset_registry.py`/`instrument_registry.py`/`feature_registry.py` existing at all, apart from the one real coupling: `StrategyCandidateSpec.__post_init__` now imports `RESEARCH_SCOPES` from `instrument_registry.py`). This is expected for infrastructure that is intentionally not yet wired into production (per Phase 4's own scope), but is worth stating plainly rather than leaving implicit.

---

## 9. Git / Scope Audit

```
git diff --name-status c1affc6 9da97fe   (the Generation-1-labeled commit specifically)

Modified (2 files):
  M  DATASET_VALIDATION_REPORT.md   (+8/-1 lines: a status-correction note, historical
                                      text preserved and marked superseded, not deleted)
  M  core/factory/candidate.py      (+13 lines: additive `research_scope` field with a
                                      default, plus its validation — no existing field
                                      removed or altered)

Added (18 files): 4 new core/factory/*.py modules, 5 new spec/report .md files, 5 new
  test files, 3 new production registry JSON files, 1 new audit artifact JSON file.
```

**No frozen/canonical economic file was touched**: `core/ml_r2/*`, `core/features/fe_r2_001.py`, `core/indicators.py`, `core/dataset_provenance.py`, `core/provenance_enforcement.py`, and every file under `data/csv/` show **zero diff** across this commit (confirmed via `git diff c1affc6 9da97fe -- core/ml_r2/ core/features/ core/dataset_provenance.py core/provenance_enforcement.py data/csv/` — empty output). **PASS — this is provably true via git history, not merely claimed in the commit message.**

**No unrelated work was touched** — every changed/added file is either new Generation-1 infrastructure, its own tests, or documentation directly describing it. `core/factory/candidate.py`'s one modification is directly required by Phase 2's own instruction (research scope must be declared on the candidate spec) and is additive/backward-compatible (confirmed: default value, existing `StrategyCandidateSpec` construction calls throughout the pre-existing test suite still pass unmodified). **PASS.**

**Documentation claims vs. implementation**: `ML-001-DATA-FACTORY-SPEC.md`, `ML-001-MARKET-UNIVERSE-SPEC.md`, `ML-001-FEATURE-FACTORY-SPEC.md`, `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` were spot-checked against the actual code for their most load-bearing claims (state ordering, `_FROZEN_OR_LATER` membership, `HOLDOUT_TESTED` reachability, checksum values, instrument list) — **all matched**. One documentation gap: `ML-001-GENERATION-1-FOUNDATION-REPORT.md` describes the Phase 4 integration path in detail but its final status block (§2/§10 of that report) does not explicitly flag, in one place, that this same pipeline is not (yet) called by the production `core/ml_r2/*` scripts. The underlying fact is not hidden — `ML-001-DATA-FACTORY-SPEC.md` §2 does state the registries exist "without changing core semantics" and Phase 4 was always scoped as "infrastructure proof only" — but no single sentence in the prior completion report states as plainly as this audit does that the registries are not currently enforced on any real training run. This is a **presentation/emphasis gap**, not a factual misstatement: everything the prior report claims is individually true, but a reader skimming only its final status block could reasonably come away believing more production enforcement exists than actually does.

---

## 10. Security / Reproducibility Audit

```
grep -riE "api[_-]?key|secret|password|token\s*=" core/factory/*.py reports/factory/*.json
  -> zero matches
grep -rn "/home/user|/tmp/claude|/root/" core/factory/*.py [new test files]
  -> zero matches
```

All `DEFAULT_*_PATH` constants across the new modules use relative `Path("reports/factory/...")` values, consistent with the pre-existing `core/factory/registry.py::DEFAULT_REGISTRY_PATH` pattern — not a new risk, an inherited convention (implicitly assumes the process CWD is the repository root, same as the rest of this Factory).

No new network requirement was introduced — all new registries are pure local file/JSON operations; no `requests`/`urllib`/`curl` call exists anywhere in the four new `core/factory/*.py` modules (confirmed via grep).

**Finding S1 (INFORMATIONAL)**: `IllegalStateTransitionError` (`core/factory/state_machine.py`) subclasses plain `Exception`, not this project's `EAFactoryError` base that every other Factory exception uses. Pre-existing (confirmed: present before Generation 1's own commit, unchanged by it), does not affect functionality, but is an inconsistency worth a future cleanup pass.

**Finding S2 (INFORMATIONAL)**: `core.factory.candidate.StrategyCandidateSpec.__post_init__` performs a function-local import of `RESEARCH_SCOPES` from `core.factory.instrument_registry`, apparently defensive against a circular import that does not actually exist (`instrument_registry.py` imports nothing from `candidate.py`, confirmed by direct read). Harmless style inconsistency.

---

## 11. Findings — full list

| ID | Area | Severity | Blocking | Summary |
|---|---|---|---|---|
| D1/M1 | Data Factory / Market Universe / Integration | MEDIUM | NON_BLOCKING | New registries are correct and tested but not imported/enforced by the real `core/ml_r2/*` production pipeline |
| G1 | Governance | MEDIUM | NON_BLOCKING | `HOLDOUT_TESTED` state-machine label has no code-level link to a verified real `PURE_HOLDOUT` data access |
| T1 | Test Quality | MEDIUM | NON_BLOCKING | Vacuous conditional assertion in `test_audit_artifact_exists_and_is_internally_consistent` |
| G2 | Governance | LOW | NON_BLOCKING | No "model identity" field exists on `StrategyCandidate` to protect from mutation — UNVERIFIED per task item D, not PASS |
| F1 | Feature Factory | LOW | NON_BLOCKING | Two "adversarial" temporal-safety tests are static source-string greps, not behavioral tests |
| D3 | Data Factory | LOW | INFORMATIONAL | Standing `_validate_ohlcv` gate does not re-check OHLC consistency/positive prices/abnormal moves per call (checked once, at acquisition) |
| G3 | Governance | LOW | INFORMATIONAL | `derive_new_version()` does not propagate `hypothesis_id`/`instrument_universe` to the child candidate |
| G4 | Governance | LOW | INFORMATIONAL | Search-history counters incrementally maintained, no structural reconciliation test |
| G5 | Governance | LOW | INFORMATIONAL | `total_strategies_tested` triggers at `DATA_VALIDATED`, earlier than "tested" might imply |
| F2 | Feature Factory | LOW | INFORMATIONAL | Cross-process reproducibility genuinely true (re-verified) but only same-process idempotency is an automated regression test |
| T2 | Test Quality | LOW | INFORMATIONAL | One test uses `pytest.raises(Exception)` instead of the specific exception class |
| D2 | Data Factory | LOW | INFORMATIONAL | `core/data_manager.py` performs silent tz/resample/dedup handling, but is confirmed unused by the audited real-data path |
| S1 | Security/Style | INFORMATIONAL | INFORMATIONAL | `IllegalStateTransitionError` doesn't subclass `EAFactoryError` (pre-existing) |
| S2 | Security/Style | INFORMATIONAL | INFORMATIONAL | Unnecessary defensive local import in `candidate.py` |

**CRITICAL_FINDINGS = 0**
**HIGH_FINDINGS = 0**
**MEDIUM_FINDINGS = 3** (D1/M1, G1, T1)
**LOW_FINDINGS = 8** (G2, F1, D3, G3, G4, G5, F2, T2)
**INFORMATIONAL_FINDINGS = 3** (D2, S1, S2)
**TOTAL_FINDINGS = 14**
**BLOCKING_FINDINGS = 0**

---

## 12. Blocking Findings

**None.** No finding in this audit materially invalidates the claim that the described Generation 1 infrastructure exists, is internally correct, and is genuinely tested. Every MEDIUM finding is a scope/integration/test-precision issue, not a governance failure, a data-integrity failure, or a fabricated result.

---

## 13. Non-Blocking Findings

All 14 findings listed in §11 are non-blocking. The three MEDIUM findings (D1/M1, G1, T1) are the ones worth prioritizing before Generation 2 registers a second real candidate:

1. Wire `assert_real_market_data_eligible()` and `assert_dataset_matches_instrument()` into whatever script Generation 2 uses to launch a new training/evaluation run, so the Data Factory/Market Universe registries become an actual enforced precondition, not just a parallel record.
2. Either (a) have `StrategyRegistry.transition()` accept and require a `ProvenanceCertificate`/equivalent proof when transitioning to `HOLDOUT_TESTED`, or (b) explicitly document, as an accepted risk, that this remains a process-discipline guarantee rather than a code-enforced one.
3. Fix the vacuous assertion in `test_audit_artifact_exists_and_is_internally_consistent` (e.g. assert directly on `assert_real_market_data_eligible(dataset_record_object)` rather than dict-membership on a serialized property that will never be present).

---

## 14. Evidence References

Every claim above cites, inline, at least one of: a specific file path, a specific class/function name, a specific test name, a specific artifact path, or a specific commit hash/diff command — re-executed live in this audit session rather than assumed from the prior report. Key re-derived values (not copied):

- `sha256(data/csv/EURUSD_H1.csv)` and `sha256(data/csv/GBPUSD_H1.csv)` — recomputed, matched registry.
- `feature_schema_identity()` — recomputed twice in separate processes, matched artifact.
- `search_history_summary()` counters — recomputed from `list_all()`, matched stored values.
- `git diff c1affc6 9da97fe -- core/ml_r2/ core/features/ ...` — empty, confirming zero frozen-file touches.
- `_ALLOWED_TRANSITIONS` reachability for `HOLDOUT_TESTED`/`EVG_REVIEW` — queried directly, matched documentation.
- `"is_real_market_data_eligible" in audit["dataset_record"]` — confirmed `False` against the real artifact, substantiating Finding T1.

---

## 15. Recommended Remediation

Not performed in this audit (observational only, per the task's explicit instruction). Recommended, in priority order, for whoever next touches this code:

1. Wire the Data Factory/Market Universe eligibility checks into the actual training/evaluation entry point Generation 2 will use.
2. Decide and document (or implement) the intended relationship between `CandidateState.HOLDOUT_TESTED` and `ProvenanceEnforcer`'s `holdout_accessed` flag.
3. Fix the vacuous test assertion (Finding T1).
4. Consider adding a `model_identity`/`model_checksum` field to `StrategyCandidate` if this project wants that governance guarantee to be structurally, not just procedurally, true.
5. Lower-priority: address the INFORMATIONAL items opportunistically (exception hierarchy consistency, unnecessary local import, `derive_new_version()` lineage propagation).

---

## 16. Final Verdict

```
AUDIT_VERDICT = GENERATION_1_CONDITIONALLY_CONFIRMED
```

The architecture is substantially complete: every subsystem the task named (Governance, Data Factory, Market Universe, Feature Factory, Integration) exists as real, working, independently-re-verified code with genuine (not merely cosmetic) test coverage, and zero fabricated PASS state or leaked/contaminated evidence was found anywhere. Specific, non-critical gaps remain — most importantly, the new registries are not yet wired into the production economic pipeline, and one integration test assertion is vacuous. None of these are blocking; all are documented above with exact remediation guidance for whoever picks this up next.
