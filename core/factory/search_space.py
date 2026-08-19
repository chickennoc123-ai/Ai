"""Search Space Model — Generation 2, Phase 9.

Makes "what exactly was searched" an explicit, serialized, hashed,
immutable artifact — not something reconstructed after the fact from
however many candidates happened to be generated.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_SEARCH_SPACE_REGISTRY_PATH = Path("reports/factory/search_space_registry.json")


class SearchSpaceSpecError(EAFactoryError):
    """Raised when a SearchSpace is incomplete."""


class SearchSpaceNotFoundError(EAFactoryError):
    pass


class DuplicateSearchSpaceError(EAFactoryError):
    pass


class FrozenSearchSpaceMutationError(EAFactoryError):
    """Raised if code attempts to register a search space under an
    already-used id with different content -- a search space, once
    registered, is immutable; a changed search must become a new id."""


@dataclass(frozen=True)
class SearchSpace:
    search_space_id: str
    symbols: Tuple[str, ...]
    timeframes: Tuple[str, ...]
    features: Tuple[str, ...]
    #: e.g. {"RSI_period": [10, 14, 20], "EMA_period": [50, 100, 200]}
    feature_parameters: Dict[str, List[Any]]
    entry_conditions: Tuple[str, ...]
    exit_conditions: Tuple[str, ...]
    stop_loss_options: Tuple[str, ...]
    take_profit_options: Tuple[str, ...]
    holding_periods: Tuple[int, ...]
    regimes: Tuple[str, ...]
    position_sizing_options: Tuple[str, ...]
    cost_model: str
    creation_timestamp: str
    generation_method: str = "MANUAL"
    generation_seed: Optional[int] = None

    def __post_init__(self) -> None:
        required_nonempty = {
            "symbols": self.symbols, "timeframes": self.timeframes, "features": self.features,
            "entry_conditions": self.entry_conditions, "exit_conditions": self.exit_conditions,
        }
        missing = [k for k, v in required_nonempty.items() if not v]
        if missing:
            raise SearchSpaceSpecError("search space is incomplete", missing_fields=missing)
        if not self.cost_model or not self.cost_model.strip():
            raise SearchSpaceSpecError("cost_model is required")

    def checksum(self) -> str:
        """Deterministic identity over the search space's CONTENT (not
        its id or creation_timestamp) -- two SearchSpace objects
        describing the same search produce the same checksum regardless
        of when/how they were constructed, which is what
        ``SearchSpaceRegistry.find_duplicate`` relies on."""
        data = {
            "symbols": sorted(self.symbols), "timeframes": sorted(self.timeframes),
            "features": sorted(self.features), "feature_parameters": self.feature_parameters,
            "entry_conditions": sorted(self.entry_conditions), "exit_conditions": sorted(self.exit_conditions),
            "stop_loss_options": sorted(self.stop_loss_options), "take_profit_options": sorted(self.take_profit_options),
            "holding_periods": sorted(self.holding_periods), "regimes": sorted(self.regimes),
            "position_sizing_options": sorted(self.position_sizing_options), "cost_model": self.cost_model,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def combination_count(self) -> int:
        """Total distinct parameter combinations this space enumerates --
        the size the Factory must account for in multiple-testing burden
        (ML-001-SEARCH-SPACE-AND-MULTIPLE-TESTING-CONTRACT.md). Product of
        every varying dimension's cardinality; dimensions with a single
        fixed choice contribute a factor of 1, not 0."""
        count = max(1, len(self.symbols)) * max(1, len(self.timeframes))
        count *= max(1, len(self.entry_conditions)) * max(1, len(self.exit_conditions))
        count *= max(1, len(self.stop_loss_options)) * max(1, len(self.take_profit_options))
        count *= max(1, len(self.holding_periods)) * max(1, len(self.regimes))
        count *= max(1, len(self.position_sizing_options))
        for param_values in self.feature_parameters.values():
            count *= max(1, len(param_values))
        return count

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["symbols"] = list(self.symbols)
        d["timeframes"] = list(self.timeframes)
        d["features"] = list(self.features)
        d["entry_conditions"] = list(self.entry_conditions)
        d["exit_conditions"] = list(self.exit_conditions)
        d["stop_loss_options"] = list(self.stop_loss_options)
        d["take_profit_options"] = list(self.take_profit_options)
        d["holding_periods"] = list(self.holding_periods)
        d["regimes"] = list(self.regimes)
        d["position_sizing_options"] = list(self.position_sizing_options)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SearchSpace":
        d = dict(d)
        for tuple_field in (
            "symbols", "timeframes", "features", "entry_conditions", "exit_conditions",
            "stop_loss_options", "take_profit_options", "holding_periods", "regimes",
            "position_sizing_options",
        ):
            d[tuple_field] = tuple(d.get(tuple_field, ()))
        return SearchSpace(**d)


class SearchSpaceRegistry:
    """Immutable, versioned, JSON-backed catalog of every search space
    ever declared. There is deliberately no ``update``/``mutate`` method
    -- a search space, once registered, never changes; a materially
    different search is a materially different ``search_space_id``."""

    def __init__(self, path: Path = DEFAULT_SEARCH_SPACE_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._spaces: Dict[str, SearchSpace] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise SearchSpaceSpecError(
                "search space registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._next_id = raw.get("next_id", 1)
        self._spaces = {sid: SearchSpace.from_dict(sdata) for sid, sdata in raw.get("search_spaces", {}).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_id": self._next_id, "search_spaces": {sid: s.to_dict() for sid, s in self._spaces.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def allocate_search_space_id(self) -> str:
        sid = f"SEARCHSPACE-{self._next_id:06d}"
        self._next_id += 1
        self._save()
        return sid

    def register(self, space: SearchSpace) -> SearchSpace:
        if space.search_space_id in self._spaces:
            existing = self._spaces[space.search_space_id]
            if existing.checksum() != space.checksum():
                raise FrozenSearchSpaceMutationError(
                    "search_space_id already registered with DIFFERENT content -- a search "
                    "space is immutable once registered; use a new id for a changed search",
                    search_space_id=space.search_space_id,
                )
            raise DuplicateSearchSpaceError("search_space_id already registered", search_space_id=space.search_space_id)
        self._spaces[space.search_space_id] = space
        self._save()
        return space

    def get(self, search_space_id: str) -> SearchSpace:
        try:
            return self._spaces[search_space_id]
        except KeyError as exc:
            raise SearchSpaceNotFoundError("no such search space", search_space_id=search_space_id) from exc

    def list_all(self) -> List[SearchSpace]:
        return list(self._spaces.values())

    def find_duplicate(self, candidate: SearchSpace) -> Optional[SearchSpace]:
        target = candidate.checksum()
        for existing in self._spaces.values():
            if existing.checksum() == target:
                return existing
        return None
