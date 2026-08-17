"""ML-001-R2 run provenance record.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 15 (Reproducibility
Requirements) and the implementation-phase requirement that "a result
without complete provenance must be rejected." This is the single most
important process fix relative to old ML-001, where every published
metric traced back to an uncommitted, unrecoverable generator.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from utils.exceptions import EAFactoryError

PROVENANCE_SPEC_ID = "PROVENANCE-R2-001"

_REQUIRED_FIELDS = (
    "strategy_id",
    "strategy_version",
    "model_version",
    "feature_version",
    "dataset_id",
    "dataset_checksum",
    "code_version",
    "config_checksum",
    "training_period",
    "validation_period",
    "holdout_period",
    "feature_schema_hash",
    "model_checksum",
    "random_seed",
    "execution_assumptions",
)


class ProvenanceIncompleteError(EAFactoryError):
    """Raised when a RunProvenance record is missing a required field."""


@dataclass(frozen=True)
class RunProvenance:
    """Immutable provenance record for a single ML-001-R2 research run.

    Every field is required — ``validate_complete()`` rejects any run
    missing one, rather than allowing an orphaned result with no
    traceable origin (the exact failure mode identified in the old
    ML-001 recovery reports).
    """

    strategy_id: str
    strategy_version: str
    model_version: str
    feature_version: str
    dataset_id: str
    dataset_checksum: str
    code_version: str
    config_checksum: str
    training_period: tuple
    validation_period: tuple
    holdout_period: tuple
    feature_schema_hash: str
    model_checksum: str
    random_seed: int
    execution_assumptions: Dict[str, Any] = field(default_factory=dict)

    def validate_complete(self) -> None:
        """Raise ``ProvenanceIncompleteError`` if any required field is empty/None."""
        missing = []
        for name in _REQUIRED_FIELDS:
            value = getattr(self, name)
            if value is None:
                missing.append(name)
            elif isinstance(value, str) and not value.strip():
                missing.append(name)
            elif isinstance(value, (tuple, list, dict)) and len(value) == 0:
                missing.append(name)
        if missing:
            raise ProvenanceIncompleteError(
                "run provenance is incomplete; result rejected", missing_fields=missing
            )

    def to_manifest_dict(self) -> Dict[str, Any]:
        self.validate_complete()
        data = asdict(self)
        data["training_period"] = list(self.training_period)
        data["validation_period"] = list(self.validation_period)
        data["holdout_period"] = list(self.holdout_period)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_manifest_dict(), indent=2, default=str)
