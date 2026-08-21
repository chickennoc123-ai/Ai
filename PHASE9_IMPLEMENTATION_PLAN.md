# Phase 9 Implementation Plan — Research Space Evolution Engine

**Written before any Phase 9 code**, per task item 29.

---

## 1. Audit: what already exists

The repository contains **two independent, mature systems** under `idea_machine/`,
built in different sessions, that Phase 9 must not duplicate.

### System A — the Strategy Factory itself (unchanged, real, authoritative)
- `discovery/cycle8_intraday.py`: real `gate(train_stats, val_stats)` function,
  real mechanism functions (`trade_dc/sc/dr/ri`), real M1/H1 price access
  (`M1Series`, `H1Series`), real event pool (`usd_events`).
- `discovery/cost_model.py`: frozen `roundtrip_cost()`, raises if a symbol has
  no pre-registered cost — no post-hoc registration permitted.
- `discovery/event_calendar.py`: `load_events()` enforces the holdout firewall
  (`guard_path` / OGD-4) structurally — a forbidden path raises before any
  data is read.
- `reports/factory/*.json`: `research_family_registry.json`,
  `candidate_spec_registry.json`, `discovery_cycles/*.json` — read-only,
  human/Factory-owned records.

**Verdict: this is the real Factory API. Phase 9 must call into it exactly as
Cycle 13 already proved works, never simulate it.**

### System B — the Phase 3/4/8 Idea Machine layer (built this session, proven live)
`idea_machine/research_memory.py`, `idea_machine/ea_code_intel/novelty_engine.py`,
`idea_machine/semantic_novelty.py`, `idea_machine/opportunity_queue.py`,
`idea_machine/real_factory_integration.py`, `idea_machine/autonomous_loop.py`.

- `ResearchMemory`: read-only aggregator over exactly the sources Phase 9's
  spec item 4 names (`research_family_registry.json`,
  `candidate_spec_registry.json`, `discovery_cycles/*.json`).
- `OpportunityQueue`: append-only, already used for STILL_UNDERPOWERED routing.
- `RealFactoryIntegrator`: pre-registers a hypothesis, then calls the **real**
  `gate()` and records **real** train/val `Stats` — proven in Cycle 13
  (`CYCLE_13_LIVE_RUN_REPORT.md`): 120 real gate evaluations, 3 real
  STILL_UNDERPOWERED entries, 0 fabricated survivors.

**Verdict: this is the proven, working bridge to the real Factory. Phase 9
reuses it directly for its end-to-end demonstration rather than building a
second bridge.**

### System C — the Phase 0–18 roadmap Idea Machine (`core/`, `governance/`,
`budget/`, `adaptive/`, `novelty/`, `knowledge/`, `queue/`, `experiment/`,
`generator/`, `combinator/`, `ranking/`, `integration/`, `feedback/`,
`scanner/`, `economics/`, `pipeline.py`, `cli.py`, `idea_machine/tests/`)

This is a **complete, independently tested, roadmap-driven system** (`python3
-m idea_machine.cli cycle/status/dashboard/governance/verify/ingest`) that
already implements a large share of what Phase 9 asks for:

| Phase 9 asks for | Already exists as |
|---|---|
| Governance boundary, "self-crash on bypass" | `governance/guard.py` + `governance/authority.py` — `GovernanceViolation`, statically proven uncatchable (`test_no_module_can_swallow_a_governance_violation`), `deny_holdout_access`, `deny_gen14_authorization`, `deny_cost_model_mutation`, `deny_ledger_reset`, `deny_failed_idea_retest`, `assert_source_tree_clean` |
| UNDERPOWERED ≠ REFUTED distinction | `core/epistemic.py` — explicit 7-state machine, `CLOSES_SEARCH_SPACE = {REFUTED}` only |
| Append-only ledgers, no history rewrite | `core/store.py` — `AppendOnlyStore`, refuses to shrink or rewrite a record under an existing id |
| Budget caps + reallocation without expansion | `budget/manager.py` — `ResearchBudget.allocate()` (largest-remainder apportionment across weights, fixed total) |
| Forward-only adaptive search (never touches a finished experiment) | `adaptive/search.py` — `AdaptiveSearch.derive_policy()`, family weights from failure memory, `MIN_WEIGHT` floor so no family goes to zero |
| No-p-hacking, frozen pre-registration | `experiment/prereg.py`, `core/idea_spec.py` (`assert_no_result_fields` structurally bans backtest numbers in a proposal) |
| Content-addressed, deterministic ids | `core/ids.py` — `mint_id`/`content_hash`/`canonical`, explicitly bans `random`/`uuid4`/dict-order dependence |
| Novelty vs failure memory | `novelty/checker.py` + `novelty/memory.py` |
| Cost model, read-only | `economics/cost_model.py` — frozen dataclass, checksum-verified, `update()`/`relax()` both call `guard.deny_cost_model_mutation` |

**What does NOT exist yet (the actual Phase 9 gap):**
1. No EXPLOIT/EXPLORE/RECOMBINE mode tagging on generated ideas, and no
   enforced minimum-exploration-share floor.
2. No multi-dimensional `ResearchSpace` model (instruments × asset classes ×
   event types × timeframes × holding periods × sessions × mechanisms ×
   drivers × confirmation rules × execution models × regime dimensions ×
   cross-asset relationships × behavioral hypotheses) with a per-dimension
   known/tested/refuted/underpowered/unexplored/blocked status. `core/families.py`
   is a flat 14-family list — one dimension, not the full space.
2b. No **exploration debt** counter, no **novelty budget** at 3 levels
   (parameter / mechanism-variation / new-family), no
   **parameter_exploration_saturation** signal.
3. No **information_gain** score independent of expected profit, no
   explainable, additive `research_value` breakdown, no support for
   generating a *discriminating experiment* between competing hypotheses.
4. No `DecisionRecord` schema (decision/reason/evidence/alternatives/score
   breakdown/confidence/reversible) and no `explain <decision_id>` command.
5. No deterministic **mutation operators** (`SWAP_INSTRUMENT`,
   `CROSS_ASSET_COMBINATION`, `MECHANISM_RECOMBINATION`, ...) with
   parent/mutation/reason/expected_information_gain provenance.
6. No `research_space_ledger.json` and no `space` / `explain` CLI commands.
7. `System C`'s `integration/factory_bridge.py` uses a **file-handoff /
   in-memory submitter** — it has never actually been wired to the real
   `gate()`. System B's `RealFactoryIntegrator` is the only proven real bridge
   in the repository (Cycle 13).

---

## 2. Design decision: build on top, reuse aggressively, never duplicate

Phase 9 (`idea_machine/research_space/`) will:

- **Reuse `idea_machine.governance.guard` directly** as its sole governance
  authority. No second guard, no second `GovernanceViolation` hierarchy.
  Extend `governance/authority.py`'s `PERMITTED` tuple with the small set of
  new declared actions Phase 9 needs (`MAP_SEARCH_SPACE`,
  `COMPUTE_EXPLORATION_DEBT`, `ALLOCATE_RESEARCH_MODE_BUDGET`,
  `SCORE_RESEARCH_VALUE`, `RECORD_DECISION`, `PROPOSE_BRANCH_CLOSURE`,
  `DESIGN_DISCRIMINATING_EXPERIMENT`). This is the one edit to an existing
  Idea Machine file this plan makes, and it is exactly the "integration
  adapter" item 29.4 permits — it touches only the Idea Machine's own
  declared-authority module, never the Strategy Factory.
- **Reuse `idea_machine.core.epistemic`** as the status vocabulary for every
  search-space dimension cell (`UNKNOWN`/`KNOWN`/`TESTED`/`SURVIVED`/
  `REFUTED`/`BLOCKED`/`UNDERPOWERED`), plus one Phase-9-local addition,
  `UNEXPLORED`, for a space region no cycle has ever touched (distinct from
  `UNKNOWN`, which epistemic.py defines as "a source claims it, untested" —
  `UNEXPLORED` means "not even proposed yet").
- **Reuse `idea_machine.core.store.AppendOnlyStore`** for
  `research_space_ledger.json` and the decision record ledger — not a new
  storage engine.
- **Reuse `idea_machine.core.ids`** (`mint_id`, `content_hash`, `canonical`)
  for every id minted in this package — determinism by construction, not by
  discipline.
- **Reuse System B's `ResearchMemory`, `NoveltyEngine`, `SemanticNoveltyEngine`,
  `OpportunityQueue`, `RealFactoryIntegrator`** as the read-only world-model
  sources and as the proven real-Factory bridge for the end-to-end
  demonstration. This is the direct implementation of spec item 4's named
  sources.
- **Reuse `discovery.cost_model.cost_table()` / `roundtrip_cost()`** (the
  frozen Factory cost model Cycle 13 already respected) for the cost-aware
  exploration check — never `idea_machine.economics.cost_model` (a
  parallel, System-C-only cost table that the real Factory pathway does not
  use) and never a new cost table.
- **Does NOT touch** `discovery/cycle8_intraday.py`, `discovery/cost_model.py`,
  `discovery/event_calendar.py`, any `reports/factory/*.json` (write access),
  or System C's `pipeline.py`/`cli.py` internals beyond the one declared
  addition of two new subcommands.

## 3. Governance boundary for Phase 9 specifically

Reusing the existing guard means Phase 9 inherits, for free, everything
System C's governance test suite already proves:

- `guard.deny_holdout_access()` at the one place Phase 9 code could
  conceivably reach for holdout (it never does, but the call is present as a
  documented, tested tripwire).
- `guard.deny_gen14_authorization()` — `research_space` can only ever
  *propose* `PROPOSE_BRANCH_CLOSURE` or emit a `DecisionRecord`; it has no
  path to `AUTHORIZE_GEN14`.
- `guard.deny_cost_model_mutation()` — the cost-aware exploration check reads
  `discovery.cost_model.cost_table()`, never writes it; a symbol without a
  registered cost is `DATA_BLOCKED`, exactly as Cycle 13 already demonstrated.
- `guard.deny_failed_idea_retest()` — a REFUTED family/mechanism cannot be
  re-proposed as EXPLOIT; the exploitation engine checks
  `ResearchMemory`/epistemic status before generating a candidate and raises
  through the guard if a caller tries anyway.
- `guard.assert_source_tree_clean()` — the existing static AST audit already
  walks every `.py` file under `idea_machine/`; `research_space/` inherits
  the check automatically because it lives inside that tree, and Phase 9's
  own test suite re-runs it explicitly as a regression guard specific to the
  new package.

## 4. The end-to-end demonstration path

The demonstration reuses the **exact proven pathway from Cycle 13**
(`discovery/cycle13_idea_machine_live.py`): real `gate()`, real M1/H1 data,
real USD NFP/CPI events, `RealFactoryIntegrator` for pre-registration and
gate evaluation, `OpportunityQueue.append()` for STILL_UNDERPOWERED routing.
What Phase 9 adds on top is the **decision layer above that pathway**: which
candidates get generated, in which mode (EXPLOIT/EXPLORE/RECOMBINE), with
what score breakdown and what recorded rationale — not a new way of touching
the Factory.

## 5. Deliverables (per spec §32)

```
idea_machine/research_space/
├── __init__.py
├── search_space.py          # ResearchSpace: dimensions × status cells, read-only world model
├── exploration_engine.py    # EXPLORE candidates: unexplored dimension combinations
├── exploitation_engine.py   # EXPLOIT candidates: deepen an evidenced family (blocked on REFUTED)
├── recombination_engine.py  # RECOMBINE candidates: structural combination, mechanism-level novelty check
├── research_allocator.py    # EXPLOIT/EXPLORE/RECOMBINE budget split, hard exploration floor
├── information_gain.py      # deterministic information_gain / research_value scoring, explainable breakdown
├── decision_engine.py       # ties allocation + scoring + generation into one cycle decision
├── decision_record.py       # DecisionRecord schema + append-only ledger of decisions
├── exploration_debt.py      # exploit-streak tracking, debt threshold -> forced exploration
├── novelty_budget.py        # 3-level novelty tracking + parameter_exploration_saturation
├── search_space_ledger.py   # AppendOnlyStore-backed cycle/decision/result ledger
├── space_mapper.py          # renders the `space` CLI report
└── explain.py                # renders the `explain <decision_id>` CLI report

reports/idea_machine/
├── PHASE9_RESEARCH_SPACE_REPORT.md
├── PHASE9_DECISION_AUDIT.md
└── PHASE9_SEARCH_SPACE_MAP.json

tests/idea_machine/research_space/
    (governance, explainability, exploration, novelty, factory, determinism)
```

Two subcommands are added to the **existing** `idea_machine/cli.py`:
`space` and `explain <decision_id>` — matching the exact invocation the spec
gives (`python3 -m idea_machine.cli space`).
