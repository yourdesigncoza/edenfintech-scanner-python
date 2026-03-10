# Coding Conventions

**Analysis Date:** 2026-03-10

## Naming Patterns

**Files:**
- Lowercase with underscores: `fmp.py`, `field_generation.py`, `structured_analysis.py`
- Test files prefix with `test_`: `test_fmp.py`, `test_scan_pipeline.py`
- Constants use UPPERCASE: `CHECK_ORDER`, `VALID_VERDICTS`, `MACHINE_STATUS`, `PLACEHOLDER_TEXT`
- Private helpers prefix with underscore: `_require_dict()`, `_round2()`, `_matches_type()`

**Functions:**
- Lowercase with underscores (snake_case): `validate_scan_input()`, `run_scan()`, `build_fmp_bundle_with_config()`
- Public functions have no leading underscore
- Private/helper functions use single leading underscore: `_require_keys()`, `_statement_sort_key()`, `_default_transport()`
- Test methods use `test_` prefix: `test_client_parses_official_shape_fmp_payloads()`, `test_local_judge_returns_contract_shape_only()`

**Variables:**
- Lowercase with underscores: `raw_bundle`, `raw_candidates`, `field_provenance`, `execution_log`
- Type hints always present in function signatures
- Dictionary lookups use `.get()` with defaults to avoid KeyError

**Types:**
- PascalCase for dataclasses: `AppConfig`, `ScanArtifacts`, `ScoreBreakdown`, `EpistemicOutcome`
- Custom callable types defined as type aliases: `FmpTransport = Callable[[str, dict[str, str]], list[dict] | dict]`
- All classes use `frozen=True` for immutable dataclasses: `@dataclass(frozen=True)`

## Code Style

**Formatting:**
- No explicit linter/formatter configuration in repo
- Standard Python conventions: 4-space indentation
- Type hints throughout: `def run_scan(payload: dict, judge_config: AppConfig) -> ScanArtifacts:`
- Union types use pipe operator: `str | None`, `list[dict] | dict`
- Future annotations imported: `from __future__ import annotations` in all modules

**Import Organization:**
- Standard library first: `import json`, `from pathlib import Path`
- `__future__` annotations at top: `from __future__ import annotations`
- Relative imports for local modules: `from .config import load_config`, `from .assets import load_json`
- Type imports grouped with functional imports (no separate TYPE_CHECKING blocks observed)

**Linting:**
- Python 3.11+ required (`requires-python = ">=3.11"`)
- Type hints mandatory in all function signatures
- No magic strings—constants extracted to module level
- No TODOs or FIXMEs in codebase

## Error Handling

**Patterns:**
- Explicit type validation with descriptive errors: `raise ValueError(f"{label} must be a non-empty string")`
- Helper validators repeat across modules for clarity: `_require_dict()`, `_require_list()`, `_require_str()`, `_require_number()`, `_require_bool()`
- Chained exceptions with `from exc` to preserve stack: `raise RuntimeError(...) from exc`
- Custom exception classes for domain-specific errors: `SchemaValidationError` extends `ValueError`
- Contract validation via dedicated functions: `validate_judge_result()`, `validate_instance()`, `validate_scan_input()`

**Error Messages:**
- Include path context in validation errors: `f"{path}: expected type {expected}"`
- Endpoint/operation context included: `f"FMP request failed for {endpoint}: HTTP {exc.code}; {body_preview}"`
- Field-by-field context in complex validation: `f"{candidate['ticker']}.screening.checks.{check_name}"`

## Logging

**Framework:** `print()` only—no logging framework observed

**Patterns:**
- Minimal console output; JSON/markdown written to files instead
- Pipeline execution logged via `execution_log` dict written to JSON
- No debug or info logging; errors are raised as exceptions

## Comments

**When to Comment:**
- Minimal comments; code is self-documenting via naming and type hints
- Rationale comments for non-obvious logic (e.g., `return (1, raw_date)` for sort key logic)
- Field generation uses template strings as comments: docstrings embedded in JSON generation (`"rationale"` field in provenance)

**Docstring/TSDoc:**
- No docstrings observed (minimal comment convention)
- JSON field generation includes rationale and evidence refs instead of docstrings: `_field_provenance()` creates structured metadata

## Function Design

**Size:**
- Small, focused functions: 10-50 lines typical
- Complex business logic extracted to named functions with clear purpose
- Helper functions use leading underscore to signal private scope

**Parameters:**
- Type hints mandatory: `def run_scan(payload: dict, judge_config: AppConfig) -> ScanArtifacts:`
- Dict and list types explicitly typed: `dict[str, str]`, `list[dict]`
- Optional parameters use `| None`: `str | None`, `AppConfig | None`
- Transport/callback functions use type aliases: `FmpTransport`, `JudgeTransport`

**Return Values:**
- Explicit return types in all functions: `-> dict`, `-> list[str]`, `-> ScanArtifacts`
- Dataclasses for structured returns: `@dataclass(frozen=True)` for immutable results
- Tuples for multiple returns: `tuple[int, str]`, `tuple[str, str] | None`

## Module Design

**Exports:**
- Public functions/classes have no leading underscore
- Imports within package use relative imports: `from .config import load_config`
- Module-level constants for shared configuration: `CHECK_ORDER`, `VALID_VERDICTS`, `PCS_MULTIPLIERS`

**Barrel Files:**
- Single-responsibility modules; no barrel file pattern observed
- Each module imports what it needs directly: `from .assets import load_json`, `from .config import AppConfig`

## Data Handling

**JSON as Source of Truth:**
- JSON schemas define contract structure in `assets/methodology/`
- Schema validation via `validate_instance()` enforces correctness
- Serialization uses `json.dumps(value, indent=2, sort_keys=True)` for consistency
- Fingerprints computed via SHA256 of sorted JSON: `hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8"))`

**Path Handling:**
- `pathlib.Path` used exclusively: `Path(__file__).resolve().parent`
- Path discovery via `discover_project_root()` and `discover_dotenv_path()` for flexibility
- Never raw strings for paths

---

*Convention analysis: 2026-03-10*
