"""Research access governance — Generation 5, Phase 1.

Closes the design-doc open question (``ML-001-GENERATION-5-DESIGN.md``
§3.3, §5.1): whether Generation 5 obtains an authorized external research
path, or scopes itself to already-accessible sources. Resolved empirically,
not by assumption — see :func:`reconfirm_external_access` and
``ML-001-G5-RESEARCH-ACCESS-GOVERNANCE.md`` for the recorded result.

This module does **not** replace ``core.factory.research_source_registry``
(Generation 2/3), which already carries the richer part of this machinery:
``access_status`` (``NOT_ATTEMPTED`` / ``ACCESSED`` / ``ACCESS_FAILED``),
``verification_status``, and a 17-value ``SOURCE_TYPES`` set. Phase 1's
job is to (a) state the crosswalk between that existing vocabulary and the
contract's requested terms explicitly, so a future reader does not have to
infer it, and (b) enforce the one behavioral rule the contract adds:
network restrictions are never bypassed, and an ``ACCESS_FAILED`` source's
content is never treated as reviewed.
"""

from __future__ import annotations

from typing import Dict

from core.factory.research_ledger import ResearchLedger
from core.factory.research_source_registry import ResearchSourceRegistry, SourceRecord
from utils.exceptions import EAFactoryError

#: Contract vocabulary -> this project's existing SourceRecord.access_status.
#: SOURCE_REACHABLE / SOURCE_UNVERIFIED collapse onto the same underlying
#: state (NOT_ATTEMPTED) because "reachable but not yet looked at" and
#: "not yet attempted" are the same fact from this registry's point of
#: view; SOURCE_VERIFIED is a verification_status distinction layered on
#: top of ACCESSED, not a separate access_status value.
ACCESS_STATUS_CROSSWALK: Dict[str, str] = {
    "SOURCE_REACHABLE": "ACCESSED",
    "SOURCE_ACCESS_FAILED": "ACCESS_FAILED",
    "SOURCE_UNVERIFIED": "NOT_ATTEMPTED",
    "SOURCE_VERIFIED": "ACCESSED",  # + verification_status in {VERIFIED, INDEPENDENTLY_VERIFIED}
}

#: Contract's source-universe classes -> the source_type values already
#: registered in research_source_registry.SOURCE_TYPES, with the
#: provenance semantics that govern what each class may ever be used for.
#: "Evidence weight" is deliberately not a number: it is a sentence,
#: because collapsing it to a score is exactly the kind of AI-plausibility-
#: as-evidence conflation Non-Negotiable Principle 22 forbids.
SOURCE_UNIVERSE = {
    "REAL_EXTERNAL_SOURCE": {
        "source_types": ("ACADEMIC_PAPER", "WORKING_PAPER", "BOOK", "TEXTBOOK", "RESEARCH_REPORT", "WEBSITE"),
        "provenance_semantics": (
            "Third-party material, external to this project. Never evidence of profitability by "
            "itself; a claim extracted from it is SOURCE_CLAIM until independently tested."
        ),
    },
    "INTERNAL_FORENSIC_SOURCE": {
        "source_types": ("INTERNAL_RESEARCH_REPORT",),
        "provenance_semantics": (
            "This project's own committed, checksummed prior work (e.g. failure forensics, prior "
            "generation reports). Verifiable at any time from the working tree; still not evidence "
            "of profitability on its own -- it is evidence of what was previously found and how."
        ),
    },
    "PUBLIC_STRATEGY": {
        "source_types": ("PUBLIC_STRATEGY", "OPEN_SOURCE_CODE"),
        "provenance_semantics": (
            "A publicly described or published trading rule. Its existence and popularity are not "
            "evidence it is profitable (Non-Negotiable Principle 23) -- only a real tested candidate "
            "can establish that."
        ),
    },
    "VIDEO": {
        "source_types": ("YOUTUBE",),
        "provenance_semantics": (
            "Informal video material. Never empirical validation (Principle 19-23 apply in full); "
            "usable only as a hypothesis-generation prompt, exactly like any other SOURCE_CLAIM."
        ),
    },
    "AI_GENERATED": {
        "source_types": ("AI_GENERATED_HYPOTHESIS",),
        "provenance_semantics": (
            "A hypothesis an AI model proposed. Plausibility is not evidence (Principle 22); it "
            "faces the identical gates as any other hypothesis, no credential and no penalty for "
            "its origin."
        ),
    },
    "USER_SUPPLIED": {
        "source_types": ("HUMAN_HYPOTHESIS",),
        "provenance_semantics": "A human-proposed idea, carrying the same non-evidentiary status as any other hypothesis source until tested.",
    },
    "DERIVED_SYNTHESIS": {
        "source_types": ("MARKET_OBSERVATION", "MACRO_DATA_SOURCE", "ALTERNATIVE_DATA_SOURCE",
                          "MACRO_RESEARCH", "ALTERNATIVE_DATA_RESEARCH"),
        "provenance_semantics": (
            "Synthesis across multiple observations/datasets rather than a single citable document. "
            "Provenance must record every input it was derived from."
        ),
    },
}

#: The Generation 5 access-policy decision, recorded once and referenced
#: (never re-derived by inference) by every Phase-1-dependent artifact.
#: "(b)" refers to ML-001-GENERATION-5-DESIGN.md §3.3's own disclosed
#: fallback option: scope to already-accessible sources rather than
#: quietly biasing the source portfolio toward whatever happens to be
#: reachable.
ACCESS_POLICY_DECISION = (
    "GENERATION_5_ACCESS_POLICY = SCOPED_TO_ACCESSIBLE_SOURCES (design doc §3.3 option (b)). "
    "Authorized external academic access (option (a)) is not obtainable from within this "
    "environment -- the network policy is set at the environment level, outside this agent's "
    "authority to grant itself. Empirically reconfirmed 2026-08-19: both academic hosts already "
    "on record as ACCESS_FAILED (SRC2-000002 arxiv.org, SRC2-000003 papers.ssrn.com) remain "
    "unreachable through the outbound proxy (CONNECT tunnel 403). No proxy, mirror, scrape, or "
    "alternate egress was attempted (Non-Negotiable Principle 20: ACCESS_FAILED means "
    "ACCESS_FAILED). Generation 5 hypothesis intake is therefore scoped to REAL_EXTERNAL_SOURCE "
    "material already registered (SRC2-000001), INTERNAL_FORENSIC_SOURCE material (SRC2-000004 "
    "and this project's own Failure Library / post-mortems), and AI_GENERATED / USER_SUPPLIED "
    "hypotheses -- each carrying its own disclosed, non-elevated provenance weight per "
    "SOURCE_UNIVERSE above. This is a disclosed scoping decision, not a silent one: the "
    "diversity/concentration reporting in Phase 24 will show the resulting source-type "
    "concentration rather than hide it."
)


class AccessPolicyError(EAFactoryError):
    pass


def classify_source_universe(source_type: str) -> str:
    """Return the contract's source-universe class for a registered
    ``source_type``, or raise if the type is not classified anywhere --
    a new source_type added to the registry without updating this
    crosswalk is a bug, not a silent gap."""
    for universe_class, spec in SOURCE_UNIVERSE.items():
        if source_type in spec["source_types"]:
            return universe_class
    raise AccessPolicyError("source_type has no source-universe classification", source_type=source_type)


def assert_access_failed_not_treated_as_reviewed(source: SourceRecord) -> None:
    """The one behavioral guard Phase 1 adds: a source whose content was
    never reached must never be presented as though it had been. Raises
    if an ACCESS_FAILED source claims a content_checksum or a
    verification_status stronger than ACCESS_FAILED -- both would imply
    the content was actually read."""
    if source.access_status != "ACCESS_FAILED":
        return
    if source.content_checksum not in ("UNKNOWN", ""):
        raise AccessPolicyError(
            "ACCESS_FAILED source carries a content_checksum -- this would imply its content was "
            "reached and reviewed, which contradicts its own access_status",
            source_id=source.source_id,
        )
    if source.verification_status != "ACCESS_FAILED":
        raise AccessPolicyError(
            "ACCESS_FAILED source does not carry a matching verification_status",
            source_id=source.source_id, verification_status=source.verification_status,
        )


def reconfirm_external_access(
    *, source_registry: ResearchSourceRegistry, ledger: ResearchLedger, reachable: Dict[str, bool],
) -> None:
    """Record a fresh, timestamped re-check of every already-registered
    ACCESS_FAILED source's reachability, WITHOUT registering duplicate
    source records for the same host (that would inflate the source count
    for no research reason) and without upgrading any status on the basis
    of a bare TCP/HTTP reachability check alone -- reachability is not the
    same thing as content having been reviewed (module docstring).

    ``reachable`` maps ``source_id -> bool`` for the reachability observed
    THIS run; every value must correspond to an existing ACCESS_FAILED
    source, and a ``True`` value does not by itself change
    ``access_status`` -- it is recorded as a ledger event only, so the
    decision to actually re-attempt intake is a distinct, later act.
    """
    for source_id, is_reachable in reachable.items():
        source = source_registry.get(source_id)
        assert_access_failed_not_treated_as_reviewed(source)
        ledger.append(
            "RESEARCH_ACCESS_REVIEWED",
            subject_id=source_id,
            reason=(
                f"Generation 5 Phase 1 reconfirmation: {source.source_url} "
                f"{'reachable' if is_reachable else 'still unreachable'} via the outbound proxy. "
                "No content was fetched by this check; access_status is unchanged."
            ),
            result="REACHABLE" if is_reachable else "STILL_ACCESS_FAILED",
            artifact_reference="ML-001-G5-RESEARCH-ACCESS-GOVERNANCE.md",
        )
