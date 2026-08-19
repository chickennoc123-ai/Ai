# Integration Example: MCP Server with Holdout Acquisition Pipeline

This document shows how to integrate the Dukascopy MCP server with the existing `holdout_acquisition.py` validation pipeline to fetch, validate, and seal the primary holdout.

---

## Overview

The complete flow:

```
1. Fetch via MCP
   └─ client.call_tool("fetch_eurusd_h1", ...)
   └─ Returns CSV + metadata

2. Create CandidateArtifact
   └─ Parse CSV into rows
   └─ Copy provenance metadata

3. Run Validation Gates
   └─ evaluate_source_candidate() → Check provenance
   └─ validate_artifact_integrity() → Check OHLC consistency
   └─ check_independence() → Check no overlap with prior research
   └─ decide_primary_holdout_eligibility() → Combined decision

4. Seal via EvidenceVault
   └─ One-time authorization
   └─ Cryptographic sealing (SHA256)
   └─ Persistent storage

5. Report Results
   └─ Checksums match
   └─ Data sealed
   └─ Generation 7 ready to start
```

---

## Step-by-Step Code Example

### 1. Fetch Data via MCP

```python
# In Claude Code environment, after MCP server is configured

from mcp import Client
import json

def fetch_from_mcp_dukascopy(start_date: str, end_date: str) -> dict:
    """
    Call MCP server running on personal machine to fetch Dukascopy data.
    
    Args:
        start_date: "YYYY-MM-DD" format (e.g., "2022-01-01")
        end_date: "YYYY-MM-DD" format (e.g., "2026-12-31")
    
    Returns:
        dict with "status", "csv_data", "metadata"
    """
    try:
        client = Client("dukascopy")
        result = client.call_tool("fetch_eurusd_h1", {
            "start_date": start_date,
            "end_date": end_date
        })
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"MCP call failed: {e}",
            "csv_data": None,
            "metadata": None
        }

# Call it
result = fetch_from_mcp_dukascopy("2022-01-01", "2026-12-31")

if result["status"] != "success":
    print(f"❌ Fetch failed: {result['message']}")
    exit(1)

print(f"✓ Fetched {result['metadata']['actual_rows']} bars")
print(f"  Checksum: {result['metadata']['checksum']}")
```

### 2. Create CandidateArtifact

```python
# In core/factory/holdout_acquisition.py, add:

from dataclasses import dataclass
from typing import Optional

@dataclass
class CandidateArtifact:
    """Represents a candidate dataset artifact."""
    data_bytes: bytes  # Raw CSV bytes
    metadata: dict  # Full metadata from source/MCP
    rows: Optional[list] = None  # Parsed OHLCV rows
    
    def __post_init__(self):
        """Parse CSV into rows on instantiation."""
        if self.rows is None:
            self.rows = self._parse_csv()
    
    def _parse_csv(self) -> list:
        """Parse CSV bytes into list of dicts."""
        lines = self.data_bytes.decode("utf-8").split("\n")
        if not lines or lines[0] != "timestamp,open,high,low,close":
            raise ValueError(f"Invalid CSV header: {lines[0] if lines else '(empty)'}")
        
        rows = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) != 5:
                raise ValueError(f"Invalid CSV row (expected 5 fields): {line}")
            
            rows.append({
                "timestamp": parts[0],
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
            })
        
        return rows

# Create artifact from MCP response
artifact = CandidateArtifact(
    data_bytes=result["csv_data"].encode("utf-8"),
    metadata=result["metadata"]
)

print(f"✓ Artifact created: {len(artifact.rows)} rows parsed")
```

### 3. Run Validation Gates

```python
from core.factory.holdout_acquisition import (
    evaluate_source_candidate,
    validate_artifact_integrity,
    check_independence,
    decide_primary_holdout_eligibility,
)

# Gate 1: Provenance (actual_origin_evidence must exist)
print("\n[Gate 1] Evaluating provenance...")
source_eval = evaluate_source_candidate(artifact.metadata)
print(f"  Provenance status: {source_eval.provenance_status}")

if source_eval.provenance_status != "VERIFIED":
    print(f"❌ REJECTED: Provenance not verified")
    print(f"   Reason: {source_eval.identity_status}")
    exit(1)

print(f"✓ Provenance verified (origin: Dukascopy via dukascopy-tick)")

# Gate 2: Artifact Integrity (OHLC relationships, monotonicity, etc.)
print("\n[Gate 2] Validating artifact integrity...")
integrity = validate_artifact_integrity(artifact)
print(f"  Is valid: {integrity.is_valid}")
print(f"  Row count: {integrity.row_count}")
print(f"  Duplicate timestamps: {integrity.duplicate_count}")
print(f"  OHLC violations: {integrity.ohlc_violation_count}")
print(f"  Non-positive prices: {integrity.non_positive_count}")

if not integrity.is_valid:
    print(f"❌ REJECTED: Artifact integrity check failed")
    print(f"   Violations: {integrity.violations}")
    exit(1)

print(f"✓ Artifact integrity validated")

# Gate 3: Independence (no overlap with DEVELOPMENT or PURE_HOLDOUT)
print("\n[Gate 3] Checking independence...")
independence = check_independence(artifact.metadata)
print(f"  Temporal overlap: {independence.temporal_overlap}")
print(f"  Research exposure: {independence.research_exposure}")

# DEVELOPMENT: 2012-11-16 to 2022-03-05
# PURE_HOLDOUT: 2021-01-01 to 2021-12-31
# New data: 2022-01-01 to 2026-12-31
# Expected: NONE (data starts after DEVELOPMENT ends)

if independence.research_exposure != "ZERO":
    print(f"❌ REJECTED: Independence check failed")
    print(f"   Exposure: {independence.research_exposure}")
    exit(1)

if independence.temporal_overlap != "NONE":
    print(f"❌ REJECTED: Temporal overlap detected")
    print(f"   Overlap: {independence.temporal_overlap}")
    exit(1)

print(f"✓ Independence verified (no overlap with prior research)")

# Gate 4: Eligibility Decision (combined)
print("\n[Gate 4] Making eligibility decision...")
eligibility = decide_primary_holdout_eligibility(artifact)
print(f"  Status: {eligibility.status}")
print(f"  Instrument match: {eligibility.instrument_match}")
print(f"  Timeframe match: {eligibility.timeframe_match}")
print(f"  Timezone match: {eligibility.timezone_match}")
print(f"  Coverage sufficient: {eligibility.coverage_sufficient}")

if eligibility.status != "ELIGIBLE":
    print(f"❌ REJECTED: Ineligible")
    print(f"   Reason: {eligibility.rejection_reason}")
    exit(1)

print(f"✓ Candidate ELIGIBLE for sealing")
```

### 4. Seal via EvidenceVault

```python
from core.factory.evidence_vault import EvidenceVault
from datetime import datetime, timezone

# Initialize vault
vault = EvidenceVault(
    vault_path="reports/factory/evidence_vault.json"
)

# Register dataset (before sealing)
print("\n[Seal] Registering dataset...")
dataset_id = vault.register_dataset_unsealed(
    dataset_name="ML-001-PRIMARY-HOLDOUT",
    instrument="EURUSD",
    timeframe="H1",
    period_start="2022-01-01",
    period_end="2026-12-31",
    source="Dukascopy Bank SA",
    source_checksum=artifact.metadata["checksum"],
)

print(f"✓ Dataset registered: {dataset_id}")

# Seal dataset
print(f"\n[Seal] Sealing dataset...")
seal_record = vault.seal_dataset(
    dataset_id=dataset_id,
    data_bytes=artifact.data_bytes,
    metadata=artifact.metadata,
)

print(f"✓ Dataset sealed")
print(f"  Seal checksum: {seal_record.seal_checksum[:16]}...")
print(f"  Sealed at: {seal_record.sealed_timestamp}")

# Verify seal is durable
print(f"\n[Verify] Verifying seal durability...")
verify_result = vault.verify_seal(dataset_id)
print(f"✓ Seal verified: {verify_result.is_valid}")

# Record in audit trail
print(f"\n[Audit] Recording acquisition completion...")
audit_trail = vault.get_audit_trail(dataset_id)
print(f"✓ Audit trail:")
print(f"  - Registered: {audit_trail[-2]['timestamp'] if len(audit_trail) > 1 else 'N/A'}")
print(f"  - Sealed: {audit_trail[-1]['timestamp']}")
```

### 5. Report Results

```python
print(f"\n" + "=" * 70)
print(f"HOLDOUT ACQUISITION COMPLETE")
print(f"=" * 70)

print(f"\nAcquisition Summary:")
print(f"  Source: Dukascopy Bank SA (via MCP server)")
print(f"  Instrument: {artifact.metadata['instrument']}")
print(f"  Timeframe: {artifact.metadata['timeframe']}")
print(f"  Period: {artifact.metadata['start_date']} to {artifact.metadata['end_date']}")
print(f"  Rows: {artifact.metadata['actual_rows']}")
print(f"  Timezone: {artifact.metadata['timezone']}")
print(f"  Synthetic: {artifact.metadata['synthetic']}")

print(f"\nValidation Results:")
print(f"  Provenance: ✓ VERIFIED (actual_origin_evidence)")
print(f"  Integrity: ✓ VALID (OHLC consistency, monotonicity)")
print(f"  Independence: ✓ VERIFIED (no research exposure)")
print(f"  Eligibility: ✓ ELIGIBLE (all gates passed)")

print(f"\nSeal Information:")
print(f"  Dataset ID: {dataset_id}")
print(f"  Seal status: SEALED")
print(f"  File checksum: {artifact.metadata['checksum']}")
print(f"  Seal checksum: {seal_record.seal_checksum}")
print(f"  Sealed timestamp: {seal_record.sealed_timestamp}")

print(f"\nNext Steps:")
print(f"  1. Document seal in ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md")
print(f"  2. Authorization: vault.authorize_evaluation(...)")
print(f"  3. Start Generation 7 research")
print(f"  4. Consumption tracking via vault.consume_dataset(...)")

print(f"\n" + "=" * 70)
```

---

## Complete Integration Script

```python
#!/usr/bin/env python3
"""
Complete script to fetch, validate, and seal Dukascopy primary holdout.

Usage:
  python acquire_and_seal_holdout.py --start 2022-01-01 --end 2026-12-31
"""

import sys
import argparse
from mcp import Client
from core.factory.holdout_acquisition import (
    CandidateArtifact,
    evaluate_source_candidate,
    validate_artifact_integrity,
    check_independence,
    decide_primary_holdout_eligibility,
)
from core.factory.evidence_vault import EvidenceVault


def main():
    parser = argparse.ArgumentParser(description="Acquire and seal primary holdout")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--vault", default="reports/factory/evidence_vault.json", help="Vault file path")
    args = parser.parse_args()

    print(f"Acquiring primary holdout: {args.start} to {args.end}")

    # 1. Fetch via MCP
    print(f"\n[1/5] Fetching via MCP...")
    client = Client("dukascopy")
    result = client.call_tool("fetch_eurusd_h1", {
        "start_date": args.start,
        "end_date": args.end
    })

    if result["status"] != "success":
        print(f"❌ Fetch failed: {result['message']}")
        return 1

    artifact = CandidateArtifact(
        data_bytes=result["csv_data"].encode("utf-8"),
        metadata=result["metadata"]
    )
    print(f"✓ Fetched {len(artifact.rows)} bars")

    # 2. Validate provenance
    print(f"\n[2/5] Validating provenance...")
    source_eval = evaluate_source_candidate(artifact.metadata)
    if source_eval.provenance_status != "VERIFIED":
        print(f"❌ Provenance failed: {source_eval.identity_status}")
        return 1
    print(f"✓ Provenance verified")

    # 3. Validate integrity
    print(f"\n[3/5] Validating integrity...")
    integrity = validate_artifact_integrity(artifact)
    if not integrity.is_valid:
        print(f"❌ Integrity failed: {integrity.violations}")
        return 1
    print(f"✓ Integrity valid")

    # 4. Check independence
    print(f"\n[4/5] Checking independence...")
    independence = check_independence(artifact.metadata)
    if independence.research_exposure != "ZERO":
        print(f"❌ Independence failed: {independence.research_exposure}")
        return 1
    print(f"✓ Independence verified")

    # 5. Seal
    print(f"\n[5/5] Sealing holdout...")
    vault = EvidenceVault(vault_path=args.vault)
    
    dataset_id = vault.register_dataset_unsealed(
        dataset_name="ML-001-PRIMARY-HOLDOUT",
        instrument="EURUSD",
        timeframe="H1",
        period_start=args.start,
        period_end=args.end,
        source="Dukascopy Bank SA",
        source_checksum=artifact.metadata["checksum"],
    )

    seal_record = vault.seal_dataset(
        dataset_id=dataset_id,
        data_bytes=artifact.data_bytes,
        metadata=artifact.metadata,
    )

    print(f"✓ Holdout sealed: {dataset_id}")

    # Summary
    print(f"\n" + "=" * 70)
    print(f"ACQUISITION COMPLETE")
    print(f"  Dataset ID: {dataset_id}")
    print(f"  Rows: {len(artifact.rows)}")
    print(f"  Checksum: {artifact.metadata['checksum']}")
    print(f"  Seal: {seal_record.seal_checksum[:16]}...")
    print(f"=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## Error Handling

```python
# Graceful error handling for each gate:

try:
    artifact = CandidateArtifact(data_bytes, metadata)
except ValueError as e:
    print(f"❌ Failed to parse CSV: {e}")
    exit(1)

try:
    source_eval = evaluate_source_candidate(metadata)
    if source_eval.provenance_status != "VERIFIED":
        raise ValueError(f"Provenance: {source_eval.identity_status}")
except Exception as e:
    print(f"❌ Provenance gate failed: {e}")
    exit(1)

try:
    integrity = validate_artifact_integrity(artifact)
    if not integrity.is_valid:
        raise ValueError(f"Integrity: {integrity.violations}")
except Exception as e:
    print(f"❌ Integrity gate failed: {e}")
    exit(1)

try:
    independence = check_independence(metadata)
    if independence.research_exposure != "ZERO":
        raise ValueError(f"Independence: {independence.research_exposure}")
except Exception as e:
    print(f"❌ Independence gate failed: {e}")
    exit(1)

try:
    eligibility = decide_primary_holdout_eligibility(artifact)
    if eligibility.status != "ELIGIBLE":
        raise ValueError(f"Eligibility: {eligibility.rejection_reason}")
except Exception as e:
    print(f"❌ Eligibility gate failed: {e}")
    exit(1)

# Only then seal
vault.seal_dataset(...)
```

---

## Checksum Verification

After sealing, verify checksums are consistent:

```python
# Verify file checksum (CSV bytes)
import hashlib

file_checksum_computed = hashlib.sha256(artifact.data_bytes).hexdigest()
file_checksum_declared = artifact.metadata["checksum"].replace("sha256:", "")

assert file_checksum_computed == file_checksum_declared, "Checksum mismatch!"

# Verify seal checksum (data + metadata + schema version)
seal_checksum_computed = vault.verify_seal(dataset_id).seal_checksum
seal_checksum_stored = seal_record.seal_checksum

assert seal_checksum_computed == seal_checksum_stored, "Seal corrupted!"

print("✓ All checksums verified")
```

---

## Testing the Integration

Before running on production data, test with a small date range:

```python
# Test with 1 week of data
result = fetch_from_mcp_dukascopy("2024-08-12", "2024-08-16")

# Should return ~120 bars (5 trading days × 24 hours)
assert result["metadata"]["actual_rows"] > 100

# Run through all gates
artifact = CandidateArtifact(...)
evaluate_source_candidate(...)
validate_artifact_integrity(...)
check_independence(...)
decide_primary_holdout_eligibility(...)

# If all pass, ready for production
print("✓ Integration test passed")
```

---

## Next Steps

1. **Set up MCP server** on personal machine (see SETUP.md)
2. **Run test script** to verify data format and checksums
3. **Configure Claude Code** to connect to MCP server
4. **Run this integration** with full 2022-2026 date range
5. **Verify seal** is durable and audit trail is complete
6. **Document results** in ML-001-PRIMARY-HOLDOUT-SEAL-RECORD.md
7. **Start Generation 7** with sealed holdout

---

## Questions?

- **MCP setup**: See SETUP.md in mcp_server_dukascopy/
- **Validation logic**: See core/factory/holdout_acquisition.py
- **Sealing mechanism**: See core/factory/evidence_vault.py
- **Governance**: See ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md
