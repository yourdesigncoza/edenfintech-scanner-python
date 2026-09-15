# Session notes — 15 September 2026

Strategy session. No code was changed. Read this, then `todo-structural-fixes.md`.

## Why this project matters again

It was shelved because no revenue stream was visible inside it. That was the
right read and the wrong frame. There isn't a clean one: retail signals hit FAIS,
selling picks means becoming a licensed advisor, running the book needs capital.

**The revenue is not what the scanner produces. It is what the scanner proves.**

This repo is a working, tested, adversarially-verified multi-agent system in a
domain where being wrong costs money. That is a credential almost nobody selling
AI work can match, and it points at a specific, well-funded niche.

## The commercial thesis

**Sell verified AI research pipelines to financial-services firms** — boutique
asset managers, family offices, research shops, fintechs.

Wedge: a fixed-fee production-readiness audit (about USD 2,000, one week),
converting to a remediation build then a retainer (USD 2,500–6,000/month).

Target: **one audit plus one retainer is roughly R50,000/month.** The gate was
always R50,000; the mistake was trying to extract it from South African buyers in
rands instead of international buyers in dollars. R50,000 is about USD 2,800.

FAIS is clear on this. Selling software engineering to firms that hold their own
licence is not advice and not an intermediary service. The blocked thing was
publishing signals to retail; that is not this.

### Why this niche and not generic AI automation

- Hallucination is a direct P&L cost for them, not a theoretical risk
- They already pay for verification, audit trails and controls — native language
- Reference implementation exists: ~11,900 lines, 152 passing tests, 27 real runs
- Domain fluency: their research process and financial models are readable to us
- The n8n crowd cannot serve it; governance platforms sell to enterprise
  procurement, not boutiques

### Market evidence gathered

- Deloitte 2026: 89% of AI agent pilots never reach production
- IDC: 88% of POCs never reach production — "for every 33 pilots, four graduate"
- MIT NANDA: 95% of GenAI pilots deliver no measurable P&L impact
- Gartner: >40% of agentic projects cancelled by 2027
- Sierra tau-bench: agent success ~60% single-run, ~25% over 8 consecutive runs
- AI automation retainers 2026: USD 1,200–3,800/mo solo, 2,500–6,000/mo for
  agent-integration work. Senior agent freelance USD 80–250/hr
- Governance-as-a-category is enterprise-only: SOC 2 / ISO 42001 as procurement
  gating conditions, competing with Cisco (acquired Galileo), Arize, Palo Alto.
  Do not position there.

## The sales artefact is already written

The 6 July review found **two of four hardening gates had never fired in
production**, CI red since 13 March, financial-math core untested, five feature
commits stacked on a broken verification layer.

That is the pitch: *"I built a governed multi-agent research system, then audited
it and found two of my four safety gates had never fired. Here's the method. Let
me run it on yours."* Self-critical, specific, true.

`todo-structural-fixes.md` is also the audit deliverable template — ordered
phases, verified file:line refs, failing-test-first, acceptance criteria. Do not
redesign it. Run it on someone else's system.

## Next actions, in order

1. **Finish `todo-structural-fixes.md` phases 1 → 3.2** (CI green). Roughly one
   focused day, per its own estimate. Now commercially load-bearing: production
   safety cannot be sold with two dead gates in the flagship.
2. Decide 5.1 and 5.2 (below), then finish 3.4 → 4 → 5 → 3.3 → 6.
3. Package the audit offer from the July review format.

## Decisions still pending

**5.1 — `risk_enrichment` is designed but never populated.** `strategy-rules.md`
specifies a 10-K demotion protocol, the rule ID exists in
`canonical-rulebook.json`, `pipeline.py:890` sorts on
`risk_enrichment.demotion_trigger`, but nothing ever writes that key.
- (a) implement — multi-day
- (b) remove the dead sort key, mark the rule "designed, not implemented" — ~1hr
- *Recommended: (b)*

**5.2 — Stage 3 is the most injection-exposed stage and the only unconstrained
one.** `analyst.py:1075-1086` passes `schema=None` while Stages 1–2 use
constrained decoding. Stage 3 takes Gemini web-grounded free text (`claim`,
`source_title`, `confidence_note` — live-search-derived, attacker-influenceable)
serialised verbatim via `json.dumps`.
- (c) wire constrained decoding if the current API can express the output shape
- (d) minimum bar: validate parsed output against `structured-analysis.schema.json`
  via `schemas.py`, reject and retry using the existing loop in `automation.py`
- *Recommended: (c). This finding is also the cleanest example of what the audit
  product sells.*

## Verified state as of today

```
152 tests            pass, 0.031s
validate-assets      crashes (FileNotFoundError) — phase 3.2 fixes
run-regression       crashes — phase 3.2 fixes
last commit          2026-07-06  docs(plans): structural fixes TODO
runs/                27 directories incl. ALGN, NKE, PYPL, batch-31..37
```

## Dropped this session

- **BokVault** (rugby content engine, `~/zoot/projects/bokvault`) — fully planned,
  33 steps, PRD written, never built. It was a demo for a business that no longer
  needs one. This repo is the better credential. Keep the plan; build it for fun
  later if ever.
- Rugby as a business: organisations have no budget, fans do not buy.
- SA property content: verified a direct competitor at 8+ months and 3 clients,
  near-zero engagement, their own Facebook page dead. Acquisition too slow.
- Betting (permanent), retail trading signals (FAIS).
