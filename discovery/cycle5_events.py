"""
GEN 7 CYCLE 5 -- event-driven discovery.

Four families, all keyed to macro release timestamps rather than price shape:

  C1 PRE_EVENT_POSITIONING  directional drift in the 24/48/72h before a release
  C2 SURPRISE_REACTION      sign and size of (actual - forecast) -> post move
  C3 VOLATILITY_EXPANSION   post-release vol spike -> reversion or continuation
  C4 EVENT_SEQUENCE         patterns across consecutive scheduled releases

Holding-period rule, stated before any evaluation runs
------------------------------------------------------
Cycle 4 imposed MIN_HOLDING_HOURS = 24 to stop H1 price patterns being
relabelled as positional trades. That guard was scoped to PRICE-PATTERN
families and does not apply here: an event trade is keyed to an exogenous
release time, not to a price shape, so it is a structurally different
mechanism. Event families are therefore permitted sub-daily windows, and in
exchange they carry two obligations that are NOT relaxed:

  1. realized holding time is MEASURED from bar timestamps and reported
     (the FAIL-000030 lesson -- never infer a horizon from a parameter);
  2. gross/cost > 2.0 still binds, so a short window only qualifies if the
     release genuinely moves price by more than twice the round trip.

Everything else -- n >= 30, train t >= 2.0, validation t >= 1.5 -- is the
Cycle 4 filter, unchanged.
"""

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.observatory import Bar, load_dev_bars, OBSERVATION_FRACTION
from discovery.cost_model import roundtrip_cost, cost_table, COST_MODEL_ID
from discovery.event_calendar import MacroEvent, load_events

MIN_TRADES = 30
TRAIN_MIN_T = 2.0
VAL_MIN_T = 1.5
MIN_GROSS_OVER_COST = 2.0

PRE_WINDOWS_H = (24, 48, 72)
POST_WINDOWS_H = (1, 4, 12, 24, 48)

DEFAULT_EVENTS = REPO_ROOT / "data/events/processed/events_dev.csv"


@dataclass
class EventTrade:
    entry_ts: str
    direction: int
    gross: float
    net: float
    realized_hours: float
    event_id: str


@dataclass
class EStats:
    n: int
    gross_mean: float
    mean_net: float
    t_stat: float
    profit_factor: float
    win_rate: float
    gross_over_cost: float
    median_hold_hours: float

    def to_dict(self) -> Dict:
        return self.__dict__.copy()


def stats(trades: List[EventTrade], cost: float) -> EStats:
    if not trades:
        return EStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    nets = [t.net for t in trades]
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
    gm = sum(abs(t_.gross) for t_ in trades) / n
    hrs = sorted(t_.realized_hours for t_ in trades)
    return EStats(n, round(gm, 8), round(mean, 8), round(t, 3), round(pf, 3),
                  round(sum(1 for x in nets if x > 0) / n, 4),
                  round(gm / cost, 3) if cost else 0.0, round(hrs[n // 2], 2))


def gate(tr: EStats, va: EStats) -> Tuple[str, str]:
    """Cycle 4 economic filter, unchanged. No 24h floor for event families."""
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


# ------------------------------------------------------------------ indexing

def index_bars(bars: List[Bar]) -> Dict[datetime, int]:
    return {b.ts: i for i, b in enumerate(bars)}


def bar_at_or_after(bars: List[Bar], ts: datetime, lo: int = 0) -> Optional[int]:
    """First bar index whose timestamp is >= ts. Linear scan from `lo`."""
    for i in range(lo, len(bars)):
        if bars[i].ts >= ts:
            return i
    return None


def _trade(bars: List[Bar], i: int, j: int, direction: int, cost: float,
           event_id: str) -> Optional[EventTrade]:
    if i is None or j is None or j <= i or j >= len(bars):
        return None
    gross = direction * math.log(bars[j].close / bars[i].close)
    hours = (bars[j].ts - bars[i].ts).total_seconds() / 3600.0
    return EventTrade(bars[i].ts.isoformat(), direction, round(gross, 8),
                      round(gross - cost, 8), round(hours, 2), event_id)


# ------------------------------------------------------------------ families

def c1_pre_event(bars: List[Bar], events: List[MacroEvent], pre_h: int,
                 direction: int, cost: float) -> List[EventTrade]:
    """Enter `pre_h` hours before the release, exit at the release bar."""
    out = []
    for e in events:
        j = bar_at_or_after(bars, e.ts)
        i = bar_at_or_after(bars, e.ts - timedelta(hours=pre_h))
        t = _trade(bars, i, j, direction, cost, e.event_id)
        if t:
            out.append(t)
    return out


def c2_surprise(bars: List[Bar], events: List[MacroEvent], post_h: int,
                mode: str, cost: float) -> List[EventTrade]:
    """
    Trade the sign of (actual - forecast). Requires both fields; events
    lacking them are skipped, never imputed.
    """
    out = []
    for e in events:
        s = e.surprise
        if s is None or s == 0:
            continue
        d = 1 if s > 0 else -1
        if mode == "FADE":
            d = -d
        i = bar_at_or_after(bars, e.ts)
        j = bar_at_or_after(bars, e.ts + timedelta(hours=post_h), i or 0)
        t = _trade(bars, i, j, d, cost, e.event_id)
        if t:
            out.append(t)
    return out


def c3_volatility(bars: List[Bar], events: List[MacroEvent], post_h: int,
                  mode: str, cost: float) -> List[EventTrade]:
    """
    The release bar's own move defines the direction; CONTINUATION follows it,
    REVERSION fades it. This is the family that needs no actual/forecast.
    """
    out = []
    for e in events:
        i = bar_at_or_after(bars, e.ts)
        if i is None or i == 0:
            continue
        move = 1 if bars[i].close > bars[i - 1].close else -1
        d = move if mode == "CONTINUATION" else -move
        j = bar_at_or_after(bars, e.ts + timedelta(hours=post_h), i)
        t = _trade(bars, i, j, d, cost, e.event_id)
        if t:
            out.append(t)
    return out


def c4_sequence(bars: List[Bar], events: List[MacroEvent], post_h: int,
                mode: str, cost: float) -> List[EventTrade]:
    """
    Condition on the PREVIOUS release of the same event type: trade only when
    the prior instance's post-release move had the same sign (streak) or the
    opposite sign (alternation).
    """
    out = []
    by_name: Dict[str, List[MacroEvent]] = {}
    for e in events:
        by_name.setdefault(e.name, []).append(e)
    for name, seq in by_name.items():
        prev_move = None
        for e in seq:
            i = bar_at_or_after(bars, e.ts)
            if i is None or i == 0:
                continue
            move = 1 if bars[i].close > bars[i - 1].close else -1
            if prev_move is not None:
                d = prev_move if mode == "STREAK" else -prev_move
                j = bar_at_or_after(bars, e.ts + timedelta(hours=post_h), i)
                t = _trade(bars, i, j, d, cost, e.event_id)
                if t:
                    out.append(t)
            prev_move = move
    return out


# --------------------------------------------------- derivable NFP calendar

def derive_nfp_events(bars: List[Bar]) -> List[MacroEvent]:
    """
    The ONLY event schedule this project may derive without a calendar file.

    Non-Farm Payrolls is released at 08:30 America/New_York on the first Friday
    of each month -- a deterministic rule, not recalled data. In UTC that is
    12:30 under EDT and 13:30 under EST, so the containing H1 bar is 12:00Z or
    13:00Z respectively. US DST runs from the second Sunday of March to the
    first Sunday of November.

    FOMC, CPI, GDP and rate decisions have irregular published schedules and
    are NOT derivable. Writing them from memory would fabricate data, so this
    function does not attempt it.
    """
    def dst_us(d: datetime) -> bool:
        # second Sunday of March .. first Sunday of November
        mar = datetime(d.year, 3, 1)
        second_sun = mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)
        nov = datetime(d.year, 11, 1)
        first_sun = nov + timedelta(days=(6 - nov.weekday()) % 7)
        return second_sun <= d < first_sun

    months, out = set(), []
    for b in bars:
        d = b.ts
        if d.weekday() != 4 or d.day > 7:
            continue
        key = (d.year, d.month)
        if key in months:
            continue
        months.add(key)
        hour = 12 if dst_us(d) else 13
        ts = datetime(d.year, d.month, d.day, hour, 30)
        out.append(MacroEvent(ts=ts, event_id=f"NFP-{d.year}{d.month:02d}",
                              name="Non-Farm Payrolls", country="US",
                              currency="USD", impact="HIGH",
                              source="derived:first-friday-0830ET"))
    out.sort(key=lambda e: e.ts)
    return out


# --------------------------------------------------------------- sweep

FEASIBLE_SYMBOLS = ["GBPUSD", "USDCAD", "USDCHF", "USDJPY", "XAUUSD"]


def sweep_symbol(symbol: str, events: List[MacroEvent], source: str) -> List[Dict]:
    bars = load_dev_bars(REPO_ROOT / "data/csv" / f"{symbol}_H1.csv")
    cut_i = int(len(bars) * OBSERVATION_FRACTION)
    tr_bars, va_bars = bars[:cut_i], bars[cut_i:]
    cut_ts = bars[cut_i].ts
    tr_ev = [e for e in events if e.ts < cut_ts]
    va_ev = [e for e in events if e.ts >= cut_ts]
    cost = roundtrip_cost(symbol)
    res: List[Dict] = []

    def emit(family, params, fn):
        tr = stats(fn(tr_bars, tr_ev), cost)
        va = stats(fn(va_bars, va_ev), cost)
        v, r = gate(tr, va)
        res.append({"family": family, "symbol": symbol, "event_source": source,
                    "params": params, "train": tr.to_dict(),
                    "validation": va.to_dict(), "verdict": v, "verdict_reason": r})

    for pre in PRE_WINDOWS_H:
        for d in (1, -1):
            emit("C1_PRE_EVENT_POSITIONING", {"pre_hours": pre, "dir": d},
                 lambda b, e, pre=pre, d=d: c1_pre_event(b, e, pre, d, cost))
    for post in POST_WINDOWS_H:
        for mode in ("CONTINUATION", "REVERSION"):
            emit("C3_VOLATILITY_EXPANSION", {"post_hours": post, "mode": mode},
                 lambda b, e, post=post, mode=mode: c3_volatility(b, e, post, mode, cost))
    for post in POST_WINDOWS_H:
        for mode in ("STREAK", "ALTERNATION"):
            emit("C4_EVENT_SEQUENCE", {"post_hours": post, "mode": mode},
                 lambda b, e, post=post, mode=mode: c4_sequence(b, e, post, mode, cost))
    return res


def main() -> int:
    have_file = DEFAULT_EVENTS.exists()
    results: List[Dict] = []
    skipped = []

    for sym in ["EURUSD"] + FEASIBLE_SYMBOLS:
        bars = load_dev_bars(REPO_ROOT / "data/csv" / f"{sym}_H1.csv")
        events = (load_events(DEFAULT_EVENTS) if have_file
                  else derive_nfp_events(bars))
        source = "supplied_calendar" if have_file else "derived:NFP-first-friday"
        cut_ts = bars[int(len(bars) * OBSERVATION_FRACTION)].ts
        n_va = sum(1 for e in events if e.ts >= cut_ts)
        if n_va < MIN_TRADES:
            skipped.append({"symbol": sym, "reason": "STRUCTURALLY_UNDERPOWERED",
                            "validation_events": n_va, "required": MIN_TRADES,
                            "note": "declared before evaluation; costs no parameter evaluations"})
            continue
        results.extend(sweep_symbol(sym, events, source))

    survivors = [r for r in results if r["verdict"] == "DISCOVERY_SURVIVOR"]
    by_family: Dict[str, Dict[str, int]] = {}
    for r in results:
        by_family.setdefault(r["family"], {})
        by_family[r["family"]][r["verdict"]] = by_family[r["family"]].get(r["verdict"], 0) + 1

    payload = {
        "cycle_id": "CYCLE-05-EVENT-DRIVEN",
        "event_source": "supplied_calendar" if have_file else "derived:NFP-first-friday",
        "event_data_status": ("SUPPLIED" if have_file else
                              "NOT_SUPPLIED -- only the deterministic NFP schedule "
                              "is derivable; FOMC/CPI/GDP/rates require a calendar file"),
        "families_runnable": ["C1_PRE_EVENT_POSITIONING", "C3_VOLATILITY_EXPANSION",
                              "C4_EVENT_SEQUENCE"],
        "families_blocked": {"C2_SURPRISE_REACTION":
                             "requires actual and forecast fields; not derivable"},
        "cost_model_id": COST_MODEL_ID, "cost_table": cost_table(),
        "economic_filter": {"min_trades": MIN_TRADES, "train_min_t": TRAIN_MIN_T,
                            "val_min_t": VAL_MIN_T,
                            "min_gross_over_cost": MIN_GROSS_OVER_COST,
                            "holding_floor": "not applicable to event families; "
                                             "realized hold is measured and reported"},
        "symbols_skipped_before_evaluation": skipped,
        "parameter_evaluations": len(results),
        "survivor_count": len(survivors), "survivors": survivors,
        "family_breakdown": by_family, "results": results,
    }
    out = REPO_ROOT / "reports/factory/discovery_cycles/cycle_05_event_sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"CYCLE 5: {len(results)} parameter evaluations, {len(survivors)} DISCOVERY_SURVIVOR")
    for s in skipped:
        print(f"  SKIPPED {s['symbol']}: {s['reason']} (val events={s['validation_events']})")
    for fam in sorted(by_family):
        print(f"  {fam:28s} " + "  ".join(f"{k}={v}" for k, v in sorted(by_family[fam].items())))
    for s in survivors:
        print(f"  SURVIVOR {s['family']} {s['symbol']} {s['params']} "
              f"train t={s['train']['t_stat']} val t={s['validation']['t_stat']} "
              f"g/c={s['train']['gross_over_cost']} hold={s['train']['median_hold_hours']}h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
