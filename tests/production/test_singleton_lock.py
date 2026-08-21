"""production.singleton_lock.SingleInstanceLock: the mandatory duplicate-
process-protection mechanism (24/7 operations spec, "DUPLICATE PROCESS
PROTECTION"). Not process-list-based (race-prone); an OS-atomic
O_CREAT|O_EXCL file create, with crash-safe stale-lock reclaim via real PID
liveness.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from production.singleton_lock import DuplicateProcessError, SingleInstanceLock


def test_second_acquire_by_a_live_process_is_refused(tmp_path):
    path = tmp_path / "lock.json"
    l1 = SingleInstanceLock(path=path)
    r1 = l1.acquire()
    assert r1.acquired is True

    l2 = SingleInstanceLock(path=path)
    r2 = l2.acquire()
    assert r2.acquired is False
    assert r2.holder_pid is not None

    l1.release()
    r3 = l2.acquire()
    assert r3.acquired is True
    l2.release()


def test_stale_lock_from_a_dead_pid_is_reclaimed(tmp_path):
    path = tmp_path / "lock.json"
    path.write_text(json.dumps({"pid": 999999, "acquired_at": "x"}), encoding="utf-8")
    lock = SingleInstanceLock(path=path)
    result = lock.acquire()
    assert result.acquired is True
    lock.release()


def test_corrupt_lock_file_is_treated_as_stale_not_fatal(tmp_path):
    path = tmp_path / "lock.json"
    path.write_text("{ not json", encoding="utf-8")
    lock = SingleInstanceLock(path=path)
    result = lock.acquire()
    assert result.acquired is True
    lock.release()


def test_release_only_removes_a_lock_this_process_still_holds(tmp_path):
    path = tmp_path / "lock.json"
    lock = SingleInstanceLock(path=path)
    lock.acquire()
    # Simulate another process having since reclaimed the file (e.g. this
    # process was killed, someone else saw it as stale, reclaimed it) --
    # release() must not delete a lock it no longer actually owns.
    path.write_text(json.dumps({"pid": 999998, "acquired_at": "y"}), encoding="utf-8")
    lock._held = True  # force the release() path as if we still thought we held it
    lock.release()
    assert path.exists()
    assert json.loads(path.read_text())["pid"] == 999998


def test_context_manager_raises_duplicate_process_error(tmp_path):
    path = tmp_path / "lock.json"
    held = SingleInstanceLock(path=path)
    held.acquire()
    try:
        with pytest.raises(DuplicateProcessError):
            with SingleInstanceLock(path=path):
                pass
    finally:
        held.release()


def test_real_cross_process_mutual_exclusion(tmp_path):
    """Not just an in-process simulation: two REAL, separate OS processes
    both try to acquire the same lock file; exactly one must succeed."""
    path = tmp_path / "lock.json"
    script = (
        "import sys, time; "
        "sys.path.insert(0, %r); "
        "from production.singleton_lock import SingleInstanceLock; "
        "l = SingleInstanceLock(path=sys.argv[1]); "
        "r = l.acquire(); "
        "print('ACQUIRED' if r.acquired else 'REFUSED'); "
        "time.sleep(2) if r.acquired else None; "
        "l.release() if r.acquired else None"
    ) % str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent)

    p1 = subprocess.Popen([sys.executable, "-c", script, str(path)],
                          stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)  # let p1 win the race deterministically
    p2 = subprocess.Popen([sys.executable, "-c", script, str(path)],
                          stdout=subprocess.PIPE, text=True)

    out1, _ = p1.communicate(timeout=10)
    out2, _ = p2.communicate(timeout=10)

    results = {out1.strip(), out2.strip()}
    assert "ACQUIRED" in out1 or "ACQUIRED" in out2
    assert results == {"ACQUIRED", "REFUSED"}, f"expected exactly one winner, got: {out1!r} {out2!r}"
