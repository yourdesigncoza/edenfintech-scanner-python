from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .fmp import FmpTransport
from .gemini import DEFAULT_GEMINI_MODEL, GeminiTransport
from .live_scan import LiveScanResult, run_live_scan
from .structured_analysis import review_structured_analysis_file, suggest_review_notes_file


@dataclass(frozen=True)
class ReviewPackageResult:
    out_dir: Path
    written_paths: dict[str, Path]
    live_scan_result: LiveScanResult


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
) -> ReviewPackageResult:
    stop_at = "report" if structured_analysis_path is not None else "raw-bundle"
    live_scan_result = run_live_scan(
        tickers,
        out_dir=out_dir,
        stop_at=stop_at,
        structured_analysis_path=structured_analysis_path,
        config=config,
        fmp_transport=fmp_transport,
        gemini_transport=gemini_transport,
        focus=focus,
        research_question=research_question,
        gemini_model=gemini_model,
    )

    written_paths = dict(live_scan_result.written_paths)
    review_source = structured_analysis_path or live_scan_result.written_paths["structured_analysis_draft"]

    review_checklist_json = out_dir / "review-checklist.json"
    review_checklist_md = out_dir / "review-checklist.md"
    review_structured_analysis_file(
        review_source,
        json_out=review_checklist_json,
        markdown_out=review_checklist_md,
    )
    written_paths["review_checklist_json"] = review_checklist_json
    written_paths["review_checklist_markdown"] = review_checklist_md

    review_note_suggestions_json = out_dir / "review-note-suggestions.json"
    review_note_suggestions_md = out_dir / "review-note-suggestions.md"
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
        "stop_at": live_scan_result.stop_at,
        "artifacts": {key: str(path) for key, path in written_paths.items()},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    written_paths["review_package_manifest"] = manifest_path

    return ReviewPackageResult(
        out_dir=out_dir,
        written_paths=written_paths,
        live_scan_result=live_scan_result,
    )
