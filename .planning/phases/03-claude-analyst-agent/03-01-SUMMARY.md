---
phase: 03-claude-analyst-agent
plan: 01
subsystem: analysis
tags: [claude, anthropic, llm, constrained-decoding, structured-analysis, provenance]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: schema enrichment with Codex fields and provenance system
provides:
  - ClaudeAnalystClient with mock transport support
  - Constrained decoding schema builder for structured analysis
  - LLM_DRAFT provenance lifecycle (create, validate, finalize)
  - generate_llm_analysis_draft function for overlay generation
  - --use-analyst CLI flag for build-review-package
  - generate-llm-analysis-draft standalone CLI subcommand
affects: [04-epistemic-validator, 05-automation-flow, 06-scan-modes-hardening]

# Tech tracking
tech-stack:
  added: [anthropic-sdk]
  patterns: [analyst-transport-injection, constrained-decoding-schema-builder, post-validate-ordering]

key-files:
  created:
    - src/edenfintech_scanner_bootstrap/analyst.py
    - tests/test_analyst.py
    - tests/test_llm_draft_provenance.py
    - tests/fixtures/analyst/llm-response-fixture.json
  modified:
    - src/edenfintech_scanner_bootstrap/structured_analysis.py
    - src/edenfintech_scanner_bootstrap/config.py
    - src/edenfintech_scanner_bootstrap/live_scan.py
    - src/edenfintech_scanner_bootstrap/cli.py
    - src/edenfintech_scanner_bootstrap/review_package.py
    - assets/methodology/structured-analysis.schema.json
    - .env.example

key-decisions:
  - "AppConfig new fields have defaults to avoid breaking existing test call sites"
  - "DRAFT_PROVENANCE_STATUSES set used for both validation and finalization checks"
  - "Transport injection pattern mirrors GeminiClient for testability"
  - "Constrained decoding schema strips minLength/minimum/maximum/minItems/maxItems/maxLength"
  - "Post-validation checks raw response text ordering, not parsed JSON structure"

patterns-established:
  - "AnalystTransport callable type for mock/live transport injection"
  - "_strip_unsupported_constraints recursively cleans schemas for constrained decoding"
  - "_post_validate checks raw text ordering before JSON parse for discipline enforcement"

requirements-completed: [AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05]

# Metrics
duration: 21min
completed: 2026-03-10
---

# Phase 3 Plan 1: Claude Analyst Agent Summary

**ClaudeAnalystClient with constrained decoding schema builder, LLM_DRAFT provenance lifecycle, fixture-backed tests, and CLI wiring via --use-analyst flag**

## Performance

- **Duration:** 21 min
- **Started:** 2026-03-10T17:18:18Z
- **Completed:** 2026-03-10T17:39:22Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments
- LLM_DRAFT provenance status fully integrated into schema validation, finalization, and coverage checks
- ClaudeAnalystClient with transport injection, constrained decoding schema builder, and raw-text ordering validation
- 37 new tests (9 provenance + 28 analyst) covering all AGNT requirements with zero regressions (151 total pass)
- CLI wiring: --use-analyst flag on build-review-package and standalone generate-llm-analysis-draft command

## Task Commits

Each task was committed atomically:

1. **Task 1: LLM_DRAFT provenance status and config additions** - `7afcb28` (feat)
2. **Task 2: Analyst module with schema builder, test fixtures, and raw-text ordering validation** - `1827e98` (feat)
3. **Task 3: Wire analyst into live_scan.py and CLI** - `f391df9` (feat)

## Files Created/Modified
- `src/edenfintech_scanner_bootstrap/analyst.py` - ClaudeAnalystClient, schema builder, evidence extraction, post-validation
- `src/edenfintech_scanner_bootstrap/structured_analysis.py` - DRAFT_PROVENANCE_STATUSES, updated finalize and validate
- `src/edenfintech_scanner_bootstrap/config.py` - anthropic_api_key and analyst_model with defaults
- `src/edenfintech_scanner_bootstrap/live_scan.py` - use_analyst parameter routing to analyst client
- `src/edenfintech_scanner_bootstrap/cli.py` - --use-analyst flag and generate-llm-analysis-draft subcommand
- `src/edenfintech_scanner_bootstrap/review_package.py` - use_analyst passthrough to run_live_scan
- `assets/methodology/structured-analysis.schema.json` - LLM_DRAFT in provenance status enum
- `.env.example` - ANTHROPIC_API_KEY and ANALYST_MODEL entries
- `tests/test_analyst.py` - 28 tests for analyst module including AGNT-01 through AGNT-05
- `tests/test_llm_draft_provenance.py` - 9 tests for LLM_DRAFT provenance lifecycle
- `tests/fixtures/analyst/llm-response-fixture.json` - Realistic LLM response fixture with ordering constraints

## Decisions Made
- AppConfig new fields (anthropic_api_key, analyst_model) given defaults to avoid breaking 20+ existing test call sites
- DRAFT_PROVENANCE_STATUSES set pattern chosen over individual status checks for extensibility
- Transport injection mirrors GeminiClient pattern for consistency
- Post-validation checks raw text ordering (substring position) rather than JSON key order for genuine ordering discipline enforcement

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added use_analyst passthrough to review_package.py**
- **Found during:** Task 3 (CLI wiring)
- **Issue:** Plan specified wiring in live_scan.py and cli.py but build_review_package also calls run_live_scan and needs the flag
- **Fix:** Added use_analyst parameter to build_review_package and passthrough to run_live_scan
- **Files modified:** src/edenfintech_scanner_bootstrap/review_package.py
- **Verification:** Import test passes, CLI help shows flag
- **Committed in:** f391df9 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Essential for correct end-to-end CLI wiring. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. ANTHROPIC_API_KEY only needed for live analyst invocation.

## Next Phase Readiness
- Analyst agent framework complete, ready for epistemic validator (Phase 4)
- All provenance lifecycle transitions tested for both MACHINE_DRAFT and LLM_DRAFT
- Transport injection pattern enables testing without live API keys

---
*Phase: 03-claude-analyst-agent*
*Completed: 2026-03-10*
