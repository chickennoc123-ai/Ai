//+------------------------------------------------------------------+
//| SC_SurpriseConfirmation_EXPERIMENTAL.mq5                         |
//|                                                                    |
//| ================================================================ |
//| EXPERIMENTAL / UNRESOLVED -- NOT A PROVEN EDGE.                  |
//|                                                                    |
//| SC_SURPRISE_CONFIRMATION has NEVER cleared internal validation   |
//| on any of its 6 pre-registered (symbol,driver,window)            |
//| combinations, across two independently pre-registered test       |
//| rounds (ML-001 GEN 7 Cycles 8 and 9). It has NEVER been          |
//| authorized for GEN 14. It has NEVER been evaluated against the   |
//| sealed holdout. Do not trade this with real capital based on     |
//| the evidence behind this file alone.                             |
//|                                                                    |
//| See: ea_products/sc_surprise_confirmation/README.md               |
//|      ea_products/sc_surprise_confirmation/AUDIT_REPORT.md         |
//|      reports/factory/candidate_spec_registry.json (CAND-SC-*)    |
//| ================================================================ |
//+------------------------------------------------------------------+
#property copyright "ML-001 Factory -- experimental research output"
#property version   "1.00"
#property strict
#property description "EXPERIMENTAL / UNRESOLVED. Not a proven edge. See README."

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| FROZEN SPECIFICATION                                              |
//| These six blocks are the ONLY combinations this EA is permitted  |
//| to run. They are transcribed byte-for-byte from                  |
//| reports/factory/candidate_spec_registry.json (CAND-SC-*) via     |
//| ea_products/sc_surprise_confirmation/config/frozen_spec.json.    |
//| Changing any value below without re-running the export script    |
//| breaks the config-validation checksum and the EA will refuse to  |
//| initialize (see ValidateFrozenConfig()).                         |
//+------------------------------------------------------------------+
enum ENUM_SC_COMBO
  {
   SC_EURUSD_US10Y_5M,
   SC_EURUSD_US10Y_15M,
   SC_GBPUSD_US10Y_5M,
   SC_XAUUSD_WTICO_5M,
   SC_USDJPY_SPX500_240M,
   SC_USDCHF_SPX500_240M
  };

struct FrozenCombo
  {
   string            candidate_id;
   string            symbol;
   string            driver_symbol_hint;   // broker-specific; operator must map via input
   int               window_min;
   int               base_dir;             // +1 or -1, driver-up -> fx direction
   int               surprise_fx_dir;      // +1 or -1, positive-USD-surprise -> fx direction
   double            roundtrip_cost;       // frozen relative cost (log-return terms)
   string            spec_hash_prefix;     // first 16 hex chars, for a visible sanity check
  };

FrozenCombo g_frozen[6];

void InitFrozenTable()
  {
// CAND-SC-EURUSD-US10Y-5M   hash f4cee7b1c6458eed  train_t=+3.94 n=149  val_t=+1.07 n=23 (need 30)
   g_frozen[0].candidate_id = "CAND-SC-EURUSD-US10Y-5M";
   g_frozen[0].symbol = "EURUSD"; g_frozen[0].driver_symbol_hint = "US10Y (broker-specific)";
   g_frozen[0].window_min = 5; g_frozen[0].base_dir = +1; g_frozen[0].surprise_fx_dir = -1;
   g_frozen[0].roundtrip_cost = 0.00010; g_frozen[0].spec_hash_prefix = "f4cee7b1c6458eed";

// CAND-SC-EURUSD-US10Y-15M  hash ef9f2eea5c9e313a  train_t=+2.39 n=149  val_t=+0.44 n=23 (need 30)
   g_frozen[1].candidate_id = "CAND-SC-EURUSD-US10Y-15M";
   g_frozen[1].symbol = "EURUSD"; g_frozen[1].driver_symbol_hint = "US10Y (broker-specific)";
   g_frozen[1].window_min = 15; g_frozen[1].base_dir = +1; g_frozen[1].surprise_fx_dir = -1;
   g_frozen[1].roundtrip_cost = 0.00010; g_frozen[1].spec_hash_prefix = "ef9f2eea5c9e313a";

// CAND-SC-GBPUSD-US10Y-5M   hash e739b69d2b1a70e2  train_t=+2.92 n=149  val_t=-0.10 n=23 (need 30)
   g_frozen[2].candidate_id = "CAND-SC-GBPUSD-US10Y-5M";
   g_frozen[2].symbol = "GBPUSD"; g_frozen[2].driver_symbol_hint = "US10Y (broker-specific)";
   g_frozen[2].window_min = 5; g_frozen[2].base_dir = +1; g_frozen[2].surprise_fx_dir = -1;
   g_frozen[2].roundtrip_cost = 0.00012; g_frozen[2].spec_hash_prefix = "e739b69d2b1a70e2";

// CAND-SC-XAUUSD-WTICO-5M   hash f1c9e9a78178b9df  train_t=+3.57 n=131  val_t=+0.11 n=22 (need 30)
   g_frozen[3].candidate_id = "CAND-SC-XAUUSD-WTICO-5M";
   g_frozen[3].symbol = "XAUUSD"; g_frozen[3].driver_symbol_hint = "WTICO/USOIL (broker-specific)";
   g_frozen[3].window_min = 5; g_frozen[3].base_dir = +1; g_frozen[3].surprise_fx_dir = -1;
   g_frozen[3].roundtrip_cost = 0.00020; g_frozen[3].spec_hash_prefix = "f1c9e9a78178b9df";

// CAND-SC-USDJPY-SPX500-240M hash c9d7872e76886b9b  train_t=+7.31 n=121  val_t=+1.79 n=23 (need 30) -- STRONGEST train signal, still underpowered
   g_frozen[4].candidate_id = "CAND-SC-USDJPY-SPX500-240M";
   g_frozen[4].symbol = "USDJPY"; g_frozen[4].driver_symbol_hint = "SPX500/US500 (broker-specific)";
   g_frozen[4].window_min = 240; g_frozen[4].base_dir = +1; g_frozen[4].surprise_fx_dir = +1;
   g_frozen[4].roundtrip_cost = 0.00010; g_frozen[4].spec_hash_prefix = "c9d7872e76886b9b";

// CAND-SC-USDCHF-SPX500-240M hash 3d0b75642ed6e889  train_t=+5.11 n=121  val_t=+0.57 n=23 (need 30)
   g_frozen[5].candidate_id = "CAND-SC-USDCHF-SPX500-240M";
   g_frozen[5].symbol = "USDCHF"; g_frozen[5].driver_symbol_hint = "SPX500/US500 (broker-specific)";
   g_frozen[5].window_min = 240; g_frozen[5].base_dir = +1; g_frozen[5].surprise_fx_dir = +1;
   g_frozen[5].roundtrip_cost = 0.00019; g_frozen[5].spec_hash_prefix = "3d0b75642ed6e889";
  }

const int    FROZEN_ENTRY_DELAY_SEC     = 60;   // NOT tunable -- see ValidateFrozenConfig()
const int    FROZEN_IMPULSE_WINDOW_MIN  = 5;    // NOT tunable

//+------------------------------------------------------------------+
//| OPERATOR INPUTS                                                   |
//| The operator selects WHICH frozen combination to run and         |
//| supplies the broker-specific driver symbol name (SPX500/US10Y/   |
//| WTI symbol names vary by broker -- e.g. "US500", "SPX500",       |
//| "USTNote10Y", "USOIL", "WTICOUSD" -- this cannot be hardcoded).  |
//| No parameter of the MECHANISM ITSELF is exposed as an input --   |
//| there is nothing here for an operator to retune.                 |
//+------------------------------------------------------------------+
input ENUM_SC_COMBO   InpCombo            = SC_USDJPY_SPX500_240M;  // Frozen combination to run
input string          InpDriverSymbol     = "";                     // Broker symbol for the driver leg (REQUIRED)
input double          InpRiskPercent      = 0.25;                   // Risk per trade, % of equity (conservative default -- experimental status)
input double          InpMaxSpreadPips    = 3.0;                    // Refuse entry if current spread exceeds this
input double          InpMaxDailyLossPct  = 2.0;                    // Kill switch: halt new entries after this daily loss %
input int             InpMaxConcurrent    = 1;                      // Max concurrent positions from this EA
input bool            InpKillSwitch       = false;                  // Manual kill switch -- true disables ALL new entries immediately
input int              InpMagic            = 20261020;               // Magic number

//+------------------------------------------------------------------+
//| STATE                                                             |
//+------------------------------------------------------------------+
FrozenCombo g_active;
datetime    g_day_start_equity_date = 0;
double      g_day_start_equity = 0.0;
bool        g_halted_for_daily_loss = false;

// pending-decision state machine (per detected event)
datetime g_pending_event_ts = 0;
double   g_pending_actual = 0, g_pending_forecast = 0;
bool     g_pending_active = false;
double   g_driver_price_at_entry = 0, g_fx_price_at_entry = 0;
datetime g_entry_done_ts = 0;
bool     g_confirmed = false;
int      g_trade_direction = 0;
datetime g_exit_due_ts = 0;
ulong    g_open_ticket = 0;

//+------------------------------------------------------------------+
//| Logging -- every decision, structured, timestamped                |
//+------------------------------------------------------------------+
void Log(string tag, string msg)
  {
   PrintFormat("[SC-EXPERIMENTAL][%s][%s] %s", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS), tag, msg);
  }

//+------------------------------------------------------------------+
//| Startup validation -- refuse any configuration that differs from  |
//| the frozen specification. This is the whole point of the file.   |
//+------------------------------------------------------------------+
bool ValidateFrozenConfig()
  {
   InitFrozenTable();
   g_active = g_frozen[InpCombo];

   if(_Symbol != g_active.symbol)
     {
      Log("INIT-REJECT", StringFormat("chart symbol %s does not match frozen combination symbol %s "
          "for %s -- attach this EA to the correct chart, do not change the symbol via a different means",
          _Symbol, g_active.symbol, g_active.candidate_id));
      return(false);
     }
   if(StringLen(InpDriverSymbol) == 0)
     {
      Log("INIT-REJECT", StringFormat("InpDriverSymbol is empty. Set it to your broker's symbol name for "
          "the %s driver instrument before starting.", g_active.driver_symbol_hint));
      return(false);
     }
   if(SymbolInfoInteger(InpDriverSymbol, SYMBOL_SELECT) == 0 &&
      !SymbolSelect(InpDriverSymbol, true))
     {
      Log("INIT-REJECT", StringFormat("driver symbol '%s' is not available from this broker/terminal.",
          InpDriverSymbol));
      return(false);
     }
   if(InpRiskPercent <= 0 || InpRiskPercent > 2.0)
     {
      Log("INIT-REJECT", "InpRiskPercent must be in (0, 2.0] -- this is an EXPERIMENTAL, "
          "UNRESOLVED mechanism; risk sizing is capped deliberately low and is not a place "
          "to compensate for the missing validation evidence.");
      return(false);
     }
   if(InpMaxConcurrent < 1 || InpMaxConcurrent > 3)
     {
      Log("INIT-REJECT", "InpMaxConcurrent must be in [1,3].");
      return(false);
     }
// the mechanism's own timing/cost/direction constants are NOT inputs and
// therefore cannot be tampered with via terminal UI at all; this check
// exists purely so a future maintainer editing this file cannot silently
// drift from the frozen spec without the mismatch being visible here.
   if(FROZEN_ENTRY_DELAY_SEC != 60 || FROZEN_IMPULSE_WINDOW_MIN != 5)
     {
      Log("INIT-REJECT", "frozen timing constants have been edited -- this build no longer "
          "matches reports/factory/candidate_spec_registry.json. Re-export the spec.");
      return(false);
     }

   Log("INIT", StringFormat("frozen combination: %s  spec_hash=%s...  symbol=%s driver=%s(%s) "
       "window=%dmin  EVIDENCE STATUS: EXPERIMENTAL / UNRESOLVED -- never cleared validation, "
       "never authorized for GEN 14, never evaluated against sealed holdout.",
       g_active.candidate_id, g_active.spec_hash_prefix, g_active.symbol, g_active.driver_symbol_hint,
       InpDriverSymbol, g_active.window_min));
   return(true);
  }

//+------------------------------------------------------------------+
//| Risk / spread / daily-loss guards                                  |
//+------------------------------------------------------------------+
bool SpreadOk()
  {
   double spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID));
   double pip = (SymbolInfoInteger(_Symbol, SYMBOL_DIGITS) == 3 ||
                SymbolInfoInteger(_Symbol, SYMBOL_DIGITS) == 5) ? 10 * _Point : _Point;
   double spread_pips = spread / pip;
   if(spread_pips > InpMaxSpreadPips)
     {
      Log("GUARD", StringFormat("spread %.1f pips exceeds InpMaxSpreadPips=%.1f -- entry skipped",
          spread_pips, InpMaxSpreadPips));
      return(false);
     }
// second guard: the frozen cost assumption itself. If the CURRENT spread
// alone already exceeds the frozen round-trip cost the research measured
// against, live economics are worse than backtested and the trade must
// not be taken even if InpMaxSpreadPips would otherwise allow it.
   double spread_relative = spread / SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(spread_relative > g_active.roundtrip_cost)
     {
      Log("GUARD", StringFormat("current relative spread %.6f exceeds the frozen research cost "
          "assumption %.6f for %s -- live economics are worse than backtested, entry skipped",
          spread_relative, g_active.roundtrip_cost, g_active.candidate_id));
      return(false);
     }
   return(true);
  }

bool DailyLossGuardOk()
  {
   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", t.year, t.mon, t.day));
   if(today != g_day_start_equity_date)
     {
      g_day_start_equity_date = today;
      g_day_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_halted_for_daily_loss = false;
     }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double loss_pct = (g_day_start_equity - equity) / g_day_start_equity * 100.0;
   if(loss_pct >= InpMaxDailyLossPct)
     {
      if(!g_halted_for_daily_loss)
         Log("KILL-SWITCH", StringFormat("daily loss %.2f%% >= InpMaxDailyLossPct=%.2f%% -- halting "
             "new entries for the rest of the day", loss_pct, InpMaxDailyLossPct));
      g_halted_for_daily_loss = true;
      return(false);
     }
   return(true);
  }

bool ConcurrentPositionsOk()
  {
   int n = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
   return(n < InpMaxConcurrent);
  }

double LotSize()
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk = equity * InpRiskPercent / 100.0;
   double atr_proxy = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0 || tick_size <= 0)
      return(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN));
// conservative stop distance: 3x the frozen relative cost, in price terms
   double stop_distance = SymbolInfoDouble(_Symbol, SYMBOL_BID) * g_active.roundtrip_cost * 3.0;
   double lots = risk / ((stop_distance / tick_size) * tick_value);
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / st) * st;
   return(MathMax(mn, MathMin(mx, lots)));
  }

//+------------------------------------------------------------------+
//| Economic calendar: detect a fresh NFP/CPI/ADP release              |
//| Uses MT5's native Calendar API (actual/forecast values), not any  |
//| externally-fetched file -- this is the live equivalent of the     |
//| research's forexfactory-derived actual/forecast fields.           |
//+------------------------------------------------------------------+
bool IsFrozenEventType(string event_name)
  {
   return(event_name == "Non-Farm Employment Change" || event_name == "Nonfarm Payrolls" ||
          event_name == "CPI y/y" || event_name == "Consumer Price Index (YoY)" ||
          event_name == "ADP Non-Farm Employment Change" || event_name == "ADP Employment Change");
  }

void CheckForNewEvent()
  {
   if(g_pending_active)
      return;   // one decision in flight at a time -- do not overlap events

   MqlCalendarValue values[];
   datetime from = TimeCurrent() - 120;   // look back 2 minutes for a just-released print
   datetime to = TimeCurrent();
   if(CalendarValueHistory(values, from, to, "US") <= 0)
      return;

   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      if(!IsFrozenEventType(ev.name))
         continue;
      if(values[i].actual_value == LONG_MIN || values[i].forecast_value == LONG_MIN)
         continue;   // no actual/forecast yet -- not a usable surprise

      g_pending_event_ts = values[i].time;
      g_pending_actual = (double)values[i].actual_value;
      g_pending_forecast = (double)values[i].forecast_value;
      g_pending_active = true;
      g_confirmed = false;
      g_entry_done_ts = 0;

      Log("EVENT", StringFormat("%s at %s  actual=%.4f forecast=%.4f", ev.name,
          TimeToString(g_pending_event_ts, TIME_DATE | TIME_SECONDS),
          g_pending_actual, g_pending_forecast));
      return;
     }
  }

//+------------------------------------------------------------------+
//| Entry-delay + impulse-confirmation state machine                  |
//| Mirrors discovery/cycle8_intraday.py::trade_sc() EXACTLY:         |
//|   entry   = event_ts + 60s      (FROZEN_ENTRY_DELAY_SEC)          |
//|   impulse = event_ts + 5min     (FROZEN_IMPULSE_WINDOW_MIN)       |
//|   exit    = event_ts + window_min                                 |
//|   confirmed iff sign(driver impulse move) * base_dir              |
//|             == sign(surprise) * surprise_fx_dir                   |
//+------------------------------------------------------------------+
void ProcessPendingEvent()
  {
   if(!g_pending_active)
      return;

   double surprise = g_pending_actual - g_pending_forecast;
   if(surprise == 0.0)
     {
      Log("SKIP", StringFormat("%s: zero surprise, no trade", g_active.candidate_id));
      g_pending_active = false;
      return;
     }

   datetime entry_ts = g_pending_event_ts + FROZEN_ENTRY_DELAY_SEC;
   datetime impulse_ts = g_pending_event_ts + FROZEN_IMPULSE_WINDOW_MIN * 60;
   datetime exit_ts = g_pending_event_ts + g_active.window_min * 60;

   if(TimeCurrent() < entry_ts)
      return;   // still waiting out the execution delay

   if(g_entry_done_ts == 0)
     {
      g_driver_price_at_entry = SymbolInfoDouble(InpDriverSymbol, SYMBOL_BID);
      g_fx_price_at_entry = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      g_entry_done_ts = TimeCurrent();
      Log("ENTRY-MARK", StringFormat("driver=%.5f fx=%.5f at %s (event+%ds)",
          g_driver_price_at_entry, g_fx_price_at_entry, TimeToString(TimeCurrent()),
          FROZEN_ENTRY_DELAY_SEC));
     }

   if(TimeCurrent() < impulse_ts)
      return;   // still inside the impulse window

   if(!g_confirmed && g_open_ticket == 0)
     {
      double driver_now = SymbolInfoDouble(InpDriverSymbol, SYMBOL_BID);
      double driver_move = MathLog(driver_now / g_driver_price_at_entry);
      int driver_sign = (driver_move > 0) ? 1 : (driver_move < 0 ? -1 : 0);
      int expected_dir = g_active.base_dir * driver_sign;
      int surprise_sign = (surprise > 0) ? 1 : -1;
      int implied_dir = g_active.surprise_fx_dir * surprise_sign;

      if(expected_dir == 0 || expected_dir != implied_dir)
        {
         Log("NO-CONFIRM", StringFormat("%s: driver did not confirm (expected_dir=%d "
             "implied_dir=%d) -- no trade this event", g_active.candidate_id, expected_dir, implied_dir));
         g_pending_active = false;
         return;
        }

      g_confirmed = true;
      g_trade_direction = implied_dir;
      g_exit_due_ts = exit_ts;
      Log("CONFIRMED", StringFormat("%s: direction=%d, will exit at %s", g_active.candidate_id,
          g_trade_direction, TimeToString(g_exit_due_ts)));

      if(InpKillSwitch)
        {
         Log("KILL-SWITCH", "InpKillSwitch is true -- confirmed signal NOT executed");
         g_pending_active = false;
         return;
        }
      if(!SpreadOk() || !DailyLossGuardOk() || !ConcurrentPositionsOk())
        {
         Log("GUARD-BLOCK", "one or more guards blocked entry -- confirmed signal NOT executed");
         g_pending_active = false;
         return;
        }

      double lots = LotSize();
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      bool ok;
      if(g_trade_direction > 0)
         ok = trade.Buy(lots, _Symbol, ask, 0, 0, StringFormat("SC-EXP-%s", g_active.candidate_id));
      else
         ok = trade.Sell(lots, _Symbol, bid, 0, 0, StringFormat("SC-EXP-%s", g_active.candidate_id));

      if(ok)
        {
         g_open_ticket = trade.ResultOrder();
         Log("ORDER", StringFormat("opened ticket=%I64u lots=%.2f dir=%d", g_open_ticket, lots, g_trade_direction));
        }
      else
        {
         Log("ORDER-FAIL", StringFormat("retcode=%d", trade.ResultRetcode()));
        }
      g_pending_active = false;   // decision made -- event fully processed
     }
  }

//+------------------------------------------------------------------+
//| Exit at the frozen window                                         |
//+------------------------------------------------------------------+
void CheckExit()
  {
   if(g_open_ticket == 0)
      return;
   if(!PositionSelectByTicket(g_open_ticket))
     {
      g_open_ticket = 0;   // closed by SL/TP/manual/broker -- clear state
      return;
     }
   if(TimeCurrent() >= g_exit_due_ts)
     {
      trade.PositionClose(g_open_ticket);
      Log("EXIT", StringFormat("closed ticket=%I64u at frozen window boundary", g_open_ticket));
      g_open_ticket = 0;
     }
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(!ValidateFrozenConfig())
      return(INIT_PARAMETERS_INCORRECT);
   EventSetTimer(1);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   CheckForNewEvent();
   ProcessPendingEvent();
   CheckExit();
  }

void OnTick()
  {
// entries/exits are timer-driven (event-anchored, not tick-driven) so
// behavior does not depend on tick arrival rate; OnTick only forces a
// same-loop exit check so a position is never held past its window
// merely because ticks went quiet.
   CheckExit();
  }
//+------------------------------------------------------------------+
