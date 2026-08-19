"""
Cumulative multiple-testing ledger for the discovery layer.

Append-only, cross-cycle, NEVER reset. Every hypothesis generated and every
parameter combination evaluated -- pass or fail -- increments this ledger.
This exists specifically to prevent "we tested 500 ideas and found the best
one" from masquerading as "we discovered a statistically strong edge": any
downstream p-value or confidence claim must be read against these totals,
not against the count from a single cycle.
"""

import json
import tempfile
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

DEFAULT_LEDGER_PATH = Path("reports/factory/multiple_testing_ledger.json")


@dataclass
class CycleRecord:
    cycle_id: str
    started_at: str
    hypotheses_generated: int
    parameter_evaluations: int
    families_touched: List[str]
    survivors: int
    notes: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class MultipleTestingLedger:
    """
    Persistent, monotonically-growing record of everything the Factory has
    ever tested. No method here can decrease a counter or remove a cycle.
    """

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH):
        self.path = Path(path)
        self.cycles: List[CycleRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.cycles = [CycleRecord(**c) for c in raw.get("cycles", [])]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cumulative_hypotheses_generated": self.total_hypotheses(),
            "cumulative_parameter_evaluations": self.total_parameter_evaluations(),
            "cumulative_survivors": self.total_survivors(),
            "cycle_count": len(self.cycles),
            "families_ever_touched": sorted(self.all_families()),
            "cycles": [c.to_dict() for c in self.cycles],
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def record_cycle(self, cycle_id: str, hypotheses_generated: int,
                     parameter_evaluations: int, families_touched: List[str],
                     survivors: int, notes: str = "") -> CycleRecord:
        if any(c.cycle_id == cycle_id for c in self.cycles):
            raise ValueError(f"cycle_id {cycle_id!r} already recorded; "
                             f"ledger is append-only, cannot re-record a cycle")
        rec = CycleRecord(
            cycle_id=cycle_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            hypotheses_generated=hypotheses_generated,
            parameter_evaluations=parameter_evaluations,
            families_touched=list(families_touched),
            survivors=survivors,
            notes=notes,
        )
        self.cycles.append(rec)
        self._save()
        return rec

    def total_hypotheses(self) -> int:
        return sum(c.hypotheses_generated for c in self.cycles)

    def total_parameter_evaluations(self) -> int:
        return sum(c.parameter_evaluations for c in self.cycles)

    def total_survivors(self) -> int:
        return sum(c.survivors for c in self.cycles)

    def all_families(self) -> set:
        out = set()
        for c in self.cycles:
            out.update(c.families_touched)
        return out

    def summary(self) -> Dict:
        return {
            "cycle_count": len(self.cycles),
            "cumulative_hypotheses_generated": self.total_hypotheses(),
            "cumulative_parameter_evaluations": self.total_parameter_evaluations(),
            "cumulative_survivors": self.total_survivors(),
            "families_ever_touched": sorted(self.all_families()),
            "cycles": [c.to_dict() for c in self.cycles],
        }
