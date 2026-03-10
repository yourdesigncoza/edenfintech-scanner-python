# Step 7: Position Sizing

Sizing is output from risk-adjusted conviction, not story excitement.

## Sizing Drivers

Current system emphasis (from late-2025 onward):
- Downside estimate (highest weight)
- Base-case probability
- Base-case CAGR

## Hard Breakpoints

- CAGR < 30% -> 0% new size
- Base-case probability < 60% -> 0% new size
- Downside 80-99% -> cap around 5%
- Total-loss tail risk -> cap around 3%

## Portfolio Constraints

- Max positions: ~12
- Theme/catalyst concentration cap: ~50% (often lower)
- Leverage baseline: ~15%, scaled higher mainly during broad drawdowns

## Legacy vs New-Capital Distinction

A position may be large due to low cost basis and past asymmetry.
That does **not** imply same size is valid for new capital today.

## Codex Extrapolation

Track both per holding:
- `Current Weight`
- `Fresh Capital Max Weight`

This avoids copying historical sizing into weaker current asymmetry.
