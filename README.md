# EdenFinTech Scanner Python Bootstrap

This repository is the pre-port hardening layer for the standalone Python scanner.
It does not execute the full scanner yet. It packages the methodology assets,
stage contracts, deterministic rule definitions, and regression fixtures that the
Python implementation will use as its source of truth.

## Included

- Vendored methodology assets from the current EdenFinTech scanner
- Machine-readable stage contracts for scan orchestration
- Canonical rulebook aligned to `strategy-rules.md`
- Regression fixtures copied from existing scan artifacts
- A small Python CLI to validate assets and run fixture checks

## Commands

```bash
python -m edenfintech_scanner_bootstrap.cli validate-assets
python -m edenfintech_scanner_bootstrap.cli run-regression
python -m edenfintech_scanner_bootstrap.cli show-contract screening
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

## Purpose

These assets exist to make the later Python port more deterministic without
changing EdenFinTech's methodology. If a contract or rule conflicts with the
vendored `strategy-rules.md`, the methodology file wins.
