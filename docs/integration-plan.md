# Integration Plan — 10 Steps

Merge the original scanner's LLM agent capabilities into the Python pipeline's
deterministic framework. Remove the human from the loop. Preserve Kyler's System Codex
as the methodology source of truth.
Reference ( original scanner's LLM ): /home/laudes/zoot/projects/edenfintech-scanner
Kyler's System : /home/laudes/zoot/projects/edenfintech-scanner-python/kylers-system-codex

**Provider assignments (stable):**
- Claude → all agents (analyst, epistemic reviewer, validator/red-team)
- Gemini Grounded Search → qualitative research retrieval
- OpenAI → final judge (existing)

**Storage:** validated JSON throughout, including sector knowledge.
**Caching:** port `fmp-api.sh` TTL/caching logic to Python.

---

## Step 1: FMP Caching Layer

Port the original scanner's mature caching logic into `fmp.py`.

**What:**
- Per-endpoint TTLs: screener/ratios/metrics/ev = 7d, profile/peers = 30d, income/balance/cashflow = 90d, price-history = 1d
- Cache directory: `data/cache/<endpoint>/<TICKER>.json`
- `--fresh` bypass flag
- Empty/error responses never cached
- `cache-status` and `cache-clear` CLI commands

**Why first:** Every downstream step depends on FMP data. Caching prevents redundant API calls
during development and mirrors production behavior. Without this, iterating on later steps
burns API quota.

**Deliverable:** `fmp.py` with caching, new CLI commands `cache-status` and `cache-clear`.
Unit tests with fixture-based responses confirming TTL behavior.

**Validates:** Run `python -m edenfintech_scanner_bootstrap.cli cache-status` and confirm
it reports per-endpoint counts. Run a retrieval, confirm cache hit on second call.

---

## Step 2: Schema Enrichments (Codex Alignment)

Add the missing structured fields that the Codex requires but the current schema lacks.

**What — new fields in `structured-analysis.schema.json` and `scan-input.schema.json`:**
- `catalyst_stack[]`: `{type: "HARD"|"MEDIUM"|"SOFT", description: str, timeline: str}`
- `invalidation_triggers[]`: `{trigger: str, falsifying_evidence: str}`
- `decision_memo`: `{better_than_peer: str, safer_than_peer: str, what_makes_wrong: str}`
- `issues_and_fixes[]`: `{issue: str, fix: str, evidence_status: "ANNOUNCED_ONLY"|"ACTION_UNDERWAY"|"EARLY_RESULTS_VISIBLE"|"PROVEN"}`
- `setup_pattern`: enum `"SOLVENCY_SCARE"|"QUALITY_FRANCHISE"|"NARRATIVE_DISCOUNT"|"NEW_OPERATOR"|"OTHER"`
- `stretch_case`: same shape as `base_case` (bear/base/stretch per Codex `05-VALUATION.md`)

**What — new pipeline gates in `pipeline.py`:**
- Reject if `catalyst_stack` has zero HARD or MEDIUM entries
- Reject if all `issues_and_fixes` entries are ANNOUNCED_ONLY (no evidence of traction)
- Flag (not reject) missing `setup_pattern` or `decision_memo`

**Why second:** These fields define the contract that LLM agents must fill. Building agents
before the schema exists means retrofitting later.

**Deliverable:** Updated schemas, updated `field_generation.py` defaults, updated pipeline
gates, updated regression fixtures.

**Validates:** `python -m edenfintech_scanner_bootstrap.cli validate-assets` passes.
Existing tests still pass. New test confirming catalyst-stack rejection gate.

---

## Step 3: Sector Knowledge Framework

Build the sector hydration pipeline — fetch, validate, store, and reuse sector research.

**What:**
- New module: `sector.py`
- Sector schema: `assets/methodology/sector-knowledge.schema.json`
  - Per sub-sector: key metrics, valuation approach, regulatory landscape, historical
    precedents, moat sources, kill factors, FCF margin ranges, typical multiples
  - Sector-level: overview, cross-cutting themes, macro context
  - Metadata: hydration date, staleness threshold (180 days), source queries
- Storage: `data/sectors/<sector-slug>/knowledge.json` (validated JSON)
- Registry: `data/sectors/registry.json` (hydration status per sector)
- Gemini grounded search integration for research queries (8 queries per sub-sector,
  same structure as original scanner's sector-researcher agent)
- Staleness check before scan: if sector data > 180 days old, warn

**Why third:** Sector knowledge feeds analyst quality. The original scanner proved this
dramatically — analysts with hydrated sector context produce industry-appropriate valuations
instead of generic FCF multiples for everything.

**Deliverable:** `sector.py` with `hydrate_sector()`, `load_sector_knowledge()`,
`check_sector_freshness()`. CLI commands: `hydrate-sector`, `sector-status`.
Schema + validation. One fixture-based test per function.

**Validates:** `hydrate-sector "Consumer Defensive"` produces a validated JSON file.
`sector-status` reports hydration dates. Second hydration reuses cache where fresh.

---

## Step 4: Claude Analyst Agent

The first LLM agent — replaces the human who fills structured analysis overlays.

**What:**
- New module: `agents/analyst.py`
- Input: merged raw bundle (FMP + Gemini) + sector knowledge (if hydrated)
- Output: populated structured analysis overlay with all `__REQUIRED__` placeholders filled
- Provenance status: `LLM_DRAFT` (new status, distinct from `MACHINE_DRAFT`)
- Must fill: screening inputs, analysis inputs (including new Codex fields: catalyst_stack,
  invalidation_triggers, decision_memo, issues_and_fixes with evidence status, setup_pattern,
  stretch_case), thesis_summary, catalysts, key_risks, moat_assessment
- Must write `review_note` per field citing specific evidence
- Prompt discipline: generate worst case BEFORE base case, bear thesis BEFORE bull thesis
- Uses sector knowledge when available for industry-appropriate valuations

**Prompt structure:**
1. System: methodology rules (strategy-rules.md), field contracts, evidence requirements
2. Context: raw bundle evidence, sector knowledge
3. Task: fill each field with evidence-grounded values
4. Output: JSON conforming to structured-analysis schema

**Why fourth:** This is the core automation — replacing the human analyst. Depends on
enriched schema (Step 2), sector knowledge (Step 3), and cached FMP data (Step 1).

**Deliverable:** `agents/analyst.py` with `run_analyst()`. Config for Claude model selection.
Integration test: given a fixture raw bundle, produces a valid structured analysis overlay.

**Validates:** Output passes `validate_structured_analysis()`. All `__REQUIRED__` markers
replaced. All `review_note` fields populated. `catalyst_stack` has typed entries.
Schema validation passes.

---

## Step 5: Epistemic Reviewer Agent (Architecturally Blind)

The independent confidence assessor — the system's epistemic moat.

**What:**
- New module: `agents/epistemic_reviewer.py`
- **Hard information barrier (code-enforced, not prompt-enforced):**
  The function signature accepts ONLY: ticker, industry, thesis_summary, key_risks,
  catalysts, moat_assessment, dominant_risk_type. It does NOT accept and cannot access:
  base_probability, base_case, worst_case, score, position_size, or any numbers.
- Output: 5 PCS answers with justification + evidence per answer
- Evidence anchoring enforcement:
  - Each answer must cite a named source OR declare `NO_EVIDENCE`
  - Detect `WEAK_EVIDENCE`: evidence field without concrete citation gets flagged
  - If >= 3 of 5 answers are `NO_EVIDENCE`, apply additional -1 friction
- PCS laundering detection: cross-reference evidence sources against analyst's evidence.
  If > 80% overlap, flag `POSSIBLE_PCS_LAUNDERING`
- Uses Gemini grounded search independently for precedent verification (Q3)

**Why fifth:** Depends on the analyst output (Step 4) to have something to review.
The architectural blindness MUST be a code-level contract — the function literally
cannot receive score/probability data.

**Deliverable:** `agents/epistemic_reviewer.py` with `run_epistemic_review()`.
Type signature enforces information barrier. Tests confirming: barrier holds,
WEAK_EVIDENCE detection works, NO_EVIDENCE friction applies.

**Validates:** Pass a fixture with known weak evidence — confirm flags are raised.
Pass a fixture where reviewer would see scores if barrier leaked — confirm it doesn't.

---

## Step 6: Red-Team Validator Agent

Adversarial review before finalization — implements the Codex's red-team prompts.

**What:**
- New module: `agents/validator.py`
- Input: analyst's filled overlay + raw evidence bundle (NOT the epistemic review or scores)
- Must answer the 5 Codex red-team questions as structured output:
  1. What has to be true for this to fail badly?
  2. Which assumption is most fragile?
  3. What evidence in next 1-2 quarters can falsify the thesis?
  4. If price dropped 30% tomorrow, add/hold/exit and why?
  5. Am I underwriting business improvement or just multiple expansion?
- Output: `validation_result` with pass/fail per question + overall verdict
- Contradiction detection: cross-check analyst's base case assumptions against raw FMP data
  (e.g., analyst claims revenue growth but FMP shows 3-year decline)
- Can REJECT the overlay (sends back to analyst with specific objections) or APPROVE

**Why sixth:** Depends on analyst output (Step 4). Creates the two-agent consensus
that replaces human judgment. The validator is the "second pair of eyes."

**Deliverable:** `agents/validator.py` with `run_validation()`. Test with fixture
containing a deliberate contradiction — confirm rejection.

**Validates:** Fixture with optimistic revenue assumption contradicted by FMP data →
validator rejects. Fixture with sound analysis → validator approves.

---

## Step 7: Automated Finalization Flow

Wire Steps 4-6 into a single-pass flow that replaces the two-pass human review package.

**What:**
- New module: `automation.py`
- Flow: `auto_analyze(ticker, config) -> FinalizedOverlay`
  1. Fetch raw bundles (FMP + Gemini) — uses caching from Step 1
  2. Load sector knowledge if available — from Step 3
  3. Run Claude analyst agent → LLM_DRAFT overlay — Step 4
  4. Run Claude validator agent → approve or reject with objections — Step 6
  5. If rejected: re-run analyst with validator objections (max 2 retries)
  6. Run Claude epistemic reviewer (architecturally blind) → PCS answers — Step 5
  7. Merge PCS answers into overlay
  8. Set provenance to `LLM_CONFIRMED`, finalize
  9. Return finalized overlay ready for deterministic pipeline
- Update `structured_analysis.py`: add `LLM_DRAFT`, `LLM_CONFIRMED`, `LLM_EDITED`
  to provenance statuses
- Update `finalize_structured_analysis()` to accept `reviewer="llm:claude-sonnet-4-6"`

**Why seventh:** All agent pieces exist. This step is pure orchestration — the
"remove the human from the loop" moment.

**Deliverable:** `automation.py` with `auto_analyze()`. Integration test: given a
ticker with fixture data, produces a finalized overlay that passes all validation.

**Validates:** End-to-end: fixture data → analyst → validator → epistemic → finalized
overlay → `validate_structured_analysis()` passes → `apply_structured_analysis()` succeeds.

---

## Step 8: Scan Modes (Sector + Individual)

Restore the original scanner's two primary scan modes.

**What:**
- **Individual ticker scan:** `auto-scan TICKER [TICKER...]`
  - Runs `auto_analyze()` per ticker → deterministic pipeline → judge → report
  - Equivalent to original's `/scan-stocks CPS BABA HRL`

- **Sector scan:** `sector-scan "Consumer Defensive"`
  - Check sector hydration (hydrate if stale)
  - Pull all NYSE stocks in sector via FMP screener endpoint
  - Apply broken-chart filter (60%+ off ATH) — fast, API-only
  - Apply industry exclusion filter
  - Group survivors into clusters
  - Run `auto_analyze()` per cluster (parallel where possible)
  - Deterministic pipeline → judge → report

- **Full NYSE scan:** `full-scan` (stretch goal — high API cost)
  - Same as sector scan but across all sectors

- Report output: `data/scans/json/` + `data/scans/` (markdown rendered from JSON)
- Manifest file per scan run

**Why eighth:** Depends on the full automation flow (Step 7). This step adds the
scan-mode routing and batch orchestration.

**Deliverable:** CLI commands `auto-scan`, `sector-scan`. Tests confirming routing
logic and report output structure.

**Validates:** `auto-scan` with fixture data produces a valid report.
`sector-scan` with fixture data applies the correct screening funnel.

---

## Step 9: 20% CAGR Exception + Probability Anchoring Hardening

Handle the edge cases that currently require human judgment.

**What:**
- **20% CAGR exception panel:** When a candidate hits 20-29.9% CAGR with exception
  evidence (top-tier CEO + 6yr+ runway):
  - Analyst, Validator, and Epistemic Reviewer each independently vote approve/reject
  - Unanimous approval required to promote to ranked candidates
  - Full reasoning chain logged in provenance
  - If not unanimous → stays in `pending_review` bucket with dissenting rationale

- **Probability anchoring detection:**
  - If LLM analyst assigns exactly 60% base probability AND dominant risk type
    carries friction → flag `PROBABILITY_ANCHORING_SUSPECT`
  - Require analyst to justify why probability isn't 50% (structured field)
  - If justification is weak (validator judges) → force probability to 50%

- **Evidence quality scoring:**
  - Count concrete citations vs. vague references per candidate
  - If evidence quality score < threshold → add methodology note warning

**Why ninth:** These are the hardening rules that prevent the LLM pipeline from
gaming its own gates. Less urgent than the core flow but critical for trust.

**Deliverable:** Updated pipeline logic for exception panel. New probability
anchoring check. Tests for each edge case.

**Validates:** Fixture with 25% CAGR + exception evidence → panel vote logged.
Fixture with 60% probability + Regulatory/Political risk → anchoring flag raised.

---

## Step 10: Holding Review + Forward Return Workflow

Complete the Codex by implementing Step 8 (After the Buy).

**What:**
- New module: `holding_review.py`
- **Forward return refresh:** Given current price + original valuation inputs,
  recompute target price and forward CAGR
- **Thesis Integrity Checklist:** For each holding, structured assessment:
  - `improved`: what's better since last review
  - `degraded`: what's worse
  - `unchanged`: what hasn't moved
  - `invalidated`: any trigger from `invalidation_triggers` that fired
- **Sell trigger evaluation:**
  - Target reached + forward returns < 30% hurdle
  - Rapid rerating + forward returns < 10-15%/year
  - Thesis break (matched against `invalidation_triggers`)
- **Replacement gate computation:**
  - Gate A: Forward CAGR delta is meaningful (> 15 percentage points)
  - Gate B: Downside profile equal or better (flag if worse, require CAGR compensation)
- **Fresh-capital vs. legacy weight tracking:**
  - `current_weight` (actual portfolio %)
  - `fresh_capital_max_weight` (what sizing rules would assign today)
- CLI: `review-holding TICKER [TICKER...]`

**Why last:** This is post-buy monitoring — important for the full Codex but doesn't
block the core scan pipeline. Building it last means we have all the infrastructure
(caching, agents, scoring, sector knowledge) already in place.

**Deliverable:** `holding_review.py`, CLI command, schema for holding review output.
Tests with fixture holdings confirming sell trigger detection and replacement gate logic.

**Validates:** Fixture holding with compressed forward returns → sell trigger fires.
Fixture replacement candidate with better CAGR but worse downside → Gate B flags it.

---

## Build Sequence Summary

| Step | Module | Depends On | Key Outcome |
|------|--------|------------|-------------|
| 1 | FMP caching | — | API efficiency, dev iteration speed |
| 2 | Schema enrichments | — | Contract for all downstream work |
| 3 | Sector knowledge | Step 1 | Research quality, industry context |
| 4 | Claude analyst agent | Steps 1, 2, 3 | Core automation — fills overlays |
| 5 | Epistemic reviewer | Step 4 | Confidence assessment with evidence discipline |
| 6 | Red-team validator | Step 4 | Adversarial check, contradiction detection |
| 7 | Automated flow | Steps 4, 5, 6 | Remove human from loop |
| 8 | Scan modes | Step 7 | Sector scan + individual scan restored |
| 9 | Edge case hardening | Step 7 | 20% exception panel, anchoring detection |
| 10 | Holding review | Steps 7, 8 | Step 8 (After the Buy) complete |

Each step is independently testable and deployable. We evaluate after each step
before proceeding to the next.

---

*Plan created 2026-03-10. Methodology source of truth: kylers-system-codex/*
