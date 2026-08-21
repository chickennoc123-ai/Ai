"""
Assembles the REAL mining results obtained in this session (GitHub
search_repositories, WebFetch on raw.githubusercontent.com, WebSearch, and
the direct-fetch attempts against mql5.com / tradingview.com / macrosynergy.com
that were blocked) into the source registry and mined-source collection.

Every text_excerpt below is copied verbatim from an actual tool result
obtained in this session -- nothing here is invented. Quoted spans (marked
with "...") in the excerpts are the tool's direct quotes from the source
document; surrounding prose is the fetch tool's own summary framing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from idea_machine.ea_code_intel.source_registry import SourceRegistry
from idea_machine.ea_code_intel.github_miner import MinedSourceCollection

registry = SourceRegistry()
mined = MinedSourceCollection()

# --- Accessible sources (real tool calls, real results) ---

registry.record_tool_availability(
    "GitHub search_repositories (MQL5)", "mcp__github__search_repositories",
    "API_TOOL", available=True,
    sample_result_summary="query='mql5 expert advisor strategy language:MQL5' returned 29 total_count, "
                          "top result geraked/metatrader5 (609 stars)")
registry.record_tool_availability(
    "GitHub search_repositories (Pine Script)", "mcp__github__search_repositories",
    "API_TOOL", available=True,
    sample_result_summary="query='pine script strategy trading indicator language:PineScript' "
                          "returned 102 total_count, top result everget/tradingview-pinescript-indicators (879 stars)")
registry.record_fetch_result(
    "geraked/metatrader5 README", "https://raw.githubusercontent.com/geraked/metatrader5/master/README.md",
    "OPEN_SOURCE_CODE", succeeded=True,
    content_sample="CEZLSMA, 3MAF, BBRSI, DHLAOS, 3MACD, 2MACDSTO, 2MAAOS, AFAOSMD, NWERSIASF, LRCUTB, COT1")
registry.record_fetch_result(
    "foeed/FvgGold-EA README", "https://raw.githubusercontent.com/foeed/FvgGold-EA/main/README.md",
    "OPEN_SOURCE_CODE", succeeded=True,
    content_sample="Buy limit placed at FVG bottom edge, Fixed R:R=1.5, London/NY killzones, Fixed lot 0.01")
registry.record_fetch_result(
    "Ahmed-GoCode/Quant-Edge-Indicators README", "https://raw.githubusercontent.com/Ahmed-GoCode/Quant-Edge-Indicators/main/README.md",
    "OPEN_SOURCE_CODE", succeeded=True,
    content_sample="16 Pine Script strategies: MSS+CHoCH+BOS, FVG, Trio Liquidity, Apex Trend, RSI Divergences, "
                   "Larry Connors RSI, Turtle Strategy, Donchian Pullback")
registry.record_fetch_result(
    "sajidmahamud835/grid-master-pro-mt5-ea README", "https://raw.githubusercontent.com/sajidmahamud835/grid-master-pro-mt5-ea/main/README.md",
    "OPEN_SOURCE_CODE", succeeded=True,
    content_sample="Grid spacing dynamically adjusts using ATR, NEUTRAL/BULLISH/BEARISH modes, "
                   "MaxDrawdownPct 5.0 circuit breaker")
registry.record_tool_availability(
    "WebSearch (academic: cross-asset macro surprise FX)", "WebSearch", "ACADEMIC_SEARCH", available=True,
    sample_result_summary="8 results incl. macrosynergy.com yield-curve-FX research, BIS working paper 1273, "
                          "arxiv.org/pdf/2408.12863 (yield curve regime switching) -- titles/snippets only")

# --- Blocked sources (real attempts, real failures -- recorded, not hidden) ---

registry.record_fetch_result(
    "MQL5 CodeBase (direct)", "https://www.mql5.com/en/code/mt5/experts", "OPEN_SOURCE_CODE_HOST",
    succeeded=False, error_detail="EGRESS_BLOCKED: Access to www.mql5.com is blocked by the network egress proxy.")
registry.record_fetch_result(
    "TradingView Scripts (direct)", "https://www.tradingview.com/scripts/", "OPEN_SOURCE_CODE_HOST",
    succeeded=False, error_detail="EGRESS_BLOCKED: Access to www.tradingview.com is blocked by the network egress proxy.")
registry.record_fetch_result(
    "Macrosynergy research (direct)", "https://macrosynergy.com/research/using-yield-curve-information-for-fx-trading/",
    "ACADEMIC_PAPER", succeeded=False,
    error_detail="EGRESS_BLOCKED: Access to macrosynergy.com is blocked by the network egress proxy.")

reg_path = registry.save()
print(f"Source registry saved: {reg_path}")
print(registry.summary())

# --- Mined source text (real excerpts) ---

mined.add("github_repo", "geraked/metatrader5",
         "https://github.com/geraked/metatrader5", language="MQL5", stars=609,
         topics=["expert-advisor", "mql5", "mt5"],
         text_excerpt=("Strategies: CEZLSMA leverages Chandelier Exit and ZLSMA indicators based on Heikin Ashi "
                      "candles. 3MAF employs three moving averages combined with Williams Fractals. BBRSI "
                      "integrates Bollinger Bands with RSI. 3MACD applies triple MACD optimized for scalping. "
                      "2MACDSTO combines dual MACD with Stochastic Oscillator signals. NWERSIASF utilizes "
                      "Nadaraya-Watson Envelope, RSI, and ATR Stop Loss Finder. COT1 combines Commitments of "
                      "Traders and Super Trend indicator."))

mined.add("github_repo", "foeed/FvgGold-EA",
         "https://github.com/foeed/FvgGold-EA", language="MQL5", stars=12,
         topics=["fair-value-gap", "order-block", "xauusd"],
         text_excerpt=("Buy limit placed at FVG bottom edge + buffer. Fixed R:R = 1.5 take-profit from entry. "
                      "Stop-losses anchor at the opposite FVG edge. Quality Score: only FVGs exceeding threshold "
                      "(default 50/100) qualify based on gap size, momentum displacement, timeframe alignment. "
                      "FVG overlaps a bullish or bearish Order Block gets score bonus. Trading restricted to "
                      "London/NY killzones: London Open 07:00-10:00; London/NY Overlap 12:00-16:00; NY Close 21:00. "
                      "Fixed lot sizing (default 0.01). Max 1 concurrent trade. Daily loss limit ($5 default). "
                      "Break-even protection activates at 0.5x ATR profit."))

mined.add("github_repo", "Ahmed-GoCode/Quant-Edge-Indicators",
         "https://github.com/Ahmed-GoCode/Quant-Edge-Indicators", language="Pine Script", stars=40,
         topics=["smc", "order-flow", "fair-value-gap"],
         text_excerpt=("Market structure shift tracking, BOS and CHoCH labels indicate directional reversals. "
                      "Adaptive fractal swing detection. Inversion IFVG detection engine identifies imbalance "
                      "zones, proximal/distal mitigation levels define closure targets. Pivot liquidity sweep "
                      "scanner triggers signals, close-back confirmation boxes define exits. ATR-based trend "
                      "cloud with supply/demand liquidity zones. 2-period RSI mean reversion with SMA 200 trend "
                      "filter, time-based max bar exits (Larry Connors RSI Strategy). Donchian breakout, Fixed SL "
                      "+ Dynamic TP + Daily target cap, 1% equity risk sizing (Turtle Strategy). EMA 200 + MACD + "
                      "RSI + ADX + Volume filter, ATR trailing stop, breakout confirmation (BTCUSD 5M Strategy)."))

mined.add("github_repo", "sajidmahamud835/grid-master-pro-mt5-ea",
         "https://github.com/sajidmahamud835/grid-master-pro-mt5-ea", language="MQL5", stars=119,
         topics=["grid-trading", "mql5"],
         text_excerpt=("Places BUY orders below AND SELL orders above current price simultaneously (Neutral "
                      "mode). Grid spacing dynamically adjusts to market volatility using ATR. Modes: NEUTRAL "
                      "(both), BULLISH (buy only), BEARISH (sell only). Trailing stop with TrailingPoints and "
                      "TrailingStep. Circuit breaker: MaxDrawdownPct 5.0 default, auto-pauses and closes all "
                      "positions on drawdown breach. Risk-based lot calculation (% of balance): "
                      "lot = (balance x riskPct) / (SL x tickValue)."))

mined.add("web_search_snippet", "Macrosynergy / academic FX yield-curve research (titles+snippets only)",
         "https://macrosynergy.com/research/using-yield-curve-information-for-fx-trading/",
         topics=["yield-curve", "macro-factors", "fx"],
         text_excerpt=("An equally weighted composite score of macro factors (inflation, credit conditions, "
                      "real estate price growth, yield-curve valuations, economic surprises) has been a highly "
                      "significant predictor of duration returns in the G4 (US, euro area, Japan, UK). Research "
                      "shows FX trading strategies can leverage yield curve information beyond short-term rates. "
                      "Real values of long-term financial assets fluctuate sharply in response to central bank "
                      "actions and announcements (monetary policy surprises), consistent with cross-asset "
                      "confirmation logic."))

mined_path = mined.save()
print(f"\nMined sources saved: {mined_path}")
print(f"Count: {len(mined.sources)}")
