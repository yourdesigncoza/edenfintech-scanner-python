---
phase: 6
slug: scan-modes-and-hardening
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-10
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | unittest (stdlib) |
| **Config file** | none — discovered via `python -m unittest discover` |
| **Quick run command** | `python -m unittest tests.test_scanner tests.test_hardening -v` |
| **Full suite command** | `python -m unittest discover -s tests -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest tests.test_scanner tests.test_hardening -v`
- **After every plan wave:** Run `python -m unittest discover -s tests -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 06-01-01 | 01 | 1 | HARD-02 | unit | `python -m unittest tests.test_hardening.TestProbabilityAnchoring tests.test_hardening.TestEvidenceQuality -v` | pending |
| 06-01-02 | 01 | 1 | HARD-01, HARD-03 | unit | `python -m unittest tests.test_hardening.TestCagrExceptionPanel -v` | pending |
| 06-02-01 | 02 | 2 | SCAN-01, SCAN-02, SCAN-03 | unit | `python -m unittest tests.test_scanner -v` | pending |
| 06-02-02 | 02 | 2 | SCAN-01, SCAN-02 | unit + smoke | `python -m unittest tests.test_scanner.TestCliDispatch -v` | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

No Wave 0 stubs needed. Both plans use `tdd="true"` tasks that create test files as part of the RED phase of TDD execution. Test files (`tests/test_hardening.py`, `tests/test_scanner.py`) are created inline by their respective plan tasks.

*Existing infrastructure (unittest discover, fixtures/) covers framework needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 — not applicable (TDD tasks create tests inline)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
