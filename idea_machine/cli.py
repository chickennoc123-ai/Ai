#!/usr/bin/env python3
"""IDEA MACHINE -- command line interface.

    python3 -m idea_machine.cli cycle       # scan -> ... -> submit to Factory
    python3 -m idea_machine.cli status      # ledger state
    python3 -m idea_machine.cli dashboard   # Phase 17 observability
    python3 -m idea_machine.cli governance  # what the machine may/may not do
    python3 -m idea_machine.cli verify      # replay every ledger, audit source
    python3 -m idea_machine.cli ingest FILE # apply Factory verdicts (JSON)

Deliberately ABSENT: any command that reads the holdout, authorizes GEN14, or
produces an EA. Those are not omissions to be filled in later -- the underlying
operations raise :class:`GovernanceViolation` by design.

``cycle`` reads its sources from a local corpus directory (``--corpus``). There
is no built-in network scanning: a provider that fetches the internet must be
registered explicitly by the operator, so an autonomous loop never generates
traffic nobody asked for.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from idea_machine.budget.manager import BudgetPolicy                      # noqa: E402
from idea_machine.core.store import DEFAULT_ROOT                          # noqa: E402
from idea_machine.economics.data_feasibility import (                     # noqa: E402
    DataCatalog,
    DatasetEntry,
)
from idea_machine.governance import guard                                 # noqa: E402
from idea_machine.integration.factory_bridge import FactoryResult         # noqa: E402
from idea_machine.observability.dashboard import build_dashboard, render_text  # noqa: E402
from idea_machine.pipeline import IdeaMachine                             # noqa: E402
from idea_machine.scanner.scanner import LocalCorpusProvider              # noqa: E402
from idea_machine.research_space.search_space import SearchSpace          # noqa: E402
from idea_machine.research_space.exploration_debt import (                # noqa: E402
    ExplorationDebtTracker, DEFAULT_DEBT_THRESHOLD,
)
from idea_machine.research_space.search_space_ledger import SearchSpaceLedger  # noqa: E402
from idea_machine.research_space.decision_record import DecisionLedger    # noqa: E402
from idea_machine.research_space import space_mapper, explain as explain_module  # noqa: E402


def _load_catalog(path: Path) -> DataCatalog:
    """Load the operator's dataset catalog. Absent file == empty catalog.

    An empty catalog blocks every idea, which is the correct default: the
    machine must not assume data it has not been told about.
    """
    if not path or not Path(path).exists():
        return DataCatalog()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return DataCatalog([DatasetEntry(**row) for row in payload])


def _machine(args) -> IdeaMachine:
    providers = []
    if args.corpus:
        providers.append(LocalCorpusProvider(Path(args.corpus)))
    return IdeaMachine(
        root=Path(args.root),
        providers=providers,
        catalog=_load_catalog(Path(args.catalog)) if args.catalog else DataCatalog(),
        budget_policy=BudgetPolicy(args.max_ideas, args.max_screened, args.max_experiments),
    )


def cmd_cycle(args) -> int:
    machine = _machine(args)
    report = machine.run_cycle(submit=not args.no_submit)
    print(json.dumps(report.to_dict(), indent=2))
    if report.submitted == 0:
        print(
            "\nNo experiment was submitted this cycle. That is a normal outcome: "
            "screening rejected everything, the budget was spent, or the data catalog "
            "is empty.",
            file=sys.stderr,
        )
    return 0


def cmd_status(args) -> int:
    print(json.dumps(_machine(args).status(), indent=2, default=str))
    return 0


def cmd_dashboard(args) -> int:
    dashboard = build_dashboard(_machine(args))
    if args.json:
        print(json.dumps(dashboard, indent=2, default=str))
    else:
        print(render_text(dashboard))
    return 0


def cmd_governance(args) -> int:
    print(json.dumps(guard.governance_report(), indent=2))
    return 0


def cmd_verify(args) -> int:
    machine = _machine(args)
    machine.verify_integrity()
    print("OK: every ledger replays cleanly and the source tree passes the governance audit.")
    return 0


def cmd_ingest(args) -> int:
    machine = _machine(args)
    payload = json.loads(Path(args.results).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else [payload]
    outcomes = machine.ingest_results([FactoryResult.from_dict(r) for r in rows])
    print(json.dumps([o.to_dict() for o in outcomes], indent=2))
    return 0


def cmd_space(args) -> int:
    """Phase 9: the research-space map (spec item 25)."""
    space = SearchSpace()
    ledger = SearchSpaceLedger()
    debt_tracker = ExplorationDebtTracker(DEFAULT_DEBT_THRESHOLD)
    history = ExplorationDebtTracker.touches_from_ledger(ledger.all())
    debt = debt_tracker.compute(history)

    rows = ledger.all()
    mode_counts: dict = {}
    for r in rows:
        if r.get("decision") == "ACCEPT":
            mode_counts[r["research_mode"]] = mode_counts.get(r["research_mode"], 0) + 1
    total_accepted = sum(mode_counts.values()) or 1
    mode_shares = {m: round(n / total_accepted, 4) for m, n in mode_counts.items()}

    space_map = space_mapper.build_space_map(space, debt=debt, mode_shares=mode_shares)
    if args.json:
        print(json.dumps(space_map, indent=2, default=str))
    else:
        print(space_mapper.render_text(space_map))
    return 0


def cmd_explain(args) -> int:
    """Phase 9: explain one decision (spec item 26)."""
    print(explain_module.render_explain(args.decision_id))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="idea_machine",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="ledger directory")
    p.add_argument("--corpus", default="", help="directory of *.json source documents")
    p.add_argument("--catalog", default="", help="JSON file describing available datasets")
    p.add_argument("--max-ideas", type=int, default=100, help="idea budget per window")
    p.add_argument("--max-screened", type=int, default=20, help="screening budget per window")
    p.add_argument("--max-experiments", type=int, default=5, help="experiment budget per window")

    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("cycle", help="run one full research cycle")
    c.add_argument("--no-submit", action="store_true", help="design experiments but do not hand off")
    c.set_defaults(fn=cmd_cycle)

    sub.add_parser("status", help="ledger state").set_defaults(fn=cmd_status)

    d = sub.add_parser("dashboard", help="Phase 17 observability")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.set_defaults(fn=cmd_dashboard)

    sub.add_parser("governance", help="declared authority boundary").set_defaults(fn=cmd_governance)
    sub.add_parser("verify", help="replay ledgers and audit the source tree").set_defaults(fn=cmd_verify)

    i = sub.add_parser("ingest", help="apply Strategy Factory verdicts")
    i.add_argument("results", help="JSON file: one FactoryResult object or a list of them")
    i.set_defaults(fn=cmd_ingest)

    sp = sub.add_parser("space", help="Phase 9: research-space map")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.set_defaults(fn=cmd_space)

    ex = sub.add_parser("explain", help="Phase 9: explain one decision")
    ex.add_argument("decision_id", help="decision id from the research_space_ledger / decision_records")
    ex.set_defaults(fn=cmd_explain)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
