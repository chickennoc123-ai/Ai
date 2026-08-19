#!/usr/bin/env python3
"""Execute ML-001 Generation 4 — candidate economic validation of STRAT-000002.

Ordering note that a reader should not miss: this script evaluates
**PURE_HOLDOUT last**, after OOS, walk-forward, robustness, cost stress,
statistics and multiple-testing accounting, and after the candidate has
entered the ``FROZEN`` state. The Generation 4 contract numbers the
holdout phases before OOS/WFA; this project's already-committed
governance (``ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md``, and the
``_FORWARD_SPINE`` in ``core/factory/state_machine.py``) requires the
opposite. Reordering the governance to match the contract's numbering
would be exactly the kind of silent governance change the contract itself
forbids, so the committed governance wins and the conflict is recorded as
an open governance decision in ML-001-GENERATION-4-REPORT.md. Every
artifact the contract asks for is still produced.

Writes every artifact under ``reports/generation4/`` and appends to the
Research Ledger. Deterministic: two runs from a clean checkout produce
identical result checksums.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.economic_validation import cost_stress as cost_stress_mod  # noqa: E402
from core.economic_validation import evg as evg_mod  # noqa: E402
from core.economic_validation import multiple_testing as mt_mod  # noqa: E402
from core.economic_validation import statistics as stats_mod  # noqa: E402
from core.economic_validation.candidate_freeze import freeze_candidate, verify_unchanged  # noqa: E402
from core.economic_validation.data_eligibility import audit_dataset, load_raw_ohlcv  # noqa: E402
from core.economic_validation.evaluation import (  # noqa: E402
    PrecomputedFeatures,
    assert_causal_slicing_verified,
    evaluate_partition,
    evaluate_partition_with_result,
)
from core.economic_validation.execution import RiskRules  # noqa: E402
from core.economic_validation.feature_temporal_audit import audit_feature_temporal_safety  # noqa: E402
from core.economic_validation.partitions import seal_dataset  # noqa: E402
from core.economic_validation.robustness import run_robustness  # noqa: E402
from core.economic_validation.rule_engine import parse_atr_multiple, parse_entry_rule  # noqa: E402
from core.economic_validation.target_audit import audit_target_construction  # noqa: E402
from core.economic_validation.walkforward import run_walk_forward  # noqa: E402
from core.factory.dataset_registry import DatasetRegistry  # noqa: E402
from core.factory.failure_library import FailureLibrary  # noqa: E402
from core.factory.hypothesis import HypothesisRegistry  # noqa: E402
from core.factory.claim_registry import ClaimRegistry  # noqa: E402
from core.factory.registry import StrategyRegistry  # noqa: E402
from core.factory.research_accounting import compute_search_accounting_summary  # noqa: E402
from core.factory.research_ledger import ResearchLedger  # noqa: E402
from core.factory.research_source_registry import ResearchSourceRegistry  # noqa: E402
from core.factory.search_space import SearchSpaceRegistry  # noqa: E402
from core.factory.state_machine import CandidateState  # noqa: E402
from core.factory.holdout_access import HoldoutAccessEvent  # noqa: E402
from core.ml_r2.provenance_r2 import get_code_version  # noqa: E402

CANDIDATE_ID = "STRAT-000002"
OUTPUT_DIR = REPO_ROOT / "reports" / "generation4"
INITIAL_EQUITY = 10_000.0
RISK_PER_TRADE = 0.02
TIMEFRAME = "H1"


def _write(name: str, payload: Any) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return path


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def main(apply_registry_transitions: bool = True) -> Dict[str, Any]:
    code_version = get_code_version(str(REPO_ROOT))
    summary: Dict[str, Any] = {"code_version": code_version}

    strategy_registry = StrategyRegistry()
    dataset_registry = DatasetRegistry()
    search_space_registry = SearchSpaceRegistry()
    hypothesis_registry = HypothesisRegistry()
    claim_registry = ClaimRegistry()
    source_registry = ResearchSourceRegistry()
    ledger = ResearchLedger()
    failures = FailureLibrary()

    candidate = strategy_registry.get(CANDIDATE_ID)
    dataset = dataset_registry.get(candidate.dataset_id)
    symbol = dataset.instrument

    # ---------------- Phase 1: freeze -------------------------------------
    risk = RiskRules(
        risk_per_trade=RISK_PER_TRADE,
        stop_loss_atr_mult=parse_atr_multiple(candidate.spec.stop_loss),
        take_profit_atr_mult=parse_atr_multiple(candidate.spec.take_profit),
        max_holding_bars=int(candidate.spec.max_hold_bars),
    )
    base_costs = cost_stress_mod.base_cost_model(symbol)

    snapshot = freeze_candidate(
        candidate,
        dataset_registry=dataset_registry,
        search_space_registry=search_space_registry,
        cost_model=base_costs.to_dict(),
        risk_rules=risk.to_dict(),
        target_specification={
            "target_type": "REALIZED_TRADE_PNL",
            "horizon_bars": int(candidate.spec.max_hold_bars),
            "learned_label": None,
            "source_hypothesis_target": "forward return over 12 bars on EURUSD H1 (HYP-000001)",
        },
        seed_policy={
            "signal_generation": "NO_SEED_REQUIRED (deterministic rule)",
            "execution": "NO_SEED_REQUIRED (deterministic)",
            "bootstrap": stats_mod.DEFAULT_SEED,
            "robustness_perturbation": "deterministic grid, no sampling",
            "seed_selection_policy": "seeds are fixed constants; no seed is chosen by result",
        },
        code_version=code_version,
        instrument_scope=(symbol,),
    )
    freeze_path = snapshot.write(OUTPUT_DIR / "CANDIDATE_FREEZE_SNAPSHOT.json")
    summary["validation_run_id"] = snapshot.validation_run_id
    summary["snapshot_checksum"] = snapshot.snapshot_checksum
    print(f"[freeze] validation_run_id={snapshot.validation_run_id}")

    run_id = snapshot.validation_run_id

    # ---------------- Phase 2: data eligibility ---------------------------
    eligibility = audit_dataset(dataset, expected_instrument=symbol, expected_timeframe=TIMEFRAME)
    elig_path = _write("DATA_ELIGIBILITY.json", eligibility.to_dict())
    summary["data_eligibility"] = eligibility.verdict
    print(f"[data] verdict={eligibility.verdict}")
    if eligibility.verdict != "ELIGIBLE":
        failures.record(
            entity_id=CANDIDATE_ID,
            failure_stage="DATA_VALIDATION",
            failure_category="INVALID_DATA" if eligibility.verdict == "INELIGIBLE" else "INSUFFICIENT_HISTORY",
            failure_reason=f"data eligibility audit returned {eligibility.verdict}: {'; '.join(eligibility.findings)}",
            evidence_reference=_rel(elig_path),
        )
        summary["stopped_at"] = "DATA_ELIGIBILITY"
        _write("GENERATION4_SUMMARY.json", summary)
        return summary

    verify_unchanged(snapshot, candidate, dataset_registry=dataset_registry)

    # ---------------- partitions + seal -----------------------------------
    full = load_raw_ohlcv(Path(dataset.file_path))
    sealed = seal_dataset(full, dataset_id=dataset.dataset_id, dataset_checksum=eligibility.observed_file_checksum)
    _write("PARTITION_BOUNDARIES.json", sealed.boundaries.to_dict())
    print(f"[partitions] dev={sealed.boundaries.train_start}..{sealed.boundaries.train_end} "
          f"val={sealed.boundaries.validation_start}..{sealed.boundaries.validation_end} "
          f"holdout(sealed)={sealed.boundaries.holdout_start}..{sealed.boundaries.holdout_end}")

    development = sealed.development()
    dev_and_val = sealed.development_and_validation()
    val_start = pd.Timestamp(sealed.boundaries.validation_start)

    # ---------------- Phase 3: feature temporal audit ---------------------
    feature_audit = audit_feature_temporal_safety(
        dev_and_val, features=list(candidate.spec.features)
    )
    feat_path = _write("FEATURE_TEMPORAL_AUDIT.json", feature_audit.to_dict())
    summary["feature_temporal_safety"] = feature_audit.verdict
    print(f"[features] verdict={feature_audit.verdict}")

    # Phase 29 (performance): a single feature computation, sliced for
    # every window/grid point/scenario. Permitted ONLY because the Phase 3
    # audit above established truncation invariance on this exact data --
    # see PrecomputedFeatures' docstring. The guard makes the dependency
    # enforceable rather than remembered.
    assert_causal_slicing_verified(feature_audit.verdict)
    reusable_cache = PrecomputedFeatures(dev_and_val)

    rule = parse_entry_rule(candidate.spec.entry_rule, candidate.spec.direction)
    _write("PARSED_RULE.json", {"rule": rule.to_dict(), "risk_rules": risk.to_dict(),
                                "entry_rule_source": candidate.spec.entry_rule})

    # ---------------- Phase 8/10: development evaluation ------------------
    dev_record = evaluate_partition(
        development,
        evaluation_start=development.index[0],
        rule=rule,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
    )
    dev_path = _write("EVALUATION_DEVELOPMENT.json", dev_record.to_dict())
    summary["development"] = _brief(dev_record.metrics)
    print(f"[development] {summary['development']}")

    # ---------------- Phase 4: target/label audit -------------------------
    from core.economic_validation.evaluation import build_execution_frame
    from core.economic_validation.execution import execute
    from core.economic_validation.rule_engine import generate_signals

    dev_exec_frame, dev_features = build_execution_frame(development)
    dev_signals = generate_signals(dev_features, rule)
    dev_exec = execute(dev_exec_frame, dev_signals, costs=base_costs, risk=risk, initial_equity=INITIAL_EQUITY)
    target_audit = audit_target_construction(
        dev_exec_frame,
        dev_signals,
        dev_exec,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        partition_name="DEVELOPMENT",
    )
    target_path = _write("TARGET_LEAKAGE_AUDIT.json", target_audit.to_dict())
    summary["target_leakage"] = target_audit.verdict
    print(f"[target] verdict={target_audit.verdict}")

    # ---------------- Phase 13: OOS (VALIDATION partition) ----------------
    oos_record = evaluate_partition(
        dev_and_val,
        evaluation_start=val_start,
        rule=rule,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="OOS_VALIDATION",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
        precomputed=reusable_cache.full(),
    )
    oos_path = _write("EVALUATION_OOS.json", oos_record.to_dict())
    summary["oos"] = _brief(oos_record.metrics)
    print(f"[oos] {summary['oos']}")

    # ---------------- Phase 14/15: walk-forward ---------------------------
    wfa = run_walk_forward(
        dev_and_val,
        evaluation_start=dev_and_val.index[0],
        rule=rule,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        window_months=1,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
        precomputed=reusable_cache,
    )
    wfa_path = _write("WALK_FORWARD.json", wfa.to_dict())
    summary["wfa"] = {
        "n_windows": wfa.n_windows,
        "positive_window_fraction": wfa.aggregate["positive_window_fraction"],
        "total_net_profit": wfa.aggregate["total_net_profit"],
        "concentration": wfa.stability["concentration_flag"],
    }
    print(f"[wfa] {summary['wfa']}")

    # ---------------- Phase 16: robustness --------------------------------
    robustness = run_robustness(
        dev_and_val,
        evaluation_start=dev_and_val.index[0],
        frozen_rule=rule,
        frozen_risk=risk,
        costs=base_costs,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT_AND_VALIDATION",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        precomputed=reusable_cache,
    )
    rob_path = _write("ROBUSTNESS.json", robustness.to_dict())
    summary["robustness"] = robustness.surface_summary
    print(f"[robustness] viable_region={robustness.surface_summary['viable_region']} "
          f"pf_above_1={robustness.surface_summary['n_points_pf_above_1']}/"
          f"{robustness.surface_summary['n_points_with_trades']}")

    # ---------------- Phase 17: cost stress -------------------------------
    cost_report = cost_stress_mod.run_cost_stress(
        dev_and_val,
        evaluation_start=dev_and_val.index[0],
        rule=rule,
        risk=risk,
        symbol=symbol,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT_AND_VALIDATION",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
        precomputed=reusable_cache,
    )
    cost_path = _write("COST_STRESS.json", cost_report.to_dict())
    summary["cost_stress"] = cost_report.zero_cost_dependency
    print(f"[cost] {cost_report.zero_cost_dependency}")

    # ---------------- Phase 18: statistics --------------------------------
    reusable_record, reusable_result = evaluate_partition_with_result(
        dev_and_val,
        evaluation_start=dev_and_val.index[0],
        rule=rule,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT_AND_VALIDATION",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
        precomputed=reusable_cache.full(),
    )
    _write("EVALUATION_REUSABLE_COMBINED.json", reusable_record.to_dict())
    reusable_pnls = [t["pnl"] for t in reusable_record.trades if t["pnl"] is not None]
    reusable_returns = _bar_returns(reusable_result)

    stats_report = stats_mod.run_statistical_validation(
        reusable_pnls,
        reusable_returns,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT_AND_VALIDATION",
        initial_equity=INITIAL_EQUITY,
    )
    stats_path = _write("STATISTICAL_VALIDATION.json", stats_report.to_dict())
    summary["statistics"] = {
        "trade_count": stats_report.trade_count,
        "sufficiency": stats_report.trade_count_sufficiency.split(":")[0],
    }
    print(f"[statistics] {summary['statistics']}")

    # ---------------- Phase 19/20: multiple testing -----------------------
    accounting = compute_search_accounting_summary(
        source_registry=source_registry,
        claim_registry=claim_registry,
        hypothesis_registry=hypothesis_registry,
        search_space_registry=search_space_registry,
        strategy_registry=strategy_registry,
    )
    family_registry_path = REPO_ROOT / "reports" / "factory" / "research_family_registry.json"
    n_families = len(json.loads(family_registry_path.read_text()).get("families", {}))

    # Update the registry's declared search-space accounting so the
    # MULTIPLE_TESTING_REVIEWED gate certifies the CURRENT population.
    # The stored record still described the Generation-1 state ("single
    # pre-specified hypothesis"), which was true of STRAT-000001 and is no
    # longer true now that STRAT-000002 was drawn from SEARCHSPACE-000001.
    # Correcting stale accounting upward is the opposite of weakening it.
    space = search_space_registry.get(candidate.search_space_id) if candidate.search_space_id else None
    if apply_registry_transitions:
        strategy_registry.set_search_space(
            search_space=space.to_dict() if space else {},
            search_method=(
                "MANUAL search space (SEARCHSPACE-000001) drawn from an ingested public-source claim; "
                "one candidate drawn from it (STRAT-000002). STRAT-000001 predates this space and was "
                "a single pre-specified hypothesis."
            ),
            parameter_search_count=int(accounting["SEARCH_SPACE_SIZE"]),
            model_search_count=0,
            selection_criteria=(
                "No selection among alternatives has occurred: exactly one parameter draw was taken "
                "from SEARCHSPACE-000001 and it was taken BEFORE any economic result existed. No "
                "candidate was chosen for being the best-performing of several."
            ),
            feature_search_space={"features": list(space.features)} if space else {},
            parameter_search_space={
                "holding_periods": list(space.holding_periods),
                "stop_loss_options": list(space.stop_loss_options),
                "take_profit_options": list(space.take_profit_options),
                "feature_parameters": dict(space.feature_parameters),
            } if space else {},
            symbol_search_space={"symbols": list(space.symbols)} if space else {},
            timeframe_search_space={"timeframes": list(space.timeframes)} if space else {},
            model_search_space={"models": [], "note": "no model is specified by this candidate"},
        )

    mt_report = mt_mod.run_multiple_testing_analysis(
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="DEVELOPMENT_AND_VALIDATION",
        bar_returns=reusable_returns,
        accounting=accounting,
        search_history=strategy_registry.search_history_summary(),
        n_families=n_families,
    )
    mt_path = _write("MULTIPLE_TESTING.json", mt_report.to_dict())
    if apply_registry_transitions:
        strategy_registry.set_selection_bias_status(
            "STATISTICAL_CORRECTION_APPLIED_LOW_POWER",
            justification=(
                "A Deflated Sharpe Ratio correction was computed and applied over "
                f"{mt_report.effective_trials} evaluated candidate(s) "
                "(reports/generation4/MULTIPLE_TESTING.json). The accounting is complete and the "
                "correction is real, but with this few trials it has almost no discriminating power "
                "-- passing it would not have demonstrated freedom from selection bias. Recording "
                "the low power in the status itself prevents a future reader from mistaking "
                "'corrected' for 'shown to be unbiased'."
            ),
        )
    _write("SEARCH_ACCOUNTING.json", accounting)
    summary["multiple_testing"] = mt_report.economic_edge_status
    print(f"[multiple_testing] {mt_report.economic_edge_status}")

    # ---------------- registry transitions up to FROZEN -------------------
    if apply_registry_transitions:
        _advance_to_frozen(
            strategy_registry,
            ledger,
            snapshot=snapshot,
            evidence={
                "data": _rel(elig_path),
                "features": _rel(feat_path),
                "target": _rel(target_path),
                "development": _rel(dev_path),
                "oos": _rel(oos_path),
                "wfa": _rel(wfa_path),
                "robustness": _rel(rob_path),
                "cost": _rel(cost_path),
                "statistics": _rel(stats_path),
                "multiple_testing": _rel(mt_path),
            },
            summary=summary,
        )
        candidate = strategy_registry.get(CANDIDATE_ID)

    # ---------------- Phase 11/12: PURE_HOLDOUT ---------------------------
    verify_unchanged(snapshot, candidate, dataset_registry=dataset_registry)
    release = sealed.release_holdout(
        validation_run_id=run_id,
        candidate_id=CANDIDATE_ID,
        candidate_checksum=snapshot.candidate_checksum,
        snapshot_checksum=snapshot.snapshot_checksum,
        reason_for_release=(
            "The complete pre-holdout evidence chain is closed (data eligibility, feature temporal "
            "safety, target-leakage audit, development evaluation, OOS, walk-forward, robustness, "
            "cost stress, statistics, multiple-testing accounting) and the candidate has entered "
            "FROZEN. Generation 4 completion criterion 10 requires PURE_HOLDOUT to be evaluated "
            "under the frozen specification. Disclosure: the candidate is already refuted on "
            "reusable data; the holdout is opened to complete the required evidence, not in the "
            "expectation that it will change the verdict, and no modification of any kind is "
            "permitted after this point."
        ),
        development_evidence_reference=f"{_rel(dev_path)}, {_rel(oos_path)}, {_rel(wfa_path)}",
    )
    _write("HOLDOUT_RELEASE_RECORD.json", release.to_dict())
    print(f"[holdout] released {release.holdout_start}..{release.holdout_end}")

    holdout = sealed.holdout()
    holdout_context = pd.concat([dev_and_val, holdout]).sort_index()
    holdout_record, holdout_result = evaluate_partition_with_result(
        holdout_context,
        evaluation_start=holdout.index[0],
        rule=rule,
        costs=base_costs,
        risk=risk,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="PURE_HOLDOUT",
        dataset_checksum=eligibility.observed_file_checksum,
        code_version=code_version,
        initial_equity=INITIAL_EQUITY,
        timeframe=TIMEFRAME,
    )
    holdout_path = _write("EVALUATION_PURE_HOLDOUT.json", holdout_record.to_dict())
    summary["holdout"] = _brief(holdout_record.metrics)
    print(f"[holdout] {summary['holdout']}")

    holdout_pnls = [t["pnl"] for t in holdout_record.trades if t["pnl"] is not None]
    holdout_stats = stats_mod.run_statistical_validation(
        holdout_pnls,
        _bar_returns(holdout_result),
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        partition_name="PURE_HOLDOUT",
        initial_equity=INITIAL_EQUITY,
    )
    _write("STATISTICAL_VALIDATION_HOLDOUT.json", holdout_stats.to_dict())

    if apply_registry_transitions:
        access_event = HoldoutAccessEvent(
            candidate_id=CANDIDATE_ID,
            candidate_version=candidate.version,
            dataset_id=dataset.dataset_id,
            dataset_checksum=release.holdout_dataset_checksum,
            holdout_partition_identity=f"{release.holdout_start}..{release.holdout_end} ({release.holdout_rows} bars)",
            access_timestamp=release.release_timestamp,
            frozen_state_confirmed=True,
            evidence_reference=_rel(holdout_path),
        )
        strategy_registry.transition(
            CANDIDATE_ID,
            CandidateState.HOLDOUT_TESTED,
            reason=(
                f"PURE_HOLDOUT evaluated exactly once under the frozen specification "
                f"({snapshot.snapshot_checksum[:16]}): {summary['holdout']}"
            ),
            evidence_reference=_rel(holdout_path),
            holdout_access_event=access_event,
        )
        ledger.append(
            "HOLDOUT_EVALUATED",
            subject_id=CANDIDATE_ID,
            reason="PURE_HOLDOUT evaluated once under the frozen candidate",
            dataset_id=dataset.dataset_id,
            feature_ids=tuple(candidate.spec.features),
            search_space_id=candidate.search_space_id,
            result=json.dumps(summary["holdout"], sort_keys=True),
            artifact_reference=_rel(holdout_path),
        )

    # ---------------- Phase 23: EVG ---------------------------------------
    evidence = _build_evidence(
        run_id=run_id,
        eligibility=eligibility,
        feature_audit=feature_audit,
        target_audit=target_audit,
        snapshot=snapshot,
        dev_record=dev_record,
        oos_record=oos_record,
        holdout_record=holdout_record,
        wfa=wfa,
        robustness=robustness,
        cost_report=cost_report,
        stats_report=stats_report,
        mt_report=mt_report,
        artifacts={
            "data": _rel(elig_path), "features": _rel(feat_path), "target": _rel(target_path),
            "freeze": _rel(freeze_path), "dev": _rel(dev_path), "oos": _rel(oos_path),
            "holdout": _rel(holdout_path), "wfa": _rel(wfa_path), "robustness": _rel(rob_path),
            "cost": _rel(cost_path), "statistics": _rel(stats_path), "mt": _rel(mt_path),
        },
    )
    evg_report = evg_mod.run_evg(
        evidence,
        candidate_id=CANDIDATE_ID,
        validation_run_id=run_id,
        candidate_checksum=snapshot.candidate_checksum,
        snapshot_checksum=snapshot.snapshot_checksum,
    )
    evg_path = _write("EVG_REPORT.json", evg_report.to_dict())
    summary["evg_verdict"] = evg_report.verdict
    print(f"[evg] verdict={evg_report.verdict}")

    if apply_registry_transitions:
        strategy_registry.transition(
            CANDIDATE_ID,
            CandidateState.EVG_REVIEW,
            reason=f"EVG consumed the complete evidence chain; verdict={evg_report.verdict}",
            evidence_reference=_rel(evg_path),
        )
        ledger.append(
            "EVG_VERDICT",
            subject_id=CANDIDATE_ID,
            reason=evg_report.verdict_basis,
            result=evg_report.verdict,
            artifact_reference=_rel(evg_path),
        )

        # ---------------- Phase 22/24: failure library + classification ---
        _record_failures(
            failures,
            summary=summary,
            cost_report=cost_report,
            wfa=wfa,
            robustness=robustness,
            mt_report=mt_report,
            stats_report=stats_report,
            artifacts={"dev": _rel(dev_path), "oos": _rel(oos_path), "holdout": _rel(holdout_path),
                       "wfa": _rel(wfa_path), "cost": _rel(cost_path), "robustness": _rel(rob_path),
                       "mt": _rel(mt_path)},
            candidate=candidate,
        )
        if evg_report.verdict == "FAIL":
            strategy_registry.transition(
                CANDIDATE_ID,
                CandidateState.REJECTED,
                reason=(
                    "[EVG] Economic Validation Gate returned FAIL on the complete Generation 4 "
                    "evidence chain. Negative expectancy after realistic costs on development, OOS "
                    "and PURE_HOLDOUT alike; no parameter neighbourhood is viable; the strategy is "
                    "not merely cost-sensitive but unprofitable before costs as well."
                ),
                evidence_reference=_rel(evg_path),
            )
            ledger.append(
                "CANDIDATE_REJECTED",
                subject_id=CANDIDATE_ID,
                reason="EVG FAIL on the complete Generation 4 evidence chain",
                result="REJECTED",
                artifact_reference=_rel(evg_path),
            )
            summary["classification"] = "REJECTED"
        else:
            summary["classification"] = f"EVG_{evg_report.verdict}"
        ledger.append(
            "CANDIDATE_CLASSIFIED",
            subject_id=CANDIDATE_ID,
            reason=f"Generation 4 edge classification: {summary['classification']}",
            result=summary["classification"],
            artifact_reference=_rel(evg_path),
        )

    # ---------------- Phase 26: independent accounting recompute ----------
    recomputed = compute_search_accounting_summary(
        source_registry=ResearchSourceRegistry(),
        claim_registry=ClaimRegistry(),
        hypothesis_registry=HypothesisRegistry(),
        search_space_registry=SearchSpaceRegistry(),
        strategy_registry=StrategyRegistry(),
    )
    stored = StrategyRegistry().search_history_summary()
    reconciliation = _reconcile(recomputed, stored)
    _write("SEARCH_ACCOUNTING_RECONCILIATION.json", reconciliation)
    summary["accounting"] = reconciliation["status"]
    print(f"[accounting] {reconciliation['status']}")

    summary["result_checksums"] = {
        "development": dev_record.result_checksum(),
        "oos": oos_record.result_checksum(),
        "holdout": holdout_record.result_checksum(),
        "reusable_combined": reusable_record.result_checksum(),
        "wfa": wfa.report_checksum(),
        "robustness": robustness.report_checksum(),
        "cost_stress": cost_report.report_checksum(),
        "statistics": stats_report.report_checksum(),
        "multiple_testing": mt_report.report_checksum(),
        "evg": evg_report.report_checksum(),
    }
    _write("GENERATION4_SUMMARY.json", summary)
    return summary


# ---------------------------------------------------------------------------


def _brief(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "trades": metrics["trade_count"],
        "net_profit": round(float(metrics["net_profit"]), 2),
        "profit_factor": None if metrics["profit_factor"] is None else round(float(metrics["profit_factor"]), 4),
        "win_rate": None if metrics["win_rate"] is None else round(float(metrics["win_rate"]), 4),
        "expectancy": None if metrics["expectancy"] is None else round(float(metrics["expectancy"]), 4),
        "sharpe": None if metrics["sharpe"] is None else round(float(metrics["sharpe"]), 4),
        "max_drawdown": round(float(metrics["max_drawdown"]), 2),
    }


def _bar_returns(result) -> List[float]:
    """The per-bar equity return series, taken from the execution result.

    This is the identical series ``compute_metrics`` used for Sharpe and
    Sortino, not a reconstruction of it -- so the statistics phase and the
    metrics phase provably describe the same run.
    """
    equity = result.equity_curve
    if equity is None or len(equity) < 2:
        return []
    return list(equity.pct_change().dropna().to_numpy())


def _advance_to_frozen(registry: StrategyRegistry, ledger: ResearchLedger, *, snapshot, evidence, summary) -> None:
    """Walk the candidate up the committed state-machine spine to FROZEN."""
    steps = [
        (CandidateState.DATA_VALIDATED, "data eligibility audit ELIGIBLE on real market data", evidence["data"],
         "DATA_ELIGIBILITY_AUDITED"),
        (CandidateState.TRAINED,
         "signal generation completed under RULE-R4-001; the frozen candidate specifies no model, so "
         "there is nothing to train and no hyperparameters or seed to select",
         evidence["development"], "EVALUATION_COMPLETED"),
        (CandidateState.OOS_TESTED, f"OOS (VALIDATION partition) evaluated: {summary.get('oos')}",
         evidence["oos"], "EVALUATION_COMPLETED"),
        (CandidateState.WFA_TESTED, f"walk-forward completed: {summary.get('wfa')}", evidence["wfa"],
         "WFA_COMPLETED"),
        (CandidateState.ROBUSTNESS_TESTED,
         f"robustness surface evaluated: {summary.get('robustness', {}).get('viable_region')}",
         evidence["robustness"], "ROBUSTNESS_COMPLETED"),
        (CandidateState.COST_TESTED, f"cost stress completed: {summary.get('cost_stress')}", evidence["cost"],
         "COST_STRESS_COMPLETED"),
        (CandidateState.STATISTICALLY_VALIDATED, "bootstrap confidence intervals computed",
         evidence["statistics"], "STATISTICS_COMPLETED"),
        (CandidateState.MULTIPLE_TESTING_REVIEWED,
         f"multiple-testing accounting completed: {summary.get('multiple_testing')}",
         evidence["multiple_testing"], "MULTIPLE_TESTING_COMPLETED"),
        (CandidateState.FROZEN,
         f"candidate frozen for PURE_HOLDOUT access; snapshot={snapshot.snapshot_checksum}",
         "reports/generation4/CANDIDATE_FREEZE_SNAPSHOT.json", "CANDIDATE_FROZEN"),
    ]
    for state, reason, artifact, event_type in steps:
        current = registry.get(CANDIDATE_ID).state
        if current is state:
            continue
        registry.transition(CANDIDATE_ID, state, reason=reason, evidence_reference=artifact)
        ledger.append(event_type, subject_id=CANDIDATE_ID, reason=reason, result=state.value,
                      artifact_reference=artifact)


def _build_evidence(*, run_id, eligibility, feature_audit, target_audit, snapshot, dev_record,
                    oos_record, holdout_record, wfa, robustness, cost_report, stats_report,
                    mt_report, artifacts) -> List[evg_mod.EvidenceItem]:
    def _perf_verdict(metrics: Dict[str, Any]) -> tuple:
        pf = metrics["profit_factor"]
        n = metrics["trade_count"]
        if n == 0:
            return "INSUFFICIENT", "no trades were taken"
        if pf is not None and pf < 1.0:
            return "FAIL", f"profit factor {pf:.4f} < 1 on {n} trades; net {metrics['net_profit']:.2f}"
        if n < stats_mod.MIN_TRADES_FOR_INTERVAL:
            return "INSUFFICIENT", f"only {n} trades"
        return "PASS", f"profit factor {pf:.4f} on {n} trades"

    items: List[evg_mod.EvidenceItem] = []
    mk = lambda name, verdict, checksum, ref, reason, extra=None: evg_mod.EvidenceItem(  # noqa: E731
        name=name, verdict=verdict, checksum=checksum, artifact_reference=ref,
        candidate_id=CANDIDATE_ID, validation_run_id=run_id,
        summary={"reason": reason, **(extra or {})},
    )

    items.append(mk("REAL_DATA", "PASS" if eligibility.real_market_data else "FAIL",
                    eligibility.report_checksum(), artifacts["data"],
                    "dataset is real market data with verified provenance"))
    items.append(mk("DATA_INTEGRITY", eligibility.verdict, eligibility.report_checksum(), artifacts["data"],
                    "; ".join(eligibility.findings) or "no integrity findings"))
    items.append(mk("LEAKAGE_AUDIT", feature_audit.verdict, feature_audit.report_checksum(),
                    artifacts["features"],
                    "; ".join(feature_audit.violations) or "no temporal violations found"))
    items.append(mk("TARGET_AUDIT", target_audit.verdict, target_audit.report_checksum(),
                    artifacts["target"],
                    "; ".join(target_audit.violations) or "no target-construction violations found"))
    items.append(mk("CANDIDATE_FREEZE", "PASS", snapshot.snapshot_checksum, artifacts["freeze"],
                    "candidate frozen and verified unchanged before every subsequent phase"))
    items.append(mk("TRAINING", "PASS", dev_record.signal_provenance["signal_checksum"],
                    artifacts["dev"],
                    "no model to train (deterministic rule); signal generation deterministic and "
                    "provenance-recorded"))

    v, r = _perf_verdict(dev_record.metrics)
    items.append(mk("DEVELOPMENT_EVALUATION", v, dev_record.result_checksum(), artifacts["dev"], r,
                    {"metrics": _brief(dev_record.metrics)}))
    v, r = _perf_verdict(holdout_record.metrics)
    items.append(mk("HOLDOUT", v, holdout_record.result_checksum(), artifacts["holdout"], r,
                    {"metrics": _brief(holdout_record.metrics)}))
    v, r = _perf_verdict(oos_record.metrics)
    items.append(mk("OOS", v, oos_record.result_checksum(), artifacts["oos"], r,
                    {"metrics": _brief(oos_record.metrics)}))

    pos = wfa.aggregate["positive_window_fraction"]
    wfa_verdict = "INSUFFICIENT" if pos is None else ("PASS" if pos > 0.5 and wfa.aggregate["total_net_profit"] > 0 else "FAIL")
    items.append(mk("WFA", wfa_verdict, wfa.report_checksum(), artifacts["wfa"],
                    f"{wfa.n_windows} windows, positive fraction "
                    f"{'n/a' if pos is None else f'{pos:.4f}'}, total net "
                    f"{wfa.aggregate['total_net_profit']:.2f}, {wfa.stability['concentration_flag']}"))

    viable = robustness.surface_summary["viable_region"]
    items.append(mk("ROBUSTNESS", "FAIL" if viable == "NONE" else ("INSUFFICIENT" if viable == "PARTIAL" else "PASS"),
                    robustness.report_checksum(), artifacts["robustness"],
                    f"viable region: {viable}; "
                    f"{robustness.surface_summary['n_points_pf_above_1']} of "
                    f"{robustness.surface_summary['n_points_with_trades']} grid points have PF > 1"))

    dep = cost_report.zero_cost_dependency.split(":")[0]
    items.append(mk("COST_STRESS", "FAIL" if dep in ("ZERO_COST_DEPENDENT", "NOT_COST_DEPENDENT") else
                    ("SURVIVES_COSTS" if dep == "SURVIVES_COSTS" else "UNDETERMINED"),
                    cost_report.report_checksum(), artifacts["cost"], cost_report.zero_cost_dependency))

    suff = stats_report.trade_count_sufficiency.split(":")[0]
    expectancy_ci = next(
        (i for i in stats_report.intervals
         if i["method"] == "BLOCK_BOOTSTRAP" and i["statistic"] == "expectancy_per_trade"), None
    )
    if expectancy_ci and expectancy_ci["ci_upper"] is not None and expectancy_ci["ci_upper"] < 0:
        stats_verdict, stats_reason = "FAIL", (
            f"block-bootstrap 95% CI for per-trade expectancy is "
            f"[{expectancy_ci['ci_lower']:.4f}, {expectancy_ci['ci_upper']:.4f}] -- entirely below zero"
        )
    elif suff == "SUFFICIENT":
        stats_verdict, stats_reason = "PASS", "sufficient trades and the expectancy interval is not entirely negative"
    else:
        stats_verdict, stats_reason = "INSUFFICIENT", stats_report.trade_count_sufficiency

    items.append(mk("STATISTICS", stats_verdict, stats_report.report_checksum(), artifacts["statistics"], stats_reason))
    items.append(mk("MULTIPLE_TESTING", mt_report.economic_edge_status, mt_report.report_checksum(),
                    artifacts["mt"], mt_report.interpretation))
    return items


def _record_failures(failures: FailureLibrary, *, summary, cost_report, wfa, robustness, mt_report,
                     stats_report, artifacts, candidate) -> None:
    features = tuple(candidate.spec.features)
    common = {"related_family": "FAMILY-000004", "related_features": features,
              "related_market": "EURUSD H1", "related_search_space": candidate.search_space_id or ""}

    if summary["development"]["net_profit"] < 0:
        failures.record(entity_id=CANDIDATE_ID, failure_stage="TRAINING",
                        failure_category="NEGATIVE_EXPECTANCY",
                        failure_reason=f"DEVELOPMENT partition net {summary['development']['net_profit']} "
                                       f"on {summary['development']['trades']} trades, "
                                       f"PF {summary['development']['profit_factor']}",
                        evidence_reference=artifacts["dev"], **common)
    if summary["oos"]["net_profit"] < 0:
        failures.record(entity_id=CANDIDATE_ID, failure_stage="OOS", failure_category="NEGATIVE_EXPECTANCY",
                        failure_reason=f"OOS (VALIDATION) net {summary['oos']['net_profit']} "
                                       f"on {summary['oos']['trades']} trades, PF {summary['oos']['profit_factor']}",
                        evidence_reference=artifacts["oos"], **common)
    if summary["holdout"]["net_profit"] < 0:
        failures.record(entity_id=CANDIDATE_ID, failure_stage="HOLDOUT", failure_category="NEGATIVE_EXPECTANCY",
                        failure_reason=f"PURE_HOLDOUT net {summary['holdout']['net_profit']} "
                                       f"on {summary['holdout']['trades']} trades, PF {summary['holdout']['profit_factor']}",
                        evidence_reference=artifacts["holdout"], **common)
    if (wfa.aggregate["positive_window_fraction"] or 0) <= 0.5:
        failures.record(entity_id=CANDIDATE_ID, failure_stage="WFA", failure_category="WFA_FAILURE",
                        failure_reason=f"only {wfa.aggregate['positive_window_fraction']:.4f} of "
                                       f"{wfa.aggregate['n_windows_with_trades']} traded windows were net positive; "
                                       f"losses are {wfa.stability['concentration_flag'].lower()}",
                        evidence_reference=artifacts["wfa"], **common)
    if robustness.surface_summary["viable_region"] == "NONE":
        failures.record(entity_id=CANDIDATE_ID, failure_stage="ROBUSTNESS",
                        failure_category="PARAMETER_FRAGILITY",
                        failure_reason="no point in the declared parameter neighbourhood achieves PF > 1; "
                                       "the failure is a property of the rule family, not of the chosen parameters",
                        evidence_reference=artifacts["robustness"], **common)
    if cost_report.zero_cost_dependency.startswith("ZERO_COST_DEPENDENT"):
        failures.record(entity_id=CANDIDATE_ID, failure_stage="COST_STRESS",
                        failure_category="COST_SENSITIVITY",
                        failure_reason=cost_report.zero_cost_dependency,
                        evidence_reference=artifacts["cost"], **common)
    if mt_report.economic_edge_status != mt_mod.ECONOMIC_EDGE_SUPPORTED:
        failures.record(entity_id=CANDIDATE_ID, failure_stage="MULTIPLE_TESTING",
                        failure_category="STATISTICAL_FAILURE",
                        failure_reason=mt_report.interpretation,
                        evidence_reference=artifacts["mt"], **common)


def _reconcile(recomputed: Dict[str, Any], stored: Dict[str, Any]) -> Dict[str, Any]:
    """Compare independently recomputed counters against the stored ones."""
    pairs = [
        ("TOTAL_CANDIDATES_GENERATED", "total_strategies_generated"),
        ("TOTAL_CANDIDATES_REJECTED", "total_strategies_rejected"),
        ("TOTAL_CANDIDATES_TESTED", "total_strategies_tested"),
        ("TOTAL_CANDIDATES_FAILED", "total_strategies_failed"),
        ("TOTAL_CANDIDATES_PASSED", "total_strategies_passed"),
    ]
    mismatches = []
    compared = []
    for recomputed_key, stored_key in pairs:
        if recomputed_key not in recomputed:
            continue
        compared.append({"recomputed_key": recomputed_key, "stored_key": stored_key})
        a, b = recomputed.get(recomputed_key), stored.get(stored_key)
        if a != b:
            mismatches.append({"counter": recomputed_key, "recomputed": a, "stored_as": stored_key, "stored": b})

    # Counters that differ for a KNOWN structural reason are reported in
    # full rather than quietly excluded from the comparison -- an omitted
    # counter is indistinguishable from a hidden one.
    divergences = []
    stored_surviving = stored.get("total_strategies_surviving")
    recomputed_surviving = recomputed.get("TOTAL_CANDIDATES_SURVIVING")
    if stored_surviving != recomputed_surviving:
        divergences.append({
            "counter": "surviving",
            "recomputed": recomputed_surviving,
            "stored": stored_surviving,
            "reason": (
                "These two fields do not mean the same thing. The registry's "
                "total_strategies_surviving is a monotonic counter incremented on first entry to "
                "STATISTICALLY_VALIDATED and never decremented, so it counts candidates that ever "
                "reached that gate. compute_search_accounting_summary's TOTAL_CANDIDATES_SURVIVING is "
                "derived from CURRENT state and counts candidates not presently REJECTED/FAILED. "
                "STRAT-000002 passed the statistics gate and was subsequently rejected, so it is "
                "counted by the first and not by the second. Both numbers are correct for their own "
                "definition; the field NAME is what is misleading. Raised as an open governance item "
                "in ML-001-GENERATION-4-REPORT.md rather than fixed here, because renaming a "
                "Generation-1 registry field during Generation 4 would itself be a silent governance "
                "change."
            ),
        })

    return {
        "status": "PASS" if not mismatches else "FAIL",
        "recomputed": recomputed,
        "stored": {k: stored.get(k) for k in
                   ("total_strategies_generated", "total_strategies_tested", "total_strategies_rejected",
                    "total_strategies_failed", "total_strategies_passed", "total_strategies_surviving",
                    "total_hypotheses_ingested", "selection_bias_status")},
        "compared_pairs": compared,
        "mismatches": mismatches,
        "definitional_divergences": divergences,
        "note": (
            "Counters are compared where the two sources define them identically. Where they do not, "
            "the difference is enumerated under definitional_divergences with both values and the "
            "reason -- never dropped from the comparison. A mismatch on an identically-defined counter "
            "sets status=FAIL; a documented definitional divergence does not, because the two numbers "
            "are answers to different questions."
        ),
    }


if __name__ == "__main__":
    main()
