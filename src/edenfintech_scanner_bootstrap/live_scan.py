from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, load_config
from .field_generation import generate_structured_analysis_draft
from .fmp import FmpTransport, build_fmp_bundle_with_config, write_fmp_bundle
from .gemini import DEFAULT_GEMINI_MODEL, GeminiTransport, build_gemini_bundle_with_config, merge_fmp_and_gemini_bundles
from .importers import build_scan_input
from .pipeline import run_scan
from .reporting import write_execution_log
from .structured_analysis import apply_structured_analysis, structured_analysis_template


@dataclass(frozen=True)
class LiveScanResult:
    stop_at: str
    out_dir: Path
    written_paths: dict[str, Path]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def run_live_scan(
    tickers: list[str],
    *,
    out_dir: Path,
    stop_at: str = "raw-bundle",
    structured_analysis_path: Path | None = None,
    config: AppConfig | None = None,
    fmp_transport: FmpTransport | None = None,
    gemini_transport: GeminiTransport | None = None,
    focus: str | None = None,
    research_question: str | None = None,
    gemini_model: str = DEFAULT_GEMINI_MODEL,
) -> LiveScanResult:
    if stop_at not in {"raw-bundle", "scan-input", "report"}:
        raise ValueError(f"unsupported stop_at value: {stop_at}")
    if not tickers:
        raise ValueError("tickers must not be empty")

    resolved_config = config or load_config()
    out_dir.mkdir(parents=True, exist_ok=True)
    written_paths: dict[str, Path] = {}

    fmp_bundle = build_fmp_bundle_with_config(
        tickers,
        config=resolved_config,
        transport=fmp_transport,
    )
    fmp_path = out_dir / "fmp-raw.json"
    write_fmp_bundle(fmp_path, fmp_bundle)
    written_paths["fmp_raw"] = fmp_path

    gemini_bundle = build_gemini_bundle_with_config(
        tickers,
        config=resolved_config,
        transport=gemini_transport,
        focus=focus,
        research_question=research_question,
        model=gemini_model,
    )
    gemini_path = out_dir / "gemini-raw.json"
    _write_json(gemini_path, gemini_bundle)
    written_paths["gemini_raw"] = gemini_path

    merged_bundle = merge_fmp_and_gemini_bundles(fmp_bundle, gemini_bundle)
    merged_path = out_dir / "merged-raw.json"
    _write_json(merged_path, merged_bundle)
    written_paths["merged_raw"] = merged_path

    structured_template = structured_analysis_template(merged_bundle)
    structured_template_path = out_dir / "structured-analysis-template.json"
    _write_json(structured_template_path, structured_template)
    written_paths["structured_analysis_template"] = structured_template_path
    structured_draft = generate_structured_analysis_draft(merged_bundle)
    structured_draft_path = out_dir / "structured-analysis-draft.json"
    _write_json(structured_draft_path, structured_draft)
    written_paths["structured_analysis_draft"] = structured_draft_path

    if stop_at == "raw-bundle":
        return LiveScanResult(stop_at=stop_at, out_dir=out_dir, written_paths=written_paths)

    if structured_analysis_path is None:
        raise ValueError(
            "structured_analysis_path is required when stop_at is scan-input or report; "
            f"template written to {structured_template_path}"
        )

    structured_payload = json.loads(structured_analysis_path.read_text())
    enriched_bundle = apply_structured_analysis(merged_bundle, structured_payload)
    enriched_path = out_dir / "enriched-raw.json"
    _write_json(enriched_path, enriched_bundle)
    written_paths["enriched_raw"] = enriched_path

    scan_input = build_scan_input(enriched_bundle)
    scan_input_path = out_dir / "scan-input.json"
    _write_json(scan_input_path, scan_input)
    written_paths["scan_input"] = scan_input_path

    if stop_at == "scan-input":
        return LiveScanResult(stop_at=stop_at, out_dir=out_dir, written_paths=written_paths)

    artifacts = run_scan(scan_input, judge_config=resolved_config)
    report_json_path = out_dir / "report.json"
    report_markdown_path = out_dir / "report.md"
    execution_log_path = out_dir / "execution-log.md"
    judge_path = out_dir / "judge.json"
    _write_json(report_json_path, artifacts.report_json)
    report_markdown_path.write_text(artifacts.report_markdown)
    write_execution_log(execution_log_path, artifacts.report_json, artifacts.execution_log, artifacts.judge)
    _write_json(judge_path, artifacts.judge)
    written_paths["report_json"] = report_json_path
    written_paths["report_markdown"] = report_markdown_path
    written_paths["execution_log"] = execution_log_path
    written_paths["judge_json"] = judge_path
    return LiveScanResult(stop_at=stop_at, out_dir=out_dir, written_paths=written_paths)
