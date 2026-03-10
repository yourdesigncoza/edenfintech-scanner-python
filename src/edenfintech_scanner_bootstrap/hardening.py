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
