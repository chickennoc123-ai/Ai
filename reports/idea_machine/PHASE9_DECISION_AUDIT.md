# Phase 9: Decision Audit — Self-Critique Against the Spec's Own Checklist

Answered honestly against the actual Cycle 14 run, not against the design
intent. Where a real problem was found, it was fixed before this document
was written, and the fix is described, not hidden.

---

**1. Có phải engine đang optimize survivor thay vì information?**

No — verified structurally, not just by intent. `InformationGainScorer`
never reads a performance number (`ResearchCandidate` has no such field,
mirroring `IdeaSpec`'s own ban). In Cycle 14, the EXPLORE candidate
(`USDJPY/UK100`) was accepted with `information_gain=8.0` and
`data_feasibility=10.0` *before* any real evaluation ran — its score came
entirely from "this driver has never been touched," not from any expectation
of profit. It then went on to score `TRAIN_NEGATIVE` in the real Factory.
That is the intended behavior: the decision to test it was sound research
regardless of the outcome.

**2. Có phải exploration thực sự tồn tại?**

Yes, and it was the site of the most serious bug found this session (Bug 2,
see `PHASE9_RESEARCH_SPACE_REPORT.md` §3): the first live run allocated an
EXPLORE slot but the family cap silently zeroed out every EXPLORE
candidate's acceptance. Fixed and re-verified: the corrected run accepted
1 EXPLOIT + 1 EXPLORE + 1 RECOMBINE, and all three were sent to the real
Factory. Exploration is real because it survived being tested against real
governance interactions, not because a unit test asserted a percentage.

**3. Có phải exploration chỉ là parameter mutation?**

No. `ExplorationEngine.swap_driver()` only proposes candidates whose driver
cell is `UNEXPLORED` (`test_explore_prioritises_mechanism_novelty_over_parameter_change`).
The five EXPLORE candidates in Cycle 14 (JP225/UK100/AU200/US2000/NATGAS)
were five genuinely different cross-asset relationships, each with its own
stated economic channel (funding-currency flow, global risk sentiment,
domestic-growth proxy, import-cost/terms-of-trade) — not five windows on one
already-tested pairing. `NoveltyBudgetTracker` independently confirms this:
`test_genuine_new_family_candidates_are_not_saturated` shows zero
`LEVEL_1_PARAMETER` tags across that batch.

**4. Có phải một family đang chiếm quá nhiều budget?**

This was checked and enforced (`maximum_single_family_share = 0.40`), but
the enforcement itself was the exact site of Bug 2 — the cap's grouping key
was too coarse and (in the wrong direction) took budget *away* from a
legitimate family rather than letting one family dominate. Fixed by
correcting the family key to `(mechanism, instrument, driver)`. Re-verified
with `test_single_family_cannot_consume_entire_budget`, which floods the
allocator with six same-triple candidates and confirms the cap drops the
excess. The same coarse-rollup mistake was found a second time (Bug 3) in
`propose_closures()`, which had proposed closing all of `instruments.EURUSD`
from a mixed evidence trail (one REFUTED hypothesis next to unrelated
STILL_UNDERPOWERED evidence). Fixed by restricting closure proposals to the
`combinations` dimension, where a cell means one coherent family, never a
rollup. Both fixes point at the same underlying lesson: a per-dimension
rollup is fine for a heatmap, never for a governance-relevant decision.

**5. Có decision nào không giải thích được?**

No — every `CandidateDecision`, accepted or rejected, produces a
`DecisionRecord` with a non-empty `reason` (structurally required:
`DecisionRecord.__post_init__` raises `ValueError` on an empty reason). All
7 candidates in Cycle 14, including the 4 rejected EXPLORE drivers, have a
recorded, retrievable explanation via `idea_machine.cli explain <id>` —
verified live, not just in a unit test (see report §... the AU200/US2000/NATGAS
rejections are in `decision_records.json` alongside the 3 accepted ones).

**6. Có decision nào không có evidence?**

No — `DecisionRecord.evidence` is populated from `candidate.rationale` in
every case, and the `alternatives_considered` field lists up to 5 sibling
candidates from the same mode's ranked pool, so a decision can be checked
against what it was ranked above.

**7. Có possibility p-hacking không?**

Checked against the concrete list in spec item 22:
- Split changed after seeing results? No — the 80/20 train/validation split
  is computed before any mechanism function runs, identically to Cycle 8/13.
- Threshold changed after seeing results? No — `gate()` is imported
  unchanged from `discovery/cycle8_intraday.py`.
- Favorable window selected after evaluation? No — each candidate proposes
  exactly ONE window (the EXPLOIT candidate's 300m was chosen for a stated
  reason — extending Cycle 13's finding — before evaluation, not selected
  from a post-hoc sweep of many).
- Cost changed after evaluation? No — `cost_registered()` is checked before
  a candidate is even sent to the Factory; AUDUSD/EURJPY-style blocks are
  reported, not routed around.
- Holdout consumed to rescue a result? Structurally impossible — no
  holdout-reading code path exists in this package.

**8. Có governance boundary nào bị bypass không?**

No new bypass was introduced. One was *found* — the six broad
`except Exception` handlers in `cycle_runner.py`/`full_cycle_runner.py`
(pre-existing, from before this session's Phase 9 audit discovered the
System-C governance framework) could structurally have swallowed a
`GovernanceViolation`, even though none of those specific code paths
currently raises one. Fixed by narrowing to concrete exception types before
this document was written, not reported as a known gap.

**9. Có branch nào bị coi là novel chỉ vì vocabulary khác?**

No — the RECOMBINE candidate (`SC_AND_DC_COMBINED_CONFIRMATION`) is
explicitly tagged `novelty_tag="RECOMBINATION"`, never `"NEW"`, both in the
dataclass validation (`ResearchCandidate.__post_init__`) and in the
recombination engine's own docstring, which states the rule directly: "novelty
is a mechanism-level question, not counted as NEW merely for having two
components." `test_recombine_candidates_are_tagged_recombination_not_new`
enforces this structurally.

**10. Có dữ liệu nào bị giả định là tồn tại nhưng thực tế không tồn tại?**

No confirmed instance. Every new driver folder used in this cycle
(JP225_USD, UK100_GBP, AU200_AUD, US2000_USD, NATGAS_USD) was checked for
real file presence across the full 2005–2020 range *before* being added to
`search_space.py`'s `KNOWN_UNEXPLORED_DRIVERS` catalog — the same discipline
Cycle 13 used for its own new drivers. `cost_registered()` is checked
independently of data presence, and both AUDUSD/EURJPY-style gaps
(confirmed present in Cycle 13's audit) are correctly excluded from this
cycle's candidate pool by construction (they were never added to Cycle 14's
instrument list in the first place, since the demo only touches
already-cost-registered symbols).

---

## Net assessment

Three real, structural bugs were found by actually running the engine, not
by inspection: an over-broad REFUTED rollup that would have wrongly blocked
legitimate exploitation (Bug 1), a too-coarse family cap that silently
defeated the mandatory exploration floor (Bug 2), and the same rollup mistake
reappearing in branch-closure proposals (Bug 3). All three were fixed before
this document was finalized, all three now have regression tests, and the
corrected behavior was re-verified against three successive real end-to-end
runs through the actual Strategy Factory. The one disclosed side-effect of
fixing bugs between runs of the same live cycle — three append-only
`OPP-000069`/`OPP-000070`/`OPP-000071` entries, all describing the same one
real USDJPY/USB02Y/300m evaluation — is reported plainly in
`PHASE9_RESEARCH_SPACE_REPORT.md` rather than concealed, since the ledger's
append-only guarantee means it could not have been undone even if that were
desirable.
