# ML-001 — Feature Factory Specification (Generation 1, Phase 3)

**Status**: IMPLEMENTED and VERIFIED against the existing, production FE-R2-001/FE-R2-003 feature pipeline. No new feature added.
**Date**: August 18, 2026
**Code**: `core/factory/feature_registry.py` (wraps, does not replace, `core/features/fe_r2_001.py`)
**Referenced by**: `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` §6.

---

## §1. Purpose

Create a deterministic, provenance-aware feature architecture that can safely expand later — without adding a single new indicator in this task. The existing five-feature FE-R2-001/FE-R2-003 pipeline is audited and formalized, not rewritten.

## §2. Feature Contract

`core.factory.feature_registry.FeatureContract`: `feature_id`, `name`, `version`, `definition`, `formula_reference`, `input_columns`, `lookback`, `timestamp_semantics`, `output_schema`, `warmup_requirement`, `code_version`, `determinism_status`, `group`. `build_feature_contracts()` constructs the current contract set **directly from `fe_r2_001.get_feature_schema()`** — the pipeline's own pre-existing, already-compliant machine-readable schema function — every call, not cached at import time, so a future `FEATURE_VERSION` bump is picked up automatically. There is exactly one source of truth for what a feature computes; this module adds structure around it, never a second, competing definition (verified: `tests/test_feature_factory.py::TestFeatureContractCompleteness::test_contract_definition_is_taken_verbatim_from_pipeline_schema`).

## §3. Feature Groups

`core.factory.feature_registry.FEATURE_GROUPS`: `PRICE`, `RETURNS`, `TREND`, `MOMENTUM`, `VOLATILITY`, `VOLUME_ORDER_FLOW`, `MARKET_STRUCTURE`, `REGIME`, `SESSION_TIME`. This project's five real features populate exactly three of these groups today — `momentum_5`/`momentum_20`/`rsi_14` → `MOMENTUM`, `atr_14` → `VOLATILITY`, `volatility_regime` → `REGIME`. The other six groups are architecturally representable (a future `FeatureContract` may declare any of them) but have **zero implemented features** — none are added by this task, per its explicit "do not add hundreds of indicators" instruction.

## §4. Temporal Safety

Every feature satisfies `feature(t)` uses only information available at or before `t` — this is the pipeline's own pre-existing, already-verified guarantee (`ML-001-R2-REAL-DATA-LEAKAGE-PROVENANCE-AUDIT.md` §3's future-injection check: 0 mismatches across 5 features × 28,800 real rows). This task adds targeted adversarial checks the task's §3.6 explicitly names and that were not already covered by `tests/test_ml_001_r2_adversarial.py`/`tests/test_ml_001_r2_leakage_integration.py`:

- **Centered rolling window**: static source audit confirms no `center=True` anywhere in `fe_r2_001.py` — a centered window would use future bars by construction.
- **Future normalization / future scaler fitting**: static source audit confirms no global-fit scaler (`StandardScaler`, `MinMaxScaler`, `RobustScaler`, `.fit_transform(`) exists anywhere in the module — this pipeline uses tree-based models that do not require feature scaling, and none was added.
- **Target-derived feature**: none of the five real features correlates with the forward label above `|corr| < 0.9` on a synthetic fixture — ruling out a disguised copy of `sign(close.shift(-1) - close)` masquerading as a feature.
- **Warmup boundary**: every feature's value is exactly `NaN` before its declared `WARMUP_BARS[feature]` boundary — not approximately, checked bar-by-bar on a synthetic fixture.
- **Cross-split contamination**: already covered by the existing `HoldoutAccessGuard`/`ProvenanceEnforcer` tests (`tests/test_ml_001_r2_adversarial.py::test_accidental_training_on_validation_blocked`, `test_accidental_training_on_holdout_blocked`) — not duplicated here.

Per the task's own instruction, this module does not attempt to prove arbitrary future feature code is mathematically leakage-free — it makes the *current* implementation's temporal semantics explicit and testable, and gives a concrete adversarial checklist a future feature addition must also pass.

## §5. Feature Schema Identity

`core.factory.feature_registry.feature_schema_identity(feature_ids_in_order)` — SHA-256 of an ordered feature-id sequence. Changing a feature, its version, its order, or removing/adding a feature changes this identity (verified: reordering, removing, and adding all independently confirmed to change the hash). `canonical_schema_identity()` computes it for the pipeline's actual current `FEATURE_ORDER`, and is confirmed reproducible across repeated calls and across fresh subprocess invocations (`tests/test_generation1_foundation_integration.py::TestReproducibilityAcrossFreshProcesses`).

This is distinct from, and complementary to, `core.ml_r2.walkforward_r2._feature_schema_hash()` (which hashes the *module's source bytes*, catching any implementation change including ones this identity function would not, like a comment edit) — the Feature Factory identity specifically tracks feature *identity and order*, independent of unrelated source-level edits.

## §6. Feature Provenance

The system can answer, for any training artifact: "what exact features were available to this model" (`spec.features` on the candidate + the schema identity recorded alongside it) and "what exact implementation produced them" (`formula_reference` on each `FeatureContract`, pointing at the single canonical module). Both questions are answered by re-runnable functions, not narrative claims.

## §7. Feature Leakage Tests

See §4. `tests/test_feature_factory.py::TestTemporalSafetyAdversarial` (6 tests) plus the pre-existing, unmodified `tests/test_ml_001_r2_adversarial.py`/`tests/test_ml_001_r2_leakage_integration.py` (already covering future-shift, shuffled/duplicate timestamps, gap rejection, feature-version drift, dataset-checksum sensitivity, and holdout/validation access blocking).

## §8. Existing Features — audit result

`FE-R2-002` (`_check_weekday_gaps`) is confirmed present, unmodified, and independently still rejecting an arbitrary mid-week gap exactly as before (`tests/test_feature_factory.py::TestExistingGapPolicyPreserved`). `FE-R2-003` (`_check_weekday_gaps_v3`) is confirmed additive — a distinct function object, not a replacement of the original. `get_feature_schema()` already existed and was already fully compliant with this specification's contract requirements (§2) before this task started; the only genuinely new code is the wrapper (`core/factory/feature_registry.py`) and the schema-identity function (§5), both of which are additive and consume, never modify, the existing pipeline.

**What is already compliant**: feature definitions, versioning, warmup semantics, no-lookahead guarantee, gap policy.
**What was incomplete before this task**: a formal `FeatureContract` object per feature, an order/identity-sensitive schema checksum distinct from the source-byte hash, and an explicit `FEATURE_GROUPS` taxonomy.
**What remains future scope**: any feature outside `MOMENTUM`/`VOLATILITY`/`REGIME` (price/returns/trend/volume-order-flow/market-structure/session-time groups have zero implemented features), and any second timeframe or instrument's feature computation (architecturally supported via `ML-001-MARKET-UNIVERSE-SPEC.md`, not implemented here).

## §9. Phase 3 Exit Criteria — status

```
FEATURE_ARCHITECTURE_DETERMINISTIC_AND_PROVENANCE_AWARE = TRUE
PRODUCTION_FEATURE_PATH_CORRECTLY_REPRESENTED = TRUE (all 5 FE-R2-003 features have contracts)
TEMPORAL_LEAKAGE_TESTS_PASS = TRUE (19 tests, tests/test_feature_factory.py)
FEATURE_SCHEMA_IDENTITY_REPRODUCIBLE = TRUE (in-process and cross-subprocess)
NO_KNOWN_FUTURE_LOOKING_FEATURE_ACCEPTED = TRUE
```
