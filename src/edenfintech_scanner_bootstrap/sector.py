"""Sector knowledge hydration, loading, and staleness tracking.

Hydrates per-sub-sector structured research via Gemini grounded search
and stores validated JSON at ``data/sectors/<slug>/knowledge.json``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from .assets import load_json, sector_knowledge_schema_path
from .config import AppConfig, discover_project_root, load_config
from .gemini import GeminiClient, _extract_response_text
from .schemas import validate_instance

logger = logging.getLogger(__name__)

STALENESS_DAYS = 180
AUTO_STALENESS_DAYS = 60
SECTOR_DATA_DIR = "data/sectors"
REGISTRY_FILENAME = "registry.json"

KNOWLEDGE_CATEGORIES = [
    "sector_economics",
    "sector_lifecycle",
    "margin_dynamics",
    "capital_allocation",
    "peer_landscape",
    "valuation_baseline",
    "competitive_dynamics",
    "turnaround_playbook",
    "regulatory_landscape",
    "cagr_achievability",
    "kill_factors",
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a sector name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _sector_dir(project_root: Path, sector_slug: str) -> Path:
    return project_root / SECTOR_DATA_DIR / sector_slug


def _registry_path(project_root: Path) -> Path:
    return project_root / SECTOR_DATA_DIR / REGISTRY_FILENAME


def _load_registry(project_root: Path) -> dict:
    path = _registry_path(project_root)
    if path.exists():
        return json.loads(path.read_text())
    return {"sectors": {}}


def _update_registry(
    project_root: Path,
    sector_name: str,
    sector_slug: str,
    sub_sectors: list[str],
) -> None:
    registry = _load_registry(project_root)
    registry["sectors"][sector_slug] = {
        "sector_name": sector_name,
        "hydrated_at": datetime.now().isoformat(),
        "sub_sectors": sub_sectors,
        "knowledge_path": f"{SECTOR_DATA_DIR}/{sector_slug}/knowledge.json",
    }
    path = _registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2))


def _sector_query_prompt(sub_sector: str, category: str) -> str:
    """Return the Gemini prompt for a given sub-sector and knowledge category."""
    templates = {
        "sector_economics": (
            f"For the {sub_sector} sub-sector, describe the core business model "
            "and unit economics. How do companies make money — volume vs price, "
            "recurring vs project-based revenue, fixed vs variable cost structure? "
            "Include key operating metrics (ROIC, ROCE, working capital needs, "
            "cash conversion cycle) and what 'good' looks like for each."
        ),
        "sector_lifecycle": (
            f"For the {sub_sector} sub-sector, is this industry in secular growth, "
            "secular decline, or cyclical mean-reversion? What drives the cycle — "
            "what does trough look like vs peak? What is the typical cycle duration "
            "from trough to peak? What leading indicators signal where the sector "
            "currently sits in its cycle?"
        ),
        "margin_dynamics": (
            f"For the {sub_sector} sub-sector, identify typical free cash flow "
            "margin ranges: best-in-class, average, and below-average with specific "
            "company examples. More importantly, HOW do companies in this sector "
            "expand margins — through cost-cutting, operating leverage, mix shift "
            "to higher-margin products/services, pricing power, or automation? "
            "What is the typical margin expansion path from trough to normalized?"
        ),
        "capital_allocation": (
            f"For the {sub_sector} sub-sector, describe typical capital allocation "
            "patterns. What is normal maintenance vs growth capex intensity? What "
            "are standard leverage ratios (Net Debt/EBITDA) for healthy vs stressed "
            "companies? What are typical dividend payout ratios and buyback behaviors? "
            "How does capital deployment differ between leaders and laggards?"
        ),
        "peer_landscape": (
            f"For the {sub_sector} sub-sector, describe the competitive landscape. "
            "Who are the key players and what are approximate market shares? Is "
            "the market fragmented or consolidated (oligopoly)? What M&A and "
            "consolidation dynamics are at play? How do new entrants typically "
            "gain share, and what barriers protect incumbents?"
        ),
        "valuation_baseline": (
            f"For the {sub_sector} sub-sector, identify typical valuation multiples "
            "including P/FCF, EV/EBITDA, and P/S ratios. Differentiate between "
            "premium and average performers. What specifically drives a premium "
            "multiple in this sector — growth rate, contract visibility, lower "
            "leverage, recurring revenue, or regulatory protection? Include "
            "DCF assumptions and comparable transaction multiples from recent M&A."
        ),
        "competitive_dynamics": (
            f"For the {sub_sector} sub-sector, evaluate which of these six moat "
            "types are viable and prevalent: (1) low-cost advantage, (2) switching "
            "costs, (3) regulatory barriers, (4) brand power, (5) capital barriers "
            "to entry, (6) network effects. For each applicable moat type, how "
            "durable is it and how easily can it be impaired? Include specific "
            "company examples."
        ),
        "turnaround_playbook": (
            f"For the {sub_sector} sub-sector, describe the typical turnaround "
            "playbook for struggling companies. What are the common problem/fix "
            "maps — what breaks and what specific actions fix it? Include historical "
            "turnaround case studies with timelines and outcomes. What catalyst "
            "types (management change, spin-off, deleveraging, cost restructuring) "
            "have historically worked in this sector?"
        ),
        "regulatory_landscape": (
            f"For the {sub_sector} sub-sector, describe the regulatory environment "
            "and macro sensitivities. Include key regulations, compliance costs, "
            "pending legislation, and how regulatory changes can act as either "
            "catalysts (clearance, deregulation) or kill factors (bans, price "
            "controls). How sensitive is this sector to interest rates, commodity "
            "inputs, or consumer spending cycles?"
        ),
        "cagr_achievability": (
            f"For the {sub_sector} sub-sector, is a 30%+ compound annual return "
            "historically achievable through a turnaround or deep-value investment? "
            "What specific combination of factors drives multi-bagger returns — "
            "earnings growth, multiple expansion, margin reversion, or deleveraging? "
            "Include specific examples of companies that delivered 30%+ CAGR from "
            "distressed levels and what drove the returns."
        ),
        "kill_factors": (
            f"For the {sub_sector} sub-sector, identify factors that cause permanent "
            "value destruction — not cyclical downturns but structural, irreversible "
            "threats. Include technology disruption and obsolescence, permanent "
            "demand destruction, regulatory wipeouts, and secular decline indicators. "
            "What distinguishes a temporary setback from a permanent impairment "
            "in this sector?"
        ),
    }
    return templates[category]


def _sector_response_schema(category: str) -> dict:
    """Return a JSON Schema for a single category's Gemini response."""
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


_MAX_CATEGORY_RETRIES = 2


def _fetch_category(
    sub_sector: str,
    category: str,
    client: GeminiClient,
) -> list[dict]:
    """Fetch a single knowledge category from Gemini with retry.

    Returns the list of evidence items, or raises after exhausting retries.
    """
    prompt = _sector_query_prompt(sub_sector, category)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "tools": [{"googleSearch": {}}, {"urlContext": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": _sector_response_schema(category),
        },
    }

    last_exc: Exception | None = None
    for attempt in range(_MAX_CATEGORY_RETRIES + 1):
        try:
            response = client.transport(
                f"https://generativelanguage.googleapis.com/v1beta/models/{client.model}:generateContent",
                {
                    "Content-Type": "application/json",
                    "x-goog-api-key": client.api_key,
                },
                payload,
            )
            response_text = _extract_response_text(response)
            parsed = json.loads(response_text)
            return parsed["items"]
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_CATEGORY_RETRIES:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "Gemini query failed for %s/%s (attempt %d/%d): %s — retrying in %ds",
                    sub_sector, category, attempt + 1,
                    _MAX_CATEGORY_RETRIES + 1, exc, wait,
                )
                time.sleep(wait)

    raise RuntimeError(
        f"Gemini query failed for {sub_sector}/{category} after "
        f"{_MAX_CATEGORY_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc


def _hydrate_sub_sector(
    sub_sector: str,
    sector_name: str,
    client: GeminiClient,
) -> dict:
    """Run Gemini queries for one sub-sector, return a sub_sector_knowledge object.

    Individual category failures are retried. If a category still fails after
    retries, it is skipped with a warning and a placeholder is stored so the
    remaining categories are not lost.
    """
    result: dict = {"sub_sector_name": sub_sector}
    failed: list[str] = []

    for i, category in enumerate(KNOWLEDGE_CATEGORIES):
        if i > 0:
            time.sleep(2)

        try:
            result[category] = _fetch_category(sub_sector, category, client)
        except Exception as exc:
            logger.error("Skipping %s/%s: %s", sub_sector, category, exc)
            result[category] = [{
                "claim": f"Hydration failed: {exc}",
                "source_title": "ERROR",
                "source_url": "N/A",
                "confidence_note": "This category failed during hydration and should be re-hydrated.",
            }]
            failed.append(category)

    if failed:
        logger.warning(
            "%d/%d categories failed for %s: %s",
            len(failed), len(KNOWLEDGE_CATEGORIES), sub_sector, ", ".join(failed),
        )

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hydrate_sector(
    sector_name: str,
    *,
    sub_sectors: list[str] | None = None,
    client: GeminiClient | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict:
    """Hydrate sector knowledge via Gemini grounded search.

    Parameters
    ----------
    sector_name:
        Human-readable sector name (e.g. "Consumer Defensive").
    sub_sectors:
        List of sub-sector names to hydrate. Required for now;
        FMP screener discovery is planned for Phase 6.
    client:
        Pre-configured GeminiClient. If *None*, one is created from *config*.
    config:
        AppConfig instance. If *None*, loaded from environment.
    project_root:
        Project root for data storage. Auto-discovered if *None*.
    """
    if not sub_sectors:
        sub_sectors = [sector_name]

    app_config = config or load_config()
    if client is None:
        app_config.require("gemini_api_key")
    resolved_client = client or GeminiClient(app_config.gemini_api_key)
    root = project_root or discover_project_root() or Path.cwd()

    sector_slug = _slugify(sector_name)

    sub_sector_data = []
    for sub_sector in sub_sectors:
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
    _update_registry(root, sector_name, sector_slug, sub_sectors)

    return knowledge_doc


def load_sector_knowledge(
    sector_name: str,
    *,
    project_root: Path | None = None,
) -> dict:
    """Load sector knowledge from disk and validate against schema.

    Raises
    ------
    FileNotFoundError
        If the sector has not been hydrated.
    """
    root = project_root or discover_project_root() or Path.cwd()
    sector_slug = _slugify(sector_name)
    knowledge_path = _sector_dir(root, sector_slug) / "knowledge.json"

    if not knowledge_path.exists():
        raise FileNotFoundError(
            f"Sector '{sector_name}' has not been hydrated. "
            f"Expected knowledge file at: {knowledge_path}"
        )

    knowledge_doc = json.loads(knowledge_path.read_text())
    schema = load_json(sector_knowledge_schema_path())
    validate_instance(knowledge_doc, schema)
    return knowledge_doc


def check_sector_freshness(
    sector_name: str,
    *,
    staleness_days: int = STALENESS_DAYS,
    project_root: Path | None = None,
) -> dict:
    """Check if sector knowledge is stale.

    Parameters
    ----------
    staleness_days:
        Number of days after which knowledge is considered stale.
        Defaults to STALENESS_DAYS (180).

    Returns
    -------
    dict with keys: sector, status, stale, and optionally hydrated_at, age_days.
    status is one of: "FRESH", "STALE", "NOT_HYDRATED".
    """
    root = project_root or discover_project_root() or Path.cwd()
    registry = _load_registry(root)
    sector_slug = _slugify(sector_name)

    entry = registry.get("sectors", {}).get(sector_slug)
    if entry is None:
        return {"sector": sector_name, "status": "NOT_HYDRATED", "stale": True}

    hydrated_at = datetime.fromisoformat(entry["hydrated_at"])
    age_days = (datetime.now() - hydrated_at).days
    is_stale = age_days > staleness_days

    return {
        "sector": sector_name,
        "status": "STALE" if is_stale else "FRESH",
        "stale": is_stale,
        "hydrated_at": entry["hydrated_at"],
        "age_days": age_days,
    }


def ensure_sector_knowledge(
    sector_name: str,
    *,
    staleness_days: int = AUTO_STALENESS_DAYS,
    client: GeminiClient | None = None,
    config: AppConfig | None = None,
    project_root: Path | None = None,
) -> dict:
    """Load sector knowledge, auto-hydrating if missing or stale.

    Uses the sector_name as its own sub-sector for single-industry hydration.
    """
    freshness = check_sector_freshness(
        sector_name, staleness_days=staleness_days, project_root=project_root,
    )

    if freshness["status"] == "FRESH":
        return load_sector_knowledge(sector_name, project_root=project_root)

    # Missing or stale — hydrate with sector_name as the single sub-sector
    num_queries = len(KNOWLEDGE_CATEGORIES)
    print(f"hydrating ({num_queries} queries) ...", end=" ", flush=True)
    return hydrate_sector(
        sector_name,
        sub_sectors=[sector_name],
        client=client,
        config=config,
        project_root=project_root,
    )
