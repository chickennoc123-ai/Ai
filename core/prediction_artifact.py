"""PredictionArtifact: Immutable prediction records with full provenance.

Each prediction is recorded as an immutable artifact with:
- Prediction value and probability
- Full timestamp chain
- Model and feature versions
- Training/test window information
- Provenance hash for verification
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class PredictionArtifactError(EAFactoryError):
    """Raised when prediction artifact is invalid."""


@dataclass(frozen=True)
class PredictionArtifact:
    """Immutable record of a single out-of-sample prediction."""

    prediction_time: datetime
    execution_time: datetime
    prediction: int  # -1, 0, +1
    probability: float
    model_version: str
    feature_version: str
    training_start: datetime
    training_end: datetime
    dataset_version: str
    hypothesis_id: str
    trial_id: str
    information_cutoff: datetime
    provenance_hash: str = ""
    artifact_timestamp: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        """Validate and compute hash."""
        # Validate prediction value
        if self.prediction not in (-1, 0, 1):
            raise PredictionArtifactError(
                "Prediction must be -1, 0, or +1",
                prediction=self.prediction,
            )

        # Validate probability
        if not 0.0 <= self.probability <= 1.0:
            raise PredictionArtifactError(
                "Probability must be between 0 and 1",
                probability=self.probability,
            )

        # Validate temporal ordering: information_cutoff <= prediction_time <= execution_time
        if self.information_cutoff > self.prediction_time:
            raise PredictionArtifactError(
                "Information cutoff cannot be after prediction time",
                information_cutoff=self.information_cutoff.isoformat(),
                prediction_time=self.prediction_time.isoformat(),
            )

        if self.prediction_time > self.execution_time:
            raise PredictionArtifactError(
                "Prediction time cannot be after execution time",
                prediction_time=self.prediction_time.isoformat(),
                execution_time=self.execution_time.isoformat(),
            )

        # Validate training window
        if self.training_start >= self.training_end:
            raise PredictionArtifactError(
                "Training start must be before training end",
                training_start=self.training_start.isoformat(),
                training_end=self.training_end.isoformat(),
            )

        # Compute hash if not provided
        if not self.provenance_hash:
            hash_str = self._compute_hash()
            object.__setattr__(self, "provenance_hash", hash_str)

    def _compute_hash(self) -> str:
        """Compute deterministic provenance hash."""
        data = (
            f"{self.hypothesis_id}:{self.trial_id}:{self.prediction_time.isoformat()}:"
            f"{self.prediction}:{self.probability}:{self.model_version}:"
            f"{self.feature_version}:{self.information_cutoff.isoformat()}"
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def verify(self) -> bool:
        """Verify artifact integrity.

        Returns:
            True if artifact is valid

        Raises:
            PredictionArtifactError: If verification fails
        """
        # Re-check all invariants
        if self.prediction not in (-1, 0, 1):
            raise PredictionArtifactError("Invalid prediction value after creation")

        if not 0.0 <= self.probability <= 1.0:
            raise PredictionArtifactError("Invalid probability after creation")

        if self.information_cutoff > self.prediction_time:
            raise PredictionArtifactError("Temporal ordering violated")

        if self.prediction_time > self.execution_time:
            raise PredictionArtifactError("Temporal ordering violated")

        # Verify hash consistency
        expected_hash = self._compute_hash()
        if self.provenance_hash != expected_hash:
            raise PredictionArtifactError(
                "Provenance hash mismatch",
                expected=expected_hash,
                actual=self.provenance_hash,
            )

        return True

    def summary(self) -> Dict[str, Any]:
        """Return artifact summary."""
        return {
            "prediction": self.prediction,
            "probability": self.probability,
            "prediction_time": self.prediction_time.isoformat(),
            "execution_time": self.execution_time.isoformat(),
            "information_cutoff": self.information_cutoff.isoformat(),
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "training_period": (
                self.training_start.isoformat(),
                self.training_end.isoformat(),
            ),
            "dataset_version": self.dataset_version,
            "hypothesis_id": self.hypothesis_id,
            "trial_id": self.trial_id,
            "provenance_hash": self.provenance_hash,
            "artifact_timestamp": self.artifact_timestamp.isoformat(),
        }


class PredictionArtifactRegistry:
    """Registry of all prediction artifacts for audit trail."""

    def __init__(self, hypothesis_id: str):
        """Initialize registry."""
        self.hypothesis_id = hypothesis_id
        self.artifacts: Dict[str, PredictionArtifact] = {}

    def register(self, artifact: PredictionArtifact) -> None:
        """Register a prediction artifact.

        Args:
            artifact: PredictionArtifact to register

        Raises:
            PredictionArtifactError: If artifact already registered
        """
        artifact.verify()

        if artifact.provenance_hash in self.artifacts:
            raise PredictionArtifactError(
                "Artifact already registered",
                provenance_hash=artifact.provenance_hash,
            )

        self.artifacts[artifact.provenance_hash] = artifact
        logger.info(
            "Registered prediction artifact",
            hypothesis_id=self.hypothesis_id,
            trial_id=artifact.trial_id,
            prediction=artifact.prediction,
            probability=artifact.probability,
        )

    def get_artifact(self, provenance_hash: str) -> PredictionArtifact:
        """Retrieve artifact by hash."""
        if provenance_hash not in self.artifacts:
            raise PredictionArtifactError(
                "Artifact not found",
                provenance_hash=provenance_hash,
            )
        return self.artifacts[provenance_hash]

    def get_all_artifacts(self) -> list[PredictionArtifact]:
        """Get all registered artifacts."""
        return list(self.artifacts.values())

    def count_by_trial(self, trial_id: str) -> int:
        """Count artifacts for a trial."""
        return sum(1 for a in self.artifacts.values() if a.trial_id == trial_id)

    def summary(self) -> Dict[str, Any]:
        """Return registry summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "total_artifacts": len(self.artifacts),
            "artifacts": [a.summary() for a in self.artifacts.values()],
        }
