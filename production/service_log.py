"""Operational service/watchdog event log.

Append-only (reuses idea_machine.core.store.AppendOnlyStore, same as every
other ledger in production/). Distinguishes the specific event kinds the
24/7 operations spec requires -- in particular, NO_EDGE_FOUND (a valid
Factory result) is never confused with an error, and MASTER_SWITCH_OFF is
never confused with a fault.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.core.ids import mint_id
from idea_machine.core.store import AppendOnlyStore

DEFAULT_SERVICE_LOG_PATH = Path(os.environ.get("AGLE_SERVICE_LOG_PATH", "reports/production/service_log.json"))

SERVICE_STARTED = "SERVICE_STARTED"
SERVICE_STOPPED = "SERVICE_STOPPED"
SUPERVISOR_STARTED = "SUPERVISOR_STARTED"
SUPERVISOR_STOPPED = "SUPERVISOR_STOPPED"
SUPERVISOR_CRASHED = "SUPERVISOR_CRASHED"
SUPERVISOR_RESTARTED = "SUPERVISOR_RESTARTED"
MASTER_SWITCH_ON = "MASTER_SWITCH_ON"
MASTER_SWITCH_OFF = "MASTER_SWITCH_OFF"
DUPLICATE_PROCESS_BLOCKED = "DUPLICATE_PROCESS_BLOCKED"
FAIL_SAFE = "FAIL_SAFE"

EVENT_KINDS = frozenset({
    SERVICE_STARTED, SERVICE_STOPPED, SUPERVISOR_STARTED, SUPERVISOR_STOPPED,
    SUPERVISOR_CRASHED, SUPERVISOR_RESTARTED, MASTER_SWITCH_ON, MASTER_SWITCH_OFF,
    DUPLICATE_PROCESS_BLOCKED, FAIL_SAFE,
})


class ServiceEventLog:
    def __init__(self, path: Path = DEFAULT_SERVICE_LOG_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="event_id", kind="service_event")

    def record(self, kind: str, *, detail: str = "", pid: Optional[int] = None) -> Dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown service event kind: {kind!r}")
        ts = datetime.now(timezone.utc).isoformat()
        row = {"kind": kind, "detail": detail, "pid": pid, "timestamp": ts}
        row["event_id"] = mint_id("SVCEVT", {**row, "seq": self.store.count()})
        return self.store.append(row)

    def all(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def last(self) -> Optional[Dict[str, Any]]:
        rows = self.store.all()
        return rows[-1] if rows else None

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
