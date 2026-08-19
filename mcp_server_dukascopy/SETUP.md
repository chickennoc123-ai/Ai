# MCP Server for Dukascopy Data Fetching — Setup Guide

**Purpose**: Run a local MCP server on your personal computer (with unrestricted internet) to fetch Dukascopy EURUSD H1 data. Claude Code connects to this server via local socket, bypassing the environment's egress policy.

**Architecture**:
```
Your Computer (Internet Access)
  └─ MCP Server (dukascopy_mcp_server.py)
      └─ Listens on local socket
      └─ Provides fetch_eurusd_h1(start_date, end_date) tool
      └─ Returns OHLC CSV + metadata

Claude Code Remote Environment (Blocked Internet)
  └─ Calls MCP Server via local socket
  └─ Receives CSV data
  └─ Validates through holdout_acquisition.py
  └─ Seals via EvidenceVault
```

---

## Step 1: Install MCP Server on Your Personal Computer

### 1.1 Prerequisites

- Python 3.9+ installed on your personal machine
- pip package manager
- Git (to clone or sync this repository)
- Internet access (unrestricted access to Dukascopy)

### 1.2 Create Virtual Environment

```bash
# Create a dedicated virtual environment
python3 -m venv ~/dukascopy_mcp_venv

# Activate it
source ~/dukascopy_mcp_venv/bin/activate  # On Windows: ~/dukascopy_mcp_venv\Scripts\activate
```

### 1.3 Install Dependencies

```bash
# Copy requirements.txt to your machine if not already there
# Then install:
pip install -r requirements.txt

# Verify installation
python -c "import dukascopy_tick; import mcp; print('✓ Dependencies installed')"
```

### 1.4 Test Local Fetcher

Before starting the MCP server, verify dukascopy-tick works:

```bash
# Run the test script (adjust dates to current trading week)
python test_dukascopy_fetcher.py

# Expected output:
# ✓ Status: success
# ✓ Header is correct
# ✓ Timezone: UTC
# ✓ OHLC relationships valid
# ✓ Checksum matches
# ✓ Timestamps are monotonically increasing
# ✓ ALL TESTS PASSED
```

If the test fails:
- Check that dukascopy-tick is installed: `pip install dukascopy-tick --upgrade`
- Verify your internet can reach Dukascopy: `curl -I https://www.dukascopy.com`
- Check the error message for missing dependencies

---

## Step 2: Start the MCP Server

### 2.1 Run the Server

```bash
# Activate your virtual environment (if not already)
source ~/dukascopy_mcp_venv/bin/activate

# Start the MCP server (it listens on stdio by default)
python dukascopy_mcp_server.py
```

**Expected output**: Server starts silently and listens on stdin/stdout. Do NOT close this terminal.

### 2.2 Verify Server is Running

Open a new terminal (keep the server running):

```bash
# Test connectivity via MCP protocol (requires mcp client installed)
# or use the test script in Claude Code environment

# For now, just verify no errors in the server terminal
```

Keep this terminal/process running throughout your work.

---

## Step 3: Configure Claude Code to Connect to MCP Server

### 3.1 Get Your Personal Computer's IP/Port

```bash
# On your personal machine, note the IP address
ifconfig | grep "inet " | grep -v 127.0.0.1  # On Mac/Linux
ipconfig                                        # On Windows, look for IPv4 Address
```

Example: `192.168.1.100` (adjust for your network)

**Port**: Default MCP servers use stdio transport (no explicit port). For local socket transport, typically port `9000` or similar. Check your MCP SDK docs.

### 3.2 Claude Code Configuration

In Claude Code environment, create or edit `.claude/claude_settings.json`:

```json
{
  "mcp": {
    "servers": {
      "dukascopy": {
        "command": "python",
        "args": ["-m", "mcp.server"],
        "env": {
          "MCP_SERVER_HOST": "192.168.1.100",
          "MCP_SERVER_PORT": "9000"
        }
      }
    }
  }
}
```

**IMPORTANT**: Replace `192.168.1.100` with your personal computer's actual IP address.

Alternatively, if your MCP server uses stdio transport, you may need:

```json
{
  "mcp": {
    "servers": {
      "dukascopy": {
        "command": "ssh",
        "args": ["user@192.168.1.100", "cd ~/path/to/mcp_server_dukascopy && python dukascopy_mcp_server.py"]
      }
    }
  }
}
```

This assumes SSH access from Claude Code environment to your machine (may not be available).

### 3.3 Alternative: Use Claude Code Web App

In the Claude Code web app (claude.ai/code):
1. Open Settings
2. Navigate to "MCP Servers"
3. Click "Add Server"
4. Name: `dukascopy`
5. Command: `python ~/dukascopy_mcp_venv/bin/python -m mcp.server`
6. Environment variables:
   - `MCP_SERVER_HOST=192.168.1.100`
   - `MCP_SERVER_PORT=9000`

---

## Step 4: Test MCP Server from Claude Code

### 4.1 Call the Tool

In Claude Code environment, call the tool:

```python
from mcp import Client

client = Client("dukascopy")
result = client.call_tool("fetch_eurusd_h1", {
    "start_date": "2024-08-12",
    "end_date": "2024-08-16"
})

print(result)
# Expected: {"status": "success", "csv_data": "...", "metadata": {...}}
```

### 4.2 Verify CSV Format

```python
import json

csv_data = result["csv_data"]
lines = csv_data.split("\n")

print(f"Header: {lines[0]}")
# Expected: timestamp,open,high,low,close

print(f"First row: {lines[1]}")
# Expected: 2024-08-12T00:00:00+00:00,1.0847,1.0851,1.0843,1.0849
```

### 4.3 Verify Metadata

```python
metadata = result["metadata"]

print(f"Source: {metadata['source']}")  # Expected: "dukascopy"
print(f"Instrument: {metadata['instrument']}")  # Expected: "EURUSD"
print(f"Timezone: {metadata['timezone']}")  # Expected: "UTC"
print(f"Synthetic: {metadata['synthetic']}")  # Expected: False
print(f"Checksum: {metadata['checksum']}")  # Expected: "sha256:..."
```

---

## Step 5: Integrate with Holdout Acquisition Pipeline

### 5.1 Use MCP Tool in Acquisition Code

In `core/factory/holdout_acquisition.py`, modify the acquisition function:

```python
from mcp import Client

def acquire_from_mcp_dukascopy(start_date: str, end_date: str) -> CandidateArtifact:
    """Fetch data via MCP server on personal machine."""
    client = Client("dukascopy")
    result = client.call_tool("fetch_eurusd_h1", {
        "start_date": start_date,
        "end_date": end_date
    })
    
    if result["status"] != "success":
        return None
    
    csv_data = result["csv_data"]
    metadata = result["metadata"]
    
    # Parse CSV into CandidateArtifact
    artifact = CandidateArtifact(
        data_bytes=csv_data.encode("utf-8"),
        metadata=metadata,
        # ... remaining fields
    )
    
    return artifact
```

### 5.2 Run Acquisition Through Pipeline

```python
# Fetch via MCP
artifact = acquire_from_mcp_dukascopy("2022-01-01", "2026-12-31")

# Validate
result = evaluate_source_candidate(artifact.metadata)
if result.provenance_status != "VERIFIED":
    print(f"❌ Provenance failed: {result.provenance_status}")
    return

# Integrity check
integrity = validate_artifact_integrity(artifact)
if not integrity.is_valid:
    print(f"❌ Integrity failed: {integrity.violations}")
    return

# Independence check
independence = check_independence(artifact.metadata)
if independence.research_exposure != "ZERO":
    print(f"❌ Independence failed: {independence.research_exposure}")
    return

# Eligibility decision
eligibility = decide_primary_holdout_eligibility(artifact)
if eligibility.status != "ELIGIBLE":
    print(f"❌ Ineligible: {eligibility.rejection_reason}")
    return

# Seal
vault = EvidenceVault()
vault.seal_dataset(artifact, "ML-001-PRIMARY-HOLDOUT")
print("✓ Holdout sealed successfully")
```

---

## Troubleshooting

### "Connection refused" error

- Verify MCP server is running on your personal machine
- Check firewall isn't blocking the connection
- Verify IP address is correct in Claude Code config
- Test local connectivity: `telnet 192.168.1.100 9000`

### "dukascopy-tick not installed"

```bash
# Reinstall in the correct virtual environment
source ~/dukascopy_mcp_venv/bin/activate
pip install dukascopy-tick --upgrade
```

### "No data returned"

- Check date range is within Dukascopy's coverage (H1 data available since ~2011)
- Verify dates are trading days (Mon-Fri)
- Check Dukascopy website isn't down: `curl -I https://www.dukascopy.com`
- Try a shorter date range: start with 1 week of data

### "Timestamp format incorrect"

- MCP server should return ISO-8601 with `+00:00` timezone
- If not, check the `_candles_to_csv()` method in `dukascopy_mcp_server.py`
- Verify dukascopy-tick version is recent: `pip show dukascopy-tick`

### "Checksum mismatch"

- Checksums must be reproducible (same data = same hash)
- Don't modify CSV between fetch and validation
- Verify no encoding issues (should be UTF-8)
- Re-run test_dukascopy_fetcher.py to isolate the issue

---

## Summary Checklist

- [ ] Python 3.9+ installed on personal machine
- [ ] Virtual environment created
- [ ] Dependencies installed (mcp, dukascopy-tick)
- [ ] test_dukascopy_fetcher.py passes
- [ ] MCP server running on personal machine
- [ ] Claude Code configured with MCP server IP/port
- [ ] Tool call test succeeds (CSV + metadata received)
- [ ] CSV format verified (header, timestamps, OHLC)
- [ ] Integration with holdout_acquisition.py complete
- [ ] Full pipeline tested (fetch → validate → seal)

---

## Next Steps

Once the MCP server is running and Claude Code can call it:

1. **Fetch real Dukascopy data**: `fetch_eurusd_h1("2022-01-01", "2026-12-31")`
2. **Run validation**: Check timestamp monotonicity, OHLC consistency, no gaps
3. **Verify independence**: No overlap with DEVELOPMENT (ends 2022-03-05) or PURE_HOLDOUT (2021-01-01 to 2021-12-31)
4. **Seal holdout**: `EvidenceVault.seal_dataset()` with full audit trail
5. **Generate reports**: Document seal, checksums, row counts, gaps

The acquisition workstream will then transition from `BLOCKED` to `SEALED`, and Generation 7 research can proceed.
