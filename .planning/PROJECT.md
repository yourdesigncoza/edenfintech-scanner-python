# EdenFintech Scanner — LLM Integration

## What This Is

A fully automated stock scanning pipeline that merges the original scanner's LLM agent capabilities into the existing deterministic Python pipeline. Replaces the human analyst with Claude-powered agents (analyst, epistemic reviewer, red-team validator) while preserving Kyler's System Codex as the methodology source of truth. Targets value investors scanning NYSE for mispriced stocks.

## Core Value

Remove the human from the analysis loop — Claude agents fill structured analysis overlays, validate them adversarially, and assess confidence with architectural blindness — while the deterministic pipeline ensures reproducible scoring and methodology compliance.

## Requirements

### Validated

<!-- Existing capabilities confirmed working in current codebase. -->

- ✓ FMP data retrieval (quotes, profiles, financials, prices) — existing `fmp.py`
- ✓ Gemini qualitative research retrieval (catalysts, risks, moat, management) — existing `gemini.py`
- ✓ Raw bundle merging with fingerprint tracking — existing `gemini.py`
- ✓ Structured analysis overlay lifecycle (DRAFT → reviewed → FINALIZED) — existing `structured_analysis.py`, `field_generation.py`
- ✓ Deterministic 5-check screening (solvency, dilution, revenue_growth, roic, valuation) — existing `pipeline.py`
- ✓ Cluster analysis, epistemic review, report assembly — existing `pipeline.py`
- ✓ Scoring engine (CAGR, floor price, decision score, confidence bands) — existing `scoring.py`
- ✓ OpenAI judge with deterministic fallback — existing `judge.py`
- ✓ JSON Schema validation at stage boundaries — existing `schemas.py`
- ✓ Review package workflow (raw → review → final) — existing `review_package.py`
- ✓ Asset validation and regression suite — existing `validation.py`, `regression.py`
- ✓ CLI entry point — existing `cli.py`

### Active

<!-- Current scope: 10-step integration plan. -->

- [ ] FMP per-endpoint caching with TTLs and `--fresh` bypass
- [ ] Schema enrichments for Codex alignment (catalyst_stack, invalidation_triggers, decision_memo, issues_and_fixes, setup_pattern, stretch_case)
- [ ] Pipeline gates for enriched fields (catalyst-stack rejection, evidence traction check)
- [ ] Sector knowledge framework (hydration, staleness, registry, Gemini grounded search)
- [ ] Claude analyst agent — fills structured analysis overlays from raw bundles + sector knowledge
- [ ] Epistemic reviewer agent — architecturally blind confidence assessment with evidence discipline
- [ ] Red-team validator agent — adversarial review with contradiction detection
- [ ] Automated finalization flow (analyst → validator → epistemic → finalize)
- [ ] New provenance statuses: LLM_DRAFT, LLM_CONFIRMED, LLM_EDITED
- [ ] Individual ticker scan mode (`auto-scan TICKER [TICKER...]`)
- [ ] Sector scan mode (`sector-scan "Consumer Defensive"`) with broken-chart filter and clustering
- [ ] 20% CAGR exception panel (unanimous 3-agent vote)
- [ ] Probability anchoring detection and correction
- [ ] Evidence quality scoring
- [ ] Holding review with forward return refresh and thesis integrity checklist
- [ ] Sell trigger evaluation and replacement gate computation

### Out of Scope

- Web UI or dashboard — CLI-only tool
- Real-time data streaming — batch scan model
- Portfolio tracking/brokerage integration — analysis tool only
- Mobile app — desktop CLI
- Multi-user auth — single-operator tool

## Context

**Existing codebase:** Deterministic Python pipeline (`src/edenfintech_scanner_bootstrap/`) with FMP/Gemini adapters, structured analysis lifecycle, 5-stage pipeline, and review package workflow. Currently requires a human analyst to fill overlays.

**Original scanner:** Node.js/Bash implementation at `/home/laudes/zoot/projects/edenfintech-scanner` with mature caching logic (`fmp-api.sh`), Claude Code agent orchestration (orchestrator → screener → analyst), sector research via Gemini grounded search, and `calc-score.sh` for financial math. Serves as reference implementation for caching, agent prompts, and sector queries.

**Kyler's System Codex:** `/home/laudes/zoot/projects/edenfintech-scanner-python/kylers-system-codex/` — 11-chapter methodology covering idea finding through after-the-buy monitoring. The Codex is the source of truth for all analytical rules, screening checks, and valuation methodology. If code disagrees with `assets/methodology/strategy-rules.md` (derived from Codex), the methodology wins.

**Integration plan:** `/home/laudes/zoot/projects/edenfintech-scanner-python/docs/integration-plan.md` — 10-step build sequence authored prior to this project. Treats as binding spec.

## Constraints

- **Tech stack**: Python 3.11+, stdlib for core pipeline, `anthropic` SDK for Claude agents, `google-generativeai` SDK for Gemini grounded search, `requests` for FMP HTTP
- **Provider assignments**: Claude → all agents (analyst, epistemic reviewer, validator); Gemini Grounded Search → qualitative research; OpenAI → final judge (existing)
- **Claude model**: Configurable per agent, default `claude-sonnet-4-6`
- **Storage**: Validated JSON throughout, including sector knowledge. `data/cache/` for FMP, `data/sectors/` for sector knowledge
- **Parallelism**: Parallel analyst runs per cluster, serial sector hydration (matching original scanner pattern)
- **Information barrier**: Epistemic reviewer must be architecturally blind — code-enforced, not prompt-enforced. Function signature cannot receive scores/probabilities.
- **Methodology primacy**: `assets/methodology/strategy-rules.md` wins over any code implementation

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Anthropic Python SDK for Claude agents | Standalone Python modules, not Claude Code agents | — Pending |
| Extend gemini.py with grounded search | Avoid separate module; existing adapter already handles Gemini | — Pending |
| Configurable Claude model per agent | Default Sonnet for cost, allow Opus override for quality | — Pending |
| Port FMP caching from original bash script | Proven TTL structure, per-endpoint granularity | — Pending |
| Match original's parallelism pattern | Parallel clusters + serial hydration avoids write conflicts | — Pending |
| All 10 steps in v1 | Full Codex coverage including holding review | — Pending |

---
*Last updated: 2026-03-10 after initialization*
