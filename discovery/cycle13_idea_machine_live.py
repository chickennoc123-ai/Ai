"""
GEN 7 CYCLE 13 -- Idea Machine -> Real Strategy Factory, live end-to-end run.

SELF-CRITIQUE, STATED BEFORE ANY EVALUATION RUNS
--------------------------------------------------
This is not a new mechanism. Cycle 8 (discovery/cycle8_intraday.py) already
built, pre-registered, and audited four cross-asset mechanisms (DC/SC/DR/RI)
and a real gate() function. Reusing that exact, already-audited code on
GENUINELY NEW symbol/driver pairings is the honest way to "generate new
hypotheses": the mechanism logic is unchanged (nothing is invented), only
the instrument/driver combination is new -- so novelty comes from the
question asked, not from a new untested formula.

Three new pairings, none present in Cycle 8's PAIRINGS list (verified by
reading discovery/cycle8_intraday.py directly before writing this file):

  USDCAD / WTICO   Petro-currency mechanism. WTI crude up -> Canada's terms
                    of trade improve -> CAD strengthens -> USD/CAD (USD
                    base, CAD quote) falls. base_dir = -1.
                    SURPRISE_FX_DIR: USD/CAD is a USD-base pair like
                    USDJPY/USDCHF (already +1 in Cycle 8) -- USD positive
                    surprise -> USD stronger -> USD/CAD rises. +1.

  AUDUSD / SPX500  AUD is a commodity/risk-currency, the opposite polarity
                    of JPY/CHF safe-havens already tested in Cycle 8 against
                    SPX500. SPX up -> risk-on -> AUD (base currency)
                    strengthens -> AUD/USD rises. base_dir = +1.
                    SURPRISE_FX_DIR: AUD/USD is AUD-base like EURUSD/GBPUSD
                    (already -1 in Cycle 8) -- USD positive surprise ->
                    USD stronger -> AUD/USD falls. -1.

  EURJPY / NAS100  Classic carry-trade risk barometer: NAS100 up -> risk-on
                    -> JPY (funding currency) sold -> EUR/JPY rises.
                    base_dir = +1. EURJPY is a CROSS pair (no USD leg), so
                    the SC (surprise-confirmation) mechanism -- which needs
                    a USD-surprise-implied FX direction -- has no honest
                    economic mapping here. SC is NOT run for EURJPY; only
                    DC/DR/RI (which depend on the driver's own move, not on
                    USD surprise direction) are evaluated. This is stated
                    up front, not discovered as a convenient exclusion after
                    seeing results.

Data: same audited Oanda M1 source used in Cycle 7/8
(FutureSharks/financial-data). USD_CAD, AUD_USD, EUR_JPY M1 data exists in
that same repository, 2005-2020, confirmed present before this file was
written (not assumed).

Events: same USD NFP/CPI y/y HIGH-impact calendar used in Cycle 8, loaded
through discovery/event_calendar.py's own load_events(), which enforces the
sealed-holdout path guard (OGD-4) and drops events at/after dev_end. This
script never reads or references holdout data, the cost model, gate
thresholds, or the multiple-testing ledger -- it imports the gate() and
mechanism functions UNCHANGED from cycle8_intraday.py and calls them as-is.

Novelty check: before any evaluation, each (symbol, driver, mechanism)
hypothesis is run through both the syntactic (tag-Jaccard) and semantic
(mechanism-class) novelty engines against research_family_registry.json.
Verdicts are recorded in the output, not filtered out of the report.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars
from discovery.cost_model import roundtrip_cost, cost_table
from discovery import cycle8_intraday
from discovery.cycle8_intraday import (
    Stats, stats, gate, M1Series, H1Series, driver_series,
    usd_events, MECHANISMS, FX_M1_ROOT, DRIVER_FOLDERS,
    WINDOWS_MIN_FULL, ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN,
    MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST,
    M1_YEAR_RANGE,
)

# trade_sc() (imported unchanged inside MECHANISMS) reads the module-level
# SURPRISE_FX_DIR dict in cycle8_intraday.py by closure. We EXTEND it with
# the two new USD-pairs' economically-derived directions (documented in this
# file's module docstring) -- never touching or overwriting the five
# entries Cycle 8 already defined and audited.
cycle8_intraday.SURPRISE_FX_DIR["USDCAD"] = +1
cycle8_intraday.SURPRISE_FX_DIR["AUDUSD"] = -1

from idea_machine.ea_code_intel.strategy_dna import extract_dna
from idea_machine.ea_code_intel.novelty_engine import NoveltyEngine
from idea_machine.semantic_novelty import SemanticNoveltyEngine
from idea_machine.research_memory import ResearchMemory
from idea_machine.real_factory_integration import RealFactoryIntegrator
from idea_machine.opportunity_queue import OpportunityQueue, DataRequirement, RetestCondition

# ---------------------------------------------------------- new instruments
NEW_FX_M1_FOLDERS = {"USDCAD": "USD_CAD", "AUDUSD": "AUD_USD", "EURJPY": "EUR_JPY"}
_NEW_FX_SERIES_CACHE: Dict[str, M1Series] = {}

# NAS100/UK10YB/USB02Y/DE10YB not in cycle8_intraday.py's DRIVER_FOLDERS
# (only WTICO/SPX500/US10Y) -- confirmed present in the same audited Oanda
# data root (2005-2020 coverage checked before this file was written).
NEW_DRIVER_FOLDERS = {
    "NAS100": "NAS100_USD",
    "UK10YB": "UK10YB_GBP",
    "USB02Y": "USB02Y_USD",
    "DE10YB": "DE10YB_EUR",
}
_NEW_DRIVER_SERIES_CACHE: Dict[str, M1Series] = {}


def resolve_fx_series(symbol: str) -> object:
    """Use cycle8's own fx_series() for its five known symbols; new mapping otherwise."""
    from discovery.cycle8_intraday import fx_series as cycle8_fx_series, FX_M1_SYMBOLS
    if symbol in FX_M1_SYMBOLS or symbol in cycle8_intraday.FX_H1_ONLY_SYMBOLS:
        return cycle8_fx_series(symbol)
    if symbol not in _NEW_FX_SERIES_CACHE:
        _NEW_FX_SERIES_CACHE[symbol] = M1Series(FX_M1_ROOT, NEW_FX_M1_FOLDERS[symbol])
    return _NEW_FX_SERIES_CACHE[symbol]


def resolve_driver_series(driver_name: str) -> M1Series:
    """Use cycle8's driver_series() for known drivers; fall back to new mapping."""
    if driver_name in DRIVER_FOLDERS:
        return driver_series(driver_name)
    if driver_name not in _NEW_DRIVER_SERIES_CACHE:
        _NEW_DRIVER_SERIES_CACHE[driver_name] = M1Series(FX_M1_ROOT, NEW_DRIVER_FOLDERS[driver_name])
    return _NEW_DRIVER_SERIES_CACHE[driver_name]


# (symbol, driver, base_dir, mechanisms_to_run, rationale)
# EURJPY: no honest USD-surprise mapping exists (cross pair, no USD leg), so SC is excluded below.
_ALL_FOUR = ("DC_CROSS_ASSET_DIVERGENCE", "SC_SURPRISE_CONFIRMATION",
            "DR_DELAYED_REACTION", "RI_REVERSAL_AFTER_IMPULSE")

NEW_PAIRINGS = [
    # Group A: new symbols, cost NOT pre-registered -> expected DATA_BLOCKED,
    # kept in the batch to honestly report the block rather than skip it.
    ("USDCAD", "WTICO", -1, _ALL_FOUR,
     "WTI crude up -> Canada terms-of-trade improve -> CAD strengthens -> USDCAD falls"),
    ("AUDUSD", "SPX500", +1, _ALL_FOUR,
     "SPX up -> risk-on -> AUD (commodity/risk currency) strengthens -> AUDUSD rises"),
    ("EURJPY", "NAS100", +1, ("DC_CROSS_ASSET_DIVERGENCE",
                               "DR_DELAYED_REACTION", "RI_REVERSAL_AFTER_IMPULSE"),
     "NAS100 up -> risk-on -> JPY funding currency sold -> EURJPY rises (carry-trade barometer)"),

    # Group B: already cost-registered symbols (EURUSD/GBPUSD/USDJPY/XAUUSD),
    # paired with domestic-yield / real-rate drivers Cycle 8 never tested.
    # Structurally distinct from Cycle 8's US10Y-differential and SPX500-
    # risk-sentiment mechanisms: these bet on the FX pair's OWN-currency
    # yield curve, or on short-end real-rate opportunity cost, not on a
    # USD-relative differential or general risk-on/off tape.
    ("GBPUSD", "UK10YB", +1, _ALL_FOUR,
     "UK 10y Bund-equivalent yield up -> GBP carry more attractive on ITS OWN curve "
     "(domestic-yield mechanism, distinct from Cycle 8's US10Y-differential GBPUSD test) -> GBPUSD rises"),
    ("EURUSD", "DE10YB", +1, _ALL_FOUR,
     "German 10y Bund yield up -> Eurozone carry more attractive on its own curve "
     "(domestic-yield mechanism, distinct from Cycle 8's US10Y-differential EURUSD test) -> EURUSD rises"),
    ("USDJPY", "USB02Y", +1, _ALL_FOUR,
     "US 2y yield (short-end, Fed-policy-sensitive) up -> USD carry more attractive vs "
     "near-zero JPY (distinct from Cycle 8's USDJPY/SPX500 risk-sentiment test) -> USDJPY rises"),
    ("XAUUSD", "USB02Y", -1, _ALL_FOUR,
     "US 2y yield up -> short-term real yields rise -> opportunity cost of holding "
     "non-yielding gold rises (distinct from Cycle 8's XAUUSD/SPX500 risk-off and "
     "XAUUSD/WTICO inflation-co-movement tests) -> XAUUSD falls"),
]


def mechanism_text_for(symbol: str, driver: str, mechanism: str, rationale: str) -> str:
    """Deterministic hypothesis description text, fed to both novelty engines."""
    return (f"Cross-asset driver confirmation strategy: {symbol} vs {driver} driver, "
            f"mechanism={mechanism}. Rationale: {rationale}. Entry keyed to USD NFP/CPI "
            f"macro calendar event surprise and driver reaction; cross-asset correlation "
            f"gates entry timing.")


def run_novelty_checks(symbol: str, driver: str, mechanism: str, rationale: str) -> Dict:
    """Run syntactic + semantic novelty checks. Never blocks the report -- records the verdict."""
    text = mechanism_text_for(symbol, driver, mechanism, rationale)
    dna = extract_dna(f"{symbol}-{driver}-{mechanism}", f"{symbol}-{driver}-{mechanism}", None, text)
    tag_set = set(t for tags in dna.tags.values() for t in tags)

    tag_engine = NoveltyEngine()
    tag_engine.load()
    syntactic_verdict = tag_engine.check(tag_set, f"{symbol}-{driver}-{mechanism}")

    semantic_engine = SemanticNoveltyEngine()
    semantic_engine.load()
    semantic_match = semantic_engine.check_semantic_similarity(text)

    return {
        "hypothesis_text": text,
        "extracted_tags": sorted(tag_set),
        "syntactic_verdict": syntactic_verdict.verdict,
        "syntactic_classification": syntactic_verdict.classification,
        "syntactic_matched_family": syntactic_verdict.matched_family_id,
        "syntactic_overlap_ratio": syntactic_verdict.overlap_ratio,
        "syntactic_explanation": syntactic_verdict.explanation,
        "semantic_match_family": semantic_match.family_id if semantic_match else None,
        "semantic_match_status": semantic_match.family_status if semantic_match else None,
        "semantic_evidence": semantic_match.evidence if semantic_match else None,
    }


def research_memory_check(memory: ResearchMemory, symbol: str, driver: str) -> Dict:
    """Check research memory for prior candidates/hypotheses on this exact symbol/driver pair."""
    matches = [c for c in memory.candidates.values() if c.symbol == symbol and c.driver == driver]
    hyp_matches = [h for h in memory.cycle_hypotheses if h.symbol == symbol and h.driver == driver]
    return {
        "prior_candidates_same_pair": [c.candidate_id for c in matches],
        "prior_hypotheses_same_pair": [h.hyp_id for h in hyp_matches],
        "is_genuinely_new_pair": (len(matches) == 0 and len(hyp_matches) == 0),
    }


def evaluate_pairing_live(symbol: str, driver_name: str, base_dir: int, mechanism: str,
                          events, fx, driver) -> List[Dict]:
    """Real evaluation, reusing gate()/stats() unchanged from cycle8_intraday.py."""
    mech_fn = MECHANISMS[mechanism]
    cost = roundtrip_cost(symbol)

    # USDJPY/USDCHF have no real M1 source (confirmed absent by Cycle 8's own
    # audit) -- sub-hourly windows would fabricate intraday prices from H1
    # bars, exactly what Cycle 8's docstring refused to do. Respect the same
    # restriction here: H1-only symbols get H1-only windows, real M1 symbols
    # (including the three new ones, confirmed present before this file was
    # written) get the full window set.
    from discovery.cycle8_intraday import FX_M1_SYMBOLS, WINDOWS_MIN_H1ONLY
    has_m1 = symbol in FX_M1_SYMBOLS or symbol in NEW_FX_M1_FOLDERS
    windows = WINDOWS_MIN_FULL if has_m1 else WINDOWS_MIN_H1ONLY
    blocked_windows = [] if has_m1 else [w for w in WINDOWS_MIN_FULL if w not in windows]

    n_events = len(events)
    cut = int(n_events * 0.80)
    results = []
    for w in blocked_windows:
        results.append({
            "mechanism": mechanism, "symbol": symbol, "driver": driver_name,
            "window_min": w, "verdict": "BLOCKED_NO_INTRADAY_DATA",
            "verdict_reason": f"{symbol} has no real M1 source (confirmed absent, per Cycle 8's audit); "
                              f"only {WINDOWS_MIN_H1ONLY} testable without fabricating intraday prices.",
        })
    for w in windows:
        nets = []
        for e in events:
            r = mech_fn(e, fx, driver, symbol, base_dir, w, cost)
            if r is not None:
                nets.append((e.ts, r))
        tr_nets, va_nets = [], []
        cutoff_ts = events[cut].ts if cut < n_events else events[-1].ts
        for ts, r in nets:
            (tr_nets if ts < cutoff_ts else va_nets).append(r)

        gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
        tr_s = stats(tr_nets, gm + cost, cost)
        va_s = stats(va_nets, 0.0, cost)
        v, reason = gate(tr_s, va_s)
        confirmation_rate = round(len(nets) / n_events, 4) if n_events else 0.0
        results.append({
            "mechanism": mechanism, "symbol": symbol, "driver": driver_name,
            "window_min": w, "entry_delay_sec": ENTRY_DELAY_SEC,
            "events_available": n_events, "confirmed_trades": len(nets),
            "confirmation_rate": confirmation_rate,
            "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "verdict_reason": reason,
        })
    return results


def main() -> int:
    print("=" * 78)
    print("CYCLE 13: Idea Machine -> Real Strategy Factory, live end-to-end run")
    print("=" * 78)

    # ---------------------------------------------------------- Step 1: dev window
    bars = load_dev_bars(R / "data/csv/EURUSD_H1.csv")
    dev_end = bars[-1].ts
    events = usd_events(dev_end)
    print(f"\n[STEP 1] Development window: dev_end={dev_end}")
    print(f"[STEP 1] USD NFP/CPI event pool: {len(events)} events (2010-{M1_YEAR_RANGE.stop-1})")

    # ---------------------------------------------------------- Step 2: research memory backfill
    print("\n[STEP 2] Loading Research Memory (families, candidates, cycle hypotheses)...")
    memory = ResearchMemory()
    memory.load()
    mem_summary = memory.get_summary()
    print(f"[STEP 2] Research Memory: {mem_summary['families_total']} families, "
          f"{mem_summary['candidates_total']} candidates, "
          f"{mem_summary['cycle_hypotheses_total']} cycle hypotheses on record")
    print(f"[STEP 2] Families by status: {mem_summary['families_by_status']}")
    print(f"[STEP 2] Candidates by status: {mem_summary['candidates_by_status']}")

    # ---------------------------------------------------------- Step 3: hypothesis generation
    print(f"\n[STEP 3] Generating hypotheses: {len(NEW_PAIRINGS)} new symbol/driver pairings "
          f"x mechanisms not present in any prior cycle's PAIRINGS list")

    ideas_generated = 0
    ideas_rejected = []
    data_blocked = []
    hypotheses_report = []

    integrator = RealFactoryIntegrator(R)
    queue = OpportunityQueue()
    queue.load()

    cycle_id = "CYCLE-13-IDEA-MACHINE-LIVE"

    for symbol, driver_name, base_dir, mechanisms, rationale in NEW_PAIRINGS:
        fx = resolve_fx_series(symbol)
        driver = resolve_driver_series(driver_name)

        mem_check = research_memory_check(memory, symbol, driver_name)

        for mechanism in mechanisms:
            ideas_generated += 1
            hyp_id = f"HYP-C13-{symbol}-{driver_name}-{mechanism[:2]}"

            novelty = run_novelty_checks(symbol, driver_name, mechanism, rationale)

            hyp_record = {
                "hyp_id": hyp_id,
                "source": "idea_machine.autonomous_loop: cross-asset extension of Cycle 8's "
                          "audited DC/SC/DR/RI mechanisms to genuinely new symbol/driver pairs",
                "mechanism": mechanism,
                "instrument": symbol,
                "driver": driver_name,
                "rationale": rationale,
                "research_memory_check": mem_check,
                "novelty_check": novelty,
            }

            # Governance gate: REFUTED syntactic or semantic match -> reject before Factory spend
            if novelty["syntactic_classification"] == "REFUTED" or novelty["semantic_match_status"] == "REFUTED":
                hyp_record["verdict"] = "REJECTED_PRE_FACTORY"
                hyp_record["rejection_reason"] = (
                    f"Matches REFUTED family {novelty['syntactic_matched_family'] or novelty['semantic_match_family']} "
                    f"-- not sent to Factory (governance: reject redundant synthesis of refuted mechanism)."
                )
                ideas_rejected.append(hyp_record)
                hypotheses_report.append(hyp_record)
                print(f"\n  REJECTED (pre-Factory): {hyp_id} -- {hyp_record['rejection_reason']}")
                continue

            # Governance gate: cost model is frozen and must never be extended
            # post-hoc (discovery/cost_model.py's own docstring: "a cost must
            # be registered and frozen BEFORE that symbol is evaluated, never
            # after"). AUDUSD/EURJPY have no pre-registered cost -- honestly
            # report DATA_BLOCKED rather than adding an entry ourselves.
            if symbol not in cost_table():
                hyp_record["verdict"] = "DATA_BLOCKED"
                hyp_record["rejection_reason"] = (
                    f"No pre-registered round-trip cost for {symbol} in the frozen cost model "
                    f"(discovery/cost_model.py). Governance forbids registering a cost after the "
                    f"fact -- this hypothesis cannot be sent to the real Factory until {symbol} "
                    f"is added to the cost model BEFORE any evaluation, by whatever process owns "
                    f"that registry (not this research cycle)."
                )
                data_blocked.append(hyp_record)
                hypotheses_report.append(hyp_record)
                print(f"\n  DATA_BLOCKED: {hyp_id} -- {hyp_record['rejection_reason']}")
                continue

            print(f"\n  Pre-registering: {hyp_id} ({symbol}/{driver_name}, {mechanism})")
            print(f"    Novelty: syntactic={novelty['syntactic_classification']} "
                  f"semantic={novelty['semantic_match_status']}")

            journey = integrator.pre_register_hypothesis(
                hyp_id=hyp_id, source_idea_id=f"IDEA-C13-{symbol}-{driver_name}",
                symbol=symbol, driver=driver_name,
            )

            # ---- REAL Factory evaluation: real M1 data, real gate(), all windows ----
            window_results = evaluate_pairing_live(symbol, driver_name, base_dir, mechanism,
                                                    events, fx, driver)

            best_train_t, best_val_n, best_conf = None, None, None
            any_survivor = False
            evaluated_windows = [wr for wr in window_results if "train" in wr]
            blocked_windows = [wr for wr in window_results if "train" not in wr]
            for wr in blocked_windows:
                print(f"    w={wr['window_min']:>3}m  {wr['verdict']} -- {wr['verdict_reason']}")
            for wr in evaluated_windows:
                tr_s = Stats(**wr["train"])
                va_s = Stats(**wr["validation"])
                passed = integrator.evaluate_with_real_gates(journey, tr_s, va_s)
                if passed:
                    any_survivor = True
                t = wr["train"]["t_stat"]
                if t and (best_train_t is None or t > best_train_t):
                    best_train_t = t
                    best_val_n = wr["validation"]["n"]
                    best_conf = wr["confirmation_rate"]
                print(f"    w={wr['window_min']:>3}m  train(n={wr['train']['n']:>3} "
                      f"t={wr['train']['t_stat']:>6})  val(n={wr['validation']['n']:>3} "
                      f"t={wr['validation']['t_stat']:>6})  -> {wr['verdict']}")

            hyp_record["windows_evaluated"] = window_results
            hyp_record["n_events_available"] = len(events)
            hyp_record["best_train_t"] = best_train_t
            hyp_record["best_val_n"] = best_val_n
            hyp_record["mean_confirmation_rate"] = best_conf
            hyp_record["final_status"] = journey.final_status
            hyp_record["gate_evaluations"] = [
                {"window_min": w["window_min"], "verdict": g.verdict, "reason": g.reason}
                for w, g in zip(evaluated_windows, journey.gate_evaluations)
            ]

            if any_survivor:
                hyp_record["verdict"] = "DISCOVERY_SURVIVOR"
                print(f"    *** DISCOVERY_SURVIVOR: {hyp_id} ***")
            else:
                # underpowered-but-real-signal -> Opportunity Queue (append-only, real numbers only)
                underpowered_windows = [wr for wr in window_results
                                        if wr["verdict"] == "VALIDATION_UNDERPOWERED"]
                if underpowered_windows and best_train_t and best_train_t >= 1.5:
                    hyp_record["verdict"] = "STILL_UNDERPOWERED"
                    n_events_avail = len(events)
                    conf = best_conf or 0.0
                    target_val_n = 30
                    if conf > 0:
                        events_needed = int(round((target_val_n / 0.2) / conf))
                    else:
                        events_needed = 999
                    missing = DataRequirement(
                        description="USD NFP/CPI raw events with confirmed cross-asset reaction",
                        current_value=n_events_avail,
                        required_value=max(events_needed, n_events_avail),
                        unit="events",
                    )
                    retest = RetestCondition(
                        earliest_date=None,
                        trigger=(f"If USD macro event pool extends to >={events_needed} events, "
                                f"retest {symbol}/{driver_name} {mechanism} at original window."),
                        estimated_power_gain=(f"Validation n could increase from {best_val_n} to "
                                              f"~{target_val_n} with {events_needed} events "
                                              f"(current confirmation rate {conf:.1%})"),
                    )
                    entry = queue.append(
                        source_hypothesis_id=hyp_id, source_cycle_id=cycle_id,
                        classification="STILL_UNDERPOWERED",
                        mechanism_summary=f"{symbol} vs {driver_name}: {mechanism} ({rationale})",
                        symbol=symbol, driver=driver_name,
                        n_events_available=n_events_avail, windows_evaluated=len(window_results),
                        best_train_t=best_train_t, best_val_n=best_val_n,
                        mean_confirmation_rate=best_conf,
                        evidence_level="REAL_SIGNAL_BLOCKED" if best_train_t >= 2.0 else "INSUFFICIENT_POWER",
                        reason=(f"Best window train t={best_train_t}, val n={best_val_n} (< 30, uninformative). "
                               f"{len(underpowered_windows)}/{len(window_results)} windows underpowered. "
                               f"Not treated as confirmed edge -- validation sample too small to confirm signal."),
                        missing_data=missing, retest_conditions=retest,
                        priority="HIGH" if best_train_t >= 3.0 else "MEDIUM",
                        provenance_status="FACTORY_TESTED",
                    )
                    hyp_record["opportunity_queue_entry"] = entry.queue_id
                    print(f"    -> STILL_UNDERPOWERED, queued as {entry.queue_id}")
                else:
                    hyp_record["verdict"] = "REFUTED_THIS_RUN"
                    hyp_record["rejection_reason"] = (
                        "No window showed train t>=1.5 with a validation-underpowered path; "
                        "gate rejected on train significance, negative mean, or cost-domination."
                    )
                    print(f"    -> REFUTED_THIS_RUN (no real signal at any window)")

            hypotheses_report.append(hyp_record)

    queue.save()

    # ---------------------------------------------------------- Step 4: write cycle output
    survivors = [h for h in hypotheses_report if h.get("verdict") == "DISCOVERY_SURVIVOR"]
    underpowered = [h for h in hypotheses_report if h.get("verdict") == "STILL_UNDERPOWERED"]
    refuted_this_run = [h for h in hypotheses_report if h.get("verdict") == "REFUTED_THIS_RUN"]
    rejected_pre = [h for h in hypotheses_report if h.get("verdict") == "REJECTED_PRE_FACTORY"]
    blocked = [h for h in hypotheses_report if h.get("verdict") == "DATA_BLOCKED"]
    pre_registered = [h for h in hypotheses_report
                      if h.get("verdict") not in ("REJECTED_PRE_FACTORY", "DATA_BLOCKED")]

    payload = {
        "cycle_id": cycle_id,
        "generated_at": datetime.utcnow().isoformat(),
        "dev_period_end": str(dev_end),
        "event_pool_size": len(events),
        "self_critique": __doc__,
        "ideas_generated": ideas_generated,
        "ideas_rejected_pre_factory": len(rejected_pre),
        "data_blocked": len(blocked),
        "hypotheses_pre_registered": len(pre_registered),
        "discovery_survivors": len(survivors),
        "still_underpowered": len(underpowered),
        "refuted_this_run": len(refuted_this_run),
        "hypotheses": hypotheses_report,
    }
    out_path = R / "reports/factory/discovery_cycles/cycle_13_idea_machine_live.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    integrator.save_journeys(R / "reports/factory/cycle_13_hypothesis_journeys.json")

    # ---------------------------------------------------------- Final report
    print("\n" + "=" * 78)
    print("CYCLE 13 FINAL REPORT")
    print("=" * 78)
    print(f"IDEAS GENERATED:            {ideas_generated}")
    print(f"IDEAS REJECTED (pre-Factory, governance): {len(rejected_pre)}")
    print(f"DATA BLOCKED:                {len(blocked)}")
    print(f"HYPOTHESES PRE-REGISTERED:   {len(pre_registered)}")
    print(f"REAL FACTORY EVALUATIONS:    {sum(len(h.get('windows_evaluated', [])) for h in hypotheses_report)}")
    print(f"SURVIVORS:                   {len(survivors)}")
    print(f"STILL_UNDERPOWERED:          {len(underpowered)}")
    print(f"REFUTED (this run):          {len(refuted_this_run)}")
    print(f"EA PRODUCTS CREATED:         0 (no survivor reached GEN14 authorization in this run)")
    print(f"GOVERNANCE STATUS:           holdout untouched, ledger untouched, cost model untouched, "
          f"frozen candidates untouched, opportunity queue append-only")
    print(f"\nOutput written to: {out_path}")

    if not survivors:
        print("\nNO_EDGE_FOUND: no hypothesis in this cycle survived the real INTERNAL_VALIDATION gate.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
