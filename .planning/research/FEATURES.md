# Feature Landscape

**Domain:** LLM-automated financial stock scanning pipeline (value investing, NYSE focus)
**Researched:** 2026-03-10

## Table Stakes

Features users expect. Missing = system is unreliable or produces untrustworthy output.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Structured output enforcement** | LLM agent outputs MUST conform to existing JSON schemas (`structured-analysis.schema.json`, `scan-input.schema.json`). Without guaranteed schema compliance, the deterministic pipeline downstream breaks. | Low | Claude now supports constrained decoding via `output_config.format` with `json_schema` type. Opus 4.6 and Sonnet 4.6 both support it (GA). This eliminates retry loops and parse-error handling. Use Anthropic's native structured outputs, not prompt-based JSON extraction. |
| **Evidence-grounded field population** | Every field the analyst agent fills must cite specific evidence from the raw bundle (FMP financials, Gemini research). Without this, LLM outputs are hallucinated opinions, not analysis. The existing provenance system (`field_provenance` with `evidence_refs`) already demands this. | Medium | Each provenance entry needs `evidence_refs` pointing to concrete data: FMP derived values, Gemini research snippets with named sources. Vague references like "industry analysis suggests" are unacceptable. |
| **Architecturally blind epistemic review** | The epistemic reviewer MUST NOT see scores, probabilities, or valuations. This is the system's core epistemic moat. If the reviewer can see the analyst's numbers, it rubber-stamps rather than independently assesses. The existing pipeline already separates screening/analysis from epistemic review. | Medium | Code-enforced via function signature constraints, not prompt instructions. The `run_epistemic_review()` function signature literally cannot accept score/probability parameters. This is already specified in the integration plan and is non-negotiable. |
| **Provenance lifecycle tracking** | New statuses `LLM_DRAFT`, `LLM_CONFIRMED`, `LLM_EDITED` to distinguish LLM-generated fields from human-reviewed ones. Without this, you lose auditability of who/what produced each analytical judgment. | Low | Extends existing `MACHINE_DRAFT`/`HUMAN_CONFIRMED`/`HUMAN_EDITED` provenance system. Straightforward enum extension in `structured_analysis.py`. |
| **Per-endpoint FMP caching with TTLs** | API rate limits and cost make uncached development impossible. The original scanner proved this: without caching, iterating on agent prompts burns $50+ per session in FMP calls alone. Every downstream step depends on FMP data. | Low | Port from original scanner's `fmp-api.sh`. Per-endpoint TTLs: screener/ratios/metrics/ev = 7d, profile/peers = 30d, financials = 90d, price-history = 1d. `--fresh` bypass flag. Never cache empty/error responses. |
| **Validator agent (red-team)** | Adversarial review catching contradictions between analyst claims and raw data (e.g., analyst claims revenue growth but FMP shows 3-year decline). Without this, LLM analysts systematically produce optimistically biased analysis. Research confirms LLMs exhibit overconfidence (ECE 0.12-0.40) and probability anchoring. | High | Must answer the 5 Codex red-team questions as structured output. Must cross-check analyst assumptions against raw FMP data. Can REJECT overlays and send back to analyst with specific objections. Max 2 retry loops. |
| **Automated finalization flow** | The analyst-validator-epistemic pipeline must run end-to-end without human intervention. This is the core value proposition: removing the human from the analysis loop. Without it, you have three agents that each need manual orchestration. | Medium | Orchestration: fetch raw bundles -> load sector knowledge -> analyst fills overlay -> validator approves/rejects -> retry if rejected (max 2) -> epistemic reviewer (blind) -> merge PCS -> finalize. Pure wiring of Steps 4-6. |
| **Schema enrichments (Codex alignment)** | The existing schemas lack fields the methodology requires: `catalyst_stack`, `invalidation_triggers`, `decision_memo`, `issues_and_fixes` with evidence status, `setup_pattern`, `stretch_case`. Without these, agents cannot fill the complete Codex-required analysis. | Medium | New pipeline gates: reject if `catalyst_stack` has zero HARD/MEDIUM entries; reject if all `issues_and_fixes` are ANNOUNCED_ONLY. These gates prevent the LLM from gaming its way through with weak evidence. |

## Differentiators

Features that set the system apart from generic LLM financial analysis tools.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Probability anchoring detection** | LLMs systematically anchor to round numbers (60% is the most common). Research shows LLM Brier scores of 0.227 vs human superforecaster 0.15-0.20, with calibration errors (ECE) of 0.12-0.40. Detecting and correcting this bias produces meaningfully better probability estimates. | Medium | Flag `PROBABILITY_ANCHORING_SUSPECT` when analyst assigns exactly 60% AND dominant risk type carries friction. Require structured justification for why probability is not 50%. If justification weak (validator judges), force to 50%. This is a rare feature -- most LLM financial tools accept model-generated probabilities at face value. |
| **Sector knowledge hydration** | Industry-appropriate context transforms generic FCF-multiple analysis into sector-aware valuation. The original scanner proved this: analysts with hydrated sector context produce dramatically better valuations. Most LLM financial tools use zero-shot analysis without sector priors. | High | 8 Gemini grounded search queries per sub-sector. Validated JSON storage at `data/sectors/`. 180-day staleness threshold. Per sub-sector: key metrics, valuation approach, regulatory landscape, historical precedents, moat sources, kill factors, FCF margin ranges, typical multiples. |
| **20% CAGR exception panel (unanimous 3-agent vote)** | Candidates with 20-29.9% CAGR that show exceptional evidence (top-tier CEO + 6yr+ runway) get a structured multi-agent vote. This prevents both false rejections (good companies excluded by rigid CAGR cutoff) and false promotions (weak companies gaming the exception gate). | Medium | All three agents (analyst, validator, epistemic) independently vote approve/reject. Unanimous required. Full reasoning chain logged in provenance. Non-unanimous stays in `pending_review` with dissenting rationale. This is genuinely novel -- multi-agent voting panels for edge-case financial decisions. |
| **Evidence quality scoring** | Automated scoring of citation concreteness: counts concrete citations vs vague references per candidate. Surfaces which analyses are well-grounded vs thinly evidenced. | Low | Count named sources, specific data points, dated observations vs "industry analysis suggests", "market participants believe". Below threshold -> methodology note warning. Simple but highly effective quality gate. |
| **PCS laundering detection** | Cross-references epistemic reviewer's evidence sources against analyst's evidence. If > 80% overlap, flags `POSSIBLE_PCS_LAUNDERING` -- the reviewer is just parroting the analyst's citations instead of independently verifying. | Low | String similarity check on evidence fields. Cheap to implement, high value for maintaining epistemic independence. |
| **Contradiction detection** | Validator cross-checks analyst base case assumptions against raw FMP data. Catches systematic LLM optimism: analyst claims margin improvement but FMP shows 3-year margin erosion. | Medium | Requires structured comparison rules: revenue direction, margin trend, share count trend, FCF trajectory. Each comparison maps to a specific validation check. |
| **Holding review with forward return refresh** | Post-buy monitoring: recompute target price and forward CAGR given current price, evaluate sell triggers, assess thesis integrity, compute replacement gates. Completes the full investment lifecycle. | High | Forward return refresh, thesis integrity checklist (improved/degraded/unchanged/invalidated), sell trigger evaluation (target reached, rapid rerating, thesis break), replacement gate computation (CAGR delta > 15pp, downside profile comparison). |
| **Scan modes (sector + individual + full NYSE)** | Sector scan with broken-chart filter and clustering. Individual ticker scan. Full NYSE sweep. Restores the original scanner's complete operational capability. | Medium | Sector scan: check hydration -> pull NYSE stocks -> broken-chart filter (60%+ off ATH) -> industry exclusion -> cluster -> parallel `auto_analyze()` per cluster -> pipeline -> judge -> report. |

## Anti-Features

Features to explicitly NOT build. These are tempting but wrong for this system.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Real-time data streaming** | The Codex methodology is inherently batch-oriented. Value investing decisions are made on quarterly financial data, not tick-by-tick prices. Real-time adds complexity without analytical value. | Batch scan model with configurable scheduling. FMP caching with per-endpoint TTLs handles data freshness. |
| **Web UI / dashboard** | Adds massive surface area (auth, state management, rendering) for a single-operator tool. CLI output + JSON/markdown reports are sufficient and auditable. | CLI-only with structured JSON output and rendered markdown reports. Use existing `data/scans/json/` + `data/scans/` output structure. |
| **Portfolio tracking / brokerage integration** | Conflates analysis tool with execution tool. The scanner's job is to identify candidates and assess holdings, not manage actual positions. Brokerage APIs add regulatory and security burden. | Output holding review reports with replacement gate computations. Operator executes trades manually. |
| **Fine-tuned financial LLMs** | Fine-tuning locks you into a model version, is expensive, and creates a maintenance burden. General-purpose Claude with well-structured prompts + methodology rules + sector knowledge outperforms fine-tuned models that drift from the Codex methodology. | Use Claude Sonnet/Opus with structured system prompts containing `strategy-rules.md`, field contracts, and sector knowledge. Model is configurable per agent. |
| **Autonomous trading / auto-execution** | Catastrophically dangerous for a system built on LLM analysis that has known calibration issues (ECE 0.12-0.40). The Codex explicitly positions itself as an analysis methodology, not a trading system. | Output ranked candidates with scores, position sizing bands, and confidence caps. Human makes final buy/sell decision. |
| **Multi-user auth / collaboration** | Single-operator tool. Adding auth, permissions, and multi-tenancy adds complexity without value for the target user (one value investor running scans). | Single `.env` config. One operator. |
| **Chat-based agent interaction** | LLM agents should fill structured schemas deterministically, not engage in conversational back-and-forth. Chat introduces variability, prompt injection risk, and makes outputs non-reproducible. | Structured prompt -> structured JSON output via constrained decoding. No conversational agent interface. |
| **Agent memory across scan sessions** | Each scan must be independently reproducible from raw data. Cross-session memory creates hidden dependencies and makes results non-auditable. | Sector knowledge provides persistent context (validated JSON, explicit staleness tracking). Each scan session starts fresh from raw bundles + sector knowledge. |

## Feature Dependencies

```
FMP Caching (Step 1) -----> Schema Enrichments (Step 2) -----> Sector Knowledge (Step 3)
                                      |                                |
                                      v                                v
                              Claude Analyst Agent (Step 4) <----------+
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
              Epistemic Reviewer (Step 5)  Red-Team Validator (Step 6)
                         |                         |
                         +------------+------------+
                                      |
                                      v
                         Automated Finalization (Step 7)
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                  Scan Modes (Step 8)    Edge Case Hardening (Step 9)
                                               |
                                               |  (probability anchoring,
                                               |   20% CAGR exception,
                                               |   evidence quality)
                                               v
                         Holding Review (Step 10)

Key dependency chains:
- Schema enrichments BEFORE agents (agents fill enriched schemas)
- Sector knowledge BEFORE analyst (analyst uses sector context)
- Analyst BEFORE validator and epistemic (they review analyst output)
- All three agents BEFORE automated flow (flow orchestrates them)
- Automated flow BEFORE scan modes (scan modes invoke the flow)
- Edge case hardening AFTER automated flow (hardens the flow)
- Holding review LAST (needs entire infrastructure)
```

## MVP Recommendation

Prioritize in this exact order (matches integration plan, which is binding spec):

1. **FMP Caching** (Step 1) -- unblocks all development iteration
2. **Schema Enrichments** (Step 2) -- defines contracts agents must fill
3. **Sector Knowledge** (Step 3) -- dramatically improves analyst output quality
4. **Claude Analyst Agent** (Step 4) -- core automation, the first human-removal step
5. **Epistemic Reviewer** (Step 5) -- independent confidence assessment
6. **Red-Team Validator** (Step 6) -- adversarial contradiction detection
7. **Automated Finalization** (Step 7) -- wires agents into single-pass flow

Defer to post-MVP:
- **Scan Modes** (Step 8): operational convenience, not analytical capability
- **Edge Case Hardening** (Step 9): important for trust but core flow works without it
- **Holding Review** (Step 10): post-buy monitoring, does not block core scan capability

The first 7 steps produce a working end-to-end automated scanner for individual tickers. Steps 8-10 add operational breadth and hardening.

## Confidence Assessment

| Feature Category | Confidence | Reason |
|-----------------|------------|--------|
| Structured output enforcement | HIGH | Verified Claude structured outputs are GA on Opus 4.6 and Sonnet 4.6 with constrained decoding |
| Evidence grounding | HIGH | Existing provenance system provides the framework; research confirms grounding is critical |
| Epistemic blindness | HIGH | Architecture already designed in codebase; function signature enforcement is proven pattern |
| Probability anchoring | MEDIUM | Research confirms LLM calibration issues (ECE 0.12-0.40) but specific detection heuristics need validation |
| Sector knowledge | MEDIUM | Original scanner proved the concept; Gemini grounded search quality needs validation |
| Multi-agent consensus | MEDIUM | Academic papers describe multi-agent financial systems but production implementations are sparse |
| Holding review | MEDIUM | Codex methodology is clear but forward return computation edge cases need testing |

## Sources

- [Anthropic Structured Outputs Documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) -- Claude structured output API details
- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview) -- Agent SDK capabilities and subagent orchestration
- [TradingAgents: Multi-Agent LLM Financial Trading](https://tradingagents-ai.github.io/) -- Multi-agent financial framework patterns
- [LLM Epistemic Calibration via Prediction Markets](https://arxiv.org/html/2512.16030v1) -- LLM calibration errors (ECE 0.12-0.40), Brier scores
- [Sector-Aware LLM Financial Analysis](https://link.springer.com/article/10.1007/s10614-026-11329-4) -- Sector-conditioned LLM reasoning
- [LLM Financial Analytics Integration Guide](https://daloopa.com/blog/analyst-best-practices/financial-data-science-revolution-integrating-llms-with-traditional-analytics) -- LLM + traditional analytics integration
- [Red-Teaming LLM Multi-Agent Systems](https://arxiv.org/abs/2502.14847) -- Multi-agent security and communication attack vectors
- [LLMOps Guide 2026](https://redis.io/blog/large-language-model-operations-guide/) -- Caching strategies, token optimization
