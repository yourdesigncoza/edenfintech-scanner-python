# Architecture

**Analysis Date:** 2026-03-10

## Pattern Overview

**Overall:** Deterministic data-processing pipeline with layered transformations and stage contracts.

**Key Characteristics:**
- Data retrieval abstraction layer insulating core pipeline from external APIs
- Structured JSON-based contracts enforcing input/output shapes at each pipeline stage
- Transactional design: raw bundles → overlays → enriched bundles → scan inputs → scored reports
- Raw bundle fingerprints flow through entire system for traceability
- JSON-first approach: markdown outputs are rendered views of validated JSON structures
- Pluggable transports for external API calls (testable without real network calls)

## Layers

**Data Retrieval Layer:**
- Purpose: Fetch quantitative and qualitative research data from external sources
- Location: `src/edenfintech_scanner_bootstrap/fmp.py`, `src/edenfintech_scanner_bootstrap/gemini.py`
- Contains: HTTP clients (FmpClient, GeminiClient) with configurable transports; adapter logic to normalize API responses into consistent schemas
- Depends on: External APIs (FMP, Gemini), config for credentials
- Used by: `live_scan.py` (orchestrator), `review_package.py` (main workflow)
- Key abstraction: FmpTransport and GeminiTransport are callables; real HTTP is default but tests inject fixtures

**Raw Bundle Integration Layer:**
- Purpose: Merge FMP (quantitative: prices, revenue, FCF) and Gemini (qualitative: catalysts, risks, moat, management) into single ranked candidate structure
- Location: `src/edenfintech_scanner_bootstrap/gemini.py` (merge_fmp_and_gemini_bundles)
- Contains: Merging logic with shared fingerprint tracking
- Depends on: FMP bundle, Gemini bundle
- Used by: `live_scan.py`, integration tests

**Structured Analysis Layer:**
- Purpose: Generate machine-drafted overlays from raw bundles; manage review lifecycle (DRAFT → reviewed → FINALIZED)
- Location: `src/edenfintech_scanner_bootstrap/field_generation.py`, `src/edenfintech_scanner_bootstrap/structured_analysis.py`
- Contains:
  - `field_generation.py`: Draft generation from raw bundles (machine-generated provenance, evidence refs)
  - `structured_analysis.py`: Template creation, draft validation, finalization workflow, review checklists, note suggestions
- Depends on: Raw merged bundle, methodology rules
- Used by: `live_scan.py`, `review_package.py`, CLI commands for review

**Importer/Enrichment Layer:**
- Purpose: Map raw bundles and structured overlays into deterministic scan input format
- Location: `src/edenfintech_scanner_bootstrap/importers.py`
- Contains: `build_scan_input()` creates candidate screening/analysis/epistemic payloads from enriched bundles
- Depends on: Merged bundle, optional finalized structured analysis
- Used by: `live_scan.py`, pipeline stage

**Scoring & Analysis Layer:**
- Purpose: Execute 5-stage deterministic pipeline on structured inputs
- Location: `src/edenfintech_scanner_bootstrap/pipeline.py`, `src/edenfintech_scanner_bootstrap/scoring.py`
- Contains:
  - `scoring.py`: Financial formulas (CAGR, target price, floor price, decision score, confidence bands)
  - `pipeline.py`: Screening (5 checks) → cluster analysis → epistemic review → report assembly → judge callback
- Depends on: Scan input payload, judge config
- Used by: `live_scan.py`, `review_package.py`

**Reporting & Output Layer:**
- Purpose: Render JSON reports into markdown; build execution logs; write artifacts to disk
- Location: `src/edenfintech_scanner_bootstrap/reporting.py`
- Contains: Markdown rendering functions, execution log formatting
- Depends on: Report JSON, execution log entries
- Used by: `pipeline.py`, `live_scan.py`, `review_package.py`

**Orchestration Layer:**
- Purpose: Coordinate multi-stage workflows and manage artifact directories
- Location: `src/edenfintech_scanner_bootstrap/live_scan.py`, `src/edenfintech_scanner_bootstrap/review_package.py`, `src/edenfintech_scanner_bootstrap/cli.py`
- Contains:
  - `live_scan.py`: Main scan workflow (fetch → merge → template/draft → scan input → report) with stop points
  - `review_package.py`: Wraps `live_scan.py` with review-specific outputs (checklists, note suggestions) and finalized-overlay reuse logic
  - `cli.py`: Thin argparse entry point routing to orchestrators and lower-level functions
- Depends on: All layers below
- Used by: External operators via CLI

**Supporting Layer:**
- Purpose: Shared utilities, config, schema validation, asset loading, testing infrastructure
- Location: `src/edenfintech_scanner_bootstrap/{assets,config,schemas,validation,regression,judge}.py`
- Contains:
  - `config.py`: AppConfig loads from dotenv; manages API keys
  - `assets.py`: Path helpers for methodology/contract/schema files
  - `schemas.py`: JSON Schema validation wrapper
  - `validation.py`: Asset integrity checks (contracts, schemas, rules alignment)
  - `judge.py`: OpenAI judge or fallback deterministic judge for final verdicts
  - `regression.py`: Fixture-based regression suite

## Data Flow

**Full Scan Workflow:**

1. User invokes `build-review-package TICKER --out-dir DIR`
2. Orchestrator creates `raw/`, `review/`, `final/` directories
3. **Retrieval**: FmpClient fetches quotes/profiles/financials; GeminiClient fetches research
4. **Merge**: Raw FMP + Gemini bundles merged with fingerprint tracking
5. **Template Generation**: Structured analysis template created from merged bundle
6. **Draft Generation**: Machine-generated overlay with evidence refs and provenance entries
7. **Stop Point (raw-bundle)**: If `--stop-at raw-bundle`, writes FMP/Gemini/merged/template/draft to `raw/`
8. User reviews `review/review-checklist.md` and `review/review-note-suggestions.md`
9. User calls `finalize-structured-analysis OVERLAY --reviewer NAME` to promote reviewed overlay
10. Orchestrator re-runs with `--structured-analysis-path FINALIZED_OVERLAY`:
11. **Enrichment**: Finalized overlay merged with raw bundle
12. **Scan Input**: Enriched bundle converted to deterministic scan format
13. **Screening**: 5-check framework (solvency, dilution, revenue_growth, roic, valuation)
14. **Cluster Analysis**: Eliminates candidates per cluster rules
15. **Epistemic Review**: PCS framework adjusts probabilities based on risk type friction
16. **Scoring**: Decision score = return_component - risk_component
17. **Report Assembly**: Builds final JSON report with ranked candidates
18. **Judge**: OpenAI (if API_KEY) or deterministic fallback adds verdict
19. **Markdown Rendering**: JSON report rendered to human-readable markdown
20. **Stop Point (report)**: Writes enriched, scan-input, report, execution-log, judge to `final/`

**State Management:**

- **Raw bundles are immutable**: Fingerprints ensure traceability through pipeline
- **Structured analysis lifecycle**: DRAFT (machine-generated) → MACHINE_DRAFT with review_notes → HUMAN_CONFIRMED or HUMAN_EDITED
- **Finalized overlays are reused**: When re-running with `--structured-analysis-path`, raw bundles are copied (not re-fetched) to preserve fingerprint continuity
- **JSON is source of truth**: Each stage output is validated against JSON Schema before passing to next stage
- **Markdown artifacts are derived**: Never commit markdown back to pipeline; always regenerate from JSON

## Key Abstractions

**Raw Bundle:**
- Purpose: Normalized container for API responses from FMP + Gemini
- Examples: `src/edenfintech_scanner_bootstrap/fmp.py:build_fmp_bundle_with_config()`, `src/edenfintech_scanner_bootstrap/gemini.py:build_gemini_bundle_with_config()`
- Pattern: Dict with ticker → candidate → {fmp_context, gemini_context, market_snapshot, fingerprint}

**Structured Analysis (Overlay):**
- Purpose: Human-reviewed enhancements to raw bundle; tracks provenance per field
- Examples: `src/edenfintech_scanner_bootstrap/structured_analysis.py`
- Pattern: Dict with candidates → per-candidate field provenance entries (status, rationale, evidence_refs, review_note)
- Lifecycle: Templates (empty shell) → Drafts (machine-filled) → Finalized (human-reviewed)

**Scan Input:**
- Purpose: Fully-formed payload for deterministic pipeline
- Examples: `src/edenfintech_scanner_bootstrap/importers.py:build_scan_input()`
- Pattern: Dict with candidates → screening/analysis/epistemic sections
- Contract: Validated against `assets/methodology/scan-input.schema.json`

**Scan Report:**
- Purpose: Final JSON output from pipeline
- Examples: `src/edenfintech_scanner_bootstrap/pipeline.py:run_scan()`
- Pattern: Dict with ranked_candidates, rejected_at_screening, rejected_at_analysis_detail_packets, pending_human_review
- Contract: Validated against `assets/methodology/scan-report.schema.json`

**Stage Contract:**
- Purpose: Enforce input/output shapes at each pipeline stage
- Examples: `assets/contracts/{screening,cluster_analysis,epistemic_review,report_assembly,codex_final_judge}.json`
- Pattern: JSON Schema + descriptive text
- Usage: `validate_assets()` ensures contracts are syntactically valid; stage implementations must conform

## Entry Points

**CLI Entry Point:**
- Location: `src/edenfintech_scanner_bootstrap/cli.py:main()`
- Triggers: `python -m edenfintech_scanner_bootstrap <command>`
- Responsibilities: Route command → handler function; emit JSON or markdown to stdout

**Main Workflow Entry Points:**
- `build-review-package`: Calls `src/edenfintech_scanner_bootstrap/review_package.py:build_review_package()` → full operator workflow
- `run-live-scan`: Calls `src/edenfintech_scanner_bootstrap/live_scan.py:run_live_scan()` → faster, no review artifacts
- `run-scan`: Calls `src/edenfintech_scanner_bootstrap/pipeline.py:run_scan_file()` → pipeline-only, expects pre-built scan input

**Testing Entry Points:**
- `validate-assets`: Calls `src/edenfintech_scanner_bootstrap/validation.py:validate_assets()`
- `run-regression`: Calls `src/edenfintech_scanner_bootstrap/regression.py:run_regression_suite()`

## Error Handling

**Strategy:** Fail fast with descriptive errors; no silent fallbacks except judge (API errors fall back to deterministic).

**Patterns:**

- **Schema validation failures**: `SchemaValidationError` from `schemas.py` includes path to offending field
- **External API failures**: `RuntimeError` with endpoint name, HTTP status, and error body preview
- **Required field missing**: `ValueError` with full path (e.g., "candidates[0].ticker")
- **Judge failures**: If OpenAI API fails, falls back to deterministic judge without exception
- **File I/O failures**: Explicit mkdirs with `parents=True, exist_ok=True`; no implicit path creation elsewhere

## Cross-Cutting Concerns

**Logging:**
- Approach: No framework; execution logs are manually-built lists of strings
- `pipeline.py` appends messages to `execution_log_entries` (e.g., "TICKER: passed screening")
- Exported as JSON in execution log with candidate count and survivor count
- Markdown rendering in `reporting.py` formats entries as ordered list

**Validation:**
- JSON Schema validation at stage boundaries (scan-input, scan-report, structured-analysis)
- Asset validation checks methodology-assets agreement (`canonical-rulebook.json` vs `strategy-rules.md`)
- Field-level type coercion with explicit errors (no None coalescing)

**Authentication:**
- Approach: Environment variables via dotenv
- `config.py:load_config()` loads FMP_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY (optional), CODEX_JUDGE_MODEL
- Secrets never logged; only used in transport calls
- Config object passed through orchestration layers

**Methodological Alignment:**
- If contracts/rules conflict with code, **`assets/methodology/strategy-rules.md` is the source of truth**
- All screening checks, epistemic multipliers, decision score formulas come from assets
- Code implementation mirrors methodology markdown exactly

---

*Architecture analysis: 2026-03-10*
