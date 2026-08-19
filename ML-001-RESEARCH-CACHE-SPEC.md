# ML-001 — Research Cache Specification (Generation 3, Phase 18)

**Status**: IMPLEMENTED (governed infrastructure; no production cache entries exist yet — nothing expensive has been recomputed twice since it landed).
**Code**: `core/factory/research_cache.py`
**Referenced by**: `ML-001-GENERATION-3-SPEC.md` §3.

---

## §1. Principle

The cache is an optimization, **never a governance shortcut**: a hit must be impossible whenever any dependency that could affect the result has changed. This is achieved structurally, not procedurally — the key IS the complete dependency set.

## §2. Key Contract

`cache_key(**dependencies)` = SHA-256 over the sorted, JSON-serialized dependency dict. It **raises** (`ResearchCacheError`) unless every member of `REQUIRED_KEY_FIELDS` is present:

```
dataset_checksum · feature_version · hypothesis_checksum · search_space_checksum
· code_version · cost_model · random_seed
```

Callers may declare MORE dependencies (each extra one also affects the key — tested), but can never omit a required one. Changing any single dependency — dataset bytes, seed, code version, cost model — produces a different key and therefore a guaranteed miss (tested for each, adversarially: `Test12CacheInvalidation`).

## §3. Lookup Contract

`ResearchCache.get(key)` is exact-key only. There is no partial, fuzzy, prefix, or "closest" lookup, so a result computed under different dependencies can never be served.

## §4. What the Cache Never Does

It never substitutes for validation (a cached result is the same result, not a skipped gate); it never stores anything a governance rule forbids computing in the first place; and clearing/expiring entries is a plain operational act with no evidentiary meaning — the registries and ledger, not the cache, are the system of record.
