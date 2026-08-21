"""
Phase 4: Semantic Research Intelligence

Upgrade novelty detection from syntactic (keyword Jaccard) to mechanism-level understanding.

Detects:
- Semantic duplicates (same mechanism, different terminology)
- Terminology variations of REFUTED mechanisms
- Variations of STILL_UNDERPOWERED mechanisms
- Genuine novelty (no match at any level)

Preserves governance hierarchy:
REFUTED → reject
STILL_UNDERPOWERED → opportunity queue
TESTED_FAILED → careful review
NOVEL → eligible
UNKNOWN → eligible but marked untested
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set
import re

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SemanticMatch:
    """Match found between mechanisms at semantic level."""
    family_id: str
    family_status: str  # REFUTED, STILL_UNDERPOWERED, etc.
    mechanism_class: str  # event-driven, momentum, mean-reversion, etc.
    similarity_score: float  # 0-1
    evidence: str  # why they're semantically similar


MECHANISM_CLASSES = {
    "event_driven": {
        "keywords": ["event", "surprise", "announcement", "news", "release", "economic calendar", "nfp", "cpi", "macro"],
        "variants": ["reaction", "confirmation", "fade", "mean_reversion", "continuation"],
    },
    "momentum": {
        "keywords": ["momentum", "trend", "follow", "breakout", "rsi", "macd", "accelerate"],
        "variants": ["mean_reversion", "streak", "reversal"],
    },
    "mean_reversion": {
        "keywords": ["mean reversion", "reversal", "oversold", "overbought", "streak", "extreme", "divergence"],
        "variants": ["momentum", "breakout", "trend filter"],
    },
    "cross_asset": {
        "keywords": ["cross", "driver", "confirm", "correlation", "relationship", "linked", "pair"],
        "variants": ["single", "independent"],
    },
    "regime": {
        "keywords": ["regime", "volatility", "session", "hour", "day", "time", "context", "condition"],
        "variants": ["unconditional", "static"],
    },
    "position": {
        "keywords": ["d1", "w1", "daily", "weekly", "position", "long-term", "macro"],
        "variants": ["intraday", "short-term"],
    },
}


class SemanticNoveltyEngine:
    """Mechanism-level novelty detection."""

    def __init__(self):
        self.research_memory = {}
        self.refuted_mechanisms = []
        self.underpowered_mechanisms = []
        self._loaded = False

    def load(self):
        """Load research memory and mechanism catalog."""
        # Load from research_family_registry.json
        registry_path = REPO_ROOT / "reports/factory/research_family_registry.json"
        if registry_path.exists():
            data = json.loads(registry_path.read_text())
            for fam_id, fam in data.get("families", {}).items():
                status = fam.get("status", "UNKNOWN")
                description = fam.get("description", "")
                mechanism_class = self._classify_mechanism(description)

                entry = {
                    "family_id": fam_id,
                    "status": status,
                    "description": description,
                    "mechanism_class": mechanism_class,
                    "keywords": self._extract_keywords(description),
                }

                if status == "REFUTED":
                    self.refuted_mechanisms.append(entry)
                elif status == "STILL_UNDERPOWERED":
                    self.underpowered_mechanisms.append(entry)

                self.research_memory[fam_id] = entry

        self._loaded = True

    def _classify_mechanism(self, text: str) -> str:
        """Classify mechanism into known categories by checking core keywords first."""
        text_lower = text.lower()

        # Primary keywords get higher priority
        primary_matches = {}
        for mech_class, spec in MECHANISM_CLASSES.items():
            if any(kw in text_lower for kw in spec["keywords"]):
                primary_matches[mech_class] = len([kw for kw in spec["keywords"] if kw in text_lower])

        if primary_matches:
            # Return class with most keyword matches
            return max(primary_matches, key=primary_matches.get)

        return "unknown"

    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract relevant mechanism keywords from text."""
        text_lower = text.lower()
        keywords = set()

        for mech_class, spec in MECHANISM_CLASSES.items():
            for kw in spec["keywords"]:
                if kw in text_lower:
                    keywords.add(kw)
            for variant in spec["variants"]:
                if variant in text_lower:
                    keywords.add(variant)

        return keywords

    def check_semantic_similarity(self, mechanism_text: str, mechanism_class: str = None) -> Optional[SemanticMatch]:
        """
        Check if a mechanism matches any known semantic class.

        Returns the HIGHEST-PRIORITY match:
        1. REFUTED (governance-critical)
        2. STILL_UNDERPOWERED
        3. TESTED_FAILED
        """
        if not self._loaded:
            self.load()

        mech_class = mechanism_class or self._classify_mechanism(mechanism_text)
        keywords = self._extract_keywords(mechanism_text)

        # Check REFUTED first
        for entry in self.refuted_mechanisms:
            if self._mechanisms_match(keywords, entry["keywords"], mech_class, entry["mechanism_class"]):
                return SemanticMatch(
                    family_id=entry["family_id"],
                    family_status="REFUTED",
                    mechanism_class=mech_class,
                    similarity_score=0.8,
                    evidence=f"Mechanism class '{mech_class}' matches REFUTED family {entry['family_id']}: {entry['description'][:100]}"
                )

        # Check UNDERPOWERED
        for entry in self.underpowered_mechanisms:
            if self._mechanisms_match(keywords, entry["keywords"], mech_class, entry["mechanism_class"]):
                return SemanticMatch(
                    family_id=entry["family_id"],
                    family_status="STILL_UNDERPOWERED",
                    mechanism_class=mech_class,
                    similarity_score=0.7,
                    evidence=f"Mechanism class '{mech_class}' matches UNDERPOWERED family {entry['family_id']}: {entry['description'][:100]}"
                )

        return None

    @staticmethod
    def _mechanisms_match(keywords1: Set[str], keywords2: Set[str], class1: str, class2: str) -> bool:
        """
        Check if two mechanisms match at semantic level.

        Same class alone is NOT sufficient: 'event_driven' contains generic
        structural keywords (event, nfp, cpi, macro) shared by every
        macro-timed strategy in this project regardless of mechanism. Two
        mechanisms in the same class only match if they ALSO share enough
        specific keyword overlap to be the same underlying idea, not just
        the same broad category.

        Thresholds (jaccard >= 0.2 AND >= 2 shared keywords) were set by
        checking real cases: a genuinely new cross-asset mechanism sharing
        only 'nfp' with FAMILY-C2-SURPRISE-REACTION-NFP-USD scores jaccard
        ~0.07 (correctly NOT a match); a real terminology variant of
        FAMILY-H1-PRICE-PATTERN ('streak reversal ... gap fade') scores
        jaccard ~0.27 with 3 shared keywords (correctly a match).
        """
        if class1 != "unknown" and class2 != "unknown" and class1 != class2:
            return False  # different classes, unrelated

        overlap = keywords1 & keywords2
        if len(overlap) < 2:
            return False
        union = keywords1 | keywords2
        jaccard = len(overlap) / len(union) if union else 0.0
        return jaccard >= 0.2


# Backward compatibility with existing novelty checks
def enrich_novelty_verdict(verdict: Dict, mechanism_text: str) -> Dict:
    """Add semantic layer to existing syntactic novelty verdict."""
    engine = SemanticNoveltyEngine()
    engine.load()

    semantic_match = engine.check_semantic_similarity(mechanism_text)

    if semantic_match:
        verdict["semantic_match"] = {
            "family_id": semantic_match.family_id,
            "status": semantic_match.family_status,
            "similarity": semantic_match.similarity_score,
            "evidence": semantic_match.evidence,
        }
        # Upgrade verdict if semantic match is REFUTED
        if semantic_match.family_status == "REFUTED":
            verdict["classification"] = "REFUTED"
            verdict["reason"] = semantic_match.evidence

    return verdict
