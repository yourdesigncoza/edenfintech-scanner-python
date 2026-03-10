from __future__ import annotations

import json
from pathlib import Path

from .structured_analysis import (
    _candidate_evidence_context,
    _fingerprint,
    _raw_bundle_fingerprint,
    validate_structured_analysis,
)


GENERATOR_VERSION = "v1"
MACHINE_STATUS = "MACHINE_DRAFT"


def _evidence_ref(kind: str, path: str, summary: str) -> dict:
    return {
        "kind": kind,
        "path": path,
        "summary": summary,
    }


def _field_provenance(field_path: str, rationale: str, evidence_refs: list[dict]) -> dict:
    return {
        "field_path": field_path,
        "status": MACHINE_STATUS,
        "rationale": rationale,
        "evidence_refs": evidence_refs,
    }


def _claims(raw_candidate: dict, key: str) -> list[str]:
    context = raw_candidate.get("gemini_context", {})
    items = context.get(key, [])
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("claim"), str) and item["claim"].strip():
            result.append(item["claim"].strip())
    return result


def _share_history(raw_candidate: dict) -> list[float]:
    statements = raw_candidate.get("fmp_context", {}).get("annual_income_statements", [])
    values: list[float] = []
    if not isinstance(statements, list):
        return values
    for item in statements:
        if not isinstance(item, dict):
            continue
        shares = item.get("weightedAverageShsOutDil") or item.get("weightedAverageShsOut")
        if isinstance(shares, (int, float)) and shares > 0:
            values.append(float(shares))
    return values


def _risk_type(raw_candidate: dict) -> str:
    risk_text = " ".join(_claims(raw_candidate, "risk_evidence")).lower()
    if any(token in risk_text for token in ["regulatory", "license", "policy", "government"]):
        return "Regulatory/Political"
    if any(token in risk_text for token in ["legal", "lawsuit", "investigation", "fraud"]):
        return "Legal/Investigation"
    if any(token in risk_text for token in ["macro", "cyclical", "recession", "consumer demand"]):
        return "Cyclical/Macro"
    if any(token in risk_text for token in ["single customer", "single point", "sole supplier", "concentration"]):
        return "Structural fragility (SPOF)"
    return "Operational/Financial"


def _screening_inputs(raw_candidate: dict) -> tuple[dict, list[dict]]:
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    pct_off_ath = float(raw_candidate.get("market_snapshot", {}).get("pct_off_ath", 0.0) or 0.0)
    latest_fcf = derived.get("latest_fcf_margin_pct")
    latest_revenue = derived.get("latest_revenue_b")
    trough_revenue = derived.get("trough_revenue_b")
    shares = _share_history(raw_candidate)
    research_text = " ".join(_claims(raw_candidate, "research_notes") + _claims(raw_candidate, "risk_evidence")).lower()

    industry_understandable = raw_candidate.get("industry") not in {None, "", "Unknown Industry"}
    industry_in_secular_decline = any(token in research_text for token in ["secular decline", "shrinking market", "terminal decline"])
    double_plus_potential = pct_off_ath >= 60.0

    if isinstance(latest_fcf, (int, float)) and latest_fcf > 0:
        solvency_verdict = "PASS"
        solvency_note = f"Latest FCF margin is {latest_fcf}%, which supports a provisional solvency pass."
    else:
        solvency_verdict = "BORDERLINE_PASS"
        solvency_note = "Raw bundle lacks strong positive FCF support; solvency needs human confirmation."

    if shares:
        dilution_pct = ((max(shares) - min(shares)) / min(shares)) * 100 if min(shares) > 0 else 0.0
        if dilution_pct <= 5.0:
            dilution_verdict = "PASS"
        elif dilution_pct <= 15.0:
            dilution_verdict = "BORDERLINE_PASS"
        else:
            dilution_verdict = "FAIL"
        dilution_note = f"Diluted share count moved about {round(dilution_pct, 2)}% across available statements."
    else:
        dilution_verdict = "BORDERLINE_PASS"
        dilution_note = "No usable share history was found in the raw bundle."

    if isinstance(latest_revenue, (int, float)) and isinstance(trough_revenue, (int, float)):
        revenue_verdict = "PASS" if latest_revenue >= trough_revenue else "BORDERLINE_PASS"
        revenue_note = f"Latest revenue {latest_revenue}b versus trough revenue {trough_revenue}b."
    else:
        revenue_verdict = "BORDERLINE_PASS"
        revenue_note = "Revenue history is incomplete in the raw bundle."

    roic_verdict = "BORDERLINE_PASS"
    roic_note = "No direct ROIC series exists in the fetched raw bundle; treat this as a machine draft requiring review."

    if pct_off_ath >= 70.0:
        valuation_verdict = "PASS"
    elif pct_off_ath >= 60.0:
        valuation_verdict = "BORDERLINE_PASS"
    else:
        valuation_verdict = "FAIL"
    valuation_note = f"Current price is {round(pct_off_ath, 2)}% below ATH in the fetched market snapshot."

    screening_inputs = {
        "industry_understandable": industry_understandable,
        "industry_in_secular_decline": industry_in_secular_decline,
        "double_plus_potential": double_plus_potential,
        "solvency": {"verdict": solvency_verdict, "evidence": solvency_note},
        "dilution": {"verdict": dilution_verdict, "evidence": dilution_note},
        "revenue_growth": {"verdict": revenue_verdict, "evidence": revenue_note},
        "roic": {"verdict": roic_verdict, "evidence": roic_note},
        "valuation": {"verdict": valuation_verdict, "evidence": valuation_note},
    }
    provenance = [
        _field_provenance(
            "screening_inputs.industry_understandable",
            "Industry understandability is drafted from the presence of a concrete industry label in the raw bundle.",
            [_evidence_ref("fmp_profile", "industry", str(raw_candidate.get("industry")))],
        ),
        _field_provenance(
            "screening_inputs.industry_in_secular_decline",
            "Secular-decline draft is based on whether risk/research snippets explicitly mention decline keywords.",
            [_evidence_ref("gemini_research", "gemini_context.research_notes", research_text or "No decline keywords detected.")],
        ),
        _field_provenance(
            "screening_inputs.double_plus_potential",
            "Double-plus potential draft is based on the fetched percentage off ATH.",
            [_evidence_ref("fmp_market_snapshot", "market_snapshot.pct_off_ath", str(pct_off_ath))],
        ),
        _field_provenance(
            "screening_inputs.solvency",
            "Solvency draft is anchored to latest free cash flow margin.",
            [_evidence_ref("fmp_derived", "fmp_context.derived.latest_fcf_margin_pct", str(latest_fcf))],
        ),
        _field_provenance(
            "screening_inputs.dilution",
            "Dilution draft is anchored to weighted average diluted share history.",
            [_evidence_ref("fmp_income", "fmp_context.annual_income_statements", f"{len(shares)} share observations")],
        ),
        _field_provenance(
            "screening_inputs.revenue_growth",
            "Revenue-growth draft compares latest and trough revenue from FMP-derived history.",
            [_evidence_ref("fmp_derived", "fmp_context.derived.revenue_history_b", f"latest {latest_revenue}, trough {trough_revenue}")],
        ),
        _field_provenance(
            "screening_inputs.roic",
            "ROIC remains a machine draft because the raw bundle does not include a direct ROIC series.",
            [_evidence_ref("fmp_derived", "fmp_context.derived", "No ROIC field available")],
        ),
        _field_provenance(
            "screening_inputs.valuation",
            "Valuation draft is based on the fetched chart break from ATH.",
            [_evidence_ref("fmp_market_snapshot", "market_snapshot.pct_off_ath", str(pct_off_ath))],
        ),
    ]
    return screening_inputs, provenance


def _analysis_inputs(raw_candidate: dict) -> tuple[dict, list[dict]]:
    derived = raw_candidate.get("fmp_context", {}).get("derived", {})
    pct_off_ath = float(raw_candidate.get("market_snapshot", {}).get("pct_off_ath", 0.0) or 0.0)
    latest_revenue = float(derived.get("latest_revenue_b", 3.0) or 3.0)
    trough_revenue = float(derived.get("trough_revenue_b", latest_revenue) or latest_revenue)
    latest_fcf = float(derived.get("latest_fcf_margin_pct", 10.0) or 10.0)
    trough_fcf = float(derived.get("trough_fcf_margin_pct", latest_fcf) or latest_fcf)
    shares_m = float(derived.get("shares_m_latest", 100.0) or 100.0)
    catalysts = _claims(raw_candidate, "catalyst_evidence")
    risks = _claims(raw_candidate, "risk_evidence")
    notes = _claims(raw_candidate, "research_notes")
    moat = _claims(raw_candidate, "moat_observations")
    precedent = _claims(raw_candidate, "precedent_observations")

    margin_trend_gate = "PASS" if latest_fcf >= trough_fcf else "PERMANENT_PASS"
    catalyst_classification = "VALID_CATALYST" if catalysts else "WATCH_ONLY"
    final_cluster_status = "CLEAR_WINNER" if catalysts and pct_off_ath >= 70.0 else "CONDITIONAL_WINNER"
    dominant_risk_type = _risk_type(raw_candidate)
    base_probability_pct = 70.0 if catalysts and latest_fcf > 0 else 60.0 if catalysts else 50.0
    if dominant_risk_type in {"Regulatory/Political", "Legal/Investigation"}:
        base_probability_pct -= 10.0

    issues_and_fixes_array: list[dict] = []
    if risks and catalysts:
        issues_and_fixes_array.append({
            "issue": risks[0],
            "fix": catalysts[0],
            "evidence_status": "ACTION_UNDERWAY",
        })
    elif risks:
        issues_and_fixes_array.append({
            "issue": risks[0],
            "fix": "No fix path identified in fetched sources.",
            "evidence_status": "ANNOUNCED_ONLY",
        })
    else:
        issues_and_fixes_array.append({
            "issue": "No explicit issues surfaced in fetched sources.",
            "fix": "Human review required.",
            "evidence_status": "ANNOUNCED_ONLY",
        })

    catalyst_stack: list[dict] = []
    for idx, cat in enumerate(catalysts):
        cat_type = "HARD" if idx == 0 else "MEDIUM"
        catalyst_stack.append({"type": cat_type, "description": cat, "timeline": "Machine draft"})
    if not catalyst_stack:
        catalyst_stack.append({"type": "SOFT", "description": "No catalysts in fetched sources.", "timeline": "Unknown"})

    invalidation_triggers = [
        {"trigger": risks[0] if risks else "No explicit trigger identified", "evidence": "Machine draft from fetched risk evidence."},
    ]

    decision_memo = {
        "better_than_peer": "Machine draft: requires human assessment of peer comparison.",
        "safer_than_peer": "Machine draft: requires human assessment of safety vs peers.",
        "what_makes_wrong": risks[0] if risks else "Machine draft: no explicit wrong-case identified in fetched sources.",
    }

    setup_pattern = "OTHER"

    stretch_case_assumptions = {
        "revenue_b": latest_revenue,
        "fcf_margin_pct": latest_fcf,
        "multiple": 24.0,
        "shares_m": shares_m,
        "years": 3.0,
        "discount_path": "Machine draft anchored to full margin recovery scenario.",
    }

    moat_assessment = moat[0] if moat else "No strong moat evidence surfaced in fetched sources; human review required."
    thesis_summary = notes[0] if notes else f"{raw_candidate.get('ticker')} remains a machine-generated draft based on fetched FMP and Gemini evidence."
    if catalysts:
        thesis_summary = f"{thesis_summary} Primary catalyst draft: {catalysts[0]}"

    analysis_inputs = {
        "margin_trend_gate": margin_trend_gate,
        "final_cluster_status": final_cluster_status,
        "catalyst_classification": catalyst_classification,
        "dominant_risk_type": dominant_risk_type,
        "catalyst_stack": catalyst_stack,
        "invalidation_triggers": invalidation_triggers,
        "decision_memo": decision_memo,
        "issues_and_fixes": issues_and_fixes_array,
        "setup_pattern": setup_pattern,
        "stretch_case_assumptions": stretch_case_assumptions,
        "moat_assessment": moat_assessment,
        "thesis_summary": thesis_summary,
        "catalysts": catalysts or ["No catalyst evidence surfaced in fetched sources."],
        "key_risks": risks or ["No explicit risk evidence surfaced; human review required."],
        "human_judgment_flags": [
            "Machine-generated structured-analysis draft.",
            *[f"Precedent note: {item}" for item in precedent],
        ],
        "base_case_assumptions": {
            "revenue_b": latest_revenue,
            "fcf_margin_pct": latest_fcf,
            "multiple": 20.0,
            "shares_m": shares_m,
            "years": 3.0,
            "discount_path": "Machine draft anchored to current FMP-derived margin and revenue profile.",
        },
        "worst_case_assumptions": {
            "revenue_b": trough_revenue,
            "fcf_margin_pct": trough_fcf,
            "multiple": 12.0,
            "shares_m": shares_m,
        },
        "probability_inputs": {
            "base_probability_pct": base_probability_pct,
            "base_rate": "Machine draft based on catalyst presence, chart break, and risk type.",
            "likert_adjustments": "Machine draft requires human overwrite before finalization.",
        },
        "exception_candidate": {
            "eligible": False,
            "reason": "Machine draft leaves the exception gate closed until human review.",
        },
    }
    provenance = [
        _field_provenance(
            "analysis_inputs.margin_trend_gate",
            "Margin trend draft compares latest and trough free cash flow margin from FMP-derived history.",
            [_evidence_ref("fmp_derived", "fmp_context.derived.fcf_margin_history_pct", f"latest {latest_fcf}, trough {trough_fcf}")],
        ),
        _field_provenance(
            "analysis_inputs.final_cluster_status",
            "Cluster status draft combines chart break severity and catalyst presence.",
            [
                _evidence_ref("fmp_market_snapshot", "market_snapshot.pct_off_ath", str(pct_off_ath)),
                _evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", f"{len(catalysts)} catalyst snippets"),
            ],
        ),
        _field_provenance(
            "analysis_inputs.catalyst_classification",
            "Catalyst classification draft is anchored to whether sourced catalyst snippets exist.",
            [_evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", "; ".join(catalysts) or "none")],
        ),
        _field_provenance(
            "analysis_inputs.dominant_risk_type",
            "Risk type draft is inferred from keywords in risk snippets.",
            [_evidence_ref("gemini_risk", "gemini_context.risk_evidence", "; ".join(risks) or "none")],
        ),
        _field_provenance(
            "analysis_inputs.catalyst_stack",
            "Catalyst stack draft maps fetched catalyst snippets to typed entries.",
            [_evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", f"{len(catalysts)} snippets")],
        ),
        _field_provenance(
            "analysis_inputs.invalidation_triggers",
            "Invalidation triggers draft derived from top risk snippet.",
            [_evidence_ref("gemini_risk", "gemini_context.risk_evidence", risks[0] if risks else "none")],
        ),
        _field_provenance(
            "analysis_inputs.decision_memo",
            "Decision memo draft requires human assessment of peer comparison.",
            [_evidence_ref("machine_rule", "analysis_inputs.decision_memo", "Machine draft default")],
        ),
        _field_provenance(
            "analysis_inputs.issues_and_fixes",
            "Issues-and-fixes draft summarizes the top risk and catalyst snippets as structured entries.",
            [
                _evidence_ref("gemini_risk", "gemini_context.risk_evidence", risks[0] if risks else "none"),
                _evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", catalysts[0] if catalysts else "none"),
            ],
        ),
        _field_provenance(
            "analysis_inputs.setup_pattern",
            "Setup pattern draft defaults to OTHER until human classification.",
            [_evidence_ref("machine_rule", "analysis_inputs.setup_pattern", "Machine draft default: OTHER")],
        ),
        _field_provenance(
            "analysis_inputs.stretch_case_assumptions",
            "Stretch case draft is anchored to latest FMP-derived revenue and margin with higher multiple.",
            [
                _evidence_ref("fmp_derived", "fmp_context.derived.latest_revenue_b", str(latest_revenue)),
                _evidence_ref("fmp_derived", "fmp_context.derived.latest_fcf_margin_pct", str(latest_fcf)),
            ],
        ),
        _field_provenance(
            "analysis_inputs.moat_assessment",
            "Moat assessment draft is anchored to moat observation snippets.",
            [_evidence_ref("gemini_moat", "gemini_context.moat_observations", moat[0] if moat else "none")],
        ),
        _field_provenance(
            "analysis_inputs.thesis_summary",
            "Thesis summary draft combines the lead research note with the first catalyst snippet.",
            [
                _evidence_ref("gemini_research", "gemini_context.research_notes", notes[0] if notes else "none"),
                _evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", catalysts[0] if catalysts else "none"),
            ],
        ),
        _field_provenance(
            "analysis_inputs.catalysts",
            "Catalyst list draft is a direct projection of sourced catalyst snippets.",
            [_evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", f"{len(catalysts)} snippets")],
        ),
        _field_provenance(
            "analysis_inputs.key_risks",
            "Risk list draft is a direct projection of sourced risk snippets.",
            [_evidence_ref("gemini_risk", "gemini_context.risk_evidence", f"{len(risks)} snippets")],
        ),
        _field_provenance(
            "analysis_inputs.base_case_assumptions",
            "Base-case draft is anchored to latest FMP-derived revenue, FCF margin, and share count.",
            [
                _evidence_ref("fmp_derived", "fmp_context.derived.latest_revenue_b", str(latest_revenue)),
                _evidence_ref("fmp_derived", "fmp_context.derived.latest_fcf_margin_pct", str(latest_fcf)),
                _evidence_ref("fmp_derived", "fmp_context.derived.shares_m_latest", str(shares_m)),
            ],
        ),
        _field_provenance(
            "analysis_inputs.worst_case_assumptions",
            "Worst-case draft is anchored to trough FMP-derived revenue and margin.",
            [
                _evidence_ref("fmp_derived", "fmp_context.derived.trough_revenue_b", str(trough_revenue)),
                _evidence_ref("fmp_derived", "fmp_context.derived.trough_fcf_margin_pct", str(trough_fcf)),
            ],
        ),
        _field_provenance(
            "analysis_inputs.probability_inputs",
            "Probability draft is based on catalyst presence, profitability, and inferred risk type.",
            [
                _evidence_ref("gemini_catalyst", "gemini_context.catalyst_evidence", f"{len(catalysts)} snippets"),
                _evidence_ref("fmp_derived", "fmp_context.derived.latest_fcf_margin_pct", str(latest_fcf)),
                _evidence_ref("gemini_risk", "gemini_context.risk_evidence", dominant_risk_type),
            ],
        ),
        _field_provenance(
            "analysis_inputs.exception_candidate",
            "Exception gate remains closed by default in the machine draft.",
            [_evidence_ref("machine_rule", "analysis_inputs.exception_candidate", "Machine draft default: not eligible")],
        ),
    ]
    return analysis_inputs, provenance


def _epistemic_inputs(raw_candidate: dict, dominant_risk_type: str) -> tuple[dict, list[dict]]:
    precedent = _claims(raw_candidate, "precedent_observations")
    anchors = _claims(raw_candidate, "epistemic_anchors")
    risks = _claims(raw_candidate, "risk_evidence")

    def pcs(answer: str, justification: str, evidence: str) -> dict:
        return {
            "answer": answer,
            "justification": justification,
            "evidence": evidence,
        }

    q1_answer = "Yes" if dominant_risk_type == "Operational/Financial" else "No"
    q2_answer = "No" if dominant_risk_type in {"Regulatory/Political", "Legal/Investigation"} else "Yes"
    q3_answer = "Yes" if precedent else "No"
    q4_answer = "No" if dominant_risk_type == "Legal/Investigation" else "Yes"
    q5_answer = "No" if dominant_risk_type == "Cyclical/Macro" else "Yes"

    epistemic_inputs = {
        "q1_operational": pcs(
            q1_answer,
            "Machine draft maps the dominant risk type into the PCS operational question.",
            anchors[0] if anchors else (risks[0] if risks else "No specific operational anchor was found."),
        ),
        "q2_regulatory": pcs(
            q2_answer,
            "Machine draft answers No when risk snippets imply regulatory or legal exposure; otherwise Yes.",
            risks[0] if risks else "No regulatory warning surfaced in fetched snippets.",
        ),
        "q3_precedent": pcs(
            q3_answer,
            "Machine draft answers Yes only when precedent observations are present.",
            precedent[0] if precedent else "No precedent observation surfaced in fetched snippets.",
        ),
        "q4_nonbinary": pcs(
            q4_answer,
            "Machine draft treats legal/investigation risk as more binary than operational or cyclical drift.",
            risks[0] if risks else "No binary-risk warning surfaced in fetched snippets.",
        ),
        "q5_macro": pcs(
            q5_answer,
            "Machine draft answers No only when macro/cyclical language dominates the risk snippets.",
            risks[0] if risks else "No macro warning surfaced in fetched snippets.",
        ),
    }
    provenance = [
        _field_provenance(
            f"epistemic_inputs.{key}",
            "PCS draft generated from precedent, anchor, and risk snippets plus inferred risk type.",
            [
                _evidence_ref("gemini_precedent", "gemini_context.precedent_observations", precedent[0] if precedent else "none"),
                _evidence_ref("gemini_anchor", "gemini_context.epistemic_anchors", anchors[0] if anchors else "none"),
                _evidence_ref("gemini_risk", "gemini_context.risk_evidence", risks[0] if risks else dominant_risk_type),
            ],
        )
        for key in ["q1_operational", "q2_regulatory", "q3_precedent", "q4_nonbinary", "q5_macro"]
    ]
    return epistemic_inputs, provenance


def generate_structured_analysis_draft(raw_bundle: dict) -> dict:
    raw_candidates = raw_bundle.get("raw_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("raw_bundle.raw_candidates must be a non-empty list")

    structured_candidates: list[dict] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict) or not isinstance(raw_candidate.get("ticker"), str):
            raise ValueError("raw_bundle.raw_candidates[] must include ticker")
        evidence_context = _candidate_evidence_context(raw_candidate)
        screening_inputs, screening_provenance = _screening_inputs(raw_candidate)
        analysis_inputs, analysis_provenance = _analysis_inputs(raw_candidate)
        epistemic_inputs, epistemic_provenance = _epistemic_inputs(raw_candidate, analysis_inputs["dominant_risk_type"])
        structured_candidates.append(
            {
                "ticker": raw_candidate["ticker"],
                "evidence_context": evidence_context,
                "evidence_fingerprint": _fingerprint(evidence_context),
                "field_provenance": screening_provenance + analysis_provenance + epistemic_provenance,
                "screening_inputs": screening_inputs,
                "analysis_inputs": analysis_inputs,
                "epistemic_inputs": epistemic_inputs,
            }
        )

    scan_parameters = raw_bundle.get("scan_parameters", {})
    payload = {
        "title": f"Machine Draft Structured Analysis Overlay - {raw_bundle.get('title', 'EdenFinTech')}",
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
        "completion_note": "Machine-generated draft only. Human review and explicit finalization are required before apply.",
        "generation_metadata": {
            "source": "field_generation.py",
            "generator_version": GENERATOR_VERSION,
            "raw_bundle_fingerprint": _raw_bundle_fingerprint(raw_bundle),
            "notes": [
                "Machine-generated fields are marked through field_provenance.status=MACHINE_DRAFT.",
                "This draft is auditable but not final; keep completion_status as DRAFT until a human finalization step exists.",
            ],
        },
        "methodology_notes": [
            "This overlay was machine-generated from merged raw evidence and is intentionally left in DRAFT status.",
            "Field-level provenance is required before any human finalization step.",
        ],
        "structured_candidates": structured_candidates,
    }
    validate_structured_analysis(payload)
    return payload


def build_structured_analysis_draft_file(raw_bundle_path: Path, json_out: Path | None = None) -> dict:
    payload = generate_structured_analysis_draft(json.loads(raw_bundle_path.read_text()))
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2))
    return payload
