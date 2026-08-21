"""
Idea Machine: Autonomous strategy idea generation and evaluation loop.

Connects to the Strategy Factory discovery pipeline to research ideas sourced from:
  - Academic literature (quantitative finance, market microstructure)
  - Trading forums (QuantConnect, Elite Trader, TradingView)
  - Research publications (event-driven, macro, technical analysis)
  - Market observations (new regime patterns, calendar anomalies)

Governance:
  - Never modifies holdout or ledger
  - Respects all Factory gates (no p-hacking, no GEN14-bypass)
  - Marks ideas BLOCKED_DATA when data is insufficient
  - Records all rejections with honest reasons
  - Only productizes when Factory authorizes

No self-declared edges. Hypothesis packaging, not edge-mining.
"""
