"""RF-R2-001 model implementation tests.

Covers: explicit hyperparameters, schema validation, determinism,
save/load with checksum verification.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import FEATURE_ORDER, build_feature_matrix
from core.ml_r2.model_r2 import (
    HYPERPARAMETERS,
    MODEL_VERSION,
    ModelIntegrityError,
    ModelNotTrainedError,
    ModelSchemaError,
    RFR2Model,
)
from core.ml_r2.target_r2 import align_features_and_labels, compute_label
from tests.r2_fixtures import make_synthetic_ohlcv


def _training_data(seed: int = 30, n: int = 800):
    df = make_synthetic_ohlcv(n, seed=seed)
    features = build_feature_matrix(df)
    labels = compute_label(df["close"])
    X, y = align_features_and_labels(features, labels)
    return X, y, df.index[0], df.index[-1]


class TestHyperparameterSpecification:
    def test_all_required_hyperparameters_present_no_defaults_relied_on(self) -> None:
        expected_keys = {
            "n_estimators",
            "max_depth",
            "min_samples_split",
            "min_samples_leaf",
            "max_features",
            "class_weight",
            "criterion",
            "bootstrap",
            "random_state",
        }
        assert expected_keys.issubset(HYPERPARAMETERS.keys())
        assert HYPERPARAMETERS["n_estimators"] == 300
        assert HYPERPARAMETERS["max_depth"] == 6
        assert HYPERPARAMETERS["min_samples_split"] == 50
        assert HYPERPARAMETERS["min_samples_leaf"] == 25
        assert HYPERPARAMETERS["max_features"] == "sqrt"
        assert HYPERPARAMETERS["class_weight"] == "balanced"
        assert HYPERPARAMETERS["criterion"] == "gini"
        assert HYPERPARAMETERS["bootstrap"] is True
        assert HYPERPARAMETERS["random_state"] == 42


class TestModelSchemaValidation:
    def test_train_rejects_wrong_column_order(self) -> None:
        X, y, start, end = _training_data()
        reordered = X[list(reversed(FEATURE_ORDER))]
        model = RFR2Model()
        with pytest.raises(ModelSchemaError):
            model.train(reordered, y, start, end)

    def test_train_rejects_nan_features(self) -> None:
        X, y, start, end = _training_data()
        broken = X.copy()
        broken.iloc[0, 0] = np.nan
        model = RFR2Model()
        with pytest.raises(ModelSchemaError):
            model.train(broken, y, start, end)

    def test_predict_before_train_raises(self) -> None:
        X, _, _, _ = _training_data()
        model = RFR2Model()
        with pytest.raises(ModelNotTrainedError):
            model.predict(X)

    def test_predict_rejects_wrong_schema(self) -> None:
        X, y, start, end = _training_data()
        model = RFR2Model()
        model.train(X, y, start, end)
        with pytest.raises(ModelSchemaError):
            model.predict(X[list(reversed(FEATURE_ORDER))])


class TestModelTrainingAndMetadata:
    def test_train_produces_complete_metadata(self) -> None:
        X, y, start, end = _training_data()
        model = RFR2Model()
        metadata = model.train(X, y, start, end)
        assert metadata.model_version == MODEL_VERSION
        assert list(metadata.feature_order) == FEATURE_ORDER
        assert metadata.hyperparameters == HYPERPARAMETERS
        assert metadata.training_rows == len(X)
        assert metadata.checksum and len(metadata.checksum) == 64  # sha256 hex

    def test_predict_proba_returns_probability_of_class_1(self) -> None:
        X, y, start, end = _training_data()
        model = RFR2Model()
        model.train(X, y, start, end)
        proba = model.predict_proba(X)
        assert proba.shape == (len(X),)
        assert (proba >= 0.0).all() and (proba <= 1.0).all()

    def test_predict_returns_binary_classes(self) -> None:
        X, y, start, end = _training_data()
        model = RFR2Model()
        model.train(X, y, start, end)
        preds = model.predict(X)
        assert set(np.unique(preds)).issubset({0, 1})


class TestModelDeterminism:
    def test_identical_training_data_yields_identical_checksum(self) -> None:
        X, y, start, end = _training_data(seed=31)
        model_a = RFR2Model()
        meta_a = model_a.train(X, y, start, end)
        model_b = RFR2Model()
        meta_b = model_b.train(X, y, start, end)
        assert meta_a.checksum == meta_b.checksum

    def test_identical_training_data_yields_identical_predictions(self) -> None:
        X, y, start, end = _training_data(seed=32)
        model_a = RFR2Model()
        model_a.train(X, y, start, end)
        model_b = RFR2Model()
        model_b.train(X, y, start, end)
        np.testing.assert_array_equal(model_a.predict(X), model_b.predict(X))
        np.testing.assert_array_almost_equal(model_a.predict_proba(X), model_b.predict_proba(X), decimal=12)


class TestModelPersistence:
    def test_save_and_load_roundtrip_preserves_predictions(self) -> None:
        X, y, start, end = _training_data(seed=33)
        model = RFR2Model()
        model.train(X, y, start, end)
        expected = model.predict_proba(X)

        with tempfile.TemporaryDirectory() as tmp:
            model_path = str(Path(tmp) / "model.joblib")
            meta_path = str(Path(tmp) / "metadata.json")
            model.save(model_path, meta_path)

            loaded = RFR2Model.load(model_path, meta_path)
            actual = loaded.predict_proba(X)
            np.testing.assert_array_almost_equal(expected, actual, decimal=12)
            assert loaded.metadata.checksum == model.metadata.checksum

    def test_load_rejects_tampered_artifact(self) -> None:
        X, y, start, end = _training_data(seed=34)
        model = RFR2Model()
        model.train(X, y, start, end)

        with tempfile.TemporaryDirectory() as tmp:
            model_path = str(Path(tmp) / "model.joblib")
            meta_path = str(Path(tmp) / "metadata.json")
            model.save(model_path, meta_path)

            import json

            with open(meta_path) as f:
                meta = json.load(f)
            meta["checksum"] = "0" * 64
            with open(meta_path, "w") as f:
                json.dump(meta, f)

            with pytest.raises(ModelIntegrityError):
                RFR2Model.load(model_path, meta_path)
