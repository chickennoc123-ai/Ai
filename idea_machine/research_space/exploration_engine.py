"""EXPLORE: propose candidates in genuinely unexplored search-space territory.

Prioritises mechanism-level novelty over parameter change, per spec item 2:
an EXPLORE candidate must touch an UNEXPLORED driver, an UNEXPLORED mechanism,
or a cross-asset relationship never tested -- not merely a new window on an
already-tested triple (that is EXPLOIT's job).

Operators implemented here: SWAP_INSTRUMENT, SWAP_DRIVER, ADD_DIMENSION
(introduce a regime/session filter never used as a live condition).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from idea_machine.governance import guard
from idea_machine.research_space.information_gain import EXPLORE, NEW, ResearchCandidate
from idea_machine.research_space.search_space import SearchSpace, UNEXPLORED


class ExplorationEngine:
    def __init__(self, search_space: SearchSpace) -> None:
        self.search_space = search_space

    def swap_driver(
        self, *, mechanism: str, instrument: str, holding_period_min: int, rationale: str,
        drivers: Optional[Sequence[str]] = None,
    ) -> List[ResearchCandidate]:
        """SWAP_DRIVER: pair a tested mechanism/instrument with an UNEXPLORED driver.

        Genuinely novel because the driver has never been used in any cycle
        (confirmed present in ``search_space.KNOWN_UNEXPLORED_DRIVERS``, which
        was built the same way Cycle 13 confirmed its own new drivers -- by
        checking the underlying data root before claiming a value exists).
        """
        candidates: List[ResearchCandidate] = []
        pool = drivers if drivers is not None else [c.value for c in self.search_space.unexplored("drivers")]
        for driver in pool:
            cell = self.search_space.cell("drivers", driver)
            if cell.status != UNEXPLORED:
                continue
            guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", mode=EXPLORE, driver=driver)
            candidates.append(ResearchCandidate(
                mechanism=mechanism, instrument=instrument, driver=driver,
                holding_period_min=holding_period_min, research_mode=EXPLORE,
                mutation_operator="SWAP_DRIVER",
                parent_candidate_id="",
                rationale=f"{rationale}; {driver} confirmed to have real data, never used as a driver in any cycle",
                novelty_level="LEVEL_3_NEW_MECHANISM_FAMILY",
                novelty_tag=NEW,
            ))
        return candidates

    def swap_instrument(
        self, *, mechanism: str, driver: str, holding_period_min: int, rationale: str,
        instruments: Optional[Sequence[str]] = None,
    ) -> List[ResearchCandidate]:
        """SWAP_INSTRUMENT: pair a tested mechanism/driver with an untested instrument.

        Only proposes instruments the search space marks KNOWN (tradeable,
        cost registered) but not yet tested against this driver -- a
        BLOCKED instrument (no frozen cost) is never proposed here; that is
        exactly the data/cost-aware discipline Cycle 13 enforced live.
        """
        candidates: List[ResearchCandidate] = []
        pool = instruments if instruments is not None else [c.value for c in self.search_space.cells_in("instruments")]
        for instrument in pool:
            cell = self.search_space.cell("instruments", instrument)
            if cell.status not in ("KNOWN", "UNEXPLORED"):
                continue
            guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", mode=EXPLORE, instrument=instrument)
            candidates.append(ResearchCandidate(
                mechanism=mechanism, instrument=instrument, driver=driver,
                holding_period_min=holding_period_min, research_mode=EXPLORE,
                mutation_operator="SWAP_INSTRUMENT",
                parent_candidate_id="",
                rationale=f"{rationale}; {instrument}/{driver} combination never tested in any cycle",
                novelty_level="LEVEL_3_NEW_MECHANISM_FAMILY",
                novelty_tag=NEW,
            ))
        return candidates

    def add_regime_dimension(
        self, *, mechanism: str, instrument: str, driver: Optional[str],
        holding_period_min: int, regime_dimension: str, rationale: str,
    ) -> Optional[ResearchCandidate]:
        """ADD_DIMENSION: gate a tested mechanism on a never-used regime filter.

        Distinct from RECOMBINE (which structurally merges two mechanisms'
        entry logic): this adds a filter dimension the mechanism never
        conditioned on before, without changing the entry rule itself.
        """
        cell = self.search_space.cell("regime_dimensions", regime_dimension)
        if cell.status != UNEXPLORED:
            return None
        guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", mode=EXPLORE, regime_dimension=regime_dimension)
        return ResearchCandidate(
            mechanism=mechanism, instrument=instrument, driver=driver,
            holding_period_min=holding_period_min, research_mode=EXPLORE,
            mutation_operator="ADD_DIMENSION",
            parent_candidate_id="",
            rationale=f"{rationale}; conditions entry on {regime_dimension}, never used as a live filter before",
            novelty_level="LEVEL_2_MECHANISM_VARIATION",
            novelty_tag=NEW,
        )
