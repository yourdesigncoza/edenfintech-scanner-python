# LLM Log Dedup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicated content from `llm-interactions.md`, fix agent label inference, and log Gemini cache hits.

**Architecture:** Content-hash elision in `write_markdown()` replaces repeated fenced code blocks with references. Two bug fixes: reorder `_infer_agent()` patterns, insert synthetic Gemini record on cache hit.

**Tech Stack:** Python stdlib only (`hashlib`). unittest for tests.

---

### Task 1: Fix `_infer_agent()` label inference

**Files:**
- Modify: `src/edenfintech_scanner_bootstrap/llm_logger.py:194-207`
- Test: `tests/test_llm_logger.py`

**Step 1: Write failing tests**

```python
class TestInferAgent(unittest.TestCase):
    """_infer_agent label inference from system prompts."""

    def test_analyst_fundamentals(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing QUANTITATIVE FUNDAMENTALS ONLY."
        self.assertEqual(_infer_agent(prompt), "analyst/fundamentals")

    def test_analyst_qualitative(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing QUALITATIVE ANALYSIS ONLY."
        self.assertEqual(_infer_agent(prompt), "analyst/qualitative")

    def test_analyst_synthesis(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a senior equity research analyst producing a UNIFIED STRUCTURED ANALYSIS OVERLAY."
        self.assertEqual(_infer_agent(prompt), "analyst/synthesis")

    def test_analyst_with_epistemic_inputs_field(self):
        """Analyst prompts mentioning 'epistemic_inputs' as output field must NOT match epistemic_reviewer."""
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = (
            "You are a senior equity research analyst producing QUANTITATIVE FUNDAMENTALS ONLY.\n"
            "SCOPE: Produce screening_inputs, epistemic_inputs, and field_provenance."
        )
        self.assertEqual(_infer_agent(prompt), "analyst/fundamentals")

    def test_epistemic_reviewer(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are an independent epistemic reviewer for the EdenFinTech scan pipeline."
        self.assertEqual(_infer_agent(prompt), "epistemic_reviewer")

    def test_validator_red_team(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are a red-team adversarial reviewer."
        self.assertEqual(_infer_agent(prompt), "validator/red_team")

    def test_validator_pre_mortem(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "Run a pre-mortem analysis with thesis invalidation conditions."
        self.assertEqual(_infer_agent(prompt), "validator/pre_mortem")

    def test_cagr_exception(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "You are evaluating a CAGR exception candidate."
        self.assertEqual(_infer_agent(prompt), "hardening/cagr_exception")

    def test_unknown_fallback(self):
        from edenfintech_scanner_bootstrap.llm_logger import _infer_agent
        prompt = "Hello world."
        self.assertEqual(_infer_agent(prompt), "unknown")
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_llm_logger.TestInferAgent -v`
Expected: `test_analyst_fundamentals`, `test_analyst_qualitative`, `test_analyst_synthesis`, `test_analyst_with_epistemic_inputs_field` FAIL (all return `epistemic_reviewer`)

**Step 3: Implement fix**

Replace `_infer_agent` in `llm_logger.py:194-207`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_llm_logger.TestInferAgent -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/edenfintech_scanner_bootstrap/llm_logger.py tests/test_llm_logger.py
git commit -m "fix: _infer_agent now labels analyst stages correctly"
```

---

### Task 2: Content-hash elision in `write_markdown()`

**Files:**
- Modify: `src/edenfintech_scanner_bootstrap/llm_logger.py:77-113`
- Test: `tests/test_llm_logger.py`

**Step 1: Write failing tests**

```python
class TestWriteMarkdownElision(unittest.TestCase):
    """write_markdown elides duplicate fenced code blocks."""

    def _make_log_with_duplication(self, tmp_dir):
        """Build a log where a large block appears in two calls."""
        log = LlmInteractionLog()
        large_block = '{"sector": "' + "x" * 3000 + '"}'

        # Call 1: contains the large block in system prompt
        log.record(
            "analyst/fundamentals", "gpt-5-mini",
            {
                "system": f"Instructions here.\nSECTOR CONTEXT:\n{large_block}\nEnd.",
                "messages": [{"role": "user", "content": "Analyze ticker X."}],
            },
            {"text": '{"result": "ok"}', "stop_reason": "end_turn"},
        )
        # Call 2: same large block in system prompt
        log.record(
            "analyst/qualitative", "gpt-5-mini",
            {
                "system": f"More instructions.\nSECTOR CONTEXT:\n{large_block}\nEnd.",
                "messages": [{"role": "user", "content": "Qualitative analysis."}],
            },
            {"text": '{"result": "qual"}', "stop_reason": "end_turn"},
        )
        return log

    def test_duplicate_block_elided(self):
        """Second occurrence of a large code block is replaced with reference."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log_with_duplication(tmp)
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            # Large block should appear once in full
            self.assertEqual(content.count("x" * 3000), 1)
            # Second occurrence should be elided
            self.assertIn("[ELIDED:", content)
            self.assertIn("Call 1", content)

    def test_response_blocks_never_elided(self):
        """Even if responses are identical, they are not elided."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            same_response = '{"verdict": "' + "y" * 3000 + '"}'
            for i in range(2):
                log.record(
                    f"agent_{i}", "model",
                    {"system": f"prompt {i}", "messages": []},
                    {"text": same_response, "stop_reason": "end_turn"},
                )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            # Response should appear twice (never elided)
            self.assertEqual(content.count("y" * 3000), 2)
            self.assertNotIn("[ELIDED:", content)

    def test_small_blocks_not_elided(self):
        """Blocks under 2KB are never elided even if duplicated."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            log = LlmInteractionLog()
            small_block = '{"tiny": "data"}'
            for i in range(2):
                log.record(
                    f"agent_{i}", "model",
                    {"system": small_block, "messages": []},
                    {"text": "ok", "stop_reason": "end_turn"},
                )
            path = log.write_markdown(Path(tmp))
            content = path.read_text()
            self.assertNotIn("[ELIDED:", content)
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_llm_logger.TestWriteMarkdownElision -v`
Expected: `test_duplicate_block_elided` FAIL (large block appears twice, no `[ELIDED:` present)

**Step 3: Implement elision**

Add `_elide_repeated_blocks` and update `write_markdown` in `llm_logger.py`:

```python
import hashlib
import re

_ELIDE_MIN_BYTES = 2048

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
        if len(body) < _ELIDE_MIN_BYTES:
            return match.group(0)
        digest = hashlib.md5(body.encode()).hexdigest()
        if digest in seen:
            first_call, size = seen[digest]
            size_kb = size // 1024
            return f"{fence_open}\n[ELIDED: ~{size_kb}KB — identical content logged in Call {first_call} above]\n```"
        seen[digest] = (call_number, len(body))
        return match.group(0)

    return re.sub(r"(```[a-z]*)\n(.*?)\n```", _replace, text, flags=re.DOTALL)
```

Update `write_markdown`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_llm_logger.TestWriteMarkdownElision -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/edenfintech_scanner_bootstrap/llm_logger.py tests/test_llm_logger.py
git commit -m "feat: elide duplicate fenced code blocks in llm-interactions.md"
```

---

### Task 3: Log Gemini cache hits

**Files:**
- Modify: `src/edenfintech_scanner_bootstrap/automation.py:138-144`
- Modify: `src/edenfintech_scanner_bootstrap/llm_logger.py` (add helper)
- Test: `tests/test_llm_logger.py`

**Step 1: Write failing test**

```python
class TestGeminiCacheHitRecord(unittest.TestCase):
    """Gemini cache hit inserts a synthetic log record."""

    def test_record_gemini_cache_hit(self):
        log = LlmInteractionLog()
        cached_data = {"raw_candidates": [{"ticker": "OMI", "catalyst_evidence": [{"claim": "test"}]}]}
        log.record_cache_hit("gemini/qualitative", "gemini-3-pro-preview", cached_data)
        self.assertEqual(len(log._records), 1)
        rec = log._records[0]
        self.assertEqual(rec["agent"], "gemini/qualitative")
        self.assertEqual(rec["model"], "gemini-3-pro-preview [CACHE HIT]")
        self.assertIn("CACHE HIT", rec["input"]["system"])
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_llm_logger.TestGeminiCacheHitRecord -v`
Expected: FAIL — `record_cache_hit` doesn't exist

**Step 3: Implement `record_cache_hit` on `LlmInteractionLog`**

Add to `LlmInteractionLog` class:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_llm_logger.TestGeminiCacheHitRecord -v`
Expected: PASS

**Step 5: Wire into `automation.py`**

After the `run_live_scan()` call and merged bundle load (around line 148), add:

```python
    # Log Gemini cache hit if transport was not called
    if llm_log is not None:
        has_gemini_record = any(r["agent"] == "gemini/qualitative" for r in llm_log._records)
        gemini_raw_path = out_dir / "gemini-raw.json"
        if not has_gemini_record and gemini_raw_path.exists():
            gemini_data = json.loads(gemini_raw_path.read_text())
            model = gemini_data.get("model", "gemini")
            llm_log.record_cache_hit("gemini/qualitative", model, gemini_data)
```

**Step 6: Run full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add src/edenfintech_scanner_bootstrap/llm_logger.py src/edenfintech_scanner_bootstrap/automation.py tests/test_llm_logger.py
git commit -m "feat: log Gemini cache hits as synthetic records in llm-interactions.md"
```

---

### Task 4: Verify against batch-32 data

**Step 1: Dry-run verification**

Write a quick script to apply the new `write_markdown` to the batch-32 records (or simply re-run `auto-scan OMI` and check the output).

Run: `python -m edenfintech_scanner_bootstrap.cli auto-scan OMI --out-dir runs/batch-33`

**Step 2: Compare log sizes**

```bash
wc -l runs/batch-32/OMI/raw/llm-interactions.md runs/batch-33/OMI/raw/llm-interactions.md
wc -c runs/batch-32/OMI/raw/llm-interactions.md runs/batch-33/OMI/raw/llm-interactions.md
```

Expected: batch-33 log ~150-200KB vs batch-32 738KB

**Step 3: Verify call labels**

```bash
grep "^## Call" runs/batch-33/OMI/raw/llm-interactions.md
```

Expected: `analyst/fundamentals`, `analyst/qualitative`, `analyst/synthesis` (not `epistemic_reviewer`), and `gemini/qualitative [... CACHE HIT]` as Call 1.

**Step 4: Verify elision markers present**

```bash
grep "\[ELIDED:" runs/batch-33/OMI/raw/llm-interactions.md
```

Expected: Multiple elision markers for sector context and forwarded stage outputs.

**Step 5: Verify LLM outputs unchanged**

```bash
diff <(python -m json.tool runs/batch-32/OMI/raw/analyst-synthesis.json) <(python -m json.tool runs/batch-33/OMI/raw/analyst-synthesis.json) | head -20
```

Expected: Outputs differ in content (different LLM run) but same structure/schema. No truncation.

**Step 6: Commit verification notes**

```bash
git commit --allow-empty -m "verify: batch-33 log dedup confirmed — ~150-200KB vs 738KB baseline"
```
