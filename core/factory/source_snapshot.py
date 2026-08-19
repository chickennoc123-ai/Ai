"""Source snapshot store — Generation 3, Phase 3 + Phase 17.

Content-addressed preservation of research-source material, where legally
and technically appropriate. The snapshot id IS the SHA-256 of the stored
bytes, so: identical content always reproduces the identical identity;
materially different content always produces a different identity; and an
altered snapshot is self-evidently altered (its bytes no longer hash to
its own filename).

**Legal discipline** (Phase 3): a snapshot is stored only when the caller
explicitly asserts a ``license_basis`` — this module refuses to store
content with no stated legal basis. Where full content cannot legally be
retained, callers store metadata + a permitted excerpt instead; the
provenance chain then references the excerpt's checksum, honestly labeled
as an excerpt, never presented as the full work.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_SNAPSHOT_DIR = Path("reports/factory/source_snapshots")

#: The legal bases under which this project stores source content.
#: NO_BASIS_STATED is deliberately not in this set -- storing requires an
#: affirmative assertion, never a default.
LICENSE_BASES = frozenset(
    {
        "PERMISSIVE_LICENSE",  # e.g. Apache-2.0 / MIT / CC-BY, verified on the source itself
        "PUBLIC_DOMAIN",
        "OWN_WORK",  # this project's own committed research output
        "PERMITTED_EXCERPT",  # short excerpt within fair-use/quotation norms, full work NOT stored
        "METADATA_ONLY",  # no content bytes at all, only descriptive metadata
    }
)

REPRESENTATIONS = frozenset({"FULL_TEXT", "EXCERPT", "METADATA", "TRANSCRIPT_EXCERPT", "CODE_FILE"})


class SnapshotError(EAFactoryError):
    """Raised when a snapshot cannot be stored/retrieved under this contract."""


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str  # sha256 of the stored bytes -- content-addressed identity
    source_id: str
    representation: str
    license_basis: str
    media_type: str
    byte_count: int
    stored_timestamp: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SnapshotRecord":
        return SnapshotRecord(**d)


class SourceSnapshotStore:
    """Content-addressed, append-only store. Files are named by their own
    SHA-256; an index JSON maps snapshot_id -> SnapshotRecord. There is no
    delete/overwrite method — a snapshot, once stored, is permanent, and
    re-storing identical bytes is a no-op returning the same identity."""

    def __init__(self, directory: Path = DEFAULT_SNAPSHOT_DIR) -> None:
        self.directory = Path(directory)
        self.index_path = self.directory / "snapshot_index.json"
        self._records: Dict[str, SnapshotRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text())
        except json.JSONDecodeError as exc:
            raise SnapshotError("snapshot index is not valid JSON; refusing to load", path=str(self.index_path)) from exc
        self._records = {sid: SnapshotRecord.from_dict(r) for sid, r in raw.get("snapshots", {}).items()}

    def _save_index(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"snapshots": {sid: r.to_dict() for sid, r in self._records.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.index_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def store(
        self,
        content: bytes,
        *,
        source_id: str,
        representation: str,
        license_basis: str,
        media_type: str = "text/plain",
        notes: str = "",
    ) -> SnapshotRecord:
        if not content:
            raise SnapshotError("refusing to store an empty snapshot", source_id=source_id)
        if license_basis not in LICENSE_BASES:
            raise SnapshotError(
                "no recognized legal basis stated for storing this content -- storage refused",
                license_basis=license_basis, allowed=sorted(LICENSE_BASES),
            )
        if representation not in REPRESENTATIONS:
            raise SnapshotError(
                "unknown representation", representation=representation, allowed=sorted(REPRESENTATIONS)
            )
        snapshot_id = hashlib.sha256(content).hexdigest()
        if snapshot_id in self._records:
            return self._records[snapshot_id]  # identical content: same identity, no duplicate write

        self.directory.mkdir(parents=True, exist_ok=True)
        blob_path = self.directory / f"{snapshot_id}.bin"
        fd, tmp_path = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            os.replace(tmp_path, blob_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            source_id=source_id,
            representation=representation,
            license_basis=license_basis,
            media_type=media_type,
            byte_count=len(content),
            stored_timestamp=utcnow().isoformat(),
            notes=notes,
        )
        self._records[snapshot_id] = record
        self._save_index()
        return record

    def get_record(self, snapshot_id: str) -> SnapshotRecord:
        if snapshot_id not in self._records:
            raise SnapshotError("no such snapshot", snapshot_id=snapshot_id)
        return self._records[snapshot_id]

    def read_verified(self, snapshot_id: str) -> bytes:
        """Return the stored bytes ONLY if they still hash to their own
        snapshot_id -- an altered blob raises rather than being silently
        served (the content-addressed tamper check, Phase 17)."""
        record = self.get_record(snapshot_id)
        blob_path = self.directory / f"{snapshot_id}.bin"
        if not blob_path.exists():
            raise SnapshotError("snapshot blob is missing on disk", snapshot_id=snapshot_id)
        content = blob_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != snapshot_id:
            raise SnapshotError(
                "snapshot blob no longer matches its content-addressed identity -- altered or corrupted",
                snapshot_id=snapshot_id,
            )
        return content

    def list_for_source(self, source_id: str) -> List[SnapshotRecord]:
        return [r for r in self._records.values() if r.source_id == source_id]
