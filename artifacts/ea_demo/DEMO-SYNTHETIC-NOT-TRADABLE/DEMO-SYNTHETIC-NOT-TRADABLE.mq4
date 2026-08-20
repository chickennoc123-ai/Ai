//+------------------------------------------------------------------+
//| DEMO-SYNTHETIC-NOT-TRADABLE.mq4  -- AGLE Strategy Factory (GEN 14 QUALIFIED)
//| spec_hash : 1a14fb2368f053159269e0bfcfeb9732f42728c1eff20d57d434f4ddfde2dc7b
//| mechanism : DEMONSTRATION ONLY -- fade the 3rd consecutive same-direction H1 bar
//+------------------------------------------------------------------+
#property strict

extern double InpRiskPercent = 0.50;
extern int    InpHoldBars    = 4;
extern int    InpStreakK     = 3;
extern int    InpHourFrom    = 7;
extern int    InpHourTo      = 17;
extern bool   UseVolFilter   = true;
extern bool   UseNR7Filter   = false;
extern int    InpMagic       = 20260820;

datetime lastBar = 0;

int HourOfBar()   { return TimeHour(Time[1]); }
bool HourAllowed(){ int h = HourOfBar(); return (h >= InpHourFrom && h < InpHourTo); }
double ATRv(int p_) { return iATR(NULL, 0, p_, 1); }
bool VolFilterOk(){ if(!UseVolFilter) return(true); return(ATRv(14) > ATRv(50)); }

int StreakLength()
{
   int dir = 0, len = 0;
   for(int i = 1; i <= 20; i++)
   {
      int d = (Close[i] > Close[i+1]) ? 1 : -1;
      if(i == 1) { dir = d; len = 1; }
      else if(d == dir) len++;
      else break;
   }
   return(dir * len);
}

bool IsNR7()
{
   double r0 = High[1] - Low[1];
   for(int i = 2; i <= 7; i++) if(High[i] - Low[i] < r0) return(false);
   return(true);
}
bool IsWeekendGapBar() { return((Time[1] - Time[2]) > 40*3600); }
double Highest(int n)  { return(High[iHighest(NULL,0,MODE_HIGH,n,2)]); }
double Lowest (int n)  { return(Low [iLowest (NULL,0,MODE_LOW ,n,2)]); }

int Signal()
{
   int streak = StreakLength();
   if(MathAbs(streak) < 3) return(0);
   if(!HourAllowed()) return(0);
   if(!VolFilterOk()) return(0);
   return(streak > 0 ? -1 : 1);   // fade the run
}

double LotSize()
{
   double risk = AccountEquity() * InpRiskPercent / 100.0;
   double atr  = ATRv(14);
   if(atr <= 0) return(MarketInfo(Symbol(), MODE_MINLOT));
   double lots = risk / (atr * 2.0 / Point * MarketInfo(Symbol(), MODE_TICKVALUE));
   double st   = MarketInfo(Symbol(), MODE_LOTSTEP);
   lots = MathFloor(lots/st)*st;
   return(MathMax(MarketInfo(Symbol(),MODE_MINLOT),
                  MathMin(MarketInfo(Symbol(),MODE_MAXLOT), lots)));
}

int start()
{
   if(Time[0] == lastBar) return(0);
   lastBar = Time[0];

   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagic) continue;
      if((TimeCurrent() - OrderOpenTime()) >= InpHoldBars * PeriodSeconds())
         OrderClose(OrderTicket(), OrderLots(),
                    OrderType() == OP_BUY ? Bid : Ask, 3);
      return(0);
   }

   int sig = Signal();
   if(sig == 0) return(0);
   double lots = LotSize(), atr = ATRv(14);
   if(sig > 0) OrderSend(Symbol(), OP_BUY,  lots, Ask, 3, Ask-2*atr, Ask+3*atr,
                         "AGLE", InpMagic, 0, clrBlue);
   else        OrderSend(Symbol(), OP_SELL, lots, Bid, 3, Bid+2*atr, Bid-3*atr,
                         "AGLE", InpMagic, 0, clrRed);
   return(0);
}
