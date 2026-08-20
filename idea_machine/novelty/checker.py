"""Novelty check (Phase 5) — is this worth a research slot at all?

The pipeline the roadmap describes, in order:

    already tested? -> duplicate? -> near-duplicate? -> refuted family?
    -> known failure mode?

with three verdicts:

* ``NOVEL`` — nothing in memory matches; proceed.
* ``REVIEW_REQUIRED`` — similar to something already examined. Not rejected,
  but flagged, because "similar" is a judgement call and the machine should not
  quietly discard an idea on a similarity score alone.
* ``REJECTED_SEARCH_SPACE`` — this exact mechanism was refuted. Testing it again
  produces no information, and re-testing a refuted idea with a nudged
  parameter is the p-hacking loop Phase 16 forbids outright.

An idea whose earlier attempt was ``UNDERPOWERED`` or ``BLOCKED`` comes back as
``NOVEL`` with the reason attached — the search space was never closed, only
deferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from idea_machine.core.ids import jaccard
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.governance import guard
from idea_machine.novelty.memory import FailureMemory

NOVEL = "NOVEL"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REJECTED_SEARCH_SPACE = "REJECTED_SEARCH_SPACE"

#: Above this mechanism-text similarity, two ideas are "the same idea, reworded".
NEAR_DUPLICATE_THRESHOLD = 0.85

#: Above this, they are close enough that a human should look before a research
#: slot is spent on both.
REVIEW_THRESHOLD = 0.70


@dataclass(frozen=True)
class NoveltyVerdict:
    idea_id: str
    verdict: str
    reason: str
    matched_idea_id: str = ""
    similarity: float = 0.0
    reopened_from: str = ""

    @property
    def may_proceed(self) -> bool:
        """REVIEW_REQUIRED still proceeds — flagged, not discarded."""
        return self.verdict in (NOVEL, REVIEW_REQUIRED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "matched_idea_id": self.matched_idea_id,
            "similarity": round(self.similarity, 4),
            "reopened_from": self.reopened_from,
        }


class NoveltyChecker:
    """Screens ideas against failure memory and against each other."""

    def __init__(
        self,
        memory: FailureMemory,
        *,
        known_ideas: Sequence[IdeaSpec] = (),
        near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
        review_threshold: float = REVIEW_THRESHOLD,
    ) -> None:
        self.memory = memory
        self.near_duplicate_threshold = near_duplicate_threshold
        self.review_threshold = review_threshold
        self._known: List[IdeaSpec] = list(known_ideas)
        self._known_ids = {i.idea_id for i in self._known}

    def check(self, idea: IdeaSpec) -> NoveltyVerdict:
        guard.require("CHECK_NOVELTY", idea_id=idea.idea_id)
        signature = idea.mechanism_signature()

        # 1. Refuted search space -- terminal.
        if self.memory.is_closed(mechanism_signature=signature, horizon=idea.holding_period):
            return NoveltyVerdict(
                idea.idea_id,
                REJECTED_SEARCH_SPACE,
                "this mechanism/horizon was refuted; re-testing it yields no information",
            )

        # 2. Exact duplicate of something already known this run or before.
        if idea.idea_id in self._known_ids:
            return NoveltyVerdict(
                idea.idea_id, REVIEW_REQUIRED, "exact duplicate of an idea already in the batch",
                matched_idea_id=idea.idea_id, similarity=1.0,
            )

        # 3. Near-duplicate by mechanism text.
        best_id, best_sim = self._closest(idea)
        if best_sim >= self.near_duplicate_threshold:
            return NoveltyVerdict(
                idea.idea_id, REVIEW_REQUIRED,
                "near-duplicate of an idea already under consideration",
                matched_idea_id=best_id, similarity=best_sim,
            )

        # 4. An earlier attempt that stalled recoverably -- novel, with context.
        reopened = self.memory.reopenable_reason(
            mechanism_signature=signature, horizon=idea.holding_period
        )
        if reopened:
            return NoveltyVerdict(
                idea.idea_id, NOVEL,
                "previously attempted but never refuted; the search space stayed open",
                reopened_from=reopened,
            )

        if best_sim >= self.review_threshold:
            return NoveltyVerdict(
                idea.idea_id, REVIEW_REQUIRED,
                "similar to an idea already under consideration; worth a look before "
                "spending two research slots",
                matched_idea_id=best_id, similarity=best_sim,
            )

        return NoveltyVerdict(idea.idea_id, NOVEL, "no prior match in failure memory or batch")

    def _closest(self, idea: IdeaSpec) -> Tuple[str, float]:
        best_id, best = "", 0.0
        for other in self._known:
            if other.family != idea.family or other.holding_period != idea.holding_period:
                continue
            sim = jaccard(idea.mechanism, other.mechanism)
            if sim > best:
                best_id, best = other.idea_id, sim
        return best_id, best

    def remember(self, idea: IdeaSpec) -> None:
        """Add ``idea`` to the batch so later ideas dedupe against it."""
        if idea.idea_id not in self._known_ids:
            self._known.append(idea)
            self._known_ids.add(idea.idea_id)

    def screen(self, ideas: Sequence[IdeaSpec]) -> Tuple[Tuple[IdeaSpec, ...], Tuple[NoveltyVerdict, ...]]:
        """Screen a whole batch. Returns (ideas that may proceed, all verdicts)."""
        passed: List[IdeaSpec] = []
        verdicts: List[NoveltyVerdict] = []
        for idea in sorted(ideas, key=lambda i: i.idea_id):
            verdict = self.check(idea)
            verdicts.append(verdict)
            if verdict.may_proceed:
                passed.append(idea)
                self.remember(idea)
        return tuple(passed), tuple(verdicts)
