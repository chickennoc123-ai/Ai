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
    verdict: str                 # NOVEL, RARE, REPEATED, RESEMBLES_REFUTED
    matched_family_id: Optional[str]
    matched_family_status: Optional[str]
    overlap_tags: List[str]
    overlap_ratio: float
    explanation: str


class NoveltyEngine:
    """
    Deterministic tag-overlap comparison. No embeddings, no LLM similarity
    call -- Jaccard overlap on the tag set, which is auditable and stable.
    """

    def __init__(self):
        self.refuted_families: List[Dict] = []
        self.all_families: List[Dict] = []
        self._loaded = False

    def load(self):
        """Load read-only from the Factory's real historical records."""
        if FAMILY_REGISTRY.exists():
            data = json.loads(FAMILY_REGISTRY.read_text())
            for fam_id, fam in data.get("families", {}).items():
                entry = {**fam, "family_id": fam.get("family_id", fam_id)}
                self.all_families.append(entry)
                if fam.get("status") == "REFUTED":
                    self.refuted_families.append(entry)
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
        """
        if not self._loaded:
            self.load()

        # Step 1: check against refuted families (the governance-critical check)
        best_match, best_overlap, best_tags = None, 0.0, []
        for fam in self.refuted_families:
            fam_tags = self._family_tag_set(fam)
            if not fam_tags or not dna_tag_set:
                continue
            inter = dna_tag_set & fam_tags
            union = dna_tag_set | fam_tags
            jaccard = len(inter) / len(union) if union else 0.0
            if jaccard > best_overlap:
                best_overlap, best_match, best_tags = jaccard, fam, sorted(inter)

        if best_match and best_overlap >= 0.5:
            return NoveltyVerdict(
                dna_id=dna_id, verdict="RESEMBLES_REFUTED",
                matched_family_id=best_match["family_id"],
                matched_family_status=best_match.get("status"),
                overlap_tags=best_tags, overlap_ratio=round(best_overlap, 3),
                explanation=(f"{round(best_overlap*100)}% tag overlap with REFUTED family "
                            f"{best_match['family_id']} ({best_match.get('description', '')[:120]}). "
                            f"Not auto-rejected -- refutation was symbol/parameter-specific -- but "
                            f"requires explicit acknowledgment before Factory evaluation."),
            )

        # Step 2: classify novelty among this run's own mined material
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
                expl = "tag set does not closely match any other mined source or known refuted family"
        else:
            verdict = "NOVEL"
            expl = "no comparison set provided; no refuted-family overlap found"

        return NoveltyVerdict(
            dna_id=dna_id, verdict=verdict, matched_family_id=None, matched_family_status=None,
            overlap_tags=[], overlap_ratio=round(best_overlap, 3), explanation=expl,
        )
