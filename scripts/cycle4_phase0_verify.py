#!/usr/bin/env python3
"""
GEN 7 Cycle 4 -- Phase 0 state verification.

Verifies the six preconditions and closes the one gap found: the H1
price-model search space eliminated by FAIL-000029 was never written into the
refuted-family registry, so the GEN 7 firewall could not block H1 variants.
"""
import json, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

REFUTED_H1 = {
    "FAMILY-H1-PRICE-PATTERN": (
        "H1 intrabar price-pattern models: streak reversal, weekend gap fade, "
        "NR7 range compression, N-bar breakout, hour-of-day drift, and any "
        "volatility/session filter layered on them, held for 1-240 H1 bars, on "
        "EURUSD GBPUSD USDCAD USDCHF USDJPY XAUUSD. Refuted by FAIL-000029: "
        "gross effect is smaller than the round-trip cost on every instrument "
        "tested; cross-sectional breadth does not defeat a cost floor."),
}

def main() -> int:
    ok = True
    print("=" * 78); print("CYCLE 4 -- PHASE 0 STATE VERIFICATION"); print("=" * 78)

    fl = json.loads((R / "reports/factory/failure_library.json").read_text())
    fails = fl.get("failures", fl if isinstance(fl, list) else [])
    has29 = any(f["failure_id"] == "FAIL-000029" for f in fails)
    print(f"[{'PASS' if has29 else 'FAIL'}] 1. FAIL-000029 recorded ({len(fails)} failures total)")
    ok &= has29

    lg = json.loads((R / "reports/factory/multiple_testing_ledger.json").read_text())
    h_ok = lg["cumulative_hypotheses_generated"] == 58
    e_ok = lg["cumulative_parameter_evaluations"] == 312
    print(f"[{'PASS' if h_ok else 'FAIL'}] 2. 58 cumulative hypotheses "
          f"(actual {lg['cumulative_hypotheses_generated']})")
    print(f"[{'PASS' if e_ok else 'FAIL'}] 5. 312 cumulative parameter evaluations "
          f"(actual {lg['cumulative_parameter_evaluations']})")
    ok &= h_ok and e_ok

    ev = json.loads((R / "reports/factory/evidence_vault.json").read_text())
    ds = ev["datasets"]["DS-HOLDOUT-EURUSD-H1-HISTDATA-20240101-20260130"]
    virgin = (len(ev["authorizations"]) == 0 and len(ev["consumptions"]) == 0
              and ds["seal_status"] == "sealed" and ds["research_exposure"] == "UNEXPOSED")
    auth_p = R / "reports/factory/holdout_authorization_registry.json"
    if auth_p.exists():
        virgin &= json.loads(auth_p.read_text())["authorizations"] == {}
    print(f"[{'PASS' if virgin else 'FAIL'}] 3. holdout intact "
          f"(seal={ds['seal_status']}, exposure={ds['research_exposure']}, "
          f"auth={len(ev['authorizations'])}, consumed={len(ev['consumptions'])})")
    ok &= virgin

    g = (R / "discovery/_guards.py").read_text()
    a3 = "Amendment 3" in g and "HoldoutFirewallViolation" in g
    print(f"[{'PASS' if a3 else 'FAIL'}] 4. OGD-4 Amendment 3 active")
    ok &= a3

    # 6. H1 family must be registered as refuted so GEN 7 can firewall it.
    reg_p = R / "reports/factory/research_family_registry.json"
    reg = json.loads(reg_p.read_text())
    fams = reg.setdefault("families", {})
    added = []
    for fid, desc in REFUTED_H1.items():
        if fid not in fams:
            fams[fid] = {
                "family_id": fid,
                "family_kind": "HYPOTHESIS_FAMILY",
                "description": desc,
                "family_signature": hashlib.sha256(desc.encode()).hexdigest(),
                "creation_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "REFUTED",
                "refuted_by": "FAIL-000029",
                "members": [],
            }
            added.append(fid)
    if added:
        reg_p.write_text(json.dumps(reg, indent=1, sort_keys=True), encoding="utf-8")
        print(f"[FIXED] 6. registered refuted family: {', '.join(added)}")
    else:
        print("[PASS] 6. H1 price-pattern family already marked REFUTED")

    print("-" * 78)
    print(f"PHASE 0: {'CLEAR -- Cycle 4 discovery may begin' if ok else 'BLOCKED'}")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
