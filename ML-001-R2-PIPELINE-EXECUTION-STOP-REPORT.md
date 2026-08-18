# ML-001-R2 Economic-Validation Pipeline — Execution Attempt & Stop Report

**Date**: August 18, 2026
**Repository state**: commit `5c2d327`, branch `claude/ea-factory-pro-system-bc9jaa`, clean tree at start.
**Role**: execution lead for the full REAL DATA → ... → EVG → GOVERNANCE VERDICT pipeline.
**Outcome**: **STOPPED at Phase 1 (Real Market Data Acquisition).** Phases 2–12 were not attempted. This is not a re-statement of the prior audit's conclusion taken on faith — this report documents a fresh, active attempt to obtain real data in this specific session, with concrete evidence of exactly why it could not be obtained.

---

## PHASE 0 — REPOSITORY RECONNAISSANCE (execution map)

Confirmed present and reusable, matching `ML-001-R2-TRAINING-PROVENANCE.md`'s inventory (not re-derived from scratch — that document's Phase 2 forensics are re-affirmed, not re-litigated):

| Component | Location |
|---|---|
| Spec | `ML-001-R2-CLEAN-REBUILD-SPEC.md` |
| Feature pipeline | `core/features/fe_r2_001.py::build_feature_matrix` |
| Target construction | `core/ml_r2/target_r2.py::compute_label`, `build_training_set`, `assert_no_leakage` |
| Temporal split | `core/ml_r2/walkforward_r2.py::compute_temporal_split`, `TemporalSplit` |
| Holdout guard | `core/ml_r2/walkforward_r2.py::HoldoutAccessGuard` |
| Model | `core/ml_r2/model_r2.py::RFR2Model` (train/save/load, checksum-verified) |
| Provenance | `core/ml_r2/provenance_r2.py::RunProvenance`, `get_code_version` |
| Backtest/§10 mechanics | `core/ml_r2/backtest_r2.py::run_backtest`, `BacktestConfig` |
| OOS / walk-forward | `core/ml_r2/walkforward_r2.py::generate_oos_predictions`, `make_walk_forward_windows` |
| Robustness/statistics | `core/validation.py::ValidationSuite` (real, general-purpose engine — currently only ever pointed at the `RSI` strategy, never at ML-001-R2) |
| EVG | `core/evidence_aggregator.py::AggregatedEvidence`/`EvidenceAggregator`, `core/decision_engine.py::DecisionEngine` |
| **Data adapters — this session's new finding** | `core/data_manager.py::SimulatedProvider` (name=`"simulated"`, disclosed synthetic), `CSVProvider` (reads `data/csv/<SYMBOL>_<TIMEFRAME>.csv`), `AlphaVantageProvider` (real REST client, requires `api_key`) |
| **Broker/data connection — this session's new finding** | `broker/xm_connection.py::XMConnection` — `simulated` mode needs nothing real; `rest` mode explicitly documented in its own module docstring as requiring the *user's own* externally-hosted MT5 bridge service ("XM does not publish a public REST trading API; point `broker.xmtrading.rest_url` at your own MT5 bridge") — not something reachable from this repository or environment on its own |

Nothing above required reimplementation. No new orchestration code was written this session because execution never proceeded past data acquisition.

---

## PHASE 1 — REAL MARKET DATA ACQUISITION (actively attempted, not assumed blocked)

Per this task's explicit instruction — "Do not stop merely because the previous audit found that the prerequisites were missing... determine whether those prerequisites can be legitimately obtained" — every plausible legitimate path in this specific repository and environment was checked directly, not inferred from the prior report.

### 1a. Local data already present

```
$ find data/ -type f
data/ea_factory.db          # no raw OHLCV table (verified again this session)

$ find / -xdev -iname "*.csv" 2>/dev/null | grep -v "/proc/|dist-packages|site-packages|node_modules" \
    | grep -viE "ML-001-R2-(PINE-PARITY|GOLDEN)"
/usr/share/distro-info/ubuntu.csv       # OS package metadata, not market data
/usr/share/distro-info/debian.csv       # same
.../zip_sums.csv (x2)                   # Go toolchain test fixtures
```
No real OHLCV CSV exists anywhere on this filesystem, in `data/csv/` (the exact path `CSVProvider` reads from) or otherwise. **`CSVProvider`: no input available.**

### 1b. Configured credentials

```
$ ls -la .env
ls: cannot access '.env': No such file or directory

$ grep ALPHAVANTAGE_API_KEY .env.example
ALPHAVANTAGE_API_KEY=

$ grep -E "^XM_(ACCOUNT_ID|PASSWORD)" .env.example
XM_ACCOUNT_ID=
XM_PASSWORD=
```
No `.env` exists; the template's vendor-key fields are empty placeholders. **`AlphaVantageProvider`: `api_key` not configured. `XMConnection` (rest mode): no account credentials configured, and per its own docstring requires a self-hosted external bridge this repository does not include.**

### 1c. Network reachability to a legitimate public source (actively tested, not assumed)

Rather than stop at "no key configured," this session tested whether a legitimate public/free data endpoint could be reached at all — checking both the vendor already wired into the codebase (Alpha Vantage) and a well-known free public FX-history source (stooq.com), to see whether the *acquisition* blocker was credentials alone or something more fundamental:

```
$ curl -sS -m 10 -o /dev/null -w "HTTP_STATUS:%{http_code}\n" "https://stooq.com/q/d/l/?s=eurusd&i=60"
curl: (56) CONNECT tunnel failed, response 403
HTTP_STATUS:000

$ curl -sS -m 10 "https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol=EUR&to_symbol=USD&interval=60min&apikey=demo"
curl: (56) CONNECT tunnel failed, response 403
```

Both requests were rejected by this session's own outbound egress proxy, **before ever reaching either vendor** — confirmed directly from the proxy's own status/diagnostic endpoint, not inferred from the curl error alone:

```
$ curl -sS "$HTTPS_PROXY/__agentproxy/status"
{
  ...
  "recentRelayFailures": [
    {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "stooq.com:443"},
    {"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "www.alphavantage.co:443"}
  ]
}
```

This session's own environment documentation (`/root/.ccr/README.md`) is explicit: *"403 / 407 from the proxy: The destination host is not allowed by your organization's egress policy for this session. Do not retry or route around it — report the blocked host."* Two independent, differently-hosted, legitimate market-data endpoints were both rejected at the network-policy layer, not the vendor layer — this is not a "wrong API key" or "vendor down" failure, it is this session's outbound network policy declining to reach FX-data hosts at all. Per that same instruction, no further domains were attempted and no workaround (proxy bypass, TLS-verification disabling, alternate transport) was attempted — both explicitly forbidden by the same README and by this task's own absolute governance rules (no substituting, no manufacturing a path around a legitimate blocker).

### 1d. Conclusion

**`REAL_MARKET_DATA = NOT OBTAINABLE IN THIS SESSION`**, for three independent, compounding reasons, each individually sufficient:
1. No real OHLCV data pre-exists anywhere in this environment.
2. No vendor credentials are configured, and the one broker integration capable of a "real" mode (`XMConnection` rest mode) explicitly requires infrastructure this repository does not include and this environment cannot stand up.
3. This session's own network egress policy blocks outbound connections to external data-vendor hosts, independent of credentials — confirmed via the proxy's own diagnostic log, not assumed.

Per the governing **STOP CONDITIONS**: *"STOP immediately if: real market data cannot legitimately be obtained... Do not manufacture evidence to continue."* This report stops here. Phases 2–12 (data integrity, training, baseline, pure holdout, OOS, walk-forward, robustness, cost stress, statistical validation, EVG, final governance report) were **not attempted** — each is explicitly conditioned on real data existing first, and proceeding with synthetic, fixture, or otherwise substituted data would violate Absolute Governance Rule 1 ("REAL DATA ONLY... If no legitimate data source is available, STOP... Do not silently substitute anything").

---

## EXACT NEXT ACTION (the one blocker that must be resolved before this pipeline can resume)

This is a **human decision point**, not something resolvable by continuing to search within this session:

1. **Provide real, licensed EURUSD/GBPUSD H1 (or comparable) historical OHLCV data directly** — e.g., upload a CSV to `data/csv/EURUSD_H1.csv` (and `GBPUSD_H1.csv`) with disclosed provenance (source, license, date range, extraction method) so `CSVProvider` can read it, and this pipeline can resume at Phase 1's data-integrity checks (Phase 2) with genuinely real data; **or**
2. **Obtain a real Alpha Vantage API key and have this session's outbound network egress policy updated to allow `www.alphavantage.co` (or another chosen vendor's domain)** — both are required together; the key alone does not help while the host is policy-blocked; **or**
3. **Stand up and point `XM_REST_URL`/`XM_ACCOUNT_ID`/`XM_PASSWORD` at a real, externally-hosted MT5-compatible bridge** the user operates, with the corresponding host also allowed through the egress policy.

No other legitimate path was found. None of these three can be actioned from inside this session without that external input.

---

## TESTING

```
python3 -m pytest -q   →   533 passed, 0 failed, 0 skipped
```

**Software test evidence, not economic evidence.** This confirms the repository's existing implementation (feature pipeline, target construction, model class, backtest mechanics, EVG, and every other component inventoried in Phase 0) remains fully functional and untouched by this session — no code was changed. It says nothing about whether ML-001-R2 has an economic edge, because no economic evaluation was run: there was no real data to run one against. No new tests were added this session, because no new orchestration code was written — none was needed before real data exists.

---

## FINAL STATUS

```
REAL_MARKET_DATA        = NO (actively attempted this session; blocked by absent local
                               data, absent vendor credentials, and this session's own
                               network egress policy rejecting outbound connections to
                               data-vendor hosts — confirmed via the proxy's own status log)
MODEL_ARTIFACT           = NO (unchanged; not attempted — training requires data)
PURE_HOLDOUT             = NOT_ESTABLISHED (nothing to hold out)
OOS_VALIDATION           = BLOCKED
WALK_FORWARD             = BLOCKED
ROBUSTNESS               = BLOCKED
COST_STRESS              = BLOCKED
STATISTICAL_VALIDATION   = BLOCKED
EVG                      = INSUFFICIENT (not invoked; no genuine evidence exists to feed it)
ECONOMIC_VALIDITY        = INSUFFICIENT_EVIDENCE
EDGE                     = NOT_PROVEN
PRODUCTION               = BLOCKED
```

No data was fabricated, generated, interpolated, or substituted at any point in this attempt. No broker was contacted. No order was placed. No governance state was modified. The blocker is external and structural to this session's environment, not a gap in the repository's implementation — everything downstream (Phases 3–12) is real, tested, and ready to execute the moment real data becomes available through one of the three paths above.
