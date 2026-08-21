# Production Mode Audit — AGLE / EA Factory Pro System

Written before any production-mode code, per task instruction. Based on a
full-repository investigation (entry points, Factory evaluation paths,
productization, runtime infrastructure, state persistence, governance,
crash-safety). No files were modified to produce this report.

---

## AGLE hiện chạy từ đâu?

Three independent CLI entry points, none of them long-running:

- `python3 -m idea_machine.cli <cmd>` (`idea_machine/cli.py`) — research
  side: `cycle, status, dashboard, governance, verify, ingest, space,
  explain, search-status, explore, exploit, search-plan, search-cycle,
  audit-search`. `search-cycle` runs
  `AutonomousIdeaMachine.run_adaptive_search_cycle` — the real
  Explore/Exploit → Factory → Evidence loop built in the last two sessions.
- `python3 factory.py <cmd>` (repo root) — Strategy Factory side:
  `observe, discover, evaluate, cycle, status, holdout status, failures`.
- Roughly a dozen directly-runnable `discovery/cycleNN_*.py` scripts, each
  its own one-shot script writing its own `reports/factory/discovery_cycles/cycle_NN_*.json`.
- `qualification/gen14_c2_nfp.py` — the one-shot GEN14 runner.

**Nothing in this stack currently runs continuously.** Every invocation is a
single process that starts, does one unit of work, and exits.

## Pipeline nào đã thực sự chạy end-to-end?

**Real, proven, real-Factory-backed:** Idea → novelty check → pre-registration
→ real `gate()` (real M1/H1 data, real USD NFP/CPI events) → evidence
→ Research Memory / Opportunity Queue. Run three times this session
(Cycle 13, 14, 15), each producing real train/validation statistics and a
real `DISCOVERY_SURVIVOR`/`STILL_UNDERPOWERED`/`REFUTED_THIS_RUN` verdict.
**Zero survivors so far** — `NO_EDGE_FOUND` every time.

**Real, but never reached in practice:** Survivor → GEN12 → GEN13 → GEN14 →
EA. The GEN14 machinery (`qualification/gen14_runner.py`,
`qualification/gen14_c2_nfp.py`) is real, holdout-gated, checksum-verified
code — but it has only ever been run once, on 4 pre-existing candidates from
an earlier research effort (not from the Idea Machine), and **all 4 failed**
(3 on `G1_min_trades`, missing the n≥30 floor by one event; 1 on
`G5_multiple_testing`, Bonferroni-adjusted). All 4 are terminal — the
holdout was consumed and cannot be retried. **No candidate has ever reached
`PRODUCTIZED`.**

**Fake, and must never be reachable from production:** `idea_machine/full_cycle_runner.py`
drives `idea_machine/factory_integration.py`'s `FactorySimulator`, which
manufactures pass/fail verdicts from an MD5 hash of the hypothesis id
(`idea_machine/factory_integration.py:159-180`) and, on a fabricated pass,
fabricates an EA product string and sets `final_status = "PRODUCTIZED"`.
Evidence it has actually been run sits on disk right now:
`reports/idea_machine/CYCLE-E2E-20260821-*_factory_journeys.json`. It is
**not** in `idea_machine/governance/authority.py`'s `FORBIDDEN_IMPORTS`, so
nothing currently stops any future code from importing it. **This is fixed
as part of this task** (§ below), not left as a known gap.

## Factory integration nào là real?

`discovery/cycle8_intraday.py:gate()` (real M1/H1 data via `M1Series`/
`H1Series`, frozen cost model, thresholds `train.n≥30, train.t≥2.0,
val.n≥30, val.t≥1.5`), reached exclusively through
`idea_machine/real_factory_integration.py:RealFactoryIntegrator` — the path
`AutonomousIdeaMachine.run_adaptive_search_cycle` already uses. This is the
**only** path production mode will use.

## Productization hiện tại có thực sự tạo .mq5 không?

Yes — `ea_generator/generator.py` is real, working code, not a stub. It
hard-refuses to package anything unless
`spec.is_frozen() and gate.has_gen14_result(id) and result == "PASS"`
(`ea_generator/generator.py:55-75`) — enforced in code. Since nothing has
ever passed GEN14, **it has never actually produced an artifact** in this
repository's history; it is real and correctly gated, but dormant. It
supports exactly 4 legacy test frameworks
(`streak_fade, gap_fade, breakout, hour_drift`) — the Idea Machine's
cross-asset mechanisms (`SC_SURPRISE_CONFIRMATION`, etc.) have no matching
template yet. This is disclosed, not silently patched around: if a
cross-asset candidate ever legitimately reaches GEN14 PASS, packaging it
will correctly raise `UnqualifiedCandidateError("no generator template for
framework ...")` rather than silently emitting something wrong.

(Separately, `ea_products/sc_surprise_confirmation/` holds a hand-authored,
explicitly `EXPERIMENTAL`-labeled `.mq5` file that bypasses `ea_generator`
entirely and was never GEN14-authorized — its own `AUDIT_REPORT.md` states
this plainly, and its own tests assert every underlying combination never
even reached `DISCOVERY_SURVIVOR`. It is governance-isolated and not part
of the production path; left untouched.)

## Runtime nào đã tồn tại? Watchdog nào đã tồn tại?

None, in the research/Factory stack. A real 24/7 loop exists
(`ml_001_agle_production_orchestrator.py`, `asyncio` health-check task,
`while True: await asyncio.sleep(300)`), but it belongs to a completely
separate system — the **live trading** account orchestrator, unrelated to
idea generation or strategy discovery. Nothing there is reused; the
research-side supervisor built for this task is new, on top of existing
one-shot entry points, not a copy of the live-trading one.

## State nào đã persist? State nào chưa?

~35 independent JSON files, no unified transaction log. Two persistence
tiers, by mechanism:

- **Atomic + checksummed** (`idea_machine.core.store.AppendOnlyStore`,
  `discovery.ledger.MultipleTestingLedger`): temp-file + `os.replace`,
  refuse-to-shrink, content-hash verified. Used by `decision_records.json`,
  `research_space_ledger.json`, `search_decision_ledger.json`,
  `governance_audit.json`, `multiple_testing_ledger.json`.
- **Not atomic, no dedup guard**: `OpportunityQueue.save()`
  (`idea_machine/opportunity_queue.py`) does a plain `write_text()` — a
  crash mid-write leaves a truncated file. `RealFactoryIntegrator.save_journeys()`
  (`idea_machine/real_factory_integration.py`) fully overwrites its target
  file on every call and has **no idempotency check** — resubmitting the
  same hypothesis id re-runs the real gate and double-records it. **Both
  are fixed as part of this task** (atomic temp+rename write for both; a
  new evaluation ledger adds the missing idempotency check).

## Những điểm nào có thể gây duplicate evaluation?

`RealFactoryIntegrator.pre_register_hypothesis()` /
`evaluate_with_real_gates()` have no id-based check against prior
evaluations, and every call site constructs a fresh `RealFactoryIntegrator`
with an empty in-memory journey list. Two `search-cycle` runs (or one run,
one crash, one restart) submitting the same `(mechanism, instrument,
driver, window)` triple would silently re-run the real gate twice. Fixed by
a new, persistent `EvaluationLedger` (append-only, id = content hash of the
triple) consulted **before** any real evaluation runs.

## Những điểm nào có thể gây mất state sau crash?

The two non-atomic writers above. Fixed by the same atomic-write pattern
already used correctly elsewhere in the codebase (`AppendOnlyStore._save`).

## Những điểm nào có thể tạo product trái governance?

`FactorySimulator`'s fabricated `"PRODUCTIZED"` status, if anything ever
consumed it as if it were real (nothing currently does downstream, but
nothing stopped it either). Fixed by (a) adding
`idea_machine.factory_integration` to `FORBIDDEN_IMPORTS` so the existing
static audit catches any future reference from inside `idea_machine/`, and
(b) removing the one real caller (`full_cycle_runner.py`'s
`_stage_5_factory_evaluation`) so it uses `RealFactoryIntegrator` instead.

---

## Design decision this audit leads to

**Master switch, supervisor, evaluation ledger, EA registry, and the
productization gate must live OUTSIDE `idea_machine/`.** The productization
gate needs authority to call `ea_generator`, `discovery.holdout_authorization`,
and `discovery.candidate_spec_registry` — modules `idea_machine/governance/authority.py`'s
`FORBIDDEN_IMPORTS` already, correctly, bars the Idea Machine itself from
touching (`idea_machine` may research; only the Factory/qualification layer
may authorize and productize). A new top-level `production/` package
(sibling to `idea_machine/`, `discovery/`, `qualification/`, `ea_generator/`)
holds this orchestration layer, exactly mirroring the existing separation
rather than weakening it. A root-level `agle.py` CLI (sibling to the
existing `factory.py`) exposes it.

## What is explicitly NOT rebuilt

Per the task's own "stop building new research modules" instruction:
`AutonomousIdeaMachine`, `RealFactoryIntegrator`'s core evaluation logic
(only its file-write atomicity is patched), `SearchSpaceRegistry`,
`AdaptiveSearchController`, `gate()`, the cost model, GEN12/13/14
qualification logic, and `ea_generator`'s packaging logic are all reused
as-is. Nothing here reimplements evaluation, novelty, scoring, or
qualification.
