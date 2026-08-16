"""Dataset Provenance Guard (DP-001): Enforce data integrity across research lifecycle.

Prevents development/validation/pure-holdout contamination by implementing
explicit governance boundaries and access control.

Lifecycle:
    DEVELOPMENT
        ↓
    VALIDATION
        ↓
    RESEARCH_FREEZE
        ↓
    PURE_HOLDOUT (protected until freeze)
        ↓
    OBSERVED

The PURE_HOLDOUT partition is architecturally protected from:
- Feature selection
- Model selection
- Hyperparameter optimization
- Any research optimization
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class DatasetRole(str, Enum):
    """Partition role in the research lifecycle."""

    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    PURE_HOLDOUT = "PURE_HOLDOUT"
    OBSERVED = "OBSERVED"


class AccessIntent(str, Enum):
    """Purpose for accessing a dataset."""

    DEVELOPMENT_RESEARCH = "DEVELOPMENT_RESEARCH"
    VALIDATION_SELECTION = "VALIDATION_SELECTION"
    FINAL_EVALUATION = "FINAL_EVALUATION"
    OBSERVATION = "OBSERVATION"


class DatasetProvenanceError(EAFactoryError):
    """Raised when dataset provenance is missing, invalid, or contradictory."""


class DatasetPartitionError(EAFactoryError):
    """Raised when partition boundaries overlap or are incorrectly ordered."""


class HoldoutAccessError(EAFactoryError):
    """Raised when PURE_HOLDOUT is accessed without proper authorization."""


class ResearchFreezeError(EAFactoryError):
    """Raised when research operations are attempted after ResearchFreeze."""


@dataclass(frozen=True)
class DatasetProvenance:
    """Immutable provenance record for a dataset partition."""

    dataset_id: str
    dataset_version: str
    symbol: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    dataset_role: DatasetRole
    source_identifier: str
    created_at: datetime = field(default_factory=utcnow)
    methodology_version: str = "DP-001-v1.0"
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate and compute hash."""
        if not self.dataset_id:
            raise DatasetProvenanceError("dataset_id is required")
        if not self.dataset_version:
            raise DatasetProvenanceError("dataset_version is required")
        if self.start_time >= self.end_time:
            raise DatasetProvenanceError(
                "Temporal range invalid",
                start_time=self.start_time.isoformat(),
                end_time=self.end_time.isoformat(),
            )
        if not self.content_hash:
            hash_str = self._compute_hash()
            object.__setattr__(self, "content_hash", hash_str)

    def _compute_hash(self) -> str:
        """Compute deterministic content hash."""
        data = (
            f"{self.dataset_id}:{self.dataset_version}:{self.symbol}:{self.timeframe}:"
            f"{self.start_time.isoformat()}:{self.end_time.isoformat()}:"
            f"{self.dataset_role.value}:{self.source_identifier}"
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    @property
    def is_development(self) -> bool:
        """True if this is a DEVELOPMENT partition."""
        return self.dataset_role == DatasetRole.DEVELOPMENT

    @property
    def is_validation(self) -> bool:
        """True if this is a VALIDATION partition."""
        return self.dataset_role == DatasetRole.VALIDATION

    @property
    def is_pure_holdout(self) -> bool:
        """True if this is a PURE_HOLDOUT partition."""
        return self.dataset_role == DatasetRole.PURE_HOLDOUT

    @property
    def is_observed(self) -> bool:
        """True if this is an OBSERVED partition."""
        return self.dataset_role == DatasetRole.OBSERVED

    def summary(self) -> Dict[str, Any]:
        """Return a summary dictionary."""
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "dataset_role": self.dataset_role.value,
            "source_identifier": self.source_identifier,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "methodology_version": self.methodology_version,
        }


@dataclass(frozen=True)
class ResearchFreeze:
    """Immutable research freeze boundary."""

    freeze_timestamp: datetime
    freeze_id: str = ""
    frozen_hypothesis_id: str = ""
    frozen_feature_count: int = 0
    frozen_target: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        """Compute freeze ID if not provided."""
        if not self.freeze_id:
            data = f"{self.freeze_timestamp.isoformat()}:{self.frozen_hypothesis_id}"
            freeze_hash = hashlib.sha256(data.encode()).hexdigest()[:12]
            object.__setattr__(self, "freeze_id", freeze_hash)

    def summary(self) -> Dict[str, Any]:
        """Return a summary dictionary."""
        return {
            "freeze_timestamp": self.freeze_timestamp.isoformat(),
            "freeze_id": self.freeze_id,
            "frozen_hypothesis_id": self.frozen_hypothesis_id,
            "frozen_feature_count": self.frozen_feature_count,
            "frozen_target": self.frozen_target,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class ProvenanceCertificate:
    """Certificate authorizing dataset access for a specific purpose."""

    hypothesis_id: str
    dataset_provenance: DatasetProvenance
    access_intent: AccessIntent
    authorized_timestamp: datetime = field(default_factory=utcnow)
    research_freeze: Optional[ResearchFreeze] = None
    certificate_id: str = ""

    def __post_init__(self) -> None:
        """Compute certificate ID."""
        if not self.certificate_id:
            data = (
                f"{self.hypothesis_id}:{self.dataset_provenance.dataset_id}:"
                f"{self.access_intent.value}:{self.authorized_timestamp.isoformat()}"
            )
            cert_hash = hashlib.sha256(data.encode()).hexdigest()[:12]
            object.__setattr__(self, "certificate_id", cert_hash)

    @property
    def is_valid_for_holdout(self) -> bool:
        """True if certificate authorizes PURE_HOLDOUT access."""
        if not self.dataset_provenance.is_pure_holdout:
            return False
        # PURE_HOLDOUT access only allowed after freeze and for final evaluation
        if not self.research_freeze or not self.research_freeze.is_active:
            return False
        return self.access_intent == AccessIntent.FINAL_EVALUATION

    @property
    def is_valid_for_development(self) -> bool:
        """True if certificate authorizes DEVELOPMENT access."""
        if not self.dataset_provenance.is_development:
            return False
        return self.access_intent == AccessIntent.DEVELOPMENT_RESEARCH

    @property
    def is_valid_for_validation(self) -> bool:
        """True if certificate authorizes VALIDATION access."""
        if not self.dataset_provenance.is_validation:
            return False
        return self.access_intent == AccessIntent.VALIDATION_SELECTION

    def summary(self) -> Dict[str, Any]:
        """Return a summary dictionary."""
        return {
            "certificate_id": self.certificate_id,
            "hypothesis_id": self.hypothesis_id,
            "dataset_id": self.dataset_provenance.dataset_id,
            "dataset_role": self.dataset_provenance.dataset_role.value,
            "access_intent": self.access_intent.value,
            "authorized_timestamp": self.authorized_timestamp.isoformat(),
            "is_valid_for_holdout": self.is_valid_for_holdout,
            "research_freeze_active": self.research_freeze is not None and self.research_freeze.is_active,
        }


class ProvenanceGuard:
    """Enforce dataset provenance governance."""

    def __init__(self, hypothesis_id: str):
        """Initialize the provenance guard."""
        self.hypothesis_id = hypothesis_id
        self.datasets: Dict[str, DatasetProvenance] = {}
        self.research_freeze: Optional[ResearchFreeze] = None
        self.certificates: Dict[str, ProvenanceCertificate] = {}

    def register_dataset(self, provenance: DatasetProvenance) -> None:
        """Register a dataset partition."""
        if not provenance.dataset_id:
            raise DatasetProvenanceError("Dataset must have dataset_id")
        if not provenance.dataset_version:
            raise DatasetProvenanceError("Dataset must have dataset_version")

        key = f"{provenance.symbol}:{provenance.timeframe}:{provenance.dataset_role.value}"
        self.datasets[key] = provenance
        logger.info(
            "Registered dataset partition",
            hypothesis_id=self.hypothesis_id,
            dataset_id=provenance.dataset_id,
            role=provenance.dataset_role.value,
            start=provenance.start_time.isoformat(),
            end=provenance.end_time.isoformat(),
        )

    def validate_temporal_boundaries(self) -> None:
        """Enforce DEVELOPMENT < VALIDATION < PURE_HOLDOUT ordering."""
        # Group by symbol/timeframe
        by_instrument: Dict[str, Dict[DatasetRole, DatasetProvenance]] = {}

        for provenance in self.datasets.values():
            key = f"{provenance.symbol}:{provenance.timeframe}"
            if key not in by_instrument:
                by_instrument[key] = {}
            by_instrument[key][provenance.dataset_role] = provenance

        # Validate ordering for each instrument
        for instrument, roles in by_instrument.items():
            if DatasetRole.DEVELOPMENT in roles and DatasetRole.VALIDATION in roles:
                dev = roles[DatasetRole.DEVELOPMENT]
                val = roles[DatasetRole.VALIDATION]
                if dev.end_time > val.start_time:
                    raise DatasetPartitionError(
                        f"Temporal overlap: DEVELOPMENT ends after VALIDATION starts",
                        instrument=instrument,
                        development_end=dev.end_time.isoformat(),
                        validation_start=val.start_time.isoformat(),
                    )

            if DatasetRole.VALIDATION in roles and DatasetRole.PURE_HOLDOUT in roles:
                val = roles[DatasetRole.VALIDATION]
                holdout = roles[DatasetRole.PURE_HOLDOUT]
                if val.end_time > holdout.start_time:
                    raise DatasetPartitionError(
                        f"Temporal overlap: VALIDATION ends after PURE_HOLDOUT starts",
                        instrument=instrument,
                        validation_end=val.end_time.isoformat(),
                        holdout_start=holdout.start_time.isoformat(),
                    )

        logger.info(
            "Temporal boundaries validated",
            hypothesis_id=self.hypothesis_id,
            partitions=len(self.datasets),
        )

    def freeze_research(
        self,
        frozen_feature_count: int = 0,
        frozen_target: str = "",
    ) -> ResearchFreeze:
        """Freeze the research hypothesis after validation selection."""
        if self.research_freeze and self.research_freeze.is_active:
            raise ResearchFreezeError(
                "Research is already frozen",
                hypothesis_id=self.hypothesis_id,
                freeze_id=self.research_freeze.freeze_id,
            )

        freeze = ResearchFreeze(
            freeze_timestamp=utcnow(),
            frozen_hypothesis_id=self.hypothesis_id,
            frozen_feature_count=frozen_feature_count,
            frozen_target=frozen_target,
            is_active=True,
        )

        self.research_freeze = freeze
        logger.info(
            "Research frozen",
            hypothesis_id=self.hypothesis_id,
            freeze_id=freeze.freeze_id,
            features=frozen_feature_count,
            target=frozen_target,
        )

        return freeze

    def validate_holdout_access_for_selection(self) -> None:
        """Prevent PURE_HOLDOUT access for selection before freeze."""
        if not self.research_freeze or not self.research_freeze.is_active:
            raise HoldoutAccessError(
                "Cannot access PURE_HOLDOUT for selection before ResearchFreeze",
                hypothesis_id=self.hypothesis_id,
            )

    def get_certificate(
        self,
        provenance: DatasetProvenance,
        access_intent: AccessIntent,
    ) -> ProvenanceCertificate:
        """Issue a provenance certificate if access is authorized."""
        # Validate dataset role/version
        if not provenance.dataset_id or not provenance.dataset_version:
            raise DatasetProvenanceError(
                "Dataset must have dataset_id and dataset_version",
                dataset_id=provenance.dataset_id,
                dataset_version=provenance.dataset_version,
            )

        # Prevent PURE_HOLDOUT access before freeze
        if provenance.is_pure_holdout:
            if not self.research_freeze or not self.research_freeze.is_active:
                raise HoldoutAccessError(
                    "PURE_HOLDOUT cannot be accessed before ResearchFreeze",
                    hypothesis_id=self.hypothesis_id,
                )

            # Only allow FINAL_EVALUATION after freeze
            if access_intent != AccessIntent.FINAL_EVALUATION:
                raise HoldoutAccessError(
                    f"PURE_HOLDOUT can only be accessed for FINAL_EVALUATION after freeze, "
                    f"not for {access_intent.value}",
                    hypothesis_id=self.hypothesis_id,
                    access_intent=access_intent.value,
                )

        # Prevent DEVELOPMENT/VALIDATION from being used for selection after they should be closed
        if provenance.is_development and access_intent != AccessIntent.DEVELOPMENT_RESEARCH:
            raise DatasetProvenanceError(
                "DEVELOPMENT dataset can only be accessed for DEVELOPMENT_RESEARCH",
                dataset_role=provenance.dataset_role.value,
                access_intent=access_intent.value,
            )

        if provenance.is_validation and access_intent != AccessIntent.VALIDATION_SELECTION:
            raise DatasetProvenanceError(
                "VALIDATION dataset can only be accessed for VALIDATION_SELECTION",
                dataset_role=provenance.dataset_role.value,
                access_intent=access_intent.value,
            )

        certificate = ProvenanceCertificate(
            hypothesis_id=self.hypothesis_id,
            dataset_provenance=provenance,
            access_intent=access_intent,
            research_freeze=self.research_freeze if provenance.is_pure_holdout else None,
        )

        cert_key = f"{provenance.dataset_id}:{access_intent.value}"
        self.certificates[cert_key] = certificate

        logger.info(
            "Certificate issued",
            hypothesis_id=self.hypothesis_id,
            certificate_id=certificate.certificate_id,
            dataset_id=provenance.dataset_id,
            access_intent=access_intent.value,
        )

        return certificate

    def summary(self) -> Dict[str, Any]:
        """Return governance summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "datasets": {key: prov.summary() for key, prov in self.datasets.items()},
            "research_freeze": self.research_freeze.summary() if self.research_freeze else None,
            "certificates_issued": len(self.certificates),
        }
