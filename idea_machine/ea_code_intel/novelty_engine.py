"""
Novelty Engine: read-only comparison of mined Strategy DNA against this
project's own real research memory.

Reads (never writes):
  reports/factory/failure_library.json         -- refuted mechanisms
  reports/factory/research_family_registry.json -- known/refuted families
  reports/factory/discovery_cycles/cycle_*.json  -- what's already been tried

Purpose: before spending Factory evaluation budget on a DNA-derived
hypothesis, check whether its mechanism tag-set overlaps heavily with a
REFUTED family. Overlap does not auto-reject (a refuted family was refuted
under SPECIFIC parameters/symbols; the same tag set on a different
symbol/driver/timeframe is not automatically the same claim) -- it flags
the resemblance so a human or a later gate can decide, and it records the
citation so the resemblance claim is checkable.

This directly implements the task's "avoid rediscovering refuted families
unless explicitly authorized by existing governance" requirement: it
produces a WARNING with evidence, not a silent rewrite or a silent skip.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FAILURE_LIBRARY = REPO_ROOT / "reports" / "factory" / "failure_library.json"
FAMILY_REGISTRY = REPO_ROOT / "reports" / "factory" / "research_family_registry.json"


@dataclass
class NoveltyVerdict:
    dna_id: str
    verdict: str                 # NOVEL, RARE, REPEATED, REFUTED, STILL_UNDERPOWERED, TESTED_FAILED, UNKNOWN
    matched_family_id: Optional[str]
    matched_family_status: Optional[str]  # status of matched family: REFUTED, STILL_UNDERPOWERED, TESTED_FAILED, etc.
    overlap_tags: List[str]
    overlap_ratio: float
    explanation: str
    classification: str = "NOVEL"  # 5-status classification: REFUTED|STILL_UNDERPOWERED|TESTED_FAILED|NOVEL|UNKNOWN


class NoveltyEngine:
    """
    Deterministic tag-overlap comparison. No embeddings, no LLM similarity
    call -- Jaccard overlap on the tag set, which is auditable and stable.
    """

    def __init__(self):
        self.refuted_families: List[Dict] = []
        self.underpowered_families: List[Dict] = []
        self.tested_failed_families: List[Dict] = []
        self.all_families: List[Dict] = []
        self._loaded = False

    def load(self):
        """Load read-only from the Factory's real historical records."""
        if FAMILY_REGISTRY.exists():
            data = json.loads(FAMILY_REGISTRY.read_text())
            for fam_id, fam in data.get("families", {}).items():
                entry = {**fam, "family_id": fam.get("family_id", fam_id)}
                self.all_families.append(entry)
                status = fam.get("status", "UNKNOWN")
                if status == "REFUTED":
                    self.refuted_families.append(entry)
                elif status == "STILL_UNDERPOWERED":
                    self.underpowered_families.append(entry)
                elif status == "TESTED_FAILED":
                    self.tested_failed_families.append(entry)
        self._loaded = True

    def _family_tag_set(self, family: Dict) -> Set[str]:
        """
        Families don't carry explicit DNA tags (they predate this module) --
        derive an approximate tag set from the family's own description text
        using the SAME deterministic extractor as strategy_dna.py, so the
        comparison is apples-to-apples.
        """
        from idea_machine.ea_code_intel.strategy_dna import extract_dna
        desc = family.get("description", "")
        dna = extract_dna(family.get("family_id", "FAM"), family.get("family_id", "FAM"), None, desc)
        return set(t for tags in dna.tags.values() for t in tags)

    def check(self, dna_tag_set: Set[str], dna_id: str,
             other_dna_tag_sets: Optional[List[Set[str]]] = None) -> NoveltyVerdict:
        """
        dna_tag_set: the tag set of the hypothesis under evaluation.
        other_dna_tag_sets: tag sets of OTHER sources mined in this same
            run, used to classify REPEATED vs RARE vs NOVEL among mined
            material (independent of the refuted-family check).

        Returns 5-status classification:
          - REFUTED: matches a REFUTED family ≥50%
          - STILL_UNDERPOWERED: matches a STILL_UNDERPOWERED family ≥50%
          - TESTED_FAILED: matches a TESTED_FAILED family ≥50%
          - NOVEL: no significant overlap with any family
          - UNKNOWN: no families in registry (no comparison possible)
        """
        if not self._loaded:
            self.load()

        # Step 1: Check against all family statuses (hierarchical: governance-critical first)
        best_match, best_overlap, best_tags, best_status = None, 0.0, [], None

        # Check REFUTED first (governance-critical)
        for fam in self.refuted_families:
            fam_tags = self._family_tag_set(fam)
            if not fam_tags or not dna_tag_set:
                continue
            inter = dna_tag_set & fam_tags
            union = dna_tag_set | fam_tags
            jaccard = len(inter) / len(union) if union else 0.0
            if jaccard > best_overlap:
                best_overlap, best_match, best_tags, best_status = jaccard, fam, sorted(inter), "REFUTED"

        # If no REFUTED match ≥50%, check STILL_UNDERPOWERED
        if best_overlap < 0.5:
            for fam in self.underpowered_families:
                fam_tags = self._family_tag_set(fam)
                if not fam_tags or not dna_tag_set:
                    continue
                inter = dna_tag_set & fam_tags
                union = dna_tag_set | fam_tags
                jaccard = len(inter) / len(union) if union else 0.0
                if jaccard > best_overlap:
                    best_overlap, best_match, best_tags, best_status = jaccard, fam, sorted(inter), "STILL_UNDERPOWERED"

        # If no UNDERPOWERED match ≥50%, check TESTED_FAILED
        if best_overlap < 0.5:
            for fam in self.tested_failed_families:
                fam_tags = self._family_tag_set(fam)
                if not fam_tags or not dna_tag_set:
                    continue
                inter = dna_tag_set & fam_tags
                union = dna_tag_set | fam_tags
                jaccard = len(inter) / len(union) if union else 0.0
                if jaccard > best_overlap:
                    best_overlap, best_match, best_tags, best_status = jaccard, fam, sorted(inter), "TESTED_FAILED"

        # If we found a significant match (≥50%), return it with appropriate classification
        if best_match and best_overlap >= 0.5:
            verdict_map = {
                "REFUTED": "REFUTED",
                "STILL_UNDERPOWERED": "STILL_UNDERPOWERED",
                "TESTED_FAILED": "TESTED_FAILED",
            }
            verdict = verdict_map.get(best_status, "REFUTED")
            expl_map = {
                "REFUTED": f"{round(best_overlap*100)}% tag overlap with REFUTED family "
                          f"{best_match['family_id']}. Not auto-rejected -- refutation was symbol/parameter-specific "
                          f"-- but requires explicit acknowledgment before Factory evaluation.",
                "STILL_UNDERPOWERED": f"{round(best_overlap*100)}% tag overlap with STILL_UNDERPOWERED family "
                                     f"{best_match['family_id']}. This mechanism has shown real signal but was blocked "
                                     f"by data scarcity in prior evaluation. Check opportunity_queue.json for retest "
                                     f"conditions before synthesizing a new variant.",
                "TESTED_FAILED": f"{round(best_overlap*100)}% tag overlap with TESTED_FAILED family "
                                f"{best_match['family_id']}. This mechanism was tested and rejected for insufficient "
                                f"evidence. Retest only if conditions materially changed.",
            }
            return NoveltyVerdict(
                dna_id=dna_id, verdict=verdict,
                matched_family_id=best_match["family_id"],
                matched_family_status=best_match.get("status"),
                overlap_tags=best_tags, overlap_ratio=round(best_overlap, 3),
                explanation=expl_map.get(best_status, ""),
                classification=best_status,
            )

        # Step 2: No significant family match; classify novelty among this run's own mined material
        if other_dna_tag_sets:
            match_counts = sum(1 for s in other_dna_tag_sets if s and dna_tag_set and
                              len(s & dna_tag_set) / len(s | dna_tag_set) >= 0.6)
            if match_counts >= 3:
                verdict = "REPEATED"
                expl = f"tag set closely matches {match_counts} other mined sources in this run"
            elif match_counts >= 1:
                verdict = "RARE"
                expl = f"tag set matches {match_counts} other mined source(s)"
            else:
                verdict = "NOVEL"
                expl = "tag set does not closely match any other mined source or known family"
        else:
            verdict = "NOVEL"
            expl = "no comparison set provided; no family overlap found"

        # Determine UNKNOWN vs NOVEL
        classification = "UNKNOWN" if not self.all_families else "NOVEL"

        return NoveltyVerdict(
            dna_id=dna_id, verdict=verdict, matched_family_id=None, matched_family_status=None,
            overlap_tags=[], overlap_ratio=round(best_overlap, 3), explanation=expl,
            classification=classification,
        )
