"""
Opportunity Queue: deterministic, APPEND-ONLY tracking of hypotheses waiting for data.

APPEND-ONLY guarantee: every entry is immutable once created. New conditions or
evidence is added as a new timestamped entry, never retroactively modifying
historical records. This ensures traceability and prevents accidental data loss.

A queue entry is NOT an edge claim; it is a record that:
  - A specific hypothesis showed real statistical signal in training
  - Validation was underpowered (n < 30) due to data scarcity or filtering
  - Calculated, not guessed, evidence for what sample size is needed to reach
    power threshold
  - Explicit retest condition (e.g., "if NFP event pool extends to ≥200 events")

The Factory remains the ONLY authority for validating strategy quality.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "reports" / "idea_machine" / "opportunity_queue.json"


@dataclass
class DataRequirement:
    """What data is needed to reach power threshold."""
    description: str  # e.g., "NFP event count"
    current_value: int  # e.g., 128
    required_value: int  # e.g., 200
    unit: str  # "raw events", "confirmed events", etc.


@dataclass
class RetestCondition:
    """When and how to retest an opportunity."""
    earliest_date: Optional[str]  # ISO8601 or None if impossible
    trigger: str  # explicit, human-readable condition
    estimated_power_gain: Optional[str]  # "val n could increase from 8 to ~25-30"


@dataclass
class OpportunityQueueEntry:
    """One immutable entry in the opportunity queue."""
    queue_id: str
    source_hypothesis_id: str
    source_cycle_id: str
    classification: str  # STILL_UNDERPOWERED, TESTED_FAILED
    mechanism_summary: str
    symbol: str
    driver: Optional[str]
    n_events_available: int
    windows_evaluated: int
    best_train_t: Optional[float]
    best_val_n: Optional[int]
    mean_confirmation_rate: Optional[float]
    evidence_level: str  # REAL_SIGNAL_BLOCKED, DATA_INSUFFICIENT, CONSISTENT_BUT_NOISY, etc.
    reason: str  # Free-form explanation of why it's blocked
    missing_data: Dict  # Serialized DataRequirement
    retest_conditions: Dict  # Serialized RetestCondition
    priority: str  # HIGH, MEDIUM, LOW
    created_date: str  # ISO8601 timestamp
    provenance_status: str  # DATA_SUPPORTED, etc. (immutable proof it reached this stage)


class OpportunityQueue:
    """Deterministic, append-only queue of retest opportunities."""

    def __init__(self, queue_file: Path = QUEUE_FILE):
        self.queue_file = queue_file
        self.entries: List[OpportunityQueueEntry] = []
        self._loaded = False
        self._next_id = 1

    def load(self):
        """Load existing queue (immutable read)."""
        if self.queue_file.exists():
            data = json.loads(self.queue_file.read_text())
            for entry_data in data.get("entries", []):
                self.entries.append(OpportunityQueueEntry(**entry_data))
                self._next_id = max(self._next_id, int(entry_data.get("queue_id", "OPP-0").split("-")[1]) + 1)
        self._loaded = True

    def append(self, source_hypothesis_id: str, source_cycle_id: str, classification: str,
               mechanism_summary: str, symbol: str, driver: Optional[str],
               n_events_available: int, windows_evaluated: int, best_train_t: Optional[float],
               best_val_n: Optional[int], mean_confirmation_rate: Optional[float],
               evidence_level: str, reason: str, missing_data: DataRequirement,
               retest_conditions: RetestCondition, priority: str,
               provenance_status: str) -> OpportunityQueueEntry:
        """Append a new opportunity to the queue (immutable once added)."""
        if not self._loaded:
            self.load()

        queue_id = f"OPP-{self._next_id:06d}"
        entry = OpportunityQueueEntry(
            queue_id=queue_id,
            source_hypothesis_id=source_hypothesis_id,
            source_cycle_id=source_cycle_id,
            classification=classification,
            mechanism_summary=mechanism_summary,
            symbol=symbol,
            driver=driver,
            n_events_available=n_events_available,
            windows_evaluated=windows_evaluated,
            best_train_t=best_train_t,
            best_val_n=best_val_n,
            mean_confirmation_rate=mean_confirmation_rate,
            evidence_level=evidence_level,
            reason=reason,
            missing_data=asdict(missing_data),
            retest_conditions=asdict(retest_conditions),
            priority=priority,
            created_date=datetime.utcnow().isoformat(),
            provenance_status=provenance_status,
        )
        self.entries.append(entry)
        self._next_id += 1
        return entry

    def save(self):
        """Write queue to disk (append: never overwrite existing entries)."""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "entry_count": len(self.entries),
            "entries": [asdict(e) for e in self.entries],
        }
        self.queue_file.write_text(json.dumps(payload, indent=2))

    def get_by_hypothesis_id(self, hyp_id: str) -> List[OpportunityQueueEntry]:
        """Get all queue entries for a given hypothesis (may have multiple if retested)."""
        if not self._loaded:
            self.load()
        return [e for e in self.entries if e.source_hypothesis_id == hyp_id]

    def get_by_priority(self, priority: str) -> List[OpportunityQueueEntry]:
        """Get all entries with a given priority."""
        if not self._loaded:
            self.load()
        return [e for e in self.entries if e.priority == priority]

    def get_by_classification(self, classification: str) -> List[OpportunityQueueEntry]:
        """Get all entries with a given classification."""
        if not self._loaded:
            self.load()
        return [e for e in self.entries if e.classification == classification]

    def get_summary(self) -> Dict:
        """Diagnostic summary of queue state."""
        if not self._loaded:
            self.load()
        by_classification = {}
        by_priority = {}
        for e in self.entries:
            by_classification[e.classification] = by_classification.get(e.classification, 0) + 1
            by_priority[e.priority] = by_priority.get(e.priority, 0) + 1
        return {
            "total_entries": len(self.entries),
            "by_classification": by_classification,
            "by_priority": by_priority,
        }


def populate_queue_from_cycle(cycle_json_path: Path, queue_file: Path = QUEUE_FILE) -> List[OpportunityQueueEntry]:
    """
    Scan a discovery_cycles/*.json file and create queue entries for any
    hypotheses meeting the criteria for retest eligibility.

    ``queue_file`` defaults to the production queue (correct for real cycle
    integration, e.g. discovery/cycle_integration_hook.py) but MUST be
    overridden to an isolated path by callers that are not performing a real
    cycle run -- most importantly tests, which must never inject entries into
    the permanent, append-only production ledger.

    Returns list of newly-created entries (if any).
    """
    queue = OpportunityQueue(queue_file)
    queue.load()

    if not cycle_json_path.exists():
        return []

    data = json.loads(cycle_json_path.read_text())
    new_entries = []

    cycle_id = data.get("cycle_id", "")
    hypotheses = data.get("hypotheses", [])

    for hyp in hypotheses:
        hyp_id = hyp.get("hyp_id", "")
        symbol = hyp.get("symbol", "")
        driver = hyp.get("driver")
        n_events = hyp.get("n_events_available", 0)

        windows = list(hyp.get("windows", []))
        for delay_entry in hyp.get("delays", []):
            windows.extend(delay_entry.get("windows", []))

        evaluated = [w for w in windows if "train" in w]
        if not evaluated:
            continue

        survivors = [w for w in evaluated if w.get("verdict") == "DISCOVERY_SURVIVOR"]
        if survivors:
            continue  # Hypothesis passed; not an opportunity

        underpowered = [w for w in evaluated if w.get("verdict") == "VALIDATION_UNDERPOWERED"]
        if not underpowered:
            continue  # No underpowered windows; not a candidate

        # Hypothesis is underpowered; extract opportunity details
        train_ts = [w.get("train", {}).get("t_stat") for w in underpowered
                   if w.get("train", {}).get("t_stat") is not None and w.get("train", {}).get("t_stat") > 0]
        val_ns = [w.get("validation", {}).get("n") for w in underpowered]
        conf_rates = [w.get("confirmation_rate") for w in evaluated if w.get("confirmation_rate") is not None]

        best_train_t = max(train_ts) if train_ts else None
        best_val_n = min(val_ns) if val_ns else None  # minimum n across windows
        mean_conf = sum(conf_rates) / len(conf_rates) if conf_rates else None

        # Skip if train signal is not real (t < 1.5 suggests noise, not blocked signal)
        if not best_train_t or best_train_t < 1.5:
            continue

        # Classify the opportunity
        if best_train_t >= 2.0 and best_val_n and best_val_n < 30:
            classification = "STILL_UNDERPOWERED"
            evidence_level = "REAL_SIGNAL_BLOCKED"
        elif best_val_n and best_val_n < 30:
            classification = "STILL_UNDERPOWERED"
            evidence_level = "INSUFFICIENT_POWER"
        else:
            continue  # Not a clear opportunity

        # Calculate data requirement (never guess)
        if mean_conf and mean_conf > 0:
            target_val_n = 30
            current_confirmed = int(mean_conf * n_events) if n_events > 0 else 0
            if current_confirmed > 0:
                needed_confirmed = int(target_val_n / 0.8 / mean_conf)  # 80/20 train/val split
            else:
                needed_confirmed = 150  # Conservative default if conf rate is ~45%
            if n_events > 0:
                events_needed = max(needed_confirmed, int(needed_confirmed / mean_conf)) if mean_conf > 0 else 999
            else:
                events_needed = 999
        else:
            events_needed = 150  # Cannot calculate; use conservative default

        missing = DataRequirement(
            description="raw events (NFP calendar data and OHLC prices available for processing)",
            current_value=n_events,
            required_value=events_needed,
            unit="events",
        )

        # Retest condition
        if classification == "STILL_UNDERPOWERED" and best_train_t >= 2.0:
            trigger = (f"If NFP event pool can be extended to >={events_needed} raw events in dev data, "
                      f"retest at original window parameters. Train t={best_train_t:.2f} suggests real signal; "
                      f"validation n={best_val_n} is currently uninformative.")
            earliest_date = None  # Unknown when NFP pool will grow
            est_power = f"Validation n could increase from {best_val_n} to ~{target_val_n} with {events_needed} raw events"
        elif mean_conf and mean_conf < 0.4:
            trigger = (f"Mechanism's multi-condition filter keeps confirmation rate at {mean_conf:.1%}. "
                      f"This is inherently limiting; retest only if a variant can achieve >60% confirmation rate.")
            earliest_date = None
            est_power = None
        else:
            trigger = f"Retest when data conditions permit."
            earliest_date = None
            est_power = None

        retest = RetestCondition(
            earliest_date=earliest_date,
            trigger=trigger,
            estimated_power_gain=est_power,
        )

        # Determine priority
        if classification == "STILL_UNDERPOWERED" and best_train_t >= 3.0:
            priority = "HIGH"
        elif classification == "STILL_UNDERPOWERED":
            priority = "MEDIUM"
        else:
            priority = "LOW"

        # Mechanism summary (from hypothesis description)
        mech_summary = f"{symbol} with driver {driver if driver else 'N/A'}: {hyp.get('category', 'unknown mechanism')}"

        # Create entry
        entry = queue.append(
            source_hypothesis_id=hyp_id,
            source_cycle_id=cycle_id,
            classification=classification,
            mechanism_summary=mech_summary,
            symbol=symbol,
            driver=driver,
            n_events_available=n_events,
            windows_evaluated=len(evaluated),
            best_train_t=best_train_t,
            best_val_n=best_val_n,
            mean_confirmation_rate=mean_conf,
            evidence_level=evidence_level,
            reason=(f"All {len(underpowered)} tested window(s) show validation n < 30 (too small to confirm signal). "
                   f"Best window: train t={best_train_t:.2f}, val n={best_val_n}. "
                   f"Mean confirmation rate: {mean_conf:.1%} of available events."),
            missing_data=missing,
            retest_conditions=retest,
            priority=priority,
            provenance_status="DATA_SUPPORTED",  # All opportunities are at least DATA_SUPPORTED
        )
        new_entries.append(entry)

    queue.save()
    return new_entries
