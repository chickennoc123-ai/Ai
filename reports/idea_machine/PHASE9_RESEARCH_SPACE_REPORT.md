# Phase 9: Research Space Evolution Engine — Implementation & Live Run Report

**Date**: 2026-08-21
**Status**: COMPLETE — `idea_machine/research_space/` built, 43 new tests passing, real
end-to-end demonstration run through the actual Strategy Factory (Cycle 14), all
216 pre-existing Idea Machine tests still passing.

---

## 0. What Phase 9 is, in one sentence

The engine decides **what to research next**, never **how to make a hypothesis
pass** — every candidate it proposes still has to survive the same real
`gate()` function on real data that every other hypothesis in this project
has always had to survive.

---

## 1. Audit first, then build (see `PHASE9_IMPLEMENTATION_PLAN.md`)

Before writing any Phase 9 code, the existing `idea_machine/` package was
audited in full. It turned out to contain **two** mature systems already:

- A Phase 0–18 roadmap Idea Machine (`core/`, `governance/`, `budget/`,
  `adaptive/`, `novelty/`, `knowledge/`, `queue/`, `experiment/`,
  `generator/`, `combinator/`, `ranking/`, `integration/`, `feedback/`,
  `scanner/`, `economics/`, `pipeline.py`, `cli.py`) with its own 216-test
  suite, a statically-proven-uncatchable `GovernanceViolation`, an
  epistemic 7-state machine, append-only stores, and a budget allocator.
- The Phase 3/4/8 layer built earlier this session
  (`research_memory.py`, `novelty_engine.py`, `semantic_novelty.py`,
  `opportunity_queue.py`, `real_factory_integration.py`) — the only proven
  bridge to the **real** `discovery/cycle8_intraday.py` `gate()` function,
  demonstrated live in Cycle 13 (`CYCLE_13_LIVE_RUN_REPORT.md`).

Phase 9 therefore **reuses rather than rebuilds**: the governance guard, the
epistemic states, `AppendOnlyStore`, content-addressed ids, `ResearchMemory`,
the novelty engines, and `RealFactoryIntegrator` are all imported directly.
The only edit to an existing file is seven new declared action names appended
to `governance/authority.py`'s `PERMITTED` tuple — the Idea Machine's own
authority list, not the Strategy Factory.

---

## 2. What was built

```
idea_machine/research_space/
├── search_space.py          ResearchSpace: 13 dimensions x epistemic status,
│                             built from real Factory records only (ResearchMemory
│                             + Cycle 8/13's own PAIRINGS/mechanism catalogs +
│                             independently-confirmed-present driver/instrument data)
├── exploitation_engine.py    EXPLOIT: CHANGE_HOLDING_HORIZON / CHANGE_CONFIRMATION_STRUCTURE,
│                             blocked on a REFUTED triple via the SAME governance guard
├── exploration_engine.py     EXPLORE: SWAP_DRIVER / SWAP_INSTRUMENT / ADD_DIMENSION,
│                             restricted to UNEXPLORED cells (mechanism novelty over parameter)
├── recombination_engine.py   RECOMBINE: MECHANISM_RECOMBINATION, includes a REAL callable
│                             AND-combination of two Cycle-8 mechanisms (trade_sc_and_dc)
├── research_allocator.py     EXPLOIT/EXPLORE/RECOMBINE slot split, 20% governance floor
│                             (never configurable lower), single-family cap
├── information_gain.py       ResearchCandidate + deterministic, additive ScoreBreakdown
│                             (never a bare number, never expected-profit-only)
├── decision_engine.py        Ties allocation + scoring + real cost/data checks into one
│                             cycle; proposes (never enacts) branch closures
├── decision_record.py        DecisionRecord schema + its own append-only ledger
├── exploration_debt.py       Consecutive-exploit-only-cycle counter, forces MORE
│                             exploration, never less
├── novelty_budget.py         3-level novelty (parameter/mechanism-variation/new-family),
│                             groups RSI(14)/(15)/(16)-style variants into ONE family
├── search_space_ledger.py    Append-only cycle/decision/result ledger (AppendOnlyStore)
├── space_mapper.py           `idea_machine.cli space` report
└── explain.py                 `idea_machine.cli explain <id>` report
```

Two subcommands added to the **existing** `idea_machine/cli.py`:
`space` and `explain <decision_id>`.

---

## 3. Real bugs found and fixed during this build (not after)

Both were caught by actually running the engine against real data, not by
inspection alone — consistent with the task's own instruction to fix first,
report second.

### Bug 1 — coarse per-dimension cells wrongly blocked exploitation
`SearchSpace.cell("instruments", "EURUSD")` rolls up **every** piece of
evidence touching EURUSD into one status. EURUSD genuinely carries a REFUTED
hypothesis (`HYP-IM-0003`, driver-less) — but a naive check against that
rolled-up cell would have refused to exploit EURUSD/US10Y (a completely
different, only-`STILL_UNDERPOWERED` triple), because the instrument alone
looked REFUTED.

**Fix**: added `SearchSpace.triple_status(mechanism, instrument, driver)`,
which matches the real `(symbol, driver[, mechanism])` combination in
`ResearchMemory` directly, and switched `ExploitationEngine` to use it instead
of the coarse rollup. Verified: `EURUSD/US10Y/SC` now correctly reports
`UNDERPOWERED` (exploitable), while a driver-less EURUSD proposal still
correctly hits `REFUTED` and is blocked.
See `tests/idea_machine/research_space/test_governance.py::test_exploitation_does_not_block_a_different_triple_on_the_same_instrument`.

### Bug 2 — family cap collapsed EXPLOIT and EXPLORE into one family
`ResearchAllocator.enforce_family_cap` originally grouped candidates by
`(mechanism, instrument)` only. Live Cycle 14 run #1 allocated 1 EXPLORE slot
out of 7, but **zero EXPLORE candidates were actually accepted** — because the
family cap saw `EXPLOIT USDJPY/USB02Y` and `EXPLORE USDJPY/JP225` (different
drivers, same mechanism+instrument) as "the same family" and capped the
combined group down to 1, and the EXPLOIT pick won that internal tie. This
would have silently defeated the mandatory exploration floor every time an
EXPLORE candidate happened to share an instrument with the cycle's EXPLOIT
pick — a real, structural violation of spec item 28 that a purely-unit-tested
build would not have caught (the unit tests for the allocator used
single-mode candidate pools).

**Fix**: family key changed to `(mechanism, instrument, driver)`, matching
`novelty_budget.py`'s own definition of a "parameter family" exactly. Re-ran
Cycle 14 clean: all three modes (EXPLOIT, EXPLORE, RECOMBINE) were accepted
and sent to the real Factory.

### Bug 3 — closure proposals used the same coarse rollup as Bug 1
`propose_closures()` iterated `search_space.by_status(REFUTED)` over **every**
dimension, including the coarse `instruments`/`drivers`/`mechanisms` rollups
Bug 1 already showed were unsafe to treat as a single verdict. Live Cycle 14
proposed `BRANCH_CLOSED` for `instruments.EURUSD` on the strength of 5 mixed
evidence entries — one genuinely REFUTED (a driver-less hypothesis) sitting
next to unrelated `STILL_UNDERPOWERED` evidence on completely different
EURUSD/US10Y triples. Proposing to close "the instrument" from that mixture
would overstate the real evidence to whoever read the proposal.

**Fix**: `propose_closures()` now only considers the `combinations` dimension,
where a cell value is a real `research_family_registry.json` family id (one
coherent thing, not a rollup). Re-verified: the two REFUTED families already
in the registry (`FAMILY-C2-SURPRISE-REACTION-NFP-USD`,
`FAMILY-H1-PRICE-PATTERN`) each carry exactly one evidence entry (they are
already closed by the Factory itself), so they correctly fall below the
"≥2 independent evidence entries" bar and produce zero *new* proposals —
which is the honest answer: there is nothing left to propose closing that the
Factory hasn't already closed.

---

## 4. Live end-to-end demonstration (Cycle 14)

Full narrative, real numbers, and the governance trail are in
`reports/factory/discovery_cycles/cycle_14_research_space_evolution.json`.
This is the FINAL run, after all three bugs in §3 were fixed. Summary:

```
CANDIDATES GENERATED:        7   (1 EXPLOIT, 5 EXPLORE, 1 RECOMBINE)
CANDIDATES ACCEPTED:         3   (EXPLOIT=1, EXPLORE=1, RECOMBINE=1)
DATA BLOCKED:                0
REAL FACTORY EVALUATIONS:    3
SURVIVORS:                   0
STILL_UNDERPOWERED:          1
REFUTED (this run):          2
EA PRODUCTS CREATED:         0
BRANCH CLOSURE PROPOSALS:    0 (advisory only -- see Bug 3; correctly empty)
```

| Mode | Triple | Window | Real train (n, t) | Real val (n, t) | Verdict |
|---|---|---|---|---|---|
| EXPLOIT | SC / USDJPY / USB02Y | 300m | n=57, t=4.832 | n=18, t=-0.264 | VALIDATION_UNDERPOWERED → queued OPP-000071 |
| EXPLORE | SC / USDJPY / UK100 | 60m | n=86, t=-0.145 | n=10, t=-0.034 | TRAIN_NEGATIVE → REFUTED_THIS_RUN |
| RECOMBINE | SC_AND_DC / GBPUSD / UK10YB | 60m | n=52, t=-1.336 | n=9, t=1.372 | TRAIN_NEGATIVE → REFUTED_THIS_RUN |

**NO_EDGE_FOUND** — no hypothesis survived the real `INTERNAL_VALIDATION`
gate. This is the correct, honest outcome; the objective was never to
manufacture a winner.

### Known limitation, disclosed rather than hidden
Bugs 2 and 3 were each found and fixed **between** successive runs of the
same demonstration cycle — the only way either was actually discoverable,
since both were interactions the unit test suite's narrower scenarios did not
exercise. Each of the three runs sent `EXPLOIT USDJPY/USB02Y/300m` to the
real Factory and correctly recorded the same genuine `STILL_UNDERPOWERED`
result (train t=4.832, val n=18). Discarding those entries was not an
option — the opportunity queue is append-only by design, and every one of the
three evaluations was arithmetically correct; only the *surrounding decision
logic* (family cap, then closure proposals) was buggy across runs 1 and 2.
The result: **`OPP-000069`, `OPP-000070`, and `OPP-000071` are three
append-only ledger entries describing the same one real finding**, not three
independent discoveries. This is stated here plainly rather than concealed by
quietly editing the ledger, which governance forbids in any case.

---

## 5. Governance verification

- ✓ Holdout: never read, never referenced (static check in
  `test_governance.py`; the sealed-holdout guard in
  `discovery/event_calendar.py` is inherited unchanged)
- ✓ GEN14: never requested. `DISCOVERY_SURVIVOR` would be frozen and
  reported for the *existing* GEN14 process (this run found none)
- ✓ Cost model: read-only (`discovery.cost_model.cost_table()`); no symbol
  was added post-hoc
- ✓ Multiple-testing ledger: untouched (`git diff` confirms)
- ✓ `research_family_registry.json` / `candidate_spec_registry.json`: read
  via `ResearchMemory` only, never written
- ✓ REFUTED triples: exploitation refuses via
  `guard.deny_failed_idea_retest`, structurally, not by convention
- ✓ Branch closures: proposed only (`PROPOSE_BRANCH_CLOSURE`), never
  enacted — `research_family_registry.json` bytes unchanged before/after
  `propose_closures()` (tested explicitly)
- ✓ No new `GovernanceViolation`-swallowing handler anywhere in
  `research_space/` (AST-audited)
- ✓ Static audit (`guard.audit_source_tree()`, walking the *whole*
  `idea_machine/` package) passes clean — this **also required fixing** six
  pre-existing broad `except Exception` handlers in `cycle_runner.py` and one
  in `full_cycle_runner.py` (written earlier this session, before this
  audit's existence was known), narrowed to concrete runtime error types so
  a `GovernanceViolation` can never be silently absorbed there either

---

## 6. Test results

```
tests/idea_machine/research_space/   44 passed  (governance, explainability,
                                       exploration, novelty, factory, determinism)
idea_machine/tests/                 216 passed  (pre-existing System C suite,
                                       unaffected by this addition)
```

---

## 7. What Phase 9 deliberately does NOT do

- It does not generate a full autonomous idea-generation corpus (that is
  System C's `generator/`/`combinator/` domain, untouched).
- It does not wire System C's `pipeline.py`/`FactoryBridge` to the real
  gate — that bridge remains file-handoff-based; Phase 9's real-Factory path
  reuses the proven Phase 8 `RealFactoryIntegrator` instead, exactly as
  Cycle 13 already did.
- It does not authorize GEN14, declare an edge, or create an EA — all three
  raise through the shared `guard`.

See `PHASE9_DECISION_AUDIT.md` for the full self-critique against the
spec's own 10-point checklist.
