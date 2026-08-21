"""agle.py service/watchdog CLI: real subprocess invocations of the actual
CLI (a fresh interpreter each time), proving the "Absolute Safety Rule"
that service lifecycle commands never touch the Master Switch, and that
the platform-aware install/uninstall behave honestly on a non-Windows host
(never fabricate a successful installation).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "AGLE_SWITCH_STATE_PATH": str(tmp_path / "switch.json"),
        "AGLE_SWITCH_AUDIT_PATH": str(tmp_path / "audit.json"),
        "AGLE_WATCHDOG_LOCK_PATH": str(tmp_path / "watchdog.lock"),
        "AGLE_SERVICE_LOG_PATH": str(tmp_path / "service_log.json"),
    }


def _run(args, env, timeout=30):
    return subprocess.run([sys.executable, "agle.py", *args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, env=env, timeout=timeout)


def test_service_status_never_touches_switch_file(tmp_path):
    env = _env(tmp_path)
    switch_path = tmp_path / "switch.json"
    assert not switch_path.exists()
    result = _run(["service", "status"], env)
    assert "AGLE SERVICE" in result.stdout
    assert not switch_path.exists(), "service status must never create/modify the switch file"


def test_service_stop_when_not_running_never_touches_switch(tmp_path):
    env = _env(tmp_path)
    switch_path = tmp_path / "switch.json"
    switch_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    before = switch_path.read_bytes()
    result = _run(["service", "stop"], env)
    assert result.returncode == 0
    assert switch_path.read_bytes() == before


def test_service_install_on_this_platform_is_honest(tmp_path):
    """This test runs on Linux -- install must clearly report it is not
    supported here, never fabricate success."""
    import platform
    if platform.system() == "Windows":
        pytest.skip("this test asserts non-Windows behavior")
    env = _env(tmp_path)
    result = _run(["service", "install"], env)
    assert result.returncode != 0
    assert "NOT SUPPORTED" in result.stdout


def test_service_uninstall_on_this_platform_is_honest(tmp_path):
    import platform
    if platform.system() == "Windows":
        pytest.skip("this test asserts non-Windows behavior")
    env = _env(tmp_path)
    result = _run(["service", "uninstall"], env)
    assert result.returncode != 0
    assert "NOT SUPPORTED" in result.stdout


def test_watchdog_cli_wiring_bounded(tmp_path):
    """`agle.py watchdog --max-iterations 1` with the switch OFF must exit
    promptly (idle poll, one iteration) and never touch anything beyond
    its own lock/log files."""
    env = _env(tmp_path)
    switch_path = tmp_path / "switch.json"
    switch_path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "agle.py", "watchdog", "--max-iterations", "1"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0
    payload_start = result.stdout.index("{")
    payload = json.loads(result.stdout[payload_start:])
    assert payload["started"] is True
    assert payload["iterations"] == 1
