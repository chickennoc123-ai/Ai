"""Feature registry — Generation 1 Phase 3 (Feature Factory).

Per ``ML-001-FEATURE-FACTORY-SPEC.md`` §2-§5: formalizes the existing,
already-compliant FE-R2-001/FE-R2-003 feature pipeline
(``core/features/fe_r2_001.py``) into an explicit, queryable
``FeatureContract`` per feature, plus a reproducible feature-schema
identity checksum. This module does not reimplement any feature — it
*wraps* ``core.features.fe_r2_001.get_feature_schema()``, the pipeline's
own existing machine-readable schema function, so there is exactly one
source of truth for what each feature actually computes. Nothing here is
a second, competing feature implementation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Tuple

from core.features import fe_r2_001
from utils.exceptions import EAFactoryError

#: Which conceptual category a feature belongs to
#: (ML-001-FEATURE-FACTORY-SPEC.md §3). This project currently implements
#: features from MOMENTUM, TREND (via momentum), VOLATILITY, and REGIME
#: only — PRICE/RETURNS/VOLUME/ORDER_FLOW/MARKET_STRUCTURE/SESSION/TIME
#: groups are architecturally supported (a feature can declare any of
#: these) but have zero implemented features today, and none are added
#: by this module.
FEATURE_GROUPS = frozenset(
    {
        "PRICE",
        "RETURNS",
        "TREND",
        "MOMENTUM",
        "VOLATILITY",
        "VOLUME_ORDER_FLOW",
        "MARKET_STRUCTURE",
        "REGIME",
        "SESSION_TIME",
    }
)

DETERMINISM_STATUSES = frozenset({"DETERMINISTIC", "DETERMINISTIC_WITH_CAVEAT", "NONDETERMINISTIC"})


class FeatureContractError(EAFactoryError):
    """Raised when a FeatureContract is incomplete or references an unknown feature."""


@dataclass(frozen=True)
class FeatureContract:
    """One feature's complete, queryable contract."""

    feature_id: str
    name: str
    version: str
    definition: str
    formula_reference: str
    input_columns: Tuple[str, ...]
    lookback: int
    timestamp_semantics: str
    output_schema: str
    warmup_requirement: int
    code_version: str
    determinism_status: str
    group: str

    def __post_init__(self) -> None:
        if self.group not in FEATURE_GROUPS:
            raise FeatureContractError("unknown feature group", group=self.group, allowed=sorted(FEATURE_GROUPS))
        if self.determinism_status not in DETERMINISM_STATUSES:
            raise FeatureContractError(
                "unknown determinism_status",
                determinism_status=self.determinism_status,
                allowed=sorted(DETERMINISM_STATUSES),
            )
        if self.warmup_requirement < 0:
            raise FeatureContractError("warmup_requirement must be non-negative", feature_id=self.feature_id)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["input_columns"] = list(self.input_columns)
        return d


#: Formulas taken verbatim from fe_r2_001.get_feature_schema()["definitions"]
#: -- not restated independently, to guarantee this contract can never
#: silently drift from what the pipeline actually computes.
_LOOKBACK_BARS = {
    "momentum_5": 5,
    "momentum_20": 20,
    "rsi_14": 14,
    "atr_14": 14,
    "volatility_regime": 500,
}
_GROUPS = {
    "momentum_5": "MOMENTUM",
    "momentum_20": "MOMENTUM",
    "rsi_14": "MOMENTUM",
    "atr_14": "VOLATILITY",
    "volatility_regime": "REGIME",
}
_INPUT_COLUMNS = {
    "momentum_5": ("close",),
    "momentum_20": ("close",),
    "rsi_14": ("close",),
    "atr_14": ("high", "low", "close"),
    "volatility_regime": ("high", "low", "close"),  # derived from atr_14, which needs h/l/c
}


def build_feature_contracts() -> Dict[str, FeatureContract]:
    """Construct the current ``FeatureContract`` set directly from
    ``fe_r2_001.get_feature_schema()`` — called fresh each time (not
    cached at import time) so a future feature-version bump is picked up
    automatically without this module needing to change."""
    schema = fe_r2_001.get_feature_schema()
    version = schema["feature_version"]
    warmup = schema["warmup_bars"]
    definitions = schema["definitions"]
    contracts: Dict[str, FeatureContract] = {}
    for name in schema["feature_order"]:
        contracts[name] = FeatureContract(
            feature_id=f"{version}::{name}",
            name=name,
            version=version,
            definition=definitions[name],
            formula_reference="core/features/fe_r2_001.py (canonical, single implementation)",
            input_columns=_INPUT_COLUMNS.get(name, ("close",)),
            lookback=_LOOKBACK_BARS.get(name, warmup[name]),
            timestamp_semantics="feature(t) uses only bars with timestamp <= t (no lookahead)",
            output_schema="float64 (ordinal {0,1,2} for volatility_regime)" if name == "volatility_regime" else "float64",
            warmup_requirement=warmup[name],
            code_version=version,
            determinism_status="DETERMINISTIC",
            group=_GROUPS.get(name, "MOMENTUM"),
        )
    return contracts


def feature_schema_identity(feature_ids_in_order: Tuple[str, ...]) -> str:
    """Deterministic checksum of an ORDERED feature-id sequence.

    Distinct from ``core.ml_r2.walkforward_r2._feature_schema_hash()``
    (which hashes the source module's bytes, catching any implementation
    change) — this hashes feature IDENTITY and ORDER specifically, so a
    training artifact's schema identity changes if the feature set, feature
    versions, or their order changes, even if the underlying module bytes
    were touched for an unrelated reason (e.g. a comment edit) that
    ``_feature_schema_hash()`` would also (correctly, but more broadly)
    flag. Reordering FEATURE_ORDER without changing FEATURE_VERSION would
    be a spec violation (fe_r2_001.py's own docstring: "Any reordering
    requires a new feature_version") — this function still produces a
    different identity in that case too, as a second, independent check.
    """
    payload = json.dumps(list(feature_ids_in_order), sort_keys=False).encode()
    return hashlib.sha256(payload).hexdigest()


def canonical_schema_identity() -> str:
    """The feature-schema identity for the pipeline's own current,
    canonical ``FEATURE_ORDER`` — the value every real training run
    (``core.ml_r2.model_r2``, ``core.ml_r2.walkforward_r2``) is implicitly
    using today."""
    contracts = build_feature_contracts()
    ordered_ids = tuple(contracts[name].feature_id for name in fe_r2_001.FEATURE_ORDER)
    return feature_schema_identity(ordered_ids)
