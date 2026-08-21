"""Regression tests for a real bug found while verifying AGLE HEALTH's live
audit: several idea_machine `load()` methods appended to in-memory lists
without resetting them first. Since ProductionSupervisor.recover_state()
calls AutonomousIdeaMachine.load() on every cycle, reusing ONE persistent
AutonomousIdeaMachine instance across a whole run_forever() invocation, this
silently doubled state on every single cycle. Found live: the real
reports/idea_machine/opportunity_queue.json had grown from 85 genuine
entries to 1360 duplicate rows (85 * 16, i.e. four repeated-load
compounding events) purely from today's session's multi-cycle `agle.py run`
invocations -- no new opportunities were ever genuinely proposed in that
window (every cycle's real still_underpowered count was 0).

Fixed in:
  - idea_machine/opportunity_queue.py (OpportunityQueue.load) -- the one
    that actually corrupted a persisted, committed file.
  - idea_machine/research_memory.py (ResearchMemory.load) -- in-memory only.
  - idea_machine/ea_code_intel/novelty_engine.py (NoveltyEngine.load) --
    in-memory only; this is the NoveltyEngine class AutonomousIdeaMachine
    actually imports and uses.
  - idea_machine/semantic_novelty.py (SemanticNoveltyEngine.load) -- a
    differently-scoped class with the same defect, fixed for consistency
    even though it is not on AutonomousIdeaMachine's hot path.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from idea_machine.opportunity_queue import DataRequirement, OpportunityQueue, RetestCondition


def _entry_kwargs(n: int) -> dict:
    return dict(
        source_hypothesis_id=f"HYP-{n}", source_cycle_id="CYCLE-TEST", classification="STILL_UNDERPOWERED",
        mechanism_summary="test", symbol="EURUSD", driver=None, n_events_available=1, windows_evaluated=1,
        best_train_t=1.0, best_val_n=1, mean_confirmation_rate=0.5, evidence_level="LOW", reason="r",
        missing_data=DataRequirement(description="d", current_value=1, required_value=1, unit="u"),
        retest_conditions=RetestCondition(earliest_date=None, trigger="t", estimated_power_gain=None),
        priority="LOW", provenance_status="TEST_FIXTURE",
    )


def test_opportunity_queue_repeated_load_does_not_duplicate(tmp_path):
    qf = tmp_path / "q.json"
    q = OpportunityQueue(queue_file=qf)
    q.append(**_entry_kwargs(1))
    q.save()
    assert len(q.entries) == 1

    # Simulate ProductionSupervisor.recover_state() calling load() again on
    # the SAME instance, once per cycle, several times in a row.
    for _ in range(5):
        q.load()
    assert len(q.entries) == 1, "repeated load() must not duplicate entries"

    q.save()
    reloaded = OpportunityQueue(queue_file=qf)
    reloaded.load()
    assert len(reloaded.entries) == 1


def test_opportunity_queue_repeated_load_preserves_next_id_correctness(tmp_path):
    qf = tmp_path / "q.json"
    q = OpportunityQueue(queue_file=qf)
    q.append(**_entry_kwargs(1))
    q.save()
    for _ in range(3):
        q.load()
    q.append(**_entry_kwargs(2))
    q.save()
    ids = sorted(e.queue_id for e in q.entries)
    assert ids == ["OPP-000001", "OPP-000002"], f"unexpected ids after repeated load: {ids}"


def test_research_memory_repeated_load_does_not_duplicate_cycle_hypotheses(monkeypatch, tmp_path):
    import idea_machine.research_memory as rm_module

    cycles_dir = tmp_path / "discovery_cycles"
    cycles_dir.mkdir(parents=True)
    (cycles_dir / "cycle_0001.json").write_text(json.dumps({
        "hypotheses": [{
            "hyp_id": "HYP-X", "windows": [{"verdict": "VALIDATION_UNDERPOWERED", "train": {"t_stat": 2.0}}],
        }]
    }), encoding="utf-8")
    monkeypatch.setattr(rm_module, "CYCLES_DIR", cycles_dir)
    monkeypatch.setattr(rm_module, "FAMILY_REGISTRY", tmp_path / "no_such_family_registry.json")
    monkeypatch.setattr(rm_module, "CANDIDATE_REGISTRY", tmp_path / "no_such_candidate_registry.json")

    memory = rm_module.ResearchMemory()
    memory.load()
    count_after_first = len(memory.cycle_hypotheses)
    assert count_after_first == 1
    for _ in range(4):
        memory.load()
    assert len(memory.cycle_hypotheses) == 1, "repeated load() must not duplicate cycle_hypotheses"


def test_ea_code_intel_novelty_engine_repeated_load_does_not_duplicate(monkeypatch, tmp_path):
    import idea_machine.ea_code_intel.novelty_engine as ne_module

    registry = tmp_path / "research_family_registry.json"
    registry.write_text(json.dumps({
        "families": {"FAM-1": {"family_id": "FAM-1", "status": "REFUTED", "description": "streak fade EURUSD"}}
    }), encoding="utf-8")
    monkeypatch.setattr(ne_module, "FAMILY_REGISTRY", registry)

    engine = ne_module.NoveltyEngine()
    for _ in range(5):
        engine.load()
    assert len(engine.all_families) == 1, "repeated load() must not duplicate all_families"
    assert len(engine.refuted_families) == 1, "repeated load() must not duplicate refuted_families"


def test_semantic_novelty_engine_repeated_load_does_not_duplicate(monkeypatch, tmp_path):
    import idea_machine.semantic_novelty as sn_module

    registry = tmp_path / "research_family_registry.json"
    registry.write_text(json.dumps({
        "families": {"FAM-2": {"family_id": "FAM-2", "status": "STILL_UNDERPOWERED", "description": "gap fade XAUUSD"}}
    }), encoding="utf-8")
    monkeypatch.setattr(sn_module, "REPO_ROOT", tmp_path)
    # sn_module builds the path as REPO_ROOT / "reports/factory/research_family_registry.json"
    (tmp_path / "reports" / "factory").mkdir(parents=True)
    (tmp_path / "reports" / "factory" / "research_family_registry.json").write_text(
        registry.read_text(), encoding="utf-8"
    )

    engine = sn_module.SemanticNoveltyEngine()
    for _ in range(5):
        engine.load()
    assert len(engine.underpowered_mechanisms) == 1, "repeated load() must not duplicate underpowered_mechanisms"
    assert len(engine.research_memory) == 1


def test_autonomous_idea_machine_repeated_load_does_not_duplicate_opportunity_queue(tmp_path):
    """End-to-end proof matching the exact real-world trigger: repeated
    AutonomousIdeaMachine.load() calls on one persistent instance (what
    ProductionSupervisor.recover_state() does every cycle) must never
    duplicate the opportunity queue."""
    from idea_machine.autonomous_loop import AutonomousIdeaMachine

    machine = AutonomousIdeaMachine()
    isolated_queue = OpportunityQueue(queue_file=tmp_path / "opp.json")
    isolated_queue.append(**_entry_kwargs(1))
    isolated_queue.save()
    machine.opportunity_queue = isolated_queue

    for _ in range(6):
        machine.load()
    assert len(machine.opportunity_queue.entries) == 1, (
        "repeated AutonomousIdeaMachine.load() (as recover_state() performs every cycle) "
        "must not duplicate the opportunity queue"
    )
