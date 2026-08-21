"""RECOMBINE: structurally combine two already-tested mechanisms into one entry rule.

Per spec item 3: a recombination is NOT novel merely because it has more
components -- novelty must be judged at the mechanism level. This module
tags every candidate it produces ``novelty_tag=RECOMBINATION`` (never
``NEW``), and the mechanism-level novelty check (Phase 4's
``idea_machine.semantic_novelty``) is left to actually classify it -- if the
combined mechanism's real keyword overlap with a REFUTED or STILL_UNDERPOWERED
family is high, that governs, regardless of how many parents fed into it.

``trade_sc_and_dc`` is a REAL, callable trading function (not a description):
it AND-combines Cycle 8's ``trade_sc`` (surprise-confirmation entry/exit) with
its ``trade_dc`` (cross-asset divergence) condition as an additional entry
gate -- "only take the surprise-confirmation trade when the driver's own
impulse move has NOT yet been followed by FX", i.e. underreaction-to-surprise
gated by presence of a lagging cross-asset divergence. It is economically
coherent (both parent mechanisms are about slow information transmission) and
genuinely untested: no cycle has AND-combined two entry conditions before
(``combinations["TWO_MECHANISM_AND"]`` is UNEXPLORED in the search space).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from idea_machine.governance import guard
from idea_machine.research_space.information_gain import RECOMBINE, RECOMBINATION, ResearchCandidate
from idea_machine.research_space.search_space import SearchSpace

from discovery.cycle8_intraday import (
    IMPULSE_WINDOW_MIN, SURPRISE_FX_DIR, MacroEvent,
    _entry_ts, _impulse_ts, _exit_ts, _sign,
)


def trade_sc_and_dc(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
                    window_min: int, cost: float) -> Optional[float]:
    """RECOMBINE candidate: SC's entry/exit, gated by DC's divergence condition.

    Enter in the surprise-implied direction (Cycle 8's SC rule) ONLY when the
    driver's own impulse-window move has NOT yet been matched by FX at that
    same point (Cycle 8's DC divergence condition) -- i.e. trade the surprise
    confirmation specifically when there is also a lagging cross-asset gap to
    exploit, rather than unconditionally.
    """
    if window_min <= IMPULSE_WINDOW_MIN:
        return None
    if event.surprise is None or event.surprise == 0:
        return None

    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)
    d0, d1 = driver.price_at_or_after(t_entry), driver.price_at_or_after(t_imp)
    f0, f1 = fx.price_at_or_after(t_entry), fx.price_at_or_after(t_imp)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f0, f1, f2) or d0 <= 0 or f0 <= 0 or f1 <= 0:
        return None

    driver_move = math.log(d1 / d0)
    expected_from_driver = base_dir * _sign(driver_move)
    implied_from_surprise = SURPRISE_FX_DIR[symbol] * _sign(event.surprise)
    if expected_from_driver == 0 or expected_from_driver != implied_from_surprise:
        return None  # SC condition: driver must confirm the surprise-implied direction

    fx_aligned_move = base_dir * math.log(f1 / f0)
    if fx_aligned_move > 0:
        return None  # DC condition: FX must NOT already have followed the driver's impulse

    gross = implied_from_surprise * math.log(f2 / f0)
    return gross - cost


RECOMBINED_MECHANISM_FUNCTIONS: Dict[str, object] = {
    "SC_AND_DC_COMBINED_CONFIRMATION": trade_sc_and_dc,
}


class RecombinationEngine:
    def __init__(self, search_space: SearchSpace) -> None:
        self.search_space = search_space

    def combine(
        self, *, parent_mechanisms: List[str], instrument: str, driver: Optional[str],
        holding_period_min: int, combined_mechanism: str, rationale: str,
    ) -> Optional[ResearchCandidate]:
        if len(parent_mechanisms) < 2:
            raise ValueError("recombination requires at least two parent mechanisms")
        if combined_mechanism not in RECOMBINED_MECHANISM_FUNCTIONS:
            raise ValueError(
                f"{combined_mechanism!r} has no real callable trade function -- "
                "a recombination proposal must be runnable, not merely described"
            )
        for m in parent_mechanisms:
            cell = self.search_space.cell("mechanisms", m)
            if cell.status not in ("TESTED", "SURVIVED", "UNDERPOWERED", "KNOWN"):
                raise ValueError(f"parent mechanism {m!r} has no evidence base to recombine from (status={cell.status})")

        guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", mode=RECOMBINE, mechanism=combined_mechanism)
        return ResearchCandidate(
            mechanism=combined_mechanism, instrument=instrument, driver=driver,
            holding_period_min=holding_period_min, research_mode=RECOMBINE,
            mutation_operator="MECHANISM_RECOMBINATION",
            parent_candidate_id="",
            rationale=(f"{rationale}; AND-combines {' + '.join(parent_mechanisms)} into one "
                      f"entry rule -- novelty is a mechanism-level question, not counted as "
                      f"NEW merely for having two components"),
            novelty_level="LEVEL_2_MECHANISM_VARIATION",
            novelty_tag=RECOMBINATION,
        )
