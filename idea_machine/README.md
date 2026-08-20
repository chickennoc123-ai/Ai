# 🧠 IDEA MACHINE

A research-idea generator that feeds the existing Strategy Factory. It finds
raw material, turns it into falsifiable experiments, hands them over, and
learns from the verdicts.

It is a **separate module**. No Strategy Factory file was modified to build it,
and no Factory governance was relaxed.

```
INTERNET / PAPERS / DATA
          ↓
   ① WORLD SCANNER          idea material only — never a source of truth
          ↓
   ② KNOWLEDGE BASE         KNOWN / TESTED / SURVIVED / REFUTED /
          ↓                 BLOCKED / UNDERPOWERED / UNKNOWN
   ③ IDEA GENERATOR         no mechanism → no idea
          ↓
   ④ COMBINATION ENGINE     new mechanisms, not a cartesian product
          ↓
   ⑤ NOVELTY / MEMORY       NOVEL / REVIEW_REQUIRED / REJECTED_SEARCH_SPACE
          ↓
   ⑥ DATA FEASIBILITY       missing data → BLOCKED_DATA, never fabricated
          ↓
   ⑦ ECONOMIC PRE-FILTER    arithmetic vs the frozen cost model, no backtest
          ↓
   ⑧ IDEA RANKING           research priority — performance is not an input
          ↓
   ⑨ EXPERIMENT DESIGNER    pre-registered, frozen, with a kill gate
          ↓
   ⑩ IDEA QUEUE
          ↓
  ┌────────────────────┐
  │  STRATEGY FACTORY  │    unchanged; the only authority on validity
  └────────────────────┘
          ↓
  SURVIVOR / FAIL / BLOCKED / UNDERPOWERED / REFUTED
          ↓
   ⑪ FEEDBACK ENGINE  →  KNOWLEDGE BASE  ↺
```

## Quick start

```bash
# One research cycle: scan → … → hand frozen experiments to the Factory
python3 -m idea_machine.cli \
    --corpus  path/to/source/documents \
    --catalog path/to/dataset_catalog.json \
    cycle

python3 -m idea_machine.cli dashboard      # Phase 17 observability
python3 -m idea_machine.cli governance     # the authority boundary, in full
python3 -m idea_machine.cli verify         # replay ledgers + audit source tree
python3 -m idea_machine.cli ingest results.json   # apply Factory verdicts
```

The dataset catalog is **empty by default**, so an unconfigured machine blocks
every idea. That is the intended failure mode: assuming data exists is how an
experiment produces a confident answer to a question it never asked.

The scanner does **not** touch the network on its own. Register a provider
explicitly (`CallableProvider`) if you want that; a local corpus directory of
`*.json` documents works out of the box.

## What it cannot do

These are not gaps to be filled in later. Each one raises
`GovernanceViolation`, which **nothing inside the package catches** — a test
walks the AST of every module to prove no `except` clause could swallow one.

| Forbidden | Why |
|---|---|
| Read or consume the holdout | An idea generator that can see it will eventually fit to it |
| Authorize GEN14 | A machine that can authorize its own final gate has no final gate |
| Modify the cost model | Loosening costs is the cheapest way to manufacture a fake edge |
| Reset a ledger | It could then erase the record of what it already tried |
| Edit failure history | It could re-dig exhausted ground forever |
| Declare an edge | Only the Factory's full gate sequence may say that |
| Create an EA | That is how research becomes an accident in a live account |
| Re-test a refuted idea with a tweaked parameter | p-hacking with extra steps |
| Bypass any Factory gate | Every gate exists because something once got through |
| Mutate a pre-registration | A design that can be edited after the result is not pre-registered |

Human authority, never the machine's: **GEN14 authorization · live deployment ·
capital allocation · final product release**.

## The three distinctions the design turns on

**`UNDERPOWERED` is not `FAIL`.** An underpowered result is a statement about
the experiment, not about the market. Only `REFUTED` closes search space;
underpowered and blocked ideas stay re-testable, and the dashboard has a
dedicated section — *"where did we never actually look?"* — so those regions do
not quietly become indistinguishable from refuted ones.

**`SURVIVED` is not "an edge".** It means the Factory's tests did not refute it.
No epistemic state in this package means "edge"; `is_edge_claim()` returns
`False` for every one of them, and a terminal queue outcome requires a Factory
evidence reference, so the machine cannot decide its own idea's fate.

**Reasoning about a claim does not strengthen it.** `DERIVED_HYPOTHESIS` carries
the same evidential rank as the `IDEA_SOURCE_ONLY` material it came from. Rank
only rises by touching real data or by passing the Factory.

## Determinism

Same inputs → same ideas, same ids, same order. No `random`, no `uuid4`, no
reliance on dict ordering. Every id is a content hash over a canonicalised
payload, which is also what makes cross-run deduplication work.

## Layout

| Path | Phase | Role |
|---|---|---|
| `core/` | 0 | `IdeaSpec`, ids, append-only store, provenance, epistemic states |
| `governance/` | 16 | The authority boundary and its enforcement |
| `scanner/` | 1 | Providers, source records, deterministic concept extraction |
| `knowledge/` | 2 | Concept graph, findings, taxonomy |
| `generator/` | 3 | Mechanism templates → `IdeaSpec` |
| `combinator/` | 4 | Composition under four screening bars |
| `novelty/` | 5 | Failure memory + novelty verdicts |
| `economics/` | 6–7 | Data feasibility, frozen cost model, economic pre-filter |
| `ranking/` | 8 | Research-priority scoring |
| `experiment/` | 9 | `ExperimentSpec`, designer, pre-registration ledger |
| `queue/` | 10 | State machine |
| `integration/` | 11 | The single Strategy Factory hand-off |
| `feedback/` | 12 | Verdicts → knowledge |
| `adaptive/` | 13 | Forward-only search policy |
| `budget/` | 14 | Per-window caps |
| `pipeline.py` | 15 | The autonomous loop |
| `observability/` | 17 | Dashboard |
| `tests/` | 18 | Unit, integration, determinism, governance |

## Ledgers

Everything is append-only under `reports/idea_machine/` (override with
`--root`): sources, knowledge, ideas, queue transitions, pre-registrations,
submissions, failure memory, budget, governance audit, and cycle reports. The
stores refuse to shrink, refuse to rewrite a record under an existing id, and
report external tampering via `verify_integrity()`.

## Tests

```bash
python3 -m pytest idea_machine/tests -q
```

Covers unit behaviour, integration, determinism, provenance, deduplication,
failure memory, governance, no-holdout-access, no-ledger-reset, no-p-hacking,
queue integrity, and Factory integration.
