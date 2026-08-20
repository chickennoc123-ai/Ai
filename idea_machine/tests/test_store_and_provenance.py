"""Append-only store, ledger-reset resistance, and scanner provenance."""

from __future__ import annotations

import json

import pytest

from idea_machine.core.errors import StoreError
from idea_machine.core.store import AppendOnlyStore
from idea_machine.scanner.extract import concept_names, extract_concepts, register_concept
from idea_machine.scanner.scanner import InMemoryProvider, ScannerError, WorldScanner


# ------------------------------------------------------------ append-only store


def test_store_appends_and_persists(tmp_path):
    store = AppendOnlyStore(tmp_path / "s.json", id_field="id")
    store.append({"id": "A", "v": 1})
    store.append({"id": "B", "v": 2})
    assert AppendOnlyStore(tmp_path / "s.json", id_field="id").count() == 2


def test_appending_identical_content_is_idempotent(tmp_path):
    store = AppendOnlyStore(tmp_path / "s.json", id_field="id")
    store.append({"id": "A", "v": 1})
    store.append({"id": "A", "v": 1})
    assert store.count() == 1


def test_rewriting_history_is_refused(tmp_path):
    store = AppendOnlyStore(tmp_path / "s.json", id_field="id")
    store.append({"id": "A", "v": 1})
    with pytest.raises(StoreError) as exc:
        store.append({"id": "A", "v": 999})
    assert "never rewrite history" in str(exc.value)


def test_store_refuses_to_shrink(tmp_path):
    """The ledger-reset defence: a smaller ledger can never overwrite a larger one."""
    path = tmp_path / "s.json"
    first = AppendOnlyStore(path, id_field="id")
    first.append_many([{"id": "A"}, {"id": "B"}, {"id": "C"}])

    # A second, ignorant writer holding only one record must not clobber three.
    second = AppendOnlyStore(path, id_field="id", autoload=False)
    second._records = [{"id": "Z"}]
    second._index = {"Z": 0}
    with pytest.raises(StoreError) as exc:
        second._save()
    assert "shrink" in str(exc.value)


def test_integrity_check_detects_external_tampering(tmp_path):
    path = tmp_path / "s.json"
    store = AppendOnlyStore(path, id_field="id")
    store.append_many([{"id": "A"}, {"id": "B"}])
    store.verify_integrity()

    payload = json.loads(path.read_text())
    payload["records"] = payload["records"][:1]
    path.write_text(json.dumps(payload))

    with pytest.raises(StoreError) as exc:
        store.verify_integrity()
    assert "history appears to have been edited" in str(exc.value)


def test_store_rejects_a_record_without_an_id(tmp_path):
    store = AppendOnlyStore(tmp_path / "s.json", id_field="id")
    with pytest.raises(StoreError):
        store.append({"no_id": 1})


def test_corrupt_store_is_reported_not_silently_emptied(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    with pytest.raises(StoreError):
        AppendOnlyStore(path, id_field="id")


# --------------------------------------------------------------- extraction


def test_extraction_is_deterministic():
    text = "A large NFP surprise moves the US 10-year yield and gold in a high volatility regime."
    assert concept_names(text) == concept_names(text)
    assert "NFP" in concept_names(text)


def test_extraction_records_the_phrase_that_matched():
    matches = extract_concepts("The turn of the month effect is strong in equities.")
    by_name = {m.concept: m for m in matches}
    assert by_name["TURN_OF_MONTH"].matched_phrase in ("turn of the month", "turn-of-month", "month-end")
    assert "turn of the month" in by_name["TURN_OF_MONTH"].context.lower()


def test_extraction_cannot_invent_a_concept():
    """A controlled vocabulary cannot hallucinate something absent from the text."""
    assert concept_names("The weather in Lisbon is pleasant this time of year.") == ()


def test_vocabulary_is_extensible():
    register_concept("TEST_CONCEPT", "MACRO", ("widget spread",))
    assert "TEST_CONCEPT" in concept_names("The widget spread is unusually wide.")


# ------------------------------------------------------------------- scanner


def test_scanner_assigns_idea_source_only_authority(scanner):
    for record in scanner.scan():
        assert record.provenance().authority == "IDEA_SOURCE_ONLY"


def test_rescanning_unchanged_sources_is_idempotent(tmp_path):
    from idea_machine.tests.conftest import DOCS

    provider = InMemoryProvider(DOCS)
    first = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    a = first.scan()
    second = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    b = second.scan()
    assert second.store.count() == len(DOCS)
    assert [r.source_id for r in a] == [r.source_id for r in b]


def test_rescanning_preserves_the_first_seen_timestamp(tmp_path):
    from idea_machine.tests.conftest import DOCS

    provider = InMemoryProvider(DOCS)
    first = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    original = {r.source_id: r.retrieved_at for r in first.scan()}
    second = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    for record in second.scan():
        assert record.retrieved_at == original[record.source_id]


def test_scanner_rejects_a_document_with_no_text(tmp_path):
    provider = InMemoryProvider([{"reference": "r", "title": "t"}])
    scanner = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    with pytest.raises(ScannerError):
        scanner.scan()


def test_scanner_rejects_a_document_with_no_reference(tmp_path):
    provider = InMemoryProvider([{"title": "t", "text": "NFP surprise"}])
    scanner = WorldScanner(ledger_path=tmp_path / "s.json", providers=[provider])
    with pytest.raises(ScannerError):
        scanner.scan()


def test_source_record_carries_concept_evidence(scanner):
    records = {r.reference: r for r in scanner.scan()}
    evidence = records["doi:10.1/a"].metadata["concept_evidence"]
    assert "NFP" in evidence
    assert evidence["NFP"]["phrase"]
    assert evidence["NFP"]["context"]
