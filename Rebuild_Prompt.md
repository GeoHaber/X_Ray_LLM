# X-Ray LLM — Rebuild Prompt (Self-Contained Blueprint)

**Purpose:** This document enables any LLM to rebuild the entire X-Ray LLM project from zero with perfect fidelity.

---

## 1. Project Overview

X-Ray LLM is a self-improving code quality agent that scans Python/JS/HTML codebases for security vulnerabilities, quality issues, Python-specific bugs, and portability problems using 42 regex-based pattern rules sourced from real production bugs.

**Core loop:** SCAN -> TEST -> FIX -> VERIFY -> LOOP

**Key capabilities:**
- 42 pattern-based scan rules (14 Security, 13 Quality, 11 Python, 4 Portability)
- 7 deterministic auto-fixers (no LLM needed)
- 3 AST-based false positive validators
- Web UI (single-page app on port 8077) with 28+ views
- 31+ REST API endpoints
- 23+ analyzer functions (dead code, smells, duplicates, coupling, etc.)
- 9 PM Dashboard features
- SARIF + JSON + text output
- Optional Rust scanner (28 rules, ~10x faster)
- LLM-powered test generation and fix generation via llama-cpp-python

## 2. Folder Structure

```
X_Ray_LLM/
+-- pyproject.toml
+-- ui_server.py
+-- ui.html
+-- build.py
+-- setup_tools.py
+-- update_tools.py
+-- generate_rust_rules.py
+-- README.md
+-- X_RAY_LLM_GUIDE.md
+-- Dockerfile
+-- docker-compose.yml
+-- MANIFEST.in
+-- xray/
|   +-- __init__.py
|   +-- __main__.py
|   +-- scanner.py       (pattern scanner engine, ~500 lines)
|   +-- agent.py          (agent loop orchestrator, ~300 lines)
|   +-- fixer.py          (7 deterministic fixers, ~400 lines)
|   +-- llm.py            (LLM inference, ~200 lines)
|   +-- runner.py          (pytest runner, ~100 lines)
|   +-- sarif.py          (SARIF output, ~150 lines)
|   +-- config.py          (pyproject.toml config, ~100 lines)
|   +-- constants.py      (shared constants, ~50 lines)
|   +-- types.py          (TypedDict definitions, ~200 lines)
|   +-- compat.py          (version/dep checker, ~300 lines)
|   +-- sca.py            (pip-audit integration, ~100 lines)
|   +-- wire_connector.py  (web framework wiring, ~200 lines)
|   +-- portability_audit.py
|   +-- rules/
|       +-- __init__.py    (exports ALL_RULES = 42 total)
|       +-- security.py    (SEC-001 to SEC-014)
|       +-- quality.py      (QUAL-001 to QUAL-013)
|       +-- python_rules.py (PY-001 to PY-011)
|       +-- portability.py  (PORT-001 to PORT-004)
+-- analyzers/
|   +-- __init__.py        (re-exports all 23+ functions)
|   +-- _shared.py          (helpers: _walk_py, _walk_ext, _safe_parse)
|   +-- format_check.py    (check_format, check_types)
|   +-- health.py          (check_project_health, estimate_remediation_time)
|   +-- security.py        (run_bandit)
|   +-- smells.py          (detect_dead_functions, detect_code_smells, detect_duplicates)
|   +-- temporal.py        (analyze_temporal_coupling)
|   +-- detection.py        (detect_ai_code, detect_web_smells, generate_test_stubs)
|   +-- pm_dashboard.py    (risk heatmap, module cards, confidence, sprint batches, etc.)
|   +-- graph.py            (detect_circular_calls, compute_coupling_metrics, detect_unused_imports)
|   +-- connections.py      (analyze_connections)
+-- services/
|   +-- __init__.py
|   +-- app_state.py        (thread-safe singleton)
|   +-- scan_manager.py    (scan orchestration, browse, Python/Rust engines)
|   +-- git_analyzer.py    (git hotspots, import parsing, ruff integration)
|   +-- chat_engine.py      (knowledge chatbot)
|   +-- satd_scanner.py    (tech debt scanning)
+-- api/
|   +-- __init__.py
|   +-- scan_routes.py      (/api/scan, /api/abort, /api/scan-progress, /api/scan-result)
|   +-- fix_routes.py      (/api/preview-fix, /api/apply-fix, /api/apply-fixes-bulk)
|   +-- analysis_routes.py  (19 analysis POST endpoints)
|   +-- pm_routes.py        (13 PM Dashboard + utility endpoints)
|   +-- browse_routes.py    (/api/browse, /api/info, /api/env-check)
+-- tests/                  (22 test files, 1013 tests total)
|   +-- __init__.py
|   +-- test_xray.py
|   +-- test_verify.py
|   +-- test_ui_paths.py
|   +-- test_e2e_real.py
|   +-- test_comprehensive.py
|   +-- test_monkey.py
|   +-- (plus 16 more test files)
+-- scanner/                (optional Rust scanner)
|   +-- Cargo.toml
|   +-- src/
|       +-- main.rs
|       +-- lib.rs
|       +-- rules/
+-- docs/
    +-- TESTING.md
```

## 3. Key Architectural Patterns

### Rule Structure
Each rule is a dict:
```python
{
    "id": "SEC-003",
    "severity": "HIGH",
    "pattern": r"subprocess\.\w+\(.*shell\s*=\s*True",
    "description": "Command injection: shell=True in subprocess call",
    "fix_hint": "Use shell=False and pass args as a list",
    "test_hint": "Create a file with subprocess.run(..., shell=True) and verify it fires",
    "lang": ["python"],
}
```

### Scanner Architecture
1. Walk directory, skip SKIP_DIRS (__pycache__, .git, node_modules, venv, etc.)
2. Detect language by extension (.py=python, .js/.ts=javascript, .html=html)
3. For each file, build non-code ranges (string literals + comments)
4. Apply each applicable rule's regex pattern against file content
5. Suppress matches inside strings/comments for string-aware rules
6. Run AST validators for PY-001, PY-005, PY-006
7. Check inline suppressions (# xray: ignore[RULE-ID])
8. Return list of Finding objects

### Web Server Architecture
- ThreadingMixIn + HTTPServer on port 8077
- Route dispatch via GET_ROUTES and POST_ROUTES dicts mapping paths to handler functions
- Background scans via daemon threads with progress polling
- AppState singleton for thread-safe state
- CORS optional via XRAY_CORS_ORIGIN env var
- Browse restriction via XRAY_BROWSE_ROOTS env var

### Fixer Architecture
- 7 deterministic fixers keyed by rule ID in FIXERS dict
- Each fixer receives (filepath, line_num, matched_text, lines) and returns FixResult
- Backup (.bak) created before writing
- Bulk fix processes files bottom-up to preserve line numbers

## 4. Dependencies

```toml
[project]
requires-python = ">=3.10"
dependencies = ["llama-cpp-python>=0.3.0", "pytest>=7.0"]

[project.optional-dependencies]
dev = ["ruff>=0.15", "ty>=0.0.1"]
```

## 5. Build & Run Commands

```bash
# Install
pip install -e ".[dev]"

# Run web UI
python ui_server.py

# Run tests
python -m pytest tests/ -v --tb=short

# Lint
python -m ruff check .

# Format
python -m ruff format .

# CLI scan
python -m xray /path/to/project --dry-run

# SARIF output
python -m xray /path/to/project --format sarif -o results.sarif
```

## 6. Test Strategy

- 22 test files, 1013 tests
- No mocks for core scanner/fixer tests (test_e2e_real.py)
- SHA-256 verification that scanning never modifies files (test_verify.py)
- Every rule tested with trigger sample AND safe-code sample
- HTTP integration tests boot a real server
- AST validator tests verify false positive suppression
- Fixer regression tests verify fixes produce valid Python and don't break code

---

*This blueprint contains sufficient detail to reconstruct X-Ray LLM from scratch.*
