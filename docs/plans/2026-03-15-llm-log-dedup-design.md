# LLM Interaction Log Deduplication

**Date:** 2026-03-15
**Status:** Approved
**Scope:** `llm_logger.py` + small `automation.py` change

## Problem

`llm-interactions.md` grew from 699KB (batch-31, 7 calls) to 738KB (batch-32, 6 calls) despite slim candidate stripping raw financial arrays from Stage 2/3. Root cause: large content blocks duplicated across calls (sector context 3x, stage outputs forwarded 2x each, synthesis overlay 2x). ~40-50% of log is duplicate content.

Two additional bugs: analyst calls mislabeled as `epistemic_reviewer`; Gemini cache hits not logged.

## Approach: Section-marker elision in `write_markdown()`

Elide duplicate fenced code blocks at write time using content hashing. Pipeline and in-memory records stay unchanged.

## Changes

### 1. Fix `_infer_agent()` (llm_logger.py)

Reorder and make patterns more specific:
- `"quantitative fundamentals"` -> `analyst/fundamentals`
- `"qualitative analysis"` -> `analyst/qualitative`
- `"unified structured analysis"` -> `analyst/synthesis`
- `"independent epistemic"` or `"pcs questions"` -> `epistemic_reviewer`
- `"pre-mortem"` or `"thesis invalidation"` -> `validator/pre_mortem`
- `"red-team"` or `"adversarial"` -> `validator/red_team`
- `"analyst"` -> `analyst` (generic fallback)

### 2. Log Gemini cache hits (automation.py)

After `run_live_scan()`, if `llm_log` has no `gemini/qualitative` record but `gemini-raw.json` exists, insert a synthetic record with `[CACHE HIT]` marker and truncated preview.

### 3. Content-hash elision in `write_markdown()` (llm_logger.py)

Algorithm:
1. For each record, extract all fenced code blocks from system prompt + user messages
2. Hash blocks >2KB with a fast hash (Python `hash()` or `hashlib.md5`)
3. Track `{hash -> (call_number, byte_size)}` for first occurrence
4. On subsequent occurrence, replace block content with:
   `[ELIDED: ~{size}KB -- identical content logged in Call {N} above]`

Only elides input blocks. Responses and output schemas are never elided.

## Expected Results

| Content | Current | After |
|---------|---------|-------|
| Sector context (3x ~80KB) | ~240KB | ~80KB + 2 refs |
| Stage 1 output forwarded (2x ~37KB) | ~74KB | ~37KB + 1 ref |
| Stage 2 output forwarded (1x ~30KB) | ~30KB | ~30KB (only in Call 3) |
| Synthesis forwarded (2x ~88KB) | ~176KB | ~88KB + 1 ref |
| **Total savings** | | **~350-400KB** |
| **Estimated final size** | 738KB | ~150-200KB |

## Not in scope

- Removing sector context from synthesis prompt (keep for contradiction resolution)
- Output token limits or schema tightening (analyst output growth is legitimate)
- Separate full-debug log file (individual JSON artifacts provide full data)
