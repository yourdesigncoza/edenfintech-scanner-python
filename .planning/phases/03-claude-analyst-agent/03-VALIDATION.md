---
phase: 3
slug: claude-analyst-agent
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-10
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python unittest (stdlib) |
| **Config file** | None — unittest discovery |
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
| 03-01-01 | 01 | 1 | AGNT-02 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_llm_draft_schema_valid -v` | W0 | pending |
| 03-01-01 | 01 | 1 | AGNT-02 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_finalization_transitions_llm_draft -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-01 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_all_placeholders_filled -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-05 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_output_validates_schema -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-03 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_all_fields_have_review_notes -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-03 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_review_notes_cite_evidence -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-04 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_worst_case_before_base_case -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-04 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_bear_before_bull -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-01 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_with_sector_knowledge -v` | W0 | pending |
| 03-01-02 | 01 | 1 | AGNT-05 | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_enriched_codex_fields_present -v` | W0 | pending |
| 03-01-03 | 01 | 1 | AGNT-01 | integration | `python -c "from edenfintech_scanner_bootstrap.live_scan import build_review_package; print('OK')"` | W0 | pending |
| 03-01-03 | 01 | 1 | AGNT-01 | cli | `python -m edenfintech_scanner_bootstrap.cli --help 2>&1 \| grep use-analyst` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_analyst.py` — test stubs for AGNT-01 through AGNT-05
- [ ] `tests/fixtures/analyst/` — fixture LLM response payloads for transport injection
- [ ] Update `structured-analysis.schema.json` provenance status enum to include `LLM_DRAFT`
- [ ] Update `REQUIRED_PROVENANCE_FIELDS` to include enriched Codex fields from Phase 1
- [ ] Add `anthropic_api_key` / `ANALYST_MODEL` to `AppConfig` and `.env.example`

*Wave 0 items are prerequisites that must be implemented before other waves can run tests.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Evidence citation quality | AGNT-03 | Requires human judgment on citation relevance | Review 3+ overlay outputs and verify review_notes cite meaningful, relevant sources |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
