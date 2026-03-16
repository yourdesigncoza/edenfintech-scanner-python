"""Auto-analyze orchestrator -- single function call to replace the manual review workflow.

Wires analyst, validator, and epistemic reviewer into an automated flow with retry logic.
Produces a finalized structured analysis overlay from raw bundles.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from typing import Callable

from .analyst import ClaudeAnalystClient, generate_llm_analysis_draft
from .cache import GeminiCacheStore
from .config import AppConfig
from .fmp import FmpTransport
from .llm_transport import LlmResponseError, default_anthropic_transport, default_openai_transport
from .epistemic_reviewer import (
    EpistemicReviewerClient,
    EpistemicReviewInput,
    epistemic_review,
    extract_epistemic_input,
)
from .live_scan import run_live_scan
from .sector import ensure_sector_knowledge
from .structured_analysis import finalize_structured_analysis
from .llm_logger import LlmInteractionLog, wrap_gemini_transport, wrap_transport
from .validator import PreMortemValidatorClient, RedTeamValidatorClient, validate_overlay

logger = logging.getLogger(__name__)

_PCS_QUESTION_KEYS = [
    "q1_operational_feasibility", "q2_risk_bounded", "q3_precedent_grounded",
    "q4_downside_steelmanned", "q5_catalyst_concrete",
]


def _save_llm_artifact(out_dir: Path, filename: str, data: dict) -> None:
    """Write an LLM result artifact to the run output directory.

    Uses atomic write (tmp + os.replace) so partial writes never corrupt.
    Raises on any failure so we never silently lose data.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(out_dir), prefix=f".{filename}.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(target))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"Artifact not on disk after write: {target}")


def _make_transport(config: AppConfig) -> Callable[[dict], dict]:
    """Build LLM transport from config provider setting."""
    if config.llm_provider == "openai":
        config.require("openai_api_key")

        def transport(payload: dict) -> dict:
            model = config.llm_model  # always use configured OpenAI model, ignore Anthropic per-stage names
            timeout = payload.pop("timeout", config.llm_timeout)
            return default_openai_transport(
                payload, api_key=config.openai_api_key, model=model,
                timeout=timeout,
            )
        return transport
    else:
        config.require("anthropic_api_key")

        def transport(payload: dict) -> dict:
            model = payload.get("model", config.analyst_model)
            # Strip keys not part of the Anthropic API
            clean = {k: v for k, v in payload.items() if k not in ("model", "timeout")}
            return default_anthropic_transport(
                clean, api_key=config.anthropic_api_key, model=model,
            )
        return transport


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
    fmp_transport: FmpTransport | None = None,
    analyst_client: ClaudeAnalystClient | None = None,
    validator_client: RedTeamValidatorClient | None = None,
    premortem_client: PreMortemValidatorClient | None = None,
    epistemic_client: EpistemicReviewerClient | None = None,
    sector_knowledge: dict | None = None,
    gemini_cache: GeminiCacheStore | None = None,
    peer_context: list[dict] | None = None,
    max_retries: int = 2,
    llm_log: LlmInteractionLog | None = None,
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
    # Build wrapped Gemini transport for logging if llm_log provided
    gemini_transport_for_scan = None
    if llm_log is not None:
        from .gemini import _default_transport as _gemini_default_transport
        gemini_transport_for_scan = wrap_gemini_transport(_gemini_default_transport, llm_log)

    # Step 1: Fetch raw bundles
    print(f"[{ticker}] Step 1/6: Fetching raw bundles ...")
    scan_result = run_live_scan(
        [ticker], out_dir=out_dir, stop_at="raw-bundle", config=config,
        fmp_transport=fmp_transport, gemini_cache=gemini_cache,
        gemini_transport=gemini_transport_for_scan,
    )

    # Step 2: Load merged bundle
    merged_path = scan_result.written_paths["merged_raw"]
    merged_bundle = json.loads(merged_path.read_text())

    # Log Gemini cache hit if transport was not called
    if llm_log is not None:
        has_gemini_record = any(r["agent"] == "gemini/qualitative" for r in llm_log._records)
        gemini_raw_path = out_dir / "gemini-raw.json"
        if not has_gemini_record and gemini_raw_path.exists():
            gemini_data = json.loads(gemini_raw_path.read_text())
            model = gemini_data.get("model", "gemini")
            llm_log.record_cache_hit("gemini/qualitative", model, gemini_data)

    # Step 3: Load sector knowledge if not provided (auto-hydrate if missing/stale)
    if sector_knowledge is None:
        raw_candidate = merged_bundle["raw_candidates"][0]
        industry = raw_candidate.get("industry", "")
        if industry:
            print(f"[{ticker}] Step 2/6: Sector knowledge for '{industry}' ...", end=" ", flush=True)
            try:
                sector_knowledge = ensure_sector_knowledge(
                    industry, config=config,
                )
                print("OK")
            except Exception:
                print("FAILED (proceeding without)")
                logger.warning(
                    "Could not ensure sector knowledge for '%s'; proceeding without",
                    industry,
                )

    # Step 4: Create agent clients if not injected
    if analyst_client is None or validator_client is None or epistemic_client is None or premortem_client is None:
        transport = _make_transport(config)
        if llm_log is not None:
            transport = wrap_transport(transport, llm_log, model_name=config.llm_model)
        api_key = (config.openai_api_key if config.llm_provider == "openai"
                   else config.anthropic_api_key)
        if analyst_client is None:
            analyst_client = ClaudeAnalystClient(
                api_key,
                model=config.analyst_model,
                fundamentals_model=config.analyst_fundamentals_model,
                qualitative_model=config.analyst_qualitative_model,
                synthesis_model=config.analyst_synthesis_model,
                transport=transport,
                synthesis_timeout=config.llm_synthesis_timeout,
                artifact_dir=out_dir,
                temperature=config.analyst_temperature,
                top_k=1,
            )
        if validator_client is None:
            validator_client = RedTeamValidatorClient(
                api_key, transport=transport,
                temperature=config.adversarial_temperature,
            )
        if premortem_client is None:
            premortem_client = PreMortemValidatorClient(
                api_key, transport=transport,
                temperature=config.adversarial_temperature,
            )
        if epistemic_client is None:
            epistemic_client = EpistemicReviewerClient(
                api_key, transport=transport,
                temperature=config.reviewer_temperature,
            )

    # Step 5: Retry loop
    objections: list[dict] | None = None
    retries_used = 0
    validation_result: dict = {}

    for attempt in range(max_retries + 1):
        attempt_label = f" (retry {attempt})" if attempt > 0 else ""
        suffix = f"-retry{attempt}" if attempt > 0 else ""

        print(f"[{ticker}] Step 3/6: Analyst draft (3-stage){attempt_label} ...", end=" ", flush=True)
        try:
            draft = generate_llm_analysis_draft(
                merged_bundle,
                client=analyst_client,
                sector_knowledge=sector_knowledge,
                validator_objections=objections,
                peer_context=peer_context,
            )
            print("OK")
        except (ValueError, LlmResponseError) as exc:
            # Synthesis-raw artifact already saved before _post_validate.
            # Convert to objection and retry (synthesis only, stages 1+2 cached).
            print(f"FAIL ({exc})")
            if attempt < max_retries:
                msg = str(exc)
                if isinstance(exc, LlmResponseError):
                    msg = (f"CRITICAL: Your previous response was NOT valid JSON. "
                           f"Error: {exc}. Return ONLY valid JSON.")
                elif "schema validation failed" in msg:
                    msg = (
                        f"SCHEMA VALIDATION FAILED: {exc}\n"
                        "Fix the errors above using ONLY these valid enum values:\n"
                        "- margin_trend_gate: PASS | PERMANENT_PASS\n"
                        "- final_cluster_status: CLEAR_WINNER | CONDITIONAL_WINNER | LOWER_PRIORITY | ELIMINATED\n"
                        "- catalyst_classification: VALID_CATALYST | SUPPORTING_TAILWIND | WATCH_ONLY | INVALID\n"
                        "- dominant_risk_type: Operational/Financial | Cyclical/Macro | Regulatory/Political | Legal/Investigation | Structural fragility (SPOF)\n"
                        "- setup_pattern: SOLVENCY_SCARE | QUALITY_FRANCHISE | NARRATIVE_DISCOUNT | NEW_OPERATOR | OTHER\n"
                        "- catalyst_stack[].type: HARD | MEDIUM | SOFT\n"
                        "- issues_and_fixes[].evidence_status: ANNOUNCED_ONLY | ACTION_UNDERWAY | EARLY_RESULTS_VISIBLE | PROVEN\n"
                        "Do NOT invent compound values. Include ALL required keys."
                    )
                objections = [{"objection": msg}]
                retries_used += 1
                continue
            raise

        # Gate: verify analyst artifacts exist on disk before proceeding
        for name in ["analyst-fundamentals.json", "analyst-qualitative.json", "analyst-synthesis-raw.json"]:
            p = out_dir / name
            if not p.exists() or p.stat().st_size == 0:
                raise RuntimeError(f"[{ticker}] Required artifact missing: {p}")

        # Save the full draft envelope
        _save_llm_artifact(out_dir, f"analyst-synthesis{suffix}.json", draft)

        overlay_candidate = draft["structured_candidates"][0]
        raw_candidate = merged_bundle["raw_candidates"][0]

        print(f"[{ticker}] Step 4/6: Validator review (parallel){attempt_label} ...", end=" ", flush=True)
        validation_result = validate_overlay(
            overlay_candidate, raw_candidate,
            client=validator_client,
            premortem_client=premortem_client,
        )
        verdict = validation_result["verdict"]
        print(verdict)

        # Save validator result
        _save_llm_artifact(out_dir, f"validator-result{suffix}.json", validation_result)

        if verdict in ("APPROVE", "APPROVE_WITH_CONCERNS"):
            if verdict == "APPROVE_WITH_CONCERNS":
                concerns = validation_result.get("objections", [])
                overlay_candidate["validator_dissent"] = concerns
                print(f"[{ticker}] Validator concerns ({len(concerns)}):")
                for i, c in enumerate(concerns, 1):
                    print(f"  {i}. {c}")
            # Attach thesis_invalidation from pre-mortem validator
            thesis_invalidation = validation_result.get("thesis_invalidation")
            if thesis_invalidation is not None:
                overlay_candidate["thesis_invalidation"] = thesis_invalidation
                _save_llm_artifact(out_dir, f"premortem-result{suffix}.json", {"thesis_invalidation": thesis_invalidation})
                imminent = thesis_invalidation.get("imminent_break_flag", False)
                strong_count = sum(
                    1 for c in thesis_invalidation.get("conditions", [])
                    if c.get("evidence_status") == "strong_evidence"
                )
                weak_count = sum(
                    1 for c in thesis_invalidation.get("conditions", [])
                    if c.get("evidence_status") == "weak_evidence"
                )
                print(f"[{ticker}] Pre-mortem: imminent={imminent}, strong={strong_count}, weak={weak_count}")
            break

        # REJECT: collect objections and print them for operator visibility
        objections = validation_result.get("objections", [])
        # Convert string objections to dict format if needed
        if objections and isinstance(objections[0], str):
            objections = [{"objection": obj} for obj in objections]
        if objections:
            print(f"[{ticker}] Rejection reasons:")
            for i, obj in enumerate(objections, 1):
                reason = obj.get("objection", obj) if isinstance(obj, dict) else obj
                print(f"  {i}. {reason}")
        if attempt < max_retries:
            retries_used += 1
    else:
        # All retries exhausted with REJECT — fatal errors persist, human must review
        final_objections = validation_result.get("objections", [])
        raise RuntimeError(
            f"[{ticker}] Validator rejected all {max_retries + 1} attempts with fatal errors. "
            f"Final objections: {final_objections}"
        )

    # Step 6: Epistemic review (always runs)
    print(f"[{ticker}] Step 5/6: Epistemic review ...", end=" ", flush=True)
    review_input = extract_epistemic_input(
        overlay_candidate, raw_candidate=merged_bundle["raw_candidates"][0],
    )
    epistemic_result = epistemic_review(review_input, client=epistemic_client)
    print("OK")

    # Save epistemic review result
    _save_llm_artifact(out_dir, "epistemic-review-result.json", epistemic_result)

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
    print(f"[{ticker}] Step 6/6: Finalizing ...", end=" ", flush=True)
    finalized = finalize_structured_analysis(
        draft,
        reviewer=f"llm:{config.analyst_model}",
        final_status="LLM_CONFIRMED",
        note="Automated finalization via auto_analyze orchestrator",
    )

    print("OK")

    # Save finalized overlay
    _save_llm_artifact(out_dir, "finalized-overlay.json", finalized)

    # Write LLM interaction audit log if logging enabled
    if llm_log is not None:
        log_path = llm_log.write_markdown(out_dir)
        print(f"[{ticker}] LLM interaction log: {log_path}")

    return AutoAnalyzeResult(
        ticker=ticker,
        finalized_overlay=finalized,
        validator_verdict=validation_result,
        epistemic_result=epistemic_result,
        retries_used=retries_used,
        raw_bundle=merged_bundle,
    )
