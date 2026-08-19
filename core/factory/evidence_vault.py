"""
OGD-4 Implementation: Evidence Vault with Cryptographic Sealing

A durable, immutable store for independent evaluation datasets.
Provides pre-research firewall: metadata visible, observations locked until authorization.

Persists to disk (``reports/factory/evidence_vault.json`` by default) using the
same atomic-write pattern as ``core.factory.dataset_registry.DatasetRegistry``,
so a seal recorded in one process is verifiable in a later, independent process —
without that, "sealed" would mean nothing beyond the lifetime of a single script.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import tempfile

DEFAULT_EVIDENCE_VAULT_PATH = Path("reports/factory/evidence_vault.json")


class EvidenceVaultCorruptionError(ValueError):
    """Raised when the persisted vault file exists but is not valid JSON."""


class EvidenceSealStatus(Enum):
    """Status of an evidence dataset seal."""
    UNSEALED = "unsealed"
    SEALED = "sealed"
    AUTHORIZED = "authorized_for_evaluation"
    CONSUMED = "consumed"
    RETIRED = "retired"


class IndependenceLevel(Enum):
    """OGD-4 Definition: Level of independence."""
    LEVEL_3 = "unseen_time_period"  # Minimum for temporal independence
    LEVEL_4 = "new_instrument"
    LEVEL_5 = "independently_sourced"
    LEVEL_6 = "forward_observation"


@dataclass
class EvidenceDatasetMetadata:
    """
    Metadata visible to research code BEFORE authorization.

    This is PUBLIC (in the cryptographic sense): the Factory may know the dataset exists
    but cannot access observations.
    """
    dataset_id: str
    instrument: str
    timeframe: str
    source: str
    source_url: str
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    timezone: str
    price_type: str  # OHLC, bid/ask, etc.

    # Seal identity (reproducible)
    data_checksum: str  # SHA256 of complete dataset
    metadata_checksum: str  # SHA256 of this metadata
    combined_seal_hash: str  # SHA256(data_checksum + metadata_checksum + schema_version)

    # Provenance
    source_verified: bool
    download_timestamp: datetime
    download_method: str  # "api", "file_download", etc.

    # Research exposure (public knowledge)
    research_exposure: str = "UNEXPOSED"  # UNEXPOSED, EXPOSED, UNKNOWN
    independence_level: str = "UNKNOWN"  # LEVEL_3, LEVEL_4, LEVEL_5, LEVEL_6, UNKNOWN

    # Seal status
    seal_status: EvidenceSealStatus = EvidenceSealStatus.UNSEALED
    seal_timestamp: Optional[datetime] = None
    seal_version: str = "1.0"

    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    seal_hash_reproducible: bool = False  # Verified by fresh-process test

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["coverage_start"] = self.coverage_start.isoformat()
        d["coverage_end"] = self.coverage_end.isoformat()
        d["download_timestamp"] = self.download_timestamp.isoformat()
        d["seal_timestamp"] = self.seal_timestamp.isoformat() if self.seal_timestamp else None
        d["created_at"] = self.created_at.isoformat()
        d["seal_status"] = self.seal_status.value
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "EvidenceDatasetMetadata":
        d = dict(d)
        d["coverage_start"] = datetime.fromisoformat(d["coverage_start"])
        d["coverage_end"] = datetime.fromisoformat(d["coverage_end"])
        d["download_timestamp"] = datetime.fromisoformat(d["download_timestamp"])
        d["seal_timestamp"] = datetime.fromisoformat(d["seal_timestamp"]) if d.get("seal_timestamp") else None
        d["created_at"] = datetime.fromisoformat(d["created_at"])
        d["seal_status"] = EvidenceSealStatus(d["seal_status"])
        return EvidenceDatasetMetadata(**d)


@dataclass
class EvidenceEvaluationAuthorization:
    """Authorization to evaluate a candidate against sealed evidence."""
    dataset_id: str
    candidate_id: str
    candidate_spec_checksum: str
    authorization_timestamp: datetime
    authorized_by: str  # "governance", specific person, etc.
    authorization_code: str  # Must match to unseal
    authorization_reason: str

    # Tracking
    evaluation_count: int = 0  # How many times this candidate has accessed it
    evaluated_at: Optional[datetime] = None
    result_checksum: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["authorization_timestamp"] = self.authorization_timestamp.isoformat()
        d["evaluated_at"] = self.evaluated_at.isoformat() if self.evaluated_at else None
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "EvidenceEvaluationAuthorization":
        d = dict(d)
        d["authorization_timestamp"] = datetime.fromisoformat(d["authorization_timestamp"])
        d["evaluated_at"] = datetime.fromisoformat(d["evaluated_at"]) if d.get("evaluated_at") else None
        return EvidenceEvaluationAuthorization(**d)


@dataclass
class EvidenceConsumptionRecord:
    """Permanent record of evidence dataset consumption."""
    dataset_id: str
    candidate_id: str
    evaluation_timestamp: datetime
    result_checksum: str  # SHA256 of evaluation results
    result_summary: str  # e.g., "passed", "failed", "not_attempted"

    # Multiple testing tracking
    cumulative_trials: int  # How many trials against this dataset total?
    bonferroni_threshold: float  # Adjusted significance threshold

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evaluation_timestamp"] = self.evaluation_timestamp.isoformat()
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "EvidenceConsumptionRecord":
        d = dict(d)
        d["evaluation_timestamp"] = datetime.fromisoformat(d["evaluation_timestamp"])
        return EvidenceConsumptionRecord(**d)


class EvidenceVault:
    """
    Cryptographically sealed independent evaluation data store.

    Separates PUBLIC METADATA (always visible to research) from
    SEALED OBSERVATIONS (locked until authorized evaluation).
    """

    def __init__(self, path: Path = DEFAULT_EVIDENCE_VAULT_PATH):
        self.path = Path(path)
        self.datasets: Dict[str, EvidenceDatasetMetadata] = {}
        self.seals: Dict[str, str] = {}  # dataset_id -> combined_seal_hash
        self.authorizations: Dict[str, EvidenceEvaluationAuthorization] = {}
        self.consumptions: List[EvidenceConsumptionRecord] = []
        self.research_exposed: set = set()  # dataset_ids that Factory accessed before seal
        self._load()

    # ============================================================
    # PERSISTENCE (atomic write; same pattern as DatasetRegistry)
    # ============================================================

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise EvidenceVaultCorruptionError(
                f"evidence vault file is not valid JSON; refusing to load: {self.path}"
            ) from exc
        self.datasets = {
            did: EvidenceDatasetMetadata.from_dict(d) for did, d in raw.get("datasets", {}).items()
        }
        self.seals = dict(raw.get("seals", {}))
        self.authorizations = {
            k: EvidenceEvaluationAuthorization.from_dict(d) for k, d in raw.get("authorizations", {}).items()
        }
        self.consumptions = [EvidenceConsumptionRecord.from_dict(d) for d in raw.get("consumptions", [])]
        self.research_exposed = set(raw.get("research_exposed", []))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "datasets": {did: m.to_dict() for did, m in self.datasets.items()},
            "seals": self.seals,
            "authorizations": {k: a.to_dict() for k, a in self.authorizations.items()},
            "consumptions": [c.to_dict() for c in self.consumptions],
            "research_exposed": sorted(self.research_exposed),
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ============================================================
    # PHASE 1: ACQUISITION & METADATA SETUP (BEFORE SEAL)
    # ============================================================

    def register_dataset_unsealed(self,
                                  dataset_id: str,
                                  instrument: str,
                                  timeframe: str,
                                  source: str,
                                  source_url: str,
                                  coverage_start: datetime,
                                  coverage_end: datetime,
                                  row_count: int,
                                  timezone: str,
                                  price_type: str,
                                  download_timestamp: datetime,
                                  download_method: str,
                                  source_verified: bool = False) -> EvidenceDatasetMetadata:
        """
        Register a raw dataset BEFORE sealing.

        At this point the Factory may know it exists, but has not computed seal.
        No observations have been accessed (if architecture is correct).
        """
        if dataset_id in self.datasets:
            raise ValueError(f"Dataset {dataset_id} already registered")

        metadata = EvidenceDatasetMetadata(
            dataset_id=dataset_id,
            instrument=instrument,
            timeframe=timeframe,
            source=source,
            source_url=source_url,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            row_count=row_count,
            timezone=timezone,
            price_type=price_type,
            data_checksum="UNCOMPUTED",
            metadata_checksum="UNCOMPUTED",
            combined_seal_hash="UNCOMPUTED",
            source_verified=source_verified,
            download_timestamp=download_timestamp,
            download_method=download_method,
            seal_status=EvidenceSealStatus.UNSEALED,
        )

        self.datasets[dataset_id] = metadata
        self._save()
        return metadata

    # ============================================================
    # PHASE 2: SEALING (ATOMIC TRANSITION)
    # ============================================================

    def seal_dataset(self,
                    dataset_id: str,
                    data_bytes: bytes,
                    research_exposure: str = "UNEXPOSED",
                    independence_level: str = "UNKNOWN") -> str:
        """
        Compute and record cryptographic seal.

        CRITICAL: This must happen BEFORE any hypothesis/feature/parameter research
        that uses this dataset's observations.

        Returns: combined_seal_hash (reproducible proof of seal)
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not registered")

        metadata = self.datasets[dataset_id]

        if metadata.seal_status != EvidenceSealStatus.UNSEALED:
            raise ValueError(f"Dataset {dataset_id} already sealed (status={metadata.seal_status.value})")

        # Compute data checksum
        data_checksum = hashlib.sha256(data_bytes).hexdigest()

        # Compute metadata checksum (deterministic JSON serialization)
        metadata_dict = {
            "dataset_id": metadata.dataset_id,
            "instrument": metadata.instrument,
            "timeframe": metadata.timeframe,
            "source": metadata.source,
            "coverage_start": metadata.coverage_start.isoformat(),
            "coverage_end": metadata.coverage_end.isoformat(),
            "row_count": metadata.row_count,
            "timezone": metadata.timezone,
            "price_type": metadata.price_type,
            "download_timestamp": metadata.download_timestamp.isoformat(),
            "download_method": metadata.download_method,
            "source_verified": metadata.source_verified,
        }
        metadata_json = json.dumps(metadata_dict, sort_keys=True, separators=(',', ':'))
        metadata_checksum = hashlib.sha256(metadata_json.encode()).hexdigest()

        # Compute combined seal (schema version included for reproducibility)
        schema_version = "1.0"
        seal_input = f"{data_checksum}:{metadata_checksum}:{schema_version}"
        combined_seal_hash = hashlib.sha256(seal_input.encode()).hexdigest()

        # Update metadata
        metadata.data_checksum = data_checksum
        metadata.metadata_checksum = metadata_checksum
        metadata.combined_seal_hash = combined_seal_hash
        metadata.seal_status = EvidenceSealStatus.SEALED
        metadata.seal_timestamp = datetime.utcnow()
        metadata.research_exposure = research_exposure
        metadata.independence_level = independence_level

        # Store seal for later verification
        self.seals[dataset_id] = combined_seal_hash

        self._save()
        return combined_seal_hash

    def verify_seal(self, dataset_id: str, data_bytes: bytes) -> bool:
        """
        Verify seal reproducibility.

        Fresh process can independently recompute the seal given bytes + metadata.
        Returns True if seal matches; False if tampered/corrupted.
        """
        if dataset_id not in self.datasets:
            return False

        if dataset_id not in self.seals:
            return False

        metadata = self.datasets[dataset_id]

        # Recompute data checksum
        data_checksum = hashlib.sha256(data_bytes).hexdigest()
        if data_checksum != metadata.data_checksum:
            return False

        # Recompute metadata checksum (same deterministic JSON)
        metadata_dict = {
            "dataset_id": metadata.dataset_id,
            "instrument": metadata.instrument,
            "timeframe": metadata.timeframe,
            "source": metadata.source,
            "coverage_start": metadata.coverage_start.isoformat(),
            "coverage_end": metadata.coverage_end.isoformat(),
            "row_count": metadata.row_count,
            "timezone": metadata.timezone,
            "price_type": metadata.price_type,
            "download_timestamp": metadata.download_timestamp.isoformat(),
            "download_method": metadata.download_method,
            "source_verified": metadata.source_verified,
        }
        metadata_json = json.dumps(metadata_dict, sort_keys=True, separators=(',', ':'))
        metadata_checksum = hashlib.sha256(metadata_json.encode()).hexdigest()
        if metadata_checksum != metadata.metadata_checksum:
            return False

        # Recompute combined seal
        schema_version = "1.0"
        seal_input = f"{data_checksum}:{metadata_checksum}:{schema_version}"
        combined_seal_hash = hashlib.sha256(seal_input.encode()).hexdigest()

        return combined_seal_hash == self.seals[dataset_id]

    # ============================================================
    # PRE-RESEARCH FIREWALL: METADATA VISIBLE, OBSERVATIONS LOCKED
    # ============================================================

    def get_metadata(self, dataset_id: str) -> Optional[EvidenceDatasetMetadata]:
        """
        Get dataset metadata (always allowed).

        Research code can know the dataset exists, its coverage, its seal status.
        But NOT the OHLC price bars.
        """
        return self.datasets.get(dataset_id)

    def get_observation_access_denied(self, dataset_id: str) -> str:
        """
        Proof that research code cannot access observations before authorization.

        This method exists to demonstrate the architectural boundary.
        Any actual attempt to access unsealed observations should raise PermissionError.
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        if self.datasets[dataset_id].seal_status == EvidenceSealStatus.SEALED:
            raise PermissionError(
                f"Observations for sealed dataset {dataset_id} are locked. "
                f"Governance authorization required."
            )

        raise PermissionError(f"Dataset {dataset_id} is not sealed; cannot access observations.")

    # ============================================================
    # PHASE 3: AUTHORIZATION & EVALUATION
    # ============================================================

    def authorize_evaluation(self,
                            dataset_id: str,
                            candidate_id: str,
                            candidate_spec_checksum: str,
                            authorization_code: str,
                            reason: str = "") -> EvidenceEvaluationAuthorization:
        """
        Governance-authorized unseal for ONE-TIME evaluation.

        After this, evaluation can proceed ONE TIME.
        Subsequent attempts against the same dataset are rejected unless re-authorized.
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        metadata = self.datasets[dataset_id]

        # Verify seal status
        if metadata.seal_status == EvidenceSealStatus.CONSUMED:
            raise ValueError(f"Dataset {dataset_id} is already consumed; cannot re-evaluate")

        if metadata.seal_status != EvidenceSealStatus.SEALED:
            raise ValueError(f"Dataset {dataset_id} is not sealed (status={metadata.seal_status.value})")

        # Verify independence (OGD-4)
        if metadata.research_exposure == "EXPOSED":
            raise ValueError(f"Dataset {dataset_id} is research-exposed; cannot use for independent evaluation")

        if metadata.independence_level == "UNKNOWN":
            raise ValueError(f"Dataset {dataset_id} has unknown independence; cannot authorize")

        # Create authorization
        auth = EvidenceEvaluationAuthorization(
            dataset_id=dataset_id,
            candidate_id=candidate_id,
            candidate_spec_checksum=candidate_spec_checksum,
            authorization_timestamp=datetime.utcnow(),
            authorized_by="governance",
            authorization_code=authorization_code,
            authorization_reason=reason,
        )

        auth_key = f"{dataset_id}:{candidate_id}"
        self.authorizations[auth_key] = auth

        # SEALED -> AUTHORIZED: consume_dataset() below requires this transition
        # to have happened, so evaluation can never skip straight from SEALED to
        # CONSUMED without an authorization on record.
        metadata.seal_status = EvidenceSealStatus.AUTHORIZED

        self._save()
        return auth

    def consume_dataset(self,
                       dataset_id: str,
                       candidate_id: str,
                       result_checksum: str,
                       result_summary: str = "evaluated") -> EvidenceConsumptionRecord:
        """
        Mark dataset as CONSUMED after evaluation completes.

        This is a one-way transition. The dataset cannot be re-evaluated after this.
        Requires a prior authorize_evaluation() call for this exact
        (dataset_id, candidate_id) pair -- SEALED -> CONSUMED without ever
        passing through AUTHORIZED is rejected.
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        metadata = self.datasets[dataset_id]

        if metadata.seal_status == EvidenceSealStatus.CONSUMED:
            raise ValueError(f"Dataset {dataset_id} is already consumed")

        if metadata.seal_status != EvidenceSealStatus.AUTHORIZED:
            raise ValueError(
                f"Dataset {dataset_id} is not authorized for evaluation "
                f"(status={metadata.seal_status.value}); call authorize_evaluation() first"
            )

        auth_key = f"{dataset_id}:{candidate_id}"
        if auth_key not in self.authorizations:
            raise ValueError(
                f"No authorization on record for candidate {candidate_id} against dataset {dataset_id}"
            )

        # Record consumption
        record = EvidenceConsumptionRecord(
            dataset_id=dataset_id,
            candidate_id=candidate_id,
            evaluation_timestamp=datetime.utcnow(),
            result_checksum=result_checksum,
            result_summary=result_summary,
            cumulative_trials=1,  # Would be incremented if multiple candidates
            bonferroni_threshold=0.05,  # Would be adjusted for multiple testing
        )

        self.consumptions.append(record)

        # Mark dataset as consumed
        metadata.seal_status = EvidenceSealStatus.CONSUMED

        self._save()
        return record

    # ============================================================
    # AUDIT & VERIFICATION
    # ============================================================

    def get_audit_trail(self, dataset_id: str) -> Dict[str, Any]:
        """Complete audit trail of a dataset's lifecycle."""
        if dataset_id not in self.datasets:
            return {}

        metadata = self.datasets[dataset_id]
        consumptions = [c for c in self.consumptions if c.dataset_id == dataset_id]

        return {
            "dataset_id": dataset_id,
            "status": metadata.seal_status.value,
            "sealed_at": metadata.seal_timestamp.isoformat() if metadata.seal_timestamp else None,
            "seal_hash": self.seals.get(dataset_id, "UNKNOWN"),
            "research_exposure": metadata.research_exposure,
            "independence_level": metadata.independence_level,
            "consumption_count": len(consumptions),
            "consumption_records": [
                {
                    "candidate_id": c.candidate_id,
                    "evaluated_at": c.evaluation_timestamp.isoformat(),
                    "result_summary": c.result_summary,
                }
                for c in consumptions
            ],
        }

    def summary(self) -> Dict[str, Any]:
        """Summary of vault state."""
        return {
            "total_datasets": len(self.datasets),
            "sealed_datasets": sum(1 for m in self.datasets.values() if m.seal_status == EvidenceSealStatus.SEALED),
            "consumed_datasets": sum(1 for m in self.datasets.values() if m.seal_status == EvidenceSealStatus.CONSUMED),
            "total_evaluations": len(self.consumptions),
        }
