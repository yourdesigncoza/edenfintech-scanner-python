# Project Research Summary

**Project:** EdenFintech Scanner -- LLM Agent Integration
**Domain:** LLM-augmented financial stock scanning pipeline (value investing, NYSE)
**Researched:** 2026-03-10
**Confidence:** HIGH

## Executive Summary

This project integrates LLM agents (Claude for analysis/review/validation, Gemini for grounded search) into an existing deterministic financial scanning pipeline. The existing codebase is deliberately dependency-free (stdlib-only Python 3.11+) with a clean overlay abstraction where LLM agents slot into exactly the position the human analyst currently occupies. The recommended approach adds only 4 direct dependencies (anthropic, google-genai, pydantic, requests), uses the Anthropic SDK's native structured output enforcement to guarantee schema compliance, and keeps all orchestration as plain Python -- no agent frameworks. The architecture is a linear pipeline (analyst -> validator -> epistemic reviewer) with one retry loop, not a graph.

The key risk is that LLM agents will produce output that is syntactically valid but semantically wrong -- unit confusion in financial fields, probability anchoring at 60-70%, fabricated citations, and rubber-stamp validation. These are well-documented LLM failure modes in financial analysis. Mitigation requires layered defenses: code-enforced information barriers (function signature gating, not prompts), deterministic cross-validation of LLM output against raw FMP data, and structured inter-agent communication (typed JSON objections, not free-form text). The existing pipeline's provenance and fingerprint tracking system provides the foundation for full traceability through the agent layer.

The integration plan's 10-step sequence is architecturally sound and should be followed as-is. Steps 1-3 (caching, schema enrichments, sector knowledge) are infrastructure prerequisites. Steps 4-6 (analyst, epistemic reviewer, validator) are the core agent layer. Step 7 (automated finalization) is the "remove the human" moment. Steps 8-10 (scan modes, edge case hardening, holding review) add operational breadth. The first 7 steps deliver a working end-to-end automated scanner for individual tickers.

## Key Findings

### Recommended Stack

The stack adds exactly 4 runtime dependencies to a previously zero-dependency codebase. This is the minimum viable set -- no frameworks, no wrappers.

**Core technologies:**
- `anthropic >=0.84.0`: Claude agent calls -- native structured output via `.parse()` with Pydantic models, prompt caching support
- `google-genai >=1.66.0`: Gemini grounded search for sector knowledge -- replaces deprecated `google-generativeai` (EOL Nov 2025)
- `pydantic >=2.12.0`: Agent response contracts at the Python type level, generates JSON Schema for existing validation infrastructure
- `requests >=2.31.0`: FMP HTTP with connection pooling via `Session` -- replaces raw `urllib` for FMP only

**Critical decisions:**
- Sync-only (no async). `concurrent.futures.ThreadPoolExecutor` for parallelism. Rate limits make async pointless.
- Plain Python orchestration. No LangChain, CrewAI, or agent frameworks. The flow is a for-loop with one retry, not a graph.
- Pydantic models as single source of truth for agent output schemas, generating JSON Schema for backward compatibility with existing `schemas.py`.
- Do NOT refactor existing `gemini.py`. Add `google-genai` SDK only in new `sector.py` and epistemic reviewer modules.

### Expected Features

**Must have (table stakes):**
- Structured output enforcement via Claude constrained decoding (eliminates parse errors)
- Evidence-grounded field population with concrete `evidence_refs` per provenance entry
- Code-enforced epistemic blindness (function signature gating, not prompt-based)
- Per-endpoint FMP caching with TTLs (ports original scanner's proven pattern)
- Red-team validator agent with structured contradiction detection
- Provenance lifecycle extension: `LLM_DRAFT`, `LLM_CONFIRMED`, `LLM_EDITED`
- Schema enrichments: `catalyst_stack`, `invalidation_triggers`, `decision_memo`, `issues_and_fixes`
- End-to-end automated finalization without human intervention

**Should have (differentiators):**
- Probability anchoring detection and correction (flags `PROBABILITY_ANCHORING_SUSPECT`)
- Sector knowledge hydration (8 Gemini grounded queries per sub-sector, 180-day staleness)
- 20% CAGR exception panel (unanimous 3-agent vote)
- PCS laundering detection (>80% citation overlap flags reviewer independence failure)
- Evidence quality scoring (concrete vs vague citation counting)
- Scan modes: sector, individual ticker, full NYSE sweep

**Defer (v2+):**
- Holding review with forward return refresh (needs entire infrastructure first)
- Real-time data, web UI, portfolio tracking, fine-tuned models, autonomous trading -- all anti-features

### Architecture Approach

The system follows a "deterministic pipeline with LLM overlay" pattern. LLM agents are structured data generators whose outputs feed into the unchanged deterministic scoring pipeline. The agent layer sits between data retrieval and the existing pipeline stages, producing finalized overlays that the pipeline consumes identically to human-produced overlays.

**Major components:**
1. **Data retrieval layer** (`fmp.py` + cache, `gemini.py`, `sector.py`) -- quantitative, qualitative, and sector knowledge acquisition
2. **Agent layer** (`agents/base.py`, `agents/analyst.py`, `agents/validator.py`, `agents/epistemic_reviewer.py`) -- structured data generation with transport injection for testability
3. **Orchestration** (`automation.py`) -- analyst-validator retry loop, epistemic review, finalization wiring
4. **Deterministic pipeline** (`pipeline.py`, `scoring.py`, `reporting.py`) -- unchanged 5-stage scan execution

**Key patterns:**
- Single `call_agent()` entry point in `agents/base.py` for all Claude API calls
- Transport injection for test isolation (extends existing `FmpTransport`/`GeminiTransport` pattern)
- Structured JSON at every agent boundary (no free-form inter-agent text)
- Schema validation gates between every component

### Critical Pitfalls

1. **Probability anchoring and overconfidence** -- LLMs default to 60-70% regardless of evidence. Require worst-case-first generation, structured base rate justification, and distribution tracking across scans. Detection gate in Step 9.

2. **Information barrier leaks in epistemic review** -- Must be code-enforced via function signature, not prompt instructions. Sanitize thesis summary to strip numeric values. Test with canary fields. Non-negotiable from Step 5.

3. **Semantic corruption in structured output** -- Valid JSON with wrong values (revenue in millions not billions, FCF margin as decimal not percentage). Layer unit assertions and cross-validation against raw FMP data on top of schema validation.

4. **Evidence fabrication and citation inflation** -- LLMs fabricate plausible citations and upgrade evidence status to strengthen theses. Validator must cross-check claims against raw bundle. Evidence quality scoring surfaces thin analyses.

5. **Multi-agent rubber-stamping** -- All agents share training biases and converge rather than genuinely debate. Validator needs deterministic cross-checks (not just LLM review), track rejection rate (should be >10%), and inject known-bad fixtures as canaries.

6. **API cost explosion** -- Sector scan with 30 candidates costs $15-50 in Claude calls. Use prompt caching (80%+ input cost reduction), screen BEFORE expensive operations, Batch API for non-interactive scans, Haiku for development iteration.

## Implications for Roadmap

Based on research, the integration plan's 10-step sequence should be followed. Steps 1-2 are parallelizable. Steps 5-6 are parallelizable. Here is the suggested phase grouping:

### Phase 1: Infrastructure Foundation
**Rationale:** FMP caching and schema enrichments are prerequisites for everything downstream. They have no mutual dependency and can be built in parallel. Without caching, development iteration burns $50+ per session in API calls.
**Delivers:** Per-endpoint FMP cache with TTLs, enriched JSON schemas with Codex-aligned fields, `agents/base.py` shared infrastructure
**Addresses:** FMP caching (table stakes), schema enrichments (table stakes), `requests` integration for FMP
**Avoids:** API cost explosion (Pitfall 7), cache staleness (Pitfall 8) by designing earnings-date-aware invalidation from the start

### Phase 2: Sector Knowledge Framework
**Rationale:** Depends on Phase 1 (uses cached FMP screener for sector discovery). Dramatically improves analyst output quality -- the original scanner proved sector-conditioned analysis is fundamentally better. Must be built before the analyst agent.
**Delivers:** `sector.py` module, `data/sectors/` storage, 8-query Gemini grounded search per sub-sector, 180-day staleness tracking
**Uses:** `google-genai` SDK, Gemini grounded search
**Avoids:** Prompt injection via research content (Pitfall 6) by implementing input sanitization patterns here

### Phase 3: Claude Analyst Agent
**Rationale:** This is the critical path item. Everything downstream depends on it. Gets the hardest prompt engineering right first. Must include unit validation and evidence grounding from day one.
**Delivers:** `agents/analyst.py`, Pydantic output models, structured overlay generation from evidence, prompt caching
**Addresses:** Structured output enforcement (table stakes), evidence-grounded field population (table stakes)
**Avoids:** Probability anchoring (Pitfall 1) via worst-case-first prompt design, semantic corruption (Pitfall 3) via unit assertions, evidence fabrication (Pitfall 4) via evidence_refs enforcement

### Phase 4: Review Agents (Epistemic + Validator)
**Rationale:** Both depend only on the analyst agent output, not on each other. Can be built in parallel. Together they provide the adversarial and independent review layers that prevent LLM optimism from propagating unchecked.
**Delivers:** `agents/validator.py` with structured objections, `agents/epistemic_reviewer.py` with code-enforced blindness, new validator/epistemic output schemas
**Addresses:** Red-team validator (table stakes), architecturally blind epistemic review (table stakes)
**Avoids:** Information barrier leaks (Pitfall 2) via function signature gating, rubber-stamping (Pitfall 5) via deterministic cross-checks

### Phase 5: Automated Finalization Flow
**Rationale:** Once all agents exist, wiring them together is straightforward Python control flow. This is the "remove the human" moment. Provenance design is critical here -- must keep LLM and human finalization paths distinct.
**Delivers:** `automation.py` orchestrator, analyst-validator retry loop, end-to-end single-pass flow, LLM provenance lifecycle
**Addresses:** Automated finalization (table stakes), provenance lifecycle tracking (table stakes)
**Avoids:** Provenance confusion (Pitfall 9) by designing separate `LLM_FINAL_STATUSES` and `finalize_structured_analysis_llm()` path

### Phase 6: Scan Modes and Operational Breadth
**Rationale:** With the automated flow working for individual tickers, extend to sector scans and full NYSE sweeps. Screening funnel ordering is critical here -- filter BEFORE expensive agent calls.
**Delivers:** Sector scan with broken-chart filter and clustering, individual ticker scan, parallel `auto_analyze()` per cluster
**Addresses:** Scan modes (differentiator)
**Avoids:** Cost explosion (Pitfall 7) via screening funnel ordering, cache staleness (Pitfall 8) via `--fresh` defaults per scan mode

### Phase 7: Edge Case Hardening
**Rationale:** Hardens the automated flow with bias detection, multi-agent voting, and evidence quality gates. These features are important for trust but the core flow works without them.
**Delivers:** Probability anchoring detection, 20% CAGR exception panel, evidence quality scoring, PCS laundering detection, contradiction detection
**Addresses:** All differentiator features from FEATURES.md
**Avoids:** Probability anchoring (Pitfall 1) automated detection, rubber-stamping (Pitfall 5) via canary fixtures

### Phase 8: Holding Review
**Rationale:** Post-buy monitoring completes the investment lifecycle. Needs the entire infrastructure. Last because it does not block core scan capability.
**Delivers:** Forward return refresh, thesis integrity checklist, sell trigger evaluation, replacement gate computation
**Addresses:** Holding review (differentiator)

### Phase Ordering Rationale

- **Phases 1-2 before agents** because agents need cached data and enriched schemas to function
- **Analyst before reviewers** because reviewers operate on analyst output
- **Automation before scan modes** because scan modes invoke the automation flow
- **Hardening after automation** because you harden what already works
- **Holding review last** because it is the only feature that requires the entire infrastructure and does not block any other capability
- **Grouping reviewers into one phase** because they share the `agents/base.py` infrastructure, are independently testable, and neither depends on the other

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Sector Knowledge):** Gemini grounded search quality and citation extraction patterns need validation. The 8-query structure and staleness threshold need testing against real sub-sectors.
- **Phase 3 (Claude Analyst):** Prompt engineering for financial analysis is the hardest part. Needs iterative refinement with real FMP/Gemini data. Unit validation thresholds need calibration.
- **Phase 7 (Edge Case Hardening):** Probability anchoring detection heuristics and 20% CAGR exception panel voting independence are novel -- no established production patterns exist.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Infrastructure Foundation):** File-based caching and JSON Schema enrichment are trivially well-understood.
- **Phase 5 (Automated Finalization):** Pure orchestration wiring with straightforward Python control flow.
- **Phase 6 (Scan Modes):** Ports the original scanner's proven sector scan pattern directly.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All SDKs verified on PyPI with current versions. Anthropic structured outputs GA. google-genai confirmed replacement for deprecated google-generativeai. |
| Features | HIGH | Feature set derived from binding integration plan and existing codebase contracts. LLM calibration research (ECE 0.12-0.40) from peer-reviewed sources. |
| Architecture | HIGH | Pattern directly extends existing overlay abstraction. Build order validated against dependency graph. Component boundaries follow existing transport injection pattern. |
| Pitfalls | HIGH | Domain-specific pitfalls verified against current LLM reliability literature (ICLR 2025, OWASP 2025, Anthropic docs). Recovery strategies practical and costed. |

**Overall confidence:** HIGH

### Gaps to Address

- **Gemini grounded search quality:** The 8-query sector hydration structure is from the original scanner. Gemini grounded search may return different quality/format than expected. Validate during Phase 2 with real queries before building the analyst dependency on it.
- **Claude prompt caching effectiveness:** The 80%+ cost reduction assumes system prompts are stable and cacheable. Verify cache hit rates in practice during Phase 3 development.
- **Probability anchoring detection thresholds:** The "60% + friction-carrying risk type" heuristic is reasonable but unvalidated. Needs calibration across a meaningful sample (20+ scans) during Phase 7.
- **Multi-agent voting independence:** Academic papers describe the pattern but production implementations of financial multi-agent voting are sparse. The 20% CAGR exception panel may need different models or temperature settings per voter -- validate during Phase 7.
- **Token budget for raw bundles in prompts:** Data-rich stocks with 10+ years of financials may exceed Claude's practical attention window even within the context limit. Need to establish per-field token budgets during Phase 3.

## Sources

### Primary (HIGH confidence)
- [Anthropic Python SDK (PyPI)](https://pypi.org/project/anthropic/) -- v0.84.0, structured outputs, prompt caching
- [Anthropic Structured Outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) -- GA constrained decoding
- [Anthropic Prompt Caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) -- cache TTL, pricing
- [google-genai SDK (PyPI)](https://pypi.org/project/google-genai/) -- v1.66.0, grounded search
- [Gemini Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search) -- native SDK support
- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) -- indirect injection via data

### Secondary (MEDIUM confidence)
- [TradingAgents: Multi-Agent LLM Financial Trading](https://tradingagents-ai.github.io/) -- multi-agent financial architecture patterns
- [LLM Epistemic Calibration via Prediction Markets](https://arxiv.org/html/2512.16030v1) -- ECE 0.12-0.40, Brier scores 0.227
- [Why Do Multi-Agent LLM Systems Fail? (ICLR 2025)](https://openreview.net/pdf?id=wM521FqPvI) -- error amplification, silent agreement
- [Silence is Not Consensus: Disrupting Agreement Bias](https://arxiv.org/html/2505.21503v1) -- multi-agent conformity
- [Evaluating LLMs in Finance Requires Explicit Bias Consideration](https://arxiv.org/html/2602.14233v1) -- financial LLM bias
- [EY Managing Hallucination Risk (Jan 2026)](https://www.ey.com/content/dam/ey-unified-site/ey-com/en-gl/technical/documents/ey-gl-managing-hallucination-risk-in-llm-deployments-01-26.pdf) -- hallucination mitigation

### Tertiary (LOW confidence)
- [Sector-Aware LLM Financial Analysis](https://link.springer.com/article/10.1007/s10614-026-11329-4) -- sector conditioning effectiveness (single study)

---
*Research completed: 2026-03-10*
*Ready for roadmap: yes*
