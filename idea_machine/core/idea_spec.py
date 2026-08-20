"""IdeaSpec — the immutable Phase 0 contract.

An IdeaSpec is a *falsifiable proposal*, not a result. It carries every field
the roadmap lists as mandatory, and it deliberately carries no place to put a
backtest number. That absence is enforced twice:

1. Structurally — the dataclass is frozen and has no performance field.
2. Semantically — :func:`assert_no_result_fields` walks every nested mapping
   and rejects keys that name realised performance (``sharpe``, ``pnl``,
   ``win_rate``, ``max_drawdown``, ...). Without this, a caller could smuggle a
   backtest result through the free-form ``entry`` or ``required_data`` dicts
   and the ranking stage would start ranking on performance, which Phase 8
   forbids.

``expected_effect`` is not a smuggled result: it is the *prediction the idea
makes before any test*, and refusing to state it would make the idea
unfalsifiable. It is a forecast, and the falsification condition says what
would prove it wrong.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple

from idea_machine.core.errors import SpecValidationError
from idea_machine.core.families import FAMILY_NAMES, HORIZONS, get_family
from idea_machine.core.ids import canonical, content_hash, mint_id
from idea_machine.core.provenance import Provenance

#: Key fragments that name a *realised* performance measurement. An IdeaSpec
#: that contains one of these has stopped being a proposal.
BANNED_RESULT_KEYS: Tuple[str, ...] = (
    "sharpe",
    "sortino",
    "calmar",
    "pnl",
    "profit_factor",
    "net_profit",
    "gross_profit",
    "win_rate",
    "winrate",
    "hit_rate",
    "drawdown",
    "equity_curve",
    "equity",
    "backtest",
    "cagr",
    "total_return",
    "annualised_return",
    "annualized_return",
    "total_trades",
    "realized_",
    "realised_",
    "t_stat",
    "tstat",
    "p_value",
    "pvalue",
    "oos_",
    "holdout",
    "wfa_",
)

EFFECT_UNITS = frozenset({"PRICE", "BPS", "PCT", "SIGMA", "TICKS"})
DIRECTIONS = frozenset({"LONG", "SHORT", "BOTH", "SPREAD"})


def assert_no_result_fields(payload: Any, *, where: str = "idea") -> None:
    """Recursively reject anything that looks like a realised backtest result."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            low = str(key).strip().lower()
            for banned in BANNED_RESULT_KEYS:
                if banned in low:
                    raise SpecValidationError(
                        "an IdeaSpec may not carry a backtest result -- ideas are proposals, "
                        "and results belong to the Strategy Factory",
                        where=where,
                        offending_key=str(key),
                        matched=banned,
                    )
            assert_no_result_fields(value, where=f"{where}.{key}")
    elif isinstance(payload, (list, tuple)):
        for i, item in enumerate(payload):
            assert_no_result_fields(item, where=f"{where}[{i}]")


@dataclass(frozen=True)
class ExpectedEffect:
    """The *prediction* the idea makes, before anything is tested."""

    magnitude: float          # absolute, per-trade, in ``unit``
    unit: str
    direction: str
    horizon_bars: int
    basis: str                # how the number was arrived at, in words

    def __post_init__(self) -> None:
        if self.unit not in EFFECT_UNITS:
            raise SpecValidationError("unknown effect unit", unit=self.unit, allowed=sorted(EFFECT_UNITS))
        if self.direction not in DIRECTIONS:
            raise SpecValidationError("unknown direction", direction=self.direction)
        if not isinstance(self.magnitude, (int, float)) or self.magnitude <= 0:
            raise SpecValidationError("expected effect magnitude must be positive", magnitude=self.magnitude)
        if int(self.horizon_bars) < 1:
            raise SpecValidationError("horizon_bars must be >= 1", horizon_bars=self.horizon_bars)
        if not str(self.basis).strip():
            raise SpecValidationError(
                "expected_effect.basis is required -- an unexplained magnitude is a guess "
                "dressed as a forecast"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ExpectedEffect":
        return ExpectedEffect(
            magnitude=float(d["magnitude"]),
            unit=str(d["unit"]),
            direction=str(d["direction"]),
            horizon_bars=int(d["horizon_bars"]),
            basis=str(d["basis"]),
        )


@dataclass(frozen=True)
class IdeaSpec:
    """An immutable, falsifiable research proposal.

    ``idea_id`` is content-addressed: it is derived from the semantic fields
    only, so the same idea proposed twice — in two different cycles, from two
    different sources — collapses to one id and is caught by deduplication.
    """

    family: str
    hypothesis: str
    mechanism: str
    instruments: Tuple[str, ...]
    timeframe: str
    entry: Mapping[str, Any]
    exit: Mapping[str, Any]
    holding_period: str
    required_data: Tuple[str, ...]
    economic_rationale: str
    expected_effect: ExpectedEffect
    falsification_condition: str
    provenance: Provenance
    created_at: str = ""          # NOT part of the identity hash
    idea_id: str = field(default="", compare=False)

    # ------------------------------------------------------------ validation

    def __post_init__(self) -> None:
        if self.family not in FAMILY_NAMES:
            raise SpecValidationError(
                "unknown idea family", family=self.family, allowed=list(FAMILY_NAMES)
            )
        if self.holding_period not in HORIZONS:
            raise SpecValidationError(
                "unknown holding_period", holding_period=self.holding_period, allowed=list(HORIZONS)
            )

        for name in ("hypothesis", "mechanism", "economic_rationale", "falsification_condition", "timeframe"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise SpecValidationError(f"IdeaSpec.{name} is required")

        # Phase 3's hard gate: no mechanism, no queue entry. A one-word
        # "mechanism" is the same thing as no mechanism, so require substance.
        if len(str(self.mechanism).split()) < 5:
            raise SpecValidationError(
                "IdeaSpec.mechanism must actually explain WHY an edge could exist; "
                f"{get_family(self.family).mechanism_question}",
                family=self.family,
                mechanism=self.mechanism,
            )
        if len(str(self.falsification_condition).split()) < 4:
            raise SpecValidationError(
                "IdeaSpec.falsification_condition must state what observation would "
                "prove this idea wrong -- an unfalsifiable idea is not researchable"
            )

        if not self.instruments:
            raise SpecValidationError("IdeaSpec.instruments must name at least one instrument")
        if not self.required_data:
            raise SpecValidationError("IdeaSpec.required_data must name the data the test needs")
        if not isinstance(self.entry, Mapping) or not self.entry:
            raise SpecValidationError("IdeaSpec.entry must be a non-empty rule mapping")
        if not isinstance(self.exit, Mapping) or not self.exit:
            raise SpecValidationError("IdeaSpec.exit must be a non-empty rule mapping")

        assert_no_result_fields(
            {
                "entry": self.entry,
                "exit": self.exit,
                "required_data": list(self.required_data),
                "hypothesis": self.hypothesis,
            },
            where="idea",
        )

        object.__setattr__(self, "instruments", tuple(self.instruments))
        object.__setattr__(self, "required_data", tuple(self.required_data))
        object.__setattr__(self, "entry", dict(self.entry))
        object.__setattr__(self, "exit", dict(self.exit))
        if not self.idea_id:
            object.__setattr__(self, "idea_id", mint_id("IDEA", self.identity_payload()))

    # -------------------------------------------------------------- identity

    def identity_payload(self) -> Dict[str, Any]:
        """The semantic content that defines *which* idea this is.

        Excludes ``created_at``, ``idea_id`` and provenance: the same idea
        arrived at from two different papers is still the same idea, and must
        deduplicate to one research slot.
        """
        return canonical(
            {
                "family": self.family,
                "hypothesis": self.hypothesis.strip().lower(),
                "mechanism": self.mechanism.strip().lower(),
                "instruments": sorted(self.instruments),
                "timeframe": self.timeframe,
                "entry": self.entry,
                "exit": self.exit,
                "holding_period": self.holding_period,
                "required_data": sorted(self.required_data),
                "expected_effect": self.expected_effect.to_dict(),
            }
        )

    def content_checksum(self) -> str:
        return content_hash(self.identity_payload())

    def mechanism_signature(self) -> str:
        """A coarser fingerprint used for near-duplicate detection."""
        return content_hash(
            {"family": self.family, "mechanism": self.mechanism.strip().lower(), "horizon": self.holding_period}
        )

    # ---------------------------------------------------------- serialisation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "family": self.family,
            "hypothesis": self.hypothesis,
            "mechanism": self.mechanism,
            "instruments": list(self.instruments),
            "timeframe": self.timeframe,
            "entry": dict(self.entry),
            "exit": dict(self.exit),
            "holding_period": self.holding_period,
            "required_data": list(self.required_data),
            "economic_rationale": self.economic_rationale,
            "expected_effect": self.expected_effect.to_dict(),
            "falsification_condition": self.falsification_condition,
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
            "content_checksum": self.content_checksum(),
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "IdeaSpec":
        return IdeaSpec(
            family=d["family"],
            hypothesis=d["hypothesis"],
            mechanism=d["mechanism"],
            instruments=tuple(d["instruments"]),
            timeframe=d["timeframe"],
            entry=dict(d["entry"]),
            exit=dict(d["exit"]),
            holding_period=d["holding_period"],
            required_data=tuple(d["required_data"]),
            economic_rationale=d["economic_rationale"],
            expected_effect=ExpectedEffect.from_dict(d["expected_effect"]),
            falsification_condition=d["falsification_condition"],
            provenance=Provenance.from_dict(d["provenance"]),
            created_at=d.get("created_at", ""),
            idea_id=d.get("idea_id", ""),
        )


def deduplicate(ideas: Sequence[IdeaSpec]) -> Tuple[IdeaSpec, ...]:
    """Collapse exact-identity duplicates, preserving first-seen order."""
    seen: Dict[str, IdeaSpec] = {}
    for idea in ideas:
        seen.setdefault(idea.idea_id, idea)
    return tuple(seen.values())
