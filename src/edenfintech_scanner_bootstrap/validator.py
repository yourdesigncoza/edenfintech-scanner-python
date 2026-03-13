"""Red-team validator agent with deterministic contradiction detection and LLM-powered adversarial questioning.

Produces APPROVE/APPROVE_WITH_CONCERNS/REJECT verdicts with specific objections.
Contradictions are detected deterministically first, then fed into LLM context for
adversarial red-team questioning.
"""
from __future__ import annotations

import json
from typing import Callable

from .llm_transport import default_anthropic_transport, parse_llm_json


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


# ---------------------------------------------------------------------------
# Red-team question templates
# ---------------------------------------------------------------------------

RED_TEAM_QUESTIONS = [
    {
        "question_id": "bull_falsifiability",
        "template": "What specific evidence would falsify the bull case?",
    },
    {
        "question_id": "worst_case_completeness",
        "template": "Does the worst case capture the actual downside scenario?",
    },
    {
        "question_id": "catalyst_plausibility",
        "template": "Are the stated catalysts realistic within the timeline?",
    },
    {
        "question_id": "competitive_durability",
        "template": "Can the competitive position survive disruption?",
    },
    {
        "question_id": "management_credibility",
        "template": "Is management's track record consistent with execution claims?",
    },
]

# ---------------------------------------------------------------------------
# Validator output schema for constrained decoding
# ---------------------------------------------------------------------------

VALIDATOR_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["verdict", "questions", "objections"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "APPROVE_WITH_CONCERNS", "REJECT"]},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question_id", "challenge", "evidence", "severity"],
                "additionalProperties": False,
                "properties": {
                    "question_id": {"type": "string"},
                    "challenge": {"type": "string"},
                    "evidence": {"type": "string"},
                    "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                },
            },
        },
        "objections": {"type": "array", "items": {"type": "string"}},
    },
}

# Fields that must NEVER appear in the validator request payload
_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "decision_score", "total_score", "ranking", "effective_probability",
})

ValidatorTransport = Callable[[dict], dict]


class RedTeamValidatorClient:
    """Client for adversarial red-team validation of analyst overlays."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-haiku-4-5-20251001",
        transport: ValidatorTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._default_transport

    def _default_transport(self, request_payload: dict) -> dict:
        """Default transport using the Anthropic SDK."""
        return default_anthropic_transport(
            request_payload,
            api_key=self.api_key,
            model=self.model,
            max_tokens=4096,
        )

    def _build_system_prompt(self) -> str:
        """Build adversarial system prompt with red-team question templates."""
        question_list = "\n".join(
            f"  {i + 1}. [{q['question_id']}] {q['template']}"
            for i, q in enumerate(RED_TEAM_QUESTIONS)
        )
        return (
            "You are an adversarial red-team validator for equity research overlays.\n"
            "Your job is to challenge the analyst's assumptions and find weaknesses.\n\n"
            "You MUST answer exactly 5 red-team questions:\n"
            f"{question_list}\n\n"
            "For each question, provide:\n"
            "- question_id: matching the ID above\n"
            "- challenge: your adversarial challenge to the analyst's position\n"
            "- evidence: specific evidence supporting your challenge\n"
            "- severity: HIGH, MEDIUM, or LOW\n\n"
            "VERDICT RUBRIC (follow strictly):\n"
            "- REJECT: ONLY for fatal errors — mathematical impossibilities, internal\n"
            "  contradictions (e.g. bull and bear cases use same assumptions), missing\n"
            "  critical data that makes the analysis indefensible, or factual errors\n"
            "  contradicted by the raw evidence.\n"
            "- APPROVE_WITH_CONCERNS: The analysis is logically defensible but you have\n"
            "  subjective disagreements — conservative vs aggressive assumptions, timing\n"
            "  estimates, risk weighting, editorial improvements. List concerns as objections.\n"
            "- APPROVE: No material issues found. Analysis is well-supported.\n\n"
            "Most real-world equity analyses will warrant APPROVE_WITH_CONCERNS. Use REJECT\n"
            "sparingly — only when the analysis cannot be defended.\n\n"
            "Return ONLY valid JSON matching the output schema. No markdown, no commentary."
        )

    def _build_user_prompt(
        self,
        overlay_candidate: dict,
        raw_candidate: dict,
        contradictions: list[dict],
    ) -> str:
        """Build user prompt with overlay data, raw FMP context, and contradictions.

        Explicitly excludes pipeline scores, rankings, and post-scoring data.
        """
        # Extract only safe overlay fields (analysis_inputs, screening_inputs, epistemic_inputs)
        safe_overlay: dict = {}
        for key in ("analysis_inputs", "screening_inputs", "epistemic_inputs",
                     "ticker", "evidence_context", "field_provenance"):
            if key in overlay_candidate:
                safe_overlay[key] = overlay_candidate[key]

        # Extract only FMP context from raw candidate
        safe_raw: dict = {}
        for key in ("ticker", "fmp_context", "market_snapshot", "industry"):
            if key in raw_candidate:
                safe_raw[key] = raw_candidate[key]

        parts = [
            "ANALYST OVERLAY (analysis_inputs only, pipeline output excluded):",
            json.dumps(safe_overlay, indent=2),
            "",
            "RAW FMP DATA:",
            json.dumps(safe_raw, indent=2),
        ]

        if contradictions:
            parts.extend([
                "",
                "PRE-COMPUTED CONTRADICTIONS (deterministic checks found these discrepancies):",
                json.dumps(contradictions, indent=2),
            ])
        else:
            parts.extend([
                "",
                "PRE-COMPUTED CONTRADICTIONS: None found.",
            ])

        return "\n".join(parts)

    def validate(
        self,
        overlay_candidate: dict,
        raw_candidate: dict,
        contradictions: list[dict],
    ) -> dict:
        """Run red-team validation against an overlay candidate.

        Returns dict with verdict, questions, objections, and contradictions keys.
        """
        request_payload = {
            "system": self._build_system_prompt(),
            "messages": [
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        overlay_candidate, raw_candidate, contradictions
                    ),
                }
            ],
            "output_schema": VALIDATOR_OUTPUT_SCHEMA,
        }

        response = self.transport(request_payload)
        result = parse_llm_json(response, agent="validator")

        # Enrich result with contradictions
        result["contradictions"] = contradictions
        return result


def validate_overlay(
    overlay_candidate: dict,
    raw_candidate: dict,
    *,
    client: RedTeamValidatorClient | None = None,
) -> dict:
    """Top-level validation function: deterministic contradictions first, then LLM red-team.

    Runs detect_contradictions() first (per research: deterministic before LLM),
    then passes contradictions into the LLM validator context.

    Returns enriched result with verdict, questions, objections, contradictions keys.
    """
    contradictions = detect_contradictions(overlay_candidate, raw_candidate)

    if client is None:
        from .config import load_config
        config = load_config()
        config.require("anthropic_api_key")
        client = RedTeamValidatorClient(config.anthropic_api_key, model=config.analyst_model)

    return client.validate(overlay_candidate, raw_candidate, contradictions)
