"""Renders the `python3 -m idea_machine.cli space` report (spec item 25)."""

from __future__ import annotations

from typing import Dict, List

from idea_machine.core import epistemic
from idea_machine.research_space.exploration_debt import ExplorationDebtState
from idea_machine.research_space.search_space import UNEXPLORED, SearchSpace


def build_space_map(
    search_space: SearchSpace,
    *,
    debt: ExplorationDebtState = None,
    mode_shares: Dict[str, float] = None,
) -> Dict:
    counts = search_space.status_counts()
    totals: Dict[str, int] = {}
    for dim_counts in counts.values():
        for status, n in dim_counts.items():
            totals[status] = totals.get(status, 0) + n

    return {
        "dimensions": counts,
        "totals": totals,
        "novelty_coverage": search_space.novelty_coverage(),
        "exploration_debt": debt.to_dict() if debt else None,
        "mode_shares": mode_shares or {},
        "refuted_cells": [c.to_dict() for c in search_space.by_status(epistemic.REFUTED)],
        "underpowered_cells": [c.to_dict() for c in search_space.by_status(epistemic.UNDERPOWERED)],
        "unexplored_cells": [c.to_dict() for c in search_space.by_status(UNEXPLORED)],
    }


def render_text(space_map: Dict) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("RESEARCH SPACE MAP")
    lines.append("=" * 72)
    lines.append("")
    lines.append("KNOWN / TESTED / REFUTED / UNDERPOWERED / UNEXPLORED / BLOCKED (all cells):")
    for status, n in sorted(space_map["totals"].items()):
        lines.append(f"  {status:14s} {n}")
    lines.append("")
    lines.append(f"Novelty coverage (fraction of cells touched at all): {space_map['novelty_coverage']:.1%}")
    lines.append("")
    if space_map.get("mode_shares"):
        lines.append("EXPLOIT / EXPLORE / RECOMBINE (last cycle):")
        for mode, share in space_map["mode_shares"].items():
            lines.append(f"  {mode:10s} {share:.1%}")
        lines.append("")
    if space_map.get("exploration_debt"):
        d = space_map["exploration_debt"]
        lines.append(f"EXPLORATION DEBT: {d['debt']} (threshold {d['threshold']}, "
                     f"forced={d['forced_exploration']})")
        lines.append(f"  {d['reason']}")
        lines.append("")
    lines.append(f"REFUTED cells ({len(space_map['refuted_cells'])}):")
    for c in space_map["refuted_cells"]:
        lines.append(f"  {c['dimension']}.{c['value']}")
    lines.append("")
    lines.append(f"UNDERPOWERED cells ({len(space_map['underpowered_cells'])}) -- real signal, blocked by data:")
    for c in space_map["underpowered_cells"]:
        lines.append(f"  {c['dimension']}.{c['value']}")
    lines.append("")
    lines.append(f"UNEXPLORED cells ({len(space_map['unexplored_cells'])}) -- never proposed:")
    for c in space_map["unexplored_cells"][:30]:
        lines.append(f"  {c['dimension']}.{c['value']}")
    if len(space_map["unexplored_cells"]) > 30:
        lines.append(f"  ... and {len(space_map['unexplored_cells']) - 30} more")
    return "\n".join(lines)
