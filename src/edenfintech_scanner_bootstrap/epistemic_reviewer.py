"""Epistemic reviewer agent with code-enforced information barrier.

Provides independent confidence review that challenges the analyst's thesis
using only qualitative context -- provably blind to scores, probabilities,
and valuations. Produces 5 PCS answers with evidence anchoring and three
evidence quality detectors (WEAK_EVIDENCE, NO_EVIDENCE friction, laundering).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .llm_transport import default_anthropic_transport, parse_llm_json


# ---------------------------------------------------------------------------
# EPST-01: Type-level information barrier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpistemicReviewInput:
    """Restricted input for epistemic reviewer.

    This dataclass enforces the information barrier specified in the
    epistemic_review contract. It EXCLUDES:
    - scores, decision_score, total_score
    - probabilities, base_probability_pct, effective_probability
    - valuations, target_price, floor_price, base_case, worst_case
    - numeric targets, cagr_pct, downside_pct
    """
    ticker: str
    industry: str
    thesis_summary: str
    key_risks: list[str]
    catalysts: list[str]
    moat_assessment: str
    dominant_risk_type: str


def extract_epistemic_input(overlay_candidate: dict) -> EpistemicReviewInput:
    """Extract restricted input from analyst overlay.

    Only copies fields listed in the epistemic_review contract.
    All numeric scores, probabilities, and valuations are dropped.
    """
    analysis = overlay_candidate.get("analysis_inputs", {})
    return EpistemicReviewInput(
        ticker=overlay_candidate["ticker"],
        industry=overlay_candidate.get("industry", ""),
        thesis_summary=analysis.get("thesis_summary", ""),
        key_risks=analysis.get("key_risks", []),
        catalysts=analysis.get("catalysts", []),
        moat_assessment=analysis.get("moat_assessment", ""),
        dominant_risk_type=analysis.get("dominant_risk_type", ""),
    )


# ---------------------------------------------------------------------------
# EPST-04: WEAK_EVIDENCE detection
# ---------------------------------------------------------------------------

WEAK_EVIDENCE_PATTERNS = [
    "industry reports",
    "various sources",
    "general consensus",
    "widely known",
    "common knowledge",
    "market observers",
    "analysts suggest",
    "reports indicate",
]

CONCRETE_SOURCE_MARKERS = [
    "10-k", "10-q", "earnings call", "sec filing",
    "annual report", "press release", "investor presentation",
]


def is_weak_evidence(evidence_text: str) -> bool:
    """Check if evidence citation lacks concrete source.

    NO_EVIDENCE and empty strings return False -- they are honest
    declarations or missing, not weak citations.
    """
    lower = evidence_text.lower().strip()
    if not lower or lower == "no_evidence":
        return False

    has_concrete = any(marker in lower for marker in CONCRETE_SOURCE_MARKERS)
    has_vague = any(pattern in lower for pattern in WEAK_EVIDENCE_PATTERNS)
    return has_vague or not has_concrete


# ---------------------------------------------------------------------------
# EPST-05: NO_EVIDENCE friction
# ---------------------------------------------------------------------------

def calculate_no_evidence_friction(pcs_answers: dict) -> int:
    """Return additional friction penalty for NO_EVIDENCE answers.

    >= 3 NO_EVIDENCE answers triggers -1 additional friction.
    """
    no_evidence_count = sum(
        1 for q in pcs_answers.values()
        if isinstance(q, dict) and q.get("evidence_source", "").upper() == "NO_EVIDENCE"
    )
    return -1 if no_evidence_count >= 3 else 0


# ---------------------------------------------------------------------------
# EPST-06: PCS laundering detection
# ---------------------------------------------------------------------------

def detect_pcs_laundering(
    analyst_provenance: list[dict],
    reviewer_citations: list[str],
) -> tuple[bool, float]:
    """Detect PCS laundering -- reviewer parroting analyst evidence.

    Returns (is_laundering, overlap_pct).
    Laundering flagged when > 80% of reviewer evidence sources
    also appear in analyst provenance.
    """
    analyst_sources: set[str] = set()
    for prov in analyst_provenance:
        for ref in prov.get("evidence_refs", []):
            summary = ref.get("summary", "").strip().lower()
            if summary:
                analyst_sources.add(summary)

    reviewer_sources: set[str] = set()
    for cite in reviewer_citations:
        stripped = cite.strip().lower()
        if stripped:
            reviewer_sources.add(stripped)

    if not reviewer_sources:
        return True, 100.0

    overlap = reviewer_sources & analyst_sources
    overlap_pct = round((len(overlap) / len(reviewer_sources)) * 100, 1)
    return overlap_pct > 80.0, overlap_pct


# ---------------------------------------------------------------------------
# Constrained decoding output schema
# ---------------------------------------------------------------------------

_PCS_QUESTION_KEYS = [
    "q1_operational", "q2_regulatory", "q3_precedent",
    "q4_nonbinary", "q5_macro",
]

EPISTEMIC_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": _PCS_QUESTION_KEYS,
    "additionalProperties": False,
    "properties": {
        key: {
            "type": "object",
            "required": ["answer", "justification", "evidence", "evidence_source"],
            "additionalProperties": False,
            "properties": {
                "answer": {"type": "string", "enum": ["Yes", "No"]},
                "justification": {"type": "string"},
                "evidence": {"type": "string"},
                "evidence_source": {"type": "string"},
            },
        }
        for key in _PCS_QUESTION_KEYS
    },
}


# ---------------------------------------------------------------------------
# Transport type and reviewer client (Task 2)
# ---------------------------------------------------------------------------

EpistemicReviewerTransport = Callable[[dict], dict]


class EpistemicReviewerClient:
    """Client for epistemic review using Claude with constrained decoding."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-haiku-4-5-20251001",
        transport: EpistemicReviewerTransport | None = None,
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
        """Build system prompt with PCS question definitions."""
        return "\n".join([
            "You are an independent epistemic reviewer for the EdenFinTech scan pipeline.",
            "",
            "CRITICAL RULE: You operate under an INFORMATION BARRIER.",
            "You will receive ONLY qualitative context: thesis, risks, catalysts, moat, and risk type.",
            "You do NOT have access to any scores, probabilities, valuations, or numeric targets.",
            "Your role is to independently assess confidence by answering 5 PCS questions.",
            "",
            "PCS (Probabilistic Confidence Score) QUESTIONS:",
            "",
            "Q1 - Operational (q1_operational):",
            "  Is this primarily an operational/financial situation where management actions can drive recovery?",
            "  Yes = management has clear levers. No = situation is outside management control.",
            "",
            "Q2 - Regulatory (q2_regulatory):",
            "  Is regulatory/political discretion LIMITED (i.e., outcomes are more predictable)?",
            "  Yes = regulatory risk is bounded. No = regulator has wide discretion over outcomes.",
            "",
            "Q3 - Precedent (q3_precedent):",
            "  Are there clear historical precedents for this type of recovery/situation?",
            "  Yes = comparable situations have played out before. No = this is novel/unprecedented.",
            "",
            "Q4 - Non-binary (q4_nonbinary):",
            "  Are outcomes distributed (non-binary) rather than all-or-nothing?",
            "  Yes = multiple recovery paths exist. No = outcome is binary (works or fails completely).",
            "",
            "Q5 - Macro (q5_macro):",
            "  Is macro exposure manageable and not the dominant risk factor?",
            "  Yes = macro is a secondary factor. No = macro conditions dominate the thesis.",
            "",
            "EVIDENCE RULES:",
            "- Each answer MUST include an evidence_source field.",
            "- evidence_source must be either a CONCRETE named source (e.g., '10-K FY2024', 'Q3 earnings call')",
            "  or the exact string 'NO_EVIDENCE' if you cannot find supporting evidence.",
            "- Do NOT use vague citations like 'industry reports' or 'general consensus'.",
            "- Honest NO_EVIDENCE is better than a vague citation.",
            "",
            "Return ONLY valid JSON matching the required schema.",
        ])

    def _build_user_prompt(self, review_input: EpistemicReviewInput) -> str:
        """Format review input for the user message."""
        return "\n".join([
            f"Ticker: {review_input.ticker}",
            f"Industry: {review_input.industry}",
            f"Dominant Risk Type: {review_input.dominant_risk_type}",
            "",
            f"Thesis Summary: {review_input.thesis_summary}",
            "",
            f"Key Risks: {json.dumps(review_input.key_risks)}",
            f"Catalysts: {json.dumps(review_input.catalysts)}",
            f"Moat Assessment: {review_input.moat_assessment}",
            "",
            "Answer all 5 PCS questions based on the context above.",
        ])

    def review(self, review_input: EpistemicReviewInput) -> dict:
        """Run epistemic review on restricted input.

        Type-checks that review_input is EpistemicReviewInput (EPST-01 enforcement).
        """
        if not isinstance(review_input, EpistemicReviewInput):
            raise TypeError(
                f"review_input must be EpistemicReviewInput, got {type(review_input).__name__}"
            )

        request_payload = {
            "system": self._build_system_prompt(),
            "messages": [{"role": "user", "content": self._build_user_prompt(review_input)}],
            "output_schema": EPISTEMIC_OUTPUT_SCHEMA,
        }

        response = self.transport(request_payload)
        pcs_answers = parse_llm_json(response, agent="epistemic_reviewer")
        return pcs_answers


# ---------------------------------------------------------------------------
# Top-level review function
# ---------------------------------------------------------------------------

def epistemic_review(
    review_input: EpistemicReviewInput,
    *,
    client: EpistemicReviewerClient | None = None,
) -> dict:
    """Run epistemic review with enforced information barrier.

    The function signature proves the barrier: review_input contains
    only qualitative analysis context, never numeric scores or valuations.

    Returns enriched result dict containing PCS answers + metadata
    (weak_evidence_flags, no_evidence_count, additional_friction).
    """
    if not isinstance(review_input, EpistemicReviewInput):
        raise TypeError(
            f"review_input must be EpistemicReviewInput, got {type(review_input).__name__}"
        )

    if client is None:
        raise ValueError(
            "client is required (no default API key available)"
        )

    pcs_answers = client.review(review_input)

    # Post-processing: evidence quality checks
    weak_evidence_flags: dict[str, bool] = {}
    no_evidence_count = 0
    for key in _PCS_QUESTION_KEYS:
        answer_data = pcs_answers.get(key, {})
        evidence_source = answer_data.get("evidence_source", "")
        weak_evidence_flags[key] = is_weak_evidence(evidence_source)
        if evidence_source.upper() == "NO_EVIDENCE":
            no_evidence_count += 1

    additional_friction = calculate_no_evidence_friction(pcs_answers)

    result = dict(pcs_answers)
    result["weak_evidence_flags"] = weak_evidence_flags
    result["no_evidence_count"] = no_evidence_count
    result["additional_friction"] = additional_friction

    return result
