"""Auto-analyze orchestrator -- single function call to replace the manual review workflow.

Wires analyst, validator, and epistemic reviewer into an automated flow with retry logic.
Produces a finalized structured analysis overlay from raw bundles.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .analyst import ClaudeAnalystClient, generate_llm_analysis_draft
from .config import AppConfig
from .epistemic_reviewer import (
    EpistemicReviewerClient,
    EpistemicReviewInput,
    epistemic_review,
    extract_epistemic_input,
)
from .live_scan import run_live_scan
from .sector import load_sector_knowledge
from .structured_analysis import finalize_structured_analysis
from .validator import RedTeamValidatorClient, validate_overlay

logger = logging.getLogger(__name__)

_PCS_QUESTION_KEYS = [
    "q1_operational", "q2_regulatory", "q3_precedent",
    "q4_nonbinary", "q5_macro",
]


@dataclass(frozen=True)
class AutoAnalyzeResult:
    """Result of a fully automated analysis run."""

    ticker: str
    finalized_overlay: dict
    validator_verdict: dict
    epistemic_result: dict
    retries_used: int
    raw_bundle: dict


def auto_analyze(
    ticker: str,
    *,
    config: AppConfig,
    out_dir: Path,
    analyst_client: ClaudeAnalystClient | None = None,
    validator_client: RedTeamValidatorClient | None = None,
    epistemic_client: EpistemicReviewerClient | None = None,
    sector_knowledge: dict | None = None,
    max_retries: int = 2,
) -> AutoAnalyzeResult:
    """Run the full automated analysis flow for a single ticker.

    Steps:
    1. Fetch raw bundles via run_live_scan
    2. Load merged bundle
    3. Try to load sector knowledge if not provided
    4. Analyst draft with retry loop (validator APPROVE/REJECT)
    5. Epistemic review (always runs)
    6. Merge epistemic PCS answers into overlay
    7. Finalize with LLM_CONFIRMED provenance
    """
    # Step 1: Fetch raw bundles
    scan_result = run_live_scan(
        [ticker], out_dir=out_dir, stop_at="raw-bundle", config=config,
    )

    # Step 2: Load merged bundle
    merged_path = scan_result.written_paths["merged_raw"]
    merged_bundle = json.loads(merged_path.read_text())

    # Step 3: Load sector knowledge if not provided
    if sector_knowledge is None:
        raw_candidate = merged_bundle["raw_candidates"][0]
        industry = raw_candidate.get("industry", "")
        if industry:
            try:
                sector_knowledge = load_sector_knowledge(industry)
            except Exception:
                logger.warning(
                    "Could not load sector knowledge for '%s'; proceeding without", industry,
                )

    # Step 4: Create analyst client if not injected
    if analyst_client is None:
        config.require("anthropic_api_key")
        analyst_client = ClaudeAnalystClient(
            config.anthropic_api_key, model=config.analyst_model,
        )

    # Step 5: Retry loop
    objections: list[dict] | None = None
    retries_used = 0
    validation_result: dict = {}

    for attempt in range(max_retries + 1):
        draft = generate_llm_analysis_draft(
            merged_bundle,
            client=analyst_client,
            sector_knowledge=sector_knowledge,
            validator_objections=objections,
        )

        overlay_candidate = draft["structured_candidates"][0]
        raw_candidate = merged_bundle["raw_candidates"][0]

        validation_result = validate_overlay(
            overlay_candidate, raw_candidate, client=validator_client,
        )

        if validation_result["verdict"] == "APPROVE":
            break

        # REJECT: collect objections for next attempt
        objections = validation_result.get("objections", [])
        # Convert string objections to dict format if needed
        if objections and isinstance(objections[0], str):
            objections = [{"objection": obj} for obj in objections]
        if attempt < max_retries:
            retries_used += 1

    # Step 6: Epistemic review (always runs)
    review_input = extract_epistemic_input(overlay_candidate)
    epistemic_result = epistemic_review(review_input, client=epistemic_client)

    # Step 7: Merge epistemic PCS answers into overlay candidate
    for key in _PCS_QUESTION_KEYS:
        if key in epistemic_result:
            pcs_answer = epistemic_result[key]
            overlay_candidate["epistemic_inputs"][key] = {
                "answer": pcs_answer["answer"],
                "justification": pcs_answer["justification"],
                "evidence": pcs_answer.get("evidence", ""),
            }

    # Step 8: Finalize
    finalized = finalize_structured_analysis(
        draft,
        reviewer=f"llm:{config.analyst_model}",
        final_status="LLM_CONFIRMED",
        note="Automated finalization via auto_analyze orchestrator",
    )

    return AutoAnalyzeResult(
        ticker=ticker,
        finalized_overlay=finalized,
        validator_verdict=validation_result,
        epistemic_result=epistemic_result,
        retries_used=retries_used,
        raw_bundle=merged_bundle,
    )
