# Batch 17-18-19 Analysis: HRL, CPS, TCMD

Date: 2026-03-13
Batches: 17 (HRL), 18 (CPS), 19 (TCMD)
All 3 tickers: FAIL at screening

---

## 1. Pipeline Health Summary

| Metric | HRL (B17) | CPS (B18) | TCMD (B19) |
|--------|-----------|-----------|------------|
| Peer lookup | 5/5 | 5/5 | 5/5 |
| Stage 1 retry | No | No | No |
| Stage 2 retry | No | No | No |
| Stage 3 retry | No | Yes (ordering) | No |
| Backfill fields | 6 | 1 (then 8 on retry) | 4 |
| Validator | APPROVE_WITH_CONCERNS | APPROVE_WITH_CONCERNS | APPROVE_WITH_CONCERNS |
| Validator concerns | 5 | 5 | 5 |
| Contradictions | 0 | 0 | 0 |
| Evidence concrete% | 76.5% | 79.4% | 77.8% |
| Screening outcome | FAIL: 58.8% off ATH (<60%) | FAIL: 36.4% off ATH (<60%) | FAIL: 55.4% off ATH (<60%) |

All three tickers failed the same hard gate: **Broken Chart** (pct_off_ath < 60%).

### Fix Verification (from batch-15/16 work)
- `multi_quote`: **FIXED** -- all 3 runs show "5 tickers, 5 with metrics"
- `key_financials` / `trough_path` / `tbv_crosscheck`: **FIXED** -- all Stage 1 outputs contain populated strings (verified via analyst-fundamentals.json in each batch)
- No 402 errors anywhere
- CPS Stage 3 ordering violation triggered retry -- existing discipline check caught it and recovered

---

## 2. Per-Ticker Analysis Against Codex

### HRL (Hormel Foods) -- Batch 17

**Codex Setup Pattern**: Quality Franchise, Temporary Margin Compression (Setup B)

| Codex Step | System Output | Alignment |
|------------|---------------|-----------|
| 01 Finding Ideas | Packaged Foods, not in exclusion list. Sector understood. | GOOD |
| 02 First Filter - Solvency | PASS: $671M cash, ~$2.9B LT debt, positive FCF | GOOD |
| 02 First Filter - Dilution | BORDERLINE_PASS: shares stable ~550M | GOOD |
| 02 First Filter - Revenue | BORDERLINE_PASS: guidance 1-4%, Q1 +2% organic | GOOD |
| 02 First Filter - ROIC | BORDERLINE_PASS: ~5% economic return | GOOD -- flags low quality vs peers |
| 02 First Filter - Valuation | BORDERLINE_PASS | GOOD |
| 03 Deep Analysis - Peer comparison | Peers: BF-B, CAG, CLX, COKE, SJM | OK -- but these are from FMP stock-peers, not necessarily deep-value peers |
| 04 Qualitative - Moat | Moderate: ~40 #1/#2 positions, brand-driven, low switching costs | GOOD |
| 04 Qualitative - Catalyst stack | MEDIUM: Transform & Modernize ($250M), Jiaxing facility, turkey divestiture | GOOD -- correctly classified, no HARD catalysts |
| 05 Valuation - 3 cases | Base $12.3B/6%/8x, Worst $10.9B/3%/6x, Stretch $13.5B/10%/10x | GOOD |
| 06 Decision - Score | Not reached (screening FAIL) | N/A |

**Codex Friction Points:**
- Validator correctly flagged dividends ($633M) exceeding FCF ($534M) -- the codex would call this a solvency warning
- 55% base probability with no HARD catalysts -- codex says "base case must not depend on Soft catalysts alone." Transform & Modernize is MEDIUM but unproven. Probability may be generous.
- GLP-1 secular risk is acknowledged but worst case only models ~10% revenue decline. Codex says "estimate a reasonable worst case" -- validator rightly pushed for 15-20% stress test.
- **Screening rejection is correct**: 58.8% off ATH, and the company doesn't have the explosive upside profile the codex demands ("double+ in 2-3 years" is hard for a mature packaged foods company growing 1-4%).

**Quality Assessment**: The analysis quality is strong. Evidence grounding is good (76.5% concrete). The system correctly identified this as a quality franchise with margin compression, which maps to codex Setup B. The screening gate is doing its job -- HRL doesn't fit the deep-value turnaround profile.

---

### CPS (Cooper-Standard) -- Batch 18

**Codex Setup Pattern**: Solvency Scare but Survival Secured (Setup A)

| Codex Step | System Output | Alignment |
|------------|---------------|-----------|
| 01 Finding Ideas | Auto Parts supplier, not in exclusion (OEM excluded, suppliers not) | GOOD |
| 02 First Filter - Solvency | BORDERLINE_PASS | CONCERN -- see below |
| 02 First Filter - Dilution | PASS | GOOD |
| 02 First Filter - Revenue | BORDERLINE_PASS: $2.74B, recovering from 2021 trough | GOOD |
| 02 First Filter - ROIC | BORDERLINE_PASS | GOOD |
| 02 First Filter - Valuation | BORDERLINE_PASS | GOOD |
| 03 Deep Analysis - Peer comparison | Peers fetched and compared | GOOD |
| 04 Qualitative - Moat | Narrow-to-moderate: Fortrex chemistry, 16% global sealing share | GOOD |
| 04 Qualitative - Catalyst stack | HARD: March 2026 refinancing. MEDIUM: $298M awards, cost program. SOFT: supply-chain risk | GOOD -- correctly identifies refinancing as HARD |
| 05 Valuation - 3 cases | Base $3.0B/5%/8x, Worst $2.33B/0.5%/3x, Stretch $3.3B/8%/10x | CONCERN |
| 06 Decision - Score | Not reached (screening FAIL) | N/A |

**Codex Friction Points:**
- **Solvency is the critical issue and the system underweights it.** FY2025 FCF was $16.25M (0.59% margin). The March 2026 refinancing at 9.25% implies ~$102M annual interest. FY2025 operating cash flow was $64.4M. The codex says "Balance sheet survival is the first moat in turnarounds" and the solvency check should arguably be FAIL, not BORDERLINE_PASS. The 9.25% coupon is a market signal of distress.
- The validator correctly identified this: "worst-case omits explicit interest-service / covenant runway model" and "FY2025 operating cash flow ~$64.4M vs projected 9.25% coupon on $1.1B ~$101.8M." The system should have escalated this to a harder solvency warning.
- 55% base probability is questionable given: (a) FCF barely positive, (b) interest coverage < 1x on operating cash flow basis, (c) $298M awards are forward-looking, not contracted production volumes. The codex says "Base-case probability < 60% -> 0% new size" -- so even if this passed screening, it would get zero sizing at 55%.
- **Screening rejection (36.4% off ATH) is correct** but for the wrong reason. CPS should arguably fail solvency before it fails the broken-chart gate. The chart gate masked a more fundamental problem.

**Quality Assessment**: Evidence quality is high (79.4% concrete). The analyst correctly identified this as Setup A (Solvency Scare). The validator red-team was excellent -- all 5 concerns are substantive. The ordering discipline violation on Stage 3 was caught and recovered cleanly. The system's biggest weakness here is the solvency gate being too lenient for a company with interest coverage < 1x.

---

### TCMD (Tactile Systems Technology) -- Batch 19

**Codex Setup Pattern**: Quality Franchise, Narrative Discount (Setup C / Setup B hybrid)

| Codex Step | System Output | Alignment |
|------------|---------------|-----------|
| 01 Finding Ideas | Medical Devices, not in exclusion list | GOOD |
| 02 First Filter - Solvency | PASS: $83.4M cash, zero debt, $40.4M FCF | GOOD -- strongest balance sheet of the 3 |
| 02 First Filter - Dilution | BORDERLINE_PASS: 2023 issuance, 2025 buybacks | GOOD |
| 02 First Filter - Revenue | PASS: 11% CAGR (2021-2025), 8-11% guidance | GOOD |
| 02 First Filter - ROIC | BORDERLINE_PASS: 5.6% proxy ROIC | GOOD |
| 02 First Filter - Valuation | PASS: P/FCF ~15x, below med-device premium | GOOD |
| 03 Deep Analysis - Peer comparison | Peers fetched and compared | GOOD |
| 04 Qualitative - Moat | ~75% advanced PCD share, clinical evidence, consumables attachment | GOOD |
| 04 Qualitative - Catalyst stack | HARD: LymphaTech acquisition (signed). MEDIUM: AffloVest growth (+66% YoY), Nimbl rollout, prior-auth mitigation | GOOD |
| 05 Valuation - 3 cases | Base $360M/12%/25x, Worst $208M/0.5%/6x, Stretch $600M/20%/30x | CONCERN |
| 06 Decision - Score | Not reached (screening FAIL) | N/A |

**Codex Friction Points:**
- **Screening gate is debatable here.** TCMD is 55.4% off ATH vs the 60% threshold. This is the closest of the three to passing. With zero debt, $83M cash, 75% gross margins, 12% FCF margins, and growing revenue -- this is arguably the most interesting candidate. The codex says "Buy quality businesses in temporary trouble" and TCMD fits that profile better than either HRL or CPS.
- **Epistemic review flags a real problem**: q1_operational=NO and q2_regulatory=NO. The dominant risk is Medicare prior-authorization policy, which is outside management control. The codex says regulatory-driven names require "extraordinary proof" and the system correctly identified this tension.
- **Worst case is too harsh**: Revenue reverts to $208M (2021 trough, 36.8% decline) with 0.5% FCF margin and 6x multiple. But 2021 was a COVID-impacted year for home healthcare devices. A more realistic worst case might use 2022 ($247M) as the trough with better margin assumptions. The validator caught this: "worst case does not explicitly model a regulatory-quality catastrophe but uses a trough that already includes one."
- **Stretch case multiple (30x) is aggressive** for a $600M revenue small-cap. The codex warns against "underwriting multiple expansion only" -- the stretch case implicitly depends on it.
- 55% base probability is reasonable here given the quality of the franchise and the specific (non-binary) nature of the regulatory risk.

**Quality Assessment**: Best overall quality of the three runs. Clean execution (no retries), strong evidence (77.8% concrete), good moat identification, and the validator raised genuinely useful concerns. The system correctly identified the regulatory/payer risk as the binding constraint.

---

## 3. What Works Well

### Pipeline Mechanics
- **Peer lookup fixed and working**: All 3 runs got 5/5 peers with metrics. The per-ticker multi_quote approach is reliable.
- **Schema fix working**: All Stage 1 outputs have populated string fields for key_financials, trough_path, tbv_crosscheck. No more empty `{}`.
- **Ordering discipline**: CPS Stage 3 violated worst_case-before-base_case ordering, retry caught and fixed it. Good safety net.
- **Evidence quality consistently high**: 76-79% concrete citation ratios across all 3 tickers. Gemini grounded search is producing sourced, specific evidence.
- **Sector hydration**: All 3 tickers triggered fresh sector hydration (Packaged Foods, Auto Parts, Medical Devices). Sector context flowed into analyst prompts.

### Analysis Quality
- **Setup pattern recognition**: HRL correctly mapped to QUALITY_FRANCHISE, CPS to NARRATIVE_DISCOUNT (solvency scare), TCMD to QUALITY_FRANCHISE. These align with the codex pattern library.
- **Validator red-team is excellent**: 15 total concerns across 3 tickers, all substantive, no padding. High-severity flags hit real weaknesses (HRL dividend/FCF gap, CPS interest coverage, TCMD regulatory tail risk).
- **Three-case valuation**: All three tickers produced bear/base/stretch with explicit assumptions. The codex requires exactly this.
- **Catalyst classification**: Correctly distinguished HARD (signed/contractual) from MEDIUM (management-led) from SOFT (narrative). CPS's March 2026 refinancing correctly tagged as HARD.
- **Epistemic reviewer independence**: Blind review caught genuine friction points. TCMD's q1=NO (operational levers insufficient vs regulatory risk) and CPS's q3=NO (no clear precedent) are both correct and useful.
- **Thesis summaries lead with bear case**: All three thesis_summary fields put downside arguments first, per codex discipline.

### Screening
- **All 3 rejections are defensible**: None of these tickers have the >60% off ATH drawdown that the codex demands for deep-value entry. The broken-chart gate is doing its job as a fast filter.

---

## 4. What Needs Improvement

### P1: Solvency Gate Too Lenient for Distressed Capital Structures

**Problem**: CPS got BORDERLINE_PASS on solvency despite:
- FY2025 FCF of $16.25M (0.59% margin)
- Refinancing at 9.25% coupon (implied ~$102M annual interest)
- Operating cash flow ($64.4M) < interest expense ($102M)
- Cash buffer ($198.3M) covers ~2 years of burn at current rates

The codex is explicit: "Balance sheet survival is the first moat in turnarounds" and "Survival uncertain and risk is not already priced in" should FAIL.

**Impact**: If CPS had passed the broken-chart gate, it could have entered the pipeline with a solvency BORDERLINE_PASS that masks genuine distress. The validator caught this, but the solvency gate itself should be harder.

**Recommendation**: Add an interest coverage check to the solvency screening logic. If operating_cash_flow < annual_interest_expense, force FAIL or at minimum flag it prominently. This is a deterministic check that can be computed from FMP data.

### P2: Backfill Volume Suggests Stage 3 Synthesis Drops Fields

**Problem**: Backfill counts across batches:
- HRL: 6 fields (key_risks, moat_assessment, human_judgment_flags, exception_candidate + 2 provenance)
- CPS retry: 8 fields (key_risks, moat_assessment, human_judgment_flags, exception_candidate + 4 provenance)
- TCMD: 4 fields (key_risks, moat_assessment + 2 provenance entries for structural_diagnosis sub-paths)

Stage 3 (Sonnet, unconstrained synthesis) is consistently dropping `key_risks`, `moat_assessment`, `human_judgment_flags`, and `exception_candidate`. These are Stage 2 fields that should survive reconciliation.

**Impact**: The backfill mechanism recovers them, so final output is correct. But this adds fragility -- if backfill had a bug, these fields would silently vanish.

**Recommendation**: Add these field names explicitly to the Stage 3 synthesis prompt's "you MUST include ALL required analysis_inputs keys" list. Currently the prompt lists margin_trend_gate, final_cluster_status, dominant_risk_type, etc. but omits key_risks, moat_assessment, human_judgment_flags, and exception_candidate.

### P3: Base Probability Defaults to 55% Across All Tickers

**Problem**: All three tickers got base_probability_pct = 55% despite very different risk profiles:
- HRL: Mature franchise, margin compression, no HARD catalysts -- 55% seems fair
- CPS: Interest coverage < 1x, 0.59% FCF margin, 9.25% coupon -- 55% seems generous
- TCMD: Zero debt, 75% gross margin, 12% FCF margin, growing revenue -- 55% seems conservative

The codex says probability is subjective but process-consistent. Getting the same number for wildly different risk profiles suggests the LLM is anchoring to a default rather than discriminating.

**Impact**: At 55%, none of these would get sized anyway (codex requires >= 60% for new capital). But in cases where a ticker barely passes screening, an anchored probability could lead to wrong-sized positions.

**Recommendation**:
- Add explicit anchoring guidance to the fundamentals prompt: "Base probability MUST differ between candidates with materially different risk profiles. A company with zero debt and 12% FCF margins should not receive the same probability as a company with interest coverage < 1x."
- Consider adding a hardening gate that flags when probability falls in a narrow band (e.g., 50-60%) across multiple tickers in the same session.

### P4: Worst-Case Assumptions Inconsistently Stressed

**Problem**:
- HRL worst case: revenue -10% to $10.9B with 3% FCF margin -- validator pushed for -15-20% GLP-1 stress
- CPS worst case: revenue to 2021 trough $2.33B, 0.5% FCF margin -- but doesn't model covenant breach or restructuring despite interest coverage < 1x
- TCMD worst case: revenue to 2021 trough $208M (COVID year), 0.5% FCF margin -- but 2021 was anomalous for home healthcare

The codex says worst case should be "non-catastrophic but adverse." The system sometimes uses historical troughs without questioning whether those troughs are representative.

**Impact**: Floor prices may be understated (TCMD) or overstated (CPS) depending on whether the historical trough is actually the right anchor.

**Recommendation**: Add prompt guidance: "When using historical trough revenue as worst-case anchor, explicitly state whether that period was anomalous (COVID, one-time disruption) and adjust if so. For levered companies, worst case MUST include interest-service feasibility check."

### P5: FMP stock-peers Returns Sector Peers, Not Business-Model Peers

**Problem**: Same issue as PYPL (batch-15). FMP's stock-peers endpoint returns broad financial-sector or industry-sector peers, not business-model comparables. For auto-scan this means:
- HRL got: BF-B, CAG, CLX, COKE, SJM -- reasonable for packaged foods
- CPS and TCMD: peers from FMP may or may not be directly comparable

This is hit-or-miss. For HRL it worked well; for fintech/payments (PYPL) it returned banks.

**Impact**: When peers are wrong, the decision memo and peer comparison table lose value. The analyst may ground its relative assessment in irrelevant comparisons.

**Recommendation**: Not a code fix needed now. Accept FMP peer quality as-is. The screener fallback already provides a safety net. A future enhancement could use Gemini to suggest business-model peers as a supplementary source.

### P6: Screening Rejects Before Full Analysis -- Context Lost

**Problem**: All 3 tickers failed at screening (broken-chart gate < 60%). The pipeline still runs the full analyst -> validator -> epistemic flow, generating rich artifacts. But the final report only shows:
```
rejected_at_screening: [{ticker: "HRL", failed_at: "Step 1 - Broken Chart", reason: "..."}]
rejected_at_analysis_detail_packets: []
```

The full analysis (cases, thesis, catalysts, risks) is in the raw artifacts but doesn't surface in the report.

**Impact**: When reviewing scan results, all three tickers look like empty rejections. The operator has to dig into raw/ to see the actual analysis quality. This is especially unfortunate for TCMD which is a genuinely interesting candidate that narrowly missed the chart gate.

**Recommendation**: Consider adding a `screening_rejected_detail_packets` section to the report that includes the analysis summary even for screening failures. This gives the operator enough context to decide whether a manual override is warranted. The codex acknowledges that the 60% threshold is a guideline, not absolute.

---

## 5. Codex Alignment Scorecard

How well does the automated pipeline implement each codex step?

| Codex Step | Implementation | Score | Notes |
|------------|----------------|-------|-------|
| 01 Finding Ideas | Sector hydration + FMP screening | 8/10 | Works well; exclusion zones not explicitly checked |
| 02 First Filter (5 checks) | Screening module | 7/10 | Solvency gate needs interest coverage; other 4 checks are solid |
| 03 Deep Analysis (peer comparison) | Peer lookup + decision memo | 7/10 | FMP peer quality varies; decision memo is well-structured |
| 04 Qualitative Deep Dive | Gemini research + analyst Stage 2 | 9/10 | Catalyst classification, moat assessment, risk identification all strong |
| 05 Valuation (3 cases) | analyst Stage 1 + synthesis | 7/10 | Cases produced; worst-case stress inconsistent; probability anchoring |
| 06 Decision (scoring) | pipeline scoring.py | 8/10 | Deterministic scoring works; not reached in these batches due to screening |
| 07 Position Sizing | pipeline breakpoints | N/A | Not tested (all failed screening) |
| 08 After the Buy | holding_review.py | N/A | Not tested |
| Validator red-team | validator.py | 9/10 | Consistently excellent, substantive concerns |
| Epistemic review | epistemic_reviewer.py | 8/10 | Good independence; blind review catches real issues |
| Evidence quality | hardening.py | 8/10 | 76-79% concrete ratios; citation tracking works |

**Overall: 7.8/10** -- The pipeline faithfully implements the codex methodology. The main gaps are in solvency gate granularity, probability calibration, and worst-case stress testing. The analysis layer (qualitative, validator, epistemic) is consistently strong.

---

## 6. Comparison Across Tickers

Which of these three is closest to the codex's ideal candidate?

| Factor | HRL | CPS | TCMD |
|--------|-----|-----|------|
| Codex setup type | B (Quality/Margin) | A (Solvency Scare) | C/B (Quality/Narrative) |
| Balance sheet | OK (dividend > FCF) | WEAK (interest > OCF) | STRONG (zero debt, $83M cash) |
| FCF quality | 4.4% margin, declining | 0.59% margin, fragile | 12.3% margin, stable |
| Catalyst quality | MEDIUM only | HARD + MEDIUM | HARD + MEDIUM |
| Moat durability | Moderate (brands) | Narrow (IP/share) | Strong (75% share, clinical) |
| Off ATH | 58.8% | 36.4% | 55.4% |
| Codex viability | Low (mature, slow growth) | Low (distressed capital) | Moderate (quality + growth) |

**TCMD is the most interesting**: quality franchise, growing revenue, strong balance sheet, regulatory catalyst risk is specific and monitorable. It narrowly missed the 60% broken-chart gate at 55.4%. If this threshold were softer or if the stock declined another 10%, it would enter the pipeline as a credible candidate.

---

## 7. Actionable Next Steps

1. **Solvency gate**: Add interest coverage ratio check (P1 above) -- code change in screening logic
2. **Stage 3 field drops**: Add missing field names to synthesis prompt (P2) -- prompt change in analyst.py
3. **Probability anchoring**: Add discrimination guidance to fundamentals prompt (P3) -- prompt change
4. **Worst-case prompt**: Add historical-trough representativeness and interest-service checks (P4) -- prompt change
5. **Screening detail packets**: Surface analysis for screening-rejected tickers in report (P6) -- pipeline/reporting change
6. **Run a ticker that passes screening** to test the full pipeline through scoring, sizing, and report generation. The broken-chart gate has been the binding constraint in all batches so far.

---

## 8. Next Runs

All 5 batches so far (PYPL, HRL, CPS, TCMD x2) failed at the 60% broken-chart screening gate. The scoring/sizing pipeline remains untested end-to-end. Priority is finding tickers that clear screening.

From the codex pattern library (CPS, BABA, BA, HRL, OMI, TCMD, QXO), the untested candidates:

| Ticker | Company | Codex Setup | Likely >60% off ATH? | Notes |
|--------|---------|-------------|---------------------|-------|
| **BABA** | Alibaba | C (Narrative Discount) | Yes (~70%+ off 2020 highs) | Classic geo/political narrative discount, strong balance sheet |
| **BA** | Boeing | D (New Operator) | Possibly (~65-70% off 2019 highs) | New CEO, operational milestones emerging |
| **OMI** | Owens & Minor | A/B (Solvency/Margin) | Likely (~75%+ off highs) | Healthcare distribution, margin compression |
| **QXO** | QXO Inc | D (New Operator) | Unknown | Newer entity, Brad Jacobs vehicle |

**Recommended run order:**
1. **OMI** -- highest likelihood of clearing the 60% gate, tests Setup A/B through full pipeline
2. **BABA** -- tests Setup C (narrative discount), exercises geo/political risk handling
3. **BA** -- tests Setup D if it clears the gate

Goal: get at least one ticker through screening into scoring/sizing to validate the complete pipeline.
