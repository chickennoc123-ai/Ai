import pytest

from idea_machine.opportunity_queue import OpportunityQueue
from idea_machine.research_memory import ResearchMemory
from idea_machine.search_decision_ledger import SearchDecisionLedger
from idea_machine.search_space_registry import SearchSpaceRegistry


@pytest.fixture
def memory() -> ResearchMemory:
    m = ResearchMemory()
    m.load()
    return m


@pytest.fixture
def registry(memory) -> SearchSpaceRegistry:
    return SearchSpaceRegistry(memory)


@pytest.fixture
def decision_ledger(tmp_path) -> SearchDecisionLedger:
    return SearchDecisionLedger(tmp_path / "sdl.json")


@pytest.fixture
def opportunity_queue(tmp_path) -> OpportunityQueue:
    q = OpportunityQueue(tmp_path / "opp.json")
    q.load()
    return q
