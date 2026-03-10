# Phase 3: Claude Analyst Agent - Research

**Researched:** 2026-03-10
**Domain:** LLM-powered structured analysis generation using Anthropic Claude API with constrained decoding
**Confidence:** HIGH

## Summary

Phase 3 replaces the deterministic `field_generation.py` machine draft with a Claude-powered analyst agent that fills all structured analysis fields from raw evidence bundles and sector knowledge. The existing codebase already has the complete pattern: `generate_structured_analysis_draft()` takes a raw bundle and produces a structured analysis overlay with per-field provenance. The Claude agent follows this exact interface but produces higher-quality, evidence-grounded outputs with `LLM_DRAFT` provenance status instead of `MACHINE_DRAFT`.

The Anthropic Python SDK (v0.77.1, already installed) supports constrained decoding via `output_config.format` with `json_schema` type. This guarantees the agent output matches the structured analysis schema at the token generation level -- the model literally cannot produce schema-violating output. The SDK also supports Pydantic models via `client.messages.parse()` for convenience.

The key architectural decision is to build a new `analyst.py` module that mirrors `field_generation.py`'s interface: takes a raw bundle (plus optional sector knowledge), calls Claude with the evidence context and methodology rules in the system prompt, receives structured output via constrained decoding, and wraps the result with `LLM_DRAFT` provenance entries and review notes citing specific evidence sources. The existing `structured_analysis.py` validation, finalization, and apply flows remain unchanged.

**Primary recommendation:** Build `analyst.py` as a new module with `ClaudeAnalystClient` class and `generate_llm_analysis_draft()` function. Use `output_config.format` with the structured analysis JSON schema for constrained decoding. Add `LLM_DRAFT` as a new provenance status to `structured_analysis.py`. Follow the existing transport-injection pattern from `gemini.py` and `judge.py` for testability.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AGNT-01 | Claude analyst agent fills all `__REQUIRED__` placeholders from raw bundle + sector knowledge | New `analyst.py` module with `generate_llm_analysis_draft()` that sends raw bundle evidence + sector knowledge as context to Claude, receives structured analysis overlay via constrained decoding |
| AGNT-02 | Provenance status `LLM_DRAFT` distinct from `MACHINE_DRAFT` | Add `LLM_DRAFT` to provenance status enum in schema and to `FINAL_PROVENANCE_STATUSES` handling in `structured_analysis.py` |
| AGNT-03 | Every field has `review_note` citing specific evidence | Prompt instructs Claude to include specific source citations from the raw bundle evidence; post-processing validates every provenance entry has a non-empty `review_note` referencing a named source |
| AGNT-04 | Worst case generated BEFORE base case, bear thesis BEFORE bull | Prompt ordering discipline: system prompt explicitly instructs worst-case-first, bear-first; output schema orders worst_case before base_case; post-validation checks field ordering in JSON output |
| AGNT-05 | Output validates against structured-analysis schema via constrained decoding | Anthropic `output_config.format` with `json_schema` type compiled from `structured-analysis.schema.json`; SDK-level constrained decoding guarantees schema compliance at token generation |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | 0.77.1 | Claude API client with structured outputs | Already installed in project environment; official SDK |
| Python stdlib `json` | 3.11+ | Schema loading, response handling | Project convention |
| Python stdlib `pathlib` | 3.11+ | File paths | Project convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic` | (transitive from anthropic) | Optional: Pydantic models for `client.messages.parse()` | If type-safe parsed output is preferred over raw JSON |
| Python stdlib `hashlib` | 3.11+ | Fingerprint continuity | Already used in `structured_analysis.py` |
| Python stdlib `copy` | 3.11+ | Deep copy for overlay assembly | Already used in `structured_analysis.py` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Anthropic `output_config` constrained decoding | Prompt-only JSON + post-validation | No schema guarantee at token level; may produce invalid JSON requiring retry loops |
| Raw `json_schema` in `output_config` | Pydantic `output_format` in `messages.parse()` | Pydantic adds type safety but the project avoids external deps in core pipeline; raw JSON schema matches existing `schemas.py` pattern |
| Direct Anthropic SDK | `instructor` library for Anthropic | External dep; project already has the validation infrastructure in `schemas.py` |

## Architecture Patterns

### New Module Structure
```
src/edenfintech_scanner_bootstrap/
    analyst.py              # NEW: ClaudeAnalystClient + generate_llm_analysis_draft()
    structured_analysis.py  # MODIFIED: add LLM_DRAFT status
    config.py               # MODIFIED: add anthropic_api_key to AppConfig
```

### Pattern 1: Transport-Injectable Client (matches gemini.py / judge.py)
**What:** A `ClaudeAnalystClient` class with injectable transport for testing.
**When to use:** Any module that calls an external LLM API.
**Why this pattern:** `GeminiClient` and `codex_judge` both use this pattern. Transport injection lets tests provide fixture responses without HTTP calls.

```python
# analyst.py
from typing import Callable

AnalystTransport = Callable[[dict], dict]  # request_payload -> response_payload

class ClaudeAnalystClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-sonnet-4-5-20250514",
        transport: AnalystTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._default_transport

    def _default_transport(self, request_payload: dict) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(**request_payload)
        return response.model_dump()

    def analyze(
        self,
        raw_candidate: dict,
        *,
        sector_knowledge: dict | None = None,
    ) -> dict:
        # Build prompt, call transport, parse response
        ...
```

### Pattern 2: Two-Phase Prompt (Worst-Case-First Discipline)
**What:** The system prompt instructs Claude to reason about worst case BEFORE base case, and bear thesis BEFORE bull thesis.
**When to use:** AGNT-04 requirement -- ordering discipline.
**Key insight:** Constrained decoding guarantees schema shape but not field ordering within the JSON object. The prompt must enforce reasoning order, and post-processing must verify that the `worst_case_assumptions` section appears before `base_case_assumptions` in the raw response text.

```python
SYSTEM_PROMPT = """You are the EdenFinTech Analyst Agent. Your task is to fill a structured
analysis overlay from raw evidence.

CRITICAL ORDERING RULES:
1. Generate worst_case_assumptions BEFORE base_case_assumptions
2. Generate bear thesis BEFORE bull thesis in thesis_summary
3. This ordering ensures conservative anchoring -- optimism must overcome pessimism, not the reverse

EVIDENCE CITATION RULES:
- Every field must cite a specific named source from the raw bundle
- Use exact source_title values from the evidence (e.g., "10-K", "Earnings call", "Industry note")
- If no evidence supports a field, state "NO_EVIDENCE: [reason]" -- do not fabricate citations

PROVENANCE RULES:
- You are generating an LLM_DRAFT, not a final analysis
- Your review_note for each field MUST cite the specific evidence source and explain your reasoning
"""
```

### Pattern 3: Schema Subsetting for Constrained Decoding
**What:** Extract the candidate-level analysis schema from the full `structured-analysis.schema.json` to use as the constrained decoding schema. The full overlay envelope (title, scan_date, generation_metadata, etc.) is assembled in Python code, not by the LLM.
**When to use:** The LLM should only generate the candidate-level analysis fields, not the envelope metadata.
**Why:** Keeps the constrained decoding schema focused on the analytical content. The envelope is deterministic and should not consume LLM tokens.

```python
def _build_candidate_output_schema() -> dict:
    """Build the JSON schema for a single candidate's analysis output.

    This is a SUBSET of the full structured-analysis schema, containing
    only the fields the LLM should generate:
    - screening_inputs
    - analysis_inputs (including enriched Codex fields)
    - epistemic_inputs
    - field_provenance (review_note per field)
    """
    full_schema = load_json(structured_analysis_schema_path())
    # Extract definitions and candidate-level properties
    # Remove unsupported constraints (minLength, minimum, maximum)
    # for constrained decoding compatibility
    # Add additionalProperties: false to all objects
    ...
```

**Important:** The Anthropic constrained decoding does NOT support `minLength`, `minimum`, `maximum`, or `minItems` constraints. These must be stripped from the schema sent to Claude and validated post-response using the existing `schemas.py` validator.

### Pattern 4: Post-Processing Validation Pipeline
**What:** After receiving the constrained-decoded response, run a validation pipeline that checks requirements beyond what the JSON schema can express.
**When to use:** Every analyst invocation.

```python
def _post_validate(candidate_output: dict, raw_candidate: dict) -> list[str]:
    """Validate LLM output beyond schema compliance."""
    issues = []

    # Check all __REQUIRED__ placeholders replaced (AGNT-01)
    if _contains_placeholder(candidate_output):
        issues.append("Output still contains __REQUIRED__ placeholders")

    # Check every provenance entry has review_note (AGNT-03)
    for prov in candidate_output.get("field_provenance", []):
        if not prov.get("review_note", "").strip():
            issues.append(f"Missing review_note for {prov.get('field_path')}")

    # Validate against full schema with constraints (AGNT-05)
    validate_structured_analysis(full_overlay)

    return issues
```

### Anti-Patterns to Avoid
- **Sending the entire raw bundle as-is to Claude:** The raw bundle contains FMP financial statements that can be very large. Extract relevant derived data and evidence snippets, not raw financial arrays.
- **Relying on JSON field ordering for AGNT-04:** JSON objects are unordered by spec. Use prompt-level reasoning ordering plus post-validation of the response text (before JSON parsing) to verify worst-case appeared first.
- **Having the LLM generate the full overlay envelope:** The title, scan_date, generation_metadata, source_bundle, etc. are deterministic. Only the candidate analysis content should come from the LLM.
- **Using `MACHINE_DRAFT` status for LLM outputs:** AGNT-02 explicitly requires `LLM_DRAFT` as a distinct status. Do not reuse the existing `MACHINE_DRAFT`.
- **Letting the LLM see pipeline decisions:** Following the existing `FORBIDDEN_METHOD_KEYS` pattern from `gemini.py`, the analyst should see evidence but NOT screening verdicts, pipeline decisions, or scores from prior runs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema compliance | Post-hoc JSON repair/retry loops | Anthropic constrained decoding (`output_config.format`) | Token-level guarantee; no retries needed for schema shape |
| Schema validation | New validator | Existing `schemas.py:validate_instance()` | Already handles `$ref`, `enum`, `required`; validates full constraints post-response |
| Provenance tracking | New provenance system | Existing `REQUIRED_PROVENANCE_FIELDS` + `_validate_provenance_coverage()` | Already implements per-field provenance with coverage checks |
| Overlay assembly | New overlay builder | Existing `structured_analysis_template()` for envelope + `validate_structured_analysis()` | The envelope structure is already proven |
| Evidence extraction | Custom raw bundle parser | Existing `_candidate_evidence_context()` from `structured_analysis.py` | Already extracts the relevant derived/evidence data from raw bundles |

**Key insight:** The analyst agent does NOT replace the pipeline infrastructure. It replaces only the field-filling logic currently in `field_generation.py`. All validation, finalization, and apply flows remain unchanged.

## Common Pitfalls

### Pitfall 1: Schema Constraint Stripping for Constrained Decoding
**What goes wrong:** Sending the full `structured-analysis.schema.json` to Anthropic's constrained decoding fails because it contains `minLength`, `minimum`, `maximum`, and `minItems` constraints that the API does not support.
**Why it happens:** The Anthropic constrained decoding supports a subset of JSON Schema. Numeric/string constraints are not supported at the token generation level.
**How to avoid:** Strip unsupported constraints from the schema before sending to the API. Apply full constraint validation post-response using `schemas.py:validate_instance()`.
**Warning signs:** API error about unsupported schema features; 400 status codes.

### Pitfall 2: Provenance Status Enum Not Updated in Schema
**What goes wrong:** Adding `LLM_DRAFT` to Python code but forgetting to add it to the `field_provenance.status.enum` in `structured-analysis.schema.json` causes schema validation to reject valid LLM-drafted overlays.
**Why it happens:** The status enum is defined in both the JSON schema and the Python code (`FINAL_PROVENANCE_STATUSES`).
**How to avoid:** Update the enum in `structured-analysis.schema.json` AND the Python constants in `structured_analysis.py` in the same commit.

### Pitfall 3: Token Budget Overflow
**What goes wrong:** The raw bundle evidence context + methodology rules + sector knowledge exceeds Claude's context window, or the output is truncated.
**Why it happens:** Raw bundles can be large (financial statements, multiple evidence arrays), and the structured analysis output itself is substantial.
**How to avoid:** (1) Extract only relevant derived data and evidence snippets, not raw financial statement arrays. (2) Set `max_tokens` to at least 8192 for the output. (3) Use the evidence_context summary from `_candidate_evidence_context()` rather than the full raw candidate.
**Warning signs:** `stop_reason: max_tokens` in the API response.

### Pitfall 4: Evidence Hallucination
**What goes wrong:** Claude invents source citations that don't exist in the raw bundle.
**Why it happens:** LLMs can fabricate plausible-sounding sources.
**How to avoid:** Post-validate that every `source_title` in review notes matches an actual `source_title` from the raw bundle's evidence arrays. Build a set of valid source titles from the input and check each review_note against it.
**Warning signs:** Review notes citing sources not present in the evidence context.

### Pitfall 5: JSON Object Key Ordering for AGNT-04
**What goes wrong:** Python's `json.loads()` preserves insertion order but JSON spec says objects are unordered. Relying on key position in the parsed dict is fragile.
**Why it happens:** AGNT-04 requires worst case BEFORE base case in the output.
**How to avoid:** Two strategies: (1) Validate ordering in the raw response text (before JSON parsing) by checking that "worst_case" substring appears before "base_case". (2) Use the prompt to enforce reasoning order and trust the constrained decoder's sequential generation. Strategy 1 is the safety net.

### Pitfall 6: Enriched Codex Fields Not in Provenance
**What goes wrong:** Phase 1 adds `catalyst_stack`, `invalidation_triggers`, `decision_memo`, `issues_and_fixes`, `setup_pattern`, `stretch_case_assumptions` to the schema. If the provenance `REQUIRED_PROVENANCE_FIELDS` list is not updated to include these new field paths, the analyst overlay will pass validation but lack provenance for enriched fields.
**Why it happens:** `REQUIRED_PROVENANCE_FIELDS` in `structured_analysis.py` is a manually maintained list.
**How to avoid:** Phase 3 must add the new enriched field paths to `REQUIRED_PROVENANCE_FIELDS`:
```python
# New entries needed:
"analysis_inputs.catalyst_stack",
"analysis_inputs.invalidation_triggers",
"analysis_inputs.decision_memo",
"analysis_inputs.issues_and_fixes",
"analysis_inputs.setup_pattern",
"analysis_inputs.stretch_case_assumptions",
```

## Code Examples

### Building the Constrained Decoding Schema
```python
# analyst.py
import json
from .assets import load_json, structured_analysis_schema_path

def _strip_unsupported_constraints(schema: dict) -> dict:
    """Remove constraints not supported by Anthropic constrained decoding."""
    result = dict(schema)
    for key in ("minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"):
        result.pop(key, None)
    if "properties" in result:
        result["properties"] = {
            k: _strip_unsupported_constraints(v)
            for k, v in result["properties"].items()
        }
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _strip_unsupported_constraints(result["items"])
    # Add additionalProperties: false to all objects
    if result.get("type") == "object":
        result["additionalProperties"] = False
    # Recursively handle $ref targets in definitions
    for def_key in ("definitions", "$defs"):
        if def_key in result:
            result[def_key] = {
                k: _strip_unsupported_constraints(v)
                for k, v in result[def_key].items()
            }
    return result

def _build_candidate_output_schema() -> dict:
    """Build constrained decoding schema for a single candidate's analysis."""
    full_schema = load_json(structured_analysis_schema_path())
    definitions = full_schema.get("definitions", {})

    # Build a focused schema for what the LLM generates per candidate
    candidate_schema = {
        "type": "object",
        "required": [
            "screening_inputs",
            "analysis_inputs",
            "epistemic_inputs",
            "field_provenance",
        ],
        "additionalProperties": False,
        "properties": {
            "screening_inputs": definitions["structured_candidate"]["properties"]["screening_inputs"],
            "analysis_inputs": definitions["analysis_inputs"],
            "epistemic_inputs": definitions["structured_candidate"]["properties"]["epistemic_inputs"],
            "field_provenance": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["field_path", "status", "rationale", "review_note", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "field_path": {"type": "string"},
                        "status": {"type": "string", "enum": ["LLM_DRAFT"]},
                        "rationale": {"type": "string"},
                        "review_note": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["kind", "path", "summary"],
                                "additionalProperties": False,
                                "properties": {
                                    "kind": {"type": "string"},
                                    "path": {"type": "string"},
                                    "summary": {"type": "string"},
                                }
                            }
                        }
                    }
                }
            },
        },
        "definitions": {k: _strip_unsupported_constraints(v) for k, v in definitions.items()},
    }
    return _strip_unsupported_constraints(candidate_schema)
```

### Calling Claude with Constrained Decoding
```python
def _default_transport(self, request_payload: dict) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=self.api_key)
    response = client.messages.create(**request_payload)
    # response.content[0].text is guaranteed valid JSON matching schema
    return {"text": response.content[0].text, "stop_reason": response.stop_reason}

def analyze(self, raw_candidate: dict, *, sector_knowledge: dict | None = None) -> dict:
    evidence_context = _candidate_evidence_context(raw_candidate)
    evidence_snippets = _extract_evidence_snippets(raw_candidate)

    system_prompt = _build_system_prompt(sector_knowledge)
    user_prompt = _build_user_prompt(raw_candidate, evidence_context, evidence_snippets)

    request_payload = {
        "model": self.model,
        "max_tokens": 8192,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": _build_candidate_output_schema(),
            }
        },
    }

    response = self.transport(request_payload)
    candidate_output = json.loads(response["text"])
    return candidate_output
```

### Adding LLM_DRAFT to Provenance System
```python
# In structured_analysis.py, update the schema enum:
# structured-analysis.schema.json field_provenance.status.enum:
#   ["MACHINE_DRAFT", "LLM_DRAFT", "HUMAN_EDITED", "HUMAN_CONFIRMED"]

# In structured_analysis.py, update validation:
FINAL_PROVENANCE_STATUSES = {"HUMAN_EDITED", "HUMAN_CONFIRMED"}
DRAFT_PROVENANCE_STATUSES = {"MACHINE_DRAFT", "LLM_DRAFT"}
# _validate_provenance_coverage already checks against MACHINE_DRAFT;
# extend to also recognize LLM_DRAFT as a draft status

# In finalize_structured_analysis, update the draft-to-final transition:
for item in candidate["field_provenance"]:
    if item.get("status") in DRAFT_PROVENANCE_STATUSES:
        review_note = item.get("review_note")
        if not isinstance(review_note, str) or not review_note.strip():
            raise ValueError(...)
        item["status"] = final_status
        converted_fields += 1
```

### Assembling the Full Overlay from LLM Output
```python
def generate_llm_analysis_draft(
    raw_bundle: dict,
    *,
    client: ClaudeAnalystClient,
    sector_knowledge: dict | None = None,
) -> dict:
    """Generate a structured analysis draft using Claude analyst agent.

    Returns a complete structured analysis overlay in the same format
    as field_generation.generate_structured_analysis_draft(), but with
    LLM_DRAFT provenance status and evidence-grounded review_notes.
    """
    raw_candidates = raw_bundle.get("raw_candidates", [])
    structured_candidates = []

    for raw_candidate in raw_candidates:
        # LLM generates analysis content
        candidate_output = client.analyze(raw_candidate, sector_knowledge=sector_knowledge)

        # Wrap with envelope fields (deterministic, not LLM-generated)
        evidence_context = _candidate_evidence_context(raw_candidate)
        structured_candidates.append({
            "ticker": raw_candidate["ticker"],
            "evidence_context": evidence_context,
            "evidence_fingerprint": _fingerprint(evidence_context),
            "field_provenance": candidate_output["field_provenance"],
            "screening_inputs": candidate_output["screening_inputs"],
            "analysis_inputs": candidate_output["analysis_inputs"],
            "epistemic_inputs": candidate_output["epistemic_inputs"],
        })

    # Assemble full overlay envelope (same as field_generation.py)
    payload = {
        "title": f"LLM Analyst Draft - {raw_bundle.get('title', 'EdenFinTech')}",
        "scan_date": raw_bundle.get("scan_date"),
        "version": raw_bundle.get("version", "v1"),
        "scan_parameters": raw_bundle.get("scan_parameters", {}),
        "source_bundle": {
            "scan_date": raw_bundle.get("scan_date"),
            "scan_mode": raw_bundle.get("scan_parameters", {}).get("scan_mode"),
            "focus": raw_bundle.get("scan_parameters", {}).get("focus"),
            "api": raw_bundle.get("scan_parameters", {}).get("api"),
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
        },
        "completion_status": "DRAFT",
        "completion_note": "LLM-generated draft. Human review required before finalization.",
        "generation_metadata": {
            "source": "analyst.py",
            "generator_version": "v1",
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
            "notes": ["LLM_DRAFT fields require human review_note confirmation."],
        },
        "methodology_notes": [
            "This overlay was generated by the Claude analyst agent from raw evidence.",
            "All fields carry LLM_DRAFT provenance status pending human review.",
        ],
        "structured_candidates": structured_candidates,
    }

    # Full schema validation (with constraints the LLM schema didn't enforce)
    validate_structured_analysis(payload)
    return payload
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `field_generation.py` machine draft (keyword matching + heuristics) | Claude analyst agent with constrained decoding | This phase | Evidence-grounded analysis instead of keyword heuristics |
| `MACHINE_DRAFT` only provenance status for drafts | `MACHINE_DRAFT` + `LLM_DRAFT` as distinct draft statuses | This phase | Can distinguish machine heuristic vs LLM-generated fields in audit trail |
| No review_notes in machine draft | Every LLM field has review_note citing specific evidence | This phase | Removes the manual review note step for most fields |
| Anthropic SDK beta header for structured outputs | GA: `output_config.format` (no beta header needed) | Late 2025 | Stable API surface; constrained decoding guarantees schema compliance |

## Open Questions

1. **Which Claude model to use?**
   - Claude Sonnet 4.5 is the cost-effective default for structured output tasks. Claude Opus 4.6 would be higher quality but 5x cost.
   - Recommendation: Default to `claude-sonnet-4-5-20250514`. Make configurable via `ANALYST_MODEL` env var so the user can upgrade per-run.

2. **Should sector knowledge be mandatory or optional?**
   - Phase 2 builds sector knowledge but may not exist for every sector at runtime. The analyst should work without it (using only raw bundle evidence) but produce better output with it.
   - Recommendation: Optional parameter. When absent, the prompt notes that sector context is unavailable and the LLM should rely solely on the raw bundle.

3. **How should AGNT-04 ordering be verified?**
   - JSON objects are unordered by spec. Two options: (A) verify in raw response text before parsing, (B) trust the prompt ordering + sequential token generation.
   - Recommendation: Use both -- raw text check as a post-validation assertion, plus prompt-level instruction.

4. **Should `field_generation.py` be deprecated or kept as fallback?**
   - The machine draft is zero-cost and instant. It serves as a useful baseline and fallback when Claude API is unavailable.
   - Recommendation: Keep `field_generation.py` as-is. `analyst.py` is an alternative generator, not a replacement. `live_scan.py` should support choosing which generator to use.

5. **How to handle API key configuration?**
   - The `anthropic` SDK is already installed but no `ANTHROPIC_API_KEY` exists in `.env.example` or `AppConfig`.
   - Recommendation: Add `anthropic_api_key` to `AppConfig` and `.env.example`. The SDK defaults to `ANTHROPIC_API_KEY` env var but explicit config is consistent with the project pattern.

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
| AGNT-01 | LLM fills all __REQUIRED__ placeholders | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_all_placeholders_filled -v` | Wave 0 |
| AGNT-01 | LLM draft with sector knowledge produces richer output | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_with_sector_knowledge -v` | Wave 0 |
| AGNT-02 | All provenance entries have LLM_DRAFT status | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_provenance_status_llm_draft -v` | Wave 0 |
| AGNT-02 | LLM_DRAFT accepted by schema validation | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_llm_draft_schema_valid -v` | Wave 0 |
| AGNT-02 | Finalization transitions LLM_DRAFT to final status | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_finalization_transitions_llm_draft -v` | Wave 0 |
| AGNT-03 | Every field_provenance entry has non-empty review_note | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_all_fields_have_review_notes -v` | Wave 0 |
| AGNT-03 | Review notes reference named sources from raw bundle | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_review_notes_cite_evidence -v` | Wave 0 |
| AGNT-04 | Worst case appears before base case in response | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_worst_case_before_base_case -v` | Wave 0 |
| AGNT-04 | Bear thesis appears before bull thesis | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_bear_before_bull -v` | Wave 0 |
| AGNT-05 | Output passes validate_structured_analysis() | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_output_validates_schema -v` | Wave 0 |
| AGNT-05 | Output passes enriched Codex field validation | unit | `python -m unittest tests.test_analyst.TestAnalystAgent.test_enriched_codex_fields_present -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest discover -s tests -v`
- **Per wave merge:** `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_analyst.py` -- covers AGNT-01 through AGNT-05 (with transport-injected fixture responses)
- [ ] `tests/fixtures/analyst/` -- fixture LLM response payloads for transport injection
- [ ] Update `structured-analysis.schema.json` provenance status enum to include `LLM_DRAFT`
- [ ] Update `REQUIRED_PROVENANCE_FIELDS` to include enriched Codex fields from Phase 1
- [ ] Add `anthropic_api_key` to `AppConfig` and `.env.example`

## Sources

### Primary (HIGH confidence)
- **Anthropic Structured Outputs docs** -- [platform.claude.com/docs/en/build-with-claude/structured-outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) -- `output_config.format` with `json_schema` type, constraint limitations, SDK helpers
- **Codebase inspection** -- `field_generation.py` (existing machine draft pattern), `structured_analysis.py` (provenance system, validation, finalization), `gemini.py` (transport injection pattern), `judge.py` (OpenAI structured output pattern), `config.py` (AppConfig), `schemas.py` (custom validator)
- **structured-analysis.schema.json** -- Full schema including enriched Codex fields from Phase 1 (catalyst_stack, invalidation_triggers, decision_memo, issues_and_fixes, setup_pattern, stretch_case_assumptions)
- **strategy-rules.md** -- Methodology rules the analyst prompt must follow

### Secondary (MEDIUM confidence)
- **Anthropic SDK version** -- v0.77.1 confirmed installed via `pip show anthropic`; supports `output_config.format` (GA, no beta header needed)
- **Model availability** -- Claude Opus 4.6, Sonnet 4.6, Sonnet 4.5, Opus 4.5, Haiku 4.5 all support structured outputs

### Tertiary (LOW confidence)
- **Token budget estimates** -- 8192 max_tokens should be sufficient for a single candidate analysis output, but complex multi-ticker bundles may need more. Needs validation with real payloads.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- anthropic SDK already installed, patterns proven in gemini.py and judge.py
- Architecture: HIGH -- mirrors existing transport-injectable pattern, extends proven provenance system
- Pitfalls: HIGH -- identified from codebase inspection (schema constraint stripping, provenance enum, token budget) and Anthropic docs (constrained decoding limitations)

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable; Anthropic structured outputs are GA)
