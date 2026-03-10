---
phase: 7
slug: holding-review
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | unittest (stdlib) |
| **Config file** | none — uses `python -m unittest discover` |
| **Quick run command** | `python -m unittest tests.test_holding_review -v` |
| **Full suite command** | `python -m unittest discover -s tests -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest tests.test_holding_review -v`
- **After every plan wave:** Run `python -m unittest discover -s tests -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | HOLD-01 | unit | `python -m unittest tests.test_holding_review.TestForwardRefresh -v` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | HOLD-02 | unit | `python -m unittest tests.test_holding_review.TestThesisIntegrity -v` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 1 | HOLD-03 | unit | `python -m unittest tests.test_holding_review.TestSellTriggers -v` | ❌ W0 | ⬜ pending |
| 07-01-04 | 01 | 1 | HOLD-04 | unit | `python -m unittest tests.test_holding_review.TestReplacementGate -v` | ❌ W0 | ⬜ pending |
| 07-01-05 | 01 | 1 | HOLD-05 | unit | `python -m unittest tests.test_holding_review.TestFreshCapitalWeight -v` | ❌ W0 | ⬜ pending |
| 07-01-06 | 01 | 1 | HOLD-06 | unit | `python -m unittest tests.test_holding_review.TestCLI -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_holding_review.py` — stubs for HOLD-01 through HOLD-06
- [ ] No framework install needed — uses stdlib unittest

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
