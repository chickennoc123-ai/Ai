"""Search-Space Registry (Phase 9, second pass): open, region-based search space model.

A "search region" is an arbitrary combination of dimensions -- instrument,
asset class, timeframe, event family, event surprise, market regime, session,
volatility state, momentum, mean reversion, cross-asset relationship, macro
driver, entry timing, exit timing, holding horizon, confirmation mechanism,
interaction effects, or any NEW dimension key nobody has used yet. The
dimension set is deliberately open (a plain dict), never a hardcoded closed
list, per spec item 2 ("Không hardcode một danh sách đóng").

Every region has a stable, content-addressed id
(``idea_machine.core.ids.mint_id``, the same determinism guarantee the rest
of the Idea Machine already relies on) -- so the SAME dimension combination
always resolves to the SAME region_id, whether it was proposed this cycle or
five cycles ago.

Reuses, rather than re-derives, the evidence-scanning logic already built and
live-demonstrated in ``idea_machine.research_space.search_space.SearchSpace``
(Phase 9 first pass, Cycle 14): this registry asks THAT module for the
(mechanism, instrument, driver) triple's real status via
``SearchSpace.triple_status`` instead of re-scanning
``research_family_registry.json``/``candidate_spec_registry.json`` a second
time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

from idea_machine.core import epistemic
from idea_machine.core.ids import content_hash, mint_id
from idea_machine.governance import guard
from idea_machine.research_memory import ResearchMemory
from idea_machine.research_space.search_space import (
    KNOWN_MECHANISMS, KNOWN_TESTED_DRIVERS, KNOWN_TRADEABLE_INSTRUMENTS,
    KNOWN_UNEXPLORED_DRIVERS, RECOMBINED_MECHANISMS, UNEXPLORED, SearchSpace,
)

#: One addition beyond the epistemic states + UNEXPLORED: a region whose
#: neighbouring combinations have all been touched and offers no further
#: genuinely new territory (spec item 10's "search-space exhausted" signal).
EXHAUSTED = "EXHAUSTED"

REGION_STATUSES = frozenset(epistemic.STATES | {UNEXPLORED, EXHAUSTED})


def _clean_mechanism_code(mechanism_text: str) -> str:
    """Extract the leading mechanism CODE from a free-text description.

    ``candidate_spec_registry.json`` stores mechanism as a full sentence
    ("SC_SURPRISE_CONFIRMATION: EURUSD vs US10Y driver, 5min window, ...").
    Using the whole sentence as a dimension value would mint a DIFFERENT
    region id for every trivial wording difference between otherwise
    identical mechanisms -- exactly the kind of accidental non-determinism
    the rest of the Idea Machine goes out of its way to avoid. Only the code
    before the first ':' (or the whole string if there is none) is kept.
    """
    if not mechanism_text:
        return ""
    return mechanism_text.split(":", 1)[0].strip()


def region_id_for(dimensions: Mapping[str, str], tag: str = "") -> str:
    """Stable, content-addressed region id. Same dimensions -> same id, always."""
    canonical_dims = {str(k): str(v) for k, v in sorted(dimensions.items())}
    digest = content_hash(canonical_dims)[:10]
    if tag:
        return f"REGION-{tag.strip().upper().replace(' ', '-')}-{digest}"
    return f"REGION-{digest}"


@dataclass(frozen=True)
class SearchRegion:
    region_id: str
    dimensions: Dict[str, str]
    status: str
    evidence: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in REGION_STATUSES:
            raise ValueError(f"unknown region status {self.status!r}")

    def to_dict(self) -> Dict:
        return {
            "region_id": self.region_id,
            "dimensions": dict(self.dimensions),
            "status": self.status,
            "evidence": list(self.evidence),
        }


class SearchSpaceRegistry:
    """Open, region-based search-space model. Read-only over the Factory's
    own records (via ResearchMemory + SearchSpace); new UNEXPLORED regions
    may be *registered* (proposed) but nothing here writes to any Factory file.
    """

    def __init__(self, memory: Optional[ResearchMemory] = None, space: Optional[SearchSpace] = None) -> None:
        self.memory = memory or ResearchMemory()
        if not self.memory._loaded:
            self.memory.load()
        self.space = space or SearchSpace(self.memory)
        self._regions: Dict[str, SearchRegion] = {}
        self._seed_from_real_history()

    # ------------------------------------------------------------- seeding

    def _seed_from_real_history(self) -> None:
        """Populate the registry from BOTH real tested triples AND the real,
        confirmed-present-but-never-tested catalog research_space.search_space
        already maintains.

        Seeding ONLY from tested history would make ``is_exhausted()``
        trivially true the moment the registry is constructed (every seeded
        region would already be TESTED/REFUTED/UNDERPOWERED by definition) --
        a real bug caught while writing this module's own tests. The registry
        must also know what is genuinely UNEXPLORED but testable, which is
        exactly the catalog ``KNOWN_UNEXPLORED_DRIVERS``/
        ``RECOMBINED_MECHANISMS`` already track (each entry independently
        confirmed to have real underlying market data, the same discipline
        Cycle 13/14 used before adding a new driver).
        """
        seen: set = set()
        for hyp in self.memory.cycle_hypotheses:
            key = ("", hyp.symbol, hyp.driver or "")
            if key in seen or not hyp.symbol:
                continue
            seen.add(key)
            self._register_from_triple(mechanism="", instrument=hyp.symbol, driver=hyp.driver)

        for cand in self.memory.candidates.values():
            mech_code = _clean_mechanism_code(cand.mechanism)
            key = (mech_code, cand.symbol, cand.driver or "")
            if key in seen or not cand.symbol:
                continue
            seen.add(key)
            self._register_from_triple(mechanism=mech_code, instrument=cand.symbol, driver=cand.driver)

        # Genuinely UNEXPLORED-but-testable regions: every tradeable
        # instrument crossed with every driver NOT yet used in any cycle.
        for instrument in KNOWN_TRADEABLE_INSTRUMENTS:
            for driver in KNOWN_UNEXPLORED_DRIVERS:
                key = ("", instrument, driver)
                if key in seen:
                    continue
                seen.add(key)
                self._register_from_triple(mechanism="", instrument=instrument, driver=driver)
        for instrument in KNOWN_TRADEABLE_INSTRUMENTS:
            for mechanism in RECOMBINED_MECHANISMS:
                key = (mechanism, instrument, "")
                if key in seen:
                    continue
                seen.add(key)
                self._register_from_triple(mechanism=mechanism, instrument=instrument, driver=None)

    def _register_from_triple(self, *, mechanism: str, instrument: str, driver: Optional[str]) -> SearchRegion:
        dims = {"instrument": instrument}
        if driver:
            dims["macro_driver"] = driver
        if mechanism:
            dims["mechanism"] = mechanism
        status, evidence = self.space.triple_status(mechanism, instrument, driver)
        if status == UNEXPLORED and not evidence:
            evidence = (f"instrument x driver combination confirmed to have real market data, "
                       f"never used in any Factory cycle",) if driver else \
                      (f"recombined mechanism, confirmed real, never run on {instrument}",)
        region = SearchRegion(region_id_for(dims, tag=instrument), dims, status, evidence)
        self._regions[region.region_id] = region
        return region

    # -------------------------------------------------------------- writing

    def register_region(self, dimensions: Mapping[str, str], *, tag: str = "") -> SearchRegion:
        """Propose a new region. Governance-visible; never mutates a Factory file."""
        guard.require("REGISTER_SEARCH_REGION", dimensions=dict(dimensions))
        rid = region_id_for(dimensions, tag=tag)
        if rid in self._regions:
            return self._regions[rid]
        region = SearchRegion(rid, dict(dimensions), UNEXPLORED, ("newly proposed, no prior evidence",))
        self._regions[rid] = region
        return region

    # -------------------------------------------------------------- reading

    def get(self, region_id: str) -> Optional[SearchRegion]:
        return self._regions.get(region_id)

    def all_regions(self) -> List[SearchRegion]:
        return sorted(self._regions.values(), key=lambda r: r.region_id)

    def by_status(self, status: str) -> List[SearchRegion]:
        return [r for r in self._regions.values() if r.status == status]

    def unexplored_regions(self) -> List[SearchRegion]:
        return self.by_status(UNEXPLORED)

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self._regions.values():
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def is_exhausted(self, *, coverage_threshold: float = 0.85) -> Tuple[bool, str]:
        """Spec item 10: detect "not enough new territory left in the current space."

        Deliberately conservative: only declares exhaustion when the KNOWN
        region set (everything actually seeded from real history) has been
        touched (TESTED/SURVIVED/REFUTED/UNDERPOWERED) at or above
        ``coverage_threshold`` AND there are zero UNEXPLORED regions left in
        the registry's current dimension catalog. This never claims
        exhaustion just because few regions exist -- a small, fully-untested
        space is UNEXPLORED, not EXHAUSTED.
        """
        total = len(self._regions)
        if total == 0:
            return False, "no regions registered yet"
        touched = sum(1 for r in self._regions.values()
                      if r.status not in (UNEXPLORED, epistemic.UNKNOWN))
        coverage = touched / total
        unexplored_left = len(self.unexplored_regions())
        exhausted = coverage >= coverage_threshold and unexplored_left == 0
        detail = (f"coverage={coverage:.1%} (threshold {coverage_threshold:.0%}), "
                 f"{unexplored_left} unexplored region(s) remaining")
        return exhausted, detail

    def to_dict(self) -> Dict:
        return {
            "status_counts": self.status_counts(),
            "regions": [r.to_dict() for r in self.all_regions()],
        }
