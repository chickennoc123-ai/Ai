"""
Tests for Generation-6 holdout closure: EST->UTC rebuild, trimming rules,
economic gate thresholds, and the persisted Evidence Vault seal.

These test the ACTUAL sealed artifacts on disk (not fixtures) where relevant,
because the seal's whole point is byte-level verifiability.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ml_001_g6_holdout_rebuild_and_seal as g6  # noqa: E402
from core.factory.evidence_vault import EvidenceVault  # noqa: E402

HOLDOUT_CSV = REPO_ROOT / "data" / "holdout" / "EURUSD_H1_HOLDOUT_20240101_20260130_UTC.csv"
RESULT_JSON = REPO_ROOT / "reports" / "factory" / "g6_holdout_seal_result.json"


# ---------------------------------------------------------------------------
# Timezone semantics
# ---------------------------------------------------------------------------

class TestEstToUtcSemantics:
    def test_est_offset_is_plus_five_hours(self):
        assert g6.EST_TO_UTC == timedelta(hours=5)

    def test_histdata_stamp_maps_to_correct_utc_hour(self):
        # HistData stamp 202401021700 (EST) must land in the 22:00 UTC bar.
        est = datetime(2024, 1, 2, 17, 0)
        utc = est + g6.EST_TO_UTC
        assert utc == datetime(2024, 1, 2, 22, 0)


class TestWeekendClassifier:
    def test_friday_2200_utc_is_weekend(self):
        assert g6.in_weekend(datetime(2024, 1, 5, 22, 0))  # Fri

    def test_friday_2100_utc_is_trading(self):
        assert not g6.in_weekend(datetime(2024, 1, 5, 21, 0))

    def test_all_saturday_is_weekend(self):
        for h in range(24):
            assert g6.in_weekend(datetime(2024, 1, 6, h, 0))

    def test_sunday_2100_utc_is_weekend(self):
        assert g6.in_weekend(datetime(2024, 1, 7, 21, 0))

    def test_sunday_2200_utc_is_trading(self):
        assert not g6.in_weekend(datetime(2024, 1, 7, 22, 0))

    def test_midweek_is_trading(self):
        assert not g6.in_weekend(datetime(2024, 1, 3, 12, 0))  # Wed noon


# ---------------------------------------------------------------------------
# Trimming / governance boundaries
# ---------------------------------------------------------------------------

class TestSealedArtifactBoundaries:
    @pytest.fixture(scope="class")
    def timestamps(self):
        lines = HOLDOUT_CSV.read_text().strip().splitlines()[1:]
        return [datetime.fromisoformat(l.split(",")[0]).replace(tzinfo=None)
                for l in lines]

    def test_artifact_exists(self):
        assert HOLDOUT_CSV.exists()

    def test_no_bar_before_2024(self, timestamps):
        assert min(timestamps) >= datetime(2024, 1, 1)

    def test_no_2023_bars(self, timestamps):
        assert not any(t.year == 2023 for t in timestamps)

    def test_no_overlap_with_development_period(self, timestamps):
        assert min(timestamps) > g6.DEVELOPMENT_END

    def test_no_overlap_with_pure_holdout_period(self, timestamps):
        assert not any(g6.PURE_HOLDOUT_START <= t <= g6.PURE_HOLDOUT_END
                       for t in timestamps)

    def test_strictly_monotonic_unique(self, timestamps):
        assert all(a < b for a, b in zip(timestamps, timestamps[1:]))

    def test_coverage_span_over_200_days(self, timestamps):
        assert (max(timestamps) - min(timestamps)).days >= 200


# ---------------------------------------------------------------------------
# Economic gate thresholds are pre-registered constants, not runtime knobs
# ---------------------------------------------------------------------------

class TestEconomicGate:
    def test_thresholds_fixed(self):
        assert g6.MIN_COVERAGE_VS_TRADING_HOURS == 0.95
        assert g6.MAX_RESIDUAL_GAP_SHARE == 0.01

    def test_recorded_result_passes_gate(self):
        result = json.loads(RESULT_JSON.read_text())
        gate = result["audit"]["economic_gate"]
        assert gate["verdict"] == "PASS"
        assert result["audit"]["coverage_vs_trading_hours"] >= 0.95
        assert result["audit"]["residual_gap_share"] <= 0.01
        assert result["audit"]["ohlc_errors"] == 0


# ---------------------------------------------------------------------------
# Evidence Vault seal (the persisted, real one)
# ---------------------------------------------------------------------------

class TestVaultSeal:
    def test_seal_verifies_against_real_bytes(self):
        vault = EvidenceVault()
        assert g6.DATASET_ID in vault.datasets
        assert vault.verify_seal(g6.DATASET_ID, HOLDOUT_CSV.read_bytes())

    def test_tampered_bytes_fail_verification(self):
        vault = EvidenceVault()
        assert not vault.verify_seal(g6.DATASET_ID, HOLDOUT_CSV.read_bytes() + b"x")

    def test_status_is_sealed_not_authorized_not_consumed(self):
        vault = EvidenceVault()
        meta = vault.datasets[g6.DATASET_ID]
        assert meta.seal_status.value == "sealed"
        assert g6.DATASET_ID not in vault.authorizations
        assert not any(c.dataset_id == g6.DATASET_ID for c in vault.consumptions)

    def test_checksum_matches_recorded_result(self):
        import hashlib
        result = json.loads(RESULT_JSON.read_text())
        actual = hashlib.sha256(HOLDOUT_CSV.read_bytes()).hexdigest()
        assert actual == result["holdout_artifact"]["sha256"]
