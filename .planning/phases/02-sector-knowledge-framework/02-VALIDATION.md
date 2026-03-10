---
phase: 2
slug: sector-knowledge-framework
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 2 — Validation Strategy

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
| 02-01-01 | 01 | 1 | SECT-02 | unit | `python -m unittest tests.test_sector.TestSectorSchema.test_valid_knowledge_passes -v` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | SECT-02 | unit | `python -m unittest tests.test_sector.TestSectorSchema.test_missing_fields_rejected -v` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | SECT-01 | unit | `python -m unittest tests.test_sector.TestHydrateSector.test_produces_valid_knowledge -v` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | SECT-01 | unit | `python -m unittest tests.test_sector.TestLoadSectorKnowledge.test_loads_and_validates -v` | ❌ W0 | ⬜ pending |
| 02-01-05 | 01 | 1 | SECT-01 | unit | `python -m unittest tests.test_sector.TestSectorFreshness.test_stale_detection -v` | ❌ W0 | ⬜ pending |
| 02-01-06 | 01 | 1 | SECT-03 | unit | `python -m unittest tests.test_sector.TestGeminiSectorQueries.test_grounded_search_per_category -v` | ❌ W0 | ⬜ pending |
| 02-01-07 | 01 | 1 | SECT-03 | unit | `python -m unittest tests.test_sector.TestGeminiSectorQueries.test_eight_queries_per_sub_sector -v` | ❌ W0 | ⬜ pending |
| 02-01-08 | 01 | 1 | SECT-04 | unit | `python -m unittest tests.test_sector.TestSectorStorage.test_knowledge_path -v` | ❌ W0 | ⬜ pending |
| 02-01-09 | 01 | 1 | SECT-04 | unit | `python -m unittest tests.test_sector.TestSectorStorage.test_registry_updated -v` | ❌ W0 | ⬜ pending |
| 02-01-10 | 01 | 1 | SECT-04 | unit | `python -m unittest tests.test_sector.TestSectorFreshness.test_180_day_threshold -v` | ❌ W0 | ⬜ pending |
| 02-01-11 | 01 | 1 | SECT-05 | unit | `python -m unittest tests.test_sector.TestSectorCli.test_hydrate_sector_command -v` | ❌ W0 | ⬜ pending |
| 02-01-12 | 01 | 1 | SECT-05 | unit | `python -m unittest tests.test_sector.TestSectorCli.test_sector_status_command -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_sector.py` — all SECT-01 through SECT-05 test stubs
- [ ] `tests/fixtures/sector/` — fixture data for sector knowledge (mock Gemini responses, sample knowledge.json)
- [ ] `assets/methodology/sector-knowledge.schema.json` — new schema file
- [ ] Update `assets.py` with `sector_knowledge_schema_path()` helper
- [ ] Add `data/` to `.gitignore`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Gemini grounded search returns valid sourced evidence | SECT-03 | Requires API key and network | Run `hydrate-sector "Consumer Defensive" --sub-sectors "Household Products"` with valid GEMINI_API_KEY |
| CLI output formatting readable | SECT-05 | Visual inspection | Run `sector-status` and verify human-readable output |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
