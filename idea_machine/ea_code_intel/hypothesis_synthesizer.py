"""
Hypothesis Synthesizer: turn mined Strategy DNA + novelty verdicts into
falsifiable DerivedHypothesis objects, gated by data availability.

A DNA tag set alone is not a hypothesis -- "uses cross-asset relationships"
says nothing testable. This module's job is narrower and stricter than a
generic idea generator: it only emits a hypothesis when
  (a) the DNA suggests a mechanism structurally distinct from what this
      project has already tried (checked via novelty_engine, but ALSO
      cross-checked by hand against known candidates -- see the synthesis
      script's own comments for why "NOVEL" alone isn't trusted blindly),
  (b) every input the mechanism needs is data this project actually has
      (checked against discovery/observatory.py's real symbol list), and
  (c) the mechanism can be stated as one falsifiable prediction with a
      specific symbol, driver(s), and direction logic -- not a vague
      "combine multiple signals" gesture.

Every synthesized hypothesis starts at provenance DERIVED_HYPOTHESIS. It
earns DATA_SUPPORTED only by actually running through the real Factory gate
(discovery/*.py), which this module does not do itself.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


# Data this project actually has (cross-checked against discovery/cycle8_intraday.py
# and discovery/observatory.py -- NOT assumed).
AVAILABLE_FX_M1 = {"EURUSD", "GBPUSD", "XAUUSD"}
AVAILABLE_FX_H1_ONLY = {"USDJPY", "USDCHF"}
AVAILABLE_DRIVERS = {"WTICO", "SPX500", "US10Y"}
AVAILABLE_EVENT_TYPES = {"Non-Farm Employment Change", "CPI y/y"}


@dataclass
class DerivedHypothesis:
    hyp_id: str
    mechanism: str
    symbol: str
    drivers: List[str]
    event_types: List[str]
    direction_logic: str
    testable_prediction: str
    source_dna_ids: List[str]
    source_citation: str
    novelty_note: str
    data_availability_check: str
    provenance: str = "DERIVED_HYPOTHESIS"
    synthesized_at: str = ""

    def __post_init__(self):
        if not self.synthesized_at:
            self.synthesized_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return asdict(self)


def check_data_availability(symbol: str, drivers: List[str], event_types: List[str]) -> Optional[str]:
    """Returns None if fully data-available, else a BLOCKED_DATA reason string."""
    missing = []
    if symbol not in AVAILABLE_FX_M1 and symbol not in AVAILABLE_FX_H1_ONLY:
        missing.append(f"symbol {symbol} not in this project's FX data")
    for d in drivers:
        if d not in AVAILABLE_DRIVERS:
            missing.append(f"driver {d} not in this project's driver data")
    for e in event_types:
        if e not in AVAILABLE_EVENT_TYPES:
            missing.append(f"event type {e} not in this project's event calendar")
    if missing:
        return "BLOCKED_DATA: " + "; ".join(missing)
    return None


def synthesize_dual_driver_confirmation(dna_citations: Dict[str, str]) -> DerivedHypothesis:
    """
    The one hypothesis this cycle's mining actually supports as genuinely
    distinct from prior work: require TWO independent cross-asset drivers
    to agree, not one.

    Provenance of the idea itself:
      - geraked/metatrader5's COT1 strategy (MINED-0001) combines
        "Commitments of Traders and Super Trend indicator" -- i.e. TWO
        distinct signal sources gating one entry, not one.
      - The mined academic snippet (MINED-0005) states explicitly: "An
        equally weighted composite score of macro factors ... has been a
        highly significant predictor ... beyond short-term rates" --
        i.e. combining multiple macro-linked signals outperforms any one
        alone, in the cited research's own claim (unverified, source claim
        only -- this project cannot independently confirm the cited paper's
        result, only that it says this).

    Why this is distinct from what's already been tried:
      - Cycle 8/9's SC_SURPRISE_CONFIRMATION (6 frozen CAND-SC-* candidates)
        requires exactly ONE driver to confirm. This requires TWO,
        simultaneously, which is a strictly stronger (and strictly rarer)
        filter -- a different, testable claim, not a parameter retune of
        the same claim.
      - Cycle 11's HYP-IM-0001 also used one driver (US10Y) on GBPUSD.
      - USDJPY with both US10Y AND SPX500 as required co-confirming
        drivers has never been tested by this project in this form.

    Symbol/driver choice: restricted to USDJPY specifically because it is
    the ONLY symbol where this project's own code already establishes a
    validated base_dir convention for BOTH drivers independently
    (discovery/cycle8_intraday.py PAIRINGS: USDJPY/SPX500 = +1; the
    USDJPY/US10Y direction is not in that list, so it is stated here
    explicitly and separately, not silently assumed -- see direction_logic).
    """
    symbol = "USDJPY"
    drivers = ["US10Y", "SPX500"]
    event_types = ["Non-Farm Employment Change"]

    availability = check_data_availability(symbol, drivers, event_types)

    direction_logic = (
        "implied_from_surprise = SURPRISE_FX_DIR[USDJPY] * sign(surprise)  [validated: +1, from Cycle 8]\n"
        "expected_from_SPX500 = (+1) * sign(SPX500 impulse move)  [validated: Cycle 8 PAIRINGS, SPX up -> risk-on -> long USDJPY]\n"
        "expected_from_US10Y = (+1) * sign(US10Y impulse move)  [STATED HERE, not copied from an existing "
        "Cycle 8 pairing: US10Y price up = yield down; by the SAME carry-cost logic Cycle 8 used for "
        "EURUSD/GBPUSD (yield down -> USD carry less attractive -> USD sold), yield down should mean USD "
        "sold against JPY too -> USDJPY DOWN on US10Y price up -> base_dir = -1 for (USDJPY, US10Y). "
        "This is an explicit economic assumption, stated before any evaluation runs, not tuned after seeing "
        "a result.]\n"
        "TRADE iff expected_from_SPX500 == expected_from_US10Y == implied_from_surprise (all three agree); "
        "otherwise no trade."
    )

    return DerivedHypothesis(
        hyp_id="HYP-EACI-0001",
        mechanism="DUAL_DRIVER_CONFIRMATION: trade NFP-surprise-implied USDJPY direction only when "
                 "BOTH US10Y and SPX500 impulse moves independently confirm the same direction",
        symbol=symbol, drivers=drivers, event_types=event_types,
        direction_logic=direction_logic,
        testable_prediction="USDJPY trades taken only when both US10Y and SPX500 confirm the NFP-surprise "
                            "direction have positive net expectancy on validation data, net of cost",
        source_dna_ids=["MINED-0001", "MINED-0005"],
        source_citation="geraked/metatrader5 COT1 ('combines Commitments of Traders and Super Trend "
                        "indicator'); academic snippet on composite macro-factor scores outperforming "
                        "single factors (source claim, not independently verified)",
        novelty_note="NOVEL per novelty_engine.py (no refuted-family tag overlap); additionally, manually "
                    "checked against the 6 frozen SC_SURPRISE_CONFIRMATION candidates and Cycle 11's own "
                    "HYP-IM-0001 -- both use exactly one driver, this uses two required simultaneously, a "
                    "materially different (stricter) claim, not a retune",
        data_availability_check=availability or "AVAILABLE: USDJPY (H1), US10Y (M1), SPX500 (M1), NFP calendar",
    )
