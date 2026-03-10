# Architecture Patterns

**Domain:** LLM-augmented financial stock scanning pipeline
**Researched:** 2026-03-10

## Recommended Architecture

The system follows a **deterministic pipeline with LLM overlay** pattern: LLM agents produce structured data that feeds into an unchanged deterministic scoring pipeline. The agents are not autonomous decision-makers; they are structured data generators whose outputs pass through the same validation and scoring gates as human-produced overlays.

This is the correct pattern because the existing pipeline already has a clean overlay abstraction (`structured_analysis.py`) with lifecycle states and provenance tracking. The LLM layer slots into exactly the position where the human analyst currently sits.

```
                         DATA RETRIEVAL
                    +---------+---------+
                    |         |         |
                  FMP     Gemini    Sector
                (quant)  (qual)   Knowledge
                    |         |         |
                    +----+----+---------+
                         |
                    Merged Raw Bundle
                         |
                    =====================
                     LLM AGENT LAYER
                    =====================
                         |
              +----------+----------+
              |                     |
         Claude Analyst        (retry loop)
         (fills overlay)   <-- Validator rejects
              |                     |
         Claude Validator ----------+
         (adversarial check)
              |
         Claude Epistemic Reviewer
         (architecturally blind)
              |
         Finalized Overlay
              |
                    =====================
                     DETERMINISTIC LAYER
                    =====================
                         |
              apply_structured_analysis()
                         |
                    build_scan_input()
                         |
              5-check screening
              cluster analysis
              epistemic review
              scoring + report
              judge
```

### Component Boundaries

| Component | Responsibility | Inputs | Outputs | Communicates With |
|-----------|---------------|--------|---------|-------------------|
| `fmp.py` (existing + cache) | Quantitative data retrieval with per-endpoint TTL caching | Ticker list, config | FMP raw bundle | Cache layer (`data/cache/`), external FMP API |
| `gemini.py` (existing + grounded search) | Qualitative research retrieval; grounded search for sector hydration | Ticker list, config, search queries | Gemini raw bundle | External Gemini API |
| `sector.py` (new) | Sector knowledge hydration, storage, staleness checks | Sector name, Gemini client | Sector knowledge JSON | `data/sectors/`, Gemini grounded search |
| `agents/analyst.py` (new) | Fill structured analysis overlay from evidence | Merged raw bundle, sector knowledge, methodology rules | LLM_DRAFT overlay | Claude API via Anthropic SDK |
| `agents/validator.py` (new) | Adversarial review of analyst overlay | Analyst overlay, raw evidence bundle (NOT scores) | Approve/Reject with objections | Claude API via Anthropic SDK |
| `agents/epistemic_reviewer.py` (new) | Blind confidence assessment | Thesis, risks, catalysts, moat ONLY (no scores, no probabilities) | 5 PCS answers with evidence | Claude API, Gemini grounded search (independent) |
| `agents/base.py` (new) | Shared agent infrastructure: retry, structured output, logging | Agent config, prompt, schema | Validated response dict | Anthropic SDK |
| `automation.py` (new) | Orchestrate agent flow: analyst -> validator -> epistemic -> finalize | Ticker, config | Finalized overlay | All agent modules, `structured_analysis.py` |
| `structured_analysis.py` (existing) | Overlay lifecycle management | Overlay dict | Validated/finalized overlay | Schema validation |
| `pipeline.py` (existing) | Deterministic 5-stage scan | Scan input JSON | Report JSON + artifacts | `scoring.py`, `judge.py` |

### Data Flow

**Phase 1: Data Acquisition (unchanged)**
```
Ticker -> FMP cache check -> FMP API (if miss) -> FMP raw bundle
Ticker -> Gemini API -> Gemini raw bundle
Sector -> Staleness check -> Gemini grounded search (if stale) -> Sector knowledge JSON
FMP bundle + Gemini bundle -> merge_fmp_and_gemini_bundles() -> Merged raw bundle
```

**Phase 2: LLM Agent Flow (new)**
```
Merged raw bundle + Sector knowledge + strategy-rules.md
    -> Claude Analyst Agent
    -> LLM_DRAFT overlay (JSON, schema-validated)

LLM_DRAFT overlay + Raw evidence bundle (no scores)
    -> Claude Validator Agent
    -> APPROVE or REJECT(objections)

If REJECT:
    LLM_DRAFT + objections -> Claude Analyst Agent (retry, max 2)
    -> Revised LLM_DRAFT -> Validator again

On APPROVE:
    ticker + industry + thesis + risks + catalysts + moat + dominant_risk_type
    (NO scores, NO probabilities, NO base_case numbers)
    -> Claude Epistemic Reviewer
    -> 5 PCS answers with evidence citations

PCS answers merged into overlay -> LLM_CONFIRMED -> finalize
```

**Phase 3: Deterministic Pipeline (unchanged)**
```
Finalized overlay + Merged raw bundle
    -> apply_structured_analysis()
    -> build_scan_input()
    -> run_scan() [screening -> cluster -> epistemic -> scoring -> report]
    -> codex_judge()
    -> Report JSON + Markdown
```

## Patterns to Follow

### Pattern 1: Agent Base Class with Structured Output Enforcement

**What:** All Claude agent calls go through a single `call_agent()` function in `agents/base.py` that enforces structured JSON output via the Anthropic SDK's `output_config` with JSON schema, handles retries, and logs all interactions.

**Why:** The existing codebase already follows this pattern with `JudgeTransport` in `judge.py` -- a callable transport abstraction that enables test injection. Extend this pattern to all agents.

**Confidence:** HIGH -- Anthropic SDK natively supports `output_config.format.type = "json_schema"` which constrains token generation at inference time. Schema violations are caught before the response returns. No parsing retries needed for structural validity.

**Example:**
```python
# agents/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import anthropic

AgentTransport = Callable[[str, str, dict, "AgentConfig"], dict]

@dataclass(frozen=True)
class AgentConfig:
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    temperature: float = 0.0
    max_retries: int = 2

def call_agent(
    *,
    system_prompt: str,
    user_prompt: str,
    output_schema: dict,
    config: AgentConfig,
    transport: AgentTransport | None = None,
) -> dict:
    """Single entry point for all Claude agent calls.

    Uses Anthropic SDK structured output to guarantee schema compliance.
    Transport injection enables fixture-based testing without API calls.
    """
    if transport:
        return transport(system_prompt, user_prompt, output_schema, config)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": output_schema,
            }
        },
    )
    return json.loads(response.content[0].text)
```

### Pattern 2: Code-Enforced Information Barrier (Type Signature Gating)

**What:** The epistemic reviewer's function signature physically cannot receive scores, probabilities, or valuation numbers. This is enforced at the Python function level, not by prompt instruction.

**Why:** Prompt-based barriers are trivially broken by context leakage. The integration plan explicitly requires "code-enforced, not prompt-enforced" blindness. The existing `structured_analysis.py` already demonstrates the pattern of strict input contracts.

**Confidence:** HIGH -- This is a design constraint from the integration plan, and the implementation pattern is straightforward.

**Example:**
```python
# agents/epistemic_reviewer.py
def run_epistemic_review(
    *,
    ticker: str,
    industry: str,
    thesis_summary: str,
    key_risks: list[str],
    catalysts: list[str],
    moat_assessment: str,
    dominant_risk_type: str,
    # BARRIER: No base_probability, no base_case, no worst_case,
    # no score, no position_size, no price targets.
    # These parameters do not exist in the signature.
    config: AgentConfig | None = None,
    transport: AgentTransport | None = None,
) -> dict:
    """Architecturally blind epistemic review.

    The function signature IS the information barrier.
    Code that calls this function cannot pass score data
    because the parameter does not exist.
    """
```

### Pattern 3: Validator Retry Loop with Structured Objections

**What:** The validator returns structured objections on rejection. The analyst receives these objections as additional context on retry. Maximum 2 retries before escalation.

**Why:** The TradingAgents framework and production multi-agent systems show that structured inter-agent communication (not free-form text) prevents information degradation across retry rounds. The integration plan specifies "re-run analyst with validator objections (max 2 retries)."

**Confidence:** HIGH -- The pattern is well-established in multi-agent literature and directly specified in the integration plan.

**Example:**
```python
# automation.py
def _analyst_validator_loop(
    merged_bundle: dict,
    sector_knowledge: dict | None,
    config: AgentConfig,
) -> dict:
    overlay = run_analyst(
        merged_bundle=merged_bundle,
        sector_knowledge=sector_knowledge,
        config=config,
    )

    for attempt in range(3):  # initial + 2 retries
        result = run_validation(
            overlay=overlay,
            raw_bundle=merged_bundle,
            config=config,
        )
        if result["verdict"] == "APPROVE":
            return overlay
        if attempt < 2:
            overlay = run_analyst(
                merged_bundle=merged_bundle,
                sector_knowledge=sector_knowledge,
                validator_objections=result["objections"],
                config=config,
            )

    raise AnalysisRejectedError(
        f"Validator rejected after {attempt + 1} attempts: "
        f"{result['objections']}"
    )
```

### Pattern 4: Transport Injection for Testability

**What:** Every external API call (Claude, Gemini, FMP, OpenAI) accepts an optional transport callable. Tests inject fixture-returning transports. Production uses real HTTP transports.

**Why:** The existing codebase already uses this pattern for `FmpTransport`, `GeminiTransport`, and `JudgeTransport`. Extending it to Claude agents maintains consistency and enables the full test suite to run without API keys.

**Confidence:** HIGH -- Existing pattern in codebase, proven working.

### Pattern 5: Provenance Chain Through Agent Layer

**What:** Each agent output carries provenance metadata that flows through the entire pipeline: which model, which prompt version, which raw bundle fingerprint, which attempt number.

**Why:** The existing pipeline already tracks fingerprints and provenance statuses. The new statuses (`LLM_DRAFT`, `LLM_CONFIRMED`, `LLM_EDITED`) extend this chain through the agent layer for full traceability.

**Confidence:** HIGH -- Natural extension of existing provenance system.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Agent Framework Overhead

**What:** Using LangChain, CrewAI, or similar agent orchestration frameworks.

**Why bad:** The existing pipeline is deliberately minimal (stdlib + requests). Agent frameworks add massive dependency trees, opinionated abstractions that fight the existing overlay lifecycle, and their own retry/routing logic that would duplicate `automation.py`. The Anthropic SDK's `output_config` handles structured output enforcement natively -- no framework needed.

**Instead:** Direct Anthropic SDK calls through `agents/base.py`. The orchestration logic in `automation.py` is ~100 lines of Python, not a framework problem.

### Anti-Pattern 2: Free-Form Inter-Agent Communication

**What:** Passing raw LLM text between agents as context.

**Why bad:** Information degrades across agent boundaries (the "telephone effect" documented in TradingAgents research). Validator objections become vague. Analyst retry context becomes bloated.

**Instead:** Structured JSON at every agent boundary. Validator returns typed objections (`{field: str, objection: str, evidence_conflict: str}`). Analyst receives these as structured input, not concatenated text.

### Anti-Pattern 3: Prompt-Based Information Barriers

**What:** Telling the epistemic reviewer "ignore any score data in the context" via system prompt.

**Why bad:** Prompt injection, context leakage, and model updates can all break prompt-based barriers. The integration plan explicitly forbids this.

**Instead:** Function signature gating (Pattern 2). The data physically never enters the function.

### Anti-Pattern 4: Monolithic Agent Prompts

**What:** Single massive prompt containing methodology rules, raw evidence, sector knowledge, and task instructions.

**Why bad:** Token limits, attention degradation, and inability to cache system prompts independently.

**Instead:** Separate system prompt (methodology + field contracts, cacheable) from user prompt (evidence + task). The Anthropic SDK supports prompt caching on system prompts, reducing cost and latency for repeated calls with the same methodology.

### Anti-Pattern 5: LLM-Driven Pipeline Routing

**What:** Having the LLM decide which pipeline stage to run next.

**Why bad:** The pipeline stages are deterministic and sequential. LLM routing adds non-determinism to what should be a fixed workflow. The Lobster/OpenClaw research confirms: "LLMs are unreliable routers."

**Instead:** `automation.py` handles all routing with plain Python control flow. The only LLM decision is the validator's approve/reject binary.

## Component Interaction Rules

### What Talks to Claude API

Only `agents/base.py:call_agent()` makes Claude API calls. All agent modules (`analyst.py`, `validator.py`, `epistemic_reviewer.py`) call through this single function. This centralizes:
- API key management
- Retry logic (exponential backoff for transient failures)
- Structured output enforcement
- Response logging and provenance
- Transport injection for tests

### What Talks to What (Boundary Rules)

| From | Can Access | Cannot Access |
|------|-----------|---------------|
| `automation.py` | All agent modules, `structured_analysis.py`, `live_scan.py` | Claude API directly |
| `agents/analyst.py` | `agents/base.py`, methodology rules, raw bundles, sector knowledge | Pipeline scores, epistemic output |
| `agents/validator.py` | `agents/base.py`, analyst overlay, raw evidence | Pipeline scores, epistemic output |
| `agents/epistemic_reviewer.py` | `agents/base.py`, thesis/risks/catalysts/moat only | Scores, probabilities, base_case, worst_case, price targets, analyst overlay |
| `pipeline.py` | Finalized overlay via `importers.py` | Agent modules, Claude API |
| `sector.py` | Gemini grounded search, `data/sectors/` | Agent modules, pipeline |

### Schema Validation Gates

Every agent output is validated against its JSON schema before passing to the next component. This is the same pattern used at every stage boundary in the existing pipeline (`schemas.py:validate_instance()`).

```
Claude Analyst output -> validate against structured-analysis.schema.json
Claude Validator output -> validate against validator-result.schema.json (new)
Claude Epistemic output -> validate against epistemic-review.schema.json (new)
Finalized overlay -> validate against structured-analysis.schema.json (existing)
Scan input -> validate against scan-input.schema.json (existing)
Report -> validate against scan-report.schema.json (existing)
```

## Suggested Build Order (Dependencies)

The integration plan's 10-step sequence is architecturally sound. Here is the dependency graph that justifies it:

```
Step 1: FMP Caching --------+
                             |
Step 2: Schema Enrichments --+-- (independent, can parallel)
                             |
Step 3: Sector Knowledge ----+-- depends on Step 1 (uses cached FMP for sector discovery)
                             |
Step 4: Claude Analyst ------+-- depends on Steps 1,2,3 (needs cache + schema + sector)
                             |      THIS IS THE CRITICAL PATH ITEM
                             |
         +-------------------+-------------------+
         |                                       |
Step 5: Epistemic Reviewer    Step 6: Validator  (both depend on Step 4, can parallel)
         |                                       |
         +-------------------+-------------------+
                             |
Step 7: Automation Flow -----+-- depends on Steps 4,5,6 (orchestrates all agents)
                             |      THIS IS THE "REMOVE HUMAN" MOMENT
                             |
Step 8: Scan Modes ----------+-- depends on Step 7 (uses automation flow)
                             |
Step 9: Edge Case Hardening -+-- depends on Step 7 (hardens automation flow)
                             |
Step 10: Holding Review -----+-- depends on Steps 7,8 (post-buy monitoring)
```

**Key build order observations:**

1. **Steps 1-2 are parallelizable** -- caching and schema enrichments have no mutual dependency. Build both before anything else.
2. **Step 3 depends on Step 1** -- sector hydration uses FMP screener endpoint which benefits from caching.
3. **Step 4 is the critical path** -- everything downstream depends on the analyst agent. Get this right first.
4. **Steps 5-6 are parallelizable** -- epistemic reviewer and validator both depend only on analyst output, not on each other. Build in parallel.
5. **Step 7 is pure orchestration** -- once agents exist, wiring them together is straightforward Python control flow.
6. **Steps 8-10 are sequential** -- scan modes, hardening, and holding review build on the automation flow incrementally.

**Infrastructure to build first (before Step 4):**
- `agents/base.py` -- the shared agent infrastructure (call_agent, transport injection, retry logic)
- `agents/__init__.py` -- package structure
- New schema files for validator and epistemic reviewer output contracts
- Test fixtures for agent responses (fixture-returning transports)

## Scalability Considerations

| Concern | Single ticker | Sector scan (20-50 tickers) | Full NYSE scan (hundreds) |
|---------|--------------|---------------------------|--------------------------|
| Claude API calls | 3 per ticker (analyst + validator + epistemic) + retries | 60-150 calls, parallel per cluster | 300+ calls, rate limiting critical |
| FMP API calls | ~10 endpoints per ticker | Cached after first scan | Fully cached after sector hydration |
| Gemini API calls | 1 research bundle + epistemic grounded search | Serial hydration per sector | Major cost driver |
| Latency | ~30-60s total (3 Claude calls) | ~5-10min with parallelism | ~30-60min with rate limiting |
| Cost | ~$0.15-0.30 (Sonnet) per ticker | ~$3-15 per sector scan | ~$50-100 per full scan |
| Storage | ~500KB per ticker run | ~10-25MB per sector run | ~100MB+ per full scan |

**Rate limiting strategy:** The integration plan specifies "parallel analyst runs per cluster, serial sector hydration." This matches the original scanner's proven pattern. Implement with Python's `concurrent.futures.ThreadPoolExecutor` for cluster-level parallelism, sequential iteration for sector hydration.

## Sources

- [Anthropic Structured Outputs Docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) -- JSON schema enforcement via `output_config` (HIGH confidence)
- [TradingAgents: Multi-Agent LLM Financial Trading Framework](https://arxiv.org/html/2412.20138v3) -- Multi-agent architecture with structured communication protocols, bullish/bearish debate pattern (MEDIUM confidence, academic paper)
- [Deterministic Multi-Agent Dev Pipeline](https://dev.to/ggondim/how-i-built-a-deterministic-multi-agent-dev-pipeline-inside-openclaw-and-contributed-a-missing-4ool) -- LLMs for creative work, code for orchestration plumbing (MEDIUM confidence)
- [Retries, Fallbacks, and Circuit Breakers in LLM Apps](https://portkey.ai/blog/retries-fallbacks-and-circuit-breakers-in-llm-apps/) -- Retry patterns with exponential backoff, crew_factory pattern for fresh retries (MEDIUM confidence)
- [Why Multi-Agent LLM Systems Fail](https://arxiv.org/pdf/2503.13657) -- Error amplification across agent boundaries, need for structured inter-agent communication (MEDIUM confidence)
- [Multi-Agent System Reliability](https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/) -- Production validation strategies for multi-agent systems (MEDIUM confidence)

---

*Architecture analysis: 2026-03-10*
