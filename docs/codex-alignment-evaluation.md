# Codex Alignment Evaluation — Where We Are

Audit of how `edenfintech-scanner-python` maps to "Kyler's System Codex",
incorporating Gemini's Plan ALPHA evaluation, with concrete gap analysis and recommendations.

---

## 1. Codex-to-Pipeline Mapping

### What maps cleanly (implemented and aligned)

| Codex Step | Pipeline Implementation | Status |
|-----------|------------------------|--------|
| **01 - Finding Ideas** (broken chart, exclusions, catalyst presence) | `pipeline.py:_screen_candidate()` — 60% ATH gate, industry gates, double-plus potential | Solid |
| **02 - First Filter** (solvency, dilution, revenue, ROIC, valuation) | `pipeline.py:_step2_failure()` — 5-check PASS/BORDERLINE_PASS/FAIL | Solid |
| **03 - Deep Analysis** (peer comparison, quality ranking) | `pipeline.py` — `margin_trend_gate`, `final_cluster_status` (CLEAR_WINNER/CONDITIONAL_WINNER/ELIMINATED) | Solid |
| **05 - Valuation** (Revenue x FCF Margin x Multiple / Shares) | `scoring.py:valuation_target_price()`, `floor_price()`, `cagr_pct()` | Solid |
| **06 - The Decision** (scoring: downside 45%, probability 40%, CAGR 15%) | `scoring.py:decision_score()` with nonlinear downside penalty | Solid |
| **07 - Position Sizing** (hard breakpoints, CAGR < 30% = 0%, prob < 60% = 0%) | `scoring.py:score_to_size_band()`, `confidence_cap_band()` | Solid |
| **Epistemic PCS** (5 questions, risk-type friction, effective probability) | `scoring.py:epistemic_outcome()`, `pipeline.py:_validate_pcs_answers()` | Solid |
| **20% CAGR exception** (human gate) | `pipeline.py` lines 581-627 — routed to `pending_human_review` | Solid |
| **Provenance tracking** | `structured_analysis.py` — per-field MACHINE_DRAFT/HUMAN_CONFIRMED with review_notes | Solid |

### What's partially implemented (present but incomplete vs. Codex)

| Codex Concept | Current State | Gap |
|--------------|---------------|-----|
| **Catalyst stack classification** (Hard/Medium/Soft from `04-QUALITATIVE-DEEP-DIVE.md`) | Pipeline checks `catalyst_classification == VALID_CATALYST` (binary) | No confidence tiers. Codex says "base case must not depend on Soft catalysts alone" — this is not enforced |
| **Three-scenario valuation** (Bear/Base/Stretch from `05-VALUATION.md`) | Pipeline computes base case + worst case only | Missing stretch case. Codex says "decision relies on probability-weighted asymmetry, not base case alone" |
| **Invalidation triggers** (from `OPERATING-CHECKLIST.md`) | Not modeled | Codex requires explicit per-position triggers: "what breaks this thesis". The structured analysis overlay has no field for this |
| **Replacement threshold** (Gate A: CAGR delta, Gate B: downside profile from `06-THE-DECISION.md`) | `_build_current_holding_overlays()` generates overlays but doesn't compute replacement gates | Overlays are status-descriptive, not decision-making |
| **Red-Team prompts** (from `OPERATING-CHECKLIST.md`) | Gemini suggests a "Red-Team Validator" | Not implemented. The Codex specifies 5 exact red-team questions that should be answered before any large add |

### What's missing entirely

| Codex Concept | Where in Codex | Impact |
|--------------|----------------|--------|
| **Active Theme List / Cold Opportunity List** (`01-FINDING-IDEAS.md`) | Two-list pipeline management | No mechanism to track "interesting but no catalyst timing yet" candidates separately |
| **One-line decision memos** (`03-DEEP-ANALYSIS.md`) | "Why better than peer A / Why safer than peer B / What makes me wrong quickly" | These force clarity — currently no structured field requires this |
| **Problem/Fix map with evidence traction** (`04-QUALITATIVE-DEEP-DIVE.md`) | Pipeline has `issues_and_fixes` as a freeform string | Codex asks: "What broke? What exact actions? What evidence of traction?" — no structure enforces this |
| **Management evidence statuses** (`04-QUALITATIVE-DEEP-DIVE.md`) | Not in schema | ANNOUNCED_ONLY / ACTION_UNDERWAY / EARLY_RESULTS_VISIBLE / PROVEN (original scanner has this) |
| **Forward return refresh** (`08-AFTER-THE-BUY.md`) | Not in pipeline | No holding-review workflow in the Python scanner |
| **Thesis Integrity Checklist** (`08-AFTER-THE-BUY.md`) | Not in pipeline | Quarterly re-underwrite with improved/degraded/unchanged/invalidated categories |
| **Setup pattern matching** (`10-REAL-EXAMPLES.md`) | Not in pipeline | No mechanism to classify candidates against known setups (Solvency Scare, Quality Franchise, Narrative Discount, New Operator) |
| **Anti-pattern detection** (`10-REAL-EXAMPLES.md`) | Partial (no-catalyst rejection exists) | Missing: "thesis depending on multiple expansion only", "position sizing based on confidence language not downside math" |
| **Legacy vs. Fresh-Capital sizing distinction** (`07-POSITION-SIZING.md`) | Overlay records `existing_position_action` | But doesn't separately compute `fresh_capital_max_weight` vs. `current_weight` |

---

## 2. Epistemic Layer — Deep Evaluation

You're right that epistemic rigor is the edge. Here's where it stands:

### What's strong

The PCS framework is well-implemented:
- 5 questions with Yes/No answers, justification, and evidence fields
- Risk-type friction table with conditional overrides (Cyclical/Macro Q3 override, Regulatory/Political Q2 override)
- Confidence → multiplier mapping (5→1.00, 4→0.95, 3→0.85, 2→0.70, 1→0.50)
- Binary outcome override (Q4=No AND adjusted_confidence ≤ 3 → max 5%)
- Probability band normalization (50/60/70/80) before epistemic adjustments
- Effective probability as the binding input to scoring

### What needs strengthening

**1. Evidence anchoring is not machine-enforced.**

The epistemic reviewer agent (in the original scanner) requires each answer to cite a source or declare `NO_EVIDENCE`. The Python scanner validates that `evidence` is a non-empty string, but doesn't validate that it's actually a concrete citation vs. vague narrative.

For LLM-generated epistemic answers, this is the attack surface. An LLM will write "Based on the company's turnaround plan" instead of "NO_EVIDENCE" — and the pipeline won't catch it.

**Recommendation:** Add a `NO_EVIDENCE` detection rule. If the evidence field doesn't contain at least one of: a named source (10-K, earnings call, SEC filing), a named precedent company, a specific data point, or the literal `NO_EVIDENCE` — flag it as `WEAK_EVIDENCE` and apply an additional -1 friction penalty.

**2. Epistemic independence is currently structural but not enforced.**

The Python pipeline receives PCS answers as pre-populated fields in `epistemic_review`. There's no mechanism preventing whoever fills those fields from also seeing the probability and score. In the original scanner, this is enforced architecturally (the epistemic reviewer agent literally never receives those numbers).

**Recommendation:** When building the LLM analyst flow, the epistemic reviewer MUST be called with a stripped input that excludes: base_probability_pct, base_case assumptions, worst_case assumptions, and any score. This must be a hard contract in the code, not just a prompt instruction.

**3. No "PCS laundering" detection.**

The original scanner's epistemic reviewer warns about this: rationalizing confidence from the quality of the analyst's narrative rather than from independent evidence. The Python pipeline has no check for this.

**Recommendation:** Cross-check epistemic evidence refs against the analyst's evidence refs. If >80% of epistemic evidence cites the same sources as the analyst's thesis/catalyst/risk sections, flag as `POSSIBLE_PCS_LAUNDERING`.

**4. Threshold-hugging detection exists but is advisory only.**

`pipeline.py` passes through `threshold_proximity_warning` from the probability section, but doesn't act on it. The Codex's spirit is clear: if your base probability is right at 60% and any epistemic friction drops it below, the candidate should fail. This works. But there's no detection of probability being artificially anchored TO 60% to survive the gate.

**Recommendation:** If an LLM assigns exactly 60% base probability AND the dominant risk type carries friction, flag as `PROBABILITY_ANCHORING_SUSPECT` and require the LLM analyst to explicitly justify why probability isn't 50%.

---

## 3. Gemini's Suggestions — Assessment

### Agree with

**Catalyst stack schema enforcement.** Gemini's suggestion to add a `catalyst_stack` array with `HARD`/`MEDIUM`/`SOFT` enums directly implements what the Codex says in `04-QUALITATIVE-DEEP-DIVE.md`. This is a clear gap. The deterministic pipeline should auto-reject if zero HARD or MEDIUM catalysts exist.

**Invalidation triggers as a required field.** The Codex's `OPERATING-CHECKLIST.md` has a decision log template that requires 3 invalidation triggers per position. This should be a required field in the structured analysis overlay — and it feeds directly into the Step 8 holding review workflow (which doesn't exist yet in Python).

**Red-Team Validator as adversarial agent.** The Codex's 5 red-team prompts are specific and valuable:
1. What has to be true for this to fail badly?
2. Which assumption is most fragile?
3. What evidence in next 1-2 quarters can falsify the thesis?
4. If price dropped 30% tomorrow, would I add, hold, or exit and why?
5. Am I underwriting business improvement or just multiple expansion?

These should be structured fields in the validation output, not freeform.

### Partially agree with

**"Weaponize the framework against LLM optimism."** The framing is right — LLMs are natural optimists and will always find a bull case. But the solution isn't just adding more rejection rules. The deeper fix is:
- Require the LLM to generate the bear case FIRST, before the bull case
- Require the worst case to be generated before the base case
- Make the LLM articulate the "why not" before the "why"

This is a prompt engineering discipline, not a schema change.

### Disagree with

**"Gate B (downside profile equal or better) must be a strict numerical check for portfolio replacements."** This oversimplifies the Codex. Gate B in `06-THE-DECISION.md` says "downside profile is equal or better" — but the Codex also acknowledges that a materially higher CAGR can compensate for slightly worse downside (the backup-candidate retention logic in `03-DEEP-ANALYSIS.md`). A strict numerical gate would reject legitimate cases where a 35% downside candidate replaces a 30% downside holding but offers 50%+ CAGR vs. 15%.

**Recommendation:** Gate B should be a flag, not a hard reject. If downside is worse, require the CAGR delta to exceed a threshold (e.g., 15+ percentage points) to compensate.

---

## 4. Architecture Recommendations

### Priority 1: Schema enrichments (low effort, high alignment)

Add to `structured-analysis.schema.json`:
- `catalyst_stack[]` with `{type: "HARD"|"MEDIUM"|"SOFT", description: str, timeline: str}`
- `invalidation_triggers[]` with `{trigger: str, evidence_that_would_confirm: str}`
- `decision_memo` with `{better_than_peer: str, safer_than_peer: str, what_makes_wrong: str}`
- `issues_and_fixes[]` structured as `{issue: str, fix: str, evidence_status: "ANNOUNCED_ONLY"|"ACTION_UNDERWAY"|"EARLY_RESULTS_VISIBLE"|"PROVEN"}`
- `setup_pattern` enum: `"SOLVENCY_SCARE"|"QUALITY_FRANCHISE"|"NARRATIVE_DISCOUNT"|"NEW_OPERATOR"|"OTHER"`

### Priority 2: Pipeline hard gates (medium effort, high alignment)

Add deterministic checks in `pipeline.py`:
- Reject if `catalyst_stack` has zero HARD or MEDIUM entries
- Reject if `issues_and_fixes` has zero entries with status >= ACTION_UNDERWAY
- Flag (not reject) if `setup_pattern` is missing
- Flag `PROBABILITY_ANCHORING_SUSPECT` when base probability == 60% AND friction applies

### Priority 3: Epistemic enforcement (medium effort, critical for LLM autonomy)

- Hard contract: epistemic reviewer input MUST NOT include probability, base_case, worst_case, or score fields
- `WEAK_EVIDENCE` detection: flag evidence fields without concrete citations
- `PCS_LAUNDERING` detection: cross-reference epistemic evidence against analyst evidence sources
- `NO_EVIDENCE` count tracking: if >=3 of 5 PCS answers declare NO_EVIDENCE, apply additional -1 friction

### Priority 4: LLM agent layer (high effort, enables autonomy)

- Bear-case-first prompting discipline
- Red-team structured output (5 specific questions from Codex)
- Multi-provider decorrelation (analyst vs. validator vs. epistemic reviewer)
- Architecturally-enforced information barriers

### Priority 5: Step 8 — Holding review workflow (high effort, Codex completeness)

Currently missing entirely from the Python scanner:
- Forward return refresh (`calc-score.sh forward-return` equivalent)
- Thesis Integrity Checklist (improved/degraded/unchanged/invalidated)
- Sell trigger evaluation (target reached, rapid rerating, thesis break)
- Replacement gate computation (Gate A: CAGR delta, Gate B: downside profile)
- Fresh-capital vs. legacy weight tracking

---

## 5. Summary

**Where we are:** The Python scanner has a strong deterministic core. The scoring math, screening gates, epistemic PCS framework, provenance tracking, and pipeline routing are all well-implemented and largely aligned with the Codex.

**Where we're not:** The qualitative depth demanded by the Codex — catalyst confidence tiers, invalidation triggers, decision memos, problem/fix evidence tracking, setup pattern matching, and the full Step 8 holding review — is either missing or reduced to freeform strings where the Codex expects structured, enforceable data.

**The epistemic layer is the moat.** You're right to emphasize this. The PCS math is solid, but the evidence-anchoring and independence enforcement that makes it trustworthy under LLM autonomy needs hardening. The original scanner's architectural blindness pattern is the gold standard — the Python scanner needs to enforce this as a code-level contract, not just a convention.

**Gemini's evaluation is directionally correct** but slightly over-indexes on adding more rejection gates. The Codex's real edge isn't more rules — it's better evidence discipline. The system that catches "I'm rationalizing a bull case from a well-written narrative" beats the system that has 50 hard gates but doesn't question evidence quality.

---

*Evaluation produced 2026-03-10. Based on kylers-system-codex/, edenfintech-scanner-python source,
plan-alpha-analysis.md, and gemini-plan-alpha-evaluation.md.*
