"""Tests for the multi-symbol-readiness provenance metadata added to
core.factory.candidate: DatasetProvenanceRecord and
StrategyCandidate.instrument_universe/hypothesis_id.

No new symbol is actually added or tested here (per the task's explicit
"do not expand symbols yet" instruction) -- these tests only exercise the
data structures that would carry that information, using the same real
EURUSD/GBPUSD provenance fields already used elsewhere in this project as
realistic (not fabricated-for-a-new-symbol) example values.
"""

from __future__ import annotations

import pytest

from core.factory.candidate import (
    DatasetProvenanceRecord,
    ProvenanceSpecError,
    StrategyCandidateSpec,
)
from core.factory.registry import StrategyRegistry


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


def _eurusd_provenance(**overrides) -> DatasetProvenanceRecord:
    base = dict(
        symbol="EURUSD",
        timeframe="H1",
        dataset_id="REAL-EURUSD-H1-komo135-forex-historical-data",
        dataset_checksum="7ac5c7403c536d7f916a14bde2e77ee0e5c22579f2fccbc085537aaf027c753f",
        source="komo135/forex-historical-data (GitHub mirror)",
        coverage_start="2012-11-16T05:00:00+00:00",
        coverage_end="2022-03-05T04:00:00+00:00",
        timezone="UTC",
        cost_model_reference="ML-001-R2-CLEAN-REBUILD-SPEC.md §7 (realistic median spread + 0.2 pip slippage)",
    )
    base.update(overrides)
    return DatasetProvenanceRecord(**base)


class TestDatasetProvenanceRecordCompleteness:
    def test_complete_record_constructs(self) -> None:
        _eurusd_provenance()

    @pytest.mark.parametrize(
        "field_name",
        [
            "symbol",
            "timeframe",
            "dataset_id",
            "dataset_checksum",
            "source",
            "coverage_start",
            "coverage_end",
            "timezone",
            "cost_model_reference",
        ],
    )
    def test_missing_required_field_raises(self, field_name) -> None:
        with pytest.raises(ProvenanceSpecError):
            _eurusd_provenance(**{field_name: ""})

    def test_symbol_specific_assumptions_default_to_empty_and_are_free_form(self) -> None:
        p = _eurusd_provenance()
        assert p.symbol_specific_assumptions == {}
        p2 = _eurusd_provenance(symbol_specific_assumptions={"pip_value": 0.0001, "typical_spread_pips": 0.8})
        assert p2.symbol_specific_assumptions["pip_value"] == 0.0001

    def test_record_is_frozen(self) -> None:
        import dataclasses

        p = _eurusd_provenance()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.symbol = "GBPUSD"  # type: ignore[misc]

    def test_to_dict_from_dict_round_trip(self) -> None:
        p = _eurusd_provenance(symbol_specific_assumptions={"pip_value": 0.0001})
        restored = DatasetProvenanceRecord.from_dict(p.to_dict())
        assert restored == p


class TestNoInstrumentIsAssumedValidOnAnotherSymbol:
    def test_candidate_universe_is_a_tuple_of_provenance_records_not_bare_symbols(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        universe = (_eurusd_provenance(), _eurusd_provenance(symbol="GBPUSD", dataset_id="REAL-GBPUSD-H1-komo135-forex-historical-data"))
        c = reg.register(
            _spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D",
            instrument_universe=universe,
        )
        assert len(c.instrument_universe) == 2
        assert {p.symbol for p in c.instrument_universe} == {"EURUSD", "GBPUSD"}
        # each instrument carries its OWN dataset id -- one is never silently
        # reused for the other
        assert c.instrument_universe[0].dataset_id != c.instrument_universe[1].dataset_id

    def test_instrument_universe_survives_registry_persistence_round_trip(self, tmp_path) -> None:
        path = tmp_path / "registry.json"
        reg = StrategyRegistry(path=path)
        universe = (_eurusd_provenance(),)
        c = reg.register(
            _spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D",
            instrument_universe=universe,
        )

        reloaded = StrategyRegistry(path=path)
        restored = reloaded.get(c.candidate_id)
        assert len(restored.instrument_universe) == 1
        assert restored.instrument_universe[0] == universe[0]

    def test_candidate_without_instrument_universe_defaults_to_empty_tuple(self, tmp_path) -> None:
        """Backward compatibility: a candidate registered without this
        field (e.g. every candidate registered before this field existed,
        including the real STRAT-000001) must still construct and load."""
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        assert c.instrument_universe == ()

    def test_production_strat_000001_loads_correctly_without_instrument_universe(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present in this checkout")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        candidate = reg.get("STRAT-000001")
        # registered before this field existed -- must default cleanly, not raise
        assert candidate.instrument_universe == ()
        assert candidate.hypothesis_id is None


class TestHypothesisLineageOnCandidates:
    def test_candidate_can_record_originating_hypothesis_id(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(
            _spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D",
            hypothesis_id="HYP-000001",
        )
        assert c.hypothesis_id == "HYP-000001"

    def test_hypothesis_id_defaults_to_none_for_directly_specified_candidates(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        assert c.hypothesis_id is None
