"""Mechanism templates — how a concept becomes a falsifiable proposal.

Phase 3's hard rule is that every hypothesis must answer *"why could this edge
exist?"*. A template is the machine-readable form of one answer: it pairs a
family with a mechanism sentence, the trading rule shape that mechanism
implies, and the observation that would falsify it.

Templates are data, not code, so adding a new way of reasoning does not mean
touching the generator. Each template declares which concept *roles* it needs
(``driver``, ``target``, ``conditioner``); the generator fills those roles from
the knowledge graph and refuses to emit anything whose roles are unfilled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from idea_machine.knowledge.taxonomy import (
    CALENDAR_WINDOW,
    EVENT_RELEASE,
    POSITIONING_MEASURE,
    RATE_SERIES,
    SESSION_WINDOW,
    STATE_VARIABLE,
    TRADABLE_ASSET,
    VOL_MEASURE,
)


@dataclass(frozen=True)
class MechanismTemplate:
    template_id: str
    family: str
    roles: Tuple[str, ...]                 # required concept roles
    #: role -> the concept kinds that may fill it. A role with no entry here
    #: cannot be filled at all, which is deliberate: a template that forgets to
    #: constrain a role should emit nothing rather than emit nonsense.
    role_kinds: Mapping[str, Tuple[str, ...]]
    holding_period: str
    timeframe: str
    mechanism: str                         # format string over roles
    hypothesis: str
    economic_rationale: str
    falsification: str
    entry: Mapping[str, Any] = field(default_factory=dict)
    exit: Mapping[str, Any] = field(default_factory=dict)
    required_data: Tuple[str, ...] = ()
    #: rough prior on effect size, in the unit below; the pre-filter checks it
    #: against real costs, and the Factory is what actually measures it.
    prior_effect: float = 0.0
    effect_unit: str = "PRICE"
    direction: str = "BOTH"
    effect_basis: str = ""

    def render(self, bindings: Mapping[str, str]) -> Dict[str, str]:
        """Fill the template's text fields from ``bindings``."""
        missing = [r for r in self.roles if not bindings.get(r)]
        if missing:
            raise KeyError(f"template {self.template_id} is missing roles: {missing}")
        return {
            "mechanism": self.mechanism.format(**bindings),
            "hypothesis": self.hypothesis.format(**bindings),
            "economic_rationale": self.economic_rationale.format(**bindings),
            "falsification": self.falsification.format(**bindings),
        }


TEMPLATES: Tuple[MechanismTemplate, ...] = (
    MechanismTemplate(
        template_id="EVENT_UNDERREACTION",
        family="EVENT",
        roles=("driver", "target"),
        role_kinds={"driver": (EVENT_RELEASE,), "target": (TRADABLE_ASSET, RATE_SERIES)},
        holding_period="INTRADAY",
        timeframe="M15",
        mechanism=(
            "Around a {driver} release, dealers widen quotes and reduce inventory risk, so the "
            "information in the release is absorbed into {target} over the following bars rather "
            "than instantaneously; the residual repricing is the tradable component."
        ),
        hypothesis="{target} continues to drift in the direction of a large {driver} surprise after the release bar.",
        economic_rationale=(
            "Attention and risk-limit constraints make liquidity providers price discrete releases "
            "conservatively, so full repricing is delayed rather than immediate."
        ),
        falsification=(
            "No drift beyond round-trip cost in {target} in the bars after large {driver} surprises, "
            "or drift present but indistinguishable from the unconditional distribution."
        ),
        entry={"trigger": "surprise_z", "operator": ">=", "threshold": 1.5, "align_to": "release_bar_close"},
        exit={"rule": "time_stop", "bars": 4, "hard_stop_atr": 2.0},
        required_data=("event_calendar_actual_consensus", "target_ohlcv_m15"),
        prior_effect=0.00030,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from published event-study magnitudes; measured by the Factory, not here",
    ),
    MechanismTemplate(
        template_id="CROSS_ASSET_LEAD_LAG",
        family="CROSS_ASSET",
        roles=("driver", "target"),
        role_kinds={"driver": (TRADABLE_ASSET, RATE_SERIES), "target": (TRADABLE_ASSET,)},
        holding_period="INTRADAY",
        timeframe="H1",
        mechanism=(
            "{driver} and {target} share an economic driver but are traded by partly different "
            "participants; when the shared driver moves, the market with faster participation "
            "reprices first and the slower one follows within the transmission lag."
        ),
        hypothesis="Moves in {driver} lead same-direction moves in {target} at a one-to-several bar lag.",
        economic_rationale=(
            "Participation is segmented by mandate and venue, so information does not arrive in all "
            "markets simultaneously."
        ),
        falsification=(
            "Lagged {driver} returns carry no incremental information about {target} returns once "
            "contemporaneous returns are controlled for."
        ),
        entry={"trigger": "driver_return_z", "operator": ">=", "threshold": 2.0, "lag_bars": 1},
        exit={"rule": "time_stop", "bars": 3},
        required_data=("driver_ohlcv_h1", "target_ohlcv_h1"),
        prior_effect=0.00025,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from cross-market transmission studies; the Factory measures the real value",
    ),
    MechanismTemplate(
        template_id="CALENDAR_FORCED_FLOW",
        family="SEASONALITY",
        roles=("driver", "target"),
        role_kinds={"driver": (CALENDAR_WINDOW,), "target": (TRADABLE_ASSET,)},
        holding_period="MULTI_DAY",
        timeframe="D1",
        mechanism=(
            "{driver} imposes a deadline on institutions that must transact in {target} regardless of "
            "price; the resulting flow is predictable in timing and direction, and its price impact "
            "reverses once the deadline passes."
        ),
        hypothesis="{target} shows a directional bias in the window around {driver}, reversing afterwards.",
        economic_rationale=(
            "Mandate-driven flows are price-insensitive, so their impact is a liquidity premium paid "
            "to whoever takes the other side."
        ),
        falsification=(
            "Returns in the {driver} window are statistically indistinguishable from returns outside it, "
            "after costs."
        ),
        entry={"trigger": "calendar_window", "window": "driver_specific", "side": "flow_direction"},
        exit={"rule": "window_close", "max_hold_days": 3},
        required_data=("target_ohlcv_d1", "calendar_definition"),
        prior_effect=0.00080,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from turn-of-month and rebalancing literature; the Factory measures it",
    ),
    MechanismTemplate(
        template_id="REGIME_CONDITIONED_EFFECT",
        family="REGIME",
        roles=("driver", "target", "conditioner"),
        role_kinds={"driver": (EVENT_RELEASE, TRADABLE_ASSET, RATE_SERIES), "target": (TRADABLE_ASSET,), "conditioner": (STATE_VARIABLE, VOL_MEASURE)},
        holding_period="MULTI_DAY",
        timeframe="H4",
        mechanism=(
            "The relationship between {driver} and {target} is not stationary: {conditioner} selects "
            "which data-generating regime is active, and the {driver}->{target} transmission is "
            "materially stronger in one regime because risk-bearing capacity differs between them."
        ),
        hypothesis="The {driver} effect on {target} is present only when {conditioner} is in its elevated state.",
        economic_rationale=(
            "Risk-bearing capacity, and therefore the compensation demanded for absorbing flow, varies "
            "with the state {conditioner} measures."
        ),
        falsification=(
            "The {driver}->{target} effect is the same size in both {conditioner} states, i.e. the "
            "interaction term adds nothing."
        ),
        entry={"trigger": "driver_signal", "gate": "conditioner_state == HIGH"},
        exit={"rule": "time_stop", "bars": 12},
        required_data=("driver_series", "target_ohlcv_h4", "conditioner_series"),
        prior_effect=0.00045,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from regime-conditional studies; conditioning shrinks sample, power checked later",
    ),
    MechanismTemplate(
        template_id="LIQUIDITY_PREMIUM_WINDOW",
        family="LIQUIDITY",
        roles=("driver", "target"),
        role_kinds={"driver": (SESSION_WINDOW, CALENDAR_WINDOW), "target": (TRADABLE_ASSET,)},
        holding_period="INTRADAY",
        timeframe="M30",
        mechanism=(
            "During {driver}, the set of willing liquidity providers in {target} shrinks, so the "
            "compensation demanded for absorbing an imbalance rises; supplying liquidity in that "
            "window earns the elevated premium, and the position is closed once normal provision returns."
        ),
        hypothesis="Fading short-term imbalances in {target} during {driver} earns more than doing so outside it.",
        economic_rationale=(
            "Liquidity provision is compensated precisely when capital is least willing to supply it."
        ),
        falsification=(
            "Imbalance-fading returns during {driver} do not exceed those outside the window after costs."
        ),
        entry={"trigger": "short_term_imbalance", "operator": "<=", "threshold": -1.5, "gate": "driver_window"},
        exit={"rule": "revert_or_time", "bars": 6},
        required_data=("target_ohlcv_m30", "session_definition"),
        prior_effect=0.00022,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from intraday liquidity-premium estimates; small by construction, cost-sensitive",
    ),
    MechanismTemplate(
        template_id="VOL_RISK_PREMIUM_HARVEST",
        family="VOLATILITY",
        roles=("driver", "target"),
        role_kinds={"driver": (VOL_MEASURE,), "target": (TRADABLE_ASSET,)},
        holding_period="MULTI_DAY",
        timeframe="D1",
        mechanism=(
            "Hedgers pay a persistent premium to transfer variance risk in {target}; when {driver} "
            "indicates that the premium is unusually wide, the compensation for bearing that risk is "
            "unusually large relative to the variance actually realised over the holding period."
        ),
        hypothesis="Short-variance exposure in {target} is better compensated when {driver} is elevated.",
        economic_rationale=(
            "The variance risk premium is compensation for a real, undiversifiable exposure, which is "
            "why publication has not eliminated it."
        ),
        falsification=(
            "Realised variance matches or exceeds the implied level conditional on elevated {driver}, "
            "leaving no premium after costs."
        ),
        entry={"trigger": "premium_z", "operator": ">=", "threshold": 1.0},
        exit={"rule": "time_stop", "bars": 5, "risk_stop": "variance_spike"},
        required_data=("implied_vol_series", "target_ohlcv_d1"),
        prior_effect=0.00100,
        effect_unit="PRICE",
        direction="SHORT",
        effect_basis="prior from variance-risk-premium literature; tail risk is the cost side",
    ),
    MechanismTemplate(
        template_id="POSITIONING_UNWIND",
        family="POSITIONING",
        roles=("driver", "target"),
        role_kinds={"driver": (POSITIONING_MEASURE,), "target": (TRADABLE_ASSET,)},
        holding_period="WEEKS",
        timeframe="D1",
        mechanism=(
            "When {driver} shows speculative positioning in {target} at an extreme, the marginal buyer "
            "is exhausted; an adverse move then forces price-insensitive liquidation, and the unwind "
            "overshoots because the forced sellers are not optimising on price."
        ),
        hypothesis="Extreme {driver} readings in {target} precede mean reversion over the following weeks.",
        economic_rationale=(
            "Crowded positions must be financed and risk-managed; stress converts them into forced flow."
        ),
        falsification=(
            "Extreme {driver} readings carry no information about subsequent {target} returns beyond "
            "what past returns already imply."
        ),
        entry={"trigger": "positioning_percentile", "operator": ">=", "threshold": 90},
        exit={"rule": "time_stop", "bars": 15},
        required_data=("positioning_report", "target_ohlcv_d1"),
        prior_effect=0.00150,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from COT-based studies; weekly data limits sample size, power checked later",
    ),
    MechanismTemplate(
        template_id="SESSION_STRUCTURE_EFFECT",
        family="MARKET_STRUCTURE",
        roles=("driver", "target"),
        role_kinds={"driver": (SESSION_WINDOW,), "target": (TRADABLE_ASSET,)},
        holding_period="INTRADAY",
        timeframe="M15",
        mechanism=(
            "{driver} is a structural boundary in the trading day: the participant mix in {target} "
            "changes discretely across it, so the order-flow process before and after the boundary "
            "is generated by different populations with different urgency."
        ),
        hypothesis="{target} return behaviour differs systematically across the {driver} boundary.",
        economic_rationale=(
            "Venue hours and regional participation are structural and change only slowly, so the "
            "effect is not competed away the way a pure statistical pattern would be."
        ),
        falsification=(
            "Return distributions on either side of {driver} are statistically indistinguishable."
        ),
        entry={"trigger": "session_boundary", "offset_bars": 1},
        exit={"rule": "session_close_or_time", "bars": 8},
        required_data=("target_ohlcv_m15", "session_definition"),
        prior_effect=0.00018,
        effect_unit="PRICE",
        direction="BOTH",
        effect_basis="prior from intraday session studies; near cost threshold by construction",
    ),
)

TEMPLATES_BY_ID = {t.template_id: t for t in TEMPLATES}


def templates_for_family(family: str) -> Tuple[MechanismTemplate, ...]:
    return tuple(t for t in TEMPLATES if t.family == family)
