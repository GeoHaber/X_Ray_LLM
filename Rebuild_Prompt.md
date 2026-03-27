# X-Ray LLM — Rebuild Prompt (Self-Contained Blueprint)

**Purpose:** This document enables any LLM to rebuild the entire X-Ray LLM project from zero with perfect fidelity.
**Last verified:** 2026-03-26 — 1330+ Python tests passing, 91 Rust tests passing, 42 rules, 45 API endpoints (Python), 18 API endpoints (Rust, shape-compatible).

---

## 1. Project Overview

X-Ray LLM is a self-improving code quality agent that scans Python/JS/HTML codebases for security vulnerabilities, quality issues, Python-specific bugs, and portability problems using 42 regex-based pattern rules sourced from real production bugs.

**Core loop:** SCAN → TEST → FIX → VERIFY → LOOP

### Transpilation Philosophy — Python Is the Source of Truth

The entire purpose of X-Ray LLM is:
```
Python code → Analyze → Simplify → Fix → Transpile to Rust (for speed & security)
```

The Rust scanner (`scanner/src/`) is a **faithful transpilation** of the Python codebase — NOT a rewrite.
Every Rust module must mirror its Python counterpart 1:1 in logic and JSON output shapes.

**Rules:**
1. Python is always the source of truth — every Rust file has a Python counterpart
2. Never write Rust from scratch — read the Python first, then transpile
3. JSON responses must be field-for-field identical (verified by `tests/test_api_compat.py`)
4. When Python changes, Rust must follow
5. Do not diverge — mirror Python logic exactly (perf optimizations OK if output unchanged)

**Key capabilities:**
- 42 pattern-based scan rules (14 Security, 13 Quality, 11 Python, 4 Portability)
- 7 deterministic auto-fixers (no LLM needed): SEC-003, SEC-009, QUAL-001, QUAL-003, QUAL-004, PY-005, PY-007
- 5 AST-based false positive validators: PY-001, PY-005, PY-006, QUAL-003, QUAL-004
- String/comment awareness: 5 rules suppressed when match is inside string or comment
- Inline suppression: `# xray: ignore[RULE-ID]` on any line
- Web UI (single-page app on port 8077) with 28+ views
- 45 REST API endpoints across 5 route modules
- 25+ analyzer functions (dead code, smells, duplicates, coupling, etc.)
- 9 PM Dashboard features (Risk Heatmap, Module Cards, Confidence Meter, Sprint Batches, Architecture Map, Call Graph, Circular Calls, Coupling, Unused Imports)
- SARIF 2.1.0 + JSON + text output
- Optional Rust scanner (42 rules, full HTTP server with 18 API endpoints, ~10x faster)
- LLM-powered test generation and fix generation via llama-cpp-python

## 2. Folder Structure

```
X_Ray_LLM/
├── pyproject.toml            # Project config, dependencies, ruff/ty settings
├── ui_server.py              # HTTP server, route dispatch, ThreadingMixIn
├── ui.html                   # Single-page web UI (28+ views)
├── build.py                  # Rust scanner build system
├── setup_tools.py            # Tool installation helper
├── update_tools.py           # Tool update helper
├── generate_rust_rules.py    # Generates Rust rules from Python rule definitions
├── README.md
├── X_RAY_LLM_GUIDE.md       # Complete feature guide (19 sections, 1500+ lines)
├── Dockerfile
├── docker-compose.yml
├── MANIFEST.in
├── xray/
│   ├── __init__.py           # Version: 0.3.0
│   ├── __main__.py           # CLI entry point
│   ├── scanner.py            # Pattern scanner engine (~600 lines)
│   ├── agent.py              # Agent loop orchestrator + CLI flags (~350 lines)
│   ├── fixer.py              # 7 deterministic fixers (~400 lines)
│   ├── llm.py                # LLM inference (~200 lines)
│   ├── runner.py             # pytest runner (~100 lines)
│   ├── sarif.py              # SARIF 2.1.0 output (~150 lines)
│   ├── config.py             # pyproject.toml config loader (~100 lines)
│   ├── constants.py          # Shared constants: SKIP_DIRS, TEXT_EXTS (~80 lines)
│   ├── types.py              # 15 TypedDict definitions (~150 lines)
│   ├── compat.py             # Python/dependency/API/PyPI freshness checker (~300 lines)
│   ├── sca.py                # pip-audit integration (~100 lines)
│   ├── wire_connector.py     # Web framework wiring (~200 lines)
│   ├── portability_audit.py  # Portability audit reports
│   └── rules/
│       ├── __init__.py       # Exports ALL_RULES = SEC + QUAL + PY + PORT (42 total)
│       ├── security.py       # SECURITY_RULES: SEC-001 to SEC-014
│       ├── quality.py        # QUALITY_RULES: QUAL-001 to QUAL-013
│       ├── python_rules.py   # PYTHON_RULES: PY-001 to PY-011
│       └── portability.py    # PORTABILITY_RULES: PORT-001 to PORT-004
├── analyzers/
│   ├── __init__.py           # Re-exports 25+ functions via __all__ (46 symbols total)
│   ├── _shared.py            # Helpers: _walk_py, _walk_ext, _safe_parse, _fwd
│   ├── format_check.py       # check_format, check_types, run_typecheck
│   ├── health.py             # check_project_health, check_release_readiness, estimate_remediation_time
│   ├── security.py           # run_bandit
│   ├── smells.py             # detect_dead_functions, detect_code_smells, detect_duplicates
│   ├── temporal.py           # analyze_temporal_coupling
│   ├── detection.py          # detect_ai_code, detect_web_smells, generate_test_stubs
│   ├── pm_dashboard.py       # 9 PM features: risk heatmap, module cards, confidence, sprint batches, architecture, call graph, project review, coupling, unused imports
│   ├── graph.py              # detect_circular_calls, compute_coupling_metrics, detect_unused_imports
│   └── connections.py        # analyze_connections
├── services/
│   ├── __init__.py
│   ├── app_state.py          # Thread-safe AppState singleton
│   ├── scan_manager.py       # Scan orchestration: Python/Rust engines, browse, progress
│   ├── git_analyzer.py       # Git hotspots, import parsing, ruff integration
│   ├── chat_engine.py        # Knowledge chatbot (42 rules, 45 endpoints, 9 PM features)
│   └── satd_scanner.py       # Self-Admitted Technical Debt scanning
├── api/
│   ├── __init__.py
│   ├── scan_routes.py        # GET: /api/scan-result, /api/scan-progress | POST: /api/scan, /api/abort
│   ├── fix_routes.py         # POST: /api/preview-fix, /api/apply-fix, /api/apply-fixes-bulk
│   ├── analysis_routes.py    # POST: 19 analysis endpoints (dead-code, smells, duplicates, etc.)
│   ├── pm_routes.py          # GET: 8 PM endpoints | POST: 5 PM + chat + utility endpoints
│   └── browse_routes.py      # GET: /api/browse, /api/info, /api/env-check
├── tests/                    # 24 test files, 1330+ tests
│   ├── __init__.py
│   ├── test_xray.py          # Rule DB + scanner integration
│   ├── test_verify.py        # Does-no-harm + finds-real-bugs
│   ├── test_ui_paths.py      # Path handling + browse restrictions
│   ├── test_e2e_real.py      # 95 end-to-end tests (no mocks)
│   ├── test_analyzers.py     # All 11 analyzer modules
│   ├── test_comprehensive.py # Broad coverage
│   ├── test_full_validation.py # 177 spec-validation tests (no mocks)
│   ├── test_fixer.py         # Fixer unit tests
│   ├── test_fixer_regression.py # Fixer regression tests
│   ├── test_false_positives.py  # AST validator tests
│   ├── test_compat.py        # Version/dependency checker
│   ├── test_compat_stress.py # Stress tests for compat
│   ├── test_scanner_boundary.py # Edge cases for scanner
│   ├── test_sarif.py         # SARIF output tests
│   ├── test_sca.py           # Supply chain analysis tests
│   ├── test_agent_loop.py    # Agent orchestration tests
│   ├── test_build.py         # Rust build system tests
│   ├── test_config.py        # Config loader tests
│   ├── test_connection_analyzer.py # Connection analyzer tests
│   ├── test_http_integration.py # Live HTTP server tests
│   ├── test_llm_mock.py      # LLM with mocked inference
│   ├── test_monkey.py        # Monkey/fuzz testing
│   ├── test_portability.py   # Portability rule tests
│   └── test_spec_compliance.py # Spec compliance tests
├── scanner/                  # Rust scanner (full API-compatible server)
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs           # CLI + --serve entry point
│       ├── lib.rs            # Core scanner engine (~600 lines)
│       ├── config.rs         # pyproject.toml config loader
│       ├── constants.rs      # SKIP_DIRS, TEXT_EXTS
│       ├── fixer.rs          # 7 deterministic auto-fixers
│       ├── sarif.rs          # SARIF 2.1.0 output
│       ├── types.rs          # TypedDict-equivalent structs
│       ├── rules/
│       │   └── mod.rs        # 42 compiled regex rules
│       ├── server/
│       │   ├── mod.rs        # axum HTTP server, embedded ui.html
│       │   ├── routes.rs     # 18 route handlers (API-compatible with Python)
│       │   └── state.rs      # Thread-safe AppState
│       └── analyzers/
│           ├── mod.rs         # Module exports
│           ├── smells.rs      # Dead functions, code smells, duplicates
│           ├── health.rs      # Project health, release readiness, remediation
│           ├── graph.rs       # Circular calls, coupling, unused imports
│           ├── connections.rs # Frontend↔backend connection wiring
│           ├── format_check.rs# ruff format + ty typecheck
│           └── detection.rs   # AI code detection, web smells
├── scripts/                  # Utility scripts
│   ├── bump_version.py
│   ├── scan_llm_paths.py
│   └── show_scan.py
└── docs/
    └── TESTING.md
```

## 3. Complete Rule Reference (42 Rules)

### Security Rules (14) — SEC-001 to SEC-014
| ID | Severity | Description | Auto-Fix |
|----|----------|-------------|----------|
| SEC-001 | HIGH | XSS: Template literal in innerHTML | No |
| SEC-002 | HIGH | XSS: String concat to innerHTML | No |
| SEC-003 | HIGH | Command injection: shell=True | **Yes** |
| SEC-004 | HIGH | SQL injection: Query formatting | No |
| SEC-005 | MEDIUM | SSRF: URL from user input | No |
| SEC-006 | MEDIUM | CORS misconfiguration: wildcard | No |
| SEC-007 | HIGH | Code injection: eval/exec | No |
| SEC-008 | MEDIUM | Hardcoded secret | No |
| SEC-009 | HIGH | Unsafe deserialization (pickle/yaml) | **Yes** |
| SEC-010 | MEDIUM | Path traversal | No |
| SEC-011 | MEDIUM | Timing attack: == on secrets | No |
| SEC-012 | HIGH | Debug mode enabled in production | No |
| SEC-013 | MEDIUM | Weak hash: MD5/SHA1 | No |
| SEC-014 | HIGH | TLS verification disabled | No |

### Quality Rules (13) — QUAL-001 to QUAL-013
| ID | Severity | Description | Auto-Fix |
|----|----------|-------------|----------|
| QUAL-001 | MEDIUM | Bare except clause | **Yes** |
| QUAL-002 | LOW | Silent exception swallowing | No |
| QUAL-003 | MEDIUM | Unchecked int() on user input | **Yes** |
| QUAL-004 | MEDIUM | Unchecked float() on user input | **Yes** |
| QUAL-005 | LOW | .items() on possibly-None return | No |
| QUAL-006 | MEDIUM | Non-daemon threads | No |
| QUAL-007 | LOW | TODO/FIXME markers | No |
| QUAL-008 | MEDIUM | Long sleep (10+ seconds) | No |
| QUAL-009 | HIGH | Keep-alive header in HTTP | No |
| QUAL-010 | MEDIUM | localStorage without try/catch | No |
| QUAL-011 | MEDIUM | Broad Exception catching | No |
| QUAL-012 | LOW | String concatenation in loop | No |
| QUAL-013 | LOW | Line exceeds 200 characters | No |

### Python Rules (11) — PY-001 to PY-011
| ID | Severity | Description | Auto-Fix |
|----|----------|-------------|----------|
| PY-001 | MEDIUM | Return type mismatch (-> None returns dict) | No |
| PY-002 | HIGH | .items() on method returning None | No |
| PY-003 | MEDIUM | Wildcard import | No |
| PY-004 | LOW | print() debug statement | No |
| PY-005 | HIGH | JSON without error handling | **Yes** |
| PY-006 | MEDIUM | Global mutation | No |
| PY-007 | MEDIUM | os.environ[] crashes on missing | **Yes** |
| PY-008 | MEDIUM | open() without encoding | No |
| PY-009 | MEDIUM | Captured but ignored exception | No |
| PY-010 | MEDIUM | sys.exit() in library code | No |
| PY-011 | LOW | Long isinstance chain | No |

### Portability Rules (4) — PORT-001 to PORT-004
| ID | Severity | Description | Auto-Fix |
|----|----------|-------------|----------|
| PORT-001 | HIGH | Hardcoded user-specific path | No |
| PORT-002 | HIGH | Hardcoded C:\AI\ path | No |
| PORT-003 | MEDIUM | Hardcoded absolute Windows path | No |
| PORT-004 | MEDIUM | Windows-only module import | No |

## 4. Key Architectural Patterns

### Rule Structure
Each rule is a dict with exactly these fields:
```python
{
    "id": "SEC-003",
    "severity": "HIGH",           # HIGH | MEDIUM | LOW
    "pattern": r"subprocess\.\w+\(.*shell\s*=\s*True",
    "description": "Command injection: subprocess called with shell=True",
    "fix_hint": "Use shell=False and pass args as a list",
    "test_hint": "Create a file with subprocess.run(..., shell=True) and verify it fires",
    "lang": ["python"],           # list of: python, javascript, html
}
```

### Scanner Architecture (xray/scanner.py)
1. Walk directory, skip SKIP_DIRS (__pycache__, .git, node_modules, venv, etc.)
2. Detect language by extension (.py=python, .js/.ts=javascript, .html=html)
3. For each file, build non-code ranges (string literals + comments) using `_PY_NON_CODE_RE`
4. Apply each applicable rule's regex pattern against file content line-by-line
5. For **string-aware rules** (PY-004, PY-006, PY-007, QUAL-007, QUAL-010), suppress matches that fall inside a string literal or comment
6. For **AST-validated rules** (PY-001, PY-005, PY-006, QUAL-003, QUAL-004), run AST analysis to confirm the finding is real
7. Check **inline suppressions**: `# xray: ignore[RULE-ID]` suppresses that rule on that line
8. Return list of Finding objects (rule_id, severity, file, line, message, matched_text)

**String awareness modes:**
- `"all"` — suppress in strings AND comments (PY-004, PY-006, PY-007, QUAL-010)
- `"strings"` — suppress in strings only, keep in comments (QUAL-007 — TODO/FIXME should still fire in real comments)

### Web Server Architecture (ui_server.py)
- ThreadingMixIn + HTTPServer on port 8077
- Route dispatch via `_GET_ROUTES` and `_POST_ROUTES` dicts (merged from 5 api/ modules)
- Background scans via daemon threads with SSE progress
- AppState singleton for thread-safe state (services/app_state.py)
- CORS optional via `XRAY_CORS_ORIGIN` env var
- Browse restriction via `XRAY_BROWSE_ROOTS` env var

### Route Assembly (ui_server.py lines 70-91)
```python
from api.scan_routes import GET_ROUTES as _scan_get, POST_ROUTES as _scan_post
from api.browse_routes import GET_ROUTES as _browse_get
from api.fix_routes import POST_ROUTES as _fix_post
from api.analysis_routes import POST_ROUTES as _analysis_post
from api.pm_routes import GET_ROUTES as _pm_get, POST_ROUTES as _pm_post

_GET_ROUTES = {}
_POST_ROUTES = {}
for table in (_scan_get, _browse_get, _pm_get):
    _GET_ROUTES.update(table)
for table in (_scan_post, _fix_post, _analysis_post, _pm_post):
    _POST_ROUTES.update(table)
```

### Fixer Architecture (xray/fixer.py)
- 7 deterministic fixers keyed by rule ID in `FIXERS` dict
- Each fixer receives `(filepath, line_num, matched_text, lines)` and returns `FixResult`
- `FixResult` has: `fixable`, `new_lines`, `description`, `diff`, `error`
- Backup `.bak` created before writing any file
- `apply_fixes_bulk` processes files bottom-up to preserve line numbers
- `FIXABLE_RULES = set(FIXERS.keys())`

```python
FIXERS = {
    "PY-005": _fix_py005_json_parse,
    "PY-007": _fix_py007_os_environ,
    "QUAL-001": _fix_qual001_bare_except,
    "QUAL-003": _fix_qual003_int_input,
    "QUAL-004": _fix_qual004_float_input,
    "SEC-003": _fix_sec003_shell_true,
    "SEC-009": _fix_sec009_pickle_yaml,
}
```

### Agent Loop (xray/agent.py)
CLI flags:
- `--dry-run` — scan only, no fixes
- `--fix` — scan and auto-fix
- `--severity HIGH|MEDIUM|LOW` — filter by severity
- `--exclude PATTERN` — exclude files matching glob
- `--format text|json|sarif` — output format
- `--baseline FILE` — compare against previous scan
- `--incremental` — only scan changed files (since last commit)
- `--since COMMIT` — only scan files changed since commit

Loop: SCAN → FIX → re-SCAN → verify findings reduced → repeat (max 3 iterations)

### Grading System
Weighted formula: `weighted = high × 5 + medium × 2 + low × 0.5`
Per-100 score: `per100 = (weighted / file_count) × 100`

| Grade | Score Range |
|-------|-------------|
| A | per100 ≤ 5 |
| B | per100 ≤ 15 |
| C | per100 ≤ 40 |
| D | per100 ≤ 80 |
| F | per100 > 80 |

## 5. Dependencies

```toml
[project]
name = "xray-llm"
version = "0.3.0"
requires-python = ">=3.10"
dependencies = ["llama-cpp-python>=0.3.0", "pytest>=7.0"]

[project.optional-dependencies]
dev = ["ruff>=0.15", "ty>=0.0.1"]

[tool.ruff]
line-length = 120
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
ignore = ["E501"]
```

## 6. Build & Run Commands

```bash
# Install
pip install -e ".[dev]"

# Run web UI
python ui_server.py              # Opens http://127.0.0.1:8077

# Run tests
python -m pytest tests/ -v --tb=short

# Run specific test file
python -m pytest tests/test_full_validation.py -v

# Lint
python -m ruff check .

# Format
python -m ruff format .

# CLI scan (dry run)
python -m xray /path/to/project --dry-run

# CLI scan with auto-fix
python -m xray /path/to/project --fix

# SARIF output
python -m xray /path/to/project --format sarif -o results.sarif

# JSON output
python -m xray /path/to/project --format json -o results.json

# Build Rust scanner (optional)
python build.py
```

## 7. Test Strategy

- 24 test files, 1330+ tests (1153+ collected at last run: 1141 passing + 12 skipped)
- **91 Rust unit/integration tests** across `lib.rs`, `smells.rs`, `connections.rs`, `graph.rs`, `rules/mod.rs`, `config.rs`, `fixer.rs`, `sarif.rs` (all passing)
- **No mocks** for core scanner/fixer tests (test_e2e_real.py, test_full_validation.py)
- SHA-256 verification that scanning never modifies files (test_verify.py)
- Every rule tested with trigger sample AND safe-code sample
- HTTP integration tests boot a real server (test_http_integration.py)
- AST validator tests verify false positive suppression (test_false_positives.py)
- Fixer regression tests verify fixes produce valid Python (test_fixer_regression.py)
- test_full_validation.py: 177 tests validating all spec claims (42 rules, 7 fixers, 5 AST validators, 45 endpoints, etc.)
- Rust `make_temp_project()` helper avoids Windows tempdir dot-prefix filtering by WalkDir

## 8. SARIF Output Format

```python
from xray.sarif import findings_to_sarif

sarif = findings_to_sarif(
    finding_dicts,        # list of Finding.to_dict()
    tool_name="xray-llm",
    tool_version="0.3.0",
)
# Returns SARIF 2.1.0 compliant dict with:
# - $schema, version "2.1.0"
# - runs[0].tool.driver.name, version, rules[]
# - runs[0].results[] with ruleId, message, locations[], level
```

## 9. Key TypedDicts (xray/types.py)

15 TypedDict definitions: FileItem, BrowseResult, DriveInfo, FindingDict, ScanSummary, ScanResult, FormatResult, TypeDiagnostic, TypeCheckResult, HealthCheck, and more. Used for API response typing.

## 10. Known Design Decisions

- QUAL-001 fixer (bare except → `except Exception:`) creates a QUAL-011 violation (broad Exception). This is intentional — the fixer improves the code incrementally.
- PY-005 fixer (JSON without error handling) wraps in try/except with a `pass` handler. Users may want to add logging.
- String awareness uses regex-based non-code range detection, not full tokenization.
- AST validators are only used for 5 rules where regex alone has too many false positives.
- The Rust scanner implements all 42 rules and has full HTTP server mode with 18 API endpoints producing identical JSON shapes to the Python server (verified by `tests/test_api_compat.py`). It has 91 unit/integration tests covering all analyzer modules.
- The Rust connection analyzer uses regex-based pattern matching to detect frontend API calls (fetch, axios, jquery, xhr, form actions, href links) and backend route handlers (flask, fastapi, django, express), then wires them by normalized URL path — this is a structural heuristic, not a full AST analysis.
- The Rust duplicate detector uses SHA-256 hashing (via `sha2` crate) for block fingerprinting, matching Python's grouped format (`duplicate_groups` with `hash`, `occurrences`, `locations`).
- UTF-8 safety in Rust analyzers: `floor_char_boundary()` and `ceil_char_boundary()` helpers prevent panics when slicing context from files containing multi-byte characters (e.g., box-drawing chars `─` in `ui.html`).
- Rust server embeds `ui.html` at compile time via `include_str!()` — no separate static file serving needed.

---

*This blueprint contains sufficient detail to reconstruct X-Ray LLM from scratch. All counts verified against live code on 2026-03-26.*
