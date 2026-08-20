"""World Scanner (Phase 1) — where the raw material comes from.

The scanner is deliberately **provider-based and offline by default**. A
provider is anything that can yield :class:`~idea_machine.scanner.source.
SourceRecord` objects; the machine ships with a local-corpus provider and an
in-memory provider, and a network provider can be registered by the operator.

Two design rules the roadmap forces:

* An external source is *idea material only*. The scanner therefore never
  assigns anything above ``IDEA_SOURCE_ONLY`` authority, and there is no
  parameter that would let it.
* Re-scanning is idempotent. Records are content-addressed on
  ``(reference, raw_content_hash)``, so an unchanged page rescanned tomorrow
  collapses onto the same record instead of inflating the knowledge base.

Nothing here fetches the network on its own. A network provider must be
constructed and registered explicitly by the operator, which keeps test runs
and CI hermetic and keeps an autonomous loop from quietly generating traffic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.errors import IdeaMachineError
from idea_machine.core.ids import content_hash
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard
from idea_machine.scanner.extract import extract_concepts
from idea_machine.scanner.source import SourceRecord
from utils.helpers import isoformat

DEFAULT_SOURCE_LEDGER = DEFAULT_ROOT / "source_ledger.json"


class ScannerError(IdeaMachineError):
    """A provider could not produce usable material."""


# ------------------------------------------------------------------ providers


class SourceProvider:
    """Base provider. Subclasses yield raw documents, not SourceRecords."""

    name: str = "provider"

    def fetch(self) -> Iterable[Mapping[str, Any]]:
        """Yield mappings with at least ``reference``, ``title``, ``text``.

        Optional keys: ``domain``, ``origin_kind``, ``source``, ``metadata``.
        """
        raise NotImplementedError


@dataclass
class InMemoryProvider(SourceProvider):
    """A fixed list of documents. The provider used by tests and fixtures."""

    documents: Sequence[Mapping[str, Any]]
    name: str = "in_memory"

    def fetch(self) -> Iterable[Mapping[str, Any]]:
        return list(self.documents)


@dataclass
class LocalCorpusProvider(SourceProvider):
    """Reads ``*.json`` documents from a directory on disk.

    Each file holds one document mapping. Files are read in sorted filename
    order so a corpus scan is reproducible.
    """

    directory: Path
    name: str = "local_corpus"

    def fetch(self) -> Iterable[Mapping[str, Any]]:
        base = Path(self.directory)
        if not base.exists():
            return []
        docs: List[Mapping[str, Any]] = []
        for path in sorted(base.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                docs.extend(payload)
            else:
                docs.append(payload)
        return docs


@dataclass
class CallableProvider(SourceProvider):
    """Wraps any callable returning documents — the hook for a network source.

    The operator supplies the fetching function, so responsibility for network
    access, rate limits, and terms of service stays with the operator rather
    than being buried inside an autonomous loop.
    """

    fn: Callable[[], Iterable[Mapping[str, Any]]]
    name: str = "callable"

    def fetch(self) -> Iterable[Mapping[str, Any]]:
        return self.fn()


# -------------------------------------------------------------------- scanner


class WorldScanner:
    """Runs providers, normalises documents, and appends to the source ledger."""

    def __init__(
        self,
        *,
        ledger_path: Path = DEFAULT_SOURCE_LEDGER,
        providers: Optional[Sequence[SourceProvider]] = None,
        clock: Callable[[], str] = isoformat,
    ) -> None:
        self.store = AppendOnlyStore(ledger_path, id_field="source_id", kind="source")
        self.providers: List[SourceProvider] = list(providers or [])
        self._clock = clock

    def register(self, provider: SourceProvider) -> None:
        self.providers.append(provider)

    # ------------------------------------------------------------------ scan

    def scan(self) -> Tuple[SourceRecord, ...]:
        """Run every provider and return the records seen this pass.

        Returns *all* records produced by the providers, including ones already
        in the ledger — the caller can tell new from known via
        :meth:`is_known`. The ledger itself deduplicates.
        """
        guard.require("SCAN_SOURCES", provider_count=len(self.providers))
        seen: Dict[str, SourceRecord] = {}
        fresh: List[Dict[str, Any]] = []
        for provider in self.providers:
            for doc in provider.fetch():
                record = self._to_record(doc, provider)
                if record.source_id in seen:
                    continue
                known = self.store.get(record.source_id)
                if known is not None:
                    # Same reference, same content: this is the document we
                    # already have. Keep the ORIGINAL record -- first-seen
                    # retrieved_at is the honest timestamp, and rewriting it
                    # would mean the ledger no longer says when we first
                    # learned this.
                    seen[record.source_id] = SourceRecord.from_dict(known)
                    continue
                seen[record.source_id] = record
                fresh.append(record.to_dict())
        if fresh:
            self.store.append_many(fresh)
        return tuple(seen[k] for k in sorted(seen))

    def _to_record(self, doc: Mapping[str, Any], provider: SourceProvider) -> SourceRecord:
        for required in ("reference", "title"):
            if not str(doc.get(required, "")).strip():
                raise ScannerError(
                    f"document from provider {provider.name!r} is missing {required!r}",
                    provider=provider.name,
                )
        text = str(doc.get("text", "") or doc.get("summary", ""))
        if not text.strip():
            raise ScannerError(
                f"document {doc['reference']!r} has no text to extract concepts from",
                provider=provider.name,
            )
        guard.require("EXTRACT_CONCEPTS", reference=str(doc["reference"]))
        matches = extract_concepts(text)
        return SourceRecord(
            domain=str(doc.get("domain", "FINANCIAL_RESEARCH")),
            source=str(doc.get("source", provider.name)),
            origin_kind=str(doc.get("origin_kind", "WEBSITE")),
            reference=str(doc["reference"]),
            title=str(doc["title"]),
            retrieved_at=str(doc.get("retrieved_at") or self._clock()),
            raw_content_hash=content_hash(text),
            summary=str(doc.get("summary", ""))[:2000],
            concepts=tuple(m.concept for m in matches),
            metadata={
                "provider": provider.name,
                "concept_evidence": {
                    m.concept: {"phrase": m.matched_phrase, "context": m.context} for m in matches
                },
                **dict(doc.get("metadata", {})),
            },
        )

    # ----------------------------------------------------------------- reads

    def is_known(self, record: SourceRecord) -> bool:
        return self.store.has(record.source_id)

    def all_records(self) -> Tuple[SourceRecord, ...]:
        return tuple(SourceRecord.from_dict(d) for d in self.store.all())

    def summary(self) -> Dict[str, Any]:
        records = self.all_records()
        by_domain: Dict[str, int] = {}
        concepts: Dict[str, int] = {}
        for r in records:
            by_domain[r.domain] = by_domain.get(r.domain, 0) + 1
            for c in r.concepts:
                concepts[c] = concepts.get(c, 0) + 1
        return {
            "source_count": len(records),
            "by_domain": dict(sorted(by_domain.items())),
            "distinct_concepts": len(concepts),
            "concept_frequency": dict(sorted(concepts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "ledger_checksum": self.store.checksum(),
        }
