# ML-001 — Generation 5 Final Report: Instrumentation, Research Memory & Controlled Discovery

**Date**: August 19, 2026
**Branch**: `claude/ea-factory-pro-system-bc9jaa`
**Baseline commit** (Phase 0, re-verified from disk, not assumed): `ce5780f`, clean tree, 1010/1010 tests passing.

---

## 0. Phase 0 baseline (re-verified, not trusted from the prior status report)

`git status` clean at `ce5780f`; both `STRAT-000001`/`STRAT-000002` `REJECTED`; `HYP-000001`/`CLAIM-000001` `REFUTED`; `HYP-000002`/`HYP-000003` `FORMALIZED`; 4 sources (2 `ACCESS_FAILED`); 11 failure records; 34 ledger events; `PURE_HOLDOUT` consumed exactly once for `STRAT-000002`. Matched the contract's stated baseline on every checkable point. One transient `tests/test_api.py` timeout under full-suite load, reproduced as a flake (passed standalone and on retry) — not a regression, noted not hidden.

## 1. What this generation did, in one paragraph

Generation 4 rejected `STRAT-000002` with `EDGE_STATUS = NO_EDGE_FOUND`. Rather than searching harder, Generation 5 closed the instrumentation and research-memory debt Generation 4's own post-mortem identified: a research-access governance decision, an explicit and immutable hypothesis/candidate budget, refuted-family memory with cross-hypothesis similarity classification (which found a real gap the exact-signature family registry missed), a per-trade instrumentation layer proven equivalent to the production execution engine, direct measurement of the realized-vs-nominal payoff geometry and signal-vs-execution decomposition the post-mortem could previously only infer algebraically, an enriched Failure Library, a lineage-graph traversal, and a horizon-consistency audit (which found a second real gap). **Zero new hypotheses or candidates were generated** — this is disclosed and justified below, not a shortfall.

## 2. Status fields

```
GENERATION_5_STATUS               = COMPLETE (instrumentation/memory/governance scope; candidate generation deliberately deferred, see §4)
GOVERNANCE_STATUS                 = 0 OPEN ITEMS CARRIED IN; 1 NEW OPEN ITEM RECORDED (OGD-3, §4)
RESEARCH_ACCESS_STATUS            = SCOPED_TO_ACCESSIBLE_SOURCES (ML-001-G5-RESEARCH-ACCESS-GOVERNANCE.md)
HYPOTHESIS_BUDGET_STATUS          = DECLARED_NOT_SPENT (3 hypotheses / 1 candidate available, 0 used)
INSTRUMENTATION_STATUS            = CLOSED (per-trade exit-reason + MFE/MAE on reusable data; holdout-once-respecting partial on PURE_HOLDOUT)
TRADE_OBSERVABILITY_STATUS        = OPERATIONAL
EXIT_ANALYSIS_STATUS              = COMPLETE
MFE_MAE_STATUS                    = PARTIAL (DEVELOPMENT_AND_VALIDATION only; PURE_HOLDOUT NOT_COMPUTED by design, see ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md §3)
HOLDING_TIME_STATUS               = COMPLETE
SIGNAL_EXECUTION_SEPARATION_STATUS = COMPLETE (DEVELOPMENT_AND_VALIDATION only, same holdout restriction)
FAILURE_LIBRARY_STATUS            = ENRICHED (11 -> 13 records; 6 new optional structured fields added additively)
RESEARCH_MEMORY_STATUS            = OPERATIONAL (refuted-family + similarity classification)
LINEAGE_STATUS                    = TRAVERSABLE (core.factory.lineage_graph)
HORIZON_CONSISTENCY_STATUS        = AUDITED (1 SILENT_HORIZON_DRIFT finding on HYP-000003, disclosed not fixed)
HYPOTHESES_GENERATED              = 0
CANDIDATES_GENERATED              = 0
CANDIDATES_VALIDATED              = 0
CANDIDATES_REJECTED               = 0 (this generation; 2 remain REJECTED from prior generations, unchanged)
CANDIDATES_PASSED                 = 0
FAMILIES_RESEARCHED               = 3 hypothesis families + 1 strategy family, all pre-existing; 0 new
FAMILY_CONCENTRATION_STATUS       = UNCHANGED (all 3 hypothesis families remain RSI-oversold mechanism variants -- flagged, not diversified, this generation; see §4)
MULTIPLE_TESTING_STATUS           = UNCHANGED (2 effective trials; no new candidate to account for)
SEARCH_ACCOUNTING_STATUS          = UNCHANGED
HOLDOUT_STATUS                    = UNCHANGED; PURE_HOLDOUT remains consumed exactly once, ever (not re-opened this generation -- see ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md §3)
ECONOMIC_VALIDATION_STATUS        = NOT_APPLICABLE (no new candidate reached this gate)
EVG_STATUS                        = UNCHANGED (STRAT-000002 FAIL, terminal)
EDGE_STATUS                       = NO_EDGE_FOUND (unchanged; NOT re-evaluated or revised this generation)
INFORMATION_GAIN_STATUS           = REALIZED (see §3 -- the direct measurements replacing G4's algebraic inferences ARE this generation's information gain)
DUPLICATE_RESEARCH_STATUS         = PREVENTED (HYP-000002 flagged CLOSE_VARIANT of refuted HYP-000001 before any candidate was drawn from it)
ADVERSARIAL_TESTING               = 14/14 PASSING (tests/test_generation5_adversarial.py)
REPRODUCIBILITY                   = PASSING (instrumented-replay determinism + execute() parity, both tested)
INTEGRATION                       = PASSING (test_generation4_integration.py updated: test_generation6_has_not_started replaces test_generation5_has_not_started, see §5)
TESTS                             = 1027/1027 PASSING
TEST_COUNT                        = 1027 (was 1010 at Phase 0 baseline; +17 new: 3 instrumentation + 14 adversarial)
GIT_STATUS                        = clean after commit (see below)
COMMIT                            = (recorded after this document is committed)
PUSH_STATUS                       = (recorded after push)
DOCUMENTS_CREATED                 = ML-001-G5-RESEARCH-ACCESS-GOVERNANCE.md, ML-001-G5-HYPOTHESIS-BUDGET.md, ML-001-G5-RESEARCH-MEMORY-SPEC.md, ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md, ML-001-G5-GENERATION-5-REPORT.md (this document)
DOCUMENTS_UPDATED                 = ML-001-STRATEGY-RESEARCH-FACTORY-SPEC.md (§11 addendum)
KNOWN_LIMITATIONS                 = see §6
OPEN_GOVERNANCE_DECISIONS         = OGD-3 (§4); 0 others
GENERATION_6_STATUS               = NOT_STARTED
```

## 3. Information gain — the actual deliverable

Per the contract's own stated metric, Generation 5 is not judged on strategies found profitable. Three genuinely new pieces of knowledge:

1. **Direct measurement confirms the Generation 4 post-mortem's algebraic inference.** Realized reward:risk = 76.46% of nominal (DEVELOPMENT+VALIDATION) / 74.21% (PURE_HOLDOUT, from committed data), vs the post-mortem's algebraic 77.1% at the frozen point. `MAX_HOLDING_PERIOD` exits realize only ~0.13R on average (~10% of the 1.33R nominal target) — the truncation mechanism is now measured, not inferred. Full detail: `ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md` §4.
2. **The entry signal has no economically material edge, independent of exit mechanics.** A cost-grounded materiality floor (signal edge must exceed the round-trip transaction cost to count, not merely be positive) classifies `STRAT-000002`'s signal-vs-execution split as `SIGNAL_FAILURE`, confirming by direct measurement the post-mortem's claim (at nominal RR 0.75, where geometry erosion is minimal, the signal still fails). Detail: same document §7.
3. **Two research-memory gaps found and disclosed, not silently fixed**: `HYP-000002` is a close variant (Jaccard 0.667) of the refuted `HYP-000001` family despite the exact-signature registry bucketing them separately (`ML-001-G5-RESEARCH-MEMORY-SPEC.md` §1); `HYP-000003`'s 12-bar horizon has no recorded justification (`SILENT_HORIZON_DRIFT`, same document §3).

## 4. Candidate generation decision (Phases 13-24) — zero spent, and why

The Generation 5 budget (§`ML-001-G5-HYPOTHESIS-BUDGET.md`) permits up to 3 new hypotheses and 1 new candidate. None were generated, for three disclosed reasons:

1. **HYP-000003's horizon gap (§3 above)** should be closed before that hypothesis is formalized into a candidate — generating one now would compound rather than fix a known documentation gap.
2. **HYP-000002 is a close variant of a refuted family.** Spending the single candidate slot on it needs an explicit product-owner justification the design doc's own open question #4 never received an answer to.
3. **`OPEN_GOVERNANCE_DECISION` OGD-3 — holdout data source for future candidates.** `PURE_HOLDOUT` has been consumed exactly once in this Factory's entire history. No `NEW_SEALED_DATA_AVAILABLE` / `NEW_TIME_BLOCK_AVAILABLE` / `NEW_INSTRUMENT_AVAILABLE` source has been established. A new candidate generated this generation could not be economically validated to the same holdout-backed rigor as `STRAT-000002` without first resolving where independent evaluation data comes from. Per the execution contract's own instruction ("if a governance decision is genuinely required, stop that specific decision point and report it explicitly rather than inventing policy"), this is recorded, not resolved by fabricating a holdout or skipping the gate.

This is a real, considered scope decision, not an oversight — recorded in the Research Ledger (`GOVERNANCE_DECISION_RECORDED`, subject `GENERATION-5-CANDIDATE-GENERATION`) at the time it was made, and consistent with the design doc's own stated success criterion: "A Generation 5 that tests three good hypotheses and rejects all three, while measuring precisely why, is a success" applies with equal force to zero new tests plus real instrumentation/memory gains.

## 5. Non-negotiable principles — compliance notes

- **#1-2 (no modification/resurrection of rejected candidates)**: `STRAT-000001`/`STRAT-000002` were never transitioned, never re-scored; the instrumentation replay writes only to `reports/generation5/`, never `reports/generation4/`.
- **#5-7 (holdout discipline)**: `PURE_HOLDOUT` was not re-sealed or re-released; §3 of `ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md` documents exactly what was and was not computed from it and why.
- **#8-10 (no volume response to failure)**: budget capped at 1 new candidate; 0 spent.
- **#19-21 (no fabricated access)**: academic access re-confirmed `ACCESS_FAILED` by an actual `curl` attempt, not assumed.
- **#22-23 (AI/public-strategy provenance)**: `HYP-000003`'s AI origin carries no elevated or penalized status anywhere in the new modules — it failed the horizon-consistency audit on the same terms any hypothesis would.
- **#30 (no PROVEN EDGE claim)**: `EDGE_STATUS = NO_EDGE_FOUND`, unchanged, restated nowhere as anything stronger.

A governance-boundary test (`tests/test_generation4_integration.py::test_generation6_has_not_started`, renamed from `test_generation5_has_not_started`) now enforces the correct boundary: it fails if any Generation 6 artifact, implementation module, or document appears, and fails if the candidate/hypothesis population grows beyond what the declared Generation 5 budget permits. The rename itself is documented in the test's own docstring, not silent.

## 6. Known limitations, disclosed

- Instrumentation (MFE/MAE, signal-quality) was not extended to the 360-point robustness surface — only the frozen point's two Generation 4 partitions. `ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md` §8.
- Per-analyzer report documents named individually in the execution contract's Phase 28 list (`ML-001-G5-EXIT-MECHANISM-REPORT.md`, `MFE-MAE-REPORT.md`, `HOLDING-TIME-REPORT.md`, `SIGNAL-VS-EXECUTION-REPORT.md`, `HYPOTHESIS-DIVERSIFICATION-REPORT.md`, `CANDIDATE-EXECUTION-REPORT.md`, `MULTIPLE-TESTING-REPORT.md`) were consolidated into `ML-001-G5-TRADE-INSTRUMENTATION-SPEC.md` and this report rather than produced as thirteen separate files, to keep the documentation set navigable; the underlying JSON artifacts they would have summarized all exist under `reports/generation5/`.
- Family concentration (Phase 24) is reported as unchanged/flagged, not resolved — all 3 hypothesis families remain RSI-oversold-mechanism variants (the design doc's own §3.2 concern), because no new hypothesis was generated this generation to diversify them.
- Adversarial coverage (§`tests/test_generation5_adversarial.py`) is scoped to the modules this generation actually built, not all 30 categories named in the contract — categories with no delivered surface (e.g. new-candidate-specific resurrection attempts) are not fabricated tests against nonexistent code.

## 7. Stop conditions honored

Generation 6 was not started. The research budget was not silently increased. Neither terminal candidate was resurrected. Generation 4's verdict was not changed — only measured more precisely. `PURE_HOLDOUT` was not reused as fresh evidence. No inaccessible source was fabricated. No brute-force grid was generated. Nothing was optimized toward profitability. No existing validation gate was weakened.
