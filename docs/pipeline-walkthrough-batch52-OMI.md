# Pipeline Walkthrough: batch-52 / OMI

Using `runs/batch-52/OMI` as a concrete example of the full auto-scan pipeline.

---

## Run Summary

- **Ticker:** OMI (Owens & Minor)
- **Scan ID:** 20260316T162315Z
- **Duration:** ~11 minutes (16:23 → 16:34 UTC)
- **Result:** FAIL

---

## Stage-by-Stage Breakdown

### 1. Data Retrieval (`raw/`)

Two parallel fetches populate the raw bundle:

| File | Source | Contents |
|------|--------|----------|
| `fmp-raw.json` | FMP API | Financials, price, ratios (quantitative) |
| `gemini-raw.json` | Gemini grounded search | Catalysts, risks, moat, management (qualitative) |
| `merged-raw.json` | Pipeline merge | Both sources merged into a single ranked bundle with fingerprint |

### 2. Structured Analysis Template (`structured-analysis-template.json`)

A blank overlay is generated from the schema — all fields initialised as `__REQUIRED__` placeholders ready for the analyst agent to fill.

### 3. Claude Analyst Agent — 3 sequential calls

Claude Haiku fills the overlay in stages, conservative-first ordering enforced:

| File | Stage | Contents |
|------|-------|----------|
| `analyst-fundamentals.json` | Stage 1 | Revenue CAGR, FCF, debt ratios — quantitative fields only |
| `analyst-qualitative.json` | Stage 2 | Moat, catalysts, risks, management quality |
| `analyst-synthesis-raw.json` | Stage 3 | Thesis summary, probability bands, base/worst/stretch cases |

> `analyst-synthesis-retry1.json` exists — synthesis failed validation on the first attempt and was retried.

Ordering discipline is enforced in prompts: `worst_case_assumptions` before `base_case_assumptions`, bear arguments before bull in `thesis_summary`.

### 4. Validator (`validator-result-retry1.json`)

Two-pass review of the filled overlay:
1. **Deterministic contradiction detection** — checks for internal inconsistencies in the overlay
2. **LLM red-team questioning** — adversarial Claude agent challenges the analyst's reasoning

Emits an APPROVE or REJECT verdict. A retry occurred here too.

### 5. Hardening (`hardening-result.json`, `premortem-result-retry1.json`)

Bias detection gates applied before the overlay reaches the deterministic pipeline:

| Gate | Result | Detail |
|------|--------|--------|
| Anchoring check | — | No flag |
| Evidence quality | **WARNING** | 32.7% concrete citations — below 50% minimum (17/52 concrete) |
| CAGR exception panel | — | No flag |
| Thesis break | **THESIS_BREAK_IMMINENT** | 3 strong-evidence invalidation conditions detected |

### 6. Epistemic Review (`epistemic-review-result.json`)

Blind review with score-filtered payload — the reviewer cannot see screening verdicts or probability scores. Assesses reasoning quality and evidence grounding independently.

### 7. Finalized Overlay (`finalized-overlay.json`)

Overlay promoted after all agent stages complete. Provenance lifecycle: `MACHINE_DRAFT → LLM_DRAFT → LLM_CONFIRMED/LLM_EDITED → FINALIZED`.

### 8. Deterministic Pipeline → Report (`report.json`, `report.md`)

Five screening checks run against the finalized overlay:

- Solvency
- Dilution
- Revenue growth
- ROIC
- Valuation

**Result: FAIL**

---

## Why OMI Failed

Three hard stops fired simultaneously:

**1. Evidence quality below threshold**
Only 33% of citations were concrete (named sources with specifics) vs. the 50% minimum. The overlay relied too heavily on vague qualitative assertions.

**2. Thesis break imminent**
Three independent conditions each met the strong-evidence bar for thesis invalidation:

- **Covenant breach risk** — FY2025 EBITDA of $101M provides limited cushion; any revenue decline >20% or margin compression >300bps triggers the 4.0x Net Debt/EBITDA covenant, impairing equity 50–80%
- **CMS reimbursement cuts** — A 15% Medicare rate cut would reduce revenue by $165–207M annually, making debt service unsustainable
- **Competitive consolidation** — Larger peers (Amedisys $8.5B, LHC Group $2.1B) could take 20–30% market share from OMI's $2.76B Patient Direct segment over 3 years

**3. Incomplete FY2025 financials**
- `operatingCashFlow=0` and `capitalExpenditure=0` but `cashAtEndOfPeriod>0`
- `revenue>0` but `costOfRevenue=0` and `grossProfit=0`
- `totalAssets>0` but `totalLiabilitiesAndTotalEquity=0`
- Ticker flagged as not actively trading

This is a textbook FAIL — the pipeline caught real structural problems across data quality, evidence quality, and thesis integrity before any capital allocation decision could be made.

---

## Artifact Map

```
runs/batch-52/
├── manifest.json                        # Run metadata, status, hardening flags
└── OMI/
    ├── report.json                      # Final scan report (structured)
    ├── report.md                        # Final scan report (human-readable)
    └── raw/
        ├── fmp-raw.json                 # FMP API response
        ├── gemini-raw.json              # Gemini qualitative bundle
        ├── merged-raw.json              # Merged ranked bundle
        ├── structured-analysis-template.json
        ├── analyst-fundamentals.json
        ├── analyst-qualitative.json
        ├── analyst-synthesis-raw.json
        ├── analyst-synthesis-retry1.json
        ├── validator-result-retry1.json
        ├── premortem-result-retry1.json
        ├── hardening-result.json
        ├── epistemic-review-result.json
        ├── finalized-overlay.json
        └── llm-interactions.md         # Full prompt/response log for every LLM call
```
