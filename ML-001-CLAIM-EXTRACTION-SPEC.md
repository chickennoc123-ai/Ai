# ML-001 — Claim Extraction Specification (Generation 3, Phases 4-5)

**Status**: IMPLEMENTED and exercised against REAL material.
**Code**: `core/factory/claim_registry.py` (extended additively)
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3-§4.

---

## §1. Claim Fields

`ClaimRecord` (frozen dataclass — text is unmodifiable after construction) now carries, additively: `source_version`, `conditions`, `extraction_method`, `claim_classification`, `epistemic_status`, `evidence_reference`, alongside the Generation 2 fields (`claim_id`, `source_id`, `claim_version`, `claim_text`, `claim_type`, `mechanism`, `instrument_scope`, `timeframe_scope`, `direction`, `supporting_context`, `verification_status`).

## §2. Epistemic Status — the central discipline

```
SOURCE_CLAIM         "the source says X"          (default; a bare extraction can be nothing else)
FACT_ESTABLISHED     "X is established by OUR evidence"  (requires non-empty evidence_reference -- enforced)
HYPOTHESIS_CANDIDATE "X reframed as a falsifiable proposition"
```

A source's claim is **never silently rewritten into a stronger statement**: `claim_text` is frozen, registry lifecycle transitions provably leave it byte-identical (`Test05ClaimStrengthening`), and the production discipline is verbatim extraction — the flagship production claim (`CLAIM-000001`) is quoted word-for-word from the stored snapshot, and an end-to-end test asserts the claim text appears verbatim inside the snapshot bytes (`test_verbatim_claim_text_exists_in_the_source_snapshot`). Where an extraction is a summary rather than a quotation (production `CLAIM-000003`), `extraction_method` says so explicitly.

## §3. Classification (Phase 5)

`claim_classification` ∈ {`MECHANISTIC`, `EMPIRICAL`, `DESCRIPTIVE`, `PREDICTIVE`, `CAUSAL`, `HEURISTIC`, `MARKET_LORE`, `UNVERIFIED`, `PROMOTIONAL`} — descriptive metadata only, **never evidence of truth** (stated in the code's own docstring; nothing anywhere consumes classification as a truth signal). Production examples: the RSI 70/30 lore is `MARKET_LORE`/`SOURCE_CLAIM`; the MACD belief is `HEURISTIC`/`SOURCE_CLAIM`; the internal coverage finding is `EMPIRICAL`/`FACT_ESTABLISHED` with its evidence reference.

## §4. Lifecycle

Unchanged from Generation 2: `UNEXTRACTED → EXTRACTED → FORMALIZATION_PENDING → FORMALIZED → TESTED → {SUPPORTED, REFUTED}`, `SUPERSEDED` from any non-terminal state; `SUPPORTED` reachable only from `TESTED` — a claim is never `SUPPORTED` because the source said it, however popular, peer-reviewed, or confidently worded the source is.
