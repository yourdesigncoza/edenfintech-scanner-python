"""LLM interaction logging — real-time terminal output + markdown audit log.

Wraps transport callables to capture every LLM input/output without changing
the underlying transport contract.
"""
from __future__ import annotations

import hashlib
import json
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_ELIDE_MIN_BYTES = 2048

# Section markers that precede large JSON blobs in prompts.
# Each marker is followed by a JSON object that may be duplicated across calls.
_SECTION_MARKERS = [
    "SECTOR CONTEXT:\n",
    "EVIDENCE CONTEXT:\n",
    "STAGE 1 FUNDAMENTALS:\n",
    "STAGE 1 FUNDAMENTALS (for reference",
    "STAGE 2 QUALITATIVE:\n",
    "ANALYST OVERLAY (analysis_inputs",
    "RAW CANDIDATE DATA",
]


class LlmInteractionLog:
    """Accumulates LLM call records for terminal display and markdown export."""

    def __init__(self) -> None:
        self._records: list[dict] = []

    def record(
        self,
        agent: str,
        model: str,
        input_payload: dict,
        output_payload: dict,
    ) -> None:
        """Store an interaction and print it to the terminal."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": model,
            "input": input_payload,
            "output": output_payload,
        }
        self._records.append(entry)
        self._print_to_terminal(entry)

    def record_cache_hit(
        self,
        agent: str,
        model: str,
        cached_data: dict,
    ) -> None:
        """Insert a synthetic record for a cache-served response."""
        preview = json.dumps(cached_data, indent=2)
        if len(preview) > 500:
            preview = preview[:500] + "\n... [truncated]"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": f"{model} [CACHE HIT]",
            "input": {
                "system": "[CACHE HIT — response served from local cache, no API call made]",
                "messages": [],
            },
            "output": {
                "text": preview,
                "stop_reason": "cache_hit",
            },
        }
        self._records.insert(0, entry)

    def _print_to_terminal(self, entry: dict) -> None:
        agent = entry["agent"]
        model = entry["model"]
        inp = entry["input"]
        out = entry["output"]

        header = f" LLM CALL: {agent} [{model}] "
        bar = header.center(72, "\u2501")
        print(f"\n{bar}")

        # Input
        print("\u2500\u2500 INPUT \u2500\u2500")
        system = inp.get("system", "")
        if system:
            preview = system[:500] + ("..." if len(system) > 500 else "")
            print(f"System: {preview}")

        messages = inp.get("messages", [])
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, indent=2)
            preview = content[:500] + ("..." if len(content) > 500 else "")
            print(f"{role.title()}: {preview}")

        if inp.get("output_schema"):
            print(f"Schema: (constrained decoding, {len(json.dumps(inp['output_schema']))} chars)")

        # Output
        print("\u2500\u2500 OUTPUT \u2500\u2500")
        stop_reason = out.get("stop_reason", "")
        text = out.get("text", "")
        print(f"Stop reason: {stop_reason}")
        preview = text[:1000] + ("..." if len(text) > 1000 else "")
        print(f"Response: {preview}")
        print("\u2501" * 72)

    def write_markdown(self, out_dir: Path) -> Path:
        """Write full untruncated audit log to out_dir/llm-interactions.md."""
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "llm-interactions.md"

        seen_blocks: dict[str, tuple[int, int]] = {}
        lines: list[str] = ["# LLM Interaction Log\n"]
        for i, entry in enumerate(self._records, 1):
            lines.append(f"## Call {i}: {entry['agent']} [{entry['model']}]\n")
            lines.append(f"**Timestamp:** {entry['timestamp']}\n")

            inp = entry["input"]
            system = inp.get("system", "")
            if system:
                lines.append("### System Prompt\n")
                system = _elide_repeated_sections(system, seen_blocks, i)
                lines.append(f"```\n{system}\n```\n")

            messages = inp.get("messages", [])
            for msg in messages:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = json.dumps(content, indent=2)
                lines.append(f"### {role.title()} Message\n")
                content = _elide_repeated_sections(content, seen_blocks, i)
                lines.append(f"```\n{content}\n```\n")

            if inp.get("output_schema"):
                lines.append("### Output Schema\n")
                lines.append(f"```json\n{json.dumps(inp['output_schema'], indent=2)}\n```\n")

            # Responses are never elided — always log in full
            out = entry["output"]
            lines.append("### Response\n")
            lines.append(f"**Stop reason:** {out.get('stop_reason', '')}\n")
            lines.append(f"```\n{out.get('text', '')}\n```\n")
            lines.append("---\n")

        path.write_text("\n".join(lines))
        return path


def _extract_json_block(text: str, start: int) -> str | None:
    """Extract a JSON object from *text* starting at *start* by brace-counting.

    Returns the substring ``{...}`` (inclusive) or ``None`` if braces don't
    balance within the remaining text.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _elide_repeated_sections(
    content: str,
    seen: dict[str, tuple[int, int]],
    call_number: int,
) -> str:
    """Replace duplicated large subsections within a raw prompt string.

    Finds known section markers (SECTOR CONTEXT, EVIDENCE CONTEXT, STAGE N ...)
    followed by a JSON object.  On first occurrence the content is kept and its
    hash is recorded.  On subsequent occurrences the JSON blob is replaced with
    an ``[ELIDED]`` reference.

    Also falls back to whole-content hashing when the entire string >= 2 KB and
    contains no recognised markers (catches forwarded stage outputs that are
    pure JSON).
    """
    result = content
    for marker in _SECTION_MARKERS:
        idx = result.find(marker)
        if idx == -1:
            continue
        # Find the opening '{' after the marker
        json_start = result.find("{", idx + len(marker))
        if json_start == -1:
            continue
        json_block = _extract_json_block(result, json_start)
        if json_block is None or len(json_block) < _ELIDE_MIN_BYTES:
            continue
        digest = hashlib.md5(json_block.encode()).hexdigest()
        if digest in seen:
            first_call, size = seen[digest]
            size_kb = size // 1024
            placeholder = f"[ELIDED: ~{size_kb}KB — identical to Call {first_call} above]"
            result = result[:json_start] + placeholder + result[json_start + len(json_block):]
        else:
            seen[digest] = (call_number, len(json_block))

    # Whole-content fallback: catches pure-JSON forwarded payloads (e.g.
    # the synthesis overlay passed to both validator calls).
    if len(result) >= _ELIDE_MIN_BYTES and result == content:
        # No markers matched — try hashing the entire content.
        digest = hashlib.md5(content.encode()).hexdigest()
        if digest in seen:
            first_call, size = seen[digest]
            size_kb = size // 1024
            return f"[ELIDED: ~{size_kb}KB — identical content logged in Call {first_call} above]"
        seen[digest] = (call_number, len(content))

    return result


def wrap_transport(
    transport: Callable[[dict], dict],
    log: LlmInteractionLog,
    *,
    model_name: str | None = None,
) -> Callable[[dict], dict]:
    """Wrap an LlmTransport to log every call.

    Model resolution chain: payload["model"] > model_name kwarg > "unknown".
    The model_name fallback is useful for OpenAI transports where the model
    is extracted from config rather than carried in the payload.
    """
    def wrapper(payload: dict) -> dict:
        model = payload.get("model") or model_name or "unknown"
        system = payload.get("system", "")

        # Infer agent label from system prompt content
        agent = _infer_agent(system)

        # Capture a clean copy of the input for logging
        log_input = {
            "system": system,
            "messages": payload.get("messages", []),
        }
        if payload.get("output_schema"):
            log_input["output_schema"] = payload["output_schema"]

        response = transport(payload)

        log.record(agent, model, log_input, response)
        return response

    return wrapper


def wrap_gemini_transport(
    transport: Callable[[str, dict, dict], dict],
    log: LlmInteractionLog,
) -> Callable[[str, dict, dict], dict]:
    """Wrap a GeminiTransport to log every call (redacts API key)."""
    def wrapper(url: str, headers: dict, payload: dict) -> dict:
        # Extract model from URL
        model = "gemini"
        if "/models/" in url:
            model = url.split("/models/")[1].split(":")[0]

        # Build log-safe input (redact API key)
        safe_headers = {k: ("REDACTED" if "key" in k.lower() else v) for k, v in headers.items()}
        user_parts = []
        for content_block in payload.get("contents", []):
            for part in content_block.get("parts", []):
                if "text" in part:
                    user_parts.append(part["text"])

        log_input = {
            "system": f"[Gemini grounded search] URL: {url}",
            "messages": [{"role": "user", "content": "\n".join(user_parts)}],
        }

        response = transport(url, headers, payload)

        # Extract response text for logging
        response_text = ""
        candidates = response.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    response_text += part["text"]
        if not response_text:
            response_text = response.get("text", json.dumps(response)[:2000])

        log.record("gemini/qualitative", model, log_input, {"text": response_text, "stop_reason": "end"})
        return response

    return wrapper


def _infer_agent(system_prompt: str) -> str:
    """Infer agent name from system prompt keywords."""
    lower = system_prompt.lower()
    if "cagr exception" in lower:
        return "hardening/cagr_exception"
    # Analyst sub-stages (must check before generic "analyst" or "epistemic")
    if "quantitative fundamentals" in lower:
        return "analyst/fundamentals"
    if "qualitative analysis" in lower:
        return "analyst/qualitative"
    if "unified structured analysis" in lower:
        return "analyst/synthesis"
    # Epistemic reviewer (check for the role, not the field name)
    if "independent epistemic" in lower or "pcs questions" in lower or "pcs (probabilistic" in lower:
        return "epistemic_reviewer"
    if "pre-mortem" in lower or "thesis invalidation" in lower:
        return "validator/pre_mortem"
    if "red-team" in lower or "adversarial" in lower:
        return "validator/red_team"
    if "analyst" in lower:
        return "analyst"
    return "unknown"
