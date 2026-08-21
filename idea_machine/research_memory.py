"""
Research Memory: deterministic, read-only aggregation of project's testing history.

Reads (never writes):
  - reports/factory/research_family_registry.json (families with status field)
  - reports/factory/candidate_spec_registry.json (frozen candidates with evidence_status)
  - reports/factory/discovery_cycles/cycle_*.json (real Factory evaluations)

Purpose: before synthesizing a new idea, check whether its DNA matches an
existing opportunity (same mechanism, different parameters, waiting for data)
or a refuted family (same mechanism, already ruled out).

Research Memory is NOT a new authority; it is a read-only VIEW over existing
immutable records maintained by domain experts and the Factory itself.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
FAMILY_REGISTRY = REPO_ROOT / "reports" / "factory" / "research_family_registry.json"
CANDIDATE_REGISTRY = REPO_ROOT / "reports" / "factory" / "candidate_spec_registry.json"
CYCLES_DIR = REPO_ROOT / "reports" / "factory" / "discovery_cycles"


@dataclass
class FamilyRecord:
    """A family entry from research_family_registry.json."""
    family_id: str
    status: str  # REFUTED, STILL_UNDERPOWERED, TESTED_FAILED, NOVEL, UNKNOWN
    description: str
    members: List[str]
    related_refutation: Optional[str] = None  # failure_id if REFUTED


@dataclass
class CandidateRecord:
    """A candidate entry from candidate_spec_registry.json."""
    candidate_id: str
    mechanism: str
    evidence_status: str  # STILL_UNDERPOWERED, TESTED_FAILED, SURVIVOR, etc.
    symbol: str
    driver: Optional[str]
    train_n: Optional[int]
    train_t: Optional[float]
    val_n: Optional[int]
    val_t: Optional[float]


@dataclass
class CycleHypothesisRecord:
    """A hypothesis from a discovery_cycles/*.json file."""
    hyp_id: str
    cycle_id: str
    symbol: str
    driver: Optional[str]
    n_events_available: int
    windows_evaluated: int
    survivors: int
    best_train_t: Optional[float]
    best_val_n: Optional[int]
    mean_confirmation_rate: Optional[float]
    classification: str  # REFUTED, STILL_UNDERPOWERED, TESTED_FAILED, SURVIVOR


class ResearchMemory:
    """Read-only queries over existing project records."""

    def __init__(self):
        self.families: Dict[str, FamilyRecord] = {}
        self.candidates: Dict[str, CandidateRecord] = {}
        self.cycle_hypotheses: List[CycleHypothesisRecord] = []
        self._loaded = False

    def load(self):
        """Load all three sources."""
        self._load_families()
        self._load_candidates()
        self._load_cycles()
        self._loaded = True

    def _load_families(self):
        """Load research_family_registry.json."""
        if not FAMILY_REGISTRY.exists():
            return
        data = json.loads(FAMILY_REGISTRY.read_text())
        for fam_id, fam in data.get("families", {}).items():
            self.families[fam_id] = FamilyRecord(
                family_id=fam.get("family_id", fam_id),
                status=fam.get("status", "UNKNOWN"),
                description=fam.get("description", ""),
                members=fam.get("members", []),
                related_refutation=fam.get("refuted_by"),
            )

    def _load_candidates(self):
        """Load candidate_spec_registry.json."""
        if not CANDIDATE_REGISTRY.exists():
            return
        data = json.loads(CANDIDATE_REGISTRY.read_text())
        for cand_id, cand in data.get("candidates", {}).items():
            params = cand.get("parameters", {})
            measured = params.get("last_measured", {})
            self.candidates[cand_id] = CandidateRecord(
                candidate_id=cand.get("candidate_id", cand_id),
                mechanism=cand.get("mechanism", ""),
                evidence_status=params.get("evidence_status", "UNKNOWN"),
                symbol=params.get("symbol", ""),
                driver=params.get("driver"),
                train_n=measured.get("train_n"),
                train_t=measured.get("train_t"),
                val_n=measured.get("val_n"),
                val_t=measured.get("val_t"),
            )

    def _load_cycles(self):
        """Load discovery_cycles/*.json hypotheses."""
        if not CYCLES_DIR.exists():
            return
        for cycle_file in sorted(CYCLES_DIR.glob("cycle_*.json")):
            try:
                data = json.loads(cycle_file.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            hyps = data.get("hypotheses", [])
            if not hyps or not isinstance(hyps, list):
                continue
            for hyp in hyps:
                hyp_id = hyp.get("hyp_id", "")
                if not hyp_id:
                    continue
                windows = list(hyp.get("windows", []))
                for delay_entry in hyp.get("delays", []):
                    windows.extend(delay_entry.get("windows", []))
                if not windows:
                    continue
                survivors = [w for w in windows if w.get("verdict") == "DISCOVERY_SURVIVOR"]
                verdicts = [w.get("verdict") for w in windows if "train" in w]
                underpowered = [w for w in windows if w.get("verdict") == "VALIDATION_UNDERPOWERED"]
                train_ts = [w.get("train", {}).get("t_stat") for w in windows
                           if "train" in w and w.get("train", {}).get("t_stat") is not None]
                val_ns = [w.get("validation", {}).get("n") for w in windows
                         if "validation" in w and w.get("validation", {}).get("n") is not None]
                conf_rates = [w.get("confirmation_rate") for w in windows
                             if w.get("confirmation_rate") is not None]
                best_train_t_val = max(train_ts) if train_ts else None
                classification = self._classify_cycle_hypothesis(verdicts, survivors, underpowered, best_train_t_val)
                self.cycle_hypotheses.append(CycleHypothesisRecord(
                    hyp_id=hyp_id,
                    cycle_id=data.get("cycle_id", ""),
                    symbol=hyp.get("symbol", ""),
                    driver=hyp.get("driver"),
                    n_events_available=hyp.get("n_events_available", 0),
                    windows_evaluated=len(windows),
                    survivors=len(survivors),
                    best_train_t=max(train_ts) if train_ts else None,
                    best_val_n=max(val_ns) if val_ns else None,
                    mean_confirmation_rate=(sum(conf_rates) / len(conf_rates)) if conf_rates else None,
                    classification=classification,
                ))

    @staticmethod
    def _classify_cycle_hypothesis(verdicts: List[str], survivors: List, underpowered: List,
                                   best_train_t: float = None) -> str:
        """Classify a hypothesis based on its window verdicts and best train t-stat."""
        if survivors:
            return "SURVIVOR"
        # If there are underpowered windows and best train t >= 1.5, it's real signal blocked by data
        if underpowered and best_train_t and best_train_t >= 1.5:
            return "STILL_UNDERPOWERED"
        # All windows show no real signal
        if not verdicts or all(v in ("TRAIN_NEGATIVE", "TRAIN_INSIGNIFICANT", "VALIDATION_NEGATIVE") for v in verdicts):
            return "REFUTED"
        return "TESTED_FAILED"

    def lookup_family_by_id(self, family_id: str) -> Optional[FamilyRecord]:
        """Look up a family by its ID."""
        if not self._loaded:
            self.load()
        return self.families.get(family_id)

    def lookup_families_by_status(self, status: str) -> List[FamilyRecord]:
        """Get all families with a given status."""
        if not self._loaded:
            self.load()
        return [f for f in self.families.values() if f.status == status]

    def lookup_candidate_by_id(self, candidate_id: str) -> Optional[CandidateRecord]:
        """Look up a candidate by its ID."""
        if not self._loaded:
            self.load()
        return self.candidates.get(candidate_id)

    def lookup_candidates_by_status(self, evidence_status: str) -> List[CandidateRecord]:
        """Get all candidates with a given evidence_status."""
        if not self._loaded:
            self.load()
        return [c for c in self.candidates.values() if c.evidence_status == evidence_status]

    def lookup_underpowered_hypotheses(self) -> List[CycleHypothesisRecord]:
        """Get all historical hypotheses classified as STILL_UNDERPOWERED."""
        if not self._loaded:
            self.load()
        return [h for h in self.cycle_hypotheses if h.classification == "STILL_UNDERPOWERED"]

    def lookup_refuted_hypotheses(self) -> List[CycleHypothesisRecord]:
        """Get all historical hypotheses classified as REFUTED."""
        if not self._loaded:
            self.load()
        return [h for h in self.cycle_hypotheses if h.classification == "REFUTED"]

    def get_summary(self) -> Dict:
        """Quick diagnostic summary of research memory."""
        if not self._loaded:
            self.load()
        return {
            "families_total": len(self.families),
            "families_by_status": {
                "REFUTED": len(self.lookup_families_by_status("REFUTED")),
                "STILL_UNDERPOWERED": len(self.lookup_families_by_status("STILL_UNDERPOWERED")),
                "TESTED_FAILED": len(self.lookup_families_by_status("TESTED_FAILED")),
                "NOVEL": len(self.lookup_families_by_status("NOVEL")),
                "UNKNOWN": len(self.lookup_families_by_status("UNKNOWN")),
            },
            "candidates_total": len(self.candidates),
            "candidates_by_status": {
                "STILL_UNDERPOWERED": len(self.lookup_candidates_by_status("STILL_UNDERPOWERED")),
                "TESTED_FAILED": len(self.lookup_candidates_by_status("TESTED_FAILED")),
                "SURVIVOR": len(self.lookup_candidates_by_status("SURVIVOR")),
            },
            "cycle_hypotheses_total": len(self.cycle_hypotheses),
            "underpowered_hypotheses": len(self.lookup_underpowered_hypotheses()),
            "refuted_hypotheses": len(self.lookup_refuted_hypotheses()),
        }
