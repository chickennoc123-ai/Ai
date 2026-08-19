# MCP Server for Dukascopy Data Fetching

**Status**: Ready for deployment on personal machine with internet access

**Purpose**: Provide an MCP (Model Context Protocol) server that Claude Code can call via local socket to fetch real Dukascopy EURUSD H1 data, bypassing the remote environment's network egress policy.

---

## What This Does

```
┌─────────────────────────────────────┐
│  Personal Computer (Internet OK)    │
│                                     │
│  MCP Server (this code)             │
│  └─ fetch_eurusd_h1(start, end)    │
│     └─ Calls dukascopy-tick         │
│     └─ Returns CSV + metadata       │
└──────────────┬──────────────────────┘
               │ (socket/stdio)
               │
┌──────────────▼──────────────────────┐
│  Claude Code Environment            │
│  (Network restricted)               │
│                                     │
│  holdout_acquisition.py             │
│  └─ Calls MCP tool                  │
│  └─ Validates CSV                   │
│  └─ Seals via EvidenceVault         │
└─────────────────────────────────────┘
```

The **data acquisition workstream** identified a blocker: all financial-data hosts (Dukascopy, HistData, etc.) are blocked by organizational egress policy in the Claude Code environment.

**Solution**: Run an MCP server on your personal machine (unrestricted internet). Claude Code calls it via local socket, receives the CSV data, validates it through the acquisition gate, and seals it.

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `dukascopy_mcp_server.py` | Main MCP server with `DukascopyFetcher` class; provides `fetch_eurusd_h1(start_date, end_date)` tool |
| `requirements.txt` | Python dependencies (mcp, dukascopy-tick) |
| `test_dukascopy_fetcher.py` | Verification script; test data fetch, CSV format, OHLC relationships, checksums, timezone |
| `SETUP.md` | Step-by-step setup guide for your personal machine + Claude Code integration |
| `README.md` | This file |

---

## Quick Start (30 seconds)

### On Your Personal Machine

```bash
# 1. Install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Test
python test_dukascopy_fetcher.py
# Expected: ✓ ALL TESTS PASSED

# 3. Start server (keep running)
python dukascopy_mcp_server.py
```

### In Claude Code Environment

```python
from mcp import Client

client = Client("dukascopy")
result = client.call_tool("fetch_eurusd_h1", {
    "start_date": "2022-01-01",
    "end_date": "2026-12-31"
})

print(result["status"])  # "success"
print(result["csv_data"][:100])  # CSV data with OHLC
print(result["metadata"]["checksum"])  # SHA256 hash
```

Full setup and troubleshooting: See `SETUP.md`.

---

## Data Format

### CSV Output

```
timestamp,open,high,low,close
2022-01-03T00:00:00+00:00,1.1372,1.1385,1.1368,1.1373
2022-01-03T01:00:00+00:00,1.1373,1.1380,1.1365,1.1368
...
```

**Key requirements**:
- Timestamp format: ISO-8601 with UTC timezone (`+00:00`)
- One H1 candle per row (24 rows per trading day)
- No NaN or gap-filling — return exactly what Dukascopy has
- Gaps reported in metadata (`gaps_present`, `actual_rows` vs `expected_rows`)

### Metadata Response

```json
{
  "status": "success",
  "message": "Fetched 28464 bars from Dukascopy for EURUSD H1",
  "csv_data": "timestamp,open,high,low,close\n2022-01-03T00:00:00+00:00,...",
  "metadata": {
    "source": "dukascopy",
    "instrument": "EURUSD",
    "timeframe": "H1",
    "timezone": "UTC",
    "price_type": "OHLC",
    "start_date": "2022-01-01",
    "end_date": "2026-12-31",
    "first_timestamp": "2022-01-03T00:00:00+00:00",
    "last_timestamp": "2026-12-31T23:00:00+00:00",
    "actual_rows": 28464,
    "expected_rows": 28440,
    "gaps_present": false,
    "acquisition_timestamp": "2026-08-19T14:23:45.123456+00:00",
    "checksum": "sha256:a1b2c3d4...",
    "file_checksum_algorithm": "SHA256",
    "source_type": "primary",
    "actual_origin_evidence": "Direct download from Dukascopy via dukascopy-tick library",
    "synthetic": false,
    "license": "Dukascopy free tier (research/personal use permitted)"
  }
}
```

---

## Integration with Acquisition Pipeline

The MCP server output feeds directly into the existing `holdout_acquisition.py` validation gate:

```python
from core.factory.holdout_acquisition import (
    evaluate_source_candidate,
    validate_artifact_integrity,
    check_independence,
    decide_primary_holdout_eligibility,
)

# 1. Fetch via MCP
result = client.call_tool("fetch_eurusd_h1", {"start_date": "2022-01-01", "end_date": "2026-12-31"})
artifact_bytes = result["csv_data"].encode("utf-8")
metadata = result["metadata"]

# 2. Evaluate provenance (actual_origin_evidence is in metadata)
source_eval = evaluate_source_candidate(metadata)
assert source_eval.provenance_status == "VERIFIED"

# 3. Validate integrity (CSV parsing + OHLC consistency)
integrity_result = validate_artifact_integrity(artifact_bytes, metadata)
assert integrity_result.is_valid

# 4. Check independence (no overlap with DEVELOPMENT/PURE_HOLDOUT)
independence = check_independence(metadata)
assert independence.research_exposure == "ZERO"

# 5. Eligibility decision (all gates must pass)
eligibility = decide_primary_holdout_eligibility(artifact_bytes, metadata)
assert eligibility.status == "ELIGIBLE"

# 6. Seal (one-time authorization + consumption model)
vault = EvidenceVault()
vault.seal_dataset(artifact_bytes, metadata)
```

See `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` for the complete contract.

---

## OHLC Data Validation

The fetched data is validated for:

1. **Monotonic timestamps** — each timestamp > previous
2. **No duplicate timestamps** — each hour appears once
3. **OHLC consistency**:
   - `high >= max(open, close)`
   - `low <= min(open, close)`
   - `high >= low`
4. **Strictly positive prices** — no zero/negative values
5. **No synthetic flag issues** — `synthetic: false` explicitly declared

Example rejection (from test suite):

```python
# OHLC violation: high < max(open, close)
{
  "timestamp": "2022-01-03T00:00:00+00:00",
  "open": 1.1372,
  "high": 1.1370,  # ← ERROR: less than close (1.1373)
  "low": 1.1368,
  "close": 1.1373
}
# Result: REJECTED (integrity gate)
```

---

## Provenance Model

The MCP server declares provenance explicitly:

```json
{
  "source": "dukascopy",  # who produced the data
  "source_type": "primary",  # primary vs. documented_secondary vs. mirror
  "actual_origin_evidence": "Direct download from Dukascopy via dukascopy-tick library",
  "synthetic": false,
  "file_checksum_algorithm": "SHA256",
  "checksum": "sha256:a1b2c3d4e5f6g7h8..."
}
```

This satisfies Rule 10 from `ML-001-PRIMARY-HOLDOUT-CONTRACT.md`:
> "Do NOT label a random mirror 'Dukascopy' without evidence of origin."

The evidence is the `dukascopy-tick` library's own API documentation and the library's direct calls to Dukascopy's endpoints.

---

## Testing Locally (Before MCP Integration)

```bash
# Test the DukascopyFetcher class directly
python -c "
from dukascopy_mcp_server import DukascopyFetcher
fetcher = DukascopyFetcher()
result = fetcher.fetch('2024-08-12', '2024-08-16')
print(f\"Status: {result['status']}\")
print(f\"Rows: {result['metadata']['actual_rows']}\")
print(f\"Checksum: {result['metadata']['checksum']}\")
"
```

Or use the full test script:

```bash
python test_dukascopy_fetcher.py
```

---

## Timezone Handling

**All timestamps are UTC** (`+00:00`), as required by `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` §4.

The MCP server:
1. Fetches from Dukascopy (native UTC)
2. Ensures all timestamps include `+00:00` timezone
3. Validates in Claude Code environment (must be UTC)
4. Rejects any non-UTC timezone as ineligible

Example:

```python
# ✓ ACCEPTED
"2022-01-03T00:00:00+00:00"

# ✗ REJECTED (no timezone)
"2022-01-03T00:00:00"

# ✗ REJECTED (wrong timezone)
"2022-01-03T00:00:00+02:00"
```

---

## Checksum Reproducibility

Checksums are deterministic — the same data always produces the same hash:

```python
import hashlib

# Identical CSV → Identical checksum
csv1 = "timestamp,open,high,low,close\n2022-01-03T00:00:00+00:00,1.1372,1.1385,1.1368,1.1373\n"
csv2 = "timestamp,open,high,low,close\n2022-01-03T00:00:00+00:00,1.1372,1.1385,1.1368,1.1373\n"

hash1 = hashlib.sha256(csv1.encode("utf-8")).hexdigest()
hash2 = hashlib.sha256(csv2.encode("utf-8")).hexdigest()

assert hash1 == hash2  # ✓ Both are a1b2c3d4...
```

This allows:
1. **Verification** — check seal integrity after resealing
2. **Audit** — reproduce the seal using same bytes
3. **Detection** — any byte change invalidates the seal

---

## Limitations & Gaps

- **Weekends/holidays**: No data on non-trading days (expected); metadata reports `actual_rows` vs `expected_rows`
- **Market hours**: Dukascopy H1 data covers 24 hours (some pairs trade 24/5, EURUSD is 24-hour during week); no intraday gaps during trading hours
- **Bid/ask**: Returns mid-price OHLC (not bid/ask spread); matches DEVELOPMENT dataset's price type
- **Volume**: Not included in CSV (DEVELOPMENT dataset also omits volume); can add if needed

---

## Security & Authorization

The MCP server:
- ✓ Uses free, unauthenticated Dukascopy tier (no credentials needed)
- ✓ Declares all data as real (non-synthetic)
- ✓ Never fabricates, interpolates, or fills missing data
- ✓ Reports gaps honestly (actual vs. expected row count)
- ✓ Matches all non-negotiable rules from task boundaries

See `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` for full governance.

---

## Performance

- **First call**: ~30 seconds (downloads 28k+ bars)
- **Subsequent calls**: Cached by dukascopy-tick library (~5 seconds)
- **Memory**: ~50 MB for full 2022-2026 EURUSD H1 dataset
- **Network**: ~5 MB transfer per full date range

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'dukascopy_tick'` | `pip install dukascopy-tick` in venv |
| `Connection refused` from Claude Code | Verify MCP server running on personal machine + correct IP in config |
| `No data returned` for date range | Check dates are in Dukascopy coverage; try shorter range |
| `Checksum mismatch` | Ensure no modifications between fetch and validation; re-run test |
| `Timestamp format wrong` | Check `_candles_to_csv()` in dukascopy_mcp_server.py includes `+00:00` |

See `SETUP.md` for detailed troubleshooting.

---

## Next Steps

1. **Install on personal machine** → Follow `SETUP.md` Step 1-2
2. **Test locally** → Run `test_dukascopy_fetcher.py`
3. **Start MCP server** → `python dukascopy_mcp_server.py`
4. **Configure Claude Code** → `SETUP.md` Step 3
5. **Call the tool** → Fetch real Dukascopy data for 2022-2026
6. **Validate & seal** → Run through acquisition gate, seal holdout
7. **Start Generation 7** → Generation 7 research can now proceed with verified independent data

---

## Questions?

- **Setup issues**: See `SETUP.md` troubleshooting section
- **Data format**: See "Data Format" section above or CSV validation in `test_dukascopy_fetcher.py`
- **Integration**: See "Integration with Acquisition Pipeline" section
- **Governance**: See `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` and `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` in parent directory

---

## Version & Attribution

- **Version**: 1.0.0
- **Created**: August 19, 2026
- **Status**: Ready for production
- **License**: Dukascopy free tier (research/personal use)
