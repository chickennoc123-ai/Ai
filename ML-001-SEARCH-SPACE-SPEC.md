# ML-001 — Search Space Specification (Generation 2, Phase 9-10, 12)

**Status**: IMPLEMENTED and tested.
**Code**: `core/factory/search_space.py`, `core/factory/candidate_generation_engine.py`, `core/factory/research_accounting.py`
**Referenced by**: `ML-001-GENERATION-2-SPEC.md` §3, §5.

---

## §1. Purpose

Makes "what exactly was searched" an explicit, serialized, hashed, **immutable** artifact — never reconstructed after the fact from however many candidates happened to be generated, and never allowed to silently change under an id already in use.

## §2. Search Space Record

`SearchSpace`: `symbols`, `timeframes`, `features`, `feature_parameters` (e.g. `{"RSI_period": [10, 14, 20]}`), `entry_conditions`, `exit_conditions`, `stop_loss_options`, `take_profit_options`, `holding_periods`, `regimes`, `position_sizing_options`, `cost_model`, `generation_method`, `generation_seed`. `combination_count()` computes the true product of every varying dimension's cardinality (verified with the task's own worked example: 2 symbols × 3 RSI periods × 3 EMA periods × 3 holding periods = 216, matching exactly).

## §3. Immutability

`SearchSpaceRegistry.register()` distinguishes two failure modes on an id collision: `DuplicateSearchSpaceError` (identical content re-registered — likely caller error, not a governance violation) vs. `FrozenSearchSpaceMutationError` (**different** content under the same id — the actual violation this contract exists to prevent). There is no `update` method. `checksum()` hashes content only (not the id or timestamp), so `find_duplicate()` can detect two independently-constructed `SearchSpace` objects describing the identical search.

## §4. Candidate Generation Engine

`core/factory/candidate_generation_engine.py` — distinct from Generation 1's `core.factory.generator` (which draws parameter variants of the ONE pre-specified ML-001-R2 hypothesis). This engine consumes **any** `FORMALIZED`-or-later `HypothesisRecord` plus **any** registered `SearchSpace`:

1. `assert_hypothesis_eligible_for_candidate_generation(hypothesis)` — refuses a vague/incomplete hypothesis (`ML-001-HYPOTHESIS-REGISTRY-SPEC.md` §5), no placeholder values substituted.
2. `generate_candidate_spec_from_draw(hypothesis, search_space, param_draw, symbol, timeframe)` — validates every drawn value is genuinely a member of the declared search space (`CandidateGenerationError` otherwise — a candidate can never silently claim to have been drawn from a space it wasn't).
3. `compute_candidate_checksum(spec, hypothesis_id, search_space_id)` — a candidate-level identity that encodes lineage, not just trading-rule content: two candidates with byte-identical spec content but different hypothesis/search-space origin produce different checksums (verified adversarially).
4. `generate_and_register_candidate(...)` registers the result via the unmodified `core.factory.registry.StrategyRegistry.register()`, with `hypothesis_id`/`search_space_id`/`candidate_checksum` all populated (additive fields on `StrategyCandidate`, `core/factory/candidate.py`).

**Reproducibility** (Phase 17): `sample_param_draws(search_space, seed, count)` mirrors `core.factory.generator`'s existing, already-tested discipline — a caller-supplied `random.Random(seed)` instance only, never the global `random` module (verified: `test_sampling_never_touches_global_random_state`). Same seed → identical draws, independently re-verified across a genuine subprocess spawn for hypothesis checksums (`tests/test_generation2_reproducibility.py::test_checksum_recomputed_in_a_fresh_process_matches`).

## §5. Search Accounting

`core/factory/research_accounting.py::compute_search_accounting_summary()` — a pure, read-only aggregator (holds no state, cannot drift from the underlying registries since every number is recomputed on every call): `TOTAL_SOURCES`, `TOTAL_CLAIMS`, `TOTAL_HYPOTHESES`, `TOTAL_FORMALIZED_HYPOTHESES`, `TOTAL_SEARCH_SPACES`, `TOTAL_CANDIDATES_GENERATED`, `TOTAL_CANDIDATES_TESTED`, `TOTAL_CANDIDATES_REJECTED`, `TOTAL_CANDIDATES_SURVIVING`, `TOTAL_CANDIDATES_FROZEN`, `SEARCH_SPACE_SIZE`, `PARAMETER_COMBINATIONS`, `SYMBOL_COMBINATIONS`, `FEATURE_COMBINATIONS`, `GENERATION_METHOD`, `SELECTION_BIAS_STATUS`.

**`SELECTION_BIAS_STATUS` is never `PASS`** — the function has no code path that produces that value; it returns `ACCOUNTING_ONLY` once at least one candidate exists, or `UNACCOUNTED` otherwise (verified: `tests/test_generation2_adversarial.py::TestFakePassState::test_selection_bias_status_never_defaults_to_pass`). A formal statistical-validation layer that could justify a stronger status does not exist yet and is out of Generation 2's scope.

## §6. What This Contract Does Not Do

- Does not implement a formal multiple-testing correction (Bonferroni, FDR control, etc.) — only the accounting a future correction would consume.
- Does not generate a search space or candidate from a real hypothesis/real market data — every example in this generation's own test suite is a synthetic fixture, registered in an isolated `tmp_path`.
