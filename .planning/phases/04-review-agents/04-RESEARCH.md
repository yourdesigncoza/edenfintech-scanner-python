# Phase 4: Review Agents - Research

**Researched:** 2026-03-10
**Domain:** Independent review layers (epistemic reviewer + red-team validator) for structured analysis overlays
**Confidence:** HIGH

## Summary

Phase 4 builds two independent review agents that challenge the analyst's structured analysis overlay before finalization. The epistemic reviewer operates under an enforced information barrier (no scores, probabilities, valuations, or numeric targets visible) and answers 5 PCS questions with sourced evidence. The red-team validator answers 5 Codex questions, cross-checks analyst assumptions against raw FMP data, and can REJECT or APPROVE the overlay.

The codebase already contains all the infrastructure these agents need. The epistemic review contract (`assets/contracts/epistemic_review.json`) defines exact inputs/outputs. The scoring module (`scoring.py`) already implements `epistemic_outcome()` which consumes PCS answers and produces confidence multipliers. The pipeline (`pipeline.py`) already calls `_validate_pcs_answers()` to validate the 5 PCS questions. The judge module (`judge.py`) demonstrates the transport-injectable LLM client pattern with structured output via JSON schema. The key insight is that both agents are LLM callers that receive restricted input views and produce structured output -- the same pattern as `judge.py` but with different information barriers and output schemas.

EPST-01 (information barrier) must be enforced at the function signature level, not just the prompt. The epistemic reviewer function must accept only the contract-specified inputs (ticker, industry, thesis_summary, key_risks, catalysts, moat_assessment, dominant_risk_type) and structurally cannot receive scores, probabilities, or valuations. VALD-02 (contradiction detection) requires deterministic cross-checking of analyst claims against raw FMP data (revenue trends, FCF margins, share counts) that can be implemented as pure Python logic without LLM involvement.

**Primary recommendation:** Build `epistemic_reviewer.py` and `validator.py` as two new modules following the transport-injectable pattern from `judge.py`. Enforce EPST-01 at the Python type level via a restricted dataclass input. Implement VALD-02 contradiction detection as deterministic Python logic comparing analyst overlay fields against FMP-derived data. Both agents use Anthropic constrained decoding for structured output.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EPST-01 | Code-enforced information barrier -- function signature excludes scores, probabilities, valuations | Restricted input dataclass containing only contract-specified fields; function does not accept raw bundle or overlay directly |
| EPST-02 | 5 PCS answers with justification + evidence per answer | Constrained decoding schema requires all 5 questions with answer/justification/evidence fields; matches existing `_validate_pcs_answers()` shape |
| EPST-03 | Evidence anchoring: each answer cites named source or declares NO_EVIDENCE | Output schema requires `evidence_source` field; post-validation checks for NO_EVIDENCE declarations |
| EPST-04 | WEAK_EVIDENCE detection for vague citations without concrete source | Deterministic Python check against a pattern list (missing source_title, generic phrases like "industry reports", "various sources") |
| EPST-05 | Additional -1 friction if >= 3 of 5 answers are NO_EVIDENCE | Pure Python logic in the reviewer result processing: count NO_EVIDENCE answers, add friction penalty |
| EPST-06 | PCS laundering detection (>80% evidence source overlap with analyst) | Compare evidence source sets between analyst provenance and reviewer citations; flag if overlap > 80% |
| VALD-01 | Answers 5 Codex red-team questions as structured output | Transport-injectable LLM call with constrained decoding schema for 5 questions with objection/evidence fields |
| VALD-02 | Contradiction detection: cross-check analyst assumptions against raw FMP data | Deterministic Python comparing overlay revenue/FCF/shares against FMP-derived actuals; flag discrepancies beyond threshold |
| VALD-03 | Can REJECT overlay with specific objections or APPROVE | Output schema with verdict enum [APPROVE, REJECT] + objections array; matches codex_final_judge pattern |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | 0.77.1 | Claude API for both review agents | Already installed; transport-injectable pattern proven in Phase 3 |
| Python stdlib `json` | 3.11+ | Schema loading, response handling | Project convention |
| Python stdlib `dataclasses` | 3.11+ | Restricted input types for information barrier | Type-level enforcement without external deps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib `hashlib` | 3.11+ | Evidence source fingerprinting for laundering detection | EPST-06 source overlap comparison |
| Python stdlib `re` | 3.11+ | WEAK_EVIDENCE pattern detection | EPST-04 vague citation matching |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Anthropic constrained decoding | OpenAI structured output | Project already uses Anthropic for analyst; consistency matters more than mixing providers |
| Restricted dataclass input | Prompt-only barrier | Prompt is not type-level enforcement; a developer could accidentally pass scores in kwargs |
| Deterministic contradiction detection (VALD-02) | LLM-based contradiction detection | Deterministic is reproducible and auditable; LLM adds variability to a verification step |

## Architecture Patterns

### New Module Structure
```
src/edenfintech_scanner_bootstrap/
    epistemic_reviewer.py   # NEW: information-barrier reviewer
    validator.py            # NEW: red-team validator + contradiction detector
    structured_analysis.py  # MODIFIED: add LLM_CONFIRMED, LLM_EDITED statuses if not done in Phase 3
    config.py               # MODIFIED: anthropic_api_key if not done in Phase 3
```

### Pattern 1: Type-Level Information Barrier (EPST-01)
**What:** A frozen dataclass that structurally cannot carry scores, probabilities, valuations, or numeric targets. The epistemic reviewer function accepts ONLY this type.
**When to use:** EPST-01 enforcement.
**Why this works:** Python type checkers (mypy, pyright) will flag any attempt to pass forbidden data. Even without type checking, the dataclass construction will reject unknown fields.

```python
# epistemic_reviewer.py
from dataclasses import dataclass

@dataclass(frozen=True)
class EpistemicReviewInput:
    """Restricted input for epistemic reviewer.

    This dataclass enforces the information barrier specified in the
    epistemic_review contract. It EXCLUDES:
    - scores, decision_score, total_score
    - probabilities, base_probability_pct, effective_probability
    - valuations, target_price, floor_price, base_case, worst_case
    - numeric targets, cagr_pct, downside_pct
    """
    ticker: str
    industry: str
    thesis_summary: str
    key_risks: list[str]
    catalysts: list[str]
    moat_assessment: str
    dominant_risk_type: str

def epistemic_review(
    review_input: EpistemicReviewInput,
    *,
    client: EpistemicReviewerClient | None = None,
) -> EpistemicReviewResult:
    """Run epistemic review with enforced information barrier.

    The function signature proves the barrier: review_input contains
    only qualitative analysis context, never numeric scores or valuations.
    """
    ...
```

### Pattern 2: Extract-Then-Review (Building the Restricted Input)
**What:** A helper function extracts the restricted input from the structured analysis overlay, provably dropping all numeric/scoring fields.
**When to use:** When the automation pipeline calls the epistemic reviewer.

```python
def extract_epistemic_input(overlay_candidate: dict) -> EpistemicReviewInput:
    """Extract restricted input from analyst overlay.

    Only copies fields listed in the epistemic_review contract.
    All numeric scores, probabilities, and valuations are dropped.
    """
    analysis = overlay_candidate.get("analysis_inputs", {})
    return EpistemicReviewInput(
        ticker=overlay_candidate["ticker"],
        industry=overlay_candidate.get("industry", ""),
        thesis_summary=analysis.get("thesis_summary", ""),
        key_risks=analysis.get("key_risks", []),
        catalysts=analysis.get("catalysts", []),
        moat_assessment=analysis.get("moat_assessment", ""),
        dominant_risk_type=analysis.get("dominant_risk_type", ""),
    )
```

### Pattern 3: Deterministic Contradiction Detection (VALD-02)
**What:** Pure Python comparison of analyst overlay claims against raw FMP data. No LLM involved.
**When to use:** VALD-02 -- must detect contradictions between analyst assumptions and factual FMP data.
**Why deterministic:** Contradiction detection is a verification step. Using an LLM for verification introduces the same calibration issues the system is designed to catch.

```python
def detect_contradictions(
    overlay_candidate: dict,
    raw_candidate: dict,
) -> list[dict]:
    """Compare analyst overlay assumptions against raw FMP data.

    Returns a list of contradiction findings, each with:
    - field: which overlay field is contradicted
    - claim: what the analyst assumed
    - actual: what FMP data shows
    - severity: HIGH/MEDIUM/LOW
    """
    contradictions = []
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    analysis = overlay_candidate.get("analysis_inputs", {})

    # Revenue growth claim vs FMP revenue trend
    # FCF margin claim vs FMP FCF history
    # Share count assumption vs FMP diluted shares
    # Catalyst timeline vs historical data
    ...
    return contradictions
```

### Pattern 4: Evidence Source Overlap Detection (EPST-06)
**What:** Compare evidence sources cited by the analyst (from provenance) against sources cited by the epistemic reviewer. Flag if overlap exceeds 80%.
**When to use:** EPST-06 laundering detection.

```python
def detect_pcs_laundering(
    analyst_provenance: list[dict],
    reviewer_citations: list[dict],
) -> tuple[bool, float]:
    """Detect PCS laundering -- reviewer parroting analyst evidence.

    Returns (is_laundering, overlap_pct).
    Laundering flagged when > 80% of reviewer evidence sources
    also appear in analyst provenance.
    """
    analyst_sources = {
        ref.get("summary", "").strip().lower()
        for prov in analyst_provenance
        for ref in prov.get("evidence_refs", [])
        if ref.get("summary", "").strip()
    }
    reviewer_sources = {
        cite.strip().lower()
        for cite in reviewer_citations
        if cite.strip()
    }
    if not reviewer_sources:
        return True, 100.0  # No independent evidence = laundering

    overlap = reviewer_sources & analyst_sources
    overlap_pct = (len(overlap) / len(reviewer_sources)) * 100
    return overlap_pct > 80.0, round(overlap_pct, 1)
```

### Pattern 5: WEAK_EVIDENCE Detection (EPST-04)
**What:** Deterministic pattern matching to flag vague citations.
**When to use:** EPST-04.

```python
WEAK_EVIDENCE_PATTERNS = [
    "industry reports",
    "various sources",
    "general consensus",
    "widely known",
    "common knowledge",
    "market observers",
    "analysts suggest",
    "reports indicate",
]

def is_weak_evidence(evidence_text: str) -> bool:
    """Check if evidence citation lacks concrete source."""
    lower = evidence_text.lower().strip()
    if not lower or lower == "no_evidence":
        return False  # NO_EVIDENCE is honest, not weak
    # Missing a concrete source identifier
    has_concrete = any(marker in lower for marker in [
        "10-k", "10-q", "earnings call", "sec filing",
        "annual report", "press release", "investor presentation",
    ])
    has_vague = any(pattern in lower for pattern in WEAK_EVIDENCE_PATTERNS)
    return has_vague or not has_concrete
```

### Anti-Patterns to Avoid
- **Passing the full structured overlay to the epistemic reviewer:** This defeats the information barrier. The reviewer must receive only the restricted dataclass fields, never the full overlay with its probability_inputs, base_case_assumptions, or worst_case_assumptions.
- **Using LLM for contradiction detection (VALD-02):** Contradictions between analyst claims and FMP data are factual, not interpretive. Deterministic comparison is more reliable and reproducible.
- **Relying on prompt-only information barrier:** A developer could accidentally add fields to the prompt context. The Python type system must enforce the barrier at the function signature level.
- **Having the reviewer see the analyst's evidence provenance before answering:** This would enable EPST-06 laundering. The reviewer should answer from its own evidence search first, then laundering detection compares after the fact.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PCS answer validation | New answer validator | Existing `_validate_pcs_answers()` in `pipeline.py` | Already validates shape, answer enum, evidence presence |
| Confidence calculation | New confidence calculator | Existing `epistemic_outcome()` in `scoring.py` | Already implements no-count to confidence, friction, multiplier logic |
| JSON schema validation | New schema checker | Existing `schemas.py:validate_instance()` | Handles $ref, enum, required; used project-wide |
| Contract enforcement | Ad-hoc checks | Load `assets/contracts/epistemic_review.json` and validate against it | Contract is the single source of truth |
| Structured LLM output | Manual JSON parsing + retries | Anthropic constrained decoding (`output_config.format`) | Token-level schema guarantee; proven in Phase 3 |
| Transport injection for tests | Mock library | Follow `judge.py` `JudgeTransport` / `GeminiTransport` callable pattern | Project convention; zero external test deps |

**Key insight:** The review agents are LLM callers with restricted views and structured output. The pipeline already handles everything downstream -- scoring, ranking, report assembly. The agents only need to produce PCS answers (epistemic) and a verdict + objections (validator).

## Common Pitfalls

### Pitfall 1: Information Barrier Leaking Through Evidence Context
**What goes wrong:** The `evidence_context` dict from `_candidate_evidence_context()` includes `fmp_derived` which has revenue, FCF margin, and share count data. If passed to the epistemic reviewer, the LLM could infer valuation.
**Why it happens:** The evidence context is designed for the analyst, not the reviewer.
**How to avoid:** The restricted dataclass contains only qualitative fields. The evidence_context is NOT passed to the epistemic reviewer. Only thesis_summary, catalysts, risks, moat_assessment, and dominant_risk_type go through.
**Warning signs:** The reviewer's PCS justifications referencing specific dollar amounts or FCF percentages.

### Pitfall 2: NO_EVIDENCE vs WEAK_EVIDENCE Conflation
**What goes wrong:** Treating NO_EVIDENCE as weak evidence or vice versa. NO_EVIDENCE is an honest declaration ("I found nothing"). WEAK_EVIDENCE is a dishonest or lazy citation ("industry reports suggest").
**Why it happens:** Both indicate low evidence quality, but they have different consequences. NO_EVIDENCE triggers friction (EPST-05). WEAK_EVIDENCE triggers a flag (EPST-04).
**How to avoid:** Check for NO_EVIDENCE exactly (string match) before running weak-evidence pattern detection. NO_EVIDENCE answers are never flagged as WEAK_EVIDENCE.
**Warning signs:** Friction being applied for WEAK_EVIDENCE answers or vice versa.

### Pitfall 3: Validator Seeing Post-Scoring Data
**What goes wrong:** The red-team validator should challenge the analyst's assumptions, not the pipeline's scores. If the validator sees decision_score or ranking, it might REJECT based on scoring disagreement rather than analytical contradiction.
**Why it happens:** The validator needs access to the analyst overlay AND raw FMP data, but must not see pipeline output.
**How to avoid:** The validator receives: (1) the analyst overlay (structured analysis draft), (2) the raw FMP data for cross-checking. It does NOT receive the pipeline scan report, scores, or ranking.

### Pitfall 4: PCS Laundering Detection False Positives
**What goes wrong:** Legitimate evidence overlap flagged as laundering. If both analyst and reviewer cite the same 10-K filing (which is expected), this is not laundering.
**Why it happens:** A company has limited public evidence sources. High overlap can be legitimate when the evidence base is small.
**How to avoid:** Track overlap at the claim level, not just source level. Two different claims from the same 10-K are independent evidence. Also consider total source count: if only 3 sources exist, 80% overlap is expected.
**Warning signs:** Every review being flagged as laundering for large-cap companies with limited recent filings.

### Pitfall 5: Contradiction Detection Threshold Too Tight
**What goes wrong:** Flagging minor numerical differences as contradictions (e.g., analyst says revenue $3.1B, FMP shows $3.05B due to rounding).
**Why it happens:** Financial data has legitimate rounding differences between sources.
**How to avoid:** Use meaningful thresholds: revenue claims contradicted if off by >10%, FCF margin if off by >3pp, share count if off by >5%. Direction matters more than magnitude for growth claims.

## Code Examples

### Epistemic Reviewer Output Schema (for Constrained Decoding)
```python
EPISTEMIC_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"],
    "additionalProperties": False,
    "properties": {
        key: {
            "type": "object",
            "required": ["answer", "justification", "evidence", "evidence_source"],
            "additionalProperties": False,
            "properties": {
                "answer": {"type": "string", "enum": ["Yes", "No"]},
                "justification": {"type": "string"},
                "evidence": {"type": "string"},
                "evidence_source": {
                    "type": "string",
                    # Either a concrete source name or "NO_EVIDENCE"
                },
            },
        }
        for key in ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]
    },
}
```

### Validator Output Schema
```python
VALIDATOR_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "questions", "objections"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question_id", "challenge", "evidence", "severity"],
                "additionalProperties": False,
                "properties": {
                    "question_id": {"type": "string"},
                    "challenge": {"type": "string"},
                    "evidence": {"type": "string"},
                    "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                },
            },
        },
        "objections": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}
```

### Contradiction Detection Logic
```python
def detect_contradictions(overlay_candidate: dict, raw_candidate: dict) -> list[dict]:
    contradictions = []
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    analysis = overlay_candidate.get("analysis_inputs", {})

    # Revenue growth claim vs FMP trend
    base_rev = analysis.get("base_case_assumptions", {}).get("revenue_b")
    latest_rev = derived.get("latest_revenue_b")
    trough_rev = derived.get("trough_revenue_b")
    if base_rev and latest_rev and base_rev > latest_rev * 1.5:
        contradictions.append({
            "field": "base_case_assumptions.revenue_b",
            "claim": f"Analyst assumes revenue ${base_rev}B",
            "actual": f"FMP latest revenue ${latest_rev}B (50%+ gap)",
            "severity": "HIGH",
        })

    # FCF margin claim vs FMP history
    base_fcf = analysis.get("base_case_assumptions", {}).get("fcf_margin_pct")
    latest_fcf = derived.get("latest_fcf_margin_pct")
    if base_fcf and latest_fcf and abs(base_fcf - latest_fcf) > 5.0:
        contradictions.append({
            "field": "base_case_assumptions.fcf_margin_pct",
            "claim": f"Analyst assumes FCF margin {base_fcf}%",
            "actual": f"FMP latest FCF margin {latest_fcf}% ({abs(base_fcf - latest_fcf):.1f}pp gap)",
            "severity": "MEDIUM" if abs(base_fcf - latest_fcf) <= 10 else "HIGH",
        })

    # Revenue growth direction: analyst claims growth but FMP shows decline
    if latest_rev and trough_rev and latest_rev < trough_rev:
        margin_gate = analysis.get("margin_trend_gate")
        if margin_gate != "PERMANENT_PASS":
            contradictions.append({
                "field": "analysis_inputs.margin_trend_gate",
                "claim": f"Analyst set margin_trend_gate to {margin_gate}",
                "actual": f"FMP shows latest revenue ${latest_rev}B below trough ${trough_rev}B -- declining",
                "severity": "HIGH",
            })

    return contradictions
```

### NO_EVIDENCE Friction Calculation (EPST-05)
```python
def calculate_no_evidence_friction(pcs_answers: dict) -> int:
    """Return additional friction penalty for NO_EVIDENCE answers.

    >= 3 NO_EVIDENCE answers triggers -1 additional friction.
    """
    no_evidence_count = sum(
        1 for q in pcs_answers.values()
        if isinstance(q, dict) and q.get("evidence_source", "").upper() == "NO_EVIDENCE"
    )
    return -1 if no_evidence_count >= 3 else 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Machine-drafted PCS answers in `field_generation.py` (keyword heuristics) | LLM epistemic reviewer with information barrier | This phase | Independent evidence-grounded PCS answers instead of mechanistic keyword mapping |
| No validator step; human manually checks overlay | Red-team validator with FMP contradiction detection | This phase | Systematic challenge layer before finalization |
| Prompt-level information barrier only | Type-level enforcement via restricted dataclass | This phase | Provable information barrier (EPST-01) |
| No evidence quality checks | WEAK_EVIDENCE detection + NO_EVIDENCE friction + laundering detection | This phase | Three-layer evidence quality assurance |

## Open Questions

1. **Should the epistemic reviewer use a different Claude model than the analyst?**
   - Architectural blindness (different model = different training biases) would strengthen independence.
   - Recommendation: Default to same model but make configurable via `EPISTEMIC_MODEL` env var. The information barrier is more important than model diversity for independence.

2. **Should VALD-02 contradiction detection run before or after the LLM validator call?**
   - Before: deterministic contradictions are included in the LLM context, helping it focus.
   - After: LLM gives independent assessment, then deterministic check adds its own findings.
   - Recommendation: Run deterministic contradictions FIRST and include them in the validator's context. This gives the LLM concrete evidence to anchor its red-team analysis.

3. **What constitutes a "5 Codex red-team questions" for VALD-01?**
   - The codex_final_judge contract answers compliance questions. The validator should ask thesis-challenging questions.
   - Recommendation: Define 5 fixed question templates that probe: (1) bull case falsifiability, (2) worst-case completeness, (3) catalyst plausibility, (4) competitive position durability, (5) management credibility. These are qualitative challenges, not compliance checks.

4. **How should the reviewer handle cases where it agrees with the analyst?**
   - Agreement is valid but must be independently justified. The reviewer should not just copy the analyst's reasoning.
   - Recommendation: Post-validation checks that the reviewer's justification text does not duplicate the analyst's thesis_summary or review_notes verbatim (in addition to EPST-06 source overlap).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Python unittest (stdlib) |
| Config file | None (unittest discovery) |
| Quick run command | `python -m unittest discover -s tests -v` |
| Full suite command | `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EPST-01 | EpistemicReviewInput dataclass rejects score/probability/valuation fields | unit | `python -m unittest tests.test_epistemic_reviewer.TestInformationBarrier.test_restricted_input_rejects_forbidden_fields -v` | Wave 0 |
| EPST-01 | epistemic_review() signature accepts only EpistemicReviewInput | unit | `python -m unittest tests.test_epistemic_reviewer.TestInformationBarrier.test_function_signature_type_check -v` | Wave 0 |
| EPST-02 | LLM produces 5 PCS answers with justification + evidence | unit | `python -m unittest tests.test_epistemic_reviewer.TestEpistemicReview.test_five_pcs_answers_complete -v` | Wave 0 |
| EPST-03 | Each answer has evidence_source or NO_EVIDENCE declaration | unit | `python -m unittest tests.test_epistemic_reviewer.TestEpistemicReview.test_evidence_anchoring -v` | Wave 0 |
| EPST-04 | WEAK_EVIDENCE detection flags vague citations | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_weak_evidence_detection -v` | Wave 0 |
| EPST-05 | >= 3 NO_EVIDENCE answers trigger -1 friction | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_no_evidence_friction -v` | Wave 0 |
| EPST-06 | PCS laundering detection flags > 80% source overlap | unit | `python -m unittest tests.test_epistemic_reviewer.TestEvidenceQuality.test_laundering_detection -v` | Wave 0 |
| VALD-01 | Validator answers 5 red-team questions as structured output | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_five_questions_answered -v` | Wave 0 |
| VALD-02 | Contradiction detection finds revenue/FCF/share discrepancies | unit | `python -m unittest tests.test_validator.TestContradictionDetection.test_revenue_contradiction -v` | Wave 0 |
| VALD-02 | Contradiction detection ignores within-threshold differences | unit | `python -m unittest tests.test_validator.TestContradictionDetection.test_within_threshold_no_flag -v` | Wave 0 |
| VALD-03 | Validator can REJECT with specific objections | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_reject_with_objections -v` | Wave 0 |
| VALD-03 | Validator can APPROVE with empty objections | unit | `python -m unittest tests.test_validator.TestRedTeamValidator.test_approve_clean -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest discover -s tests -v`
- **Per wave merge:** `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_epistemic_reviewer.py` -- covers EPST-01 through EPST-06
- [ ] `tests/test_validator.py` -- covers VALD-01 through VALD-03
- [ ] `tests/fixtures/reviewer/` -- fixture LLM response payloads for transport injection
- [ ] `tests/fixtures/validator/` -- fixture LLM response payloads for transport injection

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** -- `scoring.py` (epistemic_outcome, PCS_MULTIPLIERS, RISK_TYPE_FRICTION), `pipeline.py` (_validate_pcs_answers, epistemic review flow), `judge.py` (transport-injectable LLM pattern, structured output, validate_judge_result), `field_generation.py` (machine draft epistemic_inputs generation), `gemini.py` (FORBIDDEN_METHOD_KEYS information barrier pattern), `structured_analysis.py` (provenance system, REQUIRED_PROVENANCE_FIELDS)
- **assets/contracts/epistemic_review.json** -- Contract specifying exact inputs (ticker, industry, thesis_summary, key_risks, catalysts, moat_assessment, dominant_risk_type) and outputs (5 PCS answers, no_count, raw_confidence, adjusted_confidence, multiplier, effective_probability)
- **assets/contracts/codex_final_judge.json** -- Contract pattern for verdict/reroute structured output
- **Phase 3 Research** -- ClaudeAnalystClient transport-injectable pattern, constrained decoding, schema stripping approach

### Secondary (MEDIUM confidence)
- **strategy-rules.md** -- PCS questions defined in methodology, confidence scoring rules, risk-type friction rules
- **Anthropic SDK structured output support** -- `output_config.format` with `json_schema` type (documented in Phase 3 research)

### Tertiary (LOW confidence)
- **5 Codex red-team questions for VALD-01** -- Not formally defined anywhere yet. Recommendation in Open Questions section needs validation with the project owner.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all tools already proven in codebase (anthropic SDK, transport injection, contract validation)
- Architecture: HIGH -- extends proven patterns (judge.py for validator, gemini.py FORBIDDEN_METHOD_KEYS for barrier, scoring.py for epistemic math)
- Pitfalls: HIGH -- identified from codebase structure (information barrier leaking, evidence conflation, threshold sensitivity)
- VALD-01 question design: MEDIUM -- 5 question templates need formal definition

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable; builds on proven codebase patterns)
