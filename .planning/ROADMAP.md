# Roadmap: EdenFintech Scanner — LLM Integration

## Overview

Transform the existing deterministic Python scanner into a fully automated LLM-powered stock analysis pipeline. Starting with infrastructure prerequisites (caching, enriched schemas), then building the agent layer (analyst, reviewer, validator), wiring them into an automated flow, and extending to scan modes and holding review. Each phase delivers a testable capability that unblocks the next. The integration plan's 10-step sequence drives the ordering; parallelizable steps are merged into single phases.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Infrastructure Foundation** - FMP caching layer and Codex-aligned schema enrichments with pipeline gates
- [ ] **Phase 2: Sector Knowledge Framework** - Gemini grounded search sector hydration with storage, staleness tracking, and CLI
- [ ] **Phase 3: Claude Analyst Agent** - LLM agent that fills structured analysis overlays from raw bundles and sector knowledge
- [ ] **Phase 4: Review Agents** - Architecturally blind epistemic reviewer and adversarial red-team validator
- [ ] **Phase 5: Automated Finalization** - End-to-end orchestration wiring analyst, validator, and epistemic reviewer with retry loop
- [ ] **Phase 6: Scan Modes and Hardening** - Individual and sector scan commands plus bias detection and evidence quality gates
- [ ] **Phase 7: Holding Review** - Forward return refresh, thesis integrity, sell triggers, and replacement gate computation

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: Developer can iterate on downstream agent work without burning API quota, and all JSON schemas enforce the full Codex field contract
**Depends on**: Nothing (first phase)
**Requirements**: CACHE-01, CACHE-02, CACHE-03, CACHE-04, SCHM-01, SCHM-02, SCHM-03, SCHM-04, SCHM-05, SCHM-06, SCHM-07, SCHM-08
**Success Criteria** (what must be TRUE):
  1. Running `cache-status` reports per-endpoint cache counts and TTL expiry dates for cached tickers
  2. Second FMP retrieval for the same ticker/endpoint returns cached data without an API call; `--fresh` bypasses the cache and fetches live
  3. Empty or error FMP responses are never written to cache (verified by fixture test)
  4. `validate-assets` passes with enriched schemas containing catalyst_stack, invalidation_triggers, decision_memo, issues_and_fixes, setup_pattern, and stretch_case
  5. Pipeline rejects a scan-input with zero HARD/MEDIUM catalyst_stack entries and rejects when all issues_and_fixes are ANNOUNCED_ONLY
**Plans**: TBD

Plans:
- [ ] 01-01: FMP caching layer
- [ ] 01-02: Schema enrichments and pipeline gates

### Phase 2: Sector Knowledge Framework
**Goal**: Operator can hydrate sector research via CLI and the pipeline loads validated sector knowledge for any previously hydrated sector
**Depends on**: Phase 1 (uses cached FMP screener for sector discovery)
**Requirements**: SECT-01, SECT-02, SECT-03, SECT-04, SECT-05
**Success Criteria** (what must be TRUE):
  1. `hydrate-sector "Consumer Defensive"` produces a validated JSON file at `data/sectors/consumer-defensive/knowledge.json` with per-sub-sector metrics, valuation approach, moat sources, and kill factors
  2. `sector-status` reports hydration dates per sector and flags sectors older than 180 days as stale
  3. `load_sector_knowledge()` returns structured sector data that passes schema validation and includes Gemini grounded search results
**Plans**: TBD

Plans:
- [ ] 02-01: Sector module, schema, and Gemini grounded search integration

### Phase 3: Claude Analyst Agent
**Goal**: An LLM agent fills all required structured analysis fields from raw evidence with per-field provenance and evidence citations
**Depends on**: Phase 1 (enriched schemas), Phase 2 (sector knowledge)
**Requirements**: AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05
**Success Criteria** (what must be TRUE):
  1. Given a fixture raw bundle, the analyst produces a structured analysis overlay where every `__REQUIRED__` placeholder is replaced with evidence-grounded values
  2. Every field in the overlay has a `review_note` citing a specific named source from the raw bundle or sector knowledge
  3. Provenance entries carry status `LLM_DRAFT` (distinct from `MACHINE_DRAFT`)
  4. Output passes `validate_structured_analysis()` schema validation including all enriched Codex fields (catalyst_stack, decision_memo, etc.)
  5. Worst-case scenario is generated before base case, and bear thesis before bull thesis (verifiable in output field ordering)
**Plans**: TBD

Plans:
- [ ] 03-01: Agent base infrastructure and analyst agent

### Phase 4: Review Agents
**Goal**: Two independent review layers challenge the analyst's output — one adversarially, one with architectural blindness — before any overlay can be finalized
**Depends on**: Phase 3 (analyst output to review)
**Requirements**: EPST-01, EPST-02, EPST-03, EPST-04, EPST-05, EPST-06, VALD-01, VALD-02, VALD-03
**Success Criteria** (what must be TRUE):
  1. Epistemic reviewer function signature provably excludes scores, probabilities, valuations, and numeric targets (type-level enforcement, not prompt)
  2. Epistemic reviewer produces 5 PCS answers each with justification and evidence citation (or explicit NO_EVIDENCE declaration); >= 3 NO_EVIDENCE answers trigger additional -1 friction
  3. WEAK_EVIDENCE detection flags answers with vague citations lacking concrete sources; PCS laundering detection flags > 80% evidence source overlap with analyst
  4. Red-team validator answers 5 Codex questions as structured output and can REJECT an overlay with specific objections or APPROVE it
  5. Validator detects contradictions between analyst assumptions and raw FMP data (e.g., claimed revenue growth contradicted by 3-year decline in financials)
**Plans**: TBD

Plans:
- [ ] 04-01: Epistemic reviewer agent
- [ ] 04-02: Red-team validator agent

### Phase 5: Automated Finalization
**Goal**: A single function call replaces the entire human review workflow — fetch, analyze, validate, review, and finalize without manual intervention
**Depends on**: Phase 4 (all three agents)
**Requirements**: AUTO-01, AUTO-02, AUTO-03, AUTO-04
**Success Criteria** (what must be TRUE):
  1. `auto_analyze(ticker, config)` executes the full flow: fetch raw bundles, load sector knowledge, run analyst, run validator, run epistemic reviewer, finalize overlay
  2. When the validator rejects an overlay, the analyst re-runs with validator objections injected (up to 2 retries), then proceeds to epistemic review
  3. Finalized overlays carry provenance status `LLM_CONFIRMED` and `finalize_structured_analysis()` accepts `reviewer="llm:<model-id>"`
  4. The finalized overlay passes all existing pipeline validation and can be consumed by `apply_structured_analysis()` identically to a human-produced overlay
**Plans**: TBD

Plans:
- [ ] 05-01: Automation orchestrator and provenance lifecycle

### Phase 6: Scan Modes and Hardening
**Goal**: Operator can scan individual tickers or entire sectors from the CLI, with bias detection and evidence quality gates preventing unchecked LLM optimism
**Depends on**: Phase 5 (automated finalization flow)
**Requirements**: SCAN-01, SCAN-02, SCAN-03, HARD-01, HARD-02, HARD-03
**Success Criteria** (what must be TRUE):
  1. `auto-scan TICKER` runs auto_analyze per ticker through the deterministic pipeline and judge, producing JSON + markdown reports in `data/scans/`
  2. `sector-scan "Sector"` checks hydration, applies broken-chart filter (60%+ off ATH), excludes filtered industries, clusters survivors, and runs parallel auto_analyze per cluster
  3. Each scan run writes a manifest file listing all processed tickers with pass/fail status
  4. 20% CAGR exception panel triggers unanimous 3-agent vote with full reasoning logged; non-unanimous results stay in pending_review
  5. Probability anchoring detection flags PROBABILITY_ANCHORING_SUSPECT when analyst assigns exactly 60% with friction-carrying risk type; evidence quality scoring adds methodology warning when concrete citations fall below threshold
**Plans**: TBD

Plans:
- [ ] 06-01: Individual and sector scan CLI commands
- [ ] 06-02: Edge case hardening (CAGR exception, anchoring, evidence quality)

### Phase 7: Holding Review
**Goal**: Operator can review existing holdings for thesis integrity, sell triggers, and replacement opportunities using the full infrastructure
**Depends on**: Phase 6 (scan modes for replacement candidates)
**Requirements**: HOLD-01, HOLD-02, HOLD-03, HOLD-04, HOLD-05, HOLD-06
**Success Criteria** (what must be TRUE):
  1. `review-holding TICKER` recomputes target price and forward CAGR from current price using original valuation inputs
  2. Thesis integrity checklist produces structured improved/degraded/unchanged/invalidated assessment matched against the holding's invalidation_triggers
  3. Sell triggers fire correctly: target reached with forward < 30% hurdle, rapid rerating with forward < 10-15%/yr, thesis break from invalidation_triggers
  4. Replacement gate computes Gate A (forward CAGR delta > 15pp) and Gate B (downside profile equal or better) with appropriate flags
  5. Output includes fresh_capital_max_weight alongside current_weight for legacy vs fresh capital comparison
**Plans**: TBD

Plans:
- [ ] 07-01: Holding review module and CLI command

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 0/2 | Not started | - |
| 2. Sector Knowledge Framework | 0/1 | Not started | - |
| 3. Claude Analyst Agent | 0/1 | Not started | - |
| 4. Review Agents | 0/2 | Not started | - |
| 5. Automated Finalization | 0/1 | Not started | - |
| 6. Scan Modes and Hardening | 0/2 | Not started | - |
| 7. Holding Review | 0/1 | Not started | - |
