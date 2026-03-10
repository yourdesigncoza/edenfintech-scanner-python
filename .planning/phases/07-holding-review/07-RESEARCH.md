# Phase 7: Holding Review - Research

**Researched:** 2026-03-10
**Domain:** Post-purchase monitoring and sell-trigger evaluation within existing deterministic pipeline
**Confidence:** HIGH

## Summary

Phase 7 implements a holding review system that reuses the existing valuation math in `scoring.py` and FMP data retrieval in `fmp.py` to evaluate existing holdings against the Codex methodology's sell rules. The core work is building a new `holding_review.py` module that takes an existing holding's original valuation inputs, fetches the current price from FMP, recomputes forward CAGR, evaluates thesis integrity against stored `invalidation_triggers`, checks the 3 sell triggers from strategy-rules.md Step 8, and computes replacement gates.

All necessary financial math primitives already exist: `valuation_target_price()`, `cagr_pct()`, `floor_price()`, `downside_pct()`, `decision_score()`, and `score_to_size_band()` in `scoring.py`. The FMP adapter already supports `quote()` for current price retrieval with caching (1d TTL). The structured analysis schema already includes `invalidation_triggers[]` with `{trigger, evidence}` shape and `base_case_assumptions` / `worst_case_assumptions` with all 4 valuation inputs.

**Primary recommendation:** Build a self-contained `holding_review.py` module with pure functions that accept holding data + current price, plus a thin CLI command `review-holding` that orchestrates FMP price fetch and calls the review functions. No new schemas or external dependencies needed -- everything builds on existing infrastructure.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| HOLD-01 | Forward return refresh -- recompute target price and forward CAGR from current price + original valuation inputs | `scoring.py` already has `valuation_target_price()` and `cagr_pct()` -- reuse directly with current_price from FMP `quote()` |
| HOLD-02 | Thesis integrity checklist -- improved/degraded/unchanged/invalidated matched against invalidation_triggers | Structured analysis schema has `invalidation_triggers[]` with `{trigger, evidence}` -- compare against current evidence from Gemini grounded search |
| HOLD-03 | Sell trigger evaluation -- 3 triggers from strategy-rules.md Step 8 | Strategy rules define: (1) target reached + forward <30%, (2) rapid rerating + forward <10-15%/yr, (3) thesis break. All computable from forward CAGR + thesis checklist |
| HOLD-04 | Replacement gate computation -- Gate A: CAGR delta >15pp; Gate B: downside equal or better | Both gates use `cagr_pct()` and `downside_pct()` from scoring.py -- compare holding forward CAGR against replacement candidate CAGR |
| HOLD-05 | Fresh-capital vs legacy weight tracking | `score_to_size_band()` already maps score to weight band -- compute fresh_capital_max_weight from current score, compare against actual current_weight |
| HOLD-06 | CLI command `review-holding TICKER [TICKER...]` | Follow existing CLI pattern in `cli.py` using argparse subcommand + `_cmd_` handler function |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scoring.py | existing | valuation_target_price, cagr_pct, floor_price, downside_pct, decision_score, score_to_size_band | Already implements all Codex valuation math |
| fmp.py | existing | FmpClient.quote() for current price | Already cached with 1d TTL |
| structured_analysis.py | existing | Holding's original valuation inputs source | Contains base_case_assumptions, worst_case_assumptions, invalidation_triggers |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| gemini.py | existing | Grounded search for thesis integrity evidence | When checking invalidation_triggers against current news |
| pipeline.py | existing | _base_case_details, _worst_case_details patterns | Reference for valuation input extraction |

### Alternatives Considered
None -- all building blocks exist in the codebase.

## Architecture Patterns

### Recommended Project Structure
```
src/edenfintech_scanner_bootstrap/
    holding_review.py          # New module -- core holding review logic
    cli.py                     # Add review-holding subcommand
```

### Pattern 1: Holding Review Input Shape
**What:** A dataclass or dict defining what we need per holding
**When to use:** Every review-holding call

The holding review needs these inputs per ticker:
```python
# From the original scan report or structured analysis:
holding_input = {
    "ticker": "ABC",
    "purchase_price": 25.0,             # Original entry price
    "current_weight_pct": 8.5,          # Actual current portfolio weight
    "base_case_assumptions": {           # From original analysis
        "revenue_b": 3.0,
        "fcf_margin_pct": 10.0,
        "multiple": 24.0,
        "shares_m": 120.0,
        "years": 3.0,                   # Original time horizon
    },
    "worst_case_assumptions": {          # From original analysis
        "revenue_b": 2.4,
        "fcf_margin_pct": 8.0,
        "multiple": 12.0,
        "shares_m": 120.0,
    },
    "invalidation_triggers": [
        {"trigger": "Margin erosion resumes", "evidence": "Quarterly FCF margin below 5%"},
    ],
    "dominant_risk_type": "Operational/Financial",
    "probability_inputs": {
        "base_probability_pct": 70.0,
    },
}
```

### Pattern 2: Forward Return Refresh (HOLD-01)
**What:** Recompute target price using original valuation inputs, then compute forward CAGR from current (live) price
**When to use:** Every holding review

```python
from .scoring import valuation_target_price, cagr_pct

def forward_return_refresh(
    base_case: dict,
    current_price: float,
    years_remaining: float,
) -> dict:
    target_price = valuation_target_price(
        base_case["revenue_b"],
        base_case["fcf_margin_pct"],
        base_case["multiple"],
        base_case["shares_m"],
    )
    forward_cagr = cagr_pct(current_price, target_price, years_remaining)
    return {
        "target_price": target_price,
        "current_price": current_price,
        "forward_cagr_pct": forward_cagr,
        "years_remaining": years_remaining,
    }
```

Key design decision: `years_remaining` should be derived from original years minus elapsed time. The caller computes this from original scan_date + years horizon.

### Pattern 3: Thesis Integrity Checklist (HOLD-02)
**What:** Structured assessment of each invalidation trigger
**When to use:** Every holding review

```python
THESIS_STATUSES = {"IMPROVED", "DEGRADED", "UNCHANGED", "INVALIDATED"}

def thesis_integrity_check(
    invalidation_triggers: list[dict],
    current_evidence: list[dict],
) -> dict:
    assessments = []
    overall_status = "UNCHANGED"
    for trigger in invalidation_triggers:
        # Match current evidence against each trigger
        assessment = {
            "trigger": trigger["trigger"],
            "original_evidence": trigger["evidence"],
            "current_status": "UNCHANGED",  # or IMPROVED/DEGRADED/INVALIDATED
            "current_evidence": "",          # Filled by caller or Gemini lookup
        }
        assessments.append(assessment)
    # Worst status wins for overall
    return {
        "overall_status": overall_status,
        "assessments": assessments,
    }
```

### Pattern 4: Sell Trigger Evaluation (HOLD-03)
**What:** Evaluate the 3 sell triggers from strategy-rules.md Step 8
**When to use:** Every holding review, depends on forward_return_refresh + thesis_integrity_check

```python
SELL_TRIGGERS = {
    "TARGET_REACHED_LOW_FORWARD": {
        "description": "Target reached, forward returns < 30% hurdle",
        "threshold_cagr": 30.0,
    },
    "RAPID_RERATING_LOW_FORWARD": {
        "description": "Rapid move, forward returns < 10-15%/year",
        "threshold_cagr_low": 10.0,
        "threshold_cagr_high": 15.0,
    },
    "THESIS_BREAK": {
        "description": "Fundamental thesis break (business change, NOT price change)",
    },
}

def evaluate_sell_triggers(
    forward_refresh: dict,
    thesis_check: dict,
    purchase_price: float,
) -> list[dict]:
    fired = []
    current_price = forward_refresh["current_price"]
    target_price = forward_refresh["target_price"]
    forward_cagr = forward_refresh["forward_cagr_pct"]

    # Trigger 1: target reached + forward < 30%
    if current_price >= target_price and forward_cagr < 30.0:
        fired.append({
            "trigger": "TARGET_REACHED_LOW_FORWARD",
            "fired": True,
            "reason": f"Price ${current_price} >= target ${target_price}, forward CAGR {forward_cagr}% < 30%",
        })

    # Trigger 2: rapid rerating + forward < 10-15%/yr
    price_gain_pct = ((current_price - purchase_price) / purchase_price) * 100
    if price_gain_pct > 50.0 and forward_cagr < 15.0:
        fired.append({
            "trigger": "RAPID_RERATING_LOW_FORWARD",
            "fired": True,
            "reason": f"Price up {price_gain_pct:.1f}% from entry, forward CAGR {forward_cagr}% < 15%",
        })

    # Trigger 3: thesis break
    if thesis_check["overall_status"] == "INVALIDATED":
        fired.append({
            "trigger": "THESIS_BREAK",
            "fired": True,
            "reason": "One or more invalidation triggers have been confirmed",
        })

    return fired
```

### Pattern 5: Replacement Gate (HOLD-04)
**What:** Two-gate test for whether a replacement candidate justifies selling current holding
**When to use:** When a replacement candidate exists (optional input)

```python
def replacement_gate(
    holding_forward_cagr: float,
    holding_downside_pct: float,
    replacement_forward_cagr: float,
    replacement_downside_pct: float,
) -> dict:
    cagr_delta = replacement_forward_cagr - holding_forward_cagr
    gate_a = cagr_delta > 15.0  # >15pp CAGR advantage
    gate_b = replacement_downside_pct <= holding_downside_pct  # Equal or better downside

    return {
        "gate_a_cagr_delta": {
            "holding_cagr": holding_forward_cagr,
            "replacement_cagr": replacement_forward_cagr,
            "delta_pp": round(cagr_delta, 2),
            "passed": gate_a,
        },
        "gate_b_downside": {
            "holding_downside": holding_downside_pct,
            "replacement_downside": replacement_downside_pct,
            "passed": gate_b,
        },
        "replacement_justified": gate_a and gate_b,
    }
```

### Pattern 6: Fresh Capital vs Legacy Weight (HOLD-05)
**What:** Compare actual current_weight against what fresh-capital scoring would give
**When to use:** Every holding review

```python
from .scoring import decision_score, score_to_size_band, downside_pct, floor_price

def fresh_capital_weight(
    forward_cagr: float,
    worst_case: dict,
    current_price: float,
    effective_probability: float,
) -> dict:
    floor_val = floor_price(
        worst_case["revenue_b"],
        worst_case["fcf_margin_pct"],
        worst_case["multiple"],
        worst_case["shares_m"],
    )
    downside = downside_pct(current_price, floor_val)
    score = decision_score(downside, effective_probability, forward_cagr)
    band = score_to_size_band(score.total_score)
    return {
        "fresh_capital_max_weight": band,
        "score": score.total_score,
        "downside_pct": downside,
    }
```

### Anti-Patterns to Avoid
- **Do NOT re-fetch raw bundles:** Holding review uses original valuation inputs, not fresh analysis. Only current price is refreshed.
- **Do NOT re-run the full pipeline:** Holding review is a lightweight check, not a full scan. No screening, no cluster analysis.
- **Do NOT conflate "thesis integrity" with "price movement":** Strategy rules explicitly say price drops are NOT sell triggers. Only business changes count.
- **Do NOT make replacement gate mandatory:** It is optional -- only evaluated when a replacement candidate is provided.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Target price calculation | Custom valuation math | `scoring.valuation_target_price()` | Already tested, matches Codex formula exactly |
| CAGR computation | Custom compound growth calc | `scoring.cagr_pct()` | Edge cases handled (zero/negative prices) |
| Floor price / downside | Custom floor calc | `scoring.floor_price()`, `scoring.downside_pct()` | Already tested with trough anchoring |
| Position sizing | Custom weight rules | `scoring.decision_score()` + `scoring.score_to_size_band()` | Hard breakpoints match strategy-rules.md |
| Current price fetch | Direct HTTP calls | `fmp.FmpClient.quote()` with cache | Already cached at 1d TTL |

**Key insight:** Every financial calculation in holding review already exists in scoring.py. The new module is orchestration logic, not math.

## Common Pitfalls

### Pitfall 1: Years Remaining Miscalculation
**What goes wrong:** Using original `years` instead of `years - elapsed` for forward CAGR
**Why it happens:** The original base_case has `years: 3.0` set at scan time. If 1 year has passed, forward CAGR should use 2.0 years remaining.
**How to avoid:** Compute elapsed from original scan_date to today. Pass `max(years - elapsed, 0.25)` as years_remaining (floor at ~3 months to avoid division-by-zero-like distortions).
**Warning signs:** Forward CAGR suspiciously matches original CAGR despite price change.

### Pitfall 2: Rapid Rerating Threshold Ambiguity
**What goes wrong:** The strategy rules say "forward returns < 10-15%/year" -- is it 10% or 15%?
**Why it happens:** The range is intentionally discretionary in the methodology.
**How to avoid:** Use 15% as the programmatic threshold (conservative side = fewer false sell signals). Document that the range is 10-15% and the operator may choose to sell at 10% based on judgment.
**Warning signs:** Sell trigger fires too aggressively (10%) or too rarely (15%).

### Pitfall 3: Confusing Price Movement with Thesis Break
**What goes wrong:** Marking thesis as DEGRADED because stock price dropped further.
**Why it happens:** Natural tendency to interpret price as information.
**How to avoid:** Thesis integrity check must ONLY evaluate business fundamentals -- `invalidation_triggers` are phrased as business conditions, not price conditions. The function must not receive price data.
**Warning signs:** Thesis status changes correlate with price direction.

### Pitfall 4: Replacement Gate Without Full Analysis
**What goes wrong:** Computing replacement gate against a candidate that hasn't been fully analyzed.
**Why it happens:** Temptation to compare against any recent scan candidate.
**How to avoid:** Replacement candidate must come from a ranked scan result (Phase 6 auto-scan or existing report). The replacement's forward CAGR and downside must be from a validated pipeline run.
**Warning signs:** Replacement candidate lacks epistemic review or validated scoring.

### Pitfall 5: Holding Data Source Ambiguity
**What goes wrong:** Unclear where the holding's original valuation inputs come from at runtime.
**Why it happens:** The system doesn't currently persist "bought holdings" -- scan reports are point-in-time.
**How to avoid:** Define a `holdings.json` manifest file format that stores per-holding: ticker, purchase_price, purchase_date, scan_date (of the analysis), original base_case/worst_case/probability/invalidation_triggers, current_weight_pct. CLI reads from this file.
**Warning signs:** Users must manually construct holding data on every review.

## Code Examples

### Complete Holding Review Flow
```python
def review_holding(
    holding: dict,
    current_price: float,
    *,
    replacement_candidate: dict | None = None,
) -> dict:
    base_case = holding["base_case_assumptions"]
    worst_case = holding["worst_case_assumptions"]

    # HOLD-01: Forward return refresh
    years_remaining = holding.get("years_remaining", base_case["years"])
    refresh = forward_return_refresh(base_case, current_price, years_remaining)

    # HOLD-02: Thesis integrity
    thesis = thesis_integrity_check(
        holding["invalidation_triggers"],
        holding.get("current_evidence", []),
    )

    # HOLD-03: Sell triggers
    triggers = evaluate_sell_triggers(
        refresh, thesis, holding["purchase_price"],
    )

    # HOLD-05: Fresh capital weight
    fresh_weight = fresh_capital_weight(
        refresh["forward_cagr_pct"],
        worst_case,
        current_price,
        holding.get("effective_probability", 60.0),
    )

    result = {
        "ticker": holding["ticker"],
        "forward_refresh": refresh,
        "thesis_integrity": thesis,
        "sell_triggers": triggers,
        "sell_triggered": len(triggers) > 0,
        "fresh_capital_assessment": fresh_weight,
        "current_weight_pct": holding.get("current_weight_pct"),
    }

    # HOLD-04: Replacement gate (optional)
    if replacement_candidate is not None:
        result["replacement_gate"] = replacement_gate(
            refresh["forward_cagr_pct"],
            fresh_weight["downside_pct"],
            replacement_candidate["forward_cagr_pct"],
            replacement_candidate["downside_pct"],
        )

    return result
```

### CLI Pattern (Matching Existing Conventions)
```python
def _cmd_review_holding(
    tickers: list[str],
    holdings_path: str | None,
    json_out: str | None,
) -> int:
    config = load_config()
    from .fmp import _default_transport
    store = FmpCacheStore(_default_fmp_cache_dir())
    transport = cached_transport(_default_transport, store)
    # ... load holdings, fetch current prices, call review_holding per ticker
    return 0
```

### Holdings Manifest Format
```json
{
  "holdings": [
    {
      "ticker": "ABC",
      "purchase_price": 25.00,
      "purchase_date": "2025-06-15",
      "scan_date": "2025-06-10",
      "current_weight_pct": 8.5,
      "base_case_assumptions": {
        "revenue_b": 3.0,
        "fcf_margin_pct": 10.0,
        "multiple": 24.0,
        "shares_m": 120.0,
        "years": 3.0
      },
      "worst_case_assumptions": {
        "revenue_b": 2.4,
        "fcf_margin_pct": 8.0,
        "multiple": 12.0,
        "shares_m": 120.0
      },
      "probability_inputs": {
        "base_probability_pct": 70.0
      },
      "dominant_risk_type": "Operational/Financial",
      "invalidation_triggers": [
        {"trigger": "Margin erosion resumes", "evidence": "Quarterly FCF margin below 5%"}
      ]
    }
  ]
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual spreadsheet review | Deterministic pipeline scoring | Phase 1-5 | All math is now in scoring.py |
| Ad-hoc sell decisions | Structured 3-trigger framework | strategy-rules.md | Codex methodology defines exact sell rules |
| No position sizing refresh | Score-to-band mapping | Phase 1 | score_to_size_band() gives fresh-capital weight |

**Deprecated/outdated:**
- None -- this is a new module building on stable foundations

## Open Questions

1. **Holding data persistence format**
   - What we know: Need to store original valuation inputs per holding somewhere
   - What's unclear: Should it live in `data/holdings/` (runtime) or be passed via CLI args?
   - Recommendation: Use `data/holdings/holdings.json` manifest -- auto-populated from scan reports when a position is taken, manually editable. Store alongside `data/cache/` and `data/sectors/`.

2. **Thesis integrity evidence source**
   - What we know: invalidation_triggers define what to check, but current evidence needs to come from somewhere
   - What's unclear: Should thesis integrity check automatically fetch current evidence via Gemini, or should evidence be pre-provided?
   - Recommendation: For v1, thesis integrity check accepts pre-provided evidence (manual or from a Gemini call). A `--refresh-evidence` flag could optionally trigger Gemini grounded search. This keeps the core function deterministic.

3. **Rapid rerating definition**
   - What we know: Strategy says "rapid move" but doesn't define a threshold
   - What's unclear: What constitutes "rapid" -- 50% gain? 80%? Any gain above entry?
   - Recommendation: Use >50% gain from purchase_price as "rapid move" threshold. This is aggressive enough to catch meaningful re-ratings while avoiding false triggers on small moves. Make it configurable.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | unittest (stdlib) |
| Config file | none -- uses `python -m unittest discover` |
| Quick run command | `python -m unittest tests.test_holding_review -v` |
| Full suite command | `python -m unittest discover -s tests -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HOLD-01 | Forward CAGR recomputed from current price + original inputs | unit | `python -m unittest tests.test_holding_review.TestForwardRefresh -v` | Wave 0 |
| HOLD-02 | Thesis integrity produces structured assessment per invalidation_trigger | unit | `python -m unittest tests.test_holding_review.TestThesisIntegrity -v` | Wave 0 |
| HOLD-03 | Three sell triggers fire correctly under specified conditions | unit | `python -m unittest tests.test_holding_review.TestSellTriggers -v` | Wave 0 |
| HOLD-04 | Replacement gate computes Gate A (>15pp) and Gate B (downside) | unit | `python -m unittest tests.test_holding_review.TestReplacementGate -v` | Wave 0 |
| HOLD-05 | fresh_capital_max_weight computed alongside current_weight | unit | `python -m unittest tests.test_holding_review.TestFreshCapitalWeight -v` | Wave 0 |
| HOLD-06 | CLI review-holding parses args and produces JSON output | unit | `python -m unittest tests.test_holding_review.TestCLI -v` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m unittest tests.test_holding_review -v`
- **Per wave merge:** `python -m unittest discover -s tests -v`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_holding_review.py` -- covers HOLD-01 through HOLD-06
- [ ] No framework install needed -- uses stdlib unittest

## Sources

### Primary (HIGH confidence)
- `src/edenfintech_scanner_bootstrap/scoring.py` -- all valuation math functions verified in source
- `src/edenfintech_scanner_bootstrap/pipeline.py` -- _base_case_details and _worst_case_details patterns verified
- `assets/methodology/strategy-rules.md` -- Step 8 sell triggers and Step 5 valuation formula verified
- `assets/methodology/structured-analysis.schema.json` -- invalidation_triggers and base_case_assumptions shape verified
- `src/edenfintech_scanner_bootstrap/cli.py` -- CLI pattern verified (argparse subcommands + _cmd_ handlers)
- `src/edenfintech_scanner_bootstrap/fmp.py` -- FmpClient.quote() for current price verified

### Secondary (MEDIUM confidence)
- Holding data persistence pattern -- inferred from data/cache/ and data/sectors/ conventions

### Tertiary (LOW confidence)
- "Rapid rerating" threshold (50% gain) -- not defined in strategy-rules.md, needs operator confirmation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all building blocks exist and are tested
- Architecture: HIGH -- follows existing module patterns (single new file + CLI addition)
- Pitfalls: HIGH -- derived from codebase analysis and methodology rules
- Sell trigger thresholds: MEDIUM -- "10-15%" range and "rapid" are intentionally discretionary in methodology

**Research date:** 2026-03-10
**Valid until:** 2026-04-10 (stable -- all dependencies are internal)
