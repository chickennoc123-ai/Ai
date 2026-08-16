"""Information Audit (IA-001) test suite.

Tests verify that the audit correctly identifies:
- PASS: Features with no future information leakage
- FAIL: Features with proven future information leakage
- UNKNOWN: Features with unverifiable dependencies (BLOCKED)
"""

from __future__ import annotations

import pytest

from core.information_audit import (
    AuditBlockedError,
    AuditVerdictType,
    FeatureAudit,
    InformationAuditor,
    TargetAudit,
)
from core.temporal_contract import TemporalContractBuilder


class TestIA001A:
    """IA-001-A: Future raw value in feature."""

    def test_future_raw_value_fails(self) -> None:
        """Feature computed from future raw value should FAIL."""
        auditor = InformationAuditor("IA-001-A-test", "v1.0")

        # Feature depends on next bar's close (shift(-1))
        contract = TemporalContractBuilder("future_close_feature", "feature", decision_time=0).add_dependency(
            "next_close",
            "raw_ohlcv",
            information_time=-1,  # -1 means future
            provenance="shift(-1)",
            description="Feature uses next bar close",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed
        assert result.verdict == AuditVerdictType.FAIL
        assert len(result.violations) == 1
        assert "future information" in result.violations[0].lower()


class TestIA001B:
    """IA-001-B: shift(-1) dependency."""

    def test_shift_negative_one_fails(self) -> None:
        """Feature using shift(-1) should FAIL."""
        auditor = InformationAuditor("IA-001-B-test", "v1.0")

        contract = TemporalContractBuilder("lagged_forward_feature", "feature", decision_time=0).add_dependency(
            "close",
            "ohlcv",
            information_time=-1,
            provenance="shift(-1)",
            description="Looks one bar ahead",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001C:
    """IA-001-C: Target used as feature."""

    def test_target_as_feature_fails(self) -> None:
        """Using target variable directly as a feature should FAIL."""
        auditor = InformationAuditor("IA-001-C-test", "v1.0")

        # Target is typically future, so using it directly is future-dependent
        contract = TemporalContractBuilder("target_as_feature", "feature", decision_time=0).add_dependency(
            "return_next_5",
            "target",
            information_time=5,  # Future-looking
            provenance="direct_target_lookup",
            description="Using target as feature",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001D:
    """IA-001-D: Global normalization (fit on entire dataset)."""

    def test_global_normalization_fails(self) -> None:
        """Feature normalized using stats from entire dataset should FAIL."""
        auditor = InformationAuditor("IA-001-D-test", "v1.0")

        # Global mean/std fit on entire dataset means we use future data for normalization
        contract = TemporalContractBuilder("globally_normalized", "feature", decision_time=100).add_dependency(
            "raw_feature",
            "computed",
            information_time=100,
            provenance="raw",
            description="Raw feature",
        ).add_dependency(
            "global_mean",
            "statistic",
            information_time=1000,  # Computed from entire future dataset
            provenance="None",  # Unverifiable provenance OR future-looking
            description="Mean computed on full dataset",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        # Should fail due to unverifiable provenance
        assert result.is_failed or result.is_blocked


class TestIA001E:
    """IA-001-E: Rolling calculation including future rows."""

    def test_rolling_window_with_future_fails(self) -> None:
        """Rolling window that includes future rows should FAIL."""
        auditor = InformationAuditor("IA-001-E-test", "v1.0")

        # Rolling SMA computed with window that extends into future
        contract = TemporalContractBuilder("rolling_with_future", "feature", decision_time=100).add_dependency(
            "close",
            "ohlcv",
            information_time=105,  # Window extends 5 bars into future
            provenance="rolling(window=20)",
            description="Rolling calculation includes future bars",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001F:
    """IA-001-F: Future-derived regime label."""

    def test_future_regime_fails(self) -> None:
        """Regime label computed from future volatility should FAIL."""
        auditor = InformationAuditor("IA-001-F-test", "v1.0")

        contract = TemporalContractBuilder("future_regime", "feature", decision_time=100).add_dependency(
            "volatility_next_20",
            "computed",
            information_time=-1,  # Uses future volatility
            provenance="realized_vol(forward_looking)",
            description="Regime derived from future realized volatility",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001G:
    """IA-001-G: Valid lagged feature (shift(1))."""

    def test_valid_lagged_feature_passes(self) -> None:
        """Feature using shift(1) should PASS."""
        auditor = InformationAuditor("IA-001-G-test", "v1.0")

        # For shift(1) used at bar i to predict return at bar i+1:
        # - decision_time = 0 (at bar i)
        # - information_time = 0 (close[i-1] is available when we make decision)
        # This should PASS

        contract = TemporalContractBuilder("lagged_feature", "feature", decision_time=0).add_dependency(
            "previous_close",
            "ohlcv",
            information_time=0,  # Available at decision time
            provenance="shift(1)",
            description="Previous bar close, available now",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_passed


class TestIA001H:
    """IA-001-H: Valid rolling feature (window <= cutoff)."""

    def test_rolling_within_cutoff_passes(self) -> None:
        """Rolling window that doesn't exceed cutoff should PASS."""
        auditor = InformationAuditor("IA-001-H-test", "v1.0")

        contract = TemporalContractBuilder("valid_rolling_sma", "feature", decision_time=100).add_dependency(
            "close",
            "ohlcv",
            information_time=100,  # Max info time equals decision time (current bar close is available at decision)
            provenance="rolling_sma(window=20)",
            description="20-bar SMA computed up to current bar",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_passed


class TestIA001I:
    """IA-001-I: Target uses future information."""

    def test_target_with_future_info_passes(self) -> None:
        """Target is allowed to use future information."""
        auditor = InformationAuditor("IA-001-I-test", "v1.0")

        target_contract = TemporalContractBuilder("future_return", "target", decision_time=0).add_dependency(
            "close_5",
            "ohlcv",
            information_time=5,  # Return 5 bars ahead
            provenance="next_5_bars",
            description="5-bar forward return",
        ).build()

        auditor.register_target_contract(target_contract)
        result = auditor.audit()

        # Target audit should PASS (targets are allowed to use future info)
        assert result.target_audit is not None
        assert result.target_audit.verdict == AuditVerdictType.PASS
        assert result.target_audit.uses_future_information


class TestIA001J:
    """IA-001-J: Feature cutoff exactly at decision boundary."""

    def test_cutoff_at_boundary_passes(self) -> None:
        """Feature with max_information_time == decision_time should PASS."""
        auditor = InformationAuditor("IA-001-J-test", "v1.0")

        contract = TemporalContractBuilder("boundary_feature", "feature", decision_time=100).add_dependency(
            "current_close",
            "ohlcv",
            information_time=100,  # Exactly at decision boundary
            provenance="current_bar",
            description="Close of current bar",
        ).add_dependency(
            "prev_close",
            "ohlcv",
            information_time=99,  # Previous bar
            provenance="shift(1)",
            description="Previous bar close",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_passed


class TestIA001K:
    """IA-001-K: Misaligned pct_change() causing future info."""

    def test_misaligned_pct_change_fails(self) -> None:
        """pct_change() with wrong period alignment should FAIL."""
        auditor = InformationAuditor("IA-001-K-test", "v1.0")

        # pct_change() by default looks 1 bar back, but if not aligned correctly
        # it can accidentally include future data
        contract = TemporalContractBuilder("misaligned_pct_change", "feature", decision_time=100).add_dependency(
            "returns",
            "computed",
            information_time=101,  # Accidentally includes next bar
            provenance="pct_change(misaligned)",
            description="pct_change with wrong alignment",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001L:
    """IA-001-L: Expanding/rolling window boundary contamination."""

    def test_window_boundary_contamination_fails(self) -> None:
        """Expanding window that includes future rows should FAIL."""
        auditor = InformationAuditor("IA-001-L-test", "v1.0")

        contract = TemporalContractBuilder("expanding_window", "feature", decision_time=50).add_dependency(
            "accumulated_close",
            "ohlcv",
            information_time=100,  # Expanding window reaches into future
            provenance="expanding()",
            description="Expanding window includes future bars",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed


class TestIA001M:
    """IA-001-M: Unverifiable custom transform."""

    def test_unverifiable_custom_transform_blocks(self) -> None:
        """Unverifiable custom transform should BLOCK (UNKNOWN)."""
        auditor = InformationAuditor("IA-001-M-test", "v1.0")

        contract = TemporalContractBuilder("custom_transform", "feature", decision_time=100).add_dependency(
            "raw_input",
            "computed",
            information_time=100,
            provenance=None,  # Unknown provenance = UNVERIFIABLE
            description="Custom transformation with unknown implementation",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        # Should be BLOCKED (UNKNOWN)
        assert result.is_blocked
        assert result.verdict == AuditVerdictType.UNKNOWN

        # Attempting to get certificate should raise AuditBlockedError
        with pytest.raises(AuditBlockedError):
            auditor.get_certificate()


class TestAuditCertificate:
    """Test certificate generation."""

    def test_certificate_issued_on_pass(self) -> None:
        """Certificate should be issued when audit passes."""
        auditor = InformationAuditor("cert-test", "v1.0")

        contract = TemporalContractBuilder("safe_feature", "feature", decision_time=0).add_dependency(
            "previous_close",
            "ohlcv",
            information_time=0,
            provenance="shift(1)",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_passed

        # Should be able to get certificate
        certificate = auditor.get_certificate()
        assert certificate.hypothesis_id == "cert-test"
        assert certificate.audit_result.is_passed

    def test_certificate_denied_on_fail(self) -> None:
        """Certificate should not be issued when audit fails."""
        auditor = InformationAuditor("fail-test", "v1.0")

        contract = TemporalContractBuilder("bad_feature", "feature", decision_time=0).add_dependency(
            "future_close",
            "ohlcv",
            information_time=-1,
            provenance="shift(-1)",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        assert result.is_failed

        # Should not be able to get certificate
        from utils.exceptions import ValidationFailure

        with pytest.raises(ValidationFailure):
            auditor.get_certificate()


class TestMultipleFeatures:
    """Test auditing multiple features simultaneously."""

    def test_multiple_features_with_mixed_results(self) -> None:
        """Audit should fail if any feature fails."""
        auditor = InformationAuditor("multi-test", "v1.0")

        # Good feature
        good_contract = TemporalContractBuilder("good_feature", "feature", decision_time=0).add_dependency(
            "previous_close",
            "ohlcv",
            information_time=0,
            provenance="shift(1)",
        ).build()

        # Bad feature
        bad_contract = TemporalContractBuilder("bad_feature", "feature", decision_time=0).add_dependency(
            "future_close",
            "ohlcv",
            information_time=-1,
            provenance="shift(-1)",
        ).build()

        auditor.register_feature_contract(good_contract)
        auditor.register_feature_contract(bad_contract)
        result = auditor.audit()

        # Overall verdict should be FAIL because at least one feature failed
        assert result.is_failed
        assert len(result.feature_audits) == 2


class TestArchitecturalGate:
    """Test the architectural gate (model cannot train without certificate)."""

    def test_model_training_blocked_without_certificate(self) -> None:
        """Verify that training cannot proceed without passing audit."""
        auditor = InformationAuditor("gate-test", "v1.0")

        # Register a feature that will fail audit
        contract = TemporalContractBuilder("future_feature", "feature", decision_time=0).add_dependency(
            "next_bar",
            "ohlcv",
            information_time=-1,
            provenance="shift(-1)",
        ).build()

        auditor.register_feature_contract(contract)
        result = auditor.audit()

        # Audit should fail
        assert result.is_failed

        # Certificate should not be issuable
        from utils.exceptions import ValidationFailure

        with pytest.raises(ValidationFailure) as exc_info:
            auditor.get_certificate()

        assert "FAILED" in str(exc_info.value).upper()
