# ML-001 — Generation 5 Design

**Status**: **DESIGN ONLY — GENERATION 5 IS NOT STARTED.** No Generation 5 code, candidate, hypothesis, or evaluation exists. This document specifies what Generation 5 *should* be and why, for review before any execution contract is issued.
**Date**: August 19, 2026
**Inputs**: `ML-001-GENERATION-5-GOVERNANCE-CLOSURE.md` (0 open governance items), `ML-001-GENERATION-4-POST-MORTEM.md` (why STRAT-000002 failed), the Failure Library (11 records), and Generations 1–3 infrastructure.

---

## 1. Where the Factory actually stands

Two candidates tested, two terminally rejected, **zero** edges found:

| | Failure mode | Character |
|---|---|---|
| `STRAT-000001` (RF-R2-001, ML) | `NO_PREDICTIVE_SIGNAL` | IC ≈ 0.015–0.030, ~51% directional accuracy — nothing there |
| `STRAT-000002` (RSI rule) | `NO_SIGNAL` + `PARAMETER_FRAGILITY` | reliably negative across all 360 parameter points |

The machinery is in good shape: governance, provenance, lineage, holdout protection, accounting, novelty/family clustering, budgets, and kill switch are all built and tested (998 tests). What the Factory has *not* produced is a single positive result — and after only **2 trials**, that is the expected state of affairs, not a crisis. G4's own multiple-testing artifact is explicit that a 2-trial correction is "NEARLY_UNINFORMATIVE".

**The honest read**: the Factory has proven it can *reject* rigorously. It has not yet been given enough genuinely distinct hypotheses to have a fair chance of finding anything, and its two attempts were both single-instrument, single-timeframe, short-horizon, directional-price hypotheses — a narrow and unpromising corner of the space.

## 2. Design principle: increase *information per test*, not tests per hour

Generation 5's temptation is obvious and wrong: scale up candidate generation to hundreds of variants. The Factory's own governance says why that fails — more search increases multiple-testing burden, selection bias, and false-discovery risk, and the correction must grow with it. Generating 500 RSI variants would produce 500 members of one family and a multiplicity penalty that swallows any apparent winner.

**Generation 5 should therefore prioritise hypothesis *diversity and quality* over candidate *volume*, and instrument the pipeline so each test yields more diagnostic information than the last.**

## 3. Proposed scope

### 3.1 Instrumentation debt (**must precede new research**)

The post-mortem could only *infer* its central mechanical finding because G4 did not persist enough. Before any new candidate is evaluated:

1. **Per-parameter-point exit-reason distributions** (target / stop / timeout / reversal) and per-trade `avg_win` / `avg_loss`, so realized-vs-nominal payoff geometry is **measured**, not derived from aggregates.
2. **Per-trade records retained for every robustness point**, not only the frozen point — the 360-point surface currently yields summary statistics only.
3. **Signal-quality metrics computed independently of the trading rule** (IC / conditional forward-return by signal state), so "the entry has no edge" and "the exits destroy the edge" are separable *by measurement* at evaluation time rather than by post-hoc algebra.

Rationale: item 3 would have answered in G4 what §3 of the post-mortem had to reconstruct afterwards, and it is the single highest-value addition to the evaluation pipeline.

### 3.2 Hypothesis portfolio — breadth over depth

Two already-formalized hypotheses are sitting unused and are *not* refuted:

- `HYP-000002` (`CROSS_SOURCE_SYNTHESIS`) — RSI reversion at a **24-bar** horizon, deliberately chosen as untested territory.
- `HYP-000003` (`AI_DERIVED`) — high-volatility-regime RSI **continuation** (expects *negative* forward returns after oversold signals): mechanically distinct from both prior candidates, and a genuine test of whether the Factory can evaluate a contrarian-to-lore hypothesis on equal terms.

**Caution — family accounting.** `HYP-000002` shares the RSI mechanism with the refuted `HYP-000001`. The Failure Library already records that family's failure; `HYP-000002`'s novelty score must be recomputed *with* that failure count, and its priority must reflect that it is a horizon variant of a refuted idea, not fresh territory. `HYP-000003` is the more informative test precisely because its mechanism differs.

**New hypotheses should widen the space along axes never yet tested**: non-directional targets (volatility, range), cross-instrument relationships, longer horizons, and regime-conditional structures. The Market Universe ontology (7 asset classes, 20 instruments) and Feature Catalog (13 families) already represent this space; only EURUSD/GBPUSD H1 and 5 features are actually implemented, so **data and feature acquisition is the real constraint**, not architecture.

### 3.3 Known blocker to be resolved deliberately

Real external research access remains **network-policy-blocked** for academic hosts (arxiv, SSRN) — recorded honestly as `ACCESS_FAILED` sources, never worked around. Generation 5 should either (a) obtain an authorized data/research path, or (b) explicitly scope itself to internally-authored and already-accessible sources. Proceeding without deciding would quietly bias the entire source portfolio toward whatever happens to be reachable — a concentration risk the diversity metrics are designed to detect and would flag.

### 3.4 What Generation 5 must **not** do

- Must not re-open, re-tune, or re-test either terminally rejected candidate.
- Must not re-consume `PURE_HOLDOUT` for a rejected candidate version; a new candidate version means a new holdout access, and only after every reusable gate.
- Must not generate candidate variants at volume to manufacture the appearance of a search.
- Must not upgrade `SELECTION_BIAS_STATUS` on the basis of trial count alone.
- Must not treat `HYP-000003`'s AI origin as either a credential or a disqualification — it faces exactly the same gates.

## 4. Success criteria — deliberately not "find an edge"

Generation 5 should be judged on **research quality**, since edge discovery is not schedulable:

1. Instrumentation debt (§3.1) closed, with the realized-vs-nominal geometry gap measured directly on a live evaluation.
2. At least one hypothesis tested whose **mechanism family is genuinely new** to the Factory (not an RSI/momentum variant).
3. Multiple-testing accounting remains honest as trial count grows; `SELECTION_BIAS_STATUS` reflects real power, not aspiration.
4. Every outcome — including and especially further rejections — extracted into the Failure Library with transferable findings.
5. Governance open items remain at 0, or any new one is recorded rather than silently resolved.

**A Generation 5 that tests three good hypotheses and rejects all three, while measuring precisely why, is a success.** A Generation 5 that produces a "passing" candidate out of a 500-variant sweep is a failure regardless of its backtest.

## 5. Open questions for the product owner

1. **Data/research access** — resolve §3.3, or scope Generation 5 to available sources?
2. **Instrumentation first?** — this design says yes (§3.1 before §3.2). Confirm, or accept inferred diagnostics to move faster?
3. **Hypothesis budget** — how many candidates may Generation 5 evaluate? The `ResearchBudget` mechanism requires an explicit number; it is a governance choice, not an engineering one.
4. **`HYP-000002` admissibility** — should a horizon variant of a refuted family be tested at all, or does the family's failure record argue for spending the budget on genuinely new mechanisms?

---

**`GENERATION_5_STATUS = NOT_STARTED`.** This document is a proposal awaiting review; no execution contract has been issued and no Generation 5 work has begun.
