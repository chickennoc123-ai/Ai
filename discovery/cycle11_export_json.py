"""
Export Cycle 11 results to structured JSON for economic_feedback consumption.

Re-runs the exact trade functions from cycle11_idea_machine.py (no logic
changes) and captures full diagnostic fields: n_events_available,
n_trades_generated, confirmation_rate, gross_over_cost, mean_net, t-stats,
verdict, and specific failure reason -- everything economic_feedback needs
to learn from, without altering the frozen Cycle 11 evaluation logic itself.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.cost_model import roundtrip_cost
from discovery.event_calendar import load_events
from discovery.cycle8_intraday import fx_series, driver_series, stats
from discovery.cycle11_idea_machine import (
    trade_sc_hypim0001, trade_session_regime, trade_delay_amortization, gate,
)

event_path = R / "data/events/raw/forexfactory_2010_2023.csv"
dev_end = datetime(2020, 4, 29, 23, 59, 59)
all_events = load_events(event_path, dev_end=dev_end)

output = {
    "cycle_id": "CYCLE-11-IDEA-MACHINE",
    "generated_at": datetime.utcnow().isoformat(),
    "dev_period": {"start": "2012-11-16", "end": "2020-04-29"},
    "hypotheses": [],
}

# HYP-IM-0001
symbol, driver_name = "GBPUSD", "US10Y"
fx, driver, cost = fx_series(symbol), driver_series(driver_name), roundtrip_cost(symbol)
nfp_events = [e for e in all_events if e.name == "Non-Farm Employment Change" and e.currency == "USD"]

h1 = {
    "hyp_id": "HYP-IM-0001", "source_idea_id": "IDEA-V2-001-MACR", "idea_score": 74.0,
    "category": "MACRO_SURPRISE", "symbol": symbol, "driver": driver_name,
    "n_events_available": len(nfp_events), "windows": [],
}
for w in [5, 15, 30, 60, 120, 240]:
    nets = [trade_sc_hypim0001(e, fx, driver, symbol, 1, w, cost) for e in nfp_events]
    n_trades = sum(1 for r in nets if r is not None)
    nets = [r for r in nets if r is not None]
    if len(nets) < 5:
        h1["windows"].append({"window_min": w, "n_trades": len(nets), "verdict": "EVAL_BLOCKED",
                              "reason": "insufficient trades"})
        continue
    cut = int(len(nets) * 0.8)
    train_nets, val_nets = nets[:cut], nets[cut:]
    gm = (sum(abs(x) for x in train_nets) / len(train_nets)) if train_nets else 0.0
    tr_s, va_s = stats(train_nets, gm + cost, cost), stats(val_nets, 0.0, cost)
    v, r = gate(tr_s, va_s)
    h1["windows"].append({
        "window_min": w, "n_trades": n_trades,
        "confirmation_rate": round(n_trades / len(nfp_events), 4),
        "train": tr_s.to_dict(), "validation": va_s.to_dict(),
        "verdict": v, "reason": r,
    })
output["hypotheses"].append(h1)

# HYP-IM-0003
symbol = "EURUSD"
fx, cost = fx_series(symbol), roundtrip_cost(symbol)
us_data_names = ["Non-Farm Employment Change", "CPI y/y"]
data_events = [e for e in all_events if e.name in us_data_names and e.currency == "USD"]

h3 = {
    "hyp_id": "HYP-IM-0003", "source_idea_id": "IDEA-V2-003-REGI", "idea_score": 64.0,
    "category": "REGIME", "symbol": symbol, "driver": None,
    "n_events_available": len(data_events), "windows": [],
}
for w in [1, 5, 15, 30, 60]:
    nets = [trade_session_regime(e, fx, symbol, w, cost) for e in data_events]
    n_trades = sum(1 for r in nets if r is not None)
    nets = [r for r in nets if r is not None]
    if len(nets) < 5:
        h3["windows"].append({"window_min": w, "n_trades": len(nets), "verdict": "EVAL_BLOCKED",
                              "reason": "insufficient trades"})
        continue
    cut = int(len(nets) * 0.8)
    train_nets, val_nets = nets[:cut], nets[cut:]
    gm = (sum(abs(x) for x in train_nets) / len(train_nets)) if train_nets else 0.0
    tr_s, va_s = stats(train_nets, gm + cost, cost), stats(val_nets, 0.0, cost)
    v, r = gate(tr_s, va_s)
    h3["windows"].append({
        "window_min": w, "n_trades": n_trades,
        "confirmation_rate": round(n_trades / len(data_events), 4),
        "train": tr_s.to_dict(), "validation": va_s.to_dict(),
        "verdict": v, "reason": r,
    })
output["hypotheses"].append(h3)

# HYP-IM-0004
symbol = "EURUSD"
fx, cost = fx_series(symbol), roundtrip_cost(symbol)
nfp_events = [e for e in all_events if e.name == "Non-Farm Employment Change" and e.currency == "USD"]

h4 = {
    "hyp_id": "HYP-IM-0004", "source_idea_id": "IDEA-V2-004-MICR", "idea_score": 64.0,
    "category": "MICROSTRUCTURE", "symbol": symbol, "driver": None,
    "n_events_available": len(nfp_events), "delays": [],
}
for delay in [0, 60, 120]:
    delay_entry = {"delay_sec": delay, "windows": []}
    for w in [15, 30, 60, 120]:
        nets = [trade_delay_amortization(e, fx, symbol, delay, w, cost) for e in nfp_events]
        n_trades = sum(1 for r in nets if r is not None)
        nets = [r for r in nets if r is not None]
        if len(nets) < 5:
            delay_entry["windows"].append({"window_min": w, "n_trades": len(nets), "verdict": "EVAL_BLOCKED"})
            continue
        cut = int(len(nets) * 0.8)
        train_nets, val_nets = nets[:cut], nets[cut:]
        gm = (sum(abs(x) for x in train_nets) / len(train_nets)) if train_nets else 0.0
        tr_s, va_s = stats(train_nets, gm + cost, cost), stats(val_nets, 0.0, cost)
        v, r = gate(tr_s, va_s)
        delay_entry["windows"].append({
            "window_min": w, "n_trades": n_trades,
            "confirmation_rate": round(n_trades / len(nfp_events), 4),
            "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "reason": r,
        })
    h4["delays"].append(delay_entry)
output["hypotheses"].append(h4)

out_path = R / "reports/factory/discovery_cycles/cycle_11_idea_machine.json"
out_path.write_text(json.dumps(output, indent=2, default=str))
print(f"Wrote {out_path}")
print(json.dumps(output, indent=2, default=str)[:500])
