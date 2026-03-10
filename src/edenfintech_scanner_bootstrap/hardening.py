"""Hardening gates for LLM bias detection in scan pipeline.

Provides three gates to catch common LLM optimism patterns before
overlays reach the deterministic pipeline:

1. detect_probability_anchoring -- flags suspiciously round 60% base
   probability with friction-carrying risk types
2. score_evidence_quality -- counts concrete vs vague citations in
   overlay provenance using epistemic_reviewer markers
3. cagr_exception_panel -- 3-agent unanimous vote for CAGR exceptions
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from edenfintech_scanner_bootstrap.epistemic_reviewer import (
    CONCRETE_SOURCE_MARKERS,
    is_weak_evidence,
)


# ---------------------------------------------------------------------------
# Probability anchoring detection
# ---------------------------------------------------------------------------

FRICTION_RISK_TYPES: set[str] = {
    "Cyclical/Macro",
    "Regulatory/Political",
    "Legal/Investigation",
    "Structural fragility (SPOF)",
}


def detect_probability_anchoring(
    base_probability_pct: float,
    dominant_risk_type: str,
) -> dict | None:
    """Flag suspiciously anchored 60% base probability with friction risk.

    LLMs tend to default to 60% when uncertain. Combined with a
    friction-carrying risk type, this signals the probability may not
    reflect genuine analysis.

    Returns flag dict if detected, None otherwise.
    """
    if base_probability_pct != 60.0:
        return None
    if dominant_risk_type not in FRICTION_RISK_TYPES:
        return None
    return {
        "flag": "PROBABILITY_ANCHORING_SUSPECT",
        "base_probability_pct": base_probability_pct,
        "dominant_risk_type": dominant_risk_type,
        "reason": (
            f"Base probability is exactly 60% with friction-carrying risk type "
            f"'{dominant_risk_type}'. This combination suggests anchoring bias -- "
            f"LLMs default to 60% when uncertain about friction-heavy situations."
        ),
    }


# ---------------------------------------------------------------------------
# Evidence quality scoring
# ---------------------------------------------------------------------------

def score_evidence_quality(
    overlay_candidate: dict,
    *,
    concrete_threshold: float = 0.5,
) -> dict:
    """Score overlay provenance for concrete vs vague evidence citations.

    Uses CONCRETE_SOURCE_MARKERS from epistemic_reviewer to identify
    concrete citations, and is_weak_evidence to flag vague ones.

    Returns dict with counts, ratio, and optional methodology warning.
    """
    provenance = overlay_candidate.get("provenance", [])

    total_citations = 0
    concrete_count = 0
    vague_count = 0

    for entry in provenance:
        review_note = entry.get("review_note", "")
        if not review_note:
            continue
        total_citations += 1
        lower = review_note.lower()
        if any(marker in lower for marker in CONCRETE_SOURCE_MARKERS):
            concrete_count += 1
        elif is_weak_evidence(review_note):
            vague_count += 1

    concrete_ratio = concrete_count / total_citations if total_citations > 0 else 0.0

    methodology_warning: str | None = None
    if total_citations > 0 and concrete_ratio < concrete_threshold:
        methodology_warning = (
            f"Evidence quality below threshold: {concrete_count}/{total_citations} "
            f"concrete citations ({concrete_ratio:.1%}). "
            f"Minimum {concrete_threshold:.0%} concrete evidence required."
        )

    return {
        "total_citations": total_citations,
        "concrete_count": concrete_count,
        "vague_count": vague_count,
        "concrete_ratio": concrete_ratio,
        "methodology_warning": methodology_warning,
    }


# ---------------------------------------------------------------------------
# CAGR exception panel — 3-agent unanimous vote
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExceptionVote:
    """Single agent vote on a CAGR exception request."""
    agent: str
    approve: bool
    reasoning: str


@dataclass(frozen=True)
class ExceptionPanelResult:
    """Result of 3-agent CAGR exception vote."""
    votes: list[ExceptionVote]
    unanimous: bool
    approved: bool


_EXCEPTION_AGENTS = [
    ("analyst", "analyst_transport"),
    ("validator", "validator_transport"),
    ("epistemic", "epistemic_transport"),
]


def _build_exception_prompt(overlay_candidate: dict, raw_candidate: dict) -> str:
    """Build focused CAGR exception vote prompt from overlay data."""
    analysis = overlay_candidate.get("analysis_inputs", {})
    ticker = overlay_candidate.get("ticker", "UNKNOWN")
    thesis = analysis.get("thesis_summary", "N/A")
    catalysts = analysis.get("catalyst_stack", [])
    risks = analysis.get("key_risks", [])
    base_assumptions = analysis.get("base_case_assumptions", {})
    cagr = base_assumptions.get("cagr_pct", "N/A")

    catalyst_text = "\n".join(
        f"  - {c.get('catalyst', c) if isinstance(c, dict) else c}"
        for c in catalysts
    ) or "  None provided"

    risk_text = "\n".join(f"  - {r}" for r in risks) or "  None provided"

    return "\n".join([
        f"CAGR EXCEPTION VOTE REQUEST for {ticker}",
        "",
        f"This candidate has a {cagr}% base CAGR (20-29.9% exception range).",
        "Given the evidence summary below, should this candidate be granted",
        "an exception to proceed despite the elevated CAGR? Vote APPROVE or REJECT.",
        "",
        f"Thesis: {thesis}",
        "",
        "Catalysts:",
        catalyst_text,
        "",
        "Key Risks:",
        risk_text,
        "",
        'Respond with JSON: {"approve": true/false, "reasoning": "your reasoning"}',
    ])


def cagr_exception_panel(
    overlay_candidate: dict,
    raw_candidate: dict,
    *,
    analyst_transport: Callable[[dict], dict] | None = None,
    validator_transport: Callable[[dict], dict] | None = None,
    epistemic_transport: Callable[[dict], dict] | None = None,
    config=None,
) -> ExceptionPanelResult:
    """Run 3-agent CAGR exception vote panel.

    Each agent receives a focused prompt asking whether a candidate with
    a 20-29.9% CAGR should be granted an exception. Approval requires
    unanimous agreement from all three agents.

    Uses lightweight direct transport calls (not full client classes)
    to avoid heavy analysis cost.
    """
    transports = {
        "analyst": analyst_transport,
        "validator": validator_transport,
        "epistemic": epistemic_transport,
    }

    prompt = _build_exception_prompt(overlay_candidate, raw_candidate)
    votes: list[ExceptionVote] = []

    for agent_name, transport_key in _EXCEPTION_AGENTS:
        transport = transports[agent_name]
        if transport is None:
            raise ValueError(f"{transport_key} is required for CAGR exception panel")

        payload = {
            "system": (
                f"You are the {agent_name} agent voting on a CAGR exception. "
                "Evaluate the evidence and vote APPROVE or REJECT."
            ),
            "messages": [{"role": "user", "content": prompt}],
        }

        response = transport(payload)
        parsed = json.loads(response["text"])

        votes.append(ExceptionVote(
            agent=agent_name,
            approve=bool(parsed["approve"]),
            reasoning=str(parsed["reasoning"]),
        ))

    approvals = [v.approve for v in votes]
    all_same = len(set(approvals)) == 1
    all_approved = all(approvals)

    return ExceptionPanelResult(
        votes=votes,
        unanimous=all_same,
        approved=all_approved,
    )
