---
phase: 5
slug: automated-finalization
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | unittest (stdlib) |
| **Config file** | none — standard discovery |
| **Quick run command** | `python -m unittest tests.test_automation -v` |
| **Full suite command** | `python -m unittest discover -s tests -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest tests.test_automation -v && python -m unittest tests.test_structured_analysis -v`
- **After every plan wave:** Run `python -m unittest discover -s tests -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | AUTO-03 | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_confirmed_accepted -v` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | AUTO-03 | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_draft_to_llm_confirmed -v` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | AUTO-04 | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_reviewer_format -v` | ❌ W0 | ⬜ pending |
| 05-01-04 | 01 | 1 | AUTO-02 | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_retry_on_reject -v` | ❌ W0 | ⬜ pending |
| 05-01-05 | 01 | 1 | AUTO-02 | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_max_retries_exceeded -v` | ❌ W0 | ⬜ pending |
| 05-01-06 | 01 | 1 | AUTO-01 | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_full_flow -v` | ❌ W0 | ⬜ pending |
| 05-01-07 | 01 | 1 | AUTO-01 | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_no_sector_knowledge -v` | ❌ W0 | ⬜ pending |
| 05-01-08 | 01 | 1 | AUTO-04 | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_finalized_overlay_applies -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_automation.py` — stubs for AUTO-01, AUTO-02, AUTO-04
- [ ] Extend `tests/test_structured_analysis.py` — stubs for AUTO-03, AUTO-04 finalization paths
- [ ] Test fixtures with mock transports for analyst, validator, epistemic reviewer

*Existing test infrastructure covers framework and discovery.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
