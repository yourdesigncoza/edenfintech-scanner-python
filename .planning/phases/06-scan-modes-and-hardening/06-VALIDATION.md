---
phase: 6
slug: scan-modes-and-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
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

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | SCAN-01 | unit | `python -m unittest tests.test_scanner.TestAutoScan -v` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | SCAN-02 | unit | `python -m unittest tests.test_scanner.TestSectorScan -v` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | SCAN-03 | unit | `python -m unittest tests.test_scanner.TestScanManifest -v` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 2 | HARD-01 | unit | `python -m unittest tests.test_hardening.TestCagrExceptionPanel -v` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | HARD-02 | unit | `python -m unittest tests.test_hardening.TestProbabilityAnchoring -v` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 2 | HARD-03 | unit | `python -m unittest tests.test_hardening.TestEvidenceQuality -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_scanner.py` — stubs for SCAN-01, SCAN-02, SCAN-03
- [ ] `tests/test_hardening.py` — stubs for HARD-01, HARD-02, HARD-03

*Existing infrastructure (unittest discover, fixtures/) covers framework needs.*

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
