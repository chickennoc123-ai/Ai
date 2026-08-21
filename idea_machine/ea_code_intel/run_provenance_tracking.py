"""Record the real provenance transitions for HYP-EACI-0001 based on the actual Cycle 12 result."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from idea_machine.ea_code_intel.provenance import ProvenanceTracker, Stage
from dataclasses import asdict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
cycle12 = json.loads((REPO_ROOT / "reports/factory/discovery_cycles/cycle_12_ea_code_intel.json").read_text())
hyp = cycle12["hypotheses"][0]

t = ProvenanceTracker(entity_id="HYP-EACI-0001")
t.to_derived_hypothesis("Synthesized from geraked/metatrader5 (COT1 dual-signal pattern) + academic "
                        "composite-macro-factor snippet; passed novelty check (no refuted-family overlap) "
                        "and data-availability check (USDJPY/US10Y/SPX500/NFP all present in project data)")

verdicts = [w["verdict"] for w in hyp["windows"]]
best = next((w for w in hyp["windows"] if w["verdict"] == "DISCOVERY_SURVIVOR"), None)
summary_verdict = "DISCOVERY_SURVIVOR (at least 1 window)" if best else f"0 survivors across {len(verdicts)} windows: {verdicts}"

t.to_data_supported("reports/factory/discovery_cycles/cycle_12_ea_code_intel.json", summary_verdict)

print(f"Final provenance stage: {t.current_label()}")
print(f"History:")
for ev in t.history:
    print(f"  {ev.from_stage} -> {ev.to_stage}: {ev.reason}")

out = {
    "entity_id": t.entity_id,
    "final_stage": t.current_label(),
    "history": [asdict(e) for e in t.history],
    "note": "Did not advance past DATA_SUPPORTED: 0/3 windows cleared the internal validation gate "
           "(DISCOVERY_SURVIVOR). Cannot legally advance to FACTORY_TESTED or SURVIVOR -- "
           "ProvenanceTracker.to_factory_tested() requires a passing GEN12 result, which requires "
           "a DISCOVERY_SURVIVOR first, which this hypothesis did not produce.",
}
out_path = REPO_ROOT / "reports" / "idea_machine" / "hyp_eaci_0001_provenance.json"
out_path.write_text(json.dumps(out, indent=2))
print(f"\nSaved: {out_path}")
