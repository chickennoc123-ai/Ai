"""IDEA MACHINE — a research-idea generator that feeds the Strategy Factory.

    INTERNET / PAPERS / DATA
             |
        WORLD SCANNER  -> KNOWLEDGE BASE -> IDEA GENERATOR -> COMBINATION
             |            NOVELTY -> FEASIBILITY -> ECONOMICS -> RANKING
             |            EXPERIMENT DESIGNER -> IDEA QUEUE
             v
      STRATEGY FACTORY   (unchanged, and the only authority on validity)
             |
        PASS / FAIL / BLOCKED -> FEEDBACK -> KNOWLEDGE BASE -> (repeat)

This package is strictly **upstream** of the Strategy Factory. It proposes;
the Factory disposes. It cannot read the sealed holdout, authorize GEN14,
produce an EA, edit the cost model, reset a ledger, rewrite failure history, or
call anything an edge — those attempts raise
:class:`~idea_machine.core.errors.GovernanceViolation`, which nothing in this
package catches.

Start at :class:`idea_machine.pipeline.IdeaMachine`.
"""

from __future__ import annotations

__all__ = ["IdeaMachine", "IdeaSpec", "ExperimentSpec", "GovernanceViolation"]

__version__ = "1.0.0"


def __getattr__(name: str):
    # Lazy re-exports keep ``import idea_machine`` cheap and avoid a circular
    # import between the pipeline and the modules it assembles.
    if name == "IdeaMachine":
        from idea_machine.pipeline import IdeaMachine

        return IdeaMachine
    if name == "IdeaSpec":
        from idea_machine.core.idea_spec import IdeaSpec

        return IdeaSpec
    if name == "ExperimentSpec":
        from idea_machine.experiment.spec import ExperimentSpec

        return ExperimentSpec
    if name == "GovernanceViolation":
        from idea_machine.core.errors import GovernanceViolation

        return GovernanceViolation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
