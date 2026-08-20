"""Append-only JSON store shared by every Idea Machine ledger.

Mirrors the discipline the Strategy Factory already applies to its Research
Ledger and Failure Library: records are appended, never edited, never removed.
The store additionally refuses to *shrink* — if the file on disk already holds
more records than the in-memory view, or holds a record whose id we are about
to re-emit with different content, the write is rejected rather than silently
clobbering history.

Deleting or truncating a ledger is a Phase 16 forbidden action ("reset
ledger"), so :meth:`AppendOnlyStore.reset` does not exist; the only way to
discard history is to delete the file outside the Idea Machine, which the
integrity check then reports as tampering.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from idea_machine.core.errors import StoreError
from idea_machine.core.ids import content_hash

#: Root under which every Idea Machine ledger lives. Deliberately separate from
#: ``reports/factory`` so the Idea Machine can never write into a Strategy
#: Factory ledger, even by a path mistake.
DEFAULT_ROOT = Path("reports/idea_machine")

SCHEMA_VERSION = 1


class AppendOnlyStore:
    """A list of JSON records persisted atomically, with history protection.

    ``id_field`` names the record key that carries a unique identity. Appending
    a record whose id already exists is a no-op when the content is identical
    (idempotent replay of a deterministic cycle) and a :class:`StoreError` when
    the content differs (an attempt to rewrite history).
    """

    def __init__(
        self,
        path: Path,
        *,
        id_field: str = "id",
        kind: str = "record",
        autoload: bool = True,
    ) -> None:
        self.path = Path(path)
        self.id_field = id_field
        self.kind = kind
        self._records: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}
        if autoload:
            self.load()

    # ---------------------------------------------------------------- loading

    def load(self) -> None:
        self._records = []
        self._index = {}
        if not self.path.exists():
            return
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoreError(
                f"{self.kind} store is not valid JSON", path=str(self.path), detail=str(exc)
            ) from exc
        if not isinstance(payload, dict) or "records" not in payload:
            raise StoreError(f"{self.kind} store has no 'records' envelope", path=str(self.path))
        records = payload["records"]
        if not isinstance(records, list):
            raise StoreError(f"{self.kind} store 'records' is not a list", path=str(self.path))
        for rec in records:
            if not isinstance(rec, dict):
                raise StoreError(f"{self.kind} store holds a non-object record", path=str(self.path))
            self._append_in_memory(rec)

    def _append_in_memory(self, record: Dict[str, Any]) -> None:
        rid = record.get(self.id_field)
        if rid is None or not str(rid).strip():
            raise StoreError(
                f"{self.kind} record is missing its id field",
                id_field=self.id_field,
                path=str(self.path),
            )
        rid = str(rid)
        if rid in self._index:
            existing = self._records[self._index[rid]]
            if content_hash(existing) != content_hash(record):
                raise StoreError(
                    f"{self.kind} store already holds a DIFFERENT record under this id -- "
                    "append-only stores never rewrite history",
                    record_id=rid,
                    path=str(self.path),
                )
            return
        self._index[rid] = len(self._records)
        self._records.append(record)

    # ---------------------------------------------------------------- writing

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Append ``record`` and persist. Idempotent for identical content."""
        before = len(self._records)
        self._append_in_memory(dict(record))
        if len(self._records) != before:
            self._save()
        return self._records[self._index[str(record[self.id_field])]]

    def append_many(self, records: List[Dict[str, Any]]) -> int:
        """Append several records with a single write. Returns the new count."""
        before = len(self._records)
        for rec in records:
            self._append_in_memory(dict(rec))
        added = len(self._records) - before
        if added:
            self._save()
        return added

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._guard_against_shrink()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": self.kind,
            "record_count": len(self._records),
            "records": self._records,
            "checksum": self.checksum(),
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=False, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _guard_against_shrink(self) -> None:
        """Refuse to write a file that holds fewer records than the one on disk."""
        if not self.path.exists():
            return
        try:
            on_disk = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            # An unreadable file is reported by load()/verify_integrity(); do not
            # let it block an otherwise-valid append.
            return
        disk_count = int(on_disk.get("record_count", 0) or 0)
        if len(self._records) < disk_count:
            raise StoreError(
                f"refusing to shrink the {self.kind} store -- append-only ledgers never lose records",
                path=str(self.path),
                on_disk=disk_count,
                in_memory=len(self._records),
            )

    # ---------------------------------------------------------------- reading

    def all(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._records]

    def get(self, record_id: str) -> Optional[Dict[str, Any]]:
        idx = self._index.get(str(record_id))
        return dict(self._records[idx]) if idx is not None else None

    def has(self, record_id: str) -> bool:
        return str(record_id) in self._index

    def where(self, predicate: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._records if predicate(r)]

    def count(self) -> int:
        return len(self._records)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._records)

    def __iter__(self) -> Iterator[Dict[str, Any]]:  # pragma: no cover - trivial
        return iter(self.all())

    # ------------------------------------------------------------- integrity

    def checksum(self) -> str:
        """Order-sensitive checksum of the whole ledger."""
        return content_hash(self._records)

    def verify_integrity(self) -> None:
        """Re-read the file and confirm it still matches what we hold.

        Raises :class:`StoreError` when the on-disk ledger has been truncated,
        reordered, or edited behind the machine's back.
        """
        if not self.path.exists():
            if self._records:
                raise StoreError(
                    f"{self.kind} store file disappeared while records were held in memory",
                    path=str(self.path),
                )
            return
        payload = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        disk_records = payload.get("records", [])
        if content_hash(disk_records) != self.checksum():
            raise StoreError(
                f"{self.kind} store on disk does not match the in-memory ledger -- "
                "history appears to have been edited",
                path=str(self.path),
                disk_count=len(disk_records),
                memory_count=len(self._records),
            )
        recorded = payload.get("checksum")
        if recorded and recorded != content_hash(disk_records):
            raise StoreError(
                f"{self.kind} store checksum does not match its own records",
                path=str(self.path),
            )
