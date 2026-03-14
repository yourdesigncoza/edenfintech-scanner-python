# Pipeline Improvement Todo List

Source: [batch-17-18-19-analysis.md](batch-17-18-19-analysis.md)
Date: 2026-03-14

## P1: Solvency Gate — Interest Coverage Check
- [ ] Add interest coverage ratio to screening logic
- [ ] If operating_cash_flow < annual_interest_expense → FAIL (not BORDERLINE_PASS)
- [ ] Deterministic check using FMP data (no LLM needed)
- Files: screening logic in `pipeline.py`

## P2: Stage 3 Field Drops — Synthesis Prompt Fix
- [ ] Add `key_risks`, `moat_assessment`, `human_judgment_flags`, `exception_candidate` to Stage 3 synthesis prompt's required fields list
- [ ] Currently backfill recovers them, but Stage 3 should not drop them in the first place
- Files: `analyst.py` (Stage 3 synthesis prompt)

## P3: Probability Anchoring — Discrimination Guidance
- [ ] Add prompt guidance: "Base probability MUST differ between candidates with materially different risk profiles"
- [ ] Consider hardening gate that flags narrow-band probability (50-60%) across multiple tickers
- Files: `analyst.py` (fundamentals prompt), optionally `hardening.py`

## P4: Worst-Case Stress — Trough Representativeness
- [ ] Add prompt guidance: "When using historical trough, state whether period was anomalous (COVID, one-time) and adjust if so"
- [ ] For levered companies, worst case MUST include interest-service feasibility check
- Files: `analyst.py` (valuation prompt)

## P5: FMP Peer Quality (Deferred)
- [ ] No code change needed now — accept FMP stock-peers as-is
- [ ] Future: use Gemini to suggest business-model peers as supplementary source
- Status: **DEFERRED**

## P6: Screening Detail Packets in Report
- [ ] Add `screening_rejected_detail_packets` section to scan report
- [ ] Include analysis summary (cases, thesis, catalysts, risks) even for screening failures
- [ ] Gives operator context to decide on manual override
- Files: `pipeline.py` or `reporting.py`, possibly `scan-report.schema.json`

## P7: PreMortem `strong_evidence` — Deterministic Pre-Check
Source: [batch-25 vs batch-26 reproducibility test](batch-17-18-19-analysis.md)
- [ ] Add deterministic pre-check before PreMortem LLM runs: if `interest_coverage < 1.0 AND stockholders_equity < 0 AND fcf_margin <= 0` → auto-flag `capital_structure` as `strong_evidence`
- [ ] LLM can override down with written rationale, but default is set by observable FMP metrics
- [ ] Eliminates the single biggest source of LLM variance (B25 strong vs B26 weak on identical data)
- Files: `hardening.py` or `field_generation.py`, `validator.py` (PreMortem prompt)

## P8: Synthesis Backfill Count — Quality Warning Gate
Source: [batch-25 vs batch-26 reproducibility test](batch-17-18-19-analysis.md)
- [ ] Add hardening gate that flags when Stage 3 synthesis backfill exceeds threshold (e.g., >10 fields)
- [ ] B25 needed 5 fields backfilled; B26 needed 34 — signals synthesis quality collapse
- [ ] Flag as methodology warning (not hard reject) so operator knows overlay quality is lower
- Files: `analyst.py` (backfill logic), `hardening.py` or `automation.py`

## P9: Evidence Quality Variance — Provenance Verbosity Control
Source: [batch-25 vs batch-26 reproducibility test](batch-17-18-19-analysis.md)
- [ ] Investigate why citation count varies widely (40 vs 63) across identical inputs
- [ ] B26 generated 58% more provenance entries but mostly vague — more text, weaker sourcing
- [ ] Consider prompt guidance: "Each provenance entry MUST cite a concrete source (10-K, earnings call, FMP data)"
- [ ] Or add post-generation filter that strips provenance entries without concrete evidence refs
- Files: `analyst.py` (provenance generation prompts), `structured_analysis.py`

## P10: Anti-Anchoring Retry Loop for PreMortem
Source: [batch-25 vs batch-26 reproducibility test](batch-17-18-19-analysis.md)
- [ ] B26 PreMortem smuggled "~3.5%" into early_warning_metric text, correctly caught by hardening
- [ ] Currently flags as `THESIS_BREAK_PROBABILITY_ANCHORING` but does not trigger PreMortem retry
- [ ] Wire retry logic: on anchoring violation, re-run PreMortem with explicit feedback to remove numbers
- [ ] Max 1 retry to avoid infinite loops
- Files: `automation.py` (retry logic), `scanner.py` (hardening flag handling)
