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
- A CLI for validating assets, fetching FMP and Gemini raw bundles, generating structured-analysis overlays, merging/importing bundles, and executing scans from JSON input
- A machine-draft field-generation layer that emits auditable structured-analysis drafts with provenance from merged raw evidence
- GitHub Actions CI that runs unit tests, asset validation, and regression checks on every push and pull request
- Sanitized wire-format FMP and Gemini fixtures that harden adapter tests against response-shape drift

## Commands

```bash
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-assets
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-regression
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-contract screening
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-raw-scan-template
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-scan-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-gemini-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli show-structured-analysis-schema
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-fmp-bundle RAW1 RAW2 --json-out fmp-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli fetch-gemini-bundle RAW1 RAW2 --focus "payments software" --json-out gemini-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli merge-raw-bundles fmp-raw.json gemini-raw.json --json-out merged-raw.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-structured-analysis-template merged-raw.json --json-out structured-analysis.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli generate-structured-analysis-draft merged-raw.json --json-out structured-analysis-draft.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli review-structured-analysis structured-analysis-reviewed.json --json-out review-checklist.json --markdown-out review-checklist.md --overlay-out structured-analysis-reviewed-notes.json --set-note screening_inputs.solvency="Reviewer checked solvency against cash generation history."
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli suggest-review-notes structured-analysis-reviewed.json --json-out review-note-suggestions.json --markdown-out review-note-suggestions.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli finalize-structured-analysis structured-analysis-reviewed.json --reviewer "Analyst Name" --json-out structured-analysis-finalized.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-review-package RAW1 RAW2 --out-dir runs/review-package
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli build-scan-input raw-input.json --json-out input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli validate-scan-input input.json
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-scan input.json --json-out report.json --markdown-out report.md --execution-log-out execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-judge report.json execution-log.md
PYTHONPATH=src python -m edenfintech_scanner_bootstrap.cli run-live-scan RAW1 RAW2 --out-dir runs/demo --stop-at raw-bundle
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
  fixtures/
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

The current automation boundary between retrieval and the deterministic pipeline
is the structured-analysis overlay in
`assets/methodology/structured-analysis.schema.json`. Use
`build-structured-analysis-template` to generate a ticker-aligned overlay
template from a merged raw bundle, then replace the generated
`screening_inputs`, `analysis_inputs`, and `epistemic_inputs` with
methodology-grounded judgments before building scan input or a report. The
generated template is intentionally non-executable: it contains
`__REQUIRED__` markers, starts as `completion_status: DRAFT`, and is bound to
the raw bundle fingerprint it was generated from.

`generate-structured-analysis-draft` produces a schema-valid machine draft from
the same merged raw bundle. It still keeps `completion_status: DRAFT`, adds
`generation_metadata`, and records `field_provenance` with
`status: MACHINE_DRAFT` per generated field so human review can see what was
inferred from which raw evidence. A draft cannot be promoted just by changing
metadata: finalization now requires those provenance entries to be converted
away from `MACHINE_DRAFT`.

`finalize-structured-analysis` is the narrow helper for that last step. It does
not invent judgments or rewrite field values. It only validates the reviewed
overlay, checks internal raw-bundle fingerprint continuity, converts remaining
required `MACHINE_DRAFT` provenance entries to either `HUMAN_CONFIRMED` or
`HUMAN_EDITED`, and adds top-level finalization metadata before the overlay can
be applied. It will only convert a machine-draft provenance entry if that entry
already carries an explicit `review_note`, so an untouched machine-generated
draft cannot be rubber-stamped into a finalized overlay.

`review-structured-analysis` sits one step earlier in the workflow. It produces
a checklist of required provenance entries, surfaces which ones are still
`MACHINE_DRAFT`, `HUMAN_CONFIRMED`, or `HUMAN_EDITED`, and can write targeted
`review_note` updates into a new overlay file. It does not change field values,
provenance statuses, or completion state. JSON remains the source of truth, and
`--markdown-out` is only a rendered review artifact from the same checklist
report object.

`suggest-review-notes` is a separate non-mutating helper. It emits suggested
`review_note` scaffolds only for required provenance entries that still lack a
note, based on the existing provenance rationale and evidence references. It
does not change overlays, statuses, field values, or completion state.

`build-review-package` is the thin packaging runner for operators. It reuses the
existing live retrieval, review artifact, scan, and judge helpers to assemble a
predictable run directory. Without a finalized structured overlay it stops at
the raw-bundle boundary and writes the review artifacts beside the raw and
structured-analysis files. If you provide `--structured-analysis-path`, it also
writes the enriched raw bundle, scan input, report, execution log, judge
output, and a package manifest.

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
decisions directly. `merge-raw-bundles` combines overlapping FMP and Gemini
tickers into a single combined raw bundle; it still requires
`screening_inputs`, `analysis_inputs`, and `epistemic_inputs` before
`build-scan-input` can succeed. `run-live-scan` orchestrates the full retrieval
flow and writes all intermediate artifacts into one directory, but by default it
stops at `raw-bundle` and writes a structured-analysis template so the current
boundary stays explicit. If you later apply a structured overlay, its
`source_bundle` fingerprint must match the freshly fetched raw bundle.
`run-live-scan` now also writes `structured-analysis-draft.json` beside the
manual template so the machine-draft path is visible without bypassing review.

Adapter tests now use sanitized wire-format fixture payloads under
`tests/fixtures/fmp/` and `tests/fixtures/gemini/`, including separate
official-shape fixtures that preserve provider nesting and response noise. That
covers response-shape variance without introducing live network dependence into
CI.
