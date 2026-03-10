# Codebase Structure

**Analysis Date:** 2026-03-10

## Directory Layout

```
edenfintech-scanner-python/
├── src/edenfintech_scanner_bootstrap/    # Main package
│   ├── __init__.py                       # Package marker
│   ├── cli.py                            # CLI entry point & command routing
│   ├── config.py                         # Configuration & API credentials
│   ├── assets.py                         # Asset/path helpers
│   ├── schemas.py                        # JSON Schema validation
│   ├── validation.py                     # Asset integrity checks
│   ├── fmp.py                            # FMP API client & bundle builder
│   ├── gemini.py                         # Gemini API client & bundle builder
│   ├── field_generation.py               # Machine-draft overlay generation
│   ├── structured_analysis.py            # Overlay lifecycle (template/draft/finalize)
│   ├── importers.py                      # Raw→scan-input transformation
│   ├── pipeline.py                       # Core deterministic pipeline (5 stages)
│   ├── scoring.py                        # Financial formulas & epistemic math
│   ├── reporting.py                      # Markdown rendering & execution logs
│   ├── live_scan.py                      # Scan orchestration workflow
│   ├── review_package.py                 # Review-focused orchestration
│   ├── judge.py                          # OpenAI judge & deterministic fallback
│   └── regression.py                     # Fixture-based regression testing
├── assets/                               # Methodology & contracts
│   ├── contracts/                        # Stage contracts (JSON Schema + docs)
│   │   ├── screening.json
│   │   ├── cluster_analysis.json
│   │   ├── epistemic_review.json
│   │   ├── report_assembly.json
│   │   └── codex_final_judge.json
│   ├── methodology/                      # Methodology specs & schemas
│   │   ├── strategy-rules.md             # Source of truth for business rules
│   │   ├── scoring-formulas.md           # Decision score & CAGR formulas
│   │   ├── scan-input.schema.json        # Scan payload contract
│   │   ├── scan-report.schema.json       # Report output contract
│   │   ├── structured-analysis.schema.json
│   │   ├── gemini-raw-bundle.schema.json
│   │   └── scan-report.template.json     # Report template (filled at runtime)
│   ├── rules/                            # Executable rules
│   │   └── canonical-rulebook.json
│   └── fixtures/regression/              # Regression test snapshots
│       ├── manifest.json
│       └── *.json (snapshot reports)
├── tests/                                # Unit & integration tests
│   ├── test_fmp.py                       # FMP adapter tests
│   ├── test_gemini.py                    # Gemini adapter tests
│   ├── test_field_generation.py          # Draft generation tests
│   ├── test_structured_analysis.py       # Overlay lifecycle tests
│   ├── test_importers.py                 # Scan input generation tests
│   ├── test_scan_pipeline.py             # Pipeline stage tests
│   ├── test_live_scan.py                 # Orchestration tests
│   ├── test_review_package.py            # Review workflow tests
│   ├── test_judge.py                     # Judge logic tests
│   ├── test_bootstrap_assets.py          # Asset validation tests
│   ├── fixtures/fmp/                     # FMP response fixtures
│   │   └── *.json (sanitized API responses)
│   ├── fixtures/gemini/                  # Gemini response fixtures
│   │   └── *.json (sanitized API responses)
│   └── fixtures/raw/                     # Merged bundle fixtures
│       └── *.json (for pipeline testing)
├── runs/                                 # Output directory (generated)
│   └── [TICKER-DATE]/                    # Package outputs (raw/, review/, final/)
├── kylers-system-codex/                  # External system documentation
├── docs/                                 # Generated documentation
├── .planning/                            # GSD planning artifacts
│   ├── codebase/                         # (This location)
│   │   ├── ARCHITECTURE.md
│   │   ├── STRUCTURE.md
│   │   ├── STACK.md
│   │   ├── INTEGRATIONS.md
│   │   ├── CONVENTIONS.md
│   │   └── TESTING.md
├── .github/                              # GitHub Actions
│   └── workflows/                        # CI/CD pipelines
├── pyproject.toml                        # Package metadata
├── requirements.txt                      # Runtime dependencies
├── .env.example                          # Environment variable template
├── CLAUDE.md                             # Developer instructions
├── README.md                             # Project overview
├── AGENTS.md                             # Agent guidelines
└── .gitignore                            # Git exclusions
```

## Directory Purposes

**`src/edenfintech_scanner_bootstrap/`:**
- Purpose: Main Python package; all production code lives here
- Contains: 19 modules (~5000 lines) covering data retrieval, analysis, pipeline, and orchestration
- Key files: `cli.py` (entry), `pipeline.py` (core logic), `live_scan.py` + `review_package.py` (orchestration)

**`assets/contracts/`:**
- Purpose: Define input/output shapes for each pipeline stage
- Contains: JSON Schema documents with stage identifiers (screening, cluster_analysis, epistemic_review, report_assembly, codex_final_judge)
- Not committed to package; validated separately via `validate-assets`

**`assets/methodology/`:**
- Purpose: Methodology specifications; authoritative business rules
- Contains: `strategy-rules.md` (screening checks, epistemic thresholds), scoring formulas, JSON schemas for data structures
- **Usage**: `strategy-rules.md` is source of truth; code must conform to it

**`assets/rules/`:**
- Purpose: Machine-readable rules extracted from methodology
- Contains: `canonical-rulebook.json` with decision trees
- **Usage**: Currently minimal; may expand for rule-based systems

**`assets/fixtures/regression/`:**
- Purpose: Golden test snapshots for regression detection
- Contains: Representative scan reports from past runs
- **Usage**: `run-regression` compares current output against these fixtures

**`tests/`:**
- Purpose: Unit, integration, and fixture-based testing
- Contains: 10 test modules; fixtures organized by API (fmp/, gemini/, raw/)
- Key pattern: Fixture-based testing avoids real API calls; transport callables allow injection

**`runs/`:**
- Purpose: Output staging area (not committed)
- Contains: Generated packages (TICKER-DATE directories)
- Structure per package: `raw/` (data + drafts), `review/` (checklists), `final/` (reports)

## Key File Locations

**Entry Points:**
- CLI: `src/edenfintech_scanner_bootstrap/cli.py:main()` — routes commands to handlers
- Workflow: `src/edenfintech_scanner_bootstrap/review_package.py:build_review_package()` — main operator workflow
- Pipeline: `src/edenfintech_scanner_bootstrap/pipeline.py:run_scan()` — core deterministic engine

**Configuration:**
- Env loading: `src/edenfintech_scanner_bootstrap/config.py:load_config()` — reads .env, validates keys
- Secrets: `.env` (not committed; copy from `.env.example`)
- Paths: `src/edenfintech_scanner_bootstrap/assets.py` — helpers for methodology files

**Core Logic:**
- Scoring: `src/edenfintech_scanner_bootstrap/scoring.py` — CAGR, target price, decision score formulas
- Pipeline stages: `src/edenfintech_scanner_bootstrap/pipeline.py:_screen_candidate()`, epistemic logic (lines 150–650+)
- Structured analysis: `src/edenfintech_scanner_bootstrap/structured_analysis.py` — overlay lifecycle, finalization

**Data Retrieval:**
- FMP: `src/edenfintech_scanner_bootstrap/fmp.py:FmpClient`, `build_fmp_bundle_with_config()`
- Gemini: `src/edenfintech_scanner_bootstrap/gemini.py:GeminiClient`, `build_gemini_bundle_with_config()`
- Merging: `src/edenfintech_scanner_bootstrap/gemini.py:merge_fmp_and_gemini_bundles()`

**Testing:**
- Fixture registry: `tests/fixtures/` (fmp/, gemini/, raw/)
- Regression snapshots: `assets/fixtures/regression/manifest.json`
- Test discovery: `python -m unittest discover -s tests -v`

## Naming Conventions

**Files:**
- Modules: `snake_case.py` (e.g., `field_generation.py`, `live_scan.py`)
- Tests: `test_<module>.py` (e.g., `test_pipeline.py`, `test_fmp.py`)
- Assets: `kebab-case.json` or `kebab-case.md` (e.g., `scan-input.schema.json`, `strategy-rules.md`)
- Fixtures: `kebab-case.json` (e.g., `fmp-raw.json`, `merged-raw.json`)
- Output bundles: `kebab-case.json` written to `raw/`, `final/` dirs

**Directories:**
- Package: `snake_case_with_underscores/` (e.g., `edenfintech_scanner_bootstrap/`)
- Stages/workflows: kebab names (e.g., `raw-bundle`, `scan-input`, `report`)
- Function names: `snake_case()`
- Class names: `PascalCase` (e.g., `FmpClient`, `GeminiClient`, `SchemaValidationError`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `CHECK_ORDER`, `VALID_VERDICTS`)

**Variable naming in data structures:**
- Field paths: `snake_case` (e.g., `pct_off_ath`, `revenue_b`, `fcf_margin_pct`)
- Dicts/objects: `snake_case_keys` (e.g., `base_case`, `worst_case`, `probability`)
- Lists: plural or context-clear (e.g., `candidates`, `ranked_candidates`, `rejected_screening`)

## Where to Add New Code

**New Feature (e.g., new screening check):**
- Primary code: `src/edenfintech_scanner_bootstrap/pipeline.py` (add to `_screen_candidate()`)
- Scoring component: `src/edenfintech_scanner_bootstrap/scoring.py` (if new financial formula)
- Tests: `tests/test_scan_pipeline.py` (new test case for check)
- Methodology: Update `assets/methodology/strategy-rules.md` and `canonical-rulebook.json`
- Contract: Update `assets/contracts/screening.json` if input/output shape changes

**New Data Field (e.g., new Gemini research type):**
- Schema: `assets/methodology/gemini-raw-bundle.schema.json`
- Generator: `src/edenfintech_scanner_bootstrap/field_generation.py` (add provenance extraction)
- Importer: `src/edenfintech_scanner_bootstrap/importers.py` (map field to scan input)
- Tests: `tests/test_field_generation.py` and `tests/test_importers.py`

**New API Integration (e.g., new data source):**
- Adapter module: `src/edenfintech_scanner_bootstrap/new_source.py` (client class + build function)
- Transport callable: Follow FMP/Gemini pattern with configurable transport
- Merge logic: `src/edenfintech_scanner_bootstrap/gemini.py:merge_fmp_and_gemini_bundles()` (extend for new source)
- Tests: `tests/test_new_source.py` with fixture-based testing

**New Output Format:**
- Renderer: `src/edenfintech_scanner_bootstrap/reporting.py` (add render function)
- Writer: CLI command in `src/edenfintech_scanner_bootstrap/cli.py` (new subcommand)
- Contract: `assets/contracts/report_assembly.json` if schema changes

**Shared Helpers:**
- Pure functions: `src/edenfintech_scanner_bootstrap/scoring.py` (if financial math)
- Validation: `src/edenfintech_scanner_bootstrap/schemas.py` (if validation logic)
- Constants: `src/edenfintech_scanner_bootstrap/pipeline.py` at module level (CHECK_ORDER, VALID_VERDICTS, etc.)

## Special Directories

**`assets/` (Methodology):**
- Purpose: Source of truth for business rules
- Generated: No; hand-authored and version-controlled
- Committed: Yes; critical for reproducibility

**`tests/fixtures/`:**
- Purpose: Sanitized API responses and test data
- Generated: No; manually created from real API responses with PII removed
- Committed: Yes; enables offline testing

**`runs/` (Output packages):**
- Purpose: Staging area for generated reports
- Generated: Yes; created by `build-review-package` and `run-live-scan`
- Committed: No; in `.gitignore`

**`kylers-system-codex/`:**
- Purpose: External system context (for Claude agents)
- Generated: No; hand-authored reference material
- Committed: Yes

**`.planning/codebase/`:**
- Purpose: GSD planning artifacts (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated: Yes; written by `/gsd:map-codebase`
- Committed: Yes

---

*Structure analysis: 2026-03-10*
