"""CLI surface, including the commands that deliberately do not exist."""

from __future__ import annotations

import json

import pytest

from idea_machine.cli import build_parser, main


def base_args(tmp_path, corpus_dir, catalog_file):
    return [
        "--root", str(tmp_path / "ledgers"),
        "--corpus", str(corpus_dir),
        "--catalog", str(catalog_file),
    ]


def test_cycle_runs_and_reports(tmp_path, corpus_dir, catalog_file, capsys):
    assert main(base_args(tmp_path, corpus_dir, catalog_file) + ["cycle"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["funnel"]["submitted"] > 0


def test_no_submit_designs_without_handing_off(tmp_path, corpus_dir, catalog_file, capsys):
    main(base_args(tmp_path, corpus_dir, catalog_file) + ["cycle", "--no-submit"])
    report = json.loads(capsys.readouterr().out)
    assert report["funnel"]["designed"] > 0
    assert report["funnel"]["submitted"] == 0


def test_cycle_writes_handoff_files_under_the_given_root(tmp_path, corpus_dir, catalog_file, capsys):
    main(base_args(tmp_path, corpus_dir, catalog_file) + ["cycle"])
    capsys.readouterr()
    handoff = tmp_path / "ledgers" / "handoff"
    assert handoff.exists()
    files = list(handoff.glob("EXP-*.json"))
    assert files
    payload = json.loads(files[0].read_text())
    assert payload["experiment"]["frozen"] is True
    assert payload["preregistration_checksum"]


def test_status_and_dashboard_and_verify(tmp_path, corpus_dir, catalog_file, capsys):
    args = base_args(tmp_path, corpus_dir, catalog_file)
    main(args + ["cycle"])
    capsys.readouterr()

    assert main(args + ["status"]) == 0
    json.loads(capsys.readouterr().out)

    assert main(args + ["dashboard", "--json"]) == 0
    json.loads(capsys.readouterr().out)

    assert main(args + ["dashboard"]) == 0
    assert "WHERE ARE WE SEARCHING?" in capsys.readouterr().out

    assert main(args + ["verify"]) == 0
    assert "OK" in capsys.readouterr().out


def test_governance_command_lists_the_boundary(capsys):
    assert main(["governance"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "READ_HOLDOUT" in report["forbidden_actions"]
    assert "GEN14 authorization" in report["human_authority"]
    assert report["static_audit_findings"] == []


def test_ingest_applies_factory_verdicts(tmp_path, corpus_dir, catalog_file, capsys):
    args = base_args(tmp_path, corpus_dir, catalog_file)
    main(args + ["cycle"])
    report = json.loads(capsys.readouterr().out)

    results = [
        {
            "experiment_id": exp_id,
            "idea_id": json.loads((tmp_path / "ledgers" / "handoff" / f"{exp_id}.json").read_text())[
                "experiment"
            ]["idea_id"],
            "verdict": "FAIL",
            "evidence_reference": "reports/factory/cycle.md#e1",
            "reason": "effect below cost",
        }
        for exp_id in report["submitted_experiments"]
    ]
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps(results))

    assert main(args + ["ingest", str(results_file)]) == 0
    outcomes = json.loads(capsys.readouterr().out)
    assert outcomes
    assert all(o["verdict"] == "FAIL" for o in outcomes)


def test_an_empty_catalog_is_the_default(tmp_path, corpus_dir, capsys):
    """Running without --catalog must block, not assume data exists."""
    main(["--root", str(tmp_path / "l"), "--corpus", str(corpus_dir), "cycle"])
    report = json.loads(capsys.readouterr().out)
    assert report["funnel"]["submitted"] == 0


@pytest.mark.parametrize("forbidden", ["holdout", "gen14", "authorize", "deploy", "ea", "generate-ea"])
def test_forbidden_commands_do_not_exist(forbidden):
    """There is no CLI path to the operations Phase 16 forbids."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([forbidden])
