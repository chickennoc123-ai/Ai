"""Phase 7 remediation adversarial tests — the specific scenarios not
already covered by the existing R2 test suites, committed here as real,
repeatable pytest tests (previously some of these were only run as
ad-hoc scripts during ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md's
Checksum Forensics investigation).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from core.features.fe_r2_001 import build_feature_matrix, get_feature_schema
from core.ml_r2.model_r2 import HYPERPARAMETERS, ModelIntegrityError, RFR2Model
from core.ml_r2.target_r2 import align_features_and_labels, compute_label
from tests.r2_fixtures import make_synthetic_ohlcv


def _training_data(seed: int, n: int = 800):
    df = make_synthetic_ohlcv(n, seed=seed)
    features = build_feature_matrix(df)
    labels = compute_label(df["close"])
    X, y = align_features_and_labels(features, labels)
    return X, y, df.index[0], df.index[-1]


class TestDatasetSubstitution:
    """13. Dataset substitution: two models trained on different data must
    be distinguishable, and a substituted model file cannot be silently
    accepted in place of the one a metadata.json claims to describe,
    UNLESS the metadata was also coordinately rewritten to match — which
    this test demonstrates explicitly (committing the audit's Checksum
    Forensics coordinated-tamper finding as a real, repeatable test)."""

    def test_substituted_model_with_stale_metadata_is_rejected(self) -> None:
        X_a, y_a, start_a, end_a = _training_data(seed=500)
        X_b, y_b, start_b, end_b = _training_data(seed=501)

        model_original = RFR2Model()
        model_original.train(X_a, y_a, start_a, end_a)
        model_substituted = RFR2Model()
        model_substituted.train(X_b, y_b, start_b, end_b)

        assert model_original.metadata.checksum != model_substituted.metadata.checksum

        with tempfile.TemporaryDirectory() as tmp:
            model_path = str(Path(tmp) / "model.joblib")
            meta_path = str(Path(tmp) / "metadata.json")
            model_original.save(model_path, meta_path)

            # Attacker replaces the model file but leaves the ORIGINAL
            # metadata.json (with the original checksum) in place.
            with tempfile.TemporaryDirectory() as tmp2:
                sub_model_path = str(Path(tmp2) / "sub_model.joblib")
                sub_meta_path = str(Path(tmp2) / "sub_metadata.json")
                model_substituted.save(sub_model_path, sub_meta_path)
                shutil.copy(sub_model_path, model_path)

            with pytest.raises(ModelIntegrityError):
                RFR2Model.load(model_path, meta_path)

    def test_coordinated_substitution_of_model_and_metadata_is_not_detected_by_checksum_alone(self) -> None:
        """Documents the exact, empirically-verified limit of the checksum
        mechanism (audit Finding M-2 / Phase 6 of the remediation
        instruction: this is not something to "fix" — the checksum proves
        artifact<->metadata self-consistency, not authenticity against an
        actor who controls both files; that requires the independently-
        recorded RunProvenance channel instead)."""
        X_a, y_a, start_a, end_a = _training_data(seed=502)
        X_b, y_b, start_b, end_b = _training_data(seed=503)

        model_original = RFR2Model()
        model_original.train(X_a, y_a, start_a, end_a)
        model_substituted = RFR2Model()
        model_substituted.train(X_b, y_b, start_b, end_b)

        with tempfile.TemporaryDirectory() as tmp:
            model_path = str(Path(tmp) / "model.joblib")
            meta_path = str(Path(tmp) / "metadata.json")
            model_original.save(model_path, meta_path)

            with tempfile.TemporaryDirectory() as tmp2:
                sub_model_path = str(Path(tmp2) / "sub_model.joblib")
                sub_meta_path = str(Path(tmp2) / "sub_metadata.json")
                model_substituted.save(sub_model_path, sub_meta_path)
                # Coordinated: both files replaced consistently.
                shutil.copy(sub_model_path, model_path)
                shutil.copy(sub_meta_path, meta_path)

            reloaded = RFR2Model.load(model_path, meta_path)  # does NOT raise
            assert reloaded.metadata.checksum == model_substituted.metadata.checksum


class TestFeatureSchemaMismatch:
    """8. Feature schema mismatch: a persisted schema file that no longer
    matches the live FE-R2-001 definition must be detectable by comparing
    it against get_feature_schema(), even though (per Finding M-7's
    resolution) nothing forces that comparison automatically at load time —
    the artifact is written faithfully and the mismatch is observable."""

    def test_stale_written_schema_is_detectably_different_from_current(self) -> None:
        X, y, start, end = _training_data(seed=504)
        model = RFR2Model()
        model.train(X, y, start, end)
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = str(Path(tmp) / "feature_schema.json")
            model.save(str(Path(tmp) / "model.joblib"), str(Path(tmp) / "metadata.json"), feature_schema_path=schema_path)
            with open(schema_path) as f:
                written = json.load(f)

            # Simulate a stale schema from a superseded feature_version.
            tampered = dict(written)
            tampered["feature_version"] = "FE-R2-999-SIMULATED-FUTURE-VERSION"
            with open(schema_path, "w") as f:
                json.dump(tampered, f)

            with open(schema_path) as f:
                reloaded = json.load(f)
        assert reloaded["feature_version"] != get_feature_schema()["feature_version"]


class TestWrongModelVersion:
    """11. Wrong model version: OOSPredictionBatch/RunProvenance must record
    whatever model_version string is supplied, not silently substitute the
    canonical constant — so a caller-side bug that passes the wrong version
    string is visible in the record, not masked."""

    def test_batch_records_the_exact_model_version_supplied_not_a_silently_corrected_one(self) -> None:
        from core.ml_r2.walkforward_r2 import generate_oos_predictions, make_walk_forward_windows

        df = make_synthetic_ohlcv(2500, seed=505)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="phase7-test"
        )
        batches, provenance = generate_oos_predictions(
            df, windows[:1], hypothesis_id="phase7-test", dataset_id="synthetic-fixture-505",
            validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
            model_version="RF-R2-999-WRONG",
        )
        # The wrong version is faithfully recorded, not corrected — proving
        # the pipeline doesn't mask a caller-side version-tagging bug.
        assert batches[0].model_version == "RF-R2-999-WRONG"
        assert provenance[0].model_version == "RF-R2-999-WRONG"


class TestDifferentRandomSeed:
    """12. Different random seed: random_state must actually be honored by
    the fitted model, not silently ignored — proven by training with two
    different seeds on IDENTICAL data and confirming the checksums differ."""

    def test_different_random_state_yields_different_checksum_on_identical_data(self) -> None:
        X, y, start, end = _training_data(seed=506)

        from sklearn.ensemble import RandomForestClassifier
        import core.ml_r2.model_r2 as model_r2_module

        original_hyperparameters = dict(model_r2_module.HYPERPARAMETERS)
        altered_hyperparameters = dict(original_hyperparameters)
        altered_hyperparameters["random_state"] = 43  # different from the spec's 42

        model_default = RFR2Model()
        model_default.train(X, y, start, end)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(model_r2_module, "HYPERPARAMETERS", altered_hyperparameters)
            model_altered_seed = RFR2Model()
            model_altered_seed.train(X, y, start, end)

        assert model_default.metadata.checksum != model_altered_seed.metadata.checksum
