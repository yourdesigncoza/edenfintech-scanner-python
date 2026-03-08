from __future__ import annotations

from dataclasses import dataclass

from .assets import contract_path, contracts_root, fixtures_root, load_json, methodology_root, rules_root


EXPECTED_CONTRACTS = {
    "screening",
    "cluster_analysis",
    "epistemic_review",
    "report_assembly",
    "codex_final_judge",
}

EXPECTED_METHOD_FILES = {
    "strategy-rules.md",
    "scoring-formulas.md",
    "scan-report.schema.json",
    "scan-report.template.json",
}

EXPECTED_RULE_IDS = {
    "broken_chart_min_60pct",
    "industry_understandable_required",
    "no_secular_decline",
    "double_plus_potential_required",
    "solvency_fail_rule",
    "dilution_fail_rule",
    "revenue_growth_fail_rule",
    "roic_fail_rule",
    "valuation_hurdle_fail_rule",
    "permanent_pass_margin_decline",
    "weaker_company_retention_guard",
    "valid_catalyst_required",
    "probability_band_normalization",
    "pcs_five_questions_required",
    "pcs_multiplier_and_friction",
    "exception_candidate_human_gate",
    "risk_enrichment_demotion",
    "json_first_report_assembly",
    "codex_cannot_override_methodology",
    "codex_reroute_to_prior_stage_only",
}


@dataclass
class ValidationReport:
    ok: bool
    messages: list[str]


def validate_assets() -> ValidationReport:
    messages: list[str] = []
    ok = True

    method_files = {path.name for path in methodology_root().iterdir()}
    missing_method = EXPECTED_METHOD_FILES - method_files
    if missing_method:
        ok = False
        messages.append(f"missing methodology files: {sorted(missing_method)}")

    contract_files = {path.stem for path in contracts_root().glob("*.json")}
    missing_contracts = EXPECTED_CONTRACTS - contract_files
    if missing_contracts:
        ok = False
        messages.append(f"missing contract files: {sorted(missing_contracts)}")

    rulebook = load_json(rules_root() / "canonical-rulebook.json")
    rule_ids = {rule["id"] for rule in rulebook["rules"]}
    missing_rules = EXPECTED_RULE_IDS - rule_ids
    if missing_rules:
        ok = False
        messages.append(f"missing canonical rules: {sorted(missing_rules)}")

    for stage_id in EXPECTED_CONTRACTS:
        contract = load_json(contract_path(stage_id))
        for key in ["stage_id", "title", "summary", "source_rule_ids", "hard_checks", "failure_codes"]:
            if key not in contract:
                ok = False
                messages.append(f"{stage_id}: missing key {key}")
        for rule_id in contract.get("source_rule_ids", []):
            if rule_id not in rule_ids:
                ok = False
                messages.append(f"{stage_id}: references unknown rule {rule_id}")

    manifest = load_json(fixtures_root() / "manifest.json")
    for fixture in manifest["fixtures"]:
        fixture_path = fixtures_root() / fixture["path"]
        if not fixture_path.exists():
            ok = False
            messages.append(f"missing regression fixture: {fixture['path']}")

    if ok:
        messages.append("all methodology assets, stage contracts, and fixtures validated")

    return ValidationReport(ok=ok, messages=messages)
