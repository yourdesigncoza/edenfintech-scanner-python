from __future__ import annotations

import json
from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def assets_root() -> Path:
    return package_root() / "assets"


def contracts_root() -> Path:
    return assets_root() / "contracts"


def fixtures_root() -> Path:
    return assets_root() / "fixtures" / "regression"


def methodology_root() -> Path:
    return assets_root() / "methodology"


def rules_root() -> Path:
    return assets_root() / "rules"


def scan_input_schema_path() -> Path:
    return methodology_root() / "scan-input.schema.json"


def gemini_raw_bundle_schema_path() -> Path:
    return methodology_root() / "gemini-raw-bundle.schema.json"


def scan_report_schema_path() -> Path:
    return methodology_root() / "scan-report.schema.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_text(path: Path) -> str:
    return path.read_text()


def contract_path(stage_id: str) -> Path:
    return contracts_root() / f"{stage_id}.json"
