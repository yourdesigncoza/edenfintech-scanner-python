# Operating Checklist

## Purpose

This is the execution layer for the codex system.
Use it to keep behavior consistent under stress and avoid process drift.

## Daily Checklist (15-45 min)

- Review material news only for held names and active watchlist names.
- Update catalyst tracker for held names:
  - `On Track`
  - `Delayed`
  - `Broken`
- Check for thesis-breaking events:
  - Liquidity deterioration
  - Unexpected dilution/funding changes
  - Management behavior mismatch
  - Structural margin impairment
- Log any action triggers from `08-AFTER-THE-BUY` sell/trim rules.
- Do **not** change targets or probabilities intraday unless new fundamental data exists.

## Weekly Checklist (60-120 min)

### Portfolio Risk

- Recompute fresh-capital max sizes for all holdings.
- Check concentration:
  - Single name concentration
  - Theme/catalyst concentration
  - Geographic concentration
- Check forward return compression:
  - Flag names with forward CAGR in low-teens zone.

### Pipeline

- Add/remove names in `Active Theme List`.
- Promote only names passing Step 2 first filter.
- Drop names with no catalyst timeline.

### Decision Hygiene

- For any trade executed, verify it passed:
  - Scenario logic (`06-THE-DECISION`)
  - Sizing breakpoints (`07-POSITION-SIZING`)
  - Replacement gates (if funded by sale)

## Monthly Checklist (2-4 hrs)

### Full Re-Underwrite (Held Names)

For each holding update:
- Base case assumptions (revenue, margin, multiple, shares)
- Bear/base/stretch values
- Reasonable worst-case downside
- Base-case probability
- Forward CAGR from current price
- Fresh-capital max position size

### Portfolio Construction

- Rank all held names and top watchlist candidates by risk-adjusted score.
- Identify weakest 1-2 holdings on forward asymmetry.
- Evaluate replacement candidates under scenario 2/3 rules.

### Post-Mortem Loop

For any closed position, complete a post-mortem:
- Original thesis
- Actual outcome
- What was right
- What was wrong
- Process fix

## Quarterly Checklist (Half-day)

- Reassess exclusion list and circle-of-competence boundaries.
- Reassess leverage policy against macro and liquidity regime.
- Revalidate scoring calibration:
  - Were downside estimates too soft?
  - Were probability estimates too optimistic?
- Audit hit-rate by setup type (from `10-REAL-EXAMPLES`).
- Remove one weak rule and add one improved rule maximum (controlled evolution).

## Pre-Buy Gate (Must All Be True)

- Passes 5 first filters.
- Clear catalyst stack exists.
- Valuation supports hurdle return.
- Reasonable worst case is survivable.
- Position sizing output is non-zero.
- Trade improves portfolio asymmetry vs best alternative use of capital.

If any item is false, no buy.

## Pre-Sell / Trim Gate

Execute sell/trim only if one of these is true:
- Forward return falls below required level.
- Thesis is broken by facts.
- Better opportunity with superior asymmetry and acceptable downside.
- Position size exceeds risk tolerance after asymmetry deterioration.

## Decision Log Template

Use one entry per investment action.

```md
Date:
Ticker:
Action: Buy / Add / Trim / Sell / Pass
Price:
Position Impact:

Scenario Type (from Step 6):
- [ ] Cash available + theme wanted
- [ ] No cash + theme wanted
- [ ] No cash + theme full

Catalysts (hard/medium/soft):
1)
2)
3)

Base Case Summary:
- Revenue path:
- FCF margin path:
- Multiple:
- Share count assumption:
- Target value/date:

Risk Summary:
- Reasonable worst-case downside:
- Base-case probability:
- Forward CAGR from current price:

Sizing Output:
- Fresh-capital max size:
- Actual size taken:
- Reason for any difference:

Invalidation Triggers:
1)
2)
3)

Why this is better than next-best alternative:

Review Date:
```

## Red-Team Prompts (Use Before Large Adds)

- What has to be true for this to fail badly?
- Which assumption is most fragile?
- What evidence in next 1-2 quarters can falsify the thesis?
- If price dropped 30% tomorrow, would I add, hold, or exit and why?
- Am I underwriting business improvement or just multiple expansion?

## Operating Rules

- Consistency over complexity.
- Process changes are infrequent and logged.
- No discretionary override without written rationale in decision log.
- Price action alone is never a thesis change.
