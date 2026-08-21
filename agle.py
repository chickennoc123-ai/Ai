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

This wraps, and does not reimplement, production.master_switch.MasterSwitch,
production.supervisor.ProductionSupervisor, production.ea_registry.
EAProductRegistry, and idea_machine.opportunity_queue.OpportunityQueue.

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
from production.supervisor import DEFAULT_HEARTBEAT_PATH, ProductionSupervisor  # noqa: E402


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
    report = sup.run_one_cycle(total_slots=args.total_slots)
    _print(report.to_dict())
    return 0


def cmd_run(args) -> int:
    sup = ProductionSupervisor()
    if not sup.switch.is_on():
        print("MASTER SWITCH is OFF -- refusing to run. Run `agle.py start` first.")
        return 1
    summary = sup.run_forever(max_cycles=args.max_cycles, sleep_seconds=args.sleep_seconds,
                              total_slots=args.total_slots)
    _print(summary)
    return 0


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
