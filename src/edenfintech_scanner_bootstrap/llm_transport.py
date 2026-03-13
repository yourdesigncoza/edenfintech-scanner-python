"""Shared LLM transport and response parsing for agent layer.

Provides default Anthropic and OpenAI transports plus safe JSON parsing with
clear error diagnostics for empty responses, truncation, and malformed output.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Callable

logger = logging.getLogger(__name__)

LlmTransport = Callable[[dict], dict]


class LlmResponseError(Exception):
    """Raised when an LLM response cannot be used."""

    def __init__(self, message: str, *, agent: str, raw_text: str, stop_reason: str | None = None):
        self.agent = agent
        self.raw_text = raw_text
        self.stop_reason = stop_reason
        super().__init__(message)


def default_anthropic_transport(
    request_payload: dict,
    *,
    api_key: str | None,
    model: str,
    max_tokens: int = 8192,
) -> dict:
    """Shared default transport using the Anthropic SDK.

    Returns dict with 'text' and 'stop_reason' keys.
    Raises LlmResponseError on SDK-level failures with clear diagnostics.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    output_schema = request_payload.get("output_schema")
    create_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=request_payload["system"],
        messages=request_payload["messages"],
    )
    if output_schema:
        create_kwargs["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": output_schema,
            }
        }
    try:
        response = client.messages.create(**create_kwargs)
    except anthropic.AuthenticationError as exc:
        raise LlmResponseError(
            f"Anthropic authentication failed — check ANTHROPIC_API_KEY: {exc}",
            agent="transport",
            raw_text="",
            stop_reason=None,
        ) from exc
    except anthropic.APIError as exc:
        raise LlmResponseError(
            f"Anthropic API error: {exc}",
            agent="transport",
            raw_text="",
            stop_reason=None,
        ) from exc

    if not response.content:
        raise LlmResponseError(
            f"Anthropic returned empty content (stop_reason={response.stop_reason}, "
            f"model={model})",
            agent="transport",
            raw_text="",
            stop_reason=response.stop_reason,
        )

    text = response.content[0].text or ""
    return {"text": text, "stop_reason": response.stop_reason}


def _make_schema_strict(schema: dict) -> dict:
    """Recursively enforce OpenAI strict structured output rules.

    - Injects ``additionalProperties: false`` on every object
    - Forces all properties into the ``required`` array
    - Strips unsupported keywords (``default``, ``format``, ``$schema``, etc.)
    - Recurses into nested objects, array items, definitions, and compositions
    """
    schema = dict(schema)  # shallow copy to avoid mutating originals
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        schema["required"] = list(props.keys())
        schema["properties"] = {k: _make_schema_strict(v) for k, v in props.items()}
    elif schema.get("type") == "array" and "items" in schema:
        schema["items"] = _make_schema_strict(schema["items"])

    # Recurse into definitions / $defs
    for defs_key in ("definitions", "$defs"):
        if defs_key in schema and isinstance(schema[defs_key], dict):
            schema[defs_key] = {k: _make_schema_strict(v) for k, v in schema[defs_key].items()}

    # Recurse into composition keywords
    for composite_key in ("anyOf", "oneOf", "allOf"):
        if composite_key in schema and isinstance(schema[composite_key], list):
            schema[composite_key] = [_make_schema_strict(sub) for sub in schema[composite_key]]

    for banned in ("default", "format", "$schema", "pattern",
                    "minLength", "maxLength", "minimum", "maximum",
                    "minItems", "maxItems", "multipleOf"):
        schema.pop(banned, None)
    return schema


def default_openai_transport(
    request_payload: dict,
    *,
    api_key: str | None,
    model: str,
    max_tokens: int = 16384,
    timeout: int = 180,
) -> dict:
    """Default transport using the OpenAI Chat Completions API via urllib.

    Returns dict with 'text' and 'stop_reason' keys (same contract as Anthropic).
    Raises LlmResponseError on HTTP or response-level failures.
    """
    api_key = api_key or ""
    messages = [
        {"role": "system", "content": request_payload["system"]},
        *request_payload["messages"],
    ]

    body: dict = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }

    output_schema = request_payload.get("output_schema")
    if output_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": _make_schema_strict(output_schema),
            },
        }
    else:
        # JSON mode: guarantees valid JSON syntax without schema enforcement.
        # Requires the word "JSON" in the prompt — synthesis prompt already has it.
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read().decode()
            try:
                result = json.loads(raw_bytes)
            except json.JSONDecodeError as exc:
                raise LlmResponseError(
                    f"OpenAI returned non-JSON response (len={len(raw_bytes)}): {raw_bytes[:200]!r}",
                    agent="transport",
                    raw_text=raw_bytes,
                    stop_reason=None,
                ) from exc
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode()
        except Exception:
            pass
        raise LlmResponseError(
            f"OpenAI API error (HTTP {exc.code}): {error_body}",
            agent="transport",
            raw_text=error_body,
            stop_reason=None,
        ) from exc
    except urllib.error.URLError as exc:
        raise LlmResponseError(
            f"OpenAI API connection error: {exc.reason}",
            agent="transport",
            raw_text="",
            stop_reason=None,
        ) from exc

    choices = result.get("choices", [])
    if not choices:
        raise LlmResponseError(
            f"OpenAI returned no choices (model={model})",
            agent="transport",
            raw_text=json.dumps(result),
            stop_reason=None,
        )

    choice = choices[0]
    text = choice.get("message", {}).get("content", "") or ""
    finish_reason = choice.get("finish_reason", "")

    # Map OpenAI finish_reason to our stop_reason convention
    stop_reason_map = {"stop": "end_turn", "length": "max_tokens"}
    stop_reason = stop_reason_map.get(finish_reason, finish_reason)

    return {"text": text, "stop_reason": stop_reason}


def _extract_json_text(raw: str) -> str:
    """Extract JSON from text that may have markdown fences or preamble."""
    m = re.search(r'```(?:json)?\s*(.*?)\s*```', raw, re.DOTALL)
    if m:
        return m.group(1)
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end > start:
        return raw[start:end + 1]
    return raw


def parse_llm_json(response: dict, *, agent: str) -> dict:
    """Parse JSON from an LLM transport response with clear error diagnostics.

    Checks for empty text, max_tokens truncation, and JSON decode failures.
    Uses _extract_json_text to handle markdown fences or preamble text.
    Raises LlmResponseError with actionable messages.
    """
    raw_text = response.get("text", "")
    stop_reason = response.get("stop_reason")

    if not raw_text:
        raise LlmResponseError(
            f"[{agent}] LLM returned empty response (stop_reason={stop_reason}). "
            f"Possible causes: invalid API key, unsupported model, or content filter.",
            agent=agent,
            raw_text=raw_text,
            stop_reason=stop_reason,
        )

    if stop_reason == "max_tokens":
        logger.warning(
            "[%s] Response truncated (stop_reason=max_tokens, len=%d). "
            "JSON may be incomplete.",
            agent,
            len(raw_text),
        )

    cleaned = _extract_json_text(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        snippet = raw_text[:200] if len(raw_text) > 200 else raw_text
        raise LlmResponseError(
            f"[{agent}] Failed to parse LLM response as JSON: {exc}. "
            f"stop_reason={stop_reason}, response_length={len(raw_text)}, "
            f"snippet={snippet!r}",
            agent=agent,
            raw_text=raw_text,
            stop_reason=stop_reason,
        ) from exc
