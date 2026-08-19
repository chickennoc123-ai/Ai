"""Strategy DNA / research fingerprint — Generation 3, Phase 11.

A deterministic, comparable identity for what a candidate strategy
actually *is* (market, timeframe, features, parameters, entry/exit,
regime, risk, holding, costs). Two uses, both non-punitive:

- ``fingerprint()``: exact content identity (any component change changes it).
- ``family_fingerprint()``: parameter-stripped identity, so RSI-10/14/20
  variants share one strategy family for clustering and multiple-testing
  accounting.
- ``similarity(a, b)``: transparent component-wise fraction in [0, 1].

**No auto-rejection**: nothing in this module rejects anything. Per the
Generation 3 contract, fingerprint similarity may inform clustering,
novelty, accounting, and compute prioritization; automatic rejection
would require an explicit governance rule that does not currently exist.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from core.factory.candidate import StrategyCandidateSpec
from core.factory.novelty_engine import normalize_text
from utils.exceptions import EAFactoryError

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: The DNA components, in comparison order. Kept as an explicit tuple so
#: similarity() is decomposable: a caller can see exactly which
#: components matched, not just an opaque score.
DNA_COMPONENTS: Tuple[str, ...] = (
    "market", "timeframe", "features", "feature_parameters", "entry", "exit",
    "regime", "risk", "holding_period", "cost_model",
)


class StrategyDNAError(EAFactoryError):
    pass


@dataclass(frozen=True)
class StrategyDNA:
    market: str
    timeframe: str
    features: Tuple[str, ...]
    feature_parameters: str  # canonical textual rendering (e.g. "rsi_period=14")
    entry: str
    exit: str
    regime: str
    risk: str  # stop-loss/position-sizing description
    holding_period: str
    cost_model: str

    def _canonical(self, strip_numbers: bool) -> str:
        parts = []
        for component in DNA_COMPONENTS:
            value = getattr(self, component)
            if isinstance(value, tuple):
                value = " ".join(sorted(value))
            text = normalize_text(str(value))
            if strip_numbers:
                text = _NUMBER_RE.sub("N", text)
            parts.append(f"{component}={text}")
        return "|".join(parts)

    def fingerprint(self) -> str:
        """Exact content identity — any component change changes it."""
        return hashlib.sha256(self._canonical(strip_numbers=False).encode()).hexdigest()

    def family_fingerprint(self) -> str:
        """Parameter-stripped identity — numeric parameter variants of the
        same structure share one family fingerprint."""
        return hashlib.sha256(self._canonical(strip_numbers=True).encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["features"] = list(self.features)
        return d


def similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    """Fraction of DNA components whose parameter-stripped canonical
    forms match — fully decomposable via ``component_matches``."""
    matches = component_matches(a, b)
    return sum(matches.values()) / len(DNA_COMPONENTS)


def component_matches(a: StrategyDNA, b: StrategyDNA) -> Dict[str, bool]:
    """Per-component comparison (parameter-stripped) — the decomposition
    behind ``similarity``, so a score is always explainable."""
    out: Dict[str, bool] = {}
    for component in DNA_COMPONENTS:
        va, vb = getattr(a, component), getattr(b, component)
        if isinstance(va, tuple):
            va, vb = " ".join(sorted(va)), " ".join(sorted(vb))
        na = _NUMBER_RE.sub("N", normalize_text(str(va)))
        nb = _NUMBER_RE.sub("N", normalize_text(str(vb)))
        out[component] = na == nb
    return out


def dna_from_candidate_spec(spec: StrategyCandidateSpec, *, market: str, feature_parameters: str = "") -> StrategyDNA:
    """Build the DNA for a real ``StrategyCandidateSpec``. ``market`` is
    caller-supplied because the spec itself is symbol-agnostic (symbol
    association lives on the candidate's instrument universe/dataset)."""
    return StrategyDNA(
        market=market,
        timeframe=spec.timeframe,
        features=tuple(spec.features),
        feature_parameters=feature_parameters or "UNSPECIFIED",
        entry=spec.entry_rule,
        exit=spec.exit_rule,
        regime="UNSPECIFIED",
        risk=f"sl={spec.stop_loss} sizing={spec.position_sizing}",
        holding_period=str(spec.max_hold_bars),
        cost_model=spec.transaction_cost_model,
    )
