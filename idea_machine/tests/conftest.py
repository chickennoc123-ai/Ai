"""Shared fixtures. Every test runs against a tmp_path root — no test touches
the real ledgers under ``reports/idea_machine``, and none touches any Strategy
Factory data."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from idea_machine.economics.data_feasibility import DataCatalog, DatasetEntry
from idea_machine.governance import guard
from idea_machine.integration.factory_bridge import InMemorySubmitter
from idea_machine.knowledge.base import ConceptEdge, KnowledgeBase
from idea_machine.pipeline import IdeaMachine
from idea_machine.scanner.scanner import InMemoryProvider, WorldScanner

DOCS = [
    {
        "reference": "doi:10.1/a",
        "title": "NFP surprises and the dollar",
        "domain": "ACADEMIC",
        "origin_kind": "ACADEMIC_PAPER",
        "source": "JFE",
        "text": (
            "A large NFP surprise moves the US dollar and gold within the hour. "
            "The effect is stronger in a high volatility regime."
        ),
    },
    {
        "reference": "doi:10.1/b",
        "title": "Turn of month flows",
        "domain": "SEASONALITY",
        "origin_kind": "ACADEMIC_PAPER",
        "source": "JF",
        "text": "Turn of the month rebalancing creates predictable order flow in equities and the us dollar.",
    },
    {
        "reference": "doi:10.1/c",
        "title": "Volatility regimes and gold",
        "domain": "VOLATILITY_RESEARCH",
        "origin_kind": "WORKING_PAPER",
        "source": "SSRN",
        "text": "Implied volatility predicts gold returns; the variance risk premium is wide in a high volatility regime.",
    },
    {
        "reference": "doi:10.1/d",
        "title": "The London open",
        "domain": "MICROSTRUCTURE",
        "origin_kind": "WORKING_PAPER",
        "source": "SSRN",
        "text": (
            "At the london open the bid-ask spread in the us dollar widens and order flow "
            "imbalance predicts short horizon returns."
        ),
    },
]

_DATASETS = (
    "event_calendar_actual_consensus", "target_ohlcv_m15", "driver_ohlcv_h1", "target_ohlcv_h1",
    "target_ohlcv_d1", "calendar_definition", "driver_series", "target_ohlcv_h4",
    "conditioner_series", "target_ohlcv_m30", "session_definition", "implied_vol_series",
    "positioning_report", "instrument:EURUSD", "instrument:GBPUSD", "instrument:XAUUSD",
    "instrument:US500", "conditioner_series:VOLATILITY_REGIME",
    "conditioner_series:IMPLIED_VOLATILITY", "confirmation_series:GOLD",
    "confirmation_series:USD", "lead_series:GOLD", "lead_series:USD",
)


def make_dataset(dataset_id: str, *, rows: int = 30_000) -> DatasetEntry:
    return DatasetEntry(
        dataset_id=dataset_id,
        description=dataset_id,
        timeframe="H1",
        timestamp_precision="1s",
        timezone="UTC",
        coverage_start="2015-01-01",
        coverage_end="2025-12-31",
        row_count=rows,
        missing_data_pct=0.1,
        survivorship_bias_assessed=True,
        has_cost_data=True,
        execution_assumptions_documented=True,
    )


@pytest.fixture
def catalog() -> DataCatalog:
    return DataCatalog([make_dataset(d) for d in _DATASETS])


@pytest.fixture
def empty_catalog() -> DataCatalog:
    return DataCatalog()


@pytest.fixture
def provider() -> InMemoryProvider:
    return InMemoryProvider(DOCS)


@pytest.fixture
def scanner(tmp_path, provider) -> WorldScanner:
    return WorldScanner(ledger_path=tmp_path / "sources.json", providers=[provider])


@pytest.fixture
def knowledge(tmp_path, scanner) -> KnowledgeBase:
    """A knowledge base seeded from the fixture corpus, with supporting edges."""
    kb = KnowledgeBase(tmp_path / "knowledge.json")
    records = scanner.scan()
    for record in records:
        kb.ingest_source(record)
    by_ref = {r.reference: r.source_id for r in records}
    kb.assert_edge(ConceptEdge("NFP", "AFFECTS", "USD", (by_ref["doi:10.1/a"],)))
    kb.assert_edge(ConceptEdge("NFP", "AFFECTS", "GOLD", (by_ref["doi:10.1/a"],)))
    kb.assert_edge(ConceptEdge("TURN_OF_MONTH", "AFFECTS", "EQUITIES", (by_ref["doi:10.1/b"],)))
    kb.assert_edge(ConceptEdge("TURN_OF_MONTH", "AFFECTS", "USD", (by_ref["doi:10.1/b"],)))
    kb.assert_edge(ConceptEdge("VOLATILITY_REGIME", "CONDITIONS", "GOLD", (by_ref["doi:10.1/c"],)))
    kb.assert_edge(ConceptEdge("SESSION_BOUNDARY", "AFFECTS", "USD", (by_ref["doi:10.1/d"],)))
    return kb


@pytest.fixture
def submitter() -> InMemorySubmitter:
    return InMemorySubmitter()


@pytest.fixture
def machine(tmp_path, provider, catalog, submitter) -> IdeaMachine:
    return IdeaMachine(
        root=tmp_path / "ledgers",
        providers=[provider],
        catalog=catalog,
        submitter=submitter,
    )


@pytest.fixture
def audit(tmp_path):
    """Route governance audit rows into a temp ledger for the duration of a test."""
    a = guard.GovernanceAudit(tmp_path / "gov_audit.json")
    guard.set_audit(a)
    yield a
    guard.set_audit(None)


@pytest.fixture
def corpus_dir(tmp_path) -> Path:
    d = tmp_path / "corpus"
    d.mkdir()
    for i, doc in enumerate(DOCS):
        (d / f"doc{i}.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


@pytest.fixture
def catalog_file(tmp_path, catalog) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([asdict(e) for e in catalog.all()]), encoding="utf-8")
    return path
