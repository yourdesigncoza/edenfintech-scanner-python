---
phase: 06-scan-modes-and-hardening
plan: 01
subsystem: analysis
tags: [hardening, bias-detection, cagr-exception, evidence-quality, probability-anchoring]

requires:
  - phase: 04-review-agents
    provides: epistemic_reviewer with CONCRETE_SOURCE_MARKERS and is_weak_evidence
provides:
  - detect_probability_anchoring for flagging LLM anchoring bias at 60% with friction risk
  - score_evidence_quality for counting concrete vs vague citations in overlay provenance
  - cagr_exception_panel for 3-agent unanimous vote on CAGR exceptions
  - ExceptionVote and ExceptionPanelResult frozen dataclasses
affects: [06-02, pipeline-integration]

tech-stack:
  added: []
  patterns: [transport-injection for multi-agent voting, reuse of epistemic_reviewer evidence markers]

key-files:
  created:
    - src/edenfintech_scanner_bootstrap/hardening.py
    - tests/test_hardening.py
  modified: []

key-decisions:
  - "Lightweight direct transport calls for CAGR panel instead of full client classes to avoid heavy analysis cost"
  - "Reuse CONCRETE_SOURCE_MARKERS and is_weak_evidence from epistemic_reviewer for DRY evidence quality scoring"

patterns-established:
  - "Multi-agent voting via transport injection: each agent gets focused prompt, returns JSON vote"
  - "Frozen dataclasses for vote results to ensure immutability"

requirements-completed: [HARD-01, HARD-02, HARD-03]

duration: 4min
completed: 2026-03-10
---

# Phase 6 Plan 1: Hardening Gates Summary

**CAGR exception panel with 3-agent unanimous vote, probability anchoring detection at 60% + friction risk, and evidence quality scoring with concrete/vague citation counting**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-10T18:24:37Z
- **Completed:** 2026-03-10T18:29:03Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Probability anchoring detector flags exactly 60% base probability with friction-carrying risk types as PROBABILITY_ANCHORING_SUSPECT
- Evidence quality scorer counts concrete vs vague citations using epistemic_reviewer markers, warns below 50% threshold
- CAGR exception panel runs 3 independent agent votes (analyst, validator, epistemic) via transport injection, requires unanimous approval

## Task Commits

Each task was committed atomically:

1. **Task 1: Deterministic hardening** - `94d90ef` (test RED) + `381a632` (feat GREEN)
2. **Task 2: CAGR exception panel** - `05357b6` (test RED) + `bb19a99` (feat GREEN)

_TDD tasks each have separate test and implementation commits._

## Files Created/Modified
- `src/edenfintech_scanner_bootstrap/hardening.py` - Three hardening gates: detect_probability_anchoring, score_evidence_quality, cagr_exception_panel with ExceptionVote/ExceptionPanelResult dataclasses
- `tests/test_hardening.py` - 16 unit tests across TestProbabilityAnchoring (6), TestEvidenceQuality (5), TestCagrExceptionPanel (5)

## Decisions Made
- Used lightweight direct transport calls for CAGR panel instead of full ClaudeAnalystClient/RedTeamValidatorClient/EpistemicReviewerClient to avoid heavy analysis cost per research pitfall 4
- Reused CONCRETE_SOURCE_MARKERS and is_weak_evidence from epistemic_reviewer for DRY evidence quality scoring

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Hardening gates ready for integration into scan pipeline
- Transport injection pattern consistent with analyst/validator/epistemic clients for easy wiring

---
*Phase: 06-scan-modes-and-hardening*
*Completed: 2026-03-10*
