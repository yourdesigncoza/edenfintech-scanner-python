"""Claude analyst agent for generating LLM-drafted structured analysis overlays.

This module provides a constrained decoding approach to generating structured
analysis overlays using Claude as an analyst. The output conforms to the same
schema as field_generation.py but uses LLM_DRAFT provenance status.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Callable

from .assets import load_json, structured_analysis_schema_path
from .structured_analysis import (
    _candidate_evidence_context,
    _fingerprint,
    _raw_bundle_fingerprint,
    validate_structured_analysis,
)

AnalystTransport = Callable[[dict], dict]

# Constraints that are unsupported in constrained decoding output schemas
_UNSUPPORTED_CONSTRAINTS = {"minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}


def _strip_unsupported_constraints(schema: dict) -> dict:
    """Recursively remove constraints unsupported by constrained decoding and add additionalProperties:false to objects."""
    if not isinstance(schema, dict):
        return schema

    cleaned = {k: v for k, v in schema.items() if k not in _UNSUPPORTED_CONSTRAINTS}

    if cleaned.get("type") == "object":
        cleaned["additionalProperties"] = False

    if "properties" in cleaned:
        cleaned["properties"] = {
            k: _strip_unsupported_constraints(v)
            for k, v in cleaned["properties"].items()
        }

    if "items" in cleaned and isinstance(cleaned["items"], dict):
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

    return cleaned


def _build_candidate_output_schema() -> dict:
    """Build a constrained decoding schema for a single candidate output.

    Loads the structured-analysis schema, extracts candidate-level fields
    (screening_inputs, analysis_inputs, epistemic_inputs, field_provenance),
    strips unsupported constraints, and locks provenance status to LLM_DRAFT.
    """
    full_schema = load_json(structured_analysis_schema_path())
    definitions = full_schema.get("definitions", {})

    # Extract candidate structure
    candidate_def = definitions.get("structured_candidate", {})
    candidate_props = candidate_def.get("properties", {})

    # Build the output schema with only the fields the LLM should produce
    output_schema = {
        "type": "object",
        "required": ["screening_inputs", "analysis_inputs", "epistemic_inputs", "field_provenance"],
        "properties": {
            "screening_inputs": deepcopy(candidate_props.get("screening_inputs", {})),
            "analysis_inputs": deepcopy(definitions.get("analysis_inputs", {})),
            "epistemic_inputs": deepcopy(candidate_props.get("epistemic_inputs", {})),
            "field_provenance": {
                "type": "array",
                "items": deepcopy(definitions.get("field_provenance", {})),
            },
        },
        "definitions": deepcopy(definitions),
    }

    # Lock provenance status to LLM_DRAFT only
    prov_item = output_schema["properties"]["field_provenance"]["items"]
    if "properties" in prov_item and "status" in prov_item["properties"]:
        prov_item["properties"]["status"]["enum"] = ["LLM_DRAFT"]
    if "definitions" in output_schema and "field_provenance" in output_schema["definitions"]:
        fp_def = output_schema["definitions"]["field_provenance"]
        if "properties" in fp_def and "status" in fp_def["properties"]:
            fp_def["properties"]["status"]["enum"] = ["LLM_DRAFT"]

    # Strip unsupported constraints for constrained decoding
    output_schema = _strip_unsupported_constraints(output_schema)

    return output_schema


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


def _build_system_prompt(sector_knowledge: dict | None = None) -> str:
    """Build the system prompt for the analyst agent."""
    parts = [
        "You are a senior equity research analyst drafting a structured analysis overlay.",
        "",
        "METHODOLOGY RULES:",
        "- Every field must be grounded in specific evidence from the raw candidate data.",
        "- Every field_provenance entry must have status 'LLM_DRAFT'.",
        "- Every field_provenance entry must include a non-empty review_note that cites a specific named source.",
        "- No __REQUIRED__ placeholders may appear in any field.",
        "",
        "ORDERING DISCIPLINE (CRITICAL):",
        "- worst_case_assumptions MUST appear BEFORE base_case_assumptions in your output.",
        "- Bear thesis elements MUST appear BEFORE bull thesis elements in thesis_summary.",
        "- This ordering ensures conservative-first analysis discipline.",
        "",
        "EVIDENCE CITATION RULES:",
        "- Review notes must reference specific source titles from the raw evidence (e.g., '10-K', 'Earnings call', 'Investor deck').",
        "- Each provenance entry must include evidence_refs linking back to raw data paths.",
        "",
        "PROVENANCE RULES:",
        "- All field_provenance entries must have status set to exactly 'LLM_DRAFT'.",
        "- All field_provenance entries must have a non-empty review_note.",
        "- Provenance must cover all required fields.",
    ]

    if sector_knowledge:
        parts.extend([
            "",
            "SECTOR CONTEXT:",
            json.dumps(sector_knowledge, indent=2),
        ])

    return "\n".join(parts)


def _build_user_prompt(
    raw_candidate: dict,
    evidence_context: dict,
    evidence_snippets: set[str],
    *,
    validator_objections: list[dict] | None = None,
) -> str:
    """Format the raw candidate data for the user message."""
    parts = [
        "Analyze the following raw candidate and produce a structured analysis overlay.",
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
    ]
    if validator_objections is not None:
        parts.extend([
            "",
            "VALIDATOR OBJECTIONS (from previous attempt -- you MUST address these):",
            json.dumps(validator_objections, indent=2),
            "",
            "Revise your analysis to address each objection explicitly.",
        ])
    return "\n".join(parts)


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
    # Check no placeholders
    output_text = json.dumps(candidate_output)
    if "__REQUIRED__" in output_text:
        raise ValueError("LLM output still contains __REQUIRED__ placeholders")

    # Check provenance review_notes
    provenance = candidate_output.get("field_provenance", [])
    for item in provenance:
        review_note = item.get("review_note")
        if not isinstance(review_note, str) or not review_note.strip():
            raise ValueError(
                f"LLM output missing review_note for {item.get('field_path', 'unknown')}"
            )

    # Check ordering in raw response text
    wc_pos = raw_response_text.find("worst_case")
    bc_pos = raw_response_text.find("base_case")
    if wc_pos >= 0 and bc_pos >= 0 and wc_pos > bc_pos:
        raise ValueError(
            "LLM output violates ordering discipline: worst_case must appear before base_case in response text"
        )

    bear_pos = raw_response_text.find("bear")
    bull_pos = raw_response_text.find("bull")
    if bear_pos >= 0 and bull_pos >= 0 and bear_pos > bull_pos:
        raise ValueError(
            "LLM output violates ordering discipline: bear must appear before bull in response text"
        )


class ClaudeAnalystClient:
    """Client for generating structured analysis overlays using Claude."""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = "claude-sonnet-4-5-20250514",
        transport: AnalystTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._default_transport
        self._last_raw_response: str | None = None

    def _default_transport(self, request_payload: dict) -> dict:
        """Default transport using the Anthropic SDK."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=request_payload["system"],
            messages=request_payload["messages"],
        )
        text = response.content[0].text
        return {"text": text, "stop_reason": response.stop_reason}

    def analyze(
        self,
        raw_candidate: dict,
        *,
        sector_knowledge: dict | None = None,
        validator_objections: list[dict] | None = None,
    ) -> dict:
        """Analyze a single raw candidate and return structured output."""
        evidence_context = _candidate_evidence_context(raw_candidate)
        evidence_snippets = _extract_evidence_snippets(raw_candidate)
        output_schema = _build_candidate_output_schema()

        system_prompt = _build_system_prompt(sector_knowledge)
        user_prompt = _build_user_prompt(
            raw_candidate, evidence_context, evidence_snippets,
            validator_objections=validator_objections,
        )

        request_payload = {
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "output_schema": output_schema,
        }

        response = self.transport(request_payload)
        raw_text = response["text"]
        self._last_raw_response = raw_text

        candidate_output = json.loads(raw_text)

        _post_validate(candidate_output, raw_candidate, raw_text)

        return candidate_output


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

        evidence_context = _candidate_evidence_context(raw_candidate)
        candidate_output = client.analyze(
            raw_candidate, sector_knowledge=sector_knowledge,
            validator_objections=validator_objections,
        )

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
