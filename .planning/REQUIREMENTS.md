# Requirements: EdenFintech Scanner — LLM Integration

**Defined:** 2026-03-10
**Core Value:** Remove the human from the analysis loop — Claude agents fill, validate, and assess structured analysis overlays while the deterministic pipeline ensures reproducible scoring and methodology compliance.

## v1 Requirements

Requirements for full integration. Each maps to roadmap phases.

### Caching

- [ ] **CACHE-01**: FMP responses cached per-endpoint per-ticker with configurable TTLs (price-history 1d, screener/ratios/metrics/ev 7d, profile/peers 30d, financials 90d)
- [ ] **CACHE-02**: `--fresh` flag bypasses cache for individual calls
- [ ] **CACHE-03**: Empty/error responses never cached
- [ ] **CACHE-04**: CLI commands `cache-status` and `cache-clear`

### Schema

- [ ] **SCHM-01**: `catalyst_stack[]` with typed entries (HARD/MEDIUM/SOFT + description + timeline)
- [ ] **SCHM-02**: `invalidation_triggers[]` with falsifying evidence
- [ ] **SCHM-03**: `decision_memo` (better_than_peer, safer_than_peer, what_makes_wrong)
- [ ] **SCHM-04**: `issues_and_fixes[]` with evidence status enum (ANNOUNCED_ONLY/ACTION_UNDERWAY/EARLY_RESULTS_VISIBLE/PROVEN)
- [ ] **SCHM-05**: `setup_pattern` enum (SOLVENCY_SCARE/QUALITY_FRANCHISE/NARRATIVE_DISCOUNT/NEW_OPERATOR/OTHER)
- [ ] **SCHM-06**: `stretch_case` (same shape as base_case: bear/base/stretch per Codex 05-VALUATION.md)
- [ ] **SCHM-07**: Pipeline gate rejects if catalyst_stack has zero HARD/MEDIUM entries
- [ ] **SCHM-08**: Pipeline gate rejects if all issues_and_fixes are ANNOUNCED_ONLY

### Sector Knowledge

- [ ] **SECT-01**: `sector.py` module with `hydrate_sector()`, `load_sector_knowledge()`, `check_sector_freshness()`
- [ ] **SECT-02**: Sector schema with per-sub-sector: key metrics, valuation approach, regulatory landscape, historical precedents, moat sources, kill factors, FCF margin ranges, typical multiples
- [ ] **SECT-03**: Gemini grounded search integration (8 queries per sub-sector via google-genai SDK)
- [ ] **SECT-04**: Storage at `data/sectors/<sector-slug>/knowledge.json` with `data/sectors/registry.json` and 180-day staleness threshold
- [ ] **SECT-05**: CLI commands `hydrate-sector` and `sector-status`

### Analyst Agent

- [ ] **AGNT-01**: Claude analyst agent fills all `__REQUIRED__` placeholders from raw bundle + sector knowledge
- [ ] **AGNT-02**: Provenance status `LLM_DRAFT` distinct from `MACHINE_DRAFT`
- [ ] **AGNT-03**: Every field has `review_note` citing specific evidence
- [ ] **AGNT-04**: Worst case generated BEFORE base case, bear thesis BEFORE bull (prompt discipline)
- [ ] **AGNT-05**: Output validates against structured-analysis schema via constrained decoding

### Epistemic Reviewer

- [ ] **EPST-01**: Code-enforced information barrier — function signature excludes scores, probabilities, valuations
- [ ] **EPST-02**: 5 PCS answers with justification + evidence per answer
- [ ] **EPST-03**: Evidence anchoring: each answer cites named source or declares NO_EVIDENCE
- [ ] **EPST-04**: WEAK_EVIDENCE detection for vague citations without concrete source
- [ ] **EPST-05**: Additional -1 friction if >= 3 of 5 answers are NO_EVIDENCE
- [ ] **EPST-06**: PCS laundering detection (>80% evidence source overlap with analyst)

### Red-Team Validator

- [ ] **VALD-01**: Answers 5 Codex red-team questions as structured output
- [ ] **VALD-02**: Contradiction detection: cross-check analyst assumptions against raw FMP data
- [ ] **VALD-03**: Can REJECT overlay with specific objections or APPROVE

### Automation

- [ ] **AUTO-01**: `auto_analyze(ticker, config)` orchestrates fetch → sector → analyst → validator → epistemic → finalize
- [ ] **AUTO-02**: Rejected overlays retry with validator objections (max 2 retries)
- [ ] **AUTO-03**: New provenance statuses: LLM_DRAFT, LLM_CONFIRMED, LLM_EDITED in structured_analysis.py
- [ ] **AUTO-04**: `finalize_structured_analysis()` accepts `reviewer="llm:<model-id>"`

### Scan Modes

- [ ] **SCAN-01**: `auto-scan TICKER [TICKER...]` runs auto_analyze per ticker → pipeline → judge → report
- [ ] **SCAN-02**: `sector-scan "Sector"` with hydration check, broken-chart filter (60%+ off ATH), industry exclusion, clustering, parallel auto_analyze per cluster
- [ ] **SCAN-03**: Report output to `data/scans/json/` + `data/scans/` (markdown) with manifest per scan run

### Hardening

- [ ] **HARD-01**: 20% CAGR exception panel — analyst, validator, epistemic reviewer each independently vote; unanimous approval required; full reasoning logged
- [ ] **HARD-02**: Probability anchoring detection — flag PROBABILITY_ANCHORING_SUSPECT when exactly 60% + friction risk type; require justification; force to 50% if weak
- [ ] **HARD-03**: Evidence quality scoring — count concrete citations vs vague references; below threshold adds methodology note warning

### Holding Review

- [ ] **HOLD-01**: Forward return refresh — recompute target price and forward CAGR from current price + original valuation inputs
- [ ] **HOLD-02**: Thesis integrity checklist — improved, degraded, unchanged, invalidated (matched against invalidation_triggers)
- [ ] **HOLD-03**: Sell trigger evaluation — target reached + forward <30% hurdle; rapid rerating + forward <10-15%/yr; thesis break
- [ ] **HOLD-04**: Replacement gate computation — Gate A: forward CAGR delta >15pp; Gate B: downside profile equal or better
- [ ] **HOLD-05**: Fresh-capital vs legacy weight tracking (current_weight vs fresh_capital_max_weight)
- [ ] **HOLD-06**: CLI command `review-holding TICKER [TICKER...]`

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Batch Operations

- **BATC-01**: Full NYSE scan (`full-scan`) across all sectors
- **BATC-02**: Scheduled scan runs with configurable frequency

### Observability

- **OBSV-01**: Token usage tracking and cost reporting per scan run
- **OBSV-02**: Agent rejection rate monitoring as system health metric
- **OBSV-03**: Validator rejection rate calibration (target: 15-30%)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web UI / dashboard | CLI-only tool; JSON/markdown reports are sufficient and auditable |
| Real-time data streaming | Codex methodology is batch-oriented; value investing uses quarterly data |
| Portfolio tracking / brokerage integration | Analysis tool, not execution tool; operator trades manually |
| Fine-tuned financial LLMs | General-purpose Claude + structured prompts + methodology rules outperforms; locks model version |
| Autonomous trading / auto-execution | LLM calibration issues (ECE 0.12-0.40) make auto-execution dangerous |
| Chat-based agent interaction | Agents fill structured schemas deterministically; chat introduces variability |
| Agent memory across sessions | Each scan must be independently reproducible from raw data |
| Multi-user auth | Single-operator tool |
| Mobile app | Desktop CLI |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CACHE-01 | — | Pending |
| CACHE-02 | — | Pending |
| CACHE-03 | — | Pending |
| CACHE-04 | — | Pending |
| SCHM-01 | — | Pending |
| SCHM-02 | — | Pending |
| SCHM-03 | — | Pending |
| SCHM-04 | — | Pending |
| SCHM-05 | — | Pending |
| SCHM-06 | — | Pending |
| SCHM-07 | — | Pending |
| SCHM-08 | — | Pending |
| SECT-01 | — | Pending |
| SECT-02 | — | Pending |
| SECT-03 | — | Pending |
| SECT-04 | — | Pending |
| SECT-05 | — | Pending |
| AGNT-01 | — | Pending |
| AGNT-02 | — | Pending |
| AGNT-03 | — | Pending |
| AGNT-04 | — | Pending |
| AGNT-05 | — | Pending |
| EPST-01 | — | Pending |
| EPST-02 | — | Pending |
| EPST-03 | — | Pending |
| EPST-04 | — | Pending |
| EPST-05 | — | Pending |
| EPST-06 | — | Pending |
| VALD-01 | — | Pending |
| VALD-02 | — | Pending |
| VALD-03 | — | Pending |
| AUTO-01 | — | Pending |
| AUTO-02 | — | Pending |
| AUTO-03 | — | Pending |
| AUTO-04 | — | Pending |
| SCAN-01 | — | Pending |
| SCAN-02 | — | Pending |
| SCAN-03 | — | Pending |
| HARD-01 | — | Pending |
| HARD-02 | — | Pending |
| HARD-03 | — | Pending |
| HOLD-01 | — | Pending |
| HOLD-02 | — | Pending |
| HOLD-03 | — | Pending |
| HOLD-04 | — | Pending |
| HOLD-05 | — | Pending |
| HOLD-06 | — | Pending |

**Coverage:**
- v1 requirements: 47 total
- Mapped to phases: 0
- Unmapped: 47 ⚠️

---
*Requirements defined: 2026-03-10*
*Last updated: 2026-03-10 after initial definition*
