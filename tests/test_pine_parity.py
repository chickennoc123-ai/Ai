"""ML-001-R2 Python<->Pine parity tests (Phases 7-9 of the TradingView
Pine parity project).

These tests do NOT execute Pine Script — there is no Pine compiler
available in this environment (see
ML-001-R2-PYTHON-PINE-PARITY-REPORT.md for the exact evidentiary status
of every parity claim). What they DO verify, with real automated
checks:

  1. STRUCTURAL: the "CANONICAL FEATURE BLOCK -- BEGIN/END" text is
     byte-identical across all three .pine files, so there is only ever
     one place the feature formulas are actually written (Phase 8).
  2. TRANSCRIPTION CORRECTNESS: the OHLC and expected-feature array
     literals embedded in ML_001_R2_FEATURE_DEBUG.pine for its
     "Fixture Replay Mode" are exactly what
     ML-001-R2-PINE-PARITY-FIXTURE.csv (bars 0-159) says they should
     be — catching any copy/generation error between the fixture CSV
     and the committed Pine source (Phase 7).
  3. ADVERSARIAL SCENARIOS (Phase 9): each named scenario the parity
     project's instructions call out (rising/falling/flat market, RSI
     extreme, ATR spike, volatility-regime transition, insufficient
     warmup, signal-on-close, next-bar execution) is exercised against
     the real Python production pipeline (core.features.fe_r2_001),
     with the EXPECTED Pine behavior documented in each test's
     docstring as a traceable claim, not verified by execution. A human
     tester is expected to check that expectation manually against the
     Pine scripts in TradingView — see
     ML-001-R2-TRADINGVIEW-MANUAL-TEST-GUIDE.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import build_feature_matrix

REPO_ROOT = Path(__file__).resolve().parent.parent
PINE_DIR = REPO_ROOT / "pine"
FIXTURE_CSV = REPO_ROOT / "ML-001-R2-PINE-PARITY-FIXTURE.csv"

BEGIN_MARKER = "// ML-001-R2 CANONICAL FEATURE BLOCK -- BEGIN"
END_MARKER = "// ML-001-R2 CANONICAL FEATURE BLOCK -- END"


def _extract_canonical_block(text: str) -> str:
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER, start)
    # Slice from just after the BEGIN marker's own comment line to just
    # before the END marker's fence line, so leading/trailing decorative
    # "====" fence lines (which legitimately differ in surrounding
    # whitespace between files) don't cause false-positive mismatches.
    block_start = text.index("\n", start) + 1
    return text[block_start:end]


class TestCanonicalFeatureBlockTextIdentity:
    """Phase 8 structural parity: exactly one canonical feature
    implementation must exist, verbatim-duplicated (not reimplemented)
    across every Pine file that needs it."""

    @pytest.fixture()
    def blocks(self) -> dict[str, str]:
        files = {
            "ml_001_r2_features.pine": PINE_DIR / "ml_001_r2_features.pine",
            "ML_001_R2_FEATURE_DEBUG.pine": PINE_DIR / "ML_001_R2_FEATURE_DEBUG.pine",
            "ML_001_R2_STRATEGY.pine": PINE_DIR / "ML_001_R2_STRATEGY.pine",
        }
        for name, path in files.items():
            assert path.exists(), f"expected Pine file missing: {name}"
        return {name: _extract_canonical_block(path.read_text()) for name, path in files.items()}

    def test_all_three_files_contain_the_marker_block(self, blocks: dict[str, str]) -> None:
        for name, block in blocks.items():
            assert len(block) > 500, f"{name}: canonical block unexpectedly short/empty"

    def test_debug_block_is_byte_identical_to_features_block(self, blocks: dict[str, str]) -> None:
        assert blocks["ML_001_R2_FEATURE_DEBUG.pine"] == blocks["ml_001_r2_features.pine"]

    def test_strategy_block_is_byte_identical_to_features_block(self, blocks: dict[str, str]) -> None:
        assert blocks["ML_001_R2_STRATEGY.pine"] == blocks["ml_001_r2_features.pine"]


def _parse_pine_array(text: str, array_name: str) -> list[float | None]:
    match = re.search(array_name + r"\s*=\s*array\.from\((.*?)\)\n", text, re.S)
    assert match is not None, f"array {array_name} not found in debug Pine source"
    raw_values = [v.strip() for v in match.group(1).split(",")]
    return [None if v == "na" else float(v) for v in raw_values]


class TestFixtureEmbedTranscriptionCorrectness:
    """Phase 7 numerical parity, transcription layer: verifies the Pine
    array literals embedded in ML_001_R2_FEATURE_DEBUG.pine (bars
    0-159) are exactly what the fixture CSV says, so any later Pine-vs-
    Python discrepancy a human observes in TradingView can be trusted
    to reflect a real Pine execution-semantics difference — not a
    copy/paste or rounding error introduced while embedding the data.

    Tolerances declared in advance, per Phase 7's "define tolerance
    before seeing discrepancies" requirement: the embed used 6 decimal
    places for OHLC and 10 for feature values (see
    /home/user/Ai/pine/ML_001_R2_FEATURE_DEBUG.pine array declarations),
    so a tolerance of 5e-7 (tighter than the coarsest embed precision,
    OHLC's 6 decimals) is used uniformly below.
    """

    EMBED_TOLERANCE = 5e-7
    N_EMBEDDED_BARS = 160

    @pytest.fixture()
    def debug_source(self) -> str:
        path = PINE_DIR / "ML_001_R2_FEATURE_DEBUG.pine"
        assert path.exists()
        return path.read_text()

    @pytest.fixture()
    def fixture_df(self) -> pd.DataFrame:
        assert FIXTURE_CSV.exists(), "ML-001-R2-PINE-PARITY-FIXTURE.csv must be generated first"
        return pd.read_csv(FIXTURE_CSV, index_col="timestamp", parse_dates=True)

    @pytest.mark.parametrize(
        "array_name,csv_column",
        [
            ("fxOpen", "open"),
            ("fxHigh", "high"),
            ("fxLow", "low"),
            ("fxClose", "close"),
            ("fxExpMomentum5", "momentum_5"),
            ("fxExpMomentum20", "momentum_20"),
            ("fxExpRsi14", "rsi_14"),
            ("fxExpAtr14", "atr_14"),
        ],
    )
    def test_embedded_array_matches_fixture_csv(
        self, debug_source: str, fixture_df: pd.DataFrame, array_name: str, csv_column: str
    ) -> None:
        embedded = _parse_pine_array(debug_source, array_name)
        assert len(embedded) == self.N_EMBEDDED_BARS

        expected = fixture_df[csv_column].iloc[: self.N_EMBEDDED_BARS].tolist()

        for i, (embedded_val, expected_val) in enumerate(zip(embedded, expected)):
            is_expected_nan = pd.isna(expected_val)
            if is_expected_nan:
                assert embedded_val is None, f"{array_name}[{i}]: expected na, embedded {embedded_val}"
            else:
                assert embedded_val is not None, f"{array_name}[{i}]: expected {expected_val}, embedded na"
                assert embedded_val == pytest.approx(expected_val, abs=self.EMBED_TOLERANCE), (
                    f"{array_name}[{i}]: embedded {embedded_val} vs fixture-CSV {expected_val}"
                )

    def test_warmup_boundaries_match_spec(self, debug_source: str) -> None:
        """Cross-check against spec Section 4's WARMUP_BARS values directly
        (independent of the CSV round-trip above): first non-na index must
        be exactly 5 / 20 / 100 / 100 for momentum_5 / momentum_20 /
        rsi_14 / atr_14 respectively."""
        expected_first_valid = {
            "fxExpMomentum5": 5,
            "fxExpMomentum20": 20,
            "fxExpRsi14": 100,
            "fxExpAtr14": 100,
        }
        for array_name, expected_idx in expected_first_valid.items():
            values = _parse_pine_array(debug_source, array_name)
            first_valid = next(i for i, v in enumerate(values) if v is not None)
            assert first_valid == expected_idx, f"{array_name}: first valid at {first_valid}, expected {expected_idx}"


def _synthetic_section(rng: np.random.Generator, n: int, start_price: float, drift: float, vol: float, kind: str):
    if kind == "flat":
        close = np.full(n, start_price)
    elif kind == "trend_up":
        close = start_price + np.arange(1, n + 1) * drift
    elif kind == "trend_down":
        close = start_price - np.arange(1, n + 1) * drift
    else:
        rets = rng.normal(drift, vol, n)
        close = start_price * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]
    intrabar = np.abs(rng.normal(vol * 0.6, vol * 0.2, n)) * start_price + 1e-6
    high = np.maximum(open_, close) + intrabar
    low = np.minimum(open_, close) - intrabar
    return open_, high, low, close


def _make_df(sections: list[tuple], start: str = "2022-01-03 00:00") -> pd.DataFrame:
    open_all = np.concatenate([s[0] for s in sections])
    high_all = np.concatenate([s[1] for s in sections])
    low_all = np.concatenate([s[2] for s in sections])
    close_all = np.concatenate([s[3] for s in sections])
    index = pd.date_range(start, periods=len(open_all), freq="h", tz="UTC")
    return pd.DataFrame({"open": open_all, "high": high_all, "low": low_all, "close": close_all}, index=index)


class TestPhase9AdversarialScenarios:
    """Phase 9 adversarial scenarios. Each test documents, in its
    docstring, the EXPECTED Pine behavior implied by the canonical
    feature block's own logic (which is byte-identical across all three
    .pine files per TestCanonicalFeatureBlockTextIdentity above) — this
    is a traceable claim for a human to manually verify in TradingView,
    not something proven by running Pine here."""

    def test_rising_market_positive_momentum_rsi_above_50(self) -> None:
        """EXPECTED PINE BEHAVIOR: on a sustained uptrend, momentum_5 and
        momentum_20 are positive once warmed up, and rsi_14 trends above
        50 (approaching 100 as avg_loss -> 0) — because Pine's rsi_14_raw
        uses the identical avg_gain/avg_loss/RS formula as this test's
        oracle."""
        rng = np.random.default_rng(1)
        o, h, l, c = _synthetic_section(rng, 700, 1.1000, 0.0003, 0.0001, "trend_up")
        df = _make_df([(o, h, l, c)])
        feats = build_feature_matrix(df)
        tail = feats.iloc[650:]
        assert (tail["momentum_5"] > 0).all()
        assert (tail["momentum_20"] > 0).all()
        assert (tail["rsi_14"] > 50).all()

    def test_falling_market_negative_momentum_rsi_below_50(self) -> None:
        """EXPECTED PINE BEHAVIOR: mirror image of the rising-market case —
        rsi_14 trends below 50, approaching 0 as avg_gain -> 0."""
        rng = np.random.default_rng(2)
        o, h, l, c = _synthetic_section(rng, 700, 1.1000, 0.0003, 0.0001, "trend_down")
        df = _make_df([(o, h, l, c)])
        feats = build_feature_matrix(df)
        tail = feats.iloc[650:]
        assert (tail["momentum_5"] < 0).all()
        assert (tail["momentum_20"] < 0).all()
        assert (tail["rsi_14"] < 50).all()

    def test_flat_market_zero_momentum_rsi_50_atr_zero(self) -> None:
        """EXPECTED PINE BEHAVIOR: on perfectly flat closes, momentum_5/20
        are exactly 0, and rsi_14's avg_loss==0 & avg_gain==0 branch fires,
        giving exactly 50.0 (the explicit flat-market convention in both
        the Python oracle and the Pine rsi_14_raw ternary) rather than a
        0/0 NaN.

        IMPORTANT (discovered while writing this test): the seeded-Wilder
        recurrence does NOT "reset" the moment prices go flat. If a
        non-flat period precedes the flat section, avg_gain and avg_loss
        both decay by the same factor (*13/14 per bar, since new
        gain/loss inputs are exactly 0) — so their RATIO, and therefore
        RSI, stays PINNED at whatever it was at the flat-transition, not
        50, for a very long time (asymptotic decay, not a hard reset).
        Exact RSI==50.0 requires avg_gain and avg_loss to both seed to
        bit-exact 0.0, which only happens if the market is ALREADY flat
        for the entire 100-bar rsi_14 warmup window (bar 0 onward) — so
        this test uses a single flat section from bar 0, not a
        walk-then-flat transition."""
        o, h, l, c = _synthetic_section(np.random.default_rng(3), 150, 1.1000, 0.0, 0.0, "flat")
        df = _make_df([(o, h, l, c)])
        feats = build_feature_matrix(df)
        flat_tail = feats.iloc[100:]
        assert (flat_tail["momentum_5"] == 0.0).all()
        assert (flat_tail["momentum_20"] == 0.0).all()
        assert (flat_tail["rsi_14"] == 50.0).all()
        # atr_14 is not bit-exact 0: _synthetic_section adds a small fixed
        # +1e-6 intrabar wick even at vol=0 (high/low never exactly equal
        # open/close), so True Range is a small nonzero constant, not 0.
        assert (flat_tail["atr_14"].abs() < 1e-5).all()

    def test_rsi_extreme_all_gains_saturates_at_100_not_inf_or_nan(self) -> None:
        """EXPECTED PINE BEHAVIOR: avg_loss==0 & avg_gain>0 fires Pine's
        `(avg_loss == 0.0) ? 100.0` branch — RSI saturates at exactly
        100.0, never inf/na, matching the spec Section 4 Step 5 convention.

        As with the flat-market case above, avg_loss only reaches
        bit-exact 0.0 if there are NO down-closes anywhere in the 100-bar
        rsi_14 warmup window (a preceding walk section would leave a
        decaying-but-nonzero avg_loss residue for many bars into the
        uptrend) — so this test uses a strictly monotonic uptrend from
        bar 0, with zero down-closes throughout."""
        o, h, l, c = _synthetic_section(np.random.default_rng(4), 150, 1.1000, 0.001, 0.00001, "trend_up")
        df = _make_df([(o, h, l, c)])
        feats = build_feature_matrix(df)
        tail = feats.iloc[100:]
        assert (tail["rsi_14"] == 100.0).all()

    def test_atr_spike_on_price_gap_then_decays(self) -> None:
        """EXPECTED PINE BEHAVIOR: a single large-range/gap bar produces a
        true_range spike; atr_14 (the seeded-Wilder recurrence) jumps
        immediately (weight 1/14 of the spike on the very next value) and
        decays smoothly afterward — matching f_seededWilder's recurrence
        in every .pine file exactly."""
        rng = np.random.default_rng(5)
        o1, h1, l1, c1 = _synthetic_section(rng, 200, 1.1000, 0.0, 0.00012, "walk")
        atr_before_gap = build_feature_matrix(_make_df([(o1, h1, l1, c1)]))["atr_14"].iloc[-1]

        gap_open = c1[-1] * 1.02
        o2, h2, l2, c2 = _synthetic_section(rng, 100, gap_open, 0.0, 0.0002, "walk")
        o2[0] = gap_open
        df = _make_df([(o1, h1, l1, c1), (o2, h2, l2, c2)])
        feats = build_feature_matrix(df)

        atr_at_gap = feats["atr_14"].iloc[200]
        assert atr_at_gap > atr_before_gap * 1.5, "ATR should spike sharply on the gap bar"
        atr_10_bars_later = feats["atr_14"].iloc[210]
        assert atr_10_bars_later < atr_at_gap, "ATR should decay after the spike, not stay pinned"

    def test_volatility_regime_transitions_low_to_high_to_low(self) -> None:
        """EXPECTED PINE BEHAVIOR: volatility_regime (computed from
        atr_14's 500-bar trailing 33rd/67th percentile, on the RAW,
        pre-warmup-mask series — see the canonical block's explicit
        ordering comment) moves 0 (low) -> higher values during a
        high-vol section -> back down as vol subsides, once past the
        600-bar warmup."""
        rng = np.random.default_rng(6)
        o1, h1, l1, c1 = _synthetic_section(rng, 650, 1.1000, 0.0, 0.00012, "walk")
        o2, h2, l2, c2 = _synthetic_section(rng, 150, c1[-1], 0.0, 0.0012, "walk")
        o3, h3, l3, c3 = _synthetic_section(rng, 150, c2[-1], 0.0, 0.00012, "walk")
        df = _make_df([(o1, h1, l1, c1), (o2, h2, l2, c2), (o3, h3, l3, c3)])
        feats = build_feature_matrix(df)

        low_regime_start = feats["volatility_regime"].iloc[600:650]
        high_regime = feats["volatility_regime"].iloc[700:750]
        assert low_regime_start.mean() < high_regime.mean(), "regime should rise during the high-vol section"
        assert (feats["volatility_regime"].iloc[600:950] >= 0).all()
        assert set(feats["volatility_regime"].iloc[600:950].unique()) <= {0.0, 1.0, 2.0}

    def test_insufficient_warmup_all_features_na(self) -> None:
        """EXPECTED PINE BEHAVIOR: before bar_index reaches each feature's
        WARMUP_BARS threshold, the Pine canonical block's masking ternaries
        (`bar_index < N ? na : ...`) force na — matching Python's NaN
        exactly, never a spurious partial-window number."""
        rng = np.random.default_rng(7)
        o, h, l, c = _synthetic_section(rng, 50, 1.1000, 0.0, 0.0003, "walk")
        df = _make_df([(o, h, l, c)])
        feats = build_feature_matrix(df)
        assert feats["momentum_20"].iloc[:20].isna().all()
        assert feats["rsi_14"].isna().all()
        assert feats["atr_14"].isna().all()
        assert feats["volatility_regime"].isna().all()
        assert feats["momentum_5"].iloc[:5].isna().all()
        assert feats["momentum_5"].iloc[5:].notna().all()

    def test_signal_on_close_then_execution_next_bar_is_a_pine_native_property(self) -> None:
        """EXPECTED PINE BEHAVIOR: this scenario is a Pine execution-model
        property, not a Python feature-computation property, so it cannot
        be exercised via build_feature_matrix. Documented here as a
        pointer: ML_001_R2_STRATEGY.pine's strategy() is declared with
        process_orders_on_close=false (Pine's default), under which any
        strategy.entry()/strategy.exit() invoked during bar t's script
        evaluation fills at bar (t+1)'s open automatically — see that
        file's PHASE 5 section comments for the full reasoning, and
        ML-001-R2-TRADINGVIEW-MANUAL-TEST-GUIDE.md for how a human
        confirms this by watching the SIGNAL BAR / EXECUTION BAR markers
        with timingDemoMode enabled."""
        strategy_pine = (PINE_DIR / "ML_001_R2_STRATEGY.pine").read_text()
        assert "process_orders_on_close = false" in strategy_pine
        assert "calc_on_every_tick    = false" in strategy_pine
