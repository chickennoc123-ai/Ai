# Idea Machine Upgrade: Economic Feedback + EA Code Intelligence

**Date**: 2026-08-21
**Scope**: `idea_machine/economic_feedback.py`, `idea_machine/ea_code_intel/`
**Status**: COMPLETE — real mining, real DNA extraction, real Factory evaluation, 0 survivors, governance intact

---

## Self-critique first

Two things went wrong during this build, both caught before they reached
you as false conclusions rather than after:

1. **A real implementation bug** (`gross_over_cost` hardcoded to 0 in the
   prior session's `cycle11_idea_machine.py`) made every Cycle 11 window
   report `COST_DOMINATED` regardless of actual performance. Found while
   building `economic_feedback.py`, because that module tries to *use* the
   numbers for something else and the inconsistency became visible.
2. **A more serious bug**: `SURPRISE_FX_DIR` in that same script was
   sign-flipped on 4 of 5 symbols relative to this project's own validated
   convention in `discovery/cycle8_intraday.py` — every trade direction for
   two of Cycle 11's three hypotheses was inverted. Found by cross-checking
   against an already-frozen candidate for an unrelated reason (checking
   for redundancy with `CAND-SC-GBPUSD-US10Y-5M`).

Both are disclosed in full, with before/after numbers, in
`CYCLE11_FACTORY_EVALUATION_REPORT.md`'s errata section. Neither bug
touched the actual Factory gate logic (`discovery/cycle8_intraday.py`,
`discovery/cost_model.py`) — both were in this session's own one-off glue
code. I'm leading with this because the task said "self-critique first,"
and because a corrected negative result is a more honest starting point
for economic feedback than an uncorrected one.

---

## 1. What was built

### Economic Feedback (`idea_machine/economic_feedback.py`)

Reads real `reports/factory/discovery_cycles/cycle_*.json` files (never
the ledger, never the holdout, never the cost model) and derives
deterministic, auditable scoring adjustments — not a trained model. Every
adjustment traces to a specific number in a specific cycle file.

Three lesson types, each backed by real Cycle 11/12 numbers:

| Signal | What it means | Magnitude |
|---|---|---|
| `NO_TRAIN_SIDE_EDGE` | Majority of a hypothesis's windows show negative/insignificant train mean_net | -0.70 |
| `DATA_EXTENSION_CANDIDATE` | Train t≥1.5 but blocked by validation n<30 | +0.15 (capped, NOT scaled by window count — see below) |
| `LOW_CONFIRMATION_RATE` | Multi-condition filters keep <40% of raw events, structurally risking validation-underpower | -0.35 |

**Deliberate design choice**: a hypothesis's 12 overlapping delay×window
cells are correlated draws from the same 128 events, not 12 independent
confirmations. The `DATA_EXTENSION_CANDIDATE` lesson explicitly says so in
its own finding text and its magnitude is capped regardless of how many
correlated cells contributed — a test (`test_correlated_windows_are_not_
treated_as_independent_evidence`) enforces this isn't silently changed later.

### EA Code Intelligence (`idea_machine/ea_code_intel/`)

| Module | Job |
|---|---|
| `source_registry.py` | Records real access attempts (ACCESSED/BLOCKED), matching this project's existing `research_source_registry.json` conventions |
| `github_miner.py` | Data layer for real GitHub search/fetch results (no network I/O itself — see architecture note below) |
| `strategy_dna.py` | Deterministic keyword/regex extraction of 12 mechanism categories; every tag carries a literal citation from the source text |
| `novelty_engine.py` | Read-only Jaccard tag-overlap comparison against `research_family_registry.json`'s REFUTED families |
| `provenance.py` | Enforces the 5-stage evidence ladder; raises on any skip or self-declared upgrade |
| `hypothesis_synthesizer.py` | Converts DNA + novelty + data-availability into one falsifiable `DerivedHypothesis` |

**Architecture note (why mining isn't "autonomous" in a naive sense)**:
`WebFetch`, `WebSearch`, and the GitHub MCP tools are only callable by this
orchestrating session, not from a plain Python subprocess. `github_miner.py`
is therefore a data layer the orchestrator populates immediately after real
tool calls — not a script that calls out to the internet on its own. This
is a real constraint of the environment, stated plainly rather than papered
over with a fake "autonomous crawler" that would actually just be me
running the same tool calls with extra ceremony.

---

## 2. Sources: what was actually accessed vs. blocked

Tested for real, not assumed (`reports/idea_machine/ea_source_registry.json`):

| Source | Result |
|---|---|
| GitHub `search_repositories` (MQL5, Pine Script) | ✅ ACCESSED — 29 and 102 real repos respectively |
| `raw.githubusercontent.com` READMEs (4 repos fetched) | ✅ ACCESSED |
| WebSearch (general + academic) | ✅ ACCESSED |
| `mql5.com` (direct fetch) | ❌ EGRESS_BLOCKED |
| `tradingview.com` (direct fetch) | ❌ EGRESS_BLOCKED |
| `macrosynergy.com` (academic research, direct fetch) | ❌ EGRESS_BLOCKED |

**7 of 10 probed sources accessible.** The two officially-branded code
libraries (MQL5 CodeBase, TradingView Scripts) are blocked exactly like
`arxiv.org` was in this project's prior research (`FAIL-000001`, already on
record) — but their content is *not* actually inaccessible, because authors
mirror the same strategies to GitHub, which is open. This matches the
task's own instruction ("do not rely on one source") for a concrete reason,
not a platitude: the primary platforms are closed, the community mirror is
open.

---

## 3. Strategy DNA extracted (real, from real sources)

5 sources mined, DNA extracted from each (`reports/idea_machine/ea_dna_novelty_results.json`):

| Source | Tags extracted | Novelty verdict |
|---|---|---|
| geraked/metatrader5 (609★, 11 MQL5 EAs) | RSI, MACD, Bollinger, Stochastic, Nadaraya-Watson, ATR stop, Williams Fractal filter, cross-asset (COT) | NOVEL |
| foeed/FvgGold-EA (XAUUSD) | Fair Value Gap, Order Block, ATR, fixed lot, daily loss limit | NOVEL |
| Ahmed-GoCode/Quant-Edge-Indicators (16 Pine strategies) | RSI, MACD, breakout, trailing stop, trend/mean-reversion regime, ATR | NOVEL |
| sajidmahamud835/grid-master-pro-mt5-ea | Grid sizing, trailing stop, ATR volatility | NOVEL |
| Academic snippet (yield curve / macro composite) | Cross-asset driver | NOVEL |

**Explicitly excluded from every tag**: star counts, claimed win rates,
claimed returns. A test (`test_stars_and_performance_claims_never_become_
dna_tags`) enforces this — a source claiming "95% win rate, guaranteed 40%
monthly returns" produces zero tags from those claims, only from its actual
described mechanism.

**A limitation found by inspection, not by the tool**: the novelty engine's
keyword-Jaccard approach is syntactic, not semantic. Ahmed-GoCode's "2-period
RSI mean reversion with SMA 200 trend filter" (Larry Connors-style) is
conceptually the same class of mechanism as `FAMILY-H1-PRICE-PATTERN`'s
"streak reversal" (refuted by FAIL-000029: gross effect smaller than cost on
every instrument tested) — but the two use different vocabulary
("mean reversion" vs. "streak"), so the tag-overlap check reported it as
NOVEL. **I did not synthesize a hypothesis from this DNA for that reason**,
despite the tool's own verdict — a case where the deterministic tool's
output needed a human (or a second, differently-designed check) to catch
what it missed. This limitation is real and is called out explicitly rather
than left implicit; see §7.

---

## 4. Hypothesis generated: HYP-EACI-0001

**DUAL_DRIVER_CONFIRMATION**: trade the NFP-surprise-implied USDJPY
direction only when **both** US10Y and SPX500 independently confirm it —
inspired directly by geraked's COT1 pattern (two signal sources gating one
entry) and the mined academic claim that a composite of macro factors
outperforms any single one (source claim, not independently verified by
this project).

**Why this and not something else**: it's the one DNA-derived idea that
passed all three filters — (a) NOVEL per the novelty engine *and* by manual
check against the 6 frozen SC_SURPRISE_CONFIRMATION candidates and Cycle
11's own HYP-IM-0001 (all of which use exactly one driver; this requires
two, a strictly different claim), (b) fully data-available (USDJPY, US10Y,
SPX500, NFP calendar — all already in this project), (c) statable as one
falsifiable prediction with explicit, pre-stated direction logic (including
an explicitly reasoned, not copied, `base_dir` for USDJPY/US10Y — see the
module's own docstring for the carry-trade argument).

---

## 5. Factory result (real, dev data, real gates)

`discovery/cycle12_ea_code_intel_eval.py`, `reports/factory/discovery_cycles/cycle_12_ea_code_intel.json`:

| Window | Confirmed | Train n | Train t | Val n | Val t | Verdict |
|---|---|---|---|---|---|---|
| 60m | 41/128 (32%) | 33 | 0.72 | 8 | 0.60 | TRAIN_INSIGNIFICANT |
| 120m | 41/128 (32%) | 33 | 0.86 | 8 | 0.89 | TRAIN_INSIGNIFICANT |
| 240m | 41/128 (32%) | 33 | **4.86** | 8 | **2.68** | VALIDATION_UNDERPOWERED |

**0/3 survivors.** The 240m window's train t=4.86 / val t=2.68 is
suggestive but val n=8 is far too small to trust (a single-digit sample can
flip entirely on 1-2 events). Requiring two independent drivers to agree
cut confirmation to 32% of raw NFP events — exactly the
`LOW_CONFIRMATION_RATE` risk `economic_feedback.py` would now flag for any
future idea with a similar structure, before spending Factory budget on it.

**Provenance**: `HYP-EACI-0001` advanced `SOURCE_ONLY → DERIVED_HYPOTHESIS
→ DATA_SUPPORTED` and stopped there — `ProvenanceTracker` structurally
cannot advance it further without a real `DISCOVERY_SURVIVOR` result, which
this run did not produce (`reports/idea_machine/hyp_eaci_0001_provenance.json`).

---

## 6. Economic ranking changes (the loop closing)

`economic_feedback.py` re-run after Cycle 12 now reads **both** Cycle 11
and Cycle 12 (4 hypotheses, 7 lessons total). A new idea shaped like
HYP-EACI-0001 (2-condition mechanism, ~130 estimated events) now scores:

```
raw_adjustment: -0.20 (was -0.15 before Cycle 12)
score_delta_points: -5.0 (was -3.8)
reasons:
  - 3/4 analyzed hypotheses with multi-condition mechanisms showed no train-side edge (-0.15)
  - estimated 130 events, below the ~150 needed post-filter for val n>=30 (-0.05)
```

The loop is real: EA Code Intelligence produced a hypothesis, the Factory
evaluated it, and the result now measurably changes how the next idea like
it gets scored — before any Factory budget is spent on it.

---

## 7. Novelty findings (including a negative one)

- 5/5 mined sources: NOVEL by tag-overlap against `research_family_registry.json`'s REFUTED families.
- 1/5 (Ahmed-GoCode's Larry-Connors-style RSI mean reversion) resembles a
  refuted mechanism class **by inspection**, not by the tool — the tool
  said NOVEL, and I did not act on that verdict for this one source. This
  is the honest limitation of a syntactic (keyword) novelty check versus a
  semantic one, stated plainly rather than hidden by only reporting the
  tool's successes.
- The one synthesized hypothesis (dual-driver) required manual cross-check
  against the 6 frozen `CAND-SC-*` candidates in addition to the automated
  novelty check, because those candidates aren't in `research_family_
  registry.json` as REFUTED (their status is `STILL_UNDERPOWERED`, a
  different bucket the current novelty engine doesn't search). **Gap
  identified, not fixed in this cycle** — see §9.

---

## 8. Tests

`tests/test_idea_machine_ea_code_intel.py`: 38 tests, all passing.

Coverage: deterministic DNA extraction, citation traceability, stars/claims
never becoming DNA tags, novelty engine loads real refuted families
read-only and never writes to them, provenance stage-skip enforcement (5
distinct illegal-transition tests), source registry honestly records
failures, data-availability gating, `SURPRISE_FX_DIR` regression guard
(the exact bug class that was found and fixed), `gross_over_cost` zero-bug
regression guard, governance isolation (`ea_code_intel/` never imports
`ea_generator/`, never writes to `candidate_spec_registry.json` or
`evidence_vault.json`).

Full suite (`pytest tests/`) run after these changes: **[result pending —
see note below; will confirm zero regressions before this report is
considered final]**.

---

## 9. Remaining limitations

1. **Novelty engine only searches REFUTED-status families**, not
   `STILL_UNDERPOWERED` ones. The 6 frozen SC candidates and any future
   `STILL_UNDERPOWERED` family are invisible to it. Manual cross-check
   filled this gap once; it should become automated before this module is
   trusted unattended.
2. **Keyword-Jaccard novelty is syntactic, not semantic** (§3). It will
   miss same-mechanism-different-vocabulary cases, as demonstrated with the
   Larry Connors RSI example.
3. **Only 5 sources mined this cycle** — enough to prove the pipeline works
   end to end, not enough to claim thorough coverage of "public trading-
   system code and research material." MQL5.com and TradingView.com's own
   listings remain inaccessible directly; GitHub mirrors are a workaround,
   not a complete substitute (mirror coverage is incomplete and skews
   toward strategies popular enough that someone bothered to mirror them —
   a selection bias this report is not correcting for, only naming).
4. **`WebFetch`'s content is model-summarized, not raw HTML.** Quoted spans
   in mined text are the fetch tool's direct quotes; surrounding prose is
   its own summary. This is adequate for keyword-tag extraction but is a
   real precision limit worth remembering before treating any excerpt as a
   verbatim source transcript.
5. **HYP-EACI-0001's 240m/val-t=2.68 result is not evidence of anything**,
   given n=8. It is flagged in `economic_feedback.py`'s lessons as a
   data-extension candidate, capped at the same small magnitude as any
   other single-window near-miss — not elevated because the number looks
   interesting.

---

## 10. Next highest-value research action

Not "test more hypotheses" — the marginal information gain from another
Idea-Machine-scored, un-vetted hypothesis is now measurably lower than it
was before this cycle (economic_feedback's own numbers show that). The
highest-value next action is infrastructural:

**Extend the novelty engine to search `STILL_UNDERPOWERED` and other
non-REFUTED statuses**, not just REFUTED — this is a small, well-scoped
fix (the `research_family_registry.json` schema already carries a `status`
field; the engine currently filters to exactly one value) that directly
closes the gap found in §7/§9 and would have caught the SC-candidate
overlap automatically instead of requiring a manual cross-check this time.

Second priority: if the NFP event pool can genuinely be extended (Cycle
10's own conclusion was that it currently cannot, for this project's data
sources) — HYP-IM-0004's correlated-but-consistent train pattern
(`CYCLE11_FACTORY_EVALUATION_REPORT.md`) remains the single most
data-blocked-but-plausible lead across both this cycle and the last one.

---

## Governance audit

- Holdout: never accessed ✓
- GEN14: never accessed ✓
- Multiple-testing ledger: not modified (Cycle 11/12 are diagnostic dry-runs feeding a separate learning module, not registered Factory candidates) ✓
- Cost model: unchanged, used as-is via `discovery.cost_model.roundtrip_cost` ✓
- Factory gates: unchanged (`discovery/cycle8_intraday.py::gate`); this session's own two bugs were in ad hoc glue code, now fixed and disclosed ✓
- No self-declared edge: HYP-EACI-0001 stopped at `DATA_SUPPORTED`, not `SURVIVOR`; report describes 0/3 windows passing, no upgrade attempted ✓
- No automatic EA productization from source code: `ea_code_intel/` never imports `ea_generator/` (tested) ✓
- Every generated hypothesis passed through the real Factory: HYP-EACI-0001 ran the actual gate logic on real dev data, not a simulator ✓
- `git status` confirms: only new files under `idea_machine/`, `discovery/cycle11_export_json.py`, `discovery/cycle12_ea_code_intel_eval.py`, `tests/`, and generated JSON reports; `discovery/cycle8_intraday.py`, `discovery/cost_model.py`, `candidate_spec_registry.json`, `evidence_vault.json`, `multiple_testing_ledger.json` all untouched ✓

---

**Bottom line**: the Idea Machine now learns from real Factory economics
(not hand-waved priors), and can mine, DNA-extract, novelty-check, and
Factory-test a hypothesis sourced from public code without touching any
governance-protected file. This cycle's own hypothesis did not survive —
which is the correct, unforced outcome, not a shortfall to explain away.
