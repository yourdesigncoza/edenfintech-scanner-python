# The Epistemic Review Process

## Analogy: The Blind Jury

Think of the pipeline like a courtroom. The **analyst** is the lawyer building the case — they see everything (financials, valuations, probabilities, sector knowledge). The **validator** is opposing counsel — they also see everything and try to poke holes.

The **epistemic reviewer** is a **blindfolded jury member**. They only hear the narrative — the thesis, risks, catalysts, and moat — but are never shown the numbers. No prices, no probabilities, no target valuations. This is deliberate: it prevents the reviewer from rubber-stamping a convincing-looking score. They must judge the *quality of the reasoning* purely on qualitative grounds.

```
+-------------------------------------------------------------+
|                    FULL ANALYST OVERLAY                      |
|                                                             |
|  +------------------+  +----------------------------------+ |
|  |  ALLOWED (qual)  |  |  BLOCKED (quant)                 | |
|  |                  |  |                                  | |
|  |  ticker          |  |  base_probability_pct            | |
|  |  industry        |  |  target_price                    | |
|  |  company_desc    |  |  floor_price                     | |
|  |  thesis_summary  |  |  cagr_pct                        | |
|  |  key_risks       |  |  decision_score                  | |
|  |  catalysts       |  |  base_case_assumptions           | |
|  |  moat_assessment |  |  worst_case_assumptions          | |
|  |  dominant_risk   |  |  downside_pct                    | |
|  +--------+---------+  +----------------------------------+ |
|           |                                                  |
+-----------+--------------------------------------------------+
            |
            v
   +------------------+
   |   EPST-01         |  <-- frozen dataclass enforces barrier
   |   Information     |      at the TYPE level -- not just a
   |   Barrier         |      prompt instruction, actual code
   |   (Code-level)    |      that strips all numeric fields
   +--------+----------+
            |
            v
   +-----------------------------------------+
   |   EPISTEMIC REVIEWER (Claude Haiku)     |
   |                                         |
   |   Answers 5 Yes/No PCS questions        |
   |   Must cite evidence or say NO_EVIDENCE |
   +--------+--------------------------------+
            |
            v
   +-----------------------------------------+
   |   POST-PROCESSING                       |
   |   - WEAK_EVIDENCE detector              |
   |   - NO_EVIDENCE friction (-1 if >=3)    |
   |   - PCS laundering detector             |
   +--------+--------------------------------+
            |
            v
   +-----------------------------------------+
   |   SCORING (scoring.py)                  |
   |   PCS answers -> confidence -> mult     |
   |   -> effective_probability -> sizing    |
   +-----------------------------------------+
```

## The 5 PCS Questions

PCS = **Probabilistic Confidence Score**. Each question is Yes/No. Every "No" reduces confidence:

| Question | What It Asks | Yes means... | No means... |
|----------|-------------|-------------|-------------|
| **q1_operational** | Can management fix this? | Clear operational levers exist | Situation is outside management control |
| **q2_regulatory** | Is regulatory risk bounded? | Outcomes are predictable | Regulator has wide discretion |
| **q3_precedent** | Has this been done before? | Comparable recoveries exist | Novel/unprecedented situation |
| **q4_nonbinary** | Are outcomes distributed? | Multiple recovery paths | All-or-nothing binary outcome |
| **q5_macro** | Is macro secondary? | Company-specific factors dominate | Macro conditions drive the thesis |

## How "No" Answers Hit the Numbers

```
No answers    Raw confidence    Multiplier
   0               5              1.00x     <-- full probability preserved
   1               4              0.95x
   2               3              0.85x
   3               2              0.70x     <-- 30% haircut
   4-5             1              0.50x     <-- half the probability
```

Then the **dominant risk type** adds friction:

```
Risk Type                    Default Friction    Override
Operational/Financial              0             (none)
Cyclical/Macro                    -1             -> 0 if Q3=Yes (precedent exists)
Regulatory/Political              -2             -> -1 if Q2=Yes (bounded)
Legal/Investigation               -2             (none)
Structural fragility (SPOF)       -1             (none)
```

Friction reduces the confidence level further. Example -- BABA (Regulatory/Political, q1=NO, q2=NO, q3=NO):
- 3 No's -> raw confidence 2
- Regulatory friction -2, q2=NO so no override
- Adjusted confidence = max(1, 2 - 2) = 1
- Multiplier = 0.50x -> probability cut in half

Versus OMI (Operational/Financial, all YES):
- 0 No's -> raw confidence 5
- Operational friction = 0
- Adjusted confidence = 5
- Multiplier = 1.00x -> probability untouched

## The Three Evidence Quality Detectors

**EPST-04: WEAK_EVIDENCE** -- catches vague citations like "industry reports suggest" or "general consensus." Each PCS answer gets a weak_evidence flag if the source isn't concrete (10-K, earnings call, FMP data, etc.).

**EPST-05: NO_EVIDENCE friction** -- if >=3 of the 5 answers cite `NO_EVIDENCE`, an additional -1 friction penalty applies. This is what happened to OMI: all 5 answers were NO_EVIDENCE because the allowlist was too restrictive (now fixed with `company_description`).

**EPST-06: PCS laundering** -- detects when the reviewer is just parroting the analyst's own citations rather than independently evaluating. If >80% of reviewer sources overlap with analyst provenance, it's flagged as laundering.

## The Information Barrier

The information barrier is **code-enforced, not prompt-enforced**. The `EpistemicReviewInput` is a frozen dataclass -- you literally cannot pass numeric fields through it. The `extract_epistemic_input()` function strips everything except the qualitative fields (ticker, industry, thesis_summary, key_risks, catalysts, moat_assessment, dominant_risk_type, company_description). Even if someone modified the prompt to ask for scores, the data simply isn't there.

The `isinstance()` check rejects any dict or ad-hoc object that might bypass the barrier. The barrier is provable at the type level, not just a "please don't look at the numbers" instruction.

## Key Files

- `epistemic_reviewer.py` -- information barrier, PCS questions, evidence detectors
- `scoring.py` -- PCS answers -> confidence -> multiplier -> effective_probability
- `automation.py` -- orchestrates: analyst -> validator -> epistemic reviewer flow

---

# Review Findings (Claude + Gemini Collaborative Review, 2026-03-14)

## Core Issue: The "Forced Ignorance Paradox"

The epistemic reviewer is trapped in a no-win scenario:
- It can't cite original sources because it never saw them (NO_EVIDENCE)
- If it cites the analyst's narrative, it gets flagged for laundering (EPST-06)
- If it says NO_EVIDENCE honestly, it gets a friction penalty (EPST-05)

**We are penalizing the reviewer for being epistemically honest -- the exact opposite of what an epistemic review should do.**

## Identified Issues

### 1. NO_EVIDENCE Penalty Punishes Honesty (HIGH)

The reviewer physically cannot cite sources it never saw. The analyst summary says "elevated leverage" but the reviewer can't verify this against the actual $1.8B debt figure because it's blocked by the barrier. NO_EVIDENCE is the only honest answer, and it triggers friction.

**Evidence**: OMI (Batch 22) -- all 5 answers were YES with NO_EVIDENCE. The reviewer gave correct directional answers but was honest about having no primary sources. Result: -1 additional friction penalty for being truthful.

### 2. Questions Are Risk Filters, Not Epistemic (MEDIUM)

The 5 PCS questions grade risk TYPE (operational vs regulatory vs macro) rather than reasoning QUALITY. A true epistemic review would ask:
- Is the analyst relying on management promises or historical base rates?
- How fragile is this thesis to unknown unknowns?
- Does the bear case steel-man the opposing view or straw-man it?
- Are there unsupported assertions in the narrative?

The current questions tell you WHAT kind of risk exists. They don't tell you whether the analyst's REASONING about that risk is sound.

### 3. Yes/No Binary Is Too Crude (MEDIUM)

A "barely yes" and a "strong yes" get identical treatment. Example:

- OMI Q2 (regulatory bounded): Answered "Yes" because OMI is an operational turnaround, not because healthcare regulators are predictable. The question didn't really apply, but it contributed favorable confidence.
- A 3-tier system (CLEAR_YES / MIXED / CLEAR_NO) or an N/A option would prevent inapplicable questions from inflating confidence.

### 4. Balance Sheet Blind Spot (HIGH)

The reviewer cannot answer Q1 ("Can management fix this?") without knowing whether the company has the liquidity to survive the turnaround. It sees "elevated leverage" in key_risks but not:
- $1.8B net debt vs $207M market cap
- $0 operating cash flow in FY2025
- Interest coverage < 1x

A turnaround is not operational if solvency dictates the timeline. The barrier blocks exactly the data needed to answer the question it's asking.

### 5. Multiplier Is Really a Kill Switch (LOW -- working as intended)

At confidence 2 (0.70x multiplier), a 65% base probability becomes 45.5% -- below the codex's 60% minimum for new capital. This isn't really "sizing friction"; it's a dressed-up veto. This may be fine by design, but it should be understood as such.

### 6. Friction Overrides Are Asymmetric (MEDIUM)

| Risk Type | Default Friction | Override | Result |
|-----------|-----------------|----------|--------|
| Cyclical/Macro | -1 | Q3=Yes -> 0 | Full removal |
| Regulatory/Political | -2 | Q2=Yes -> -1 | Partial removal |

Why does Cyclical get full friction removal with precedent, but Regulatory only gets partial reduction when bounded? There's no principled basis for this asymmetry. Both overrides reward favorable PCS answers, but at different rates.

## Proposed Improvements

### A. Strategic Information Permeability

Maintain the barrier against forward-looking predictions (targets, CAGR, base_probability). Allow trailing/historical fundamentals so the reviewer can verify operational claims:

```
KEEP BLOCKED (forward-looking):     ALLOW THROUGH (historical):
  base_probability_pct                debt_to_equity ratio
  target_price                        interest_coverage
  floor_price                         trailing FCF margin
  cagr_pct                            revenue_history trend
  base/worst/stretch cases            cash_runway_months
  decision_score                      shares_outstanding trend
```

This lets the reviewer verify "management has operational levers" against actual balance sheet reality without anchoring on the analyst's predictions.

### B. 3-Tier Grading System

Replace binary Yes/No with:
- **CLEAR_YES** (1.0) -- strong evidence supporting favorable answer
- **MIXED_OR_CONDITIONAL** (0.5) -- partially applicable, evidence is ambiguous
- **CLEAR_NO** (0.0) -- strong evidence against

This prevents inapplicable questions from inflating confidence (OMI Q2) and captures the nuance that binary can't.

### C. Redefine "Evidence" Standard

Instead of demanding external citations the reviewer can't have, evaluate **internal coherence** of the analyst's narrative:
- Change from "cite your source" to "identify unsupported assertions"
- Flag when the analyst claims management will cut costs but provides no specific mechanism
- Flag when worst case uses a trough that may not be representative
- This aligns with what epistemology actually means: evaluating how we know what we claim to know

### D. Add a True Epistemic Question

Current questions assess risk type. Add a question that assesses reasoning quality:

**Q6 (proposed): Does the thesis rely on unprecedented assumptions or management projections that contradict historical base rates?**

This directly catches optimism bias -- the primary failure mode the epistemic review is supposed to prevent.

## Real-World Results Supporting These Findings

| Ticker | PCS Answers | Evidence Quality | What Went Wrong |
|--------|------------|-----------------|-----------------|
| BABA | q1=NO, q2=NO, q3=NO | All NO_EVIDENCE | Correct penalty, but NO_EVIDENCE is honest -- reviewer couldn't cite China regulatory sources it never saw |
| OMI | All YES | All NO_EVIDENCE | 5 correct answers, penalized for honesty. Couldn't verify $1.8B debt or $0 OCF claims |
| TCMD | q1=NO, q2=NO, q3=NO | Mixed | Correct that regulatory is dominant. But couldn't assess whether 55.4% off ATH is "close enough" because price data is blocked |
| HRL | Varies | 76.5% concrete | Best evidence quality -- US domestic tickers with standard financial data produce better grounding |

## Implementation Priority

1. **Fix NO_EVIDENCE penalty** -- stop penalizing honest answers (change meaning or remove penalty)
2. **Add historical fundamentals** to the allowlist (strategic permeability)
3. **Add N/A option** to prevent inapplicable questions from inflating scores
4. **Add an epistemic question** that assesses reasoning quality, not just risk type
5. **3-tier grading** -- replace Yes/No binary (larger refactor, do after validating 1-4)
