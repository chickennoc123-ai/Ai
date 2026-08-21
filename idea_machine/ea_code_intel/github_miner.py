"""
GitHub Miner: structures REAL results obtained via GitHub search/fetch tool
calls into MinedSource records.

Important architectural note: WebFetch, WebSearch, and the GitHub MCP tools
are only callable by the orchestrating agent (this session), not from a
plain Python subprocess. This module therefore does not perform network
I/O itself -- it is the data layer the orchestrator populates with results
from its own real tool calls, immediately after making them. This keeps a
hard separation between "a tool call actually happened and returned this"
and "code assembled a plausible-looking record" -- every MinedSource here
must trace to an actual search_repositories/search_code/WebFetch result the
orchestrator obtained in the same session.

Governance: stars/forks are recorded as metadata for context only. They are
explicitly excluded from strategy_dna.py's extraction and from any Idea
Machine viability scoring -- this file's docstring and its tests both
assert that.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "reports" / "idea_machine" / "ea_mined_sources.json"


@dataclass
class MinedSource:
    """
    One real, tool-fetched public source. `readme_excerpt` (or
    `text_excerpt` for non-README material) holds only enough text for
    strategy_dna.py's keyword extraction to run against -- not necessarily
    the full document, and never the platform's own compiled/executable
    code beyond what's needed to identify structural tags.
    """
    source_id: str
    platform: str            # "github_repo", "github_code_search", "web_search_snippet"
    full_name: str            # e.g. "geraked/metatrader5"
    url: str
    language: Optional[str]
    stars: Optional[int]      # metadata only -- NEVER used as evidence of edge
    topics: List[str] = field(default_factory=list)
    text_excerpt: str = ""
    fetched_at: str = ""

    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()


class MinedSourceCollection:
    def __init__(self):
        self.sources: List[MinedSource] = []
        self._next_id = 1

    def add(self, platform: str, full_name: str, url: str, text_excerpt: str,
           language: Optional[str] = None, stars: Optional[int] = None,
           topics: Optional[List[str]] = None) -> MinedSource:
        sid = f"MINED-{self._next_id:04d}"
        self._next_id += 1
        src = MinedSource(
            source_id=sid, platform=platform, full_name=full_name, url=url,
            language=language, stars=stars, topics=topics or [], text_excerpt=text_excerpt,
        )
        self.sources.append(src)
        return src

    def save(self, out_path: Path = OUT_PATH) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Every entry traces to a real GitHub search_repositories / "
                   "search_code / WebFetch call made in this session. stars/topics "
                   "are recorded for context only and are never used as evidence "
                   "of strategy edge by any downstream scoring.",
            "count": len(self.sources),
            "sources": [asdict(s) for s in self.sources],
        }
        out_path.write_text(json.dumps(payload, indent=2))
        return out_path
