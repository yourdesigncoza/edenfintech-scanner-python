"""Holding review -- forward return refresh, thesis integrity, sell triggers,
replacement gate, and fresh capital weight computation.

All financial math delegates to scoring.py. This module is orchestration logic only.
"""
from __future__ import annotations

from .scoring import (
    cagr_pct,
    decision_score,
    downside_pct,
    floor_price,
    score_to_size_band,
    valuation_target_price,
)

# -- Constants ----------------------------------------------------------------

THESIS_STATUSES = {"IMPROVED", "DEGRADED", "UNCHANGED", "INVALIDATED"}

_THESIS_SEVERITY: dict[str, int] = {
    "IMPROVED": 0,
    "UNCHANGED": 1,
    "DEGRADED": 2,
    "INVALIDATED": 3,
}

RAPID_RERATING_THRESHOLD = 50.0  # percent gain from purchase price
FORWARD_HURDLE_PCT = 30.0  # sell trigger 1 forward CAGR threshold
RAPID_FORWARD_THRESHOLD = 15.0  # sell trigger 2 (conservative end of 10-15%)
MIN_YEARS_REMAINING = 0.25  # floor to avoid CAGR distortion


# -- HOLD-01: Forward return refresh ------------------------------------------

def forward_return_refresh(
    base_case: dict,
    current_price: float,
    years_remaining: float,
) -> dict:
    """Recompute target price and forward CAGR from current price."""
    years_remaining = max(years_remaining, MIN_YEARS_REMAINING)
    target_price = valuation_target_price(
        base_case["revenue_b"],
        base_case["fcf_margin_pct"],
        base_case["multiple"],
        base_case["shares_m"],
    )
    forward_cagr = cagr_pct(current_price, target_price, years_remaining)
    return {
        "target_price": target_price,
        "current_price": current_price,
        "forward_cagr_pct": forward_cagr,
        "years_remaining": years_remaining,
    }


# -- HOLD-02: Thesis integrity check ------------------------------------------

def thesis_integrity_check(
    invalidation_triggers: list[dict],
    current_evidence: list[dict],
) -> dict:
    """Match current evidence against invalidation triggers. Worst status wins."""
    evidence_by_trigger: dict[str, dict] = {
        e["trigger"]: e for e in current_evidence
    }

    assessments = []
    worst_severity = 0

    for trigger in invalidation_triggers:
        trigger_text = trigger["trigger"]
        match = evidence_by_trigger.get(trigger_text)

        if match:
            status = match["status"]
            current_ev = match.get("evidence", "")
        else:
            status = "UNCHANGED"
            current_ev = ""

        assessments.append({
            "trigger": trigger_text,
            "original_evidence": trigger["evidence"],
            "current_status": status,
            "current_evidence": current_ev,
        })

        severity = _THESIS_SEVERITY.get(status, 1)
        worst_severity = max(worst_severity, severity)

    severity_to_status = {v: k for k, v in _THESIS_SEVERITY.items()}
    overall_status = severity_to_status.get(worst_severity, "UNCHANGED")

    return {
        "overall_status": overall_status,
        "assessments": assessments,
    }


# -- HOLD-03: Sell trigger evaluation ------------------------------------------

def evaluate_sell_triggers(
    forward_refresh: dict,
    thesis_check: dict,
    purchase_price: float,
) -> list[dict]:
    """Evaluate the 3 sell triggers from strategy-rules.md Step 8."""
    fired: list[dict] = []
    current_price = forward_refresh["current_price"]
    target_price = forward_refresh["target_price"]
    forward_cagr = forward_refresh["forward_cagr_pct"]

    # Trigger 1: target reached + forward < 30%
    if current_price >= target_price and forward_cagr < FORWARD_HURDLE_PCT:
        fired.append({
            "trigger": "TARGET_REACHED_LOW_FORWARD",
            "fired": True,
            "reason": (
                f"Price ${current_price} >= target ${target_price}, "
                f"forward CAGR {forward_cagr}% < {FORWARD_HURDLE_PCT}%"
            ),
        })

    # Trigger 2: rapid rerating (>50% gain) + forward < 15%
    price_gain_pct = ((current_price - purchase_price) / purchase_price) * 100
    if price_gain_pct > RAPID_RERATING_THRESHOLD and forward_cagr < RAPID_FORWARD_THRESHOLD:
        fired.append({
            "trigger": "RAPID_RERATING_LOW_FORWARD",
            "fired": True,
            "reason": (
                f"Price up {price_gain_pct:.1f}% from entry, "
                f"forward CAGR {forward_cagr}% < {RAPID_FORWARD_THRESHOLD}%"
            ),
        })

    # Trigger 3: thesis break
    if thesis_check["overall_status"] == "INVALIDATED":
        fired.append({
            "trigger": "THESIS_BREAK",
            "fired": True,
            "reason": "One or more invalidation triggers have been confirmed",
        })

    return fired


# -- HOLD-04: Replacement gate ------------------------------------------------

def replacement_gate(
    holding_forward_cagr: float,
    holding_downside_pct: float,
    replacement_forward_cagr: float,
    replacement_downside_pct: float,
) -> dict:
    """Two-gate test: Gate A (>15pp CAGR delta) and Gate B (downside equal or better)."""
    cagr_delta = replacement_forward_cagr - holding_forward_cagr
    gate_a = cagr_delta > 15.0  # strictly greater than
    gate_b = replacement_downside_pct <= holding_downside_pct

    return {
        "gate_a_cagr_delta": {
            "holding_cagr": holding_forward_cagr,
            "replacement_cagr": replacement_forward_cagr,
            "delta_pp": round(cagr_delta, 2),
            "passed": gate_a,
        },
        "gate_b_downside": {
            "holding_downside": holding_downside_pct,
            "replacement_downside": replacement_downside_pct,
            "passed": gate_b,
        },
        "replacement_justified": gate_a and gate_b,
    }


# -- HOLD-05: Fresh capital weight ---------------------------------------------

def fresh_capital_weight(
    forward_cagr: float,
    worst_case: dict,
    current_price: float,
    effective_probability: float,
) -> dict:
    """Compute fresh-capital max weight using scoring.py pipeline."""
    floor_val = floor_price(
        worst_case["revenue_b"],
        worst_case["fcf_margin_pct"],
        worst_case["multiple"],
        worst_case["shares_m"],
    )
    ds = downside_pct(current_price, floor_val)
    score = decision_score(ds, effective_probability, forward_cagr)
    band = score_to_size_band(score.total_score)
    return {
        "fresh_capital_max_weight": band,
        "score": score.total_score,
        "downside_pct": ds,
    }


# -- Integration: review_holding -----------------------------------------------

def review_holding(
    holding: dict,
    current_price: float,
    *,
    replacement_candidate: dict | None = None,
) -> dict:
    """Run all holding review checks and return consolidated result."""
    base_case = holding["base_case_assumptions"]
    worst_case = holding["worst_case_assumptions"]

    # HOLD-01: Forward return refresh
    years_remaining = holding.get("years_remaining", base_case["years"])
    refresh = forward_return_refresh(base_case, current_price, years_remaining)

    # HOLD-02: Thesis integrity
    thesis = thesis_integrity_check(
        holding["invalidation_triggers"],
        holding.get("current_evidence", []),
    )

    # HOLD-03: Sell triggers
    triggers = evaluate_sell_triggers(refresh, thesis, holding["purchase_price"])

    # HOLD-05: Fresh capital weight
    fresh_weight = fresh_capital_weight(
        refresh["forward_cagr_pct"],
        worst_case,
        current_price,
        holding.get("effective_probability", 60.0),
    )

    result = {
        "ticker": holding["ticker"],
        "forward_refresh": refresh,
        "thesis_integrity": thesis,
        "sell_triggers": triggers,
        "sell_triggered": len(triggers) > 0,
        "fresh_capital_assessment": fresh_weight,
        "current_weight_pct": holding.get("current_weight_pct"),
    }

    # HOLD-04: Replacement gate (optional)
    if replacement_candidate is not None:
        result["replacement_gate"] = replacement_gate(
            refresh["forward_cagr_pct"],
            fresh_weight["downside_pct"],
            replacement_candidate["forward_cagr_pct"],
            replacement_candidate["downside_pct"],
        )

    return result


# -- Thesis invalidation → Step 8 monitoring checklist ----------------------

_MONITORING_ACTIONS = {
    "no_current_evidence": "QUARTERLY_REVIEW",
    "weak_evidence": "MONTHLY_REVIEW",
    "strong_evidence": "IMMEDIATE_REVIEW",
}


def thesis_integrity_checklist(thesis_invalidation: dict | None) -> list[dict]:
    """Convert thesis invalidation conditions into Step 8 monitoring items.

    Each item includes the early_warning_metric as the KPI to track
    and a monitoring_action based on evidence severity at entry.
    """
    if thesis_invalidation is None:
        return []
    return [
        {
            "category": c["category"],
            "risk_description": c["risk_description"],
            "early_warning_metric": c["early_warning_metric"],
            "evidence_status_at_entry": c["evidence_status"],
            "monitoring_action": _MONITORING_ACTIONS.get(
                c["evidence_status"], "QUARTERLY_REVIEW"
            ),
        }
        for c in thesis_invalidation.get("conditions", [])
    ]
