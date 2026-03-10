"""Red-team validator agent with deterministic contradiction detection and LLM-powered adversarial questioning.

Produces APPROVE/REJECT verdicts with specific objections. Contradictions are detected
deterministically first, then fed into LLM context for adversarial red-team questioning.
"""
from __future__ import annotations

import json
from typing import Callable


def _safe_get(data: dict, *keys, default=None):
    """Safely traverse nested dict keys, returning default if any key is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def detect_contradictions(overlay_candidate: dict, raw_candidate: dict) -> list[dict]:
    """Compare analyst overlay claims against raw FMP data and flag discrepancies.

    Pure deterministic comparison -- no LLM involved. Checks:
    1. Revenue: base_case_assumptions.revenue_b vs derived.latest_revenue_b
    2. FCF margin: base_case_assumptions.fcf_margin_pct vs derived.latest_fcf_margin_pct
    3. Revenue direction: flags if FMP shows decline but analyst does not acknowledge
    4. Share count: base_case_assumptions.shares_m vs derived.shares_m_latest

    Returns list of contradiction dicts with field, claim, actual, severity keys.
    Handles missing fields gracefully by skipping checks where data is absent.
    """
    contradictions: list[dict] = []

    derived = _safe_get(raw_candidate, "fmp_context", "derived")
    base_case = _safe_get(overlay_candidate, "analysis_inputs", "base_case_assumptions")

    if derived is None or base_case is None:
        return contradictions

    # 1. Revenue check
    claim_revenue = base_case.get("revenue_b")
    actual_revenue = derived.get("latest_revenue_b")
    if claim_revenue is not None and actual_revenue is not None and actual_revenue > 0:
        pct_gap = abs(claim_revenue - actual_revenue) / actual_revenue
        if pct_gap > 0.50:
            contradictions.append({
                "field": "revenue_b",
                "claim": str(claim_revenue),
                "actual": str(actual_revenue),
                "severity": "HIGH",
            })
        elif pct_gap > 0.10:
            contradictions.append({
                "field": "revenue_b",
                "claim": str(claim_revenue),
                "actual": str(actual_revenue),
                "severity": "MEDIUM",
            })

    # 2. FCF margin check (absolute percentage point difference)
    claim_fcf = base_case.get("fcf_margin_pct")
    actual_fcf = derived.get("latest_fcf_margin_pct")
    if claim_fcf is not None and actual_fcf is not None:
        pp_gap = abs(claim_fcf - actual_fcf)
        if pp_gap > 10.0:
            contradictions.append({
                "field": "fcf_margin_pct",
                "claim": str(claim_fcf),
                "actual": str(actual_fcf),
                "severity": "HIGH",
            })
        elif pp_gap > 5.0:
            contradictions.append({
                "field": "fcf_margin_pct",
                "claim": str(claim_fcf),
                "actual": str(actual_fcf),
                "severity": "MEDIUM",
            })

    # 3. Revenue direction check
    latest_revenue = derived.get("latest_revenue_b")
    trough_revenue = derived.get("trough_revenue_b")
    if latest_revenue is not None and trough_revenue is not None:
        if latest_revenue < trough_revenue:
            # FMP shows decline -- check if analyst acknowledges it
            thesis = _safe_get(overlay_candidate, "analysis_inputs", "thesis_summary") or ""
            margin_gate = _safe_get(overlay_candidate, "analysis_inputs", "margin_trend_gate") or ""
            decline_keywords = ("decline", "declining", "contraction", "shrink", "downturn", "deteriorat")
            text_to_check = f"{thesis} {margin_gate}".lower()
            acknowledges_decline = any(kw in text_to_check for kw in decline_keywords)
            if not acknowledges_decline:
                contradictions.append({
                    "field": "revenue_direction",
                    "claim": "growth implied",
                    "actual": f"latest {latest_revenue}B < trough {trough_revenue}B (declining)",
                    "severity": "HIGH",
                })

    # 4. Share count check
    claim_shares = base_case.get("shares_m")
    actual_shares = derived.get("shares_m_latest")
    if claim_shares is not None and actual_shares is not None and actual_shares > 0:
        pct_gap = abs(claim_shares - actual_shares) / actual_shares
        if pct_gap > 0.05:
            contradictions.append({
                "field": "shares_m",
                "claim": str(claim_shares),
                "actual": str(actual_shares),
                "severity": "MEDIUM",
            })

    return contradictions
