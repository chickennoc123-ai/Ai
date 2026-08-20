"""Adaptive search (Phase 13) — learning where to look next.

After enough cycles the machine should be able to answer: which families
produce useful hypotheses, which sources are worth scanning, which mechanisms
keep failing, which combinations remain unexplored, and where budget is being
wasted.

The rule that makes this safe is stated in the roadmap and enforced here:

    *Feedback may only influence FUTURE search. It may never reach back and
    modify an experiment that has already been designed or run.*

So this module is strictly read-only over history. It computes weights; it does
not touch the pre-registration ledger, the queue, or any completed experiment.
:class:`SearchPolicy` is a plain value object handed to the *next* cycle.

It also only ever reads *counts and verdicts*, never performance numbers —
which is what stops holdout results from steering research targeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from idea_machine.core.families import FAMILY_NAMES
from idea_machine.governance import guard
from idea_machine.knowledge.base import KnowledgeBase
from idea_machine.novelty.memory import FailureMemory
from idea_machine.queue.queue import IdeaQueue

#: Weight floor. A family is never driven to zero: a mechanism class that has
#: failed ten times may still be the one that works on the eleventh, and a hard
#: zero would make that permanently untestable.
MIN_WEIGHT = 0.10
MAX_WEIGHT = 2.00


@dataclass(frozen=True)
class SearchPolicy:
    """Guidance for the *next* cycle. Never applied retroactively."""

    family_weights: Mapping[str, float]
    exhausted_mechanisms: Tuple[str, ...]
    reopenable_mechanisms: Tuple[str, ...]
    productive_sources: Tuple[str, ...]
    unexplored_families: Tuple[str, ...]
    wasted_budget_signals: Tuple[str, ...]
    generated_at: str = ""

    def weight_for(self, family: str) -> float:
        return float(self.family_weights.get(family, 1.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family_weights": {k: round(v, 3) for k, v in sorted(self.family_weights.items())},
            "exhausted_mechanisms": list(self.exhausted_mechanisms),
            "reopenable_mechanisms": list(self.reopenable_mechanisms),
            "productive_sources": list(self.productive_sources),
            "unexplored_families": list(self.unexplored_families),
            "wasted_budget_signals": list(self.wasted_budget_signals),
            "generated_at": self.generated_at,
        }


class AdaptiveSearch:
    """Reads history, emits a policy for the next cycle. Writes nothing."""

    def __init__(
        self,
        *,
        memory: FailureMemory,
        knowledge: KnowledgeBase,
        queue: IdeaQueue,
    ) -> None:
        self.memory = memory
        self.knowledge = knowledge
        self.queue = queue

    def derive_policy(self, *, at: str = "") -> SearchPolicy:
        entries = self.memory.entries()

        outcomes_by_family: Dict[str, Dict[str, int]] = {}
        for e in entries:
            bucket = outcomes_by_family.setdefault(e.family, {})
            bucket[e.outcome] = bucket.get(e.outcome, 0) + 1

        weights: Dict[str, float] = {}
        wasted: List[str] = []
        for family in FAMILY_NAMES:
            bucket = outcomes_by_family.get(family, {})
            tested = sum(bucket.values())
            if tested == 0:
                weights[family] = 1.0
                continue

            refuted = bucket.get("REFUTED", 0)
            survived = bucket.get("SURVIVED", 0)
            underpowered = bucket.get("UNDERPOWERED", 0)
            blocked = bucket.get("BLOCKED", 0)
            # A FAIL narrows the search space (this mechanism did not pay at
            # this horizon) without closing it, so it counts toward the penalty
            # alongside outright economic rejections.
            failed_econ = bucket.get("FAILED_ECONOMICS", 0) + bucket.get("FAIL", 0)

            # Refutations and economic failures reduce weight. Underpowered and
            # blocked results do NOT: they say the machine could not look, not
            # that there was nothing there.
            informative = refuted + failed_econ + survived
            penalty = (refuted + failed_econ) / max(informative, 1)
            reward = survived / max(informative, 1)
            weight = 1.0 - 0.7 * penalty + 0.8 * reward
            weights[family] = max(MIN_WEIGHT, min(MAX_WEIGHT, weight))

            if underpowered >= 3:
                wasted.append(
                    f"{family}: {underpowered} underpowered verdicts -- designs are being queued "
                    "that the available sample cannot resolve; tighten the power check rather "
                    "than spending more slots"
                )
            if blocked >= 3:
                wasted.append(
                    f"{family}: {blocked} blocked verdicts -- ideas are being generated against "
                    "data that does not exist; the data catalog should gate generation earlier"
                )
            if refuted >= 5 and survived == 0:
                wasted.append(
                    f"{family}: {refuted} refutations and no survivors -- this mechanism class "
                    "looks exhausted at the horizons tried so far"
                )

        exhausted = tuple(sorted({e.mechanism_signature for e in entries if e.closes_search_space}))
        reopenable = tuple(
            sorted(
                {
                    e.mechanism_signature
                    for e in entries
                    if e.outcome in ("UNDERPOWERED", "BLOCKED")
                    and not self.memory.is_closed(
                        mechanism_signature=e.mechanism_signature, horizon=e.horizon
                    )
                }
            )
        )

        return SearchPolicy(
            family_weights=weights,
            exhausted_mechanisms=exhausted,
            reopenable_mechanisms=reopenable,
            productive_sources=self._productive_sources(),
            unexplored_families=tuple(
                f for f in FAMILY_NAMES if f not in outcomes_by_family
            ),
            wasted_budget_signals=tuple(wasted),
            generated_at=at,
        )

    def _productive_sources(self) -> Tuple[str, ...]:
        """Sources whose concepts actually reached a tested idea.

        Counted by *participation*, not by result quality, so a source is not
        rewarded for having produced a profitable-looking idea — only for
        having produced a testable one.
        """
        counts: Dict[str, int] = {}
        for edge in self.knowledge.edges():
            for sid in edge.source_ids:
                counts[sid] = counts.get(sid, 0) + 1
        return tuple(k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20])

    def apply_to_experiment(self, *_: Any, **__: Any) -> None:
        """Forbidden. Feedback influences future search only.

        Present as a named method so that reaching for it crashes rather than
        quietly editing an experiment that has already been designed or run.
        """
        guard.forbid(
            "MUTATE_PREREGISTRATION",
            detail="adaptive search may only shape the NEXT cycle, never a completed experiment",
        )

    def report(self, *, at: str = "") -> Dict[str, Any]:
        policy = self.derive_policy(at=at)
        return {
            "policy": policy.to_dict(),
            "where_we_are_searching": [
                f for f, w in sorted(policy.family_weights.items(), key=lambda kv: -kv[1]) if w > 1.0
            ],
            "where_we_proved_it_does_not_work": list(policy.exhausted_mechanisms),
            "where_we_never_actually_looked": list(policy.reopenable_mechanisms),
        }
