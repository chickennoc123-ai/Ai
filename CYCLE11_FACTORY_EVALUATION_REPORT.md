# Cycle 11 Factory Evaluation Report — TWICE CORRECTED

**Date**: 2026-08-21
**Cycle**: GEN 7 CYCLE 11 — Idea Machine Integration
**Status**: COMPLETE — 3 hypotheses evaluated, 0 survivors, 2 implementation bugs found and fixed in this session's own glue code

---

## Errata (read first — two separate bugs, both in this session's code, neither in the Factory)

### Bug 1 (found first): `gross_over_cost` hardcoded to 0

`gate()` checks `gross_over_cost = gross_mean/cost` before `mean_net`/`t_stat`. The
first version of `discovery/cycle11_idea_machine.py` called
`stats(train_nets, 0.0, cost)`, hardcoding `gross_mean=0.0` instead of
computing it (`gm = mean(|net|); stats(train_nets, gm+cost, cost)`, Cycle
8's own pattern). This made every window `COST_DOMINATED` regardless of
actual performance. Fixed by copying Cycle 8's `gm` computation.

### Bug 2 (found second, more serious): `SURPRISE_FX_DIR` sign-flipped

While re-verifying the corrected numbers against this project's already-frozen
`CAND-SC-GBPUSD-US10Y-5M` candidate (see below), the direction convention was
cross-checked against `discovery/cycle8_intraday.py`'s own validated
`SURPRISE_FX_DIR` dict:

```
Cycle 8 (validated):  {"EURUSD": -1, "GBPUSD": -1, "XAUUSD": -1, "USDJPY": +1, "USDCHF": +1}
Cycle 11 (this bug):  {"EURUSD": +1, "GBPUSD": +1, "XAUUSD": -1, "USDJPY": -1, "USDCHF": -1}
```

Four of five symbols were sign-flipped. The economics of Cycle 8's
convention are simple and checkable: EURUSD is USD-per-EUR, so a USD-bullish
surprise (positive NFP surprise) should push EURUSD **down** (`-1`); USDJPY
is JPY-per-USD, so the same surprise should push USDJPY **up** (`+1`).
Cycle 11's dict had this backward for EURUSD, GBPUSD, USDJPY, and USDCHF —
**every trade direction in the first two versions of this report was
inverted** for HYP-IM-0001 and HYP-IM-0004 (HYP-IM-0003 was unaffected: its
direction logic is a separate hardcoded `-sign(surprise)` expression that,
by cross-check, already matched the correct convention). Fixed by copying
Cycle 8's dict verbatim.

**Both bugs are now fixed in `discovery/cycle11_idea_machine.py` and
`discovery/cycle11_export_json.py`. Both scripts were re-run. This report is
rewritten from the twice-corrected output, not patched.**

---

## What actually changed

| Hypothesis | v1 (both bugs) | v2 (bug 1 fixed) | v3 (both bugs fixed, current) |
|---|---|---|---|
| HYP-IM-0001 | 6/6 COST_DOMINATED | 6/6 no train edge (TRAIN_NEGATIVE/INSIG) | 1/6 (5m) clears train t=2.44, val t=2.12, still VALIDATION_UNDERPOWERED (n=14); other 5 windows insignificant/negative |
| HYP-IM-0003 | 5/5 COST_DOMINATED | 5/5 no train edge | **unchanged** — this hypothesis's direction logic was never affected by bug 2 |
| HYP-IM-0004 | 12/12 COST_DOMINATED | mixed underpowered/insignificant | 12/12 windows now show train t in [1.64, 4.83] (mostly ≥2), but validation t is inconsistent: one negative (-0.55), most near 0, one at 2.24; n=12-15 throughout |

**Top-line result is unchanged across all three versions: 0 survivors.**
What changed is the diagnostic picture, materially for two of the three hypotheses.

---

## Reading the corrected numbers honestly (this section matters more than the tables)

**HYP-IM-0004's "12/12 windows clear train significance" is weaker evidence
than it looks.** The 12 combinations (3 delays × 4 windows) are drawn from
the same 128 NFP events with overlapping definitions (a 30m window and a
60m window share most of their trade set; delay=60s and delay=120s filter
overlapping event subsets) — they are not 12 independent tests. Seeing
correlated train t-stats cluster above 2.0 is more consistent with **one**
underlying pattern (real or spurious) expressed 12 correlated ways than
with 12 independent confirmations. Meanwhile validation t-stats across the
same 12 cells range from -0.55 to +2.24 with no consistent sign or
magnitude — which is exactly what you'd expect from small-sample noise
(n=12-15) dominating whatever the train-side pattern is, in either
direction (real-but-noisy or spurious-and-regressing-to-zero look similar
at this sample size).

**Correct conclusion: still genuinely ambiguous, not a hidden survivor.**
This is not strong enough evidence to claim a real edge, and not weak
enough to dismiss outright. It is exactly a "collect more data before
concluding anything" case — which is precisely what `VALIDATION_UNDERPOWERED`
already says, honestly, without embellishment.

**HYP-IM-0001's signal is even weaker: 1 of 6 (uncorrelated-window) draws
clears the bar.** With 6 window choices tested per hypothesis, seeing one
exceed a t≈2 threshold by chance is not a low-probability event under a
null of no effect. The 5m window's train t=2.44/val t=2.12 is *interesting*
enough to note, not strong enough to act on.

**Important cross-reference**: HYP-IM-0001 (GBPUSD, US10Y driver, 5-minute
window, surprise-confirmation mechanism) is the same *nominal* combination
as this project's already-frozen `CAND-SC-GBPUSD-US10Y-5M`
(`reports/factory/candidate_spec_registry.json`), which was measured via
the Factory's canonical `evaluate_pairing()` at **train t=+2.92 (n=149),
val t=-0.10 (n=23)** — see `ea_products/sc_surprise_confirmation/README.md`.
This Cycle 11 evaluation used a **different, less rigorous harness**:
events were filtered to NFP only (the frozen candidate's evaluation used
NFP+CPI, per `EVENT_TYPES`), and the train/validation split was computed
by index-position on the *filtered trade list* rather than by chronological
event timestamp (`evaluate_pairing`'s actual method). The different n (54
train / 14 val here vs. 149/23 there) and different t-stats confirm these
are not the same computation. **This Cycle 11 result does not replicate,
confirm, or add evidence to the frozen candidate — it is a separate,
methodologically weaker probe of an overlapping question, and should not
be cited as corroboration.** The frozen candidate's own status
(`STILL_UNDERPOWERED`) already captures everything rigorously known about
this exact combination; nothing here changes it.

---

## Execution Summary

| Hypothesis | Idea Score | Symbol | Mechanism | Windows Tested | Survivors |
|---|---|---|---|---|---|
| HYP-IM-0001 | 74.0 | GBPUSD/US10Y | Macro surprise confirmation | 6 | 0 |
| HYP-IM-0003 | 64.0 | EURUSD | Session regime bias | 5 | 0 |
| HYP-IM-0004 | 64.0 | EURUSD | Post-event entry delay | 12 | 0 |

**Total parameter combinations tested**: 23. **Discovery survivors**: 0.

---

## Per-hypothesis gate tables (corrected)

### HYP-IM-0001 — GBPUSD/US10Y

| Window | Train n | Train t | Val n | Val t | Verdict |
|---|---|---|---|---|---|
| 5m | 54 | 2.44 | 14 | 2.12 | VALIDATION_UNDERPOWERED |
| 15m | 54 | 1.16 | 14 | 0.20 | TRAIN_INSIGNIFICANT |
| 30m | 54 | 0.64 | 14 | 0.11 | TRAIN_INSIGNIFICANT |
| 60m | 54 | 0.67 | 14 | -0.43 | TRAIN_INSIGNIFICANT |
| 120m | 54 | -0.22 | 14 | 0.34 | TRAIN_NEGATIVE |
| 240m | 54 | -0.39 | 14 | 0.73 | TRAIN_NEGATIVE |

### HYP-IM-0003 — EURUSD session regime (unaffected by either bug)

| Window | Train n | Train t | Val n | Val t | Verdict |
|---|---|---|---|---|---|
| 1m | 161 | numerically unstable | 41 | numerically unstable | TRAIN_NEGATIVE |
| 5m | 161 | 0.46 | 41 | -0.79 | TRAIN_INSIGNIFICANT |
| 15m | 161 | 0.35 | 41 | -0.91 | TRAIN_INSIGNIFICANT |
| 30m | 161 | 0.04 | 41 | 0.41 | TRAIN_INSIGNIFICANT |
| 60m | 161 | -0.10 | 41 | -0.02 | TRAIN_NEGATIVE |

A large, well-powered null (161 train events, t≈0 throughout). Clean
falsification of the "US-data-day directional bias" hypothesis as specified.

### HYP-IM-0004 — EURUSD post-event delay

| Delay | Window | Train n | Train t | Val n | Val t | Verdict |
|---|---|---|---|---|---|---|
| 0s | 15m | 48 | 3.88 | 12 | -0.55 | VALIDATION_UNDERPOWERED |
| 0s | 30m | 48 | 2.16 | 12 | 1.09 | VALIDATION_UNDERPOWERED |
| 0s | 60m | 48 | 2.45 | 12 | 0.34 | VALIDATION_UNDERPOWERED |
| 0s | 120m | 48 | 1.64 | 12 | 1.46 | TRAIN_INSIGNIFICANT |
| 60s | 15m | 59 | 4.24 | 15 | 0.01 | VALIDATION_UNDERPOWERED |
| 60s | 30m | 59 | 2.33 | 15 | 0.70 | VALIDATION_UNDERPOWERED |
| 60s | 60m | 59 | 2.69 | 15 | 0.24 | VALIDATION_UNDERPOWERED |
| 60s | 120m | 59 | 2.34 | 15 | 0.95 | VALIDATION_UNDERPOWERED |
| 120s | 15m | 53 | 4.83 | 14 | 2.24 | VALIDATION_UNDERPOWERED |
| 120s | 30m | 53 | 2.29 | 14 | 1.73 | VALIDATION_UNDERPOWERED |
| 120s | 60m | 53 | 2.94 | 14 | 0.43 | VALIDATION_UNDERPOWERED |
| 120s | 120m | 53 | 2.19 | 14 | 1.14 | VALIDATION_UNDERPOWERED |

---

## Overall Findings

| Hypothesis | Real failure mode | Actionable? |
|---|---|---|
| HYP-IM-0001 | 1 of 6 correlated windows clears train+val significance; not strong evidence at 6-window multiplicity; not a replication of the frozen SC candidate it nominally overlaps with | Weak — no action beyond noting the overlap with an already-known, already-frozen, already-`STILL_UNDERPOWERED` family |
| HYP-IM-0003 | Well-powered null (t≈0, n=161) | No — clean falsification |
| HYP-IM-0004 | Train-side pattern too consistent across 12 correlated cells to be pure noise, but validation (n=12-15, inconsistent sign) neither confirms nor refutes it | Yes, cautiously — the single most data-blocked-but-plausible lead this Idea Machine effort has produced; do not deploy on this evidence, do consider it if the NFP event pool can be extended |

### Factory Gate Sequence

```
Stage 1: Internal Validation Gate (train + val on dev data)
  ├─ HYP-IM-0001: mostly TRAIN_INSIGNIFICANT/NEGATIVE; best window VALIDATION_UNDERPOWERED
  ├─ HYP-IM-0003: TRAIN_NEGATIVE/TRAIN_INSIGNIFICANT (well-powered null)
  └─ HYP-IM-0004: VALIDATION_UNDERPOWERED throughout (real-looking train pattern, unconfirmed by validation)
        └─ None advance to GEN12
Stage 2: GEN12 Adversarial Gate — not reached
Stage 3: GEN14 Sealed Holdout Gate — not reached
```

---

## Lessons Learned

1. **A sign-convention bug can silently survive a first review because it produces plausible-looking negative results.** "No edge found" reads as a mundane, unremarkable outcome — exactly the kind of result that doesn't invite scrutiny. It took cross-referencing this session's own numbers against an unrelated already-frozen candidate (done for a different reason — checking for redundancy) to surface the inversion. **Lesson for process, not just this cycle: a negative result should be cross-checked against a known-good reference computation before being trusted, not just a positive one.**
2. **Multiple-window/multiple-delay sweeps on overlapping event pools produce correlated, not independent, evidence.** HYP-IM-0004's "12/12 windows clear train significance" looks compelling until you account for the fact that 12 overlapping filters on 128 events are not 12 independent experiments. This is a general caution for how `idea_machine/economic_feedback.py` should weight "consistency across many parameter cells" going forward — it should not be treated as 12x the evidence of one cell.
3. **Idea Machine viability score still did not predict which hypothesis would be most interesting.** All three scored similarly (74.0, 64.0, 64.0); the corrected result differentiates them sharply (HYP-IM-0004 > HYP-IM-0001 > HYP-IM-0003 in "worth another look" terms) for reasons the original scoring never captured (confirmation-rate stability, event-pool overlap structure).
4. **Cross-referencing new probes against the project's own frozen candidates is a cheap, valuable sanity check** — it caught this bug, and it also prevented the report from overclaiming the GBPUSD/US10Y result as a fresh discovery when it nominally overlaps ground already covered (and already honestly labeled `STILL_UNDERPOWERED`) by Cycle 8/9.

---

## Governance Audit

- Dev bars/events: loaded via the same holdout-firewalled loaders used throughout this project ✓
- Holdout: never accessed ✓
- Multiple-testing ledger: not modified (these are diagnostic dry-runs, not registered candidates) ✓
- Cost model: unchanged, used as-is ✓
- Frozen candidate spec registry: not modified; HYP-IM-0001's overlap with `CAND-SC-GBPUSD-US10Y-5M` is documented as non-corroborating, not merged into or treated as new evidence for that frozen record ✓
- Both corrections disclosed openly, with full before/after numbers, not silently amended ✓

---

## Files

```
discovery/cycle11_idea_machine.py       ← evaluation module (both bugs fixed)
discovery/cycle11_export_json.py        ← JSON export (both bugs fixed)
reports/factory/discovery_cycles/cycle_11_idea_machine.json  ← twice-corrected results
CYCLE11_FACTORY_EVALUATION_REPORT.md    ← this report (rewritten twice, not patched)
```

---

**Status**: REJECTED (0 survivors), twice corrected and re-verified
**Next**: `idea_machine/economic_feedback.py` now learns from the corrected numbers — see that module's lessons for how this cycle informs future idea ranking
