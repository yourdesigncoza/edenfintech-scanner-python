# Testing Patterns

**Analysis Date:** 2026-03-10

## Test Framework

**Runner:**
- `unittest` (standard library)
- Config: `tests/` directory structure
- No pytest or other test runner configured

**Assertion Library:**
- `unittest.TestCase` with standard assertions: `assertEqual()`, `assertRaisesRegex()`, `assertIn()`

**Run Commands:**
```bash
python -m unittest discover -s tests -v              # Run all tests
python -m unittest tests.test_fmp -v                 # Run single test file
python -m unittest tests.test_fmp.TestFmpAdapter.test_quote_parsing -v  # Run single test method
```

## Test File Organization

**Location:**
- Co-located in `tests/` directory parallel to `src/`
- Test file naming: `test_*.py` (e.g., `test_fmp.py`, `test_pipeline.py`)
- Test directory structure mirrors source structure

**Naming:**
- Test files: `test_<module>.py`
- Test classes: `<Module>Test` or `<Concept>Test` (e.g., `FmpTest`, `ScanPipelineTest`, `JudgeTest`, `ConfigTest`)
- Test methods: `test_<scenario>()` (e.g., `test_client_parses_official_shape_fmp_payloads()`, `test_local_judge_returns_contract_shape_only()`)

**Structure:**
```
tests/
├── fixtures/
│   ├── fmp/               # FMP API response fixtures
│   │   ├── official_profile_raw1.json
│   │   ├── official_quote_raw1.json
│   │   └── ...
│   ├── gemini/            # Gemini API response fixtures
│   ├── raw/               # Merged raw bundle fixtures
│   │   ├── merged_candidate_bundle.json
│   │   └── ranked_candidate_bundle.json
│   └── generated/         # Generated overlay/draft fixtures
│       └── merged_candidate_draft_overlay.json
├── test_fmp.py
├── test_gemini.py
├── test_scan_pipeline.py
├── test_judge.py
├── test_importers.py
├── test_field_generation.py
├── test_structured_analysis.py
├── test_bootstrap_assets.py
├── test_review_package.py
├── test_live_scan.py
└── test_review_helper.py
```

## Test Structure

**Suite Organization:**
```python
class FmpTest(unittest.TestCase):
    def test_client_parses_official_shape_fmp_payloads(self) -> None:
        # Arrange
        client = FmpClient(
            "fmp-test-key",
            transport=_fixture_transport({...})
        )

        # Act
        candidate = build_raw_candidate_from_fmp("RAW1", client)

        # Assert
        self.assertEqual(candidate["industry"], "Industrial Components")
```

**Patterns:**
- Arrange-Act-Assert (AAA) pattern implicit in structure
- No setUp/tearDown methods observed; fixtures loaded per-test
- Test methods use type hints: `def test_name(self) -> None:`
- Fixture loading via helper functions: `_load_fixture()`, `_fixture_transport()`

## Mocking

**Framework:**
- `unittest.mock` (standard library) for transport mocking
- No external mock library; uses dependency injection for test doubles

**Patterns:**
```python
# Transport function mocking
def _fixture_transport(mapping: dict[str, str]):
    def transport(endpoint: str, params: dict[str, str]):
        if endpoint not in mapping:
            raise AssertionError(f"unexpected endpoint: {endpoint}")
        return _load_fixture(mapping[endpoint])
    return transport

# Usage in test
client = FmpClient("test-key", transport=_fixture_transport({...}))

# Config mocking via direct instantiation
config = AppConfig(
    fmp_api_key=None,
    gemini_api_key="gemini-test-key",
    openai_api_key=None,
    codex_judge_model="gpt-5-codex"
)

# Environment variable patching
with patch.dict(os.environ, {}, clear=True):
    config = load_config(dotenv_path)
```

**What to Mock:**
- External HTTP transports (FMP, Gemini, OpenAI): provide fixture-based `transport` callback
- Configuration: instantiate `AppConfig` with test values directly
- Environment: use `patch.dict(os.environ, ...)` for env var testing

**What NOT to Mock:**
- Internal functions (pipeline, scoring, validation) - test integration
- JSON schema validation - runs real validator
- File I/O with fixtures - uses actual fixture files, not mocks
- Date/time - not mocked; uses literal test dates

## Fixtures and Factories

**Test Data:**
```python
# Fixture loading helper
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "fmp"

def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

# Config factory
def _no_judge_config() -> AppConfig:
    return AppConfig(
        fmp_api_key=None,
        gemini_api_key=None,
        openai_api_key=None,
        codex_judge_model="gpt-5-codex",
    )

# Payload builder
def _base_payload() -> dict:
    return {
        "title": "Pipeline Test Scan",
        "scan_date": "2026-03-08",
        "version": "v1",
        "scan_parameters": {...},
        "portfolio_context": {...},
        "methodology_notes": [...],
        "candidates": [],
    }
```

**Location:**
- Test fixtures in `tests/fixtures/` organized by category
- Fixture files are JSON; wire-format responses from APIs
- Both official API shape variants and normalized variants tested
- Generated overlays stored in `tests/fixtures/generated/`
- Regression fixtures in `assets/fixtures/regression/`

## Coverage

**Requirements:** Not explicitly enforced; regression tests provide coverage

**View Coverage:**
No coverage tool configured. Coverage measured implicitly via:
- Unit tests: adapter layer (FMP, Gemini)
- Integration tests: pipeline (screening, cluster, epistemic, report stages)
- Regression tests: comparison against golden fixtures in `assets/fixtures/regression/`

## Test Types

**Unit Tests:**
- **Adapters:** `test_fmp.py`, `test_gemini.py` - API parsing and bundle building
- **Config:** `test_importers.py` - dotenv discovery, config loading
- **Schema:** `test_bootstrap_assets.py` - asset validation, contract loading
- Scope: Single module or small group of related functions
- Dependencies mocked via transport functions or direct instantiation

**Integration Tests:**
- **Pipeline:** `test_scan_pipeline.py` - full screening → ranking → epistemic → report flow
- **Field generation:** `test_field_generation.py` - raw bundle → draft overlay generation
- **Judge:** `test_judge.py` - report generation → judge verdict → validation
- **Importers:** `test_importers.py` - raw bundle → scan input → run scan e2e
- Scope: Multiple stages or complex workflows
- Real JSON validation, schema checking, contract enforcement

**E2E/Regression Tests:**
- **Location:** `tests/regression.py` and `assets/fixtures/regression/`
- **Approach:** Compare generated reports against golden fixture snapshots
- **Run via:** `python -m edenfintech_scanner_bootstrap.cli run-regression`
- Ensures output structure and calculations match across releases

## Common Patterns

**Async Testing:**
Not applicable; no async code in codebase.

**Error Testing:**
```python
def test_client_requires_fmp_key(self) -> None:
    with self.assertRaisesRegex(ValueError, "missing required configuration: fmp_api_key"):
        build_fmp_bundle_with_config(
            ["RAW1"],
            config=AppConfig(
                fmp_api_key=None,
                gemini_api_key=None,
                openai_api_key=None,
                codex_judge_model="gpt-5-codex",
            ),
            transport=_fixture_transport({...}),
        )

def test_validate_judge_result_rejects_contradictory_fields(self) -> None:
    with self.assertRaisesRegex(ValueError, "APPROVE verdict must target approve"):
        validate_judge_result({
            "verdict": "APPROVE",
            "target_stage": "report_assembly",
            "findings": [],
            "reroute_reason": "",
        })
```

**Fixture-Based Testing:**
```python
def test_generated_draft_matches_golden_fixture(self) -> None:
    raw_bundle = load_json(FIXTURES_ROOT / "raw" / "merged_candidate_bundle.json")
    expected = load_json(FIXTURES_ROOT / "generated" / "merged_candidate_draft_overlay.json")

    generated = generate_structured_analysis_draft(raw_bundle)

    self.assertEqual(generated, expected)
```

**Transport Injection:**
```python
def test_builds_retrieval_only_bundle(self) -> None:
    seen_requests: list[dict] = []

    def transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        seen_requests.append({"url": url, "headers": headers, "payload": payload})
        return _load_fixture("generate_content_rest_raw1.json")

    bundle = build_gemini_bundle_with_config(
        ["RAW1"],
        config=AppConfig(...),
        transport=transport,
        focus="fintech vertical software",
        research_question="Collect source-backed catalysts and risks.",
    )

    self.assertEqual(bundle["scan_parameters"]["api"], "Gemini")
    self.assertIn("googleSearch", seen_requests[0]["payload"]["tools"][0])
```

## Test Execution

**CI Configuration:**
- Tests run on every push/PR via GitHub Actions
- Commands in order: unit tests → asset validation → regression
- Failure on any stage blocks merge

**Local Test Commands:**
```bash
# All tests with verbose output
python -m unittest discover -s tests -v

# Single test file
python -m unittest tests.test_fmp -v

# Single test method
python -m unittest tests.test_fmp.FmpTest.test_client_parses_official_shape_fmp_payloads -v

# Asset validation (schemas, contracts, rules)
python -m edenfintech_scanner_bootstrap.cli validate-assets

# Regression suite
python -m edenfintech_scanner_bootstrap.cli run-regression
```

---

*Testing analysis: 2026-03-10*
