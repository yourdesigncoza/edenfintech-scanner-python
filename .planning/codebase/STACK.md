# Technology Stack

**Analysis Date:** 2026-03-10

## Languages

**Primary:**
- Python 3.11+ - Core pipeline, CLI, and test suite

**Secondary:**
- JSON - Configuration, methodology assets, schemas, and all data interchange

## Runtime

**Environment:**
- CPython 3.13.5 (via miniconda3)

**Package Manager:**
- pip - Configured through `pyproject.toml` with setuptools
- Virtual Environment: `.venv/` (via venv module)

**Lockfile:**
- Missing - Only `requirements.txt` with `-e .` (editable install of the package itself)

## Frameworks

**Core:**
- None - Pure standard library implementation for the pipeline

**Testing:**
- unittest (stdlib) - All test discovery via `python -m unittest discover -s tests`

**Build/Dev:**
- setuptools - Package building via `[build-system]` in `pyproject.toml`
- argparse (stdlib) - CLI argument parsing in `src/edenfintech_scanner_bootstrap/cli.py`

## Key Dependencies

**Runtime:**
- urllib (stdlib) - HTTP transport for FMP API (`fmp.py`) and Gemini API (`gemini.py`)
- json (stdlib) - All JSON parsing and serialization
- pathlib (stdlib) - File path handling
- datetime (stdlib) - Date/timestamp operations
- hashlib (stdlib) - Hashing for fingerprints
- copy (stdlib) - Deep copying for data structures
- dataclasses (stdlib) - Configuration class definition
- os (stdlib) - Environment variable access

**No External Dependencies:**
- Zero third-party packages required for core pipeline execution
- This is intentional per CLAUDE.md: "No external dependencies beyond stdlib for core pipeline"

## Configuration

**Environment:**
- Loaded via `.env` file using custom dotenv parser in `src/edenfintech_scanner_bootstrap/config.py`
- Auto-discovery of project root via `pyproject.toml` presence and `assets/methodology/` structure
- Environment variable precedence: explicit `EDENFINTECH_SCANNER_DOTENV` → `.env` in project root → OS environment

**Build:**
- `pyproject.toml`: Package metadata, requires-python >=3.11, setuptools build backend
- `setup.py`: Not present (build is entirely PEP 517 via setuptools)
- CLI entry point: `edenfintech-bootstrap` command registered via `[project.scripts]`

**Key Configs Required:**
- `FMP_API_KEY` - Financial Modeling Prep API key (required for `fmp.py` operations)
- `GEMINI_API_KEY` - Google Gemini API key (required for `gemini.py` operations)
- `OPENAI_API_KEY` - OpenAI API key (optional; enables Codex judge, falls back to local judge if missing)
- `CODEX_JUDGE_MODEL` - OpenAI model for judge calls (default: `gpt-5-codex`)

## Platform Requirements

**Development:**
- Python 3.11+ required by `pyproject.toml`
- Tested with Python 3.13.5
- Git repository for version control

**Production:**
- No database required
- No external services required except APIs (FMP, Gemini, OpenAI - all optional/conditional)
- Outputs JSON reports and markdown summaries to local filesystem
- All computation is deterministic and stateless

## Testing Infrastructure

**Test Runner:**
- unittest (stdlib)
- Run all tests: `python -m unittest discover -s tests -v`
- Run single test file: `python -m unittest tests.test_fmp -v`
- Run single test method: `python -m unittest tests.test_fmp.TestFmpAdapter.test_quote_parsing -v`

**Test Fixtures:**
- `tests/fixtures/fmp/` - Sanitized wire-format FMP API response fixtures
- `tests/fixtures/gemini/` - Sanitized wire-format Gemini API response fixtures
- `tests/fixtures/raw/` - Pre-merged candidate bundles for pipeline tests
- `tests/fixtures/generated/` - Generated overlay test fixtures
- `assets/fixtures/regression/` - Regression snapshot fixtures for `run-regression` command

**Validation:**
- Asset validation: `python -m edenfintech_scanner_bootstrap.cli validate-assets`
- Regression suite: `python -m edenfintech_scanner_bootstrap.cli run-regression`

## Package Structure

**Package Name:**
- `edenfintech-scanner-bootstrap`

**Entry Point:**
- `src/edenfintech_scanner_bootstrap/cli.py:main()` → registered as `edenfintech-bootstrap` command

**Modules:**
- Core pipeline: `pipeline.py`, `scoring.py`, `reporting.py`
- Data retrieval: `fmp.py`, `gemini.py`
- Analysis layer: `field_generation.py`, `structured_analysis.py`
- Utilities: `config.py`, `assets.py`, `schemas.py`, `importers.py`, `judge.py`, `validation.py`, `regression.py`
- Orchestration: `live_scan.py`, `review_package.py`

---

*Stack analysis: 2026-03-10*
