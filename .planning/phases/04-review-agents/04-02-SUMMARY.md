---
phase: 04-review-agents
plan: 02
subsystem: validation
tags: [red-team, contradiction-detection, adversarial-validation, anthropic, constrained-decoding]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: "AppConfig with anthropic_api_key, transport-injectable pattern"
  - phase: 03-analyst-agent
    provides: "Analyst overlay structure (analysis_inputs, screening_inputs)"
provides:
  - "detect_contradictions() deterministic FMP-vs-overlay comparison"
  - "RedTeamValidatorClient with 5 adversarial questions"
  - "validate_overlay() top-level flow (contradictions first, then LLM)"
  - "APPROVE/REJECT verdict pattern with objections array"
affects: [05-pipeline-integration, 06-automation-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns: [transport-injectable-client, deterministic-before-llm, safe-overlay-filtering]

key-files:
  created:
    - src/edenfintech_scanner_bootstrap/validator.py
    - tests/test_validator.py
    - tests/fixtures/validator/llm-response-fixture.json
  modified: []

key-decisions:
  - "Used shares_m_latest (actual FMP field name) instead of diluted_shares_m from plan"
  - "Safe overlay filtering via allowlist (analysis_inputs, screening_inputs, epistemic_inputs) rather than blocklist to prevent score leakage"
  - "Revenue direction check uses keyword matching against thesis_summary and margin_trend_gate"

patterns-established:
  - "Deterministic-before-LLM: always run pure-Python checks first, feed results into LLM context"
  - "Safe payload filtering: allowlist approach for what enters LLM context, never blocklist"

requirements-completed: [VALD-01, VALD-02, VALD-03]

# Metrics
duration: 6min
completed: 2026-03-10
---

# Phase 4 Plan 2: Red-Team Validator Summary

**Deterministic contradiction detection (4 FMP checks with thresholds) plus LLM-powered adversarial 5-question red-team validator producing APPROVE/REJECT verdicts**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-10T17:38:06Z
- **Completed:** 2026-03-10T17:44:30Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments
- Deterministic contradiction detection compares revenue (10%/50%), FCF margin (5pp/10pp), revenue direction, and share count (5%) against FMP data
- 5 adversarial red-team questions with structured output (question_id, challenge, evidence, severity)
- REJECT verdict carries specific objections array, APPROVE carries empty objections
- Validator provably blind to pipeline scores via allowlist filtering
- Contradictions run deterministically first and feed into LLM context

## Task Commits

Each task was committed atomically (TDD: test then feat):

1. **Task 1: Deterministic contradiction detection**
   - `25cbc2d` (test: failing tests for contradiction detection)
   - `655c598` (feat: implement deterministic contradiction detection)
2. **Task 2: RedTeamValidatorClient and validate_overlay**
   - `008b1fa` (test: failing tests for client and flow)
   - `282ff03` (feat: implement client, 5 questions, validate_overlay)

## Files Created/Modified
- `src/edenfintech_scanner_bootstrap/validator.py` - Red-team validator with detect_contradictions(), RedTeamValidatorClient, validate_overlay() (329 lines)
- `tests/test_validator.py` - 20 tests covering contradiction thresholds, client behavior, APPROVE/REJECT paths, score exclusion (297 lines)
- `tests/fixtures/validator/llm-response-fixture.json` - REJECT fixture with 5 questions and 2 objections (39 lines)

## Decisions Made
- Used `shares_m_latest` (actual FMP derived field name) instead of `diluted_shares_m` referenced in plan -- the plan used a conceptual name, the codebase uses `shares_m_latest`
- Implemented allowlist-based payload filtering rather than blocklist -- only `analysis_inputs`, `screening_inputs`, `epistemic_inputs`, `ticker`, `evidence_context`, and `field_provenance` are passed to the LLM, preventing any future score field additions from leaking
- Revenue direction check scans thesis_summary and margin_trend_gate for decline-related keywords rather than requiring a specific structured field

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed system prompt containing forbidden substring "ranking"**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** User prompt description "no scores or rankings" contained the word "ranking" which triggered the test checking for forbidden payload keys
- **Fix:** Changed prompt text to "pipeline output excluded" to avoid false positive
- **Files modified:** src/edenfintech_scanner_bootstrap/validator.py
- **Verification:** test_request_payload_excludes_scores passes
- **Committed in:** 282ff03

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor text change in prompt, no functional impact.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Validator module ready for pipeline integration
- Both review agents (epistemic reviewer + red-team validator) now complete
- validate_overlay() provides the top-level entry point for integration

---
*Phase: 04-review-agents*
*Completed: 2026-03-10*
