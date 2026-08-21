"""AGLE Master Switch: the operator's persistent, human-operable ON/OFF control.

THE CORE REQUIREMENT this module exists to satisfy: AGLE must remain
controllable by a human even if Claude Code, the development environment, or
the original automation workflow is gone. The authoritative switch state
therefore lives in ONE plain, human-editable JSON file -- not inside an
append-only, checksummed, content-hash-keyed ledger that only this
codebase's own writer could ever produce correctly by hand.

Two files, two jobs, never confused with each other:

  runtime/master_switch.json              AUTHORITATIVE. A human with a text
                                           editor and no tooling at all can
                                           write {"enabled": true} or
                                           {"enabled": false} directly. This
                                           file, and ONLY this file, decides
                                           whether the factory may run. Every
                                           read is a fresh read from disk --
                                           never cached, never inferred.

  reports/production/master_switch.json   AUDIT TRAIL (unchanged path/schema
                                           from before this module's
                                           disaster-recovery rework, so the
                                           real history already recorded
                                           there is preserved). Append-only
                                           history of every transition this
                                           process performed. Purely for
                                           observability -- never consulted
                                           to decide current permission, and
                                           its own corruption must never
                                           block a switch operation.

FAIL-SAFE (mandatory): if the authoritative file is missing, unreadable,
malformed, or ambiguous (no boolean "enabled" key), the factory is OFF.
Never inferred ON from memory, defaults, prior history, or a previous
Claude Code command -- see read_switch_state().

OFF never deletes, resets, or touches any other file: turning OFF only
(re)writes the one-line authoritative state file and appends one audit
record; every research/Factory ledger (opportunity queue, research memory,
evaluation ledger, EA registry) is completely untouched by a switch
transition.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from idea_machine.core.errors import StoreError
from idea_machine.core.ids import mint_id
from idea_machine.core.store import AppendOnlyStore

logger = logging.getLogger(__name__)

#: The authoritative, human-editable control file. Overridable via
#: AGLE_SWITCH_STATE_PATH -- e.g. to point a disaster-recovery drill or a
#: test at an isolated file without touching the real production state.
DEFAULT_STATE_PATH = Path(os.environ.get("AGLE_SWITCH_STATE_PATH", "runtime/master_switch.json"))

#: Append-only observability trail. Never authoritative, never required to
#: exist or be valid for the switch itself to function correctly.
DEFAULT_AUDIT_PATH = Path(os.environ.get("AGLE_SWITCH_AUDIT_PATH", "reports/production/master_switch.json"))

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """tempfile + fsync + os.replace -- a crash mid-write leaves the OLD file
    (or no file) intact, never a truncated/partial document that could be
    misread as {"enabled": true}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_switch_state(path: Path = DEFAULT_STATE_PATH) -> Tuple[bool, Dict[str, Any], str]:
    """The single fail-safe read path for the authoritative switch file.

    Returns (enabled, raw_dict, fail_safe_reason). ``fail_safe_reason`` is
    "" for a clean, unambiguous read; a non-empty string whenever fail-safe
    OFF was applied, explaining exactly why -- missing file, unreadable
    file, empty file, invalid JSON, wrong shape, or a non-boolean/absent
    "enabled" key are ALL treated identically: OFF, with the reason logged,
    never a guess.
    """
    if not path.exists():
        return False, {}, "switch file missing"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, {}, f"switch file unreadable: {exc}"
    if not raw.strip():
        return False, {}, "switch file empty"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, {}, f"switch file corrupted (invalid JSON): {exc}"
    if not isinstance(data, dict):
        return False, {}, "switch file does not contain a JSON object"
    if "enabled" not in data:
        return False, data, "switch file missing 'enabled' field"
    enabled = data["enabled"]
    if not isinstance(enabled, bool):
        return False, data, f"switch file 'enabled' is not a boolean (got {enabled!r})"
    return enabled, data, ""


class MasterSwitch:
    """The operator's persistent, human-operable ON/OFF control.

    current() / is_on() ALWAYS re-read the authoritative state file from
    disk -- see module docstring for the fail-safe contract and the split
    between that file and the audit trail.
    """

    def __init__(self, state_path: Path = DEFAULT_STATE_PATH, audit_path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.audit_store: Optional[AppendOnlyStore] = None
        try:
            self.audit_store = AppendOnlyStore(self.audit_path, id_field="record_id", kind="master_switch")
        except (StoreError, OSError) as exc:
            # Audit-trail corruption must never block the safety-critical
            # read/write path -- but this is deliberately narrow (only what
            # AppendOnlyStore's load() can actually raise), never a bare
            # Exception/BaseException catch that could also swallow a
            # GovernanceViolation.
            logger.warning("MASTER_SWITCH_AUDIT_UNAVAILABLE reason=%s", exc)

    # ------------------------------------------------------------- reading

    def current(self) -> SwitchState:
        """The current, authoritative state -- always a fresh disk read,
        fail-safe OFF on any missing/corrupt/ambiguous file. Every call logs
        the observed state (and, on fail-safe, the reason) so this doubles
        as the "log the current state" observability hook required at
        startup and on every supervisor re-read."""
        enabled, data, fail_reason = read_switch_state(self.state_path)
        if fail_reason:
            logger.warning("MASTER_SWITCH_ERROR reason=%s FAIL_SAFE_STATE=OFF", fail_reason)
            state = SwitchState(
                enabled=False, state=OFF, changed_at=_now(),
                reason=f"FAIL_SAFE: {fail_reason}", source="FAIL_SAFE", record_id="",
            )
        else:
            # Fields beyond "enabled" are optional enrichments a CLI write
            # adds; a bare hand-edited {"enabled": false} is still fully
            # valid, and its source is reported honestly as PERSISTED_STATE
            # -- this process cannot know which human touched the file.
            state = SwitchState(
                enabled=enabled, state=ON if enabled else OFF,
                changed_at=str(data.get("changed_at") or _now()),
                reason=str(data.get("reason") or "persisted state"),
                source=str(data.get("source") or "PERSISTED_STATE"),
                record_id=str(data.get("record_id") or ""),
            )
        logger.info("MASTER_SWITCH_STATE state=%s source=%s", state.state, state.source)
        return state

    def is_on(self) -> bool:
        return self.current().enabled

    # ------------------------------------------------------------- writing

    def _set(self, enabled: bool, *, reason: str, source: str) -> SwitchState:
        previous = self.current()
        ts = _now()
        record_id = mint_id("SWITCH", {"enabled": enabled, "reason": reason, "source": source, "ts": ts})
        payload = {
            "enabled": enabled, "state": ON if enabled else OFF, "changed_at": ts,
            "reason": reason, "source": source, "record_id": record_id,
        }
        _atomic_write_json(self.state_path, payload)
        logger.info("MASTER_SWITCH_CHANGED previous=%s current=%s source=%s", previous.state, payload["state"], source)
        self._append_audit(payload)
        return SwitchState(**{k: payload[k] for k in ("enabled", "state", "changed_at", "reason", "source", "record_id")})

    def turn_on(self, *, reason: str, source: str = "operator") -> SwitchState:
        return self._set(True, reason=reason, source=source)

    def turn_off(self, *, reason: str, source: str = "operator") -> SwitchState:
        return self._set(False, reason=reason, source=source)

    def _append_audit(self, payload: Dict[str, Any]) -> None:
        if self.audit_store is None:
            return
        try:
            self.audit_store.append(dict(payload))
        except (StoreError, OSError) as exc:
            # Deliberately narrow, same reasoning as __init__ above: the
            # switch write already succeeded, so audit-append failure is
            # logged, not fatal -- but never at the cost of a handler broad
            # enough to swallow a GovernanceViolation.
            logger.warning("MASTER_SWITCH_AUDIT_WRITE_FAILED reason=%s", exc)

    def history(self) -> List[Dict[str, Any]]:
        return self.audit_store.all() if self.audit_store is not None else []

    def verify_integrity(self) -> None:
        """Verifies the AUDIT TRAIL only -- a malformed authoritative state
        file is an expected, handled, fail-safe-OFF condition (see
        read_switch_state), not corruption to raise on. Audit tampering, by
        contrast, is a genuine integrity problem."""
        if self.audit_store is not None:
            self.audit_store.verify_integrity()
