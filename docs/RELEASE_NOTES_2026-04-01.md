# Release Notes — 2026-04-01

This document summarizes the implementation batch completed on 2026-04-01 for X-Ray LLM.

## Scope

Implemented and validated:

- Taint-lite enhancements for high-noise security rules
- Policy profile controls (strict, balanced, relaxed-tests)
- UI controls and multilingual UX expansion
- CLI/API wiring for new scan options
- Rust-request fallback transparency in UI
- Test-runner compatibility when pytest-timeout plugin is missing

## Functional Changes

### 1. Scanner: Taint + Policy

Updated file:

- `xray/scanner.py`

Highlights:

- Added taint-scope helpers and taint-aware filtering for:
  - `SEC-004` (SQL injection)
  - `SEC-005` (SSRF)
  - `SEC-010` (path traversal)
- Added policy gate logic:
  - `strict`
  - `balanced`
  - `relaxed-tests`
- Added `SEC-010` context validation wrapper and mapping
- Added scan function parameters and propagation:
  - `policy_profile`
  - `taint_mode`

Behavior:

- `taint_mode=lite` filters non-tainted low-signal matches for selected SEC rules
- `taint_mode=strict` keeps broader context-validated findings
- `policy_profile=relaxed-tests` suppresses selected noisy rules in test paths

### 2. Security Rule Coverage

Updated file:

- `xray/rules/security.py`

Highlights:

- Expanded `SEC-010` regex trigger to include more realistic path composition patterns so validator/taint logic can classify findings more accurately.

### 3. Config and CLI Options

Updated files:

- `xray/config.py`
- `xray/agent.py`

Highlights:

- Added config fields:
  - `policy_profile`
  - `taint_mode`
- Added CLI flags:
  - `--policy-profile {strict,balanced,relaxed-tests}`
  - `--taint-mode {off,lite,strict}`
- Ensured agent scan and re-scan flows pass these options into scanner config.

### 4. API and Scan Manager Wiring

Updated files:

- `api/scan_routes.py`
- `services/scan_manager.py`

Highlights:

- `/api/scan` now accepts and validates:
  - `policy_profile`
  - `taint_mode`
- Python scan path receives and applies both options.

### 5. Rust Request Fallback + Badge

Updated files:

- `services/scan_manager.py`
- `ui.html`

Highlights:

- If user requests Rust engine with non-default policy/taint options, backend falls back to Python scanner for parity.
- Progress/result metadata now includes:
  - `engine_requested`
  - `engine_effective`
- UI now renders a tiny explicit badge during scan when switch occurs:
  - `Engine switched: rust -> python`

### 6. UI Settings + i18n Expansion

Updated file:

- `ui.html`

Highlights:

- Added settings controls:
  - Policy profile selector
  - Taint mode selector
- Added language selector and i18n dictionary support (EN/ES/FR)
- Expanded translated labels across:
  - Scan controls/status/errors
  - Sidebar section titles
  - Welcome panel text
  - Tool button labels

## Test and Compatibility Updates

Updated files:

- `xray/runner.py`
- `tests/test_xray.py`

Highlights:

- `run_tests()` now retries pytest invocation without `--timeout` when pytest-timeout plugin is absent.
- Added regression test for timeout-argument fallback behavior.
- Added tests for:
  - taint-lite suppression
  - taint strict-vs-lite behavior
  - relaxed-tests policy behavior

## Validation Performed

- Targeted scanner tests passed.
- Targeted scanner + runner tests passed.
- CLI smoke test passed with:
  - `python -m xray . --dry-run --severity HIGH --policy-profile strict --taint-mode lite --format json`

## Files Changed In This Batch

- `api/scan_routes.py`
- `services/scan_manager.py`
- `xray/scanner.py`
- `xray/rules/security.py`
- `xray/config.py`
- `xray/agent.py`
- `xray/runner.py`
- `ui.html`
- `tests/test_xray.py`
- `README.md`
- `CHANGELOG.md`
