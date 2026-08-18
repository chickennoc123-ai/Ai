"""Regression tests for the checksum-vs-behavior non-determinism artifact
documented in ML-001-NONDETERMINISM-AUDIT.md.

Root finding: ``RFR2Model.train()``'s ``checksum`` (a hash of the raw
joblib-serialized bytes) can legitimately differ between two calls with
IDENTICAL inputs and IDENTICAL ``random_state`` if an unrelated
``joblib.load()`` happened earlier in the same process — independently
verified to be a serialization-byte-layout artifact only: predictions,
``feature_importances_``, and individual tree structure (node count,
thresholds) are bit-identical regardless. ``structural_fingerprint``
(added alongside this test) is a content-based hash immune to this,
kept as the reliable cross-run reproducibility signal.

These tests do NOT assert the checksum artifact is "fixed" — it isn't,
and this file does not attempt to eliminate it (root cause traced to
joblib's serialization byte layout varying with prior process activity,
not fully isolated to a single internal joblib mechanism, and doing so
was judged out of scope for a targeted, low-risk fix). They assert the
one property that actually matters economically: model BEHAVIOR is
unaffected, and the fingerprint captures that reliably.
"""

from __future__ import annotations

import io

import joblib
import numpy as np
import pandas as pd
import pytest

from core.ml_r2.model_r2 import RFR2Model, _serialize_model
from core.ml_r2.target_r2 import align_features_and_labels, compute_label
from core.features.fe_r2_001 import build_feature_matrix
from tests.r2_fixtures import make_synthetic_ohlcv


def _training_set(seed: int = 900, n: int = 900):
    df = make_synthetic_ohlcv(n, seed=seed)
    features = build_feature_matrix(df)
    labels = compute_label(df["close"])
    X, y = align_features_and_labels(features, labels)
    return X, y, df.index[0], df.index[-1]


class TestStructuralFingerprintIsOrderIndependent:
    def test_fingerprint_identical_across_two_clean_trains(self) -> None:
        X, y, start, end = _training_set()
        m1 = RFR2Model()
        meta1 = m1.train(X, y, training_start=start, training_end=end)
        m2 = RFR2Model()
        meta2 = m2.train(X, y, training_start=start, training_end=end)
        assert meta1.structural_fingerprint == meta2.structural_fingerprint
        assert meta1.checksum == meta2.checksum  # also true in the clean case

    def test_fingerprint_and_predictions_survive_a_prior_joblib_load(self) -> None:
        """The documented artifact: train once, serialize it, then joblib.load
        that serialized model (simulating "the Factory loaded a previous
        candidate"), THEN train a fresh model with the same inputs/seed.
        The raw byte checksum may legitimately differ; the structural
        fingerprint and actual predictions must not."""
        X, y, start, end = _training_set()

        baseline = RFR2Model()
        baseline_meta = baseline.train(X, y, training_start=start, training_end=end)
        baseline_probs = baseline.predict_proba(X)

        # Simulate "a previously-trained model gets loaded from disk"
        serialized = _serialize_model(baseline._model)
        _ = joblib.load(io.BytesIO(serialized))  # the act that (may) perturb the checksum

        probe = RFR2Model()
        probe_meta = probe.train(X, y, training_start=start, training_end=end)
        probe_probs = probe.predict_proba(X)

        # The property that actually matters: behavior is unaffected.
        assert probe_meta.structural_fingerprint == baseline_meta.structural_fingerprint
        assert np.array_equal(probe_probs, baseline_probs)
        assert np.array_equal(probe._model.feature_importances_, baseline._model.feature_importances_)
        # Deliberately NOT asserting probe_meta.checksum == baseline_meta.checksum here --
        # that equality is not guaranteed (documented artifact), and asserting it would
        # make this test flaky/misleading rather than a true regression guard.

    def test_fingerprint_is_present_and_a_valid_sha256_hex_string(self) -> None:
        X, y, start, end = _training_set()
        m = RFR2Model()
        meta = m.train(X, y, training_start=start, training_end=end)
        assert meta.structural_fingerprint is not None
        assert len(meta.structural_fingerprint) == 64
        int(meta.structural_fingerprint, 16)  # raises ValueError if not valid hex

    def test_fingerprint_differs_for_a_genuinely_different_model(self) -> None:
        """Sanity check the fingerprint isn't trivially constant: a model
        trained on a materially different dataset must fingerprint differently."""
        X1, y1, start1, end1 = _training_set(seed=900)
        X2, y2, start2, end2 = _training_set(seed=901)
        m1 = RFR2Model()
        meta1 = m1.train(X1, y1, training_start=start1, training_end=end1)
        m2 = RFR2Model()
        meta2 = m2.train(X2, y2, training_start=start2, training_end=end2)
        assert meta1.structural_fingerprint != meta2.structural_fingerprint


class TestExistingMetadataStillLoads:
    def test_model_metadata_without_structural_fingerprint_field_still_constructs(self) -> None:
        """Metadata JSON saved before this field existed (e.g. this project's
        own already-committed RF-R2-001 canonical artifacts) must still load
        -- structural_fingerprint is optional/defaulted, not required."""
        from core.ml_r2.model_r2 import ModelMetadata

        legacy_dict = {
            "model_version": "RF-R2-001",
            "feature_version": "FE-R2-003",
            "feature_order": ["momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"],
            "hyperparameters": {},
            "sklearn_version": "1.0.0",
            "python_version": "3.11.0",
            "training_timestamp": "2026-01-01T00:00:00",
            "training_start": "2026-01-01T00:00:00",
            "training_end": "2026-01-02T00:00:00",
            "training_rows": 10,
            "class_balance": {"0.0": 5, "1.0": 5},
            "checksum": "deadbeef",
            # no structural_fingerprint key at all -- simulates pre-existing metadata
        }
        meta = ModelMetadata(**legacy_dict)
        assert meta.structural_fingerprint is None
