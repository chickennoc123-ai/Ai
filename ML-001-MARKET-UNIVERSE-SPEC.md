# ML-001 — Market Universe Specification (Generation 1, Phase 2)

**Status**: IMPLEMENTED and VERIFIED. Architecture only — no new instrument added.
**Date**: August 18, 2026
**Code**: `core/factory/instrument_registry.py`
**Referenced by**: `ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md` §6.

---

## §1. Purpose

Make instrument expansion a first-class capability without running any large-scale economic research across instruments yet, and without ever letting a strategy tested on one instrument be silently assumed valid on another.

## §2. Instrument Registry

`core.factory.instrument_registry.InstrumentRecord`/`InstrumentRegistry`: `instrument_id`, `symbol`, `asset_class`, `venue_provider`, `quote_currency`, `timezone_session_semantics`, `tick_size`, `price_precision`, `contract_metadata`, `data_availability`, `cost_model_reference`, `status` (`ACTIVE`/`CANDIDATE`/`UNSUPPORTED`/`RETIRED`, defaulting to `CANDIDATE` — never `ACTIVE` unless explicitly asserted).

**Every unestablished field defaults to the literal string `"UNKNOWN"`**, never a plausible-looking guess. This project's two real, registered instruments (`INSTR-EURUSD`, `INSTR-GBPUSD`) are honest examples of this: `venue_provider = "UNKNOWN"` (this project used a historical-data mirror, not a live broker feed, so no specific venue has been established) and `tick_size = "UNKNOWN"` (never independently confirmed), while `price_precision`, `data_availability`, and `cost_model_reference` are populated because those *were* actually established (5-decimal quotes observed directly in the CSVs; coverage and cost-model reference already documented elsewhere in this project).

## §3. Instrument/Dataset/Timeframe Compatibility

`assert_dataset_matches_instrument(dataset_symbol, dataset_timeframe, instrument)` (`core/factory/instrument_registry.py`) is the explicit anti-substitution check: raises `InstrumentSpecError` if a dataset's recorded symbol does not match the instrument it is being wired to. This is a real, callable guard, not a documentation-only rule — exercised in `tests/test_market_universe.py::TestNoSilentCrossInstrumentSubstitution` and again in the Phase 4 integration path (`tests/test_generation1_foundation_integration.py`), including the adversarial case (a GBPUSD dataset deliberately checked against a EURUSD instrument, confirmed rejected).

## §4. Multi-Symbol Semantics & Research Scope

`StrategyCandidateSpec.research_scope` (`core/factory/candidate.py`, additive field, default `"SINGLE_INSTRUMENT"`) — one of `SINGLE_INSTRUMENT`/`INSTRUMENT_FAMILY`/`MULTI_INSTRUMENT` (`core.factory.instrument_registry.RESEARCH_SCOPES`), validated at construction (`CandidateSpecError` on an unrecognized value). Declared on the spec, at candidate-generation time — before any evaluation runs, never inferred afterward from how many instruments the evaluation happened to touch. `STRAT-000001` is, correctly, `SINGLE_INSTRUMENT`-shaped in retrospect: EURUSD and GBPUSD were evaluated as two **separate** walk-forward runs (each producing its own PF/expectancy/rejection evidence — `ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md` §3), never pooled into a single cross-instrument claim. Nothing in this task requires that candidate's registry record to be retroactively annotated — `research_scope` defaults to the value consistent with what actually happened, and the field did not exist when `STRAT-000001` was registered.

**A strategy tested on EURUSD is never automatically validated on any other instrument** — enforced structurally (§3's compatibility check) and by convention (a candidate's `instrument_universe`, `ML-001-STRATEGY-FACTORY-SPEC.md` §12, must carry a `DatasetProvenanceRecord` per instrument it actually claims to have tested).

## §5. Cross-Instrument Testing — supported, not required

No architectural rule forces every candidate to be evaluated across every instrument. `research_scope` (§4) exists precisely so a candidate can honestly declare it only ever claims `SINGLE_INSTRUMENT` validity, without that being treated as an incomplete or lesser result.

## §6. Timeframe Registry

`core.factory.instrument_registry.SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")` — a fixed architectural enumeration. `is_supported_timeframe()`/`assert_supported_timeframe()` check membership only; **membership in this tuple does not imply data exists for that timeframe** — that is a separate, dataset-registry-level fact (`ML-001-DATA-FACTORY-SPEC.md` §3). This project currently has real data for exactly one timeframe, H1, for exactly two instruments.

## §7. Cost Model Reference

`InstrumentRecord.cost_model_reference` defaults to `"UNKNOWN"`. For EURUSD/GBPUSD it is populated (`"ML-001-R2-CLEAN-REBUILD-SPEC.md sec 7 (realistic median spread + 0.2 pip slippage)"`) because that cost model was actually specified and used (`core/ml_r2/backtest_r2.py::BacktestConfig`) — this task does not fabricate a realistic-looking cost figure for any instrument this project has not actually priced.

## §8. Phase 2 Exit Criteria — status

```
ARCHITECTURE_REPRESENTS_MULTIPLE_INSTRUMENTS_AND_TIMEFRAMES = TRUE (without changing core
    candidate-lifecycle semantics -- research_scope is an additive, defaulted field)
NO_SILENT_SYMBOL_SUBSTITUTION = TRUE (assert_dataset_matches_instrument, tested adversarially)
NO_IMPLICIT_CROSS_INSTRUMENT_VALIDITY = TRUE (research_scope declared per-candidate, defaults
    to the narrowest claim)
TESTS_COVER_SYMBOL_TIMEFRAME_IDENTITY = TRUE (tests/test_market_universe.py, 20 tests)
INSTRUMENTS_REGISTERED = EURUSD, GBPUSD only -- no fabricated metadata for any other symbol
```
