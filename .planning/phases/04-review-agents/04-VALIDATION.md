---
phase: 4
slug: review-agents
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 4 — Validation Strategy

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
| 04-01-01 | 01 | 1 | EPST-01 | unit | `python -m unittest tests.test_epistemic_reviewer.TestInformationBarrier.test_restricted_input_rejects_forbidden_fields -v` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | EPST-01 | unit | `python -m unittest tests.test_epistemic_reviewer.TestInformationBarrier.test_function_signature_type_check -v` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | EPST-02 | unit | `python -m unittest tests.test_epistemic_reviewer.TestEpistemicReview.test_five_pcs_answers_complete -v` | ❌ W0 | ⬜ pending |
| 04-01-04 | 01 | 1 | EPST-03 | unit | `python -m unittest tests.test_epistemic_reviewer.TestEpistemicReview.test_evidence_anchoring -v` | ❌ W0 | ⬜ pending |
| 04-01-05 | 01 | 1 | EPST-04 | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_weak_evidence_detection -v` | ❌ W0 | ⬜ pending |
| 04-01-06 | 01 | 1 | EPST-05 | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_no_evidence_friction -v` | ❌ W0 | ⬜ pending |
| 04-01-07 | 01 | 1 | EPST-06 | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_laundering_detection -v` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | VALD-01 | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_five_questions_answered -v` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | VALD-02 | unit | `python -m unittest tests.test_validator.TestContradictionDetection.test_revenue_contradiction -v` | ❌ W0 | ⬜ pending |
| 04-02-03 | 02 | 1 | VALD-02 | unit | `python -m unittest tests.test_validator.TestContradictionDetection.test_within_threshold_no_flag -v` | ❌ W0 | ⬜ pending |
| 04-02-04 | 02 | 1 | VALD-03 | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_reject_with_objections -v` | ❌ W0 | ⬜ pending |
| 04-02-05 | 02 | 1 | VALD-03 | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_approve_clean -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_epistemic_reviewer.py` — stubs for EPST-01 through EPST-06
- [ ] `tests/test_validator.py` — stubs for VALD-01 through VALD-03
- [ ] `tests/fixtures/reviewer/` — fixture LLM response payloads for transport injection
- [ ] `tests/fixtures/validator/` — fixture LLM response payloads for transport injection

*Existing unittest infrastructure covers framework needs.*

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
