"""The idea families the machine is allowed to search in (roadmap Phase 3).

A family is a *mechanism class*, not a strategy template. It answers "what kind
of economic reason could make this work?" — which is why every family carries a
``mechanism_question`` the generator must answer before an idea may be minted,
and a ``typical_horizon`` used by the economic pre-filter to sanity-check that
an idea's holding period matches the mechanism it claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Family:
    name: str
    mechanism_question: str
    typical_horizon: Tuple[str, ...]   # allowed holding-period classes
    why_edge_could_persist: str


#: Holding-period classes used across the machine.
HORIZONS: Tuple[str, ...] = ("INTRABAR", "INTRADAY", "MULTI_DAY", "WEEKS", "MONTHS")


_FAMILY_LIST = (
    Family(
        "MACRO",
        "Which macro state variable changes the distribution of returns, and why do prices not already reflect it?",
        ("MULTI_DAY", "WEEKS", "MONTHS"),
        "Macro risk premia compensate holders for bearing states investors dislike; the compensation survives being known.",
    ),
    Family(
        "EVENT",
        "Which scheduled or unscheduled event releases information, and who is slow to price it?",
        ("INTRADAY", "MULTI_DAY"),
        "Attention and mandate constraints delay repricing around discrete releases.",
    ),
    Family(
        "SEASONALITY",
        "Which recurring calendar constraint forces a flow, and who must transact regardless of price?",
        ("MULTI_DAY", "WEEKS"),
        "Calendar-bound institutional flows (rebalances, settlements, fiscal dates) are price-insensitive.",
    ),
    Family(
        "MOMENTUM",
        "Which underreaction or flow-continuation mechanism keeps pushing price in one direction?",
        ("MULTI_DAY", "WEEKS", "MONTHS"),
        "Slow diffusion of information and trend-following capital create autocorrelated flow.",
    ),
    Family(
        "MEAN_REVERSION",
        "Which liquidity provider is being paid to absorb an imbalance, and over what horizon do they unwind?",
        ("INTRABAR", "INTRADAY", "MULTI_DAY"),
        "Inventory risk must be compensated; the compensation reverts once inventory clears.",
    ),
    Family(
        "VOLATILITY",
        "Which volatility risk premium or volatility-of-volatility effect is being harvested, and who pays it?",
        ("INTRADAY", "MULTI_DAY", "WEEKS"),
        "Hedgers pay a persistent premium to transfer variance risk.",
    ),
    Family(
        "MARKET_STRUCTURE",
        "Which rule, venue, or session boundary mechanically shapes the order flow?",
        ("INTRABAR", "INTRADAY"),
        "Structural rules change slowly and bind participants regardless of their views.",
    ),
    Family(
        "CROSS_ASSET",
        "Which economic linkage makes one asset informative about another, and why is the transmission delayed?",
        ("INTRADAY", "MULTI_DAY", "WEEKS"),
        "Segmented participation means information reaches markets at different speeds.",
    ),
    Family(
        "POSITIONING",
        "Whose position is crowded, what forces them out, and what does the unwind look like?",
        ("MULTI_DAY", "WEEKS"),
        "Crowded positioning creates forced, price-insensitive unwinds under stress.",
    ),
    Family(
        "MICROSTRUCTURE",
        "Which order-book mechanic produces the effect, and does it survive realistic execution?",
        ("INTRABAR", "INTRADAY"),
        "Queue position, tick size, and quote-update mechanics are stable features of a venue.",
    ),
    Family(
        "LIQUIDITY",
        "When does liquidity provision become scarce, and who is compensated for supplying it then?",
        ("INTRADAY", "MULTI_DAY"),
        "Liquidity provision earns a premium precisely when capital is unwilling to supply it.",
    ),
    Family(
        "REGIME",
        "Which observable state variable separates two genuinely different data-generating regimes?",
        ("MULTI_DAY", "WEEKS", "MONTHS"),
        "Regimes persist because the underlying policy or volatility state persists.",
    ),
    Family(
        "CARRY",
        "What is the yield/roll being earned, and what risk is the carry compensating?",
        ("WEEKS", "MONTHS"),
        "Carry is compensation for bearing a real risk, not a free lunch, so it survives publication.",
    ),
    Family(
        "TERM_STRUCTURE",
        "Which part of the curve is being traded, and who has a maturity-segmented mandate?",
        ("MULTI_DAY", "WEEKS", "MONTHS"),
        "Preferred-habitat investors are constrained to segments of the curve.",
    ),
    Family(
        "CALENDAR",
        "Which fixed date or time-of-day boundary changes participant behaviour?",
        ("INTRABAR", "INTRADAY", "MULTI_DAY"),
        "Fixings, session opens, and month-ends impose deadlines that are indifferent to price.",
    ),
)

FAMILIES: Dict[str, Family] = {f.name: f for f in _FAMILY_LIST}

FAMILY_NAMES = tuple(sorted(FAMILIES))


def get_family(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError:
        raise KeyError(f"unknown idea family {name!r}; known: {', '.join(FAMILY_NAMES)}") from None


def horizon_is_plausible(family: str, holding_period: str) -> bool:
    """Does ``holding_period`` match the mechanism class ``family`` claims?

    A microstructure mechanism that claims a three-month holding period is
    almost certainly not the mechanism actually being described; the economic
    pre-filter uses this to catch mechanism/horizon mismatches early.
    """
    fam = get_family(family)
    return holding_period in fam.typical_horizon
