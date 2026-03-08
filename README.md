# EdenFinTech Scanner Python

This repository now contains a deterministic Python scan pipeline built from the
vendored EdenFinTech methodology assets. It consumes structured research inputs,
applies the stage contracts locally, and emits JSON-first scan reports plus
markdown summaries without changing the underlying methodology.

## Included

- Vendored methodology assets from the current EdenFinTech scanner
- Machine-readable stage contracts for scan orchestration
- Canonical rulebook aligned to `strategy-rules.md`
- Regression fixtures copied from existing scan artifacts
- A deterministic Python pipeline for screening, analysis, epistemic review, report assembly, execution-log generation, and config-gated judge review
- A CLI for validating assets, fetching FMP and Gemini raw bundles, merging them, importing raw research bundles, and executing scans from JSON input

## Commands

```bash
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-assets
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-regression
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-contract screening
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-raw-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-gemini-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-fmp-bundle RAW1 RAW2 --json-out fmp-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-gemini-bundle RAW1 RAW2 --focus "payments software" --json-out gemini-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli merge-raw-bundles fmp-raw.json gemini-raw.json --json-out merged-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-scan-input raw-input.json --json-out input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-scan-input input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-scan input.json --json-out report.json --markdown-out report.md --execution-log-out execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-judge report.json execution-log.md
```

## Layout

```text
assets/
  contracts/
  fixtures/regression/
  methodology/
  rules/
src/edenfintech_scanner_bootstrap/
tests/
```

## Scan Input Model

`run-scan` expects a structured JSON payload. Each candidate must include
screening data; names that pass screening must also include analysis inputs
(`base_case`, `worst_case`, `probability`, catalyst/risk fields) and an
`epistemic_review` object with the five PCS answers. `portfolio_context` may
also include `current_holdings` so the report can populate
`current_holding_overlays`.

Use `show-scan-template` to generate a working example payload and
`show-scan-schema` to inspect the versioned contract in
`assets/methodology/scan-input.schema.json`. `validate-scan-input` performs
schema validation plus stage-aware runtime checks before a scan is run. The
pipeline also supports a raw-bundle import step through `show-raw-scan-template`
and `build-scan-input`, which maps a simpler research bundle into the validated
scan-input contract. Future importer code can read API keys from `.env`; see
`.env.example` for the expected variables. If a helper or contract ever
disagrees with the vendored `strategy-rules.md`, the methodology file wins.

The judge layer is advisory and config-gated. If `OPENAI_API_KEY` is missing,
the pipeline falls back to a deterministic local judge that stays within the
existing `codex_final_judge` contract.

`fetch-fmp-bundle` is retrieval-only. It emits raw-bundle fields from Financial
Modeling Prep, including current price, derived `% off ATH`, revenue history,
share-count, and FCF-margin history. `fetch-gemini-bundle` is also retrieval-
only. It emits sourced qualitative evidence arrays defined in
`assets/methodology/gemini-raw-bundle.schema.json`, such as research notes,
catalyst evidence, risk evidence, management/moat/precedent observations, and
epistemic anchors. Neither command emits scan-input payloads or methodology
decisions directly. `merge-raw-bundles` combines those retrieval outputs into a
single importer-ready raw bundle while leaving normalization in `importers.py`.
