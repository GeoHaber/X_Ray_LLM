# Changelog

## v0.3.1 — 2026-03-22

### Added
- **E2E test suite** (`tests/test_e2e_real.py`): 95 end-to-end tests with zero mocks — real scanner, fixer, agent, all 46 API routes, services, SARIF, analyzers, rules, and full workflow.
- **Testing guide** (`docs/TESTING.md`): complete reference for all 22 test files, CI pipeline, and test patterns.
- **SOTA analysis** (`SOTA_ANALYSIS_2026.md`): competitive positioning vs Semgrep, Bandit, SonarQube, Snyk; tech radar and 18-month roadmap recommendations.
- **Cost/benefit analysis** (`COST_BENEFIT_ANALYSIS_2026.md`): ROI documentation (50-100× year-1), break-even analysis, and competitor cost comparison.
- **Enhancement roadmap** (`Enhance_Plan.md`): 4-phase 18-month plan — pre-commit hook, GitHub Action, VSCode extension, ML FP suppression, JetBrains plugin, Go support.
- **Audit summary** (`AUDIT_SUMMARY_2026_03_21.md`): executive summary of full spec compliance audit (42 rules, 46 endpoints, 23+ analyzers — all verified).

### Fixed
- **Zombie process vulnerability** (`services/scan_manager.py`): `execute_monkey_tests()` now has guaranteed subprocess cleanup via `try/finally` — `proc.kill()` + `proc.wait()` called on both timeout and generic exceptions.
- **Rust process cleanup on abort** (`api/scan_routes.py`): added `state.rust_proc.wait()` after `kill()` in the abort handler.
- **Server exit cleanup** (`ui_server.py`): registered `atexit` handler + explicit `_cleanup()` in `KeyboardInterrupt` handler so Rust subprocesses are always terminated on server shutdown.
- **PytestCollectionWarning** (`xray/runner.py`): added `__test__ = False` to `TestResult` dataclass so pytest doesn't collect it as a test class.
- **`.gitignore` encoding corruption**: last two patterns (`*.bak`, `.xray_cache.json`) were UTF-16 LE encoded, causing git to read a bare `*` wildcard that silently ignored all new untracked files. Rewritten as clean UTF-8.

### Changed
- Test count: 1013 collected, **999 passing**, 14 skipped (added 95 new E2E tests).
- `X_RAY_LLM_GUIDE.md` §17 (Testing): expanded test file table to all 22 files with accurate counts; added `docs/` to §18 file tree.
- `Rebuild_Prompt.md`: updated with audit verification status (100% compliant as of 2026-03-21).

---

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
- Total test count: 1013 collected, 999 passing, 14 skipped.

Full changelog: [docs/CHANGELOG.md](docs/CHANGELOG.md)
