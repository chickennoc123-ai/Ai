"""
Source Registry: real, tested access status for public trading-strategy
source-code repositories and research material.

Matches the project's existing evidence conventions
(reports/factory/research_source_registry.json) -- access_status and
verification_status are recorded from an ACTUAL attempt, never assumed.
A source is ACCESS_FAILED until a real fetch/search proves otherwise, and
ACCESSED entries carry a checksum of what was actually retrieved so the
claim is checkable later.

This module never touches reports/factory/research_source_registry.json
(the Factory's own historical record) -- it writes to a parallel file
under reports/idea_machine/ so the two audit trails stay separable.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "reports" / "idea_machine" / "ea_source_registry.json"


@dataclass
class SourceProbeResult:
    source_id: str
    source_type: str          # OPEN_SOURCE_CODE_HOST, CODE_LIBRARY, ACADEMIC, FORUM, API_TOOL
    title: str
    url: Optional[str]
    access_status: str        # ACCESSED, ACCESS_FAILED, TOOL_AVAILABLE, TOOL_UNAVAILABLE
    verification_status: str  # PROVISIONALLY_VERIFIED, ACCESS_FAILED, UNVERIFIED
    content_checksum: Optional[str]
    notes: str
    retrieval_timestamp: str


class SourceRegistry:
    """
    Tracks real probe results for candidate sources. Every entry here traces
    to an actual tool call result recorded by the caller -- this class does
    not perform network I/O itself (WebFetch/WebSearch/GitHub MCP tools are
    not importable Python functions in this environment), it structures and
    persists results the orchestrator obtained.
    """

    def __init__(self):
        self.results: List[SourceProbeResult] = []
        self._next_id = 1

    def record_fetch_result(self, title: str, url: str, source_type: str,
                            succeeded: bool, content_sample: Optional[str] = None,
                            error_detail: Optional[str] = None) -> SourceProbeResult:
        """Record the outcome of a real WebFetch attempt."""
        sid = f"EASRC-{self._next_id:06d}"
        self._next_id += 1

        if succeeded and content_sample:
            checksum = hashlib.sha256(content_sample.encode("utf-8")).hexdigest()
            result = SourceProbeResult(
                source_id=sid, source_type=source_type, title=title, url=url,
                access_status="ACCESSED", verification_status="PROVISIONALLY_VERIFIED",
                content_checksum=checksum,
                notes="Fetched live via WebFetch; content checksum recorded. "
                     "Any strategy claims in the content are source claims only, "
                     "not independently corroborated.",
                retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
            )
        else:
            result = SourceProbeResult(
                sid, source_type, title, url,
                access_status="ACCESS_FAILED", verification_status="ACCESS_FAILED",
                content_checksum=None,
                notes=error_detail or "Fetch failed, no substitute source presented as this source.",
                retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
            )
        self.results.append(result)
        return result

    def record_tool_availability(self, title: str, tool_name: str, source_type: str,
                                 available: bool, sample_result_summary: Optional[str] = None) -> SourceProbeResult:
        """Record whether an MCP tool (e.g. GitHub search) actually returned real data."""
        sid = f"EASRC-{self._next_id:06d}"
        self._next_id += 1
        result = SourceProbeResult(
            source_id=sid, source_type=source_type, title=title, url=f"tool:{tool_name}",
            access_status="TOOL_AVAILABLE" if available else "TOOL_UNAVAILABLE",
            verification_status="PROVISIONALLY_VERIFIED" if available else "ACCESS_FAILED",
            content_checksum=(hashlib.sha256(sample_result_summary.encode("utf-8")).hexdigest()
                             if available and sample_result_summary else None),
            notes=sample_result_summary or "Tool call did not return usable data.",
            retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.results.append(result)
        return result

    def summary(self) -> Dict:
        accessed = [r for r in self.results if r.access_status in ("ACCESSED", "TOOL_AVAILABLE")]
        failed = [r for r in self.results if r.access_status in ("ACCESS_FAILED", "TOOL_UNAVAILABLE")]
        return {
            "total_probed": len(self.results),
            "accessible": len(accessed),
            "blocked": len(failed),
            "accessible_sources": [r.title for r in accessed],
            "blocked_sources": [r.title for r in failed],
        }

    def save(self, out_path: Path = OUT_PATH) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Real, tested access results for candidate EA Code Intelligence "
                   "sources. Every ACCESSED entry corresponds to an actual tool call "
                   "made in this session; nothing here is assumed or inferred.",
            "summary": self.summary(),
            "sources": [asdict(r) for r in self.results],
        }
        out_path.write_text(json.dumps(payload, indent=2))
        return out_path
