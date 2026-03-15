# Batch-34: Methodology Evaluation Against Kyler's System Codex

**Ticker:** OMI (Owens & Minor, Inc.)
**Scan Date:** 2026-03-15
**Batch:** batch-34 (post-dedup, elision active)

## The Right Call

Batch-34 rejects OMI with `THESIS_BREAK_IMMINENT: Strong evidence of structural break in categories: capital_structure`. This is the correct decision per the codex:

- "Balance sheet survival is the first moat in turnarounds" (00-START-HERE) -- interest coverage 0.26, negative equity, net debt ~$2.09B. Survival is genuinely uncertain.
- "No survival runway -> no position" (11-CHEAT-SHEET) -- `imminent_break_flag: true` enforces this.
- "Probability <60% -> no new capital" -- effective probability 33.25% after epistemic adjustment. Correctly blocked.

Compared to batch-31 where the LLM anchored on garbage FY2025 data and produced a confused analysis, batch-34 reasons from clean data and reaches the right conclusion for the right reasons.

## What Batch-34 Does Well (Codex Alignment)

### Bear-first discipline (00: "Prioritize downside protection over upside fantasy")
Thesis summary leads with bear case. Worst case modeled before base case. Ordering discipline is enforced.

### 5 First Filters (02) -- all present and populated

| Filter | Codex Check | B-34 Output |
|--------|-------------|-------------|
| Solvency | Cash/liquidity, debt maturity, FCF trend | Interest coverage 0.26, current ratio 0.58, negative equity, FCF -$66.7M |
| Dilution | Share count trend, SBC | Shares 77.288M tracked, validator flags dilution NOT modeled in worst case |
| Revenue Path | Historical cycle, demand drivers | FY2021-2024 trend ($9.79B->$10.70B), $300-350M contract roll-off identified |
| Capital Efficiency | ROIC/ROCE, peer relative | Negative NOPAT, heavy invested capital -- correctly assessed |
| Valuation | P/S, P/FCF, preliminary CAGR | Base CAGR 57.95%, worst case -100% downside |

### Catalyst stack (04: "No catalyst stack -> no position", classify as Hard/Medium/Soft)
P&HS divestiture (Hard, $375M), Rotech termination fee (Hard, $80M), Optum agreement (Medium). Base case doesn't depend on Soft catalysts alone. Correct.

### 3-scenario valuation (05: "Require 3 outputs, not 1")
Bear ($9.0B rev, -1.5% FCF, 5x), Base ($10.2B rev, 1.0% FCF, 8x), Stretch present. Simple `Revenue x FCF Margin x Multiple` model. Correct.

### Red-team (OPERATING-CHECKLIST: "What has to be true for this to fail badly?")
Validator produces 5 targeted challenges and 4 substantive objections. Directly maps to codex's red-team prompts. The validator correctly identifies that the worst case doesn't model covenant breach or dilution.

### Thesis invalidation -- 5 structured conditions with evidence grading

| Category | Evidence Status | Codex Alignment |
|----------|----------------|-----------------|
| Single point failure (mgmt discretion) | weak_evidence | Matches "Which assumption is most fragile?" |
| Capital structure death spiral | strong_evidence | Triggers rejection -- "Survival uncertain" |
| Regulatory (reimbursement shift) | weak_evidence | Identified, not yet realized |
| Tech disruption | no_current_evidence | Honest -- no data supports this yet |
| Market structure (contract loss) | weak_evidence | Observable signals, not proven |

### Epistemic review
Blind review with PCS questions: q1=MODERATE, q2=MODERATE, q3=MODERATE (NO_EVIDENCE), q4=STRONG, q5=MODERATE (NO_EVIDENCE). The NO_EVIDENCE citations on q3 and q5 are intellectually honest -- the epistemic reviewer can't verify claims behind the information barrier.

## Where Batch-34 Falls Short

See individual gap files in this directory for detailed analysis and improvement context:

| Gap | File | Priority |
|-----|------|----------|
| No peer comparison | [gap-peer-comparison-framing.md](gap-peer-comparison-framing.md) | High |
| Incentive alignment missing | [gap-incentive-alignment.md](gap-incentive-alignment.md) | Medium |
| Worst case doesn't model dilution/covenant breach | [gap-worst-case-modeling.md](gap-worst-case-modeling.md) | Medium |
| Screening inconsistency across batches | [gap-screening-determinism.md](gap-screening-determinism.md) | Low |
| Catalyst duplication in output | [gap-catalyst-deduplication.md](gap-catalyst-deduplication.md) | Low |

## Gap Resolution (2026-03-15)

All 5 gaps closed in a single session. 8 commits, 36 new tests (94 total), zero regressions.

| Gap | Fix | Commits |
|-----|-----|---------|
| Peer comparison | Extracted `_build_peer_context()` helper, wired into `sector_scan` | `248aa00`, `50ef000` |
| Incentive alignment | Added `compensation_evidence` to Gemini layer, `incentive_alignment` to Stage 2 prompt/schema/fields tuple | `1208111`, `1ee9c7d` |
| Worst-case modeling | Added dilution/covenant breach instructions to Stage 1 fundamentals prompt | `d8b6505` |
| Screening determinism | Added `roic_pct`/`sbc_pct_of_revenue` to trailing_ratios, deterministic thresholds for solvency/ROIC/dilution | `781032f`, `5d1ac53` |
| Catalyst deduplication | Added dedup instruction to Stage 3 synthesis prompt | `af37bf9` |

## Gemini Review Observations

Each gap document was independently reviewed by Gemini. Cross-cutting themes and notable callouts:

### 1. False Negative Risk on Screening (from screening-determinism review)
A good candidate randomly getting FAIL from the LLM is permanently discarded -- later pipeline stages cannot save it. Our deterministic thresholds (PASS if ROIC >= 10%, FAIL if < 6%, BORDERLINE 6-10%) fix this for solvency/ROIC/dilution, but `revenue_growth` and `valuation` remain LLM-judged. Worth monitoring for false-negative patterns.

### 2. BORDERLINE_PASS Frequency Audit (from screening-determinism review)
If the LLM defaults to BORDERLINE_PASS when uncertain, the first filter becomes theater -- it passes everything to later stages rather than actually filtering. Should audit BORDERLINE_PASS frequency across scans to verify the filter is doing real work.

### 3. Catalyst Dedup Fragility (from catalyst-deduplication review)
The prompt-only dedup approach (Option A) is the weakest fix shipped. LLMs may hallucinate, delete unique catalysts that sound similar, or combine facts inaccurately. Gemini suggested Option D: change the `catalysts` schema to structured objects `{event_summary, evidence, source_url}` forcing the LLM to merge summary + citation into one entry. If prompt-only proves unreliable in live scans, this is the clear next step.

### 4. LLM Hallucination Risk on Thin Evidence (from incentive-alignment and worst-case reviews)
Executive compensation plans are complex (e.g., "50% TSR, 25% EBITDA, 25% strategic goals"). If Gemini can't find proxy data, the LLM may hallucinate standard industry metrics. The `UNKNOWN` enum on `gameable_risk` partially mitigates this. Similarly, covenant terms are buried in 10-K footnotes -- if not in context, the LLM will fabricate triggers. Both areas need anti-hallucination vigilance.

### Assessment

Gemini's review was ~20% novel signal, ~80% confirmation of known concerns. The false-negative risk and BORDERLINE audit are the two most actionable items. The catalyst dedup structured-object suggestion is a good fallback if the current approach fails. Most "blind spots" flagged (context bloat, token costs, API rate limits) are standard LLM engineering concerns already mitigated by existing architecture (slim candidates, peer cap at 5, TTL caching).

## Key Metrics (batch-34)

- Pipeline verdict: THESIS_BREAK_IMMINENT (capital_structure, strong_evidence)
- Validator verdict: APPROVE_WITH_CONCERNS (5 challenges, 4 objections)
- Effective probability: 33.25% (below 60% non-negotiable)
- Base CAGR: 57.95% (above 30% hurdle)
- Worst case downside: 100% (floor price negative)
- Epistemic: 2x NO_EVIDENCE, 0 weak_evidence_flags
