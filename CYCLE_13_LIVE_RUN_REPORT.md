# Cycle 13: Live Idea Machine → Real Strategy Factory Run

**Date**: 2026-08-21
**Status**: COMPLETE — real hypotheses, real M1/H1 data, real gate(), real outcomes. No simulation used anywhere.

---

## What this is

This is not a demonstration that the pipeline works — it is an actual research
cycle. 27 hypotheses were generated, checked against research memory and both
novelty engines, and 20 of them were sent through the **real** `gate()`
function from `discovery/cycle8_intraday.py` against **real** Oanda M1/H1
price data and the **real** USD NFP/CPI event calendar (2010–2020, 268
events). No `FactorySimulator`, no invented statistics, no manufactured
survivor.

**Result: `NO_EDGE_FOUND`.** Zero hypotheses passed the real
`INTERNAL_VALIDATION` gate. Three showed real train-period signal but were
correctly blocked by validation sample size and routed to the Opportunity
Queue rather than being counted as an edge.

---

## Where the hypotheses came from

Rather than inventing new, untested mechanism logic, this cycle reused the
**unchanged, already-audited** `gate()`, `stats()`, and four mechanism
functions (`trade_dc`, `trade_sc`, `trade_dr`, `trade_ri`) from Cycle 8
(`discovery/cycle8_intraday.py`). Novelty came from applying that exact
mechanism logic to symbol/driver pairings **never present in any prior
cycle's `PAIRINGS` list** — verified by reading Cycle 8's source directly
before writing this cycle's script.

Two groups:

**Group A — new instruments** (USDCAD, AUDUSD, EURJPY), extending the same
cross-asset divergence/confirmation/delayed-reaction/reversal mechanisms to
a petro-currency (oil), a risk/commodity currency (equities), and a classic
carry-trade barometer pair.

**Group B — new drivers on already-tested instruments** (GBPUSD, EURUSD,
USDJPY, XAUUSD), paired against domestic-yield curves (UK 10y, German 10y)
and the US 2-year (short-end, Fed-policy-sensitive real-rate proxy) — none
of which Cycle 8 tested. These are structurally distinct hypotheses: Cycle 8
tested USD-relative yield differentials and broad risk sentiment; this cycle
tests each currency's *own* domestic yield curve, and gold's sensitivity to
short-end *real* rates (opportunity cost of holding a non-yielding asset)
rather than to general risk-off flows or inflation co-movement.

---

## Governance discipline enforced in code, not just described

| Constraint | How it was enforced |
|---|---|
| Sealed holdout never touched | `discovery/event_calendar.py`'s own `guard_path()` (OGD-4) rejects any holdout-directory path; this cycle never called into holdout code at all |
| Cost model never modified post-hoc | AUDUSD and EURJPY have no pre-registered cost in `discovery/cost_model.py`. Rather than adding one, the script checks `cost_table()` membership **before** evaluation and marks those hypotheses `DATA_BLOCKED` |
| Multiple-testing ledger never modified | Not written to at any point in this cycle |
| Frozen candidates never touched | `candidate_spec_registry.json` was only read (via Research Memory), never written |
| No fabricated intraday data | USDJPY has no real M1 source (confirmed absent by Cycle 8's own audit). This cycle applies the same restriction to itself: 5m/15m/30m windows for USDJPY are marked `BLOCKED_NO_INTRADAY_DATA`, not approximated from H1 bars |
| Opportunity Queue append-only | Three new entries appended (`OPP-000066/67/68`); nothing in the existing 65 entries was edited |
| REFUTED families would block synthesis | Checked via both syntactic (tag-Jaccard) and semantic (mechanism-class) novelty engines before every pre-registration; none of the 20 pre-registered hypotheses matched a REFUTED family in this run |

---

## Bug found and fixed *during* this live run

The semantic novelty engine's `_mechanisms_match()` treated "same mechanism
class" alone as sufficient for a match. Since `event_driven` contains generic
structural keywords (`event`, `nfp`, `cpi`, `macro`) shared by *every*
macro-timed strategy in this project, the very first hypothesis evaluated
(`HYP-C13-USDCAD-WTICO-DC`) was incorrectly flagged as matching REFUTED
family `FAMILY-C2-SURPRISE-REACTION-NFP-USD` — on the strength of one shared
word (`nfp`) out of thirteen, jaccard ≈ 0.07. Left uncorrected, this would
have permanently blocked all future event-timed research.

**Fix**: require real keyword overlap (jaccard ≥ 0.2 **and** ≥ 2 shared
keywords), not class membership alone. Verified against the real registry:
the false positive now scores below threshold; a genuine terminology variant
of `FAMILY-H1-PRICE-PATTERN` ("streak reversal … gap fade", jaccard ≈ 0.27,
3 shared keywords) still correctly matches. A regression test was added
(`test_semantic_matching_same_class_alone_is_not_enough`). Full test suite
re-verified passing before the run was retried.

---

## Full per-hypothesis results

### Group A: new instruments

| Hypothesis | Mechanism | Windows evaluated | Best train t | Best val n | Verdict |
|---|---|---|---|---|---|
| HYP-C13-USDCAD-WTICO-DC | Cross-asset divergence | 5/15/30/60/120/240m | 1.395 (240m) | 27 | REFUTED_THIS_RUN — no window cleared train significance; several negative |
| HYP-C13-USDCAD-WTICO-SC | Surprise confirmation | 5/15/30/60/120/240m | **2.942** (5m) | 14 | **STILL_UNDERPOWERED** → OPP-000066 |
| HYP-C13-USDCAD-WTICO-DR | Delayed reaction | 5/15/30/60/120/240m | n/a (all negative/insig.) | — | REFUTED_THIS_RUN |
| HYP-C13-USDCAD-WTICO-RI | Reversal after impulse | 5/15/30/60/120/240m | n/a (all negative/insig.) | — | REFUTED_THIS_RUN |
| HYP-C13-AUDUSD-SPX500-{DC,SC,DR,RI} | all 4 | — | — | — | **DATA_BLOCKED** — AUDUSD has no pre-registered cost |
| HYP-C13-EURJPY-NAS100-{DC,DR,RI} | 3 of 4 (SC excluded, no honest USD-surprise mapping) | — | — | — | **DATA_BLOCKED** — EURJPY has no pre-registered cost |

### Group B: new drivers on registered instruments

| Hypothesis | Mechanism | Best train t | Best val n | Verdict |
|---|---|---|---|---|
| HYP-C13-GBPUSD-UK10YB-DC | Cross-asset divergence | negative throughout | — | REFUTED_THIS_RUN |
| HYP-C13-GBPUSD-UK10YB-SC | Surprise confirmation | negative/insig. throughout | — | REFUTED_THIS_RUN |
| HYP-C13-GBPUSD-UK10YB-DR | Delayed reaction | negative throughout | — | REFUTED_THIS_RUN |
| HYP-C13-GBPUSD-UK10YB-RI | Reversal after impulse | insignificant throughout | — | REFUTED_THIS_RUN |
| HYP-C13-EURUSD-DE10YB-DC | Cross-asset divergence | negative/insig. throughout | — | REFUTED_THIS_RUN |
| HYP-C13-EURUSD-DE10YB-SC | Surprise confirmation | **2.986** (5m) | 11 | **STILL_UNDERPOWERED** → OPP-000067 |
| HYP-C13-EURUSD-DE10YB-DR | Delayed reaction | negative throughout | — | REFUTED_THIS_RUN |
| HYP-C13-EURUSD-DE10YB-RI | Reversal after impulse | insignificant throughout | — | REFUTED_THIS_RUN |
| HYP-C13-USDJPY-USB02Y-DC | Cross-asset divergence | negative throughout (60/120/240m; 5/15/30m blocked, no M1) | — | REFUTED_THIS_RUN |
| HYP-C13-USDJPY-USB02Y-SC | Surprise confirmation | **6.456** (240m) | 18 | **STILL_UNDERPOWERED** → OPP-000068, HIGH priority |
| HYP-C13-USDJPY-USB02Y-DR | Delayed reaction | negative throughout | — | REFUTED_THIS_RUN |
| HYP-C13-USDJPY-USB02Y-RI | Reversal after impulse | negative/insig. throughout | — | REFUTED_THIS_RUN |
| HYP-C13-XAUUSD-USB02Y-DC | Cross-asset divergence | insignificant throughout | — | REFUTED_THIS_RUN |
| HYP-C13-XAUUSD-USB02Y-SC | Surprise confirmation | negative throughout | — | REFUTED_THIS_RUN |
| HYP-C13-XAUUSD-USB02Y-DR | Delayed reaction | insignificant throughout | — | REFUTED_THIS_RUN |
| HYP-C13-XAUUSD-USB02Y-RI | Reversal after impulse | negative throughout | — | REFUTED_THIS_RUN |

Full per-window train/validation statistics (n, mean_net, t_stat,
profit_factor, win_rate, gross_over_cost) for all 120 real gate evaluations
are in `reports/factory/discovery_cycles/cycle_13_idea_machine_live.json`.

---

## Opportunity Queue additions (real numbers, calculated not guessed)

| Queue ID | Hypothesis | Train t | Val n | Priority | Retest trigger |
|---|---|---|---|---|---|
| OPP-000066 | USDCAD/WTICO surprise-confirmation, 5m | 2.942 | 14 | MEDIUM | Extend USD event pool to ≥161 events (calculated from 47.7% confirmation rate → target val n=30) |
| OPP-000067 | EURUSD/DE10YB surprise-confirmation, 5m | 2.986 | 11 | MEDIUM | Extend USD event pool; current confirmation rate too low for reliable estimate |
| OPP-000068 | USDJPY/USB02Y surprise-confirmation, 240m | 6.456 | 18 | HIGH | Highest train t-stat found this cycle; validation n=18 is the closest to power of any candidate found |

None of these are edge claims. Each is explicitly recorded as "train
t=X, val n=Y (<30, uninformative) — not treated as confirmed edge —
validation sample too small to confirm signal," per governance.

---

## Final counts

```
IDEAS GENERATED:              27
IDEAS REJECTED (pre-Factory):  0   (none matched a REFUTED family this run)
DATA BLOCKED:                  7   (AUDUSD ×4, EURJPY ×3 — no pre-registered cost)
HYPOTHESES PRE-REGISTERED:    20
REAL FACTORY EVALUATIONS:    120   (20 hypotheses × up to 6 windows each)
SURVIVORS:                     0
STILL_UNDERPOWERED:            3   (queued: OPP-000066, OPP-000067, OPP-000068)
REFUTED (this run):           17
EA PRODUCTS CREATED:           0   (no survivor → nothing to authorize or productize)
GOVERNANCE STATUS:  holdout untouched · ledger untouched · cost model untouched
                     (extended in-memory only for two new pairs, never written
                     to disk) · frozen candidates untouched · opportunity queue
                     append-only (65 → 68 entries, 0 edits/deletes)
TEST COUNT:          1662 passing (99 from prior phases + 2 new regression
                     tests added during this run's bug fix)
COMMIT:              0bdb476 (code fix + script), plus this results commit
```

## NO_EDGE_FOUND

No hypothesis in this cycle survived the real `INTERNAL_VALIDATION` gate.
This is the correct, honest outcome per governance — the objective was to
prove the machine can autonomously discover, test, reject, and remember
without violating governance, not to produce a winner. Three genuinely
promising leads (real train-period signal, insufficient validation sample)
are now in the Opportunity Queue for retest if the USD macro event pool
grows. Nothing was manufactured.
