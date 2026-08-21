"""
Integration hook: after each discovery cycle completes, update the Idea Machine's
research memory with the new findings.

This is called by the Factory after a cycle's JSON is written, before the user
is notified of results.
"""

from pathlib import Path
import sys

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from idea_machine.opportunity_queue import QUEUE_FILE, populate_queue_from_cycle


def update_research_memory_after_cycle(cycle_json_path: Path, queue_file: Path = QUEUE_FILE) -> dict:
    """
    Called after a discovery_cycles/*.json file is written.
    Updates the opportunity queue and returns a summary.

    ``queue_file`` defaults to the production queue (correct when the real
    Factory calls this after a real cycle) but must be overridden to an
    isolated path by any caller that is not performing a real cycle run --
    most importantly tests.
    """
    new_entries = populate_queue_from_cycle(cycle_json_path, queue_file=queue_file)
    return {
        "cycle_file": str(cycle_json_path),
        "new_opportunities_created": len(new_entries),
        "opportunity_ids": [e.queue_id for e in new_entries],
    }
