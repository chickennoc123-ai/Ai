"""
EA GENERATOR: frozen candidate specification -> MT5 / MT4 / TradingView code.

The generator is deliberately the narrowest part of the factory. It refuses to
emit anything for a candidate that has not PASSED GEN 14 against the sealed
holdout. That refusal is the whole point: an EA is the artifact a human will
put real money behind, so nothing that skipped a gate may ever be packaged.

Supported test frameworks (the ones GEN 7 actually emits):
    streak_fade  -- fade the n-th consecutive same-direction bar
    gap_fade     -- fade the weekend gap, time-boxed exit
    breakout     -- N-bar high/low breakout, optional NR7 no-trade filter
    hour_drift   -- fixed-hour directional drift
"""

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.candidate_spec_registry import CandidateSpecRegistry
from discovery.holdout_authorization import HoldoutAuthorizationGate

SUPPORTED_FRAMEWORKS = ("streak_fade", "gap_fade", "breakout", "hour_drift")


class UnqualifiedCandidateError(RuntimeError):
    """Raised when packaging is attempted for a candidate that did not pass GEN 14."""


@dataclass
class EAPackage:
    candidate_id: str
    symbol: str
    spec_hash: str
    files: Dict[str, Path]

    def to_dict(self) -> Dict:
        return {"candidate_id": self.candidate_id, "symbol": self.symbol,
                "spec_hash": self.spec_hash,
                "files": {k: str(v) for k, v in self.files.items()}}


class EAGenerator:
    def __init__(self, registry: CandidateSpecRegistry, gate: HoldoutAuthorizationGate):
        self.registry = registry
        self.gate = gate

    # -- gate -------------------------------------------------------------
    def _require_qualified(self, candidate_id: str):
        spec = self.registry.get_candidate(candidate_id)
        if spec is None:
            raise UnqualifiedCandidateError(f"{candidate_id} is not registered")
        if not spec.is_frozen():
            raise UnqualifiedCandidateError(
                f"{candidate_id} specification is not frozen; only a frozen, "
                f"GEN 14-passed candidate may be packaged")
        if not self.gate.has_gen14_result(candidate_id):
            raise UnqualifiedCandidateError(
                f"{candidate_id} has no terminal GEN 14 result; packaging an "
                f"unqualified candidate is forbidden")
        result = self.gate.authorizations[candidate_id].result
        if result != "PASS":
            raise UnqualifiedCandidateError(
                f"{candidate_id} carries GEN 14 verdict {result!r}; only PASS may "
                f"be packaged into a tradable EA")
        if spec.test_framework not in SUPPORTED_FRAMEWORKS:
            raise UnqualifiedCandidateError(
                f"no generator template for framework {spec.test_framework!r}")
        return spec

    # -- signal blocks ----------------------------------------------------
    @staticmethod
    def _mql_signal(spec) -> str:
        p, fw = spec.parameters, spec.test_framework
        if fw == "streak_fade":
            k = int(p.get("k", 3))
            return f"""   int streak = StreakLength();
   if(MathAbs(streak) < {k}) return(0);
   if(!HourAllowed()) return(0);
   if(!VolFilterOk()) return(0);
   return(streak > 0 ? -1 : 1);   // fade the run"""
        if fw == "gap_fade":
            mg = float(p.get("min_gap", 0.0))
            return f"""   if(!IsWeekendGapBar()) return(0);
   double gap = iOpen(_Symbol,_Period,0) - iClose(_Symbol,_Period,1);
   if(MathAbs(gap)/iClose(_Symbol,_Period,1) < {mg}) return(0);
   return(gap > 0 ? -1 : 1);      // fade the gap"""
        if fw == "breakout":
            lb = int(p.get("lookback", 4))
            return f"""   if(UseNR7Filter && IsNR7()) return(0);
   double hi = Highest({lb}), lo = Lowest({lb});
   double c  = iClose(_Symbol,_Period,1);
   if(c > hi) return(1);
   if(c < lo) return(-1);
   return(0);"""
        hour_long = int(p.get("hour_long", 6)); hour_short = int(p.get("hour_short", 4))
        return f"""   int h = HourOfBar();
   if(h == {hour_long})  return(1);
   if(h == {hour_short}) return(-1);
   return(0);"""

    @staticmethod
    def _pine_signal(spec) -> str:
        p, fw = spec.parameters, spec.test_framework
        if fw == "streak_fade":
            k = int(p.get("k", 3))
            return (f"streak = ta.barssince(close <= open) \n"
                    f"upRun  = ta.rising(close, {k})\n"
                    f"dnRun  = ta.falling(close, {k})\n"
                    f"long_  = dnRun and hourOk and volOk\n"
                    f"short_ = upRun and hourOk and volOk")
        if fw == "gap_fade":
            return ("isGapBar = dayofweek == dayofweek.sunday or "
                    "(time - time[1]) > 40 * 60 * 60 * 1000\n"
                    "gap    = open - close[1]\n"
                    "long_  = isGapBar and gap < 0\n"
                    "short_ = isGapBar and gap > 0")
        if fw == "breakout":
            lb = int(p.get("lookback", 4))
            return (f"hh = ta.highest(high, {lb})[1]\n"
                    f"ll = ta.lowest(low, {lb})[1]\n"
                    f"long_  = close > hh and not nr7\n"
                    f"short_ = close < ll and not nr7")
        hl = int(p.get("hour_long", 6)); hs = int(p.get("hour_short", 4))
        return (f"long_  = hour == {hl}\n"
                f"short_ = hour == {hs}")

    # -- renderers --------------------------------------------------------
    def _mql5(self, spec, symbol: str) -> str:
        p = spec.parameters
        hours = p.get("hours")
        h_lo, h_hi = (hours[0], hours[1]) if hours else (0, 24)
        return f"""//+------------------------------------------------------------------+
//| {spec.candidate_id}.mq5                                          
//| Generated by AGLE Strategy Factory -- GEN 14 QUALIFIED           
//| spec_hash : {spec.spec_hash}                                     
//| mechanism : {spec.mechanism}
//| framework : {spec.test_framework}   symbol: {symbol}
//| Parameters below are FROZEN. Changing them voids qualification.  
//+------------------------------------------------------------------+
#property strict
#include <Trade\\Trade.mqh>
CTrade trade;

input double InpRiskPercent  = 0.50;    // risk per trade (% of equity)
input int    InpHoldBars     = {int(p.get('horizon', p.get('horizon_bars', 1)))};      // frozen holding horizon
input int    InpStreakK      = {int(p.get('k', 3))};      // frozen streak length
input int    InpHourFrom     = {h_lo};
input int    InpHourTo       = {h_hi};
input bool   UseVolFilter    = {'true' if p.get('vol_above_median') else 'false'};
input bool   UseNR7Filter    = {'true' if p.get('nr7_filter') else 'false'};
input int    InpMagic        = 20260820;

datetime lastBar = 0;
int      barsInTrade = 0;

int HourOfBar() {{ MqlDateTime t; TimeToStruct(iTime(_Symbol,_Period,1), t); return t.hour; }}
bool HourAllowed() {{ int h = HourOfBar(); return (h >= InpHourFrom && h < InpHourTo); }}

int StreakLength()
{{
   int dir = 0, len = 0;
   for(int i = 1; i <= 20; i++)
   {{
      int d = (iClose(_Symbol,_Period,i) > iClose(_Symbol,_Period,i+1)) ? 1 : -1;
      if(i == 1) {{ dir = d; len = 1; }}
      else if(d == dir) len++;
      else break;
   }}
   return dir * len;
}}

double ATR(int period) {{ return iATR(_Symbol, _Period, period, 1); }}

bool VolFilterOk()
{{
   if(!UseVolFilter) return(true);
   return(ATR(14) > ATR(50));
}}

bool IsNR7()
{{
   double r0 = iHigh(_Symbol,_Period,1) - iLow(_Symbol,_Period,1);
   for(int i = 2; i <= 7; i++)
      if(iHigh(_Symbol,_Period,i) - iLow(_Symbol,_Period,i) < r0) return(false);
   return(true);
}}

bool IsWeekendGapBar()
{{ return((iTime(_Symbol,_Period,1) - iTime(_Symbol,_Period,2)) > 40*3600); }}

double Highest(int n) {{ return iHigh(_Symbol,_Period,iHighest(_Symbol,_Period,MODE_HIGH,n,2)); }}
double Lowest (int n) {{ return iLow (_Symbol,_Period,iLowest (_Symbol,_Period,MODE_LOW ,n,2)); }}

int Signal()
{{
{self._mql_signal(spec)}
}}

double LotSize()
{{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk   = equity * InpRiskPercent / 100.0;
   double atr    = ATR(14);
   double tickV  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickS  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(atr <= 0 || tickV <= 0 || tickS <= 0) return(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN));
   double lots = risk / ((atr * 2.0 / tickS) * tickV);
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots/st)*st;
   return(MathMax(mn, MathMin(mx, lots)));
}}

int OnInit() {{ trade.SetExpertMagicNumber(InpMagic); return(INIT_SUCCEEDED); }}

void OnTick()
{{
   datetime t = iTime(_Symbol, _Period, 0);
   if(t == lastBar) return;             // one decision per closed bar
   lastBar = t;

   if(PositionSelect(_Symbol))
   {{
      barsInTrade++;
      if(barsInTrade >= InpHoldBars) {{ trade.PositionClose(_Symbol); barsInTrade = 0; }}
      return;
   }}

   int sig = Signal();
   if(sig == 0) return;

   double lots = LotSize();
   double atr  = ATR(14);
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(sig > 0) trade.Buy (lots, _Symbol, ask, ask - 2.0*atr, ask + 3.0*atr);
   else        trade.Sell(lots, _Symbol, bid, bid + 2.0*atr, bid - 3.0*atr);
   barsInTrade = 0;
}}
"""

    def _mql4(self, spec, symbol: str) -> str:
        p = spec.parameters
        hours = p.get("hours")
        h_lo, h_hi = (hours[0], hours[1]) if hours else (0, 24)
        return f"""//+------------------------------------------------------------------+
//| {spec.candidate_id}.mq4  -- AGLE Strategy Factory (GEN 14 QUALIFIED)
//| spec_hash : {spec.spec_hash}
//| mechanism : {spec.mechanism}
//+------------------------------------------------------------------+
#property strict

extern double InpRiskPercent = 0.50;
extern int    InpHoldBars    = {int(p.get('horizon', p.get('horizon_bars', 1)))};
extern int    InpStreakK     = {int(p.get('k', 3))};
extern int    InpHourFrom    = {h_lo};
extern int    InpHourTo      = {h_hi};
extern bool   UseVolFilter   = {'true' if p.get('vol_above_median') else 'false'};
extern bool   UseNR7Filter   = {'true' if p.get('nr7_filter') else 'false'};
extern int    InpMagic       = 20260820;

datetime lastBar = 0;

int HourOfBar()   {{ return TimeHour(Time[1]); }}
bool HourAllowed(){{ int h = HourOfBar(); return (h >= InpHourFrom && h < InpHourTo); }}
double ATRv(int p_) {{ return iATR(NULL, 0, p_, 1); }}
bool VolFilterOk(){{ if(!UseVolFilter) return(true); return(ATRv(14) > ATRv(50)); }}

int StreakLength()
{{
   int dir = 0, len = 0;
   for(int i = 1; i <= 20; i++)
   {{
      int d = (Close[i] > Close[i+1]) ? 1 : -1;
      if(i == 1) {{ dir = d; len = 1; }}
      else if(d == dir) len++;
      else break;
   }}
   return(dir * len);
}}

bool IsNR7()
{{
   double r0 = High[1] - Low[1];
   for(int i = 2; i <= 7; i++) if(High[i] - Low[i] < r0) return(false);
   return(true);
}}
bool IsWeekendGapBar() {{ return((Time[1] - Time[2]) > 40*3600); }}
double Highest(int n)  {{ return(High[iHighest(NULL,0,MODE_HIGH,n,2)]); }}
double Lowest (int n)  {{ return(Low [iLowest (NULL,0,MODE_LOW ,n,2)]); }}

int Signal()
{{
{self._mql_signal(spec).replace('iOpen(_Symbol,_Period,0)','Open[0]').replace('iClose(_Symbol,_Period,1)','Close[1]')}
}}

double LotSize()
{{
   double risk = AccountEquity() * InpRiskPercent / 100.0;
   double atr  = ATRv(14);
   if(atr <= 0) return(MarketInfo(Symbol(), MODE_MINLOT));
   double lots = risk / (atr * 2.0 / Point * MarketInfo(Symbol(), MODE_TICKVALUE));
   double st   = MarketInfo(Symbol(), MODE_LOTSTEP);
   lots = MathFloor(lots/st)*st;
   return(MathMax(MarketInfo(Symbol(),MODE_MINLOT),
                  MathMin(MarketInfo(Symbol(),MODE_MAXLOT), lots)));
}}

int start()
{{
   if(Time[0] == lastBar) return(0);
   lastBar = Time[0];

   for(int i = OrdersTotal()-1; i >= 0; i--)
   {{
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagic) continue;
      if((TimeCurrent() - OrderOpenTime()) >= InpHoldBars * PeriodSeconds())
         OrderClose(OrderTicket(), OrderLots(),
                    OrderType() == OP_BUY ? Bid : Ask, 3);
      return(0);
   }}

   int sig = Signal();
   if(sig == 0) return(0);
   double lots = LotSize(), atr = ATRv(14);
   if(sig > 0) OrderSend(Symbol(), OP_BUY,  lots, Ask, 3, Ask-2*atr, Ask+3*atr,
                         "AGLE", InpMagic, 0, clrBlue);
   else        OrderSend(Symbol(), OP_SELL, lots, Bid, 3, Bid+2*atr, Bid-3*atr,
                         "AGLE", InpMagic, 0, clrRed);
   return(0);
}}
"""

    def _pine(self, spec, symbol: str) -> str:
        p = spec.parameters
        hours = p.get("hours")
        h_lo, h_hi = (hours[0], hours[1]) if hours else (0, 24)
        return f"""//@version=5
// {spec.candidate_id} -- AGLE Strategy Factory (GEN 14 QUALIFIED)
// spec_hash : {spec.spec_hash}
// mechanism : {spec.mechanism}
strategy("{spec.candidate_id}", overlay=true, initial_capital=10000,
         default_qty_type=strategy.percent_of_equity, default_qty_value=2,
         commission_type=strategy.commission.percent, commission_value=0.01)

holdBars = input.int({int(p.get('horizon', p.get('horizon_bars', 1)))}, "Holding horizon (bars)")
hourFrom = input.int({h_lo}, "Hour from")
hourTo   = input.int({h_hi}, "Hour to")

hourOk = hour >= hourFrom and hour < hourTo
volOk  = {'ta.atr(14) > ta.atr(50)' if p.get('vol_above_median') else 'true'}
range_ = high - low
nr7    = range_ < ta.lowest(range_, 7)[1]

{self._pine_signal(spec)}

if long_
    strategy.entry("L", strategy.long)
if short_
    strategy.entry("S", strategy.short)

barsHeld = ta.barssince(strategy.opentrades > 0 and strategy.opentrades[1] == 0)
if strategy.opentrades > 0 and barsHeld >= holdBars
    strategy.close_all(comment="horizon exit")
"""

    # -- entry point ------------------------------------------------------
    def package(self, candidate_id: str, symbol: str, out_dir: Path) -> EAPackage:
        """Emit MT5 + MT4 + Pine sources for a GEN 14-PASSED candidate."""
        spec = self._require_qualified(candidate_id)
        out_dir = Path(out_dir) / candidate_id
        out_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "mql5": out_dir / f"{candidate_id}.mq5",
            "mql4": out_dir / f"{candidate_id}.mq4",
            "pine": out_dir / f"{candidate_id}.pine",
        }
        files["mql5"].write_text(self._mql5(spec, symbol), encoding="utf-8")
        files["mql4"].write_text(self._mql4(spec, symbol), encoding="utf-8")
        files["pine"].write_text(self._pine(spec, symbol), encoding="utf-8")

        manifest = {
            "candidate_id": candidate_id, "symbol": symbol,
            "spec_hash": spec.spec_hash, "mechanism": spec.mechanism,
            "framework": spec.test_framework, "parameters": spec.parameters,
            "gen14_verdict": self.gate.authorizations[candidate_id].result,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "warning": ("Parameters are frozen. Any modification voids the GEN 14 "
                        "qualification and the EA must not be traded."),
        }
        files["manifest"] = out_dir / "manifest.json"
        files["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return EAPackage(candidate_id, symbol, spec.spec_hash, files)
