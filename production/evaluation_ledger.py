"""Evaluation Ledger: idempotency guard in front of the real Factory.

The audit (PRODUCTION_MODE_AUDIT.md) found that
idea_machine.real_factory_integration.RealFactoryIntegrator has no id-based
check against prior evaluations -- resubmitting the same (mechanism,
instrument, driver, window) triple across two runs (two `search-cycle`
invocations, or a crash-and-restart) would silently re-run the real gate()
and double-record the result.

This ledger closes that gap WITHOUT touching RealFactoryIntegrator's own
logic (which stays exactly as tested): before submitting a candidate to the
real Factory, the production loop checks `already_evaluated()`; only if it
returns None does it proceed to pre-register + evaluate, then calls
`record()` with the real, already-computed verdict.

The record id is a content hash of the (mechanism, instrument, driver,
window) triple ONLY -- so two submissions of the exact same triple always
resolve to the exact same ledger id, and AppendOnlyStore's own idempotency
(identical content under an existing id is a silent no-op; different
content under an existing id raises) becomes the actual duplicate-detection
mechanism, not a separate lookup table that could drift out of sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from idea_machine.core.errors import StoreError
from idea_machine.core.ids import mint_id
from idea_machine.core.store import AppendOnlyStore

DEFAULT_LEDGER_PATH = Path("reports/production/evaluation_ledger.json")


def evaluation_id(mechanism: str, instrument: str, driver: Optional[str], window_min: int) -> str:
    return mint_id("EVAL", {"mechanism": mechanism, "instrument": instrument,
                            "driver": driver or "", "window_min": window_min})


@dataclass(frozen=True)
class EvaluationRecord:
    eval_id: str
    mechanism: str
    instrument: str
    driver: Optional[str]
    window_min: int
    hyp_id: str
    cycle_id: str
    verdict: str
    final_status: str
    train: Dict[str, Any]
    validation: Dict[str, Any]
    evaluated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eval_id": self.eval_id, "mechanism": self.mechanism, "instrument": self.instrument,
            "driver": self.driver, "window_min": self.window_min, "hyp_id": self.hyp_id,
            "cycle_id": self.cycle_id, "verdict": self.verdict, "final_status": self.final_status,
            "train": self.train, "validation": self.validation, "evaluated_at": self.evaluated_at,
        }


class EvaluationLedger:
    def __init__(self, path: Path = DEFAULT_LEDGER_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="eval_id", kind="production_evaluation")

    def already_evaluated(self, mechanism: str, instrument: str, driver: Optional[str],
                          window_min: int) -> Optional[Dict[str, Any]]:
        """Real, already-recorded evidence for this exact triple, or None.

        A caller finding a non-None result here MUST NOT re-run the real
        gate() for this triple -- the recorded verdict is the answer.
        """
        return self.store.get(evaluation_id(mechanism, instrument, driver, window_min))

    def record(
        self, *, mechanism: str, instrument: str, driver: Optional[str], window_min: int,
        hyp_id: str, cycle_id: str, verdict: str, final_status: str,
        train: Dict[str, Any], validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist a real, already-computed verdict. Idempotent by id: a
        retry for a triple already recorded (e.g. a caller that skipped
        already_evaluated() and resubmits) returns the EXISTING record
        unchanged rather than attempting a fresh append.

        This check must happen here, not just at the call site, because
        the record's own `evaluated_at` timestamp would otherwise make two
        honest retries of the SAME verdict look like conflicting content
        under the SAME id to the underlying append-only store -- turning a
        harmless retry into a StoreError instead of a no-op. A genuinely
        DIFFERENT verdict for the same triple (which should never happen --
        the real Factory is deterministic on the same data) still raises:
        only the timestamp is ignored when deciding "is this the same
        retry", never the verdict itself.
        """
        eval_id = evaluation_id(mechanism, instrument, driver, window_min)
        existing = self.store.get(eval_id)
        new_content = {
            "mechanism": mechanism, "instrument": instrument, "driver": driver,
            "window_min": window_min, "verdict": verdict, "final_status": final_status,
            "train": train, "validation": validation,
        }
        if existing is not None:
            existing_content = {k: existing.get(k) for k in new_content}
            if existing_content == new_content:
                return existing
            raise StoreError(
                "production_evaluation store already holds a DIFFERENT verdict for this "
                "exact (mechanism, instrument, driver, window) triple -- the real Factory "
                "is deterministic on the same data, so this indicates corruption or a "
                "genuine non-determinism bug, not a harmless retry",
                eval_id=eval_id, path=str(self.store.path),
            )
        row = {
            "eval_id": eval_id,
            "mechanism": mechanism, "instrument": instrument, "driver": driver,
            "window_min": window_min, "hyp_id": hyp_id, "cycle_id": cycle_id,
            "verdict": verdict, "final_status": final_status, "train": train, "validation": validation,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.store.append(row)

    def all(self) -> list:
        return self.store.all()

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
