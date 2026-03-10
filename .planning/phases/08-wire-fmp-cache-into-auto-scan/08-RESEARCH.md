# Phase 8: Wire FMP Cache into Auto-Scan Paths - Research

**Researched:** 2026-03-10
**Domain:** Python internal wiring / transport injection
**Confidence:** HIGH

## Summary

This phase closes a gap identified in the v1.0 milestone audit: the FMP cache layer (Phase 1) works correctly for manual CLI paths (`fetch-fmp-bundle`, `run-live-scan`, `build-review-package`) but is bypassed entirely in the `auto-scan` and `sector-scan` code paths. The root cause is clear: `auto_analyze()` has no `fmp_transport` parameter, so `run_live_scan()` inside it receives `None` for `fmp_transport` and falls back to uncached HTTP calls. The `--fresh` flag is parsed by CLI but silently discarded.

The fix is a threading exercise across three files (`automation.py`, `scanner.py`, `cli.py`) with no new dependencies, no new architectural patterns, and no design ambiguity. The existing `FmpCacheStore` + `cached_transport` wrapper pattern is proven and tested. This phase replicates the exact pattern already used in `_cmd_fetch_fmp_bundle`, `_cmd_run_live_scan`, and `_cmd_build_review_package`.

**Primary recommendation:** Thread `fmp_transport` parameter through `auto_analyze()` -> `run_live_scan()`, accept it in `auto_scan()` and `sector_scan()`, construct `FmpCacheStore` + `cached_transport` in CLI handlers `_cmd_auto_scan` and `_cmd_sector_scan`, and wire `--fresh` through.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CACHE-01 | FMP responses cached per-endpoint per-ticker with configurable TTLs | Thread `fmp_transport` into auto_analyze -> run_live_scan so the cached transport is used. Existing FmpCacheStore TTL config is already correct. |
| CACHE-02 | `--fresh` flag bypasses cache for individual calls | CLI handlers must construct `cached_transport(..., fresh=args.fresh)` and pass it down. Pattern proven in `_cmd_fetch_fmp_bundle`. |
| CACHE-03 | Empty/error responses never cached | Existing `FmpCacheStore.put()` guard handles this. Once cache is constructed in auto-scan/sector-scan paths, the guard is automatically exercised. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11+ | All implementation | Project convention: no external deps for core pipeline |
| unittest + unittest.mock | stdlib | Testing | Project's existing test framework |

### Supporting
No new libraries required. This phase uses only existing project modules:

| Module | Purpose | Already Exists |
|--------|---------|----------------|
| `cache.py` | `FmpCacheStore`, `cached_transport` | Yes (Phase 1) |
| `fmp.py` | `FmpTransport` type alias, `_default_transport` | Yes (Phase 1) |
| `automation.py` | `auto_analyze()` orchestrator | Yes (Phase 5) |
| `scanner.py` | `auto_scan()`, `sector_scan()` | Yes (Phase 6) |
| `cli.py` | CLI handlers `_cmd_auto_scan`, `_cmd_sector_scan` | Yes (Phase 6) |

**No installation needed.**

## Architecture Patterns

### Existing Transport Injection Pattern (reuse exactly)

The project already has a proven pattern for FMP cache wiring. Three CLI handlers do it identically:

```python
# Pattern from _cmd_fetch_fmp_bundle, _cmd_run_live_scan, _cmd_build_review_package
from .fmp import _default_transport
store = FmpCacheStore(_default_fmp_cache_dir())
transport = cached_transport(_default_transport, store, fresh=fresh)
# Then pass transport= downstream
```

This phase replicates the same pattern in `_cmd_auto_scan` and `_cmd_sector_scan`.

### Call Chain That Needs Wiring

```
CLI handler (_cmd_auto_scan / _cmd_sector_scan)
  -> constructs FmpCacheStore + cached_transport    [NEW]
  -> passes fmp_transport= to auto_scan/sector_scan [NEW parameter]
    -> passes fmp_transport= to auto_analyze        [NEW parameter]
      -> passes fmp_transport= to run_live_scan     [EXISTING parameter, currently receives None]
        -> passes transport= to build_fmp_bundle_with_config [EXISTING]
          -> FmpClient uses transport               [EXISTING]
```

### Files Changed (3 files, ~20 lines total)

```
src/edenfintech_scanner_bootstrap/
  automation.py   # Add fmp_transport param to auto_analyze(), forward to run_live_scan()
  scanner.py      # Add fmp_transport param to auto_scan() + sector_scan(), forward to auto_analyze()
                  # Also: sector_scan's FmpClient for screener should use cached transport
  cli.py          # _cmd_auto_scan and _cmd_sector_scan: construct cache + transport, pass down
```

### sector_scan Special Case

`sector_scan()` creates its own `FmpClient` for the screener step (line 393-395). This client also needs to use the cached transport. The `fmp_client` parameter already exists on `sector_scan()`, so the CLI handler should construct an `FmpClient` with the cached transport and pass it via `fmp_client=`.

```python
# In _cmd_sector_scan: construct FmpClient with cached transport for screener
from .fmp import _default_transport, FmpClient
store = FmpCacheStore(_default_fmp_cache_dir())
transport = cached_transport(_default_transport, store, fresh=fresh)
fmp_client = FmpClient(config.fmp_api_key, transport=transport)
# Pass both fmp_transport (for auto_analyze path) and fmp_client (for screener)
result = sector_scan(..., fmp_client=fmp_client, fmp_transport=transport)
```

### Anti-Patterns to Avoid
- **Constructing cache inside auto_analyze or scanner.py:** Cache construction belongs in CLI handlers (composition root). Inner modules receive transports via injection.
- **Adding cache_dir or fresh params to auto_analyze:** These are CLI concerns. Inner functions take an already-configured `fmp_transport`.
- **Breaking existing tests:** All new parameters must have `None` defaults so existing callers (including tests that mock auto_analyze) continue working unchanged.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cache logic | New cache mechanism | Existing `FmpCacheStore` + `cached_transport` | Already built, tested, proven in 3 CLI paths |
| Transport wrapping | New wrapper function | Existing `cached_transport()` | Handles fresh flag, put guards, all edge cases |

**Key insight:** This phase adds zero new functionality. It threads existing functionality through a call path that was missed.

## Common Pitfalls

### Pitfall 1: Forgetting sector_scan's Own FmpClient
**What goes wrong:** Cache is wired into auto_analyze path but sector_scan's screener + build_raw_candidate_from_fmp calls (lines 396-408) still use an uncached FmpClient.
**Why it happens:** sector_scan constructs its own FmpClient when `fmp_client is None`. Easy to miss this separate FMP usage.
**How to avoid:** Pass a cached `FmpClient` via the existing `fmp_client=` parameter on sector_scan. The CLI handler constructs it.
**Warning signs:** Running sector-scan shows HTTP calls for screener/profile/quote during the filter phase even after wiring.

### Pitfall 2: Breaking Existing Test Mocks
**What goes wrong:** Tests that mock `auto_analyze` or call `auto_scan`/`sector_scan` directly fail because new required parameters are missing.
**Why it happens:** Adding `fmp_transport` without a default value.
**How to avoid:** All new `fmp_transport` parameters default to `None`. When `None`, behavior is unchanged (falls back to uncached, matching current behavior).
**Warning signs:** Existing test_scanner.py or test_automation.py tests start failing.

### Pitfall 3: Silently Discarding --fresh (Already Happening)
**What goes wrong:** `_cmd_auto_scan` and `_cmd_sector_scan` accept `fresh` parameter but never use it.
**Why it happens:** This is the current bug. The fix is to pass `fresh=` into `cached_transport()`.
**How to avoid:** Verify `args.fresh` flows into `cached_transport(... fresh=args.fresh)` in both CLI handlers.
**Warning signs:** `--fresh` flag accepted by parser but cache still serves stale data.

### Pitfall 4: render_scan_markdown Unused Import
**What goes wrong:** Tech debt flagged in audit: scanner.py imports `render_scan_markdown` but never uses it.
**How to avoid:** Remove unused import while editing scanner.py. Clean up is free here.

## Code Examples

### Change 1: automation.py -- Add fmp_transport parameter

```python
# automation.py: auto_analyze signature change
def auto_analyze(
    ticker: str,
    *,
    config: AppConfig,
    out_dir: Path,
    fmp_transport: FmpTransport | None = None,  # NEW
    analyst_client: ClaudeAnalystClient | None = None,
    validator_client: RedTeamValidatorClient | None = None,
    epistemic_client: EpistemicReviewerClient | None = None,
    sector_knowledge: dict | None = None,
    max_retries: int = 2,
) -> AutoAnalyzeResult:
    # Step 1: Forward fmp_transport to run_live_scan
    scan_result = run_live_scan(
        [ticker], out_dir=out_dir, stop_at="raw-bundle", config=config,
        fmp_transport=fmp_transport,  # NEW
    )
    # ... rest unchanged
```

Need to add `FmpTransport` import:
```python
from .fmp import FmpTransport
```

### Change 2: scanner.py -- Add fmp_transport to auto_scan and sector_scan

```python
# scanner.py: auto_scan
def auto_scan(
    tickers: list[str],
    *,
    config: AppConfig,
    fmp_transport: FmpTransport | None = None,  # NEW
    out_dir: Path | None = None,
    # ... existing params
) -> ScanResult:
    # In the loop, forward to auto_analyze:
    auto_result = auto_analyze(
        ticker,
        config=config,
        out_dir=out_dir / ticker / "raw",
        fmp_transport=fmp_transport,  # NEW
        # ... existing params
    )
```

```python
# scanner.py: sector_scan
def sector_scan(
    sector_name: str,
    *,
    config: AppConfig,
    fmp_transport: FmpTransport | None = None,  # NEW
    out_dir: Path | None = None,
    # ... existing params
) -> ScanResult:
    # In _analyze_ticker closure, forward fmp_transport:
    auto_result = auto_analyze(
        ticker,
        config=config,
        out_dir=out_dir / ticker / "raw",
        fmp_transport=fmp_transport,  # NEW (captured in closure)
        # ... existing params
    )
```

Need to add `FmpTransport` import:
```python
from .fmp import FmpClient, FmpTransport, build_raw_candidate_from_fmp
```

### Change 3: cli.py -- Construct cache in _cmd_auto_scan and _cmd_sector_scan

```python
def _cmd_auto_scan(tickers: list[str], out_dir: str | None, fresh: bool = False) -> int:
    config = load_config()
    config.require("fmp_api_key", "anthropic_api_key")
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store, fresh=fresh)
    result = auto_scan(
        tickers,
        config=config,
        fmp_transport=transport,
        out_dir=Path(out_dir) if out_dir else None,
    )
    # ... rest unchanged
```

```python
def _cmd_sector_scan(
    sector_name: str,
    out_dir: str | None,
    max_workers: int,
    exclude_industry: list[str] | None,
    fresh: bool = False,
) -> int:
    config = load_config()
    config.require("fmp_api_key", "anthropic_api_key", "gemini_api_key")
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store, fresh=fresh)
    fmp_client = FmpClient(config.fmp_api_key, transport=transport)
    result = sector_scan(
        sector_name,
        config=config,
        fmp_transport=transport,
        fmp_client=fmp_client,
        out_dir=Path(out_dir) if out_dir else None,
        max_workers=max_workers,
        excluded_industries=exclude_industry,
    )
    # ... rest unchanged
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual CLI paths use cache | All paths should use cache | Phase 8 (this) | Eliminates redundant API calls in automated scans |

**No deprecated patterns.** This is purely an internal wiring fix using existing, stable project code.

## Open Questions

None. The gap is precisely diagnosed in the milestone audit. The fix pattern is proven in 3 existing CLI handlers. No ambiguity remains.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | unittest (stdlib) |
| Config file | none (stdlib discovery) |
| Quick run command | `python -m unittest tests.test_cache tests.test_scanner -v` |
| Full suite command | `python -m unittest discover -s tests -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CACHE-01 | auto_scan forwards fmp_transport to auto_analyze, second run hits cache | unit | `python -m unittest tests.test_scanner.TestAutoScanCache -v` | Wave 0 |
| CACHE-02 | --fresh flag constructs cached_transport with fresh=True in both CLI handlers | unit | `python -m unittest tests.test_scanner.TestAutoScanCache.test_fresh_flag_forwarded -v` | Wave 0 |
| CACHE-03 | Empty/error FMP responses not cached in auto-scan path | unit | `python -m unittest tests.test_scanner.TestAutoScanCache.test_empty_not_cached -v` | Wave 0 |
| CACHE-01 | sector_scan threads cached transport through screener + auto_analyze | unit | `python -m unittest tests.test_scanner.TestSectorScanCache -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest tests.test_cache tests.test_scanner tests.test_automation -v`
- **Per wave merge:** `python -m unittest discover -s tests -v`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_scanner.py::TestAutoScanCache` -- new test class covering CACHE-01/02/03 for auto_scan path
- [ ] `tests/test_scanner.py::TestSectorScanCache` -- new test class covering CACHE-01 for sector_scan path (screener + auto_analyze both cached)
- [ ] Verify existing tests in test_scanner.py and test_automation.py still pass unchanged (no regressions from new optional params)

## Sources

### Primary (HIGH confidence)
- Source code analysis: `cache.py`, `fmp.py`, `automation.py`, `scanner.py`, `cli.py`, `live_scan.py`
- Milestone audit: `.planning/v1.0-MILESTONE-AUDIT.md` (precise gap diagnosis)
- Existing tests: `tests/test_cache.py`, `tests/test_scanner.py`

### Secondary (MEDIUM confidence)
- None needed. This is an internal wiring task with no external dependencies.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, reuse existing
- Architecture: HIGH -- exact pattern already proven in 3 CLI handlers
- Pitfalls: HIGH -- gap precisely diagnosed in audit with file/line-level evidence

**Research date:** 2026-03-10
**Valid until:** indefinite (internal codebase wiring, no external dependencies to age)
