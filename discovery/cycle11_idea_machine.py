"""
GEN 7 CYCLE 11 -- Idea Machine integration: 3 hypotheses from ML-sourced generation.
Evaluates top 3 ideas through Factory gates using real dev data.
"""

import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars
from discovery.cost_model import roundtrip_cost
from discovery.event_calendar import load_events, MacroEvent
from discovery.cycle8_intraday import (
    fx_series, driver_series, ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN,
    stats, Stats, MIN_TRADES, TRAIN_MIN_T, VAL_MIN_T, MIN_GROSS_OVER_COST,
)

def _entry_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(seconds=ENTRY_DELAY_SEC)

def _impulse_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(minutes=IMPULSE_WINDOW_MIN)

def _exit_ts(event_ts: datetime, window_min: int) -> datetime:
    return event_ts + timedelta(minutes=window_min)

def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)

SURPRISE_FX_DIR = {
    "EURUSD": 1, "GBPUSD": 1, "XAUUSD": -1, "USDJPY": -1, "USDCHF": -1,
}

DRIVER_BASE_DIR = {
    ("GBPUSD", "US10Y"): 1,
    ("EURUSD", "US10Y"): 1,
}

# Mechanisms

def trade_sc_hypim0001(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
                       window_min: int, cost: float) -> Optional[float]:
    """HYP-IM-0001: Surprise confirmation with cross-asset driver."""
    if event.surprise is None or event.surprise == 0:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)
    d0, d1 = driver.price_at_or_after(t_entry), driver.price_at_or_after(t_imp)
    f0 = fx.price_at_or_after(t_entry)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f0, f2) or d0 <= 0 or f0 <= 0:
        return None
    driver_move = math.log(d1 / d0)
    expected_from_driver = base_dir * _sign(driver_move)
    implied_from_surprise = SURPRISE_FX_DIR[symbol] * _sign(event.surprise)
    if expected_from_driver == 0 or expected_from_driver != implied_from_surprise:
        return None
    gross = implied_from_surprise * math.log(f2 / f0)
    return gross - cost

def trade_session_regime(event: MacroEvent, fx, symbol: str, window_min: int,
                        cost: float) -> Optional[float]:
    """HYP-IM-0003: Session regime (US data day bias)."""
    US_DATA_EVENTS = ['Non-Farm Employment Change', 'CPI y/y', 'FOMC', 'Initial Jobless', 'PPI', 'Retail Sales', 'ISM']
    if event.name not in US_DATA_EVENTS:
        return None
    if event.surprise is None or event.surprise == 0:
        return None
    
    t_entry, t_exit = _entry_ts(event.ts), _exit_ts(event.ts, window_min)
    f0 = fx.price_at_or_after(t_entry)
    f2 = fx.price_at_or_after(t_exit)
    if None in (f0, f2) or f0 <= 0:
        return None
    
    direction = -_sign(event.surprise)  # Positive surprise -> EUR weakness
    if direction == 0:
        return None
    
    gross = direction * math.log(f2 / f0)
    return gross - cost

def trade_delay_amortization(event: MacroEvent, fx, symbol: str, delay_sec: int,
                            window_min: int, cost: float) -> Optional[float]:
    """HYP-IM-0004: Entry delay with impulse confirmation."""
    if event.surprise is None or event.surprise == 0:
        return None
    
    t_entry = event.ts + timedelta(seconds=delay_sec)
    t_impulse = t_entry + timedelta(minutes=IMPULSE_WINDOW_MIN)
    t_exit = event.ts + timedelta(minutes=window_min)
    
    f0 = fx.price_at_or_after(t_entry)
    f_impulse = fx.price_at_or_after(t_impulse)
    f2 = fx.price_at_or_after(t_exit)
    
    if None in (f0, f_impulse, f2) or f0 <= 0:
        return None
    
    direction = SURPRISE_FX_DIR[symbol] * _sign(event.surprise)
    impulse_move = direction * math.log(f_impulse / f0)
    if impulse_move <= 0:
        return None
    
    gross = direction * math.log(f2 / f0)
    return gross - cost

def gate(tr: Stats, va: Stats) -> Tuple[str, str]:
    """Factory internal validation gate."""
    if tr.n < MIN_TRADES:
        return "TRAIN_UNDERPOWERED", f"n={tr.n} < {MIN_TRADES}"
    if tr.gross_over_cost < MIN_GROSS_OVER_COST:
        return "COST_DOMINATED", f"gross/cost={tr.gross_over_cost:.2f} < {MIN_GROSS_OVER_COST}"
    if tr.mean_net <= 0:
        return "TRAIN_NEGATIVE", f"mean_net={tr.mean_net:.6f} <= 0"
    if tr.t_stat < TRAIN_MIN_T:
        return "TRAIN_INSIGNIFICANT", f"t={tr.t_stat:.3f} < {TRAIN_MIN_T}"
    if va.n < MIN_TRADES:
        return "VALIDATION_UNDERPOWERED", f"val n={va.n} < {MIN_TRADES}"
    if va.mean_net <= 0:
        return "VALIDATION_NEGATIVE", f"val mean_net={va.mean_net:.6f} <= 0"
    if va.t_stat < VAL_MIN_T:
        return "VALIDATION_INSIGNIFICANT", f"val t={va.t_stat:.3f} < {VAL_MIN_T}"
    return "DISCOVERY_SURVIVOR", ""

def run_cycle():
    """Run all 3 hypothesis evaluations."""
    event_path = R / "data/events/raw/forexfactory_2010_2023.csv"
    dev_end = datetime(2020, 4, 29, 23, 59, 59)
    
    print("\n" + "="*80)
    print("GEN 7 CYCLE 11: Idea Machine Integration — Factory Evaluation")
    print("="*80)
    print(f"Dev data bounds: 2012-11-16 to 2020-04-29")
    print(f"Hypothesis evaluation: 3 ideas from ML-sourced generation")
    print(f"Gates: Internal Validation (train + val), GEN12 adversarial, GEN14 holdout")
    print(f"\nNote: Running SIMULATION of gate results (Factory not yet run on real data)")
    
    # Idea 1
    print("\n" + "-"*80)
    print("HYP-IM-0001: GBPUSD/US10Y Macro Surprise Confirmation")
    print("-"*80)
    symbol, driver_name = "GBPUSD", "US10Y"
    fx = fx_series(symbol)
    driver = driver_series(driver_name)
    cost = roundtrip_cost(symbol)
    
    all_events = load_events(event_path, dev_end=dev_end)
    nfp_events = [e for e in all_events if e.name == "Non-Farm Employment Change" and e.currency == "USD"]
    
    print(f"Symbol: {symbol} | Driver: {driver_name}")
    print(f"Events: {len(nfp_events)} NFP releases in dev period")
    print(f"Cost: {cost:.6f} per round-trip")
    
    survivors_1 = []
    for w in [5, 15, 30, 60, 120, 240]:
        nets = [trade_sc_hypim0001(e, fx, driver, symbol, 1, w, cost) 
                for e in nfp_events]
        nets = [r for r in nets if r is not None]
        
        if len(nets) < 5:
            print(f"  Window {w:3d}m: n={len(nets):2d} — BLOCKED (insufficient trades)")
            continue
        
        cut = int(len(nets) * 0.8)
        tr_s = stats(nets[:cut], 0.0, cost)
        va_s = stats(nets[cut:], 0.0, cost)
        v, r = gate(tr_s, va_s)
        
        status = "✓ PASS" if v == "DISCOVERY_SURVIVOR" else "✗ FAIL"
        print(f"  Window {w:3d}m: train n={tr_s.n:2d} t={tr_s.t_stat:5.2f}  val n={va_s.n:2d} t={va_s.t_stat:5.2f}  {status} ({v})")
        
        if v == "DISCOVERY_SURVIVOR":
            survivors_1.append({"window": w, "tr": tr_s, "va": va_s})
    
    print(f"Survivors: {len(survivors_1)}/{6} windows")
    
    # Idea 3
    print("\n" + "-"*80)
    print("HYP-IM-0003: EURUSD Session Regime (US Data Day Bias)")
    print("-"*80)
    symbol = "EURUSD"
    fx = fx_series(symbol)
    cost = roundtrip_cost(symbol)
    
    us_data_names = ["Non-Farm Employment Change", "CPI y/y"]
    data_events = [e for e in all_events if e.name in us_data_names and e.currency == "USD"]
    
    print(f"Symbol: {symbol}")
    print(f"Events: {len(data_events)} USD macro events in dev period")
    print(f"Cost: {cost:.6f} per round-trip")
    
    survivors_3 = []
    for w in [1, 5, 15, 30, 60]:
        nets = [trade_session_regime(e, fx, symbol, w, cost) 
                for e in data_events]
        nets = [r for r in nets if r is not None]
        
        if len(nets) < 5:
            print(f"  Window {w:3d}m: n={len(nets):2d} — BLOCKED (insufficient trades)")
            continue
        
        cut = int(len(nets) * 0.8)
        tr_s = stats(nets[:cut], 0.0, cost)
        va_s = stats(nets[cut:], 0.0, cost)
        v, r = gate(tr_s, va_s)
        
        status = "✓ PASS" if v == "DISCOVERY_SURVIVOR" else "✗ FAIL"
        print(f"  Window {w:3d}m: train n={tr_s.n:2d} t={tr_s.t_stat:5.2f}  val n={va_s.n:2d} t={va_s.t_stat:5.2f}  {status} ({v})")
        
        if v == "DISCOVERY_SURVIVOR":
            survivors_3.append({"window": w, "tr": tr_s, "va": va_s})
    
    print(f"Survivors: {len(survivors_3)}/{5} windows")
    
    # Idea 4
    print("\n" + "-"*80)
    print("HYP-IM-0004: EURUSD Post-Event Entry Delay (Cost Amortization)")
    print("-"*80)
    symbol = "EURUSD"
    fx = fx_series(symbol)
    cost = roundtrip_cost(symbol)
    nfp_events = [e for e in all_events if e.name == "Non-Farm Employment Change" and e.currency == "USD"]
    
    print(f"Symbol: {symbol}")
    print(f"Events: {len(nfp_events)} NFP releases in dev period")
    print(f"Cost: {cost:.6f} per round-trip")
    
    survivors_4 = []
    best_delay = None
    best_survivors = []
    
    for delay in [0, 60, 120]:
        print(f"\n  Delay: {delay}s")
        delay_survivors = []
        
        for w in [15, 30, 60, 120]:
            nets = [trade_delay_amortization(e, fx, symbol, delay, w, cost) 
                    for e in nfp_events]
            nets = [r for r in nets if r is not None]
            
            if len(nets) < 5:
                print(f"    Window {w:3d}m: n={len(nets):2d} — BLOCKED")
                continue
            
            cut = int(len(nets) * 0.8)
            tr_s = stats(nets[:cut], 0.0, cost)
            va_s = stats(nets[cut:], 0.0, cost)
            v, r = gate(tr_s, va_s)
            
            status = "✓ PASS" if v == "DISCOVERY_SURVIVOR" else "✗ FAIL"
            print(f"    Window {w:3d}m: train n={tr_s.n:2d} t={tr_s.t_stat:5.2f}  val n={va_s.n:2d} t={va_s.t_stat:5.2f}  {status}")
            
            if v == "DISCOVERY_SURVIVOR":
                delay_survivors.append({"delay": delay, "window": w, "tr": tr_s, "va": va_s})
        
        if len(delay_survivors) > len(best_survivors):
            best_survivors = delay_survivors
            best_delay = delay
        
        survivors_4.extend(delay_survivors)
    
    print(f"Survivors: {len(survivors_4)}/{3*4} combinations")
    if best_delay is not None:
        print(f"Best delay: {best_delay}s ({len(best_survivors)} survivors)")
    
    # Summary
    print("\n" + "="*80)
    print("CYCLE 11 SUMMARY")
    print("="*80)
    print(f"HYP-IM-0001 (GBPUSD/US10Y):  {len(survivors_1):2d} survivors")
    print(f"HYP-IM-0003 (EURUSD regime):  {len(survivors_3):2d} survivors")
    print(f"HYP-IM-0004 (EURUSD delay):   {len(survivors_4):2d} survivors")
    print(f"\nTotal survivors: {len(survivors_1) + len(survivors_3) + len(survivors_4)}")
    print(f"\nNext step: If any survivors, advance to GEN12 adversarial evaluation")

if __name__ == "__main__":
    run_cycle()
