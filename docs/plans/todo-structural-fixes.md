# TODO: Structural Fixes — Attend to This FIRST

> **⚠️ START HERE next work session.** This plan must be completed before any new
> feature work. The project review of 2026-07-06 found that CI has been red since
> 2026-03-13, two of four hardening gates are dead code, and the financial-math
> core is untested. The last five feature commits were made on top of a broken
> verification layer. Fix the safety nets before building on them again.

Review date: 2026-07-06 · HEAD at review: `1f71b7d` · Every finding below was
verified against actual code/schemas at review time (file:line refs may drift a
few lines — re-locate by the quoted code, not the line number).

---

## Context for the executor (read before touching anything)

**Setup & verification commands** (run from repo root):

```bash
source .venv/bin/activate                          # ALWAYS first
python -m unittest discover -s tests -v            # 152 tests, all green at review time, ~0.03s
python -m edenfintech_scanner_bootstrap.cli validate-assets   # currently CRASHES (FileNotFoundError) — Phase 3.2 fixes
python -m edenfintech_scanner_bootstrap.cli run-regression    # currently CRASHES — Phase 3.2 fixes
```

The package is installed editable (`pip install -e .`) — no `PYTHONPATH` needed
locally. Do **not** be alarmed by the two CLI crashes; they are finding #3.2, not
something you broke.

**Testing pattern used throughout this repo:** every LLM client and the FMP
adapter accept an injectable transport (`Callable[[dict], dict]` for LLM clients,
`Callable[[str, dict], list|dict]` for FMP). Tests never hit the network — they
pass a fake transport that returns canned dicts. Copy the style of existing tests
(e.g. `tests/test_scanner_peer_context.py`, `tests/test_screening_determinism.py`)
when writing new ones.

**Ground rules:**
- Work phase by phase, in order. Run the full unittest suite after each phase.
- Write the failing test FIRST for every bug fix (each bug below exists precisely
  because no test covered it).
- If code disagrees with `assets/methodology/strategy-rules.md`, the methodology
  file wins (project rule) — but see Phase 4 for the one documented case where
  the *doc* is the stale artifact.
- Never mention AI assistance in commits, comments, or docs.
- Do not commit/push unless John explicitly asks.

---

## Phase 1 — Restore the hardening gates (highest severity, smallest diff)

Two of the four documented hardening gates in `hardening.py` have **never fired in
production** because `_extract_hardening_flags` in `scanner.py` (defined at
`scanner.py:70`, called at `scanner.py:193` from `_process_single_ticker`) reads
fields that don't exist under those names / at that pipeline stage. No test
references `_extract_hardening_flags`, `detect_probability_anchoring`, or
`cagr_exception_panel` — which is why this went unnoticed.

### 1.1 Fix probability-anchoring gate (dead code)

**The bug** — `scanner.py:85` (inside `_extract_hardening_flags`):

```python
analysis = overlay_candidate.get("analysis_inputs", {})
prob = analysis.get("probability", {})          # BUG: field is "probability_inputs"
base_prob = prob.get("base_probability_pct", 0.0)
```

Schema-verified facts (from `assets/methodology/structured-analysis.schema.json`):
- The field under `analysis_inputs` is named **`probability_inputs`** — the key
  `probability` never exists anywhere in the schema.
- The inner key **`base_probability_pct` is correct** as-is (the
  `probability_inputs` definition contains: `base_probability_pct`, `base_rate`,
  `likert_adjustments`, `ceilings_applied`, `threshold_proximity_warning`).

So `prob` is always `{}`, `base_prob` is always `0.0`, and
`detect_probability_anchoring` (`hardening.py:42`) — which returns a flag **only
when `base_probability_pct == 60.0` exactly AND `dominant_risk_type` is in
`FRICTION_RISK_TYPES`** — can never trigger.

**The fix** — one line:

```python
prob = analysis.get("probability_inputs", {})
```

**The tests** — new file `tests/test_hardening_gates.py`. You need
`FRICTION_RISK_TYPES` (defined at `hardening.py:34`):
`{"Cyclical/Macro", "Regulatory/Political", "Legal/Investigation", "Structural fragility (SPOF)"}`.

Test cases (call `_extract_hardening_flags` directly; it takes
`(overlay_candidate, raw_candidate, ...)` with transport kwargs — pass stub
transports or None where unused, check the signature):

1. `analysis_inputs.probability_inputs.base_probability_pct = 60.0` +
   `dominant_risk_type = "Regulatory/Political"` → `flags["anchoring"]` is not
   None and has `"flag": "PROBABILITY_ANCHORING_SUSPECT"`.
2. Same but `base_probability_pct = 59.0` → `flags["anchoring"]` is None.
3. `60.0` but `dominant_risk_type = "Execution"` (not a friction type) → None.

**Pitfall:** this test would have passed against the OLD buggy code if you build
the fixture with a `probability` key. Build the fixture using the **schema
field name** (`probability_inputs`) so the test fails before the fix and passes
after — verify that ordering explicitly.

### 1.2 Fix CAGR exception panel gate (dead code)

**The bug** — `scanner.py:96-98`:

```python
base_assumptions = analysis.get("base_case_assumptions", {})
cagr = base_assumptions.get("cagr_pct", 0.0)    # BUG: field doesn't exist here
if 20.0 <= cagr < 30.0:
```

Schema-verified: `base_case_assumptions` contains **only**
`revenue_b, fcf_margin_pct, multiple, shares_m, years, discount_path`. There is
no `cagr_pct` — CAGR is a *computed* value produced downstream in `pipeline.py:207`
(`implied_cagr = cagr_pct(current_price, target_price, years)`). So `cagr` is
always `0.0`, and the 3-agent unanimous-vote panel (`cagr_exception_panel` in
`hardening.py`) never executes. `hardening.py:364` (`_build_exception_prompt`) is
consequently unreachable dead code too.

**The fix (Option A — compute CAGR in place; use this one):** replicate the
pipeline's own math inside `_extract_hardening_flags` using the already-imported
`scoring` functions. Verified facts you need:

- `raw_candidate["current_price"]` **exists at this call site** — it is set
  top-level on the raw candidate by `fmp.py:558`, and `scanner.py:257` already
  reads `raw_candidate.get("current_price", 0.0)` elsewhere. `raw_candidate` is
  already a parameter of `_extract_hardening_flags`.
- Signatures (from `scoring.py`):
  `valuation_target_price(revenue_b, fcf_margin_pct, multiple, shares_m) -> float`
  and `cagr_pct(current_price, target_price, years) -> float`.
- `cagr_pct` **raises ValueError** if `current_price <= 0` or `years <= 0`, and
  `valuation_target_price` raises if `shares_m <= 0` — you MUST guard.

```python
from .scoring import cagr_pct as compute_cagr_pct, valuation_target_price

base_assumptions = analysis.get("base_case_assumptions", {})
current_price = raw_candidate.get("current_price", 0.0)
required = ("revenue_b", "fcf_margin_pct", "multiple", "shares_m", "years")
cagr = 0.0
if current_price > 0 and all(
    isinstance(base_assumptions.get(k), (int, float)) for k in required
):
    try:
        target = valuation_target_price(
            base_assumptions["revenue_b"],
            base_assumptions["fcf_margin_pct"],
            base_assumptions["multiple"],
            base_assumptions["shares_m"],
        )
        if target > 0 and base_assumptions["years"] > 0:
            cagr = compute_cagr_pct(current_price, target, base_assumptions["years"])
    except ValueError:
        cagr = 0.0   # unparseable assumptions → no exception-band routing
```

(Adjust import names to avoid clashing with the local variable `cagr`. If
`scoring` imports already exist in `scanner.py`, extend them.)

**The tests** (add to `tests/test_hardening_gates.py`):

1. Assumptions that compute to CAGR in [20, 30) — e.g. `current_price=10.0`,
   `revenue_b=1.0`, `fcf_margin_pct=20.0`, `multiple=15.0`, `shares_m=200.0`,
   `years=3` → target = (1.0 × 0.20 × 15 × 1000)/200 = 15.0 → CAGR ≈ 14.47 —
   **compute your fixture values with the actual functions first**, don't trust
   mental math; pick inputs that land inside the band. Mock all three transports
   with canned unanimous-approve JSON and assert `cagr_exception_panel` was
   invoked (e.g. transports called) and flags populated.
2. Unanimous "no" from the panel → assert the returned `status_override` routes
   to pending review (read `scanner.py:100-121` for the exact override string
   before asserting).
3. Boundary: CAGR ≈ 19.9 and ≈ 30.0 → panel NOT invoked.
4. Missing `current_price` (0.0) → no crash, panel not invoked.

**Also fix while here:** `hardening.py:432-438` does `parsed["approve"]` /
`parsed["reasoning"]` on `parse_llm_json` output — a malformed panel response
raises bare `KeyError` (swallowed by the broad `except Exception` at
`scanner.py:118-121`, defaulting to pending review — not a crash, but opaque).
Replace with `.get()` + an explicit raise naming the missing key, or pass an
`output_schema` like every other client in this repo does.

## Phase 2 — Fix data-correctness bugs

### 2.1 Sector screener cache-key collision

**The bug** — `cache.py:245` inside `cached_transport`:

```python
ticker = params.get("symbol", "UNKNOWN")
```

The stock screener (`fmp.py:130-135`) calls the `company-screener` endpoint with
`sector`, `exchange`, and filter params — **no `symbol`** — so every screener
call, for every sector/exchange/filter combination, reads and writes the single
cache entry `company-screener/UNKNOWN.json` with a 7-day TTL (`DEFAULT_TTLS`,
`cache.py:15-28`). Concrete failure: `sector-scan Technology` today, then
`sector-scan Healthcare` tomorrow → Healthcare silently receives Technology's
cached ticker list.

**Critical constraint discovered during review:** `FmpClient._get`
(`fmp.py:63`) injects the API key into params **before** the transport is
called: `self.transport(endpoint, {"apikey": self.api_key, **params})`. So the
cached transport's `params` dict CONTAINS `apikey`. The derived cache key must
**exclude `apikey`** — otherwise you (a) write a secret into a filename on disk
and (b) invalidate the whole cache on key rotation.

**The fix** — in `cached_transport._transport`, keep the `symbol` fast path,
otherwise derive a deterministic filesystem-safe key from all remaining params:

```python
import hashlib

def _cache_key(params: dict[str, str]) -> str:
    if "symbol" in params:
        return params["symbol"]
    material = "&".join(
        f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey"
    )
    if not material:
        return "NOPARAMS"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
```

Use it for both `cache_store.get(endpoint, key)` and `cache_store.set(...)`.
Check `cache.py`'s `get`/`set` for any assumption that the key looks like a
ticker (path building, sanitization) and adjust if needed.

**The tests** — new file `tests/test_cache_keying.py`, exercising
`cached_transport` **directly** (existing screener tests mock `FmpClient`
entirely and never touch this layer):

1. Two calls to endpoint `company-screener` with `{"apikey": "k", "sector": "Technology"}`
   vs `{"apikey": "k", "sector": "Healthcare"}` and an underlying fake transport
   that returns distinguishable payloads → second call must NOT return the first
   call's payload; two distinct cache files exist.
2. Same params twice → second call is a cache hit (`stats["hits"] == 1`) and the
   underlying transport was called once.
3. Same params but different `apikey` → still a cache hit (apikey excluded).
4. `symbol` param present → key is the plain symbol (backward compat: existing
   per-ticker cache entries stay valid).

**Cleanup:** delete any existing poisoned entries on disk:
`rm -f data/cache/company-screener/UNKNOWN.json data/cache/company-screener/UNKNOWN.meta.json`
(check actual filename pattern in `cache.py` first; `data/` is gitignored).

### 2.2 Exception-candidate routing bypasses hard gates

**The bug** — `pipeline.py:787-852`. The 20–29.9% CAGR exception branch
(`if exception_candidate: ... continue` around line 787-799) builds its
`pending_human_review` packet and `continue`s **before** three later hard gates
in the same loop:

- the `THESIS_BREAK_IMMINENT` hard gate (~line 804)
- the `effective_probability < 60.0` epistemic floor (~line 831)
- the `post_score.total_score < 45.0` watchlist floor (~line 852)

So a candidate in the exception band with `thesis_invalidation.imminent_break_flag
= True` and strong evidence is routed to human review instead of being rejected —
and the packet built at ~787-799 contains only `ticker`, `reason`,
`base_case_cagr_pct`, `effective_probability_pct`, `score`, so the reviewing
human **cannot see the thesis break**.

**The fix:**
1. Move the thesis-break hard-gate evaluation so it runs **before** the
   exception-candidate branch — a confirmed imminent break must hard-reject
   regardless of CAGR band. Read the existing gate block at ~804 carefully and
   relocate/reorder rather than duplicating logic (DRY).
2. Enrich the pending-review packet: include `thesis_invalidation`, `catalysts`,
   `key_risks` (copy the optional-key allowlist approach used by
   `_ranked_candidate_packet` at `pipeline.py:346-348`), plus explicit warning
   strings when `effective_probability < 60.0` or `post_score.total_score < 45.0`
   so the human sees the sub-floor numbers flagged, not raw.

**The tests** — new file `tests/test_pipeline_gate_ordering.py`, driving
`run_scan` (or the narrowest callable that contains this loop) with fixture
scan-inputs:

1. Candidate in exception band + `imminent_break_flag=True` with strong evidence
   → appears in rejections with the thesis-break reason, NOT in
   `pending_human_review`.
2. Candidate in exception band, no break → in `pending_human_review`, and the
   packet contains `thesis_invalidation`, `catalysts`, `key_risks` keys.
3. Candidate in exception band, no break, `effective_probability = 55` → packet
   contains a below-floor warning.

**⚠️ Interaction with Phase 3.2:** the old regression fixture
`exception_candidate_pending_human_review` expects `pending_human_review_count: 1`.
After this fix, regenerate fixtures so expectations match the corrected behavior
(this is why Phase 3.2 comes after Phase 2).

### 2.3 Negative-FCF-margin crash in scoring

**The bug** — `scoring.py:51-63`. `scan-input.schema.json` places no lower bound
on `fcf_margin_pct`, so a negative base-case margin (plausible for a
still-losing-money turnaround) yields a negative `target_price`;
`cagr_pct` then computes `(negative) ** (1/years)`, which in Python produces a
**complex number**, and `round2()` raises
`TypeError: type complex doesn't define __round__ method` — an unhandled,
cryptic crash far from the bad input.

**The fix:** in `cagr_pct`, add
`if target_price <= 0: raise ValueError("target_price must be positive")` —
mirroring the existing guards for `current_price` and `years`. Then check every
caller of `cagr_pct` (pipeline.py:207 and the Phase 1.2 code you just wrote)
handles/propagates `ValueError` with a per-candidate rejection rather than a
whole-scan crash — see how `pipeline.py` handles `_as_float` failures for the
established per-candidate error pattern.

**The tests:** covered by Phase 3.1's scoring suite (explicit case there).

## Phase 3 — Restore the verification layer

### 3.1 Unit tests for `scoring.py` (zero coverage today)

`scoring.py` (189 lines) holds ALL financial math driving buy/sell/size
decisions and is imported by no test. All functions are pure — this is
mechanical, high-value work. New file `tests/test_scoring.py`; cover every
public function:

- `valuation_target_price` — formula is `(revenue_b × margin% × multiple × 1000) / shares_m`;
  golden case: (1.0, 20.0, 15.0, 200.0) → 15.0. `shares_m <= 0` → ValueError.
- `cagr_pct` — golden case: (10.0, 15.0, 3) → 14.47. Guards: `current_price <= 0`,
  `years <= 0`, and (after 2.3) `target_price <= 0` → ValueError.
- `floor_price` — same as valuation_target_price (aliased).
- `downside_pct` — including the documented `floor_value <= 0 → 100.0` behavior
  (verify by reading `scoring.py:70-76` before asserting).
- `adjusted_downside_pct` — golden values from `assets/methodology/scoring-formulas.md`:
  30% → 34.5, 60% → 78 (hand-verified at review time).
- `decision_score` / `ScoreBreakdown` — verify weights against
  `scoring-formulas.md`; note the review found `risk_component` can go negative
  for near-100% downside (adjusted 150 → component −22.5): assert current
  behavior with a comment that it only affects already-rejected candidates.
- `score_to_size_band`, `confidence_cap_band` — band-edge cases (exactly on each
  threshold).
- `normalize_probability_band` — **document the midpoint tie-break**: raw 65 is
  equidistant between 60 and 70 and resolves to the LOWER band (tuple ordering
  in the `min()` key). Assert 55/65/75 explicitly so any future change is
  deliberate, with a comment noting this is an implicit policy choice.
- `epistemic_outcome`, `_raw_confidence_from_grades` — the 3-tier
  STRONG/MODERATE/WEAK scheme: thresholds total ≥4.0→5, ≥3.0→4, ≥2.5→3, ≥1.5→2,
  else 1 (`scoring.py:127-149`). Test each threshold boundary.

**Rule:** where the doc and code disagree (see Phase 4, PCS section), assert
CODE behavior and fix the DOC — do not "fix" the code to match the stale doc.

### 3.2 Regenerate regression fixtures — make CI green

**History:** commit `a8407ce` (2026-03-13) deleted `assets/fixtures/regression/`
entirely ("Remove legacy test suite and fixtures pending rewrite" — the rewrite
never happened). `validate_assets()` (`validation.py:92-97`) and
`run_regression_suite()` (`regression.py:33`) both `load_json(fixtures_root() /
"manifest.json")` via `assets.py:19-20` and crash with FileNotFoundError.
`.github/workflows/ci.yml:29-33` runs both on every push → **every CI run since
mid-March is red** (verified via `gh run list`).

**Recover the old fixture shapes from git** (they define the expected manifest
format — `regression.py` still expects this exact shape):

```bash
git show a8407ce^:assets/fixtures/regression/manifest.json
git show a8407ce^:assets/fixtures/regression/2026-03-07-cps-aap-dorm-pypl-scan-report-v5.json > /tmp/old-report.json
git show a8407ce^:assets/fixtures/regression/pending-human-review-exception.json > /tmp/old-exception.json
```

The old manifest had two fixtures, each with `id`, `path` (a scan-report JSON),
and `expectations` (`required_categories`, `ranked_candidates_count`,
`pending_human_review_count`, `screening_rejections`, `analysis_rejections`).

**Steps:**
1. Read `regression.py` (80 lines) end-to-end to confirm the manifest/report
   shapes it expects TODAY (the schema may have drifted since March — e.g. new
   screening checks were added in commits `5d1ac53`, `781032f`).
2. Diff the old fixture reports against the current
   `assets/methodology/scan-report.schema.json`; update field shapes as needed.
3. Regenerate fixture reports by running the CURRENT pipeline (post Phases 1–2)
   against small synthetic scan-inputs — do NOT hand-resurrect the old reports
   verbatim if the pipeline output shape has changed, and do NOT do this before
   Phase 2 lands (2.2 changes exception-candidate behavior that fixture #2
   encodes).
4. Write `assets/fixtures/regression/manifest.json` + fixture files.
5. Add `tests/test_regression_suite.py`: a smoke test that calls
   `run_regression_suite()` and `validate_assets()` directly so a future fixture
   deletion fails `unittest` too, not just CI (zero tests referenced either
   function at review time — that's how this stayed invisible).
6. Verify all three CI commands pass locally, then (only when John asks to push)
   confirm the GitHub Actions run goes green.

### 3.3 Coverage for remaining untested modules (second pass, lower priority)

Modules with zero test references at review time: `pipeline.py` (1,101 lines —
scan core), `holding_review.py` (sell triggers, replacement gate — money-touching),
`importers.py`, `reporting.py`, `live_scan.py`, `review_package.py`, `schemas.py`,
`judge.py`, `llm_transport.py`, `cli.py`, `regression.py`.

Priority order: `pipeline.py` (Phase 2.2's tests start this — extend to screening
verdicts and rejection packets), `holding_review.py`, `schemas.py` (see 3.4),
`importers.py`. The rest as opportunity allows. Don't block CI-green on this
phase.

### 3.4 `schemas.py`: honor `additionalProperties: false`

**The bug:** the hand-rolled validator (`validate_instance` /
`validate_all_errors` in `schemas.py`) implements `type`, `const`, `enum`,
`minimum`/`maximum`, `minLength`, `minItems`, `items`, `required`, `properties` —
but silently ignores `additionalProperties`. Yet
`structured-analysis.schema.json:407,425` declares `"additionalProperties": false`
on `thesis_invalidation_condition` and `thesis_invalidation`. Consequence: a
typo like `imminent_break_flg` validates cleanly, and since `pipeline.py:804`'s
hard gate reads `imminent_break_flag`, the typo **silently disables the
thesis-break rejection**.

**The fix:** in the object-validation branch, after checking `properties`, if
`schema.get("additionalProperties") is False`, emit an error for any instance
key not in `properties`. Follow the existing error-message format in the file.

**The tests:** in a new `tests/test_schemas_validator.py`: an instance with an
unknown key inside `thesis_invalidation` fails validation with a message naming
the key; a clean instance still passes; schemas WITHOUT `additionalProperties`
still allow extra keys (don't accidentally make it strict globally — that will
break other fixtures).

## Phase 4 — Documentation reconciliation (one sitting)

The docs describe the pre-rewrite (pre-March) world. Fix each:

- **CLAUDE.md**
  - Lines ~20-23: example commands reference `tests.test_fmp` /
    `tests.test_fmp.TestFmpAdapter.test_quote_parsing` — that file was deleted in
    `a8407ce`. Point at a real surviving test, e.g.
    `python -m unittest tests.test_screening_determinism -v`.
  - "Test fixtures" section lists `tests/fixtures/fmp|gemini|raw|generated|
    analyst|reviewer|validator|sector/` — only `tests/fixtures/gemini/`
    survives (one file, `golden_prompt_v2.txt`). Rewrite to match reality
    (including whatever Phase 3.2 adds back).
  - "Code Research" section mandates `graphify-out/GRAPH_REPORT.md` + `/graphify`
    — `graphify-out/` does not exist. Either regenerate the graph or delete the
    section. (If unsure, delete — a doc pointing at missing tooling is worse
    than no doc.)
  - CLAUDE.md says no `PYTHONPATH=src` needed (editable install) but
    `.github/workflows/ci.yml` prefixes every command with `PYTHONPATH=src`.
    Preferred fix: make CI do `pip install -e .` and drop the prefixes, matching
    the documented workflow.
- **README.md** — says `ANALYST_MODEL` defaults to `claude-sonnet-4-5-20250514`;
  ground truth is `config.py:19` = `claude-haiku-4-5-20251001`. Fix README.
- **`assets/methodology/scoring-formulas.md`** — the PCS confidence section
  documents a binary Yes/No 5-question model with confidence mapped by "No"
  count. The CODE (`scoring.py:127-149`) uses a 3-tier STRONG/MODERATE/WEAK
  grading with thresholds total ≥4.0→5, ≥3.0→4, ≥2.5→3, ≥1.5→2, else 1. The
  3-tier scheme is the intentional one (it matches the enum in
  `assets/contracts/epistemic_review.json:37` and `VALID_ANSWERS` in
  `pipeline.py:37`) — **update the DOC to describe the 3-tier scheme; do not
  change the code.** This is the one sanctioned exception to "methodology file
  wins": the doc is provably the stale artifact here.
- **`.planning/STATE.md`** — last updated 2026-03-10, says "completed, no
  blockers" — one day before the commit that broke CI. Update it to reference
  this plan and the actual state.
- **`assets/contracts/epistemic_review.json`** — claims the reviewer "never sees
  the analyst's probability or score." Reality (`epistemic_reviewer.py`): the
  allowlist excludes score/probability FIELDS, but analyst-authored freeform
  text (`thesis_summary`, `catalysts`, `key_risks`) crosses the barrier
  unscrubbed and can carry quantitative language. Reword to "structured
  probability/score fields are excluded" (a shape guarantee, not a content
  guarantee), or implement text scrubbing if John wants the stronger claim.

## Phase 5 — Decisions needed (ASK JOHN before implementing; do not choose silently)

### 5.1 Step 5b risk-enrichment demotion: implement or remove

The dangling pieces: `strategy-rules.md:177-201` designs a 10-K-driven demotion
protocol; `canonical-rulebook.json` contains rule ID `risk_enrichment_demotion`
(required to exist by `validation.py:45`); `pipeline.py:890` sorts ranked
candidates on `item["risk_enrichment"].get("demotion_trigger")`. But **no code
path ever populates a `risk_enrichment` key** (verified: not in
`_ranked_candidate_packet`'s allowlist at `pipeline.py:346-348`, not in any
schema, not written anywhere in `src/`). The sort key can never fire.

- **(a) Implement:** 10-K risk ingestion → schema field → analyst prompt →
  `_ranked_candidate_packet` → demotion sort. Multi-day project.
- **(b) Remove:** delete the dead sort key at `pipeline.py:890`; mark the rule
  "designed, not implemented" in `canonical-rulebook.json` and
  `strategy-rules.md` (keep `validation.py` happy — check what it asserts about
  the rule ID before editing).

Present both to John; (b) is an hour, (a) is a project.

### 5.2 Stage 3 synthesis: add output schema

`analyst.py:1075-1086` — Stage 3 (Synthesis) passes `schema=None`
("No output_schema — prompt-based JSON"), while Stages 1–2 use constrained
decoding. Stage 3 receives the full raw candidate including Gemini's
web-grounded free text (`claim`, `source_title`, `confidence_note` — live
Google-search-derived, attacker-influenceable, serialized verbatim into the
prompt via `json.dumps`), making it simultaneously the most
injection-exposed stage and the only structurally unconstrained one.

Investigate whether the constrained-decoding path used for Stages 1–2 can
express Stage 3's output shape (read `_run_stage`/stage-1-2 call sites in
`analyst.py` for how `output_schema` is passed; the earlier comment suggests a
prior limitation — verify whether it still holds against the current Claude
API). If constrained decoding fits, wire it. If not, minimum bar: validate
Stage 3's parsed output against the relevant sections of
`structured-analysis.schema.json` via `schemas.py` before accepting it, and
reject/retry on failure (the retry loop already exists in `automation.py`).

## Phase 6 — Hygiene sweep (15 minutes)

- [ ] **Plaintext `.env` on disk** violates the README's own encrypted-env
      policy ("API keys are never stored as plaintext on disk"; the sanctioned
      path is `.env.age` + `scripts/setup-age.sh`). It is gitignored and has
      never been committed (verified across full history) — local exposure only.
      **Before deleting:** confirm `.env.age` decrypts and `config.py`'s
      resolution chain (env > `.env.age` > `.env`) actually works without `.env`,
      THEN `rm .env`. Note: `.env` contains a `MASSIVE_API_KEY` that appears in
      neither `.env.example` nor any doc — grep `src/` for it; if unused, drop
      it; if used, add to `.env.example` and README.
- [ ] Delete tracked empty files: `docs/debug.txt` (0 bytes) and the empty
      `plan/` directory (`git rm`).
- [ ] Optional, do last: parallelize `sector.py:_hydrate_sub_sector` — 11
      Gemini category calls run strictly sequentially with `time.sleep(2)`
      between each; they're independent (`ThreadPoolExecutor`, keep the existing
      per-call retry/backoff). Efficiency only; skip if time-boxed.

---

## Acceptance criteria (definition of done)

1. `python -m unittest discover -s tests` passes, including NEW tests:
   `test_hardening_gates.py`, `test_cache_keying.py`,
   `test_pipeline_gate_ordering.py`, `test_scoring.py`,
   `test_schemas_validator.py`, `test_regression_suite.py`.
2. `validate-assets` and `run-regression` run clean locally.
3. GitHub Actions CI is **green** (only after John approves a push).
4. Each Phase-1 test demonstrably FAILED against the pre-fix code (run them
   before applying the fix; this proves they test the right thing).
5. No doc names a file, fixture, command, or default that doesn't exist.
6. Phase 5 decisions were presented to John, not made unilaterally.

## Suggested working order

Phase 1 → 2 → 3.1 → 3.2 (CI green here) → 3.4 → 4 → 5 (ask John) → 3.3 → 6.
Phases 1–3.2 are roughly one focused day and restore the project to matching
its own design intent.
