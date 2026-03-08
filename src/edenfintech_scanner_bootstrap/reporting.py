from __future__ import annotations

import json
from pathlib import Path


def _bullet_lines(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2)


def render_scan_markdown(report: dict, execution_log: dict, judge: dict | None = None) -> str:
    lines = [
        f"# {report['title']}",
        "",
        f"- Date: {report['date']}",
        f"- Universe: {report['scan_parameters']['universe']}",
        f"- Focus: {report['scan_parameters']['focus']}",
        f"- Stocks scanned: {report['scan_parameters']['stocks_scanned']}",
        "",
        "## Executive Summary",
    ]
    lines.extend(_bullet_lines(report["executive_summary"]))

    lines.extend(["", "## Ranked Candidates"])
    if report["ranked_candidates"]:
        for candidate in report["ranked_candidates"]:
            lines.extend(
                [
                    f"### {candidate['rank']}. {candidate['ticker']}",
                    f"- Cluster: {candidate['cluster_name']}",
                    f"- Status: {candidate['final_cluster_status']}",
                    f"- Score: {candidate['score']['post_epistemic']['total_score']}",
                    f"- Effective probability: {candidate['epistemic_confidence']['effective_probability']}%",
                    f"- Base-case CAGR: {candidate['base_case']['cagr_pct']}%",
                    f"- Downside: {candidate['worst_case']['downside_pct']}%",
                    f"- Size band: {candidate['position_size']['score_band']}",
                ]
            )
            if candidate.get("thesis_summary"):
                lines.append(f"- Thesis: {candidate['thesis_summary']}")
            if candidate.get("catalysts"):
                lines.append(f"- Catalysts: {', '.join(str(item) for item in candidate['catalysts'])}")
            lines.append("- Epistemic confidence:")
            lines.append(f"  - adjusted confidence {candidate['epistemic_confidence']['adjusted_confidence']}/5")
            lines.append(f"  - friction note: {candidate['epistemic_confidence']['friction_note']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Pending Human Review"])
    if report.get("pending_human_review"):
        for item in report["pending_human_review"]:
            lines.append(f"- {item['ticker']}: {item['reason']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Rejected At Screening"])
    if report["rejected_at_screening"]:
        for item in report["rejected_at_screening"]:
            lines.append(f"- {item['ticker']}: {item['failed_at']} - {item['reason']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Rejected At Analysis"])
    if report["rejected_at_analysis_detail_packets"]:
        for item in report["rejected_at_analysis_detail_packets"]:
            lines.append(f"### {item['ticker']}")
            lines.append(f"- Reason: {item['rejection_reason']}")
            if "base_case" in item:
                lines.append(f"- Base-case CAGR: {item['base_case']['cagr_pct']}%")
            if "worst_case" in item:
                lines.append(f"- Downside: {item['worst_case']['downside_pct']}%")
            if item.get("thesis_summary"):
                lines.append(f"- Thesis: {item['thesis_summary']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Current Holding Overlays"])
    if report["current_holding_overlays"]:
        for item in report["current_holding_overlays"]:
            lines.append(
                f"- {item['ticker']}: {item['status_in_scan']} | new capital {item['new_capital_decision']} | "
                f"existing action {item['existing_position_action']} | {item['reason']}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Portfolio Impact"])
    lines.extend(_bullet_lines(report["portfolio_impact"]))

    lines.extend(["", "## Methodology Notes"])
    lines.extend(_bullet_lines(report["methodology_notes"]))

    lines.extend(["", "## Execution Summary"])
    lines.append(f"- Candidate count: {execution_log['candidate_count']}")
    lines.append(f"- Ranked count: {execution_log['survivor_count']}")
    if judge is not None:
        lines.append(f"- Judge verdict: {judge['verdict']} -> {judge['target_stage']}")

    return "\n".join(lines) + "\n"


def render_execution_log_markdown(report: dict, execution_log: dict, judge: dict | None = None) -> str:
    lines = [
        f"# Execution Log - {report['title']}",
        "",
        "## Stage Events",
    ]
    lines.extend(_bullet_lines(execution_log["entries"]))
    lines.extend(
        [
            "",
            "## Metrics",
            f"- Candidate count: {execution_log['candidate_count']}",
            f"- Ranked count: {execution_log['survivor_count']}",
        ]
    )
    if judge is not None:
        lines.extend(
            [
                "",
                "## Judge",
                f"- Verdict: {judge['verdict']}",
                f"- Target stage: {judge['target_stage']}",
                f"- Reroute reason: {judge['reroute_reason'] or 'None'}",
            ]
        )
        if judge.get("findings"):
            lines.extend(["- Findings:"])
            lines.extend([f"  - {item}" for item in judge["findings"]])

    lines.extend(
        [
            "",
            "## Report Snapshot",
            "```json",
            _pretty_json(
                {
                    "ranked_candidates": [item["ticker"] for item in report["ranked_candidates"]],
                    "pending_human_review": [item["ticker"] for item in report.get("pending_human_review", [])],
                    "rejected_at_screening": [item["ticker"] for item in report["rejected_at_screening"]],
                    "rejected_at_analysis": [item["ticker"] for item in report["rejected_at_analysis_detail_packets"]],
                }
            ),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def write_execution_log(path: Path, report: dict, execution_log: dict, judge: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(
            _pretty_json(
                {
                    "report_title": report["title"],
                    "execution_log": execution_log,
                    "judge": judge,
                }
            )
        )
        return
    path.write_text(render_execution_log_markdown(report, execution_log, judge))
