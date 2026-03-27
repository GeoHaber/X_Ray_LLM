# X-Ray LLM — Copilot Instructions

You are working inside the **X-Ray LLM** project — a self-improving code quality agent
that scans codebases for security vulnerabilities, quality issues, Python-specific bugs,
and portability problems.

## CRITICAL: Transpilation Philosophy — Python Is the Source of Truth

The **entire purpose** of X-Ray LLM is:

```
Python code → Analyze → Simplify → Fix → Transpile to Rust (for speed & security)
```

**Rules for the Rust scanner (`scanner/src/`):**
1. **Python is always the source of truth.** Every Rust module is a direct transpilation of its Python counterpart.
2. **Never write Rust from scratch.** Always read the corresponding Python file first, then faithfully convert its logic to Rust.
3. **JSON response shapes must be identical.** The Rust server's API responses must match the Python server's responses field-for-field (verified by `tests/test_api_compat.py`).
4. **When Python changes, Rust must follow.** If a Python analyzer gets a new feature, the Rust version must be updated to match.
5. **Do not "improve" or diverge.** The Rust code should mirror Python logic 1:1. Performance optimizations are fine only if they don't change behavior or output.

**Mapping:** Each Python file has a Rust counterpart:
| Python | Rust |
|--------|------|
| `analyzers/smells.py` | `scanner/src/analyzers/smells.rs` |
| `analyzers/health.py` | `scanner/src/analyzers/health.rs` |
| `analyzers/graph.py` | `scanner/src/analyzers/graph.rs` |
| `analyzers/connections.py` | `scanner/src/analyzers/connections.rs` |
| `analyzers/format_check.py` | `scanner/src/analyzers/format_check.rs` |
| `analyzers/detection.py` | `scanner/src/analyzers/detection.rs` |
| `analyzers/temporal.py` | `scanner/src/analyzers/temporal.rs` |
| `analyzers/security.py` | `scanner/src/analyzers/security.rs` |
| `analyzers/pm_dashboard.py` | `scanner/src/analyzers/pm_dashboard.rs` |
| `services/satd_scanner.py` | `scanner/src/analyzers/satd.rs` |
| `services/git_analyzer.py` | `scanner/src/analyzers/git_analyzer.rs` |
| `xray/scanner.py` | `scanner/src/lib.rs` |
| `xray/fixer.py` | `scanner/src/fixer.rs` |
| `xray/sarif.py` | `scanner/src/sarif.rs` |
| `xray/constants.py` | `scanner/src/constants.rs` |
| `xray/types.py` | `scanner/src/types.rs` |
| `api/*_routes.py` | `scanner/src/server/routes.rs` |
| `ui_server.py` | `scanner/src/server/mod.rs` |

## IMPORTANT: Read the Full Guide First

Before answering ANY question about X-Ray LLM's features, capabilities, rules, API endpoints,
analyzers, PM Dashboard, auto-fixers, UI views, or architecture:

**You MUST read `X_RAY_LLM_GUIDE.md`** in the project root. It is the single source of truth
(19 sections) covering everything the tool can do.

## Quick Reference

- **42 scan rules**: 14 Security (SEC-001–014), 13 Quality (QUAL-001–013), 11 Python (PY-001–011), 4 Portability (PORT-001–004)
- **7 deterministic auto-fixers**: SEC-003, SEC-009, QUAL-001, QUAL-003, QUAL-004, PY-005, PY-007
- **5 AST validators**: Reduce false positives for PY-001, PY-005, PY-006, QUAL-003, QUAL-004
- **Dual engines**: Python scanner (`xray/scanner.py`) + Rust scanner (`scanner/src/`, 18 source files)
- **Rust server**: Full HTTP server mode (`--serve --port 8078`) with **18/18 API endpoint parity** (verified by `tests/test_api_compat.py`)
- **Web UI**: `ui.html` served by `ui_server.py` on port 8077 — 28+ views
- **45 API endpoints** (Python): All under `http://127.0.0.1:8077/api/`
- **18 API endpoints** (Rust): Under `http://127.0.0.1:8078/api/` — identical JSON shapes
- **23+ analyzer functions**: In `analyzers/` package — dead code, smells, duplicates, formatting, type checking, PM Dashboard
- **9 PM Dashboard features**: Risk Heatmap, Module Cards, Confidence Meter, Sprint Batches, Architecture Map, Call Graph, Circular Calls, Coupling, Unused Imports
- **Agent loop**: `python -m xray.agent /path --fix` for SCAN→TEST→FIX→VERIFY→LOOP cycle
- **Grading**: A (90+) through F (0-29), with letter grades and weighted severity scoring

## Key Files

| File | Purpose |
|------|---------|
| `X_RAY_LLM_GUIDE.md` | Complete feature guide (READ THIS) |
| `ui_server.py` | Thin HTTP dispatcher + route tables |
| `ui.html` | Single-page web UI |
| `analyzers/` | 11-module package: 23+ analysis functions |
| `services/` | Business logic: app state, scan manager, git, chat, SATD |
| `api/` | 5 route modules: scan, fix, analysis, PM, browse |
| `xray/scanner.py` | Python scanning engine (string/comment-aware + AST validators) |
| `xray/compat.py` | Python/dependency/API/PyPI freshness checker |
| `xray/fixer.py` | Auto-fixers (7 deterministic + LLM) |
| `xray/agent.py` | CLI agent loop orchestrator |
| `xray/llm.py` | Local LLM inference |
| `xray/constants.py` | Shared constants (SKIP_DIRS, file extensions) |
| `xray/types.py` | TypedDict definitions for API responses |
| `scanner/src/` | Rust scanner: 18 source files, 42 rules, HTTP server, analyzers |
| `tests/` | 1153+ Python tests (24 files, pytest) + 91 Rust tests — includes `test_api_compat.py` |

## Coding Conventions

- Python 3.10+, no type: ignore without justification
- All API routes return JSON with consistent error structure
- UI state management via `AppState` object in `ui.html`
- Tests use pytest; run with `pytest tests/ -v`
- Rust server JSON shapes must match Python (verified by `tests/test_api_compat.py`)
- Rust build: always use `--target x86_64-pc-windows-msvc` on Windows
