# EdenFinTech Strategy Rules — Complete Reference

This is the single source of truth for all strategy rules. Agents must follow these exactly.

## Philosophy

- Deep value turnaround investing — buy beaten-down companies with catalysts for recovery
- Concentrated portfolio: max 12 positions, 1-4yr holds
- Discipline beats talent. Risk management comes first. Patience is an edge.
- Only invest when expected CAGR >= 30% (with one exception noted below)
- "The stock and business are not the same thing" — price drops are not thesis breaks

## Step 1: Finding Ideas

### Starting Signal
- Stock price down **60%+ from all-time high** ("broken chart")
- This is NOT an automatic buy — it's the start of investigation

### Two Mandatory Conditions Before Investigating Any Industry
1. **Must be understandable** — basic comprehension of how companies make money
2. **Must NOT be in secular decline** — industry not permanently shrinking

### Quick Quality Sniff (Early Stage)
1. **Leverage**: How much debt relative to company size? Too much in beaten-down industry = dangerous
2. **Returns on capital (ROIC/ROCE)**: Is the company good at turning money into more money?
3. **Growth vs. share count**: Is revenue growth real per-share growth, or dilution-masked?

### Double-Plus Potential Check
- Stock must be able to **more than double (100%+ upside)** over next 2-3 years
- Check historical margins + historical multiples for "coiled spring" potential

### Idea Sources
- Primary: Top-down sector approach (underperforming sectors with catalysts)
- Secondary: Substack writers, YouTube, podcasts, news
- Tools: Stock Unlock, Finviz, Financial Modeling Prep

## Step 2: First Filter — 5 Checks

### Check 1: SOLVENCY
- Look at: total cash, current debt (due <12mo), long-term debt, FCF
- Deeper if worried: debt maturity schedule, credit facilities, asset sale potential
- **FAIL if**: solvency risk exists AND stock hasn't fallen enough to price it in
- **PASS if**: risk IS priced in (dramatic decline) + company can likely survive

### Check 2: DILUTION
- **FAIL if**: SBC > 5% of revenue WITHOUT corresponding growth
- **FAIL if**: shares issued to pay debt (near-immediate disqualification)
- **PASS if**: dilution is value-creating (acquisitions growing revenue faster than dilution)
- Check: per-share revenue growth, not just total revenue

### Check 3: REVENUE GROWTH
- Check 5-10 year historical trend
- **FAIL if**: no growth AND no catalysts to change it
- **PASS if**: growth exists OR clear catalysts identified

### Check 4: ROCE/ROIC
- **Minimum**: ~6% median (below = barely earning cost of capital)
- **Ideal**: ~10% median or higher
- **Cyclical exception**: full-cycle evaluation matters more than any single period
- **FAIL if**: chronically below ~6% AND worst in peer group

### Check 5: VALUATION
- Compare P/S, P/FCF, EV/FCF, EV/EBITDA against OWN historical averages
- Normalize: if margins depressed, use historical margins for "normalized P/FCF"
- **Hurdle**: must reasonably achieve 30% annual CAGR
- **FAIL if**: cannot meet 30% hurdle

## Step 3: Deep Analysis — Competitor Comparison

- Line up companies in same industry
- Compare: leverage, ROIC/ROCE, margins, industry niches, growth, dilution, potential returns
- Quality priority: **balance sheet strength > superior niches/margins > overall risk-adjusted return**
- **Permanent pass**: any clear downtrend in margins (falling steadily 5+ years)
- Keep weaker companies ONLY if: (1) no failure in earlier steps, (2) materially higher returns, (3) few alternatives

## Step 4: Qualitative Deep Dive — 5 Questions

### Q1: Durable Competitive Advantages (Moats)?
Six types: low-cost production, regulatory barriers, switching costs, network effects, capital requirements, brand strength

### Q2: Does Leadership Have Positive Operating History?
- CEO track record at current AND past roles
- Turnarounds need operators, not visionaries
- Background must match company's biggest challenge

### Q3: What Issues, and How Addressing Them?
- Must see: concrete, specific actions with measurable results
- Not acceptable: vague "working on it"

### Q4: What Is Management Compensation Tied To?
- Best: FCF (hardest to fake)
- Acceptable: EPS, Revenue, EBITDA
- Red flags: broken promises, vague language, overly promotional

### Q5: What Catalysts Could Change Things?
- Types: margin expansion, regulatory clearance, new leadership, faster growth, falling rates, demographic/FX tailwinds, demand drivers, divestitures, combination
- **HARD RULE: if no catalysts found, ALWAYS pass**

## Step 5: Valuation

### Formula
```
Revenue x FCF Margin x FCF Multiple / Shares Outstanding = Price Target
```

### 4 Inputs
1. **Revenue**: bottom-up from industry baseline + company initiatives + management targets + catalysts
2. **FCF Margin**: historical baseline, adjusted for cost cuts and operating leverage
3. **FCF Multiple**: start with industry normal, adjust up for quality/growth, down for leverage/risk
4. **Shares**: account for buybacks (good) or dilution (bad). If unclear, leave flat.

### Industry Multiple Rules of Thumb
- Cyclical/industrials: 12-15x FCF
- Consumer staples: 25-28x FCF
- Healthcare: higher baseline
- China/geopolitical: apply discount (e.g., 18x instead of low 20s)

### Hurdle Rate
- **Primary**: 30%+ annual CAGR required
- **Exception**: 20%+ acceptable IF: (1) 6yr+ compounding runway AND (2) top-tier CEO
- Below hurdle = no investment

**20% Exception — Human Gate:**
The LLM pipeline CANNOT approve the 20% exception. When a stock has CAGR 20-29.9% with plausible exception conditions:
1. Full analysis still runs (valuation, moats, catalysts, epistemic confidence)
2. Stock appears in the "Pending Human Review — 20% CAGR Exception Candidates" table, NOT in ranked candidates
3. Human approves or rejects after reading the complete report
4. Only a human-approved exception candidate may be promoted to the ranked list

### Trough-Anchored Worst Case (Required)

The worst case uses the same 4-input valuation formula as the base case, but with trough inputs anchored to 5yr FMP historical data. Same stock + same data = same downside estimate. The mechanical floor from `calc-score.sh floor` is the starting point, not the final answer.

#### Trough Input Anchoring

| Input | Trough Anchor | Source |
|-------|---------------|--------|
| Revenue | Lowest trailing-12-month revenue in 5yr FMP history | `income` endpoint |
| FCF Margin | Lowest annual FCF margin in 5yr FMP history | `cashflow` / `income` endpoints |
| FCF Multiple | Industry baseline from valuation-guidelines.md MINUS full discount schedule | `valuation-guidelines.md` |
| Shares | Current diluted shares (no buyback credit in worst case) | `metrics` endpoint |

Default behavior is strict minimum-anchor selection. Calibrated exceptions are allowed only when they match documented deterministic triggers in `valuation-guidelines.md`:
- `growth_revenue_bound_70pct_current`
- `margin_outlier_adjustment_second_lowest`

If an exception is used, the analyst must show the helper output and trigger condition in the trough-path notes.

#### 5-Step Structured Process

- **Step A:** Identify trough inputs from 5yr FMP data already fetched in Step 3
- **Step B:** Run `calc-score.sh floor` with trough inputs to get mechanical floor price
- **Step C:** Cross-check floor against tangible book value per share (see valuation-guidelines.md TBV Cross-Check)
- **Step D:** Analyst adjustment — may make floor harsher (event risk, litigation) freely; making it more optimistic triggers Heroic Optimism flag (see valuation-guidelines.md)
- **Step E:** Show "trough path" — a table mapping each trough input to a specific fiscal year and FMP data point

#### Asymmetric Override Rule

"Pessimism is free, optimism is flagged." The analyst may freely adjust the floor downward for event risk, litigation exposure, or structural concerns not captured in historical data. Adjusting the floor UPWARD from the mechanical calculation triggers the "Heroic Optimism" flag, which requires the analyst to justify why trough conditions are implausible. The orchestrator audits unresolved Heroic Optimism flags.

#### Trough Path Format

| Input | Trough Value | Fiscal Year | FMP Data Point |
|-------|-------------|-------------|----------------|
| Revenue | $2.2B | FY2022 | income statement, trailing 12mo |
| FCF Margin | 7.0% | FY2021 | cashflow / income |
| FCF Multiple | 10x | — | Industry 15x minus discounts (-3x leverage, -2x decline) |
| Shares | 130M | Current | metrics, diluted |

See `scoring-formulas.md` for the mechanical downside anchoring requirement and `valuation-guidelines.md` for the Heroic Optimism test and TBV cross-check.

### Gut Check
- Does implied multiple make sense vs. own history?
- Does it make sense vs. peers?
- If gut check fails, adjust or walk away

## Step 5b: Risk Factor Enrichment Override Protocol

Risk enrichment via 10-K filings may reveal risks invisible in financial statements. Scores are NEVER revised post-enrichment, but candidate ranking may be adjusted.

### Demotion Triggers

A candidate MAY be demoted in the final ranking if enrichment reveals ANY of:
1. **Customer concentration** > 70% of revenue in 3 or fewer accounts
2. **Structural demand destruction** — technology substitution, regulatory ban, or demographic shift that permanently shrinks the addressable market
3. **Previously unidentified kill-level risk** with no disclosed management mitigation plan
4. **Supply chain single point of failure** that directly threatens an identified catalyst

### Demotion Process
1. Enrichment findings are documented in the report but scores remain unchanged
2. If a demotion trigger is found, add a **DEMOTION** flag with the specific trigger and evidence
3. Demoted candidates are ranked below all non-demoted candidates, regardless of score
4. The next-highest non-demoted candidate fills any vacated deployment slot
5. The demotion reason MUST appear in the Portfolio Impact section of the report

### What Is NOT a Demotion Trigger
- Risks already identified and reflected in the pre-enrichment analysis
- Generic industry risks without company-specific evidence (e.g., "competition may increase")
- Risks with clear, specific management mitigation plans disclosed in filings
- Risks that confirm (rather than contradict) the existing thesis

## Step 6: Decision Scoring

See `scoring-formulas.md` for the math.

## Step 7: Position Sizing

See `scoring-formulas.md` for rules and hard breakpoints.

## Step 8: After the Buy — Monitoring & Sell Rules

### 5 Things to Track
1. Are catalysts showing up on schedule?
2. Is management saying one thing, doing another?
3. Are margins shifting in unexpected ways?
4. Are competitors pulling ahead?
5. Which macro events actually matter?

### 3 Sell Triggers
1. Target reached, forward returns < 30% hurdle
2. Rapid move, forward returns < 10-15%/year
3. Fundamental thesis break (business change, NOT price change)

### What is NOT a Sell Trigger
- Stock price going down
- Scary headlines without business impact
- Fear or general market sentiment
