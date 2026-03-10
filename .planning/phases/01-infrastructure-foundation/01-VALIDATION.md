---
phase: 1
slug: infrastructure-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python unittest (stdlib) |
| **Config file** | None (unittest discovery) |
| **Quick run command** | `python -m unittest discover -s tests -v` |
| **Full suite command** | `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m unittest discover -s tests -v`
- **After every plan wave:** Run `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | CACHE-01..04 | unit | `python -m unittest tests.test_cache -v` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | SCHM-01..06 | unit | `python -m unittest tests.test_schema_enrichment -v` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 0 | SCHM-07,08 | unit | `python -m unittest tests.test_scan_pipeline.TestPipelineGates -v` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | CACHE-01 | unit | `python -m unittest tests.test_cache.TestFmpCache.test_cached_response_returned -v` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | CACHE-01 | unit | `python -m unittest tests.test_cache.TestFmpCache.test_expired_cache_refetches -v` | ❌ W0 | ⬜ pending |
| 1-01-06 | 01 | 1 | CACHE-02 | unit | `python -m unittest tests.test_cache.TestFmpCache.test_fresh_flag_bypasses -v` | ❌ W0 | ⬜ pending |
| 1-01-07 | 01 | 1 | CACHE-03 | unit | `python -m unittest tests.test_cache.TestFmpCache.test_empty_response_not_cached -v` | ❌ W0 | ⬜ pending |
| 1-01-08 | 01 | 1 | CACHE-03 | unit | `python -m unittest tests.test_cache.TestFmpCache.test_error_response_not_cached -v` | ❌ W0 | ⬜ pending |
| 1-01-09 | 01 | 1 | CACHE-04 | unit | `python -m unittest tests.test_cache.TestCacheCli.test_cache_status_output -v` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | SCHM-01 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_catalyst_stack_validation -v` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | SCHM-02 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_invalidation_triggers -v` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 1 | SCHM-03 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_decision_memo -v` | ❌ W0 | ⬜ pending |
| 1-02-04 | 02 | 1 | SCHM-04 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_issues_and_fixes_array -v` | ❌ W0 | ⬜ pending |
| 1-02-05 | 02 | 1 | SCHM-05 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_setup_pattern -v` | ❌ W0 | ⬜ pending |
| 1-02-06 | 02 | 1 | SCHM-06 | unit | `python -m unittest tests.test_schema_enrichment.TestSchemaEnrichment.test_stretch_case -v` | ❌ W0 | ⬜ pending |
| 1-02-07 | 02 | 1 | SCHM-07 | unit | `python -m unittest tests.test_scan_pipeline.TestPipelineGates.test_rejects_no_hard_medium_catalysts -v` | ❌ W0 | ⬜ pending |
| 1-02-08 | 02 | 1 | SCHM-08 | unit | `python -m unittest tests.test_scan_pipeline.TestPipelineGates.test_rejects_all_announced_only -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cache.py` — stubs for CACHE-01 through CACHE-04
- [ ] `tests/test_schema_enrichment.py` — stubs for SCHM-01 through SCHM-06
- [ ] Update `tests/test_scan_pipeline.py` with `TestPipelineGates` class — stubs for SCHM-07, SCHM-08
- [ ] Update existing test fixtures in `tests/fixtures/raw/` and `tests/fixtures/generated/` to include new schema fields
- [ ] Update regression fixtures in `assets/fixtures/regression/` to include new schema fields

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
