# Batch 30: Utilities Sector Scan — Initial Analysis

**Date:** 2026-03-14
**Sector:** Utilities (NYSE)
**Duration:** 68 minutes (18:27 → 19:35 UTC)
**Result:** 0/5 PASS, 5/5 FAIL

## Pipeline Summary

| Ticker | Industry | Thesis Break | Evidence Quality | Rejection Reason |
|--------|----------|-------------|-----------------|------------------|
| **SMR** | Renewable Utilities | IMMINENT (market_structure: strong) | 48.7% (FAIL) | Pre-commercial SMR with Fluor overhang |
| **AQN** | Renewable Utilities | WATCH (4 weak) | 69.0% (PASS) | Epistemic/scoring filter |
| **OKLO** | Regulated Electric | IMMINENT (capital_structure + regulatory: strong) | 47.5% (FAIL) | Zero revenue, NRC risk, dilution spiral |
| **NRGV** | Renewable Utilities | WATCH (4 weak) | 63.3% (PASS) | Epistemic/scoring filter |
| **HE** | Diversified Utilities | WATCH (4 weak) | 26.8% (FAIL) | Maui liability + weak evidence |

**Clusters:** Renewable Utilities (AQN, SMR, NRGV), Regulated Electric (OKLO), Diversified Utilities (HE)

## Thesis Invalidation Module Performance

### IMMINENT breaks (deterministic + LLM)
- **SMR**: market_structure strong_evidence — Fluor monetization creates persistent supply overhang, pre-commercial company can't raise non-dilutive capital
- **OKLO**: capital_structure + regulatory strong_evidence — $9.1B market cap vs $250M tangible equity and zero revenue; NRC previously rejected Aurora design

### WATCH conditions (weak_evidence across multiple categories)
- **AQN**: 4 weak (SPOF on rate-case, capital structure leverage 7x, regulatory ROE risk, wholesale market oversupply)
- **NRGV**: 4 weak (SOSA project dependency, convertible dilution, Li-ion cost disruption, project-finance market shift)
- **HE**: 4 weak (Maui settlement SPOF, leverage/coverage stress, PUC securitization denial, legislative liability reallocation)

## Validator Observations

All 5 tickers received **APPROVE_WITH_CONCERNS**. Common themes:
1. Base-case revenue assumptions diverge from FMP actuals (SMR: $150M assumed vs $31.5M actual; AQN: $2.83B vs $2.45B)
2. Worst-case modeling omits forced equity raises and covenant breach scenarios
3. Probability assignments lack quantified sensitivity analysis
4. Catalyst timelines are optimistic (regulatory/licensing cycles take longer than modeled)

## Hardening Gate Results

| Gate | SMR | AQN | OKLO | NRGV | HE |
|------|-----|-----|------|------|----|
| Anchoring | Clean | Clean | Clean | Clean | Clean |
| Evidence quality | FAIL (48.7%) | PASS (69.0%) | FAIL (47.5%) | PASS (63.3%) | FAIL (26.8%) |
| Thesis break | IMMINENT | WATCH | IMMINENT | WATCH | WATCH |

## Notable Items

1. **Auto-hydration worked** — 3 sub-sector knowledge bases auto-hydrated during scan (Renewable Utilities, Regulated Electric, Diversified Utilities)
2. **HE ordering retry** — Analyst failed ordering discipline (worst_case before base_case), auto-retried from cached stages 1+2, succeeded on retry
3. **OKLO valuation disconnect** — $9.12B market cap on zero revenue and $250M tangible equity; validator correctly flagged this as requiring explicit commercialization-to-valuation math
4. **3 data gaps** — SOMN (cash flow missing), PPLC (income statement missing), DTK (income statement missing) — skipped gracefully
5. **Evidence quality threshold** — 3/5 tickers failed the 50% concrete citation minimum; HE worst at 26.8%
6. **Backfill counts** — SMR dropped 14 out-of-scope entries (highest), indicating synthesis prompt may need tightening for pre-commercial companies
