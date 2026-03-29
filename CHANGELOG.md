# Changelog

## v0.4.3 — 2026-03-28

### Added — Context Validation Pipeline & False-Positive Elimination

New **`_CTX_VALIDATORS`** pipeline for language-agnostic context-aware validation,
complementing the existing Python AST validators. Applied to a real-world scan of
ZenAIos-Dashboard (50K+ LOC), reducing findings from **763 → 542** (29% FP reduction).

#### New Context Validators (6)

| Validator | Rule | What it suppresses | FPs eliminated |
|-----------|------|--------------------|----------------|
| `_ctx_validate_sec001` | SEC-001 (XSS) | Multi-line template literals with sanitizer functions (forward 20-line search) | 4 |
| `_ctx_validate_sec002` | SEC-002 (XSS) | Wider window (-6/+15 lines) for `escapeHtml`, `DOMPurify`, numeric-only values | 6 |
| `_ctx_validate_sec004` | SEC-004 (SQLi) | Parameterized `%s` queries + f-string table names from hardcoded loops/regex-validated vars | 13 |
| `_ctx_validate_sec005` | SEC-005 (SSRF) | Test file paths and localhost URLs | 6 |
| `_ctx_validate_sec007` | SEC-007 (eval) | JS `.exec()` on RegExp, regex pattern objects, test file meta-assertions | 5 |
| `_ctx_validate_qual010` | QUAL-010 (localStorage) | Backward try/catch search + test file suppression | 34 |

#### Improved AST Validators (2)

| Validator | Rule | Improvement | FPs eliminated |
|-----------|------|-------------|----------------|
| `_ast_validate_py008` | PY-008 (encoding) | Detects `Image.open()`, binary mode `'rb'/'wb'`, `encoding=` keyword arg | 22 |
| `_ast_validate_py007` | PY-007 (os.environ) | Suppresses test files, `os.environ[k]=v` setting, try/except KeyError | 18 |
| `_ast_validate_qual004` | QUAL-004 (float cast) | argparse `float(args.X)` pattern detection | 3 |

#### String-Aware Rule Additions

- **SEC-007** added to `_STRING_AWARE_RULES` — suppresses `eval`/`exec` mentions in
  comments and docstrings (1 FP eliminated)

### Changed

- Validation pipeline: `_STRING_AWARE_RULES` → `_AST_VALIDATORS` → **`_CTX_VALIDATORS`** → inline suppression
- Test count: 201 core + **24 new FP tests** = 225 total (all passing)
- ZenAIos-Dashboard scan progression: 763 → 654 (code fixes) → 564 → 551 → 542 (scanner enhancements)

---

## v0.4.2 — 2026-03-27

### Added — Dual-Server Comparison Test Framework (36/36)

A new exhaustive test suite (`tests/test_dual_server.py`) compares the Python server
(port 8077) and Rust server (port 8078) end-to-end across **36 endpoints**, verifying
identical HTTP status codes and top-level JSON key shapes for every API route.

- **`TestGetEndpoints`** (5 tests): `/api/info`, `/api/browse`, `/api/scan-progress`, `/api/scan-result`, root `/`
- **`TestAnalysisEndpoints`** (19 tests): all POST analysis routes (`/api/smells`, `/api/health`, `/api/duplicates`, `/api/format`, `/api/typecheck`, `/api/dead-code`, `/api/connection-test`, `/api/release-readiness`, `/api/remediation-time`, `/api/circular-calls`, `/api/coupling`, `/api/unused-imports`, `/api/web-smells`, `/api/detect-language`, `/api/tech-stack`, `/api/satd`, `/api/git-summary`, `/api/pm-dashboard`, `/api/module-cards`)
- **`TestDashboardEndpoints`** (10 tests): PM Dashboard sub-routes
- **`TestFixEndpoints`** (2 tests): `/api/preview-fix`, `/api/apply-fix`

All **36/36 pass**. Run with:

```bash
python -m pytest tests/test_dual_server.py -v -s --tb=short
```

### Fixed

- **`/api/web-smells` panic — negative lookahead in `regex` crate**: `detect_web_smells()`
  in `scanner/src/analyzers/detection.rs` used patterns like `==(?!=)` and
  `<img(?![^>]*alt\s*=)` which the standard `regex` crate rejects at runtime (panics on
  `unwrap()`). Fixed by switching to `fancy_regex::Regex` for all 12 web-smell patterns,
  with `pat.is_match(line).unwrap_or(false)` for safe evaluation.

- **UTF-8 char-boundary panics (6 files)**: Several Rust analyzers truncated evidence
  strings with `&s[..120]` byte-slice notation. On strings containing multi-byte UTF-8
  characters (e.g., em-dashes `—` in `ui.html`), byte index 120 could fall mid-codepoint,
  causing a runtime panic. Fixed across all affected files using char-safe slicing:

  ```rust
  // Before (panics on multi-byte chars)
  &evidence[..120]
  // After (safe)
  let n = evidence.chars().count().min(120);
  let end = evidence.char_indices().nth(n).map(|(i,_)| i).unwrap_or(evidence.len());
  &evidence[..end]
  ```

  **Files fixed**: `detection.rs` (2 sites), `satd.rs`, `security.rs` (2 sites),
  `git_analyzer.rs`, `temporal.rs`, `lib.rs`.

- **`/api/apply-fix` response shape mismatch**: Rust failure branch was returning
  `{ok, description, error}` (extra `description` key). Python returns `{ok, error}` on
  failure. Fixed to omit `description` in the error path.

- **`/api/preview-fix` response shape mismatch**: Rust was serializing the full `FixResult`
  struct (including `new_lines` key absent from Python). Fixed to explicitly construct
  `{fixable, diff, description, error}` matching exact Python shape.

### Changed

- Rust test count: **91 → 102** (all passing, 0 failures).
- API route count: **38 routes → 40 routes, 38 API endpoints** (route table includes
  static file serving and root handler).
- `tests/test_api_compat.py`: Refined endpoint coverage (user-updated, committed `3c6f6e3`).
- `tests/test_llm_mock.py`, `xray/llm.py`: User-updated, committed `3c6f6e3`.

---

## v0.4.1 — 2026-03-26

### Added — Comprehensive Rust Test Suite (91 Tests)

The Rust scanner now has **91 unit/integration tests** (up from 34), with 56 new tests
covering the three enhanced analyzer modules. All tests pass on Windows (MSVC target).

#### New Tests by Module

- **smells.rs** — 20 new tests:
  - `detect_code_smells`: long_function, too_many_params, self_excluded, bare_except, no_bare_except_on_specific, mutable_default_list, mutable_default_dict, magic_number, no_magic_for_small_nums, by_type_populated, clean_code_no_smells (11 tests)
  - `detect_duplicates`: identical_blocks, no_false_positive, shape (3 tests)
  - `detect_dead_functions`: detects_uncalled, excludes_called, skips_tiny, skips_exempt_prefixes, attribute_calls_count, shape (6 tests)

- **connections.rs** — 18 new tests:
  - `normalize_route`: strips_trailing_slash, replaces_flask_params, replaces_express_params, replaces_braces_params, strips_query_string, root (6 tests)
  - `floor/ceil_char_boundary`: ascii, multibyte, past_end (5 tests)
  - `is_relative_api`: yes, no (2 tests)
  - `infer_method`: form_action, explicit, unknown (3 tests)
  - `analyze_connections` integration: shape_empty, detects_flask_backend, detects_fetch_frontend, wires_matching_routes, orphan_backend, orphan_ui (6 tests)

- **graph.rs** — 18 new tests (expanded from 1):
  - `detect_circular_calls`: shape, detects_cycle, no_cycle, detects_recursion (4 tests)
  - `compute_coupling_metrics`: shape, module_fields, cohesion_high, cohesion_low, health_summary_keys, imported_by (6 tests)
  - `detect_unused_imports`: shape, detects_unused, from_import, by_file, none_when_all_used (5 tests)
  - Plus existing: test_fwd (1 test)

#### Test Infrastructure

- **`make_temp_project()` helper**: All 3 analyzer test modules use a shared pattern that creates temp directories with a `project/` subdirectory, avoiding Windows `tempfile::tempdir()` dot-prefix filtering by WalkDir.
- **Return pattern**: `(tempfile::TempDir, String)` — TempDir kept alive for RAII cleanup, String is the project path passed to analyzer functions.

### Fixed

- **Dead function false-call on `def` lines** (`smells.rs`): The `func_call_re` regex was matching function names on definition lines (e.g., `def big_unused(x):` counted `big_unused` as "called"). Fixed by skipping call extraction on lines matching `func_def_re.is_match()`. This improves dead function detection accuracy.

### Changed

- Rust test count: 34 → **91** (all passing, 0 failures).
- All 15 API compatibility tests continue to pass (`tests/test_api_compat.py`).
- Release binary: ~4.9 MB (MSVC x86_64).

---

## v0.4.0 — 2026-03-26

### Added — Rust Server API Parity (18/18 Endpoints)

The Rust scanner (`scanner/src/`) now ships a **full HTTP server** mode (`--serve --port PORT`) with
**18 REST API endpoints** producing **identical JSON shapes** to the Python server. Automated shape
comparison via `tests/test_api_compat.py` confirms 18/18 compatibility.

#### New Rust Server Endpoints
All endpoints match the Python server response shapes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/info` | GET | Platform, version, rules count, fixable rules |
| `/api/browse` | GET | Directory listing with drive discovery |
| `/api/scan-progress` | GET | Scan status, files scanned, findings count |
| `/api/scan-result` | GET | Full scan results payload |
| `/api/scan` | POST | Start background scan |
| `/api/health` | POST | 10-point project health score |
| `/api/smells` | POST | Code smell detection (magic numbers, mutable defaults, bare excepts) |
| `/api/dead-code` | POST | Dead function detection |
| `/api/duplicates` | POST | Duplicate block detection (grouped format with SHA-256) |
| `/api/format` | POST | Format check via ruff |
| `/api/typecheck` | POST | Type check via ty |
| `/api/connection-test` | POST | Frontend→backend connection wiring analysis |
| `/api/release-readiness` | POST | Release readiness assessment |
| `/api/remediation-time` | POST | Fix time estimation per finding |
| `/api/circular-calls` | POST | Function-level circular call detection |
| `/api/coupling` | POST | Module coupling, cohesion, health metrics |
| `/api/unused-imports` | POST | AST-based unused import detection |

#### Rust Analyzer Enhancements

- **Smells analyzer** (`scanner/src/analyzers/smells.rs`):
  - Added `magic_number` detection (numbers > 2 outside indices/returns, LOW severity)
  - Added `mutable_default` detection (function params with `=[]` or `={}`)
  - Added `bare_except` detection (bare `except:` clauses)

- **Duplicates analyzer** (`scanner/src/analyzers/smells.rs`):
  - Restructured from pairwise format to Python-compatible **grouped format**
  - Returns `duplicate_groups[{hash, occurrences, locations[{file, line}], lines}]`
  - Uses SHA-256 hashing, capped at 200 groups / 10 locations per group

- **Connection analyzer** (`scanner/src/analyzers/connections.rs`):
  - **Complete rewrite** from simple import-edge analysis to full UI↔backend connection wiring
  - Phase A: Scans frontend files (JS/TS/HTML/Vue/Svelte) for 7 API call patterns (fetch, axios, jquery, api, xhr, form_action, href)
  - Phase B: Scans backend files (Python/JS/TS) for 5 route handler patterns (flask, fastapi, django, express, xray_custom)
  - Phase C: Wires connections by normalized URL path with cardinality detection (1:1, 1:many, many:1)
  - Returns: `{wired, orphan_ui, orphan_backend, summary, frameworks_detected}`
  - UTF-8-safe string slicing via `floor_char_boundary()`/`ceil_char_boundary()` helpers

- **Circular calls** (`scanner/src/analyzers/graph.rs`):
  - Added `functions` array to each cycle: `[{name, file, line}]` per node

- **Coupling** (`scanner/src/analyzers/graph.rs`):
  - Added `cohesion` field ("high"/"medium"/"low")
  - Added `imports` and `imported_by` sorted lists
  - Added `health_summary` dict with per-category counts
  - Added `god_modules`, `fragile_modules`, `isolated_modules` (top 10 each)

- **Unused imports** (`scanner/src/analyzers/graph.rs`):
  - Added `files_with_unused` count
  - Added `by_file` dict (top 20 files by count, sorted descending)

#### New Test: API Compatibility
- **`tests/test_api_compat.py`**: Automated shape comparison that hits both Python (port 8077) and Rust (port 8078) servers, compares response JSON structures, and reports diffs.
  - Tolerates extra fields in Rust (backwards-compatible additions)
  - Handles empty arrays and dynamic dict keys (e.g., `by_file` with filename keys)
  - Usage: `python tests/test_api_compat.py --py-port 8077 --rs-port 8078 --scan-dir /path`

### Fixed
- **Connection analyzer UTF-8 crash**: Rust server panicked on multi-byte characters (e.g., `─` in `ui.html`) when slicing context strings. Added `floor_char_boundary()` and `ceil_char_boundary()` helpers for safe string slicing.
- **Scan progress idle response**: Rust idle response now includes zero-value fields (`files_scanned: 0`, `total_files: 0`, `findings_count: 0`, `elapsed_ms: 0.0`) matching Python's shape.
- **Browse API `\\?\` prefix**: Rust browse endpoint stripped Windows extended-length path prefixes that broke UI navigation.
- **Scan timing race**: UI polling during slow scan start got "idle" status and treated scan as done. Fixed by setting status to "scanning" immediately before scan begins.

### Changed
- Rust scanner architecture expanded from 3 source files to **18 source files** across 4 modules (`analyzers/`, `server/`, `rules/`, root).
- Rust release binary: ~4.9 MB, supports both CLI scan mode and HTTP server mode.
- All 91 Rust unit/integration tests pass (56 new analyzer tests + 35 existing).

---

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
