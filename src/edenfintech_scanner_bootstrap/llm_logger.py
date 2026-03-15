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
                block = f"```\n{system}\n```\n"
                block = _elide_repeated_blocks(block, seen_blocks, i)
                lines.append(block)

            messages = inp.get("messages", [])
            for msg in messages:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = json.dumps(content, indent=2)
                lines.append(f"### {role.title()} Message\n")
                block = f"```\n{content}\n```\n"
                block = _elide_repeated_blocks(block, seen_blocks, i)
                lines.append(block)

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


def _elide_repeated_blocks(
    text: str,
    seen: dict[str, tuple[int, int]],
    call_number: int,
) -> str:
    """Replace fenced code blocks that duplicate earlier calls with references.

    Args:
        text: markdown string containing ```...``` blocks
        seen: {md5_hex: (first_call_number, byte_size)} — mutated in place
        call_number: current call number (1-based)

    Returns:
        text with duplicate blocks replaced by [ELIDED: ...] references
    """
    def _replace(match: re.Match) -> str:
        fence_open = match.group(1)  # e.g. "```json" or "```"
        body = match.group(2)
        # Whole-block dedup
        if len(body) >= _ELIDE_MIN_BYTES:
            digest = hashlib.md5(body.encode()).hexdigest()
            if digest in seen:
                first_call, size = seen[digest]
                size_kb = size // 1024
                return f"{fence_open}\n[ELIDED: ~{size_kb}KB — identical content logged in Call {first_call} above]\n```"
            seen[digest] = (call_number, len(body))
        # Line-level dedup for large lines within non-duplicate blocks
        lines = body.split("\n")
        changed = False
        for j, line in enumerate(lines):
            if len(line) < _ELIDE_MIN_BYTES:
                continue
            line_key = f"L:{hashlib.md5(line.encode()).hexdigest()}"
            if line_key in seen:
                first_call, size = seen[line_key]
                size_kb = size // 1024
                lines[j] = f"[ELIDED: ~{size_kb}KB — identical content logged in Call {first_call} above]"
                changed = True
            else:
                seen[line_key] = (call_number, len(line))
        if changed:
            return f"{fence_open}\n" + "\n".join(lines) + "\n```"
        return match.group(0)

    return re.sub(r"(```[a-z]*)\n(.*?)\n```", _replace, text, flags=re.DOTALL)


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
