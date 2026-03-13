from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .assets import load_json, structured_analysis_schema_path
from .schemas import SchemaValidationError, validate_all_errors, validate_instance


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
    "analysis_inputs.catalyst_stack",
    "analysis_inputs.invalidation_triggers",
    "analysis_inputs.decision_memo",
    "analysis_inputs.issues_and_fixes",
    "analysis_inputs.setup_pattern",
    "analysis_inputs.stretch_case_assumptions",
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
FINAL_PROVENANCE_STATUSES = {"HUMAN_EDITED", "HUMAN_CONFIRMED", "LLM_CONFIRMED", "LLM_EDITED"}
DRAFT_PROVENANCE_STATUSES = {"MACHINE_DRAFT", "LLM_DRAFT"}


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


def _provenance_by_path(candidate: dict) -> dict[str, dict]:
    provenance = candidate.get("field_provenance")
    if not isinstance(provenance, list):
        return {}
    entries: dict[str, dict] = {}
    for item in provenance:
        if isinstance(item, dict) and isinstance(item.get("field_path"), str):
            entries[item["field_path"]] = item
    return entries


def _validate_provenance_coverage(
    candidate: dict,
    *,
    allow_machine_draft: bool,
    require_review_note_for_finalized: bool,
) -> None:
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
        if not allow_machine_draft and status in DRAFT_PROVENANCE_STATUSES:
            raise ValueError(
                f"structured candidate {candidate.get('ticker')} still has {status} provenance for {field_path}"
            )
        if require_review_note_for_finalized:
            review_note = item.get("review_note")
            if not isinstance(review_note, str) or not review_note.strip():
                raise ValueError(
                    f"structured candidate {candidate.get('ticker')} is missing review_note for {field_path}"
                )

    missing = [field_path for field_path in REQUIRED_PROVENANCE_FIELDS if field_path not in provenance_by_path]
    if missing:
        raise ValueError(
            f"structured candidate {candidate.get('ticker')} is missing provenance for: {', '.join(missing)}"
        )


def validate_structured_analysis(payload: dict) -> None:
    errors = validate_all_errors(payload, _load_schema())
    if errors:
        raise ValueError(f"structured analysis schema validation failed: {'; '.join(errors)}")


def review_structured_analysis(payload: dict) -> dict:
    validate_structured_analysis(payload)
    structured_candidates = payload.get("structured_candidates")
    if not isinstance(structured_candidates, list) or not structured_candidates:
        raise ValueError("structured_payload.structured_candidates must be a non-empty list")

    candidate_reports: list[dict] = []
    total_counts = {
        "required_entries": 0,
        "machine_draft": 0,
        "human_confirmed": 0,
        "human_edited": 0,
        "llm_confirmed": 0,
        "llm_edited": 0,
        "missing_review_notes": 0,
        "missing_provenance": 0,
    }
    ready_for_finalization = True

    for candidate in structured_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("structured_payload.structured_candidates[] must be objects")
        ticker = candidate.get("ticker")
        provenance_by_path = _provenance_by_path(candidate)
        entries: list[dict] = []
        counts = {
            "required_entries": len(REQUIRED_PROVENANCE_FIELDS),
            "machine_draft": 0,
            "human_confirmed": 0,
            "human_edited": 0,
            "llm_confirmed": 0,
            "llm_edited": 0,
            "missing_review_notes": 0,
            "missing_provenance": 0,
        }
        for field_path in REQUIRED_PROVENANCE_FIELDS:
            item = provenance_by_path.get(field_path)
            if item is None:
                counts["missing_provenance"] += 1
                entries.append(
                    {
                        "field_path": field_path,
                        "status": "MISSING",
                        "has_review_note": False,
                        "needs_review_note": True,
                    }
                )
                continue
            status = item.get("status", "UNKNOWN")
            review_note = item.get("review_note")
            has_review_note = isinstance(review_note, str) and bool(review_note.strip())
            needs_review_note = not has_review_note
            if status == "MACHINE_DRAFT":
                counts["machine_draft"] += 1
            elif status == "HUMAN_CONFIRMED":
                counts["human_confirmed"] += 1
            elif status == "HUMAN_EDITED":
                counts["human_edited"] += 1
            elif status == "LLM_CONFIRMED":
                counts["llm_confirmed"] += 1
            elif status == "LLM_EDITED":
                counts["llm_edited"] += 1
            if needs_review_note:
                counts["missing_review_notes"] += 1
            entries.append(
                {
                    "field_path": field_path,
                    "status": status,
                    "has_review_note": has_review_note,
                    "needs_review_note": needs_review_note,
                }
            )

        candidate_ready = (
            counts["machine_draft"] == 0
            and counts["missing_review_notes"] == 0
            and counts["missing_provenance"] == 0
            and not _contains_placeholder(candidate)
        )
        ready_for_finalization = ready_for_finalization and candidate_ready
        for key, value in counts.items():
            total_counts[key] += value
        candidate_reports.append(
            {
                "ticker": ticker,
                "ready_for_finalization": candidate_ready,
                "counts": counts,
                "entries": entries,
            }
        )

    return {
        "title": payload.get("title"),
        "scan_date": payload.get("scan_date"),
        "completion_status": payload.get("completion_status"),
        "ready_for_finalization": ready_for_finalization,
        "summary": total_counts,
        "candidates": candidate_reports,
    }


def render_review_structured_analysis_markdown(report: dict) -> str:
    lines = [
        "# Structured Analysis Review Checklist",
        "",
        f"- Title: {report.get('title', '')}",
        f"- Scan Date: {report.get('scan_date', '')}",
        f"- Completion Status: {report.get('completion_status', '')}",
        f"- Ready For Finalization: {'Yes' if report.get('ready_for_finalization') else 'No'}",
        "",
        "## Summary",
        "",
        f"- Required Entries: {report.get('summary', {}).get('required_entries', 0)}",
        f"- MACHINE_DRAFT: {report.get('summary', {}).get('machine_draft', 0)}",
        f"- HUMAN_CONFIRMED: {report.get('summary', {}).get('human_confirmed', 0)}",
        f"- HUMAN_EDITED: {report.get('summary', {}).get('human_edited', 0)}",
        f"- Missing Review Notes: {report.get('summary', {}).get('missing_review_notes', 0)}",
        f"- Missing Provenance: {report.get('summary', {}).get('missing_provenance', 0)}",
        "",
    ]

    for candidate in report.get("candidates", []):
        lines.extend(
            [
                f"## {candidate.get('ticker', 'Unknown Ticker')}",
                "",
                f"- Ready For Finalization: {'Yes' if candidate.get('ready_for_finalization') else 'No'}",
                f"- Required Entries: {candidate.get('counts', {}).get('required_entries', 0)}",
                f"- MACHINE_DRAFT: {candidate.get('counts', {}).get('machine_draft', 0)}",
                f"- HUMAN_CONFIRMED: {candidate.get('counts', {}).get('human_confirmed', 0)}",
                f"- HUMAN_EDITED: {candidate.get('counts', {}).get('human_edited', 0)}",
                f"- Missing Review Notes: {candidate.get('counts', {}).get('missing_review_notes', 0)}",
                f"- Missing Provenance: {candidate.get('counts', {}).get('missing_provenance', 0)}",
                "",
                "### Required Provenance Entries",
                "",
            ]
        )
        for entry in candidate.get("entries", []):
            needs_note = "missing review_note" if entry.get("needs_review_note") else "review_note present"
            lines.append(f"- `{entry.get('field_path', '')}`: {entry.get('status', '')} ({needs_note})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def suggest_review_notes(payload: dict) -> dict:
    validate_structured_analysis(payload)
    structured_candidates = payload.get("structured_candidates")
    if not isinstance(structured_candidates, list) or not structured_candidates:
        raise ValueError("structured_payload.structured_candidates must be a non-empty list")

    candidates: list[dict] = []
    total_suggestions = 0
    for candidate in structured_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("structured_payload.structured_candidates[] must be objects")
        ticker = candidate.get("ticker")
        provenance_by_path = _provenance_by_path(candidate)
        suggestions: list[dict] = []
        for field_path in REQUIRED_PROVENANCE_FIELDS:
            item = provenance_by_path.get(field_path)
            if item is None:
                continue
            review_note = item.get("review_note")
            if isinstance(review_note, str) and review_note.strip():
                continue
            evidence_refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            evidence_summary = "; ".join(
                ref.get("summary", "")
                for ref in evidence_refs
                if isinstance(ref, dict) and isinstance(ref.get("summary"), str) and ref.get("summary").strip()
            ) or "available evidence references"
            rationale = item.get("rationale") if isinstance(item.get("rationale"), str) else ""
            suggested_note = (
                f"Reviewer checked {field_path} against {evidence_summary}. "
                f"Review focus: {rationale or 'confirm the field remains appropriate against the cited evidence.'}"
            ).strip()
            suggestions.append(
                {
                    "field_path": field_path,
                    "status": item.get("status", "UNKNOWN"),
                    "suggested_review_note": suggested_note,
                }
            )
        total_suggestions += len(suggestions)
        candidates.append(
            {
                "ticker": ticker,
                "suggestions": suggestions,
            }
        )

    return {
        "title": payload.get("title"),
        "scan_date": payload.get("scan_date"),
        "completion_status": payload.get("completion_status"),
        "total_suggestions": total_suggestions,
        "candidates": candidates,
    }


def render_review_note_suggestions_markdown(report: dict) -> str:
    lines = [
        "# Review Note Suggestions",
        "",
        f"- Title: {report.get('title', '')}",
        f"- Scan Date: {report.get('scan_date', '')}",
        f"- Completion Status: {report.get('completion_status', '')}",
        f"- Total Suggestions: {report.get('total_suggestions', 0)}",
        "",
    ]
    for candidate in report.get("candidates", []):
        lines.extend(
            [
                f"## {candidate.get('ticker', 'Unknown Ticker')}",
                "",
            ]
        )
        suggestions = candidate.get("suggestions", [])
        if not suggestions:
            lines.append("- No missing required review_note entries.")
            lines.append("")
            continue
        for suggestion in suggestions:
            lines.append(f"- `{suggestion.get('field_path', '')}` [{suggestion.get('status', '')}]")
            lines.append(f"  Suggested note: {suggestion.get('suggested_review_note', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def apply_review_note_updates(payload: dict, updates: list[dict[str, str]]) -> dict:
    validate_structured_analysis(payload)
    if not updates:
        return deepcopy(payload)

    structured_candidates = payload.get("structured_candidates")
    if not isinstance(structured_candidates, list) or not structured_candidates:
        raise ValueError("structured_payload.structured_candidates must be a non-empty list")

    updated = deepcopy(payload)
    candidates_by_ticker = {
        candidate.get("ticker"): candidate
        for candidate in updated["structured_candidates"]
        if isinstance(candidate, dict) and isinstance(candidate.get("ticker"), str)
    }
    single_ticker = next(iter(candidates_by_ticker)) if len(candidates_by_ticker) == 1 else None

    for update in updates:
        ticker = update.get("ticker") or single_ticker
        field_path = update.get("field_path")
        note = update.get("review_note")
        if not isinstance(ticker, str) or not ticker:
            raise ValueError("review note updates must include ticker when multiple structured candidates exist")
        if not isinstance(field_path, str) or not field_path:
            raise ValueError("review note updates must include field_path")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("review note updates must include a non-empty review_note")
        candidate = candidates_by_ticker.get(ticker)
        if candidate is None:
            raise ValueError(f"structured analysis does not contain ticker {ticker}")
        provenance_item = _provenance_by_path(candidate).get(field_path)
        if provenance_item is None:
            raise ValueError(f"structured candidate {ticker} does not contain provenance for {field_path}")
        provenance_item["review_note"] = note.strip()

    return updated


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
        "catalyst_stack": [
            {"type": PLACEHOLDER_TEXT, "description": PLACEHOLDER_TEXT, "timeline": PLACEHOLDER_TEXT},
        ],
        "invalidation_triggers": [
            {"trigger": PLACEHOLDER_TEXT, "evidence": PLACEHOLDER_TEXT},
        ],
        "decision_memo": {
            "better_than_peer": PLACEHOLDER_TEXT,
            "safer_than_peer": PLACEHOLDER_TEXT,
            "what_makes_wrong": PLACEHOLDER_TEXT,
        },
        "issues_and_fixes": [
            {"issue": PLACEHOLDER_TEXT, "fix": PLACEHOLDER_TEXT, "evidence_status": PLACEHOLDER_TEXT},
        ],
        "setup_pattern": PLACEHOLDER_TEXT,
        "stretch_case_assumptions": {
            "revenue_b": latest_revenue,
            "fcf_margin_pct": latest_fcf,
            "multiple": 24.0,
            "shares_m": latest_shares,
            "years": 3.0,
            "discount_path": PLACEHOLDER_TEXT,
        },
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
        _validate_provenance_coverage(
            candidate,
            allow_machine_draft=False,
            require_review_note_for_finalized=True,
        )
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
        _validate_provenance_coverage(
            candidate,
            allow_machine_draft=True,
            require_review_note_for_finalized=False,
        )
        for item in candidate["field_provenance"]:
            if item.get("status") in DRAFT_PROVENANCE_STATUSES:
                review_note = item.get("review_note")
                if not isinstance(review_note, str) or not review_note.strip():
                    raise ValueError(
                        f"structured candidate {ticker} cannot finalize {item.get('field_path')} without review_note"
                    )
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
        _validate_provenance_coverage(
            candidate,
            allow_machine_draft=False,
            require_review_note_for_finalized=True,
        )
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


def review_structured_analysis_file(
    structured_analysis_path: Path,
    *,
    json_out: Path | None = None,
    markdown_out: Path | None = None,
    overlay_out: Path | None = None,
    note_updates: list[dict[str, str]] | None = None,
) -> dict:
    payload = load_json(structured_analysis_path)
    resolved_updates = note_updates or []
    if resolved_updates and overlay_out is None:
        raise ValueError("overlay_out is required when note_updates are provided")
    updated_payload = apply_review_note_updates(payload, resolved_updates)
    if overlay_out is not None:
        overlay_out.parent.mkdir(parents=True, exist_ok=True)
        overlay_out.write_text(json.dumps(updated_payload, indent=2))
    report = review_structured_analysis(updated_payload)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2))
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(render_review_structured_analysis_markdown(report), encoding="utf-8")
    return report


def suggest_review_notes_file(
    structured_analysis_path: Path,
    *,
    json_out: Path | None = None,
    markdown_out: Path | None = None,
) -> dict:
    payload = load_json(structured_analysis_path)
    report = suggest_review_notes(payload)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(render_review_note_suggestions_markdown(report), encoding="utf-8")
    return report
