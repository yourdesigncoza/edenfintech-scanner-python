# Batch-31 Post-Mortem: Baseline Report

**Ticker:** OMI (Owens & Minor, Inc.)
**Scan Date:** 2026-03-15
**Scan Type:** auto-scan
**Batch:** batch-31 (pre-optimization baseline)

## Purpose

This document records the analysis of the first full terminal output from the scanner pipeline, including all LLM interactions, hardening flags, and identified issues. It serves as the **baseline** for comparing future runs after the fixes applied below.

---

## Pipeline Execution Summary

| # | Agent | Model | Timestamp | Duration |
|---|-------|-------|-----------|----------|
| 1 | Gemini qualitative research | gemini-3-pro-preview | 12:24:16 | ~13 min |
| 2 | Analyst fundamentals (quant) | gpt-5-mini | 12:37:15 | ~1.7 min |
| 3 | Analyst qualitative | gpt-5-mini | 12:38:59 | ~2.3 min |
| 4 | Analyst synthesis (merged) | gpt-5-mini | 12:41:14 | ~0.4 min |
| 5 | Validator red-team | unknown* | 12:41:38 | ~0.2 min |
| 6 | Validator pre-mortem | unknown* | 12:41:49 | ~0.5 min |
| 7 | Epistemic reviewer (blind) | unknown* | 12:42:21 | ~0.1 min |

**Total wall time:** ~18 minutes (12:23:25 to 12:42:24)
**LLM interactions log:** 12,608 lines

\* Model showed `[unknown]` due to logger bug (C1, now fixed).

---

## Issues Found and Fixes Applied

### Phase A: FMP Data Quality Infrastructure (all implemented)

**A1. Zero-Filled Statement Detection + FCF History Exclusion (CRITICAL)**
- FY2025 cash flow had all zeros (OCF=0, FCF=0, CapEx=0) yet cashAtEnd=$282M
- FY2025 income statement had revenue=$2.76B but COGS=0, grossProfit=0
- Pipeline treated 0% FCF margin as real data; LLM anchored on the "drop"
- **Fix:** Added `_check_statement_completeness()` in `fmp.py` with structural invariant heuristics. Incomplete years excluded from `fcf_margin_history_pct` and `revenue_history_b` arrays via `exclude_years` parameter. Data quality warnings added to `data_quality` dict in raw bundle.

**A2. Discontinued Operations Flag (LOW-MEDIUM)**
- OMI netIncome=-$1.1B vs netIncomeFromContinuingOps=-$102.7M (~$1B gap from writedowns)
- **Fix:** Extract `netIncomeFromContinuingOperations` in `_compute_trailing_ratios()`. Flag when gap > 15% of abs(netIncome). Surfaced in `data_quality` dict.

**A3. isActivelyTrading Warning (LOW)**
- FMP profile said `isActivelyTrading: false` for OMI but pipeline didn't check
- **Fix:** Extracted into `data_quality` dict. Warning-only, no hard block.

### Phase B: Hardening & Evidence Fixes (all implemented)

**B1. Probability Anchoring Regex False Positives (HIGH)**
- `\b0\.\d+\b` in `_THESIS_ANCHORING_PATTERN` matched ALL decimals (e.g., "interest coverage = 0.26"), causing false `THESIS_BREAK_PROBABILITY_ANCHORING` flags
- **Fix:** Removed bare decimal pattern. Now requires probability context words (bidirectional: "probability of 0.15" and "0.15 probability").

**B2. Gemini URL Evidence Classification (MEDIUM)**
- Gemini `vertexaisearch.cloud.google.com/grounding-api-redirect/` URLs classified as "vague" (not in `CONCRETE_SOURCE_MARKERS`)
- Batch-31 result: 19/46 concrete citations (41.3%) — below 50% threshold
- **Fix:** Added Gemini grounding domains + URL regex fallback (`https?://`) to `is_weak_evidence()`. Any URL now treated as concrete evidence.

### Phase C: LLM Logger (implemented)

**C1. [unknown] Model in Log**
- `wrap_transport()` relied on `payload.get("model")` but OpenAI transport strips model from payload
- **Fix:** Added `model_name` kwarg fallback to `wrap_transport()`. Passed `config.llm_model` from `automation.py`.

### Phase D: Integration (all implemented)

**D1. data_quality in Manifest**
- `data_quality` flags now surfaced in hardening output via `scanner.py`

**D2. data_quality in Analyst Prompt**
- `_format_data_quality_warning()` prepends DATA QUALITY WARNING block to analyst prompts when incomplete statements detected, preventing LLM from hallucinating crisis narratives around zero-filled years.

### Context Deduplication (implemented)

**Problem:** Full `raw_candidate` (50-200KB) passed to all 3 analyst stages. Stages 2 and 3 don't need 5 years of raw financial statements — Stage 1 already analyzed them.

**Fix:** Added `_build_slim_candidate()` in `analyst.py` that shallow-copies raw_candidate and replaces 3 bulky `fmp_context` arrays (`annual_income_statements`, `annual_cash_flows`, `annual_balance_sheets`) with placeholder strings. Stage 2 and Stage 3 prompt builders now use slim candidate. Stage 1 unchanged.

**Expected savings:** 40-60% fewer input tokens on Stage 2 and Stage 3 calls.

---

## Batch-31 Baseline Metrics (pre-optimization)

### Hardening Flags

```json
{
  "anchoring": null,
  "evidence_quality": {
    "total_citations": 46,
    "concrete_count": 19,
    "vague_count": 27,
    "concrete_ratio": 0.413,
    "methodology_warning": "Evidence quality below threshold: 19/46 concrete citations (41.3%). Minimum 50% concrete evidence required."
  },
  "cagr_exception": null,
  "thesis_break": {
    "flag": "THESIS_BREAK_PROBABILITY_ANCHORING",
    "reason": "Thesis invalidation condition contains probability anchor in early_warning_metric: 'trailing interest coverage = 0.26'"
  }
}
```

### Screening Verdicts

| Check | Verdict |
|-------|---------|
| industry_understandable | true |
| industry_in_secular_decline | false |
| double_plus_potential | true |
| solvency | BORDERLINE_PASS |
| dilution | PASS |
| revenue_growth | BORDERLINE_PASS |
| roic | FAIL |
| valuation | BORDERLINE_PASS |

### Epistemic Inputs

| Question | Answer |
|----------|--------|
| q1_operational_feasibility | MODERATE |
| q2_risk_bounded | WEAK |
| q3_precedent_grounded | STRONG |
| q4_downside_steelmanned | MODERATE / STRONG |
| q5_catalyst_concrete | STRONG / MODERATE |

### Key Analysis Outputs

- **Setup pattern:** SOLVENCY_SCARE
- **Catalyst classification:** VALID_CATALYST
- **Dominant risk type:** Operational/Financial
- **Final cluster status:** CONDITIONAL_WINNER
- **Base probability:** 40%
- **Pre-mortem imminent_break_flag:** true (capital structure — strong_evidence)
- **Validator verdict:** APPROVE_WITH_CONCERNS (5 objections)

### Data Quality Issues (detected post-hoc, now automated)

| Issue | FY2025 Value | Real Situation |
|-------|-------------|----------------|
| FCF margin | 0.0% (treated as real) | Unknown (zero-filled CF statement) |
| Operating cash flow | $0 | Unknown (zero-filled) |
| Cost of revenue | $0 | Unknown (zero-filled IS) |
| Net income | -$1.1B | -$102.7M continuing ops + ~$998M writedown |
| isActivelyTrading | false | Company still trading on NYSE |

### LLM Interaction Log Size

- **Total lines:** 12,608
- **Estimated context duplication:** ~60% of lines are repeated raw_candidate data across stages

---

## Batch-32 Results (post-fix comparison)

**Scan Date:** 2026-03-15
**LLM interactions log:** `runs/batch-32/OMI/raw/llm-interactions.md`

### Fix Verification

| # | Fix | Batch-31 | Batch-32 | Status |
|---|-----|----------|----------|--------|
| A1 | FY2025 excluded from derived history | `revenue_history_b` includes 2025 ($2.762B), `fcf_margin_history_pct` includes 2025 (0.0%) | Starts at FY2024 ($10.7B rev, -0.62% FCF). `latest_revenue_b` corrected from $2.762B to $10.7B | FIXED |
| A2 | Discontinued ops flag | Not present | `discontinued_ops_flag: true` in `data_quality` | FIXED |
| A3 | isActivelyTrading warning | Not surfaced | `is_actively_trading: false` in `data_quality` | FIXED |
| B1 | Probability anchoring false positive | `THESIS_BREAK_PROBABILITY_ANCHORING` on "interest coverage = 0.26" | No false trigger | FIXED |
| B2 | Evidence concrete ratio | 41.3% (19/46) | Not persisted to file | UNVERIFIABLE |
| C1 | Model names in log | 4/7 known, 3 `[unknown]` (calls 5-7) | 6/6 known (all `gpt-5-mini`) | FIXED |
| D1 | data_quality in manifest | Not present | `has_incomplete_statements`, `discontinued_ops_flag`, `is_actively_trading` all surfaced | FIXED |
| D2 | DATA QUALITY WARNING in analyst prompts | Not present | Present: "FMP API returned incomplete data for: FY2025 (Cash Flow, Income Statement, Balance Sheet)" | FIXED |
| -- | Slim candidate (Stage 2/3) | Full `annual_income_statements/cash_flows/balance_sheets` in all stages | Raw arrays only in Stage 1; Stages 2/3 stripped | FIXED |
| -- | Prompt says "or prior stage outputs" | No | Yes | FIXED |

### Key Metrics Comparison

| Metric | Batch-31 | Batch-32 | Target | Verdict |
|--------|----------|----------|--------|---------|
| LLM log lines | 12,608 | 12,728 | ~8,000-9,000 | MISS (+0.95%) |
| LLM log bytes | 699KB | 738KB | ~400-500KB | MISS (+5.6%) |
| Calls logged | 7 | 6 | 7 | REGRESSION |
| Models identified | 4/7 (57%) | 6/6 (100%) | 100% | FIXED |
| Analyst output total | 107KB | 155KB | <=107KB | REGRESSION (+45%) |
| ROIC rejection basis | FY2025 incomplete ($5.23M EBIT, -$461M equity) | FY2024 real data (-0.62% FCF margin) | Real data | FIXED |

### Pipeline Execution (batch-32)

| # | Agent | Model | Timestamp |
|---|-------|-------|-----------|
| -- | Gemini qualitative | gemini-3-pro-preview | NOT LOGGED (cache hit) |
| 1 | analyst/fundamentals* | gpt-5-mini | 14:30:57 |
| 2 | analyst/qualitative* | gpt-5-mini | 14:33:07 |
| 3 | analyst/synthesis* | gpt-5-mini | 14:35:40 |
| 4 | validator/red_team | gpt-5-mini | 14:36:51 |
| 5 | validator/pre_mortem | gpt-5-mini | 14:37:05 |
| 6 | epistemic_reviewer | gpt-5-mini | 14:37:22 |

\* Logged as `epistemic_reviewer` due to label inference bug (E1, fix planned).

### Epistemic Review Comparison

| Question | Batch-31 | Batch-32 |
|----------|----------|----------|
| q1_operational_feasibility | MODERATE | MODERATE |
| q2_risk_bounded | STRONG | STRONG |
| q3_precedent_grounded | MODERATE | MODERATE |
| q4_downside_steelmanned | STRONG | STRONG |
| q5_catalyst_concrete | MODERATE | MODERATE |
| weak_evidence_flags | 2/5 | 5/5 |

Batch-32 reviewer cites generic "Trailing Financial Ratios (audited statements)" vs batch-31's specific sources ("Apria acquisition (2022) M&A record", "2025 balance sheet"). All 5 weak_evidence_flags triggered in batch-32 may reflect the added data quality conservatism.

### Analysis Quality Improvements

- `latest_revenue_b` corrected: $2.762B (garbage FY2025) -> $10.7B (real FY2024)
- `trough_revenue_b` corrected: $2.762B -> $9.785B
- Analyst provenance explicitly references `data_quality` warnings and caveats FY2025
- Validator thesis_invalidation has 5 structured conditions with `evidence_status` grading (vs 3 simpler in batch-31)
- Pipeline rejects OMI on real financials (FY2024 negative FCF) instead of corrupt FY2025 zeros

### New Issues Found in Batch-32

**E1. Call labels wrong (pre-existing, not caught in batch-31)**
`_infer_agent()` checks `"epistemic" in lower` before `"analyst" in lower`. Analyst prompts contain `"epistemic_inputs"` as an output field name, triggering wrong label. All 3 analyst calls labeled `epistemic_reviewer`.

**E2. Gemini cache hits not logged**
`wrap_gemini_transport` wraps the HTTP transport, but when Gemini serves from cache the transport is never called. Batch-32 has 6 calls logged vs batch-31's 7 — the Gemini call is missing.

**E3. Log size did not shrink despite slim candidate**
Log grew by 39KB despite: (a) one fewer call logged, (b) raw financial arrays stripped from Stage 2/3 prompts. Root cause: analyst LLM outputs grew +45% (fundamentals +80%, synthesis +46%) due to richer provenance and data_quality references. Additionally, sector context (~80KB) is duplicated 3x across analyst calls, and forwarded stage outputs add ~300KB of duplicated content.

**E4. Evidence quality not persisted**
Hardening metrics (evidence_quality ratio, thesis_break flags) are computed at runtime and printed to terminal but never written to a file. Cannot verify B2 fix from artifacts alone.

**E5. Epistemic reviewer evidence sourcing degraded**
Batch-32 uses generic evidence_source strings ("Trailing Financial Ratios (audited statements) and Thesis Summary/Catalysts") vs batch-31's specific sources. May need prompt refinement.

---

## Fixes Planned for Batch-33

Plan: `docs/plans/2026-03-15-llm-log-dedup-plan.md`

| # | Fix | Addresses |
|---|-----|-----------|
| 1 | Reorder `_infer_agent()` with specific analyst sub-stage patterns | E1 |
| 2 | Content-hash elision in `write_markdown()` — replace duplicate fenced code blocks >2KB with `[ELIDED: See Call N]` references | E3 |
| 3 | `record_cache_hit()` on `LlmInteractionLog` + wire in `automation.py` for Gemini cache hits | E2 |

### Not addressed yet (future work)

- **E4**: Persist hardening metrics to `raw/hardening-result.json`
- **E5**: Epistemic reviewer prompt refinement for specific evidence sourcing

### Key Metrics to Track in Batch-33

| Metric | Batch-31 | Batch-32 | Batch-33 Target |
|--------|----------|----------|-----------------|
| LLM log bytes | 699KB | 738KB | ~150-200KB |
| LLM log lines | 12,608 | 12,728 | ~3,000-5,000 |
| Calls logged | 7 | 6 | 7 (Gemini cache hit + 6 LLM) |
| Call labels correct | 4/7 | 3/6 | 7/7 |
| Elision markers | N/A | N/A | Multiple (sector ctx, stage fwd) |
| LLM outputs unchanged | -- | -- | Same schema/structure |
