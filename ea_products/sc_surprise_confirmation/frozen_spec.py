"""
Single source of truth for what "the frozen SC_SURPRISE_CONFIRMATION
specification" actually is.

There is no one frozen spec -- there are SIX, one per (symbol, driver,
window) combination that showed train-side significance across Cycles 8-9.
None cleared validation. This module loads them from
reports/factory/candidate_spec_registry.json (the project's own append-only,
hash-verified freeze registry, NOT a new ad-hoc file) and refuses to run if
that registry's content has drifted from what this file expects.

Every consumer of this module -- the Python replay engine, the MQL5 config
exporter, the test suite -- reads through here, so there is exactly one
place a mismatch between "what was frozen" and "what the EA runs" could ever
be introduced, and it is checked, not assumed.
"""
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

R = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import roundtrip_cost, COST_MODEL_ID

REGISTRY_PATH = R / "reports/factory/candidate_spec_registry.json"

# The exact 6 candidate_ids frozen for this product, and nothing else --
# hardcoded here so an unrelated future CAND-SC-* addition to the registry
# does not silently get pulled into this EA's tradable set.
FROZEN_CANDIDATE_IDS = (
    "CAND-SC-EURUSD-US10Y-5M",
    "CAND-SC-EURUSD-US10Y-15M",
    "CAND-SC-GBPUSD-US10Y-5M",
    "CAND-SC-XAUUSD-WTICO-5M",
    "CAND-SC-USDJPY-SPX500-240M",
    "CAND-SC-USDCHF-SPX500-240M",
)

ENTRY_DELAY_SEC = 60
IMPULSE_WINDOW_MIN = 5
EVENT_TYPES = ("Non-Farm Employment Change", "CPI y/y", "ADP Non-Farm Employment Change")
SURPRISE_FX_DIR = {"EURUSD": -1, "GBPUSD": -1, "XAUUSD": -1, "USDJPY": +1, "USDCHF": +1}
DRIVER_BASE_DIR = {
    ("EURUSD", "US10Y"): +1, ("GBPUSD", "US10Y"): +1,
    ("XAUUSD", "SPX500"): -1, ("XAUUSD", "WTICO"): +1,
    ("USDJPY", "SPX500"): +1, ("USDCHF", "SPX500"): +1,
}


class FrozenSpecDriftError(RuntimeError):
    """Raised when the on-disk registry no longer matches what this module expects."""


@dataclass(frozen=True)
class FrozenCombination:
    candidate_id: str
    symbol: str
    driver: str
    window_min: int
    base_dir: int
    surprise_fx_dir: int
    entry_delay_sec: int
    impulse_window_min: int
    roundtrip_cost: float
    spec_hash: str
    evidence_status: str
    last_measured: Dict

    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id, "symbol": self.symbol, "driver": self.driver,
            "window_min": self.window_min, "base_dir": self.base_dir,
            "surprise_fx_dir": self.surprise_fx_dir, "entry_delay_sec": self.entry_delay_sec,
            "impulse_window_min": self.impulse_window_min,
            "roundtrip_cost": self.roundtrip_cost, "spec_hash": self.spec_hash,
            "evidence_status": self.evidence_status, "last_measured": self.last_measured,
        }


def load_frozen_combinations() -> List[FrozenCombination]:
    """
    Load and cross-validate the 6 frozen combinations against the registry.

    Raises FrozenSpecDriftError if:
      - the registry file is missing
      - any expected candidate_id is missing from it
      - any candidate is not actually frozen (frozen_at is None)
      - any candidate's evidence_status is not STILL_UNDERPOWERED (i.e. it
        was somehow later authorized/consumed/upgraded -- this product must
        not silently start claiming a stronger status than what was true
        when it was built)
    """
    if not REGISTRY_PATH.exists():
        raise FrozenSpecDriftError(f"candidate spec registry not found at {REGISTRY_PATH}")
    raw = json.loads(REGISTRY_PATH.read_text())
    candidates = raw.get("candidates", {})

    out = []
    for cid in FROZEN_CANDIDATE_IDS:
        if cid not in candidates:
            raise FrozenSpecDriftError(f"expected frozen candidate {cid!r} not found in registry")
        c = candidates[cid]
        if c.get("frozen_at") is None:
            raise FrozenSpecDriftError(f"{cid} is registered but not frozen (frozen_at is None)")
        p = c["parameters"]
        if p.get("evidence_status") != "STILL_UNDERPOWERED":
            raise FrozenSpecDriftError(
                f"{cid} evidence_status is {p.get('evidence_status')!r}, expected "
                f"'STILL_UNDERPOWERED' -- this product's labeling assumes an unresolved "
                f"candidate and must not be built against a status it doesn't know about")
        symbol, driver = p["symbol"], p["driver"]
        out.append(FrozenCombination(
            candidate_id=cid, symbol=symbol, driver=driver, window_min=p["window_min"],
            base_dir=DRIVER_BASE_DIR[(symbol, driver)],
            surprise_fx_dir=SURPRISE_FX_DIR[symbol],
            entry_delay_sec=p["entry_delay_sec"], impulse_window_min=p["impulse_window_min"],
            roundtrip_cost=roundtrip_cost(symbol), spec_hash=c["spec_hash"],
            evidence_status=p["evidence_status"], last_measured=p["last_measured"],
        ))
    return out


def find_combination(symbol: str, driver: str, window_min: int) -> Optional[FrozenCombination]:
    for c in load_frozen_combinations():
        if c.symbol == symbol and c.driver == driver and c.window_min == window_min:
            return c
    return None


def export_spec_json(out_path: Path) -> Dict:
    """Write the frozen spec as a standalone JSON the MQL5 side ships with."""
    combos = load_frozen_combinations()
    payload = {
        "product": "SC_SURPRISE_CONFIRMATION",
        "evidence_status": "EXPERIMENTAL_UNRESOLVED",
        "warning": ("No combination in this file has cleared internal validation. None "
                   "is authorized for GEN 14. None has been evaluated against the sealed "
                   "holdout. This is NOT a proven edge. Do not trade this with real capital "
                   "based on this evidence alone."),
        "cost_model_id": COST_MODEL_ID,
        "event_types": list(EVENT_TYPES),
        "combinations": [c.to_dict() for c in combos],
        "spec_bundle_hash": hashlib.sha256(
            json.dumps([c.spec_hash for c in combos], sort_keys=True).encode()
        ).hexdigest(),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    combos = load_frozen_combinations()
    print(f"{len(combos)} frozen combinations loaded, all STILL_UNDERPOWERED:")
    for c in combos:
        print(f"  {c.candidate_id}  hash={c.spec_hash[:16]}")
