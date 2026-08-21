"""Shared, OS-level process-liveness helpers.

Promoted out of production/health.py so production/singleton_lock.py and
production/watchdog.py reuse the exact same liveness/identity checks
instead of each re-implementing (and potentially disagreeing about) what
"this PID is really an AGLE process" means.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def is_pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just isn't ours to signal
    except OSError:
        return False
    return True


def looks_like_agle_process(pid: int, *, marker: str = "agle.py") -> Optional[bool]:
    """Best-effort /proc check (Linux only) to avoid a false positive after
    PID reuse. Returns None -- "unconfirmed", not "no" -- when the check
    cannot be performed at all (non-Linux, no /proc, permission denied);
    callers must treat None as "can't tell", never as a negative."""
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if not cmdline_path.exists():
        return None
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return None
    text = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
    return marker in text
