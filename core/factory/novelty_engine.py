"""Novelty / duplication engine — Generation 3, Phase 10.

Deterministic research-similarity machinery: exact duplicates, near
duplicates (token overlap), parameter-stripped mechanism families, and a
durable family registry (HYPOTHESIS_FAMILY / STRATEGY_FAMILY /
RESEARCH_CLUSTER) whose members are preserved permanently.

Parameter variation is NOT independent research: ``RSI 10 / RSI 14 /
RSI 20 / RSI 30`` all normalize to the same mechanism signature
(``rsi_N``) and therefore the same family — which is exactly what the
multiple-testing/false-discovery accounting later needs to know.

Everything here is deterministic and explainable — no embedding models,
no fuzzy scoring that two runs could disagree on. Similarity is used for
clustering/novelty/accounting/prioritization; it never auto-rejects a
candidate (no such code path exists in this module — an explicit
governance rule would have to add one deliberately).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_FAMILY_REGISTRY_PATH = Path("reports/factory/research_family_registry.json")

FAMILY_KINDS = frozenset({"HYPOTHESIS_FAMILY", "STRATEGY_FAMILY", "RESEARCH_CLUSTER"})

_WORD_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


class FamilyRegistryError(EAFactoryError):
    pass


def normalize_text(text: str) -> str:
    """Lowercase, collapse punctuation/whitespace — the shared first step
    for every signature below, so 'RSI-14 works!' and 'rsi 14 works'
    normalize identically."""
    return " ".join(_WORD_RE.findall(text.lower()))


def text_signature(text: str) -> str:
    """Exact-duplicate identity: SHA-256 of the normalized text."""
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def mechanism_signature(text: str) -> str:
    """Family identity: numbers are replaced by the placeholder ``N``
    BEFORE hashing, so parameter variants of the same mechanism collapse
    to one signature ('rsi 14 oversold' == 'rsi 30 oversold' == 'rsi N
    oversold') while genuinely different mechanisms stay distinct."""
    stripped = _NUMBER_RE.sub("N", normalize_text(text))
    return hashlib.sha256(stripped.encode()).hexdigest()


def token_jaccard(a: str, b: str) -> float:
    """Deterministic near-duplicate measure: Jaccard overlap of the
    normalized token sets. 1.0 = identical vocabulary, 0.0 = disjoint."""
    ta, tb = set(normalize_text(a).split()), set(normalize_text(b).split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_exact_duplicate(a: str, b: str) -> bool:
    return text_signature(a) == text_signature(b)


def is_near_duplicate(a: str, b: str, *, threshold: float = 0.8) -> bool:
    """Same-hypothesis-different-wording detector. The threshold is an
    explicit argument (recorded by callers), never a hidden constant a
    future edit could silently move."""
    return token_jaccard(a, b) >= threshold


def is_same_mechanism(a: str, b: str) -> bool:
    """Same mechanism with parameter variation — the family test."""
    return mechanism_signature(a) == mechanism_signature(b)


@dataclass(frozen=True)
class FamilyRecord:
    family_id: str
    family_kind: str
    family_signature: str  # the mechanism signature (or DNA family fingerprint) shared by members
    description: str
    creation_timestamp: str
    members: Tuple[str, ...] = ()  # hypothesis/candidate ids -- preserved, append-only

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["members"] = list(self.members)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FamilyRecord":
        d = dict(d)
        d["members"] = tuple(d.get("members", ()))
        return FamilyRecord(**d)


class FamilyRegistry:
    """Durable registry of research families. Members are only ever
    appended; a family and its membership history are permanent — this is
    the raw material for later false-discovery analysis ('how many
    variants of this idea were really tried')."""

    def __init__(self, path: Path = DEFAULT_FAMILY_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._families: Dict[str, FamilyRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise FamilyRegistryError("family registry is not valid JSON; refusing to load", path=str(self.path)) from exc
        self._next_id = raw.get("next_id", 1)
        self._families = {fid: FamilyRecord.from_dict(f) for fid, f in raw.get("families", {}).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_id": self._next_id, "families": {fid: f.to_dict() for fid, f in self._families.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def find_by_signature(self, family_kind: str, family_signature: str) -> Optional[FamilyRecord]:
        for f in self._families.values():
            if f.family_kind == family_kind and f.family_signature == family_signature:
                return f
        return None

    def assign(self, *, family_kind: str, family_signature: str, member_id: str, description: str) -> FamilyRecord:
        """Idempotently place ``member_id`` in the family for this
        signature, creating the family on first sight. Returns the
        (possibly new) family with the member included."""
        if family_kind not in FAMILY_KINDS:
            raise FamilyRegistryError("unknown family_kind", family_kind=family_kind, allowed=sorted(FAMILY_KINDS))
        existing = self.find_by_signature(family_kind, family_signature)
        if existing is None:
            fid = f"FAMILY-{self._next_id:06d}"
            self._next_id += 1
            record = FamilyRecord(
                family_id=fid, family_kind=family_kind, family_signature=family_signature,
                description=description, creation_timestamp=utcnow().isoformat(), members=(member_id,),
            )
            self._families[fid] = record
            self._save()
            return record
        if member_id not in existing.members:
            updated = FamilyRecord(**{**existing.to_dict(), "members": tuple(existing.members) + (member_id,)})
            self._families[existing.family_id] = updated
            self._save()
            return updated
        return existing

    def get(self, family_id: str) -> FamilyRecord:
        if family_id not in self._families:
            raise FamilyRegistryError("no such family", family_id=family_id)
        return self._families[family_id]

    def family_of_member(self, member_id: str, family_kind: Optional[str] = None) -> Optional[FamilyRecord]:
        for f in self._families.values():
            if member_id in f.members and (family_kind is None or f.family_kind == family_kind):
                return f
        return None

    def member_count(self, family_id: str) -> int:
        return len(self.get(family_id).members)

    def list_all(self) -> List[FamilyRecord]:
        return list(self._families.values())
