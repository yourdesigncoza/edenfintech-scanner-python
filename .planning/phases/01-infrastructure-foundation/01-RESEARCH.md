# Phase 1: Infrastructure Foundation - Research

**Researched:** 2026-03-10
**Domain:** FMP response caching, JSON Schema enrichment, pipeline validation gates
**Confidence:** HIGH

## Summary

Phase 1 has two independent workstreams: (A) FMP response caching to save API quota during development, and (B) enriching the JSON schemas with new Codex fields and adding pipeline validation gates. Both are pure Python stdlib work -- no new external dependencies needed.

The caching workstream wraps the existing `FmpClient._get()` transport layer with a file-based cache keyed by endpoint+ticker, with per-endpoint TTLs. The schema workstream adds 6 new field groups to `scan-input.schema.json` and `structured-analysis.schema.json`, then adds two validation gates in `pipeline.py` that reject inputs failing business rules.

**Primary recommendation:** Implement caching as a new `cache.py` module that wraps the existing `FmpTransport` callable, keeping the FmpClient completely unaware of caching. Schema changes are additive JSON edits plus two `if` checks in the pipeline validation path.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CACHE-01 | FMP responses cached per-endpoint per-ticker with configurable TTLs | Cache module wrapping FmpTransport with TTL config dict; file-based storage in `data/cache/fmp/` |
| CACHE-02 | `--fresh` flag bypasses cache for individual calls | Transport wrapper checks `fresh` param; CLI passes flag through to FmpClient construction |
| CACHE-03 | Empty/error responses never cached | Guard in cache write path: skip if payload is empty list, empty dict, or contains `Error Message` |
| CACHE-04 | CLI commands `cache-status` and `cache-clear` | Two new subparser commands reading cache directory metadata |
| SCHM-01 | `catalyst_stack[]` with typed entries (HARD/MEDIUM/SOFT + description + timeline) | New array property in `analysis` and `analysis_inputs` with item schema |
| SCHM-02 | `invalidation_triggers[]` with falsifying evidence | New array property with `{trigger, evidence}` item shape |
| SCHM-03 | `decision_memo` (better_than_peer, safer_than_peer, what_makes_wrong) | New object property with 3 required string fields |
| SCHM-04 | `issues_and_fixes[]` with evidence status enum | Replace current string `issues_and_fixes` with array of `{issue, fix, evidence_status}` objects; enum ANNOUNCED_ONLY/ACTION_UNDERWAY/EARLY_RESULTS_VISIBLE/PROVEN |
| SCHM-05 | `setup_pattern` enum | New string property with enum constraint |
| SCHM-06 | `stretch_case` (same shape as base_case) | New object property reusing `base_case_assumptions` shape |
| SCHM-07 | Pipeline gate rejects if catalyst_stack has zero HARD/MEDIUM entries | Validation check in `validate_scan_input()` or early in `run_scan()` |
| SCHM-08 | Pipeline gate rejects if all issues_and_fixes are ANNOUNCED_ONLY | Validation check alongside SCHM-07 |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `json` | 3.11+ | Cache serialization, schema files | Already used throughout; no external deps policy |
| Python stdlib `pathlib` | 3.11+ | Cache file paths | Already the project pattern |
| Python stdlib `datetime` | 3.11+ | TTL expiry timestamps | Already used for scan dates |
| Python stdlib `hashlib` | 3.11+ | Cache key hashing (endpoint+ticker) | Deterministic, no collisions for this use case |
| Python stdlib `unittest` | 3.11+ | Test framework | Project standard, 59 existing tests |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `shutil` | 3.11+ | `cache-clear` implementation | rmtree for directory clearing |
| Python stdlib `time` | 3.11+ | Epoch timestamps for TTL | Cache entry metadata |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| File-based cache | SQLite | Overkill for per-endpoint JSON blobs; adds complexity |
| Custom TTL logic | `cachetools` | External dependency violates project convention |
| Stdlib `json` schema validation | `jsonschema` | External dependency; project already has custom `schemas.py` validator |

## Architecture Patterns

### Cache Module Structure
```
src/edenfintech_scanner_bootstrap/
├── cache.py              # NEW: CacheStore class + cached_transport wrapper
data/
├── cache/
│   └── fmp/
│       ├── profile/
│       │   └── {TICKER}.json       # cached response
│       ├── quote/
│       │   └── {TICKER}.json
│       ├── historical-price-eod--full/
│       │   └── {TICKER}.json
│       ├── income-statement/
│       │   └── {TICKER}.json
│       └── cash-flow-statement/
│           └── {TICKER}.json
```

### Pattern 1: Transport Wrapper (Decorator Pattern)
**What:** Wrap the existing `FmpTransport` callable with a caching layer that checks file cache before delegating to the real transport.
**When to use:** When you want to add cross-cutting behavior to an existing interface without modifying it.
**Why this pattern:** `FmpClient` already accepts a `transport` parameter (a callable `(endpoint, params) -> dict|list`). The cache wraps this callable, maintaining the same signature. Zero changes to `FmpClient` or `fmp.py`.

```python
# cache.py
import json
import time
from pathlib import Path

# TTLs in seconds, keyed by FMP endpoint prefix
DEFAULT_TTLS: dict[str, int] = {
    "quote": 86400,                      # 1 day
    "historical-price-eod/full": 86400,  # 1 day
    "profile": 2592000,                  # 30 days
    "income-statement": 7776000,         # 90 days
    "cash-flow-statement": 7776000,      # 90 days
}

class FmpCacheStore:
    def __init__(self, cache_dir: Path, ttls: dict[str, int] | None = None):
        self.cache_dir = cache_dir
        self.ttls = ttls or DEFAULT_TTLS

    def _cache_path(self, endpoint: str, ticker: str) -> Path:
        safe_endpoint = endpoint.replace("/", "--")
        return self.cache_dir / safe_endpoint / f"{ticker.upper()}.json"

    def _meta_path(self, cache_path: Path) -> Path:
        return cache_path.with_suffix(".meta.json")

    def get(self, endpoint: str, ticker: str) -> dict | list | None:
        path = self._cache_path(endpoint, ticker)
        meta_path = self._meta_path(path)
        if not path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        if time.time() > meta["expires_at"]:
            return None  # expired
        return json.loads(path.read_text())

    def put(self, endpoint: str, ticker: str, data: dict | list) -> None:
        # CACHE-03: never cache empty/error responses
        if _is_empty_or_error(data):
            return
        path = self._cache_path(endpoint, ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        ttl = self.ttls.get(endpoint, 86400)
        meta = {"cached_at": time.time(), "expires_at": time.time() + ttl, "endpoint": endpoint, "ticker": ticker}
        self._meta_path(path).write_text(json.dumps(meta))

def _is_empty_or_error(data: dict | list) -> bool:
    if isinstance(data, list) and len(data) == 0:
        return True
    if isinstance(data, dict) and (not data or data.get("Error Message")):
        return True
    return False

def cached_transport(inner_transport, cache_store: FmpCacheStore, *, fresh: bool = False):
    def transport(endpoint: str, params: dict[str, str]):
        ticker = params.get("symbol", "UNKNOWN")
        if not fresh:
            cached = cache_store.get(endpoint, ticker)
            if cached is not None:
                return cached
        result = inner_transport(endpoint, params)
        cache_store.put(endpoint, ticker, result)
        return result
    return transport
```

### Pattern 2: Schema Enrichment (Additive Properties)
**What:** Add new properties to existing JSON Schema `$defs`/`definitions` objects without breaking existing validation.
**When to use:** When extending a schema that existing data already validates against.
**Key insight:** All new fields should be added to `required` arrays in the schema so that future inputs must include them. Existing test fixtures will need updating to include the new fields.

### Pattern 3: Pipeline Validation Gates
**What:** Business-rule checks that run during `validate_scan_input()` or at the start of analysis processing.
**When to use:** When the schema alone cannot express the constraint (e.g., "at least one HARD or MEDIUM entry").
**Where:** Add to `pipeline.py:validate_scan_input()` after the schema validation call, checking candidates that pass screening.

```python
# In pipeline.py, after existing validation in validate_scan_input():
def _validate_catalyst_stack(candidate: dict, ticker: str) -> None:
    analysis = candidate.get("analysis", {})
    catalyst_stack = analysis.get("catalyst_stack", [])
    hard_medium = [c for c in catalyst_stack if c.get("type") in ("HARD", "MEDIUM")]
    if not hard_medium:
        raise ValueError(f"{ticker}: catalyst_stack must have at least one HARD or MEDIUM entry")

def _validate_issues_and_fixes(candidate: dict, ticker: str) -> None:
    analysis = candidate.get("analysis", {})
    issues = analysis.get("issues_and_fixes", [])
    if issues and all(i.get("evidence_status") == "ANNOUNCED_ONLY" for i in issues):
        raise ValueError(f"{ticker}: all issues_and_fixes are ANNOUNCED_ONLY; at least one must show progress")
```

### Anti-Patterns to Avoid
- **Modifying FmpClient for caching:** The transport abstraction already exists; changing FmpClient couples caching to the client class.
- **Using `os.path` instead of `pathlib`:** The entire codebase uses `pathlib.Path`; do not introduce `os.path` calls.
- **Making new schema fields optional:** The requirements say these fields ARE the Codex contract; they should be `required` in the schema for candidates that reach analysis.
- **Caching at the bundle level:** Cache individual endpoint responses, not entire bundles; different endpoints have different TTLs.
- **Using `$defs` vs `definitions`:** `scan-input.schema.json` uses `$defs` (JSON Schema 2020-12 style), while `structured-analysis.schema.json` uses `definitions` (draft-07 style). Keep each file's existing convention.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema validation | Custom recursive validator | Existing `schemas.py:validate_instance()` | Already handles `$ref`, `enum`, `required`, type checks; just extend schemas |
| File-based TTL tracking | Inline `os.stat` mtime checks | Explicit `.meta.json` sidecar files | mtime is unreliable across git operations and can be reset by file copies |
| CLI argument parsing | Manual sys.argv parsing | Existing `argparse` subparser pattern in `cli.py` | Project convention; consistent UX |
| Endpoint name sanitization | Regex-based cleaning | Simple `replace("/", "--")` | FMP endpoints only contain alphanumeric and `/` characters |

## Common Pitfalls

### Pitfall 1: Breaking the existing `issues_and_fixes` string field
**What goes wrong:** The current schema defines `issues_and_fixes` as `{"type": "string"}` in both `scan-input.schema.json` and `structured-analysis.schema.json`. Changing it to an array of objects will break all existing test fixtures and regression fixtures.
**Why it happens:** Direct type change without migration.
**How to avoid:** Update all fixtures (`tests/fixtures/raw/`, `tests/fixtures/generated/`, `assets/fixtures/regression/`) in the same commit as the schema change. Run `validate-assets` and full test suite to verify.
**Warning signs:** Test failures mentioning "expected type string" or "expected type array".

### Pitfall 2: Cache directory not in .gitignore
**What goes wrong:** Cached API responses containing financial data get committed to git.
**Why it happens:** New `data/cache/` directory created at runtime.
**How to avoid:** Add `data/cache/` to `.gitignore` in the same commit that introduces caching.

### Pitfall 3: Race condition in cache writes
**What goes wrong:** Data file written but meta file write fails, leaving orphaned cache entry with no expiry.
**Why it happens:** Crash between two file writes.
**How to avoid:** Write meta file first, then data file. On read, require both files to exist. This is a single-operator CLI tool so true concurrency is unlikely, but write ordering is cheap insurance.

### Pitfall 4: TTL endpoint matching with nested paths
**What goes wrong:** `historical-price-eod/full` contains a `/`, so using the endpoint directly as a directory name fails on filesystem.
**Why it happens:** FMP uses hierarchical endpoint names.
**How to avoid:** Replace `/` with `--` in the cache path (e.g., `historical-price-eod--full/`).

### Pitfall 5: Schema `$defs` vs `definitions` inconsistency
**What goes wrong:** Adding `$ref` using wrong anchor style causes validation to silently skip checks.
**Why it happens:** `scan-input.schema.json` uses `$defs` (2020-12), `structured-analysis.schema.json` uses `definitions` (draft-07).
**How to avoid:** Match the existing convention in each file. The custom `schemas.py` resolver handles both `#/$defs/` and `#/definitions/` paths.

### Pitfall 6: Forgetting to update `validate-assets` expectations
**What goes wrong:** `validate-assets` passes but doesn't check for the new schema fields.
**Why it happens:** `validation.py` checks for file existence and contract structure but doesn't deeply inspect schema content.
**How to avoid:** The existing `validate-assets` already validates that schemas parse and contracts reference valid rules. New schema fields are enforced by the schema validation itself during pipeline runs. No changes to `validation.py` needed unless adding new contracts.

## Code Examples

### Adding `catalyst_stack` to scan-input.schema.json
```json
// In $defs.candidate.properties.analysis.properties, add:
"catalyst_stack": {
  "type": "array",
  "minItems": 1,
  "items": {
    "type": "object",
    "required": ["type", "description", "timeline"],
    "properties": {
      "type": {
        "type": "string",
        "enum": ["HARD", "MEDIUM", "SOFT"]
      },
      "description": {
        "type": "string",
        "minLength": 1
      },
      "timeline": {
        "type": "string",
        "minLength": 1
      }
    }
  }
}
```

### Adding `issues_and_fixes` array to replace string
```json
// Replace current "issues_and_fixes": { "type": "string" } with:
"issues_and_fixes": {
  "type": "array",
  "minItems": 1,
  "items": {
    "type": "object",
    "required": ["issue", "fix", "evidence_status"],
    "properties": {
      "issue": {
        "type": "string",
        "minLength": 1
      },
      "fix": {
        "type": "string",
        "minLength": 1
      },
      "evidence_status": {
        "type": "string",
        "enum": ["ANNOUNCED_ONLY", "ACTION_UNDERWAY", "EARLY_RESULTS_VISIBLE", "PROVEN"]
      }
    }
  }
}
```

### Adding `decision_memo` object
```json
"decision_memo": {
  "type": "object",
  "required": ["better_than_peer", "safer_than_peer", "what_makes_wrong"],
  "properties": {
    "better_than_peer": { "type": "string", "minLength": 1 },
    "safer_than_peer": { "type": "string", "minLength": 1 },
    "what_makes_wrong": { "type": "string", "minLength": 1 }
  }
}
```

### Adding `stretch_case` (same shape as base_case)
```json
// In scan-input.schema.json, $defs.candidate.properties.analysis.properties:
"stretch_case": {
  "type": "object",
  "required": ["revenue_b", "fcf_margin_pct", "multiple", "shares_m", "years"],
  "properties": {
    "revenue_b": { "type": "number" },
    "fcf_margin_pct": { "type": "number" },
    "multiple": { "type": "number" },
    "shares_m": { "type": "number", "minimum": 0 },
    "years": { "type": "number", "minimum": 0 },
    "discount_path": { "type": "string" }
  }
}

// In structured-analysis.schema.json, add stretch_case_assumptions
// using same shape as base_case_assumptions definition
```

### Wiring cache into CLI
```python
# In cli.py, modify _cmd_fetch_fmp_bundle:
def _cmd_fetch_fmp_bundle(tickers: list[str], json_out: str | None, fresh: bool = False) -> int:
    config = load_config()
    cache_store = FmpCacheStore(cache_dir=discover_cache_dir())
    transport = cached_transport(_default_transport, cache_store, fresh=fresh)
    bundle = build_fmp_bundle_with_config(tickers, config=config, transport=transport)
    # ...

# New subparser:
fetch_fmp_bundle.add_argument("--fresh", action="store_true", help="Bypass cache")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `issues_and_fixes` as free-text string | Structured array with evidence_status enum | This phase | Pipeline can programmatically reject ANNOUNCED_ONLY-only analyses |
| `catalysts` as untyped array | `catalyst_stack` with HARD/MEDIUM/SOFT typing | This phase | Pipeline can gate on catalyst quality |
| Single base/worst case valuation | Three cases: worst, base, stretch | This phase | Richer valuation range for scoring |
| No FMP response caching | Per-endpoint per-ticker file cache with TTLs | This phase | Saves API quota during development |

## Open Questions

1. **Where should the cache directory live?**
   - Recommendation: `data/cache/fmp/` relative to project root, discovered via `config.py:discover_project_root()`. Add to `.gitignore`.
   - Alternative: Configurable via env var `EDENFINTECH_CACHE_DIR`.

2. **Should `stretch_case` be required in `analysis`?**
   - The requirement says "same shape as base_case". Since `base_case` is required, `stretch_case` should also be required for candidates that reach analysis. This matches the Codex 05-VALUATION.md contract (bear/base/stretch).
   - Recommendation: Make it required in the schema for analysis-level candidates.

3. **Should the new fields be added to `structured-analysis.schema.json` `analysis_inputs` as well?**
   - Yes. The structured analysis is the upstream source that feeds scan-input via `importers.py`. Both schemas need the same fields for the pipeline to work end-to-end.

4. **How should `catalyst_stack` relate to existing `catalysts` array?**
   - `catalyst_stack` replaces `catalysts` as the richer typed version. The old `catalysts` array (untyped `items: {}`) should be removed or kept as optional for backward compat during migration.
   - Recommendation: Keep `catalysts` as optional (not in `required`) for one phase, then remove. Add `catalyst_stack` as required.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Python unittest (stdlib) |
| Config file | None (unittest discovery via `python -m unittest discover -s tests -v`) |
| Quick run command | `python -m unittest discover -s tests -v` |
| Full suite command | `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CACHE-01 | Cached FMP response returned on second call | unit | `python -m unittest tests.test_cache.TestFmpCache.test_cached_response_returned -v` | Wave 0 |
| CACHE-01 | TTL expiry triggers fresh fetch | unit | `python -m unittest tests.test_cache.TestFmpCache.test_expired_cache_refetches -v` | Wave 0 |
| CACHE-02 | `--fresh` bypasses cache | unit | `python -m unittest tests.test_cache.TestFmpCache.test_fresh_flag_bypasses -v` | Wave 0 |
| CACHE-03 | Empty response not cached | unit | `python -m unittest tests.test_cache.TestFmpCache.test_empty_response_not_cached -v` | Wave 0 |
| CACHE-03 | Error response not cached | unit | `python -m unittest tests.test_cache.TestFmpCache.test_error_response_not_cached -v` | Wave 0 |
| CACHE-04 | `cache-status` reports counts and TTLs | unit | `python -m unittest tests.test_cache.TestCacheCli.test_cache_status_output -v` | Wave 0 |
| CACHE-04 | `cache-clear` removes cache files | unit | `python -m unittest tests.test_cache.TestCacheCli.test_cache_clear -v` | Wave 0 |
| SCHM-01 | Schema validates catalyst_stack with HARD/MEDIUM/SOFT | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_catalyst_stack_validation -v` | Wave 0 |
| SCHM-02 | Schema validates invalidation_triggers | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_invalidation_triggers -v` | Wave 0 |
| SCHM-03 | Schema validates decision_memo | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_decision_memo -v` | Wave 0 |
| SCHM-04 | Schema validates issues_and_fixes array with enum | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_issues_and_fixes_array -v` | Wave 0 |
| SCHM-05 | Schema validates setup_pattern enum | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_setup_pattern -v` | Wave 0 |
| SCHM-06 | Schema validates stretch_case | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_stretch_case -v` | Wave 0 |
| SCHM-07 | Pipeline rejects zero HARD/MEDIUM catalyst_stack | unit | `python -m unittest tests.test_scan_pipeline.TestPipelineGates.test_rejects_no_hard_medium_catalysts -v` | Wave 0 |
| SCHM-08 | Pipeline rejects all-ANNOUNCED_ONLY issues | unit | `python -m unittest tests.test_scan_pipeline.TestPipelineGates.test_rejects_all_announced_only -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest discover -s tests -v`
- **Per wave merge:** `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_cache.py` -- covers CACHE-01 through CACHE-04
- [ ] `tests/test_schema_enrichment.py` -- covers SCHM-01 through SCHM-06 (schema validation tests)
- [ ] Update `tests/test_scan_pipeline.py` with `TestPipelineGates` class -- covers SCHM-07, SCHM-08
- [ ] Update all existing test fixtures in `tests/fixtures/raw/` and `tests/fixtures/generated/` to include new schema fields
- [ ] Update regression fixtures in `assets/fixtures/regression/` to include new schema fields

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** -- `fmp.py` (FmpTransport callable pattern), `cli.py` (argparse subparser pattern), `config.py` (project root discovery), `schemas.py` (custom JSON Schema validator), `pipeline.py` (validate_scan_input flow), `validation.py` (validate-assets expectations)
- **Existing schemas** -- `scan-input.schema.json` ($defs style, 2020-12), `structured-analysis.schema.json` (definitions style, draft-07)
- **Test suite** -- 59 tests passing, `unittest` framework, fixture-based testing with transport injection pattern
- **REQUIREMENTS.md** -- Exact requirement definitions for CACHE-01..04 and SCHM-01..08

### Secondary (MEDIUM confidence)
- **TTL values** -- Requirement says "price-history 1d, screener/ratios/metrics/ev 7d, profile/peers 30d, financials 90d". The FMP endpoints used in the codebase map: quote=1d, historical-price-eod/full=1d, profile=30d, income-statement=90d, cash-flow-statement=90d. The 7d tier (screener/ratios/metrics/ev) maps to endpoints not currently used; can be added as defaults for future use.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure stdlib Python, all patterns already in codebase
- Architecture: HIGH -- transport wrapper pattern already exists, schema extension is mechanical
- Pitfalls: HIGH -- identified from direct codebase inspection (fixture updates, path sanitization, schema style differences)

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable; no external dependencies to change)
