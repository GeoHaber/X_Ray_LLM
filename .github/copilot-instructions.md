# X-Ray LLM — Copilot Instructions

You are working inside the **X-Ray LLM** project — a self-improving code quality agent
that scans codebases for security vulnerabilities, quality issues, and Python-specific bugs.

## IMPORTANT: Read the Full Guide First

Before answering ANY question about X-Ray LLM's features, capabilities, rules, API endpoints,
analyzers, PM Dashboard, auto-fixers, UI views, or architecture:

**You MUST read `X_RAY_LLM_GUIDE.md`** in the project root. It is the single source of truth
(857 lines, 19 sections) covering everything the tool can do.

## Quick Reference

- **28 scan rules**: 10 Security (SEC-001 to SEC-010), 10 Quality (QUAL-001 to QUAL-010), 8 Python (PY-001 to PY-008)
- **7 deterministic auto-fixers**: SEC-003, SEC-009, QUAL-001, QUAL-003, PY-001, PY-002, PY-003
- **Dual engines**: Python scanner (`xray/scanner.py`) + optional Rust scanner (`scanner/src/`)
- **Web UI**: `ui.html` served by `ui_server.py` on port 8077 — 25+ views
- **31 API endpoints**: All under `http://127.0.0.1:8077/api/`
- **18 analyzer functions**: In `analyzers.py` — dead code, smells, duplicates, formatting, type checking, PM Dashboard
- **6 PM Dashboard features**: Risk Heatmap, Module Cards, Confidence Meter, Sprint Batches, Architecture Map, Call Graph
- **Agent loop**: `python -m xray.agent /path --fix` for SCAN→TEST→FIX→VERIFY→LOOP cycle
- **Grading**: A+ (0 issues) through F (21+), with letter grades and weighted severity scoring

## Key Files

| File | Purpose |
|------|---------|
| `X_RAY_LLM_GUIDE.md` | Complete feature guide (READ THIS) |
| `ui_server.py` | Web server + all API routes |
| `ui.html` | Single-page web UI |
| `analyzers.py` | 18 analysis functions |
| `xray/scanner.py` | Python scanning engine (string/comment-aware) |
| `xray/compat.py` | Python/dependency/API compatibility checker |
| `xray/fixer.py` | Auto-fixers (7 deterministic + LLM) |
| `xray/agent.py` | CLI agent loop orchestrator |
| `xray/llm.py` | Local LLM inference |
| `tests/` | 673+ tests (pytest) |

## Coding Conventions

- Python 3.10+, no type: ignore without justification
- All API routes return JSON with consistent error structure
- UI state management via `AppState` object in `ui.html`
- Tests use pytest; run with `pytest tests/ -v`
- The Rust scanner is optional; Python scanner is the reference implementation
