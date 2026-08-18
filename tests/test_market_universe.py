"""Tests for core.factory.instrument_registry — Generation 1 Phase 2
(Market Universe): instrument registry, timeframe registry, research
scope, and dataset/instrument compatibility enforcement.

No new instrument is added by this task beyond the real EURUSD/GBPUSD
pair this project already has real data for — tests using other symbols
(XAUUSD, USDJPY, ...) use them only as synthetic, clearly-fictional
examples to exercise the architecture, never as claims that real data or
validated metadata exists for them.
"""

from __future__ import annotations

import pytest

from core.factory.candidate import CandidateSpecError, StrategyCandidateSpec
from core.factory.instrument_registry import (
    RESEARCH_SCOPES,
    SUPPORTED_TIMEFRAMES,
    UNKNOWN,
    DuplicateInstrumentError,
    InstrumentNotFoundError,
    InstrumentRecord,
    InstrumentRegistry,
    InstrumentSpecError,
    UnsupportedTimeframeError,
    assert_dataset_matches_instrument,
    assert_supported_timeframe,
    assert_valid_research_scope,
    is_supported_timeframe,
)


def _spec(**overrides) -> StrategyCandidateSpec:
    base = dict(
        entry_rule="model probability > 0.55",
        exit_rule="stop/target/max_hold",
        features=("momentum_5", "rsi_14"),
        timeframe="H1",
        direction="long_only",
        stop_loss="1.5x ATR",
        take_profit="2.0x ATR",
        max_hold_bars=24,
        position_sizing="fixed_fractional",
        transaction_cost_model="realistic",
    )
    base.update(overrides)
    return StrategyCandidateSpec(**base)


def _instrument(**overrides) -> InstrumentRecord:
    base = dict(instrument_id="INSTR-TEST", symbol="TESTUSD", asset_class="FX_SPOT")
    base.update(overrides)
    return InstrumentRecord(**base)


class TestInstrumentRecordHonestUnknowns:
    def test_unspecified_fields_default_to_unknown_not_a_guess(self) -> None:
        i = _instrument()
        assert i.venue_provider == UNKNOWN
        assert i.quote_currency == UNKNOWN
        assert i.tick_size == UNKNOWN
        assert i.cost_model_reference == UNKNOWN

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(InstrumentSpecError):
            _instrument(symbol="")

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(InstrumentSpecError):
            _instrument(status="DEFINITELY_TRADEABLE")

    def test_default_status_is_candidate_not_active(self) -> None:
        """A newly-constructed instrument record must not silently claim
        ACTIVE (implying real validated data/usage) -- that must be an
        explicit assertion."""
        i = _instrument()
        assert i.status == "CANDIDATE"


class TestInstrumentRegistryPersistence:
    def test_register_and_reload(self, tmp_path) -> None:
        path = tmp_path / "instruments.json"
        reg = InstrumentRegistry(path=path)
        reg.register(_instrument())
        reloaded = InstrumentRegistry(path=path)
        assert reloaded.get("INSTR-TEST").symbol == "TESTUSD"

    def test_duplicate_rejected(self, tmp_path) -> None:
        reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        reg.register(_instrument())
        with pytest.raises(DuplicateInstrumentError):
            reg.register(_instrument())

    def test_unknown_id_raises(self, tmp_path) -> None:
        reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        with pytest.raises(InstrumentNotFoundError):
            reg.get("INSTR-NOPE")

    def test_get_by_symbol(self, tmp_path) -> None:
        reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        reg.register(_instrument())
        assert reg.get_by_symbol("TESTUSD").instrument_id == "INSTR-TEST"
        with pytest.raises(InstrumentNotFoundError):
            reg.get_by_symbol("NOSUCHSYMBOL")


class TestTimeframeRegistry:
    def test_h1_is_supported(self) -> None:
        assert is_supported_timeframe("H1") is True
        assert_supported_timeframe("H1")  # must not raise

    def test_unsupported_timeframe_rejected(self) -> None:
        assert is_supported_timeframe("W1") is False
        with pytest.raises(UnsupportedTimeframeError):
            assert_supported_timeframe("W1")

    def test_full_enumeration_matches_spec(self) -> None:
        assert SUPPORTED_TIMEFRAMES == ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


class TestResearchScope:
    def test_single_instrument_is_valid(self) -> None:
        assert_valid_research_scope("SINGLE_INSTRUMENT")  # must not raise

    def test_unknown_scope_rejected(self) -> None:
        with pytest.raises(InstrumentSpecError):
            assert_valid_research_scope("EVERYTHING_EVERYWHERE")

    def test_candidate_spec_defaults_to_single_instrument(self) -> None:
        spec = _spec()
        assert spec.research_scope == "SINGLE_INSTRUMENT"

    def test_candidate_spec_accepts_declared_multi_instrument_scope(self) -> None:
        spec = _spec(research_scope="MULTI_INSTRUMENT")
        assert spec.research_scope == "MULTI_INSTRUMENT"

    def test_candidate_spec_rejects_invalid_scope(self) -> None:
        with pytest.raises(CandidateSpecError):
            _spec(research_scope="ALL_INSTRUMENTS_AT_ONCE")


class TestNoSilentCrossInstrumentSubstitution:
    def test_matching_symbol_passes(self) -> None:
        instrument = _instrument(symbol="EURUSD")
        assert_dataset_matches_instrument("EURUSD", "H1", instrument)  # must not raise

    def test_mismatched_symbol_rejected(self) -> None:
        """The core anti-substitution guarantee: a GBPUSD dataset must
        never be silently usable for a EURUSD-declared instrument."""
        instrument = _instrument(symbol="EURUSD")
        with pytest.raises(InstrumentSpecError):
            assert_dataset_matches_instrument("GBPUSD", "H1", instrument)


class TestProductionInstrumentsAreRealNotFabricated:
    def test_only_eurusd_and_gbpusd_are_registered(self) -> None:
        from core.factory.instrument_registry import DEFAULT_INSTRUMENT_REGISTRY_PATH

        if not DEFAULT_INSTRUMENT_REGISTRY_PATH.exists():
            pytest.skip("production instrument registry not present in this checkout")
        reg = InstrumentRegistry(path=DEFAULT_INSTRUMENT_REGISTRY_PATH)
        symbols = {i.symbol for i in reg.list_all()}
        # exactly the instruments this project has real data for -- no
        # invented USDJPY/XAUUSD/etc. entries with fabricated metadata
        assert symbols == {"EURUSD", "GBPUSD"}

    def test_production_instruments_have_honest_unknown_venue(self) -> None:
        from core.factory.instrument_registry import DEFAULT_INSTRUMENT_REGISTRY_PATH

        if not DEFAULT_INSTRUMENT_REGISTRY_PATH.exists():
            pytest.skip("production instrument registry not present in this checkout")
        reg = InstrumentRegistry(path=DEFAULT_INSTRUMENT_REGISTRY_PATH)
        eurusd = reg.get_by_symbol("EURUSD")
        # this project never verified a specific live broker/venue -- must
        # not silently claim one
        assert eurusd.venue_provider == UNKNOWN
        assert eurusd.status == "ACTIVE"  # explicitly asserted, real data does exist
