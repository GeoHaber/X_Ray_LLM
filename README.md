# X-Ray LLM

Self-improving code quality agent.  **SCAN → TEST → FIX → VERIFY → LOOP**

Built from real bugs discovered in production projects — not synthetic patterns.

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
```

## Toolchain

X-Ray LLM v0.3.0+ uses the **Astral toolchain** for fast, Rust-based analysis:

| Tool | Version | Purpose |
|------|---------|---------|
| [uv](https://docs.astral.sh/uv/) | 0.10+ | Package & tool manager (optional but recommended) |
| [ruff](https://docs.astral.sh/ruff/) | 0.15+ | Linter + formatter (replaces flake8/black/isort) |
| [ty](https://docs.astral.sh/ty/) | 0.0.23+ | Type checker (replaces pyright) |

```bash
python setup_tools.py          # Bootstrap all three tools
python update_tools.py --check # Show current versions
python update_tools.py         # Update all tools to latest
```

## Architecture

```
  ┌───────────┐
  │   SCAN    │  38 rules (security / quality / python)
  └─────┬─────┘  Python regex scanner (38 rules) + Rust scanner (28 rules)
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

## Pattern Rules (38 total)

| Category | Count | Examples |
|----------|-------|---------|
| Security | 14 | XSS, SQL injection, command injection, SSRF, eval, secrets, deserialization, path traversal, timing attacks, debug mode, weak hash, TLS bypass |
| Quality | 13 | Bare except, silent swallow, unchecked int(), non-daemon threads, TODO markers, broad Exception, string concat in loops, long lines |
| Python | 11 | Wildcard imports, print debug, JSON without try, global mutation, os.environ[], captured-but-ignored exception, sys.exit in lib, long isinstance |

All rules sourced from real bugs found in real projects.

> **Note:** The Python scanner implements all 38 rules. The Rust scanner currently has
> the original 28 rules; run `python generate_rust_rules.py` to sync the 10 new rules.

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

```bash
cd scanner
cargo build --release
./target/release/xray-scanner /path/to/project --json
```

## License

MIT
