"""Deterministic concept extraction (Phase 1).

The scanner must turn free text into *named concepts* the knowledge base can
reason over. This is done with a controlled vocabulary rather than a language
model, for three reasons the roadmap cares about:

* **Determinism** — the same document always yields the same concepts, so a
  whole cycle is reproducible and ids are stable.
* **Auditability** — every extracted concept points at the exact phrase that
  produced it, so provenance survives extraction.
* **No invention** — a model asked to "find the trading idea" will happily
  invent one. Matching a vocabulary cannot hallucinate a concept that is not
  in the text.

The vocabulary is intentionally extensible: :func:`register_concept` lets a
caller add domain terms without touching this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from idea_machine.core.ids import normalize_text

#: canonical concept name -> (family hint, surface phrases)
_VOCABULARY: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    # macro / events
    "NFP": ("EVENT", ("nfp", "non-farm payroll", "nonfarm payroll", "payrolls")),
    "CPI": ("EVENT", ("cpi", "consumer price index", "inflation print", "inflation release")),
    "FOMC": ("EVENT", ("fomc", "federal open market committee", "fed meeting", "rate decision")),
    "CENTRAL_BANK_POLICY": ("MACRO", ("central bank", "monetary policy", "policy rate", "hawkish", "dovish")),
    "SURPRISE": ("EVENT", ("surprise", "consensus miss", "beat expectations", "economic surprise")),
    "GDP": ("MACRO", ("gdp", "gross domestic product")),
    "UNEMPLOYMENT": ("MACRO", ("unemployment rate", "jobless claims")),
    # rates / curve
    "US10Y": ("CROSS_ASSET", ("us10y", "10-year treasury", "ten-year yield", "10y yield", "10-year yield", "10 year yield")),
    "YIELD_CURVE": ("TERM_STRUCTURE", ("yield curve", "curve steepening", "curve flattening", "term spread")),
    "RATE_DIFFERENTIAL": ("CARRY", ("rate differential", "interest rate differential", "yield differential")),
    "CARRY_TRADE": ("CARRY", ("carry trade", "carry return", "forward premium")),
    # fx / assets
    "USD": ("CROSS_ASSET", ("usd", "dollar index", "dxy", "us dollar")),
    "GOLD": ("CROSS_ASSET", ("gold", "xauusd", "bullion")),
    "EQUITIES": ("CROSS_ASSET", ("equities", "s&p 500", "stock index", "equity index")),
    "OIL": ("CROSS_ASSET", ("crude oil", "wti", "brent")),
    # volatility
    "VOLATILITY_REGIME": ("REGIME", ("volatility regime", "high volatility", "low volatility", "vol regime")),
    "IMPLIED_VOLATILITY": ("VOLATILITY", ("implied volatility", "option-implied", "vix")),
    "VARIANCE_RISK_PREMIUM": ("VOLATILITY", ("variance risk premium", "volatility risk premium")),
    "REALIZED_VOLATILITY": ("VOLATILITY", ("realized volatility", "realised volatility", "historical volatility")),
    # structure / flow
    "ORDER_FLOW": ("MICROSTRUCTURE", ("order flow", "order imbalance", "trade imbalance")),
    "BID_ASK_SPREAD": ("MICROSTRUCTURE", ("bid-ask spread", "bid ask spread", "quoted spread")),
    "LIQUIDITY_PROVISION": ("LIQUIDITY", ("liquidity provision", "market making", "inventory risk")),
    "POSITIONING_DATA": ("POSITIONING", ("cot report", "commitment of traders", "speculative positioning", "crowded trade")),
    "SESSION_BOUNDARY": ("MARKET_STRUCTURE", ("london open", "tokyo session", "new york open", "session open", "market open")),
    "FIXING": ("CALENDAR", ("wm/r fix", "london fix", "benchmark fixing", "4pm fix")),
    # time / calendar
    "TURN_OF_MONTH": ("SEASONALITY", ("turn of the month", "turn-of-month", "month-end")),
    "DAY_OF_WEEK": ("SEASONALITY", ("day-of-week", "monday effect", "friday effect")),
    "TIME_OF_DAY": ("CALENDAR", ("time-of-day", "intraday seasonality", "hour of day")),
    "QUARTER_END": ("SEASONALITY", ("quarter-end", "quarter end rebalancing")),
    # behaviour
    "MOMENTUM": ("MOMENTUM", ("momentum", "trend following", "time-series momentum", "underreaction")),
    "MEAN_REVERSION": ("MEAN_REVERSION", ("mean reversion", "mean-reverting", "overreaction", "reversal")),
    "LEAD_LAG": ("CROSS_ASSET", ("lead-lag", "lead lag", "spillover", "information transmission")),
    "ANNOUNCEMENT_DRIFT": ("EVENT", ("post-announcement drift", "drift after announcement", "pead")),
}

_registered: Dict[str, Tuple[str, Tuple[str, ...]]] = {}


def register_concept(name: str, family_hint: str, phrases: Tuple[str, ...]) -> None:
    """Extend the vocabulary at runtime (deterministically, by name)."""
    _registered[name.strip().upper()] = (family_hint, tuple(sorted(p.lower() for p in phrases)))


def vocabulary() -> Mapping[str, Tuple[str, Tuple[str, ...]]]:
    merged = dict(_VOCABULARY)
    merged.update(_registered)
    return merged


@dataclass(frozen=True)
class ConceptMatch:
    concept: str
    family_hint: str
    matched_phrase: str
    context: str          # the sentence the phrase appeared in, for provenance


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def extract_concepts(text: str) -> Tuple[ConceptMatch, ...]:
    """Return every vocabulary concept present in ``text``, deterministically.

    Results are sorted by concept name so the output never depends on document
    order or dict iteration order.
    """
    matches: Dict[str, ConceptMatch] = {}
    sentences = _sentences(text)
    normalized = [(s, normalize_text(s)) for s in sentences]

    for concept, (family_hint, phrases) in sorted(vocabulary().items()):
        for phrase in phrases:
            needle = normalize_text(phrase)
            for original, norm in normalized:
                if needle in norm:
                    # Keep the first (document-order) occurrence of each concept.
                    if concept not in matches:
                        matches[concept] = ConceptMatch(
                            concept=concept,
                            family_hint=family_hint,
                            matched_phrase=phrase,
                            context=original[:400],
                        )
                    break
            if concept in matches:
                break

    return tuple(matches[k] for k in sorted(matches))


def concept_names(text: str) -> Tuple[str, ...]:
    return tuple(m.concept for m in extract_concepts(text))
