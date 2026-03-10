from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .fmp import FmpTransport
from .gemini import DEFAULT_GEMINI_MODEL, GeminiTransport
from .importers import build_scan_input
from .live_scan import LiveScanResult, run_live_scan
from .pipeline import run_scan
from .reporting import write_execution_log
from .structured_analysis import (
    apply_structured_analysis,
    review_structured_analysis_file,
    suggest_review_notes_file,
)


@dataclass(frozen=True)
class ReviewPackageResult:
    out_dir: Path
    written_paths: dict[str, Path]
    live_scan_result: LiveScanResult


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _reuse_raw_bundle_dir(structured_analysis_path: Path) -> Path | None:
    review_dir = structured_analysis_path.parent
    package_dir = review_dir.parent
    candidate = package_dir / "raw"
    required = [
        candidate / "fmp-raw.json",
        candidate / "gemini-raw.json",
        candidate / "merged-raw.json",
        candidate / "structured-analysis-template.json",
        candidate / "structured-analysis-draft.json",
    ]
    if review_dir.name != "review":
        return None
    if all(path.exists() for path in required):
        return candidate
    return None


def _copy_reused_raw_bundle(raw_source_dir: Path, raw_dir: Path) -> dict[str, Path]:
    mapping = {
        "fmp_raw": "fmp-raw.json",
        "gemini_raw": "gemini-raw.json",
        "merged_raw": "merged-raw.json",
        "structured_analysis_template": "structured-analysis-template.json",
        "structured_analysis_draft": "structured-analysis-draft.json",
    }
    written_paths: dict[str, Path] = {}
    raw_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in mapping.items():
        source = raw_source_dir / filename
        target = raw_dir / filename
        shutil.copyfile(source, target)
        written_paths[key] = target
    return written_paths


def build_review_package(
    tickers: list[str],
    *,
    out_dir: Path,
    config: AppConfig,
    structured_analysis_path: Path | None = None,
    focus: str | None = None,
    research_question: str | None = None,
    gemini_model: str = DEFAULT_GEMINI_MODEL,
    fmp_transport: FmpTransport | None = None,
    gemini_transport: GeminiTransport | None = None,
    use_analyst: bool = False,
) -> ReviewPackageResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    review_dir = out_dir / "review"
    final_dir = out_dir / "final"

    reused_raw_dir = _reuse_raw_bundle_dir(structured_analysis_path) if structured_analysis_path is not None else None
    if reused_raw_dir is not None:
        written_paths = _copy_reused_raw_bundle(reused_raw_dir, raw_dir)
        raw_live_scan_result = LiveScanResult(stop_at="raw-bundle", out_dir=raw_dir, written_paths=written_paths)
    else:
        raw_live_scan_result = run_live_scan(
            tickers,
            out_dir=raw_dir,
            stop_at="raw-bundle",
            config=config,
            fmp_transport=fmp_transport,
            gemini_transport=gemini_transport,
            focus=focus,
            research_question=research_question,
            gemini_model=gemini_model,
            use_analyst=use_analyst,
        )
        written_paths = dict(raw_live_scan_result.written_paths)
    stop_at = "raw-bundle"
    review_source = written_paths["structured_analysis_draft"]

    if structured_analysis_path is not None:
        stop_at = "report"
        packaged_overlay_path = final_dir / "structured-analysis-finalized.json"
        packaged_overlay_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(structured_analysis_path, packaged_overlay_path)
        written_paths["structured_analysis_finalized"] = packaged_overlay_path
        review_source = packaged_overlay_path

        merged_bundle = json.loads(written_paths["merged_raw"].read_text(encoding="utf-8"))
        structured_payload = json.loads(packaged_overlay_path.read_text(encoding="utf-8"))
        enriched_bundle = apply_structured_analysis(merged_bundle, structured_payload)
        enriched_path = final_dir / "enriched-raw.json"
        _write_json(enriched_path, enriched_bundle)
        written_paths["enriched_raw"] = enriched_path

        scan_input = build_scan_input(enriched_bundle)
        scan_input_path = final_dir / "scan-input.json"
        _write_json(scan_input_path, scan_input)
        written_paths["scan_input"] = scan_input_path

        artifacts = run_scan(scan_input, judge_config=config)
        report_json_path = final_dir / "report.json"
        report_markdown_path = final_dir / "report.md"
        execution_log_path = final_dir / "execution-log.md"
        judge_path = final_dir / "judge.json"
        _write_json(report_json_path, artifacts.report_json)
        report_markdown_path.write_text(artifacts.report_markdown, encoding="utf-8")
        write_execution_log(execution_log_path, artifacts.report_json, artifacts.execution_log, artifacts.judge)
        _write_json(judge_path, artifacts.judge)
        written_paths["report_json"] = report_json_path
        written_paths["report_markdown"] = report_markdown_path
        written_paths["execution_log"] = execution_log_path
        written_paths["judge_json"] = judge_path

    review_checklist_json = review_dir / "review-checklist.json"
    review_checklist_md = review_dir / "review-checklist.md"
    review_structured_analysis_file(
        review_source,
        json_out=review_checklist_json,
        markdown_out=review_checklist_md,
    )
    written_paths["review_checklist_json"] = review_checklist_json
    written_paths["review_checklist_markdown"] = review_checklist_md

    review_note_suggestions_json = review_dir / "review-note-suggestions.json"
    review_note_suggestions_md = review_dir / "review-note-suggestions.md"
    suggest_review_notes_file(
        review_source,
        json_out=review_note_suggestions_json,
        markdown_out=review_note_suggestions_md,
    )
    written_paths["review_note_suggestions_json"] = review_note_suggestions_json
    written_paths["review_note_suggestions_markdown"] = review_note_suggestions_md

    manifest_path = out_dir / "review-package-manifest.json"
    manifest = {
        "out_dir": str(out_dir),
        "stop_at": stop_at,
        "directories": {
            "raw": str(raw_dir),
            "review": str(review_dir),
            "final": str(final_dir),
        },
        "artifacts": {key: str(path) for key, path in written_paths.items()},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    written_paths["review_package_manifest"] = manifest_path

    live_scan_result = LiveScanResult(stop_at=stop_at, out_dir=out_dir, written_paths=written_paths)
    return ReviewPackageResult(
        out_dir=out_dir,
        written_paths=written_paths,
        live_scan_result=live_scan_result,
    )
