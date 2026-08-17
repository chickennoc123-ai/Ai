"""PROVENANCE-R2-001 run-provenance record tests.

Covers: complete-provenance requirement (a result without complete
provenance must be rejected) and manifest serialization.
"""

from __future__ import annotations

import json

import pytest

from core.ml_r2.provenance_r2 import ProvenanceIncompleteError, RunProvenance


def _complete_kwargs(**overrides):
    base = dict(
        strategy_id="ML-001-R2",
        strategy_version="1.0.0",
        model_version="RF-R2-001",
        feature_version="FE-R2-001",
        dataset_id="DATA-R2-001",
        dataset_checksum="a" * 64,
        code_version="deadbeef",
        config_checksum="b" * 64,
        training_period=("2020-01-01", "2022-12-31"),
        validation_period=("2023-01-01", "2023-12-31"),
        holdout_period=("2024-01-01", "2024-12-31"),
        feature_schema_hash="c" * 64,
        model_checksum="d" * 64,
        random_seed=42,
        execution_assumptions={"slippage_price": 0.00002},
    )
    base.update(overrides)
    return base


class TestProvenanceCompleteness:
    def test_complete_record_validates(self) -> None:
        record = RunProvenance(**_complete_kwargs())
        record.validate_complete()  # should not raise

    @pytest.mark.parametrize(
        "field_name,empty_value",
        [
            ("strategy_id", ""),
            ("dataset_checksum", ""),
            ("code_version", ""),
            ("model_checksum", ""),
            ("training_period", ()),
            ("execution_assumptions", {}),
        ],
    )
    def test_missing_field_rejected(self, field_name, empty_value) -> None:
        record = RunProvenance(**_complete_kwargs(**{field_name: empty_value}))
        with pytest.raises(ProvenanceIncompleteError):
            record.validate_complete()

    def test_none_field_rejected(self) -> None:
        record = RunProvenance(**_complete_kwargs(random_seed=None))
        with pytest.raises(ProvenanceIncompleteError):
            record.validate_complete()

    def test_to_manifest_dict_requires_completeness(self) -> None:
        record = RunProvenance(**_complete_kwargs(dataset_id=""))
        with pytest.raises(ProvenanceIncompleteError):
            record.to_manifest_dict()

    def test_to_json_is_valid_and_round_trips_key_fields(self) -> None:
        record = RunProvenance(**_complete_kwargs())
        payload = json.loads(record.to_json())
        assert payload["strategy_id"] == "ML-001-R2"
        assert payload["model_version"] == "RF-R2-001"
        assert payload["training_period"] == ["2020-01-01", "2022-12-31"]
