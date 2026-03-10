# External Integrations

**Analysis Date:** 2026-03-10

## APIs & External Services

**Financial Data (Quantitative):**
- Financial Modeling Prep (FMP)
  - What it's used for: Fetch ticker quotes, company profiles, historical prices, income statements, cash flow statements
  - SDK/Client: Custom HTTP client in `src/edenfintech_scanner_bootstrap/fmp.py`
  - Auth: `FMP_API_KEY` environment variable
  - Base URL: `https://financialmodelingprep.com/stable/`
  - Transport: Uses urllib (stdlib) with 60-second timeout
  - Endpoints accessed:
    - `quote?symbol={ticker}`
    - `profile?symbol={ticker}`
    - `historical-price-eod/full?symbol={ticker}`
    - `income-statement?symbol={ticker}&period=annual&limit=5`
    - `cash-flow-statement?symbol={ticker}&period=annual&limit=5`

**Qualitative Evidence (Research):**
- Google Gemini
  - What it's used for: Collect sourced research evidence (catalysts, risks, moat, management observations)
  - SDK/Client: Custom HTTP client in `src/edenfintech_scanner_bootstrap/gemini.py`
  - Auth: `GEMINI_API_KEY` environment variable (x-goog-api-key header)
  - Base URL: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
  - Model: `gemini-3-pro-preview` (configurable via code default)
  - Transport: Uses urllib (stdlib) with 90-second timeout
  - Request format: JSON with contents, tools (googleSearch, urlContext), and generationConfig
  - Response format: Structured JSON with evidence arrays (research_notes, catalyst_evidence, risk_evidence, management_observations, moat_observations, precedent_observations, epistemic_anchors)
  - Features used: JSON schema validation on response, tool-enabled web search and URL context

**AI Judge (Deterministic Review):**
- OpenAI Responses API
  - What it's used for: Optional Codex judge review of assembled reports for methodology compliance
  - SDK/Client: Custom HTTP client in `src/edenfintech_scanner_bootstrap/judge.py:openai_judge_transport()`
  - Auth: `OPENAI_API_KEY` environment variable (Bearer token in Authorization header)
  - Base URL: `https://api.openai.com/v1/responses`
  - Model: Configurable via `CODEX_JUDGE_MODEL` environment variable (default: `gpt-5-codex`)
  - Transport: Uses urllib (stdlib) with 60-second timeout
  - Request format: JSON with model, input (judge prompt), and text.format (JSON schema specification)
  - Response format: Structured JSON with verdict, target_stage, findings (array), reroute_reason
  - Fallback: Automatic fallback to `local_judge()` deterministic logic if API unavailable, missing key, or error

## Data Storage

**Databases:**
- None - All state is ephemeral and file-based

**File Storage:**
- Local filesystem only
- Output structure:
  - `runs/{package-name}/raw/` - Raw FMP and Gemini bundles (JSON)
  - `runs/{package-name}/review/` - Structured analysis draft and review checklist (JSON + markdown)
  - `runs/{package-name}/final/` - Finalized scan report and execution log (JSON + markdown)
- Manifest file: `review-package-manifest.json` in output directory

**Caching:**
- None - All data is refetched or loaded from file on each invocation
- Raw bundle fingerprints are tracked through pipeline for traceability but not cached

## Authentication & Identity

**Auth Provider:**
- None (service-to-service API key authentication only)

**Implementation:**
- FMP: API key appended to query parameters
- Gemini: API key in `x-goog-api-key` request header
- OpenAI: Bearer token in `Authorization: Bearer {key}` header
- All keys stored as environment variables, loaded via `.env` file

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service

**Logs:**
- Execution logs: `src/edenfintech_scanner_bootstrap/reporting.py` writes to markdown and JSON files
- Structured execution log: JSON format with phase/stage details
- Log output: `runs/{package-name}/final/execution-log.md` and `execution-log.json`
- Console logging: Direct print statements via CLI

## CI/CD & Deployment

**Hosting:**
- GitHub Actions (inferred from README)
- Codebase: Deployed as importable Python package via setuptools

**CI Pipeline:**
- Runs: `python -m unittest discover -s tests`
- Runs: `python -m edenfintech_scanner_bootstrap.cli validate-assets`
- Runs: `python -m edenfintech_scanner_bootstrap.cli run-regression`
- All three on every push/PR

## Environment Configuration

**Required env vars:**
- `FMP_API_KEY` - Financial Modeling Prep (only required if running `fmp.py` operations)
- `GEMINI_API_KEY` - Google Gemini (only required if running `gemini.py` operations)

**Optional env vars:**
- `OPENAI_API_KEY` - OpenAI (optional; judge falls back to deterministic local judge if missing)
- `CODEX_JUDGE_MODEL` - Judge model name (default: `gpt-5-codex`)
- `EDENFINTECH_SCANNER_DOTENV` - Explicit path to `.env` file (auto-discovery if not set)

**Secrets location:**
- `.env` file (not committed; see `.env.example` for template)
- Environment variables loaded by `src/edenfintech_scanner_bootstrap/config.py:load_config()`

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None - All operations are request-response only

## API Response Handling

**FMP API:**
- Error handling: Raises `RuntimeError` if HTTP error, network error, or `Error Message` field in response
- Response validation: Checks for expected list/dict structure, validates key fields present
- Implemented in: `src/edenfintech_scanner_bootstrap/fmp.py:_default_transport()` and `FmpClient._get()`

**Gemini API:**
- Error handling: Raises `RuntimeError` on `URLError` or HTTP error
- Response validation: Extracts text from candidates array, validates JSON structure in response
- Schema validation: Validates full bundle against `assets/methodology/gemini-raw-bundle.schema.json`
- Implemented in: `src/edenfintech_scanner_bootstrap/gemini.py:_default_transport()` and response handling

**OpenAI Judge API:**
- Error handling: Catches `HTTPError` and `URLError`, falls back to local deterministic judge
- Response validation: Extracts text from output array, parses JSON, validates against judge contract schema
- Fallback: `_safe_fallback_judge()` returns deterministic result with reroute_reason if API unavailable
- Implemented in: `src/edenfintech_scanner_bootstrap/judge.py:openai_judge_transport()` and `codex_judge()`

## Bundle Lifecycle

**Raw Bundle Fingerprints:**
- FMP bundle: Generated automatically with scan metadata (scan_date, version, api)
- Gemini bundle: Generated automatically with scan metadata
- Merged bundle: Combines FMP + Gemini with merged candidates
- Fingerprints preserved through pipeline for traceability and audit
- Re-running with finalized overlay reuses raw bundles (not refetched) to maintain fingerprint continuity

---

*Integration audit: 2026-03-10*
