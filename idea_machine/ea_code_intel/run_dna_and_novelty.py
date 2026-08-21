"""
Run deterministic DNA extraction + novelty check on the real mined sources.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from idea_machine.ea_code_intel.strategy_dna import extract_dna, signature
from idea_machine.ea_code_intel.novelty_engine import NoveltyEngine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
mined_path = REPO_ROOT / "reports" / "idea_machine" / "ea_mined_sources.json"
mined = json.loads(mined_path.read_text())

ne = NoveltyEngine()
ne.load()

dnas = []
for src in mined["sources"]:
    dna = extract_dna(src["source_id"], src["full_name"], src["url"], src["text_excerpt"])
    dnas.append(dna)

all_tag_sets = [set(t for tags in d.tags.values() for t in tags) for d in dnas]

results = []
print(f"{'Source':45s} {'Tags':6s} Verdict")
print("-" * 90)
for i, dna in enumerate(dnas):
    others = [s for j, s in enumerate(all_tag_sets) if j != i]
    verdict = ne.check(all_tag_sets[i], dna.dna_id, others)
    results.append({"dna": dna.to_dict(), "novelty": {
        "verdict": verdict.verdict, "matched_family_id": verdict.matched_family_id,
        "matched_family_status": verdict.matched_family_status,
        "overlap_tags": verdict.overlap_tags, "overlap_ratio": verdict.overlap_ratio,
        "explanation": verdict.explanation,
    }})
    print(f"{dna.source_title[:45]:45s} {dna.tag_count():<6d} {verdict.verdict}")
    for cat, tags in dna.tags.items():
        print(f"    {cat}: {tags}")
    print(f"    -> {verdict.explanation}")
    print()

out_path = REPO_ROOT / "reports" / "idea_machine" / "ea_dna_novelty_results.json"
out_path.write_text(json.dumps(results, indent=2))
print(f"Saved: {out_path}")
