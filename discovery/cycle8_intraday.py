"""
GEN 7 CYCLE 8 -- event x cross-asset intraday.

SELF-CRITIQUE, STATED BEFORE ANY EVALUATION RUNS
--------------------------------------------------
The request asks for 5m/15m/30m/1H/2H/4H windows on EURUSD, GBPUSD, USDJPY,
USDCHF, XAUUSD. This project's own FX dev data is H1-only. Sub-hourly testing
on H1 bars would require inventing intraday prices -- exactly the kind of
data fabrication this project has refused at every prior step (FAIL-000033
documents the same discipline for event timestamps).

Real intraday data was sought, not assumed absent:
  - EURUSD, GBPUSD, XAUUSD: genuine Oanda M1 bars ARE available (cloned from
    FutureSharks/financial-data, the same source already used and audited in
    Cycle 7), 2005-2020. All six windows are tested on these three.
  - USDJPY, USDCHF: no M1 source was found in that repository or in a second
    search (philipperemy/FX-1-Minute-Data is a histdata.com API CLIENT, not
    committed data -- histdata.com itself is network-blocked, so this path
    is a dead end, confirmed not assumed). These two symbols are tested ONLY
    at 1H/2H/4H, using the existing H1 dev data. 5m/15m/30m are marked
    BLOCKED_NO_INTRADAY_DATA for USDJPY/USDCHF -- not silently dropped, not
    approximated.

Execution delay: every entry is filled at (release_time + ENTRY_DELAY_SEC),
using the first M1/H1 bar at or after that instant -- never at the release
timestamp itself. This is a stated, non-zero latency assumption, applied
uniformly, not tuned per symbol to help a result.

Four economically distinct mechanisms (pre-registered, not a menu chosen
after seeing results):

  DC  CROSS_ASSET_DIVERGENCE     If the driver asset has already moved but FX
                                 has not yet followed (checked at 5 min), bet
                                 on convergence in the remaining window.
  SC  SURPRISE_CONFIRMATION      Trade the calendar surprise direction (like
                                 Cycle 6's C2), but ONLY when the cross-asset
                                 driver's own reaction confirms the same
                                 macro read within the first 5 minutes.
  DR  DELAYED_REACTION           Trade FX in the driver's post-impulse
                                 direction, entering only AFTER the driver's
                                 initial 5-minute move, testing whether FX
                                 catches up with a lag intraday (the event
                                 anchor Cycle 7 lacked).
  RI  REVERSAL_AFTER_IMPULSE     Fade the driver's initial 5-minute impulse
                                 direction in FX, testing mean-reversion of
                                 the immediate cross-asset overreaction.

None of these is a parameter variant of a refuted family: DC/DR/RI require a
cross-asset driver leg entirely absent from H1-family and C2-NFP mechanisms;
SC differs from Cycle 6's C2 by requiring cross-asset confirmation, which
changes which trades are taken, not just their timing.
"""
import csv
import json
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

FX_M1_ROOT = Path("/home/user/futuresharks/financial-data/pyfinancialdata/data/currencies/oanda")
FX_M1_FOLDERS = {"EURUSD": "EUR_USD", "GBPUSD": "GBP_USD", "XAUUSD": "XAU_USD"}
FX_M1_SYMBOLS = set(FX_M1_FOLDERS)
FX_H1_ONLY_SYMBOLS = {"USDJPY", "USDCHF"}

DRIVER_FOLDERS = {"WTICO": "WTICO_USD", "SPX500": "SPX500_USD", "US10Y": "USB10Y_USD"}

WINDOWS_MIN_FULL = [5, 15, 30, 60, 120, 240]
WINDOWS_MIN_H1ONLY = [60, 120, 240]
ENTRY_DELAY_SEC = 60          # realistic execution latency, stated, uniform
IMPULSE_WINDOW_MIN = 5        # the "initial reaction" window for DC/DR/RI

MIN_TRADES = 30
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_GROSS_OVER_COST = 2.0

M1_YEAR_RANGE = range(2010, 2021)   # matches Cycle 7's audited cross-asset coverage

# (symbol, driver, mechanism_bias) -- pre-registered before any evaluation.
# mechanism_bias encodes the textbook direction: +1 means "driver up -> long
# the pair", -1 means "driver up -> short the pair" (USDJPY/USDCHF quoted
# USD-per-unit, so risk-on/JPY-CHF-sold means the pair itself goes UP, +1).
PAIRINGS = [
    ("EURUSD", "US10Y", +1, "US10Y price up (yield down) -> USD carry less attractive -> long EURUSD"),
    ("GBPUSD", "US10Y", +1, "US10Y price up (yield down) -> USD carry less attractive -> long GBPUSD"),
    ("XAUUSD", "SPX500", -1, "SPX up -> risk-on -> gold sold -> short XAUUSD on SPX up"),
    ("XAUUSD", "WTICO", +1, "Oil up -> inflation co-movement -> long XAUUSD"),
    ("USDJPY", "SPX500", +1, "SPX up -> risk-on, JPY funding-currency sold -> long USDJPY"),
    ("USDCHF", "SPX500", +1, "SPX up -> risk-on, CHF safe-haven sold -> long USDCHF"),
]


@dataclass
class Stats:
    n: int
    mean_net: float
    t_stat: float
    profit_factor: float
    win_rate: float
    gross_over_cost: float

    def to_dict(self) -> Dict:
        return self.__dict__.copy()


def stats(nets: List[float], gross_mean: float, cost: float) -> Stats:
    if not nets:
        return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(nets)
    mean = sum(nets) / n
    if n > 1:
        var = sum((x - mean) ** 2 for x in nets) / (n - 1)
        t = mean / math.sqrt(var / n) if var > 0 else 0.0
    else:
        t = 0.0
    gains = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    return Stats(n, round(mean, 8), round(t, 3), round(pf, 3),
                 round(sum(1 for x in nets if x > 0) / n, 4),
                 round(gross_mean / cost, 3) if cost else 0.0)


def gate(tr: Stats, va: Stats) -> Tuple[str, str]:
    if tr.n < MIN_TRADES:
        return "TRAIN_UNDERPOWERED", f"train n={tr.n} < {MIN_TRADES}"
    if tr.gross_over_cost < MIN_GROSS_OVER_COST:
        return "COST_DOMINATED", f"gross/cost={tr.gross_over_cost} < {MIN_GROSS_OVER_COST}"
    if tr.mean_net <= 0:
        return "TRAIN_NEGATIVE", f"train mean_net={tr.mean_net} <= 0"
    if tr.t_stat < TRAIN_MIN_T:
        return "TRAIN_INSIGNIFICANT", f"train t={tr.t_stat} < {TRAIN_MIN_T}"
    if va.n < MIN_TRADES:
        return "VALIDATION_UNDERPOWERED", f"validation n={va.n} < {MIN_TRADES}"
    if va.mean_net <= 0:
        return "VALIDATION_NEGATIVE", f"validation mean_net={va.mean_net} <= 0"
    if va.t_stat < VAL_MIN_T:
        return "VALIDATION_INSIGNIFICANT", f"validation t={va.t_stat} < {VAL_MIN_T}"
    return "DISCOVERY_SURVIVOR", ""


# ---------------------------------------------------------------- M1 access

class M1Series:
    """Lazy, month-cached M1 price lookup -- reads only the files touched."""

    def __init__(self, root: Path, folder: str):
        self.root = root / folder
        self._cache: Dict[Tuple[int, int], Dict[datetime, float]] = {}

    def _load_month(self, year: int, month: int) -> Dict[datetime, float]:
        key = (year, month)
        if key in self._cache:
            return self._cache[key]
        f = self.root / str(year) / f"oanda-{self.root.name}-{year}-{month}.csv"
        data: Dict[datetime, float] = {}
        if f.exists():
            with open(f, "r", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ts = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
                    data[ts] = float(row["close"])
        self._cache[key] = data
        return data   # bounded naturally: <=132 months (2010-2020) per series, ~400MB worst case

    def price_at_or_after(self, ts: datetime, max_search_min: int = 30) -> Optional[float]:
        """First M1 close at or after ts, searching forward up to max_search_min."""
        t = ts.replace(second=0, microsecond=0)
        end = ts + timedelta(minutes=max_search_min)
        while t <= end:
            month = self._load_month(t.year, t.month)
            if t in month:
                return month[t]
            t += timedelta(minutes=1)
        return None


class H1Series:
    """Wraps existing dev H1 bars for USDJPY/USDCHF (no M1 available)."""

    def __init__(self, symbol: str):
        bars = load_dev_bars(R / "data/csv" / f"{symbol}_H1.csv")
        self._by_ts = {b.ts: b.close for b in bars}
        self._sorted = sorted(self._by_ts)

    def price_at_or_after(self, ts: datetime, max_search_hours: int = 6) -> Optional[float]:
        import bisect
        i = bisect.bisect_left(self._sorted, ts)
        if i < len(self._sorted) and (self._sorted[i] - ts).total_seconds() <= max_search_hours * 3600:
            return self._by_ts[self._sorted[i]]
        return None


_FX_SERIES_CACHE: Dict[str, object] = {}
_DRIVER_SERIES_CACHE: Dict[str, M1Series] = {}


def fx_series(symbol: str) -> object:
    """Memoized across pairings -- XAUUSD is used by two pairings and must
    not reload its M1 months twice."""
    if symbol not in _FX_SERIES_CACHE:
        _FX_SERIES_CACHE[symbol] = (M1Series(FX_M1_ROOT, FX_M1_FOLDERS[symbol])
                                    if symbol in FX_M1_SYMBOLS else H1Series(symbol))
    return _FX_SERIES_CACHE[symbol]


def driver_series(name: str) -> M1Series:
    """Memoized across pairings -- US10Y and SPX500 are each used more than once."""
    if name not in _DRIVER_SERIES_CACHE:
        _DRIVER_SERIES_CACHE[name] = M1Series(FX_M1_ROOT, DRIVER_FOLDERS[name])
    return _DRIVER_SERIES_CACHE[name]


# -------------------------------------------------------------- event pool

def usd_events(dev_end: datetime) -> List[MacroEvent]:
    """NFP + CPI y/y, USD, HIGH impact, within M1 coverage AND dev_end."""
    all_ev = load_events(R / "data/events/raw/forexfactory_2010_2023.csv", dev_end=dev_end)
    keep = {"Non-Farm Employment Change", "CPI y/y"}
    ev = [e for e in all_ev if e.currency == "USD" and e.impact == "HIGH" and e.name in keep]
    return [e for e in ev if M1_YEAR_RANGE.start <= e.ts.year <= M1_YEAR_RANGE.stop - 1]


# ------------------------------------------------------------- mechanisms

SURPRISE_FX_DIR = {"EURUSD": -1, "GBPUSD": -1, "XAUUSD": -1, "USDJPY": +1, "USDCHF": +1}


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _entry_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(seconds=ENTRY_DELAY_SEC)


def _impulse_ts(event_ts: datetime) -> datetime:
    return event_ts + timedelta(minutes=IMPULSE_WINDOW_MIN)


def _exit_ts(event_ts: datetime, window_min: int) -> datetime:
    return event_ts + timedelta(minutes=window_min)


def trade_dc(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
            window_min: int, cost: float) -> Optional[float]:
    """CROSS_ASSET_DIVERGENCE: FX hasn't followed the driver's impulse -> bet on convergence."""
    if window_min <= IMPULSE_WINDOW_MIN:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)
    d0, d1 = driver.price_at_or_after(t_entry), driver.price_at_or_after(t_imp)
    f0, f1 = fx.price_at_or_after(t_entry), fx.price_at_or_after(t_imp)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f0, f1, f2) or d0 <= 0 or f0 <= 0 or f1 <= 0:
        return None
    driver_move = math.log(d1 / d0)
    fx_aligned_move = base_dir * math.log(f1 / f0)
    expected_dir = base_dir * _sign(driver_move)
    if expected_dir == 0 or fx_aligned_move > 0:
        return None   # no real driver move, or FX already followed -- no divergence
    gross = expected_dir * math.log(f2 / f1)
    return gross - cost


def trade_sc(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
            window_min: int, cost: float) -> Optional[float]:
    """SURPRISE_CONFIRMATION: trade the surprise direction only if the driver confirms it."""
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
        return None   # driver does not confirm the surprise-implied direction
    gross = implied_from_surprise * math.log(f2 / f0)
    return gross - cost


def trade_dr(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
            window_min: int, cost: float) -> Optional[float]:
    """DELAYED_REACTION: follow the driver's impulse move, entering after it, unconditionally."""
    if window_min <= IMPULSE_WINDOW_MIN:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)
    d0, d1 = driver.price_at_or_after(t_entry), driver.price_at_or_after(t_imp)
    f1 = fx.price_at_or_after(t_imp)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f1, f2) or d0 <= 0 or f1 <= 0:
        return None
    expected_dir = base_dir * _sign(math.log(d1 / d0))
    if expected_dir == 0:
        return None
    gross = expected_dir * math.log(f2 / f1)
    return gross - cost


def trade_ri(event: MacroEvent, fx, driver, symbol: str, base_dir: int,
            window_min: int, cost: float) -> Optional[float]:
    """REVERSAL_AFTER_IMPULSE: fade the driver's impulse-implied direction."""
    if window_min <= IMPULSE_WINDOW_MIN:
        return None
    t_entry, t_imp, t_exit = _entry_ts(event.ts), _impulse_ts(event.ts), _exit_ts(event.ts, window_min)
    d0, d1 = driver.price_at_or_after(t_entry), driver.price_at_or_after(t_imp)
    f1 = fx.price_at_or_after(t_imp)
    f2 = fx.price_at_or_after(t_exit)
    if None in (d0, d1, f1, f2) or d0 <= 0 or f1 <= 0:
        return None
    expected_dir = base_dir * _sign(math.log(d1 / d0))
    if expected_dir == 0:
        return None
    gross = -expected_dir * math.log(f2 / f1)   # fade the DR direction
    return gross - cost


MECHANISMS = {
    "DC_CROSS_ASSET_DIVERGENCE": trade_dc,
    "SC_SURPRISE_CONFIRMATION": trade_sc,
    "DR_DELAYED_REACTION": trade_dr,
    "RI_REVERSAL_AFTER_IMPULSE": trade_ri,
}


# ------------------------------------------------------------------ sweep

def evaluate_pairing(symbol: str, driver_name: str, base_dir: int, mechanism: str,
                     mech_fn, events: List[MacroEvent], fx=None, driver=None) -> List[Dict]:
    fx = fx if fx is not None else fx_series(symbol)
    driver = driver if driver is not None else driver_series(driver_name)
    cost = roundtrip_cost(symbol)
    windows = WINDOWS_MIN_FULL if symbol in FX_M1_SYMBOLS else WINDOWS_MIN_H1ONLY
    blocked = [] if symbol in FX_M1_SYMBOLS else [w for w in WINDOWS_MIN_FULL if w not in windows]

    n_events = len(events)
    cut = int(n_events * 0.80)
    results = []
    for w in windows:
        nets = []
        for e in events:
            r = mech_fn(e, fx, driver, symbol, base_dir, w, cost)
            if r is not None:
                nets.append((e.ts, r))
        # split chronologically at the event pool's 80/20 boundary
        tr_nets, va_nets = [], []
        cutoff_ts = events[cut].ts if cut < n_events else events[-1].ts
        for ts, r in nets:
            (tr_nets if ts < cutoff_ts else va_nets).append(r)

        gm = (sum(abs(x) for x in tr_nets) / len(tr_nets)) if tr_nets else 0.0
        tr_s = stats(tr_nets, gm + cost, cost)
        va_s = stats(va_nets, 0.0, cost)
        v, reason = gate(tr_s, va_s)
        results.append({
            "mechanism": mechanism, "symbol": symbol, "driver": driver_name,
            "window_min": w, "entry_delay_sec": ENTRY_DELAY_SEC,
            "events_available": n_events, "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "verdict_reason": reason,
        })
    for w in blocked:
        results.append({
            "mechanism": mechanism, "symbol": symbol, "driver": driver_name,
            "window_min": w, "verdict": "BLOCKED_NO_INTRADAY_DATA",
            "verdict_reason": f"{symbol} has no M1 source; only {WINDOWS_MIN_H1ONLY} testable",
        })
    return results


def main() -> int:
    bars = load_dev_bars(R / "data/csv/EURUSD_H1.csv")
    dev_end = bars[-1].ts
    events = usd_events(dev_end)
    print(f"event pool: {len(events)} USD NFP/CPI events, 2010-{M1_YEAR_RANGE.stop-1}, "
          f"entry delay={ENTRY_DELAY_SEC}s")

    all_results = []
    for symbol, driver_name, base_dir, mechanism_note in PAIRINGS:
        fx = fx_series(symbol)              # loaded once, reused warm across all 4 mechanisms
        driver = driver_series(driver_name)
        for mech_name, mech_fn in MECHANISMS.items():
            all_results.extend(evaluate_pairing(symbol, driver_name, base_dir, mech_name,
                                                mech_fn, events, fx=fx, driver=driver))

    tested = [r for r in all_results if r["verdict"] != "BLOCKED_NO_INTRADAY_DATA"]
    blocked = [r for r in all_results if r["verdict"] == "BLOCKED_NO_INTRADAY_DATA"]
    survivors = [r for r in tested if r["verdict"] == "DISCOVERY_SURVIVOR"]

    payload = {
        "cycle_id": "CYCLE-08-EVENT-CROSSASSET-INTRADAY",
        "self_critique": ("5m/15m/30m windows require genuine sub-hourly FX prices. Only "
                          "EURUSD/GBPUSD/XAUUSD have real M1 data (Oanda, via "
                          "FutureSharks/financial-data, same audited source as Cycle 7). "
                          "USDJPY/USDCHF have no M1 source found (histdata.com blocked; "
                          "philipperemy/FX-1-Minute-Data is an API client with no committed "
                          "data, confirmed not assumed) and are tested ONLY at 1H/2H/4H; "
                          "5m/15m/30m for these two are BLOCKED_NO_INTRADAY_DATA, not "
                          "approximated from H1 bars."),
        "execution_delay_sec": ENTRY_DELAY_SEC,
        "event_pool_size": len(events),
        "parameter_evaluations": len(tested),
        "blocked_combinations": len(blocked),
        "survivor_count": len(survivors),
        "survivors": survivors,
        "results": all_results,
    }
    out = R / "reports/factory/discovery_cycles/cycle_08_intraday.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    by_mech = {}
    for r in tested:
        by_mech.setdefault(r["mechanism"], {})
        by_mech[r["mechanism"]][r["verdict"]] = by_mech[r["mechanism"]].get(r["verdict"], 0) + 1
    print(f"\nCYCLE 8: {len(tested)} evaluations, {len(blocked)} blocked (no intraday data), "
          f"{len(survivors)} DISCOVERY_SURVIVOR")
    for m in sorted(by_mech):
        print(f"  {m:28s} " + "  ".join(f"{k}={v}" for k, v in sorted(by_mech[m].items())))
    for s in survivors:
        print(f"  SURVIVOR {s['mechanism']} {s['symbol']}/{s['driver']} w={s['window_min']}m "
              f"train t={s['train']['t_stat']} val t={s['validation']['t_stat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
