# Phase 2: Sector Knowledge Framework - Research

**Researched:** 2026-03-10
**Domain:** Sector knowledge hydration via Gemini grounded search, JSON schema validation, CLI commands
**Confidence:** HIGH

## Summary

Phase 2 builds a sector knowledge module that hydrates structured sector research via Gemini grounded search and stores it as validated JSON. The module has three layers: (1) a `sector.py` module with `hydrate_sector()`, `load_sector_knowledge()`, and `check_sector_freshness()`, (2) a `sector-knowledge.schema.json` that defines per-sub-sector data shape, and (3) two CLI commands (`hydrate-sector`, `sector-status`).

The primary technical challenge is Gemini grounded search integration. SECT-03 specifies "8 queries per sub-sector via google-genai SDK." However, there is a critical compatibility issue: the google-genai SDK does NOT support combining structured JSON output (`response_schema`) with Google Search grounding -- the API rejects the combination. The existing codebase already works around this by using the raw REST API (`urllib`) which allows `responseJsonSchema` + `googleSearch` tool on certain models. The recommendation is to keep the existing raw REST API transport pattern (already proven in `gemini.py`) and NOT introduce the google-genai SDK as a dependency. The requirement's intent (grounded search with structured output) is achievable with the current approach.

The sector knowledge data flows downstream into Phase 3 (analyst agent uses sector context), Phase 6 (sector-scan hydration check), and Phase 7 (holding review). The schema must capture: key metrics, valuation approach, regulatory landscape, historical precedents, moat sources, kill factors, FCF margin ranges, and typical multiples per sub-sector.

**Primary recommendation:** Build `sector.py` reusing the existing `GeminiClient` transport pattern with sector-specific prompts. Use 8 structured queries per sub-sector covering the SECT-02 required fields. Store at `data/sectors/<sector-slug>/knowledge.json` with a `data/sectors/registry.json` tracking hydration dates.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SECT-01 | `sector.py` module with `hydrate_sector()`, `load_sector_knowledge()`, `check_sector_freshness()` | New module following existing adapter patterns (GeminiClient, FmpClient). Three public functions with clear responsibilities. |
| SECT-02 | Sector schema with per-sub-sector: key metrics, valuation approach, regulatory landscape, historical precedents, moat sources, kill factors, FCF margin ranges, typical multiples | New `sector-knowledge.schema.json` in `assets/methodology/`. Schema uses `definitions` style consistent with gemini-raw-bundle.schema.json. |
| SECT-03 | Gemini grounded search integration (8 queries per sub-sector via google-genai SDK) | Use existing raw REST API transport (NOT google-genai SDK -- see pitfall). 8 queries map to the 8 required data categories in SECT-02. GeminiClient already supports googleSearch + urlContext + responseJsonSchema. |
| SECT-04 | Storage at `data/sectors/<sector-slug>/knowledge.json` with `data/sectors/registry.json` and 180-day staleness threshold | File-based storage with slugified sector names. Registry tracks hydration timestamps per sector. Staleness is `datetime.now() - hydration_date > 180 days`. |
| SECT-05 | CLI commands `hydrate-sector` and `sector-status` | Two new argparse subcommands following existing pattern in `cli.py`. `hydrate-sector` takes sector name. `sector-status` reports all sectors with freshness. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `json` | 3.11+ | Sector knowledge serialization, schema files | Already used throughout; no external deps policy |
| Python stdlib `pathlib` | 3.11+ | File paths for sector data | Project standard |
| Python stdlib `datetime` | 3.11+ | Hydration timestamps, staleness checks | Already used for scan dates |
| Python stdlib `re` | 3.11+ | Sector name slugification | Minimal, no external deps |
| Python stdlib `unittest` | 3.11+ | Test framework | Project standard |
| Existing `GeminiClient` | N/A | Gemini API transport with grounded search | Already proven with googleSearch + urlContext + responseJsonSchema |
| Existing `schemas.py` | N/A | JSON Schema validation | Project's custom validator handles $ref, required, enum, type checks |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Existing `config.py` | N/A | API key loading | Load GEMINI_API_KEY for hydration |
| Existing `assets.py` | N/A | Path helpers | Add `sector_knowledge_schema_path()` helper |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw REST API (urllib) | google-genai SDK | SDK cannot combine structured output with Google Search grounding; raw API can. SDK would be a new dependency violating project convention. |
| File-based sector storage | SQLite | Overkill; JSON files are auditable and version-controllable |
| Custom slug function | `python-slugify` | External dependency; sector names are simple enough for `re.sub` |

**Installation:** No new dependencies required.

## Architecture Patterns

### Recommended Project Structure
```
src/edenfintech_scanner_bootstrap/
    sector.py                         # NEW: hydrate_sector(), load_sector_knowledge(), check_sector_freshness()
assets/methodology/
    sector-knowledge.schema.json      # NEW: sector knowledge schema
data/
    sectors/
        registry.json                 # Hydration dates, sector metadata
        consumer-defensive/
            knowledge.json            # Per-sector knowledge file
        technology/
            knowledge.json
```

### Pattern 1: Sector Hydration as Multi-Query Gemini Pipeline
**What:** Each sub-sector requires 8 Gemini grounded search queries, one per knowledge category. Results are merged into a single structured knowledge object per sub-sector.
**When to use:** When a single API call cannot cover all required data (grounded search works best with focused queries).
**Key design:** The 8 queries per sub-sector map directly to SECT-02 required fields:

1. `key_metrics` -- "What are the key financial metrics for evaluating {sub-sector} companies?"
2. `valuation_approach` -- "What valuation methods and typical multiples are used for {sub-sector} companies?"
3. `regulatory_landscape` -- "What is the current regulatory environment for {sub-sector} companies?"
4. `historical_precedents` -- "What are notable turnaround or recovery precedents in {sub-sector}?"
5. `moat_sources` -- "What are the primary sources of competitive advantage in {sub-sector}?"
6. `kill_factors` -- "What factors typically cause permanent value destruction in {sub-sector}?"
7. `fcf_margin_ranges` -- "What are typical FCF margin ranges for {sub-sector} companies?"
8. `typical_multiples` -- "What are typical valuation multiples (P/FCF, EV/EBITDA, P/S) for {sub-sector}?"

```python
# sector.py - core hydration function sketch
from __future__ import annotations
import json
import re
from datetime import date, datetime
from pathlib import Path
from .config import AppConfig, load_config
from .gemini import GeminiClient
from .assets import load_json, sector_knowledge_schema_path
from .schemas import validate_instance, SchemaValidationError

STALENESS_DAYS = 180
SECTOR_DATA_DIR = "data/sectors"
REGISTRY_FILENAME = "registry.json"

KNOWLEDGE_CATEGORIES = [
    "key_metrics",
    "valuation_approach",
    "regulatory_landscape",
    "historical_precedents",
    "moat_sources",
    "kill_factors",
    "fcf_margin_ranges",
    "typical_multiples",
]

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def _sector_dir(project_root: Path, sector_slug: str) -> Path:
    return project_root / SECTOR_DATA_DIR / sector_slug

def _registry_path(project_root: Path) -> Path:
    return project_root / SECTOR_DATA_DIR / REGISTRY_FILENAME
```

### Pattern 2: Registry File for Staleness Tracking
**What:** A `registry.json` at `data/sectors/registry.json` tracks when each sector was last hydrated.
**When to use:** For `sector-status` and freshness checks before scans.

```python
# registry.json shape
{
    "sectors": {
        "consumer-defensive": {
            "sector_name": "Consumer Defensive",
            "hydrated_at": "2026-03-10T14:30:00",
            "sub_sectors": ["Household & Personal Products", "Food Products", ...],
            "knowledge_path": "data/sectors/consumer-defensive/knowledge.json"
        }
    }
}
```

### Pattern 3: Reusing GeminiClient with Sector-Specific Prompts
**What:** Create a `SectorResearchClient` that wraps `GeminiClient` with sector-focused query templates and a different response schema.
**When to use:** For hydrating sector knowledge (different from ticker-based qualitative research).

```python
# The existing GeminiClient.qualitative_research() is ticker-oriented.
# For sector knowledge, create a new method or a wrapper function
# that sends sector-focused prompts with a sector response schema.

def _sector_query_prompt(sub_sector: str, category: str) -> str:
    templates = {
        "key_metrics": (
            f"For the {sub_sector} sub-sector, identify the key financial metrics "
            "investors use to evaluate companies. Include margins, growth rates, "
            "leverage ratios, and efficiency metrics specific to this industry."
        ),
        "kill_factors": (
            f"For the {sub_sector} sub-sector, identify factors that typically cause "
            "permanent value destruction. Include regulatory risks, technology disruption, "
            "demand destruction, and structural decline indicators."
        ),
        # ... similar templates for other categories
    }
    return templates[category]

def _sector_response_schema(category: str) -> dict:
    """Return a JSON Schema for a single category's response."""
    return {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["claim", "source_title", "source_url"],
                    "properties": {
                        "claim": {"type": "string"},
                        "source_title": {"type": "string"},
                        "source_url": {"type": "string"},
                        "confidence_note": {"type": "string"},
                    },
                },
            }
        },
    }
```

### Pattern 4: Sub-Sector Discovery from FMP Profile Data
**What:** FMP profile responses include `sector` and `industry` fields. Sub-sectors (industries within a sector) can be discovered by querying the FMP screener or available-industries endpoint filtered by sector.
**When to use:** To build the list of sub-sectors for a given sector before running Gemini queries.
**Note:** Phase 1 provides cached FMP screener data. The FMP `available-sectors` endpoint returns sector names. FMP profile data has `sector` (e.g., "Industrials") and `industry` (e.g., "Industrial Components") which maps to the sector > sub-sector hierarchy.

### Anti-Patterns to Avoid
- **Using google-genai SDK:** Cannot combine structured output with Google Search grounding. The raw REST API already works. Do not introduce this dependency.
- **Single monolithic query per sector:** Too broad for grounded search. 8 focused queries per sub-sector produce better sourced evidence.
- **Storing sector data outside `data/`:** Keep runtime data in `data/` (gitignored), methodology assets in `assets/`.
- **Coupling sector module to pipeline:** `sector.py` should be a standalone data layer. The pipeline loads sector knowledge via `load_sector_knowledge()` but the hydration workflow is independent.
- **Hardcoding sub-sector lists:** Derive sub-sectors from FMP data or accept them as input; different operators may need different sub-sector granularity.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema validation | Custom sector validator | Existing `schemas.py:validate_instance()` | Already handles $ref, required, enum, type checks |
| Gemini API transport | New HTTP client | Existing `GeminiClient` transport pattern | Already handles auth, error extraction, JSON parsing, search tools |
| CLI argument parsing | Manual sys.argv | Existing argparse subparser pattern | Project convention |
| Date parsing/formatting | Custom parser | `datetime.fromisoformat()` / `.isoformat()` | Python 3.11+ stdlib |
| Sector name slugification | Complex unicode normalization | `re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")` | Sector names are ASCII-only in FMP data |

**Key insight:** The existing `gemini.py` already solved the hard problem of grounded search with structured output via the raw REST API. Reuse the transport pattern, just change the prompts and response schema.

## Common Pitfalls

### Pitfall 1: google-genai SDK Cannot Combine Structured Output with Grounding
**What goes wrong:** Installing `google-genai` and trying to use `response_schema` with `GoogleSearch()` tool raises "controlled generation is not supported with google_search tool."
**Why it happens:** The SDK validates this combination client-side and rejects it. The raw REST API does not have this restriction on all models.
**How to avoid:** Do NOT introduce google-genai SDK. Use the existing raw REST API transport in `GeminiClient` which already works with `googleSearch` + `urlContext` + `responseJsonSchema`.
**Warning signs:** ImportError for `google.genai`, or explicit error about controlled generation.

### Pitfall 2: Grounding Metadata Empty with Structured Output
**What goes wrong:** When combining `responseJsonSchema` with `googleSearch` via the raw REST API, `grounding_chunks` and `grounding_supports` may be empty even though searches ran.
**Why it happens:** Known Gemini API behavior -- grounding metadata is not populated when structured output is enabled.
**How to avoid:** Do NOT rely on grounding metadata for source URLs. Instead, require source URLs in the response schema itself (the `claim`, `source_title`, `source_url` pattern already used in `gemini-raw-bundle.schema.json`). The model will include sources in the structured response even without grounding metadata.
**Warning signs:** Empty `grounding_chunks` in API response.

### Pitfall 3: Rate Limiting with 8 Queries per Sub-Sector
**What goes wrong:** A sector with 10 sub-sectors = 80 Gemini API calls. Rate limits may be hit.
**Why it happens:** Gemini API has per-minute request limits.
**How to avoid:** Add a small delay between calls (e.g., `time.sleep(2)` between queries). Hydration is infrequent (every 180 days), so speed is not critical. Consider sequential processing within a sub-sector, parallel across sub-sectors only if needed.
**Warning signs:** HTTP 429 responses from Gemini API.

### Pitfall 4: Sector Data Directory Not in .gitignore
**What goes wrong:** Hydrated sector knowledge files (potentially large JSON) get committed to git.
**Why it happens:** `data/` directory is not yet gitignored (it does not exist yet).
**How to avoid:** Add `data/` to `.gitignore`. The `runs/` directory is already gitignored; `data/` follows the same pattern.

### Pitfall 5: Sub-Sector Discovery Requires FMP API Call
**What goes wrong:** `hydrate-sector` needs to know what sub-sectors exist within a sector, but this requires either a hardcoded list or an FMP API call.
**Why it happens:** FMP's `available-industries` endpoint or screener can provide this, but Phase 1 caching may not be complete yet when Phase 2 starts.
**How to avoid:** Accept sub-sectors as optional CLI input. If not provided, use the FMP screener (with cache from Phase 1) to discover industries within the sector. Fall back to a reasonable default list if FMP is unavailable.

### Pitfall 6: Schema Divergence Between Sector Knowledge and Pipeline Expectations
**What goes wrong:** Sector knowledge schema defines fields that downstream consumers (analyst agent in Phase 3) expect differently.
**Why it happens:** Schema designed in isolation without considering consumers.
**How to avoid:** Design the sector knowledge schema with explicit references to `strategy-rules.md` concepts: moat types from Q1, kill factors from Step 5b demotion triggers, valuation multiples from Industry Multiple Rules of Thumb, FCF margin ranges from the valuation formula inputs.

## Code Examples

### Sector Knowledge Schema Structure
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Sector Knowledge",
  "type": "object",
  "required": ["sector_name", "sector_slug", "hydrated_at", "model", "sub_sectors"],
  "properties": {
    "sector_name": { "type": "string", "minLength": 1 },
    "sector_slug": { "type": "string", "minLength": 1 },
    "hydrated_at": { "type": "string", "minLength": 1 },
    "model": { "type": "string", "minLength": 1 },
    "sub_sectors": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/definitions/sub_sector_knowledge" }
    }
  },
  "definitions": {
    "evidence_item": {
      "type": "object",
      "required": ["claim", "source_title", "source_url"],
      "properties": {
        "claim": { "type": "string", "minLength": 1 },
        "source_title": { "type": "string", "minLength": 1 },
        "source_url": { "type": "string", "minLength": 1 },
        "confidence_note": { "type": "string" }
      }
    },
    "sub_sector_knowledge": {
      "type": "object",
      "required": [
        "sub_sector_name",
        "key_metrics",
        "valuation_approach",
        "regulatory_landscape",
        "historical_precedents",
        "moat_sources",
        "kill_factors",
        "fcf_margin_ranges",
        "typical_multiples"
      ],
      "properties": {
        "sub_sector_name": { "type": "string", "minLength": 1 },
        "key_metrics": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "valuation_approach": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "regulatory_landscape": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "historical_precedents": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "moat_sources": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "kill_factors": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "fcf_margin_ranges": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        },
        "typical_multiples": {
          "type": "array", "minItems": 1,
          "items": { "$ref": "#/definitions/evidence_item" }
        }
      }
    }
  }
}
```

### Hydration Flow
```python
def hydrate_sector(
    sector_name: str,
    *,
    sub_sectors: list[str] | None = None,
    client: GeminiClient | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict:
    """Hydrate sector knowledge via Gemini grounded search."""
    app_config = config or load_config()
    app_config.require("gemini_api_key")
    resolved_client = client or GeminiClient(app_config.gemini_api_key)
    root = project_root or discover_project_root() or Path.cwd()

    sector_slug = _slugify(sector_name)
    resolved_sub_sectors = sub_sectors or _discover_sub_sectors(sector_name, app_config)

    sub_sector_data = []
    for sub_sector in resolved_sub_sectors:
        knowledge = _hydrate_sub_sector(sub_sector, sector_name, resolved_client)
        sub_sector_data.append(knowledge)

    knowledge_doc = {
        "sector_name": sector_name,
        "sector_slug": sector_slug,
        "hydrated_at": datetime.now().isoformat(),
        "model": resolved_client.model,
        "sub_sectors": sub_sector_data,
    }

    # Validate against schema
    schema = load_json(sector_knowledge_schema_path())
    validate_instance(knowledge_doc, schema)

    # Write to disk
    out_dir = _sector_dir(root, sector_slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "knowledge.json"
    out_path.write_text(json.dumps(knowledge_doc, indent=2))

    # Update registry
    _update_registry(root, sector_name, sector_slug, resolved_sub_sectors)

    return knowledge_doc
```

### Sector Freshness Check
```python
def check_sector_freshness(
    sector_name: str,
    *,
    project_root: Path | None = None,
) -> dict:
    """Check if sector knowledge is stale (older than 180 days)."""
    root = project_root or discover_project_root() or Path.cwd()
    registry = _load_registry(root)
    sector_slug = _slugify(sector_name)

    entry = registry.get("sectors", {}).get(sector_slug)
    if entry is None:
        return {"sector": sector_name, "status": "NOT_HYDRATED", "stale": True}

    hydrated_at = datetime.fromisoformat(entry["hydrated_at"])
    age_days = (datetime.now() - hydrated_at).days
    is_stale = age_days > STALENESS_DAYS

    return {
        "sector": sector_name,
        "status": "STALE" if is_stale else "FRESH",
        "stale": is_stale,
        "hydrated_at": entry["hydrated_at"],
        "age_days": age_days,
    }
```

### CLI Integration
```python
# In cli.py build_parser():
hydrate_sector = subparsers.add_parser("hydrate-sector")
hydrate_sector.add_argument("sector_name")
hydrate_sector.add_argument("--sub-sectors", nargs="+", help="Override sub-sector list")
hydrate_sector.add_argument("--model", default="gemini-3-pro-preview")

sector_status = subparsers.add_parser("sector-status")
sector_status.add_argument("--sector", help="Check specific sector (default: all)")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No sector context in pipeline | Per-sub-sector knowledge hydrated via Gemini grounded search | This phase | Analyst agent (Phase 3) gets industry-specific baselines |
| Manual industry research | Automated 8-query research per sub-sector | This phase | Consistent coverage across all sub-sectors |
| Strategy rules inline multiples only | Schema-validated sector multiples + FCF ranges | This phase | Valuation uses sector-specific data, not just rules of thumb |

## Open Questions

1. **How should sub-sectors be discovered when FMP cache is not yet populated?**
   - What we know: FMP profile has `sector` and `industry` fields. FMP available-industries endpoint exists. Phase 1 caching may not be complete.
   - What's unclear: Whether to hardcode common sector/sub-sector mappings as fallback or require Phase 1 completion.
   - Recommendation: Accept `--sub-sectors` as optional CLI override. If not provided, query FMP available-industries filtered by sector. If that fails, raise an error requiring `--sub-sectors`.

2. **Should sector knowledge be versioned?**
   - What we know: The 180-day staleness window implies periodic re-hydration.
   - What's unclear: Whether to keep historical versions or overwrite.
   - Recommendation: Overwrite `knowledge.json` on re-hydration. The registry tracks the hydration date. If versioning is needed later, add a `version` suffix.

3. **How many sub-sectors per sector is typical?**
   - What we know: FMP sectors like "Consumer Defensive" typically have 5-8 industries (sub-sectors). "Technology" may have 8-12.
   - Recommendation: Support variable counts. With 8 queries per sub-sector and 10 sub-sectors, that is 80 API calls. At 2-second intervals, hydration takes ~3 minutes per sector -- acceptable for a 180-day operation.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Python unittest (stdlib) |
| Config file | None (unittest discovery) |
| Quick run command | `python -m unittest discover -s tests -v` |
| Full suite command | `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SECT-01 | `hydrate_sector()` produces valid knowledge.json | unit | `python -m unittest tests.test_sector.TestHydrateSector.test_produces_valid_knowledge -v` | Wave 0 |
| SECT-01 | `load_sector_knowledge()` returns structured data | unit | `python -m unittest tests.test_sector.TestLoadSectorKnowledge.test_loads_and_validates -v` | Wave 0 |
| SECT-01 | `check_sector_freshness()` detects stale sectors | unit | `python -m unittest tests.test_sector.TestSectorFreshness.test_stale_detection -v` | Wave 0 |
| SECT-02 | Schema validates well-formed sector knowledge | unit | `python -m unittest tests.test_sector.TestSectorSchema.test_valid_knowledge_passes -v` | Wave 0 |
| SECT-02 | Schema rejects missing sub-sector fields | unit | `python -m unittest tests.test_sector.TestSectorSchema.test_missing_fields_rejected -v` | Wave 0 |
| SECT-03 | Gemini grounded search returns sourced evidence per category | unit | `python -m unittest tests.test_sector.TestGeminiSectorQueries.test_grounded_search_per_category -v` | Wave 0 |
| SECT-03 | 8 queries executed per sub-sector | unit | `python -m unittest tests.test_sector.TestGeminiSectorQueries.test_eight_queries_per_sub_sector -v` | Wave 0 |
| SECT-04 | Knowledge stored at correct path | unit | `python -m unittest tests.test_sector.TestSectorStorage.test_knowledge_path -v` | Wave 0 |
| SECT-04 | Registry updated on hydration | unit | `python -m unittest tests.test_sector.TestSectorStorage.test_registry_updated -v` | Wave 0 |
| SECT-04 | 180-day staleness threshold | unit | `python -m unittest tests.test_sector.TestSectorFreshness.test_180_day_threshold -v` | Wave 0 |
| SECT-05 | `hydrate-sector` CLI produces knowledge.json | unit | `python -m unittest tests.test_sector.TestSectorCli.test_hydrate_sector_command -v` | Wave 0 |
| SECT-05 | `sector-status` CLI reports freshness | unit | `python -m unittest tests.test_sector.TestSectorCli.test_sector_status_command -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest discover -s tests -v`
- **Per wave merge:** `python -m unittest discover -s tests -v && python -m edenfintech_scanner_bootstrap.cli validate-assets && python -m edenfintech_scanner_bootstrap.cli run-regression`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_sector.py` -- all SECT-01 through SECT-05 tests (new file)
- [ ] `tests/fixtures/sector/` -- fixture data for sector knowledge (mock Gemini responses, sample knowledge.json)
- [ ] `assets/methodology/sector-knowledge.schema.json` -- new schema file
- [ ] Update `assets.py` with `sector_knowledge_schema_path()` helper
- [ ] Add `data/` to `.gitignore`

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** -- `gemini.py` (GeminiClient transport pattern, grounded search with responseJsonSchema), `fmp.py` (FmpClient transport pattern, profile.sector/industry fields), `cli.py` (argparse subparser pattern), `config.py` (AppConfig, project root discovery), `schemas.py` (custom JSON Schema validator), `assets.py` (path helpers)
- **Existing schemas** -- `gemini-raw-bundle.schema.json` (evidence_item definition reusable for sector knowledge)
- **REQUIREMENTS.md** -- Exact SECT-01..05 definitions
- **strategy-rules.md** -- Sector-relevant concepts: moat types (Q1), kill factors (Step 5b), industry multiples (Step 5), valuation formula inputs

### Secondary (MEDIUM confidence)
- [Google AI Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search) -- Confirmed grounding API works with googleSearch tool via REST
- [googleapis/python-genai issue #665](https://github.com/googleapis/python-genai/issues/665) -- Confirmed google-genai SDK cannot combine structured output with Google Search grounding
- [Google AI Structured Output](https://ai.google.dev/gemini-api/docs/structured-output) -- Confirmed structured output works with response_schema
- [FMP Available Sectors API](https://site.financialmodelingprep.com/developer/docs/stable/available-sectors) -- Sector list endpoint exists

### Tertiary (LOW confidence)
- FMP API response format for available-sectors/available-industries endpoints (docs were 403-blocked; inferred from profile fixture data)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure stdlib Python, reuses existing codebase patterns, no new dependencies
- Architecture: HIGH -- sector module follows established adapter patterns (GeminiClient, FmpClient), schema follows existing JSON Schema conventions
- Pitfalls: HIGH -- google-genai SDK limitation verified via GitHub issue; grounding metadata limitation documented; rate limiting is standard API concern

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable; Gemini API grounding behavior may evolve but raw REST approach is resilient)
