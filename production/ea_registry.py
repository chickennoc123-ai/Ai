"""EA Product Registry: one immutable record per productized EA.

Append-only (idea_machine.core.store.AppendOnlyStore). A product, once
registered, is never edited -- to change a mechanism, freeze a NEW
candidate, run a NEW GEN14 evaluation, and register a NEW product version.
This module never decides whether a candidate MAY be productized (that is
production.productization.maybe_productize's job, which defers entirely to
ea_generator.EAGenerator's own GEN14-PASS gate); it only records the fact,
immutably, once packaging has already succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.core.ids import mint_id
from idea_machine.core.store import AppendOnlyStore

DEFAULT_REGISTRY_PATH = Path("reports/production/ea_product_registry.json")


@dataclass(frozen=True)
class EAProductRecord:
    product_id: str
    candidate_id: str
    hypothesis_id: str
    factory_evaluation_id: str
    spec_hash: str
    source: str
    status: str  # "CREATED"
    created_at: str
    artifact_path: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id, "candidate_id": self.candidate_id,
            "hypothesis_id": self.hypothesis_id, "factory_evaluation_id": self.factory_evaluation_id,
            "spec_hash": self.spec_hash, "source": self.source, "status": self.status,
            "created_at": self.created_at, "artifact_path": self.artifact_path,
        }


class EAProductRegistry:
    def __init__(self, path: Path = DEFAULT_REGISTRY_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="product_id", kind="ea_product")

    def register(
        self, *, candidate_id: str, hypothesis_id: str, factory_evaluation_id: str,
        spec_hash: str, source: str, artifact_path: str,
    ) -> Dict[str, Any]:
        """Register a newly-packaged EA product. Idempotent by id: the same
        (candidate_id, spec_hash) pair always mints the same product_id, and
        a retry (e.g. a crash after the real packaging succeeded but before
        the caller recorded that success) returns the EXISTING record
        unchanged rather than attempting a fresh append -- this check must
        happen before a new `created_at` timestamp is minted, because that
        timestamp would otherwise make two honest retries of the same
        product look like conflicting content under the same id.
        """
        product_id = mint_id("EAPROD", {"candidate_id": candidate_id, "spec_hash": spec_hash})
        existing = self.store.get(product_id)
        new_content = {
            "candidate_id": candidate_id, "hypothesis_id": hypothesis_id,
            "factory_evaluation_id": factory_evaluation_id, "spec_hash": spec_hash,
            "source": source, "artifact_path": artifact_path,
        }
        if existing is not None:
            existing_content = {k: existing.get(k) for k in new_content}
            if existing_content == new_content:
                return existing
            raise StoreError(
                "ea_product store already holds a DIFFERENT registration for this "
                "(candidate_id, spec_hash) product identity -- an EA product is immutable "
                "after release; to change anything, freeze a NEW candidate and register a "
                "NEW product version",
                product_id=product_id, path=str(self.store.path),
            )
        row = {
            "candidate_id": candidate_id, "hypothesis_id": hypothesis_id,
            "factory_evaluation_id": factory_evaluation_id, "spec_hash": spec_hash,
            "source": source, "status": "CREATED", "artifact_path": artifact_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "product_id": product_id,
        }
        return self.store.append(row)

    def for_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return self.store.where(lambda r: r.get("candidate_id") == candidate_id)

    def all(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def count(self) -> int:
        return self.store.count()

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
