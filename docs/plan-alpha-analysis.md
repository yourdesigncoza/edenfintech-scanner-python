# Plan ALPHA — LLM-Integrated Pipeline Analysis

Comparison of the proposed autonomous Python scanner ("Plan ALPHA") against the existing
Claude Code multi-agent scanner (`edenfintech-scanner`), with architectural recommendations.

---

## 1. Current Python Scanner (`edenfintech-scanner-python`)

A **deterministic, stage-gated pipeline** with human review gates:

- **Data retrieval**: FMP (quantitative) + Gemini (qualitative) adapters fetch raw bundles
- **Structured analysis overlay**: Machine-generated draft with `__REQUIRED__` placeholders and per-field provenance (`MACHINE_DRAFT` → `HUMAN_CONFIRMED`/`HUMAN_EDITED`)
- **Finalization gate**: All placeholders must be replaced, all fields need explicit `review_note`, reviewer identity recorded
- **Deterministic pipeline**: screening (5 checks) → cluster analysis → epistemic review → report assembly
- **Judge**: Optional OpenAI Codex judge for methodology compliance, with deterministic `local_judge` fallback
- **20% CAGR exception**: Hard-blocked for LLMs — routed to "Pending Human Review"

### Human Gates (4 total)

| Gate | Location | What human does |
|------|----------|-----------------|
| Structured analysis review | `structured_analysis.py` | Replace placeholders, write review_notes, confirm/edit fields |
| Finalization | `finalize_structured_analysis()` | Trigger promotion from DRAFT → FINALIZED |
| 20% CAGR exception | `pipeline.py` report assembly | Approve or reject exception candidates |
| Review package two-pass | `review_package.py` | First pass generates drafts; human reviews; second pass runs pipeline |

---

## 2. Original Scanner (`edenfintech-scanner`)

A **native Claude Code multi-agent pipeline** where LLMs already ARE the decision makers:

### Agent Architecture

```
/scan-stocks skill (entry point)
    → orchestrator agent (coordinator, has Task tool)
        → screener agent (Phase 1: quantitative filtering, Steps 1-2)
        → analyst agents (Phase 2: Steps 3-6, one per industry cluster, parallel)
        → epistemic reviewer agent (independent confidence assessment)
    → final ranked report saved to disk
```

### Agent Roles

| Agent | Tools | What it decides |
|-------|-------|-----------------|
| **Screener** | Bash, Read, FMP script, WebSearch | Applies broken-chart detection, industry exclusions, 5-check filter. Makes pass/fail judgments on each check. |
| **Analyst** (per cluster) | Bash, Read, FMP script, Gemini search, WebSearch | Competitor comparison, moat assessment, catalyst identification, valuation model (4-input formula), decision scoring, structural diagnosis |
| **Epistemic Reviewer** | Bash, Read, Gemini search, WebSearch | Answers 5 PCS questions independently. Never sees analyst probability or score. Evidence-anchored (must cite source or declare NO_EVIDENCE). |
| **Orchestrator** | All + Task tool | Dispatches agents, applies risk-type friction, runs `calc-score.sh` (deterministic), performs 6+ compliance audits, compiles report |
| **Sector Researcher** | Bash, Read, Gemini/Perplexity | 8 research queries per sub-sector, produces per-industry knowledge files |

### Key Design Patterns

1. **Epistemic independence**: The reviewer is architecturally blind to the analyst's probability and score — different information set, not just different model.

2. **Deterministic math externalization**: All scoring math lives in `calc-score.sh` (bash). LLMs make qualitative judgments; math is never LLM-generated.

3. **6+ orchestrator compliance audits**:
   - Step 3 ranking completeness (cluster ranking record, quality ordering, enum purity)
   - Step 4 catalyst quality (valid catalyst requirement, issues-fixes evidence, management evidence status)
   - Downside compliance (floor calc, Heroic Optimism, TBV cross-check, trough path, calibration rules)
   - Multiple consistency (median deviation flagging)
   - Probability band normalization
   - Threshold-hugging detection

4. **Evidence-anchored PCS**: Each epistemic answer must cite a specific source or declare `NO_EVIDENCE`. Prevents "PCS laundering" (rationalizing confidence from narrative quality).

5. **Risk-type friction table** with conditional overrides:

   | Risk Type | Default Friction | Override Condition | Overridden Friction |
   |-----------|------------------|--------------------|---------------------|
   | Operational/Financial | 0 | — | — |
   | Cyclical/Macro | -1 | Q3=Yes with named precedent | 0 |
   | Regulatory/Political | -2 | Q2=Yes (stable regulatory) | -1 |
   | Legal/Investigation | -2 | — (no override) | — |
   | Structural fragility (SPOF) | -1 | — (also sets binary flag) | — |

6. **Sector hydration**: Pre-scan knowledge loading via parallel researcher agents producing per-sub-sector files (metrics, valuation approaches, regulations, precedent tables, moat sources).

---

## 3. Plan ALPHA — Proposed LLM-Integrated Python Scanner

Replace the 4 human gates with LLM agents:

### Gate 1: Structured Analysis Review → Analyst LLM

An LLM agent that:
- Takes raw evidence context (FMP + Gemini bundles) and the draft template
- Fills every `__REQUIRED__` placeholder with reasoned values grounded in evidence
- Writes a `review_note` per field citing specific evidence refs
- Sets status to `LLM_CONFIRMED` or `LLM_EDITED` (new provenance statuses)

### Gate 2: Finalization → Validator LLM

A separate LLM agent (different model/provider) that:
- Cross-checks every filled field against evidence context and `strategy-rules.md`
- Flags contradictions (e.g., solvency marked PASS but debt/FCF ratio is 8x)
- Only approves finalization if no contradictions found
- Creates two-LLM consensus (Analyst fills, Validator verifies)

### Gate 3: 20% CAGR Exception

Two options:
- **Conservative**: Keep human-only (rare, high-stakes)
- **Aggressive**: Three-LLM panel vote (Analyst, Validator, Devil's Advocate). Unanimous agreement required. Full reasoning chain logged.

### Gate 4: Codex Final Judge (already partially LLM)

Enhancements:
- Make judge aware it's reviewing LLM-generated analysis (stricter scrutiny)
- Add `review_provenance_audit` — verify LLM_CONFIRMED fields cite real evidence refs
- Use different model/provider than Analyst to decorrelate errors

### Proposed Architecture

```
FMP + Gemini (data retrieval)
       │
       ▼
  Merged Raw Bundle
       │
       ▼
  ┌─────────────┐
  │ Analyst LLM  │  fills placeholders, writes review_notes
  └──────┬──────┘
         ▼
  ┌──────────────┐
  │ Validator LLM │  adversarial cross-check against evidence + rules
  └──────┬───────┘
         ▼
  Auto-finalization (if Validator approves)
         │
         ▼
  Deterministic Pipeline (screening → cluster → epistemic → report)
         │
         ▼
  ┌────────────┐
  │ Judge LLM   │  methodology compliance (existing, enhanced)
  └─────┬──────┘
        ▼
     Final Report
```

### Code Changes Required

| File | Change |
|------|--------|
| `structured_analysis.py` | Add `LLM_CONFIRMED`/`LLM_EDITED` statuses; new `llm_review_structured_analysis()` |
| New: `llm_analyst.py` | Analyst agent — prompt construction, structured output parsing, evidence grounding |
| New: `llm_validator.py` | Validator agent — adversarial review, contradiction detection |
| `judge.py` | Add provenance audit for LLM-generated fields |
| `review_package.py` | New single-pass flow: `build_automated_review_package()` |
| `cli.py` | New command: `auto-scan TICKER` (fully automated end-to-end) |
| `strategy-rules.md` | Document LLM agent roles, consensus requirements |
| `config.py` | New keys: `ANALYST_MODEL`, `VALIDATOR_MODEL` |

---

## 4. Comparison: Plan ALPHA vs. Original Scanner

### What Plan ALPHA reinvents (already solved in original)

| Capability | Original Scanner | Plan ALPHA |
|-----------|-----------------|------------|
| LLM-as-analyst | Claude agent does full qualitative analysis freely | Constrained: LLM fills structured JSON template fields |
| Epistemic independence | Architecturally blind reviewer (different info set) | "Validator LLM" cross-checks (weaker — same info set, different model) |
| Multi-agent orchestration | Parallel analyst agents per cluster via Task tool | Would rebuild in Python |
| Deterministic math | `calc-score.sh` (bash) | `scoring.py` (Python) — equivalent |
| Sector knowledge | `/sector-hydrate` with parallel researcher agents | Not addressed |

### What Plan ALPHA adds (original lacks)

| Capability | Plan ALPHA | Original Scanner |
|-----------|------------|-----------------|
| Per-field provenance tracking | JSON fingerprints, evidence refs per field | Implicit in agent transcripts |
| Schema-validated contracts | JSON Schema at every stage boundary | Prompt-level orchestrator audits |
| Reproducibility | Regression fixtures, deterministic replay | LLM outputs vary per run |
| Multi-provider decorrelation | Different LLM providers for Analyst vs. Validator | Same Claude model for all agents |
| Programmatic auditability | Machine-readable provenance chain | Human-readable agent logs |

### What the original does better

| Capability | Original | Plan ALPHA gap |
|-----------|----------|----------------|
| Orchestrator audits | 6+ distinct compliance checks (ranking completeness, enum purity, catalyst quality, downside compliance, heroic optimism, multiple consistency, TBV cross-check) | "Validator LLM" vaguely defined |
| Evidence-anchored epistemic | Each PCS answer must cite source or NO_EVIDENCE; prevents PCS laundering | Not specified |
| Risk-type friction | Proper friction table with conditional overrides | Not addressed |
| Sector hydration | 8 queries per sub-sector, pre-loaded before analysis | No equivalent |
| CAGR momentum gate | Early exit for borderline stocks (3 API calls vs. 20+) | Not addressed |
| Structural diagnosis | Driver/Filler/Watchlist role, upgrade triggers, kill triggers | Not addressed |
| Probability sensitivity tables | Score at each probability band (50/60/70/80%) | Not addressed |

---

## 5. Recommendation: Hybrid Architecture

Rather than implementing Plan ALPHA as described, the most efficient path is **porting the original scanner's proven agent patterns into the Python scanner's contract-enforced framework**.

### What to take from the original scanner:

1. **Epistemic reviewer agent pattern** — architecturally blind to scores, evidence-anchored PCS answers, NO_EVIDENCE declaration requirement
2. **Orchestrator compliance audits** — Step 3 ranking completeness, Step 4 catalyst quality, downside compliance, multiple consistency
3. **Risk-type friction with conditional overrides** — deterministic, not LLM-judged
4. **Sector hydration pipeline** — pre-scan knowledge loading
5. **CAGR momentum gate** — early exit for borderline stocks
6. **Structural diagnosis** — Driver/Filler/Watchlist classification

### What to keep from the Python scanner:

1. **Per-field provenance tracking** — stronger auditability than agent transcripts
2. **JSON Schema contracts** — machine-enforced stage boundaries
3. **Regression fixtures** — reproducibility guarantees
4. **Fingerprint continuity** — raw bundle traceability end-to-end
5. **Structured analysis overlay lifecycle** — DRAFT → reviewed → FINALIZED

### What to add new:

1. **Multi-provider decorrelation** — Analyst (e.g., Claude) vs. Validator (e.g., Gemini) to avoid correlated failure modes
2. **Single-pass automated flow** — `auto-scan TICKER` that chains retrieval → LLM analysis → LLM validation → finalization → pipeline → judge without stopping
3. **Explicit provenance status for LLM decisions** — `LLM_CONFIRMED`/`LLM_EDITED` distinct from `HUMAN_CONFIRMED`/`HUMAN_EDITED` for audit clarity
4. **20% CAGR exception panel** — three-LLM consensus or keep human (configurable)

### Critical Design Principle

**Never let the same LLM that generates analysis also validate it.** Use different models, different providers, or at minimum different system prompts with adversarial framing AND different information sets. The original scanner's epistemic reviewer pattern (architecturally blind to scores) is the gold standard — replicate this, don't weaken it.

---

## 6. Implementation Priority

If building the hybrid:

1. **Port epistemic reviewer** — highest value, already proven, well-defined contract
2. **Port orchestrator audits** — deterministic compliance checks translate directly to Python
3. **Build LLM analyst agent** — fills structured overlay from evidence context
4. **Build LLM validator agent** — adversarial cross-check (different provider)
5. **Wire single-pass flow** — `auto-scan` CLI command
6. **Port sector hydration** — pre-scan knowledge (optional but high-impact)

---

*Analysis produced 2026-03-10. Based on comparison of `edenfintech-scanner-python` (Python deterministic pipeline)
and `edenfintech-scanner` (Claude Code multi-agent pipeline).*
