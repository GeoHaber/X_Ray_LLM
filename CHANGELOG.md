# Changelog

## v0.3.0 — 2026-03-21

### Added
- **Environment & API compatibility checker** (`xray/compat.py`): validates Python version (>=3.10), dependency versions, and library API surface at startup. Detects breaking changes after upgrades before they cause runtime errors.
- **Scanner string/comment awareness**: `scan_file()` now identifies Python string literals and comments and suppresses false-positive matches for rules prone to matching inside non-code regions (PY-004, PY-006, PY-007, QUAL-007, QUAL-010). Uses two filtering modes: "all" (strings + comments) and "strings-only" (for rules like QUAL-007 where comment matches are genuine).
- `/api/env-check` endpoint in `ui_server.py` — returns environment verification results as JSON.
- `require_environment()` guard in both `xray/agent.py` and `ui_server.py` entry points.
- 104 new tests: `tests/test_compat.py` (40 tests) and `tests/test_compat_stress.py` (64 tests) covering version parsing, API compatibility, and breaking-change simulation.
- `scripts/show_scan.py` utility for displaying self-scan results.
- **Parallel scanning** via `ProcessPoolExecutor` — 3-5x speedup on multi-core systems.
- **Incremental scanning** with SHA-256 file hash cache (`.xray_cache.json`) — 10-50x faster on re-scans.
- **Pre-compiled regex cache** — avoids recompiling patterns per-file.
- **Inline suppression comments** (`# xray: ignore[RULE-ID, ...]`) — per-line rule suppression.
- **SARIF v2.1.0 output** (`xray/sarif.py`) — compatible with GitHub Code Scanning, VS Code SARIF Viewer, Azure DevOps Advanced Security.
- **Baseline/diff scanning** (`--baseline`) — filter out known findings, show only new issues.
- **SCA integration** (`xray/sca.py`) — wraps pip-audit for dependency vulnerability scanning.
- **`python -m xray` entry point** (`xray/__main__.py`) — simpler invocation.
- **Project-level config** (`xray/config.py`) — reads `[tool.xray]` from pyproject.toml, CLI flags override.
- **New CLI flags**: `--format sarif|json|text`, `-o/--output`, `--baseline`, `--incremental`, `--no-parallel`.
- **Docker support** — `Dockerfile` and `docker-compose.yml` for containerized scanning.
- **PyPI publishing pipeline** (`.github/workflows/publish.yml`).
- **GitHub Release pipeline** (`.github/workflows/release.yml`) — auto-release + GHCR Docker push on tag.
- **Version sync script** (`scripts/bump_version.py`) — atomic version bump across pyproject.toml, Cargo.toml, `__init__.py`.
- **GitHub Action** (`action.yml`) — reusable action for CI integration (`uses: owner/xray-llm@v1`).

### Fixed
- Scanner false positives reduced by ~12% (329 → 292 findings on self-scan) by skipping regex matches that land inside Python string literals or comments.
- `scripts/show_scan.py`: added error handling around `json.load()` (PY-005 fix).
- **Thread-safe LLM initialization** — `_ensure_model()` now uses `threading.Lock` to prevent race conditions.
- **Request body limit** — 413 response if `Content-Length > 10 MB` to prevent DoS.
- **Debug mode from env var** — `XRAY_DEBUG` instead of hardcoded `True`.
- **Fixer backup** — `apply_fix()` now creates `.bak` copy via `shutil.copy2()` before writing.
- **`_scan_progress` initialization** — no longer raises `NameError` on first access.
- **Robust environment parsing** — safe int/float conversion with fallbacks for non-numeric env vars.
- **Wire connector false positives** — status code check uses `200 <= status < 500`.
- **CI workflow** — replaced old `x_ray_claude.py` reference with `python -m xray`, added SARIF upload, updated actions to v4/v5.

### Changed
- `xray/scanner.py`: added `_PY_NON_CODE_RE`, `_PY_STRING_ONLY_RE` regexes and `_STRING_AWARE_RULES` dict for context-aware scanning.
- `xray/scanner.py`: `scan_directory()` now supports `parallel=True` and `incremental=True` keyword arguments.
- `xray/scanner.py`: `Finding` now has `from_dict()` static method; `ScanResult` now has `cached_files` field.
- `xray/agent.py`: CLI integrated with `XRayConfig.from_pyproject()` for per-project settings.
- Version bumped to **0.3.0** across pyproject.toml, Cargo.toml, and `xray/__init__.py`.
- Total test count: 673 passed, 10 skipped.

Full changelog: [docs/CHANGELOG.md](docs/CHANGELOG.md)
