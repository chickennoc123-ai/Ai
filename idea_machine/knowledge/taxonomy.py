"""Concept taxonomy — what *kind* of thing each concept is.

Without this, the generator will happily bind any concept into any role and
emit sentences like "gold shows a directional bias in the window around
post-announcement drift", which is not a hypothesis — it is a template with
words in the wrong slots.

Each concept is assigned a kind, and each mechanism template declares which
kinds may fill each of its roles. A binding whose kinds do not match is never
proposed, so nonsense combinations are impossible rather than merely unlikely.

Concepts labelled ``MECHANISM_LABEL`` (``MOMENTUM``, ``LEAD_LAG``, ...) name a
*behaviour*, not an observable variable. They are useful for retrieval and for
the failure map, but they can never be bound as a driver, target, or
conditioner: you cannot trade "momentum", you trade an instrument using a
momentum mechanism.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

EVENT_RELEASE = "EVENT_RELEASE"
EVENT_ATTRIBUTE = "EVENT_ATTRIBUTE"
CALENDAR_WINDOW = "CALENDAR_WINDOW"
SESSION_WINDOW = "SESSION_WINDOW"
TRADABLE_ASSET = "TRADABLE_ASSET"
RATE_SERIES = "RATE_SERIES"
STATE_VARIABLE = "STATE_VARIABLE"
VOL_MEASURE = "VOL_MEASURE"
FLOW_MEASURE = "FLOW_MEASURE"
POSITIONING_MEASURE = "POSITIONING_MEASURE"
MACRO_STATE = "MACRO_STATE"
MECHANISM_LABEL = "MECHANISM_LABEL"

KINDS: FrozenSet[str] = frozenset(
    {
        EVENT_RELEASE, EVENT_ATTRIBUTE, CALENDAR_WINDOW, SESSION_WINDOW,
        TRADABLE_ASSET, RATE_SERIES, STATE_VARIABLE, VOL_MEASURE,
        FLOW_MEASURE, POSITIONING_MEASURE, MACRO_STATE, MECHANISM_LABEL,
    }
)

CONCEPT_KINDS: Dict[str, str] = {
    # scheduled releases
    "NFP": EVENT_RELEASE,
    "CPI": EVENT_RELEASE,
    "FOMC": EVENT_RELEASE,
    "GDP": EVENT_RELEASE,
    "UNEMPLOYMENT": EVENT_RELEASE,
    # attributes OF an event, not events themselves
    "SURPRISE": EVENT_ATTRIBUTE,
    "ANNOUNCEMENT_DRIFT": EVENT_ATTRIBUTE,
    # recurring calendar structure
    "TURN_OF_MONTH": CALENDAR_WINDOW,
    "DAY_OF_WEEK": CALENDAR_WINDOW,
    "QUARTER_END": CALENDAR_WINDOW,
    "TIME_OF_DAY": CALENDAR_WINDOW,
    "FIXING": CALENDAR_WINDOW,
    "SESSION_BOUNDARY": SESSION_WINDOW,
    # things you can actually hold
    "USD": TRADABLE_ASSET,
    "GOLD": TRADABLE_ASSET,
    "EQUITIES": TRADABLE_ASSET,
    "OIL": TRADABLE_ASSET,
    "EURUSD": TRADABLE_ASSET,
    "GBPUSD": TRADABLE_ASSET,
    "XAUUSD": TRADABLE_ASSET,
    # rates
    "US10Y": RATE_SERIES,
    "YIELD_CURVE": RATE_SERIES,
    "RATE_DIFFERENTIAL": RATE_SERIES,
    # states and measures
    "VOLATILITY_REGIME": STATE_VARIABLE,
    "REALIZED_VOLATILITY": STATE_VARIABLE,
    "IMPLIED_VOLATILITY": VOL_MEASURE,
    "VARIANCE_RISK_PREMIUM": VOL_MEASURE,
    "ORDER_FLOW": FLOW_MEASURE,
    "LIQUIDITY_PROVISION": FLOW_MEASURE,
    "BID_ASK_SPREAD": FLOW_MEASURE,
    "POSITIONING_DATA": POSITIONING_MEASURE,
    "CENTRAL_BANK_POLICY": MACRO_STATE,
    # behaviours -- never bindable into a role
    "MOMENTUM": MECHANISM_LABEL,
    "MEAN_REVERSION": MECHANISM_LABEL,
    "LEAD_LAG": MECHANISM_LABEL,
    "CARRY_TRADE": MECHANISM_LABEL,
}

#: Kinds that can never fill a template role, whatever the template asks for.
UNBINDABLE_KINDS: FrozenSet[str] = frozenset({MECHANISM_LABEL, EVENT_ATTRIBUTE})


def kind_of(concept: str) -> str:
    """Kind of ``concept``; unknown concepts are treated as unbindable."""
    return CONCEPT_KINDS.get(concept.strip().upper(), MECHANISM_LABEL)


def is_bindable(concept: str) -> bool:
    return kind_of(concept) not in UNBINDABLE_KINDS


def concepts_of_kind(*kinds: str) -> Tuple[str, ...]:
    wanted = set(kinds)
    return tuple(sorted(c for c, k in CONCEPT_KINDS.items() if k in wanted))


def register_concept_kind(concept: str, kind: str) -> None:
    if kind not in KINDS:
        raise KeyError(f"unknown concept kind {kind!r}")
    CONCEPT_KINDS[concept.strip().upper()] = kind
