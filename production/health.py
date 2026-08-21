"""AGLE HEALTH: a real, observational-only live health check.

This module is OBSERVATIONAL ONLY. check_health() never starts AGLE, never
starts a Supervisor, never changes the Master Switch, never modifies
production state, never creates an EA, never bypasses governance, never
alters an evaluation result. Every value comes from either a live process
check or the real, currently persisted on-disk state -- never hardcoded,
never mocked, never inferred from what "should" be happening.

Three distinct things this module is careful never to conflate (the spec's
own warning): MASTER SWITCH (a persisted permission, see master_switch.py),
SUPERVISOR (whether a real OS process from a prior `agle.py run`/`cycle`
invocation is still alive), and CURRENT FACTORY STATE (what that process,
if alive, last reported itself doing via its heartbeat). A switch being ON
says nothing about whether anything is actually running -- this codebase
has no background daemon mode; `agle.py run`/`cycle` are foreground
processes that exit, so "Master Switch ON" and "Supervisor RUNNING" are
independent facts, checked independently.

Known, disclosed limitation on ERRORS TODAY: production/supervisor.py's
CycleReport.errors field exists but nothing currently appends to it (a
cycle either completes and logs a clean report, or raises and is caught by
run_forever(), which records only the single most recent failure in
last_error -- overwritten on the next success, never accumulated into a
per-day ledger). There is therefore no exact, ledger-backed "errors today"
count to reuse. This module reports the best honest floor available from
real persisted state -- see _errors_today() -- and says so, rather than
fabricating a precise number the system does not actually track.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.core.errors import StoreError
from idea_machine.governance import guard
from production.ea_registry import DEFAULT_REGISTRY_PATH, EAProductRegistry
from production.evaluation_ledger import DEFAULT_LEDGER_PATH, EvaluationLedger
from production.master_switch import MasterSwitch
from production.process_utils import is_pid_alive, looks_like_agle_process
from production.supervisor import DEFAULT_HEARTBEAT_PATH, DEFAULT_OPERATION_LOG_PATH
from production.watchdog import DEFAULT_WATCHDOG_LOCK_PATH

UNKNOWN = "UNKNOWN"
NA = "N/A"

PRODUCTION_ROOT = Path(__file__).resolve().parent

# heartbeat "state" -> health "CURRENT STATE" vocabulary. Reuses the
# existing supervisor state model (production/supervisor.py's
# self.state values) rather than inventing a new state machine.
_STATE_MAP = {
    "LOADING": "RUNNING",
    "FACTORY_EVALUATION": "RUNNING",
    "IDLE": "IDLE",
    "DEGRADED": "BLOCKED",
    "STOPPED": "STOPPED",
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_lock_holder(path: Path):
    """Read a production.singleton_lock.SingleInstanceLock's PID file
    directly -- read-only, never touches the lock itself, never calls
    acquire()/release()."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data["pid"]), data.get("acquired_at")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _local_midnight(now: datetime) -> datetime:
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def _cycle_result(cycle: Dict[str, Any]) -> str:
    """Derive a single-word result label from a completed CycleReport's real
    recorded fields -- never a separate, independently-tracked "result"
    field (none exists), always computed from what actually happened."""
    if cycle.get("errors"):
        return "ERROR"
    if cycle.get("ea_products_created", 0) > 0:
        return "EA_PRODUCT_CREATED"
    if cycle.get("survivors", 0) > 0:
        return "SURVIVOR_FOUND_NOT_PRODUCTIZED"
    return "NO_EDGE_FOUND"


@dataclass
class HealthReport:
    master_switch_state: str
    master_switch_source: str
    service_state: str  # RUNNING | STOPPED | NOT INSTALLED
    service_pid: Optional[int]
    supervisor_state: str  # RUNNING | STOPPED
    supervisor_pid: Optional[int]
    current_state: str  # RUNNING | IDLE | STOPPED | BLOCKED | UNKNOWN
    last_cycle_at: str  # ISO timestamp or N/A
    last_cycle_result: str
    last_factory_run_at: str  # ISO timestamp or N/A
    cycles_today: int
    errors_today: int
    errors_today_is_floor: bool
    governance_state: str  # PASS | FAIL | BLOCKED
    governance_reason: str
    last_ea_product: str
    last_ea_product_created_at: str
    last_ea_product_path: str
    ea_product_notification: str
    overall: str  # HEALTHY | SAFE / IDLE | ATTENTION REQUIRED
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "master_switch": self.master_switch_state, "master_switch_source": self.master_switch_source,
            "service": self.service_state, "service_pid": self.service_pid,
            "supervisor": self.supervisor_state, "pid": self.supervisor_pid,
            "current_state": self.current_state, "last_cycle_at": self.last_cycle_at,
            "last_cycle_result": self.last_cycle_result, "last_factory_run_at": self.last_factory_run_at,
            "cycles_today": self.cycles_today, "errors_today": self.errors_today,
            "errors_today_is_floor": self.errors_today_is_floor,
            "governance": self.governance_state, "governance_reason": self.governance_reason,
            "last_ea_product": self.last_ea_product, "last_ea_product_created_at": self.last_ea_product_created_at,
            "last_ea_product_path": self.last_ea_product_path,
            "ea_product_notification": self.ea_product_notification,
            "overall": self.overall, "notes": self.notes,
        }


def _governance_check() -> "tuple[str, str]":
    findings = guard.audit_source_tree()
    prod_findings = guard.audit_source_tree(root=PRODUCTION_ROOT)
    prod_broad = [f for f in prod_findings if f.kind == "BROAD_EXCEPT"]
    problems = list(findings) + prod_broad
    if problems:
        reason = "; ".join(f"{p.file}:{p.line} {p.kind}: {p.detail}" for p in problems)
        return "FAIL", reason
    return "PASS", ""


def _integrity_check(switch: MasterSwitch, evaluation_ledger_path: Path, ea_registry_path: Path) -> List[str]:
    """Narrow-except integrity probe. Deliberately does NOT catch a bare
    Exception/BaseException (that would itself be a BROAD_EXCEPT finding
    and could swallow a GovernanceViolation) -- only StoreError/OSError,
    exactly what AppendOnlyStore's load()/verify_integrity() can raise."""
    problems: List[str] = []
    try:
        switch.verify_integrity()
    except (StoreError, OSError) as exc:
        problems.append(f"master_switch audit trail: {exc}")
    try:
        EvaluationLedger(path=evaluation_ledger_path).verify_integrity()
    except (StoreError, OSError) as exc:
        problems.append(f"evaluation_ledger: {exc}")
    try:
        EAProductRegistry(path=ea_registry_path).verify_integrity()
    except (StoreError, OSError) as exc:
        problems.append(f"ea_registry: {exc}")
    return problems


def check_health(
    *,
    switch: Optional[MasterSwitch] = None,
    heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH,
    operation_log_path: Path = DEFAULT_OPERATION_LOG_PATH,
    evaluation_ledger_path: Path = DEFAULT_LEDGER_PATH,
    ea_registry_path: Path = DEFAULT_REGISTRY_PATH,
    watchdog_lock_path: Path = DEFAULT_WATCHDOG_LOCK_PATH,
    now: Optional[datetime] = None,
) -> HealthReport:
    """The single entry point. Read-only: touches no persisted state,
    starts no process, changes nothing. Safe to call at any time."""
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []
    switch = switch or MasterSwitch()

    switch_state = switch.current()

    # ---- service (watchdog) liveness -- separate concept from the
    # supervisor: a watchdog can be alive and correctly idling with no
    # supervisor child running (switch OFF), and a supervisor can be alive
    # with no watchdog at all (a human's manual `agle.py run`).
    #
    # Deliberately uses ONLY is_pid_alive() here, matching
    # production.singleton_lock.SingleInstanceLock.acquire()'s own
    # authoritative definition of "is this lock still held" exactly --
    # this must never disagree with what `agle.py service start` would
    # itself decide (report STOPPED here while the lock would still
    # refuse a new acquire as "already held" would be a misleading,
    # self-contradictory health report). Identity confirmation is
    # informational only (a note), never a reason to say STOPPED. -------
    service_pid: Optional[int] = None
    if not watchdog_lock_path.exists():
        service_state = "NOT INSTALLED"
    else:
        svc_holder = _read_lock_holder(watchdog_lock_path)
        if svc_holder is None:
            service_state = "STOPPED"
            notes.append("watchdog lock file exists but is unreadable/corrupt -- treated as not running")
        else:
            svc_pid, _ = svc_holder
            svc_alive = is_pid_alive(svc_pid)
            service_state = "RUNNING" if svc_alive else "STOPPED"
            service_pid = svc_pid if svc_alive else None
            if svc_pid and not svc_alive:
                notes.append(f"watchdog lock records pid={svc_pid} but that process is not alive (stale lock)")
            elif svc_pid and svc_alive and looks_like_agle_process(svc_pid) is None:
                notes.append("service liveness confirmed by PID only (process-identity check unavailable on this platform)")

    # ---- supervisor liveness (independent of the switch) -----------------
    heartbeat = _read_json(heartbeat_path)
    hb_pid = heartbeat.get("pid")
    pid_alive = is_pid_alive(hb_pid)
    confirmed = looks_like_agle_process(hb_pid) if pid_alive and hb_pid else None
    if confirmed is None and pid_alive:
        notes.append("supervisor liveness confirmed by PID only (process-identity check unavailable on this platform)")
    supervisor_running = bool(pid_alive and confirmed is not False)
    supervisor_state = "RUNNING" if supervisor_running else "STOPPED"
    supervisor_pid = int(hb_pid) if (supervisor_running and hb_pid) else None
    if hb_pid and not supervisor_running:
        notes.append(f"heartbeat records pid={hb_pid} but that process is not alive (stale heartbeat)")

    # ---- current operational state ---------------------------------------
    if supervisor_running:
        current_state = _STATE_MAP.get(heartbeat.get("state"), UNKNOWN)
    elif not heartbeat:
        current_state = "STOPPED"
    else:
        current_state = "STOPPED"

    # ---- last completed cycle ---------------------------------------------
    op_log = _read_json(operation_log_path)
    cycles: List[Dict[str, Any]] = op_log.get("cycles", []) if isinstance(op_log, dict) else []
    last_cycle = cycles[-1] if cycles else None
    last_cycle_at = last_cycle.get("ended_at", NA) if last_cycle else NA
    last_cycle_result = _cycle_result(last_cycle) if last_cycle else NA
    if not cycles:
        notes.append("no completed production cycle recorded yet")

    # ---- last REAL factory evaluation (never simulated) --------------------
    eval_ledger_raw = _read_json(evaluation_ledger_path)
    eval_records: List[Dict[str, Any]] = eval_ledger_raw.get("records", []) if isinstance(eval_ledger_raw, dict) else []
    last_factory_run_at = NA
    if eval_records:
        parsed = [(r, _parse_iso(r.get("evaluated_at"))) for r in eval_records]
        parsed = [(r, dt) for r, dt in parsed if dt is not None]
        if parsed:
            last_factory_run_at = max(parsed, key=lambda pair: pair[1])[0]["evaluated_at"]
    else:
        notes.append("no real Factory evaluation recorded yet")

    # ---- cycles today / errors today (local midnight) ----------------------
    midnight_local = _local_midnight(now)
    cycles_today = 0
    logged_errors_today = 0
    for c in cycles:
        ended = _parse_iso(c.get("ended_at"))
        if ended is None:
            continue
        if ended.astimezone() >= midnight_local:
            cycles_today += 1
            logged_errors_today += len(c.get("errors") or [])

    # CycleReport.errors is not currently populated by any code path (see
    # module docstring) -- the only other real error signal is the live
    # heartbeat's last_error, a single most-recent snapshot, not a ledger.
    # Treated as a floor (>=), not an exact day total, and disclosed as such.
    errors_today = logged_errors_today
    errors_today_is_floor = False
    hb_last_error = heartbeat.get("last_error")
    hb_ts = _parse_iso(heartbeat.get("timestamp"))
    if hb_last_error and hb_ts is not None and hb_ts.astimezone() >= midnight_local:
        errors_today = max(errors_today, logged_errors_today + 1)
        errors_today_is_floor = True
        notes.append(
            "errors_today includes the single most-recent live error snapshot from the heartbeat "
            "(no per-day error ledger exists in this codebase yet) -- treat as a floor, not an exact count"
        )

    # ---- governance -----------------------------------------------------
    governance_state, governance_reason = _governance_check()
    integrity_problems = _integrity_check(switch, evaluation_ledger_path, ea_registry_path)
    if integrity_problems and governance_state == "PASS":
        governance_state = "BLOCKED"
        governance_reason = "; ".join(integrity_problems)
    elif integrity_problems:
        governance_reason = governance_reason + "; " + "; ".join(integrity_problems)

    # ---- EA product status ------------------------------------------------
    ea_registry_raw = _read_json(ea_registry_path)
    ea_records: List[Dict[str, Any]] = ea_registry_raw.get("records", []) if isinstance(ea_registry_raw, dict) else []
    if ea_records:
        last_product = ea_records[-1]
        last_ea_product = last_product.get("candidate_id", NA)
        last_ea_product_created_at = last_product.get("created_at", NA)
        last_ea_product_path = last_product.get("artifact_path", NA)
    else:
        last_ea_product, last_ea_product_created_at, last_ea_product_path = "NONE", NA, NA

    # No notification channel exists anywhere in production/ or agle.py
    # (verified by inspection, not assumed) -- never claim SENT.
    ea_product_notification = "NOT IMPLEMENTED"

    # ---- overall ----------------------------------------------------------
    # Three-way, not two-way: an intentional Master Switch OFF is NOT a
    # failure state and must never read as "ATTENTION REQUIRED" merely for
    # being OFF -- that would train an operator to associate a deliberate
    # pause with an alarm. Governance always overrides everything else: a
    # governance FAIL/BLOCKED is never HEALTHY and never SAFE / IDLE.
    #   HEALTHY       -- switch ON, supervisor alive (RUNNING or IDLE
    #                    between cycles), governance PASS: production is
    #                    actually happening or ready to on the next tick.
    #   SAFE / IDLE   -- switch OFF (intentional pause) and nothing else is
    #                    wrong (not BLOCKED/DEGRADED, governance PASS).
    #   ATTENTION REQUIRED -- anything else: governance trouble, switch ON
    #                    but nothing servicing it, or BLOCKED/DEGRADED
    #                    regardless of switch state (a crash loop while OFF
    #                    is still worth a human's attention).
    if governance_state != "PASS":
        overall = "ATTENTION REQUIRED"
    elif current_state == "BLOCKED":
        overall = "ATTENTION REQUIRED"
    elif not switch_state.enabled:
        overall = "SAFE / IDLE"
    elif supervisor_state == "RUNNING" and current_state in ("RUNNING", "IDLE"):
        overall = "HEALTHY"
    else:
        overall = "ATTENTION REQUIRED"

    if switch_state.enabled and service_state != "RUNNING":
        notes.append(
            f"master switch is ON but no watchdog service is running (service={service_state}) -- "
            "production is not being kept alive automatically; a human or manual `agle.py run` is required"
        )

    return HealthReport(
        master_switch_state=switch_state.state, master_switch_source=switch_state.source,
        service_state=service_state, service_pid=service_pid,
        supervisor_state=supervisor_state, supervisor_pid=supervisor_pid, current_state=current_state,
        last_cycle_at=last_cycle_at, last_cycle_result=last_cycle_result, last_factory_run_at=last_factory_run_at,
        cycles_today=cycles_today, errors_today=errors_today, errors_today_is_floor=errors_today_is_floor,
        governance_state=governance_state, governance_reason=governance_reason,
        last_ea_product=last_ea_product, last_ea_product_created_at=last_ea_product_created_at,
        last_ea_product_path=last_ea_product_path, ea_product_notification=ea_product_notification,
        overall=overall, notes=notes,
    )


def _fmt_local_time(iso_ts: str) -> str:
    dt = _parse_iso(iso_ts)
    if dt is None:
        return NA
    return dt.astimezone().strftime("%H:%M:%S")


def render_health_text(report: HealthReport) -> str:
    pid_display = str(report.supervisor_pid) if report.supervisor_pid else NA
    lines = [
        "AGLE HEALTH",
        "─" * 40,
        f"MASTER SWITCH     {report.master_switch_state}",
        f"SERVICE           {report.service_state}",
        f"SUPERVISOR        {report.supervisor_state}",
        f"PID               {pid_display}",
        f"CURRENT STATE     {report.current_state}",
        f"LAST CYCLE        {_fmt_local_time(report.last_cycle_at)}",
        f"LAST RESULT       {report.last_cycle_result}",
        f"LAST FACTORY RUN  {_fmt_local_time(report.last_factory_run_at)}",
        f"CYCLES TODAY      {report.cycles_today}",
        f"ERRORS TODAY      {report.errors_today}{'+' if report.errors_today_is_floor else ''}",
        f"GOVERNANCE        {report.governance_state}",
        "─" * 40,
        f"OVERALL           {report.overall}",
        "",
        "EA PRODUCT",
        "─" * 40,
        f"LAST EA PRODUCT      {report.last_ea_product}",
        f"PRODUCT CREATED      {report.last_ea_product_created_at if report.last_ea_product_created_at == NA else _fmt_local_time(report.last_ea_product_created_at)}",
        f"PRODUCT PATH         {report.last_ea_product_path}",
        f"PRODUCT NOTIFICATION {report.ea_product_notification}",
    ]
    if report.governance_reason:
        lines.append("")
        lines.append(f"GOVERNANCE REASON: {report.governance_reason}")
    if report.notes:
        lines.append("")
        lines.append("NOTES:")
        for n in report.notes:
            lines.append(f"  - {n}")
    return "\n".join(lines)
