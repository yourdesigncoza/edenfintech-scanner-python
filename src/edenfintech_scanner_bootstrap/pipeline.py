from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .assets import load_json, load_text, methodology_root, scan_input_schema_path, scan_report_schema_path
from .config import AppConfig
from .judge import codex_judge
from .reporting import render_scan_markdown, write_execution_log
from .scoring import (
    EpistemicOutcome,
    ScoreBreakdown,
    cagr_pct,
    confidence_cap_band,
    decision_score,
    downside_pct,
    epistemic_outcome,
    floor_price,
    normalize_probability_band,
    score_to_size_band,
    valuation_target_price,
)
from .schemas import SchemaValidationError, validate_instance


CHECK_ORDER = ["solvency", "dilution", "revenue_growth", "roic", "valuation"]
CHECK_LABELS = {
    "solvency": "Solvency",
    "dilution": "Dilution",
    "revenue_growth": "Revenue Growth",
    "roic": "ROIC",
    "valuation": "Valuation",
}
VALID_VERDICTS = {"PASS", "BORDERLINE_PASS", "FAIL"}
VALID_ANSWERS = {"STRONG", "MODERATE", "WEAK"}
VALID_SCAN_MODES = {"full_nyse", "sector", "specific_tickers"}


@dataclass(frozen=True)
class ScanArtifacts:
    report_json: dict
    report_markdown: str
    execution_log: dict
    judge: dict


def _require_keys(obj: dict, keys: list[str], label: str) -> None:
    for key in keys:
        if key not in obj:
            raise ValueError(f"{label} missing required key: {key}")


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _as_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _as_float(value: object, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _load_template() -> dict:
    return load_json(methodology_root() / "scan-report.template.json")


def _load_schema() -> dict:
    return load_json(scan_report_schema_path())


def _load_input_schema() -> dict:
    return load_json(scan_input_schema_path())


def _step2_failure(candidate: dict) -> tuple[str, str] | None:
    checks = _require_dict(candidate["screening"]["checks"], f"{candidate['ticker']}.screening.checks")
    for check_name in CHECK_ORDER:
        check = _require_dict(checks.get(check_name), f"{candidate['ticker']}.screening.checks.{check_name}")
        verdict = _require_nonempty_string(check.get("verdict"), f"{candidate['ticker']}.{check_name}.verdict")
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"{candidate['ticker']}.{check_name}.verdict invalid: {verdict}")
        if verdict == "FAIL":
            return check_name, _require_nonempty_string(check.get("note"), f"{candidate['ticker']}.{check_name}.note")
    return None


def _screen_candidate(candidate: dict) -> tuple[bool, dict | None]:
    screening = _require_dict(candidate.get("screening"), f"{candidate['ticker']}.screening")
    pct_off_ath = _as_float(screening.get("pct_off_ath"), f"{candidate['ticker']}.screening.pct_off_ath")
    if pct_off_ath < 60.0:
        return False, {
            "ticker": candidate["ticker"],
            "failed_at": "Step 1 - Broken Chart",
            "reason": f"Only {pct_off_ath:.1f}% off ATH; minimum threshold is 60%.",
        }

    if not _as_bool(screening.get("industry_understandable"), f"{candidate['ticker']}.screening.industry_understandable"):
        return False, {
            "ticker": candidate["ticker"],
            "failed_at": "Step 1 - Industry Understandability",
            "reason": "Industry is not understandable enough to proceed under methodology rules.",
        }

    if _as_bool(screening.get("industry_in_secular_decline"), f"{candidate['ticker']}.screening.industry_in_secular_decline"):
        return False, {
            "ticker": candidate["ticker"],
            "failed_at": "Step 1 - Secular Decline",
            "reason": "Industry is in secular decline and is rejected before deeper work.",
        }

    if not _as_bool(screening.get("double_plus_potential"), f"{candidate['ticker']}.screening.double_plus_potential"):
        return False, {
            "ticker": candidate["ticker"],
            "failed_at": "Step 1 - Double Plus Potential",
            "reason": "Candidate does not show plausible 100%+ upside over 2-3 years.",
        }

    failed_check = _step2_failure(candidate)
    if failed_check is not None:
        check_name, note = failed_check
        return False, {
            "ticker": candidate["ticker"],
            "failed_at": f"Step 2 - {CHECK_LABELS[check_name]}",
            "reason": note,
        }

    return True, None


def _validate_catalyst_stack(candidate: dict, ticker: str) -> None:
    analysis = candidate.get("analysis", {})
    catalyst_stack = analysis.get("catalyst_stack", [])
    hard_medium_count = sum(
        1 for entry in catalyst_stack if entry.get("type") in ("HARD", "MEDIUM")
    )
    if hard_medium_count == 0:
        raise ValueError(
            f"{ticker}: catalyst_stack contains zero HARD/MEDIUM entries; "
            f"at least one actionable catalyst is required"
        )


def _validate_issues_and_fixes(candidate: dict, ticker: str) -> None:
    analysis = candidate.get("analysis", {})
    issues = analysis.get("issues_and_fixes", [])
    if isinstance(issues, list) and issues:
        all_announced = all(
            entry.get("evidence_status") == "ANNOUNCED_ONLY" for entry in issues
        )
        if all_announced:
            raise ValueError(
                f"{ticker}: all issues_and_fixes have evidence_status ANNOUNCED_ONLY; "
                f"at least one must show ACTION_UNDERWAY, EARLY_RESULTS_VISIBLE, or PROVEN"
            )


def _validate_pcs_answers(candidate: dict) -> dict[str, dict[str, str]]:
    pcs = _require_dict(candidate.get("epistemic_review"), f"{candidate['ticker']}.epistemic_review")
    answers: dict[str, dict[str, str]] = {}
    for key in ["q1_operational_feasibility", "q2_risk_bounded", "q3_precedent_grounded", "q4_downside_steelmanned", "q5_catalyst_concrete"]:
        check = _require_dict(pcs.get(key), f"{candidate['ticker']}.epistemic_review.{key}")
        answer = _require_nonempty_string(check.get("answer"), f"{candidate['ticker']}.epistemic_review.{key}.answer")
        if answer not in VALID_ANSWERS:
            raise ValueError(f"{candidate['ticker']}.epistemic_review.{key}.answer invalid: {answer}")
        justification = _require_nonempty_string(
            check.get("justification"),
            f"{candidate['ticker']}.epistemic_review.{key}.justification",
        )
        evidence = _require_nonempty_string(check.get("evidence"), f"{candidate['ticker']}.epistemic_review.{key}.evidence")
        answers[key] = {"answer": answer, "justification": justification, "evidence": evidence}
    return answers


def _base_case_details(candidate: dict) -> tuple[dict, float]:
    analysis = _require_dict(candidate.get("analysis"), f"{candidate['ticker']}.analysis")
    base_case = _require_dict(analysis.get("base_case"), f"{candidate['ticker']}.analysis.base_case")
    current_price = _as_float(candidate.get("current_price"), f"{candidate['ticker']}.current_price")
    years = _as_float(base_case.get("years"), f"{candidate['ticker']}.analysis.base_case.years")
    target_price = valuation_target_price(
        _as_float(base_case.get("revenue_b"), f"{candidate['ticker']}.analysis.base_case.revenue_b"),
        _as_float(base_case.get("fcf_margin_pct"), f"{candidate['ticker']}.analysis.base_case.fcf_margin_pct"),
        _as_float(base_case.get("multiple"), f"{candidate['ticker']}.analysis.base_case.multiple"),
        _as_float(base_case.get("shares_m"), f"{candidate['ticker']}.analysis.base_case.shares_m"),
    )
    implied_cagr = cagr_pct(current_price, target_price, years)
    result = {
        "revenue_b": _as_float(base_case["revenue_b"], f"{candidate['ticker']}.analysis.base_case.revenue_b"),
        "fcf_margin_pct": _as_float(base_case["fcf_margin_pct"], f"{candidate['ticker']}.analysis.base_case.fcf_margin_pct"),
        "multiple": _as_float(base_case["multiple"], f"{candidate['ticker']}.analysis.base_case.multiple"),
        "shares_m": _as_float(base_case["shares_m"], f"{candidate['ticker']}.analysis.base_case.shares_m"),
        "target_price": target_price,
        "cagr_pct": implied_cagr,
        "years": years,
    }
    if "discount_path" in base_case:
        result["discount_path"] = base_case["discount_path"]
    return result, implied_cagr


def _worst_case_details(candidate: dict) -> tuple[dict, float]:
    analysis = _require_dict(candidate["analysis"], f"{candidate['ticker']}.analysis")
    worst_case = _require_dict(analysis.get("worst_case"), f"{candidate['ticker']}.analysis.worst_case")
    current_price = _as_float(candidate.get("current_price"), f"{candidate['ticker']}.current_price")
    floor_value = floor_price(
        _as_float(worst_case.get("revenue_b"), f"{candidate['ticker']}.analysis.worst_case.revenue_b"),
        _as_float(worst_case.get("fcf_margin_pct"), f"{candidate['ticker']}.analysis.worst_case.fcf_margin_pct"),
        _as_float(worst_case.get("multiple"), f"{candidate['ticker']}.analysis.worst_case.multiple"),
        _as_float(worst_case.get("shares_m"), f"{candidate['ticker']}.analysis.worst_case.shares_m"),
    )
    downside = downside_pct(current_price, floor_value)
    result = {
        "revenue_b": _as_float(worst_case["revenue_b"], f"{candidate['ticker']}.analysis.worst_case.revenue_b"),
        "fcf_margin_pct": _as_float(worst_case["fcf_margin_pct"], f"{candidate['ticker']}.analysis.worst_case.fcf_margin_pct"),
        "multiple": _as_float(worst_case["multiple"], f"{candidate['ticker']}.analysis.worst_case.multiple"),
        "shares_m": _as_float(worst_case["shares_m"], f"{candidate['ticker']}.analysis.worst_case.shares_m"),
        "floor_price": floor_value,
        "downside_pct": downside,
    }
    if "trough_path" in worst_case:
        result["trough_path"] = worst_case["trough_path"]
    if "tbv_crosscheck" in worst_case:
        result["tbv_crosscheck"] = worst_case["tbv_crosscheck"]
    return result, downside


def _probability_details(candidate: dict) -> tuple[dict, float]:
    probability = _require_dict(candidate["analysis"].get("probability"), f"{candidate['ticker']}.analysis.probability")
    base_probability = _as_float(
        probability.get("base_probability_pct"),
        f"{candidate['ticker']}.analysis.probability.base_probability_pct",
    )
    normalized = normalize_probability_band(base_probability)
    result = {
        "raw_before_band": base_probability,
        "final_band": f"{int(normalized)}%",
    }
    for optional_key in ["base_rate", "likert_adjustments", "ceilings_applied", "threshold_proximity_warning"]:
        if optional_key in probability:
            result[optional_key] = probability[optional_key]
    return result, normalized


def _analysis_rejection_packet(
    candidate: dict,
    rejection_reason: str,
    *,
    base_case: dict | None = None,
    worst_case: dict | None = None,
    probability: dict | None = None,
    score: dict | None = None,
    epi: dict | None = None,
) -> dict:
    packet: dict = {
        "ticker": candidate["ticker"],
        "rejection_reason": rejection_reason,
    }
    if base_case is not None:
        packet["base_case"] = base_case
    if worst_case is not None:
        packet["worst_case"] = worst_case
    if probability is not None:
        packet["probability"] = probability
    if score is not None:
        packet["score"] = score
    if epi is not None:
        packet["epistemic_confidence"] = epi
    for optional_key in ["thesis_summary", "catalysts", "key_risks", "structural_diagnosis", "key_financials", "source_research", "thesis_invalidation"]:
        if optional_key in candidate["analysis"]:
            packet[optional_key] = candidate["analysis"][optional_key]
    return packet


def _ranked_candidate_packet(
    candidate: dict,
    rank: int,
    base_case: dict,
    worst_case: dict,
    probability: dict,
    pre_score: ScoreBreakdown,
    post_score: ScoreBreakdown,
    epi_result: EpistemicOutcome,
    pcs_answers: dict[str, dict[str, str]],
) -> dict:
    analysis = candidate["analysis"]
    confidence_cap = confidence_cap_band(epi_result.adjusted_confidence)
    size_band = score_to_size_band(post_score.total_score)
    packet: dict = {
        "rank": rank,
        "ticker": candidate["ticker"],
        "cluster_name": candidate["cluster_name"],
        "analysis_status": "ADVANCE_TO_EPISTEMIC",
        "final_cluster_status": analysis["final_cluster_status"],
        "score": {
            "pre_epistemic": pre_score.__dict__,
            "post_epistemic": {
                **post_score.__dict__,
                "effective_probability": epi_result.effective_probability,
            },
        },
        "position_size": {
            "score_band": size_band,
            "confidence_cap": confidence_cap,
            "binary_override": epi_result.binary_override,
        },
        "base_case": base_case,
        "worst_case": worst_case,
        "probability": probability,
        "epistemic_confidence": {
            **pcs_answers,
            "no_count": epi_result.no_count,
            "raw_confidence": epi_result.raw_confidence,
            "risk_type": analysis["dominant_risk_type"],
            "risk_type_friction": epi_result.risk_type_friction,
            "friction_note": epi_result.friction_note,
            "adjusted_confidence": epi_result.adjusted_confidence,
            "multiplier": epi_result.multiplier,
            "effective_probability": epi_result.effective_probability,
            "confidence_cap_pct": confidence_cap,
            "binary_override": epi_result.binary_override,
            "threshold_proximity_warning": probability.get("threshold_proximity_warning"),
            "human_judgment_flags": list(analysis.get("human_judgment_flags", [])),
        },
    }
    for optional_key in ["thesis_summary", "catalysts", "key_risks", "issues_and_fixes", "moat_assessment", "source_research", "thesis_invalidation"]:
        if optional_key in analysis:
            packet[optional_key] = analysis[optional_key]
    return packet


def rank_within_cluster(candidates: list[dict]) -> list[dict]:
    """Deterministic within-cluster peer ranking per codex priority order.

    Scores each candidate on:
      - Balance sheet strength (40%): debt_to_equity, solvency verdict
      - Margin durability (25%): fcf_margin trend, ROIC median
      - Catalyst capture (20%): HARD > MEDIUM > SOFT count
      - Optionality/upside (15%): CAGR spread (stretch - worst)

    Assigns final_cluster_status and ranking_rationale.
    Returns candidates with cluster_rank populated.
    """
    if len(candidates) < 2:
        for c in candidates:
            c.setdefault("peer_comparison", {})
            c["peer_comparison"]["cluster_rank"] = 1
            c["peer_comparison"]["ranking_rationale"] = "Only candidate in cluster"
        return candidates

    scored: list[tuple[float, dict]] = []
    for candidate in candidates:
        analysis = candidate.get("analysis", {})
        screening = candidate.get("screening", {})
        checks = screening.get("checks", {})

        # Balance sheet strength (40%)
        solvency = checks.get("solvency", {}).get("verdict", "FAIL")
        balance_score = 1.0 if solvency == "PASS" else (0.5 if solvency == "BORDERLINE_PASS" else 0.0)

        worst_case = analysis.get("worst_case", {})
        # Lower floor downside = stronger balance sheet support
        downside = abs(worst_case.get("downside_pct", 50.0)) if "downside_pct" in worst_case else 50.0
        balance_score += max(0.0, 1.0 - downside / 100.0)
        balance_component = (balance_score / 2.0) * 0.40

        # Margin durability (25%)
        margin_gate = analysis.get("margin_trend_gate", "PASS")
        margin_score = 0.0 if margin_gate == "PERMANENT_PASS" else 1.0
        # Boost if FCF margin data is positive
        wc_fcf = worst_case.get("fcf_margin_pct", 0.0)
        if isinstance(wc_fcf, (int, float)) and wc_fcf > 0:
            margin_score += min(wc_fcf / 20.0, 1.0)
        margin_component = (margin_score / 2.0) * 0.25

        # Catalyst capture (20%)
        catalyst_stack = analysis.get("catalyst_stack", [])
        hard_count = sum(1 for c in catalyst_stack if c.get("type") == "HARD")
        medium_count = sum(1 for c in catalyst_stack if c.get("type") == "MEDIUM")
        catalyst_score = min((hard_count * 2 + medium_count) / 4.0, 1.0)
        catalyst_component = catalyst_score * 0.20

        # Optionality/upside (15%)
        base_case = analysis.get("base_case", {})
        base_cagr = base_case.get("cagr_pct", 0.0)
        if not isinstance(base_cagr, (int, float)):
            base_cagr = 0.0
        stretch = analysis.get("stretch_case", {})
        stretch_cagr = stretch.get("cagr_pct", base_cagr)
        if not isinstance(stretch_cagr, (int, float)):
            stretch_cagr = base_cagr
        upside_spread = max(stretch_cagr - base_cagr, 0.0)
        upside_score = min(upside_spread / 30.0, 1.0)
        upside_component = upside_score * 0.15

        total = balance_component + margin_component + catalyst_component + upside_component
        scored.append((total, candidate))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0] if scored else 0.0

    for rank_idx, (score, candidate) in enumerate(scored, start=1):
        candidate.setdefault("peer_comparison", {})
        candidate["peer_comparison"]["cluster_rank"] = rank_idx
        candidate["peer_comparison"]["cluster_score"] = round(score, 4)

        # Assign final_cluster_status based on relative score
        if top_score > 0:
            pct_of_top = score / top_score
        else:
            pct_of_top = 1.0

        analysis = candidate.get("analysis", {})
        margin_gate = analysis.get("margin_trend_gate", "PASS")

        if margin_gate == "PERMANENT_PASS":
            status = "ELIMINATED"
            rationale = "5yr margin decline triggers elimination"
        elif rank_idx == 1:
            status = "CLEAR_WINNER"
            rationale = f"Top scorer ({score:.3f})"
        elif pct_of_top >= 0.90:
            status = "CONDITIONAL_WINNER"
            rationale = f"Within 10% of top scorer ({pct_of_top:.0%})"
        else:
            # Check Keep/Cut: keep backup if passed all filters AND materially higher returns
            screening = candidate.get("screening", {})
            all_passed = all(
                screening.get("checks", {}).get(ck, {}).get("verdict") in ("PASS", "BORDERLINE_PASS")
                for ck in CHECK_ORDER
            )
            base_cagr = analysis.get("base_case", {}).get("cagr_pct", 0.0)
            if not isinstance(base_cagr, (int, float)):
                base_cagr = 0.0

            if all_passed and base_cagr >= 30.0:
                status = "LOWER_PRIORITY"
                rationale = f"Backup: passed filters, CAGR {base_cagr:.1f}%"
            elif len(scored) < 3:
                # Few alternatives — keep everyone who passed
                status = "LOWER_PRIORITY"
                rationale = f"Kept: <3 candidates in cluster"
            else:
                status = "ELIMINATED"
                rationale = f"Cut: inferior ({pct_of_top:.0%} of top) with alternatives available"

        candidate["peer_comparison"]["ranking_rationale"] = rationale
        candidate["peer_comparison"]["final_cluster_status"] = status

    return [c for _, c in scored]


def validate_scan_input(payload: dict) -> None:
    try:
        validate_instance(payload, _load_input_schema())
    except SchemaValidationError as exc:
        raise ValueError(f"scan_input schema validation failed: {exc}") from exc

    _require_keys(payload, ["scan_parameters", "candidates"], "scan_input")
    scan_parameters = _require_dict(payload["scan_parameters"], "scan_parameters")
    _require_keys(scan_parameters, ["scan_mode", "focus"], "scan_parameters")
    scan_mode = _require_nonempty_string(scan_parameters["scan_mode"], "scan_parameters.scan_mode")
    if scan_mode not in VALID_SCAN_MODES:
        raise ValueError(f"scan_parameters.scan_mode invalid: {scan_mode}")

    candidates = _require_list(payload["candidates"], "scan_input.candidates")
    if not candidates:
        raise ValueError("scan_input.candidates must not be empty")

    for idx, candidate in enumerate(candidates):
        item = _require_dict(candidate, f"candidates[{idx}]")
        _require_keys(item, ["ticker", "cluster_name", "industry", "current_price", "screening"], f"candidates[{idx}]")
        _require_nonempty_string(item["ticker"], f"candidates[{idx}].ticker")
        _require_nonempty_string(item["cluster_name"], f"candidates[{idx}].cluster_name")
        _require_nonempty_string(item["industry"], f"candidates[{idx}].industry")
        _as_float(item["current_price"], f"candidates[{idx}].current_price")
        screening_passed, _ = _screen_candidate(item)
        if screening_passed:
            _require_keys(item, ["analysis", "epistemic_review"], f"candidates[{idx}]")
            _base_case_details(item)
            _worst_case_details(item)
            _probability_details(item)
            _validate_pcs_answers(item)
            _validate_catalyst_stack(item, item["ticker"])
            _validate_issues_and_fixes(item, item["ticker"])


def validate_scan_report(report: dict) -> None:
    try:
        validate_instance(report, _load_schema())
    except SchemaValidationError as exc:
        raise ValueError(f"scan_report schema validation failed: {exc}") from exc


def _build_current_holding_overlays(
    portfolio_context: dict,
    ranked_candidates: list[dict],
    pending_human_review: list[dict],
    rejected_screening: list[dict],
    rejected_analysis: list[dict],
) -> list[dict]:
    holdings = _require_list(portfolio_context.get("current_holdings", []), "portfolio_context.current_holdings")
    if not holdings:
        return []

    ranked_by_ticker = {item["ticker"]: item for item in ranked_candidates}
    pending_by_ticker = {item["ticker"]: item for item in pending_human_review}
    screen_reject_by_ticker = {item["ticker"]: item for item in rejected_screening}
    analysis_reject_by_ticker = {item["ticker"]: item for item in rejected_analysis}
    overlays: list[dict] = []

    for idx, holding in enumerate(holdings):
        item = _require_dict(holding, f"portfolio_context.current_holdings[{idx}]")
        ticker = _require_nonempty_string(item.get("ticker"), f"portfolio_context.current_holdings[{idx}].ticker")
        weight = item.get("current_weight_pct")
        weight_prefix = f"Current weight {weight}%." if isinstance(weight, (int, float)) else "Current holding."
        note = item.get("note")

        if ticker in ranked_by_ticker:
            reason = f"{weight_prefix} Candidate ranked in current scan and remains eligible for new capital."
            if note:
                reason = f"{reason} {note}"
            overlays.append(
                {
                    "ticker": ticker,
                    "status_in_scan": "RANKED",
                    "new_capital_decision": "ADD",
                    "existing_position_action": item.get("existing_position_action", "HOLD"),
                    "reason": reason,
                }
            )
            continue

        if ticker in analysis_reject_by_ticker:
            reason = f"{weight_prefix} Rejected at analysis: {analysis_reject_by_ticker[ticker]['rejection_reason']}"
            if note:
                reason = f"{reason} {note}"
            overlays.append(
                {
                    "ticker": ticker,
                    "status_in_scan": "REJECTED_AT_ANALYSIS",
                    "new_capital_decision": "DO_NOT_ADD",
                    "existing_position_action": item.get("existing_position_action", "HOLD_AND_MONITOR"),
                    "reason": reason,
                }
            )
            continue

        if ticker in pending_by_ticker:
            reason = f"{weight_prefix} Pending human review: {pending_by_ticker[ticker]['reason']}"
            if note:
                reason = f"{reason} {note}"
            overlays.append(
                {
                    "ticker": ticker,
                    "status_in_scan": "PENDING_HUMAN_REVIEW",
                    "new_capital_decision": "DO_NOT_ADD",
                    "existing_position_action": item.get("existing_position_action", "HOLD_AND_MONITOR"),
                    "reason": reason,
                }
            )
            continue

        if ticker in screen_reject_by_ticker:
            reason = f"{weight_prefix} Rejected at screening: {screen_reject_by_ticker[ticker]['reason']}"
            if note:
                reason = f"{reason} {note}"
            overlays.append(
                {
                    "ticker": ticker,
                    "status_in_scan": "REJECTED_AT_SCREENING",
                    "new_capital_decision": "DO_NOT_ADD",
                    "existing_position_action": item.get("existing_position_action", "HOLD"),
                    "reason": reason,
                }
            )
            continue

        reason = f"{weight_prefix} This holding was not part of the current scan scope, so the scan made no new methodology conclusion about it."
        if note:
            reason = f"{reason} {note}"
        overlays.append(
            {
                "ticker": ticker,
                "status_in_scan": "NOT_IN_SCAN_SCOPE",
                "new_capital_decision": "DO_NOT_ADD",
                "existing_position_action": item.get("existing_position_action", "HOLD"),
                "reason": reason,
            }
        )

    return overlays


def run_scan(
    payload: dict,
    *,
    judge_config: AppConfig | None = None,
    judge_transport=None,
) -> ScanArtifacts:
    return run_scan_with_judge(payload, judge_config=judge_config, judge_transport=judge_transport)


def run_scan_with_judge(
    payload: dict,
    *,
    judge_config: AppConfig | None = None,
    judge_transport=None,
) -> ScanArtifacts:
    validate_scan_input(payload)
    template = _load_template()

    scan_parameters = payload["scan_parameters"]
    template["title"] = payload.get("title", f"EdenFinTech Stock Scan - {scan_parameters['focus']}")
    template["date"] = payload.get("scan_date", str(date.today()))
    template["version"] = payload.get("version", "v1")
    template["scan_parameters"] = {
        "universe": {
            "full_nyse": "NYSE",
            "sector": "Sector",
            "specific_tickers": "Specific tickers",
        }[scan_parameters["scan_mode"]],
        "focus": scan_parameters["focus"],
        "stocks_scanned": len(payload["candidates"]),
        "api": scan_parameters.get("api", "Structured research input"),
    }

    rejected_screening: list[dict] = []
    rejected_analysis: list[dict] = []
    pending_human_review: list[dict] = []
    ranked_candidates: list[dict] = []
    execution_log_entries: list[str] = []

    survivors: list[dict] = []
    for candidate in payload["candidates"]:
        passed, rejection = _screen_candidate(candidate)
        if passed:
            survivors.append(candidate)
            execution_log_entries.append(f"{candidate['ticker']}: passed screening")
        else:
            rejected_screening.append(rejection)
            execution_log_entries.append(f"{candidate['ticker']}: rejected at screening ({rejection['failed_at']})")

    for candidate in survivors:
        analysis = candidate["analysis"]
        base_case, base_cagr = _base_case_details(candidate)
        worst_case, downside = _worst_case_details(candidate)
        probability, normalized_probability = _probability_details(candidate)

        # Thesis invalidation: weak_evidence penalty (LLM-confirmed only)
        thesis_inv = analysis.get("thesis_invalidation")
        if thesis_inv:
            weak_count = sum(
                1 for c in thesis_inv.get("conditions", [])
                if c.get("evidence_status") == "weak_evidence"
            )
            if weak_count > 0:
                penalty = min(weak_count * 5.0, 15.0)
                normalized_probability = max(normalized_probability - penalty, 0.0)

        pre_score = decision_score(downside, normalized_probability, base_cagr)

        if analysis["margin_trend_gate"] == "PERMANENT_PASS":
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    "Permanent pass triggered by clear multi-year margin erosion.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score=pre_score.__dict__,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at analysis (permanent pass)")
            continue

        catalyst_stack = analysis.get("catalyst_stack", [])
        hard_medium_count = sum(
            1 for c in catalyst_stack
            if isinstance(c, dict) and c.get("type") in ("HARD", "MEDIUM")
        )
        if analysis["catalyst_classification"] != "VALID_CATALYST" and hard_medium_count == 0:
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    "No valid catalyst identified; methodology requires automatic rejection.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score=pre_score.__dict__,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at analysis (no valid catalyst)")
            continue
        if analysis["catalyst_classification"] != "VALID_CATALYST" and hard_medium_count > 0:
            execution_log_entries.append(
                f"{candidate['ticker']}: catalyst_classification={analysis['catalyst_classification']} "
                f"overridden by catalyst_stack ({hard_medium_count} HARD/MEDIUM entries)"
            )

        if analysis["final_cluster_status"] == "ELIMINATED":
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    "Cluster analysis eliminated the candidate before epistemic review.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score=pre_score.__dict__,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at analysis (cluster eliminated)")
            continue

        exception_gate = _require_dict(
            analysis.get("exception_20_pct_gate", {"eligible": False}),
            f"{candidate['ticker']}.analysis.exception_20_pct_gate",
        )
        if base_cagr < 20.0:
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    f"Base-case CAGR {base_cagr}% is below the 20% exception floor.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score=pre_score.__dict__,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at analysis (CAGR below 20%)")
            continue

        exception_candidate = 20.0 <= base_cagr < 30.0 and _as_bool(
            exception_gate.get("eligible", False),
            f"{candidate['ticker']}.analysis.exception_20_pct_gate.eligible",
        )
        if 20.0 <= base_cagr < 30.0 and not exception_candidate:
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    f"Base-case CAGR {base_cagr}% is below the 30% hurdle and no exception path was provided.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score=pre_score.__dict__,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at analysis (sub-30 CAGR)")
            continue

        pcs_answers = _validate_pcs_answers(candidate)
        epi_result = epistemic_outcome(normalized_probability, analysis["dominant_risk_type"], pcs_answers)
        post_score = decision_score(downside, epi_result.effective_probability, base_cagr)
        epi_payload = {
            **pcs_answers,
            "no_count": epi_result.no_count,
            "raw_confidence": epi_result.raw_confidence,
            "risk_type": analysis["dominant_risk_type"],
            "risk_type_friction": epi_result.risk_type_friction,
            "friction_note": epi_result.friction_note,
            "adjusted_confidence": epi_result.adjusted_confidence,
            "multiplier": epi_result.multiplier,
            "effective_probability": epi_result.effective_probability,
        }

        if exception_candidate:
            pending_human_review.append(
                {
                    "ticker": candidate["ticker"],
                    "reason": exception_gate.get(
                        "reason",
                        f"Base-case CAGR {base_cagr}% falls in the 20-29.9% exception band and requires human approval.",
                    ),
                    "base_case_cagr_pct": base_cagr,
                    "effective_probability_pct": epi_result.effective_probability,
                    "score": post_score.total_score,
                }
            )
            execution_log_entries.append(f"{candidate['ticker']}: full analysis complete; routed to pending human review")
            continue

        # Thesis invalidation: imminent break hard gate
        if thesis_inv and thesis_inv.get("imminent_break_flag"):
            strong_cats = [
                c["category"] for c in thesis_inv.get("conditions", [])
                if c.get("evidence_status") == "strong_evidence"
            ]
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    f"THESIS_BREAK_IMMINENT: Strong evidence of structural break in categories: {', '.join(strong_cats)}.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score={
                        "pre_epistemic": pre_score.__dict__,
                        "post_epistemic": {
                            **post_score.__dict__,
                            "effective_probability": epi_result.effective_probability,
                        },
                    },
                    epi=epi_payload,
                )
            )
            execution_log_entries.append(
                f"{candidate['ticker']}: rejected at analysis (THESIS_BREAK_IMMINENT: {', '.join(strong_cats)})"
            )
            continue

        if epi_result.effective_probability < 60.0:
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    f"Epistemic confidence filter rejected the candidate: effective probability {epi_result.effective_probability}% is below 60%.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score={
                        "pre_epistemic": pre_score.__dict__,
                        "post_epistemic": {
                            **post_score.__dict__,
                            "effective_probability": epi_result.effective_probability,
                        },
                    },
                    epi=epi_payload,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected at epistemic review")
            continue

        if post_score.total_score < 45.0:
            rejected_analysis.append(
                _analysis_rejection_packet(
                    candidate,
                    f"Final decision score {post_score.total_score} is below the 45-point watchlist threshold.",
                    base_case=base_case,
                    worst_case=worst_case,
                    probability=probability,
                    score={
                        "pre_epistemic": pre_score.__dict__,
                        "post_epistemic": {
                            **post_score.__dict__,
                            "effective_probability": epi_result.effective_probability,
                        },
                    },
                    epi=epi_payload,
                )
            )
            execution_log_entries.append(f"{candidate['ticker']}: rejected after scoring")
            continue

        ranked_candidates.append(
            _ranked_candidate_packet(
                candidate,
                rank=0,
                base_case=base_case,
                worst_case=worst_case,
                probability=probability,
                pre_score=pre_score,
                post_score=post_score,
                epi_result=epi_result,
                pcs_answers=pcs_answers,
            )
        )
        execution_log_entries.append(f"{candidate['ticker']}: ranked candidate")

    ranked_candidates.sort(
        key=lambda item: (
            "risk_enrichment" in item and item["risk_enrichment"].get("demotion_trigger") is not None,
            -item["score"]["post_epistemic"]["total_score"],
        )
    )
    for idx, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = idx

    portfolio_context = _require_dict(payload.get("portfolio_context", {}), "portfolio_context")
    current_holding_overlays = _build_current_holding_overlays(
        portfolio_context,
        ranked_candidates,
        pending_human_review,
        rejected_screening,
        rejected_analysis,
    )

    template["ranked_candidates"] = ranked_candidates
    template["pending_human_review"] = pending_human_review
    template["rejected_at_screening"] = rejected_screening
    template["rejected_at_analysis_detail_packets"] = rejected_analysis
    template["current_holding_overlays"] = current_holding_overlays

    survivor_count = len(ranked_candidates)
    template["executive_summary"] = [
        f"{survivor_count} ranked candidate(s) survived out of {len(payload['candidates'])} scanned.",
        f"{len(rejected_screening)} rejected at screening, {len(rejected_analysis)} rejected at analysis, {len(pending_human_review)} pending human review.",
    ]
    if not ranked_candidates:
        template["executive_summary"].append("No investable candidates cleared the full pipeline at current assumptions.")
    if pending_human_review:
        template["executive_summary"].append("Exception candidates remain out of ranked output until human approval.")

    current_positions = int(portfolio_context.get("current_positions", 0))
    max_positions = int(portfolio_context.get("max_positions", 12))
    available_slots = max(max_positions - current_positions, 0)
    template["portfolio_impact"] = [
        f"Current positions: {current_positions}/{max_positions} | Available slots: {available_slots}",
        f"New ranked candidates: {len(ranked_candidates)} | Pending human review: {len(pending_human_review)}",
    ]
    if current_holding_overlays:
        template["portfolio_impact"].append(f"Current holding overlays generated: {len(current_holding_overlays)}")
    template["methodology_notes"] = list(payload.get("methodology_notes", [])) + [
        "Assembly is JSON-first and markdown is rendered from the validated report object.",
        "Probability was normalized to the canonical 50/60/70/80 bands before epistemic adjustments.",
        "20-29.9% CAGR exception candidates stay outside ranked output until a human approves them.",
    ]
    execution_log = {
        "entries": execution_log_entries,
        "candidate_count": len(payload["candidates"]),
        "survivor_count": len(ranked_candidates),
    }
    validate_scan_report(template)
    judge = codex_judge(template, execution_log, config=judge_config, transport=judge_transport)
    markdown = render_scan_markdown(template, execution_log, judge)
    return ScanArtifacts(report_json=template, report_markdown=markdown, execution_log=execution_log, judge=judge)


def run_scan_file(
    input_path: Path,
    json_out: Path | None = None,
    markdown_out: Path | None = None,
    execution_log_out: Path | None = None,
    judge_config: AppConfig | None = None,
    judge_transport=None,
) -> ScanArtifacts:
    payload = load_json(input_path)
    artifacts = run_scan_with_judge(payload, judge_config=judge_config, judge_transport=judge_transport)

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(artifacts.report_json, indent=2))
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(artifacts.report_markdown)
    if execution_log_out is not None:
        write_execution_log(execution_log_out, artifacts.report_json, artifacts.execution_log, artifacts.judge)

    return artifacts


def validate_scan_input_file(input_path: Path) -> dict:
    payload = load_json(input_path)
    validate_scan_input(payload)
    return payload


def scan_input_template() -> dict:
    return {
        "title": "EdenFinTech Stock Scan - Example",
        "scan_date": str(date.today()),
        "version": "v1",
        "scan_parameters": {
            "scan_mode": "specific_tickers",
            "focus": "ABC, XYZ",
            "api": "Financial Modeling Prep",
        },
        "portfolio_context": {
            "current_positions": 4,
            "max_positions": 12,
            "current_holdings": [
                {
                    "ticker": "ABC",
                    "current_weight_pct": 6.5,
                    "existing_position_action": "HOLD",
                    "note": "Example current holding for overlay generation.",
                }
            ],
        },
        "methodology_notes": [
            "Populate this payload with deterministic research inputs before running the pipeline.",
        ],
        "candidates": [
            {
                "ticker": "ABC",
                "cluster_name": "example-cluster",
                "industry": "Example Industry",
                "current_price": 25.0,
                "screening": {
                    "pct_off_ath": 72.0,
                    "industry_understandable": True,
                    "industry_in_secular_decline": False,
                    "double_plus_potential": True,
                    "checks": {
                        "solvency": {"verdict": "PASS", "note": "Liquidity appears adequate."},
                        "dilution": {"verdict": "PASS", "note": "Per-share growth remains intact."},
                        "revenue_growth": {"verdict": "PASS", "note": "Revenue base has stabilized."},
                        "roic": {"verdict": "PASS", "note": "Returns are above the minimum threshold."},
                        "valuation": {"verdict": "PASS", "note": "Valuation clears the hurdle preliminarily."},
                    },
                },
                "analysis": {
                    "margin_trend_gate": "PASS",
                    "final_cluster_status": "CLEAR_WINNER",
                    "catalyst_classification": "VALID_CATALYST",
                    "catalyst_stack": [
                        {"type": "HARD", "description": "Cost savings program", "timeline": "Q2 2026"},
                        {"type": "MEDIUM", "description": "Pricing reset", "timeline": "FY2026"},
                    ],
                    "invalidation_triggers": [
                        {"trigger": "Margin erosion resumes", "evidence": "Quarterly FCF margin below 5%"},
                    ],
                    "decision_memo": {
                        "better_than_peer": "Higher FCF margin than direct competitors",
                        "safer_than_peer": "Lower leverage ratio and better liquidity",
                        "what_makes_wrong": "Demand decline in core end market",
                    },
                    "issues_and_fixes": [
                        {"issue": "Cost structure elevated", "fix": "Cost savings program", "evidence_status": "ACTION_UNDERWAY"},
                        {"issue": "Leverage above target", "fix": "Deleveraging from FCF", "evidence_status": "EARLY_RESULTS_VISIBLE"},
                    ],
                    "setup_pattern": "QUALITY_FRANCHISE",
                    "stretch_case": {
                        "revenue_b": 3.5,
                        "fcf_margin_pct": 12.0,
                        "multiple": 28.0,
                        "shares_m": 120.0,
                        "years": 3.0,
                    },
                    "moat_assessment": "Switching costs remain meaningful.",
                    "thesis_summary": "Example turnaround with improving margins and identifiable catalysts.",
                    "catalysts": ["Cost savings program", "Pricing reset"],
                    "key_risks": ["Execution miss", "Demand softness"],
                    "dominant_risk_type": "Operational/Financial",
                    "base_case": {
                        "revenue_b": 3.0,
                        "fcf_margin_pct": 10.0,
                        "multiple": 24.0,
                        "shares_m": 120.0,
                        "years": 3.0,
                    },
                    "worst_case": {
                        "revenue_b": 2.4,
                        "fcf_margin_pct": 8.0,
                        "multiple": 12.0,
                        "shares_m": 120.0,
                    },
                    "probability": {
                        "base_probability_pct": 68.0,
                        "base_rate": "60% turnaround precedent base rate",
                        "likert_adjustments": "Management +10, balance sheet 0, market 0",
                    },
                    "exception_20_pct_gate": {
                        "eligible": False,
                    },
                },
                "epistemic_review": {
                    "q1_operational_feasibility": {"answer": "STRONG", "justification": "Company has runway and levers to execute turnaround.", "evidence": "Management plan and filings."},
                    "q2_risk_bounded": {"answer": "STRONG", "justification": "Risk assessment is evidence-backed.", "evidence": "Stable operating regime."},
                    "q3_precedent_grounded": {"answer": "STRONG", "justification": "Thesis aligns with historical base rates.", "evidence": "Named industry precedents."},
                    "q4_downside_steelmanned": {"answer": "STRONG", "justification": "Bear case is adequately steelmanned.", "evidence": "Multiple downside scenarios considered."},
                    "q5_catalyst_concrete": {"answer": "STRONG", "justification": "Catalysts are exogenous and verifiable.", "evidence": "Specific catalyst timeline and triggers."},
                },
            }
        ],
    }


def scan_input_template_markdown() -> str:
    return (
        "# Scan Input Contract\n\n"
        "Use `run-scan` with a JSON payload shaped like the example returned by `show-scan-template`.\n"
        "The pipeline is deterministic: it does not fetch market data, research, or quotes on its own.\n"
        "Populate the screening, analysis, and epistemic sections with structured upstream research first.\n"
    )


def load_scan_input_template_text() -> str:
    return json.dumps(scan_input_template(), indent=2) + "\n"


def methodology_excerpt() -> str:
    return load_text(methodology_root() / "strategy-rules.md")
