"""
Deterministic replay engine for SC_SURPRISE_CONFIRMATION.

This is the ground-truth reference implementation the MQL5 EA is written to
match, and the harness the test suite runs against. It reuses the exact
research trade logic (discovery.cycle8_intraday.trade_sc, imported not
copied) so there is zero risk of the "reference" silently drifting from what
was actually measured in Cycles 8-9.

It operates ONLY on development data (data/csv/*.csv for FX H1, the M1
sources already used in discovery/cycle8_intraday.py for FX M1 and the
cross-asset drivers) via the SAME loader functions research used. Nothing
here opens a holdout file -- the same guard_path() firewall discovery uses
is still in effect for every price source this module touches.
"""
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

R = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars
from discovery.event_calendar import load_events, MacroEvent
from discovery.cycle8_intraday import (
    trade_sc, fx_series, driver_series, FX_M1_SYMBOLS,
)
from ea_products.sc_surprise_confirmation.frozen_spec import (
    FrozenCombination, load_frozen_combinations, find_combination, EVENT_TYPES,
)


@dataclass
class ReplayTrade:
    event_ts: str
    net_return: float
    candidate_id: str


class ReplayResult:
    def __init__(self, combination: FrozenCombination, trades: List[ReplayTrade]):
        self.combination = combination
        self.trades = trades

    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.combination.candidate_id,
            "n_trades": len(self.trades),
            "trades": [t.__dict__ for t in self.trades],
        }


def event_pool(dev_end: datetime) -> List[MacroEvent]:
    """Same frozen event pool construction as discovery/cycle9_power.py, reused not
    reimplemented, filtered to the event types this product was frozen against."""
    all_ev = load_events(R / "data/events/raw/forexfactory_2010_2023.csv", dev_end=dev_end)
    return [e for e in all_ev if e.currency == "USD" and e.impact == "HIGH"
            and e.name in EVENT_TYPES]


def replay(candidate_id: str, dev_end: Optional[datetime] = None) -> ReplayResult:
    """
    Deterministically replay one frozen combination against development data.

    dev_end defaults to that symbol's own dev CSV's last bar -- the same
    boundary discovery/cycle9_power.py used, so this can never accidentally
    read past the development window into holdout-adjacent event data.
    """
    combos = {c.candidate_id: c for c in load_frozen_combinations()}
    if candidate_id not in combos:
        raise ValueError(f"{candidate_id} is not one of the 6 frozen combinations")
    c = combos[candidate_id]

    bars = load_dev_bars(R / "data/csv" / f"{c.symbol}_H1.csv")
    end = dev_end or bars[-1].ts
    events = [e for e in event_pool(end) if e.ts < end]

    fx = fx_series(c.symbol)
    driver = driver_series(c.driver)

    trades = []
    for e in events:
        net = trade_sc(e, fx, driver, c.symbol, c.base_dir, c.window_min, c.roundtrip_cost)
        if net is None:
            continue
        trades.append(ReplayTrade(event_ts=e.ts.isoformat(), net_return=net,
                                  candidate_id=candidate_id))
    return ReplayResult(c, trades)


def audit_trade(candidate_id: str, event: MacroEvent) -> Optional[Dict]:
    """
    Full-detail single-trade audit: every timestamp and price used, for the
    no-lookahead test. Recomputes the same trade_sc() decision but exposes
    the intermediate reads instead of only the final net return.
    """
    combos = {c.candidate_id: c for c in load_frozen_combinations()}
    c = combos[candidate_id]
    fx = fx_series(c.symbol)
    driver = driver_series(c.driver)

    from discovery.cycle8_intraday import _entry_ts, _impulse_ts, _exit_ts, _sign
    import math

    if event.surprise is None or event.surprise == 0:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, c.window_min)
    d0 = driver.price_at_or_after(t_entry)
    d1 = driver.price_at_or_after(t_imp)
    f0 = fx.price_at_or_after(t_entry)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f0, f2) or d0 <= 0 or f0 <= 0:
        return None
    driver_move = math.log(d1 / d0)
    expected = c.base_dir * _sign(driver_move)
    implied = c.surprise_fx_dir * _sign(event.surprise)
    if expected == 0 or expected != implied:
        return None
    gross = implied * math.log(f2 / f0)
    return {
        "event_ts": event.ts.isoformat(), "entry_ts": t_entry.isoformat(),
        "impulse_ts": t_imp.isoformat(), "exit_ts": t_exit.isoformat(),
        "driver_price_at_entry": d0, "driver_price_at_impulse": d1,
        "fx_price_at_entry": f0, "fx_price_at_exit": f2,
        "direction": implied, "net_return": gross - c.roundtrip_cost,
    }


if __name__ == "__main__":
    for c in load_frozen_combinations():
        r = replay(c.candidate_id)
        print(f"{c.candidate_id}: {r.to_dict()['n_trades']} trades replayed on dev data")
