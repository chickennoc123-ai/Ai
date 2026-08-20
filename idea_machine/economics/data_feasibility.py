"""Data feasibility (Phase 6) — can this even be tested, before we spend a slot?

The rule this module exists to enforce is *"Không được fabricate"*: if a
dataset is not in the catalog, the answer is ``BLOCKED_DATA``. It is never
"assume it exists", never "approximate it", and never "proceed and find out".

A dataset is only usable if it can answer all nine questions Phase 6 lists:
existence, timestamp precision, coverage, sample size, timezone, survivorship,
missing data, cost data, and execution assumptions. A catalog entry that leaves
any of them unanswered is treated as *unknown*, which blocks — an unverified
dataset is more dangerous than a missing one, because it produces numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.governance import guard

FEASIBLE = "FEASIBLE"
BLOCKED_DATA = "BLOCKED_DATA"

#: Minimum bars before an experiment has any chance of resolving a small effect.
#: This is a floor, not a power calculation -- the real power check happens in
#: the experiment designer, where the effect size is known.
MIN_SAMPLE_BARS = 2000


@dataclass(frozen=True)
class DatasetEntry:
    """What we actually know about one dataset. Unknown fields block."""

    dataset_id: str
    description: str
    timeframe: str
    timestamp_precision: str          # e.g. "1s", "1m"; "" == unknown
    timezone: str                     # e.g. "UTC"; "" == unknown
    coverage_start: str
    coverage_end: str
    row_count: int
    missing_data_pct: Optional[float] = None
    survivorship_bias_assessed: bool = False
    has_cost_data: bool = False
    execution_assumptions_documented: bool = False
    notes: str = ""

    def unanswered_questions(self) -> Tuple[str, ...]:
        """Which of the nine Phase 6 questions this entry cannot answer."""
        missing: List[str] = []
        if not self.timestamp_precision.strip():
            missing.append("timestamp_precision")
        if not self.timezone.strip():
            missing.append("timezone")
        if not (self.coverage_start.strip() and self.coverage_end.strip()):
            missing.append("coverage")
        if self.row_count < MIN_SAMPLE_BARS:
            missing.append(f"sample_size(<{MIN_SAMPLE_BARS})")
        if self.missing_data_pct is None:
            missing.append("missing_data")
        if not self.survivorship_bias_assessed:
            missing.append("survivorship")
        if not self.has_cost_data:
            missing.append("cost_data")
        if not self.execution_assumptions_documented:
            missing.append("execution_assumptions")
        return tuple(missing)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["unanswered"] = list(self.unanswered_questions())
        return d


class DataCatalog:
    """The datasets the operator actually holds. Absence means blocked."""

    def __init__(self, entries: Sequence[DatasetEntry] = ()) -> None:
        self._entries: Dict[str, DatasetEntry] = {e.dataset_id: e for e in entries}

    def register(self, entry: DatasetEntry) -> None:
        self._entries[entry.dataset_id] = entry

    def get(self, dataset_id: str) -> Optional[DatasetEntry]:
        return self._entries.get(dataset_id)

    def has(self, dataset_id: str) -> bool:
        return dataset_id in self._entries

    def all(self) -> Tuple[DatasetEntry, ...]:
        return tuple(self._entries[k] for k in sorted(self._entries))

    def dataset_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._entries))


@dataclass(frozen=True)
class FeasibilityVerdict:
    idea_id: str
    verdict: str
    missing_datasets: Tuple[str, ...] = field(default_factory=tuple)
    incomplete_datasets: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    usable_datasets: Tuple[str, ...] = field(default_factory=tuple)
    min_rows: int = 0
    reason: str = ""

    @property
    def may_proceed(self) -> bool:
        return self.verdict == FEASIBLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "verdict": self.verdict,
            "missing_datasets": list(self.missing_datasets),
            "incomplete_datasets": {k: list(v) for k, v in sorted(self.incomplete_datasets.items())},
            "usable_datasets": list(self.usable_datasets),
            "min_rows": self.min_rows,
            "reason": self.reason,
        }


class FeasibilityChecker:
    """Maps an idea's ``required_data`` onto the catalog and answers yes/no."""

    def __init__(self, catalog: DataCatalog) -> None:
        self.catalog = catalog

    def check(self, idea: IdeaSpec) -> FeasibilityVerdict:
        guard.require("CHECK_DATA_FEASIBILITY", idea_id=idea.idea_id)

        missing: List[str] = []
        incomplete: Dict[str, Tuple[str, ...]] = {}
        usable: List[str] = []
        rows: List[int] = []

        for requirement in sorted(set(idea.required_data)):
            entry = self.catalog.get(requirement)
            if entry is None:
                missing.append(requirement)
                continue
            unanswered = entry.unanswered_questions()
            if unanswered:
                incomplete[requirement] = unanswered
                continue
            usable.append(requirement)
            rows.append(entry.row_count)

        if missing or incomplete:
            parts = []
            if missing:
                parts.append(f"{len(missing)} dataset(s) not in the catalog")
            if incomplete:
                parts.append(f"{len(incomplete)} dataset(s) with unanswered quality questions")
            return FeasibilityVerdict(
                idea.idea_id,
                BLOCKED_DATA,
                missing_datasets=tuple(missing),
                incomplete_datasets=dict(sorted(incomplete.items())),
                usable_datasets=tuple(usable),
                min_rows=min(rows) if rows else 0,
                reason=(
                    "; ".join(parts)
                    + ". Blocked rather than approximated -- fabricating or assuming data is "
                    "how an experiment produces a confident answer to a question it never asked."
                ),
            )

        return FeasibilityVerdict(
            idea.idea_id,
            FEASIBLE,
            usable_datasets=tuple(usable),
            min_rows=min(rows) if rows else 0,
            reason="all required datasets are present and answer every quality question",
        )

    def screen(
        self, ideas: Sequence[IdeaSpec]
    ) -> Tuple[Tuple[IdeaSpec, ...], Tuple[FeasibilityVerdict, ...]]:
        passed: List[IdeaSpec] = []
        verdicts: List[FeasibilityVerdict] = []
        for idea in sorted(ideas, key=lambda i: i.idea_id):
            verdict = self.check(idea)
            verdicts.append(verdict)
            if verdict.may_proceed:
                passed.append(idea)
        return tuple(passed), tuple(verdicts)


def default_catalog() -> DataCatalog:
    """A deliberately EMPTY catalog.

    There is no plausible default: what data exists is a property of the
    operator's machine, not of this package. Starting empty means an unconfigured
    Idea Machine blocks every idea, which is the safe failure mode — the unsafe
    one would be assuming datasets exist and generating experiments against them.
    """
    return DataCatalog()
