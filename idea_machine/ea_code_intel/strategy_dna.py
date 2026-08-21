"""
Strategy DNA: deterministic extraction of mechanism STRUCTURE from mined
source text, not the source's code or its performance claims.

Design principle (explicit, from the task's own instruction): "Extract
Strategy DNA rather than copying strategies." This module never stores a
full code listing. It stores short tags plus the exact phrase in the source
text that justified each tag, so every tag is traceable and falsifiable
against the original source -- and never fabricated.

Extraction is keyword/pattern based, not an LLM guessing at intent. This is
intentional (task instruction: "prefer simple, deterministic components
over unnecessary AI complexity") and it also means every tag can be
audited: re-running extraction on the same text always produces the same
DNA.
"""

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


DNA_CATEGORIES = [
    "entry_mechanism", "exit_mechanism", "filters", "regime_detection",
    "volatility_logic", "session_time_logic", "event_logic", "mtf_structure",
    "cross_asset_relationships", "position_sizing", "risk_management",
    "execution_assumptions",
]

# Deterministic keyword -> (category, tag) map. Each entry is a regex and the
# tag it contributes if matched. Kept small and legible on purpose -- this is
# meant to be auditable, not exhaustive.
PATTERNS: List[tuple] = [
    (r"\bmoving average\b|\bMA cross", "entry_mechanism", "MA_CROSSOVER"),
    (r"\brsi\b", "entry_mechanism", "RSI_THRESHOLD"),
    (r"\bmacd\b", "entry_mechanism", "MACD_SIGNAL"),
    (r"\bbollinger band", "entry_mechanism", "BOLLINGER_BAND"),
    (r"\bbreakout\b", "entry_mechanism", "RANGE_BREAKOUT"),
    (r"\bfair value gap\b|\bfvg\b", "entry_mechanism", "FAIR_VALUE_GAP"),
    (r"\border block", "entry_mechanism", "ORDER_BLOCK"),
    (r"\bengulfing\b", "entry_mechanism", "CANDLESTICK_ENGULFING"),
    (r"\bsupertrend\b", "entry_mechanism", "SUPERTREND"),
    (r"\bstochastic\b", "entry_mechanism", "STOCHASTIC_SIGNAL"),
    (r"\bnadaraya[- ]watson\b", "entry_mechanism", "NADARAYA_WATSON_ENVELOPE"),

    (r"\btrailing stop\b", "exit_mechanism", "TRAILING_STOP"),
    (r"\btake profit\b|\btp\b", "exit_mechanism", "FIXED_TAKE_PROFIT"),
    (r"\bstop loss\b|\bsl\b", "exit_mechanism", "FIXED_STOP_LOSS"),
    (r"\batr stop", "exit_mechanism", "ATR_BASED_STOP"),
    (r"\btime stop\b|\btime-based exit", "exit_mechanism", "TIME_STOP"),

    (r"\bfilter\b", "filters", "GENERIC_FILTER"),
    (r"\bwilliams fractal", "filters", "WILLIAMS_FRACTAL_FILTER"),
    (r"\bandean oscillator", "filters", "ANDEAN_OSCILLATOR_FILTER"),

    (r"\bregime\b", "regime_detection", "EXPLICIT_REGIME_MODEL"),
    (r"\btrend[- ]following\b|\btrend filter\b", "regime_detection", "TREND_REGIME_FILTER"),
    (r"\bmean[- ]revers", "regime_detection", "MEAN_REVERSION_REGIME"),

    (r"\batr\b|\baverage true range", "volatility_logic", "ATR_BASED"),
    (r"\bvolatility\b", "volatility_logic", "GENERIC_VOLATILITY_LOGIC"),
    (r"\bcompression\b|\bsqueeze\b", "volatility_logic", "VOLATILITY_COMPRESSION"),

    (r"\bsession\b|\blondon session\b|\bny session\b|\basian session\b",
     "session_time_logic", "SESSION_FILTER"),
    (r"\bday of week\b|\bturn of month\b", "session_time_logic", "CALENDAR_DAY_EFFECT"),

    (r"\bnews\b|\bnfp\b|\bcpi\b|\beconomic calendar\b|\bevent\b",
     "event_logic", "MACRO_EVENT_LOGIC"),

    (r"\bmulti[- ]?timeframe\b|\bhigher timeframe\b|\bhtf\b",
     "mtf_structure", "MULTI_TIMEFRAME_CONFIRM"),

    (r"\bcorrelat", "cross_asset_relationships", "CORRELATION_BASED"),
    (r"\bcross[- ]asset\b|\bdxy\b|\byield\b|\bcot\b|\bcommitments of traders",
     "cross_asset_relationships", "CROSS_ASSET_DRIVER"),

    (r"\bmartingale\b", "position_sizing", "MARTINGALE"),
    (r"\bgrid\b", "position_sizing", "GRID_SIZING"),
    (r"\bfixed lot\b|\bfixed size\b", "position_sizing", "FIXED_LOT"),
    (r"\brisk[- ]?%|\bpercent risk\b|\brisk per trade", "position_sizing", "PERCENT_RISK_SIZING"),

    (r"\bmax drawdown\b|\bdrawdown limit", "risk_management", "DRAWDOWN_LIMIT"),
    (r"\bdaily loss limit\b|\bmax daily loss", "risk_management", "DAILY_LOSS_LIMIT"),
    (r"\bhedge\b|\bhedging\b", "risk_management", "HEDGING"),

    (r"\bslippage\b", "execution_assumptions", "SLIPPAGE_MODELED"),
    (r"\bspread\b", "execution_assumptions", "SPREAD_GUARD"),
    (r"\bno repaint", "execution_assumptions", "NON_REPAINTING_CLAIM"),
    (r"\bbacktest", "execution_assumptions", "BACKTEST_CLAIMED"),
]


@dataclass
class StrategyDNA:
    """
    Structural fingerprint of ONE mined source. Tags are grouped by
    category; each tag carries the literal matched phrase as its citation,
    never a paraphrase invented beyond what matched.
    """
    dna_id: str
    source_title: str
    source_url: Optional[str]
    tags: Dict[str, List[str]] = field(default_factory=dict)   # category -> [tag, ...]
    citations: Dict[str, str] = field(default_factory=dict)    # tag -> literal matched text
    provenance: str = "SOURCE_ONLY"
    # explicitly NOT extracted: stars, claimed win-rate, claimed returns.
    # those are recorded separately as unverified source metadata, never
    # mixed into the DNA or into any score.
    unverified_source_claims: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    def tag_count(self) -> int:
        return sum(len(v) for v in self.tags.values())


def extract_dna(dna_id: str, source_title: str, source_url: Optional[str],
                text: str, unverified_claims: Optional[Dict[str, str]] = None) -> StrategyDNA:
    """
    Deterministic extraction: scan text once, record every pattern match.
    Same text in -> same DNA out, always. No randomness, no model call.
    """
    dna = StrategyDNA(dna_id=dna_id, source_title=source_title, source_url=source_url,
                      unverified_source_claims=unverified_claims or {})
    lower = text.lower()
    for pattern, category, tag in PATTERNS:
        m = re.search(pattern, lower)
        if m:
            dna.tags.setdefault(category, [])
            if tag not in dna.tags[category]:
                dna.tags[category].append(tag)
                # citation: a short window of the ORIGINAL (not lowered) text around the match
                start = max(0, m.start() - 20)
                end = min(len(text), m.end() + 40)
                dna.citations[tag] = text[start:end].strip().replace("\n", " ")
    return dna


def signature(dna: StrategyDNA) -> str:
    """
    A stable, order-independent signature of the DNA's tag set -- used by
    the novelty engine to compare mechanisms without caring which source
    produced them. Two sources with identical tag sets get the same
    signature regardless of naming/wording differences.
    """
    all_tags = sorted(t for tags in dna.tags.values() for t in tags)
    return "|".join(all_tags)
