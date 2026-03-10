from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .assets import load_json
from .pipeline import load_scan_input_template_text, scan_input_template, validate_scan_input


RAW_CHECK_ORDER = ["solvency", "dilution", "revenue_growth", "roic", "valuation"]
RAW_PCS_ORDER = ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]
RAW_GEMINI_EVIDENCE_ORDER = [
    "research_notes",
    "catalyst_evidence",
    "risk_evidence",
    "management_observations",
    "moat_observations",
    "precedent_observations",
    "epistemic_anchors",
]


def _require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _coerce_string_list(value: object, label: str) -> list[str]:
    return [_require_str(item, f"{label}[]") for item in _require_list(value, label)]


def _format_evidence_item(item: dict, label: str) -> str:
    claim = _require_str(item.get("claim"), f"{label}.claim")
    source_title = _require_str(item.get("source_title"), f"{label}.source_title")
    source_url = _require_str(item.get("source_url"), f"{label}.source_url")
    return f"{claim} ({source_title}: {source_url})"


def _import_gemini_context(raw_candidate: dict) -> dict | None:
    if "gemini_context" not in raw_candidate:
        return None

    gemini_context = _require_dict(raw_candidate.get("gemini_context"), f"{raw_candidate['ticker']}.gemini_context")
    prompt_context = _require_dict(
        gemini_context.get("prompt_context"),
        f"{raw_candidate['ticker']}.gemini_context.prompt_context",
    )
    imported = {
        "prompt_context": {
            "model": _require_str(prompt_context.get("model"), f"{raw_candidate['ticker']}.gemini_context.prompt_context.model"),
            "research_question": _require_str(
                prompt_context.get("research_question"),
                f"{raw_candidate['ticker']}.gemini_context.prompt_context.research_question",
            ),
            "search_scope": _require_str(
                prompt_context.get("search_scope"),
                f"{raw_candidate['ticker']}.gemini_context.prompt_context.search_scope",
            ),
        }
    }
    for evidence_key in RAW_GEMINI_EVIDENCE_ORDER:
        raw_items = _require_list(gemini_context.get(evidence_key, []), f"{raw_candidate['ticker']}.gemini_context.{evidence_key}")
        imported[evidence_key] = [
            {
                "claim": _require_str(item.get("claim"), f"{raw_candidate['ticker']}.gemini_context.{evidence_key}[{idx}].claim"),
                "source_title": _require_str(
                    item.get("source_title"),
                    f"{raw_candidate['ticker']}.gemini_context.{evidence_key}[{idx}].source_title",
                ),
                "source_url": _require_str(
                    item.get("source_url"),
                    f"{raw_candidate['ticker']}.gemini_context.{evidence_key}[{idx}].source_url",
                ),
            }
            for idx, item in enumerate(
                _require_dict(entry, f"{raw_candidate['ticker']}.gemini_context.{evidence_key}[]")
                for entry in raw_items
            )
        ]
    return imported


def _enrich_analysis_with_gemini(raw_candidate: dict, analysis: dict) -> None:
    source_research = _import_gemini_context(raw_candidate)
    if source_research is None:
        return

    catalyst_items = [_format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.catalyst_evidence") for item in source_research["catalyst_evidence"]]
    risk_items = [_format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.risk_evidence") for item in source_research["risk_evidence"]]
    moat_items = [_format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.moat_observations") for item in source_research["moat_observations"]]
    management_items = [
        _format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.management_observations")
        for item in source_research["management_observations"]
    ]
    precedent_items = [
        _format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.precedent_observations")
        for item in source_research["precedent_observations"]
    ]
    research_items = [_format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.research_notes") for item in source_research["research_notes"]]
    epistemic_items = [
        _format_evidence_item(item, f"{raw_candidate['ticker']}.gemini_context.epistemic_anchors")
        for item in source_research["epistemic_anchors"]
    ]

    if catalyst_items:
        analysis["catalysts"] = _dedupe_strings(list(analysis.get("catalysts", [])) + catalyst_items)
    if risk_items:
        analysis["key_risks"] = _dedupe_strings(list(analysis.get("key_risks", [])) + risk_items)
    if moat_items:
        moat_text = " | ".join(moat_items)
        existing_moat = analysis.get("moat_assessment")
        analysis["moat_assessment"] = f"{existing_moat} | {moat_text}" if existing_moat else moat_text

    human_flags = _coerce_string_list(analysis.get("human_judgment_flags", []), f"{raw_candidate['ticker']}.analysis_inputs.human_judgment_flags")
    human_flags.extend(management_items)
    human_flags.extend(precedent_items)
    human_flags.extend(epistemic_items)
    if research_items:
        human_flags.append(
            f"Gemini research notes imported ({len(research_items)} items) for {source_research['prompt_context']['research_question']}"
        )
    if human_flags:
        analysis["human_judgment_flags"] = _dedupe_strings(human_flags)

    analysis["source_research"] = source_research


def _screening_check(raw_candidate: dict, check_name: str) -> dict:
    checks = _require_dict(raw_candidate["screening_inputs"], f"{raw_candidate['ticker']}.screening_inputs")
    raw_check = _require_dict(checks.get(check_name), f"{raw_candidate['ticker']}.screening_inputs.{check_name}")
    verdict = _require_str(raw_check.get("verdict"), f"{raw_candidate['ticker']}.screening_inputs.{check_name}.verdict")
    evidence = _require_str(raw_check.get("evidence"), f"{raw_candidate['ticker']}.screening_inputs.{check_name}.evidence")
    return {"verdict": verdict, "note": evidence}


def _import_screening(raw_candidate: dict) -> dict:
    market_snapshot = _require_dict(raw_candidate.get("market_snapshot"), f"{raw_candidate['ticker']}.market_snapshot")
    screening_inputs = _require_dict(raw_candidate.get("screening_inputs"), f"{raw_candidate['ticker']}.screening_inputs")
    return {
        "pct_off_ath": _require_number(
            market_snapshot.get("pct_off_ath"),
            f"{raw_candidate['ticker']}.market_snapshot.pct_off_ath",
        ),
        "industry_understandable": _require_bool(
            screening_inputs.get("industry_understandable"),
            f"{raw_candidate['ticker']}.screening_inputs.industry_understandable",
        ),
        "industry_in_secular_decline": _require_bool(
            screening_inputs.get("industry_in_secular_decline"),
            f"{raw_candidate['ticker']}.screening_inputs.industry_in_secular_decline",
        ),
        "double_plus_potential": _require_bool(
            screening_inputs.get("double_plus_potential"),
            f"{raw_candidate['ticker']}.screening_inputs.double_plus_potential",
        ),
        "checks": {check_name: _screening_check(raw_candidate, check_name) for check_name in RAW_CHECK_ORDER},
    }


def _import_analysis(raw_candidate: dict) -> dict:
    analysis_inputs = _require_dict(raw_candidate.get("analysis_inputs"), f"{raw_candidate['ticker']}.analysis_inputs")
    base_case = _require_dict(
        analysis_inputs.get("base_case_assumptions"),
        f"{raw_candidate['ticker']}.analysis_inputs.base_case_assumptions",
    )
    worst_case = _require_dict(
        analysis_inputs.get("worst_case_assumptions"),
        f"{raw_candidate['ticker']}.analysis_inputs.worst_case_assumptions",
    )
    probability_inputs = _require_dict(
        analysis_inputs.get("probability_inputs"),
        f"{raw_candidate['ticker']}.analysis_inputs.probability_inputs",
    )
    analysis: dict = {
        "margin_trend_gate": _require_str(
            analysis_inputs.get("margin_trend_gate"),
            f"{raw_candidate['ticker']}.analysis_inputs.margin_trend_gate",
        ),
        "final_cluster_status": _require_str(
            analysis_inputs.get("final_cluster_status"),
            f"{raw_candidate['ticker']}.analysis_inputs.final_cluster_status",
        ),
        "catalyst_classification": _require_str(
            analysis_inputs.get("catalyst_classification"),
            f"{raw_candidate['ticker']}.analysis_inputs.catalyst_classification",
        ),
        "dominant_risk_type": _require_str(
            analysis_inputs.get("dominant_risk_type"),
            f"{raw_candidate['ticker']}.analysis_inputs.dominant_risk_type",
        ),
        "base_case": {
            "revenue_b": _require_number(base_case.get("revenue_b"), f"{raw_candidate['ticker']}.base_case_assumptions.revenue_b"),
            "fcf_margin_pct": _require_number(base_case.get("fcf_margin_pct"), f"{raw_candidate['ticker']}.base_case_assumptions.fcf_margin_pct"),
            "multiple": _require_number(base_case.get("multiple"), f"{raw_candidate['ticker']}.base_case_assumptions.multiple"),
            "shares_m": _require_number(base_case.get("shares_m"), f"{raw_candidate['ticker']}.base_case_assumptions.shares_m"),
            "years": _require_number(base_case.get("years"), f"{raw_candidate['ticker']}.base_case_assumptions.years"),
        },
        "worst_case": {
            "revenue_b": _require_number(worst_case.get("revenue_b"), f"{raw_candidate['ticker']}.worst_case_assumptions.revenue_b"),
            "fcf_margin_pct": _require_number(worst_case.get("fcf_margin_pct"), f"{raw_candidate['ticker']}.worst_case_assumptions.fcf_margin_pct"),
            "multiple": _require_number(worst_case.get("multiple"), f"{raw_candidate['ticker']}.worst_case_assumptions.multiple"),
            "shares_m": _require_number(worst_case.get("shares_m"), f"{raw_candidate['ticker']}.worst_case_assumptions.shares_m"),
        },
        "probability": {
            "base_probability_pct": _require_number(
                probability_inputs.get("base_probability_pct"),
                f"{raw_candidate['ticker']}.analysis_inputs.probability_inputs.base_probability_pct",
            ),
        },
    }

    if "discount_path" in base_case:
        analysis["base_case"]["discount_path"] = base_case["discount_path"]
    for optional_key in ["trough_path", "tbv_crosscheck"]:
        if optional_key in worst_case:
            analysis["worst_case"][optional_key] = worst_case[optional_key]
    for optional_key in ["base_rate", "likert_adjustments", "ceilings_applied", "threshold_proximity_warning"]:
        if optional_key in probability_inputs:
            analysis["probability"][optional_key] = probability_inputs[optional_key]
    for required_key in [
        "catalyst_stack",
        "invalidation_triggers",
        "decision_memo",
        "issues_and_fixes",
        "setup_pattern",
    ]:
        if required_key in analysis_inputs:
            analysis[required_key] = analysis_inputs[required_key]
    if "stretch_case_assumptions" in analysis_inputs:
        stretch = _require_dict(analysis_inputs["stretch_case_assumptions"], f"{raw_candidate['ticker']}.analysis_inputs.stretch_case_assumptions")
        analysis["stretch_case"] = {
            "revenue_b": _require_number(stretch.get("revenue_b"), f"{raw_candidate['ticker']}.stretch_case.revenue_b"),
            "fcf_margin_pct": _require_number(stretch.get("fcf_margin_pct"), f"{raw_candidate['ticker']}.stretch_case.fcf_margin_pct"),
            "multiple": _require_number(stretch.get("multiple"), f"{raw_candidate['ticker']}.stretch_case.multiple"),
            "shares_m": _require_number(stretch.get("shares_m"), f"{raw_candidate['ticker']}.stretch_case.shares_m"),
            "years": _require_number(stretch.get("years"), f"{raw_candidate['ticker']}.stretch_case.years"),
        }
        if "discount_path" in stretch:
            analysis["stretch_case"]["discount_path"] = stretch["discount_path"]
    for optional_key in [
        "moat_assessment",
        "thesis_summary",
        "key_financials",
        "structural_diagnosis",
        "human_judgment_flags",
    ]:
        if optional_key in analysis_inputs:
            analysis[optional_key] = analysis_inputs[optional_key]

    if "catalysts" in analysis_inputs:
        analysis["catalysts"] = list(_require_list(analysis_inputs["catalysts"], f"{raw_candidate['ticker']}.analysis_inputs.catalysts"))
    if "key_risks" in analysis_inputs:
        analysis["key_risks"] = list(_require_list(analysis_inputs["key_risks"], f"{raw_candidate['ticker']}.analysis_inputs.key_risks"))
    if "exception_candidate" in analysis_inputs:
        exception_candidate = _require_dict(
            analysis_inputs["exception_candidate"],
            f"{raw_candidate['ticker']}.analysis_inputs.exception_candidate",
        )
        analysis["exception_20_pct_gate"] = {
            "eligible": _require_bool(
                exception_candidate.get("eligible"),
                f"{raw_candidate['ticker']}.analysis_inputs.exception_candidate.eligible",
            )
        }
        if "reason" in exception_candidate:
            analysis["exception_20_pct_gate"]["reason"] = exception_candidate["reason"]

    _enrich_analysis_with_gemini(raw_candidate, analysis)
    return analysis


def _import_epistemic_review(raw_candidate: dict) -> dict:
    epistemic_inputs = _require_dict(raw_candidate.get("epistemic_inputs"), f"{raw_candidate['ticker']}.epistemic_inputs")
    return {
        key: _require_dict(epistemic_inputs.get(key), f"{raw_candidate['ticker']}.epistemic_inputs.{key}")
        for key in RAW_PCS_ORDER
    }


def import_candidate(raw_candidate: dict) -> dict:
    _require_str(raw_candidate.get("ticker"), "raw_candidate.ticker")
    imported = {
        "ticker": _require_str(raw_candidate["ticker"], "raw_candidate.ticker"),
        "cluster_name": _require_str(raw_candidate.get("cluster_name"), f"{raw_candidate['ticker']}.cluster_name"),
        "industry": _require_str(raw_candidate.get("industry"), f"{raw_candidate['ticker']}.industry"),
        "current_price": _require_number(raw_candidate.get("current_price"), f"{raw_candidate['ticker']}.current_price"),
        "screening": _import_screening(raw_candidate),
    }
    if "analysis_inputs" in raw_candidate:
        imported["analysis"] = _import_analysis(raw_candidate)
    if "epistemic_inputs" in raw_candidate:
        imported["epistemic_review"] = _import_epistemic_review(raw_candidate)
    return imported


def build_scan_input(raw_payload: dict) -> dict:
    scan_parameters = _require_dict(raw_payload.get("scan_parameters"), "raw_payload.scan_parameters")
    raw_candidates = _require_list(raw_payload.get("raw_candidates"), "raw_payload.raw_candidates")
    if not raw_candidates:
        raise ValueError("raw_payload.raw_candidates must not be empty")

    payload = {
        "title": raw_payload.get("title", "EdenFinTech Imported Scan"),
        "scan_date": raw_payload.get("scan_date", str(date.today())),
        "version": raw_payload.get("version", "v1"),
        "scan_parameters": {
            "scan_mode": _require_str(scan_parameters.get("scan_mode"), "raw_payload.scan_parameters.scan_mode"),
            "focus": _require_str(scan_parameters.get("focus"), "raw_payload.scan_parameters.focus"),
            "api": scan_parameters.get("api", "Imported raw research bundle"),
        },
        "portfolio_context": raw_payload.get("portfolio_context", {"current_positions": 0, "max_positions": 12}),
        "methodology_notes": list(raw_payload.get("methodology_notes", [])),
        "candidates": [import_candidate(_require_dict(candidate, "raw_payload.raw_candidates[]")) for candidate in raw_candidates],
    }
    validate_scan_input(payload)
    return payload


def build_scan_input_file(raw_input_path: Path, json_out: Path | None = None) -> dict:
    raw_payload = load_json(raw_input_path)
    payload = build_scan_input(raw_payload)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2))
    return payload


def raw_scan_template() -> dict:
    structured = scan_input_template()
    candidate = structured["candidates"][0]
    return {
        "title": structured["title"],
        "scan_date": structured["scan_date"],
        "version": structured["version"],
        "scan_parameters": structured["scan_parameters"],
        "portfolio_context": structured["portfolio_context"],
        "methodology_notes": structured["methodology_notes"],
        "raw_candidates": [
            {
                "ticker": candidate["ticker"],
                "cluster_name": candidate["cluster_name"],
                "industry": candidate["industry"],
                "current_price": candidate["current_price"],
                "market_snapshot": {
                    "pct_off_ath": candidate["screening"]["pct_off_ath"],
                },
                "screening_inputs": {
                    "industry_understandable": candidate["screening"]["industry_understandable"],
                    "industry_in_secular_decline": candidate["screening"]["industry_in_secular_decline"],
                    "double_plus_potential": candidate["screening"]["double_plus_potential"],
                    "solvency": {
                        "verdict": candidate["screening"]["checks"]["solvency"]["verdict"],
                        "evidence": candidate["screening"]["checks"]["solvency"]["note"],
                    },
                    "dilution": {
                        "verdict": candidate["screening"]["checks"]["dilution"]["verdict"],
                        "evidence": candidate["screening"]["checks"]["dilution"]["note"],
                    },
                    "revenue_growth": {
                        "verdict": candidate["screening"]["checks"]["revenue_growth"]["verdict"],
                        "evidence": candidate["screening"]["checks"]["revenue_growth"]["note"],
                    },
                    "roic": {
                        "verdict": candidate["screening"]["checks"]["roic"]["verdict"],
                        "evidence": candidate["screening"]["checks"]["roic"]["note"],
                    },
                    "valuation": {
                        "verdict": candidate["screening"]["checks"]["valuation"]["verdict"],
                        "evidence": candidate["screening"]["checks"]["valuation"]["note"],
                    },
                },
                "analysis_inputs": {
                    "margin_trend_gate": candidate["analysis"]["margin_trend_gate"],
                    "final_cluster_status": candidate["analysis"]["final_cluster_status"],
                    "catalyst_classification": candidate["analysis"]["catalyst_classification"],
                    "dominant_risk_type": candidate["analysis"]["dominant_risk_type"],
                    "catalyst_stack": candidate["analysis"]["catalyst_stack"],
                    "invalidation_triggers": candidate["analysis"]["invalidation_triggers"],
                    "decision_memo": candidate["analysis"]["decision_memo"],
                    "issues_and_fixes": candidate["analysis"]["issues_and_fixes"],
                    "setup_pattern": candidate["analysis"]["setup_pattern"],
                    "stretch_case_assumptions": candidate["analysis"]["stretch_case"],
                    "moat_assessment": candidate["analysis"]["moat_assessment"],
                    "thesis_summary": candidate["analysis"]["thesis_summary"],
                    "catalysts": candidate["analysis"]["catalysts"],
                    "key_risks": candidate["analysis"]["key_risks"],
                    "base_case_assumptions": candidate["analysis"]["base_case"],
                    "worst_case_assumptions": candidate["analysis"]["worst_case"],
                    "probability_inputs": candidate["analysis"]["probability"],
                    "exception_candidate": candidate["analysis"]["exception_20_pct_gate"],
                },
                "epistemic_inputs": candidate["epistemic_review"],
            }
        ],
    }


def load_raw_scan_template_text() -> str:
    return json.dumps(raw_scan_template(), indent=2) + "\n"


def structured_scan_template_text() -> str:
    return load_scan_input_template_text()
