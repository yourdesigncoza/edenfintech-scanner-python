from __future__ import annotations

from dataclasses import dataclass


VALID_PROBABILITY_BANDS = (50.0, 60.0, 70.0, 80.0)

PCS_MULTIPLIERS = {
    5: 1.00,
    4: 0.95,
    3: 0.85,
    2: 0.70,
    1: 0.50,
}

RISK_TYPE_FRICTION = {
    "Operational/Financial": 0,
    "Cyclical/Macro": -1,
    "Regulatory/Political": -2,
    "Legal/Investigation": -2,
    "Structural fragility (SPOF)": -1,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    downside_pct: float
    adjusted_downside: float
    risk_component: float
    probability_component: float
    return_component: float
    total_score: float


@dataclass(frozen=True)
class EpistemicOutcome:
    no_count: int
    raw_confidence: int
    risk_type_friction: int
    friction_note: str
    adjusted_confidence: int
    multiplier: float
    effective_probability: float
    binary_override: bool


def round2(value: float) -> float:
    return round(value, 2)


def valuation_target_price(revenue_b: float, fcf_margin_pct: float, multiple: float, shares_m: float) -> float:
    if shares_m <= 0:
        raise ValueError("shares_m must be positive")
    fcf_b = revenue_b * (fcf_margin_pct / 100)
    return round2((fcf_b * multiple * 1000) / shares_m)


def cagr_pct(current_price: float, target_price: float, years: float) -> float:
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if years <= 0:
        raise ValueError("years must be positive")
    return round2((((target_price / current_price) ** (1 / years)) - 1) * 100)


def floor_price(revenue_b: float, fcf_margin_pct: float, multiple: float, shares_m: float) -> float:
    return valuation_target_price(revenue_b, fcf_margin_pct, multiple, shares_m)


def downside_pct(current_price: float, floor_value: float) -> float:
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if floor_value <= 0:
        return 100.0
    return round2(max(0.0, ((current_price - floor_value) / current_price) * 100))


def adjusted_downside_pct(raw_downside_pct: float) -> float:
    return round2(raw_downside_pct * (1 + (raw_downside_pct / 100) * 0.5))


def normalize_probability_band(raw_probability_pct: float) -> float:
    bounded = min(max(raw_probability_pct, 50.0), 80.0)
    return min(VALID_PROBABILITY_BANDS, key=lambda band: (abs(band - bounded), band))


def decision_score(downside: float, probability: float, cagr: float) -> ScoreBreakdown:
    adjusted_downside = adjusted_downside_pct(downside)
    risk_component = round2((100 - adjusted_downside) * 0.45)
    probability_component = round2(probability * 0.40)
    return_component = round2(min(cagr, 100.0) * 0.15)
    total_score = round2(risk_component + probability_component + return_component)
    return ScoreBreakdown(
        downside_pct=round2(downside),
        adjusted_downside=adjusted_downside,
        risk_component=risk_component,
        probability_component=probability_component,
        return_component=return_component,
        total_score=total_score,
    )


def score_to_size_band(score: float) -> str:
    if score >= 75:
        return "15-20%"
    if score >= 65:
        return "10-15%"
    if score >= 55:
        return "6-10%"
    if score >= 45:
        return "3-6%"
    return "0%"


def confidence_cap_band(confidence: int) -> str | None:
    if confidence == 5:
        return None
    if confidence == 4:
        return "12%"
    if confidence == 3:
        return "8%"
    if confidence == 2:
        return "5%"
    return "0%"


def _raw_confidence_from_no_count(no_count: int) -> int:
    if no_count == 0:
        return 5
    if no_count == 1:
        return 4
    if no_count == 2:
        return 3
    if no_count == 3:
        return 2
    return 1


def _risk_type_friction(risk_type: str, pcs_answers: dict[str, dict[str, str]]) -> tuple[int, str]:
    if risk_type not in RISK_TYPE_FRICTION:
        raise ValueError(f"invalid dominant risk type: {risk_type}")

    default_friction = RISK_TYPE_FRICTION[risk_type]
    applied = default_friction
    note = f"{risk_type} -> friction {default_friction}"

    if risk_type == "Cyclical/Macro" and pcs_answers["q3_precedent"]["answer"] == "Yes":
        applied = 0
        note = f"{risk_type}, Q3=Yes -> friction 0"
    elif risk_type == "Regulatory/Political" and pcs_answers["q2_regulatory"]["answer"] == "Yes":
        applied = -1
        note = f"{risk_type}, Q2=Yes -> friction -1"
    elif risk_type == "Structural fragility (SPOF)":
        note = f"{risk_type} -> friction -1"

    return applied, note


def epistemic_outcome(base_probability: float, dominant_risk_type: str, pcs_answers: dict[str, dict[str, str]]) -> EpistemicOutcome:
    no_count = sum(1 for check in pcs_answers.values() if check["answer"] == "No")
    raw_confidence = _raw_confidence_from_no_count(no_count)
    friction, friction_note = _risk_type_friction(dominant_risk_type, pcs_answers)
    adjusted_confidence = max(1, raw_confidence - abs(friction))
    multiplier = PCS_MULTIPLIERS[adjusted_confidence]
    effective_probability = round2(base_probability * multiplier)
    binary_override = pcs_answers["q4_nonbinary"]["answer"] == "No" and adjusted_confidence <= 3
    return EpistemicOutcome(
        no_count=no_count,
        raw_confidence=raw_confidence,
        risk_type_friction=friction,
        friction_note=friction_note,
        adjusted_confidence=adjusted_confidence,
        multiplier=multiplier,
        effective_probability=effective_probability,
        binary_override=binary_override,
    )
