"""ML-001 Adapter: RandomForest strategy for FX/Gold trading.

Implements ML-001 hypothesis:
- Uses Random Forest model
- Features: momentum_5, momentum_20, rsi_14, atr_14, volatility_regime
- Target: 1-bar binary classification
- Execution: EURUSD H1 timeframe
- No fallback strategy (no signal if model unavailable)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.information_audit import AuditCertificate
from core.prediction_artifact import PredictionArtifact, PredictionArtifactRegistry
from utils.exceptions import EAFactoryError
from utils.logger import get_logger

logger = get_logger(__name__)


class ML001ConfigurationError(EAFactoryError):
    """Raised when ML-001 configuration is invalid."""


class ML001ExecutionError(EAFactoryError):
    """Raised when ML-001 execution fails."""


@dataclass(frozen=True)
class ML001HypothesisContract:
    """Frozen ML-001 hypothesis contract."""

    hypothesis_id: str = "ML-001"
    asset: Dict[str, str] = None
    features: List[str] = None
    target: Dict[str, Any] = None
    execution: Dict[str, str] = None

    def __post_init__(self) -> None:
        """Validate contract."""
        if self.asset is None:
            raise ML001ConfigurationError("asset is required")
        if self.features is None:
            raise ML001ConfigurationError("features is required")
        if self.target is None:
            raise ML001ConfigurationError("target is required")
        if self.execution is None:
            raise ML001ConfigurationError("execution is required")

        expected_features = ["momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"]
        if self.features != expected_features:
            raise ML001ConfigurationError(
                "Features must match ML-001 specification",
                expected=expected_features,
                actual=self.features,
            )

    @staticmethod
    def create_default() -> ML001HypothesisContract:
        """Create default ML-001 contract."""
        return ML001HypothesisContract(
            asset={"symbol": "EURUSD", "timeframe": "H1"},
            features=["momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"],
            target={"horizon": "1_bar", "threshold": 0.001},
            execution={
                "signal_time": "candle_close_t",
                "execution_time": "candle_open_t_plus_1",
            },
        )


class ML001Adapter:
    """ML-001 RandomForest strategy adapter."""

    def __init__(
        self,
        hypothesis_id: str = "ML-001",
        model_version: str = "RF-v1.0",
        feature_version: str = "FE-v1.0",
    ):
        """Initialize ML-001 adapter.

        Args:
            hypothesis_id: Hypothesis identifier
            model_version: Random Forest model version
            feature_version: Feature extraction version
        """
        self.hypothesis_id = hypothesis_id
        self.model_version = model_version
        self.feature_version = feature_version
        self.contract = ML001HypothesisContract.create_default()
        self.audit_certificate: Optional[AuditCertificate] = None
        self.prediction_registry: Optional[PredictionArtifactRegistry] = None
        self.current_trial_id: Optional[str] = None

    def set_audit_certificate(self, certificate: AuditCertificate) -> None:
        """Set IA-001 audit certificate.

        Raises:
            ML001ExecutionError: If audit did not pass
        """
        if not certificate.audit_result.is_passed:
            raise ML001ExecutionError(
                "Cannot use non-passing audit certificate",
                hypothesis_id=self.hypothesis_id,
                verdict=certificate.audit_result.verdict.value,
            )

        self.audit_certificate = certificate
        logger.info(
            "ML-001 audit certificate set",
            hypothesis_id=self.hypothesis_id,
            certificate_id=certificate.certificate_id,
        )

    def initialize_prediction_registry(self) -> PredictionArtifactRegistry:
        """Initialize prediction artifact registry."""
        self.prediction_registry = PredictionArtifactRegistry(self.hypothesis_id)
        return self.prediction_registry

    def set_trial_context(self, trial_id: str) -> None:
        """Set current trial context."""
        self.current_trial_id = trial_id

    def create_prediction_artifact(
        self,
        prediction_time: datetime,
        execution_time: datetime,
        prediction: int,
        probability: float,
        training_start: datetime,
        training_end: datetime,
        dataset_version: str,
        information_cutoff: datetime,
    ) -> PredictionArtifact:
        """Create an immutable prediction artifact.

        Args:
            prediction_time: When prediction was made
            execution_time: When prediction will be executed
            prediction: -1, 0, or +1
            probability: Confidence [0, 1]
            training_start: Training window start
            training_end: Training window end
            dataset_version: Dataset version identifier
            information_cutoff: Information availability cutoff

        Returns:
            PredictionArtifact

        Raises:
            ML001ExecutionError: If artifact creation fails
        """
        if self.audit_certificate is None:
            raise ML001ExecutionError(
                "No audit certificate; cannot create predictions",
                hypothesis_id=self.hypothesis_id,
            )

        if self.current_trial_id is None:
            raise ML001ExecutionError(
                "No trial context; set via set_trial_context()",
                hypothesis_id=self.hypothesis_id,
            )

        artifact = PredictionArtifact(
            prediction_time=prediction_time,
            execution_time=execution_time,
            prediction=prediction,
            probability=probability,
            model_version=self.model_version,
            feature_version=self.feature_version,
            training_start=training_start,
            training_end=training_end,
            dataset_version=dataset_version,
            hypothesis_id=self.hypothesis_id,
            trial_id=self.current_trial_id,
            information_cutoff=information_cutoff,
        )

        if self.prediction_registry:
            self.prediction_registry.register(artifact)

        logger.info(
            "Prediction artifact created",
            hypothesis_id=self.hypothesis_id,
            trial_id=self.current_trial_id,
            prediction=prediction,
            probability=probability,
        )

        return artifact

    def get_all_prediction_artifacts(self) -> List[PredictionArtifact]:
        """Get all registered prediction artifacts."""
        if not self.prediction_registry:
            return []
        return self.prediction_registry.get_all_artifacts()

    def summary(self) -> Dict[str, Any]:
        """Return adapter summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "contract": {
                "asset": self.contract.asset,
                "features": self.contract.features,
                "target": self.contract.target,
                "execution": self.contract.execution,
            },
            "audit_certificate_set": self.audit_certificate is not None,
            "current_trial_id": self.current_trial_id,
            "prediction_count": (
                len(self.get_all_prediction_artifacts())
                if self.prediction_registry
                else 0
            ),
        }
