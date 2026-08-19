# ML-001 — Generation 5, Phase 1: Research Access Governance

**Date**: August 19, 2026
**Status**: `RESEARCH_ACCESS_STATUS = SCOPED_TO_ACCESSIBLE_SOURCES` (design doc §3.3 option (b))

---

## 1. The decision, and how it was reached

`ML-001-GENERATION-5-DESIGN.md` §3.3 left one question open: obtain authorized external research access, or explicitly scope Generation 5 to already-accessible sources. This was resolved **empirically, not by assumption**:

```
$ curl -sS -m 8 https://arxiv.org/abs/2106.00001
curl: (56) CONNECT tunnel failed, response 403

$ curl -sS -m 8 https://papers.ssrn.com
curl: (56) CONNECT tunnel failed, response 403
```

Both academic hosts already on record as `ACCESS_FAILED` from Generation 3 (`SRC2-000002` arxiv.org, `SRC2-000003` papers.ssrn.com) remain unreachable. The network policy is set at the environment level, outside this agent's authority to grant itself — option (a) is not available. No proxy, mirror, scrape, or alternate egress was attempted (Non-Negotiable Principle 20: `ACCESS_FAILED` means `ACCESS_FAILED`). The reconfirmation is recorded as `RESEARCH_ACCESS_REVIEWED` ledger events referencing the existing source records — no duplicate source registered for the same host.

**Decision: (b).** Generation 5 hypothesis intake is scoped to material already accessible: `SRC2-000001` (real external, permissively licensed), `SRC2-000004` and this project's own Failure Library/post-mortems (internal forensic), and AI-generated/human-supplied hypotheses — each carrying its own disclosed, non-elevated provenance weight (§2 below). This is a disclosed scoping decision: Phase 24 (portfolio diversity) reports the resulting source-type concentration rather than hiding it.

## 2. Vocabulary crosswalk

Generation 2/3 already built the substantive machinery (`core.factory.research_source_registry`): `access_status` (`NOT_ATTEMPTED` / `ACCESSED` / `ACCESS_FAILED`), `verification_status` (7 values), and a 17-value `SOURCE_TYPES` set. `core.factory.research_access_policy` crosswalks that machinery to this contract's vocabulary rather than rebuilding it:

| Contract term | This registry's `access_status` | Notes |
|---|---|---|
| `SOURCE_REACHABLE` | `ACCESSED` | |
| `SOURCE_ACCESS_FAILED` | `ACCESS_FAILED` | first-class, honest, never silently retried into a substitute |
| `SOURCE_UNVERIFIED` | `NOT_ATTEMPTED` | |
| `SOURCE_VERIFIED` | `ACCESSED` + `verification_status ∈ {VERIFIED, INDEPENDENTLY_VERIFIED}` | |

Source universe (`SOURCE_UNIVERSE` in the module), each with its own provenance semantics — none elevated to "evidence of profitability":

| Universe class | `source_type` values | Provenance semantics |
|---|---|---|
| `REAL_EXTERNAL_SOURCE` | `ACADEMIC_PAPER`, `WORKING_PAPER`, `BOOK`, `TEXTBOOK`, `RESEARCH_REPORT`, `WEBSITE` | third-party; SOURCE_CLAIM until independently tested |
| `INTERNAL_FORENSIC_SOURCE` | `INTERNAL_RESEARCH_REPORT` | this project's own checksummed prior work |
| `PUBLIC_STRATEGY` | `PUBLIC_STRATEGY`, `OPEN_SOURCE_CODE` | popularity is never evidence of profitability |
| `VIDEO` | `YOUTUBE` | never empirical validation |
| `AI_GENERATED` | `AI_GENERATED_HYPOTHESIS` | plausibility is not evidence; no credential, no penalty |
| `USER_SUPPLIED` | `HUMAN_HYPOTHESIS` | same non-evidentiary status as any hypothesis source |
| `DERIVED_SYNTHESIS` | `MARKET_OBSERVATION`, `MACRO_DATA_SOURCE`, `ALTERNATIVE_DATA_SOURCE`, `MACRO_RESEARCH`, `ALTERNATIVE_DATA_RESEARCH` | must record every input it derives from |

Every one of the 17 registered `source_type` values classifies into exactly one universe class (verified by `tests/test_generation5_adversarial.py` transitively via production data checks).

## 3. Behavioral guard

`assert_access_failed_not_treated_as_reviewed(source)` raises if an `ACCESS_FAILED` source carries a `content_checksum` or a `verification_status` inconsistent with `ACCESS_FAILED` — both would imply content that was never reached had been reviewed. All 4 production source records pass this guard today.
