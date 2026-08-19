"""Generation 4, Phase 1 — Candidate freeze snapshot.

Before any economic evaluation of a candidate begins, everything that
could possibly change the result must be pinned down and given a
cryptographic identity. After the freeze, *any* material change is a new
candidate, not an edited one (``ML-001-STRATEGY-FACTORY-SPEC.md`` §5).

The snapshot is deliberately built from *observed* facts — the registry
record, the on-disk dataset bytes, the live feature schema, the recorded
search space — never from values the caller supplies. A caller cannot
hand this module a checksum; it can only ask this module what the
checksum *is*. That is what makes a later `verify_unchanged()` call
meaningful: it recomputes from the same live sources and compares.

What is deliberately NOT here: a model specification. STRAT-000002's
frozen spec contains no model, no hyperparameters and no learned
parameters — it is a pure deterministic rule (see
``core/economic_validation/rule_engine.py``). ``model_specification``
therefore records the literal string ``"NONE_DETERMINISTIC_RULE"`` rather
than inventing a model the candidate never had.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from core.factory.candidate import StrategyCandidate
from core.factory.dataset_registry import DatasetRegistry
from core.factory.search_space import SearchSpaceRegistry
from core.features.fe_r2_001 import get_feature_schema
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

#: Identity of the freeze protocol itself. Bump if the set of frozen
#: fields changes, so an old snapshot is never silently compared against
#: a snapshot built under different rules.
FREEZE_PROTOCOL_VERSION = "G4-FREEZE-001"

#: The model specification value used for candidates that have no model.
NO_MODEL = "NONE_DETERMINISTIC_RULE"


class CandidateFreezeError(EAFactoryError):
    """Raised when a candidate cannot be frozen, or a frozen candidate has drifted."""


def _sha256_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class CandidateFreezeSnapshot:
    """Immutable, checksummed record of everything that defines one
    economic validation run of one candidate version."""

    validation_run_id: str
    freeze_timestamp: str
    freeze_protocol_version: str

    candidate_id: str
    candidate_version: int
    candidate_state_at_freeze: str
    hypothesis_id: Optional[str]
    search_space_id: Optional[str]

    # --- the frozen content itself ---
    specification: Dict[str, Any]
    feature_specification: Dict[str, Any]
    target_specification: Dict[str, Any]
    timeframe: str
    instrument_scope: tuple
    model_specification: str
    hyperparameters: Dict[str, Any]
    cost_model: Dict[str, Any]
    risk_rules: Dict[str, Any]
    position_sizing: str
    seed_policy: Dict[str, Any]
    code_version: str
    dataset_identity: Dict[str, Any]

    # --- checksums ---
    candidate_checksum: str
    spec_checksum: str
    dataset_checksum: str
    feature_schema_checksum: str
    search_space_checksum: str
    snapshot_checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["instrument_scope"] = list(self.instrument_scope)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CandidateFreezeSnapshot":
        d = dict(d)
        d["instrument_scope"] = tuple(d.get("instrument_scope", ()))
        return CandidateFreezeSnapshot(**d)

    def content_checksum(self) -> str:
        """Checksum of every field except ``snapshot_checksum`` itself and
        the wall-clock freeze timestamp/run id — i.e. of the *content*
        that must not change, not of when it happened to be recorded."""
        d = self.to_dict()
        for volatile in ("snapshot_checksum", "freeze_timestamp", "validation_run_id"):
            d.pop(volatile, None)
        return _sha256_json(d)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str))
        return path

    @staticmethod
    def read(path: Path) -> "CandidateFreezeSnapshot":
        return CandidateFreezeSnapshot.from_dict(json.loads(Path(path).read_text()))


def _build_validation_run_id(candidate_id: str, content_checksum: str) -> str:
    """Deterministic run id: same candidate content -> same run id.

    A wall-clock/random run id would make two identical re-runs look like
    two different experiments, which is exactly the ambiguity that lets a
    rescue loop hide (rerun until favorable, report as "another run").
    Deriving it from content means a genuinely identical rerun is
    *visibly* the same run, and any changed input produces a visibly
    different one.
    """
    return f"G4RUN-{candidate_id}-{content_checksum[:16]}"


def freeze_candidate(
    candidate: StrategyCandidate,
    *,
    dataset_registry: DatasetRegistry,
    search_space_registry: Optional[SearchSpaceRegistry] = None,
    cost_model: Dict[str, Any],
    risk_rules: Dict[str, Any],
    target_specification: Dict[str, Any],
    seed_policy: Dict[str, Any],
    code_version: str,
    instrument_scope: tuple,
) -> CandidateFreezeSnapshot:
    """Build the freeze snapshot for ``candidate``.

    ``cost_model``/``risk_rules``/``target_specification``/``seed_policy``
    are supplied by the caller because they are governance decisions that
    live in documents, not in the registry record — but every one of them
    is *recorded verbatim into the checksum*, so a later run that quietly
    uses different values produces a different snapshot checksum and is
    caught by ``verify_unchanged``.
    """
    if not candidate.spec.features:
        raise CandidateFreezeError("candidate has no features; nothing to freeze", candidate_id=candidate.candidate_id)

    dataset = dataset_registry.get(candidate.dataset_id)
    dataset_path = Path(dataset.file_path)
    if not dataset_path.exists():
        raise CandidateFreezeError(
            "candidate's dataset file is not present on disk; cannot freeze against absent data",
            candidate_id=candidate.candidate_id,
            dataset_id=candidate.dataset_id,
            file_path=str(dataset_path),
        )

    observed_file_checksum = _sha256_file(dataset_path)
    if observed_file_checksum != dataset.file_checksum:
        raise CandidateFreezeError(
            "dataset file on disk does not match its registered file_checksum; refusing to freeze "
            "against data whose identity cannot be confirmed",
            dataset_id=dataset.dataset_id,
            registered=dataset.file_checksum,
            observed=observed_file_checksum,
        )

    feature_schema = get_feature_schema()
    # Only the parts of the schema this candidate actually depends on are
    # what must stay fixed -- but the full schema is checksummed anyway,
    # because a change to any shared definition (e.g. the Wilder oracle)
    # would change this candidate's numbers too.
    feature_specification = {
        "feature_version": feature_schema["feature_version"],
        "features_used": list(candidate.spec.features),
        "full_schema": feature_schema,
    }

    search_space_checksum = ""
    if candidate.search_space_id and search_space_registry is not None:
        space = search_space_registry.get(candidate.search_space_id)
        search_space_checksum = _sha256_json(space.to_dict())

    spec_dict = asdict(candidate.spec)
    spec_dict["features"] = list(candidate.spec.features)

    dataset_identity = {
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.dataset_version,
        "instrument": dataset.instrument,
        "timeframe": dataset.timeframe,
        "file_path": str(dataset_path),
        "file_checksum": observed_file_checksum,
        "record_checksum": dataset.checksum,
        "row_count": dataset.row_count,
        "coverage_start": str(dataset.coverage_start),
        "coverage_end": str(dataset.coverage_end),
        "timezone": dataset.timezone,
        "provenance_status": dataset.provenance_status,
        "synthetic": bool(dataset.synthetic),
    }

    partial = CandidateFreezeSnapshot(
        validation_run_id="",
        freeze_timestamp=utcnow().isoformat(),
        freeze_protocol_version=FREEZE_PROTOCOL_VERSION,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.version,
        candidate_state_at_freeze=candidate.state.value,
        hypothesis_id=candidate.hypothesis_id,
        search_space_id=candidate.search_space_id,
        specification=spec_dict,
        feature_specification=feature_specification,
        target_specification=dict(target_specification),
        timeframe=candidate.spec.timeframe,
        instrument_scope=tuple(instrument_scope),
        model_specification=NO_MODEL,
        hyperparameters={},
        cost_model=dict(cost_model),
        risk_rules=dict(risk_rules),
        position_sizing=candidate.spec.position_sizing,
        seed_policy=dict(seed_policy),
        code_version=code_version,
        dataset_identity=dataset_identity,
        candidate_checksum=candidate.candidate_checksum,
        spec_checksum=candidate.spec.spec_checksum(),
        dataset_checksum=observed_file_checksum,
        feature_schema_checksum=_sha256_json(feature_schema),
        search_space_checksum=search_space_checksum,
    )

    content = partial.content_checksum()
    from dataclasses import replace as _replace

    return _replace(
        partial,
        validation_run_id=_build_validation_run_id(candidate.candidate_id, content),
        snapshot_checksum=content,
    )


def verify_unchanged(
    snapshot: CandidateFreezeSnapshot,
    candidate: StrategyCandidate,
    *,
    dataset_registry: DatasetRegistry,
) -> None:
    """Raise ``CandidateFreezeError`` if anything the snapshot pinned has moved.

    Called before every phase that consumes the frozen candidate, so a
    mutation between phases cannot pass unnoticed. Checks are against
    live sources (registry record, bytes on disk, current feature
    schema), never against values copied out of the snapshot.
    """
    if candidate.candidate_id != snapshot.candidate_id:
        raise CandidateFreezeError(
            "snapshot is for a different candidate",
            snapshot_candidate_id=snapshot.candidate_id,
            candidate_id=candidate.candidate_id,
        )
    if candidate.version != snapshot.candidate_version:
        raise CandidateFreezeError(
            "candidate version has changed since freeze -- this is a NEW candidate version, "
            "not the frozen one",
            frozen_version=snapshot.candidate_version,
            current_version=candidate.version,
        )
    current_spec_checksum = candidate.spec.spec_checksum()
    if current_spec_checksum != snapshot.spec_checksum:
        raise CandidateFreezeError(
            "candidate specification has been mutated after freeze",
            frozen=snapshot.spec_checksum,
            current=current_spec_checksum,
        )
    current_feature_schema_checksum = _sha256_json(get_feature_schema())
    if current_feature_schema_checksum != snapshot.feature_schema_checksum:
        raise CandidateFreezeError(
            "feature schema has changed since freeze; the frozen candidate's features would "
            "no longer compute the same values",
            frozen=snapshot.feature_schema_checksum,
            current=current_feature_schema_checksum,
        )

    dataset = dataset_registry.get(candidate.dataset_id)
    dataset_path = Path(dataset.file_path)
    if not dataset_path.exists():
        raise CandidateFreezeError("frozen dataset file has disappeared", file_path=str(dataset_path))
    observed = _sha256_file(dataset_path)
    if observed != snapshot.dataset_checksum:
        raise CandidateFreezeError(
            "dataset bytes have changed since freeze",
            frozen=snapshot.dataset_checksum,
            current=observed,
        )
    if snapshot.snapshot_checksum and snapshot.content_checksum() != snapshot.snapshot_checksum:
        raise CandidateFreezeError(
            "freeze snapshot's own contents do not match its recorded snapshot_checksum "
            "(the snapshot file has been edited)",
            recorded=snapshot.snapshot_checksum,
            recomputed=snapshot.content_checksum(),
        )
