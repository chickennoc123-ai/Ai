# ML-001 Primary Holdout Acquisition — Blocker Report

**Date**: August 19, 2026
**Status**: `DATA_ACQUISITION_STATUS = BLOCKED`

This document is the honest record required when acquisition is
impossible: what was attempted, what was tested, what failed, what
remains possible, and whether a user-provided artifact could unblock it.
Per the governing task's Rule 18, this is a valid terminal state, not a
failure to be hidden or routed around.

---

## Attempted Sources (Phase 2 Ordering)

### A. Existing local artifacts

Searched the entire repository and filesystem (excluding `/proc`) for any
file matching Dukascopy/HistData naming, any `EURUSD` file referencing
2022/2023/2024/2025/2026, and any `.bi5`/`.hst` (Dukascopy/MT4 native
formats). **None found.** The only EURUSD data present is
`data/csv/EURUSD_H1.csv`, covering 2012-11-16 to 2022-03-05 — the existing
DEVELOPMENT dataset, not eligible to serve as its own holdout.

| source_id | status |
|---|---|
| LOCAL-REPO-SEARCH | NOT_FOUND |

### B. Existing mounted/user-provided files

Checked `/mnt/attach` and `/mnt/user-data` (the supported mechanisms for
files a user may have provided to this session). Both are empty.

| source_id | status |
|---|---|
| MNT-ATTACH | NOT_FOUND |
| MNT-USER-DATA | NOT_FOUND |

### C. Existing repository artifacts

`reports/factory/`, `data/csv/`, and the full repository tree were
inspected. No Evidence Vault persistence file exists yet
(`reports/factory/evidence_vault.json` is absent — correct, since nothing
has been sealed). No acquisition-utility script pre-existed before this
task (`core/factory/holdout_acquisition.py` was written in this task).

### D/E. Legitimate publicly accessible endpoints / mirrors

Tested via two independent channels — direct `curl` through this
session's egress proxy, and the first-party `WebFetch` tool (routed
through Anthropic's own fetch infrastructure) — to rule out a
client-specific problem rather than a genuine policy block.

| source_id | source_name | url | access_status | network_status | result |
|---|---|---|---|---|---|
| SRC-DUKASCOPY-WEB | Dukascopy historical export page | `https://www.dukascopy.com/swiss/english/marketwatch/historical/` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) + `EGRESS_BLOCKED` (WebFetch) | BLOCKED |
| SRC-DUKASCOPY-DATAFEED | Dukascopy raw datafeed endpoint | `https://datafeed.dukascopy.com/datafeed/EURUSD/...` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-DUKASCOPY-FREESERV | Dukascopy freeserv endpoint | `https://freeserv.dukascopy.com` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-HISTDATA-WEB | HistData main site | `https://www.histdata.com` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) + `EGRESS_BLOCKED` (WebFetch) | BLOCKED |
| SRC-HISTDATA-DOWNLOAD | HistData download subdomain | `https://download.histdata.com` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-EXCHANGERATE-HOST | api.exchangerate.host (generic FX API, considered as a possible alternate) | `https://api.exchangerate.host` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-ALPHAVANTAGE | Alpha Vantage (generic FX/equity API, considered as a possible alternate) | `https://www.alphavantage.co` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-YAHOO-FINANCE | Yahoo Finance query API (already ruled ineligible on other grounds in the prior OGD-4 audit; re-tested for network status only) | `https://query1.finance.yahoo.com` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-STOOQ | Stooq (generic historical-data API, considered as a possible alternate) | `https://stooq.com` | ACCESS_FAILED | HTTP 403 (curl, proxy policy denial) | BLOCKED |
| SRC-GITHUB-RAW | `raw.githubusercontent.com` (the one host reachable in this environment) | n/a | AVAILABLE | HTTP 301 | REACHABLE, see §F |

### F. Legitimate downloadable mirrors

`raw.githubusercontent.com` is the one financial-data-adjacent host proven
reachable in this session (confirmed via both `curl` and `WebFetch`,
matching the channel already used to acquire the existing DEVELOPMENT
dataset from the `komo135/forex-historical-data` GitHub repository). This
was investigated as a possible path, with appropriate skepticism about
what reachability actually proves.

**Checked**: whether the same GitHub repository already used for
DEVELOPMENT data (source_id `SRC-KOMO135-FOREX-HISTORICAL-DATA` in
`data/csv/PROVENANCE_MANIFEST.json`) happens to extend into 2022-2026.

```
$ curl -s ".../komo135/forex-historical-data/main/EURUSD/EURUSDh1.csv" | tail -5
2022-03-04 19:00:00, ...
2022-03-04 20:00:00, ...
2022-03-04 21:00:00, ...
2022-03-04 22:00:00, ...
2022-03-04 23:00:00, ...
```

**Result**: this repository's data ends 2022-03-04/05 — identical to the
already-cataloged DEVELOPMENT dataset's coverage. It does **not** extend
into the approved 2022-2026 period.

`api.github.com` (needed to browse the repository for other files,
branches, or related repositories) itself returns `HTTP 403` under this
session's egress policy — so even a broader search of what else exists
under that GitHub account is not possible from here.

**Even if a GitHub-hosted CSV claiming EURUSD 2022-2026 coverage were
found**, it would be a MIRROR_LOCATION, not a verified SOURCE_IDENTITY
(see `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md` §2-3). Per Rule 10 of
the governing task ("DO NOT label a random mirror 'Dukascopy' without
evidence"), any such file would require independently corroborated
provenance evidence before `provenance_status` could become `VERIFIED` —
evidence this environment currently has no way to obtain, since the very
channel that would let us cross-check against Dukascopy's own published
data (Dukascopy itself) is the thing that is blocked. This is recorded as
a structural limitation, not resolved by lowering the evidence bar.

| source_id | source_name | source_type | provenance_status | eligibility_status |
|---|---|---|---|---|
| SRC-KOMO135-EXTENDED-CHECK | komo135/forex-historical-data (existing DEVELOPMENT source, checked for extended coverage) | documented_secondary | N/A — does not contain the required period | NOT_FOUND (period absent) |

### Root Cause (Confirmed, Not Assumed)

The egress proxy's own status endpoint confirms this is a **policy
decision**, not a transient failure or Dukascopy/HistData-side outage:

```
$ curl -sS http://127.0.0.1:41263/__agentproxy/status
"recentRelayFailures": [
  {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "www.dukascopy.com:443"},
  {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "datafeed.dukascopy.com:443"},
  {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "freeserv.dukascopy.com:443"},
  {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "www.histdata.com:443"},
  ... (9 distinct financial-data hosts, all "policy denial")
]
```

The proxy's own documentation (`/root/.ccr/README.md`) is explicit:

> "403 / 407 from the proxy: The destination host is not allowed by your
> organization's egress policy for this session. **Do not retry or route
> around it — report the blocked host.**"

This governs the response here: the block is reported, not circumvented.

---

## What Was Actually Tested

- 9 distinct financial-data hosts, via 2 independent access channels
  (proxy-routed `curl`, first-party `WebFetch`) — all returned explicit
  policy-denial responses, not timeouts or ambiguous failures.
- The one already-known, already-used GitHub mirror for this exact
  instrument — confirmed to lack the required period.
- Local filesystem, `/mnt/attach`, `/mnt/user-data` — confirmed empty of
  any relevant artifact.
- `api.github.com` (for a broader mirror search) — also blocked.

## What Was Unavailable

Every direct or indirect path to Dukascopy or HistData bytes. No
Dukascopy/HistData-sourced EURUSD 2022-2026 file exists anywhere
reachable from this environment.

## What Remains Possible

1. **Owner-provided artifact** (see `ML-001-PRIMARY-HOLDOUT-ACQUISITION-SPEC.md`,
   "User-Provided Data Path" section, and Phase 10 below) — the most
   direct unblock. The interface is fully specified and the same
   provenance/integrity/independence gate (`core/factory/holdout_acquisition.py`)
   applies to it as to any automated download.
2. **A change to this environment's egress policy** to permit reaching
   Dukascopy and/or HistData directly — outside this task's authority to
   request or perform.
3. **A different, already-reachable source that can independently satisfy
   the approved governance identity** (same instrument, timeframe, period,
   with genuine — not filename-based — Dukascopy or HistData provenance) —
   none was found in this session; a future session with different
   network policy or a different mirror search might find one, but it
   would still require the same provenance bar, and would still require
   fresh governance sign-off if it is not literally Dukascopy or HistData
   (per `ML-001-PRIMARY-HOLDOUT-CONTRACT.md` §16).

## Whether HistData Independently Qualifies as an Alternative

Per the governing task's Phase 9 instruction, HistData is recorded
separately here as `ALTERNATIVE_HOLDOUT_CANDIDATE` status — not silently
substituted for Dukascopy, and not sealed automatically:

```
ALTERNATIVE_HOLDOUT_CANDIDATE = HistData EURUSD H1 2022-2026
STATUS                        = ACCESS_FAILED (same blocker as Dukascopy)
GOVERNANCE_NOTE                = Already discussed in
                                 ML-001-OGD4-CANDIDATE-EVALUATION.md as a
                                 functionally-equivalent audit outcome to
                                 Dukascopy (both same-market, temporally
                                 independent). Substitution, if it ever
                                 becomes viable, would still require
                                 explicit owner authorization per
                                 ML-001-PRIMARY-HOLDOUT-CONTRACT.md §16,
                                 since the governance closure named
                                 Dukascopy specifically.
```

HistData is equally blocked in this session, so this is currently moot —
recorded for completeness, not as a live option.

---

## Disposition

```
DATA_ACQUISITION_STATUS       = BLOCKED
TOTAL_SOURCES_ATTEMPTED       = 11 (9 financial-data hosts + 1 GitHub mirror check + 1 GitHub API check)
TOTAL_SOURCES_ACCESS_FAILED   = 10 (all financial-data hosts + api.github.com)
TOTAL_SOURCES_NOT_FOUND       = 1 (GitHub mirror reachable but lacks the required period)
TOTAL_SOURCES_ELIGIBLE        = 0
SEAL_STATUS                   = NOT_SEALED
```

No source was fabricated, no mirror was labeled "Dukascopy" without
evidence, and no egress restriction was bypassed or scraped around.
