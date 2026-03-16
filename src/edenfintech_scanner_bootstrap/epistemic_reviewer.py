"""Epistemic reviewer agent with code-enforced information barrier.

Provides independent confidence review that challenges the analyst's thesis
using only qualitative context -- provably blind to scores, probabilities,
and valuations. Produces 5 PCS answers with 3-tier grading (STRONG/MODERATE/WEAK),
evidence anchoring, and evidence quality detectors (WEAK_EVIDENCE, laundering).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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

    trailing_ratios are historical performance ratios (not forward predictions,
    not absolute dollar amounts, not prices). Safe to pass through the barrier.
    """
    ticker: str
    industry: str
    thesis_summary: str
    key_risks: list[str]
    catalysts: list[str]
    moat_assessment: str
    dominant_risk_type: str
    company_description: str = ""
    trailing_ratios: dict = field(default_factory=dict)


def extract_epistemic_input(
    overlay_candidate: dict,
    raw_candidate: dict | None = None,
) -> EpistemicReviewInput:
    """Extract restricted input from analyst overlay.

    Only copies fields listed in the epistemic_review contract.
    All numeric scores, probabilities, and valuations are dropped.
    """
    analysis = overlay_candidate.get("analysis_inputs", {})
    company_description = ""
    trailing_ratios = {}
    if raw_candidate:
        company_description = raw_candidate.get("company_description", "")
        trailing_ratios = raw_candidate.get("trailing_ratios", {})
    return EpistemicReviewInput(
        ticker=overlay_candidate["ticker"],
        industry=overlay_candidate.get("industry", ""),
        thesis_summary=analysis.get("thesis_summary", ""),
        key_risks=analysis.get("key_risks", []),
        catalysts=analysis.get("catalysts", []),
        moat_assessment=analysis.get("moat_assessment", ""),
        dominant_risk_type=analysis.get("dominant_risk_type", ""),
        company_description=company_description,
        trailing_ratios=trailing_ratios,
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
    # SEC / IR sources
    "10-k", "10-q", "earnings call", "sec filing",
    "annual report", "press release", "investor presentation",
    "proxy statement", "def 14a", "proxy",
    # FMP quantitative sources
    "fmp", "financial statements", "income statement",
    "balance sheet", "cash flow statement", "key metrics",
    "financial data",
    # Gemini qualitative sources
    "seeking alpha", "fintool", "grounded search",
    # Gemini grounding URLs
    "vertexaisearch", "grounding-api-redirect",
    # Common Gemini-sourced domains
    "businesswire", "bioworld", "spglobal", "simplywall",
    "morningstar", "tradingeconomics", "zacks", "gurufocus",
    # Sector / pipeline context
    "sector knowledge", "sector context",
]

# Pattern for named-source citations: Per 'Article Title Here' (straight or smart quotes)
_NAMED_SOURCE_PATTERN = re.compile(r"(?:per|confirmed by|per\s+stage)\s+['\u2018\u2019\u201c\u201d][^'\u2018\u2019\u201c\u201d]{5,}['\u2018\u2019\u201c\u201d]", re.IGNORECASE)

# Separate markers for the epistemic reviewer, which operates behind an
# information barrier and can only cite the pipeline artifacts it receives.
EPISTEMIC_CONTEXT_MARKERS = [
    "trailing financial ratios", "audited statements",
    "thesis summary", "catalysts", "key risks",
    "base case assumptions", "worst case assumptions",
    "moat assessment", "dominant risk type",
]

_URL_PATTERN = re.compile(r'https?://\S+')


def is_weak_evidence(
    evidence_text: str,
    *,
    context_markers: list[str] | None = None,
) -> bool:
    """Check if evidence citation lacks concrete source.

    NO_EVIDENCE and empty strings return False -- they are honest
    declarations or missing, not weak citations.

    Pass *context_markers* to override the default CONCRETE_SOURCE_MARKERS.
    The epistemic reviewer should pass EPISTEMIC_CONTEXT_MARKERS since it
    operates behind an information barrier and can only cite pipeline artifacts.
    """
    lower = evidence_text.lower().strip()
    if not lower or lower == "no_evidence":
        return False

    markers = context_markers if context_markers is not None else CONCRETE_SOURCE_MARKERS
    has_concrete = any(marker in lower for marker in markers) or bool(_URL_PATTERN.search(lower))
    has_vague = any(pattern in lower for pattern in WEAK_EVIDENCE_PATTERNS)
    return has_vague or not has_concrete


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
    "q1_operational_feasibility", "q2_risk_bounded", "q3_precedent_grounded",
    "q4_downside_steelmanned", "q5_catalyst_concrete",
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
                "answer": {"type": "string", "enum": ["STRONG", "MODERATE", "WEAK"]},
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
        temperature: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._default_transport
        self.temperature = temperature

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
            "You will receive ONLY qualitative context: thesis, risks, catalysts, moat, risk type,",
            "and trailing financial ratios (historical, not forward-looking).",
            "You do NOT have access to any scores, probabilities, valuations, or numeric targets.",
            "Your role is to independently assess the REASONING QUALITY of the analyst's thesis",
            "by answering 5 PCS questions.",
            "",
            "You have been provided with trailing financial ratios computed from audited financial",
            "statements. Use them to verify claims in the thesis and risk narratives.",
            "",
            "PCS (Probabilistic Confidence Score) QUESTIONS:",
            "",
            "Q1 - Operational Feasibility (q1_operational_feasibility):",
            "  Given the trailing financials, does the company have the runway and levers",
            "  to execute the stated turnaround?",
            "",
            "Q2 - Risk Bounded (q2_risk_bounded):",
            "  Is the analyst's assessment of the dominant risk supported by specific evidence",
            "  or precedent, not just assumptions?",
            "",
            "Q3 - Precedent Grounded (q3_precedent_grounded):",
            "  Does the thesis align with historical base rates for this type of situation,",
            "  or does it rely on unprecedented outcomes?",
            "",
            "Q4 - Downside Steelmanned (q4_downside_steelmanned):",
            "  Has the analyst adequately steelmanned the bear case, or is the worst case",
            "  a weak strawman?",
            "",
            "Q5 - Catalyst Concrete (q5_catalyst_concrete):",
            "  Are the catalysts exogenous and verifiable, or merely 'management will execute better'?",
            "",
            "3-TIER GRADING (use instead of Yes/No):",
            "- STRONG: well-supported, evidence-backed reasoning",
            "- MODERATE: partially supported, gaps or ambiguity present",
            "- WEAK: unsupported, flawed reasoning, or inapplicable",
            "",
            "EVIDENCE RULES:",
            "- Each answer MUST include an evidence_source field.",
            "- evidence_source must cite the SPECIFIC context you used (e.g., 'Trailing financial ratios (audited statements)',",
            "  'Thesis summary', 'Catalysts', 'Key Risks', 'Base case assumptions')",
            "  or the exact string 'NO_EVIDENCE' if you cannot find supporting evidence.",
            "- Do NOT use vague citations like 'industry reports' or 'general consensus'.",
            "- Honest NO_EVIDENCE is better than a vague citation.",
            "",
            "Return ONLY valid JSON matching the required schema.",
        ])

    def _build_user_prompt(self, review_input: EpistemicReviewInput) -> str:
        """Format review input for the user message."""
        lines = [
            f"Ticker: {review_input.ticker}",
            f"Industry: {review_input.industry}",
        ]
        if review_input.company_description:
            lines.append(f"Company Description: {review_input.company_description}")
        lines += [
            f"Dominant Risk Type: {review_input.dominant_risk_type}",
            "",
            f"Thesis Summary: {review_input.thesis_summary}",
        ]

        # Add trailing ratios section if available
        if review_input.trailing_ratios:
            lines.append("")
            lines.append("Trailing Financial Ratios (from audited statements):")
            for key, value in review_input.trailing_ratios.items():
                label = key.replace("_", " ").title()
                if value is not None:
                    lines.append(f"  {label}: {value}")
                else:
                    lines.append(f"  {label}: N/A")

        return "\n".join(lines + [
            "",
            f"Key Risks: {json.dumps(review_input.key_risks)}",
            f"Catalysts: {json.dumps(review_input.catalysts)}",
            f"Moat Assessment: {review_input.moat_assessment}",
            "",
            "Answer all 5 PCS questions based on the context above.",
            "Grade each as STRONG, MODERATE, or WEAK.",
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
            "temperature": self.temperature,
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
    (weak_evidence_flags, no_evidence_count).
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
        weak_evidence_flags[key] = is_weak_evidence(
            evidence_source, context_markers=EPISTEMIC_CONTEXT_MARKERS,
        )
        if evidence_source.upper() == "NO_EVIDENCE":
            no_evidence_count += 1

    result = dict(pcs_answers)
    result["weak_evidence_flags"] = weak_evidence_flags
    result["no_evidence_count"] = no_evidence_count

    return result
