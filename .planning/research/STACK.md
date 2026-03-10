# Technology Stack

**Project:** EdenFintech Scanner — LLM Agent Integration
**Researched:** 2026-03-10

## Current Baseline

The existing codebase is stdlib-only Python 3.11+ with zero third-party runtime dependencies. HTTP calls use `urllib.request`, JSON handling is stdlib `json`, and there are no ORM, framework, or SDK dependencies. This is deliberate -- the deterministic pipeline should remain dependency-light.

The new milestone introduces three SDK dependencies (Anthropic, Google GenAI, Pydantic) and one utility dependency (requests). This is the minimum viable set. No frameworks.

---

## Recommended Stack

### LLM SDKs

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `anthropic` | `>=0.84.0` | Claude agent calls (analyst, epistemic reviewer, validator) | Official Python SDK. GA structured outputs via `client.messages.parse()` with Pydantic models. No wrapper libraries needed. Supports Claude Sonnet 4.5/4.6 and Opus 4.5/4.6. | HIGH |
| `google-genai` | `>=1.66.0` | Gemini grounded search for sector knowledge and epistemic precedent verification | The **new** unified Google GenAI SDK. Replaces the deprecated `google-generativeai` (EOL Nov 2025). Native grounded search via `types.Tool(google_search=types.GoogleSearch())`. Requires Python >=3.10 which aligns with the project's 3.11+ constraint. | HIGH |
| `pydantic` | `>=2.12.0` | Structured output schemas for all Claude agent responses | Required by `anthropic` SDK's `.parse()` method. Also enforces agent response contracts at the Python type level, complementing the existing JSON Schema validation. Use Pydantic models as the canonical definition for agent output shapes, generate JSON Schema from them where needed. | HIGH |

### HTTP / Networking

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `requests` | `>=2.31.0` | FMP API calls (replacing raw `urllib`) | The integration plan's constraint doc specifies `requests` for FMP HTTP. The caching layer (Step 1) benefits from `requests.Session` for connection pooling across batch scans. Keep `urllib` for Gemini/OpenAI calls that go through SDK-managed transports. | MEDIUM |

**Alternative considered:** Keep `urllib` for everything. Rejected because the FMP caching layer needs clean response handling (status codes, retries, timeouts) and `requests` is the practical standard. The Gemini and OpenAI paths already use SDK-managed HTTP -- only FMP needs raw HTTP.

**What NOT to use:** `httpx`. While it's async-capable and the `anthropic` SDK vendors it internally, adding it as a direct dependency introduces confusion about sync vs async patterns. The pipeline is fundamentally synchronous (serial sector hydration, sequential agent chain). Use `requests` for FMP, let SDKs manage their own HTTP.

### Caching

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| stdlib `pathlib` + `json` + `os.stat` | N/A (stdlib) | File-based FMP cache with per-endpoint TTLs | Port the original scanner's proven `fmp-api.sh` caching pattern directly to Python. File-per-endpoint-per-ticker (`data/cache/<endpoint>/<TICKER>.json`). TTL checked via `os.stat().st_mtime`. Zero dependencies. | HIGH |

**What NOT to use:**

- `diskcache` -- Overkill. Uses SQLite under the hood, adds a dependency, and the caching requirement is trivially simple: check file age against TTL, serve or fetch. The original bash implementation is ~30 lines. The Python port will be ~50 lines.
- `shelve` -- Binary format, not human-inspectable. The cache files should be plain JSON so operators can inspect cached responses during debugging.
- `functools.lru_cache` -- In-memory only, lost between runs. The whole point is disk persistence across scan sessions.

### Agent Orchestration

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Plain Python functions + `concurrent.futures` | N/A (stdlib) | Multi-agent pipeline orchestration | The agent flow is a deterministic pipeline: analyst -> validator -> epistemic reviewer. This is a function call chain, not a graph. No framework needed. Use `concurrent.futures.ThreadPoolExecutor` for parallel cluster analysis (Step 8 sector scans). | HIGH |

**What NOT to use:**

- `langgraph` / `langchain` -- Massive dependency tree, abstractions that obscure the pipeline. The integration plan describes a linear flow with one retry loop (validator rejection -> re-run analyst, max 2 retries). This is a for-loop, not a graph.
- `autogen` / `crewai` -- Agent framework overhead for a 3-agent pipeline with fixed topology. These frameworks solve dynamic agent routing problems this project doesn't have.
- `pydantic-ai` -- Interesting abstraction but adds a layer between the code and the Anthropic SDK. The structured output pattern is clean enough with raw `anthropic` + `pydantic`.
- `openai-agents-sdk` -- Wrong provider. The agents use Claude, not OpenAI.

### Configuration

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Existing `config.py` + `AppConfig` dataclass | N/A (existing) | Centralized configuration | Extend the existing `AppConfig` with new fields: `anthropic_api_key`, `claude_analyst_model`, `claude_reviewer_model`, `claude_validator_model`. Keep the existing dotenv discovery. | HIGH |

### Testing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `unittest` (stdlib) | N/A | All tests | Existing test infrastructure. No reason to switch. Agent tests use fixture-based mocking of SDK calls. | HIGH |
| `unittest.mock` (stdlib) | N/A | Mock SDK calls in agent tests | Mock `anthropic.Anthropic().messages.parse()` and `google.genai.Client().models.generate_content()` in unit tests. Never hit live APIs in CI. | HIGH |

**What NOT to use:** `pytest`. The existing suite is `unittest`-based with a working pattern. Migration adds no value and creates churn.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Claude SDK | `anthropic` (direct) | `pydantic-ai`, `instructor` | Extra abstraction layer. The SDK's `.parse()` method already does Pydantic integration natively. |
| Gemini SDK | `google-genai` | `google-generativeai` | Deprecated. Support ended Nov 2025. No new features. |
| Gemini SDK | `google-genai` | Raw HTTP to Gemini API | Loses grounded search convenience, citation extraction, and schema management. |
| Caching | File-based (stdlib) | `diskcache`, `redis` | SQLite/network overhead for a trivial file-age check. Plain JSON is debuggable. |
| Orchestration | Plain Python | `langgraph`, `crewai`, `autogen` | Fixed 3-agent linear pipeline. Framework overhead is negative value. |
| HTTP | `requests` | `httpx` | Async not needed. SDKs handle their own HTTP. Only FMP calls need `requests`. |
| HTTP | `requests` | `urllib` (current) | `requests.Session` connection pooling matters for batch FMP scans (50+ tickers). Cleaner error handling. |
| Structured output | `anthropic` + `pydantic` | `instructor` | Instructor was essential before the SDK had native `.parse()`. Now redundant. |

---

## Dependency Impact Analysis

### Before (current)
```
Runtime dependencies: 0
```

### After (proposed)
```
Runtime dependencies: 4 direct
  anthropic >=0.84.0    (~15 transitive deps including httpx, pydantic)
  google-genai >=1.66.0 (~10 transitive deps including google-auth, requests)
  pydantic >=2.12.0     (pydantic-core, typing-extensions, annotated-types)
  requests >=2.31.0     (urllib3, certifi, charset-normalizer, idna)
```

Note: `pydantic` and `requests` are already transitive dependencies of `anthropic` and `google-genai` respectively. Pinning them directly ensures version control and makes them explicit imports.

### Dependency Overlap

Both `anthropic` and `google-genai` pull in `pydantic` and HTTP libraries. No conflicts expected -- `anthropic` uses `httpx` internally, `google-genai` uses `requests`/`httplib2`. They coexist without issues.

---

## SDK Usage Patterns

### Anthropic: Structured Output with Pydantic (Agent Pattern)

```python
from pydantic import BaseModel, Field
from anthropic import Anthropic

class AnalystOverlay(BaseModel):
    """Structured analysis overlay produced by the analyst agent."""
    catalyst_stack: list[CatalystEntry]
    invalidation_triggers: list[InvalidationTrigger]
    decision_memo: DecisionMemo
    # ... remaining fields per schema

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

response = client.messages.parse(
    model="claude-sonnet-4-6",  # configurable per agent
    max_tokens=8192,
    system="You are a financial analyst. Follow strategy-rules.md exactly...",
    messages=[{"role": "user", "content": f"Analyze {ticker} given this evidence:\n{raw_bundle_json}"}],
    output_format=AnalystOverlay,
)

overlay: AnalystOverlay = response.parsed_output
```

### Google GenAI: Grounded Search (Sector Knowledge Pattern)

```python
from google import genai
from google.genai import types

client = genai.Client()  # reads GOOGLE_API_KEY from env

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=f"What are the key competitive dynamics in {sub_sector}?",
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    ),
)

# Extract grounding metadata (citations, search queries used)
grounding = response.candidates[0].grounding_metadata
```

### FMP Cache (File-Based TTL Pattern)

```python
import json
import time
from pathlib import Path

TTL_MAP = {
    "screener": 604800,   # 7 days
    "profile": 2592000,   # 30 days
    "income": 7776000,    # 90 days
    "price-history": 86400,  # 1 day
    # ... matches original scanner
}

def cached_fetch(endpoint: str, ticker: str, fetch_fn, *, fresh: bool = False) -> dict:
    cache_file = Path(f"data/cache/{endpoint}/{ticker}.json")
    if not fresh and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < TTL_MAP.get(endpoint, 604800):
            return json.loads(cache_file.read_text())

    data = fetch_fn()
    if data:  # never cache empty/error responses
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, indent=2))
    return data
```

---

## Configuration Changes

Extend `AppConfig` in `config.py`:

```python
@dataclass(frozen=True)
class AppConfig:
    # Existing
    fmp_api_key: str | None
    gemini_api_key: str | None
    openai_api_key: str | None
    codex_judge_model: str

    # New: Anthropic
    anthropic_api_key: str | None
    claude_analyst_model: str      # default: "claude-sonnet-4-6"
    claude_reviewer_model: str     # default: "claude-sonnet-4-6"
    claude_validator_model: str    # default: "claude-sonnet-4-6"

    # New: Gemini model for grounded search
    gemini_search_model: str       # default: "gemini-2.5-flash"
```

New `.env` variables:
```
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_ANALYST_MODEL=claude-sonnet-4-6
CLAUDE_REVIEWER_MODEL=claude-sonnet-4-6
CLAUDE_VALIDATOR_MODEL=claude-sonnet-4-6
GEMINI_SEARCH_MODEL=gemini-2.5-flash
```

---

## Installation

```bash
# Production dependencies
pip install anthropic>=0.84.0 google-genai>=1.66.0 pydantic>=2.12.0 requests>=2.31.0

# Update pyproject.toml dependencies section:
# [project]
# dependencies = [
#     "anthropic>=0.84.0",
#     "google-genai>=1.66.0",
#     "pydantic>=2.12.0",
#     "requests>=2.31.0",
# ]

# Then reinstall in editable mode
pip install -e .
```

No dev-only dependencies needed beyond what's already present.

---

## Key Technical Decisions

### 1. Pydantic Models as Agent Contracts (not just JSON Schema)

The existing codebase uses JSON Schema files in `assets/methodology/` for validation. The new agent layer should define Pydantic models that **generate** JSON Schema (via `model.model_json_schema()`) rather than duplicating schema definitions. This keeps the Pydantic models as the single source of truth for agent output shapes while remaining compatible with the existing `schemas.py` validation infrastructure.

**Flow:** Pydantic model -> generates JSON Schema -> validates against existing pipeline contracts.

### 2. Sync-Only (No Async)

The integration plan specifies "parallel analyst runs per cluster, serial sector hydration." This maps to `concurrent.futures.ThreadPoolExecutor` for parallelism, not `asyncio`. The Anthropic SDK supports both sync and async clients -- use the sync client (`Anthropic()`) throughout.

**Why not async:** The pipeline is I/O-bound on API calls with rate limits. Async adds complexity (event loop management, async context managers) without meaningful throughput gain when you're rate-limited to ~50 requests/minute on Claude API.

### 3. Transport Injection Pattern (Preserved)

The existing codebase uses `GeminiTransport = Callable[[str, dict, dict], dict]` for dependency injection in tests. Extend this pattern to the Anthropic client:

```python
# Production: real SDK client
client = Anthropic()

# Test: mock that returns fixture responses
client = MockAnthropicClient(fixtures_dir="tests/fixtures/agents/")
```

This preserves the existing testing philosophy of fixture-based response mocking with no live API calls in CI.

### 4. google-genai NOT google-generativeai

The existing `gemini.py` uses raw `urllib` HTTP calls to the Gemini API (not the SDK). For the new grounded search capability (Step 3: Sector Knowledge), use the `google-genai` SDK which provides native `GoogleSearch` tool support. The existing `gemini.py` raw-bundle retrieval can remain as-is (it works, has tests, and doesn't need grounded search). Add grounded search as a new function in `sector.py` that uses the `google-genai` SDK.

**Migration path:** Don't refactor existing `gemini.py`. Add `google-genai` SDK calls only in new `sector.py` module and in the epistemic reviewer's independent precedent verification.

---

## Sources

- [Anthropic Python SDK on PyPI](https://pypi.org/project/anthropic/) -- v0.84.0, Feb 2026
- [Anthropic Structured Outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) -- GA, supports Pydantic `.parse()`
- [google-genai on PyPI](https://pypi.org/project/google-genai/) -- v1.66.0, Mar 2026
- [google-generativeai deprecation](https://pypi.org/project/google-generativeai/) -- EOL Nov 2025, replaced by google-genai
- [Gemini Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search) -- native SDK support
- [Pydantic on PyPI](https://pypi.org/project/pydantic/) -- v2.12.5
- [Anthropic SDK GitHub](https://github.com/anthropics/anthropic-sdk-python) -- structured outputs, tool use
- [Google GenAI SDK GitHub](https://github.com/googleapis/python-genai) -- grounded search, unified SDK
