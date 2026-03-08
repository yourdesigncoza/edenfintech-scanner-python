from __future__ import annotations

from dataclasses import dataclass

from .assets import fixtures_root, load_json


@dataclass
class RegressionResult:
    fixture_id: str
    passed: bool
    details: list[str]


def _derive_categories(report: dict) -> set[str]:
    categories: set[str] = set()
    if not report.get("ranked_candidates"):
        categories.add("no_survivors")
    if report.get("rejected_at_screening"):
        categories.add("screening_rejection")
    if report.get("rejected_at_analysis_detail_packets"):
        categories.add("analysis_rejection")
    if report.get("pending_human_review"):
        categories.add("pending_human_review_exception")
    for packet in report.get("rejected_at_analysis_detail_packets", []):
        reason = str(packet.get("rejection_reason", "")).lower()
        if "epistemic" in reason:
            categories.add("epistemic_rejection")
    return categories


def run_regression_suite() -> list[RegressionResult]:
    manifest = load_json(fixtures_root() / "manifest.json")
    results: list[RegressionResult] = []

    for fixture in manifest["fixtures"]:
        fixture_path = fixtures_root() / fixture["path"]
        report = load_json(fixture_path)
        details: list[str] = []
        passed = True

        categories = _derive_categories(report)
        expected_categories = set(fixture["expectations"]["required_categories"])
        missing = expected_categories - categories
        if missing:
            passed = False
            details.append(f"missing categories: {sorted(missing)}")

        ranked_expected = fixture["expectations"]["ranked_candidates_count"]
        ranked_actual = len(report.get("ranked_candidates", []))
        if ranked_actual != ranked_expected:
            passed = False
            details.append(
                f"ranked_candidates count mismatch: expected {ranked_expected}, got {ranked_actual}"
            )

        pending_expected = fixture["expectations"]["pending_human_review_count"]
        pending_actual = len(report.get("pending_human_review", []))
        if pending_actual != pending_expected:
            passed = False
            details.append(
                f"pending_human_review count mismatch: expected {pending_expected}, got {pending_actual}"
            )

        for ticker in fixture["expectations"].get("screening_rejections", []):
            if not any(item.get("ticker") == ticker for item in report.get("rejected_at_screening", [])):
                passed = False
                details.append(f"missing screening rejection ticker: {ticker}")

        for ticker in fixture["expectations"].get("analysis_rejections", []):
            if not any(
                item.get("ticker") == ticker
                for item in report.get("rejected_at_analysis_detail_packets", [])
            ):
                passed = False
                details.append(f"missing analysis rejection ticker: {ticker}")

        results.append(RegressionResult(fixture_id=fixture["id"], passed=passed, details=details))

    return results
