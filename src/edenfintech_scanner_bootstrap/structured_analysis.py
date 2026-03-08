from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .assets import load_json, structured_analysis_schema_path
from .schemas import SchemaValidationError, validate_instance


RAW_CHECK_ORDER = ["solvency", "dilution", "revenue_growth", "roic", "valuation"]
RAW_PCS_ORDER = ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]


def _load_schema() -> dict:
    return load_json(structured_analysis_schema_path())


def validate_structured_analysis(payload: dict) -> None:
    try:
        validate_instance(payload, _load_schema())
    except SchemaValidationError as exc:
        raise ValueError(f"structured analysis schema validation failed: {exc}") from exc


def _candidate_defaults(raw_candidate: dict) -> tuple[dict, dict]:
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    latest_revenue = derived.get("latest_revenue_b", 3.0)
    trough_revenue = derived.get("trough_revenue_b", latest_revenue)
    latest_fcf = derived.get("latest_fcf_margin_pct", 10.0)
    trough_fcf = derived.get("trough_fcf_margin_pct", latest_fcf)
    latest_shares = derived.get("shares_m_latest", 100.0)
    market_snapshot = raw_candidate.get("market_snapshot", {})
    gemini_context = raw_candidate.get("gemini_context", {})

    analysis_inputs = {
        "margin_trend_gate": "PASS",
        "final_cluster_status": "CLEAR_WINNER",
        "catalyst_classification": "VALID_CATALYST",
        "dominant_risk_type": "Operational/Financial",
        "issues_and_fixes": "Replace with structured analysis grounded in the raw evidence bundle.",
        "moat_assessment": "Replace with a grounded moat assessment or remove if not applicable.",
        "thesis_summary": "Replace with the actual thesis once the structured analysis is complete.",
        "catalysts": ["Replace with a methodology-grounded catalyst list."],
        "key_risks": ["Replace with a methodology-grounded risk list."],
        "base_case_assumptions": {
            "revenue_b": latest_revenue,
            "fcf_margin_pct": latest_fcf,
            "multiple": 20.0,
            "shares_m": latest_shares,
            "years": 3.0,
        },
        "worst_case_assumptions": {
            "revenue_b": trough_revenue,
            "fcf_margin_pct": trough_fcf,
            "multiple": 12.0,
            "shares_m": latest_shares,
        },
        "probability_inputs": {
            "base_probability_pct": 70.0,
        },
        "exception_candidate": {
            "eligible": False,
        },
    }
    epistemic_inputs = {
        key: {
            "answer": "Yes",
            "justification": "Replace with the actual structured PCS judgment.",
            "evidence": "Replace with the specific evidence anchor supporting this answer.",
        }
        for key in RAW_PCS_ORDER
    }
    evidence_context = {
        "market_snapshot": market_snapshot,
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
                "screening_inputs": {
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    **{
                        check_name: {
                            "verdict": "PASS",
                            "evidence": "Replace with evidence grounded in the fetched raw bundle.",
                        }
                        for check_name in RAW_CHECK_ORDER
                    },
                },
                "analysis_inputs": analysis_inputs,
                "epistemic_inputs": epistemic_payload,
            }
        )

    return {
        "title": f"Structured Analysis Overlay - {raw_bundle.get('title', 'EdenFinTech')}",
        "scan_date": raw_bundle.get("scan_date"),
        "version": raw_bundle.get("version", "v1"),
        "scan_parameters": deepcopy(raw_bundle.get("scan_parameters", {})),
        "methodology_notes": [
            "This payload is the current automation boundary between raw evidence retrieval and deterministic pipeline execution.",
            "Replace the example structured fields with methodology-grounded judgments before building scan input or a report.",
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

    structured_by_ticker = {}
    for candidate in structured_candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("ticker"), str):
            raise ValueError("structured_payload.structured_candidates[] must include ticker")
        ticker = candidate["ticker"]
        if ticker in structured_by_ticker:
            raise ValueError(f"duplicate structured candidate for ticker {ticker}")
        structured_by_ticker[ticker] = candidate

    merged = deepcopy(raw_bundle)
    merged_candidates: list[dict] = []
    missing = []
    for raw_candidate in raw_candidates:
        ticker = raw_candidate.get("ticker")
        if ticker not in structured_by_ticker:
            missing.append(ticker)
            continue
        overlay = structured_by_ticker[ticker]
        merged_candidate = deepcopy(raw_candidate)
        merged_candidate["screening_inputs"] = deepcopy(overlay["screening_inputs"])
        if "analysis_inputs" in overlay:
            merged_candidate["analysis_inputs"] = deepcopy(overlay["analysis_inputs"])
        if "epistemic_inputs" in overlay:
            merged_candidate["epistemic_inputs"] = deepcopy(overlay["epistemic_inputs"])
        merged_candidates.append(merged_candidate)

    if missing:
        raise ValueError(f"structured analysis is missing tickers: {', '.join(str(item) for item in missing)}")

    extra = sorted(ticker for ticker in structured_by_ticker if ticker not in {candidate.get('ticker') for candidate in raw_candidates})
    if extra:
        raise ValueError(f"structured analysis contains unknown tickers: {', '.join(extra)}")

    merged["raw_candidates"] = merged_candidates
    merged["methodology_notes"] = list(dict.fromkeys([
        *list(raw_bundle.get("methodology_notes", [])),
        *list(structured_payload.get("methodology_notes", [])),
        "Structured analysis overlay applied before build-scan-input.",
    ]))
    merged["scan_parameters"] = deepcopy(structured_payload.get("scan_parameters", raw_bundle.get("scan_parameters", {})))
    return merged


def build_structured_analysis_template_file(raw_bundle_path: Path, json_out: Path | None = None) -> dict:
    payload = structured_analysis_template(load_json(raw_bundle_path))
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2))
    return payload
