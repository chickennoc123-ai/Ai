"""The autonomous loop (Phase 15) — one full cycle, wired end to end.

    SCAN -> UNDERSTAND -> GENERATE -> COMBINE -> FILTER -> RANK -> DESIGN
         -> QUEUE -> FACTORY -> {FAIL | SURVIVE} -> LEARN -> SCAN AGAIN

:meth:`IdeaMachine.run_cycle` performs everything up to and including handing
frozen experiments to the Strategy Factory. It stops there, because the Factory
runs on its own schedule and owns everything downstream.
:meth:`IdeaMachine.ingest_results` closes the loop when verdicts come back.

The cycle is deterministic given the same inputs, budget-bounded at every
stage, and governed at every boundary. A ``GovernanceViolation`` raised
anywhere inside it is not caught: the cycle dies, the audit ledger keeps the
attempt, and the operator finds out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.adaptive.search import AdaptiveSearch, SearchPolicy
from idea_machine.budget.manager import (
    EXPERIMENTS_REGISTERED,
    IDEAS_GENERATED,
    IDEAS_SCREENED,
    BudgetPolicy,
    ResearchBudget,
)
from idea_machine.combinator.combinator import CombinationEngine
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.economics.cost_model import DEFAULT_COST_MODEL, CostModel, verify_frozen_costs
from idea_machine.economics.data_feasibility import DataCatalog, FeasibilityChecker
from idea_machine.economics.prefilter import EconomicPreFilter
from idea_machine.experiment.designer import ExperimentDesigner
from idea_machine.experiment.prereg import PreregistrationLedger
from idea_machine.feedback.engine import FeedbackEngine, FeedbackOutcome
from idea_machine.generator.generator import IdeaGenerator
from idea_machine.governance import guard
from idea_machine.integration.factory_bridge import (
    FactoryBridge,
    FactoryResult,
    FactorySubmitter,
    FileHandoffSubmitter,
)
from idea_machine.knowledge.base import KnowledgeBase
from idea_machine.novelty.checker import NoveltyChecker
from idea_machine.novelty.memory import FailureMemory
from idea_machine.queue import queue as queue_states
from idea_machine.queue.queue import IdeaQueue
from idea_machine.ranking.ranker import IdeaRanker
from idea_machine.scanner.scanner import SourceProvider, WorldScanner
from utils.helpers import isoformat

DEFAULT_IDEA_LEDGER = DEFAULT_ROOT / "idea_ledger.json"


@dataclass(frozen=True)
class CycleReport:
    """Everything one cycle did, in the order the roadmap lists it."""

    cycle_id: str
    started_at: str
    finished_at: str
    scanned: int
    concepts_known: int
    generated: int
    combined: int
    novelty_passed: int
    feasible: int
    economically_viable: int
    ranked: int
    designed: int
    underpowered_by_design: int
    submitted: int
    budget: Mapping[str, Any] = field(default_factory=dict)
    rejections: Mapping[str, Any] = field(default_factory=dict)
    submitted_experiments: Tuple[str, ...] = field(default_factory=tuple)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "funnel": {
                "scanned": self.scanned,
                "concepts_known": self.concepts_known,
                "generated": self.generated,
                "combined": self.combined,
                "novelty_passed": self.novelty_passed,
                "feasible": self.feasible,
                "economically_viable": self.economically_viable,
                "ranked": self.ranked,
                "designed": self.designed,
                "underpowered_by_design": self.underpowered_by_design,
                "submitted": self.submitted,
            },
            "budget": dict(self.budget),
            "rejections": dict(self.rejections),
            "submitted_experiments": list(self.submitted_experiments),
            "notes": list(self.notes),
        }


class IdeaMachine:
    """The whole machine, assembled. Nothing here bypasses a governance check."""

    def __init__(
        self,
        *,
        root: Path = DEFAULT_ROOT,
        providers: Sequence[SourceProvider] = (),
        catalog: Optional[DataCatalog] = None,
        cost_model: CostModel = DEFAULT_COST_MODEL,
        budget_policy: BudgetPolicy = BudgetPolicy(),
        submitter: Optional[FactorySubmitter] = None,
        clock=isoformat,
    ) -> None:
        verify_frozen_costs()
        root = Path(root)
        self.root = root
        self._clock = clock

        self.scanner = WorldScanner(ledger_path=root / "source_ledger.json", providers=list(providers), clock=clock)
        self.knowledge = KnowledgeBase(root / "knowledge_base.json", clock=clock)
        self.memory = FailureMemory(root / "failure_memory.json", clock=clock)
        self.queue = IdeaQueue(root / "idea_queue.json", clock=clock)
        self.prereg = PreregistrationLedger(root / "preregistrations.json", clock=clock)
        # Default the hand-off directory under this machine's root, so a machine
        # pointed at a scratch root does not write into the shared one.
        self.bridge = FactoryBridge(
            self.prereg,
            submitter=submitter or FileHandoffSubmitter(root / "handoff"),
            ledger_path=root / "factory_submissions.json",
            clock=clock,
        )
        self.budget = ResearchBudget(policy=budget_policy, path=root / "research_budget.json", clock=clock)
        self.catalog = catalog if catalog is not None else DataCatalog()
        self.cost_model = cost_model

        self.generator = IdeaGenerator(self.knowledge, clock=clock)
        self.combinator = CombinationEngine(self.knowledge, clock=clock)
        self.feasibility = FeasibilityChecker(self.catalog)
        self.prefilter = EconomicPreFilter(cost_model)
        self.designer = ExperimentDesigner(cost_model=cost_model, clock=clock)
        self.adaptive = AdaptiveSearch(memory=self.memory, knowledge=self.knowledge, queue=self.queue)
        self.feedback = FeedbackEngine(
            knowledge=self.knowledge, memory=self.memory, queue=self.queue, clock=clock
        )

        #: Every IdeaSpec ever minted, so results can be matched back to ideas.
        self.idea_ledger = AppendOnlyStore(root / "idea_ledger.json", id_field="idea_id", kind="idea")
        self.cycle_ledger = AppendOnlyStore(root / "cycles.json", id_field="cycle_id", kind="cycle")

    # -------------------------------------------------------------- one cycle

    def run_cycle(self, *, submit: bool = True) -> CycleReport:
        started = self._clock()
        notes: List[str] = []
        policy = self.adaptive.derive_policy(at=started)

        # (1) SCAN
        records = self.scanner.scan()

        # (2) UNDERSTAND
        for record in records:
            self.knowledge.ingest_source(record)

        # (3) GENERATE + (4) COMBINE, bounded by budget
        gen_allowance = self.budget.remaining(IDEAS_GENERATED)
        generation = self.generator.generate()
        combination = self.combinator.combine(generation.ideas)
        all_ideas = list(generation.ideas) + list(combination.ideas)
        all_ideas = self._prioritise_by_policy(all_ideas, policy)[:gen_allowance]
        spent = self.budget.spend_up_to(IDEAS_GENERATED, len(all_ideas), note="generation+combination")
        all_ideas = all_ideas[:spent]
        self._record_ideas(all_ideas)
        for idea in all_ideas:
            self.queue.admit(idea, reason="generated this cycle")

        # (5) FILTER: novelty -> data feasibility -> economics.
        # The checker starts with an empty batch: cross-cycle duplicates are
        # already collapsed by content-addressed ids (an identical idea keeps
        # its queue state through `admit`), so seeding it with every idea ever
        # minted would only flag this cycle's ideas against their own past
        # selves as REVIEW_REQUIRED.
        novelty_checker = NoveltyChecker(self.memory, known_ideas=[])
        nov_passed, nov_verdicts = novelty_checker.screen(all_ideas)
        self._reject(all_ideas, nov_passed, nov_verdicts, stage="novelty")

        screen_allowance = self.budget.remaining(IDEAS_SCREENED)
        nov_passed = nov_passed[:screen_allowance]
        self.budget.spend_up_to(IDEAS_SCREENED, len(nov_passed), note="screening")
        for idea in nov_passed:
            self.queue.advance(idea.idea_id, queue_states.SCREENED, reason="passed novelty check")

        feas_passed, feas_verdicts = self.feasibility.screen(nov_passed)
        for verdict in feas_verdicts:
            if not verdict.may_proceed and self.queue.state_of(verdict.idea_id) == queue_states.SCREENED:
                self.queue.advance(verdict.idea_id, queue_states.BLOCKED_DATA, reason=verdict.reason[:400])

        econ_passed, econ_verdicts = self.prefilter.screen(feas_passed)
        for verdict in econ_verdicts:
            if not verdict.may_proceed:
                self.queue.advance(verdict.idea_id, queue_states.REJECTED, reason=verdict.reason[:400])

        # (6) RANK
        ranker = IdeaRanker(family_failure_counts=self.memory.family_failure_counts())
        ranked = ranker.rank(
            econ_passed,
            novelty={v.idea_id: v for v in nov_verdicts},
            feasibility={v.idea_id: v for v in feas_verdicts},
            economics={v.idea_id: v for v in econ_verdicts},
        )

        # (7) DESIGN + (8) QUEUE, bounded by the experiment budget
        experiment_allowance = self.budget.remaining(EXPERIMENTS_REGISTERED)
        feas_map = {v.idea_id: v for v in feas_verdicts}
        econ_map = {v.idea_id: v for v in econ_verdicts}

        designed = 0
        underpowered = 0
        submitted_ids: List[str] = []

        for idea, priority in ranked:
            if designed >= experiment_allowance:
                notes.append(
                    f"experiment budget reached after {designed} design(s); "
                    f"{len(ranked) - designed} ranked idea(s) carried to the next cycle"
                )
                break
            outcome = self.designer.design(
                idea, feasibility=feas_map[idea.idea_id], economics=econ_map[idea.idea_id]
            )
            if not outcome.designed:
                underpowered += 1
                self.queue.advance(idea.idea_id, queue_states.REJECTED, reason=outcome.reason[:400])
                continue

            frozen = self.prereg.register(outcome.spec)
            self.budget.spend(EXPERIMENTS_REGISTERED, 1, note=f"experiment {frozen.experiment_id}")
            designed += 1

            self.queue.advance(
                idea.idea_id,
                queue_states.APPROVED_FOR_RESEARCH,
                reason="experiment designed and pre-registered",
                experiment_id=frozen.experiment_id,
                priority=priority.score,
            )
            self.queue.advance(idea.idea_id, queue_states.QUEUED, reason="awaiting factory capacity")

            # (9) FACTORY hand-off
            if submit:
                self.bridge.submit(frozen)
                self.queue.advance(idea.idea_id, queue_states.RUNNING, reason="submitted to Strategy Factory")
                submitted_ids.append(frozen.experiment_id)

        finished = self._clock()
        report = CycleReport(
            cycle_id=self._cycle_id(started),
            started_at=started,
            finished_at=finished,
            scanned=len(records),
            concepts_known=len(self.knowledge.concepts()),
            generated=len(generation.ideas),
            combined=len(combination.ideas),
            novelty_passed=len(nov_passed),
            feasible=len(feas_passed),
            economically_viable=len(econ_passed),
            ranked=len(ranked),
            designed=designed,
            underpowered_by_design=underpowered,
            submitted=len(submitted_ids),
            budget=self.budget.summary(),
            rejections={
                "generation": generation.summary(),
                "combination": combination.summary(),
                "novelty": _count_verdicts(nov_verdicts),
                "feasibility": _count_verdicts(feas_verdicts),
                "economics": _count_verdicts(econ_verdicts),
            },
            submitted_experiments=tuple(submitted_ids),
            notes=tuple(notes),
        )
        self.cycle_ledger.append({"cycle_id": report.cycle_id, **report.to_dict()})
        return report

    # ------------------------------------------------------- closing the loop

    def ingest_results(self, results: Sequence[FactoryResult]) -> Tuple[FeedbackOutcome, ...]:
        """(10) LEARN — apply Factory verdicts, then the next cycle sees them."""
        outcomes: List[FeedbackOutcome] = []
        ideas = {d["idea_id"]: IdeaSpec.from_dict(d) for d in self.idea_ledger.all()}
        for result in sorted(results, key=lambda r: r.experiment_id):
            self.bridge.receive(result)
            idea = ideas.get(result.idea_id)
            if idea is None:
                continue
            if self.queue.state_of(idea.idea_id) == queue_states.RUNNING:
                self.queue.advance(
                    idea.idea_id, queue_states.FACTORY_RESULT, reason="factory reported a verdict"
                )
            outcomes.append(self.feedback.apply(idea, result))
        return tuple(outcomes)

    # ---------------------------------------------------------------- helpers

    def _prioritise_by_policy(self, ideas: Sequence[IdeaSpec], policy: SearchPolicy) -> List[IdeaSpec]:
        """Order candidates by the adaptive policy before the budget truncates.

        This is the only place the policy has any effect, and it affects which
        ideas get *considered* — never a design or a result that already exists.
        """
        return sorted(ideas, key=lambda i: (-policy.weight_for(i.family), i.idea_id))

    def _record_ideas(self, ideas: Sequence[IdeaSpec]) -> None:
        rows = [i.to_dict() for i in ideas if not self.idea_ledger.has(i.idea_id)]
        if rows:
            self.idea_ledger.append_many(rows)

    def _reject(self, all_ideas, passed, verdicts, *, stage: str) -> None:
        passed_ids = {i.idea_id for i in passed}
        by_id = {v.idea_id: v for v in verdicts}
        for idea in all_ideas:
            if idea.idea_id in passed_ids:
                continue
            verdict = by_id.get(idea.idea_id)
            reason = getattr(verdict, "reason", stage) if verdict else stage
            if self.queue.state_of(idea.idea_id) == queue_states.GENERATED:
                self.queue.advance(idea.idea_id, queue_states.REJECTED, reason=f"{stage}: {reason}"[:400])

    def _cycle_id(self, started: str) -> str:
        from idea_machine.core.ids import mint_id

        return mint_id("CYCLE", {"t": started, "n": self.cycle_ledger.count()})

    # ---------------------------------------------------------------- reports

    def status(self) -> Dict[str, Any]:
        return {
            "sources": self.scanner.summary(),
            "knowledge": self.knowledge.summary(),
            "queue": self.queue.summary(),
            "preregistration": self.prereg.summary(),
            "factory": self.bridge.summary(),
            "failure_memory": self.memory.summary(),
            "budget": self.budget.summary(),
            "cycles_run": self.cycle_ledger.count(),
        }

    def verify_integrity(self) -> None:
        """Re-read every ledger and confirm nothing has been rewritten."""
        for store in (
            self.scanner.store, self.knowledge.store, self.memory.store,
            self.prereg.store, self.bridge.store, self.budget.store,
            self.idea_ledger, self.cycle_ledger,
        ):
            store.verify_integrity()
        self.queue.verify_integrity()
        guard.assert_source_tree_clean()


def _count_verdicts(verdicts: Sequence[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    return dict(sorted(counts.items()))
