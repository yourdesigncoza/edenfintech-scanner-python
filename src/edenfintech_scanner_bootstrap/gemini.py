from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable
from urllib import error, request

from .assets import gemini_raw_bundle_schema_path, load_json
from .config import AppConfig, load_config
from .schemas import SchemaValidationError, validate_instance


DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"
GEMINI_PROMPT_VERSION = "v2-2026-04-20"
EVIDENCE_ARRAY_KEYS = [
    "research_notes",
    "catalyst_evidence",
    "risk_evidence",
    "management_observations",
    "compensation_evidence",
    "moat_observations",
    "precedent_observations",
    "epistemic_anchors",
]
FORBIDDEN_METHOD_KEYS = {
    "analysis",
    "analysis_inputs",
    "catalyst_classification",
    "cluster_status",
    "decision",
    "epistemic_inputs",
    "epistemic_review",
    "final_cluster_status",
    "pass",
    "probability",
    "reject",
    "screening",
    "screening_inputs",
    "target_stage",
    "verdict",
}
ALLOWED_BUNDLE_KEYS = {"title", "scan_date", "version", "scan_parameters", "methodology_notes", "raw_candidates"}
ALLOWED_SCAN_PARAMETER_KEYS = {"scan_mode", "focus", "api"}
ALLOWED_CANDIDATE_KEYS = {"ticker", "cluster_name", "industry", "gemini_context"}
ALLOWED_GEMINI_CONTEXT_KEYS = {"prompt_context", *EVIDENCE_ARRAY_KEYS}
ALLOWED_PROMPT_CONTEXT_KEYS = {"model", "research_question", "search_scope", "search_directives", "context_entities"}
# Each entry: (directive_sentence, target_evidence_array)
SEARCH_DIRECTIVES: tuple[tuple[str, str], ...] = (
    (
        "Credit-rating actions: latest Fitch, Moody's, and S&P ratings with date and outlook change; "
        "any downgrades in the last 18 months "
        "(or equivalent rating agency filings in the issuer's jurisdiction).",
        "risk_evidence",
    ),
    (
        "Debt maturity schedule: principal amount and year for every tranche due within 36 months; "
        "identify any maturity wall concentrated in a single year "
        "(or equivalent debt-disclosure filings in the issuer's jurisdiction).",
        "risk_evidence",
    ),
    (
        "Revenue concentration: top 5 customers (or payers, for healthcare; merchants, for payments; "
        "tenants, for real estate) by revenue share with most recent percentage; "
        "recent contract losses, non-renewals, or renegotiations "
        "(or equivalent customer-concentration disclosure in the issuer's jurisdiction).",
        "risk_evidence",
    ),
    (
        "Regulatory and rate-setting cadence: material regulatory actions, pricing or reimbursement rate changes "
        "relevant to the issuer's sector (e.g. CMS for healthcare, FERC for energy, CFPB/OCC for financial services), "
        "FTC/DOJ enforcement actions, consent decrees, and state AG actions with dates and status "
        "(or equivalent regulatory filings in the issuer's jurisdiction).",
        "catalyst_evidence",
    ),
    (
        "Insider transactions from Form 4 in the trailing 12 months: buys versus sells by named executives, "
        "dollar value, and any 10b5-1 plan disclosures "
        "(or equivalent insider-filing disclosures in the issuer's jurisdiction).",
        "management_observations",
    ),
    (
        "Executive compensation structure from the most recent DEF 14A proxy: which metrics performance pay "
        "is tied to (FCF, EPS, EBITDA, revenue, ROIC), target thresholds, and any broken-promise history "
        "(or equivalent compensation filing in the issuer's jurisdiction).",
        "compensation_evidence",
    ),
    (
        "Competitive landscape: recent market-share shifts, new entrants, competitor product launches, "
        "and structural changes to industry dynamics that could threaten the company's competitive position.",
        "moat_observations",
    ),
)
ALLOWED_EVIDENCE_ITEM_KEYS = {"claim", "source_title", "source_url", "source_type", "published_at", "confidence_note"}

GeminiTransport = Callable[[str, dict[str, str], dict], dict]


def _load_schema() -> dict:
    return load_json(gemini_raw_bundle_schema_path())


def _response_schema() -> dict:
    schema = _load_schema()
    context_schema = schema["definitions"]["gemini_context"]
    return {
        "type": "object",
        "required": list(EVIDENCE_ARRAY_KEYS),
        "properties": {
            key: context_schema["properties"][key]
            for key in EVIDENCE_ARRAY_KEYS
        },
        "definitions": schema["definitions"],
    }


def _default_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
    http_request = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with request.urlopen(http_request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            last_exc = exc
            if attempt == 0:
                import time
                time.sleep(2)
    raise RuntimeError(f"Gemini request failed after 2 attempts: {last_exc}") from last_exc


def _reject_unknown_keys(value: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported keys: {', '.join(unknown)}")


def _reject_forbidden_method_keys(value: object, label: str) -> None:
    if isinstance(value, dict):
        forbidden = sorted(FORBIDDEN_METHOD_KEYS & set(value))
        if forbidden:
            raise ValueError(f"{label} contains forbidden methodology keys: {', '.join(forbidden)}")
        for key, child in value.items():
            _reject_forbidden_method_keys(child, f"{label}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_method_keys(child, f"{label}[{idx}]")


def _validate_gemini_bundle_shape(bundle: dict) -> None:
    try:
        validate_instance(bundle, _load_schema())
    except SchemaValidationError as exc:
        raise ValueError(f"gemini raw bundle schema validation failed: {exc}") from exc

    _reject_forbidden_method_keys(bundle, "gemini_bundle")
    _reject_unknown_keys(bundle, ALLOWED_BUNDLE_KEYS, "gemini_bundle")
    _reject_unknown_keys(bundle["scan_parameters"], ALLOWED_SCAN_PARAMETER_KEYS, "gemini_bundle.scan_parameters")

    for idx, candidate in enumerate(bundle["raw_candidates"]):
        label = f"gemini_bundle.raw_candidates[{idx}]"
        _reject_unknown_keys(candidate, ALLOWED_CANDIDATE_KEYS, label)
        _reject_unknown_keys(candidate["gemini_context"], ALLOWED_GEMINI_CONTEXT_KEYS, f"{label}.gemini_context")
        _reject_unknown_keys(
            candidate["gemini_context"]["prompt_context"],
            ALLOWED_PROMPT_CONTEXT_KEYS,
            f"{label}.gemini_context.prompt_context",
        )
        for evidence_key in EVIDENCE_ARRAY_KEYS:
            for item_idx, item in enumerate(candidate["gemini_context"][evidence_key]):
                _reject_unknown_keys(item, ALLOWED_EVIDENCE_ITEM_KEYS, f"{label}.gemini_context.{evidence_key}[{item_idx}]")


def _extract_response_text(payload: dict) -> str:
    direct_text = payload.get("text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini response did not include candidates")

    for candidate in candidates:
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        text_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
        if text_parts:
            return "".join(text_parts)

    raise RuntimeError("Gemini response did not include a supported text payload")


def _format_directives_block(directives: tuple[tuple[str, str], ...]) -> str:
    lines = ["Search directives — for each directive, populate the specified evidence array:"]
    for directive, array_name in directives:
        lines.append(f"- {directive} → populate `{array_name}`")
    lines.append(
        "\nCRITICAL: Adhere strictly to the 8-array output schema. Do NOT create new arrays. "
        "Do NOT editorialize or emit verdicts, decisions, probabilities, pass/reject judgments, "
        "or cluster status. Extract factual evidence with sources only."
    )
    return "\n".join(lines)


def _candidate_prompt(
    ticker: str,
    research_question: str,
    search_scope: str,
    *,
    entities: dict[str, str] | None = None,
    directives: tuple[tuple[str, str], ...] | None = None,
) -> str:
    parts: list[str] = [
        "Collect raw qualitative research evidence for the EdenFinTech scanner.\n"
        f"Ticker: {ticker}\n"
        f"Research question: {research_question}\n"
        f"Search scope: {search_scope}\n"
    ]
    if entities:
        entity_lines = ["Company context:"]
        for key, value in entities.items():
            entity_lines.append(f"  {key}: {value}")
        parts.append("\n".join(entity_lines) + "\n")
    if directives:
        parts.append(_format_directives_block(directives) + "\n")
    parts.append(
        "Return only sourced evidence snippets. Do not return screening verdicts, pass/reject decisions, "
        "probability bands, final catalyst classifications, or cluster status judgments.\n"
        "Populate each evidence item with a concise claim, source title, and source URL.\n"
        "Include executive compensation structure from proxy filings (DEF 14A) if available: "
        "what metrics is pay tied to (revenue, EPS, EBITDA, FCF, ROIC)? "
        "Note insider buying/selling patterns."
    )
    return "".join(parts)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        transport: GeminiTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport or _default_transport

    def qualitative_research(
        self,
        ticker: str,
        *,
        research_question: str,
        search_scope: str,
        context_entities: dict[str, str] | None = None,
        directives: tuple[tuple[str, str], ...] | None = None,
    ) -> dict:
        prompt_ctx: dict = {
            "model": self.model,
            "research_question": research_question,
            "search_scope": search_scope,
        }
        if directives is not None:
            prompt_ctx["search_directives"] = [f"{d} → {a}" for d, a in directives]
        if context_entities is not None:
            prompt_ctx["context_entities"] = context_entities

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _candidate_prompt(
                        ticker,
                        research_question,
                        search_scope,
                        entities=context_entities,
                        directives=directives,
                    )}],
                }
            ],
            "tools": [{"googleSearch": {}}, {"urlContext": {}}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": _response_schema(),
            },
        }
        response = self.transport(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            payload,
        )

        response_text = _extract_response_text(response)
        try:
            raw_context = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini response did not contain valid JSON") from exc
        if not isinstance(raw_context, dict):
            raise RuntimeError("Gemini response JSON must be an object")

        candidate = {
            "ticker": ticker,
            "gemini_context": {
                "prompt_context": prompt_ctx,
                **raw_context,
            },
        }
        bundle = {
            "title": "Gemini Raw Bundle Validation",
            "scan_date": str(date.today()),
            "version": "v1",
            "scan_parameters": {
                "scan_mode": "specific_tickers",
                "focus": search_scope,
                "api": "Gemini",
            },
            "methodology_notes": ["Validation wrapper"],
            "raw_candidates": [candidate],
        }
        _validate_gemini_bundle_shape(bundle)
        return candidate


def build_gemini_bundle(
    tickers: list[str],
    *,
    client: GeminiClient,
    scan_mode: str = "specific_tickers",
    focus: str | None = None,
    research_question: str | None = None,
    context_entities: dict[str, dict[str, str]] | None = None,
    directives: tuple[tuple[str, str], ...] | None = None,
) -> dict:
    if not tickers:
        raise ValueError("tickers must not be empty")

    search_scope = focus or ", ".join(tickers)
    resolved_question = research_question or "Collect sourced qualitative research evidence relevant to this scan."
    resolved_directives = directives if directives is not None else SEARCH_DIRECTIVES
    bundle = {
        "title": f"EdenFinTech Gemini Raw Bundle - {', '.join(tickers)}",
        "scan_date": str(date.today()),
        "version": "v1",
        "scan_parameters": {
            "scan_mode": scan_mode,
            "focus": search_scope,
            "api": "Gemini",
        },
        "methodology_notes": [
            "This bundle was fetched from Gemini and contains sourced qualitative evidence only.",
            "It does not emit screening verdicts, final classifications, probability bands, or pass/reject decisions.",
        ],
        "raw_candidates": [
            client.qualitative_research(
                ticker,
                research_question=resolved_question,
                search_scope=search_scope,
                context_entities=(context_entities or {}).get(ticker),
                directives=resolved_directives,
            )
            for ticker in tickers
        ],
    }
    _validate_gemini_bundle_shape(bundle)
    return bundle


def build_gemini_bundle_with_config(
    tickers: list[str],
    *,
    config: AppConfig | None = None,
    transport: GeminiTransport | None = None,
    model: str = DEFAULT_GEMINI_MODEL,
    focus: str | None = None,
    research_question: str | None = None,
    context_entities: dict[str, dict[str, str]] | None = None,
    directives: tuple[tuple[str, str], ...] | None = None,
) -> dict:
    app_config = config or load_config()
    app_config.require("gemini_api_key")
    client = GeminiClient(app_config.gemini_api_key, model=model, transport=transport)
    return build_gemini_bundle(
        tickers,
        client=client,
        focus=focus,
        research_question=research_question,
        context_entities=context_entities,
        directives=directives,
    )


def merge_fmp_and_gemini_bundles(fmp_bundle: dict, gemini_bundle: dict) -> dict:
    _validate_gemini_bundle_shape(gemini_bundle)
    if "raw_candidates" not in fmp_bundle or not isinstance(fmp_bundle["raw_candidates"], list):
        raise ValueError("fmp_bundle.raw_candidates must be a list")

    gemini_by_ticker = {candidate["ticker"]: candidate for candidate in gemini_bundle["raw_candidates"]}
    merged_candidates: list[dict] = []
    seen: set[str] = set()

    for candidate in fmp_bundle["raw_candidates"]:
        if not isinstance(candidate, dict) or "ticker" not in candidate:
            raise ValueError("fmp_bundle.raw_candidates[] must be objects with ticker")
        ticker = candidate["ticker"]
        overlay = gemini_by_ticker.get(ticker)
        merged = dict(candidate)
        if overlay is not None:
            for key, value in overlay.items():
                if key == "ticker":
                    continue
                if key in merged and merged[key] != value:
                    raise ValueError(f"bundle merge conflict for {ticker}.{key}")
                merged[key] = value
        merged_candidates.append(merged)
        seen.add(ticker)

    unmatched_gemini = sorted(ticker for ticker in gemini_by_ticker if ticker not in seen)
    if unmatched_gemini:
        raise ValueError(
            "gemini bundle contains tickers that are missing from the FMP bundle: "
            + ", ".join(unmatched_gemini)
        )

    methodology_notes = list(dict.fromkeys([
        *list(fmp_bundle.get("methodology_notes", [])),
        *list(gemini_bundle.get("methodology_notes", [])),
        "Merged bundle keeps adapters retrieval-only; importers.py remains the normalization boundary.",
        "Add screening_inputs, analysis_inputs, and epistemic_inputs before running build-scan-input.",
    ]))

    fmp_params = fmp_bundle.get("scan_parameters", {})
    gemini_params = gemini_bundle.get("scan_parameters", {})
    merged_bundle = {
        "title": f"{fmp_bundle.get('title', 'EdenFinTech FMP Raw Bundle')} + Gemini",
        "scan_date": max(str(fmp_bundle.get("scan_date", "")), str(gemini_bundle.get("scan_date", ""))),
        "version": fmp_bundle.get("version", gemini_bundle.get("version", "v1")),
        "scan_parameters": {
            "scan_mode": fmp_params.get("scan_mode", gemini_params.get("scan_mode", "specific_tickers")),
            "focus": fmp_params.get("focus", gemini_params.get("focus", "")),
            "api": "Financial Modeling Prep + Gemini",
        },
        "portfolio_context": fmp_bundle.get("portfolio_context", {}),
        "methodology_notes": methodology_notes,
        "raw_candidates": merged_candidates,
    }
    return merged_bundle


def write_gemini_bundle(path: Path, bundle: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2))
