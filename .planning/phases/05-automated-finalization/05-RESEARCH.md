# Phase 5: Automated Finalization - Research

**Researched:** 2026-03-10
**Domain:** Pipeline orchestration, provenance lifecycle, retry logic
**Confidence:** HIGH

## Summary

Phase 5 wires together all three Phase 4 agents (analyst, validator, epistemic reviewer) into a single `auto_analyze(ticker, config)` function that replaces the manual human review workflow. The core challenge is orchestration with retry logic: when the validator REJECTs an overlay, the analyst must re-run with validator objections injected, up to 2 retries. The finalized overlay must carry `LLM_CONFIRMED` provenance status and pass all existing pipeline validation identically to human-produced overlays.

All building blocks exist. The analyst (`analyst.py`), validator (`validator.py`), and epistemic reviewer (`epistemic_reviewer.py`) are implemented with transport injection for testability. The structured analysis module (`structured_analysis.py`) handles finalization but currently only accepts `HUMAN_CONFIRMED` and `HUMAN_EDITED` as final provenance statuses. The sector knowledge loader (`sector.py:load_sector_knowledge()`) is available for optional sector context injection.

**Primary recommendation:** Build a new `automation.py` module containing `auto_analyze()` that orchestrates existing components, extend `FINAL_PROVENANCE_STATUSES` to include `LLM_CONFIRMED`, and add `reviewer="llm:<model-id>"` acceptance to `finalize_structured_analysis()`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AUTO-01 | `auto_analyze(ticker, config)` orchestrates fetch -> sector -> analyst -> validator -> epistemic -> finalize | New `automation.py` module composing existing `live_scan.run_live_scan()`, `analyst.generate_llm_analysis_draft()`, `validator.validate_overlay()`, `epistemic_reviewer.epistemic_review()`, and `structured_analysis.finalize_structured_analysis()` |
| AUTO-02 | Rejected overlays retry with validator objections (max 2 retries) | Analyst `ClaudeAnalystClient.analyze()` accepts `sector_knowledge` kwarg; extend to also accept validator objections context. Retry loop in orchestrator with counter. |
| AUTO-03 | New provenance statuses: LLM_DRAFT, LLM_CONFIRMED, LLM_EDITED in structured_analysis.py | `LLM_DRAFT` already exists in `DRAFT_PROVENANCE_STATUSES`. Add `LLM_CONFIRMED` (and optionally `LLM_EDITED`) to `FINAL_PROVENANCE_STATUSES`. |
| AUTO-04 | `finalize_structured_analysis()` accepts `reviewer="llm:<model-id>"` | Currently validates `reviewer` is non-empty string and `final_status` is in `FINAL_PROVENANCE_STATUSES`. Extend status set; no signature change needed for reviewer format. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | (existing) | Claude API for analyst, validator, epistemic reviewer | Already used by all three agents |
| google-genai | (existing) | Gemini for sector hydration | Already used by sector.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest | stdlib | Test framework | All tests in project use unittest |
| dataclasses | stdlib | Result types | Pattern used throughout (LiveScanResult, ReviewPackageResult) |

No new dependencies required. Phase 5 is pure orchestration of existing components.

## Architecture Patterns

### Recommended Project Structure
```
src/edenfintech_scanner_bootstrap/
    automation.py          # NEW: auto_analyze() orchestrator
    structured_analysis.py # MODIFY: extend provenance statuses
    analyst.py             # MODIFY: accept validator objections in prompts
    config.py              # MODIFY: optional validator_model, reviewer_model config fields
    cli.py                 # MODIFY: add auto-analyze CLI command
```

### Pattern 1: Orchestrator with Transport Injection
**What:** `auto_analyze()` composes existing functions, each with injectable transports for testability
**When to use:** Always -- matches analyst.py, validator.py, epistemic_reviewer.py pattern
**Example:**
```python
@dataclass(frozen=True)
class AutoAnalyzeResult:
    ticker: str
    finalized_overlay: dict
    validator_verdict: dict
    epistemic_result: dict
    retries_used: int
    written_paths: dict[str, Path]

def auto_analyze(
    ticker: str,
    *,
    config: AppConfig,
    out_dir: Path,
    analyst_client: ClaudeAnalystClient | None = None,
    validator_client: RedTeamValidatorClient | None = None,
    epistemic_client: EpistemicReviewerClient | None = None,
    sector_knowledge: dict | None = None,
    max_retries: int = 2,
) -> AutoAnalyzeResult:
    ...
```

### Pattern 2: Retry Loop with Objection Injection
**What:** When validator returns REJECT, analyst re-runs with objections added to prompt context
**When to use:** AUTO-02 -- max 2 retries, then proceed to epistemic review regardless
**Example:**
```python
for attempt in range(max_retries + 1):
    draft = generate_llm_analysis_draft(merged_bundle, client=analyst_client,
                                         sector_knowledge=sector_knowledge,
                                         validator_objections=objections)
    validation = validate_overlay(draft_candidate, raw_candidate, client=validator_client)
    if validation["verdict"] == "APPROVE":
        break
    objections = validation["objections"]
# Always proceed to epistemic review after loop
```

### Pattern 3: Provenance Status Extension
**What:** Add `LLM_CONFIRMED` to `FINAL_PROVENANCE_STATUSES` so LLM-finalized overlays pass apply validation
**When to use:** AUTO-03, AUTO-04
**Critical:** `apply_structured_analysis()` checks `allow_machine_draft=False` which rejects DRAFT statuses, and `require_review_note_for_finalized=True`. LLM_CONFIRMED must be in the FINAL set for these checks to pass.

### Anti-Patterns to Avoid
- **Bypassing finalize_structured_analysis():** Do NOT build a separate finalization path. Use the existing function with extended status support.
- **Hardcoding model IDs:** Use `config.analyst_model` pattern. The `reviewer="llm:<model-id>"` format provides traceability without coupling.
- **Skipping epistemic review after validator rejection:** Even after max retries with REJECT, epistemic review must still run. It operates under information barrier and provides independent assessment.
- **Modifying transport signatures:** All three agents use `Callable[[dict], dict]` transport. Do not change this.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Raw bundle fetching | Custom fetch logic | `run_live_scan(stop_at="raw-bundle")` | Already handles FMP + Gemini + merge + template + draft |
| Schema validation | Manual field checks | `validate_structured_analysis()` | JSON Schema validation with proper error messages |
| Provenance validation | Manual provenance walk | `_validate_provenance_coverage()` | Handles all edge cases, duplicate detection, status checks |
| Sector knowledge loading | File reading | `load_sector_knowledge()` | Handles schema validation, path resolution, staleness |
| Evidence context extraction | Manual dict traversal | `_candidate_evidence_context()` | Canonical extraction with fingerprinting |

## Common Pitfalls

### Pitfall 1: Finalization Status Gate
**What goes wrong:** `finalize_structured_analysis()` currently rejects any `final_status` not in `FINAL_PROVENANCE_STATUSES = {"HUMAN_EDITED", "HUMAN_CONFIRMED"}`. Adding `LLM_CONFIRMED` without updating this set causes ValueError.
**Why it happens:** The set is hardcoded, not configurable.
**How to avoid:** Update `FINAL_PROVENANCE_STATUSES` to include `LLM_CONFIRMED`. Also update `DRAFT_PROVENANCE_STATUSES` if adding `LLM_EDITED`.
**Warning signs:** `ValueError: final_status must be one of: HUMAN_CONFIRMED, HUMAN_EDITED`

### Pitfall 2: apply_structured_analysis Rejects Draft Statuses
**What goes wrong:** After finalization, `apply_structured_analysis()` calls `_validate_provenance_coverage(allow_machine_draft=False)` which rejects anything in `DRAFT_PROVENANCE_STATUSES`. If provenance entries are not properly converted to `LLM_CONFIRMED`, apply fails.
**Why it happens:** The finalization function converts statuses in `DRAFT_PROVENANCE_STATUSES` to `final_status`. If `LLM_CONFIRMED` is not in `FINAL_PROVENANCE_STATUSES`, this conversion never happens.
**How to avoid:** Ensure `LLM_CONFIRMED` is added to `FINAL_PROVENANCE_STATUSES` BEFORE any auto_analyze code runs.

### Pitfall 3: Completion Status Must Be DRAFT Before Finalize
**What goes wrong:** `finalize_structured_analysis()` checks `completion_status != "DRAFT"` and raises. If the analyst retry loop somehow produces a non-DRAFT status, finalization fails.
**Why it happens:** `generate_llm_analysis_draft()` always sets `completion_status: "DRAFT"` -- this is safe as long as retries regenerate fresh drafts.
**How to avoid:** Never mutate `completion_status` during retry loop. Only `finalize_structured_analysis()` should set it to "FINALIZED".

### Pitfall 4: Epistemic Input Extraction From Overlay vs Raw
**What goes wrong:** `extract_epistemic_input()` expects an overlay candidate dict with `analysis_inputs` key. If passed raw candidate instead, fields are empty.
**Why it happens:** Mixing up overlay candidate (from analyst draft) with raw candidate (from merged bundle).
**How to avoid:** Always pass the structured candidate from the analyst draft to `extract_epistemic_input()`, not the raw candidate.

### Pitfall 5: Objection Injection Must Not Break Schema
**What goes wrong:** When injecting validator objections into the analyst re-run, if objections are added to the wrong location or format, constrained decoding fails.
**Why it happens:** The analyst system prompt has a specific structure. Objections should be added as additional context, not replacing existing prompt sections.
**How to avoid:** Add objections as a new section in the user prompt or system prompt, following the existing pattern of `_build_system_prompt(sector_knowledge)`.

## Code Examples

### Extending Provenance Statuses (AUTO-03)
```python
# In structured_analysis.py
FINAL_PROVENANCE_STATUSES = {"HUMAN_EDITED", "HUMAN_CONFIRMED", "LLM_CONFIRMED"}
DRAFT_PROVENANCE_STATUSES = {"MACHINE_DRAFT", "LLM_DRAFT"}
```
No other changes needed -- `finalize_structured_analysis()` already uses set membership checks.

### Accepting LLM Reviewer Format (AUTO-04)
```python
# finalize_structured_analysis() already accepts any non-empty string for reviewer
# Usage:
finalize_structured_analysis(
    draft_payload,
    reviewer="llm:claude-sonnet-4-5-20250514",
    final_status="LLM_CONFIRMED",
    note="Automated finalization after validator approval and epistemic review.",
)
```

### Analyst Retry with Objections (AUTO-02)
```python
# Extend _build_system_prompt or _build_user_prompt in analyst.py
def _build_user_prompt(raw_candidate, evidence_context, evidence_snippets,
                        validator_objections=None):
    parts = [...]  # existing parts
    if validator_objections:
        parts.extend([
            "",
            "VALIDATOR OBJECTIONS (from previous attempt -- you MUST address these):",
            json.dumps(validator_objections, indent=2),
            "",
            "Revise your analysis to address each objection explicitly.",
        ])
    return "\n".join(parts)
```

### Merging Epistemic Inputs Into Overlay (for finalization)
```python
# After epistemic review, merge PCS answers into the structured candidate
for candidate in draft["structured_candidates"]:
    if candidate["ticker"] == ticker:
        # Map epistemic result back to overlay epistemic_inputs format
        for key in ["q1_operational", "q2_regulatory", "q3_precedent",
                     "q4_nonbinary", "q5_macro"]:
            answer_data = epistemic_result[key]
            candidate["epistemic_inputs"][key] = {
                "answer": answer_data["answer"],
                "justification": answer_data["justification"],
                "evidence": answer_data["evidence"],
            }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Human fills __REQUIRED__ placeholders | LLM analyst fills all fields | Phase 3 | Human review still needed for finalization |
| Human writes review_notes | LLM analyst generates review_notes with evidence citations | Phase 3 | Human confirms rather than writes |
| Manual CLI finalize-structured-analysis | `auto_analyze()` single function call | Phase 5 (this phase) | Fully automated flow |

## Open Questions

1. **Should auto_analyze proceed to pipeline/report after finalization?**
   - What we know: Phase 6 (SCAN-01) adds `auto-scan` which runs auto_analyze -> pipeline -> judge -> report
   - What's unclear: Whether Phase 5 should stop at finalized overlay or include pipeline run
   - Recommendation: Stop at finalized overlay. Phase 6 adds the pipeline integration. This keeps phases cleanly separated.

2. **Should sector knowledge loading be automatic or explicit?**
   - What we know: `load_sector_knowledge()` requires prior hydration via `hydrate-sector` CLI
   - What's unclear: Should `auto_analyze()` attempt to load sector knowledge and silently proceed without it if not hydrated?
   - Recommendation: Try to load, warn if missing, proceed without. Sector context improves quality but is not required for the pipeline to function.

3. **What happens to epistemic provenance entries on retry?**
   - What we know: Analyst fills `epistemic_inputs` with placeholders or LLM content. Epistemic reviewer produces independent PCS answers.
   - What's unclear: Whether epistemic reviewer output should overwrite analyst's `epistemic_inputs` in the overlay before finalization.
   - Recommendation: Yes -- the epistemic reviewer's answers should replace the analyst's `epistemic_inputs` since the reviewer operates under information barrier and provides the authoritative PCS assessment.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | unittest (stdlib) |
| Config file | none (standard discovery) |
| Quick run command | `python -m unittest tests.test_automation -v` |
| Full suite command | `python -m unittest discover -s tests -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUTO-01 | auto_analyze orchestrates full flow | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_full_flow -v` | No -- Wave 0 |
| AUTO-01 | auto_analyze handles missing sector knowledge gracefully | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_no_sector_knowledge -v` | No -- Wave 0 |
| AUTO-02 | Rejected overlay triggers retry with objections | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_retry_on_reject -v` | No -- Wave 0 |
| AUTO-02 | Max 2 retries then proceed | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_max_retries_exceeded -v` | No -- Wave 0 |
| AUTO-03 | LLM_CONFIRMED in FINAL_PROVENANCE_STATUSES | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_confirmed_accepted -v` | No -- Wave 0 |
| AUTO-03 | LLM_DRAFT -> LLM_CONFIRMED transition | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_draft_to_llm_confirmed -v` | No -- Wave 0 |
| AUTO-04 | reviewer="llm:model-id" format accepted | unit | `python -m unittest tests.test_structured_analysis.TestFinalizeStructuredAnalysis.test_llm_reviewer_format -v` | No -- Wave 0 |
| AUTO-04 | Finalized overlay passes apply_structured_analysis | unit | `python -m unittest tests.test_automation.TestAutoAnalyze.test_finalized_overlay_applies -v` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest tests.test_automation -v && python -m unittest tests.test_structured_analysis -v`
- **Per wave merge:** `python -m unittest discover -s tests -v`
- **Phase gate:** Full suite green before verify

### Wave 0 Gaps
- [ ] `tests/test_automation.py` -- covers AUTO-01, AUTO-02, AUTO-04
- [ ] Extend `tests/test_structured_analysis.py` -- covers AUTO-03, AUTO-04 finalization paths
- [ ] Test fixtures with mock transports for all three agents (analyst, validator, epistemic)

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `structured_analysis.py` -- provenance status sets, finalization logic, apply validation
- Direct code inspection of `analyst.py` -- transport pattern, prompt building, draft generation
- Direct code inspection of `validator.py` -- contradiction detection, validate_overlay interface, APPROVE/REJECT verdicts
- Direct code inspection of `epistemic_reviewer.py` -- information barrier, EpistemicReviewInput, review interface
- Direct code inspection of `live_scan.py` -- existing orchestration pattern for fetch -> merge -> template -> draft
- Direct code inspection of `config.py` -- AppConfig pattern, require() method

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies, pure composition of existing modules
- Architecture: HIGH - All integration points are well-defined, interfaces are clear
- Pitfalls: HIGH - Code inspection reveals exact failure modes and validation gates

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable -- internal codebase, no external dependency changes)
