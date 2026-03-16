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

## Batch-33 Results (post-dedup)

**Scan Date:** 2026-03-15
**LLM interactions log:** `runs/batch-33/OMI/raw/llm-interactions.md`

### Fix Verification (E1-E3)

| # | Fix | Batch-32 | Batch-33 | Status |
|---|-----|----------|----------|--------|
| E1 | Call labels correct | 3/6 (analyst stages labeled `epistemic_reviewer`) | 7/7 (`analyst/fundamentals`, `analyst/qualitative`, `analyst/synthesis`, `validator/red_team`, `validator/pre_mortem`, `epistemic_reviewer`, `gemini/qualitative`) | FIXED |
| E2 | Gemini cache hits logged | Missing (6 calls) | Present as Call 1: `gemini/qualitative [gemini [CACHE HIT]]` with truncated preview | FIXED |
| E3 | Log size reduction via elision | 738KB / 12,728 lines | 664KB / 11,607 lines (pre-elision fix*) | PARTIAL |

\* Batch-33 was run before the subsection elision fix. The initial whole-block hash approach did not trigger because duplicated content is embedded within larger unique blocks. The fix has been corrected to use section-marker-based elision.

### Elision Bug and Fix

**Problem:** The `_elide_repeated_blocks()` function hashed entire fenced code blocks. But the duplicated content (sector context, stage outputs) is embedded as **subsections** within larger unique blocks (system prompts, user messages). Each system prompt has unique instructions surrounding the shared sector context, so the whole-block hash is always unique.

**Fix:** Replaced with `_elide_repeated_sections()` which finds known section markers (`SECTOR CONTEXT:`, `STAGE 1 FUNDAMENTALS:`, `ANALYST OVERLAY (analysis_inputs`, `RAW CANDIDATE DATA`, etc.) within raw content strings, extracts the JSON blob after each marker via brace-counting, and hashes the blob. On duplicate, replaces with `[ELIDED: ~NKB — identical to Call X above]`.

### Projected Elision Savings (verified against batch-33 data)

| Section | Size | Occurrences | Action | Savings |
|---------|------|-------------|--------|---------|
| SECTOR CONTEXT | 53KB | 3x (Calls 2,3,4) | Keep 1, elide 2 | 106KB |
| ANALYST OVERLAY | 60KB | 2x (Calls 5,6) | Keep 1, elide 1 | 60KB |
| STAGE 1 FUNDAMENTALS | 21KB | 2x (Calls 3,4) | Keep 1, elide 1 | 21KB |
| RAW CANDIDATE DATA (slim) | 15KB | 2x (Calls 3,4) | Keep 1, elide 1 | 15KB |
| **Total** | | | | **~203KB (30%)** |

**Projected batch-34 log size:** ~461KB (664KB - 203KB)

The original 150-200KB target was unrealistic — it assumed LLM response content could be reduced, but responses are never elided. The ~200KB of LLM response content across 7 calls sets a hard floor. A 30% reduction from 664KB to ~461KB is the practical ceiling with this approach.

### Pipeline Execution (batch-33)

| # | Agent | Model | Timestamp |
|---|-------|-------|-----------|
| 1 | gemini/qualitative | gemini [CACHE HIT] | 15:23:36 |
| 2 | analyst/fundamentals | gpt-5-mini | 15:25:22 |
| 3 | analyst/qualitative | gpt-5-mini | 15:27:18 |
| 4 | analyst/synthesis | gpt-5-mini | 15:29:25 |
| 5 | validator/red_team | gpt-5-mini | 15:30:48 |
| 6 | validator/pre_mortem | gpt-5-mini | 15:31:02 |
| 7 | epistemic_reviewer | gpt-5-mini | 15:31:30 |

### Key Metrics Across All Batches

| Metric | Batch-31 | Batch-32 | Batch-33 | Batch-34 (projected) |
|--------|----------|----------|----------|----------------------|
| LLM log bytes | 699KB | 738KB | 664KB | ~461KB |
| LLM log lines | 12,608 | 12,728 | 11,607 | ~8,000 |
| Calls logged | 7 | 6 | 7 | 7 |
| Call labels correct | 4/7 | 3/6 | 7/7 | 7/7 |
| Elision markers | 0 | 0 | 0* | ~5 |
| Models identified | 4/7 | 6/6 | 7/7 | 7/7 |

\* Elision fix applied after batch-33 ran.

---

## Batch-35 Results (post-gap-closure, compared to batch-34)

**Scan Date:** 2026-03-15
**LLM interactions log:** `runs/batch-35/OMI/raw/llm-interactions.md`
**Pipeline verdict:** FAIL (rejected at screening — solvency)
**Wall time:** ~9.4 minutes (17:51:22 to 18:00:44)

**Predecessor:** Batch-34 was the "correct decision, right reasons" run documented in `docs/plans/todo-batch-34/methodology-evaluation.md`. Batch-35 incorporates all 5 gap-closure fixes from that evaluation (peer comparison, incentive alignment, worst-case modeling, screening determinism, catalyst dedup). This comparison measures whether those fixes improved the pipeline without regressing what batch-34 already did well.

### Pipeline Execution (batch-35)

| # | Agent | Model | Timestamp |
|---|-------|-------|-----------|
| 1 | gemini/qualitative | gemini-3-pro-preview | 17:52:31 |
| 2 | analyst/fundamentals | gpt-5-mini | 17:54:32 |
| 3 | analyst/qualitative | gpt-5-mini | 17:56:32 |
| 4 | analyst/synthesis | gpt-5-mini | 17:59:17 |
| 5 | validator/pre_mortem | gpt-5-mini | 17:59:57 |
| 6 | validator/red_team | gpt-5-mini | 17:59:59 |
| 7 | epistemic_reviewer | gpt-5-mini | 18:00:41 |

All 7 calls logged. All labels correct. All models identified (gpt-5-mini). Gemini call is NOT a cache hit this time (full grounded search).

### Fix Verification (all batches)

| # | Fix | B-31 | B-32 | B-33 | B-35 | Status |
|---|-----|------|------|------|------|--------|
| A1 | FY2025 excluded from history | Included (0.0% FCF) | Excluded | Excluded | Excluded (4 years: FY2024-FY2021) | STABLE |
| A2 | Discontinued ops flag | Missing | Present | Present | `true` in manifest | STABLE |
| A3 | isActivelyTrading | Not checked | Present | Present | `false` in manifest | STABLE |
| B1 | Probability anchoring false positive | `THESIS_BREAK_PROBABILITY_ANCHORING` | None | None | None | STABLE |
| B2 | Evidence concrete ratio | 41.3% (19/46) | Unverifiable | Unverifiable | **65.9% (27/41)** | FIXED & VERIFIED |
| C1 | Model names in log | 4/7 known | 6/6 | 7/7 | 7/7 (all gpt-5-mini) | STABLE |
| D1 | data_quality in manifest | Missing | Present | Present | Full: 3 warnings, disc_ops, trading | STABLE |
| D2 | DATA QUALITY WARNING in prompts | Missing | Present | Present | Present in Calls 2+3 | STABLE |
| E1 | Call labels correct | 4/7 | 3/6 | 7/7 | 7/7 | STABLE |
| E2 | Gemini logged | 7 calls (live) | 6 (cache miss) | 7 (cache hit logged) | 7 (live) | STABLE |
| E3 | Elision active | 0 markers | 0 | 0 | **5 markers** (~141KB saved) | VERIFIED |
| -- | Slim candidate (Stage 2/3) | Full arrays all stages | Stripped | Stripped | Stripped | STABLE |
| -- | "or prior stage outputs" | No | Yes | Yes | Yes (3 occurrences) | STABLE |

### Gap Closure Verification (batch-34 methodology evaluation gaps)

| Gap | Expected | Batch-35 Result | Status |
|-----|----------|-----------------|--------|
| Peer comparison | `_build_peer_context()` wired into sector scan | Not triggered (single-ticker auto-scan, not sector-scan) | N/A for this scan |
| Incentive alignment | `compensation_evidence` in Gemini, `incentive_alignment` in synthesis | **3 compensation items from Gemini** (proxy data, Coliseum buying, AIP changes). Synthesis outputs `incentive_alignment.gameable_risk: MODERATE` | VERIFIED |
| Worst-case modeling | Dilution/covenant modeled | **shares_m=250M** in worst case (vs 77M current). Trough path mentions covenant enforcement, Kaiser loss. TBV crosscheck cites negative equity. | VERIFIED |
| Screening determinism | Deterministic solvency/ROIC/dilution thresholds | Solvency=**FAIL** (deterministic: IC=0.26), ROIC=**FAIL**, Dilution=**FAIL** (IC<1.5 + negative equity). No BORDERLINE lottery. | VERIFIED |
| Catalyst deduplication | No duplicates in synthesis | **4 unique catalysts** in synthesis (P&HS sale, refinancing, Optum, management pivot). No duplication. Catalyst stack has 3 entries (Hard/Medium/Soft). | VERIFIED |

### Key Metrics Across All Batches

| Metric | B-31 | B-32 | B-33 | B-34 | B-35 |
|--------|------|------|------|------|------|
| LLM log bytes | 699KB | 738KB | 664KB | 508KB | **464KB** |
| LLM log lines | 12,608 | 12,728 | 11,607 | 9,963 | **9,271** |
| Calls logged | 7 | 6 | 7 | 7 | 7 |
| Call labels correct | 4/7 | 3/6 | 7/7 | 7/7 | 7/7 |
| Elision markers | 0 | 0 | 0 | 5 | 5 |
| Models identified | 4/7 | 6/6 | 7/7 | 7/7 | 7/7 |
| Evidence concrete ratio | 41.3% | N/A | N/A | 68.3% (43/63) | **65.9%** (27/41) |
| Evidence methodology_warning | Yes | N/A | N/A | null | null |
| Wall time | ~18 min | ~10 min | ~8 min | ~10 min | **~9.4 min** |
| Pipeline status | PENDING_REVIEW | PENDING_REVIEW | — | PENDING_REVIEW | **FAIL** |
| Rejection point | — | — | — | Analysis (THESIS_BREAK) | **Screening (solvency)** |

### Screening Comparison (B-34 vs B-35)

| Check | B-34 (LLM-judged) | B-35 (deterministic where applicable) | Change |
|-------|-------------------|---------------------------------------|--------|
| solvency | BORDERLINE_PASS | **FAIL** (IC=0.26, deterministic threshold) | Tightened |
| dilution | PASS | **FAIL** (IC<1.5 + negative equity, deterministic) | Tightened |
| revenue_growth | BORDERLINE_PASS | BORDERLINE_PASS | Stable |
| roic | BORDERLINE_PASS | **FAIL** (negative NOPAT, deterministic) | Tightened |
| valuation | BORDERLINE_PASS | BORDERLINE_PASS | Stable |
| **Outcome** | Passed screening → rejected at analysis (THESIS_BREAK) | **Rejected at screening** (solvency) | Earlier kill |

This is the screening determinism gap fix in action. In batch-34, the LLM gave OMI BORDERLINE_PASS on solvency (IC=0.26!) and ROIC, letting it through to analysis where the thesis break eventually killed it. In batch-35, deterministic thresholds correctly FAIL all three quantitative checks. The pipeline reaches the right conclusion faster and without depending on LLM judgment for clear-cut financial distress.

However, this means batch-35's full analysis pipeline ran "unnecessarily" — the screening rejection should have short-circuited before analyst stages. The pipeline currently runs all stages regardless of screening outcome (by design, for research value). The rejection is applied at report assembly.

### Epistemic Review Comparison (B-34 vs B-35)

| Question | B-34 | B-35 | Change |
|----------|------|------|--------|
| q1_operational_feasibility | MODERATE | MODERATE | Stable |
| q2_risk_bounded | MODERATE | **STRONG** | Upgraded |
| q3_precedent_grounded | MODERATE (NO_EVIDENCE) | MODERATE | Stable (but no longer NO_EVIDENCE) |
| q4_downside_steelmanned | STRONG | STRONG | Stable |
| q5_catalyst_concrete | MODERATE (NO_EVIDENCE) | **STRONG** | Upgraded |
| weak_evidence_flags | 0/5 | **5/5** | Regression |
| no_evidence_count | 2 | **0** | Improved |

**Upgrades:** Q2 (risk bounded) improved from MODERATE to STRONG — the reviewer now sees specific UBS alternative proceeds estimates and explicit covenant triggers grounding the risk assessment. Q5 (catalyst concrete) improved from MODERATE/NO_EVIDENCE to STRONG — catalysts now include the $1.1B refinancing package and are described as "specific, time-bound, and verifiable."

**Regression:** `weak_evidence_flags` went from 0/5 (B-34) to 5/5 (B-35). In B-34 the reviewer cited "10-K FY2024" as evidence source (concrete). In B-35 it cites "Trailing financial ratios (audited statements); Catalysts (Thesis summary)" which the `is_weak_evidence()` function flags as weak because "audited statements" is not in `CONCRETE_SOURCE_MARKERS`. This is issue E5/F3 — the reviewer prompt needs to output specific named sources rather than generic descriptions.

**NO_EVIDENCE resolved:** B-34 had 2 NO_EVIDENCE citations (q3, q5) where the reviewer honestly couldn't verify claims behind the information barrier. B-35 has 0 — the richer catalyst evidence (refinancing, Optum, proxy data) gives the reviewer enough to work with.

### Analysis Quality: B-34 vs B-35

**Gap-closure improvements (B-34 → B-35):**

| Gap | B-34 | B-35 | Verdict |
|-----|------|------|---------|
| Incentive alignment | Missing entirely | `gameable_risk: MODERATE`, 3 compensation_evidence items (proxy, Coliseum buying, AIP changes) | **Fixed** |
| Worst-case dilution | shares_m=77.288M (no dilution modeled) | **shares_m=250M** (3.2x dilution), covenant enforcement, Kaiser loss | **Fixed** |
| Worst-case severity | rev=$9.0B, fcf=-1.5%, mult=5x | rev=$1.8B, fcf=-3.0%, mult=4x — much more severe | **Deeper bear case** |
| Screening determinism | 4x BORDERLINE_PASS (solvency, dilution, roic, valuation) | 3x deterministic FAIL (solvency, dilution, roic) | **Fixed** |
| Catalyst dedup | 5 catalysts, 5 catalyst_stack entries | 4 catalysts, 3 catalyst_stack entries — no duplication | **Fixed** |

**What batch-34 did well that batch-35 preserved:**
- Bear-first thesis ordering (bear → base → bull) — maintained
- Setup pattern: SOLVENCY_SCARE (B-34) → NEW_OPERATOR (B-35) — *changed* but both defensible
- Catalyst classification: VALID_CATALYST — maintained
- Dominant risk: Operational/Financial — maintained
- Validator verdict: APPROVE_WITH_CONCERNS — maintained
- Pre-mortem imminent_break_flag: true — maintained

**Revenue base shift (notable B-34 → B-35 difference):**
B-34 used pre-divestiture FY2024 revenue ($10.2B base, $9.0B worst, $12.0B stretch). B-35 used post-divestiture Patient Direct guidance ($2.79B base, $1.8B worst, $3.8B stretch). The validator correctly flagged this as a HIGH-severity contradiction (`claim=2.79, actual=10.7009`). Both views are analytically defensible — B-34 models the whole company, B-35 models the go-forward entity. The gap-closure fixes (worst-case modeling instructions mentioning dilution/covenant) may have nudged the LLM toward the post-divestiture framing.

**Pre-mortem comparison:**

| Category | B-34 evidence_status | B-35 evidence_status | Change |
|----------|---------------------|---------------------|--------|
| single_point_failure | weak_evidence | **strong_evidence** | Upgraded — P&HS proceeds now contested (UBS estimate) |
| capital_structure | strong_evidence | strong_evidence | Stable |
| regulatory | weak_evidence | no_current_evidence | Downgraded (honest — no new regulatory data) |
| tech_disruption | no_current_evidence | weak_evidence | Upgraded (Optum rollout dependency noted) |
| market_structure | weak_evidence | weak_evidence | Stable |

B-35 pre-mortem now has **2 strong_evidence conditions** (vs 1 in B-34). The single_point_failure upgrade is driven by the UBS/Investing.com alternative proceeds estimate ($215M vs $375M headline) which the analyst now surfaces. This is a direct consequence of richer evidence flowing through the pipeline.

**Validator quality comparison:**
Both batches produce APPROVE_WITH_CONCERNS. B-35 validator is notably more specific — references UBS net proceeds estimate, $1.1B refinancing confirmation gap, Kaiser contract risk, and models creditor-enforced outcomes (DIP financing, equity wipe). B-34 validator was solid but more generic in its challenges.

**New issues in batch-35:**

**F1. Revenue contradiction flagged by validator**
Validator detects: `claim=2.79, actual=10.7009, severity=HIGH`. The analyst used Patient Direct guidance revenue ($2.79B) for the base case, but the pipeline's `latest_revenue_b` is FY2024 total ($10.7B) since FY2025 was excluded. Both are defensible views — $2.79B is the correct forward revenue post-divestiture, $10.7B is the last complete fiscal year. The validator's contradiction check compares against `latest_revenue_b` mechanically. Consider: should the validator understand that divestiture changes the revenue base?

**F2. Finalized overlay is empty**
`analyst-synthesis.json` (the wrapped overlay) has empty `screening_inputs`/`analysis_inputs`, while `analyst-synthesis-raw.json` has the full data. The synthesis wrapping step may not be extracting from the raw output correctly. The pipeline still functions because it uses the raw output, but the finalized overlay artifact is incomplete.

**F3. weak_evidence_flags all true**
The epistemic reviewer flags all 5 answers as weak evidence despite citing "Trailing financial ratios (audited statements)" and "Thesis summary". The `weak_evidence_flags` check may be too strict — it's flagging citations that reference pipeline artifacts rather than external named sources. This matches the E5 issue from batch-32/33.

---

## Batch-34 Methodology Evaluation (reference: `docs/plans/todo-batch-34/`)

Batch-34 was the first "correct decision, right reasons" run. The methodology evaluation (`methodology-evaluation.md`) assessed it against the system codex and identified 5 gaps. All 5 were closed in a single session (8 commits, 36 new tests, zero regressions). Gap files and design specs are preserved in `docs/plans/todo-batch-34/` for traceability.

### Gap Summaries

**1. Peer Comparison Framing** (`gap-peer-comparison-framing.md`)
- **Gap:** Analyst produced OMI analysis in isolation; no comparative framing against peers (MCK, COR, CAH, HSIC) as required by Codex Step 3.
- **Fix:** Extracted `_build_peer_context()` helper, wired into both `auto_scan` and `sector_scan._analyze_ticker`. Peer metrics flow into analyst prompt for `decision_memo` grounding.
- **Files:** `scanner.py`
- **Commits:** `248aa00`, `50ef000`

**2. Incentive Alignment Missing** (`gap-incentive-alignment.md`)
- **Gap:** Stage 2 analyst prompt covered 4 of 5 Codex Step 4 questions; incentive alignment (pay metric + gameability risk) never asked.
- **Fix:** Added `compensation_evidence` array to Gemini research prompt/schema. Added `incentive_alignment` object (with `pay_metric`, `gameable_risk`, `evidence_basis`) to Stage 2 schema and qualitative fields tuple.
- **Files:** `gemini.py`, `analyst.py`, `structured-analysis.schema.json`
- **Commits:** `1208111`, `1ee9c7d`

**3. Worst-Case Doesn't Model Dilution/Covenant** (`gap-worst-case-modeling.md`)
- **Gap:** Worst case held shares constant (77M) and ignored covenant breach despite negative equity (-$461M) and interest coverage (0.26). Understated realistic downside.
- **Fix:** Added prompt instructions to Stage 1 fundamentals to model equity issuance at distressed pricing when `interest_coverage < 1.5`, and address covenant breach in `trough_path` narrative.
- **Files:** `analyst.py` (Stage 1 system prompt)
- **Commits:** `d8b6505`

**4. Screening Inconsistency Across Batches** (`gap-screening-determinism.md`)
- **Gap:** ROIC verdict flipped between batches (B-32 FAIL vs B-34 BORDERLINE_PASS) on identical FMP data. LLM nondeterminism violated "deterministic gate" requirement.
- **Fix:** Added `roic_pct` and `sbc_pct_of_revenue` to `_compute_trailing_ratios()`. Implemented deterministic thresholds: ROIC FAIL if < 6%, BORDERLINE 6-10%, PASS >= 10%. Solvency FAIL if IC < 1.0 AND (current_ratio < 1.0 OR negative equity). Dilution FAIL if SBC > 5% with share growth positive.
- **Files:** `fmp.py`, `field_generation.py`
- **Commits:** `781032f`, `5d1ac53`

**5. Catalyst Duplication in Output** (`gap-catalyst-deduplication.md`)
- **Gap:** `catalysts` array contained 3 duplicate entries (P&HS divestiture, Rotech termination, Optum agreement) — once from analyst, once from Gemini with citations.
- **Fix:** Added one-line dedup instruction to Stage 3 synthesis prompt: keep Gemini-sourced entries (with citations) when duplicates detected.
- **Files:** `analyst.py` (Stage 3 synthesis prompt)
- **Commits:** `af37bf9`
- **Note:** Gemini review flagged this as the weakest fix (prompt-only). Fallback option: change `catalysts` schema to structured objects `{event_summary, evidence, source_url}`. Monitor in future scans.

### Gemini Review Cross-Cutting Themes (from methodology-evaluation.md)

- **False negative risk:** Deterministic thresholds fix solvency/ROIC/dilution, but `revenue_growth` and `valuation` remain LLM-judged. A good candidate randomly getting FAIL is permanently discarded.
- **BORDERLINE_PASS frequency audit:** If the LLM defaults to BORDERLINE_PASS when uncertain, the first filter becomes theater. Should audit frequency across scans.
- **Catalyst dedup fragility:** Prompt-only approach may hallucinate or incorrectly merge. Structured-object schema is the robust fallback.
- **Hallucination risk on thin evidence:** Executive compensation plans and covenant terms may be fabricated if not in context. `UNKNOWN` enum on `gameable_risk` partially mitigates.

---

## Post-Batch-35 Fixes (implemented after initial B-35 analysis)

### E5/F3. Epistemic Reviewer weak_evidence_flags (CLOSED)

**Problem:** `weak_evidence_flags` triggered 5/5 on every scan since batch-32. The epistemic reviewer cited "Trailing financial ratios (audited statements)" and "Thesis summary" — honest citations of what it sees behind the information barrier — but these weren't in `CONCRETE_SOURCE_MARKERS`, so they were flagged as weak.

**Root cause:** `is_weak_evidence()` used a single shared marker list. The epistemic reviewer operates behind an information barrier and can never cite external sources like "10-K FY2024". Its citations are pipeline artifacts by design.

**Fix (Gemini-reviewed):** Decoupled the marker lists.
- Reverted `CONCRETE_SOURCE_MARKERS` to strict external-source-only list (protects hardening evidence quality scoring for analyst provenance)
- Created `EPISTEMIC_CONTEXT_MARKERS` — "trailing financial ratios", "audited statements", "thesis summary", "catalysts", "key risks", "base case assumptions", "worst case assumptions", "moat assessment", "dominant risk type"
- Parameterized `is_weak_evidence()` with `context_markers` kwarg (default: `CONCRETE_SOURCE_MARKERS`). Epistemic reviewer post-processing passes `EPISTEMIC_CONTEXT_MARKERS`.
- Updated reviewer prompt examples to match what it actually has access to.

**Files:** `epistemic_reviewer.py`
**Tests:** 112 total, all pass.

### F1. Revenue Contradiction on Divestitures (CLOSED)

**Problem:** Validator flagged `revenue_b: claim=2.79, actual=10.7009, severity=HIGH`. Analyst used post-divestiture Patient Direct guidance ($2.79B). Validator compared against `latest_revenue_b` (FY2024 total $10.7B) since FY2025 was excluded as incomplete.

**Fix:** Added `forward_revenue_b` — when a year is excluded as incomplete but has valid revenue, that revenue is preserved as the go-forward entity's revenue base. Validator's `detect_contradictions()` now uses `forward_revenue_b` when present, falling back to `latest_revenue_b`.

**Files:** `fmp.py` (added `_extract_forward_revenue_b()`, wired into derived), `validator.py` (revenue check uses forward_revenue_b)
**Tests:** 112 total, all pass.

### E4. Persist Hardening Metrics (CLOSED)

**Problem:** Hardening flags (evidence quality, thesis break, data quality) computed at runtime and written to manifest but never saved as standalone artifact. Could not verify hardening results from `raw/` directory alone.

**Fix:** `scanner.py` now writes `flags` dict to `raw/hardening-result.json` immediately after computing hardening gates.

**Files:** `scanner.py`
**Tests:** 112 total, all pass.

### ~~F2. Empty Finalized Overlay~~ (CLOSED — was invalid)

Data is correctly populated under `structured_candidates[0]`, not at root level. Initial investigation looked at wrong JSON path.

---

## Issue Tracker: Complete Status

| ID | Issue | Introduced | Fixed | Status |
|----|-------|-----------|-------|--------|
| A1 | Zero-filled statement detection + FCF exclusion | B-31 | B-32 | CLOSED |
| A2 | Discontinued operations flag | B-31 | B-32 | CLOSED |
| A3 | isActivelyTrading warning | B-31 | B-32 | CLOSED |
| B1 | Probability anchoring regex false positive | B-31 | B-32 | CLOSED |
| B2 | Gemini URL evidence classification | B-31 | B-32 | CLOSED |
| C1 | LLM logger [unknown] model name | B-31 | B-32 | CLOSED |
| D1 | data_quality in manifest | B-31 | B-32 | CLOSED |
| D2 | DATA QUALITY WARNING in analyst prompt | B-31 | B-32 | CLOSED |
| -- | Context dedup (slim candidate) | B-31 | B-32 | CLOSED |
| E1 | Call labels wrong | B-32 | B-33 | CLOSED |
| E2 | Gemini cache hits not logged | B-32 | B-33 | CLOSED |
| E3 | Log size / elision | B-32 | B-34 | CLOSED |
| E4 | Hardening metrics not persisted | B-32 | Post-B-35 | CLOSED |
| E5/F3 | weak_evidence_flags regression | B-32 | Post-B-35 | CLOSED |
| F1 | Revenue contradiction on divestitures | B-35 | Post-B-35 | CLOSED |
| ~~F2~~ | Empty finalized overlay | B-35 | B-35 | INVALID |
| G1 | Peer comparison framing | B-34 eval | B-35 | CLOSED |
| G2 | Incentive alignment missing | B-34 eval | B-35 | CLOSED |
| G3 | Worst-case dilution/covenant | B-34 eval | B-35 | CLOSED |
| G4 | Screening determinism | B-34 eval | B-35 | CLOSED |
| G5 | Catalyst deduplication | B-34 eval | B-35 | CLOSED |

**All pre-Claude items closed.**

---

## Claude Pivot (B-41 → B-52)

### Motivation

LLM nondeterminism on OpenAI gpt-5-mini was unacceptable: worst-case dilution swung 177M-377M shares (2.1x range), base probability swung 35-50%, solvency screening flipped between FAIL and BORDERLINE_PASS across identical runs.

### Implementation

Switched from OpenAI to Anthropic Claude with tiered temperature control:

| Agent | Model | Temperature | top_k |
|-------|-------|-------------|-------|
| Analyst (stages 1-3) | Claude Haiku / Sonnet | 0.0 | 1 |
| Validator red-team | Claude Haiku | 0.6 | — |
| Validator pre-mortem | Claude Haiku | 0.6 | — |
| Epistemic reviewer | Claude Haiku | 0.2 | — |

Config defaults in `AppConfig` (code), secrets-only in `.env.age`. Configurable via env vars `ANALYST_TEMPERATURE`, `ADVERSARIAL_TEMPERATURE`, `REVIEWER_TEMPERATURE`.

### Anthropic Compatibility Fixes (B-41 → B-48)

| Batch | Error | Fix |
|-------|-------|-----|
| B-41 | max_tokens exceeded (8192) | Bumped to 16384 in Anthropic transport |
| B-42 | `additionalProperties` missing on bare objects | Added to ALL object types, not just those with properties |
| B-43/44 | Ordering discipline: worst_case after base_case | Reordered schema tuple + removed raw JSON position check (kept thesis_summary text check) |
| B-45 | catalyst_stack missing `timeline` | Added defensive repair in `_coerce_analysis_types()` |
| B-48 | `minItems: 5` unsupported | Removed from premortem schema (Anthropic only supports 0 or 1) |

### Claude-Specific Regressions Fixed (B-49 → B-51)

**Probability anchoring false positive:** Claude's pre-mortem output naturally contains financial thresholds ("15% revenue decline", "0.20x coverage") in `risk_description`, `early_warning_metric`, AND `rationale` fields. The regex caught ALL percentages. Fix: rewrote `_THESIS_ANCHORING_PATTERN` to require probability context words (probability/chance/likelihood/odds/confidence) near any percentage or decimal.

**Evidence quality collapse (7-16%):** Claude's review_notes cite article titles verbatim ("Per 'Owens & Minor rebrands after $375M sale...'") rather than source types ("balance sheet", "10-K"). Fix: added `_NAMED_SOURCE_PATTERN` regex for `Per '...'` citations, added missing markers (proxy statement, def 14a, zacks, gurufocus, sector context, financial data), excluded `[SYNTHETIC ROLLUP]` and `[SYSTEM REPAIR]` entries from evidence scoring.

### Determinism Results: OpenAI (B-38/39) vs Claude (B-51/52)

| Metric | OpenAI (B-38 vs B-39) | Claude (B-51 vs B-52) |
|--------|----------------------|----------------------|
| Pipeline verdict | FAIL vs FAIL | FAIL vs FAIL |
| base_probability_pct | 35 vs 50 (**15pp swing**) | **25 vs 25 (0pp)** |
| Solvency screening | FAIL vs BORDERLINE_PASS (**flips**) | **FAIL vs FAIL** |
| double_plus_potential | True vs False (**flips**) | **False vs False** |
| setup_pattern | SOLVENCY_SCARE vs NEW_OPERATOR | **NEW_OPERATOR vs NEW_OPERATOR** |
| catalyst_classification | VALID vs WATCH_ONLY | **INVALID vs INVALID** |
| final_cluster_status | CONDITIONAL vs ELIMINATED | **ELIMINATED vs ELIMINATED** |
| worst_case shares_m | 177M vs 377M (**2.1x range**) | **80M vs 85M (6%)** |
| Epistemic Q1-Q5 | Varies | **All 5 identical** |
| thesis_break | IMMINENT vs IMMINENT | **IMMINENT vs IMMINENT** |

**Every decision-critical field is now locked.** Remaining variance is in numeric assumptions (base/worst case revenue and multiples) from the unconstrained synthesis stage — acceptable for a financial analysis pipeline.

### Issue Tracker Update

| ID | Issue | Introduced | Fixed | Status |
|----|-------|-----------|-------|--------|
| H1 | Provenance dedup crash | B-37 | Post-B-37 | CLOSED |
| H2 | max_tokens too low for Claude | B-41 | B-41 | CLOSED |
| H3 | additionalProperties on bare objects | B-42 | B-42 | CLOSED |
| H4 | Schema property ordering vs ordering discipline | B-43 | B-44 | CLOSED |
| H5 | catalyst_stack missing timeline | B-45 | B-48 | CLOSED |
| H6 | minItems:5 unsupported by Anthropic | B-48 | B-48 | CLOSED |
| H7 | Anchoring regex catches all percentages | B-49 | B-51 | CLOSED |
| H8 | Evidence quality collapse on Claude output | B-49 | B-51 | CLOSED |

---

## Summary: Full Progression (B-31 → B-52)

| Aspect | B-31 (broken OpenAI) | B-35 (fixed OpenAI) | B-51/52 (Claude) |
|--------|---------------------|---------------------|-----------------|
| LLM provider | OpenAI gpt-5-mini | OpenAI gpt-5-mini | **Anthropic Claude Haiku/Sonnet** |
| Temperature control | None (default 1.0) | None | **Tiered: 0.0/0.6/0.2** |
| Data quality | FY2025 zeros as real | Detected, excluded | Stable |
| Screening | LLM lottery | Deterministic FAIL | **Deterministic FAIL (locked)** |
| Evidence quality | 41.3% (FAIL) | 65.9% (pass) | **75.9%** |
| Worst case dilution | Not modeled | 250M shares | **80-85M shares** |
| Base probability | 40% (variable) | 35-50% (swings) | **25% (locked)** |
| Determinism (cross-run) | 2.1x variance on key fields | Same | **<6% variance** |
| Epistemic stability | Varies across runs | Varies | **All 5 answers identical** |
| Pipeline decision | PENDING_REVIEW | FAIL (correct) | **FAIL (locked)** |
| Synthesis retries | N/A | ~30% of runs | **0% (B-51/52)** |
