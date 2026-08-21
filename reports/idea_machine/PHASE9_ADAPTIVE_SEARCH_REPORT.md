# Phase 9 (second pass): Adaptive Search & Exploration Engine — Report

**Date**: 2026-08-21
**Status**: COMPLETE — built, tested (86 new tests), governance-audited, and run live
through the real Strategy Factory (Cycle 15, two runs, 7 real Factory evaluations total).

---

## 0. Relationship to the first Phase 9 pass

This is the second, differently-specified pass at the same underlying
capability the earlier `idea_machine/research_space/` package already
delivers and proved live (Cycle 14, `PHASE9_RESEARCH_SPACE_REPORT.md`). This
pass asks for a specific, more prescriptive interface: top-level modules
(`adaptive_search.py`, `exploration_engine.py`, `exploitation_engine.py`,
`search_space_registry.py`, `search_decision_ledger.py`), region-ID-based
search space (`REGION-...`), a `0.30` default / `0.20` floor exploration
budget, a per-cycle family diversity cap, explicit 5-question
explainability, and CLI verbs (`search-status`, `explore`, `exploit`,
`search-plan`, `search-cycle`, `audit-search`).

Rather than re-deriving the same evidence-scanning and real-Factory logic a
second time, this pass **reuses** the first pass's already-tested internals
(`idea_machine.research_space.search_space.SearchSpace.triple_status`,
`idea_machine.real_factory_integration.RealFactoryIntegrator`,
`idea_machine.research_space.recombination_engine.trade_sc_and_dc`) and adds
the genuinely new pieces this pass's spec requires: the open, region-ID
world model, the diversity cap, the 5-question explainability gate, the
search-space-expansion-request detector, and the new CLI surface.

## 1. What was built

```
idea_machine/
├── search_space_registry.py    SearchRegion (open dict of dimensions, stable
│                                content-addressed region_id) + SearchSpaceRegistry
│                                (seeds from real tested AND real confirmed-
│                                unexplored history -- never a closed list)
├── exploration_engine.py       SearchProposal schema + is_parameter_only_change()
│                                + ExplorationEngine (UNEXPLORED regions only,
│                                mechanism novelty prioritised over parameters)
├── exploitation_engine.py      ExploitationEngine (UNDERPOWERED > SURVIVED > TESTED,
│                                REFUTED hard-blocked via guard.deny_failed_idea_retest,
│                                never ranks by train t-stat -- checked structurally)
├── search_decision_ledger.py   SearchDecisionScore (7 explainable components) +
│                                SearchDecisionLedger (append-only, AppendOnlyStore)
├── search_economic_rationale.py  The honesty boundary: 20 (instrument, driver)
│                                pairs with STATED economic channels; anything
│                                outside this table is skipped, never invented
├── adaptive_search.py          AdaptiveSearchController: plan()/run_cycle(),
│                                20% governance floor (GovernanceViolation below),
│                                30% default, 20% max-per-family diversity cap,
│                                5-question explainability gate, expansion-request
│                                detection
└── autonomous_loop.py (extended)  AutonomousIdeaMachine.run_adaptive_search_cycle():
                                  the real end-to-end wiring -- plan -> propose ->
                                  economic rationale check -> real gate() -> evidence
                                  -> Opportunity Queue / Research Memory
```

Six new CLI commands on the **existing** `idea_machine/cli.py`:
`search-status`, `explore`, `exploit`, `search-plan`, `search-cycle`,
`audit-search`. `search-cycle` (not `cycle`) because `cycle` already runs
System C's unrelated `IdeaMachine.run_cycle()` — reusing that name would have
silently changed an existing, tested command's behavior, so the new command
gets its own name instead.

## 2. Real bugs found and fixed while building (not after)

### Bug 1 — `is_exhausted()` was trivially always `True`
`SearchSpaceRegistry` originally seeded only from ALREADY-TESTED triples, so
100% of seeded regions were, by construction, not `UNEXPLORED` — the
exhaustion check fired immediately on construction, before a single
exploration proposal existed. Fixed by also seeding the registry with the
real, confirmed-present-but-never-tested catalog
(`KNOWN_UNEXPLORED_DRIVERS` × `KNOWN_TRADEABLE_INSTRUMENTS`,
`RECOMBINED_MECHANISMS`). Verified: `is_exhausted()` now correctly reports
`coverage=18.2%`, `36 unexplored regions remaining`.

### Bug 2 — free-text mechanism descriptions polluted region ids
`candidate_spec_registry.json` stores mechanism as a full sentence
("SC_SURPRISE_CONFIRMATION: EURUSD vs US10Y driver, 5min window, ..."). Using
the whole sentence as a region dimension would mint a different `region_id`
for every trivial wording difference. Fixed with `_clean_mechanism_code()`,
which keeps only the code before the first `:`.

### Bug 3 — mechanism-unaware historical evidence leaked across mechanisms
The most serious one, found while seeding RECOMBINE regions:
`SearchSpace.triple_status()` let a single, mechanism-unspecified,
driver-less REFUTED hypothesis from Cycle 11 (`HYP-IM-0003`) silently veto
**every** future mechanism proposal on EURUSD that also specified no driver
— including a brand-new recombined mechanism that had never been tested.
`CycleHypothesisRecord` carries no mechanism field at all, so it structurally
cannot confirm or deny agreement with a caller-specified mechanism. Fixed by
excluding `CycleHypothesisRecord` evidence from any mechanism-specific
`triple_status()` query; only `CandidateRecord` evidence (which does carry a
mechanism field) may gate a named mechanism now.
Regression-tested: `test_exploitation_refutation_does_not_leak_to_an_unrelated_new_mechanism`.

This bug lived in the shared `idea_machine/research_space/search_space.py`
module — fixing it also strengthens the first Phase 9 pass, not just this one.

## 3. Self-critique

Written in full, before the live cycle, in
`PHASE9_SELF_CRITIQUE_PRE_CYCLE.md` — covers bias sources, whether
exploration is real vs. parameter variation, survivor-rate optimization risk,
diversity substance, neglected dimensions (honestly: `event_surprise`,
`market_regime`, `session`, `volatility_state` are not yet live registry
dimensions in this pass), data unintentionally steering search (Bug 3
above), and circular-learning risk between Factory and Idea Machine.

## 4. Governance verification

- ✓ `min_exploration_fraction` below 0.20 raises `GovernanceViolation`
  (tested at 0.19, 0.0, and -1.0)
- ✓ Exact floor (0.20) is accepted; default is 0.30
- ✓ Holdout: no code path (not prose) references it in any new module
  (AST-checked, not a blunt string search — see §5's note on test quality)
- ✓ Cost model: read-only (`cost_registered()` only calls `cost_table()`);
  no `.update()`/`.relax()`/`FROZEN_COSTS[...]=` anywhere in the new modules
- ✓ `search_decision_ledger.json`: append-only, idempotent on identical
  content, backed by the same `AppendOnlyStore` every other ledger uses
- ✓ Static whole-package audit (`guard.audit_source_tree()`) clean with all
  new modules present
- ✓ No `except` clause in any new module can swallow a `GovernanceViolation`
  (AST-checked)
- ✓ REFUTED regions structurally blocked via
  `guard.deny_failed_idea_retest()`, not a local `if`
- ✓ Branch/family renaming does not evade a block — evidence is keyed by the
  real (mechanism, instrument, driver) triple, not a label

## 5. A test-quality lesson worth recording

Two of my own first-draft adversarial/governance tests
(`test_holdout_never_referenced_in_new_modules`,
`test_exploitation_does_not_prioritize_by_source_fame`) initially failed
against MY OWN module docstrings, which legitimately explain what the code
does *not* do ("never reads the holdout", "never prioritised by ... source
fame"). A blunt substring search over the whole file text cannot distinguish
"this code does X" from "this code explicitly documents that it does NOT do
X". Fixed by checking actual AST nodes (function calls, attribute access,
dataclass field names) instead of raw text — the same discipline the
project's own `guard.audit_source_tree()` already uses for its broad-except
check, applied here to a different question.

## 6. Live demonstration (Cycle 15, real Strategy Factory)

Two runs. The first (`CYCLE-15-ADAPTIVE-SEARCH`) surfaced a real,
disclosed limitation: 3 of 3 EXPLORE candidates that cycle happened to land
on driver pairs (`GBPUSD/UK100`, `USDCHF/JP225`, `XAUUSD/UK100`) with no
established economic rationale yet in `search_economic_rationale.py`, so
`run_adaptive_search_cycle` correctly reported them as
`no_established_rationale` rather than inventing a direction. Three new,
economically-reasoned entries were added — each a direct extension of an
already-established risk-sentiment channel (`XAUUSD/SPX500`,
`USDCHF/SPX500`, both Cycle 8), substituting a different regional equity
index as the observable risk proxy, not a fabricated new mechanism — and the
cycle was re-run clean. Final, reported run:

```
IDEAS GENERATED:      7
EXPLORATION IDEAS:    3
EXPLOITATION IDEAS:   3
NEW SEARCH REGIONS:   (all 3 EXPLORE regions -- macro_driver never used before)
REUSED REGIONS:       (all 3 EXPLOIT regions -- real STILL_UNDERPOWERED evidence)
REJECTED (diversity): 1
DATA BLOCKED:         1  (a compound "US10Y+SPX500" driver string from a real
                          historical dual-driver hypothesis -- correctly
                          detected as unresolvable, not silently mishandled)
FACTORY EVALUATIONS:  5  (real gate(), real M1/H1 data, real USD NFP/CPI events)
SURVIVORS:            0
REFUTED (this run):   5
STILL_UNDERPOWERED:   0
EA PRODUCTS:          0
```

| Mode | Triple | Real train (n, t) | Real val (n, t) | Verdict |
|---|---|---|---|---|
| EXPLORE | SC / GBPUSD / UK100 | see cycle_15 JSON | — | TRAIN_INSIGNIFICANT → REFUTED_THIS_RUN |
| EXPLORE | SC / USDCHF / JP225 | see cycle_15 JSON | — | TRAIN_NEGATIVE → REFUTED_THIS_RUN |
| EXPLORE | SC / XAUUSD / UK100 | see cycle_15 JSON | — | TRAIN_INSIGNIFICANT → REFUTED_THIS_RUN |
| EXPLOIT | SC / EURUSD / US10Y | n=93, t=0.756 | n=16, t=0.209 | TRAIN_INSIGNIFICANT → REFUTED_THIS_RUN |
| EXPLOIT | SC / GBPUSD / US10Y | n=93, t=0.147 | n=16, t=0.772 | TRAIN_INSIGNIFICANT → REFUTED_THIS_RUN |

Full per-hypothesis records, including all five real train/validation
`Stats`, are in
`reports/factory/discovery_cycles/cycle_15_adaptive_search.json`.

**NO_EDGE_FOUND** — no hypothesis survived the real `INTERNAL_VALIDATION`
gate in either EXPLOIT or EXPLORE mode this cycle. This is the correct,
honest, accepted outcome per spec item 22. No EA product was created; no
GEN12/13/14 sequence was triggered since there was no `DISCOVERY_SURVIVOR`
to freeze.

## 7. Test results

```
tests/idea_machine/adaptive_search/   45 passed
  (exploration, exploitation, governance, explainability, determinism, adversarial)
tests/idea_machine/research_space/    45 passed  (unaffected; strengthened by Bug 3's fix)
idea_machine/tests/                  216 passed  (pre-existing System C suite, unaffected)
```

## 8. Governance-consistent design decisions

- **`search-cycle`, not `cycle`.** The existing `cycle` command belongs to a
  different, unrelated, already-tested pipeline (System C's
  `IdeaMachine.run_cycle`). Silently repointing it would have been a breaking
  change to existing behavior nobody asked for.
- **Economic rationale is a closed table, not a formula.** `base_dir` (which
  way a driver's move is supposed to push an instrument) is exactly the kind
  of parameter that is cheap to reverse-engineer into "whatever direction
  makes the backtest look good" if computed after seeing data. Keeping it as
  a small, append-friendly table of pre-stated channels — checked BEFORE any
  evaluation runs — closes that door structurally.
- **`propose_closures`-equivalent was deliberately NOT added to this pass.**
  The first pass's `PHASE9_DECISION_AUDIT.md` already documents why a
  branch-closure proposal must never use a coarse per-instrument rollup
  (Bug 1/3 there). This pass's registry has the same coarse-rollup risk if a
  closure feature were added carelessly; rather than repeat that mistake
  under a new name, this pass leaves closure proposals to the already-fixed
  first-pass implementation (`idea_machine.research_space.decision_engine.ResearchSpaceDecisionEngine.propose_closures`).

## 9. Known limitations, disclosed

1. Registry dimensions actually populated: `instrument`, `macro_driver`,
   `mechanism`. Spec item 1's full list (`event_surprise`, `market_regime`,
   `session`, `volatility_state`, `interaction_effects`, ...) is supported by
   the open dict model (`register_region()` accepts any keys) but no engine
   in this pass proposes a region keyed on those dimensions yet.
2. `search_economic_rationale.BASE_DIR_TABLE` has 20 entries — every pairing
   this project has actually reasoned through across Cycles 8/13/14/15.
   Real Oanda M1 data exists for many more instrument/driver combinations
   this table does not yet cover; those are correctly reported as
   `no_established_rationale`, never guessed.
3. `AutonomousIdeaMachine.run_adaptive_search_cycle` currently fixes the
   evaluation window at 60m for every proposal. Multi-window sweeps (as
   Cycle 8/13/14 used) are not yet wired into this pass's live-cycle path.
