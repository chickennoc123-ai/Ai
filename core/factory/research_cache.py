"""Governed research cache — Generation 3, Phase 18.

An optimization, never a governance shortcut. A cache key is the SHA-256
of EVERY dependency that can affect the cached result — dataset checksum,
feature version, hypothesis checksum, search-space checksum, code
version, cost model, random seed, and anything else the caller declares.
A lookup with any dependency changed produces a different key and
therefore a guaranteed miss; there is no partial-key or fuzzy lookup.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_RESEARCH_CACHE_PATH = Path("reports/factory/research_cache.json")

#: Dependencies every cache key MUST declare (a caller may add more, but
#: can never omit these -- omitting one would let a stale result survive
#: a change in that dependency).
REQUIRED_KEY_FIELDS = frozenset(
    {"dataset_checksum", "feature_version", "hypothesis_checksum", "search_space_checksum",
     "code_version", "cost_model", "random_seed"}
)


class ResearchCacheError(EAFactoryError):
    pass


def cache_key(**dependencies: Any) -> str:
    """Deterministic key over ALL declared dependencies. Raises unless
    every REQUIRED_KEY_FIELDS member is present — a key that silently
    dropped a dependency is exactly the failure mode this contract
    forbids."""
    missing = sorted(REQUIRED_KEY_FIELDS - set(dependencies.keys()))
    if missing:
        raise ResearchCacheError(
            "cache key is missing required dependency fields -- a cache hit must be "
            "impossible when any relevant dependency changed",
            missing_fields=missing,
        )
    return hashlib.sha256(json.dumps(dependencies, sort_keys=True, default=str).encode()).hexdigest()


class ResearchCache:
    def __init__(self, path: Path = DEFAULT_RESEARCH_CACHE_PATH) -> None:
        self.path = Path(path)
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise ResearchCacheError("research cache is not valid JSON; refusing to load", path=str(self.path)) from exc
        self._entries = raw.get("entries", {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": self._entries}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def put(self, key: str, value: Dict[str, Any]) -> None:
        self._entries[key] = {"value": value, "stored_timestamp": utcnow().isoformat()}
        self._save()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Exact-key lookup only. Any dependency change produces a
        different key upstream (cache_key), so this can never return a
        result computed under different dependencies."""
        entry = self._entries.get(key)
        return entry["value"] if entry is not None else None
