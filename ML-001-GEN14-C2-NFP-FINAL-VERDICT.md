# ML-001 — GEN 14: FINAL SEALED-HOLDOUT EVALUATION

**Date**: 2026-08-20
**Candidates**: 4 frozen C2 NFP-surprise candidates (Cycle 6)
**Result**: **0/4 PASS — TERMINAL FAIL, all four**
**Holdout**: 4 datasets consumed (GBPUSD, USDCHF, USDJPY, XAUUSD). EURUSD's Gen 6 holdout untouched.

---

## 1. Verdict

```
CAND-C2-NFP-GBPUSD   FAIL   G1(n=29) FAIL, G5(Bonferroni) FAIL
CAND-C2-NFP-USDCHF   FAIL   G1(n=29) FAIL, G5(Bonferroni) FAIL
CAND-C2-NFP-USDJPY   FAIL   G1(n=29) FAIL, G5(Bonferroni) FAIL
CAND-C2-NFP-XAUUSD   FAIL   G1(n=31) PASS, G5(Bonferroni) FAIL

0/4 PASS. All four terminal. None may be retuned or resubmitted.
```

**This is not a "proven edge."** It is a terminal FAIL against pre-registered
gates, at the strictest Bonferroni bar this project has ever applied
(M=1,222). Nothing here should be read as vindicating the mechanism, and
nothing here should be read as fully refuting it either — both readings are
stated plainly below, without picking one to make the story cleaner.

---

## 2. What actually happened, stated without softening

**All 4 candidates were net-positive on the holdout, with the same sign as
the Cycle 6 dev-window finding.** t-statistics ranged 2.83–3.14 (GBPUSD,
USDCHF, USDJPY) and 2.92 (XAUUSD) — genuinely significant in isolation, well
above the ordinary t≥2.0 bar (G3 passed for all four), and profit factors
4.0–4.4 (G4 passed for all four). **The mechanism replicated out-of-sample.**
That is real evidence against pure dev-window overfitting.

It failed for two compounding reasons, both disclosed before the holdout was
ever touched, not discovered after:

1. **G1 (n≥30) failed for 3 of 4 candidates by exactly one trade** (n=29).
   The acquired economic calendar's coverage ends 2026-01-30; each symbol's
   holdout runs to 2026-08-20 — a 202-day tail with no acquired event data.
   This was written into `qualification/gen14_c2_nfp.py`'s docstring and
   printed in every result's `event_source_note` *before* the run, not
   patched in afterward to explain a disappointing number.

2. **G5 (Bonferroni, M=1,222) failed for all four**, and this is the real
   verdict-determining gate. `p < 0.05/1222 = 4.09e-05` requires roughly
   `|t| ≥ 4.1`. Holdout t-statistics of 2.8–3.1 do not come close, even
   though they would clear an *uncorrected* significance test easily. This
   is the multiple-testing correction doing exactly what it exists to do:
   after six discovery cycles and 1,222 parameter evaluations searching for
   *something* that clears a bar, a result has to be dramatically stronger
   than "significant" to survive the correction for how much was searched.

## 3. Was the calendar gap decisive? An honest accounting

If GBPUSD/USDCHF/USDJPY had cleared G1 (one more trade), they still would
have failed G5 by a wide margin (p≈1.7–4.6e-3 vs. the required 4.09e-5 — off
by roughly two orders of magnitude). **The calendar gap did not cost these
candidates their qualification.** The Bonferroni correction did, on its own,
independent of the sample-size shortfall. This is stated explicitly so the
202-day gap is not mistaken for "the reason it failed" — it is a real,
disclosed limitation, but not the load-bearing one.

---

## 4. Governance — verified directly, not asserted

| Check | Status |
|---|---|
| Two-layer authorization (EvidenceVault + HoldoutAuthorizationGate) | Both required, both enforced |
| Sealed dataset registration for GBPUSD/USDCHF/USDJPY/XAUUSD | Done in this run, `research_exposure=UNEXPOSED` (verified: only prior touch was a filename listing, no bytes read — checked by code inspection before sealing) |
| Seal cryptographic verification before read | PASS for all four (SHA-256 over exact file bytes) |
| Fixed M=1,222, set before any candidate's result was seen | Confirmed in every result record |
| One-shot consumption | All four datasets: `sealed → authorized → consumed`, one-way |
| Retune blocked after terminal result | Tested directly: `FrozenSpecViolation` raised for all four |
| Re-authorization blocked | Tested directly: `ValueError` raised for all four |
| Re-consumption blocked | Tested directly: `ValueError` raised for all four datasets |
| EURUSD's Gen 6 holdout unaffected | Confirmed: still `sealed`, not touched by this run |
| Failure memory withholds holdout statistics | Verified by test: exact `n`/`mean_net`/`t` values do not appear in the failure record |
| No EA generated | Verified: `artifacts/ea/` contains no new file for these candidates |

**Pipeline tested on synthetic data before touching the real holdout.** A
throwaway synthetic holdout and calendar were built, the full seal →
authorize → evaluate → consume → terminal-block chain was exercised end to
end, double-consumption and post-terminal retuning were both confirmed
blocked — all *before* `qualification/gen14_c2_nfp.py` was run against real
data. This followed the same discipline as the earlier factory-pipeline
E2E tests.

---

## 5. What is terminal, and what is not

**Terminal, permanently:**
- `CAND-C2-NFP-GBPUSD`, `CAND-C2-NFP-USDCHF`, `CAND-C2-NFP-USDJPY`,
  `CAND-C2-NFP-XAUUSD` — none may be retuned, re-parameterised, or
  resubmitted against these holdouts.
- The four holdout datasets themselves — `GBPUSD`, `USDCHF`, `USDJPY`,
  `XAUUSD` sealed holdout data — are consumed and cannot be re-evaluated.
- `FAMILY-C2-SURPRISE-REACTION-NFP-USD` — marked `REFUTED`,
  `refuted_by: FAIL-000037`.

**Not terminal:**
- The underlying *idea* — NFP-surprise-driven USD strength — is not proven
  false. It replicated in sign and direction out-of-sample; it simply
  could not clear a Bonferroni bar built from this project's entire search
  history. A structurally *different* candidate (different event, different
  horizon, different symbol set, or evaluated against freshly-sealed
  evidence rather than this consumed holdout) is not blocked by this
  result — reusing the mechanism idea without reusing the frozen specs or
  the consumed holdout is legitimate future research.
- EURUSD's original Gen 6 holdout — still sealed, still unconsumed, still
  available for a future EURUSD candidate.

---

## 6. Multiple-testing accounting

GEN 14 evaluation does not add to the discovery-search denominator (it
consumed already-frozen candidates, it did not search a parameter space) —
consistent with how `qualification/gen14_runner.py` was designed. No new
entry was added to `multiple_testing_ledger.json`; the four candidates were
already counted as survivors under `CYCLE-06-EVENT-DRIVEN-REAL-CALENDAR`.
The ledger's cumulative total (72 hypotheses / 1,222 parameter evaluations /
5 survivors — the 5th being B2_TURN_OF_MONTH, still un-evaluated at GEN 14)
is unchanged by this run.

---

## 7. Compliance

| Rule | Status |
|---|---|
| Holdout used exactly once per candidate | PASS |
| No retune, no spec change, no rescue attempt | PASS — none of the 4 candidates' parameters were touched after freezing |
| All GEN 14 gates run, Bonferroni at M=1,222 | PASS |
| Each candidate evaluated independently | PASS |
| Common mechanism evaluated together (sign-consistency reading) | PASS — reported, not used to override individual gate results |
| FAIL → terminal, failure memory recorded, no retry | PASS |
| No "proven edge" claim from a PASS | N/A — no PASS occurred |
| No EA generated | PASS |
| No live deployment | PASS |

---

## 8. What this means for the factory going forward

Six cycles, 1,222 parameter evaluations, one candidate set that replicated
out-of-sample in sign and direction — and still 0/4 at the qualification bar.
This is not a failure of the factory; it is the factory working as designed.
A pre-registered, ever-growing Bonferroni correction is *supposed* to be hard
to clear after this much search, precisely so that a result which does clear
it means something.

The sealed EURUSD holdout remains available. The XAUUSD B2_TURN_OF_MONTH
candidate from Cycle 4 remains parked, unauthorized, unconsumed. No candidate
has yet cleared GEN 14. `NO_EDGE_FOUND` remains the honest running summary of
this project — narrower now than before (one real mechanism found, tested,
and refuted at the highest bar), but still the accurate word for where things
stand.
