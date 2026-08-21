"""AGLE Master Switch: persistent, auditable ON/OFF control for production mode.

Persisted as an append-only log (reusing
idea_machine.core.store.AppendOnlyStore -- same atomic-write, refuse-to-
rewrite discipline as every other ledger in this repository). Current state
is the LAST record in the log, never a separate mutable field, so there is
exactly one source of truth and no way for "current state" and "history" to
drift apart.

OFF never deletes, resets, or touches any other file. Turning OFF only
appends a new switch-state record; every research/Factory ledger
(opportunity queue, research memory, multiple-testing ledger, evaluation
ledger, EA registry) is completely untouched by a switch transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.core.ids import mint_id
from idea_machine.core.store import AppendOnlyStore

DEFAULT_SWITCH_PATH = Path("reports/production/master_switch.json")

ON = "ON"
OFF = "OFF"


@dataclass(frozen=True)
class SwitchState:
    enabled: bool
    state: str  # "ON" | "OFF"
    changed_at: str
    reason: str
    source: str
    record_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled, "state": self.state, "changed_at": self.changed_at,
            "reason": self.reason, "source": self.source, "record_id": self.record_id,
        }


class MasterSwitch:
    """The single, persistent, auditable ON/OFF control for AGLE production mode."""

    def __init__(self, path: Path = DEFAULT_SWITCH_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="record_id", kind="master_switch")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, enabled: bool, reason: str, source: str) -> SwitchState:
        ts = self._now()
        row = {
            "enabled": enabled, "state": ON if enabled else OFF, "changed_at": ts,
            "reason": reason, "source": source,
        }
        row["record_id"] = mint_id("SWITCH", {**row, "seq": self.store.count()})
        saved = self.store.append(row)
        return SwitchState(**saved)

    def turn_on(self, *, reason: str, source: str = "operator") -> SwitchState:
        return self._append(True, reason, source)

    def turn_off(self, *, reason: str, source: str = "operator") -> SwitchState:
        return self._append(False, reason, source)

    def current(self) -> SwitchState:
        """The current state -- always the last record, or a default OFF if
        the switch has never been touched (safe default: production mode
        does not silently start itself)."""
        rows = self.store.all()
        if not rows:
            return SwitchState(enabled=False, state=OFF, changed_at="", reason="never initialized",
                              source="default", record_id="")
        return SwitchState(**rows[-1])

    def is_on(self) -> bool:
        return self.current().enabled

    def history(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
