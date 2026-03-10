# Codebase Concerns

**Analysis Date:** 2026-03-10

## Tech Debt

**Broad Exception Handling in Judge Module:**
- Issue: Catch-all `except Exception` clause at line 231 in `src/edenfintech_scanner_bootstrap/judge.py` masks all errors with fallback behavior
- Files: `src/edenfintech_scanner_bootstrap/judge.py:231`
- Impact: Legitimate errors (missing fields, schema violations) get converted to REVISE verdict with generic fallback, making debugging difficult. Network failures and parsing errors get same treatment as code bugs.
- Fix approach: Distinguish between recoverable transport errors (which should trigger fallback) and unrecoverable validation errors (which should raise). Separate exception types for judge transport vs. response parsing.

**Monolithic Pipeline File:**
- Issue: `src/edenfintech_scanner_bootstrap/pipeline.py` (877 lines) combines screening, cluster analysis, epistemic review, report assembly, and artifact packaging with heavy nested logic
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py`
- Impact: Single change to one stage's logic may require scanning entire file. Test failures hard to isolate. Logic for decision scoring, epistemic outcome computation, and rejection packet assembly all mixed together.
- Fix approach: Extract stage implementations into separate modules (e.g., `screening.py`, `cluster.py`, `epistemic.py`, `report.py`). Each stage receives validated input dict and returns output dict. Use factory pattern to compose pipeline.

**Large Structured Analysis Module:**
- Issue: `src/edenfintech_scanner_bootstrap/structured_analysis.py` (796 lines) handles template generation, draft creation, provenance validation, finalization, review suggestions, and markdown rendering
- Files: `src/edenfintech_scanner_bootstrap/structured_analysis.py`
- Impact: Changes to provenance logic, template generation, or review workflow all require understanding entire module. Difficult to test template generation in isolation from finalization logic.
- Fix approach: Split into `structured_analysis_core.py` (validation, finalization), `template_generation.py`, and `review_workflow.py`. Each handles single concern.

**Dotenv Parser Implementation:**
- Issue: Manual regex-based `.env` file parsing in `src/edenfintech_scanner_bootstrap/config.py:_parse_dotenv_line` handles only basic `KEY=VALUE` with optional quotes
- Files: `src/edenfintech_scanner_bootstrap/config.py:21-31`
- Impact: Does not handle escaped quotes, multiline values, or comments mixed with values. If user provides `API_KEY="value # with hash"`, hash is not treated as part of value.
- Fix approach: Replace with standard library dotenv parser or explicit test coverage for edge cases. Currently only basic parsing tested.

**Multiple Validation Entry Points:**
- Issue: Schema validation logic spread across three places: inline `_require_*` validators in `pipeline.py` (lines 49-83), structured analysis validation in `structured_analysis.py`, and generic JSON schema validator in `schemas.py`
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py`, `src/edenfintech_scanner_bootstrap/structured_analysis.py`, `src/edenfintech_scanner_bootstrap/schemas.py`
- Impact: Validation rules duplicated. A field like `candidate['ticker']` validated three times in different ways. Hard to maintain single source of truth for what constitutes valid input.
- Fix approach: Consolidate validation into schema-first approach. Pipeline stages use JSON Schema validator for input, not inline helpers. Remove duplicate validation code.

---

## Known Bugs

**Regex Pattern Assumption in Judge Response Parsing:**
- Symptoms: If OpenAI judge includes "## Structured Execution Log" header but with non-ASCII spacing or extra whitespace before/after markdown fence, regex at line 156 in `src/edenfintech_scanner_bootstrap/judge.py` fails silently and returns None
- Files: `src/edenfintech_scanner_bootstrap/judge.py:155-160`
- Trigger: When OpenAI includes markdown fence with trailing spaces: ` ```json ` instead of `\`\`\`json`, or uses Unicode non-breaking space
- Workaround: Fallback to `local_judge` is in place, but execution log extraction is lost; user won't see judge reasoning

**File Encoding Inconsistency:**
- Symptoms: Some file writes specify `encoding="utf-8"` explicitly (`src/edenfintech_scanner_bootstrap/review_package.py:31`, `src/edenfintech_scanner_bootstrap/structured_analysis.py:792`), others rely on platform default
- Files: `src/edenfintech_scanner_bootstrap/live_scan.py:26`, `src/edenfintech_scanner_bootstrap/fmp.py:258`, `src/edenfintech_scanner_bootstrap/reporting.py:67`
- Trigger: Running on Windows system with non-UTF-8 default encoding could produce file I/O errors or silent data corruption on non-ASCII characters in markdown output
- Workaround: None; would require fix to all `Path.write_text()` calls

**Missing Default Market Snapshot in Field Generation:**
- Symptoms: If `raw_candidate` lacks `market_snapshot` key, code in `src/edenfintech_scanner_bootstrap/field_generation.py` silently substitutes empty dict, which may cause downstream NoneType errors
- Files: `src/edenfintech_scanner_bootstrap/field_generation.py:76`
- Trigger: If raw bundle from non-standard source (not built via `build_raw_candidate_from_fmp`) is used
- Workaround: Ensure raw bundles always come through FMP adapter; validation doesn't catch missing market_snapshot

---

## Security Considerations

**API Key Exposure in Judge Prompt:**
- Risk: Full rulebook, stage contracts, report, and execution log are sent to OpenAI API as plaintext in judge prompt at `src/edenfintech_scanner_bootstrap/judge.py:115-141`
- Files: `src/edenfintech_scanner_bootstrap/judge.py:135-140`
- Current mitigation: Private API key stored in env var; request goes over HTTPS
- Recommendations: Consider redacting sensitive fields from report before sending to judge (e.g., strip company identifying information if present), or use local judge exclusively for sensitive data. Add opt-in logging to audit what data was sent to LLM.

**Configuration Loading from Anywhere:**
- Risk: `discover_project_root()` in `src/edenfintech_scanner_bootstrap/config.py:38-53` walks up directory tree looking for `pyproject.toml` and methodology files; an attacker with write access to parent directory can inject malicious `.env`
- Files: `src/edenfintech_scanner_bootstrap/config.py:38-53`
- Current mitigation: Only environment variable or explicit path can be set; discovery is deterministic
- Recommendations: Document that `.env` file location should not be writable by unprivileged users. Consider refusing to load `.env` if file permissions are world-writable.

**No Input Size Limits:**
- Risk: Pipeline accepts arbitrary candidate counts and field list sizes. A malicious scan input with 10,000 candidates or 100MB JSON could consume all memory or timeout
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py`, `src/edenfintech_scanner_bootstrap/live_scan.py`
- Current mitigation: None; relies on operator discipline
- Recommendations: Add explicit size checks: max 100 candidates per scan, max candidate JSON size, max report size. Fail fast with clear error if limits exceeded.

---

## Performance Bottlenecks

**Full Report/Rulebook Serialization in Judge Prompt:**
- Problem: Judge receives entire `report` dict (all ranked, analysis detail, rejection packets) + entire `execution_log` + full methodology rulebook and all stage contracts as JSON strings in single prompt at `src/edenfintech_scanner_bootstrap/judge.py:200`
- Files: `src/edenfintech_scanner_bootstrap/judge.py:135-140`
- Cause: Rulebook alone can be 20KB+; with report 500KB+, entire prompt can exceed 1.5MB, causing OpenAI API latency of 30+ seconds for tokenization and inference
- Improvement path: Send only critical excerpts (e.g., ranked candidates + execution summary, not full execution_log). Cache rulebook/contracts across judge calls. Use gpt-4-turbo instead of gpt-5-codex if available for faster processing.

**Repeated JSON Serialization:**
- Problem: Pipeline calls `json.dumps()` on full candidate bundles multiple times: once in FMP adapter, once during merge, once during enrichment, once during import, once during final report assembly
- Files: `src/edenfintech_scanner_bootstrap/fmp.py:223`, `src/edenfintech_scanner_bootstrap/gemini.py`, `src/edenfintech_scanner_bootstrap/live_scan.py`, `src/edenfintech_scanner_bootstrap/importers.py`
- Cause: No intermediate representation; each stage re-parses JSON from disk
- Improvement path: Keep bundles as dicts in memory across stage boundaries; only serialize to JSON for checkpointing or output.

**Gemini Evidence Context Rebuilding:**
- Problem: `_candidate_evidence_context()` in `src/edenfintech_scanner_bootstrap/structured_analysis.py:66-85` reconstructs evidence count dict on every call by iterating all evidence arrays
- Files: `src/edenfintech_scanner_bootstrap/structured_analysis.py:66-85`
- Cause: Function called per candidate in template generation; with 50 candidates, iterates 350+ list items to compute 7 counts each time
- Improvement path: Compute context once during merge and cache in `fmp_context`/`gemini_context`.

---

## Fragile Areas

**Provenance Status Transitions:**
- Files: `src/edenfintech_scanner_bootstrap/structured_analysis.py:705-724`
- Why fragile: Finalization logic assumes all MACHINE_DRAFT fields must have review_note before promotion to HUMAN_EDITED or HUMAN_CONFIRMED. But if intermediate stage or external tool edits provenance array, status field might be missing or in unexpected state. No guards against partial updates or concurrent modifications.
- Safe modification: Always validate provenance array schema before finalization. Use immutable field names; never allow deleting/reordering provenance items. Add test for finalization with missing/corrupt status fields.
- Test coverage: Tests exist for happy path finalization but no tests for malformed provenance (e.g., missing status key, duplicate field_path, review_note on non-draft items).

**Scanning Mode Validation:**
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py:38`, `src/edenfintech_scanner_bootstrap/fmp.py:216`
- Why fragile: `VALID_SCAN_MODES` constant at pipeline.py:38 is static string set, but `scan_parameters.scan_mode` can be any string. If new scanning mode is added to contracts but not to pipeline.py, validation passes but pipeline crashes downstream.
- Safe modification: Make scan mode validation schema-driven from contracts. Pipeline should validate against schema, not hardcoded set.
- Test coverage: No regression tests verify that added scan mode to contract causes validation failure in pipeline.

**Epistemic Question Answer Validation:**
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py:152-166`, `src/edenfintech_scanner_bootstrap/schemas.py`
- Why fragile: Epistemic review answers hardcoded to `{"Yes", "No"}` in VALID_ANSWERS at pipeline.py:37. If methodology changes to allow "Maybe" or "N/A", all validation code must be updated.
- Safe modification: Derive VALID_ANSWERS from schema/contract, not hardcoded set. Use schema validation instead of inline `_require_nonempty_string` + manual enum check.
- Test coverage: Tests validate Yes/No answers but no tests verify that invalid answer strings are rejected before reaching scoring.

**Cluster Status Enumeration:**
- Files: `src/edenfintech_scanner_bootstrap/field_generation.py:177-195`, `src/edenfintech_scanner_bootstrap/pipeline.py`
- Why fragile: Field generation drafts cluster_status as one of hardcoded strings (CLEAR_WINNER, HIDDEN_GEM, etc.), but pipeline validation doesn't verify these match contract enums
- Safe modification: Validate generated overlay against schema immediately after generation; catch enum mismatches before finalization.
- Test coverage: No tests verify that generated field values match contract constraints.

---

## Scaling Limits

**Candidate Count Growth:**
- Current capacity: Pipeline tested with up to 20 candidates per scan; no known hard limit
- Limit: At 500+ candidates, report JSON exceeds 5MB, judge transport times out (>60s). Memory usage of pipeline dict structures exceeds 500MB.
- Scaling path: Implement batch processing—split candidates into cohorts of 50, run screening/cluster/epistemic per cohort, then aggregate results. Cache intermediate results per cohort. Use streaming JSON parser for large reports.

**Raw Bundle Size:**
- Current capacity: ~50KB per candidate (FMP profile + quote + statements + Gemini context)
- Limit: At 200 candidates, merged bundle exceeds 10MB; filesystem operations slow to >5 seconds per write
- Scaling path: Implement streaming JSON write for bundles. Compress large bundles with gzip. Move to columnar format (parquet) for faster filtering.

**Provenance Tracking Overhead:**
- Current capacity: Field provenance array adds ~5% overhead per field; with 50 candidates and 20 provenance entries per candidate, tracking arrays total 50KB per scan
- Limit: At 1000 candidates, provenance overhead becomes 5MB+; finalization validation becomes O(n²) to check all provenance paths
- Scaling path: Implement lazy provenance—only track selected fields; use hash digest instead of full provenance objects for immutable entries; store provenance separately from overlay.

---

## Dependencies at Risk

**Google Gemini SDK Version:**
- Risk: `DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"` is hardcoded in `src/edenfintech_scanner_bootstrap/gemini.py:14`; if Google deprecates preview model or changes API, code breaks
- Impact: Gemini bundle generation fails; pipeline cannot proceed without manual model name update and re-testing
- Migration plan: Load model name from contract/config instead of hardcoded constant. Add version negotiation—check model availability before use. Fall back to last-known-stable model if preferred not available.

**OpenAI API Endpoint Assumption:**
- Risk: Judge uses `/v1/responses` endpoint at `src/edenfintech_scanner_bootstrap/judge.py:166`, which may not exist in future OpenAI API versions
- Impact: OpenAI judge calls fail; fallback to local judge, losing semantic review capability
- Migration plan: Parameterize endpoint URL in config. Test endpoint availability on startup. Document fallback behavior explicitly.

---

## Missing Critical Features

**No Audit Trail for Human Review Changes:**
- Problem: When operator adds `review_note` to provenance entries, no record of who changed what or when (besides finalization metadata)
- Blocks: Cannot reconstruct review decisions; difficult to answer "who approved this field?" or "when was this consensus reached?"
- Impact: Limited accountability; if error traced to field, no way to know if human reviewer was asked or changed their mind later

**No Dry-Run Mode:**
- Problem: Pipeline must run to completion; no way to validate that scan input would pass all checks without generating full report and judge calls
- Blocks: Users cannot preview pipeline behavior or check for data quality issues before committing compute
- Impact: Wasted API quota on invalid inputs; no early feedback during review phase

**No Candidate Diff Tool:**
- Problem: If raw bundles change between rescans (e.g., FMP updated financials), no tool shows what changed and how it affects analysis
- Blocks: Cannot assess impact of data updates before re-running full pipeline
- Impact: Operator must manually compare JSON files or re-run redundant scans

---

## Test Coverage Gaps

**FMP Adapter Integration:**
- What's not tested: Network error handling beyond basic URLError. Timeout behavior. Handling of partial responses (e.g., profile missing but quote present). Response with non-standard capitalization keys (FMP API may return camelCase variations).
- Files: `src/edenfintech_scanner_bootstrap/fmp.py`
- Risk: Unknown FMP API variants could silently skip field extraction; downstream validation would catch but with poor error messages.
- Priority: High—FMP is critical data source

**Judge Response Parsing Variants:**
- What's not tested: Judge responses with markdown code fence variations (tabs, trailing spaces, Unicode). Responses where JSON is embedded in narrative text (not isolated in fence). Partial JSON responses.
- Files: `src/edenfintech_scanner_bootstrap/judge.py:155-160`
- Risk: OpenAI API format shifts or user error in judge prompting could cause silent loss of judge reasoning
- Priority: Medium—fallback exists but loses data

**Provenance Finalization Edge Cases:**
- What's not tested: Finalization of partial overlays (missing fields vs. missing provenance). Finalization with conflicting review_note and status. Re-finalization of already-finalized overlay. Finalization with empty structured_candidates.
- Files: `src/edenfintech_scanner_bootstrap/structured_analysis.py:695-733`
- Risk: Malformed finalized overlay could pass validation but fail during pipeline execution
- Priority: High—finalized overlays are hard to fix after generation

**Rejection Packet Assembly:**
- What's not tested: Rejection packets with missing optional fields (score, epistemic). Rejection due to multiple independent reasons (how does rejection_reason combine them?). Rejection reason not found in valid codes.
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py:238-280`
- Risk: Report could include rejection packets with missing keys; judge validation would catch but message unclear
- Priority: Medium—affects data quality reporting

**Cluster Analysis Tie-Breaking:**
- What's not tested: Clustering with identical scores. Clustering with 100+ candidates (tie-breaking algorithm behavior at scale). Clustering where threshold exactly equals scores (boundary conditions).
- Files: `src/edenfintech_scanner_bootstrap/pipeline.py` (cluster logic)
- Risk: Determinism assumption violated—same input might rank candidates differently on different runs if ties exist
- Priority: High—determinism is core guarantee
