# Pitfalls Research

**Domain:** LLM-automated financial stock scanning pipeline
**Researched:** 2026-03-10
**Confidence:** HIGH (domain-specific, verified against codebase and current literature)

## Critical Pitfalls

### Pitfall 1: Probability Anchoring and Overconfidence

**What goes wrong:**
LLMs default to round, moderate-sounding probabilities -- especially 60% and 70% -- regardless of the actual evidence quality. Research confirms LLMs exhibit systematic overconfidence: even when explicitly anchored to 50%, models show "irrational upward drift" in confidence. In this pipeline, the analyst agent assigns `base_probability_pct` from a constrained set (50, 60, 70, 80). The most common failure is the agent picking 70% as a safe middle ground for every stock, making the probability field decorative rather than discriminating.

Compounding this: LLMs show confirmation bias, clinging to initial judgments even when counter-evidence accumulates. Once the analyst drafts a bullish thesis, it will unconsciously select the probability that supports the thesis rather than the one the evidence warrants.

**Why it happens:**
LLM training rewards confident, decisive-sounding text. Probability estimation requires genuine uncertainty quantification, which is fundamentally at odds with the generative objective. The model has no internal calibration mechanism -- it produces text that *sounds* like calibrated probability rather than text that *is* calibrated.

**How to avoid:**
- Require the analyst to generate the worst case BEFORE the base case (already in the integration plan, Step 4). This forces pessimistic framing first.
- Require structured justification for why probability is NOT one band lower. The field `probability_inputs.base_rate` + `likert_adjustments` exists in the schema but must be enforced: the analyst must cite a named base rate and show each adjustment step.
- Implement the anchoring detection from Step 9: flag `PROBABILITY_ANCHORING_SUSPECT` when 60% is assigned alongside a friction-carrying risk type (Regulatory/Political = -2, Legal/Investigation = -2). Force the agent to justify why not 50%.
- Track distribution across scans: if > 60% of analyst outputs use the same probability band, emit a pipeline warning.

**Warning signs:**
- Probability distribution across a sector scan clusters at a single band (e.g., 8 of 10 stocks get 70%).
- `likert_adjustments` field contains vague text like "overall favorable" without specific evidence references.
- Base rate field says something generic like "historical average for value stocks" without a named source or number.

**Phase to address:**
Step 4 (Claude Analyst Agent) for prompt discipline. Step 9 (Probability Anchoring Hardening) for automated detection and correction.

---

### Pitfall 2: Information Barrier Leaks in Epistemic Review

**What goes wrong:**
The epistemic reviewer is supposed to assess confidence *blind* to scores, probabilities, and valuations -- it sees only the qualitative thesis. If the barrier leaks, the reviewer's PCS (Probabilistic Confidence Score) answers become rubber-stamps of the analyst's numbers rather than independent assessments. The barrier must be code-enforced (function signature), not prompt-enforced ("please ignore the scores").

The subtle version: even without seeing raw scores, the reviewer can *infer* them. If the thesis summary says "30% CAGR with 70% probability," the barrier is effectively broken. Similarly, if the evidence bundle includes fields that encode scores (like `decision_score` or `position_size`), the reviewer has been compromised.

**Why it happens:**
Prompt-based barriers fail because LLMs treat all context as relevant. A prompt instruction saying "ignore the following fields" is about as reliable as telling a human to ignore the elephant in the room. Even well-intentioned developers pass "the whole object" to the reviewer for convenience, accidentally including scored fields.

**How to avoid:**
- The function signature for `run_epistemic_review()` MUST accept only: `ticker`, `industry`, `thesis_summary`, `key_risks`, `catalysts`, `moat_assessment`, `dominant_risk_type`. This is already specified in the integration plan (Step 5). Enforce via type hints and a whitelist -- reject any kwarg not in the allowed set.
- Sanitize `thesis_summary` before passing to the reviewer: strip any numeric values that could encode scores. Use a regex to detect patterns like "$X target" or "X% CAGR" or "X% probability" and redact them.
- The reviewer's Gemini grounded search (Q3 precedent verification) must be independent -- it cannot reuse the analyst's search results or evidence bundle.
- Test the barrier with a "canary field" approach: inject a unique sentinel value into the score fields and verify it never appears in the reviewer's output.

**Warning signs:**
- PCS answers correlate suspiciously well with analyst probability (e.g., analyst says 70%, reviewer gives 4/5 or 5/5 on all questions).
- Reviewer's evidence citations overlap > 80% with analyst's (the `POSSIBLE_PCS_LAUNDERING` flag from Step 5).
- Reviewer output contains specific dollar amounts or percentages that only exist in the scored overlay.

**Phase to address:**
Step 5 (Epistemic Reviewer Agent). Must be enforced at the code level during implementation, not deferred to hardening.

---

### Pitfall 3: Structured Output Schema Drift and Silent Corruption

**What goes wrong:**
The Claude analyst must produce JSON conforming to `structured-analysis.schema.json`. Even with structured output modes, LLMs can produce *semantically* wrong output that passes *syntactic* validation. Examples specific to this pipeline:
- Revenue in millions instead of billions (the schema uses `revenue_b` but the LLM fills it with 3000 instead of 3.0).
- FCF margin as a decimal (0.10) instead of percentage (10.0) -- the field is `fcf_margin_pct`.
- Shares in raw count instead of millions -- `shares_m` expects millions.
- `multiple` field filled with P/E ratio when the system uses FCF multiples.
- Catalyst classification text that technically validates against the enum but is semantically wrong for the setup pattern.
- Boolean fields (`industry_understandable`, `industry_in_secular_decline`) that the LLM sets to the "safe" default rather than the evidence-grounded answer.

This is distinct from JSON parsing failures (which modern structured output largely solves). The danger is *valid JSON with wrong values*.

**Why it happens:**
Schema validation checks types and enums but cannot validate semantic correctness. The LLM has seen millions of financial documents using inconsistent unit conventions. Without explicit unit reminders in the prompt, it will use whatever convention its training data most commonly associates with the field name.

**How to avoid:**
- Add unit assertions in the pipeline AFTER the analyst fills fields but BEFORE scoring. Specific checks:
  - `revenue_b` must be < 1000 (no public company has $1T+ revenue; catches millions-instead-of-billions).
  - `fcf_margin_pct` must be between -100 and 100 (catches decimal-vs-percentage confusion).
  - `shares_m` must be > 0.1 and < 50000 (catches raw-count-vs-millions).
  - `multiple` must be between 1 and 100 (catches earnings-vs-FCF confusion and absurd values).
- Cross-validate LLM-filled values against FMP raw data. The raw bundle contains `derived.latest_revenue_b`, `derived.latest_fcf_margin_pct`, `derived.shares_m_latest`. If the LLM's values deviate by more than 10x from the raw data without an explicit justification, flag it.
- Include explicit unit examples in the analyst prompt: "revenue_b: revenue in billions of USD (e.g., 3.2 means $3.2 billion)".

**Warning signs:**
- CAGR calculations produce absurd results (> 500% or negative) after analyst fills fields.
- Floor price or target price is orders of magnitude different from current price.
- `valuation_target_price()` in `scoring.py` produces prices that don't pass a sanity check against the current market price.

**Phase to address:**
Step 4 (Claude Analyst Agent) for prompt engineering. Step 7 (Automated Finalization Flow) for validation gates between analyst output and deterministic pipeline.

---

### Pitfall 4: Evidence Quality Inflation and Citation Fabrication

**What goes wrong:**
The analyst agent is required to write `review_note` per field citing specific evidence. LLMs are known to fabricate plausible-sounding but non-existent citations. In a financial context, this means:
- Citing a quarterly earnings call that didn't happen yet or doesn't exist.
- Referencing "management commentary from Q3 2025 10-K" when the company only files 10-Qs quarterly.
- Attributing a claim to "FMP data" when the claim isn't in the raw bundle.
- Describing a catalyst as "announced" when the Gemini research only found analyst speculation.

The `issues_and_fixes` field with its evidence status enum (`ANNOUNCED_ONLY`, `ACTION_UNDERWAY`, `EARLY_RESULTS_VISIBLE`, `PROVEN`) is particularly vulnerable: the LLM will upgrade evidence status to make the thesis more compelling.

**Why it happens:**
LLMs generate text that is *plausible given the context*, not text that is *verified against the context*. The model optimizes for coherence, and a well-cited analysis is more coherent than one full of `NO_EVIDENCE` markers. The training data contains countless financial analyses with citations, so the model has strong priors on what a "good" citation looks like.

**How to avoid:**
- Implement evidence grounding verification in the validator agent (Step 6): the validator receives the raw evidence bundle and must cross-check every claim the analyst makes. If the analyst says "revenue grew 15% in FY2025," the validator checks whether FMP data confirms this.
- For `issues_and_fixes`, require the analyst to quote the exact text from the Gemini research that supports each evidence status level. The validator then verifies the quote exists in the raw bundle.
- Evidence quality scoring (Step 9): count concrete vs. vague citations. A "concrete citation" references a specific document, date, and data point. A "vague reference" says things like "according to industry analysis" or "based on available data."
- The `review_note` field per provenance entry MUST reference a specific `evidence_refs` entry by path. Don't allow freeform review notes that aren't anchored to the evidence context.

**Warning signs:**
- Review notes cite sources not present in `evidence_context` or `gemini_context`.
- All `issues_and_fixes` entries are rated `ACTION_UNDERWAY` or higher (statistically unlikely for most stocks).
- Evidence quality score is suspiciously high (> 90%) across all candidates in a scan.
- Dates in citations don't match the scan date or are in the future.

**Phase to address:**
Step 4 (Analyst prompt discipline), Step 6 (Red-Team Validator cross-checking), Step 9 (Evidence Quality Scoring).

---

### Pitfall 5: Multi-Agent Consensus as Rubber-Stamping

**What goes wrong:**
The pipeline uses three agents: analyst, validator, and epistemic reviewer. Research on multi-agent LLM systems identifies "Silent Agreement" and "Toxic Agreement" as primary failure modes -- agents converge on the same conclusion without genuine debate. In this pipeline:
- The validator receives the analyst's overlay and "approves" it without finding real contradictions because the analyst's output is well-structured and internally consistent (even if wrong).
- The 20% CAGR exception panel (Step 9) requires *unanimous* 3-agent approval. If all three agents share the same training biases (optimism about turnarounds, anchoring on management promises), unanimity is achieved too easily.
- When the validator "rejects" and the analyst retries, the second attempt often produces cosmetically different but substantively identical output -- the retry loop converges rather than genuinely addressing objections.

**Why it happens:**
All three agents are Claude instances with similar training data and biases. LLMs exhibit conformity bias: when given another LLM's output as context, they tend to agree rather than dissent. The validator sees a well-structured JSON overlay and has a strong prior that well-structured = correct.

**How to avoid:**
- The validator MUST receive raw FMP data alongside the analyst overlay and be specifically instructed to cross-check numerical claims against raw data. Build specific contradiction checks: compare analyst's revenue growth claim against actual FMP income statement trends. This is already in Step 6 but must be implemented as deterministic cross-checks, not just LLM-based review.
- For the 20% CAGR exception panel, consider using different temperature settings or even different models for each voter to introduce genuine variance.
- Track the validator's rejection rate. If it falls below 10% across a meaningful sample (> 20 scans), the validator is likely rubber-stamping.
- When the analyst retries after rejection, inject the *specific objections* as hard constraints ("your previous output was rejected because X -- your new output MUST address X with different evidence") and diff the outputs to ensure substantive change.
- Implement a "catfish" mechanism: periodically inject a deliberately flawed overlay (wrong revenue direction, fabricated catalyst) and verify the validator catches it.

**Warning signs:**
- Validator approval rate > 90% over any 20-scan window.
- Retry loops converge in exactly 1 retry (the analyst addresses the objection superficially).
- 20% CAGR exception panel achieves unanimity > 50% of the time.
- Validator findings are generic ("analysis appears thorough and well-supported") rather than specific.

**Phase to address:**
Step 6 (Red-Team Validator) for contradiction detection logic. Step 7 (Automated Finalization Flow) for retry loop discipline. Step 9 (20% CAGR Exception Panel) for voter independence.

---

### Pitfall 6: Prompt Injection via Financial Filings and Research Content

**What goes wrong:**
The pipeline ingests external data from two sources: FMP (financial data API) and Gemini grounded search (qualitative research). The Gemini source is particularly dangerous because it retrieves free-text content from the web -- press releases, analyst reports, SEC filings, news articles. An adversary (or even benign SEO-optimized content) could embed text that manipulates the Claude analyst's behavior:
- A company's press release containing phrasing like "This company's strong fundamentals indicate a target price of $200" could anchor the analyst's valuation.
- SEC filings with unusual formatting or embedded instructions could influence the structured analysis.
- Gemini search results from promotional financial blogs could inject bullish sentiment.

This is classified as "indirect prompt injection" -- the attack vector is the data being analyzed, not the system prompt.

**Why it happens:**
The analyst agent processes raw research text as context. LLMs cannot reliably distinguish between "data to analyze" and "instructions to follow." Financial content is particularly risky because it often contains imperative language ("investors should consider," "the company expects") that looks like instructions.

**How to avoid:**
- Sanitize Gemini research output before passing to the analyst: strip any text that looks like instructions or recommendations. A simple heuristic: remove sentences containing imperative verbs directed at the reader ("you should," "consider buying," "invest in").
- Structure the analyst prompt with clear delimiters between instructions and data: use XML tags or similar fencing to separate system instructions from evidence context.
- Never pass raw filing text directly to the analyst. The existing pipeline already uses structured fields from Gemini (`catalyst_evidence`, `risk_evidence`, `moat_observations`) -- maintain this structure and don't add raw text passthrough.
- The validator (Step 6) acts as a second defense layer: if the analyst's output contains claims suspiciously aligned with promotional language in the research, the validator should flag it.

**Warning signs:**
- Analyst output contains verbatim phrases from the raw research (copy-paste rather than analysis).
- Target price or valuation assumptions exactly match numbers mentioned in press releases or analyst reports.
- Thesis summary reads like a press release rather than an independent analysis.

**Phase to address:**
Step 3 (Sector Knowledge Framework) for input sanitization patterns. Step 4 (Claude Analyst Agent) for prompt structure. Step 6 (Red-Team Validator) for adversarial detection.

---

### Pitfall 7: API Cost Explosion During Development and Sector Scans

**What goes wrong:**
A sector scan involves: hydrating sector knowledge (8 Gemini queries per sub-sector), fetching FMP data for potentially dozens of stocks, then running 3 Claude agents per surviving candidate. With Claude Sonnet at $3/$15 per million input/output tokens and Opus at $5/$25, a single sector scan with 30 candidates could cost $15-50 in Claude API calls alone. During development, iterating on prompts without caching means burning this cost repeatedly. The 20% CAGR exception panel triples the agent cost for edge cases.

Extended thinking (if used for complex analysis) compounds costs further since thinking tokens bill at output rates.

**Why it happens:**
Developers iterate on prompts by running full pipeline tests. Each iteration reruns all three agents. FMP caching (Step 1) prevents redundant data fetches, but there's no equivalent for Claude prompt caching during development. Sector scans fan out to many stocks, and the screening funnel (broken-chart filter, industry exclusion) runs AFTER expensive data retrieval.

**How to avoid:**
- Use Anthropic's prompt caching: the system prompt (methodology rules, field contracts, strategy-rules.md) is identical across all analyst calls. Cache it with the 1-hour TTL ($0.30 write, $0.003 read per million tokens vs. $3.00 input). This alone reduces analyst input costs by 80%+ after the first call.
- Move screening filters BEFORE expensive operations: apply the broken-chart filter and industry exclusion using FMP screener data (cheap, cached) before fetching full financials or running Claude agents.
- Use the Batch API (50% discount) for non-interactive sector scans where latency doesn't matter.
- During development, use Claude Haiku ($1/$5) for prompt iteration and only switch to Sonnet/Opus for validation runs.
- Implement a token budget per scan run with a hard ceiling. Log cumulative token usage and abort if a scan exceeds the budget.
- Cache analyst/validator/reviewer outputs per (ticker, raw_bundle_fingerprint) pair so re-runs with the same data don't re-invoke agents.

**Warning signs:**
- Monthly API bill exceeds budget after the first week of development.
- Token logs show repeated identical system prompts without cache hits.
- Sector scans run all three agents on stocks that would have been filtered by the screener.

**Phase to address:**
Step 1 (FMP Caching) for data-layer caching. Step 4 (Claude Analyst Agent) for prompt caching implementation. Step 8 (Scan Modes) for screening funnel ordering.

---

### Pitfall 8: Cache Staleness Causing Stale-Data Investment Decisions

**What goes wrong:**
The FMP caching layer (Step 1) uses per-endpoint TTLs: price-history = 1 day, screener = 7 days, financials = 90 days. A stock's fundamentals can change dramatically between quarterly filings. If the cache serves 85-day-old financial data for a company that just reported a terrible quarter, the analyst builds a thesis on stale numbers. Worse, the pipeline's fingerprint continuity system means the stale raw bundle flows through the entire pipeline with full traceability -- giving a false sense of rigor to outdated data.

The sector knowledge cache (180-day staleness) is similarly dangerous: industry dynamics can shift rapidly (regulatory changes, competitive disruption).

**Why it happens:**
TTLs are set for API efficiency, not analytical accuracy. A 90-day TTL for financials seems reasonable because companies report quarterly, but earnings dates aren't evenly distributed and the TTL doesn't align with the company's actual reporting calendar.

**How to avoid:**
- Implement a `--fresh` bypass flag (already in Step 1) that forces refetch for the current scan target.
- Cross-check cached financial data dates against the company's most recent earnings date (available via FMP's earnings calendar endpoint). If the cache is from before the latest earnings, auto-invalidate.
- Add a `cache_age_warning` field to the raw bundle metadata. If any cached data source is > 50% through its TTL, emit a warning in the scan report.
- For sector knowledge, check whether any significant regulatory or competitive events have occurred since hydration (a lightweight Gemini query).
- The `--fresh` flag should be the DEFAULT for individual ticker scans (`auto-scan`). Caching primarily benefits sector scans where you're screening dozens of stocks and only a few survive to full analysis.

**Warning signs:**
- Analyst thesis contradicts recent news (the news is newer than the cached data).
- FMP `derived` fields show data from a prior fiscal year when a new year's data is available.
- Multiple stocks in a sector scan share identical financial data timestamps (batch-cached, not individually refreshed).

**Phase to address:**
Step 1 (FMP Caching Layer) for cache design. Step 8 (Scan Modes) for default cache behavior per scan mode.

---

### Pitfall 9: Provenance Status Confusion Between Human and LLM Review

**What goes wrong:**
The existing pipeline has two finalization statuses: `HUMAN_CONFIRMED` and `HUMAN_EDITED`. The integration plan adds `LLM_DRAFT`, `LLM_CONFIRMED`, and `LLM_EDITED`. The danger is treating LLM confirmation as equivalent to human confirmation. If the `finalize_structured_analysis()` function accepts `LLM_CONFIRMED` as a valid final status, the entire provenance system -- designed to ensure human accountability -- is silently bypassed.

Additionally, if a human later reviews an LLM-finalized overlay, the provenance should show the upgrade from `LLM_CONFIRMED` to `HUMAN_CONFIRMED`, not overwrite it. Losing the audit trail of who (human vs. LLM) made each decision defeats the purpose of provenance tracking.

**Why it happens:**
The `FINAL_PROVENANCE_STATUSES` set in `structured_analysis.py` currently only contains `{"HUMAN_EDITED", "HUMAN_CONFIRMED"}`. Adding LLM statuses requires deciding whether they're "final" or "intermediate." The temptation is to add them as final to avoid breaking the existing flow.

**How to avoid:**
- Keep `LLM_CONFIRMED` as a DISTINCT status that is NOT in `FINAL_PROVENANCE_STATUSES`. Instead, create a separate `LLM_FINAL_STATUSES` set and a separate `finalize_structured_analysis_llm()` path.
- The `apply_structured_analysis()` function should accept both human and LLM finalized overlays, but the scan report should clearly indicate which path was used.
- Maintain a provenance history (not just current status): `[MACHINE_DRAFT -> LLM_DRAFT -> LLM_CONFIRMED]` vs `[MACHINE_DRAFT -> HUMAN_EDITED -> HUMAN_CONFIRMED]`. This is a list of transitions, not a single status field.
- Add an `automation_level` field to the scan report: `"fully_automated"`, `"llm_with_human_review"`, `"human_reviewed"`.

**Warning signs:**
- `finalize_structured_analysis()` starts accepting `LLM_CONFIRMED` in the same code path as `HUMAN_CONFIRMED`.
- Scan reports don't distinguish between human-reviewed and LLM-reviewed candidates.
- `FINAL_PROVENANCE_STATUSES` set grows to include LLM statuses without separate validation logic.

**Phase to address:**
Step 7 (Automated Finalization Flow). Must be designed carefully before implementation, not retrofitted.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Single Claude model for all agents | Simpler config, one API key pattern | Loses ability to use cheaper models for validator vs. analyst | Never -- configurable model per agent is already in the plan |
| Skipping raw data cross-validation | Faster analyst development | Silent numerical errors propagate to scores | Only during initial prompt iteration with fixture data |
| Caching Claude responses by ticker only | Simple cache key | Stale analysis when raw data changes | Never -- must include raw_bundle_fingerprint in cache key |
| Passing full overlay to validator | Simpler function signature | Information barrier violations, rubber-stamping | Never -- validator should see overlay + raw data, not scores |
| Hardcoding prompt templates in Python | Faster iteration | Methodology changes require code changes | MVP only -- move to `assets/` alongside strategy-rules.md |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Claude API (Anthropic SDK) | Not using prompt caching for repeated system prompts | Mark system prompt blocks with `cache_control: {"type": "ephemeral"}` for 5-min TTL or use 1-hour caching for methodology content |
| Claude structured output | Trusting JSON schema enforcement alone for semantic correctness | Layer domain-specific validators on top: unit checks, range checks, cross-validation against raw FMP data |
| Gemini Grounded Search | Treating search results as verified facts | Treat as unverified claims requiring cross-reference. Tag each piece of research with source URL and retrieval date |
| FMP API | Assuming all endpoints return the same shape across time | Use response-shape drift testing (already in test fixtures). Pin expected fields and alert on new/missing fields |
| OpenAI Judge | Assuming the judge will always be available | The existing fallback to `local_judge()` is correct. Maintain the deterministic fallback as the floor |
| Multiple LLM providers (Claude + Gemini + OpenAI) | Inconsistent error handling and retry logic across providers | Create a shared transport abstraction with unified retry, timeout, and error classification |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Serial agent execution per candidate | Full sector scan takes 30+ minutes | Run analyst calls in parallel across candidates within a cluster (already planned) | > 10 candidates per cluster |
| Unthrottled Gemini grounded search | Rate limiting causes scan failures mid-run | Implement backoff with jitter, max 8 queries per sub-sector, reuse sector knowledge across scans | > 3 sub-sectors hydrated in sequence |
| Full raw bundle in every Claude prompt | Token count exceeds context window for data-rich stocks | Summarize/truncate raw bundle fields that exceed a per-field token budget. Include derived metrics, not raw financial statements | Companies with 10+ years of financial history |
| No token budget tracking | Cost surprises, scan runs consuming entire monthly budget | Log tokens per agent call, per candidate, per scan. Set per-scan ceiling with abort | First sector scan in production |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging full Claude prompts with API keys in context | API key exposure in scan logs | Sanitize logs: never log headers or config objects. Use structured logging with explicit field selection |
| Storing raw Gemini search results without sanitization | Indirect prompt injection persists in cached sector knowledge | Sanitize before caching: strip HTML, remove instruction-like content, validate against expected schema |
| No rate limiting on CLI scan commands | Accidental cost explosion from scripted scan loops | Add a `--dry-run` mode that estimates cost before execution. Add a confirmation prompt for scans exceeding $X |

## "Looks Done But Isn't" Checklist

- [ ] **Analyst agent:** Often missing unit validation -- verify `revenue_b`, `fcf_margin_pct`, `shares_m`, `multiple` are in expected ranges by cross-checking against FMP raw data
- [ ] **Epistemic reviewer:** Often missing information barrier testing -- verify the function signature physically cannot receive score/probability fields, not just that the prompt says to ignore them
- [ ] **Validator agent:** Often missing negative test cases -- verify it actually rejects a deliberately flawed overlay, not just that it approves good ones
- [ ] **20% CAGR exception panel:** Often missing independence verification -- verify the three voters don't see each other's votes, and that rejection is genuinely possible
- [ ] **Provenance trail:** Often missing transition history -- verify the system records the full status chain, not just the final status
- [ ] **Cache invalidation:** Often missing earnings-date awareness -- verify cached financials are invalidated when new quarterly data is available
- [ ] **Sector knowledge:** Often missing staleness enforcement -- verify the 180-day warning actually fires and blocks stale knowledge from feeding the analyst
- [ ] **Prompt caching:** Often missing cache hit verification -- verify Anthropic API responses include `cache_read` token counts, confirming the cache is actually being used

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Probability anchoring undetected | LOW | Re-run affected scans with anchoring detection enabled. Compare pre/post distributions. Flag candidates whose scores changed materially |
| Information barrier leak | MEDIUM | Audit all epistemic review outputs. Re-run reviews with confirmed barrier. Compare PCS scores -- significant changes indicate previous leak |
| Unit confusion in analyst output | LOW | Add unit validation gate. Re-run `scoring.py` on all existing overlays with range checks. Any that fail were scored incorrectly |
| Evidence fabrication in citations | HIGH | No automated recovery. Must manually verify a sample of citations against raw bundles. If fabrication rate is high, all LLM-generated overlays are suspect |
| Rubber-stamp validator | MEDIUM | Inject known-bad fixtures and measure catch rate. If rate is low, re-architect validator with deterministic cross-checks rather than pure LLM review |
| Cost explosion | LOW | Immediate: pause scans, review token logs. Add budget ceiling. Switch development to Haiku. Enable prompt caching and batch API |
| Stale cache data | MEDIUM | Clear cache for affected tickers. Re-run scans with `--fresh`. Add earnings-date-aware invalidation to prevent recurrence |
| Provenance confusion | HIGH | If LLM and human statuses were conflated, must audit all finalized overlays to determine true provenance. Requires schema migration to add transition history |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Probability anchoring | Step 4 (prompt), Step 9 (detection) | Distribution analysis across 20+ scans shows variance across probability bands |
| Information barrier leak | Step 5 (code-enforced) | Canary field test: inject sentinel into scores, confirm absent from reviewer output |
| Structured output semantic errors | Step 4 (prompt), Step 7 (gates) | Unit validation gate catches 100% of range violations in fixture tests |
| Evidence quality inflation | Step 4 (prompt), Step 6 (cross-check), Step 9 (scoring) | Evidence quality score correlates with actual citation verifiability in spot-checks |
| Multi-agent rubber-stamping | Step 6 (validator), Step 7 (retry logic), Step 9 (exception panel) | Validator rejection rate > 10% across a 20-scan sample; known-bad fixture test passes |
| Prompt injection via filings | Step 3 (sanitization), Step 4 (prompt structure) | Inject adversarial content in test fixtures, confirm analyst output is unaffected |
| API cost explosion | Step 1 (FMP cache), Step 4 (prompt cache), Step 8 (funnel order) | Token log shows cache hit rate > 80% for system prompts; per-scan cost within budget |
| Cache staleness | Step 1 (cache design), Step 8 (scan mode defaults) | Cached data auto-invalidates when new earnings are available (earnings calendar check) |
| Provenance confusion | Step 7 (finalization flow) | LLM and human finalization paths produce distinct provenance chains in the output JSON |

## Sources

- [Structured Output AI Reliability: JSON Schema & Function Calling Guide 2025](https://www.cognitivetoday.com/2025/10/structured-output-ai-reliability/)
- [LLM Hallucinations: What Are the Implications for Financial Institutions?](https://biztechmagazine.com/article/2025/08/llm-hallucinations-what-are-implications-financial-institutions)
- [Managing hallucination risk in LLM deployments (EY, Jan 2026)](https://www.ey.com/content/dam/ey-unified-site/ey-com/en-gl/technical/documents/ey-gl-managing-hallucination-risk-in-llm-deployments-01-26.pdf)
- [LLM01:2025 Prompt Injection - OWASP Gen AI Security Project](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [LLM Prompt Injection Prevention Cheat Sheet - OWASP](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [Evaluating LLMs in Finance Requires Explicit Bias Consideration (Feb 2026)](https://arxiv.org/html/2602.14233v1)
- [Your AI, Not Your View: The Bias of LLMs in Investment Analysis (2025)](https://arxiv.org/html/2507.20957v4)
- [Overconfidence in LLM-as-a-Judge: Diagnosis and Confidence-Driven Solution](https://arxiv.org/html/2508.06225v2)
- [Silence is Not Consensus: Disrupting Agreement Bias in Multi-Agent LLMs (2025)](https://arxiv.org/html/2505.21503v1)
- [Why Do Multi-Agent LLM Systems Fail? (ICLR 2025)](https://openreview.net/pdf?id=wM521FqPvI)
- [Risk Analysis Techniques for Governed LLM-based Multi-Agent Systems](https://arxiv.org/html/2508.05687v1)
- [Anthropic Prompt Caching Documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic API Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

---
*Pitfalls research for: LLM-automated financial stock scanning pipeline*
*Researched: 2026-03-10*
