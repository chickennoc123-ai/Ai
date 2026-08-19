"""
Generation 6, Phase 4: Data Source Discovery

Attempt to discover legitimate independent market-data sources.
Respects network policy; never bypasses access_failed.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import subprocess


class SourceVerificationStatus(Enum):
    """Status of source verification."""
    VERIFIED = "verified"
    ACCESS_FAILED = "access_failed"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"
    REACHABLE = "reachable"


@dataclass
class DataSourceCandidate:
    """Candidate data source for independent evaluation."""
    source_id: str
    source_name: str
    source_url: Optional[str]
    description: str
    instruments: List[str]  # Symbols it provides
    timeframes: List[str]  # Available timeframes
    coverage_period: str  # e.g., "2015-present", "2020-2023"
    data_type: str  # historical, real-time, streaming, bulk_export, api, etc.
    cost_model: str  # free, paid, broker_exclusive, academic_only, etc.

    # Verification
    verification_status: SourceVerificationStatus = SourceVerificationStatus.UNVERIFIED
    verification_attempt_timestamp: Optional[datetime] = None
    network_policy_compliant: bool = True
    requires_authorization: bool = False
    authorization_status: Optional[str] = None

    # Quality
    data_quality_assessment: str = "unknown"  # high, medium, low, unknown
    duplicate_bar_rate: Optional[float] = None
    missing_bar_rate: Optional[float] = None

    # Relationships
    uses_same_underlying_source: List[str] = field(default_factory=list)  # If derived from another source
    distinct_from: List[str] = field(default_factory=list)  # Explicitly independent from these

    # Eligibility
    eligible_for_evaluation: bool = False
    eligibility_reason: str = ""

    def is_reachable(self) -> bool:
        """True if access is not blocked by network policy."""
        return self.verification_status != SourceVerificationStatus.ACCESS_FAILED


@dataclass
class SourceDiscoveryReport:
    """Report of data source discovery attempt."""
    attempted_sources: int
    verified_sources: int
    access_failed_sources: int
    rejected_sources: int
    eligible_sources: int
    assessment_timestamp: datetime = field(default_factory=datetime.utcnow)

    sources: List[DataSourceCandidate] = field(default_factory=list)

    def add_source(self, source: DataSourceCandidate) -> None:
        """Add a discovered source to the report."""
        self.sources.append(source)


class DataSourceDiscoveryEngine:
    """
    Attempt to discover additional independent evaluation datasets.

    Permitted sources:
    - Dukascopy
    - HistData
    - Public exchange datasets
    - Reputable public repositories
    - Broker historical data (with appropriate authorization)
    - Reachable public datasets
    - Later time periods of existing sources
    - Additional instruments from existing sources

    Not permitted:
    - Proxies, credential bypass, circumvention, hidden endpoints
    - Policy workarounds
    """

    def __init__(self):
        self.discovered_sources: Dict[str, DataSourceCandidate] = {}
        self.discovery_report: Optional[SourceDiscoveryReport] = None

    def register_known_source(self, source: DataSourceCandidate) -> None:
        """Register a source already in use."""
        self.discovered_sources[source.source_id] = source

    def attempt_discover(self) -> SourceDiscoveryReport:
        """
        Attempt to discover independent data sources.

        Respects network policy; records access_failed honestly.
        """
        report = SourceDiscoveryReport(
            attempted_sources=0,
            verified_sources=0,
            access_failed_sources=0,
            rejected_sources=0,
            eligible_sources=0,
        )

        # List of known legitimate sources to attempt
        candidate_sources = [
            DataSourceCandidate(
                source_id="SRC-DUKASCOPY",
                source_name="Dukascopy Bank",
                source_url="https://www.dukascopy.com/services/data-download/",
                description="Legitimate broker historical data",
                instruments=["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD"],
                timeframes=["M1", "M5", "M15", "M30", "H1", "D1"],
                coverage_period="1990-present",
                data_type="bulk_export",
                cost_model="free",
            ),
            DataSourceCandidate(
                source_id="SRC-HISTDATA",
                source_name="HistData.com",
                source_url="https://www.histdata.com/",
                description="Historical forex data repository",
                instruments=["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD"],
                timeframes=["M1", "M5", "M15", "M30", "H1", "D1"],
                coverage_period="2000-present",
                data_type="bulk_export",
                cost_model="free_limited",
            ),
            DataSourceCandidate(
                source_id="SRC-YAHOO-FINANCE",
                source_name="Yahoo Finance",
                source_url="https://finance.yahoo.com/",
                description="Public equity and index data",
                instruments=["SPY", "QQQ", "TLT", "GLD", "USO"],
                timeframes=["D1"],
                coverage_period="1990-present",
                data_type="api",
                cost_model="free",
                network_policy_compliant=True,
            ),
            DataSourceCandidate(
                source_id="SRC-FRED",
                source_name="FRED (St. Louis Fed)",
                source_url="https://fred.stlouisfed.org/",
                description="US economic data and indicators",
                instruments=["DFF", "UNRATE", "CPIAUCSL"],
                timeframes=["D1", "M1"],
                coverage_period="varies",
                data_type="api",
                cost_model="free",
                network_policy_compliant=True,
            ),
            DataSourceCandidate(
                source_id="SRC-ECB",
                source_name="European Central Bank",
                source_url="https://www.ecb.europa.eu/stats/data/",
                description="EUR-related economic and market data",
                instruments=["EURUSD"],
                timeframes=["D1", "M1"],
                coverage_period="1990-present",
                data_type="api",
                cost_model="free",
                network_policy_compliant=True,
            ),
        ]

        # Attempt to verify each source
        for source in candidate_sources:
            report.attempted_sources += 1

            # Check network reachability (no proxies, no workarounds)
            if source.source_url:
                reachable = self._verify_network_access(source.source_url)
                if not reachable:
                    source.verification_status = SourceVerificationStatus.ACCESS_FAILED
                    report.access_failed_sources += 1
                else:
                    source.verification_status = SourceVerificationStatus.REACHABLE
                    report.verified_sources += 1

                source.verification_attempt_timestamp = datetime.utcnow()

            # Determine eligibility based on verification and policy
            if source.verification_status == SourceVerificationStatus.REACHABLE:
                if source.network_policy_compliant and source.cost_model in ["free", "free_limited"]:
                    source.eligible_for_evaluation = True
                    source.eligibility_reason = "Reachable, policy compliant, accessible"
                    report.eligible_sources += 1
                else:
                    source.eligible_for_evaluation = False
                    if not source.network_policy_compliant:
                        source.eligibility_reason = "Not compliant with network policy"
                    else:
                        source.eligibility_reason = "Requires authorization or payment"

            # Record in report
            report.add_source(source)
            self.discovered_sources[source.source_id] = source

        self.discovery_report = report
        return report

    def _verify_network_access(self, url: str) -> bool:
        """
        Verify network access to a URL.

        Returns True if reachable, False if access_failed.
        Never attempts proxies, workarounds, or credential bypass.
        """
        try:
            # Simple HEAD request with timeout
            result = subprocess.run(
                ["curl", "-s", "-m", "8", "-I", url],
                capture_output=True,
                timeout=10,
                text=True
            )
            # curl exit code 0 = success, any other = access failed
            return result.returncode == 0
        except Exception:
            return False

    def get_new_instruments(self) -> List[str]:
        """Get list of new instruments available from eligible sources."""
        instruments = set()
        for source in self.discovered_sources.values():
            if source.eligible_for_evaluation:
                instruments.update(source.instruments)
        return list(instruments)

    def get_new_data_periods(self) -> Dict[str, str]:
        """Get additional time periods available from existing sources."""
        # Would compare coverage_period of newly discovered sources
        # with existing coverage and report expansions
        return {}

    def get_verified_sources_not_in_use(self) -> List[str]:
        """Get sources that verified as reachable but are not yet in use."""
        return [
            source.source_id
            for source in self.discovered_sources.values()
            if source.verification_status == SourceVerificationStatus.REACHABLE
            and not source.uses_same_underlying_source
        ]

    def summary(self) -> Dict[str, Any]:
        """Summary of discovery attempt."""
        if not self.discovery_report:
            return {}

        return {
            "attempted": self.discovery_report.attempted_sources,
            "verified": self.discovery_report.verified_sources,
            "access_failed": self.discovery_report.access_failed_sources,
            "eligible": self.discovery_report.eligible_sources,
            "sources": [
                {
                    "id": s.source_id,
                    "name": s.source_name,
                    "status": s.verification_status.value,
                    "eligible": s.eligible_for_evaluation,
                    "instruments": s.instruments,
                    "coverage": s.coverage_period,
                }
                for s in self.discovery_report.sources
            ]
        }
