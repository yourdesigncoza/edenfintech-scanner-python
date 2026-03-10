# Phase 6: Scan Modes and Hardening - Research

**Researched:** 2026-03-10
**Domain:** CLI scan orchestration, sector screening, bias detection, evidence quality gates
**Confidence:** HIGH

## Summary

Phase 6 builds two capabilities on top of the Phase 5 `auto_analyze()` orchestrator: (1) CLI scan commands that run `auto_analyze` per ticker and produce JSON+markdown reports with manifests, and (2) hardening gates that detect LLM bias patterns (probability anchoring, CAGR exceptions, weak evidence).

The codebase already contains all the building blocks. `auto_analyze()` (Phase 5) handles the per-ticker flow. `pipeline.run_scan()` handles deterministic scoring. `fmp.py` already has `build_raw_candidate_from_fmp()` which computes `pct_off_ath`. The `stock-screener` FMP endpoint is already in the cache TTL table but no client method wraps it yet. The sector module has `hydrate_sector()`, `load_sector_knowledge()`, and `check_sector_freshness()`. No parallelism exists in the codebase -- `sector-scan` needs `concurrent.futures.ThreadPoolExecutor` for parallel auto_analyze calls.

**Primary recommendation:** Build `scanner.py` module for scan orchestration (auto-scan + sector-scan) and `hardening.py` for bias detection gates. Both integrate into `cli.py` as new subcommands. The CAGR exception panel reuses the existing 3-agent architecture (analyst, validator, epistemic reviewer) with a specialized voting prompt.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCAN-01 | `auto-scan TICKER [TICKER...]` runs auto_analyze per ticker -> pipeline -> judge -> report | auto_analyze() from Phase 5 handles per-ticker flow; scanner.py wraps it with output management to data/scans/ |
| SCAN-02 | `sector-scan "Sector"` with hydration check, broken-chart filter, industry exclusion, clustering, parallel auto_analyze | FMP stock-screener endpoint (already in cache TTLs), sector.py for hydration checks, concurrent.futures for parallelism |
| SCAN-03 | Report output to `data/scans/json/` + `data/scans/` (markdown) with manifest per scan run | Follows review_package.py manifest pattern -- JSON manifest listing all tickers with pass/fail status |
| HARD-01 | 20% CAGR exception panel -- 3-agent unanimous vote with full reasoning logged | Reuses ClaudeAnalystClient, RedTeamValidatorClient, EpistemicReviewerClient with specialized exception voting prompts |
| HARD-02 | Probability anchoring detection -- flag exactly 60% + friction risk type | Pure deterministic check on `base_probability_pct` and `dominant_risk_type` in the structured analysis overlay |
| HARD-03 | Evidence quality scoring -- count concrete citations vs vague, add methodology warning below threshold | Extends epistemic_reviewer.py's existing is_weak_evidence() and CONCRETE_SOURCE_MARKERS |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| concurrent.futures | stdlib | Parallel auto_analyze in sector-scan | stdlib ThreadPoolExecutor; no new dependency needed |
| argparse | stdlib | CLI subcommands for auto-scan, sector-scan | Already used in cli.py |
| json | stdlib | Manifest files, report output | Already used throughout |
| pathlib | stdlib | Output directory management | Already used throughout |
| datetime | stdlib | Scan run timestamps for manifests | Already used throughout |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Warning/info logs for scan progress | Already used in automation.py (Phase 5) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| concurrent.futures | asyncio | Unnecessarily complex; all transports are synchronous urllib; ThreadPoolExecutor is simpler |
| Custom parallelism | Sequential loop | sector-scan with 10+ tickers would be too slow; ThreadPoolExecutor with max_workers=3-4 balances API rate limits |

**Installation:**
```bash
# No new dependencies -- all stdlib
```

## Architecture Patterns

### Recommended Project Structure
```
src/edenfintech_scanner_bootstrap/
  scanner.py           # NEW: auto_scan() and sector_scan() orchestrators
  hardening.py         # NEW: CAGR exception panel, anchoring detection, evidence quality scoring
  cli.py               # MODIFIED: add auto-scan and sector-scan subcommands
  fmp.py               # MODIFIED: add stock_screener() method to FmpClient
  automation.py        # FROM PHASE 5: auto_analyze() per-ticker orchestrator
  pipeline.py          # EXISTING: deterministic scoring pipeline
  epistemic_reviewer.py # EXISTING: evidence quality utilities (is_weak_evidence, etc.)
```

### Pattern 1: Scan Orchestrator (scanner.py)
**What:** Single module coordinating multi-ticker scan runs with output management
**When to use:** Both auto-scan and sector-scan share the same per-ticker flow and output structure
**Example:**
```python
@dataclass(frozen=True)
class ScanResult:
    scan_id: str  # timestamp-based unique ID
    tickers_processed: list[str]
    results: dict[str, TickerResult]  # ticker -> result
    manifest_path: Path

@dataclass(frozen=True)
class TickerResult:
    ticker: str
    status: str  # "PASS", "FAIL", "ERROR"
    report_json_path: Path | None
    report_markdown_path: Path | None
    error: str | None

def auto_scan(
    tickers: list[str],
    *,
    config: AppConfig,
    out_dir: Path | None = None,  # defaults to data/scans/<scan_id>/
) -> ScanResult:
    """Run auto_analyze per ticker, then pipeline + judge, write reports + manifest."""

def sector_scan(
    sector_name: str,
    *,
    config: AppConfig,
    out_dir: Path | None = None,
    max_workers: int = 3,
    excluded_industries: list[str] | None = None,
) -> ScanResult:
    """Check hydration, screener, broken-chart filter, cluster, parallel auto_analyze."""
```

### Pattern 2: Sector Scan Flow (sequential steps)
**What:** The sector-scan command follows a strict pipeline
**When to use:** sector-scan only
**Steps:**
1. Check sector hydration via `check_sector_freshness()` -- error if NOT_HYDRATED
2. Use FMP stock-screener endpoint to get tickers in sector (new `FmpClient.stock_screener()` method)
3. Apply broken-chart filter: fetch `pct_off_ath` per ticker from FMP, keep only >= 60%
4. Exclude filtered industries (operator-provided list)
5. Cluster survivors by sub-sector/industry
6. Run `auto_analyze` per ticker using `ThreadPoolExecutor(max_workers=N)`
7. Collect results, run pipeline + judge per ticker, write reports
8. Write manifest

### Pattern 3: CAGR Exception Panel (hardening.py)
**What:** When base_cagr is 20-29.9%, three agents vote independently
**When to use:** Replaces the current pipeline behavior that routes 20-29.9% CAGR to pending_human_review
**Flow:**
```python
@dataclass(frozen=True)
class ExceptionVote:
    agent: str  # "analyst", "validator", "epistemic_reviewer"
    approve: bool
    reasoning: str

@dataclass(frozen=True)
class ExceptionPanelResult:
    votes: list[ExceptionVote]
    unanimous: bool
    approved: bool  # True only if all 3 approve

def cagr_exception_panel(
    overlay_candidate: dict,
    raw_candidate: dict,
    *,
    analyst_client: ClaudeAnalystClient,
    validator_client: RedTeamValidatorClient,
    epistemic_client: EpistemicReviewerClient,
) -> ExceptionPanelResult:
```
Each agent gets a focused prompt asking: "Should this 20-29.9% CAGR candidate be granted an exception? Vote APPROVE or REJECT with full reasoning." All three must APPROVE for the candidate to advance. Non-unanimous stays in pending_review.

### Pattern 4: Deterministic Bias Detection (hardening.py)
**What:** Pure code checks for probability anchoring and evidence quality
**When to use:** Run as post-processing after analyst draft, before finalization
**Example:**
```python
def detect_probability_anchoring(
    base_probability_pct: float,
    dominant_risk_type: str,
) -> dict | None:
    """Flag PROBABILITY_ANCHORING_SUSPECT when exactly 60% + friction risk type."""
    friction_types = {"Cyclical/Macro", "Regulatory/Political", "Legal/Investigation", "Structural fragility (SPOF)"}
    if base_probability_pct == 60.0 and dominant_risk_type in friction_types:
        return {
            "flag": "PROBABILITY_ANCHORING_SUSPECT",
            "base_probability_pct": base_probability_pct,
            "dominant_risk_type": dominant_risk_type,
            "reason": "Analyst assigned exactly 60% probability with a friction-carrying risk type. This pattern suggests anchoring to the minimum viable probability rather than evidence-based estimation.",
        }
    return None

def score_evidence_quality(
    overlay_candidate: dict,
    *,
    concrete_threshold: float = 0.5,  # 50% concrete citations required
) -> dict:
    """Count concrete vs vague citations, return quality score + methodology warning."""
```

### Anti-Patterns to Avoid
- **Building a separate pipeline for sector-scan:** Reuse `auto_analyze()` per ticker -- sector-scan is just ticker discovery + parallel orchestration
- **Modifying pipeline.py for hardening:** Keep hardening checks in their own module; they run before/after the pipeline, not inside it
- **Synchronous sector-scan:** Without parallelism, scanning 10+ tickers in a sector would take too long (each auto_analyze involves multiple API calls)
- **Custom manifest format:** Follow the existing `review-package-manifest.json` pattern from review_package.py

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-ticker analysis flow | Custom fetch/analyze/validate chain | `auto_analyze()` from Phase 5 | Already handles retry loop, epistemic review, finalization |
| FMP data fetching | Direct HTTP calls | `FmpClient` with cached transport | Cache layer prevents quota burn |
| Evidence quality detection | Custom regex patterns | `is_weak_evidence()`, `CONCRETE_SOURCE_MARKERS` from epistemic_reviewer.py | Already battle-tested patterns |
| Report rendering | Custom markdown | `render_scan_markdown()` from reporting.py | Already renders from validated report JSON |
| Sector hydration check | File existence check | `check_sector_freshness()` from sector.py | Handles staleness, registry lookup |

## Common Pitfalls

### Pitfall 1: FMP Stock Screener Endpoint Shape
**What goes wrong:** FMP screener returns a flat list of company objects with sector/industry fields, not grouped by sector
**Why it happens:** Assuming the screener response is structured like the sector knowledge
**How to avoid:** The screener endpoint is `stock-screener` with params like `sector=Consumer Defensive&exchange=NYSE`. Parse the flat list and filter/group client-side. The `stock-screener` endpoint is already in `DEFAULT_TTLS` in cache.py but no `FmpClient` method wraps it yet.
**Warning signs:** Empty screener results (wrong sector name casing)

### Pitfall 2: Rate Limiting in Parallel Sector Scan
**What goes wrong:** FMP or LLM API rate limits hit when running multiple tickers in parallel
**Why it happens:** ThreadPoolExecutor fires all requests simultaneously
**How to avoid:** Limit `max_workers` to 3-4; each auto_analyze call involves multiple sequential API calls already. The cached FMP transport mitigates FMP rate limits for repeated queries.
**Warning signs:** HTTP 429 errors, RuntimeError from FMP transport

### Pitfall 3: Probability Anchoring False Positives
**What goes wrong:** Flagging legitimate 60% probability assignments as anchoring
**Why it happens:** Some stocks genuinely warrant exactly 60% probability
**How to avoid:** The flag is `PROBABILITY_ANCHORING_SUSPECT`, not `REJECT`. It adds a methodology warning note and optionally forces to 50% only if the justification is weak (no concrete evidence for the 60% assignment). The flag should trigger human review, not automatic rejection.
**Warning signs:** Over-rejection of valid analyses

### Pitfall 4: CAGR Exception Panel Token Cost
**What goes wrong:** Running 3 full LLM agents for every 20-29.9% CAGR candidate burns excessive tokens
**Why it happens:** Exception panel uses the same heavy prompts as full analysis
**How to avoid:** Use focused, short prompts for the exception vote. Each agent gets a summary of the analysis + the specific question. Do NOT re-run full analysis/validation/review -- use the existing overlay as context.
**Warning signs:** Excessive API costs per sector scan

### Pitfall 5: Manifest vs Report Confusion
**What goes wrong:** Mixing up the scan manifest (ticker list + status) with individual ticker reports
**Why it happens:** Both are JSON files in the same output directory
**How to avoid:** Clear naming: `manifest.json` at scan root level, individual reports in per-ticker subdirectories. Structure: `data/scans/<scan-id>/manifest.json`, `data/scans/<scan-id>/<ticker>/report.json`, etc.
**Warning signs:** Tests checking wrong file paths

## Code Examples

### FMP Stock Screener Client Method
```python
# New method on FmpClient in fmp.py
def stock_screener(self, sector: str, exchange: str = "NYSE", **filters) -> list[dict]:
    """Fetch tickers in a given sector from FMP screener."""
    params = {"sector": sector, "exchange": exchange, **filters}
    payload = self._get("stock-screener", **params)
    if not isinstance(payload, list):
        raise RuntimeError(f"FMP screener response malformed for sector={sector}")
    return payload
```

### Broken-Chart Filter
```python
def apply_broken_chart_filter(
    screener_results: list[dict],
    fmp_client: FmpClient,
    threshold: float = 60.0,
) -> tuple[list[dict], list[dict]]:
    """Filter screener results by pct_off_ath >= threshold.

    Returns (survivors, filtered_out).
    Uses existing build_raw_candidate_from_fmp which computes pct_off_ath.
    """
    survivors = []
    filtered_out = []
    for company in screener_results:
        ticker = company["symbol"]
        try:
            raw_candidate = build_raw_candidate_from_fmp(ticker, fmp_client)
            pct_off_ath = raw_candidate["market_snapshot"]["pct_off_ath"]
            if pct_off_ath >= threshold:
                survivors.append(raw_candidate)
            else:
                filtered_out.append({"ticker": ticker, "pct_off_ath": pct_off_ath})
        except Exception as exc:
            filtered_out.append({"ticker": ticker, "error": str(exc)})
    return survivors, filtered_out
```

### Scan Manifest Structure
```python
# Manifest written at data/scans/<scan-id>/manifest.json
{
    "scan_id": "2026-03-10T14-30-00",
    "scan_type": "auto-scan",  # or "sector-scan"
    "sector": null,  # or "Consumer Defensive" for sector-scan
    "started_at": "2026-03-10T14:30:00",
    "completed_at": "2026-03-10T14:45:00",
    "tickers": {
        "TICKER1": {"status": "PASS", "report_path": "TICKER1/report.json"},
        "TICKER2": {"status": "FAIL", "reason": "Rejected at screening", "report_path": "TICKER2/report.json"},
        "TICKER3": {"status": "ERROR", "error": "FMP request failed"}
    },
    "summary": {
        "total": 3,
        "passed": 1,
        "failed": 1,
        "errored": 1
    }
}
```

### Evidence Quality Scoring
```python
def score_evidence_quality(overlay_candidate: dict) -> dict:
    """Count concrete vs vague citations across all provenance entries."""
    from .epistemic_reviewer import is_weak_evidence, CONCRETE_SOURCE_MARKERS

    provenance = overlay_candidate.get("provenance", [])
    total_citations = 0
    concrete_count = 0
    vague_count = 0

    for entry in provenance:
        for ref in entry.get("evidence_refs", []):
            total_citations += 1
            summary = ref.get("summary", "")
            if any(marker in summary.lower() for marker in CONCRETE_SOURCE_MARKERS):
                concrete_count += 1
            elif is_weak_evidence(summary):
                vague_count += 1

    concrete_ratio = concrete_count / total_citations if total_citations > 0 else 0.0
    methodology_warning = None
    if concrete_ratio < 0.5:  # Below 50% concrete threshold
        methodology_warning = (
            f"Evidence quality below threshold: {concrete_count}/{total_citations} "
            f"({concrete_ratio:.0%}) concrete citations. Review for methodology compliance."
        )

    return {
        "total_citations": total_citations,
        "concrete_count": concrete_count,
        "vague_count": vague_count,
        "concrete_ratio": round(concrete_ratio, 2),
        "methodology_warning": methodology_warning,
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual human review for 20% CAGR exception | 3-agent voting panel (HARD-01) | Phase 6 | Automates exception approval while maintaining safety via unanimity requirement |
| Single probability assignment | Anchoring detection + forced downgrade (HARD-02) | Phase 6 | Catches LLM tendency to default to round probability numbers |
| Manual evidence quality check | Automated citation scoring (HARD-03) | Phase 6 | Catches vague "industry reports" style evidence before it reaches pipeline |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | unittest (stdlib) |
| Config file | none -- discovered via `python -m unittest discover -s tests -v` |
| Quick run command | `python -m unittest tests.test_scanner -v` |
| Full suite command | `python -m unittest discover -s tests -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCAN-01 | auto-scan runs auto_analyze per ticker, produces reports + manifest | unit | `python -m unittest tests.test_scanner.TestAutoScan -v` | Wave 0 |
| SCAN-02 | sector-scan with hydration check, broken-chart filter, clustering, parallel auto_analyze | unit | `python -m unittest tests.test_scanner.TestSectorScan -v` | Wave 0 |
| SCAN-03 | Report output to data/scans/ with manifest | unit | `python -m unittest tests.test_scanner.TestScanManifest -v` | Wave 0 |
| HARD-01 | CAGR exception panel with 3-agent unanimous vote | unit | `python -m unittest tests.test_hardening.TestCagrExceptionPanel -v` | Wave 0 |
| HARD-02 | Probability anchoring detection | unit | `python -m unittest tests.test_hardening.TestProbabilityAnchoring -v` | Wave 0 |
| HARD-03 | Evidence quality scoring with methodology warning | unit | `python -m unittest tests.test_hardening.TestEvidenceQuality -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest tests.test_scanner tests.test_hardening -v`
- **Per wave merge:** `python -m unittest discover -s tests -v`
- **Phase gate:** Full suite green before verify-work

### Wave 0 Gaps
- [ ] `tests/test_scanner.py` -- covers SCAN-01, SCAN-02, SCAN-03
- [ ] `tests/test_hardening.py` -- covers HARD-01, HARD-02, HARD-03
- [ ] `src/edenfintech_scanner_bootstrap/scanner.py` -- new module
- [ ] `src/edenfintech_scanner_bootstrap/hardening.py` -- new module

## Open Questions

1. **FMP Stock Screener Response Shape**
   - What we know: Endpoint is `stock-screener`, it accepts sector/exchange params, it's already in cache TTLs
   - What's unclear: Exact response fields (symbol, sector, industry, price, marketCap, etc.)
   - Recommendation: Add `stock_screener()` to FmpClient, test with a fixture matching the known FMP response pattern. The profile endpoint already returns `industry` and `sector` fields -- screener likely mirrors this.

2. **Sector-Scan Clustering Strategy**
   - What we know: Requirements say "clusters survivors" before running auto_analyze "per cluster"
   - What's unclear: Whether clustering means grouping by industry/sub-sector or a more sophisticated grouping
   - Recommendation: Group by `industry` field from FMP profile data. Each industry group becomes a "cluster" for the scan-input's `cluster_name` field. This matches the existing `cluster_name` usage in pipeline.py.

3. **Evidence Quality Threshold Value**
   - What we know: HARD-03 says "below threshold adds methodology note warning"
   - What's unclear: Exact threshold percentage for concrete citations
   - Recommendation: Start with 50% (majority of citations must be concrete). This is Claude's discretion -- the planner should pick a reasonable default with config override.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: fmp.py, pipeline.py, sector.py, epistemic_reviewer.py, scoring.py, cli.py, review_package.py, live_scan.py, automation.py (Phase 5 plans)
- cache.py DEFAULT_TTLS -- confirms stock-screener endpoint exists and is cacheable
- assets/methodology/strategy-rules.md -- 20% CAGR exception rules, broken-chart 60% threshold

### Secondary (MEDIUM confidence)
- FMP API documentation (web search) -- stock-screener endpoint accepts sector/exchange params

### Tertiary (LOW confidence)
- FMP screener response shape -- inferred from profile response pattern, needs fixture validation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all stdlib, no new dependencies
- Architecture: HIGH - clear patterns from existing codebase (review_package.py, live_scan.py)
- Pitfalls: HIGH - rate limiting and bias detection patterns well understood from prior phases
- FMP screener specifics: MEDIUM - endpoint confirmed but exact response shape needs fixture

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable domain, methodology-driven)
