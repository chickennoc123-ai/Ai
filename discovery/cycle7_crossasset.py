"""
GEN 7 CYCLE 7 -- Phase 2: cross-asset search.

Pre-registered mechanisms (fixed before any evaluation), lagged 1 trading day
so the signal is actually tradeable (yesterday's cross-asset close informs
today's FX/gold trade, never same-day contemporaneous correlation):

  H_OIL_CAD   WTI up  => CAD strengthens (oil exporter)      => short USDCAD
  H_SPX_JPY   SPX up  => risk-on, JPY funding-currency sold   => long USDJPY
  H_SPX_CHF   SPX up  => risk-on, CHF safe-haven sold         => long USDCHF
  H_SPX_XAU   SPX down => risk-off, gold bid (safe haven)     => short XAUUSD on SPX up
  H_US10Y_EUR US10Y price up (yield down, dovish) => USD carry
              less attractive => long EURUSD
  H_OIL_XAU   oil up => inflation-expectation co-movement     => long XAUUSD
              (weakest prior of the six -- flagged as exploratory, not a
              named textbook mechanism like the other five)

No DXY series was acquired (every direct source is network-blocked, same as
prior cycles). A DXY PROXY is NOT used as a standalone tradeable signal here
-- regressing EURUSD-heavy DXY against EURUSD itself would be close to
tautological. It is reported in Phase 0 for completeness only.

Data: WTICO/US10Y/SPX500 daily, resampled from Oanda M1 (FutureSharks/
financial-data), 2010-01-04 .. 2020-05-14. This is a REDUCED window relative
to the FX dev windows (which extend to 2022-2023) -- stated here, not
discovered after the fact. Split 80/20 train/validation on the OVERLAP
window only.
"""
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))

from discovery.observatory import load_dev_bars
from discovery.cycle4_economics import to_daily, DayBar
from discovery.cost_model import roundtrip_cost

MIN_TRADES = 30
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_GROSS_OVER_COST = 2.0

CROSSASSET_DIR = R / "data/crossasset/processed"
HOLD_DAYS = (1, 2)   # pre-registered: next-day and 2-day hold


@dataclass
class XStats:
    n: int
    mean_net: float
    t_stat: float
    profit_factor: float
    win_rate: float
    gross_over_cost: float

    def to_dict(self) -> Dict:
        return self.__dict__.copy()


def load_series(name: str) -> Dict:
    rows = list(csv.DictReader(open(CROSSASSET_DIR / f"{name}_D1.csv")))
    return {datetime.fromisoformat(r["date"]).date(): float(r["close"]) for r in rows}


def load_fx_daily(symbol: str) -> List[DayBar]:
    bars = load_dev_bars(R / "data/csv" / f"{symbol}_H1.csv")
    return to_daily(bars)


def stats(rets: List[float]) -> XStats:
    if not rets:
        return XStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(rets)
    mean = sum(rets) / n
    if n > 1:
        var = sum((x - mean) ** 2 for x in rets) / (n - 1)
        t = mean / math.sqrt(var / n) if var > 0 else 0.0
    else:
        t = 0.0
    gains = sum(x for x in rets if x > 0)
    losses = -sum(x for x in rets if x < 0)
    pf = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    return XStats(n, round(mean, 8), round(t, 3), round(pf, 3),
                  round(sum(1 for x in rets if x > 0) / n, 4), 0.0)


def gate(tr: XStats, va: XStats) -> Tuple[str, str]:
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


def _lagged_signal(driver: Dict, dates: List) -> Dict:
    """sign of the driver's own daily log return, lagged 1 day (tradeable)."""
    ordered = sorted(driver)
    sig = {}
    for i in range(1, len(ordered)):
        d0, d1 = ordered[i - 1], ordered[i]
        r = math.log(driver[d1] / driver[d0])
        sig[d1] = 1 if r > 0 else (-1 if r < 0 else 0)
    return sig


HYPOTHESES = [
    ("H_OIL_CAD", "WTICO", "USDCAD", -1, "WTI up -> CAD strengthens -> short USDCAD"),
    ("H_SPX_JPY", "SPX500", "USDJPY", +1, "SPX up -> risk-on, JPY sold -> long USDJPY"),
    ("H_SPX_CHF", "SPX500", "USDCHF", +1, "SPX up -> risk-on, CHF sold -> long USDCHF"),
    ("H_SPX_XAU", "SPX500", "XAUUSD", -1, "SPX up -> risk-on, gold sold -> short XAUUSD"),
    ("H_US10Y_EUR", "US10Y", "EURUSD", +1, "US10Y price up (yield down) -> USD carry less attractive -> long EURUSD"),
    ("H_OIL_XAU", "WTICO", "XAUUSD", +1, "oil up -> inflation co-movement -> long XAUUSD (exploratory, weak prior)"),
]


def evaluate(name: str, driver_name: str, symbol: str, base_dir: int,
            mechanism: str) -> List[Dict]:
    driver = load_series(driver_name)
    fx_days = load_fx_daily(symbol)
    fx_by_date = {d.date.date(): d for d in fx_days}
    common_dates = sorted(set(driver) & set(fx_by_date))
    signal = _lagged_signal(driver, common_dates)
    cost = roundtrip_cost(symbol)

    # split 80/20 chronologically on the OVERLAP window only
    n_common = len(common_dates)
    cut_date = common_dates[int(n_common * 0.80)]

    results = []
    for hold in HOLD_DAYS:
        tr_rets, va_rets = [], []
        idx_by_date = {d: i for i, d in enumerate(common_dates)}
        for date in common_dates:
            sig = signal.get(date)
            if not sig:
                continue
            i = idx_by_date[date]
            if i + hold >= len(common_dates):
                continue
            exit_date = common_dates[i + hold]
            entry_fx = fx_by_date[date].close
            exit_fx = fx_by_date[exit_date].close
            direction = base_dir * sig
            gross = direction * math.log(exit_fx / entry_fx)
            net = gross - cost
            (tr_rets if date < cut_date else va_rets).append(net)

        tr_s, va_s = stats(tr_rets), stats(va_rets)
        gm_tr = (sum(abs(x) for x in tr_rets) / len(tr_rets)) if tr_rets else 0.0
        tr_s.gross_over_cost = round((gm_tr + cost) / cost, 3) if cost else 0.0
        v, reason = gate(tr_s, va_s)
        results.append({
            "hypothesis": name, "driver": driver_name, "symbol": symbol,
            "mechanism": mechanism, "params": {"hold_days": hold, "base_dir": base_dir},
            "train": tr_s.to_dict(), "validation": va_s.to_dict(),
            "verdict": v, "verdict_reason": reason,
            "overlap_window": {"start": str(common_dates[0]), "end": str(common_dates[-1]),
                               "n_days": n_common},
        })
    return results


def main() -> int:
    all_results = []
    for name, driver, symbol, base_dir, mechanism in HYPOTHESES:
        all_results.extend(evaluate(name, driver, symbol, base_dir, mechanism))

    survivors = [r for r in all_results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    payload = {
        "cycle_id": "CYCLE-07-CROSSASSET", "stage": "Phase 2 cross-asset search",
        "data_source": "FutureSharks/financial-data (Oanda M1, resampled to D1)",
        "overlap_limitation": ("Cross-asset data covers 2010-01-04..2020-05-14 only; "
                               "FX dev windows extend to 2022-2023. Evaluated on the "
                               "OVERLAP window, which is smaller than the full FX dev window."),
        "dxy_note": "No direct DXY source acquired (network-blocked); not used as a signal.",
        "parameter_evaluations": len(all_results),
        "survivor_count": len(survivors), "survivors": survivors,
        "results": all_results,
    }
    out = R / "reports/factory/discovery_cycles/cycle_07_crossasset.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"CYCLE 7 PHASE 2: {len(all_results)} evaluations, {len(survivors)} DISCOVERY_SURVIVOR")
    for name, driver, symbol, base_dir, mechanism in HYPOTHESES:
        rows = [r for r in all_results if r["hypothesis"] == name]
        print(f"\n{name}: {mechanism}")
        for r in rows:
            print(f"    hold={r['params']['hold_days']}d  {r['verdict']:22s} "
                  f"train(n={r['train']['n']},t={r['train']['t_stat']:+.2f}) "
                  f"val(n={r['validation']['n']},t={r['validation']['t_stat']:+.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
