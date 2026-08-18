# ML-001-R2 Python↔Pine Simulator Parity — Forensic Baseline (Phase 0)

**Date**: August 18, 2026
**Purpose**: independently re-verify, before any new code is written, every
factual claim the prior Pine-parity work (commit `5a516c3`) rested on.
Nothing below is copied from a prior report without being re-run.

---

## 1. Git status

```
$ git status --short
(empty — clean working tree)
```

## 2. Current commit

```
$ git rev-parse HEAD
5a516c3d438c97b7ebd6cdd31b93969a511f6521
$ git log --oneline -3
5a516c3 feat(ml-r2): add TradingView Pine parity layer for manual verification only
6910142 docs(ml-r2): economic validation blocked by missing real data source
8b97332 fix(ml-r2): resolve RSI ATR numerical specification ambiguity
$ git branch --show-current
claude/ea-factory-pro-system-bc9jaa
```

This is the baseline commit for this phase's work.

## 3. No trained RF-R2-001 artifact exists

```
$ git ls-files | grep -iE '\.joblib|\.pkl|\.pickle|\.h5|model.*\.(bin|dat)$|rf.*artifact'
(no output — nothing tracked)

$ find . -iname "*.joblib" -o -iname "*rf-r2-001*" -o -iname "*RF_R2_001*" | grep -v '\.git/'
(no output — nothing on disk)

$ git log --all --diff-filter=A --name-only | grep -iE '\.joblib|\.pkl|\.pickle|model.*\.(bin|dat)'
(no output — never committed, at any point in this repo's history)
```

## 4. No model artifact hidden in gitignored paths

```
$ cat .gitignore
```
Gitignored patterns of possible relevance: `artifacts/`, `data/cache/`,
`data/*.parquet`, `data/*.csv`, `*.db`, `*.sqlite3`. Checked each:

```
$ find ./artifacts -type f          -> empty
$ find ./data/cache -type f         -> empty
$ find / -xdev -iname "*.joblib" -o -iname "*.pkl" -o -iname "*.h5" | grep -v /proc/
```
Result: the only `.pkl` files anywhere on the filesystem are third-party
library self-test fixtures (`numpy/_core/tests/data/astype_copy.pkl`,
`joblib/test/data/joblib_0.*_pickle_*.pkl`) — not project files, not
model artifacts, and not reachable from this repository's code paths.

One directory warranted a closer look: `./models/`. It is **not**
gitignored and **is** tracked, but on inspection it is an unrelated
SQLAlchemy-style ORM package (`account.py`, `order.py`, `position.py`,
`strategy.py`, `trade.py`, `metrics.py`, `database.py`) — application
data models, not a trained ML artifact. Confirmed by content, not name
alone.

**Conclusion, independently re-verified**: no trained RF-R2-001 model
artifact exists anywhere in this repository, its git history, or its
gitignored local state.

## 5. Current Pine files and their SHA-256 hashes (pre-this-phase)

```
$ sha256sum pine/*.pine
615eb426890b96072f57259693dba554bdd0c603ebe20fb20a7e32954d559b2b  pine/ML_001_R2_FEATURE_DEBUG.pine
019592f5a9f9e3ce624366ac48b13e08fb33fae1f7cbc5b91e1d9ae6cf56dae0  pine/ML_001_R2_STRATEGY.pine
dcfc8c04f18906ba973092e894b1a8105543d193ae33fd22673e8b406773cad8  pine/ml_001_r2_features.pine
```
These are the hashes as committed in `5a516c3`, before this phase's
`pine/ML_001_R2_STRATEGY.pine` edit (Phase 7's PARITY TEST FIXTURE MODE
addition — the canonical feature block inside it is unchanged and
re-verified byte-identical by `tests/test_pine_parity.py` after the
edit, see this phase's own report for the post-edit hash).

## 6. Current FE-R2-002 Python source hash

```
$ sha256sum core/features/fe_r2_001.py
1d8ce135daaafedd8c085b243f41beeb1b8aafb165f7169d3722dc6e99ffd3dd  core/features/fe_r2_001.py
```
Not modified by this phase — Python FE-R2-002 remains the source of
truth (governance rule 10), re-confirmed by hash-diff at the end of
this phase's work.

## 7. Existing test suite (pre-this-phase baseline)

```
508/508 full repository suite passing
206/206 R2 + Pine-parity suite passing (186 pre-existing R2 tests + 20 Pine parity tests)
```
Re-run independently at the start of this phase (not merely quoted from
the prior report) — see the accompanying test run logs referenced in
`ML-001-R2-PYTHON-PINE-SIMULATOR-PARITY-REPORT.md`, Section on Tests.

## 8. Discrepancies found versus the prior report's claims

None. Every claim above was independently re-derived, not trusted from
`ML-001-R2-PYTHON-PINE-PARITY-REPORT.md` (the prior report). The prior
report's MODEL_ARTIFACT/MODEL_PARITY findings are corroborated exactly.
