"""Claude analyst agent for generating LLM-drafted structured analysis overlays.

Uses a 3-stage sequential pipeline to stay within Anthropic's grammar compiler
limits for constrained decoding:

  Stage 1 (Fundamentals) — screening, cases, financials  [Haiku, constrained]
  Stage 2 (Qualitative)  — catalysts, risks, thesis      [Haiku, constrained]
  Stage 3 (Synthesis)    — unified overlay assembly       [Sonnet, prompt-only]

Stage 2 receives Stage 1 output as context. Stage 3 receives both and reconciles.
On validator REJECT retry, only Stage 3 re-runs (Stages 1+2 cached).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable

from .assets import load_json, structured_analysis_schema_path
from .llm_transport import LlmResponseError, LlmTransport, default_anthropic_transport, parse_llm_json
from .structured_analysis import (
    REQUIRED_PROVENANCE_FIELDS,
    _candidate_evidence_context,
    _fingerprint,
    _raw_bundle_fingerprint,
    validate_structured_analysis,
)

AnalystTransport = Callable[[dict], dict]

# Constraints that are unsupported in constrained decoding output schemas
_UNSUPPORTED_CONSTRAINTS = {"minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}

# Fields assigned to each stage (tuples for deterministic schema property ordering)
_FUNDAMENTALS_ANALYSIS_FIELDS = (
    "margin_trend_gate", "setup_pattern",
    "base_case_assumptions", "worst_case_assumptions", "stretch_case_assumptions",
    "probability_inputs", "key_financials",
)

_QUALITATIVE_ANALYSIS_FIELDS = (
    "catalyst_classification", "catalyst_stack", "catalysts",
    "dominant_risk_type", "key_risks", "invalidation_triggers",
    "moat_assessment", "thesis_summary", "structural_diagnosis",
    "decision_memo", "issues_and_fixes",
    "human_judgment_flags", "exception_candidate", "final_cluster_status",
)

# Pause duration (seconds) before retrying after a transient API error (500/529)
_API_RETRY_PAUSE_SECS = 5 * 60  # 5 minutes


def _backfill_from_stages(
    synthesis_output: dict,
    fundamentals_output: dict,
    qualitative_output: dict,
) -> None:
    """Backfill missing fields from cached stage outputs into synthesis output.

    On retry, the LLM may focus on objections and omit unchanged fields.
    This merges them back from the constrained-decoding stage outputs.
    """
    filled: list[str] = []

    # analysis_inputs backfill
    synth_ai = synthesis_output.get("analysis_inputs", {})
    fund_ai = fundamentals_output.get("analysis_inputs", {})
    qual_ai = qualitative_output.get("analysis_inputs", {})

    for field in _FUNDAMENTALS_ANALYSIS_FIELDS:
        if field not in synth_ai and field in fund_ai:
            synth_ai[field] = fund_ai[field]
            filled.append(field)
        elif field in synth_ai and field in fund_ai and isinstance(fund_ai[field], dict) and isinstance(synth_ai[field], dict):
            # Deep-merge: fill missing nested keys from stage output
            for k, v in fund_ai[field].items():
                if k not in synth_ai[field]:
                    synth_ai[field][k] = v
                    filled.append(f"{field}.{k}")
    for field in _QUALITATIVE_ANALYSIS_FIELDS:
        if field not in synth_ai and field in qual_ai:
            synth_ai[field] = qual_ai[field]
            filled.append(field)
        elif field in synth_ai and field in qual_ai and isinstance(qual_ai[field], dict) and isinstance(synth_ai[field], dict):
            for k, v in qual_ai[field].items():
                if k not in synth_ai[field]:
                    synth_ai[field][k] = v
                    filled.append(f"{field}.{k}")

    # screening_inputs backfill
    synth_si = synthesis_output.get("screening_inputs", {})
    fund_si = fundamentals_output.get("screening_inputs", {})
    for key in fund_si:
        if key not in synth_si:
            synth_si[key] = fund_si[key]
            filled.append(f"screening_inputs.{key}")

    # epistemic_inputs backfill
    synth_ei = synthesis_output.get("epistemic_inputs", {})
    qual_ei = qualitative_output.get("epistemic_inputs", {})
    for key in qual_ei:
        if key not in synth_ei:
            synth_ei[key] = qual_ei[key]
            filled.append(f"epistemic_inputs.{key}")

    # field_provenance backfill
    synth_prov = synthesis_output.get("field_provenance", [])
    synth_paths = {p.get("field_path") for p in synth_prov if isinstance(p, dict)}
    for stage_output in [fundamentals_output, qualitative_output]:
        for entry in stage_output.get("field_provenance", []):
            if isinstance(entry, dict) and entry.get("field_path") not in synth_paths:
                synth_prov.append(entry)
                filled.append(f"provenance:{entry.get('field_path')}")

    if filled:
        print(f"  [backfill] {len(filled)} fields from stages 1+2: {', '.join(filled)}")


def _ensure_provenance_completeness(
    synthesis_output: dict,
    fundamentals_output: dict,
    qualitative_output: dict,
) -> None:
    """Ensure all REQUIRED_PROVENANCE_FIELDS have provenance entries.

    Creates synthetic entries for missing parent fields, tagged with
    [SYNTHETIC ROLLUP] for audit transparency.
    """
    prov_list = synthesis_output.get("field_provenance", [])

    # Repair structurally incomplete entries from unconstrained Stage 3
    repaired: list[str] = []
    for entry in prov_list:
        if not isinstance(entry, dict):
            continue
        fp = entry.get("field_path", "unknown")
        if "rationale" not in entry or not entry.get("rationale"):
            entry["rationale"] = f"[SYSTEM REPAIR] Rationale omitted during Stage 3 synthesis for {fp}"
            repaired.append(f"{fp}:rationale")
        if "evidence_refs" not in entry:
            entry["evidence_refs"] = [{"kind": "system_recovery", "path": "unspecified",
                                        "summary": "System-generated placeholder due to missing LLM output"}]
            repaired.append(f"{fp}:evidence_refs")
    if repaired:
        print(f"  [provenance repair] {len(repaired)} fields: {', '.join(repaired)}")

    existing = {p.get("field_path") for p in prov_list if isinstance(p, dict)}
    filled: list[str] = []

    for required_path in REQUIRED_PROVENANCE_FIELDS:
        if required_path in existing:
            continue
        # Check if child provenance exists (roll-up)
        children = [p for p in prov_list if isinstance(p, dict)
                     and p.get("field_path", "").startswith(required_path + ".")]
        if children:
            sources = ", ".join(c.get("field_path", "") for c in children[:3])
            review_note = f"[SYNTHETIC ROLLUP] Aggregated from child fields: {sources}"
        else:
            section = required_path.split(".")[0]
            stage = "1 (Fundamentals)" if section != "epistemic_inputs" else "2 (Qualitative)"
            review_note = f"[SYNTHETIC ROLLUP] Carried over from constrained Stage {stage} output"

        prov_list.append({
            "field_path": required_path,
            "status": "LLM_DRAFT",
            "rationale": f"Required provenance for {required_path}",
            "review_note": review_note,
            "evidence_refs": [{"kind": "backfill", "path": "stages_1_2",
                               "summary": "System-generated from cached stage outputs"}],
        })
        filled.append(required_path)

    if filled:
        print(f"  [provenance sweep] {len(filled)} synthetic entries: {', '.join(filled)}")


def _coerce_analysis_types(analysis_inputs: dict) -> dict:
    """Coerce trivially wrong types for freeform fields. Logs warnings."""
    ts = analysis_inputs.get("thesis_summary")
    if isinstance(ts, dict):
        analysis_inputs["thesis_summary"] = " ".join(str(v) for v in ts.values())
        print("  [coerce] thesis_summary: object -> string")
    elif isinstance(ts, list):
        analysis_inputs["thesis_summary"] = " ".join(str(v) for v in ts)
        print("  [coerce] thesis_summary: list -> string")
    return analysis_inputs


def _strip_unsupported_constraints(schema: dict) -> dict:
    """Recursively remove constraints unsupported by constrained decoding and add additionalProperties:false to objects."""
    if not isinstance(schema, dict):
        return schema

    cleaned = {k: v for k, v in schema.items() if k not in _UNSUPPORTED_CONSTRAINTS}

    # Constrained decoding doesn't support type arrays — collapse to single type.
    # Prefer "object" when present (LLM produces structured data; coercion handles mismatches).
    schema_type = cleaned.get("type")
    if isinstance(schema_type, list):
        cleaned["type"] = "object" if "object" in schema_type else schema_type[0]

    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False

    if "properties" in cleaned:
        cleaned["properties"] = {
            k: _strip_unsupported_constraints(v)
            for k, v in cleaned["properties"].items()
        }

    if "items" in cleaned and isinstance(cleaned["items"], dict):
        if not cleaned["items"]:
            cleaned["items"] = {"type": "string"}
        cleaned["items"] = _strip_unsupported_constraints(cleaned["items"])

    if "definitions" in cleaned:
        cleaned["definitions"] = {
            k: _strip_unsupported_constraints(v)
            for k, v in cleaned["definitions"].items()
        }

    if "$defs" in cleaned:
        cleaned["$defs"] = {
            k: _strip_unsupported_constraints(v)
            for k, v in cleaned["$defs"].items()
        }

    for composite_key in ("anyOf", "allOf", "oneOf"):
        if composite_key in cleaned and isinstance(cleaned[composite_key], list):
            cleaned[composite_key] = [
                _strip_unsupported_constraints(sub) for sub in cleaned[composite_key]
            ]

    return cleaned


def _load_schema_parts() -> tuple[dict, dict, dict]:
    """Load and return (definitions, candidate_props, analysis_props) from the full schema."""
    full_schema = load_json(structured_analysis_schema_path())
    definitions = full_schema.get("definitions", {})
    candidate_def = definitions.get("structured_candidate", {})
    candidate_props = candidate_def.get("properties", {})
    analysis_def = definitions.get("analysis_inputs", {})
    analysis_props = analysis_def.get("properties", {})
    return definitions, candidate_props, analysis_props


def _build_provenance_array(definitions: dict) -> dict:
    """Build a field_provenance array schema locked to LLM_DRAFT."""
    prov_item = deepcopy(definitions.get("field_provenance", {}))
    if "properties" in prov_item and "status" in prov_item["properties"]:
        prov_item["properties"]["status"]["enum"] = ["LLM_DRAFT"]
    return {"type": "array", "items": prov_item}


def _build_fundamentals_schema() -> dict:
    """Build constrained decoding schema for Stage 1: Fundamentals.

    Covers screening_inputs + quantitative analysis fields + provenance.
    """
    definitions, candidate_props, analysis_props = _load_schema_parts()

    # Pick only the analysis fields for this stage
    stage_analysis_props = {
        k: deepcopy(analysis_props[k])
        for k in _FUNDAMENTALS_ANALYSIS_FIELDS
        if k in analysis_props
    }

    # Required keys = intersection of schema required and our field set
    full_required = definitions.get("analysis_inputs", {}).get("required", [])
    stage_required = [k for k in full_required if k in _FUNDAMENTALS_ANALYSIS_FIELDS]

    output_schema = {
        "type": "object",
        "required": ["screening_inputs", "analysis_inputs", "field_provenance"],
        "properties": {
            "screening_inputs": deepcopy(candidate_props.get("screening_inputs", {})),
            "analysis_inputs": {
                "type": "object",
                "required": stage_required,
                "properties": stage_analysis_props,
            },
            "field_provenance": _build_provenance_array(definitions),
        },
        "definitions": {
            k: deepcopy(definitions[k])
            for k in (
                "screening_check",
                "base_case_assumptions",
                "worst_case_assumptions",
                "stretch_case_assumptions",
                "probability_inputs",
            )
            if k in definitions
        },
    }

    return _strip_unsupported_constraints(output_schema)


def _build_qualitative_schema() -> dict:
    """Build constrained decoding schema for Stage 2: Qualitative.

    Covers qualitative analysis fields + epistemic_inputs + provenance.
    """
    definitions, candidate_props, analysis_props = _load_schema_parts()

    stage_analysis_props = {
        k: deepcopy(analysis_props[k])
        for k in _QUALITATIVE_ANALYSIS_FIELDS
        if k in analysis_props
    }

    full_required = definitions.get("analysis_inputs", {}).get("required", [])
    stage_required = [k for k in full_required if k in _QUALITATIVE_ANALYSIS_FIELDS]

    output_schema = {
        "type": "object",
        "required": ["analysis_inputs", "epistemic_inputs", "field_provenance"],
        "properties": {
            "analysis_inputs": {
                "type": "object",
                "required": stage_required,
                "properties": stage_analysis_props,
            },
            "epistemic_inputs": deepcopy(candidate_props.get("epistemic_inputs", {})),
            "field_provenance": _build_provenance_array(definitions),
        },
        "definitions": {
            k: deepcopy(definitions[k])
            for k in ("pcs_check",)
            if k in definitions
        },
    }

    return _strip_unsupported_constraints(output_schema)


def _extract_evidence_snippets(raw_candidate: dict) -> set[str]:
    """Collect all source_title values from evidence arrays in the raw candidate."""
    titles: set[str] = set()
    gemini = raw_candidate.get("gemini_context", {})
    evidence_keys = [
        "research_notes", "catalyst_evidence", "risk_evidence",
        "management_observations", "moat_observations",
        "precedent_observations", "epistemic_anchors",
    ]
    for key in evidence_keys:
        items = gemini.get(key, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    title = item.get("source_title")
                    if isinstance(title, str) and title.strip():
                        titles.add(title.strip())
    return titles


# ---------------------------------------------------------------------------
# Shared prompt rules
# ---------------------------------------------------------------------------

_METHODOLOGY_RULES = """\
METHODOLOGY RULES:
- Every field must be grounded in specific evidence from the raw candidate data.
- Every field_provenance entry must have status 'LLM_DRAFT'.
- Every field_provenance entry must include a non-empty review_note that cites a specific named source.
- No __REQUIRED__ placeholders may appear in any field.

ORDERING DISCIPLINE (CRITICAL):
- worst_case_assumptions MUST appear BEFORE base_case_assumptions in your output.
- In the thesis_summary string, bear arguments MUST appear BEFORE bull arguments.
- This ordering ensures conservative-first analysis discipline.

EVIDENCE CITATION RULES:
- Review notes must reference specific source titles from the raw evidence (e.g., '10-K', 'Earnings call', 'Investor deck').
- Each provenance entry must include evidence_refs linking back to raw data paths.

PROVENANCE RULES:
- All field_provenance entries must have status set to exactly 'LLM_DRAFT'.
- All field_provenance entries must have a non-empty review_note.
- Provenance must cover all required fields."""


def _format_sector_block(sector_knowledge: dict | None) -> str:
    if not sector_knowledge:
        return ""
    return f"\n\nSECTOR CONTEXT:\n{json.dumps(sector_knowledge, indent=2)}"


# ---------------------------------------------------------------------------
# Stage 1: Fundamentals prompts
# ---------------------------------------------------------------------------

def _build_fundamentals_system_prompt(sector_knowledge: dict | None = None) -> str:
    return (
        "You are a senior equity research analyst producing QUANTITATIVE FUNDAMENTALS ONLY.\n\n"
        + _METHODOLOGY_RULES
        + "\n\nSCOPE: Produce screening_inputs, quantitative analysis_inputs "
        "(margin_trend_gate, setup_pattern, base/worst/stretch case assumptions, "
        "probability_inputs, key_financials), and field_provenance for these fields ONLY.\n"
        "Do NOT produce qualitative fields (catalysts, risks, thesis, epistemic inputs)."
        + _format_sector_block(sector_knowledge)
    )


def _build_fundamentals_user_prompt(
    raw_candidate: dict,
    evidence_context: dict,
    evidence_snippets: set[str],
) -> str:
    return "\n".join([
        "Analyze the following raw candidate and produce the quantitative fundamentals overlay.",
        "",
        f"Ticker: {raw_candidate.get('ticker', 'UNKNOWN')}",
        f"Industry: {raw_candidate.get('industry', 'Unknown')}",
        f"Current Price: {raw_candidate.get('current_price', 'N/A')}",
        "",
        "EVIDENCE CONTEXT:",
        json.dumps(evidence_context, indent=2),
        "",
        "AVAILABLE SOURCE TITLES:",
        ", ".join(sorted(evidence_snippets)),
        "",
        "RAW CANDIDATE DATA:",
        json.dumps(raw_candidate, indent=2),
    ])


# ---------------------------------------------------------------------------
# Stage 2: Qualitative prompts
# ---------------------------------------------------------------------------

def _build_qualitative_system_prompt(sector_knowledge: dict | None = None) -> str:
    return (
        "You are a senior equity research analyst producing QUALITATIVE ANALYSIS ONLY.\n\n"
        + _METHODOLOGY_RULES
        + "\n\nSCOPE: Produce qualitative analysis_inputs "
        "(catalyst_classification, catalyst_stack, catalysts, dominant_risk_type, key_risks, "
        "invalidation_triggers, moat_assessment, thesis_summary, structural_diagnosis, "
        "decision_memo, issues_and_fixes, human_judgment_flags, exception_candidate, "
        "final_cluster_status), epistemic_inputs, and field_provenance for these fields ONLY.\n"
        "Do NOT produce screening_inputs or quantitative fields.\n"
        "You will receive Stage 1 fundamentals output for reference — use it to ground your "
        "qualitative judgments but do not reproduce those fields."
        + _format_sector_block(sector_knowledge)
    )


def _build_qualitative_user_prompt(
    raw_candidate: dict,
    evidence_context: dict,
    evidence_snippets: set[str],
    fundamentals_output: dict,
) -> str:
    return "\n".join([
        "Analyze the following raw candidate and produce the qualitative analysis overlay.",
        "",
        f"Ticker: {raw_candidate.get('ticker', 'UNKNOWN')}",
        f"Industry: {raw_candidate.get('industry', 'Unknown')}",
        f"Current Price: {raw_candidate.get('current_price', 'N/A')}",
        "",
        "STAGE 1 FUNDAMENTALS (for reference — do not reproduce these fields):",
        json.dumps(fundamentals_output, indent=2),
        "",
        "EVIDENCE CONTEXT:",
        json.dumps(evidence_context, indent=2),
        "",
        "AVAILABLE SOURCE TITLES:",
        ", ".join(sorted(evidence_snippets)),
        "",
        "RAW CANDIDATE DATA:",
        json.dumps(raw_candidate, indent=2),
    ])


# ---------------------------------------------------------------------------
# Stage 3: Synthesis prompts
# ---------------------------------------------------------------------------

def _build_synthesis_system_prompt(sector_knowledge: dict | None = None) -> str:
    return (
        "You are a senior equity research analyst producing a UNIFIED STRUCTURED ANALYSIS OVERLAY.\n\n"
        + _METHODOLOGY_RULES
        + "\n\nYour job is to reconcile Stage 1 (fundamentals) and Stage 2 (qualitative) outputs "
        "into a single unified overlay. Check for consistency between the quantitative assumptions "
        "and qualitative assessments. If you find contradictions, resolve them with clear reasoning "
        "and update provenance accordingly.\n\n"
        "You may OVERRIDE Stage 1 or Stage 2 values if:\n"
        "- Validator objections require it\n"
        "- You detect internal contradictions\n"
        "- Evidence better supports a different value\n"
        "When overriding, update the field_provenance review_note to explain the override.\n\n"
        "OUTPUT FORMAT: Respond with a single JSON object containing exactly these top-level keys:\n"
        "{\n"
        '  "screening_inputs": { ... },\n'
        '  "analysis_inputs": {\n'
        '    "thesis_summary": "<string: single text block — bear arguments first, then bull>",\n'
        '    "structural_diagnosis": "<string or object: narrative assessment of structural position>",\n'
        '    "key_financials": "<string or object: key financial metrics>",\n'
        '    ... (all other fields per schema)\n'
        '  },\n'
        '  "epistemic_inputs": { ... },\n'
        '  "field_provenance": [ ... ]\n'
        "}\n"
        "All field_provenance entries must have status 'LLM_DRAFT'.\n\n"
        "CRITICAL SCHEMA CONSTRAINTS:\n"
        "You are reconciling Stage 1 & 2 data. Preserve their exact enum values — DO NOT invent "
        "compound enums (e.g. 'HARD_LOW_PROB', 'ANNOUNCED_ONLY / REQUIRES_FUTURE_DISCLOSURE').\n"
        "You MUST include ALL required analysis_inputs keys: margin_trend_gate, final_cluster_status, "
        "dominant_risk_type, invalidation_triggers, setup_pattern, base_case_assumptions (with revenue_b), "
        "worst_case_assumptions, stretch_case_assumptions, probability_inputs, catalyst_stack, "
        "catalyst_classification, decision_memo, issues_and_fixes.\n\n"
        "EXACT ENUM VALUES (use ONLY these, case-sensitive):\n"
        "- margin_trend_gate: PASS | PERMANENT_PASS\n"
        "- final_cluster_status: CLEAR_WINNER | CONDITIONAL_WINNER | LOWER_PRIORITY | ELIMINATED\n"
        "- catalyst_classification: VALID_CATALYST | SUPPORTING_TAILWIND | WATCH_ONLY | INVALID\n"
        "- dominant_risk_type: Operational/Financial | Cyclical/Macro | Regulatory/Political | Legal/Investigation | Structural fragility (SPOF)\n"
        "- setup_pattern: SOLVENCY_SCARE | QUALITY_FRANCHISE | NARRATIVE_DISCOUNT | NEW_OPERATOR | OTHER\n"
        "- catalyst_stack[].type: HARD | MEDIUM | SOFT\n"
        "- issues_and_fixes[].evidence_status: ANNOUNCED_ONLY | ACTION_UNDERWAY | EARLY_RESULTS_VISIBLE | PROVEN\n"
        "- screening verdicts: PASS | BORDERLINE_PASS | FAIL"
        + _format_sector_block(sector_knowledge)
    )


def _build_synthesis_user_prompt(
    raw_candidate: dict,
    fundamentals_output: dict,
    qualitative_output: dict,
    *,
    validator_objections: list[dict] | None = None,
) -> str:
    parts = [
        "Reconcile the following stage outputs into a unified structured analysis overlay.",
        "",
        f"Ticker: {raw_candidate.get('ticker', 'UNKNOWN')}",
        "",
        "STAGE 1 FUNDAMENTALS:",
        json.dumps(fundamentals_output, indent=2),
        "",
        "STAGE 2 QUALITATIVE:",
        json.dumps(qualitative_output, indent=2),
        "",
        "RAW CANDIDATE DATA (for cross-reference):",
        json.dumps(raw_candidate, indent=2),
    ]
    if validator_objections:
        parts.extend([
            "",
            "VALIDATOR OBJECTIONS (from previous attempt — you MUST address these):",
            json.dumps(validator_objections, indent=2),
            "",
            "Revise your analysis to address each objection explicitly. You may override "
            "Stage 1/2 values if needed to resolve objections — update provenance accordingly.",
            "",
            "STRUCTURAL REMINDER: While fixing objections, do NOT drop required keys "
            "(margin_trend_gate, final_cluster_status, dominant_risk_type, setup_pattern, "
            "invalidation_triggers, revenue_b, etc.) and do NOT invent compound enum values. "
            "Use ONLY the exact enum values listed in the system prompt.",
        ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Inter-stage validation
# ---------------------------------------------------------------------------

_FUNDAMENTALS_EXPECTED_KEYS = {"screening_inputs", "analysis_inputs", "field_provenance"}
_QUALITATIVE_EXPECTED_KEYS = {"analysis_inputs", "epistemic_inputs", "field_provenance"}


def _validate_stage_output(stage_name: str, output: dict, expected_keys: set[str]) -> None:
    """Lightweight structural check between stages."""
    missing = expected_keys - set(output.keys())
    if missing:
        raise LlmResponseError(
            f"[analyst/{stage_name}] Missing expected keys: {sorted(missing)}",
            agent=f"analyst/{stage_name}",
            raw_text=json.dumps(output)[:500],
        )

    # Verify field_provenance is a list
    prov = output.get("field_provenance")
    if not isinstance(prov, list):
        raise LlmResponseError(
            f"[analyst/{stage_name}] field_provenance must be a list, got {type(prov).__name__}",
            agent=f"analyst/{stage_name}",
            raw_text=json.dumps(output)[:500],
        )

    # Verify analysis_inputs is a dict
    ai = output.get("analysis_inputs")
    if not isinstance(ai, dict):
        raise LlmResponseError(
            f"[analyst/{stage_name}] analysis_inputs must be a dict, got {type(ai).__name__}",
            agent=f"analyst/{stage_name}",
            raw_text=json.dumps(output)[:500],
        )


# ---------------------------------------------------------------------------
# Post-validation (runs on final Stage 3 output)
# ---------------------------------------------------------------------------

def _post_validate(
    candidate_output: dict,
    raw_candidate: dict,
    raw_response_text: str,
) -> None:
    """Post-validation checks on the LLM output.

    Validates:
    1. No __REQUIRED__ placeholders remain
    2. Every provenance entry has a non-empty review_note
    3. worst_case appears before base_case in raw response text
    4. bear appears before bull in raw response text
    """
    output_text = json.dumps(candidate_output)
    if "__REQUIRED__" in output_text:
        raise ValueError("LLM output still contains __REQUIRED__ placeholders")

    provenance = candidate_output.get("field_provenance", [])
    for item in provenance:
        review_note = item.get("review_note")
        if not isinstance(review_note, str) or not review_note.strip():
            raise ValueError(
                f"LLM output missing review_note for {item.get('field_path', 'unknown')}"
            )

    wc_pos = raw_response_text.find('"worst_case')
    bc_pos = raw_response_text.find('"base_case')
    if wc_pos >= 0 and bc_pos >= 0 and wc_pos > bc_pos:
        raise ValueError(
            "LLM output violates ordering discipline: worst_case must appear before base_case in response text"
        )

    bear_pos = raw_response_text.find('"bear')
    bull_pos = raw_response_text.find('"bull')
    if bear_pos >= 0 and bull_pos >= 0 and bear_pos > bull_pos:
        raise ValueError(
            "LLM output violates ordering discipline: bear must appear before bull in response text"
        )


# ---------------------------------------------------------------------------
# Countdown helper for transient API errors
# ---------------------------------------------------------------------------

def _countdown(seconds: int, ticker: str) -> None:
    """Print a live countdown, overwriting the same line."""
    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        print(f"\r[{ticker}] ⏳ Resuming in {mins:02d}:{secs:02d} ...", end="", flush=True)
        time.sleep(1)
    print(f"\r[{ticker}] ⏳ Resuming now.              ")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ClaudeAnalystClient:
    """Client for generating structured analysis overlays using a 3-stage pipeline."""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = "claude-haiku-4-5-20251001",
        fundamentals_model: str | None = None,
        qualitative_model: str | None = None,
        synthesis_model: str | None = None,
        transport: AnalystTransport | None = None,
        synthesis_timeout: int = 300,
        artifact_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fundamentals_model = fundamentals_model or model
        self.qualitative_model = qualitative_model or model
        self.synthesis_model = synthesis_model or model
        self.synthesis_timeout = synthesis_timeout
        self.transport = transport or self._default_transport
        self._last_raw_response: str | None = None
        self._cached_fundamentals: dict | None = None
        self._cached_qualitative: dict | None = None
        self.artifact_dir = artifact_dir

    def _default_transport(self, request_payload: dict) -> dict:
        """Default transport — pops model/timeout keys from payload to select per-stage model."""
        model = request_payload.pop("model", self.model)
        request_payload.pop("timeout", None)  # not used by Anthropic SDK
        return default_anthropic_transport(
            request_payload,
            api_key=self.api_key,
            model=model,
            max_tokens=8192,
        )

    @property
    def last_fundamentals(self) -> dict | None:
        """Last fundamentals stage output (available after analyze())."""
        return self._cached_fundamentals

    @property
    def last_qualitative(self) -> dict | None:
        """Last qualitative stage output (available after analyze())."""
        return self._cached_qualitative

    def clear_stage_cache(self) -> None:
        """Reset cached stage outputs. Call per-candidate."""
        self._cached_fundamentals = None
        self._cached_qualitative = None

    def _save_stage_artifact(self, name: str, data: dict) -> None:
        """Save a stage result to disk immediately via atomic write.

        Skipped when artifact_dir is None. Raises on any failure so the
        pipeline halts rather than silently losing data.
        """
        if self.artifact_dir is None:
            return
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / f"analyst-{name}.json"
        fd, tmp = tempfile.mkstemp(
            dir=str(self.artifact_dir), prefix=f".analyst-{name}.", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"Artifact not on disk after write: {path}")

    def _call_stage(
        self,
        stage_name: str,
        stage_num: int,
        model: str,
        schema: dict | None,
        system_prompt: str,
        user_prompt: str,
        ticker: str,
        *,
        timeout: int | None = None,
    ) -> dict:
        """Call a single pipeline stage and return parsed JSON.

        On transient API errors (500/529), pauses with a visible countdown
        then retries once.
        """
        request_payload: dict = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if schema is not None:
            request_payload["output_schema"] = schema
        if timeout is not None:
            request_payload["timeout"] = timeout

        last_err: LlmResponseError | None = None
        for attempt in range(2):  # initial + 1 retry
            if attempt == 0:
                print(f"[{ticker}] Stage {stage_num}/3: {stage_name} ...", end=" ", flush=True)
            else:
                print(f"[{ticker}] Stage {stage_num}/3: {stage_name} (retry) ...", end=" ", flush=True)

            try:
                # Rebuild payload on retry (transport may have popped keys)
                payload = dict(request_payload)
                response = self.transport(payload)
                raw_text = response.get("text", "")
                self._last_raw_response = raw_text
                result = parse_llm_json(response, agent=f"analyst/{stage_name.lower()}")
                print("OK")
                return result
            except LlmResponseError as exc:
                last_err = exc
                is_transient = ("500" in str(exc) or "529" in str(exc)
                                or "overloaded" in str(exc).lower()
                                or "timed out" in str(exc).lower())
                if not is_transient or attempt > 0:
                    raise
                # Transient error — pause and retry
                pause = _API_RETRY_PAUSE_SECS
                print(f"\n[{ticker}] ⚠ API error (will retry in {pause // 60}m): {exc}")
                _countdown(pause, ticker)

        raise last_err  # type: ignore[misc]  # unreachable but satisfies type checker

    def analyze(
        self,
        raw_candidate: dict,
        *,
        sector_knowledge: dict | None = None,
        validator_objections: list[dict] | None = None,
    ) -> dict:
        """Analyze a single raw candidate via the 3-stage pipeline."""
        ticker = raw_candidate.get("ticker", "UNKNOWN")
        evidence_context = _candidate_evidence_context(raw_candidate)
        evidence_snippets = _extract_evidence_snippets(raw_candidate)

        # Stage 1: Fundamentals (skip if cached on retry)
        if self._cached_fundamentals is None:
            fundamentals_schema = _build_fundamentals_schema()
            fundamentals_output = self._call_stage(
                "Fundamentals", 1, self.fundamentals_model,
                fundamentals_schema,
                _build_fundamentals_system_prompt(sector_knowledge),
                _build_fundamentals_user_prompt(raw_candidate, evidence_context, evidence_snippets),
                ticker,
            )
            _validate_stage_output("Fundamentals", fundamentals_output, _FUNDAMENTALS_EXPECTED_KEYS)
            self._cached_fundamentals = fundamentals_output
            self._save_stage_artifact("fundamentals", fundamentals_output)
        else:
            print(f"[{ticker}] Stage 1/3: Fundamentals ... cached")
        fundamentals_output = self._cached_fundamentals

        # Stage 2: Qualitative (skip if cached on retry)
        if self._cached_qualitative is None:
            qualitative_schema = _build_qualitative_schema()
            qualitative_output = self._call_stage(
                "Qualitative", 2, self.qualitative_model,
                qualitative_schema,
                _build_qualitative_system_prompt(sector_knowledge),
                _build_qualitative_user_prompt(
                    raw_candidate, evidence_context, evidence_snippets, fundamentals_output,
                ),
                ticker,
            )
            _validate_stage_output("Qualitative", qualitative_output, _QUALITATIVE_EXPECTED_KEYS)
            self._cached_qualitative = qualitative_output
            self._save_stage_artifact("qualitative", qualitative_output)
        else:
            print(f"[{ticker}] Stage 2/3: Qualitative ... cached")
        qualitative_output = self._cached_qualitative

        # Stage 3: Synthesis (always runs, no constrained decoding)
        # Synthesis needs longer timeout — reconciles two stages + full raw candidate
        synthesis_output = self._call_stage(
            "Synthesis", 3, self.synthesis_model,
            None,  # No output_schema — prompt-based JSON
            _build_synthesis_system_prompt(sector_knowledge),
            _build_synthesis_user_prompt(
                raw_candidate, fundamentals_output, qualitative_output,
                validator_objections=validator_objections,
            ),
            ticker,
            timeout=self.synthesis_timeout,
        )

        _backfill_from_stages(synthesis_output, fundamentals_output, qualitative_output)
        _ensure_provenance_completeness(synthesis_output, fundamentals_output, qualitative_output)

        _validate_stage_output(
            "Synthesis", synthesis_output,
            {"screening_inputs", "analysis_inputs", "epistemic_inputs", "field_provenance"},
        )
        self._save_stage_artifact("synthesis-raw", synthesis_output)
        _post_validate(synthesis_output, raw_candidate, self._last_raw_response or "")

        return synthesis_output


def generate_llm_analysis_draft(
    raw_bundle: dict,
    *,
    client: ClaudeAnalystClient,
    sector_knowledge: dict | None = None,
    validator_objections: list[dict] | None = None,
) -> dict:
    """Generate a complete LLM-drafted structured analysis overlay.

    Iterates raw_candidates, calls client.analyze per candidate, wraps with
    envelope (same structure as field_generation.py), validates, and returns.
    """
    raw_candidates = raw_bundle.get("raw_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("raw_bundle.raw_candidates must be a non-empty list")

    structured_candidates: list[dict] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict) or not isinstance(raw_candidate.get("ticker"), str):
            raise ValueError("raw_bundle.raw_candidates[] must include ticker")

        # Only clear cache on the first attempt — on retry (with objections)
        # we keep stages 1+2 cached so only synthesis reruns.
        if validator_objections is None:
            client.clear_stage_cache()
        evidence_context = _candidate_evidence_context(raw_candidate)
        candidate_output = client.analyze(
            raw_candidate, sector_knowledge=sector_knowledge,
            validator_objections=validator_objections,
        )
        _coerce_analysis_types(candidate_output.get("analysis_inputs", {}))

        structured_candidates.append({
            "ticker": raw_candidate["ticker"],
            "evidence_context": evidence_context,
            "evidence_fingerprint": _fingerprint(evidence_context),
            "field_provenance": candidate_output["field_provenance"],
            "screening_inputs": candidate_output["screening_inputs"],
            "analysis_inputs": candidate_output["analysis_inputs"],
            "epistemic_inputs": candidate_output["epistemic_inputs"],
        })

    scan_parameters = raw_bundle.get("scan_parameters", {})
    payload = {
        "title": f"LLM Draft Structured Analysis Overlay - {raw_bundle.get('title', 'EdenFinTech')}",
        "scan_date": raw_bundle.get("scan_date"),
        "version": raw_bundle.get("version", "v1"),
        "scan_parameters": {
            "scan_mode": scan_parameters.get("scan_mode", "specific_tickers"),
            "focus": scan_parameters.get("focus", ""),
            "api": scan_parameters.get("api", "Merged raw bundle"),
        },
        "source_bundle": {
            "scan_date": raw_bundle.get("scan_date"),
            "scan_mode": scan_parameters.get("scan_mode", "specific_tickers"),
            "focus": scan_parameters.get("focus", ""),
            "api": scan_parameters.get("api", "Merged raw bundle"),
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
        },
        "completion_status": "DRAFT",
        "completion_note": "LLM-generated draft. Human review and explicit finalization are required before apply.",
        "generation_metadata": {
            "source": "analyst.py",
            "generator_version": "v1",
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
            "notes": [
                "LLM-generated fields are marked through field_provenance.status=LLM_DRAFT.",
                "This draft includes evidence-citing review_notes but still requires human finalization.",
            ],
        },
        "methodology_notes": [
            "This overlay was LLM-generated from merged raw evidence and is intentionally left in DRAFT status.",
            "Field-level provenance with review_notes is included; human finalization step still required.",
        ],
        "structured_candidates": structured_candidates,
    }
    validate_structured_analysis(payload)
    return payload
