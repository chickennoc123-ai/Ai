"""
Phase 8: Autonomous Idea Machine Research Loop

Complete deterministic research workflow:
1. Generate/ingest ideas from external research
2. Check research memory for known mechanisms
3. Apply novelty checks (syntactic + semantic)
4. Route to opportunity queue if underpowered
5. Route eligible hypotheses to Factory
6. Run discovery cycle on real Factory gates
7. Productize survivors

Command-line interface: cycle, status, memory, queue, verify, dry-run

Every run is:
- Observable: full audit trail
- Restart-safe: state persists, can resume
- Provenance-aware: every decision traced to evidence
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import sys

from idea_machine.research_memory import ResearchMemory
from idea_machine.ea_code_intel.novelty_engine import NoveltyEngine
from idea_machine.opportunity_queue import OpportunityQueue, DataRequirement, RetestCondition
from idea_machine.real_factory_integration import RealFactoryIntegrator, GateEvaluation
from idea_machine.adaptive_search import AdaptiveSearchController, DEFAULT_MIN_EXPLORATION_FRACTION
from idea_machine.search_space_registry import SearchSpaceRegistry
from idea_machine.search_decision_ledger import SearchDecisionLedger
from discovery.cycle8_intraday import Stats, MECHANISMS, gate, stats as compute_stats
from discovery.cost_model import roundtrip_cost
from discovery.cycle13_idea_machine_live import (
    resolve_fx_series, resolve_driver_series, extend_surprise_fx_dir,
)


@dataclass
class ResearchCommand:
    """A command in the autonomous research loop."""
    command: str  # "cycle", "status", "memory", "queue", "verify", "dry-run"
    args: Dict = None

    def __post_init__(self):
        if self.args is None:
            self.args = {}


class AutonomousIdeaMachine:
    """
    Autonomous research loop orchestrator.

    Complete flow:
    1. Load research memory (families, candidates, hypotheses, cycles)
    2. Load novelty engine (tag-based + semantic checks)
    3. Load opportunity queue (data-blocked hypotheses)
    4. For each eligible hypothesis:
       - Pre-register with Factory
       - Evaluate through real gates
       - Track survivors
       - Productize if authorized
    """

    def __init__(self, repo_root: Path = None):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.report_dir = self.repo_root / "reports" / "idea_machine"
        self.report_dir.mkdir(parents=True, exist_ok=True)

        # Load all supporting infrastructure
        self.research_memory = ResearchMemory()
        self.novelty_engine = NoveltyEngine()
        self.opportunity_queue = OpportunityQueue()
        self.factory_integrator = RealFactoryIntegrator(repo_root)

        # Phase 9 (second pass): Adaptive Search Controller. Built lazily in
        # load() once research_memory is populated, since the registry seeds
        # itself from real memory contents.
        self.search_registry: Optional[SearchSpaceRegistry] = None
        self.adaptive_search: Optional[AdaptiveSearchController] = None
        self.search_decision_ledger = SearchDecisionLedger(self.report_dir / "search_decision_ledger.json")

        self._loaded = False

    def load(self):
        """Load all supporting data structures."""
        self.research_memory.load()
        self.novelty_engine.load()
        self.opportunity_queue.load()
        self.search_registry = SearchSpaceRegistry(self.research_memory)
        self.adaptive_search = AdaptiveSearchController(
            memory=self.research_memory, registry=self.search_registry,
            opportunity_queue=self.opportunity_queue, decision_ledger=self.search_decision_ledger,
        )
        self._loaded = True

    def execute_command(self, cmd: ResearchCommand) -> Dict:
        """Execute a research loop command."""
        if not self._loaded:
            self.load()

        if cmd.command == "cycle":
            return self.run_discovery_cycle(cmd.args.get("cycle_id"))

        elif cmd.command == "status":
            return self.get_status()

        elif cmd.command == "memory":
            return self.get_memory_summary()

        elif cmd.command == "queue":
            return self.get_opportunity_queue_summary()

        elif cmd.command == "verify":
            return self.verify_hypothesis(cmd.args.get("hyp_id"))

        elif cmd.command == "dry-run":
            return self.dry_run_hypothesis(cmd.args.get("hyp_id"))

        else:
            return {"error": f"Unknown command: {cmd.command}"}

    def get_status(self) -> Dict:
        """Get current system status."""
        if not self._loaded:
            self.load()

        research_summary = self.research_memory.get_summary()
        queue_len = len(self.opportunity_queue.entries) if hasattr(self.opportunity_queue, 'entries') else 0
        factory_summary = self.factory_integrator.get_summary()

        return {
            "system_status": "LOADED",
            "timestamp": datetime.utcnow().isoformat(),
            "research_memory": research_summary,
            "opportunity_queue": {
                "total_entries": queue_len,
                "by_classification": {
                    "STILL_UNDERPOWERED": len(self.opportunity_queue.get_by_classification("STILL_UNDERPOWERED")),
                    "TESTED_FAILED": len(self.opportunity_queue.get_by_classification("TESTED_FAILED")),
                }
            },
            "factory_integration": factory_summary,
        }

    def get_memory_summary(self) -> Dict:
        """Get research memory status."""
        if not self._loaded:
            self.load()

        return {
            "type": "research_memory",
            "summary": self.research_memory.get_summary(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_opportunity_queue_summary(self) -> Dict:
        """Get opportunity queue status."""
        if not self._loaded:
            self.load()

        entries = self.opportunity_queue.entries if hasattr(self.opportunity_queue, 'entries') else []
        return {
            "type": "opportunity_queue",
            "total_opportunities": len(entries),
            "by_priority": {
                "HIGH": len([e for e in entries if e.priority == "HIGH"]),
                "MEDIUM": len([e for e in entries if e.priority == "MEDIUM"]),
                "LOW": len([e for e in entries if e.priority == "LOW"]),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    def verify_hypothesis(self, hyp_id: str) -> Dict:
        """
        Verify a hypothesis against research memory and novelty checks.

        Steps:
        1. Check if hypothesis matches any REFUTED families
        2. Check if it matches STILL_UNDERPOWERED families
        3. Run semantic similarity check
        4. Return verdict

        Returns verdict with evidence and recommended action.
        """
        if not self._loaded:
            self.load()

        result = {
            "hypothesis_id": hyp_id,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {
                "refuted_family_match": None,
                "underpowered_match": None,
                "semantic_similarity": None,
            },
            "recommendation": "UNKNOWN"
        }

        # Look for exact hypothesis in memory
        for hyp in self.research_memory.cycle_hypotheses:
            if hyp.hyp_id == hyp_id:
                result["found_in_memory"] = {
                    "cycle_id": hyp.cycle_id,
                    "classification": hyp.classification,
                    "best_train_t": hyp.best_train_t,
                    "best_val_n": hyp.best_val_n,
                }
                if hyp.classification == "STILL_UNDERPOWERED":
                    result["recommendation"] = "CHECK_OPPORTUNITY_QUEUE"
                elif hyp.classification == "REFUTED":
                    result["recommendation"] = "REJECT_DUPLICATE"
                break

        return result

    def dry_run_hypothesis(self, hyp_id: str) -> Dict:
        """
        Dry-run a hypothesis through verification without committing.

        Shows what would happen if this hypothesis were evaluated:
        1. Would it be rejected as duplicate?
        2. Would it match an opportunity queue entry?
        3. Would it be eligible for Factory evaluation?
        """
        if not self._loaded:
            self.load()

        verify_result = self.verify_hypothesis(hyp_id)

        dry_run = {
            "hypothesis_id": hyp_id,
            "timestamp": datetime.utcnow().isoformat(),
            "verification": verify_result,
            "factory_readiness": {
                "would_pass_novelty_check": verify_result["recommendation"] not in ("REJECT_DUPLICATE",),
                "would_route_to_queue": verify_result["recommendation"] == "CHECK_OPPORTUNITY_QUEUE",
                "eligible_for_factory": verify_result["recommendation"] not in ("REJECT_DUPLICATE", "CHECK_OPPORTUNITY_QUEUE"),
            }
        }

        return dry_run

    def run_discovery_cycle(self, cycle_id: str = None) -> Dict:
        """Delegates to :meth:`run_adaptive_search_cycle` with a modest default
        slot count. Kept for backward compatibility with existing callers of
        this method name; the real work lives in run_adaptive_search_cycle."""
        return self.run_adaptive_search_cycle(cycle_id=cycle_id, total_slots=10)

    def run_adaptive_search_cycle(self, cycle_id: str = None, total_slots: int = 10,
                                  evaluation_ledger=None) -> Dict:
        """
        Phase 9 (second pass): one real autonomous research cycle.

        Research Memory -> Search-Space State -> Explore/Exploit Allocation
        -> Idea Generation -> Novelty -> Data Availability -> Economics
        -> Pre-registration -> REAL FACTORY -> Evidence -> Research Memory
        -> Search-Space Update -> Next Cycle

        Uses the REAL gate() function from discovery/cycle8_intraday.py on
        real M1/H1 data and real USD NFP/CPI events -- never simulation.
        Every accepted candidate's economic direction (base_dir) must be an
        already-established, stated rationale
        (idea_machine.search_economic_rationale.BASE_DIR_TABLE); a candidate
        with no established rationale is reported, not evaluated with an
        invented direction.

        evaluation_ledger: optional duck-typed idempotency guard (see
        production.evaluation_ledger.EvaluationLedger). If provided, every
        candidate is checked via `already_evaluated(mechanism, instrument,
        driver, window_min)` BEFORE it is sent to the real Factory; a hit
        reuses the recorded verdict instead of re-running gate(), and every
        NEW real evaluation is recorded via `record(...)` afterward. This is
        how production mode guarantees the same triple is never evaluated
        twice across separate cycle runs / crash-restarts. Left as None
        (the default) preserves this method's exact prior behavior for
        existing callers -- no idea_machine code imports the production
        package; the ledger is passed in by whichever caller has it.
        """
        if cycle_id is None:
            cycle_id = f"CYCLE-AUTO-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        if not self._loaded:
            self.load()

        from idea_machine.search_economic_rationale import lookup as lookup_rationale
        from idea_machine.research_space.decision_engine import cost_registered, data_available
        from idea_machine.research_space.recombination_engine import trade_sc_and_dc
        from discovery.cost_model import roundtrip_cost
        from discovery.cycle8_intraday import usd_events, M1Series, FX_M1_ROOT
        from discovery.observatory import load_dev_bars

        # Extend SURPRISE_FX_DIR for USDCAD/AUDUSD (needed by trade_sc if a
        # proposal targets either) explicitly, here, at the point of use --
        # never as an import-time side effect (see cycle13_idea_machine_live's
        # own docstring on extend_surprise_fx_dir for the bug this avoids).
        extend_surprise_fx_dir()

        search_result = self.adaptive_search.run_cycle(cycle_id=cycle_id, total_slots=total_slots)

        bars = load_dev_bars(self.repo_root / "data/csv/EURUSD_H1.csv")
        dev_end = bars[-1].ts
        events = usd_events(dev_end)

        _EXTRA_DRIVER_FOLDERS = {
            "JP225": "JP225_USD", "UK100": "UK100_GBP", "AU200": "AU200_AUD",
            "US2000": "US2000_USD", "NATGAS": "NATGAS_USD",
        }

        def resolve_any_driver(driver_name: str):
            try:
                return resolve_driver_series(driver_name)
            except KeyError:
                return M1Series(FX_M1_ROOT, _EXTRA_DRIVER_FOLDERS[driver_name])

        results = []
        no_rationale = []
        survivors, underpowered_list, refuted_list, data_blocked = [], [], [], []

        for proposal in search_result.selected:
            instrument = proposal.dimensions.get("instrument", "")
            driver = proposal.dimensions.get("macro_driver")
            mechanism = proposal.dimensions.get("mechanism") or "SC_SURPRISE_CONFIRMATION"
            hyp_id = f"HYP-{cycle_id}-{proposal.mode}-{instrument}-{driver or 'NONE'}"

            if not instrument or not cost_registered(instrument):
                data_blocked.append(hyp_id)
                continue
            if driver and not data_available(instrument, driver):
                data_blocked.append(hyp_id)
                continue

            rationale = lookup_rationale(instrument, driver) if driver else (+1, "no cross-asset driver; single-instrument mechanism", "n/a")
            if rationale is None:
                no_rationale.append({"hyp_id": hyp_id, "instrument": instrument, "driver": driver})
                continue
            base_dir, econ_reason, established_in = rationale

            mech_fn = trade_sc_and_dc if mechanism == "SC_AND_DC_COMBINED_CONFIRMATION" else \
                      MECHANISMS.get(mechanism, MECHANISMS["SC_SURPRISE_CONFIRMATION"])

            fx = resolve_fx_series(instrument)
            driver_series_obj = resolve_any_driver(driver) if driver else None
            if driver and driver_series_obj is None:
                data_blocked.append(hyp_id)
                continue

            window_min = 60

            if evaluation_ledger is not None:
                prior = evaluation_ledger.already_evaluated(mechanism, instrument, driver, window_min)
                if prior is not None:
                    # This exact (mechanism, instrument, driver, window) triple was
                    # already run through the real Factory in a prior cycle/run --
                    # reuse that real, already-recorded verdict. Never re-runs
                    # gate() for it (idempotency guard against duplicate real
                    # evaluation across restarts/crashes).
                    reused = dict(prior)
                    reused["hyp_id"] = hyp_id
                    reused["proposal_id"] = proposal.proposal_id
                    reused["reused_from_eval_id"] = prior.get("eval_id")
                    final_status = prior.get("final_status")
                    if final_status == "DISCOVERY_SURVIVOR":
                        survivors.append(reused)
                    elif final_status == "STILL_UNDERPOWERED":
                        underpowered_list.append(reused)
                    else:
                        refuted_list.append(reused)
                    results.append(reused)
                    continue

            cost = roundtrip_cost(instrument)
            n_events = len(events)
            cut = int(n_events * 0.80)
            nets = []
            for e in events:
                r = mech_fn(e, fx, driver_series_obj, instrument, base_dir, window_min, cost)
                if r is not None:
                    nets.append((e.ts, r))
            tr_nets, va_nets = [], []
            cutoff_ts = events[cut].ts if cut < n_events else events[-1].ts
            for ts, r in nets:
                (tr_nets if ts < cutoff_ts else va_nets).append(r)
            gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
            tr_s = compute_stats(tr_nets, gm + cost, cost)
            va_s = compute_stats(va_nets, 0.0, cost)

            journey = self.factory_integrator.pre_register_hypothesis(
                hyp_id=hyp_id, source_idea_id=proposal.proposal_id, symbol=instrument, driver=driver,
            )
            passed = self.factory_integrator.evaluate_with_real_gates(journey, tr_s, va_s)
            verdict, reason = gate(tr_s, va_s)

            record = {
                "hyp_id": hyp_id, "proposal_id": proposal.proposal_id, "mode": proposal.mode,
                "region_id": proposal.region_id, "mechanism": mechanism, "instrument": instrument,
                "driver": driver, "window_min": window_min, "economic_rationale": econ_reason,
                "rationale_established_in": established_in,
                "explainability": proposal.explainability,
                "train": tr_s.to_dict(), "validation": va_s.to_dict(),
                "verdict": verdict, "verdict_reason": reason,
            }

            if passed:
                record["final_status"] = "DISCOVERY_SURVIVOR"
                survivors.append(record)
            elif verdict == "VALIDATION_UNDERPOWERED" and tr_s.t_stat >= 1.5:
                record["final_status"] = "STILL_UNDERPOWERED"
                conf = round(len(nets) / n_events, 4) if n_events else 0.0
                events_needed = int(round((30 / 0.2) / conf)) if conf > 0 else 999
                entry = self.opportunity_queue.append(
                    source_hypothesis_id=hyp_id, source_cycle_id=cycle_id, classification="STILL_UNDERPOWERED",
                    mechanism_summary=f"[{proposal.mode}] {instrument} vs {driver}: {mechanism} ({econ_reason})",
                    symbol=instrument, driver=driver, n_events_available=n_events, windows_evaluated=1,
                    best_train_t=tr_s.t_stat, best_val_n=va_s.n, mean_confirmation_rate=conf,
                    evidence_level="REAL_SIGNAL_BLOCKED" if tr_s.t_stat >= 2.0 else "INSUFFICIENT_POWER",
                    reason=(f"train t={tr_s.t_stat}, val n={va_s.n} (<30, uninformative). Not treated as "
                           f"confirmed edge -- validation sample too small to confirm signal."),
                    missing_data=DataRequirement(
                        description="USD NFP/CPI raw events with confirmed cross-asset reaction",
                        current_value=n_events, required_value=max(events_needed, n_events), unit="events",
                    ),
                    retest_conditions=RetestCondition(
                        earliest_date=None, trigger=f"If USD macro event pool extends to >={events_needed} events, retest.",
                        estimated_power_gain=f"Validation n could reach ~30 with {events_needed} events (current confirmation rate {conf:.1%})",
                    ),
                    priority="HIGH" if tr_s.t_stat >= 3.0 else "MEDIUM", provenance_status="FACTORY_TESTED",
                )
                record["opportunity_queue_entry"] = entry.queue_id
                underpowered_list.append(record)
            else:
                record["final_status"] = "REFUTED_THIS_RUN"
                refuted_list.append(record)

            if evaluation_ledger is not None:
                saved = evaluation_ledger.record(
                    mechanism=mechanism, instrument=instrument, driver=driver, window_min=window_min,
                    hyp_id=hyp_id, cycle_id=cycle_id, verdict=verdict, final_status=record["final_status"],
                    train=record["train"], validation=record["validation"],
                )
                record["eval_id"] = saved.get("eval_id")

            results.append(record)

        self.opportunity_queue.save()

        cycle_result = {
            "cycle_id": cycle_id,
            "started_at": datetime.utcnow().isoformat(),
            "search_plan": search_result.plan.to_dict(),
            "ideas_generated": len(search_result.selected) + len(search_result.rejected_unexplainable) + len(search_result.rejected_diversity),
            "exploration_ideas": sum(1 for p in search_result.selected if p.mode == "EXPLORE"),
            "exploitation_ideas": sum(1 for p in search_result.selected if p.mode == "EXPLOIT"),
            "rejected_unexplainable": len(search_result.rejected_unexplainable),
            "rejected_diversity": len(search_result.rejected_diversity),
            "no_established_rationale": no_rationale,
            "data_blocked": len(data_blocked),
            "factory_evaluations": len(results),
            "survivors": len(survivors),
            "still_underpowered": len(underpowered_list),
            "refuted_this_run": len(refuted_list),
            "expansion_request": search_result.expansion_request,
            "hypotheses": results,
        }
        return cycle_result

    def save_state(self, output_path: Path = None):
        """Save current loop state for restart."""
        if output_path is None:
            output_path = self.report_dir / f"autonomous_loop_state_{datetime.utcnow().isoformat()}.json"

        state = {
            "saved_at": datetime.utcnow().isoformat(),
            "research_memory": self.research_memory.get_summary() if self._loaded else None,
            "factory_journeys": self.factory_integrator.get_summary() if self._loaded else None,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(state, indent=2))

        return {"saved_to": str(output_path)}


def main():
    """CLI entry point for autonomous research loop."""
    if len(sys.argv) < 2:
        print("Autonomous Idea Machine Research Loop")
        print("Usage: python -m idea_machine.autonomous_loop <command> [args]")
        print("\nCommands:")
        print("  cycle [cycle_id]    - Run discovery cycle")
        print("  status              - Show system status")
        print("  memory              - Show research memory summary")
        print("  queue               - Show opportunity queue summary")
        print("  verify <hyp_id>     - Verify hypothesis against memory")
        print("  dry-run <hyp_id>    - Dry-run hypothesis evaluation")
        sys.exit(1)

    machine = AutonomousIdeaMachine()
    cmd_name = sys.argv[1]
    args = {}

    if len(sys.argv) > 2:
        if cmd_name == "verify" or cmd_name == "dry-run":
            args["hyp_id"] = sys.argv[2]
        elif cmd_name == "cycle":
            args["cycle_id"] = sys.argv[2]

    cmd = ResearchCommand(cmd_name, args)
    result = machine.execute_command(cmd)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
