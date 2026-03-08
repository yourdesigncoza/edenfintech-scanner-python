# Scoring Formulas

## Decision Scoring (Buy/Don't Buy)

Used to compare opportunities and decide whether to invest.

| Input | Weight | Description |
|-------|--------|-------------|
| Reasonable worst case downside | 45% | % decline in share price if thesis is wrong |
| Base case probability | 40% | Likelihood base case valuation (or better) plays out |
| Base case CAGR | 15% | Annual return implied by base case |

### Downside Penalty Curve

Downside risk is scored on a non-linear curve:
- Moving from 20% downside to 30% carries ~1.5x the penalty the raw numbers suggest
- High-risk stocks are punished disproportionately more
- A stock with 60% downside is dramatically worse than one with 30% (not just "twice as bad")

### Scoring Formula

```
Score = (100 - adjusted_downside) * 0.45 + probability * 0.40 + min(cagr, 100) * 0.15
```

Where `adjusted_downside` applies the 1.5x penalty curve:
```
adjusted_downside = downside_pct * (1 + (downside_pct / 100) * 0.5)
```

Example: 30% downside → adjusted = 30 * 1.15 = 34.5. 60% downside → adjusted = 60 * 1.30 = 78.

### Downside Anchoring

The worst-case downside percentage used in decision scoring MUST be anchored to a mechanical floor price:

1. Analyst identifies trough inputs from 5yr FMP historical data (see `strategy-rules.md` Step 5 trough input anchoring table)
   - default = minimum-anchor inputs
   - exceptions allowed only if deterministic calibration rules in `valuation-guidelines.md` are triggered
2. Analyst runs `calc-score.sh floor <revenue_b> <margin_pct> <multiple> <shares_m> <current_price>` to compute the mechanical floor price and downside percentage
3. The mechanical floor is the STARTING POINT -- analyst may adjust downward (harsher) freely, but adjusting upward triggers "Heroic Optimism" flag
4. Final downside_pct used in scoring must have an auditable trough path tracing each input to a specific fiscal year

The floor command output provides the anchored downside_pct that feeds into the scoring formula above.

## Position Sizing

Used to determine how much capital goes into each position.

| Input | Weight | Description |
|-------|--------|-------------|
| Estimated % downside (worst case) | 50% | Higher weight than decision scoring |
| Estimated probability base case happens | 35% | |
| CAGR from base case | 15% | |

### Hard Breakpoints (Override Everything)

| Condition | Result |
|-----------|--------|
| Expected CAGR below 30% | Position size = 0% (no investment) |
| Probability of base case below 60% | Position size = 0% (no investment) |
| Downside risk of 80-99% | Position capped at 5% |
| Downside risk of 100% (total loss possible) | Position capped at 3% |

*Footnote: CAGR 20-29.9% with exception conditions (top-tier CEO + 6yr+ runway) → routed to "Pending Human Review" table, not auto-rejected. Full analysis still runs; human approves/rejects.*

### Probability Ceilings

These ceilings cap the analyst's probability estimate BEFORE scoring. If the analyst's estimate exceeds a ceiling, use the ceiling value and note which ceiling was applied.

| Condition | Max Probability | Rationale |
|-----------|----------------|-----------|
| Revenue or volume declined 3+ consecutive years | 65% | Persistent decline signals structural uncertainty regardless of narrative |
| Negative equity (not from spinoff/restructuring leverage) | 60% | Genuine solvency concern caps confidence |
| CEO tenure < 1 year at time of analysis | 65% | Insufficient track record at current company |

Note: Negative equity resulting from spinoff leverage (e.g., BRBR from Post Holdings) or deliberate recapitalization does NOT trigger the 60% ceiling — only negative equity from operating deterioration.

### Probability Banding

Analysts MUST assign probability as one of: **50% / 60% / 70% / 80%**. No other values permitted.
**80% is the maximum band** — raw totals above 80% (e.g., from stacked Likert modifiers) snap to 80%.
Raw estimates (e.g., 67%) are invalid — round to nearest band.

#### Base-Rate Anchoring

1. Read turnaround base rate from sector hydration Q6 (e.g., "3 of 5 recovered → 60%")
2. If no sector knowledge or no precedents: default to 50% band
3. Name closest historical precedent (e.g., "Synovus 2009-2013")
4. Apply sub-factor adjustments (see Likert Modifiers below)
5. Move to nearest band

#### Likert Modifiers (Sub-Factor Adjustments)

| Sub-Factor | Strong | Neutral | Weak |
|------------|--------|---------|------|
| Management execution | +10% | 0% | -10% |
| Balance sheet survival | +10% | 0% | -10% |
| Market conditions | +10% | 0% | -10% |

Net adjustment → move to nearest band. Sub-factors are reasoning scaffolds only — do NOT multiply them.

### Probability Confidence Score (PCS)

Assessed by the **Epistemic Reviewer agent** independently — the reviewer never sees the analyst's probability estimate or score. This prevents self-assessment bias.

**5-Question Checklist** (count "No" answers):

| # | Question | "Yes" = modelable/low uncertainty | "No" = hard to model/high uncertainty |
|---|----------|-----------------------------------|---------------------------------------|
| 1 | Is risk primarily operational (modelable)? | Normal business execution risk | Regulatory, legal, or existential risk dominates |
| 2 | Is regulatory discretion minimal? | Predictable regulatory environment | Outcome depends on discretionary regulatory action |
| 3 | Are there historical precedents? | Similar turnarounds have played out before | No comparable precedent exists |
| 4 | Is outcome non-binary? | Gradient of outcomes possible | Success/failure with little middle ground |
| 5 | Is macro/geopolitical exposure limited? | Primarily domestic/micro factors | Material exposure to macro, FX, or geopolitical risk |

**Confidence Score Mapping:**

| "No" Count | Confidence | Multiplier |
|------------|------------|------------|
| 0 | 5 | x1.00 |
| 1 | 4 | x0.95 |
| 2 | 3 | x0.85 |
| 3 | 2 | x0.70 |
| 4-5 | 1 | x0.50 |

**Formula:**
```
effective_probability = base_probability * multiplier
```

Use `effective_probability` (not base) in the scoring formula AND hard breakpoint checks (e.g., probability < 60% = size 0%).

**Confidence-Based Size Cap** (Layer 3 — applied AFTER score-to-size mapping):

| Confidence | Max Position Size |
|------------|-------------------|
| 5 | No cap (score matrix applies) |
| 4 | 12% max |
| 3 | 8% max |
| 2 | 5% max |
| 1 | 0% (watchlist only) |

```
final_size = min(score_based_size, confidence_cap, downside_cap)
```

**Binary Outcome Override:**
If question 4 ("Is outcome non-binary?") = **No** AND confidence ≤ 3 → max 5% regardless of score.

### Risk-Type PCS Friction

The analyst classifies each candidate's **dominant risk type**. Before computing effective probability, the orchestrator applies a friction modifier to the PCS confidence score. Friction makes confidence harder to achieve for structurally uncertain risk types.

| Dominant Risk Type | Default Friction | Override Condition | Overridden Friction |
|--------------------|------------------|--------------------|---------------------|
| Operational / Financial | 0 | — | — |
| Cyclical / Macro | -1 | Q3 = Yes (named historical precedent) | 0 |
| Regulatory / Political | -2 | Q2 = Yes (stable regulatory environment) | -1 |
| Legal / Investigation | -2 | No override available | -2 |
| Structural fragility (SPOF) | -1 | No override; also sets binary flag if Q4 not already No | -1 |

**Application:** `adjusted_confidence = max(1, raw_confidence - abs(friction))`

**Override logic is deterministic:**
1. Look up risk type → get default friction
2. Check PCS answer for override condition → apply or keep default
3. Record `friction_note` with decision: "{risk_type}, Q{n}={answer} -> friction {value}"

**Friction does NOT stack with PCS answers** — it applies after the 5-question count. The override conditions use PCS answers to determine WHETHER to soften friction, not to add more.

### Score-to-Position-Size Mapping

The decision score directly dictates the maximum position size for new capital:

| Score Range | Max Position Size | Interpretation |
|-------------|-------------------|----------------|
| 75+ | 15-20% | Highest conviction — exceptional risk/reward |
| 65-74 | 10-15% | Strong opportunity — clear thesis with manageable risk |
| 55-64 | 6-10% | Good opportunity — some uncertainty but favorable asymmetry |
| 45-54 | 3-6% | Moderate — acceptable but meaningful questions remain |
| Below 45 | 0% (Watchlist) | Insufficient score — do not invest |

Note: These maximums are FURTHER constrained by the hard breakpoints above (CAGR, probability, downside caps). The lower of the two limits applies.

### Portfolio-Level Rules

| Rule | Limit |
|------|-------|
| Maximum positions | 12 |
| Maximum single catalyst/theme exposure | 50% |
| Normal leverage | 15% |
| Leverage at S&P -10% | 20% |
| Leverage at S&P -15% | 25% |
| Leverage at S&P -25% | 30% |

## Valuation Formula

```
Revenue x FCF Margin x FCF Multiple / Shares Outstanding = Price Target
```

### CAGR Calculation

```
CAGR = ((target_price / current_price) ^ (1 / years)) - 1
```

### Hurdle Rate

- Primary: 30% annual CAGR minimum
- Exception: 20%+ acceptable IF top-tier CEO + 6yr+ runway (smaller position)

## Deployment Scenarios

### Scenario 1: Cash Available
- Compare new idea's score to best existing position that still has room to add
- Higher score gets the capital

### Scenario 2: No Cash Available
1. Does any current position have forward returns below 15%/year? If yes AND new position has lower downside risk → sell for new idea
2. If no position below 15% → need 40+ point score gap to justify swap

### Scenario 3: No Cash + Already Maxed on Theme
- Compare new idea to weakest holding within same theme only
- Apply Scenario 2 rules

## Sell Triggers

| Trigger | Condition |
|---------|-----------|
| Target reached | Forward returns fall below 30% hurdle |
| Rapid move | Forward returns fall below 10-15%/year |
| Thesis broken | Fundamental business change (not price change) |
