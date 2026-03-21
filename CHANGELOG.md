# Changelog

## v0.3.0 — 2026-03-21

### Added
- **Environment & API compatibility checker** (`xray/compat.py`): validates Python version (>=3.10), dependency versions, and library API surface at startup. Detects breaking changes after upgrades before they cause runtime errors.
- **Scanner string/comment awareness**: `scan_file()` now identifies Python string literals and comments and suppresses false-positive matches for rules prone to matching inside non-code regions (PY-004, PY-006, PY-007, QUAL-007, QUAL-010). Uses two filtering modes: "all" (strings + comments) and "strings-only" (for rules like QUAL-007 where comment matches are genuine).
- `/api/env-check` endpoint in `ui_server.py` — returns environment verification results as JSON.
- `require_environment()` guard in both `xray/agent.py` and `ui_server.py` entry points.
- 104 new tests: `tests/test_compat.py` (40 tests) and `tests/test_compat_stress.py` (64 tests) covering version parsing, API compatibility, and breaking-change simulation.
- `scripts/show_scan.py` utility for displaying self-scan results.

### Fixed
- Scanner false positives reduced by ~12% (329 → 292 findings on self-scan) by skipping regex matches that land inside Python string literals or comments.
- `scripts/show_scan.py`: added error handling around `json.load()` (PY-005 fix).

### Changed
- `xray/scanner.py`: added `_PY_NON_CODE_RE`, `_PY_STRING_ONLY_RE` regexes and `_STRING_AWARE_RULES` dict for context-aware scanning.
- Total test count: 673 passed, 10 skipped.

Full changelog: [docs/CHANGELOG.md](docs/CHANGELOG.md)
