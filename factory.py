#!/usr/bin/env python3
"""
ML-001 STRATEGY FACTORY -- command line interface.

    python3 factory.py observe                 # GEN 8: market observations
    python3 factory.py discover                # GEN 7: observations -> hypotheses
    python3 factory.py evaluate                # GEN 9-11: train + internal validation
    python3 factory.py cycle                   # observe -> discover -> evaluate
    python3 factory.py status                  # factory + governance state
    python3 factory.py holdout status          # sealed holdout state (no data access)
    python3 factory.py failures                # failure library summary

Deliberately ABSENT: any command that reads the sealed holdout. Replication
(GEN 13) requires an explicit authorization code and is invoked only through
discovery.replication by a governance-approved script -- never casually from
a shell.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))


def cmd_observe(args):
    from discovery.observatory import main as observe_main
    return observe_main()


def cmd_discover(args):
    from discovery.engine import main as discover_main
    return discover_main()


def cmd_evaluate(args):
    from discovery.evaluation import main as eval_main
    return eval_main()


def cmd_cycle(args):
    for step in (cmd_observe, cmd_discover, cmd_evaluate):
        print()
        rc = step(args)
        if rc != 0:
            return rc
    return 0


def cmd_status(args):
    from core.factory.evidence_vault import EvidenceVault
    print("=" * 70)
    print("ML-001 STRATEGY FACTORY -- STATUS")
    print("=" * 70)

    obs_p = REPO_ROOT / "reports/factory/market_observations.json"
    q_p = REPO_ROOT / "reports/factory/discovery_queue.json"
    ev_p = REPO_ROOT / "reports/factory/hypothesis_evaluation.json"

    if obs_p.exists():
        o = json.loads(obs_p.read_text())
        print(f"\nGEN 8 observatory : {o['observation_count']} observations, "
              f"{o['significant_count']} significant")
        print(f"  window          : {o['observation_window']['start']} .. "
              f"{o['observation_window']['end']}")
    if q_p.exists():
        q = json.loads(q_p.read_text())
        print(f"\nGEN 7 discovery   : {q['queue_size']} hypotheses queued, "
              f"{len(q['rejections'])} filtered out")
    if ev_p.exists():
        e = json.loads(ev_p.read_text())
        verdicts = {}
        for r in e["results"]:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        print(f"\nGEN 9-11 eval     : {len(e['results'])} tested, "
              f"{len(e['survivors'])} survivors")
        for v, c in sorted(verdicts.items()):
            print(f"  {v:20s} {c}")

    vault = EvidenceVault()
    print("\nSEALED EVIDENCE:")
    if not vault.datasets:
        print("  (none)")
    for ds_id, meta in vault.datasets.items():
        print(f"  {ds_id}")
        print(f"    status {meta.seal_status.value} | {meta.row_count} bars | "
              f"{meta.instrument} {meta.timeframe} {meta.timezone}")

    print("\nEDGE_STATUS: ", end="")
    if ev_p.exists() and json.loads(ev_p.read_text())["survivors"]:
        print("CANDIDATES_PENDING_ADVERSARIAL")
    else:
        print("NO_EDGE_FOUND")
    return 0


def cmd_holdout(args):
    from core.factory.evidence_vault import EvidenceVault
    vault = EvidenceVault()
    for ds_id, meta in vault.datasets.items():
        print(f"{ds_id}")
        print(f"  seal status      : {meta.seal_status.value}")
        print(f"  instrument       : {meta.instrument} {meta.timeframe} ({meta.timezone})")
        print(f"  coverage         : {meta.coverage_start} .. {meta.coverage_end}")
        print(f"  rows             : {meta.row_count}")
        print(f"  authorizations   : "
              f"{'YES' if ds_id in vault.authorizations else 'NONE'}")
        print(f"  consumptions     : "
              f"{sum(1 for c in vault.consumptions if c.dataset_id == ds_id)}")
    print("\n(no observation data is displayed -- metadata only, by design)")
    return 0


def cmd_failures(args):
    from core.factory.failure_library import FailureLibrary
    lib = FailureLibrary()
    counts = lib.count_by_category()
    print(f"FAILURE LIBRARY: {len(lib.all_failures())} records")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:35s} {n}")
    if args.verbose:
        print("\nPrevention rules accumulated:")
        seen = set()
        for f in lib.all_failures():
            if f.prevention_rule and f.prevention_rule not in seen:
                seen.add(f.prevention_rule)
                print(f"  - [{f.failure_id}] {f.prevention_rule}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="factory.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("observe", help="GEN 8: compute market observations").set_defaults(fn=cmd_observe)
    sub.add_parser("discover", help="GEN 7: observations -> hypotheses").set_defaults(fn=cmd_discover)
    sub.add_parser("evaluate", help="GEN 9-11: train + internal validation").set_defaults(fn=cmd_evaluate)
    sub.add_parser("cycle", help="observe -> discover -> evaluate").set_defaults(fn=cmd_cycle)
    sub.add_parser("status", help="factory and governance state").set_defaults(fn=cmd_status)
    h = sub.add_parser("holdout", help="sealed holdout metadata (never data)")
    h.add_argument("subcommand", nargs="?", default="status", choices=["status"])
    h.set_defaults(fn=cmd_holdout)
    f = sub.add_parser("failures", help="failure library summary")
    f.add_argument("-v", "--verbose", action="store_true", help="show prevention rules")
    f.set_defaults(fn=cmd_failures)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(args.fn(args))
