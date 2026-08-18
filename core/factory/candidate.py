"""Strategy Factory candidate specification and record.

Per ``ML-001-STRATEGY-FACTORY-SPEC.md`` §2 (Candidate Lifecycle) and §5
(Versioning & Immutability): every candidate has an immutable identifier
and a complete, versioned specification. ``StrategyCandidateSpec`` is a
frozen dataclass so in-place mutation is rejected at the type level, not
by convention; ``StrategyRegistry.assert_mutation_allowed`` additionally
blocks *swapping in* a whole new spec object once a candidate is FROZEN or
later. Any change to entry, exit, features, parameters, model, timeframe,
or cost assumptions requires constructing a *new* ``StrategyCandidate``
with a new ``candidate_id`` and ``parent_candidate_id`` set to the old
one — never mutating the old record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from core.factory.state_machine import CandidateState
from utils.exceptions import EAFactoryError


class CandidateSpecError(EAFactoryError):
    """Raised when a candidate specification is incomplete or invalid."""


class FrozenCandidateMutationError(EAFactoryError):
    """Raised when code attempts to alter a FROZEN-or-later candidate's spec."""


class ProvenanceSpecError(EAFactoryError):
    """Raised when a ``DatasetProvenanceRecord`` is missing a required field."""


@dataclass(frozen=True)
class DatasetProvenanceRecord:
    """One instrument's dataset provenance, per
    ``ML-001-STRATEGY-FACTORY-SPEC.md`` §12 (multi-symbol readiness).

    A candidate's ``instrument_universe`` is a tuple of these — never a
    bare symbol string — so instrument identity is always carried together
    with the specific dataset it was tested against. This exists so the
    Factory can never silently assume "tested on EURUSD" implies "valid on
    GBPUSD/USDJPY/XAUUSD/...": each instrument in a candidate's universe
    has its own dataset id, checksum, source, coverage, timezone, and any
    symbol-specific assumptions (e.g. pip value, session hours, spread
    regime) recorded explicitly.
    """

    symbol: str
    timeframe: str
    dataset_id: str
    dataset_checksum: str
    source: str
    coverage_start: str
    coverage_end: str
    timezone: str
    cost_model_reference: str
    symbol_specific_assumptions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = (
            "symbol",
            "timeframe",
            "dataset_id",
            "dataset_checksum",
            "source",
            "coverage_start",
            "coverage_end",
            "timezone",
            "cost_model_reference",
        )
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise ProvenanceSpecError("dataset provenance record is incomplete", missing_fields=missing)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DatasetProvenanceRecord":
        return DatasetProvenanceRecord(**d)


@dataclass(frozen=True)
class StrategyCandidateSpec:
    """Complete, immutable trading-rule specification for one candidate.

    Every field ML-001-STRATEGY-FACTORY-SPEC.md §2 requires ("ENTRY, EXIT, FEATURES,
    TIMEFRAME, DIRECTION, STOP_LOSS, TAKE_PROFIT, MAX_HOLD,
    POSITION_SIZING, TRANSACTION_COST_MODEL") is present and required —
    there is no optional/default trading rule a candidate can omit.
    """

    entry_rule: str
    exit_rule: str
    features: tuple
    timeframe: str
    direction: str
    stop_loss: str
    take_profit: str
    max_hold_bars: int
    position_sizing: str
    transaction_cost_model: str

    def __post_init__(self) -> None:
        required_str_fields = (
            "entry_rule",
            "exit_rule",
            "timeframe",
            "direction",
            "stop_loss",
            "take_profit",
            "position_sizing",
            "transaction_cost_model",
        )
        missing = [f for f in required_str_fields if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if not self.features:
            missing.append("features")
        if self.max_hold_bars is None or self.max_hold_bars <= 0:
            missing.append("max_hold_bars")
        if missing:
            raise CandidateSpecError("candidate specification is incomplete", missing_fields=missing)

    def spec_checksum(self) -> str:
        """Deterministic checksum of this spec's content (for dedup/audit)."""
        import hashlib
        import json

        data = asdict(self)
        data["features"] = list(self.features)
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class StrategyCandidate:
    """One Strategy Factory candidate: immutable identity + versioned spec + lifecycle state.

    ``candidate_id`` and ``version`` together are the immutable identity
    (ML-001-STRATEGY-FACTORY-SPEC.md §5: "STRAT-001 v1 -> FAILED; STRAT-001 v2 -> NEW
    CANDIDATE. Never mutate v1 into v2."). ``state`` is the only field this
    module expects to change in place after registration; every other
    identity/spec field is fixed at construction. Spec mutation after
    ``state`` reaches FROZEN or later is rejected by
    ``StrategyRegistry.transition`` — see ``core/factory/registry.py``.
    """

    candidate_id: str
    version: int
    spec: StrategyCandidateSpec
    state: CandidateState
    creation_timestamp: str
    generator_id: str
    generator_parameters: Dict[str, Any]
    code_version: str
    dataset_id: str
    parent_candidate_id: Optional[str] = None
    history: list = field(default_factory=list)
    #: Per-instrument dataset provenance (ML-001-STRATEGY-FACTORY-SPEC.md
    #: §12). Optional/defaulted to () for backward compatibility with
    #: candidates registered before this field existed (e.g. STRAT-000001,
    #: whose real per-symbol provenance instead lives in
    #: reports/ml_r2_real_data/WALKFORWARD_*.json) -- absence here does not
    #: mean the provenance doesn't exist, only that it predates this field.
    instrument_universe: Tuple[DatasetProvenanceRecord, ...] = ()
    #: Links this candidate back to the HypothesisRecord (if any) it was
    #: generated from (core/factory/hypothesis.py). None for candidates
    #: generated directly from a pre-specified hypothesis document (e.g.
    #: ML-001-R2-CLEAN-REBUILD-SPEC.md) rather than an ingested external
    #: source claim.
    hypothesis_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["spec"] = asdict(self.spec)
        d["spec"]["features"] = list(self.spec.features)
        d["state"] = self.state.value
        d["instrument_universe"] = [p.to_dict() for p in self.instrument_universe]
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StrategyCandidate":
        spec_d = dict(d["spec"])
        spec_d["features"] = tuple(spec_d["features"])
        spec = StrategyCandidateSpec(**spec_d)
        return StrategyCandidate(
            candidate_id=d["candidate_id"],
            version=d["version"],
            spec=spec,
            state=CandidateState(d["state"]),
            creation_timestamp=d["creation_timestamp"],
            generator_id=d["generator_id"],
            generator_parameters=d["generator_parameters"],
            code_version=d["code_version"],
            dataset_id=d["dataset_id"],
            parent_candidate_id=d.get("parent_candidate_id"),
            history=list(d.get("history", [])),
            instrument_universe=tuple(
                DatasetProvenanceRecord.from_dict(p) for p in d.get("instrument_universe", [])
            ),
            hypothesis_id=d.get("hypothesis_id"),
        )

    def new_version_with(self, **spec_overrides: Any) -> "StrategyCandidateSpec":
        """Return a NEW spec with the given fields changed — never mutates ``self.spec``.

        Callers must register the result under a brand-new ``candidate_id``
        (see ``StrategyRegistry.derive_new_version``); this method alone
        does not create a registry entry, precisely so a spec change can
        never accidentally reuse the old candidate's identity.
        """
        return replace(self.spec, **spec_overrides)
