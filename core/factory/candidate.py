"""Strategy Factory candidate specification and record.

Per the roadmap Section 6/20: every candidate has an immutable identifier
and a complete, versioned specification. Once a candidate is FROZEN
(``core.factory.state_machine.CandidateState.FROZEN``), its specification
becomes immutable — ``StrategyCandidateSpec`` is a frozen dataclass so this
is enforced at the type level, not by convention. Any change to entry,
exit, features, parameters, model, timeframe, or cost assumptions requires
constructing a *new* ``StrategyCandidate`` with a new ``candidate_id`` and
``parent_candidate_id`` set to the old one — never mutating the old record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Optional

from core.factory.state_machine import CandidateState
from utils.exceptions import EAFactoryError


class CandidateSpecError(EAFactoryError):
    """Raised when a candidate specification is incomplete or invalid."""


class FrozenCandidateMutationError(EAFactoryError):
    """Raised when code attempts to alter a FROZEN-or-later candidate's spec."""


@dataclass(frozen=True)
class StrategyCandidateSpec:
    """Complete, immutable trading-rule specification for one candidate.

    Every field the roadmap Section 6 requires ("ENTRY, EXIT, FEATURES,
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
    (roadmap Section 20: "STRAT-001 v1 -> FAILED; STRAT-001 v2 -> NEW
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

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["spec"] = asdict(self.spec)
        d["spec"]["features"] = list(self.spec.features)
        d["state"] = self.state.value
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
        )

    def new_version_with(self, **spec_overrides: Any) -> "StrategyCandidateSpec":
        """Return a NEW spec with the given fields changed — never mutates ``self.spec``.

        Callers must register the result under a brand-new ``candidate_id``
        (see ``StrategyRegistry.derive_new_version``); this method alone
        does not create a registry entry, precisely so a spec change can
        never accidentally reuse the old candidate's identity.
        """
        return replace(self.spec, **spec_overrides)
