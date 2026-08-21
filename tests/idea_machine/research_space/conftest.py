import pytest

from idea_machine.research_space.decision_record import DecisionLedger
from idea_machine.research_space.search_space import SearchSpace
from idea_machine.research_space.search_space_ledger import SearchSpaceLedger


@pytest.fixture
def search_space() -> SearchSpace:
    return SearchSpace()


@pytest.fixture
def decision_ledger(tmp_path) -> DecisionLedger:
    return DecisionLedger(tmp_path / "decisions.json")


@pytest.fixture
def space_ledger(tmp_path) -> SearchSpaceLedger:
    return SearchSpaceLedger(tmp_path / "space_ledger.json")
