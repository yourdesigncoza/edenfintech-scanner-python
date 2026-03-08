from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib import error, request

from .assets import contract_path, load_json, load_text, rules_root
from .config import AppConfig, load_config


JudgeTransport = Callable[[dict, AppConfig], dict]


def _judge_contract() -> dict:
    return load_json(contract_path("codex_final_judge"))


def validate_judge_result(result: dict) -> dict:
    contract = _judge_contract()
    if not isinstance(result, dict):
        raise ValueError("judge result must be an object")

    for key in contract["outputs"]["required"]:
        if key not in result:
            raise ValueError(f"judge result missing required key: {key}")

    if result["verdict"] not in contract["enums"]["verdict"]:
        raise ValueError(f"judge verdict invalid: {result['verdict']}")
    if result["target_stage"] not in contract["enums"]["target_stage"]:
        raise ValueError(f"judge target_stage invalid: {result['target_stage']}")
    if not isinstance(result["findings"], list):
        raise ValueError("judge findings must be a list")
    if not all(isinstance(item, str) for item in result["findings"]):
        raise ValueError("judge findings must contain only strings")
    if not isinstance(result["reroute_reason"], str):
        raise ValueError("judge reroute_reason must be a string")

    if result["verdict"] == "APPROVE":
        if result["target_stage"] != "approve":
            raise ValueError("judge APPROVE verdict must target approve")
        if result["reroute_reason"]:
            raise ValueError("judge APPROVE verdict must not include a reroute_reason")
    else:
        if result["target_stage"] == "approve":
            raise ValueError("judge REVISE verdict must target a prior stage")
        if not result["reroute_reason"]:
            raise ValueError("judge REVISE verdict must include a reroute_reason")

    extra_keys = set(result) - set(contract["outputs"]["required"])
    if extra_keys:
        raise ValueError(f"judge result contains unsupported keys: {sorted(extra_keys)}")

    return result


def local_judge(report: dict, execution_log: dict) -> dict:
    findings: list[str] = []
    target_stage = "approve"
    verdict = "APPROVE"
    reroute_reason = ""

    ranked_tickers = {item["ticker"] for item in report["ranked_candidates"]}
    pending_tickers = {item["ticker"] for item in report.get("pending_human_review", [])}
    overlap = ranked_tickers & pending_tickers
    if overlap:
        verdict = "REVISE"
        target_stage = "report_assembly"
        reroute_reason = "ranked_exception_candidate_present"
        findings.extend(
            f"{ticker} appears in both ranked candidates and pending human review."
            for ticker in sorted(overlap)
        )

    for packet in report["rejected_at_analysis_detail_packets"]:
        epi = packet.get("epistemic_confidence")
        if epi and epi.get("effective_probability", 0) >= 60:
            findings.append(
                f"{packet['ticker']} was rejected after epistemic review despite effective probability >= 60; verify rejection basis."
            )

    if report["current_holding_overlays"]:
        missing_status = [item["ticker"] for item in report["current_holding_overlays"] if not item.get("status_in_scan")]
        if missing_status:
            verdict = "REVISE"
            target_stage = "report_assembly"
            reroute_reason = reroute_reason or "judge_payload_invalid"
            findings.append(f"Holding overlays missing status for: {', '.join(sorted(missing_status))}")

    return validate_judge_result(
        {
            "verdict": verdict,
            "target_stage": target_stage,
            "findings": findings,
            "reroute_reason": reroute_reason,
        }
    )


def _safe_fallback_judge(report: dict, execution_log: dict, reason_code: str, detail: str) -> dict:
    local_result = local_judge(report, execution_log)
    findings = [f"Codex judge unavailable; deterministic fallback used: {detail}"]
    findings.extend(local_result["findings"])
    return validate_judge_result(
        {
            "verdict": "REVISE",
            "target_stage": "report_assembly",
            "findings": findings,
            "reroute_reason": reason_code,
        }
    )


def _judge_prompt(report: dict, execution_log: dict) -> str:
    methodology_rulebook = load_json(rules_root() / "canonical-rulebook.json")
    stage_contracts = {
        stage_id: load_json(contract_path(stage_id))
        for stage_id in [
            "screening",
            "cluster_analysis",
            "epistemic_review",
            "report_assembly",
            "codex_final_judge",
        ]
    }
    instructions = (
        "You are the Codex Final Judge for the EdenFinTech scan pipeline.\n"
        "Review the assembled report for methodology compliance.\n"
        "You may only approve or reroute to one of: screening, cluster_analysis, epistemic_review, report_assembly, approve.\n"
        "You may not change methodology, scores, rankings, or candidate outcomes.\n"
        "Return only JSON with keys: verdict, target_stage, findings, reroute_reason.\n"
        "If you are uncertain or detect malformed inputs, prefer REVISE with a specific reroute_reason.\n"
    )
    return (
        f"{instructions}\n"
        f"Methodology rulebook:\n{json.dumps(methodology_rulebook, indent=2)}\n\n"
        f"Stage contracts:\n{json.dumps(stage_contracts, indent=2)}\n\n"
        f"Assembled report:\n{json.dumps(report, indent=2)}\n\n"
        f"Execution log:\n{json.dumps(execution_log, indent=2)}\n"
    )


def _extract_response_text(response_payload: dict) -> str:
    output = response_payload.get("output", [])
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI judge response did not contain output text")


def _extract_structured_execution_log(markdown_text: str) -> dict | None:
    pattern = re.compile(r"## Structured Execution Log\s+```json\s*(\{.*?\})\s*```", re.DOTALL)
    match = pattern.search(markdown_text)
    if not match:
        return None
    return json.loads(match.group(1))


def openai_judge_transport(request_payload: dict, config: AppConfig) -> dict:
    config.require("openai_api_key")
    http_request = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        body_preview = body.strip().replace("\n", " ")
        if len(body_preview) > 400:
            body_preview = f"{body_preview[:400]}..."
        raise RuntimeError(f"OpenAI judge request failed: HTTP {exc.code}: {body_preview}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI judge request failed: {exc}") from exc


def codex_judge(
    report: dict,
    execution_log: dict,
    *,
    config: AppConfig | None = None,
    transport: JudgeTransport | None = None,
) -> dict:
    app_config = config or load_config()
    if not app_config.openai_api_key:
        return local_judge(report, execution_log)

    request_payload = {
        "model": app_config.codex_judge_model,
        "input": _judge_prompt(report, execution_log),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "codex_final_judge",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["verdict", "target_stage", "findings", "reroute_reason"],
                    "properties": {
                        "verdict": {"type": "string", "enum": ["APPROVE", "REVISE"]},
                        "target_stage": {
                            "type": "string",
                            "enum": ["screening", "cluster_analysis", "epistemic_review", "report_assembly", "approve"],
                        },
                        "findings": {"type": "array", "items": {"type": "string"}},
                        "reroute_reason": {"type": "string"},
                    },
                },
                "strict": True,
            }
        },
    }

    judge_transport = transport or openai_judge_transport
    try:
        response_payload = judge_transport(request_payload, app_config)
        raw_text = _extract_response_text(response_payload)
        return validate_judge_result(json.loads(raw_text))
    except RuntimeError as exc:
        return _safe_fallback_judge(report, execution_log, "judge_transport_unavailable", str(exc))
    except Exception as exc:
        return _safe_fallback_judge(report, execution_log, "judge_payload_invalid", str(exc))


def run_judge_file(
    report_path: Path,
    execution_log_path: Path,
    *,
    config: AppConfig | None = None,
    transport: JudgeTransport | None = None,
) -> dict:
    report = load_json(report_path)
    if execution_log_path.suffix.lower() == ".json":
        execution_log_wrapper = load_json(execution_log_path)
        execution_log = execution_log_wrapper.get("execution_log", execution_log_wrapper)
    else:
        markdown_text = load_text(execution_log_path)
        execution_log = _extract_structured_execution_log(markdown_text)
        if execution_log is None:
            execution_log = {
                "source_path": str(execution_log_path),
                "content": markdown_text,
            }
    return codex_judge(report, execution_log, config=config, transport=transport)
