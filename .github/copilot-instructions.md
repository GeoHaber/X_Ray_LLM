# X-Ray LLM — Copilot Instructions

You are working inside the **X-Ray LLM** project — a self-improving code quality agent
that scans codebases for security vulnerabilities, quality issues, Python-specific bugs,
and portability problems.

## IMPORTANT: Read the Full Guide First

Before answering ANY question about X-Ray LLM's features, capabilities, rules, API endpoints,
analyzers, PM Dashboard, auto-fixers, UI views, or architecture:

**You MUST read `X_RAY_LLM_GUIDE.md`** in the project root. It is the single source of truth
(19 sections) covering everything the tool can do.

## Quick Reference

- **42 scan rules**: 14 Security (SEC-001–014), 13 Quality (QUAL-001–013), 11 Python (PY-001–011), 4 Portability (PORT-001–004)
- **7 deterministic auto-fixers**: SEC-003, SEC-009, QUAL-001, QUAL-003, QUAL-004, PY-005, PY-007
- **3 AST validators**: Reduce false positives for PY-001, PY-005, PY-006
- **Dual engines**: Python scanner (`xray/scanner.py`) + optional Rust scanner (`scanner/src/`)
- **Web UI**: `ui.html` served by `ui_server.py` on port 8077 — 28+ views
- **31 API endpoints**: All under `http://127.0.0.1:8077/api/`
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
| `tests/` | 800+ tests (pytest) |

## Coding Conventions

- Python 3.10+, no type: ignore without justification
- All API routes return JSON with consistent error structure
- UI state management via `AppState` object in `ui.html`
- Tests use pytest; run with `pytest tests/ -v`
- The Rust scanner is optional; Python scanner is the reference implementation
