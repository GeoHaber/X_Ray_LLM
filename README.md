# X-Ray LLM

Self-improving code quality agent.  **SCAN → TEST → FIX → VERIFY → LOOP**

Built from real bugs discovered in production projects — not synthetic patterns.

### Core Philosophy: Python → Rust Transpilation

```
Python code → Analyze → Simplify → Fix → Transpile to Rust (for speed & security)
```

The Rust scanner is a **faithful transpilation** of the Python codebase — not a rewrite.
Python is **always** the source of truth. See `X_RAY_LLM_GUIDE.md` § 1 for full rules.

## Quick Start

```bash
# First-time setup (installs uv, ruff, ty)
python setup_tools.py

# Start the Web UI (no LLM required)
python ui_server.py                   # Open http://127.0.0.1:8077

# Scan only (CLI)
python -m xray /path/to/project --dry-run

# SARIF output (GitHub Code Scanning compatible)
python -m xray /path/to/project --format sarif -o results.sarif

# JSON output
python -m xray /path/to/project --format json -o results.json

# Scan with auto-fix (requires a GGUF model)
export XRAY_MODEL_PATH=/path/to/model.gguf
python -m xray /path/to/project --fix

# High-severity only, incremental (skip unchanged files)
python -m xray /path/to/project --severity HIGH --incremental

# Show only new findings vs a baseline
python -m xray /path/to/project --baseline previous_scan.json

# Taint-aware scan (less noise on injection/SSRF/path traversal)
python -m xray /path/to/project --taint-mode lite

# Policy profile tuning
python -m xray /path/to/project --policy-profile strict
```

## New in v0.5 (2026-04-03)

- **21 JavaScript/TypeScript rules** — security (innerHTML XSS, eval, document.write, localStorage secrets, prototype pollution), React (dangerouslySetInnerHTML, stale state, missing AbortController), quality (empty catch, console.log, var declarations, loose equality), dead code (unused React imports)
- **7 new analyzers:**
  - **Orphan Map** — bidirectional UI↔Backend connectivity audit with Mermaid diagrams
  - **Schema Drift** — detects mismatches between Pydantic models and frontend field usage
  - **Coverage Map** — maps tested vs untested endpoints, functions, and components
  - **Smart Test Gen** — generates targeted pytest tests from schema drift, orphan map, and coverage gaps
  - **Design Review** — LLM-powered (with rule-based fallback) architecture review
  - **Contract Verify** — validates code against YAML/JSON design contracts
  - **File Watcher** — polling-based incremental scan on file changes
- **GitHub Actions CI** — `.github/workflows/xray-scan.yml` with SARIF upload and PR commenting
- **Total: 63 rules, 29 API endpoints, 7 auto-fixers**



- Taint modes for SEC-004/SEC-005/SEC-010:
      - `--taint-mode off|lite|strict`
- Policy profiles:
      - `--policy-profile strict|balanced|relaxed-tests`
- UI settings now include Policy + Taint controls.
- UI includes multilingual labels (EN/ES/FR) for key scan flows.
- If Rust is requested with non-default policy/taint behavior, scan execution
      falls back to Python scanner for parity. The UI now shows this explicitly with
      an engine switch badge.

## Migration Notes (v0.4.3 -> v0.4.4)

If you are upgrading from `v0.4.3`, review these behavior updates:

1. New scan controls are available and optional:
      - `--taint-mode off|lite|strict`
      - `--policy-profile strict|balanced|relaxed-tests`

2. Defaults preserve the previous baseline behavior for most users:
      - `taint_mode=lite`
      - `policy_profile=balanced`

3. Rust execution fallback is now explicit when parity requires Python scanner:
      - Trigger condition: Rust requested + non-default policy/taint behavior
      - UI now displays an engine switch badge during scan

4. CI pipelines using wrapper test execution no longer require pytest-timeout plugin:
      - Test runner retries without `--timeout` when plugin support is unavailable

5. Suggested upgrade check command:

```bash
python -m xray . --dry-run --severity HIGH --policy-profile strict --taint-mode lite --format json
```

6. If your team previously tuned suppression comments heavily, start with:
      - `--taint-mode strict` for higher sensitivity and compare output before adopting `lite`.

## Toolchain

X-Ray LLM v0.3.0+ uses the **Astral toolchain** for fast, Rust-based analysis:

| Tool | Version | Purpose |
|------|---------|---------|
| [uv](https://docs.astral.sh/uv/) | 0.11+ | Package & tool manager (optional but recommended) |
| [ruff](https://docs.astral.sh/ruff/) | 0.15+ | Linter + formatter (replaces flake8/black/isort) |
| [ty](https://docs.astral.sh/ty/) | 0.0.23+ | **Primary** type checker (replaces pyright) |

```bash
python setup_tools.py          # Bootstrap all three tools
python update_tools.py --check # Show current versions
python update_tools.py         # Update all tools to latest
```

## Architecture

```
  ┌───────────┐
  │   SCAN    │  63 rules (security / quality / python / portability / javascript)
  └─────┬─────┘  Python regex scanner (63 rules) + Rust scanner (42 rules, 102 tests)
        │
  ┌─────▼─────┐
  │   TEST    │  Auto-generate pytest tests for each finding
  └─────┬─────┘  via local LLM (Qwen2.5-Coder, DeepSeek, Codestral)
        │
  ┌─────▼─────┐
  │    FIX    │  Generate minimal, targeted fixes
  └─────┬─────┘  LLM generates patch → runner verifies
        │
  ┌─────▼─────┐
  │  VERIFY   │  Run full test suite
  └─────┬─────┘  Confirm fix doesn't break anything
        │
  ┌─────▼─────┐
  │   LOOP    │  Re-scan → still findings? → retry (max 3)
  └─────┬─────┘
        │
  ┌─────▼─────┐
  │  REPORT   │  JSON summary + human-readable output
  └───────────┘
```

## Pattern Rules (63 total)

| Category | Count | Examples |
|----------|-------|---------|
| Security | 14 | XSS, SQL injection, command injection, SSRF, eval, secrets, deserialization, path traversal, timing attacks, debug mode, weak hash, TLS bypass |
| Quality | 13 | Bare except, silent swallow, unchecked int(), non-daemon threads, TODO markers, broad Exception, string concat in loops, long lines |
| Python | 11 | Wildcard imports, print debug, JSON without try, global mutation, os.environ[], captured-but-ignored exception, sys.exit in lib, long isinstance |
| Portability | 4 | Hardcoded user paths, hardcoded C:\AI\ paths, Windows-only imports without guards |
| JS Security | 8 | innerHTML XSS, document.write, eval(), localStorage secrets, postMessage wildcard, prototype pollution, CSRF, dynamic Function() |
| JS React | 4 | dangerouslySetInnerHTML, useEffect missing cleanup, unstable useState, stale state closure |
| JS Quality | 8 | Empty .catch(), async without try/catch, console.log, loose equality, var usage, TODO markers, zero-delay timers, re-throw without cause |
| JS Dead Code | 1 | Unused React imports |

All rules sourced from real bugs found in real projects.

## False-Positive Elimination Pipeline (v0.4.3)

X-Ray uses a **4-stage validation pipeline** to suppress false positives without losing real findings:

```
Pattern Match → String-Aware Filter → AST Validator → Context Validator → Inline Suppression
```

| Stage | Scope | Validators |
|-------|-------|------------|
| String-Aware | 6 rules | Suppresses matches inside strings/comments (PY-004, PY-006, PY-007, SEC-007, QUAL-007, QUAL-010) |
| AST Validators | 7 validators | Python AST analysis — `Image.open()`, binary mode, `encoding=` kwarg, argparse `float()`, test files, `os.environ` setting |
| Context Validators | 6 validators | Language-agnostic — multi-line sanitizer search (SEC-001/002), parameterized SQL (SEC-004), localhost URLs (SEC-005), RegExp `.exec()` (SEC-007), try/catch search (QUAL-010) |
| Inline Suppression | All rules | `# xray: ignore[RULE-ID]` comments |

Real-world result: **29% FP reduction** on ZenAIos-Dashboard (763 → 542 findings, 221 false positives eliminated).

### Signal Controls (v0.4.4)

X-Ray now supports two orthogonal controls for finding quality:

- **Taint mode** (depth of source-to-sink filtering):
      - `off`: regex/context findings only
      - `lite`: suppresses low-signal non-tainted matches for selected security rules
      - `strict`: preserves broader context-validated matches
- **Policy profile** (environment tuning):
      - `strict`: maximum sensitivity
      - `balanced`: default behavior
      - `relaxed-tests`: reduces expected noise in test paths

> **Note:** The Python scanner implements all 63 rules. The Rust scanner implements 42 core rules.
> Both scanners provide full HTTP server mode — Python with **29 API endpoints**,
> Rust with **38 API endpoints** (36/36 verified by `tests/test_dual_server.py`).

### Integration Analyzers (v0.5)

| Analyzer | Endpoint | What It Does |
|----------|----------|--------------|
| Orphan Map | `/api/orphan-map` | Bidirectional UI↔Backend orphan detection with Mermaid diagrams |
| Schema Drift | `/api/schema-drift` | Pydantic model vs frontend field mismatch detection |
| Coverage Map | `/api/coverage-map` | Maps tested vs untested endpoints, functions, components |
| Smart Test Gen | `/api/smart-test-gen` | Generates targeted pytest tests from analysis results |
| Design Review | `/api/design-review` | LLM-powered or rule-based architecture review |
| Contract Verify | `/api/contract-verify` | Validates code against YAML/JSON design contracts |
| Integration Tests | `/api/integration-tests` | Generates API endpoint integration tests |
| Watch Mode | `/api/watch-start` | File watcher with incremental scanning |

## Recommended Models

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| Qwen2.5-Coder-32B-Q4_K_M | 19 GB | ★★☆ | ★★★ |
| DeepSeek-Coder-V2-Lite | 9 GB | ★★★ | ★★☆ |
| Codestral-22B-Q4_K_M | 13 GB | ★★☆ | ★★★ |

## Self-Test

X-Ray scans its own codebase as part of CI:

```bash
python -m pytest tests/ -v
```

## Cross-Platform Launchers

```bash
# Windows
Run_me.bat

# Linux / macOS
chmod +x run.sh && ./run.sh
```

Both launchers use `uv run` when available, falling back to plain `python`.

## Rust Scanner (optional speed boost)

The Rust scanner is a standalone ~4.9 MB binary with **full API parity** — 36/36 REST
endpoints produce identical JSON shapes to the Python server (verified by `tests/test_dual_server.py`).

```bash
# Build
cd scanner
cargo build --release
cd ..

# CLI scan mode
./scanner/target/release/xray-scanner /path/to/project --json

# HTTP server mode (full REST API + web UI)
./scanner/target/release/xray-scanner --serve --port 8078
# Open http://127.0.0.1:8078

# Validate Rust↔Python API parity (both servers must be running)
python tests/test_api_compat.py --py-port 8077 --rs-port 8078 --scan-dir /path

# Exhaustive 36-endpoint dual-server comparison (both servers must be running)
python -m pytest tests/test_dual_server.py -v
```

Includes: 42 scan rules, 7 auto-fixers, 38 REST endpoints, 102 unit/integration tests,
code analyzers (smells, dead code, duplicates, coupling, connections, health), and the full web UI.

## Portfolio Scan Results (v0.5, 19 repos)

```
Total files scanned:   2,836 (production only, tests excluded)
Total findings:       10,997
  HIGH:                 464
  MEDIUM:             4,109
  LOW:                6,450
Auto-fixed:              28
Smart tests generated: 1,078 (schema: 188, orphan: 193, coverage: 697)
```

## License

MIT
