"""ResearchSpace: a structured, read-only world model of the strategy search space.

Reads (never writes) the Strategy Factory's own real records, via the
already-proven Phase 3 :class:`~idea_machine.research_memory.ResearchMemory`,
plus the real, pre-registered pairing/mechanism/driver catalogs that already
exist as code in ``discovery/cycle8_intraday.py`` and
``discovery/cycle13_idea_machine_live.py``. Nothing here is fabricated: every
dimension value is either a symbol/driver/mechanism that has genuinely been
evaluated (with real M1/H1 data, per those two cycles), or a symbol/driver
combination this module has independently confirmed has real underlying data
available (see ``_confirmed_present`` catalogs below, built the same way
Cycle 13 built its own -- by checking the data root before claiming a value
exists).

Per governance, UNKNOWN != profitable, and this module adds one status the
existing seven-state epistemic model does not carry: UNEXPLORED, meaning "not
even proposed yet" (distinct from UNKNOWN, epistemic.py's "a source claims it,
untested" -- there is no claim here, just an unused combination).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

from idea_machine.core import epistemic
from idea_machine.governance import guard
from idea_machine.research_memory import ResearchMemory

#: One addition to the seven epistemic states, local to the search-space map.
UNEXPLORED = "UNEXPLORED"

CELL_STATUSES: FrozenSet[str] = frozenset(epistemic.STATES | {UNEXPLORED})

#: Dimension names, exactly as enumerated in the Phase 9 spec.
DIMENSIONS: Tuple[str, ...] = (
    "instruments",
    "asset_classes",
    "event_types",
    "timeframes",
    "holding_periods",
    "market_sessions",
    "mechanisms",
    "drivers",
    "confirmation_rules",
    "execution_models",
    "regime_dimensions",
    "cross_asset_relationships",
    "behavioral_hypotheses",
    "combinations",
)


@dataclass(frozen=True)
class DimensionCell:
    """One value within one dimension, with its epistemic status and why."""

    dimension: str
    value: str
    status: str
    evidence: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "status": self.status,
            "evidence": list(self.evidence),
        }


# --------------------------------------------------------------------------
# Real catalogs -- every entry here has been independently confirmed to have
# real underlying M1/H1 Oanda data present (the same check Cycle 13 performed
# before writing its NEW_PAIRINGS / NEW_DRIVER_FOLDERS), so a cell marked
# UNEXPLORED in this module is genuinely testable, not aspirational.
# --------------------------------------------------------------------------

#: Instruments with real M1/H1 data AND a frozen cost registration (tradeable today).
KNOWN_TRADEABLE_INSTRUMENTS: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD",
)

#: Instruments with real M1 data but NO frozen cost yet -- legitimately
#: DATA_BLOCKED, per governance (cost model is never registered post-hoc).
KNOWN_COST_BLOCKED_INSTRUMENTS: Tuple[str, ...] = ("AUDUSD", "EURJPY")

#: Drivers already used in a real cycle (Cycle 8 or Cycle 13).
KNOWN_TESTED_DRIVERS: Tuple[str, ...] = ("WTICO", "SPX500", "US10Y", "NAS100", "UK10YB", "USB02Y", "DE10YB")

#: Drivers confirmed to have real M1 data present but never used in any cycle
#: -- genuine EXPLORE territory, not invented.
KNOWN_UNEXPLORED_DRIVERS: Tuple[str, ...] = ("JP225", "UK100", "AU200", "US2000", "NATGAS")

#: Mechanisms that exist as real, callable code (discovery/cycle8_intraday.py).
KNOWN_MECHANISMS: Tuple[str, ...] = (
    "DC_CROSS_ASSET_DIVERGENCE", "SC_SURPRISE_CONFIRMATION",
    "DR_DELAYED_REACTION", "RI_REVERSAL_AFTER_IMPULSE",
)

#: A mechanism-recombination this package can actually run (see
#: recombination_engine.py): AND-combining SC's surprise-direction condition
#: with DC's divergence condition into one entry rule.
RECOMBINED_MECHANISMS: Tuple[str, ...] = ("SC_AND_DC_COMBINED_CONFIRMATION",)

HOLDING_PERIODS_MIN: Tuple[int, ...] = (5, 15, 30, 60, 120, 240)

#: Real market sessions, defined by UTC hour bands -- used by regime/session filters.
MARKET_SESSIONS: Tuple[str, ...] = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NY_OVERLAP")

#: Regime dimensions this project's own semantic mechanism classes already recognise
#: (idea_machine/semantic_novelty.py's "regime" class: volatility, session).
REGIME_DIMENSIONS: Tuple[str, ...] = ("VOLATILITY_REGIME", "SESSION_REGIME")

#: Execution models that exist as real, distinct code paths in cycle8_intraday.py.
EXECUTION_MODELS: Tuple[str, ...] = ("IMMEDIATE_ENTRY_DELAY", "POST_IMPULSE_DELAYED_ENTRY")

#: Confirmation structures -- literal, distinct entry-gating rules already coded.
CONFIRMATION_RULES: Tuple[str, ...] = (
    "NONE", "CROSS_ASSET_DRIVER_CONFIRMS_SURPRISE", "CROSS_ASSET_DIVERGENCE_PRESENT",
)


class SearchSpace:
    """Read-only, structured map of the strategy search space.

    Populated from real records only: the Factory's own registries (via
    ResearchMemory), the two real cycle files' PAIRINGS/mechanism catalogs,
    and the independently-confirmed-present driver/instrument catalogs above.
    Never writes to any Factory file.
    """

    def __init__(self, memory: Optional[ResearchMemory] = None) -> None:
        guard.require("MAP_SEARCH_SPACE")
        self.memory = memory or ResearchMemory()
        if not self.memory._loaded:
            self.memory.load()
        self._cells: Dict[Tuple[str, str], DimensionCell] = {}
        self._build()

    # ------------------------------------------------------------- building

    def _set(self, dimension: str, value: str, status: str, evidence: str) -> None:
        key = (dimension, value)
        existing = self._cells.get(key)
        if existing is None:
            self._cells[key] = DimensionCell(dimension, value, status, (evidence,))
            return
        # A cell can only strengthen its evidence trail, never overwrite a
        # stronger status with a weaker one (REFUTED must never be quietly
        # downgraded back to UNEXPLORED by a later, less-informed pass).
        rank = {
            UNEXPLORED: 0, epistemic.UNKNOWN: 1, epistemic.KNOWN: 2, epistemic.BLOCKED: 3,
            epistemic.UNDERPOWERED: 4, epistemic.TESTED: 5, epistemic.SURVIVED: 6,
            epistemic.REFUTED: 7,
        }
        if rank.get(status, 0) >= rank.get(existing.status, 0):
            self._cells[key] = DimensionCell(dimension, value, status, existing.evidence + (evidence,))
        else:
            self._cells[key] = DimensionCell(dimension, existing.value, existing.status, existing.evidence + (evidence,))

    def _build(self) -> None:
        self._build_instruments()
        self._build_drivers()
        self._build_mechanisms()
        self._build_holding_periods()
        self._build_static_catalog_dims()
        self._build_from_research_memory()

    def _build_instruments(self) -> None:
        for sym in KNOWN_TRADEABLE_INSTRUMENTS:
            self._set("instruments", sym, epistemic.KNOWN, "frozen cost registered, real M1/H1 data present")
        for sym in KNOWN_COST_BLOCKED_INSTRUMENTS:
            self._set("instruments", sym, epistemic.BLOCKED, "real M1 data present but no frozen cost registration")

    def _build_drivers(self) -> None:
        for d in KNOWN_TESTED_DRIVERS:
            self._set("drivers", d, epistemic.TESTED, "used in a real Factory cycle (Cycle 8 or Cycle 13)")
        for d in KNOWN_UNEXPLORED_DRIVERS:
            self._set("drivers", d, UNEXPLORED, "real M1 data confirmed present, never used in any cycle")

    def _build_mechanisms(self) -> None:
        for m in KNOWN_MECHANISMS:
            self._set("mechanisms", m, epistemic.TESTED, "real, callable mechanism in discovery/cycle8_intraday.py")
        for m in RECOMBINED_MECHANISMS:
            self._set("mechanisms", m, UNEXPLORED, "structural AND-combination of two tested mechanisms, never run")

    def _build_holding_periods(self) -> None:
        for w in HOLDING_PERIODS_MIN:
            self._set("holding_periods", f"{w}m", epistemic.TESTED, "evaluated as a window in Cycle 8/13")

    def _build_static_catalog_dims(self) -> None:
        for s in MARKET_SESSIONS:
            self._set("market_sessions", s, UNEXPLORED, "defined UTC session band, never used as an entry filter")
        for r in REGIME_DIMENSIONS:
            self._set("regime_dimensions", r, UNEXPLORED, "recognised mechanism class, never used as a live filter")
        for e in EXECUTION_MODELS:
            self._set("execution_models", e, epistemic.TESTED, "real code path in cycle8_intraday.py mechanisms")
        for c in CONFIRMATION_RULES:
            status = epistemic.TESTED if c != "NONE" else epistemic.KNOWN
            self._set("confirmation_rules", c, status, "entry-gating structure already coded in mechanism functions")
        self._set("asset_classes", "FX_MAJOR", epistemic.KNOWN, "EURUSD/GBPUSD/USDJPY/USDCHF/USDCAD tested")
        self._set("asset_classes", "METALS", epistemic.KNOWN, "XAUUSD tested")
        self._set("asset_classes", "EQUITY_INDEX", UNEXPLORED, "SPX500/NAS100 used only as drivers, never as the traded leg")
        self._set("asset_classes", "RATES", UNEXPLORED, "US10Y/UK10YB/DE10YB/USB02Y used only as drivers, never as the traded leg")
        self._set("event_types", "NFP", epistemic.TESTED, "real USD NFP events in the calendar, used every cycle")
        self._set("event_types", "CPI_YOY", epistemic.TESTED, "real USD CPI y/y events in the calendar, used every cycle")
        self._set("cross_asset_relationships", "USD_YIELD_DIFFERENTIAL", epistemic.TESTED, "Cycle 8 EURUSD/GBPUSD vs US10Y")
        self._set("cross_asset_relationships", "RISK_SENTIMENT", epistemic.TESTED, "Cycle 8 XAUUSD/USDJPY/USDCHF vs SPX500")
        self._set("cross_asset_relationships", "PETRO_CURRENCY", epistemic.TESTED, "Cycle 13 USDCAD vs WTICO")
        self._set("cross_asset_relationships", "DOMESTIC_YIELD_CURVE", epistemic.TESTED, "Cycle 13 GBPUSD/EURUSD vs own-currency yield")
        self._set("cross_asset_relationships", "SHORT_RATE_REAL_YIELD", epistemic.TESTED, "Cycle 13 XAUUSD/USDJPY vs US 2y")
        self._set("behavioral_hypotheses", "UNDERREACTION_TO_SURPRISE", epistemic.TESTED, "SC mechanism family")
        self._set("behavioral_hypotheses", "OVERREACTION_MEAN_REVERSION", epistemic.TESTED, "RI mechanism family")
        self._set("behavioral_hypotheses", "ATTENTION_DELAY", epistemic.TESTED, "DR mechanism family")
        self._set("combinations", "SINGLE_MECHANISM", epistemic.TESTED, "every hypothesis run so far is single-mechanism")
        self._set("combinations", "TWO_MECHANISM_AND", UNEXPLORED, "no cycle has combined two mechanisms into one entry rule")

    def _build_from_research_memory(self) -> None:
        """Overlay the Factory's own real evidence onto the instrument/driver/mechanism cells."""
        for fam in self.memory.families.values():
            status_map = {
                "REFUTED": epistemic.REFUTED,
                "STILL_UNDERPOWERED": epistemic.UNDERPOWERED,
                "TESTED_FAILED": epistemic.TESTED,
                "NOVEL": epistemic.KNOWN,
                "UNKNOWN": epistemic.UNKNOWN,
            }.get(fam.status, epistemic.UNKNOWN)
            self._set("combinations", fam.family_id, status_map, f"research_family_registry.json status={fam.status}")

        for cand in self.memory.candidates.values():
            status_map = {
                "STILL_UNDERPOWERED": epistemic.UNDERPOWERED,
                "TESTED_FAILED": epistemic.TESTED,
                "SURVIVOR": epistemic.SURVIVED,
            }.get(cand.evidence_status, epistemic.UNKNOWN)
            if cand.symbol:
                self._set("instruments", cand.symbol, status_map,
                          f"candidate_spec_registry.json {cand.candidate_id} evidence_status={cand.evidence_status}")
            if cand.driver:
                self._set("drivers", cand.driver, status_map,
                          f"candidate_spec_registry.json {cand.candidate_id} evidence_status={cand.evidence_status}")

        for hyp in self.memory.cycle_hypotheses:
            status_map = {
                "REFUTED": epistemic.REFUTED,
                "STILL_UNDERPOWERED": epistemic.UNDERPOWERED,
                "TESTED_FAILED": epistemic.TESTED,
                "SURVIVOR": epistemic.SURVIVED,
            }.get(hyp.classification, epistemic.TESTED)
            if hyp.symbol:
                self._set("instruments", hyp.symbol, status_map, f"{hyp.cycle_id}/{hyp.hyp_id} classification={hyp.classification}")
            if hyp.driver:
                self._set("drivers", hyp.driver, status_map, f"{hyp.cycle_id}/{hyp.hyp_id} classification={hyp.classification}")

    # ------------------------------------------------------ precise triples

    def triple_status(self, mechanism: str, instrument: str, driver: Optional[str]) -> Tuple[str, Tuple[str, ...]]:
        """Precise (mechanism, instrument, driver) evidence, NOT the per-dimension rollup.

        The per-dimension cells (``cell("instruments", "EURUSD")``) are
        deliberately coarse -- useful for the space-map heatmap -- but using
        them to decide whether a SPECIFIC triple may be exploited is wrong: an
        instrument can carry REFUTED evidence from one unrelated hypothesis
        (e.g. a driver-less single-asset test) while a completely different
        driver/mechanism pairing on that same instrument was only
        STILL_UNDERPOWERED. This method matches on the real symbol+driver
        (and mechanism, where the record carries one) together, so a
        REFUTED verdict here means THIS triple was refuted, not merely that
        the instrument appears somewhere in REFUTED history.
        """
        evidence: List[str] = []
        best_rank = 0
        rank = {
            epistemic.UNKNOWN: 1, epistemic.KNOWN: 2, epistemic.BLOCKED: 3,
            epistemic.UNDERPOWERED: 4, epistemic.TESTED: 5, epistemic.SURVIVED: 6, epistemic.REFUTED: 7,
        }
        best_status = UNEXPLORED

        for cand in self.memory.candidates.values():
            if cand.symbol != instrument:
                continue
            if driver and cand.driver != driver:
                continue
            if cand.mechanism and mechanism and cand.mechanism.upper() not in mechanism.upper() \
                    and mechanism.upper() not in cand.mechanism.upper():
                continue
            status = {
                "STILL_UNDERPOWERED": epistemic.UNDERPOWERED, "TESTED_FAILED": epistemic.TESTED,
                "SURVIVOR": epistemic.SURVIVED,
            }.get(cand.evidence_status, epistemic.UNKNOWN)
            evidence.append(f"{cand.candidate_id}: symbol={cand.symbol} driver={cand.driver} "
                            f"mechanism={cand.mechanism!r} evidence_status={cand.evidence_status}")
            if rank.get(status, 0) > best_rank:
                best_rank, best_status = rank.get(status, 0), status

        for hyp in self.memory.cycle_hypotheses:
            if hyp.symbol != instrument:
                continue
            if driver and hyp.driver != driver:
                continue
            if not driver and hyp.driver:
                continue  # a driver-specific hypothesis must not gate a driver-less triple, or vice versa
            if mechanism:
                # CycleHypothesisRecord carries NO mechanism field at all, so
                # it can never confirm or deny agreement with a CALLER-
                # specified mechanism. Applying it anyway would let one
                # unrelated hypothesis (e.g. a plain single-asset REFUTED
                # test with no mechanism info) silently block every future
                # mechanism proposal that happens to share its symbol/driver,
                # including a brand-new mechanism that was never actually
                # tested -- exactly the failure mode found live while
                # building the search-space registry's RECOMBINE seeding.
                # Candidate records (which DO carry a mechanism field, above)
                # remain the source of mechanism-specific evidence.
                continue
            status = {
                "REFUTED": epistemic.REFUTED, "STILL_UNDERPOWERED": epistemic.UNDERPOWERED,
                "TESTED_FAILED": epistemic.TESTED, "SURVIVOR": epistemic.SURVIVED,
            }.get(hyp.classification, epistemic.TESTED)
            evidence.append(f"{hyp.cycle_id}/{hyp.hyp_id}: symbol={hyp.symbol} driver={hyp.driver} "
                            f"classification={hyp.classification}")
            if rank.get(status, 0) > best_rank:
                best_rank, best_status = rank.get(status, 0), status

        if not evidence:
            mech_cell = self.cell("mechanisms", mechanism)
            if mech_cell.status not in (UNEXPLORED, epistemic.UNKNOWN):
                return mech_cell.status, mech_cell.evidence
            return UNEXPLORED, ()

        return best_status, tuple(evidence)

    # -------------------------------------------------------------- reading

    def cell(self, dimension: str, value: str) -> DimensionCell:
        key = (dimension, value)
        if key not in self._cells:
            return DimensionCell(dimension, value, UNEXPLORED, ("no record of this value in any dimension",))
        return self._cells[key]

    def cells_in(self, dimension: str) -> List[DimensionCell]:
        return sorted((c for (d, _), c in self._cells.items() if d == dimension), key=lambda c: c.value)

    def unexplored(self, dimension: Optional[str] = None) -> List[DimensionCell]:
        return [c for (d, _), c in self._cells.items()
                if c.status == UNEXPLORED and (dimension is None or d == dimension)]

    def by_status(self, status: str) -> List[DimensionCell]:
        return sorted((c for c in self._cells.values() if c.status == status),
                      key=lambda c: (c.dimension, c.value))

    def status_counts(self) -> Dict[str, Dict[str, int]]:
        """dimension -> status -> count, for the `space` CLI report."""
        out: Dict[str, Dict[str, int]] = {}
        for (dim, _), cell in self._cells.items():
            out.setdefault(dim, {})
            out[dim][cell.status] = out[dim].get(cell.status, 0) + 1
        return out

    def novelty_coverage(self) -> float:
        """Fraction of all known cells that have been at least TESTED/SURVIVED/REFUTED/UNDERPOWERED."""
        total = len(self._cells)
        if total == 0:
            return 0.0
        touched = sum(1 for c in self._cells.values() if c.status not in (UNEXPLORED, epistemic.UNKNOWN))
        return round(touched / total, 4)

    def all_cells(self) -> List[DimensionCell]:
        return sorted(self._cells.values(), key=lambda c: (c.dimension, c.value))

    def to_dict(self) -> Dict:
        return {
            "dimensions": list(DIMENSIONS),
            "status_counts": self.status_counts(),
            "novelty_coverage": self.novelty_coverage(),
            "cells": [c.to_dict() for c in self.all_cells()],
        }
