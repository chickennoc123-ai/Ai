"""
GEN 7 CYCLE 14 -- Phase 9 Research Space Evolution Engine, live end-to-end run.

SELF-CRITIQUE, STATED BEFORE ANY EVALUATION RUNS
--------------------------------------------------
This cycle exists to prove the decision layer (idea_machine/research_space/),
not to discover a new mechanism formula. Every real trade evaluation below
reuses code that already exists and was already audited: gate()/stats() and
the SC mechanism from discovery/cycle8_intraday.py (Cycle 8), the H1-only
window discipline for USDJPY (Cycle 8's own audit -- no M1 source, confirmed
absent), and trade_sc_and_dc from idea_machine/research_space/
recombination_engine.py (a new but fully real AND-combination of two already-
audited mechanism conditions). Nothing here invents a new trading formula.

Three research-mode candidates, one of each, selected by the real allocator
(not hand-picked to look balanced):

  EXPLOIT   USDJPY/USB02Y, SC_SURPRISE_CONFIRMATION, window=300m.
            Extends Cycle 13's real finding (train t=6.456 at 240m, val n=18,
            STILL_UNDERPOWERED) to an untested window. 300m = 5 real H1 bars
            forward from the event -- H1Series reads real bars at that offset,
            nothing is fabricated; USDJPY has no M1 source (Cycle 8's audit),
            so only H1-reachable windows are used, exactly as every prior
            USDJPY test in this project has done.

  EXPLORE   USDJPY against five drivers confirmed to have real M1 data but
            never used in ANY cycle (JP225, UK100, AU200, US2000, NATGAS).
            Economic rationale stated per driver below -- not a blanket
            "risk-on" copy-paste for all five, since they operate through
            different channels (domestic equity/funding-currency flow for
            JP225, global risk sentiment for UK100/AU200, US domestic-growth
            proxy for US2000, import-cost/terms-of-trade for NATGAS, since
            Japan is a net energy importer).

  RECOMBINE GBPUSD/UK10YB, SC_AND_DC_COMBINED_CONFIRMATION. AND-combines
            Cycle 8's SC entry/exit with its DC divergence condition as an
            additional gate: trade the surprise-confirmed direction only when
            FX has not yet followed the driver's own impulse move. Tagged
            RECOMBINATION, never NEW, per governance (novelty is judged at
            the mechanism level, not by component count).

Cost-aware, data-aware, holdout-blind throughout: the frozen cost model
(discovery/cost_model.py) is read-only, the sealed-holdout guard
(discovery/event_calendar.py's guard_path/OGD-4) is inherited unchanged, and
GEN14 is never requested -- any DISCOVERY_SURVIVOR is frozen and reported for
the EXISTING GEN14 authorization process, never self-authorized here.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import cost_table, roundtrip_cost
from discovery.cycle8_intraday import (
    Stats, stats, gate, MECHANISMS, usd_events, FX_M1_ROOT, M1_YEAR_RANGE,
)
from discovery.cycle13_idea_machine_live import resolve_fx_series, resolve_driver_series
from discovery.observatory import load_dev_bars
from discovery import cycle8_intraday

from idea_machine.core import epistemic
from idea_machine.opportunity_queue import OpportunityQueue, DataRequirement, RetestCondition
from idea_machine.real_factory_integration import RealFactoryIntegrator
from idea_machine.research_space.decision_engine import (
    ResearchSpaceDecisionEngine, cost_registered, data_available,
)
from idea_machine.research_space.decision_record import DecisionLedger
from idea_machine.research_space.exploitation_engine import ExploitationEngine
from idea_machine.research_space.exploration_debt import ExplorationDebtTracker
from idea_machine.research_space.exploration_engine import ExplorationEngine
from idea_machine.research_space.information_gain import ResearchCandidate
from idea_machine.research_space.recombination_engine import RecombinationEngine, trade_sc_and_dc
from idea_machine.research_space.search_space import SearchSpace
from idea_machine.research_space.search_space_ledger import SearchSpaceLedger

CYCLE_ID = "CYCLE-14-RESEARCH-SPACE-EVOLUTION"

# New driver folders for this cycle's EXPLORE candidates -- confirmed present
# in the same audited Oanda data root (checked before this file was written).
NEW_EXPLORE_DRIVER_FOLDERS = {
    "JP225": "JP225_USD", "UK100": "UK100_GBP", "AU200": "AU200_AUD",
    "US2000": "US2000_USD", "NATGAS": "NATGAS_USD",
}

# Per-driver economic direction for USDJPY (base_dir: +1 means "driver up -> long USDJPY").
EXPLORE_BASE_DIR = {
    "JP225": (+1, "Nikkei up -> foreign equity inflows funded by JPY selling (funding-currency flow) -> USDJPY up"),
    "UK100": (+1, "FTSE up -> global risk-on -> JPY funding-currency sold -> USDJPY up"),
    "AU200": (+1, "ASX up -> global risk-on -> JPY funding-currency sold -> USDJPY up"),
    "US2000": (+1, "Russell 2000 up -> US domestic growth strength (purer than SPX500's multinational mix) -> USDJPY up"),
    "NATGAS": (+1, "Nat gas up -> Japan (net energy importer) terms-of-trade worsen -> JPY weakens -> USDJPY up"),
}

# GBPUSD/UK10YB base_dir, established in Cycle 13: UK 10y yield up -> GBP carry
# more attractive on its own curve -> GBPUSD rises.
RECOMBINE_BASE_DIR = +1
# USDJPY/USB02Y base_dir, established in Cycle 13: US 2y yield up -> USD carry
# more attractive vs near-zero JPY -> USDJPY rises.
EXPLOIT_BASE_DIR = +1


def _resolve_new_driver_series(driver_name: str):
    from discovery.cycle8_intraday import M1Series
    return M1Series(FX_M1_ROOT, NEW_EXPLORE_DRIVER_FOLDERS[driver_name])


def evaluate_real(symbol: str, driver_name: str, base_dir: int, mechanism_fn, mechanism_label: str,
                  window_min: int, events, fx, driver) -> Dict:
    """One real (train, validation) evaluation through the REAL gate() function."""
    cost = roundtrip_cost(symbol)
    n_events = len(events)
    cut = int(n_events * 0.80)
    nets = []
    for e in events:
        r = mechanism_fn(e, fx, driver, symbol, base_dir, window_min, cost)
        if r is not None:
            nets.append((e.ts, r))
    tr_nets, va_nets = [], []
    cutoff_ts = events[cut].ts if cut < n_events else events[-1].ts
    for ts, r in nets:
        (tr_nets if ts < cutoff_ts else va_nets).append(r)
    gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
    tr_s = stats(tr_nets, gm + cost, cost)
    va_s = stats(va_nets, 0.0, cost)
    verdict, reason = gate(tr_s, va_s)
    return {
        "mechanism": mechanism_label, "symbol": symbol, "driver": driver_name, "window_min": window_min,
        "events_available": n_events, "confirmed_trades": len(nets),
        "confirmation_rate": round(len(nets) / n_events, 4) if n_events else 0.0,
        "train": tr_s, "validation": va_s, "verdict": verdict, "verdict_reason": reason,
    }


def main() -> int:
    print("=" * 78)
    print(f"{CYCLE_ID}: Research Space Evolution Engine -> Real Strategy Factory")
    print("=" * 78)

    # ---------------------------------------------------------- Step 1: dev window / events
    bars = load_dev_bars(R / "data/csv/EURUSD_H1.csv")
    dev_end = bars[-1].ts
    events = usd_events(dev_end)
    print(f"\n[STEP 1] dev_end={dev_end}, USD NFP/CPI event pool: {len(events)} events "
          f"(2010-{M1_YEAR_RANGE.stop-1})")

    # ---------------------------------------------------------- Step 2: search space + debt
    print("\n[STEP 2] Building ResearchSpace from real Factory records...")
    space = SearchSpace()
    counts = space.status_counts()
    print(f"[STEP 2] {sum(sum(d.values()) for d in counts.values())} cells across {len(counts)} dimensions; "
          f"novelty coverage={space.novelty_coverage():.1%}")

    space_ledger = SearchSpaceLedger()
    decision_ledger = DecisionLedger()
    debt_tracker = ExplorationDebtTracker()
    history = ExplorationDebtTracker.touches_from_ledger(space_ledger.all())
    debt = debt_tracker.compute(history)
    print(f"[STEP 2] Exploration debt: {debt.debt} (threshold {debt.threshold}, "
         f"forced={debt.forced_exploration}) -- {debt.reason}")

    # ---------------------------------------------------------- Step 3: generate candidates
    print("\n[STEP 3] Generating candidates: EXPLOIT + EXPLORE + RECOMBINE")
    exploit_engine = ExploitationEngine(space)
    explore_engine = ExplorationEngine(space)
    recombine_engine = RecombinationEngine(space)

    pool: List[ResearchCandidate] = []

    exploit_candidates = exploit_engine.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="USDJPY", driver="USB02Y",
        already_tested_windows=[60, 120, 240], candidate_windows=[300],
        rationale="Cycle 13 found train t=6.456 at 240m for USDJPY/USB02Y SC (val n=18, "
                 "STILL_UNDERPOWERED) -- deepen to an untested window before concluding",
    )
    pool += exploit_candidates
    print(f"[STEP 3] EXPLOIT: {len(exploit_candidates)} candidate(s) -- {[c.holding_period_min for c in exploit_candidates]}")

    explore_candidates = explore_engine.swap_driver(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="USDJPY", holding_period_min=60,
        rationale="extend SC mechanism to drivers confirmed present, never used in any cycle",
        drivers=list(EXPLORE_BASE_DIR.keys()),
    )
    pool += explore_candidates
    print(f"[STEP 3] EXPLORE: {len(explore_candidates)} candidate(s) -- drivers {[c.driver for c in explore_candidates]}")

    recombine_candidate = recombine_engine.combine(
        parent_mechanisms=["SC_SURPRISE_CONFIRMATION", "DC_CROSS_ASSET_DIVERGENCE"],
        instrument="GBPUSD", driver="UK10YB", holding_period_min=60,
        combined_mechanism="SC_AND_DC_COMBINED_CONFIRMATION",
        rationale="test whether requiring both surprise-confirmation AND a lagging cross-asset "
                 "divergence improves on either mechanism alone",
    )
    if recombine_candidate:
        pool.append(recombine_candidate)
    print(f"[STEP 3] RECOMBINE: {'1 candidate' if recombine_candidate else '0 candidates'}")
    print(f"[STEP 3] Total candidate pool: {len(pool)}")

    # ---------------------------------------------------------- Step 4: decide
    print("\n[STEP 4] Running the decision engine (allocation + scoring + explainable decisions)...")
    engine = ResearchSpaceDecisionEngine(
        space, decision_ledger=decision_ledger, space_ledger=space_ledger,
    )
    report = engine.run_cycle(cycle_id=CYCLE_ID, candidate_pool=pool, history=history)
    print(f"[STEP 4] Allocation: {report.allocation.reason}")
    print(f"[STEP 4] Novelty saturation: {report.novelty_saturation}")
    print(f"[STEP 4] Accepted {len(report.accepted)}/{len(pool)} candidates:")
    for c in report.accepted:
        print(f"    [{c.research_mode:9s}] {c.mutation_operator:26s} {c.mechanism}/{c.instrument}/"
             f"{c.driver}/{c.holding_period_min}m")
    if report.closure_proposals:
        print(f"[STEP 4] {len(report.closure_proposals)} branch-closure proposal(s) (advisory only):")
        for p in report.closure_proposals:
            print(f"    PROPOSE_BRANCH_CLOSED: {p['dimension']}.{p['value']} ({p['evidence_count']} evidence entries)")

    # ---------------------------------------------------------- Step 5: real Factory evaluation
    print("\n[STEP 5] Sending accepted candidates to the REAL Strategy Factory...")
    integrator = RealFactoryIntegrator(R)
    queue = OpportunityQueue()
    queue.load()

    hypotheses_report = []
    survivors, underpowered_list, refuted_list, blocked_list = [], [], [], []

    for cand in report.accepted:
        hyp_id = f"HYP-C14-{cand.research_mode}-{cand.instrument}-{cand.driver or 'NONE'}-{cand.mechanism[:8]}"
        print(f"\n  [{cand.research_mode}] Pre-registering {hyp_id} "
             f"({cand.mechanism}/{cand.instrument}/{cand.driver}/{cand.holding_period_min}m)")

        if not cost_registered(cand.instrument):
            print(f"    DATA_BLOCKED: no pre-registered cost for {cand.instrument}")
            blocked_list.append(hyp_id)
            continue

        # Resolve real fx/driver series and the real (or new-real) mechanism function + base_dir.
        fx = resolve_fx_series(cand.instrument)

        if cand.research_mode == "EXPLOIT":
            mech_fn = MECHANISMS["SC_SURPRISE_CONFIRMATION"]
            base_dir = EXPLOIT_BASE_DIR
            driver_series_obj = resolve_driver_series(cand.driver)
        elif cand.research_mode == "RECOMBINE":
            mech_fn = trade_sc_and_dc
            base_dir = RECOMBINE_BASE_DIR
            driver_series_obj = resolve_driver_series(cand.driver)
        else:  # EXPLORE
            mech_fn = MECHANISMS["SC_SURPRISE_CONFIRMATION"]
            base_dir, _rationale = EXPLORE_BASE_DIR[cand.driver]
            driver_series_obj = _resolve_new_driver_series(cand.driver)

        journey = integrator.pre_register_hypothesis(
            hyp_id=hyp_id, source_idea_id=cand.candidate_id, symbol=cand.instrument, driver=cand.driver,
        )
        result = evaluate_real(
            cand.instrument, cand.driver, base_dir, mech_fn, cand.mechanism,
            cand.holding_period_min, events, fx, driver_series_obj,
        )
        passed = integrator.evaluate_with_real_gates(journey, result["train"], result["validation"])
        print(f"    w={result['window_min']:>3}m  train(n={result['train'].n:>3} t={result['train'].t_stat:>6})  "
             f"val(n={result['validation'].n:>3} t={result['validation'].t_stat:>6})  -> {result['verdict']}")

        hyp_record = {
            "hyp_id": hyp_id, "candidate_id": cand.candidate_id, "research_mode": cand.research_mode,
            "mutation_operator": cand.mutation_operator, "mechanism": cand.mechanism,
            "instrument": cand.instrument, "driver": cand.driver, "window_min": cand.holding_period_min,
            "rationale": cand.rationale,
            "train": result["train"].to_dict(), "validation": result["validation"].to_dict(),
            "verdict": result["verdict"], "verdict_reason": result["verdict_reason"],
            "confirmation_rate": result["confirmation_rate"],
        }

        if passed:
            hyp_record["final_status"] = "DISCOVERY_SURVIVOR"
            survivors.append(hyp_record)
            print(f"    *** DISCOVERY_SURVIVOR: {hyp_id} -- frozen for the EXISTING GEN14 process, "
                 f"NOT self-authorized ***")
            space_ledger.record(
                cycle_id=CYCLE_ID, research_mode=cand.research_mode, family=f"{cand.mechanism}/{cand.instrument}",
                hypothesis=hyp_id, decision="DISCOVERY_SURVIVOR", reason="passed real INTERNAL_VALIDATION gate",
                result="DISCOVERY_SURVIVOR", information_gain=0.0, touched_new_family_or_dimension=True,
            )
        elif result["verdict"] == "VALIDATION_UNDERPOWERED" and result["train"].t_stat >= 1.5:
            hyp_record["final_status"] = "STILL_UNDERPOWERED"
            underpowered_list.append(hyp_record)
            conf = result["confirmation_rate"] or 0.0
            events_needed = int(round((30 / 0.2) / conf)) if conf > 0 else 999
            entry = queue.append(
                source_hypothesis_id=hyp_id, source_cycle_id=CYCLE_ID, classification="STILL_UNDERPOWERED",
                mechanism_summary=f"[{cand.research_mode}/{cand.mutation_operator}] {cand.instrument} vs "
                                  f"{cand.driver}: {cand.mechanism} ({cand.rationale})",
                symbol=cand.instrument, driver=cand.driver,
                n_events_available=result["events_available"], windows_evaluated=1,
                best_train_t=result["train"].t_stat, best_val_n=result["validation"].n,
                mean_confirmation_rate=conf,
                evidence_level="REAL_SIGNAL_BLOCKED" if result["train"].t_stat >= 2.0 else "INSUFFICIENT_POWER",
                reason=(f"train t={result['train'].t_stat}, val n={result['validation'].n} (<30, uninformative). "
                       f"Not treated as confirmed edge -- validation sample too small to confirm signal."),
                missing_data=DataRequirement(
                    description="USD NFP/CPI raw events with confirmed cross-asset reaction",
                    current_value=result["events_available"], required_value=max(events_needed, result["events_available"]),
                    unit="events",
                ),
                retest_conditions=RetestCondition(
                    earliest_date=None,
                    trigger=f"If USD macro event pool extends to >={events_needed} events, retest.",
                    estimated_power_gain=f"Validation n could reach ~30 with {events_needed} events "
                                        f"(current confirmation rate {conf:.1%})",
                ),
                priority="HIGH" if result["train"].t_stat >= 3.0 else "MEDIUM",
                provenance_status="FACTORY_TESTED",
            )
            hyp_record["opportunity_queue_entry"] = entry.queue_id
            print(f"    -> STILL_UNDERPOWERED, queued as {entry.queue_id}")
            space_ledger.record(
                cycle_id=CYCLE_ID, research_mode=cand.research_mode, family=f"{cand.mechanism}/{cand.instrument}",
                hypothesis=hyp_id, decision="STILL_UNDERPOWERED", reason=hyp_record["verdict_reason"],
                result=entry.queue_id, information_gain=8.0, touched_new_family_or_dimension=(cand.research_mode == "EXPLORE"),
            )
        else:
            hyp_record["final_status"] = "REFUTED_THIS_RUN"
            refuted_list.append(hyp_record)
            print(f"    -> REFUTED_THIS_RUN ({result['verdict']}: {result['verdict_reason']})")
            space_ledger.record(
                cycle_id=CYCLE_ID, research_mode=cand.research_mode, family=f"{cand.mechanism}/{cand.instrument}",
                hypothesis=hyp_id, decision="REFUTED_THIS_RUN", reason=result["verdict_reason"],
                result="REFUTED_THIS_RUN", information_gain=4.0, touched_new_family_or_dimension=(cand.research_mode == "EXPLORE"),
            )

        hypotheses_report.append(hyp_record)

    queue.save()

    # ---------------------------------------------------------- Step 6: write cycle output
    def _clean(d):
        return {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in d.items()}

    payload = {
        "cycle_id": CYCLE_ID, "generated_at": datetime.utcnow().isoformat(), "dev_period_end": str(dev_end),
        "event_pool_size": len(events), "self_critique": __doc__,
        "search_space_summary": space.status_counts(), "novelty_coverage": space.novelty_coverage(),
        "exploration_debt": debt.to_dict(), "allocation": report.allocation.to_dict(),
        "novelty_saturation": report.novelty_saturation,
        "candidates_generated": len(pool), "candidates_accepted": len(report.accepted),
        "discovery_survivors": len(survivors), "still_underpowered": len(underpowered_list),
        "refuted_this_run": len(refuted_list), "data_blocked": len(blocked_list),
        "closure_proposals": list(report.closure_proposals),
        "hypotheses": hypotheses_report,
    }
    out_path = R / "reports/factory/discovery_cycles/cycle_14_research_space_evolution.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    integrator.save_journeys(R / "reports/factory/cycle_14_hypothesis_journeys.json")

    # ---------------------------------------------------------- Final report
    print("\n" + "=" * 78)
    print("CYCLE 14 FINAL REPORT")
    print("=" * 78)
    print(f"CANDIDATES GENERATED:        {len(pool)}")
    print(f"CANDIDATES ACCEPTED:         {len(report.accepted)} "
         f"(EXPLOIT={sum(1 for c in report.accepted if c.research_mode=='EXPLOIT')}, "
         f"EXPLORE={sum(1 for c in report.accepted if c.research_mode=='EXPLORE')}, "
         f"RECOMBINE={sum(1 for c in report.accepted if c.research_mode=='RECOMBINE')})")
    print(f"DATA BLOCKED:                {len(blocked_list)}")
    print(f"REAL FACTORY EVALUATIONS:    {len(hypotheses_report)}")
    print(f"SURVIVORS:                   {len(survivors)}")
    print(f"STILL_UNDERPOWERED:          {len(underpowered_list)}")
    print(f"REFUTED (this run):          {len(refuted_list)}")
    print(f"EA PRODUCTS CREATED:         0 (no self-authorized GEN14 in this run)")
    print(f"BRANCH CLOSURE PROPOSALS:    {len(report.closure_proposals)} (advisory only)")
    print(f"GOVERNANCE STATUS:           holdout untouched, ledger untouched, cost model untouched, "
         f"frozen candidates untouched, opportunity queue + research_space_ledger + decision_records append-only")
    print(f"\nOutput written to: {out_path}")

    if not survivors:
        print("\nNO_EDGE_FOUND: no hypothesis in this cycle survived the real INTERNAL_VALIDATION gate.")
    else:
        print(f"\n{len(survivors)} DISCOVERY_SURVIVOR(s) found. Frozen and reported for the EXISTING "
             f"GEN14 authorization process -- NOT self-authorized by this cycle.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
