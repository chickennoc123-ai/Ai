"""Idea Machine exception hierarchy.

Every error raised inside ``idea_machine`` derives from
:class:`~utils.exceptions.EAFactoryError` so the repository keeps a single
catchable base class at process boundaries.

One exception is deliberately special: :class:`GovernanceViolation`. Phase 16
of the roadmap says the Idea Machine must be *unable* to step outside its
authority, and Phase 18 requires that it "self-crash if it tries to bypass
governance". That is implemented as a hard rule, enforced by
``tests/test_governance_uncatchable.py``:

    **No module inside ``idea_machine`` may catch GovernanceViolation, and no
    module inside ``idea_machine`` may use a bare ``except:`` or a broad
    ``except Exception:`` that would swallow it by accident.**

A governance violation therefore always propagates out of the whole machine
and terminates the run. It is not a control-flow signal; it means the code
attempted something it is structurally forbidden from doing.
"""

from __future__ import annotations

from utils.exceptions import EAFactoryError


class IdeaMachineError(EAFactoryError):
    """Base class for every recoverable Idea Machine failure."""


class GovernanceViolation(IdeaMachineError):
    """The Idea Machine attempted an action outside its authority.

    Never caught inside ``idea_machine``. See the module docstring.
    """


class SpecValidationError(IdeaMachineError):
    """An IdeaSpec / ExperimentSpec is incomplete or self-contradictory."""


class ImmutabilityError(IdeaMachineError):
    """An attempt was made to mutate a frozen / pre-registered record."""


class StoreError(IdeaMachineError):
    """An append-only store is missing, corrupt, or was asked to rewrite history."""


class ProvenanceError(IdeaMachineError):
    """A record cannot demonstrate where it came from."""


class KnowledgeError(IdeaMachineError):
    """An illegal knowledge-state assertion or transition."""


class QueueError(IdeaMachineError):
    """An illegal idea-queue transition."""


class BudgetExhausted(IdeaMachineError):
    """The research budget for this window is spent."""
