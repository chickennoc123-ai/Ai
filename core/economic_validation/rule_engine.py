"""Generation 4, Phase 8 — Deterministic rule execution (RULE-R4-001).

STRAT-000002 has **no model**. Its frozen specification is a
deterministic rule over two features:

    entry: rsi_14 crosses back above 30 from below
    exit:  stop-loss 1.5xATR, take-profit 2.0xATR, or 12 bars elapsed
    direction: long only

There is therefore nothing to train, no hyperparameters, no seed, and no
learned artifact. This module says so explicitly rather than manufacturing
a model the candidate never specified, because the Generation 4 contract's
"model training" phase is conditional on the frozen specification
("*or the exact model specified by STRAT-000002*") and inventing one would
itself be a post-freeze specification change.

What "training" is replaced by is signal generation, which is a pure
function of the features and the frozen thresholds. It is trivially
deterministic and reproducible, and this module records provenance for it
in exactly the same shape a training run would, so downstream evidence
consumers do not need to special-case a rule-based candidate.

**Signal parsing is exact, not fuzzy.** ``parse_entry_rule`` recognises
one specific rule grammar and raises on anything else. A rule string the
parser does not understand must never fall through to a default
interpretation — that would let a specification and its execution silently
disagree, which is the exact failure mode this project's freeze machinery
exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from utils.exceptions import EAFactoryError

RULE_ENGINE_ID = "RULE-R4-001"

LONG = 1
SHORT = -1


class RuleSpecificationError(EAFactoryError):
    """Raised when a frozen rule string cannot be parsed unambiguously."""


@dataclass(frozen=True)
class CrossoverRule:
    """``feature`` crosses ``threshold`` in ``crossing_direction``.

    ``crossing_direction`` is ``"up"`` (was strictly below at t-1, is at
    or above at t) or ``"down"`` (was strictly above at t-1, is at or
    below at t). The strict/non-strict asymmetry is deliberate and
    matches the plain meaning of "crosses back above 30 from below": a
    bar that merely *touches* 30 from below has crossed; a bar already at
    30 that stays at 30 has not.
    """

    feature: str
    threshold: float
    crossing_direction: str
    direction: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


#: The ONLY entry-rule grammar this engine understands, expressed once.
#: STRAT-000002's rule string ends with the canonical clause
#: "rsi_14 crosses back above 30 from below"; the prose preamble that
#: precedes it in the registry record (the source's own wording, retained
#: verbatim for lineage) is not an additional condition and is not
#: interpreted -- see ``parse_entry_rule``.
_CROSS_UP_PATTERN = re.compile(
    r"(?P<feature>[a-z_0-9]+)\s+crosses\s+(?:back\s+)?above\s+(?P<threshold>[0-9]+(?:\.[0-9]+)?)\s+from\s+below",
    re.IGNORECASE,
)
_CROSS_DOWN_PATTERN = re.compile(
    r"(?P<feature>[a-z_0-9]+)\s+crosses\s+(?:back\s+)?below\s+(?P<threshold>[0-9]+(?:\.[0-9]+)?)\s+from\s+above",
    re.IGNORECASE,
)


def parse_entry_rule(entry_rule: str, direction: str) -> CrossoverRule:
    """Parse a frozen ``entry_rule`` string into an executable rule.

    Raises ``RuleSpecificationError`` if the string does not match exactly
    one supported pattern, or if it matches a pattern inconsistent with
    the candidate's declared ``direction``.
    """
    if not entry_rule or not entry_rule.strip():
        raise RuleSpecificationError("entry_rule is empty")

    up = _CROSS_UP_PATTERN.findall(entry_rule)
    down = _CROSS_DOWN_PATTERN.findall(entry_rule)

    # The registry's entry_rule for STRAT-000002 repeats the same canonical
    # clause twice (once inside the retained source prose, once as the
    # formalized condition). Repetition of an IDENTICAL clause is not
    # ambiguity; two DIFFERENT clauses would be, and is rejected.
    distinct_up = {(f.lower(), t) for f, t in up}
    distinct_down = {(f.lower(), t) for f, t in down}

    if len(distinct_up) + len(distinct_down) == 0:
        raise RuleSpecificationError(
            "entry_rule does not match any grammar RULE-R4-001 understands; refusing to guess",
            entry_rule=entry_rule,
        )
    if len(distinct_up) + len(distinct_down) > 1:
        raise RuleSpecificationError(
            "entry_rule contains more than one distinct crossover condition; RULE-R4-001 "
            "executes exactly one and will not silently pick",
            entry_rule=entry_rule,
            up=sorted(distinct_up),
            down=sorted(distinct_down),
        )

    if distinct_up:
        feature, threshold = next(iter(distinct_up))
        crossing = "up"
        implied_direction = LONG
    else:
        feature, threshold = next(iter(distinct_down))
        crossing = "down"
        implied_direction = SHORT

    declared = direction.strip().lower()
    if declared == "long_only" and implied_direction != LONG:
        raise RuleSpecificationError(
            "entry_rule implies a short entry but the candidate declares long_only",
            entry_rule=entry_rule,
            direction=direction,
        )
    if declared == "short_only" and implied_direction != SHORT:
        raise RuleSpecificationError(
            "entry_rule implies a long entry but the candidate declares short_only",
            entry_rule=entry_rule,
            direction=direction,
        )
    if declared not in ("long_only", "short_only", "long_and_short"):
        raise RuleSpecificationError("unknown direction", direction=direction)

    return CrossoverRule(
        feature=feature,
        threshold=float(threshold),
        crossing_direction=crossing,
        direction=implied_direction,
    )


def parse_atr_multiple(text: str) -> float:
    """Parse ``"1.5xATR"`` -> ``1.5``. Raises on anything else."""
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[xX]\s*ATR\s*", text or "")
    if not m:
        raise RuleSpecificationError(
            "stop_loss/take_profit must be expressed as '<multiple>xATR'; refusing to guess", value=text
        )
    return float(m.group(1))


def generate_signals(features: pd.DataFrame, rule: CrossoverRule) -> pd.Series:
    """Return an integer signal series aligned to ``features.index``.

    ``+1`` (or ``-1``) on every bar where the crossover completes at that
    bar's close; ``0`` elsewhere. A bar whose feature value at ``t`` or
    ``t-1`` is undefined produces ``0`` -- an unknown condition is never
    treated as a satisfied one.
    """
    if rule.feature not in features.columns:
        raise RuleSpecificationError(
            "rule references a feature not present in the feature matrix",
            feature=rule.feature,
            available=list(features.columns),
        )
    series = features[rule.feature]
    prev = series.shift(1)

    if rule.crossing_direction == "up":
        fired = (prev < rule.threshold) & (series >= rule.threshold)
    elif rule.crossing_direction == "down":
        fired = (prev > rule.threshold) & (series <= rule.threshold)
    else:  # pragma: no cover - constructor restricts the value
        raise RuleSpecificationError("unknown crossing_direction", crossing_direction=rule.crossing_direction)

    defined = series.notna() & prev.notna()
    return pd.Series(np.where(fired & defined, rule.direction, 0), index=features.index, dtype="int64")


@dataclass(frozen=True)
class SignalGenerationProvenance:
    """Provenance for one signal-generation event.

    Deliberately mirrors the shape of a training-provenance record so
    downstream evidence consumers treat rule-based and model-based
    candidates uniformly.
    """

    rule_engine_id: str
    candidate_id: str
    validation_run_id: str
    partition_name: str
    rule: Dict[str, Any]
    feature_version: str
    dataset_checksum: str
    n_bars: int
    n_signals: int
    first_signal: Optional[str]
    last_signal: Optional[str]
    signal_checksum: str
    seed: Optional[int]
    seed_policy: str
    deterministic: bool
    code_version: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def signal_checksum(signals: pd.Series) -> str:
    """Checksum over the exact (timestamp, signal) sequence."""
    payload = [[str(ts), int(v)] for ts, v in signals.items() if v != 0]
    return hashlib.sha256(json.dumps(payload, sort_keys=False).encode()).hexdigest()
