---
phase: 8
slug: wire-fmp-cache-into-auto-scan
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | unittest (stdlib) |
| **Config file** | none — stdlib discovery |
| **Quick run command** | `python -m unittest tests.test_cache tests.test_scanner tests.test_automation -v` |
| **Full suite command** | `python -m unittest discover -s tests -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest tests.test_cache tests.test_scanner tests.test_automation -v`
- **After every plan wave:** Run `python -m unittest discover -s tests -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 0 | CACHE-01/02/03 | unit | `python -m unittest tests.test_scanner.TestAutoScanCache tests.test_scanner.TestSectorScanCache -v` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | CACHE-01 | unit | `python -m unittest tests.test_scanner.TestAutoScanCache.test_transport_forwarded -v` | ❌ W0 | ⬜ pending |
| 08-01-03 | 01 | 1 | CACHE-01 | unit | `python -m unittest tests.test_scanner.TestSectorScanCache.test_transport_forwarded -v` | ❌ W0 | ⬜ pending |
| 08-01-04 | 01 | 1 | CACHE-02 | unit | `python -m unittest tests.test_scanner.TestAutoScanCache.test_fresh_flag_forwarded -v` | ❌ W0 | ⬜ pending |
| 08-01-05 | 01 | 1 | CACHE-03 | unit | `python -m unittest tests.test_scanner.TestAutoScanCache.test_empty_not_cached -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_scanner.py::TestAutoScanCache` — new test class covering CACHE-01/02/03 for auto_scan path
- [ ] `tests/test_scanner.py::TestSectorScanCache` — new test class covering CACHE-01 for sector_scan path (screener + auto_analyze both cached)
- [ ] Verify existing tests in test_scanner.py and test_automation.py still pass unchanged

*Existing infrastructure covers test framework needs.*

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
