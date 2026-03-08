from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .assets import load_json, structured_analysis_schema_path
from .schemas import SchemaValidationError, validate_instance


RAW_CHECK_ORDER = ["solvency", "dilution", "revenue_growth", "roic", "valuation"]
RAW_PCS_ORDER = ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]
PLACEHOLDER_TEXT = "__REQUIRED__"
REQUIRED_PROVENANCE_FIELDS = [
    "screening_inputs.industry_understandable",
    "screening_inputs.industry_in_secular_decline",
    "screening_inputs.double_plus_potential",
    "screening_inputs.solvency",
    "screening_inputs.dilution",
    "screening_inputs.revenue_growth",
    "screening_inputs.roic",
    "screening_inputs.valuation",
    "analysis_inputs.margin_trend_gate",
    "analysis_inputs.final_cluster_status",
    "analysis_inputs.catalyst_classification",
    "analysis_inputs.dominant_risk_type",
    "analysis_inputs.issues_and_fixes",
    "analysis_inputs.moat_assessment",
    "analysis_inputs.thesis_summary",
    "analysis_inputs.catalysts",
    "analysis_inputs.key_risks",
    "analysis_inputs.base_case_assumptions",
    "analysis_inputs.worst_case_assumptions",
    "analysis_inputs.probability_inputs",
    "analysis_inputs.exception_candidate",
    "epistemic_inputs.q1_operational",
    "epistemic_inputs.q2_regulatory",
    "epistemic_inputs.q3_precedent",
    "epistemic_inputs.q4_nonbinary",
    "epistemic_inputs.q5_macro",
]
FINAL_PROVENANCE_STATUSES = {"HUMAN_EDITED", "HUMAN_CONFIRMED"}


def _load_schema() -> dict:
    return load_json(structured_analysis_schema_path())


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _raw_bundle_fingerprint(raw_bundle: dict) -> str:
    return _fingerprint(
        {
            "scan_date": raw_bundle.get("scan_date"),
            "version": raw_bundle.get("version"),
            "scan_parameters": raw_bundle.get("scan_parameters"),
            "raw_candidates": raw_bundle.get("raw_candidates"),
        }
    )


def _candidate_evidence_context(raw_candidate: dict) -> dict:
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    gemini_context = raw_candidate.get("gemini_context", {})
    return {
        "market_snapshot": raw_candidate.get("market_snapshot", {}),
        "fmp_derived": derived,
        "gemini_prompt_context": gemini_context.get("prompt_context"),
        "gemini_evidence_counts": {
            key: len(gemini_context.get(key, []))
            for key in [
                "research_notes",
                "catalyst_evidence",
                "risk_evidence",
                "management_observations",
                "moat_observations",
                "precedent_observations",
                "epistemic_anchors",
            ]
        },
    }


def _contains_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return PLACEHOLDER_TEXT in value
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    return False


def _template_field_provenance(evidence_context: dict) -> list[dict]:
    summary = f"Evidence fingerprint {_fingerprint(evidence_context)}"
    return [
        {
            "field_path": field_path,
            "status": "MACHINE_DRAFT",
            "rationale": "This field still requires human review and explicit replacement or confirmation.",
            "evidence_refs": [
                {
                    "kind": "evidence_context",
                    "path": "evidence_context",
                    "summary": summary,
                }
            ],
        }
        for field_path in REQUIRED_PROVENANCE_FIELDS
    ]


def _validate_provenance_coverage(candidate: dict, *, allow_machine_draft: bool) -> None:
    provenance = candidate.get("field_provenance")
    if not isinstance(provenance, list) or not provenance:
        raise ValueError(f"structured candidate {candidate.get('ticker')} must include field_provenance before apply")

    provenance_by_path: dict[str, dict] = {}
    for item in provenance:
        if not isinstance(item, dict):
            raise ValueError(f"structured candidate {candidate.get('ticker')} has malformed field_provenance entries")
        field_path = item.get("field_path")
        status = item.get("status")
        if not isinstance(field_path, str) or not field_path:
            raise ValueError(f"structured candidate {candidate.get('ticker')} has field_provenance without field_path")
        if field_path in provenance_by_path:
            raise ValueError(f"structured candidate {candidate.get('ticker')} has duplicate provenance for {field_path}")
        provenance_by_path[field_path] = item
        if not allow_machine_draft and status == "MACHINE_DRAFT":
            raise ValueError(
                f"structured candidate {candidate.get('ticker')} still has MACHINE_DRAFT provenance for {field_path}"
            )

    missing = [field_path for field_path in REQUIRED_PROVENANCE_FIELDS if field_path not in provenance_by_path]
    if missing:
        raise ValueError(
            f"structured candidate {candidate.get('ticker')} is missing provenance for: {', '.join(missing)}"
        )


def validate_structured_analysis(payload: dict) -> None:
    try:
        validate_instance(payload, _load_schema())
    except SchemaValidationError as exc:
        raise ValueError(f"structured analysis schema validation failed: {exc}") from exc


def _validate_generation_fingerprint_continuity(payload: dict) -> None:
    source_bundle = payload.get("source_bundle")
    if not isinstance(source_bundle, dict):
        raise ValueError("structured_payload.source_bundle must be an object")
    generation_metadata = payload.get("generation_metadata")
    if not isinstance(generation_metadata, dict):
        raise ValueError("structured analysis must include generation_metadata")
    source_fingerprint = source_bundle.get("raw_bundle_fingerprint")
    generation_fingerprint = generation_metadata.get("raw_bundle_fingerprint")
    if source_fingerprint != generation_fingerprint:
        raise ValueError("structured analysis generation metadata fingerprint does not match source_bundle")


def _candidate_defaults(raw_candidate: dict) -> tuple[dict, dict]:
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    latest_revenue = derived.get("latest_revenue_b", 3.0)
    trough_revenue = derived.get("trough_revenue_b", latest_revenue)
    latest_fcf = derived.get("latest_fcf_margin_pct", 10.0)
    trough_fcf = derived.get("trough_fcf_margin_pct", latest_fcf)
    latest_shares = derived.get("shares_m_latest", 100.0)

    analysis_inputs = {
        "margin_trend_gate": PLACEHOLDER_TEXT,
        "final_cluster_status": PLACEHOLDER_TEXT,
        "catalyst_classification": PLACEHOLDER_TEXT,
        "dominant_risk_type": PLACEHOLDER_TEXT,
        "issues_and_fixes": PLACEHOLDER_TEXT,
        "moat_assessment": PLACEHOLDER_TEXT,
        "thesis_summary": PLACEHOLDER_TEXT,
        "catalysts": [PLACEHOLDER_TEXT],
        "key_risks": [PLACEHOLDER_TEXT],
        "base_case_assumptions": {
            "revenue_b": latest_revenue,
            "fcf_margin_pct": latest_fcf,
            "multiple": 20.0,
            "shares_m": latest_shares,
            "years": 3.0,
            "discount_path": PLACEHOLDER_TEXT,
        },
        "worst_case_assumptions": {
            "revenue_b": trough_revenue,
            "fcf_margin_pct": trough_fcf,
            "multiple": 12.0,
            "shares_m": latest_shares,
        },
        "probability_inputs": {
            "base_probability_pct": 70.0,
            "base_rate": PLACEHOLDER_TEXT,
            "likert_adjustments": PLACEHOLDER_TEXT,
        },
        "exception_candidate": {
            "eligible": False,
            "reason": PLACEHOLDER_TEXT,
        },
    }
    epistemic_inputs = {
        key: {
            "answer": PLACEHOLDER_TEXT,
            "justification": PLACEHOLDER_TEXT,
            "evidence": PLACEHOLDER_TEXT,
        }
        for key in RAW_PCS_ORDER
    }
    evidence_context = _candidate_evidence_context(raw_candidate)
    return analysis_inputs, {**epistemic_inputs, "_evidence_context": evidence_context}


def structured_analysis_template(raw_bundle: dict) -> dict:
    raw_candidates = raw_bundle.get("raw_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("raw_bundle.raw_candidates must be a non-empty list")

    structured_candidates: list[dict] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict) or not isinstance(raw_candidate.get("ticker"), str):
            raise ValueError("raw_bundle.raw_candidates[] must include ticker")
        analysis_inputs, epistemic_payload = _candidate_defaults(raw_candidate)
        evidence_context = epistemic_payload.pop("_evidence_context")
        structured_candidates.append(
            {
                "ticker": raw_candidate["ticker"],
                "evidence_context": evidence_context,
                "evidence_fingerprint": _fingerprint(evidence_context),
                "field_provenance": _template_field_provenance(evidence_context),
                "screening_inputs": {
                    "industry_understandable": False,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": False,
                    **{
                        check_name: {
                            "verdict": PLACEHOLDER_TEXT,
                            "evidence": PLACEHOLDER_TEXT,
                        }
                        for check_name in RAW_CHECK_ORDER
                    },
                },
                "analysis_inputs": analysis_inputs,
                "epistemic_inputs": epistemic_payload,
            }
        )

    scan_parameters = deepcopy(raw_bundle.get("scan_parameters", {}))
    return {
        "title": f"Structured Analysis Overlay - {raw_bundle.get('title', 'EdenFinTech')}",
        "scan_date": raw_bundle.get("scan_date"),
        "version": raw_bundle.get("version", "v1"),
        "scan_parameters": scan_parameters,
        "source_bundle": {
            "scan_date": raw_bundle.get("scan_date"),
            "scan_mode": scan_parameters.get("scan_mode"),
            "focus": scan_parameters.get("focus"),
            "api": scan_parameters.get("api"),
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
        },
        "completion_status": "DRAFT",
        "completion_note": f"Replace all {PLACEHOLDER_TEXT} markers and set completion_status to FINALIZED before applying this overlay.",
        "generation_metadata": {
            "source": "build_structured_analysis_template",
            "generator_version": "v1",
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
            "notes": [
                "This is a manual-review scaffold, not an executable overlay.",
                "All field_provenance entries start as MACHINE_DRAFT and must be updated during human review.",
            ],
        },
        "methodology_notes": [
            "This payload is the current automation boundary between raw evidence retrieval and deterministic pipeline execution.",
            f"The generated template is intentionally non-executable until every {PLACEHOLDER_TEXT} marker is replaced.",
        ],
        "structured_candidates": structured_candidates,
    }


def apply_structured_analysis(raw_bundle: dict, structured_payload: dict) -> dict:
    validate_structured_analysis(structured_payload)
    raw_candidates = raw_bundle.get("raw_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("raw_bundle.raw_candidates must be a non-empty list")

    structured_candidates = structured_payload.get("structured_candidates")
    if not isinstance(structured_candidates, list) or not structured_candidates:
        raise ValueError("structured_payload.structured_candidates must be a non-empty list")

    if structured_payload.get("completion_status") != "FINALIZED":
        raise ValueError("structured analysis must be FINALIZED before it can be applied")
    if not isinstance(structured_payload.get("finalization_metadata"), dict):
        raise ValueError("structured analysis must include finalization_metadata before apply")

    source_bundle = structured_payload.get("source_bundle")
    if not isinstance(source_bundle, dict):
        raise ValueError("structured_payload.source_bundle must be an object")
    expected_scan_parameters = raw_bundle.get("scan_parameters", {})
    if source_bundle.get("scan_date") != raw_bundle.get("scan_date"):
        raise ValueError("structured analysis source_bundle.scan_date does not match the current raw bundle")
    if source_bundle.get("scan_mode") != expected_scan_parameters.get("scan_mode"):
        raise ValueError("structured analysis source_bundle.scan_mode does not match the current raw bundle")
    if source_bundle.get("focus") != expected_scan_parameters.get("focus"):
        raise ValueError("structured analysis source_bundle.focus does not match the current raw bundle")
    if source_bundle.get("api") != expected_scan_parameters.get("api"):
        raise ValueError("structured analysis source_bundle.api does not match the current raw bundle")
    if source_bundle.get("raw_bundle_fingerprint") != _raw_bundle_fingerprint(raw_bundle):
        raise ValueError("structured analysis source bundle fingerprint does not match the current raw bundle")

    _validate_generation_fingerprint_continuity(structured_payload)
    generation_metadata = structured_payload["generation_metadata"]
    if generation_metadata.get("raw_bundle_fingerprint") != _raw_bundle_fingerprint(raw_bundle):
        raise ValueError("structured analysis generation metadata fingerprint does not match the current raw bundle")

    structured_by_ticker: dict[str, dict] = {}
    for candidate in structured_candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("ticker"), str):
            raise ValueError("structured_payload.structured_candidates[] must include ticker")
        ticker = candidate["ticker"]
        if ticker in structured_by_ticker:
            raise ValueError(f"duplicate structured candidate for ticker {ticker}")
        if _contains_placeholder(candidate):
            raise ValueError(f"structured candidate {ticker} still contains placeholder markers")
        _validate_provenance_coverage(candidate, allow_machine_draft=False)
        structured_by_ticker[ticker] = candidate

    merged = deepcopy(raw_bundle)
    merged_candidates: list[dict] = []
    missing = []
    raw_tickers = {candidate.get("ticker") for candidate in raw_candidates}
    for raw_candidate in raw_candidates:
        ticker = raw_candidate.get("ticker")
        if ticker not in structured_by_ticker:
            missing.append(ticker)
            continue
        overlay = structured_by_ticker[ticker]
        expected_evidence_context = _candidate_evidence_context(raw_candidate)
        if overlay.get("evidence_context") != expected_evidence_context:
            raise ValueError(f"structured analysis evidence context does not match the current raw bundle for {ticker}")
        if overlay.get("evidence_fingerprint") != _fingerprint(expected_evidence_context):
            raise ValueError(f"structured analysis evidence fingerprint does not match the current raw bundle for {ticker}")
        merged_candidate = deepcopy(raw_candidate)
        merged_candidate["screening_inputs"] = deepcopy(overlay["screening_inputs"])
        if "analysis_inputs" in overlay:
            merged_candidate["analysis_inputs"] = deepcopy(overlay["analysis_inputs"])
        if "epistemic_inputs" in overlay:
            merged_candidate["epistemic_inputs"] = deepcopy(overlay["epistemic_inputs"])
        merged_candidates.append(merged_candidate)

    if missing:
        raise ValueError(f"structured analysis is missing tickers: {', '.join(str(item) for item in missing)}")

    extra = sorted(ticker for ticker in structured_by_ticker if ticker not in raw_tickers)
    if extra:
        raise ValueError(f"structured analysis contains unknown tickers: {', '.join(extra)}")

    merged["raw_candidates"] = merged_candidates
    merged["methodology_notes"] = list(
        dict.fromkeys(
            [
                *list(raw_bundle.get("methodology_notes", [])),
                *list(structured_payload.get("methodology_notes", [])),
                "Structured analysis overlay applied before build-scan-input.",
            ]
        )
    )
    merged["scan_parameters"] = deepcopy(structured_payload.get("scan_parameters", raw_bundle.get("scan_parameters", {})))
    return merged


def build_structured_analysis_template_file(raw_bundle_path: Path, json_out: Path | None = None) -> dict:
    payload = structured_analysis_template(load_json(raw_bundle_path))
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2))
    return payload


def finalize_structured_analysis(
    payload: dict,
    *,
    reviewer: str,
    final_status: str = "HUMAN_CONFIRMED",
    note: str | None = None,
) -> dict:
    structured_candidates = payload.get("structured_candidates")
    if isinstance(structured_candidates, list):
        for candidate in structured_candidates:
            if isinstance(candidate, dict) and _contains_placeholder(candidate):
                ticker = candidate.get("ticker")
                if ticker:
                    raise ValueError(f"structured candidate {ticker} still contains placeholder markers")
                raise ValueError("structured analysis still contains placeholder markers")
    validate_structured_analysis(payload)
    if payload.get("completion_status") != "DRAFT":
        raise ValueError("structured analysis must be DRAFT before finalization")
    if final_status not in FINAL_PROVENANCE_STATUSES:
        raise ValueError(f"final_status must be one of: {', '.join(sorted(FINAL_PROVENANCE_STATUSES))}")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("reviewer must be a non-empty string")

    _validate_generation_fingerprint_continuity(payload)
    finalized = deepcopy(payload)
    converted_fields = 0
    for candidate in finalized.get("structured_candidates", []):
        ticker = candidate.get("ticker")
        if _contains_placeholder(candidate):
            raise ValueError(f"structured candidate {ticker} still contains placeholder markers")
        _validate_provenance_coverage(candidate, allow_machine_draft=True)
        for item in candidate["field_provenance"]:
            if item.get("status") == "MACHINE_DRAFT":
                item["status"] = final_status
                converted_fields += 1

    finalized["completion_status"] = "FINALIZED"
    finalized["completion_note"] = note or f"Finalized by {reviewer.strip()} after human review."
    finalized["finalization_metadata"] = {
        "reviewer": reviewer.strip(),
        "finalized_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "provenance_transition_status": final_status,
        "converted_machine_fields": converted_fields,
        "notes": [finalized["completion_note"]],
    }

    validate_structured_analysis(finalized)
    for candidate in finalized["structured_candidates"]:
        _validate_provenance_coverage(candidate, allow_machine_draft=False)
    return finalized


def finalize_structured_analysis_file(
    structured_analysis_path: Path,
    *,
    reviewer: str,
    json_out: Path | None = None,
    final_status: str = "HUMAN_CONFIRMED",
    note: str | None = None,
) -> dict:
    payload = finalize_structured_analysis(
        load_json(structured_analysis_path),
        reviewer=reviewer,
        final_status=final_status,
        note=note,
    )
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2))
    return payload
