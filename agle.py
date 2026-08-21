#!/usr/bin/env python3
"""AGLE -- production-mode command line interface.

    python3 agle.py status         # master switch + supervisor + registry snapshot
    python3 agle.py switch status  # human-readable master switch state
    python3 agle.py switch on      # turn the master switch ON (persistent)
    python3 agle.py switch off     # turn the master switch OFF (persistent, safe)
    python3 agle.py start      # alias for `switch on`
    python3 agle.py stop       # alias for `switch off`
    python3 agle.py restart    # stop, then start (both persisted, both audited)
    python3 agle.py cycle      # run exactly one production cycle and report it
    python3 agle.py run        # run the 24/7 loop (blocks until switch is OFF,
                                #   max-cycles reached, or bounded failures trip)
    python3 agle.py verify     # verify_integrity() on every production ledger
    python3 agle.py products   # list every registered EA product
    python3 agle.py queue      # opportunity queue summary
    python3 agle.py health     # real, observational live health check
    python3 agle.py health --json  # same, as machine-readable JSON
    python3 agle.py service install    # register the watchdog to start at boot (Windows)
    python3 agle.py service start      # start the watchdog now (keeps a Supervisor alive)
    python3 agle.py service stop       # ask the watchdog to stop gracefully
    python3 agle.py service restart    # stop then start
    python3 agle.py service status     # is the watchdog alive right now
    python3 agle.py service uninstall  # remove the boot registration

This wraps, and does not reimplement, production.master_switch.MasterSwitch,
production.supervisor.ProductionSupervisor, production.watchdog.
ServiceWatchdog, production.ea_registry.EAProductRegistry, and
idea_machine.opportunity_queue.OpportunityQueue.

Three distinct layers, never merged: the WATCHDOG/SERVICE keeps a
Supervisor process alive (process availability); the MASTER SWITCH is the
authoritative production permission; the SUPERVISOR runs the actual
production loop. `agle.py service *` commands only ever touch the first --
they never read, write, or imply anything about the Master Switch.

This CLI is a convenience, not a requirement: the master switch's
authoritative state is the plain file at runtime/master_switch.json
({"enabled": true} or {"enabled": false}). An operator can edit that file
directly with any text editor -- no Claude Code, no Python, no this CLI --
and the supervisor will honor it on its next read. See
production/master_switch.py for the fail-safe read contract.

There is no --force, --skip-gates, or --ignore-governance flag anywhere in
this file, and there never should be: the master switch controls only
whether NEW work may start, never whether governance applies to it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from idea_machine.opportunity_queue import OpportunityQueue  # noqa: E402
from production.ea_registry import EAProductRegistry  # noqa: E402
from production.evaluation_ledger import EvaluationLedger  # noqa: E402
from production.master_switch import MasterSwitch  # noqa: E402
from production.health import check_health, render_health_text  # noqa: E402
from production.singleton_lock import DUPLICATE_PROCESS_EXIT_CODE, DuplicateProcessError  # noqa: E402
from production.supervisor import DEFAULT_HEARTBEAT_PATH, ProductionSupervisor  # noqa: E402
from production.watchdog import DEFAULT_WATCHDOG_LOCK_PATH, ServiceWatchdog  # noqa: E402


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_status(args) -> int:
    switch = MasterSwitch()
    ea_registry = EAProductRegistry()
    heartbeat = {}
    if DEFAULT_HEARTBEAT_PATH.exists():
        try:
            heartbeat = json.loads(DEFAULT_HEARTBEAT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            heartbeat = {}
    _print({
        "master_switch": switch.current().to_dict(),
        "ea_products_created": ea_registry.count(),
        "heartbeat": heartbeat,
    })
    return 0


def _print_switch_box(lines) -> None:
    print("MASTER SWITCH")
    print("-------------")
    for line in lines:
        print(line)


def cmd_switch_status(args) -> int:
    state = MasterSwitch().current()
    _print_switch_box([f"State: {state.state}", "Source: persistent runtime state"])
    return 0


def cmd_switch_on(args) -> int:
    switch = MasterSwitch()
    previous = switch.current()
    new = switch.turn_on(reason=args.reason or "operator switch on via agle.py", source="cli")
    _print_switch_box([f"Previous: {previous.state}", f"Current:  {new.state}"])
    return 0


def cmd_switch_off(args) -> int:
    switch = MasterSwitch()
    previous = switch.current()
    new = switch.turn_off(reason=args.reason or "operator switch off via agle.py", source="cli")
    _print_switch_box([f"Previous: {previous.state}", f"Current:  {new.state}"])
    return 0


def cmd_start(args) -> int:
    return cmd_switch_on(args)


def cmd_stop(args) -> int:
    return cmd_switch_off(args)


def cmd_restart(args) -> int:
    switch = MasterSwitch()
    switch.turn_off(reason="restart (stop phase)", source="cli")
    state = switch.turn_on(reason="restart (start phase)", source="cli")
    _print(state.to_dict())
    return 0


def cmd_cycle(args) -> int:
    sup = ProductionSupervisor()
    if not sup.switch.is_on():
        print("MASTER SWITCH is OFF -- refusing to run a cycle. Run `agle.py start` first.")
        return 1
    try:
        report = sup.run_one_cycle(total_slots=args.total_slots)
    except DuplicateProcessError as exc:
        print(f"REFUSED: another AGLE production process is already running (pid {exc.holder_pid}) -- {exc}")
        return DUPLICATE_PROCESS_EXIT_CODE
    _print(report.to_dict())
    return 0


def cmd_run(args) -> int:
    sup = ProductionSupervisor()
    if not sup.switch.is_on():
        print("MASTER SWITCH is OFF -- refusing to run. Run `agle.py start` first.")
        return 1
    try:
        summary = sup.run_forever(max_cycles=args.max_cycles, sleep_seconds=args.sleep_seconds,
                                  total_slots=args.total_slots)
    except DuplicateProcessError as exc:
        print(f"REFUSED: another AGLE production process is already running (pid {exc.holder_pid}) -- {exc}")
        return DUPLICATE_PROCESS_EXIT_CODE
    _print(summary)
    return 0


def cmd_watchdog(args) -> int:
    """Foreground, blocking: the process a Windows Task Scheduler action
    (or `agle.py service start`, spawned in the background) actually runs.
    Keeps exactly one Supervisor child alive while the Master Switch
    permits it -- see production/watchdog.py for the full contract."""
    watchdog = ServiceWatchdog()
    summary = watchdog.run(max_iterations=args.max_iterations)
    _print(summary)
    return 0


def _print_service_box(lines) -> None:
    print("AGLE SERVICE")
    print("------------")
    for line in lines:
        print(line)


def cmd_service_install(args) -> int:
    import platform

    if platform.system() != "Windows":
        _print_service_box([
            "Install: NOT SUPPORTED on this platform",
            f"(detected: {platform.system()})",
            "This installs a Windows Task Scheduler entry ('run whether user",
            "is logged on or not', trigger: at system startup) that launches",
            "`python agle.py watchdog`. On Linux/macOS, use your own process",
            "supervisor (systemd, launchd, etc.) to run the same command, or",
            "run `python agle.py service start` interactively.",
        ])
        return 1

    import subprocess as _subprocess
    task_name = "AGLE_Watchdog"
    python_exe = sys.executable
    script = str(REPO_ROOT / "agle.py")
    action = f'"{python_exe}" "{script}" watchdog'
    cmd = [
        "schtasks", "/create", "/tn", task_name, "/sc", "onstart",
        "/rl", "HIGHEST", "/tr", action, "/f",
    ]
    result = _subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        _print_service_box([f"Installed scheduled task '{task_name}' (runs `agle.py watchdog` at startup)."])
        return 0
    _print_service_box([f"schtasks /create FAILED: {result.stderr.strip() or result.stdout.strip()}"])
    return 1


def cmd_service_uninstall(args) -> int:
    import platform

    if platform.system() != "Windows":
        _print_service_box(["Uninstall: NOT SUPPORTED on this platform (nothing was installed here)."])
        return 1

    import subprocess as _subprocess
    task_name = "AGLE_Watchdog"
    result = _subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"], capture_output=True, text=True)
    if result.returncode == 0:
        _print_service_box([f"Removed scheduled task '{task_name}'."])
        return 0
    _print_service_box([f"schtasks /delete FAILED (may already be absent): {result.stderr.strip() or result.stdout.strip()}"])
    return 1


def cmd_service_start(args) -> int:
    import subprocess as _subprocess
    import time as _time

    watchdog = ServiceWatchdog()
    status = watchdog.status()
    if status["running"]:
        _print_service_box([f"Already running (pid {status['pid']})."])
        return 0

    popen_kwargs: dict = {"cwd": str(REPO_ROOT)}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = _subprocess.CREATE_NEW_PROCESS_GROUP | getattr(_subprocess, "DETACHED_PROCESS", 0)
    else:
        popen_kwargs["start_new_session"] = True
    _subprocess.Popen([sys.executable, str(REPO_ROOT / "agle.py"), "watchdog"], **popen_kwargs)

    for _ in range(50):  # wait up to ~5s for the lock to actually be claimed
        _time.sleep(0.1)
        status = watchdog.status()
        if status["running"]:
            _print_service_box([f"Started (pid {status['pid']})."])
            return 0
    _print_service_box(["Spawned, but could not confirm it acquired the watchdog lock within 5s -- check `agle.py service status`."])
    return 1


def cmd_service_stop(args) -> int:
    import signal as _signal
    import time as _time

    watchdog = ServiceWatchdog()
    status = watchdog.status()
    if not status["running"]:
        _print_service_box(["Already stopped."])
        return 0

    pid = status["pid"]
    try:
        if sys.platform == "win32":
            sig = getattr(_signal, "CTRL_BREAK_EVENT", _signal.SIGTERM)
        else:
            sig = _signal.SIGTERM
        os.kill(pid, sig)
    except OSError as exc:
        _print_service_box([f"Could not signal pid {pid}: {exc}"])
        return 1

    for _ in range(int(args.timeout_seconds * 10)):
        _time.sleep(0.1)
        status = watchdog.status()
        if not status["running"]:
            _print_service_box(["Stopped."])
            return 0
    _print_service_box([
        f"Signaled pid {pid} but it has not exited after {args.timeout_seconds}s -- it may be waiting for an "
        "active evaluation to finish (this is expected behavior, not a bug -- see Phase 7). Try again later, "
        "or increase --timeout-seconds.",
    ])
    return 1


def cmd_service_restart(args) -> int:
    stop_rc = cmd_service_stop(args)
    if stop_rc != 0:
        return stop_rc
    return cmd_service_start(args)


def cmd_service_status(args) -> int:
    watchdog = ServiceWatchdog()
    status = watchdog.status()
    if status["running"]:
        _print_service_box([f"State: RUNNING", f"PID:   {status['pid']}"])
    else:
        _print_service_box(["State: STOPPED", "PID:   N/A"])
    return 0 if status["running"] else 1


def cmd_verify(args) -> int:
    ok = True
    checks = [
        ("master_switch", MasterSwitch()),
        ("evaluation_ledger", EvaluationLedger()),
        ("ea_registry", EAProductRegistry()),
    ]
    results = {}
    for name, obj in checks:
        try:
            obj.verify_integrity()
            results[name] = "OK"
        except Exception as exc:  # noqa: BLE001 -- report every failure, never hide one
            results[name] = f"FAIL: {exc}"
            ok = False
    _print(results)
    return 0 if ok else 1


def cmd_products(args) -> int:
    _print(EAProductRegistry().all())
    return 0


def cmd_queue(args) -> int:
    _print(OpportunityQueue().get_summary())
    return 0


def cmd_health(args) -> int:
    """Real, observational-only live health check -- see production/health.py.
    Never starts AGLE, never starts a Supervisor, never changes the Master
    Switch, never modifies production state. Safe to run at any time."""
    report = check_health()
    if getattr(args, "json", False):
        _print(report.to_dict())
    else:
        print(render_health_text(report))
    return 0 if report.overall == "HEALTHY" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agle.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="master switch + supervisor + registry snapshot")
    p_status.set_defaults(func=cmd_status)

    p_switch = sub.add_parser("switch", help="human-operable master switch control")
    switch_sub = p_switch.add_subparsers(dest="switch_command", required=True)

    p_switch_status = switch_sub.add_parser("status", help="show master switch state")
    p_switch_status.set_defaults(func=cmd_switch_status)

    p_switch_on = switch_sub.add_parser("on", help="turn the master switch ON")
    p_switch_on.add_argument("--reason", default=None)
    p_switch_on.set_defaults(func=cmd_switch_on)

    p_switch_off = switch_sub.add_parser("off", help="turn the master switch OFF")
    p_switch_off.add_argument("--reason", default=None)
    p_switch_off.set_defaults(func=cmd_switch_off)

    p_start = sub.add_parser("start", help="alias for `switch on`")
    p_start.add_argument("--reason", default=None)
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="alias for `switch off`")
    p_stop.add_argument("--reason", default=None)
    p_stop.set_defaults(func=cmd_stop)

    p_restart = sub.add_parser("restart", help="stop then start")
    p_restart.set_defaults(func=cmd_restart)

    p_cycle = sub.add_parser("cycle", help="run exactly one production cycle")
    p_cycle.add_argument("--total-slots", dest="total_slots", type=int, default=10)
    p_cycle.set_defaults(func=cmd_cycle)

    p_run = sub.add_parser("run", help="run the 24/7 loop until switch OFF / bounded failure")
    p_run.add_argument("--max-cycles", dest="max_cycles", type=int, default=None)
    p_run.add_argument("--sleep-seconds", dest="sleep_seconds", type=float, default=60.0)
    p_run.add_argument("--total-slots", dest="total_slots", type=int, default=10)
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify", help="verify_integrity() every production ledger")
    p_verify.set_defaults(func=cmd_verify)

    p_products = sub.add_parser("products", help="list every registered EA product")
    p_products.set_defaults(func=cmd_products)

    p_queue = sub.add_parser("queue", help="opportunity queue summary")
    p_queue.set_defaults(func=cmd_queue)

    p_health = sub.add_parser("health", help="real, observational live health check")
    p_health.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p_health.set_defaults(func=cmd_health)

    p_watchdog = sub.add_parser("watchdog", help="foreground: keep exactly one Supervisor alive (spec Phase 6)")
    p_watchdog.add_argument("--max-iterations", dest="max_iterations", type=int, default=None,
                            help="for testing/soak runs only -- omit for a real, unbounded watchdog")
    p_watchdog.set_defaults(func=cmd_watchdog)

    p_service = sub.add_parser("service", help="Windows-service-style control of the watchdog process")
    service_sub = p_service.add_subparsers(dest="service_command", required=True)

    p_svc_install = service_sub.add_parser("install", help="register the watchdog to start at Windows boot")
    p_svc_install.set_defaults(func=cmd_service_install)

    p_svc_uninstall = service_sub.add_parser("uninstall", help="remove the boot registration")
    p_svc_uninstall.set_defaults(func=cmd_service_uninstall)

    p_svc_start = service_sub.add_parser("start", help="start the watchdog now (background)")
    p_svc_start.set_defaults(func=cmd_service_start)

    p_svc_stop = service_sub.add_parser("stop", help="ask the watchdog to stop gracefully")
    p_svc_stop.add_argument("--timeout-seconds", dest="timeout_seconds", type=float, default=15.0)
    p_svc_stop.set_defaults(func=cmd_service_stop)

    p_svc_restart = service_sub.add_parser("restart", help="stop then start")
    p_svc_restart.add_argument("--timeout-seconds", dest="timeout_seconds", type=float, default=15.0)
    p_svc_restart.set_defaults(func=cmd_service_restart)

    p_svc_status = service_sub.add_parser("status", help="is the watchdog alive right now")
    p_svc_status.set_defaults(func=cmd_service_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
