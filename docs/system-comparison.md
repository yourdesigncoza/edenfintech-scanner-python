# EdenFinTech Scanner: Original vs Python Rewrite

## Overview

The original `edenfintech-scanner` is an AI-augmented multi-agent research tool.
The Python rewrite `edenfintech-scanner-python` is a deterministic pipeline that
expects human judgment via structured-analysis overlays rather than LLM agents.

## Side-by-Side Comparison

| Aspect | Original | Python Rewrite |
|--------|----------|----------------|
| **Language** | Bash scripts + Claude Code agents/skills + markdown | Pure Python package (stdlib only) |
| **Architecture** | Multi-agent pipeline (Orchestrator → Screener → Analyst → Epistemic Reviewer agents) | Single deterministic library with CLI |
| **LLM dependency** | Core — Claude agents make screening/analysis judgments at runtime | None — all logic is hardcoded in Python |
| **Entry point** | `/scan-stocks` skill → agent orchestration | `python -m edenfintech_scanner_bootstrap.cli` |
| **API adapters** | `fmp-api.sh` (bash), `gemini-search.sh` (bash) | `fmp.py`, `gemini.py` (Python `urllib`) |
| **Scoring** | `calc-score.sh` (600+ lines bash) | `scoring.py` (Python) |
| **Report rendering** | `report_json.py` + agents | `reporting.py` (deterministic) |
| **Structured analysis** | Agents fill in judgments live | Machine-draft → human review → finalize workflow with provenance tracking |
| **Judge** | N/A (agents self-check) | OpenAI judge (optional) + local deterministic fallback |
| **Testing** | Regression harness (methodology drift detection) | `unittest` suite (59 tests) + asset validation + regression fixtures |
| **Caching** | Transparent file cache (1-90 day TTLs) | None built-in |
| **Sector knowledge** | Hydration system (pre-loaded sector research files) | Not implemented |
| **Holding reviews** | Step 8 monitoring via `/review-holding` | Not implemented |

## What the Python Rewrite Extracts

The deterministic core of the original system:

- Screening checks (solvency, dilution, revenue growth, ROIC, valuation)
- Scoring math (CAGR, floor price, decision score, confidence bands)
- Report assembly and schema validation
- Epistemic confidence review (5 PCS questions → confidence multiplier)

## What the Python Rewrite Adds

- Per-field provenance tracking with `MACHINE_DRAFT` → `HUMAN_CONFIRMED`/`HUMAN_EDITED` lifecycle
- Review package workflow with manifest and raw-bundle fingerprint continuity
- JSON Schema validation at every pipeline boundary
- Proper unit test suite (59 tests) with wire-format fixture coverage
- Machine-draft field generation from merged raw evidence

## What the Python Rewrite Does Not Include

- Sector hydration/knowledge system
- Holding review (Step 8 monitoring)
- Transparent API caching
- Competitor comparison (Step 3 is implicit in the overlay)
- Claude agent orchestration — no LLM-at-runtime dependency

## Reproducibility Trade-off

The original is more capable but less reproducible — agent-driven analysis means
different runs can produce different results. The Python version guarantees
identical output for identical input.

## Original Architecture (for reference)

```
User → /scan-stocks
        ↓
        Orchestrator Agent
        ├── Screener Agent (Phase 1: Steps 1-2, quantitative filtering)
        ├── Groups survivors by industry cluster
        ├── Sector Knowledge Check (hydration status & freshness)
        └── Analyst Agents (Phase 2: Steps 3-6, parallel deep analysis)
            ├── Competitor comparison (Step 3)
            ├── Qualitative deep dive (Step 4)
            ├── Valuation modeling (Step 5)
            └── Decision scoring (Step 6)
        ↓
        Epistemic Reviewer Agent (independent confidence assessment)
        ↓
        Final ranked report + JSON artifact
```

## Python Rewrite Architecture

```
CLI → build-review-package TICKER
        ↓
        Data Retrieval (fmp.py + gemini.py)
        ├── FMP raw bundle (price, revenue, FCF, shares)
        └── Gemini raw bundle (catalysts, risks, moat, management)
        ↓
        Merge → field_generation.py (machine draft with provenance)
        ↓
        Human review (review-checklist, review-note-suggestions)
        ↓
        finalize-structured-analysis (promotes overlay)
        ↓
        pipeline.py (screening → cluster analysis → epistemic review → report)
        ↓
        judge.py (OpenAI or local deterministic)
        ↓
        Final package: report.json, report.md, execution-log.md, judge.json
```

## Roadmap: Adding LLM Features to the Python Rewrite

The Python system already separates data retrieval, judgment, and deterministic
execution into distinct layers. LLM features slot into the judgment layer without
touching the pipeline core. The recommendation is to build on the Python rewrite
rather than starting over — the deterministic foundation (schema validation,
provenance tracking, fingerprint continuity, test suite) is the harder part done
right.

### 1. LLM-Powered Field Generation

**What:** Replace the heuristic `field_generation.py` with an LLM call that fills
the structured-analysis overlay from merged raw evidence.

**Why it fits:** The schema, provenance system, and review workflow already exist.
Add an `LLM_GENERATED` provenance status alongside `MACHINE_DRAFT`. The same
review-checklist and finalization gates apply — the LLM just produces better
initial drafts than the current heuristic rules.

**Integration point:** `field_generation.py` — new `generate_structured_analysis_draft_llm()`
function that calls an LLM with the merged raw bundle + methodology rules as
context, returns a schema-valid overlay with `LLM_GENERATED` provenance per field.

### 2. Sector Knowledge Hydration

**What:** A knowledge store of pre-researched sector context (valuation multiples,
regulatory environment, precedent turnarounds, sub-sector dynamics) that enriches
the analysis.

**Why it fits:** The `gemini.py` adapter already handles grounded search. Add a
`sectors/` knowledge directory and a hydration CLI command that populates it via
Gemini Search. The structured-analysis draft can then reference sector context
when generating fields.

**Integration point:** New `sector_knowledge.py` module + `hydrate-sector` CLI
command. The knowledge store feeds into field generation and enriches the Gemini
raw bundle prompt.

### 3. Competitor Comparison (Step 3)

**What:** Pull peer financials via FMP, let an LLM summarize competitive position,
and emit a cluster ranking record.

**Why it fits:** The `fmp.py` adapter already fetches financials. FMP's
`/stock-peers` endpoint provides peer lists. Add a `competitor.py` module that
fetches peer data, builds comparison tables, and optionally calls an LLM for
qualitative ranking. The cluster ranking feeds into `analysis_inputs.final_cluster_status`
in the structured-analysis overlay.

**Integration point:** New `competitor.py` module + `compare-peers` CLI command.
Output merges into the raw bundle or structured-analysis draft as additional
evidence context.

### 4. Holding Reviews (Step 8)

**What:** Monitor existing positions for thesis integrity, catalyst tracking,
forward-return refresh (30% hurdle check), and sell-trigger audit.

**Why it fits:** Same pipeline pattern as the scan — fetch fresh data, compare
against stored thesis, emit a structured review report. Add a holding-review
schema alongside the existing scan-report schema.

**Integration point:** New `holding_review.py` module + `review-holding` CLI
command. Reuses `fmp.py` and `gemini.py` for fresh data retrieval. Output follows
a new `holding-review.schema.json` contract.

### 5. API Response Caching

**What:** Transparent file-based cache with configurable TTLs per endpoint to
avoid redundant API calls.

**Why it fits:** Both `fmp.py` and `gemini.py` use `urllib` for HTTP. Wrap the
transport layer with a cache-aware decorator that stores responses keyed by
endpoint + params with TTL metadata.

**Integration point:** New `cache.py` module wrapping the transport callables in
`fmp.py` and `gemini.py`. Cache directory under `data/cache/` with TTL config
(e.g. profile: 7 days, price: 1 day, financials: 90 days).

### Suggested Implementation Order

```
1. API Caching          — low effort, immediate savings on repeated runs
2. LLM Field Generation — highest value, overlay system already supports it
3. Competitor Comparison — enriches analysis quality, FMP adapter ready
4. Sector Hydration      — improves LLM draft quality, depends on #2
5. Holding Reviews       — new pipeline stage, builds on all the above
```

### Target Architecture After LLM Integration

```
CLI → build-review-package TICKER
        ↓
        Data Retrieval (fmp.py + gemini.py) ← cache.py
        ├── FMP raw bundle (price, revenue, FCF, shares, peers)
        ├── Gemini raw bundle (catalysts, risks, moat, management)
        └── Competitor data (peer financials via FMP)
        ↓
        Merge + sector knowledge enrichment
        ↓
        LLM-powered field generation (provenance: LLM_GENERATED)
        ↓
        Human review (review-checklist, review-note-suggestions)
        ↓
        finalize-structured-analysis (promotes overlay)
        ↓
        pipeline.py (screening → cluster analysis → epistemic review → report)
        ↓
        judge.py (OpenAI or local deterministic)
        ↓
        Final package: report.json, report.md, execution-log.md, judge.json
```
