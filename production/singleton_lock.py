"""Single-instance protection for the production loop.

Mandatory per the 24/7 operations spec: it must be impossible for "AGLE
Service + manual `python agle.py run` + another watchdog" to accidentally
run two production loops at once. A process-list check ("is agle.py
already in `ps`?") is race-prone -- two processes can both observe "no,
not running" in the same instant and both proceed. This uses an
OS-level-atomic file create (O_CREAT | O_EXCL) as the actual mutex: only
one process can ever win that syscall for a given path, on both POSIX and
Windows.

The lock is acquired ONCE, inside ProductionSupervisor.run_forever()
itself (not in agle.py, not in the watchdog) -- so every path that could
ever start a production loop, whether a human's manual `agle.py run`, a
`agle.py cycle`, or the watchdog's spawned child, funnels through the
exact same check. There is no second, parallel place a caller could bypass
it from.

Stale-lock recovery: if the process that acquired the lock has since died
(a real crash, not a graceful release), the lock file is a leftover, not a
live claim. Reused via production.process_utils.is_pid_alive -- the same
liveness check production/health.py already uses -- so "is this lock still
real" and "is that supervisor still running" are never answered by two
different, potentially-disagreeing mechanisms.

Deliberately does NOT also require the holder's cmdline to "look like"
agle.py before treating it as live: SingleInstanceLock is used directly,
in-process, by many legitimate callers that are not the agle.py subprocess
at all -- most of this codebase's own tests construct ProductionSupervisor()
in a bare pytest process. Trusting is_pid_alive() alone means an alive PID
always blocks acquisition, never reclaimed just because its argv happens
not to contain a particular string. The cost of that (occasionally
refusing to reclaim a lock that actually IS free, if the identity check
were used and got it right) is far smaller than the cost of the opposite
mistake -- wrongly reclaiming a lock a live process still legitimately
holds, which is exactly the duplicate-Supervisor outcome this class exists
to prevent.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from production.process_utils import is_pid_alive

DEFAULT_SUPERVISOR_LOCK_PATH = Path("runtime/agle_supervisor.lock")

#: Process exit code agle.py uses when a DuplicateProcessError refuses to
#: start a production loop -- distinct from 0 (clean) and 1 (ordinary
#: error), so a watchdog spawning `agle.py run` as a child can tell "was
#: refused because one is already running" apart from "crashed."
DUPLICATE_PROCESS_EXIT_CODE = 2


@dataclass
class LockResult:
    acquired: bool
    reason: str
    holder_pid: Optional[int] = None


class SingleInstanceLock:
    """A named, PID-stamped, crash-safe mutual-exclusion lock backed by one
    file. Not reentrant -- one instance holds or does not hold the lock."""

    def __init__(self, path: Path = DEFAULT_SUPERVISOR_LOCK_PATH) -> None:
        self.path = Path(path)
        self._held = False

    def acquire(self) -> LockResult:
        """Try to atomically claim the lock. Reclaims a STALE lock (the
        recorded PID is no longer alive) rather than refusing forever after
        any unclean crash. Never blocks; returns immediately either way."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        for _attempt in range(2):  # one retry, only after reclaiming a confirmed-stale lock
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                existing = self._read_holder()
                if existing is None:
                    # Unreadable/corrupt lock file -- treat as stale, same
                    # fail-safe posture as production/master_switch.py's
                    # read_switch_state(): an ambiguous state is never
                    # treated as "someone else legitimately holds this."
                    self._force_remove_stale()
                    continue
                holder_pid, _holder_started = existing
                if is_pid_alive(holder_pid):
                    return LockResult(acquired=False, reason=f"already held by live pid {holder_pid}", holder_pid=holder_pid)
                # Stale: recorded holder is no longer alive -- safe to reclaim.
                self._force_remove_stale()
                continue
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat()}, fh)
                    fh.flush()
                    os.fsync(fh.fileno())
                self._held = True
                return LockResult(acquired=True, reason="acquired")
        return LockResult(acquired=False, reason="lock contention could not be resolved after reclaim attempt")

    def release(self) -> None:
        """Remove the lock file, but ONLY if it still records our own PID
        -- never delete a lock another process has since legitimately
        acquired (e.g. after we were killed, reclaimed the file, and a new
        holder took over before we got here)."""
        if not self._held:
            return
        existing = self._read_holder()
        if existing is not None and existing[0] == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass
        self._held = False

    def _read_holder(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return int(data["pid"]), data.get("acquired_at")
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def _force_remove_stale(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    def __enter__(self) -> "SingleInstanceLock":
        result = self.acquire()
        if not result.acquired:
            raise DuplicateProcessError(result.reason, holder_pid=result.holder_pid)
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class DuplicateProcessError(RuntimeError):
    """Raised when a second production loop tries to start while one is
    already alive. Never a GovernanceViolation -- this is a process-
    lifecycle concern, not a scientific/governance one -- but it is also
    never silently swallowed by run_forever()'s bounded-retry loop (see
    supervisor.py)."""

    def __init__(self, reason: str, *, holder_pid: Optional[int] = None) -> None:
        super().__init__(reason)
        self.holder_pid = holder_pid
