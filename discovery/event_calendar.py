"""
Macro event calendar loader + quality gates (EVENT-CONTRACT-V1).

Nothing in GEN 7-13 may read the sealed holdout, and that applies to event data
as much as to price data: an event row whose timestamp lands in the holdout
window is dropped by the loader, not merely ignored downstream.

The seven gates are the ones written in data/events/EVENT_DATA_CONTRACT.md.
They exist because FAIL-000030 showed what a mis-stamped timestamp does to this
pipeline: it manufactures an apparent edge with t = 7.
"""

import csv
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery._guards import guard_path

REQUIRED = ("timestamp_utc", "event_id", "event_name", "country", "currency",
            "impact", "source")
OPTIONAL = ("actual", "forecast", "previous", "revision")
IMPACTS = ("HIGH", "MEDIUM", "LOW")
MIN_INSTANCES = 30
MIN_COVERAGE_FRACTION = 0.80


class EventDataError(RuntimeError):
    """Raised when a calendar fails a contract gate."""


@dataclass
class MacroEvent:
    ts: datetime
    event_id: str
    name: str
    country: str
    currency: str
    impact: str
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    revision: Optional[float] = None
    source: str = ""

    @property
    def surprise(self) -> Optional[float]:
        """actual - forecast, or None when either side is missing."""
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


def _num(v) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_events(path: Path, dev_end: Optional[datetime] = None) -> List[MacroEvent]:
    """
    Load a calendar and apply gates G-E1..G-E3 and the holdout cut.

    dev_end: last timestamp of the development window. Events at or after it
    are dropped -- discovery never sees holdout-period events.
    """
    path = guard_path(path)
    if not Path(path).exists():
        raise EventDataError(f"no event calendar at {path}")

    rows = list(csv.DictReader(open(path, "r", encoding="utf-8")))
    if not rows:
        raise EventDataError(f"{path} is empty")

    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:                                                    # G-E1
        raise EventDataError(f"missing required columns: {missing}")

    events, seen = [], set()
    for i, r in enumerate(rows):
        raw_ts = (r.get("timestamp_utc") or "").strip()
        if not raw_ts:                                             # G-E2
            raise EventDataError(f"row {i}: empty timestamp_utc")
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as e:
            raise EventDataError(f"row {i}: unparseable timestamp {raw_ts!r} ({e})")
        eid = r["event_id"].strip()
        if eid in seen:                                            # G-E3
            raise EventDataError(f"duplicate event_id {eid!r}")
        seen.add(eid)
        impact = r["impact"].strip().upper()
        if impact not in IMPACTS:
            raise EventDataError(f"row {i}: impact {impact!r} not in {IMPACTS}")
        if dev_end is not None and ts >= dev_end:
            continue                                               # holdout cut
        events.append(MacroEvent(
            ts=ts, event_id=eid, name=r["event_name"].strip(),
            country=r["country"].strip(), currency=r["currency"].strip().upper(),
            impact=impact, actual=_num(r.get("actual")),
            forecast=_num(r.get("forecast")), previous=_num(r.get("previous")),
            revision=_num(r.get("revision")), source=r["source"].strip()))
    events.sort(key=lambda e: e.ts)
    return events


def audit(events: List[MacroEvent], dev_start: datetime,
          dev_end: datetime) -> Dict:
    """Gates G-E4..G-E7. Returns a report; never raises."""
    if not events:
        return {"passed": False, "reason": "no events after the holdout cut"}

    minutes = Counter(e.ts.minute for e in events)
    top_minute, top_count = minutes.most_common(1)[0]
    minute_concentration = top_count / len(events)
    ge4 = minute_concentration >= 0.30            # scheduled releases cluster

    # G-E5: a real UTC calendar shifts an event's hour across DST boundaries
    by_name: Dict[str, set] = {}
    for e in events:
        by_name.setdefault(e.name, set()).add(e.ts.hour)
    multi = {k: sorted(v) for k, v in by_name.items() if len(v) > 1}
    recurring = {k: v for k, v in by_name.items()
                 if sum(1 for e in events if e.name == k) >= 12}
    ge5 = (not recurring) or bool(set(multi) & set(recurring))

    span = (dev_end - dev_start).total_seconds()
    covered = (events[-1].ts - events[0].ts).total_seconds()
    ge6 = span > 0 and covered / span >= MIN_COVERAGE_FRACTION

    counts = Counter(e.name for e in events)
    usable = {k: v for k, v in counts.items() if v >= MIN_INSTANCES}
    ge7 = bool(usable)

    return {
        "passed": bool(ge4 and ge5 and ge6 and ge7),
        "events": len(events),
        "window": {"start": events[0].ts.isoformat(), "end": events[-1].ts.isoformat()},
        "gates": {
            "G-E4_release_minute_clustering": {
                "pass": ge4, "dominant_minute": top_minute,
                "concentration": round(minute_concentration, 3),
                "note": "flat minute distribution indicates import-stamped times"},
            "G-E5_dst_shift_present": {
                "pass": ge5, "events_with_multiple_utc_hours": len(multi),
                "recurring_event_types": len(recurring)},
            "G-E6_dev_window_coverage": {
                "pass": ge6, "covered_fraction": round(covered / span, 3) if span else 0.0,
                "required": MIN_COVERAGE_FRACTION},
            "G-E7_sufficient_instances": {
                "pass": ge7, "event_types_with_30_plus": len(usable),
                "top": counts.most_common(10)},
        },
        "impact_distribution": dict(Counter(e.impact for e in events)),
        "currency_distribution": dict(Counter(e.currency for e in events).most_common(10)),
        "surprise_available": sum(1 for e in events if e.surprise is not None),
    }
