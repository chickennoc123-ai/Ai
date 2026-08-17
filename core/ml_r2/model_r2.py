"""RF-R2-001: the ML-001-R2 candidate model.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 6. Every hyperparameter
is explicit — none rely on scikit-learn defaults. ``n_jobs=1`` is added
purely for run-to-run determinism (parallel tree building can vary
floating-point summation order across runs); it is not one of the
strategy hyperparameters and does not affect the fitted model's
predictions, only the reproducibility of the fitting process itself.
"""

from __future__ import annotations

import hashlib
import io
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier

from core.features.fe_r2_001 import FEATURE_ORDER, FEATURE_VERSION
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

MODEL_VERSION = "RF-R2-001"

#: Explicit hyperparameters per spec Section 6. No unspecified defaults.
HYPERPARAMETERS: Dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 6,
    "min_samples_split": 50,
    "min_samples_leaf": 25,
    "max_features": "sqrt",
    "class_weight": "balanced",
    "criterion": "gini",
    "bootstrap": True,
    "random_state": 42,
}

#: Reproducibility-only setting, not a strategy hyperparameter (see module docstring).
_DETERMINISM_SETTINGS: Dict[str, Any] = {"n_jobs": 1}


class ModelSchemaError(EAFactoryError):
    """Raised when input features do not match FE-R2-001's schema."""


class ModelIntegrityError(EAFactoryError):
    """Raised when a loaded model artifact fails checksum verification."""


class ModelNotTrainedError(EAFactoryError):
    """Raised when predict/predict_proba is called before train()/load()."""


@dataclass(frozen=True)
class ModelMetadata:
    """Immutable record of everything needed to audit a trained RF-R2-001 artifact."""

    model_version: str
    feature_version: str
    feature_order: Sequence[str]
    hyperparameters: Dict[str, Any]
    sklearn_version: str
    python_version: str
    training_timestamp: str
    training_start: str
    training_end: str
    training_rows: int
    class_balance: Dict[str, int]
    checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _validate_feature_schema(X: pd.DataFrame) -> None:
    if list(X.columns) != list(FEATURE_ORDER):
        raise ModelSchemaError(
            "feature columns do not match FE-R2-001 order",
            expected=list(FEATURE_ORDER),
            actual=list(X.columns),
        )
    if X.isna().any().any():
        raise ModelSchemaError("feature matrix contains NaN values; align/drop before training or inference")


def _serialize_model(model: RandomForestClassifier) -> bytes:
    """Serialize a fitted estimator to bytes exactly once.

    The checksum is always computed on these bytes directly — never by
    re-serializing a model that has been reconstructed from a previous
    dump. Pickling is not guaranteed to be byte-stable across a
    dump -> load -> re-dump round trip even when the reconstructed
    object is semantically identical (e.g. internal numpy array
    layout/strides can differ), so re-pickling after load is not a
    valid integrity check and must never be used as one.
    """
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return buffer.getvalue()


def _checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RFR2Model:
    """RF-R2-001 wrapper: train/predict/predict_proba with strict schema validation."""

    def __init__(self) -> None:
        self._model: Optional[RandomForestClassifier] = None
        self._metadata: Optional[ModelMetadata] = None
        self._serialized_bytes: Optional[bytes] = None

    @property
    def metadata(self) -> ModelMetadata:
        if self._metadata is None:
            raise ModelNotTrainedError("model has not been trained or loaded")
        return self._metadata

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        training_start: datetime,
        training_end: datetime,
    ) -> ModelMetadata:
        """Fit RF-R2-001 on (X, y). X/y must already be leakage-safe and NaN-free."""
        _validate_feature_schema(X)
        if y.isna().any():
            raise ModelSchemaError("label vector contains NaN values")
        if len(X) != len(y):
            raise ModelSchemaError("feature/label length mismatch", n_features=len(X), n_labels=len(y))
        if len(X) == 0:
            raise ModelSchemaError("cannot train on an empty dataset")

        model = RandomForestClassifier(**HYPERPARAMETERS, **_DETERMINISM_SETTINGS)
        model.fit(X.to_numpy(), y.to_numpy())

        class_balance = {str(k): int(v) for k, v in y.value_counts().sort_index().items()}
        serialized = _serialize_model(model)
        checksum = _checksum_bytes(serialized)

        metadata = ModelMetadata(
            model_version=MODEL_VERSION,
            feature_version=FEATURE_VERSION,
            feature_order=tuple(FEATURE_ORDER),
            hyperparameters=dict(HYPERPARAMETERS),
            sklearn_version=sklearn.__version__,
            python_version=sys.version.split()[0],
            training_timestamp=utcnow().isoformat(),
            training_start=training_start.isoformat(),
            training_end=training_end.isoformat(),
            training_rows=len(X),
            class_balance=class_balance,
            checksum=checksum,
        )

        self._model = model
        self._metadata = metadata
        self._serialized_bytes = serialized
        return metadata

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            raise ModelNotTrainedError("model has not been trained or loaded")
        _validate_feature_schema(X)
        return self._model.predict(X.to_numpy())

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return P(label=1) — probability the next bar closes higher."""
        if self._model is None:
            raise ModelNotTrainedError("model has not been trained or loaded")
        _validate_feature_schema(X)
        proba = self._model.predict_proba(X.to_numpy())
        class_1_index = list(self._model.classes_).index(1)
        return proba[:, class_1_index]

    def save(self, model_path: str, metadata_path: str) -> None:
        if self._model is None or self._metadata is None or self._serialized_bytes is None:
            raise ModelNotTrainedError("cannot save an untrained model")
        # Write the exact bytes that were checksummed at train() time —
        # never re-serialize, so the on-disk checksum can never drift from
        # the recorded metadata.
        with open(model_path, "wb") as f:
            f.write(self._serialized_bytes)

        import json

        with open(metadata_path, "w") as f:
            json.dump(self._metadata.to_dict(), f, indent=2)

    @classmethod
    def load(cls, model_path: str, metadata_path: str) -> "RFR2Model":
        import json

        with open(metadata_path) as f:
            meta_dict = json.load(f)
        with open(model_path, "rb") as f:
            raw_bytes = f.read()

        # Verify integrity on the raw bytes read from disk — not on a
        # re-serialization of the reconstructed object (see
        # _serialize_model's docstring for why that would be unsound).
        recomputed = _checksum_bytes(raw_bytes)
        if recomputed != meta_dict.get("checksum"):
            raise ModelIntegrityError(
                "loaded model checksum does not match metadata",
                expected=meta_dict.get("checksum"),
                actual=recomputed,
            )

        model = joblib.load(io.BytesIO(raw_bytes))
        if list(model.classes_) != [0, 1] and list(model.classes_) != [0.0, 1.0]:
            raise ModelIntegrityError("loaded model classes are not binary {0, 1}", classes=list(model.classes_))

        instance = cls()
        instance._model = model
        instance._metadata = ModelMetadata(**meta_dict)
        instance._serialized_bytes = raw_bytes
        return instance
