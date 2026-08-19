"""Research Failure Library — Generation 3, Phase 15.

Failures are information, not waste. Every rejected hypothesis/candidate
may record a durable, categorized failure entry; nothing here is ever
deleted (append-only, mirroring the Research Ledger's discipline). The
library is one of the two sanctioned inputs to research-knowledge
feedback (Phase 16): family-level *counts* of prior failures may inform
novelty/priority/compute allocation — the records deliberately carry NO
performance metrics field, so holdout/OOS numbers structurally cannot
flow back into research targeting through this channel.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_FAILURE_LIBRARY_PATH = Path("reports/factory/failure_library.json")

FAILURE_STAGES = frozenset(
    {
        "INTAKE", "CLAIM_EXTRACTION", "FORMALIZATION", "QUALITY_GATE", "NOVELTY",
        "PREFLIGHT", "DATA_VALIDATION", "TRAINING", "OOS", "WFA", "ROBUSTNESS",
        "COST_STRESS", "STATISTICS", "MULTIPLE_TESTING", "HOLDOUT", "GOVERNANCE",
    }
)

FAILURE_CATEGORIES = frozenset(
    {
        "INVALID_DATA",
        "INSUFFICIENT_HISTORY",
        "LEAKAGE",
        "TEMPORAL_INVALIDITY",
        "NO_SIGNAL",
        "NEGATIVE_EXPECTANCY",
        "COST_SENSITIVITY",
        "PARAMETER_FRAGILITY",
        "OOS_DECAY",
        "WFA_FAILURE",
        "STATISTICAL_FAILURE",
        "DUPLICATE",
        "GOVERNANCE_FAILURE",
        "PROVENANCE_FAILURE",
        "SEARCH_SPACE_INVALID",
        "SOURCE_ACCESS_FAILED",
        "FORMALIZATION_INCOMPLETE",
    }
)


class FailureLibraryError(EAFactoryError):
    pass


@dataclass(frozen=True)
class FailureRecord:
    failure_id: str
    entity_id: str  # hypothesis/candidate/source/claim id
    failure_stage: str
    failure_category: str
    failure_reason: str
    timestamp: str
    evidence_reference: str = ""
    related_family: str = ""
    related_features: tuple = ()
    related_market: str = ""
    related_search_space: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["related_features"] = list(self.related_features)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FailureRecord":
        d = dict(d)
        d["related_features"] = tuple(d.get("related_features", ()))
        return FailureRecord(**d)


class FailureLibrary:
    """Append-only. No delete/update method exists, by design."""

    def __init__(self, path: Path = DEFAULT_FAILURE_LIBRARY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._failures: List[FailureRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise FailureLibraryError("failure library is not valid JSON; refusing to load", path=str(self.path)) from exc
        self._next_id = raw.get("next_id", 1)
        self._failures = [FailureRecord.from_dict(f) for f in raw.get("failures", [])]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_id": self._next_id, "failures": [f.to_dict() for f in self._failures]}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def record(
        self,
        *,
        entity_id: str,
        failure_stage: str,
        failure_category: str,
        failure_reason: str,
        evidence_reference: str = "",
        related_family: str = "",
        related_features: tuple = (),
        related_market: str = "",
        related_search_space: str = "",
    ) -> FailureRecord:
        if failure_stage not in FAILURE_STAGES:
            raise FailureLibraryError("unknown failure_stage", failure_stage=failure_stage, allowed=sorted(FAILURE_STAGES))
        if failure_category not in FAILURE_CATEGORIES:
            raise FailureLibraryError(
                "unknown failure_category", failure_category=failure_category, allowed=sorted(FAILURE_CATEGORIES)
            )
        record = FailureRecord(
            failure_id=f"FAIL-{self._next_id:06d}",
            entity_id=entity_id,
            failure_stage=failure_stage,
            failure_category=failure_category,
            failure_reason=failure_reason,
            timestamp=utcnow().isoformat(),
            evidence_reference=evidence_reference,
            related_family=related_family,
            related_features=tuple(related_features),
            related_market=related_market,
            related_search_space=related_search_space,
        )
        self._next_id += 1
        self._failures.append(record)
        self._save()
        return record

    def all_failures(self) -> List[FailureRecord]:
        return list(self._failures)

    def failures_for_entity(self, entity_id: str) -> List[FailureRecord]:
        return [f for f in self._failures if f.entity_id == entity_id]

    def count_by_family(self, family_id: str) -> int:
        """The Phase 16-sanctioned feedback quantity: HOW MANY failures a
        family has accumulated — a count, never a performance number."""
        return sum(1 for f in self._failures if f.related_family == family_id)

    def count_by_category(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self._failures:
            out[f.failure_category] = out.get(f.failure_category, 0) + 1
        return out
