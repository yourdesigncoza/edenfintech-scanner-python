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
- A deterministic Python pipeline for screening, analysis, epistemic review, and report assembly
- A CLI for validating assets, importing raw research bundles, and executing scans from JSON input

## Commands

```bash
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-assets
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-regression
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-contract screening
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-raw-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-scan-input raw-input.json --json-out input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-scan-input input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-scan input.json --json-out report.json --markdown-out report.md
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
`epistemic_review` object with the five PCS answers.

Use `show-scan-template` to generate a working example payload and
`show-scan-schema` to inspect the versioned contract in
`assets/methodology/scan-input.schema.json`. `validate-scan-input` performs
schema validation plus stage-aware runtime checks before a scan is run. The
pipeline also supports a raw-bundle import step through `show-raw-scan-template`
and `build-scan-input`, which maps a simpler research bundle into the validated
scan-input contract. Future importer code can read API keys from `.env`; see
`.env.example` for the expected variables. If a helper or contract ever
disagrees with the vendored `strategy-rules.md`, the methodology file wins.
