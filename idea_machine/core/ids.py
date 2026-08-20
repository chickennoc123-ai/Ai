"""Deterministic, content-addressed identity.

Determinism is a hard requirement of the roadmap: the same inputs must always
produce the same ideas, with the same ids, in the same order. Nothing in the
Idea Machine may use ``random``, ``uuid4``, ``time`` or dict iteration order to
mint an identity.

Every id is therefore a short prefix plus a truncated SHA-256 of a
*canonicalised* payload. Canonicalisation sorts mapping keys, normalises
whitespace-insensitive text, and renders floats with a fixed repr so that
``0.1 + 0.2`` and ``0.30000000000000004`` cannot silently produce two different
ids for one idea.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

_WS_RE = re.compile(r"\s+")

#: Length of the hex digest kept in an id. 16 hex chars = 64 bits; at the scale
#: this machine operates (millions of ideas at the very most) collision
#: probability is negligible, and short ids stay readable in reports.
DIGEST_LEN = 16


def normalize_text(text: str) -> str:
    """Lower-case, collapse whitespace, strip. Used for semantic hashing."""
    return _WS_RE.sub(" ", str(text).strip().lower())


def canonical(value: Any) -> Any:
    """Recursively convert ``value`` into a canonical, JSON-serialisable form.

    Mappings become key-sorted dicts, sequences keep their order (order is
    semantic for rule lists), floats are rendered through ``repr`` so their
    textual form is stable, and every other scalar becomes its ``str``.
    """
    if isinstance(value, Mapping):
        return {str(k): canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return repr(float(value))
    if isinstance(value, int):
        return value
    if value is None:
        return None
    return str(value)


def canonical_json(value: Any) -> str:
    """Byte-stable JSON rendering of ``value``."""
    return json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    """Full SHA-256 hex digest of ``value``'s canonical form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def mint_id(prefix: str, payload: Any) -> str:
    """Return ``PREFIX-<16 hex>``, derived only from ``payload``'s content.

    Two calls with equal content always return the same id — that is what makes
    deduplication across runs, and reproducibility of a whole cycle, possible.
    """
    if not prefix or not str(prefix).strip():
        raise ValueError("mint_id requires a non-empty prefix")
    return f"{prefix.strip().upper()}-{content_hash(payload)[:DIGEST_LEN]}"


def semantic_tokens(text: str) -> frozenset:
    """Word tokens of ``text``, for similarity comparisons."""
    return frozenset(t for t in re.findall(r"[a-z0-9]+", normalize_text(text)) if len(t) > 2)


def jaccard(a: str, b: str) -> float:
    """Token Jaccard similarity of two texts, in ``[0.0, 1.0]``."""
    ta, tb = semantic_tokens(a), semantic_tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def stable_sort_key(*parts: Any) -> tuple:
    """A total ordering key that never depends on insertion order."""
    return tuple(canonical_json(p) for p in parts)


def sequence_checksum(items: Sequence[Any]) -> str:
    """Checksum of an ordered sequence — order-sensitive by design."""
    return content_hash([canonical(i) for i in items])
