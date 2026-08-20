"""Feedback Engine (Phase 12) — turning verdicts into knowledge.

    Factory -> Result -> failure/survivor analysis -> knowledge update -> Idea Machine

The distinction this module refuses to blur:

    FAIL          the mechanism did not pay for itself. Search space narrows.
    REFUTED       the mechanism is wrong. Search space closes.
    UNDERPOWERED  the experiment was too small. Search space does NOT close.
    BLOCKED       the data was not there. Search space does NOT close.
    SURVIVOR      the Factory's tests did not refute it. NOT "an edge".

``UNDERPOWERED != FAIL`` is stated in the roadmap and enforced here: an
underpowered verdict writes an ``UNDERPOWERED`` epistemic state and a failure
entry marked reopenable, so the novelty checker will let the idea back through
once more data exists. Folding it into FAIL would permanently blacklist regions
the machine never actually examined.

What is *not* fed back: performance numbers. Results carry an evidence
reference, not a Sharpe ratio, so holdout performance cannot steer future
research through this channel. What is fed back is the mechanism, the reason,
and a prevention rule — the parts that generalise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from idea_machine.core import epistemic
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.governance import guard
from idea_machine.integration.factory_bridge import FactoryResult
from idea_machine.knowledge.base import Finding, KnowledgeBase
from idea_machine.novelty.memory import FailureEntry, FailureMemory
from idea_machine.queue.queue import IdeaQueue
from utils.helpers import isoformat

#: Factory verdict -> (epistemic state, queue state, closes search space?)
_VERDICT_MAP: Mapping[str, Tuple[str, str, bool]] = {
    "REFUTED": (epistemic.REFUTED, "REFUTED", True),
    "FAIL": (epistemic.TESTED, "FAIL", False),
    "SURVIVED": (epistemic.SURVIVED, "SURVIVOR", False),
    "SURVIVOR": (epistemic.SURVIVED, "SURVIVOR", False),
    "UNDERPOWERED": (epistemic.UNDERPOWERED, "UNDERPOWERED", False),
    "BLOCKED": (epistemic.BLOCKED, "BLOCKED", False),
}

#: What each verdict teaches, phrased so a future idea can be checked against it.
_PREVENTION_RULES: Mapping[str, str] = {
    "REFUTED": (
        "Do not propose this mechanism at this horizon again. A new proposal in this family must "
        "identify a DIFFERENT mechanism, not a different threshold."
    ),
    "FAIL": (
        "Before proposing this mechanism again, show that the expected effect clears cost at the "
        "proposed horizon by a wider margin than last time -- the same idea at the same horizon "
        "will fail the same way."
    ),
    "UNDERPOWERED": (
        "Do not re-run this design until the usable sample is materially larger. Re-running an "
        "underpowered design produces another underpowered result, not an answer."
    ),
    "BLOCKED": (
        "Acquire and validate the missing data before this idea is queued again. Do not substitute "
        "a proxy series without re-deriving the mechanism for that proxy."
    ),
    "SURVIVOR": (
        "Not refuted is not proven. Any further claim about this idea comes from the Strategy "
        "Factory's own gates, never from the Idea Machine."
    ),
}


@dataclass(frozen=True)
class FeedbackOutcome:
    idea_id: str
    verdict: str
    epistemic_state: str
    queue_state: str
    closed_search_space: bool
    knowledge_finding_id: str
    failure_entry_id: str
    lesson: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "verdict": self.verdict,
            "epistemic_state": self.epistemic_state,
            "queue_state": self.queue_state,
            "closed_search_space": self.closed_search_space,
            "knowledge_finding_id": self.knowledge_finding_id,
            "failure_entry_id": self.failure_entry_id,
            "lesson": self.lesson,
        }


class FeedbackEngine:
    """Applies a Factory verdict to the queue, failure memory, and knowledge."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeBase,
        memory: FailureMemory,
        queue: IdeaQueue,
        clock=isoformat,
    ) -> None:
        self.knowledge = knowledge
        self.memory = memory
        self.queue = queue
        self._clock = clock

    def apply(self, idea: IdeaSpec, result: FactoryResult) -> FeedbackOutcome:
        guard.require("RECORD_FEEDBACK", idea_id=idea.idea_id, verdict=result.verdict)

        if result.idea_id != idea.idea_id:
            raise ValueError(
                f"result is for {result.idea_id}, not {idea.idea_id}"
            )

        epistemic_state, queue_state, closes = _VERDICT_MAP[result.verdict]
        signature = idea.mechanism_signature()
        lesson = _PREVENTION_RULES.get(result.verdict, "")

        # 1. Queue -- requires the Factory's evidence reference, always.
        if self.queue.state_of(idea.idea_id) is not None:
            self.queue.advance(
                idea.idea_id,
                queue_state,
                reason=f"factory verdict {result.verdict}: {result.reason}"[:500],
                evidence_reference=result.evidence_reference,
            )

        # 2. Failure memory. SURVIVOR is recorded too -- knowing what was tried
        #    and not refuted is as useful for targeting as knowing what failed.
        entry = self.memory.record(
            FailureEntry(
                idea_id=idea.idea_id,
                family=idea.family,
                mechanism_signature=signature,
                horizon=idea.holding_period,
                outcome="SURVIVED" if queue_state == "SURVIVOR" else result.verdict,
                reason=result.reason or f"factory verdict {result.verdict}",
                prevention_rule=lesson,
                scope=(
                    f"{idea.family} / {idea.holding_period} / {'/'.join(idea.instruments)}; "
                    f"evidence: {result.evidence_reference}"
                ),
                recorded_at=self._clock(),
            )
        )

        # 3. Knowledge base. The state machine walks KNOWN -> TESTED -> outcome;
        #    creating a finding directly at a terminal state is rejected, so the
        #    path an idea took stays visible.
        finding_id = self._update_knowledge(idea, signature, epistemic_state, result)

        return FeedbackOutcome(
            idea_id=idea.idea_id,
            verdict=result.verdict,
            epistemic_state=epistemic_state,
            queue_state=queue_state,
            closed_search_space=closes,
            knowledge_finding_id=finding_id,
            failure_entry_id=entry.entry_id,
            lesson=lesson,
        )

    def _update_knowledge(
        self, idea: IdeaSpec, signature: str, target_state: str, result: FactoryResult
    ) -> str:
        current = self.knowledge.state_of(
            family=idea.family, mechanism_signature=signature, horizon=idea.holding_period
        )
        statement_base = f"{idea.family}/{idea.holding_period}: {idea.hypothesis}"
        evidence = (result.evidence_reference,)

        def write(state: str, statement: str) -> Finding:
            return self.knowledge.record_finding(
                Finding(
                    family=idea.family,
                    mechanism_signature=signature,
                    horizon=idea.holding_period,
                    state=state,
                    statement=statement,
                    evidence_refs=evidence,
                    updated_at=self._clock(),
                )
            )

        if current == epistemic.UNKNOWN:
            write(epistemic.KNOWN, f"{statement_base} -- proposed and queued")
            current = epistemic.KNOWN

        if target_state == epistemic.BLOCKED:
            return write(epistemic.BLOCKED, f"{statement_base} -- blocked: {result.reason}").finding_id

        if current in (epistemic.KNOWN, epistemic.BLOCKED, epistemic.UNDERPOWERED, epistemic.SURVIVED):
            write(epistemic.TESTED, f"{statement_base} -- experiment completed")
            current = epistemic.TESTED

        if target_state == epistemic.TESTED:
            # A FAIL is a completed test whose effect did not cover cost. It
            # narrows the search space without closing it, so the finding stays
            # at TESTED rather than being upgraded to REFUTED.
            return write(
                epistemic.TESTED,
                f"{statement_base} -- did not cover cost: {result.reason}",
            ).finding_id

        return write(target_state, f"{statement_base} -- {result.verdict}: {result.reason}").finding_id

    def apply_many(
        self, ideas: Mapping[str, IdeaSpec], results: Tuple[FactoryResult, ...]
    ) -> Tuple[FeedbackOutcome, ...]:
        out: List[FeedbackOutcome] = []
        for result in sorted(results, key=lambda r: r.experiment_id):
            idea = ideas.get(result.idea_id)
            if idea is None:
                continue
            out.append(self.apply(idea, result))
        return tuple(out)

    def summary(self) -> Dict[str, Any]:
        return {
            "failure_memory": self.memory.summary(),
            "knowledge": self.knowledge.summary(),
            "queue": self.queue.counts(),
        }
