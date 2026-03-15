# X-Ray LLM

Self-improving code quality agent.  **SCAN → TEST → FIX → VERIFY → LOOP**

Built from real bugs discovered in production projects — not synthetic patterns.

## Quick Start

```bash
# Scan only (no LLM required)
python -m xray.agent /path/to/project --dry-run

# Scan with auto-fix (requires a GGUF model)
export XRAY_MODEL_PATH=/path/to/model.gguf
python -m xray.agent /path/to/project --fix

# High-severity only
python -m xray.agent /path/to/project --severity HIGH --dry-run
```

## Architecture

```
  ┌───────────┐
  │   SCAN    │  28 rules (security / quality / python)
  └─────┬─────┘  Python regex scanner + optional Rust scanner
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

## Pattern Rules (28 total)

| Category | Count | Examples |
|----------|-------|---------|
| Security | 10 | XSS, SQL injection, command injection, SSRF, eval, secrets, deserialization, path traversal |
| Quality | 10 | Bare except, silent swallow, unchecked int(), non-daemon threads, TODO markers |
| Python | 8 | Wildcard imports, print debug, JSON without try, global mutation, os.environ[] |

All rules sourced from real bugs found in real projects.

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

## Rust Scanner (optional speed boost)

```bash
cd scanner
cargo build --release
./target/release/xray-scanner /path/to/project --json
```

## License

MIT
