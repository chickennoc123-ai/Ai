"""Hypothesis record + registry — the Strategy Factory's external-source intake ledger.

Per ``ML-001-STRATEGY-FACTORY-SPEC.md`` §9/§10 (Hypothesis Sources) and
``ML-001-HYPOTHESIS-SOURCE-CONTRACT.md``: a trading idea from any external
source (a paper, a book, a website, a YouTube video, user research) may be
captured as a ``HypothesisRecord`` so the Factory has somewhere to put it
— but capturing a claim is never the same thing as validating it.
**A hypothesis's own ``evidence_level`` can never assert more than
"someone claimed this"** until an actual ``StrategyCandidate`` is
generated from it, registered in ``StrategyRegistry``, and tested through
the real pipeline; this module contains no economic logic and computes no
trading result — it only records provenance of *where an idea came from*
and links it, once real testing exists, to the candidate(s) it produced.

Nothing in this module ingests anything automatically. It exists so that,
when a hypothesis IS captured (a future, separate action — not performed
by this commit), it has a place to go that keeps its own unverified claim
textually and structurally distinct from any subsequent, independently
generated test evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_HYPOTHESIS_REGISTRY_PATH = Path("reports/factory/hypothesis_registry.json")

#: Where a trading idea may have come from (ML-001-HYPOTHESIS-SOURCE-CONTRACT.md §2).
SOURCE_TYPES = frozenset(
    {
        "USER_RESEARCH",
        "ACADEMIC_PAPER",
        "BOOK",
        "WEBSITE",
        "PUBLIC_STRATEGY_DESCRIPTION",
        "YOUTUBE",
        "OTHER_DOCUMENTED_SOURCE",
    }
)

#: How much this hypothesis has actually been substantiated by real testing
#: (ML-001-HYPOTHESIS-SOURCE-CONTRACT.md §5). Ordered roughly weakest to
#: strongest, but nothing in this module enforces monotonic progression —
#: that discipline lives in ``HypothesisRegistry.update_evidence_level``,
#: which appends to history rather than silently overwriting, and in the
#: separate, real ``StrategyRegistry`` pipeline that actually produces the
#: only evidence capable of justifying anything past ``UNVALIDATED_CLAIM``.
EVIDENCE_LEVELS = frozenset(
    {
        "UNVALIDATED_CLAIM",  # captured, not yet formalized into a testable rule
        "FORMALIZED_UNTESTED",  # a concrete trading rule exists, no candidate registered yet
        "CANDIDATE_GENERATED",  # a StrategyCandidate exists in the Factory registry
        "CANDIDATE_TESTED_NO_EDGE",  # tested, evidence says no edge (e.g. STRAT-000001's outcome)
        "CANDIDATE_TESTED_EDGE_NOT_PROVEN",  # tested, inconclusive/insufficient evidence
        "CANDIDATE_HOLDOUT_PASSED",  # the linked candidate passed PURE_HOLDOUT + EVG
    }
)

#: A hypothesis may never be CAPTURED already claiming validated evidence
#: -- those levels can only be reached later, via update_evidence_level,
#: after a real candidate has actually produced that evidence.
_LEVELS_FORBIDDEN_AT_CAPTURE = frozenset(
    {
        "CANDIDATE_GENERATED",
        "CANDIDATE_TESTED_NO_EDGE",
        "CANDIDATE_TESTED_EDGE_NOT_PROVEN",
        "CANDIDATE_HOLDOUT_PASSED",
    }
)


class HypothesisSpecError(EAFactoryError):
    """Raised when a HypothesisRecord is incomplete or self-contradictory."""


class HypothesisNotFoundError(EAFactoryError):
    pass


class DuplicateHypothesisError(EAFactoryError):
    pass


class HypothesisRegistryCorruptionError(EAFactoryError):
    """Raised when the on-disk hypothesis registry file is not valid JSON."""


@dataclass
class HypothesisRecord:
    """One captured trading idea and its provenance.

    Deliberately NOT a frozen dataclass — ``transformation_history`` and
    ``candidate_ids`` grow over the hypothesis's life (formalization,
    candidate generation, re-formalization), and this module's discipline
    is enforced by ``HypothesisRegistry`` always appending rather than
    letting a caller silently overwrite, not by Python-level immutability.
    The one field this module treats as load-bearing is ``original_claim``
    — never rewritten once set, so the source's own words remain
    distinguishable from anything formalized or tested afterward.
    """

    hypothesis_id: str
    source_type: str
    source_reference: str
    original_claim: str
    date_captured: str
    assumptions: Tuple[str, ...] = ()
    formalized_trading_rule: Optional[str] = None
    evidence_level: str = "UNVALIDATED_CLAIM"
    transformation_history: List[Dict[str, Any]] = field(default_factory=list)
    candidate_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise HypothesisSpecError(
                "unknown source_type", source_type=self.source_type, allowed=sorted(SOURCE_TYPES)
            )
        if not self.source_reference or not str(self.source_reference).strip():
            raise HypothesisSpecError("source_reference is required")
        if not self.original_claim or not str(self.original_claim).strip():
            raise HypothesisSpecError("original_claim is required")
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise HypothesisSpecError(
                "unknown evidence_level", evidence_level=self.evidence_level, allowed=sorted(EVIDENCE_LEVELS)
            )
        if self.evidence_level in _LEVELS_FORBIDDEN_AT_CAPTURE and not self.transformation_history:
            # a hypothesis constructed directly (not via the registry's
            # normal register()+update flow) must not claim tested-level
            # evidence out of the gate with nothing behind that claim.
            raise HypothesisSpecError(
                "evidence_level implies real test evidence but transformation_history is empty",
                evidence_level=self.evidence_level,
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["assumptions"] = list(self.assumptions)
        d["candidate_ids"] = list(self.candidate_ids)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "HypothesisRecord":
        d = dict(d)
        d["assumptions"] = tuple(d.get("assumptions", ()))
        d["candidate_ids"] = tuple(d.get("candidate_ids", ()))
        d["transformation_history"] = list(d.get("transformation_history", []))
        return HypothesisRecord(**d)


class HypothesisRegistry:
    """Durable, file-backed ledger of captured hypotheses.

    Mirrors ``core.factory.registry.StrategyRegistry``'s persistence
    pattern (single atomically-written JSON file) deliberately, so the two
    registries are equally auditable/diffable, but is intentionally a
    separate file and a separate class: a hypothesis is source provenance,
    a ``StrategyCandidate`` is tested economic evidence, and conflating
    their storage would make it easy to accidentally conflate their
    meaning too.
    """

    def __init__(self, path: Path = DEFAULT_HYPOTHESIS_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._hypotheses: Dict[str, HypothesisRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise HypothesisRegistryCorruptionError(
                "hypothesis registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._next_id = raw.get("next_id", 1)
        self._hypotheses = {
            hid: HypothesisRecord.from_dict(hdata) for hid, hdata in raw.get("hypotheses", {}).items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "hypotheses": {hid: h.to_dict() for hid, h in self._hypotheses.items()},
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def allocate_hypothesis_id(self) -> str:
        hid = f"HYP-{self._next_id:06d}"
        self._next_id += 1
        self._save()
        return hid

    def register(
        self,
        *,
        source_type: str,
        source_reference: str,
        original_claim: str,
        assumptions: Tuple[str, ...] = (),
        hypothesis_id: Optional[str] = None,
    ) -> HypothesisRecord:
        """Capture a new hypothesis. Always starts at ``UNVALIDATED_CLAIM`` —
        callers cannot pass a higher evidence_level here; that can only be
        reached later, through ``update_evidence_level``, once real testing
        exists to justify it."""
        hid = hypothesis_id or self.allocate_hypothesis_id()
        if hid in self._hypotheses:
            raise DuplicateHypothesisError("hypothesis_id already registered", hypothesis_id=hid)
        record = HypothesisRecord(
            hypothesis_id=hid,
            source_type=source_type,
            source_reference=source_reference,
            original_claim=original_claim,
            date_captured=utcnow().isoformat(),
            assumptions=tuple(assumptions),
            evidence_level="UNVALIDATED_CLAIM",
            transformation_history=[
                {"timestamp": utcnow().isoformat(), "event": "captured", "detail": "hypothesis registered"}
            ],
        )
        self._hypotheses[hid] = record
        self._save()
        return record

    def get(self, hypothesis_id: str) -> HypothesisRecord:
        try:
            return self._hypotheses[hypothesis_id]
        except KeyError as exc:
            raise HypothesisNotFoundError("no such hypothesis", hypothesis_id=hypothesis_id) from exc

    def formalize(self, hypothesis_id: str, *, formalized_trading_rule: str, reason: str = "") -> HypothesisRecord:
        """Attach a concrete, testable trading rule. Advances evidence_level
        to FORMALIZED_UNTESTED (only from UNVALIDATED_CLAIM — you cannot
        re-formalize a hypothesis that already has candidates without going
        through the same append-only history)."""
        record = self.get(hypothesis_id)
        record.formalized_trading_rule = formalized_trading_rule
        if record.evidence_level == "UNVALIDATED_CLAIM":
            record.evidence_level = "FORMALIZED_UNTESTED"
        record.transformation_history.append(
            {
                "timestamp": utcnow().isoformat(),
                "event": "formalized",
                "detail": reason or "trading rule formalized",
            }
        )
        self._save()
        return record

    def link_candidate(self, hypothesis_id: str, candidate_id: str) -> HypothesisRecord:
        """Record that ``candidate_id`` (a real ``core.factory.registry
        .StrategyRegistry`` candidate) was generated from this hypothesis.
        Advances evidence_level to CANDIDATE_GENERATED if not already at
        least that far. Idempotent — linking the same candidate twice does
        not duplicate it in ``candidate_ids``."""
        record = self.get(hypothesis_id)
        if candidate_id not in record.candidate_ids:
            record.candidate_ids = record.candidate_ids + (candidate_id,)
        if record.evidence_level in ("UNVALIDATED_CLAIM", "FORMALIZED_UNTESTED"):
            record.evidence_level = "CANDIDATE_GENERATED"
        record.transformation_history.append(
            {
                "timestamp": utcnow().isoformat(),
                "event": "candidate_linked",
                "detail": candidate_id,
            }
        )
        self._save()
        return record

    def update_evidence_level(self, hypothesis_id: str, new_level: str, *, reason: str) -> HypothesisRecord:
        """The ONLY sanctioned way to change ``evidence_level`` after
        capture — always appends to ``transformation_history``, never
        silently overwrites. Raises if ``new_level`` is not a recognized
        level (no free-text evidence claims)."""
        if new_level not in EVIDENCE_LEVELS:
            raise HypothesisSpecError("unknown evidence_level", evidence_level=new_level, allowed=sorted(EVIDENCE_LEVELS))
        record = self.get(hypothesis_id)
        old_level = record.evidence_level
        record.evidence_level = new_level
        record.transformation_history.append(
            {
                "timestamp": utcnow().isoformat(),
                "event": "evidence_level_changed",
                "detail": f"{old_level} -> {new_level}: {reason}",
            }
        )
        self._save()
        return record

    def list_all(self) -> List[HypothesisRecord]:
        return list(self._hypotheses.values())

    def summary(self) -> Dict[str, Any]:
        by_level: Dict[str, int] = {}
        for h in self._hypotheses.values():
            by_level[h.evidence_level] = by_level.get(h.evidence_level, 0) + 1
        return {
            "total_hypotheses_ingested": len(self._hypotheses),
            "by_evidence_level": by_level,
        }
