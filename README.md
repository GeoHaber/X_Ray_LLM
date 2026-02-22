# X-Ray — AI-Powered Code Quality Scanner & Rust Accelerator

**Version 5.1.0** · Python 3.10+ · 882 tests · 5 languages · MIT License

---

## What Is X-Ray?

X-Ray is a **two-phase code quality platform** that *diagnoses* problems in any
Python codebase, then helps you *cure* them — including automatically transpiling
performance-critical functions to Rust.

### Phase 1 — Diagnose (Scan & Grade)

A unified 4-tool scanner that produces a single **letter grade (A+ → F)**
from a 0–100 score:

| Tool | What It Checks |
|---|---|
| **Code Smells** | 12+ categories — long functions, god classes, deep nesting, high complexity, missing docstrings, boolean blindness, and more |
| **Duplicate Finder** | 4-stage pipeline: exact hash → structural hash → token n-gram + AST histogram → semantic similarity |
| **Ruff Lint** | Fast Python linting (unused imports, undefined names, bare-excepts, style issues) |
| **Bandit Security** | Security audit (hardcoded passwords, SQL injection, unsafe eval, subprocess misuse) |
| **Ruff Format** | Formatting check (`ruff format --check`) when available |
| **Library Advisor** | Groups duplicates and suggests shared library extractions with unified APIs |
| **Smart Graph** | Interactive HTML visualization with health-colored nodes and duplicate edges |

### Phase 2 — Cure (Rustify)

After X-Ray identifies the hot-path functions (high complexity, duplicate-heavy,
CPU-bound), it can **accelerate them with Rust** via a PyO3-based native module:

| Capability | Description |
|---|---|
| **Rust Core Module** | `x_ray_core` — PyO3 `.pyd`/`.so` that replaces Python hot-paths with zero-copy Rust |
| **Transparent Fallback** | Every Rust-accelerated function has a pure-Python fallback; set `X_RAY_DISABLE_RUST=1` to force Python-only mode |
| **10–50× Speedup** | Token normalization, n-gram fingerprinting, code similarity, batch matrix — all ported |
| **Parity Verified** | Golden-file test harness ensures Rust and Python produce identical outputs |
| **Transpilation Harness** | Framework for converting Python functions to Rust, compiling, and verifying correctness |

#### Ported Functions (Python → Rust)

| Python | Rust (`x_ray_core`) | Speedup |
|--------|---------------------|---------|
| `_normalized_token_stream` | `normalized_token_stream` | ~15× |
| `_ngram_fingerprints` | `ngram_fingerprints` | ~12× |
| `_token_ngram_similarity` | `token_ngram_similarity` | ~14× |
| `_ast_node_histogram` | `ast_node_histogram` | ~10× |
| `code_similarity` | `code_similarity` | ~18× |
| `cosine_similarity` | `cosine_similarity_map` | ~8× |
| `normalize_code` | `normalize_code` | ~20× |
| *(new)* | `batch_code_similarity` | ~50× (parallel via Rayon) |

### Key Design Principles

- **Zero external dependencies for core** — works with only Python stdlib
- **Rust acceleration is optional** — all features work without Rust installed
- **LLM enrichment is optional** — all detectors provide useful results without any LLM
- **Fast parallel scanning** — `concurrent.futures` for multi-file AST parsing
- **Unified grading** — single A+ → F grade combining all 4 tools
- **500+ tests** — comprehensive test suite with parity verification

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/GeoHaber/X_Ray.git
cd X_Ray

# Install (optional — core works with stdlib only)
pip install -r requirements.txt   # or: uv sync

### CLI

```bash
# Default scan (smells + lint + security)
python x_ray_claude.py --path /your/project

# Full 4-tool scan with unified grade
python x_ray_claude.py --full-scan --path /your/project

# Save JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project

# Rank functions for Rust porting
python x_ray_claude.py --rustify --path /your/project
```

<details>
<summary>All CLI flags</summary>

| Flag | Description |
|---|---|
| `--path` | Directory to scan (required) |
| `--smell` | Code smell detection only |
| `--duplicates` | Find similar/duplicate functions |
| `--lint` | Ruff linter only |
| `--security` | Bandit security only |
| `--full-scan` | Run all analyzers |
| `--rustify` | Score & rank functions for Rust porting |
| `--report FILE` | Save JSON report to file |
| `--graph` | Generate interactive HTML dependency graph |

</details>

---

## Analyzers

### Phase 1 — Diagnose

| Analyzer | What It Checks |
|---|---|
| **Code Smells** | 12+ categories — long functions, god classes, deep nesting, high cyclomatic complexity, missing docstrings, boolean blindness, too many params/returns/branches |
| **Duplicate Finder** | 4-stage pipeline: exact hash → structural hash → token n-gram + AST histogram → semantic similarity |
| **Ruff Lint** | Fast Python linting (unused imports, undefined names, bare-excepts, style) |
| **Bandit Security** | Security audit (hardcoded passwords, SQL injection, unsafe eval, subprocess) |
| **UI Compat** | AST-scans for UI framework calls (Flet, tkinter, PyQt, PySide, Kivy, wxPython, Dear PyGui), validates kwargs against live `inspect.signature()`, catches `TypeError` before runtime |

### Phase 2 — Cure (Rustify)

| Capability | Description |
|---|---|
| **Rust Advisor** | Scores every function for Rust-portability (purity, complexity, CPU intensity) |
| **AST Transpiler** | 2,259-line transpiler with 19 module handlers — `os`, `json`, `re`, `pathlib`, `time`, `datetime`, `subprocess`, `hashlib`, `argparse`, `collections`, `functools`, `itertools`, `logging`, `sys`, and more |
| **LLM Fallback** | When AST transpiler emits `todo!()` stubs, a local LLM completes them, then `rustc --check` validates |
| **Auto-Rustify Pipeline** | End-to-end: Scan → Score → Transpile → Cargo build → Verify |
| **Rust Core** | Optional `x_ray_core.pyd` (PyO3 + Rayon) replaces Python hot-paths with 10–50× speedup |

---

## Desktop GUI

The Flet GUI provides a native Material 3 experience:

- **Sidebar** — directory picker, 6 analyzer toggles, scan button, progress bar with file counter & ETA
- **9 Dashboard Tabs** — Smells · Duplicates · Lint · Security · Rustify · Heatmap · Complexity · Auto-Rustify · UI Compat
- **Theme** — light / dark mode toggle
- **Language** — switch between EN, RO, ES, FR, DE at runtime
- **Onboarding** — first-run stepper that walks through features
- **Export** — JSON and Markdown report export

---

## Grading Formula

The unified score is `100 − penalties`:

| Tool | Penalty Weights | Cap |
|---|---|---|
| Smells | critical × 0.25 + warning × 0.05 + info × 0.01 | 30 |
| Duplicates | groups × 0.1 | 15 |
| Lint | critical × 0.3 + warning × 0.05 + info × 0.005 | 25 |
| Security | critical × 1.5 + warning × 0.3 + info × 0.005 | 30 |

| Grade | Score |
|---|---|
| A+ | ≥ 97 |
| A | ≥ 93 |
| A− | ≥ 90 |
| B+ | ≥ 87 |
| B | ≥ 83 |
| B− | ≥ 80 |
| C | ≥ 70 |
| D | ≥ 60 |
| F | < 60 |

---

## Python → Rust Transpiler

The transpiler (`Analysis/transpiler.py`) converts Python functions to Rust via
proper `ast.parse` — no regex. It handles:

- Type inference, `match`/`if-let`, iterators, closures
- 19 stdlib module mappings (os, json, re, pathlib, datetime, subprocess, etc.)
- `async def` → `async fn`, `await` → `.await`
- Format strings, f-strings, tuple unpacking, attribute assignment
- Escape hatch: `todo!()` for unsupported patterns (filled by LLM fallback)

### Coverage (14 real projects)

| Stage | Transpilable | Rate |
|---|---|---|
| Pre-Tier 3 | 4,322 / 14,044 | 30.8 % |
| Post-Tier 3 + Threshold Tuning | 7,485 / 14,064 | 53.2 % |
| Post-Round 2 Fixes | 7,694 (6,917 clean compile) | 54.7 % |

### Optional Rust Core Module

The `x_ray_core.pyd` native extension accelerates hot-paths:

| Function | Speedup |
|---|---|
| `normalized_token_stream` | ~15× |
| `ngram_fingerprints` | ~12× |
| `code_similarity` | ~18× |
| `normalize_code` | ~20× |
| `batch_code_similarity` | ~50× (Rayon parallel) |

Build it:
```bash
cd Core/x_ray_core
pip install maturin
maturin develop --release
```

Runs without Rust installed — all functions have pure-Python fallbacks.

---

## Running Tests

```bash
pip install pytest

# Full suite (882 tests)
python -m pytest tests/ -q --tb=short

# Specific modules
python -m pytest tests/test_ui_compat.py -v         # 51 UI compat tests
python -m pytest tests/test_transpiler.py -v         # Transpiler tests
python -m pytest tests/test_analysis_smells.py -v    # Smell detector tests

# Rust parity
python -m pytest tests/verify_parity.py -v
```

---

## Project Structure

```
X_Ray/
├── x_ray_flet.py                # Flet desktop GUI (2,175 lines)
├── x_ray_claude.py              # Interactive CLI (598 lines)
├── x_ray_web.py                 # Streamlit web UI
├── x_ray_exe.py                 # Standalone exe entry point
│
├── Analysis/                    # Analyzers (20 modules)
│   ├── smells.py                #   Code smell detector (12+ categories)
│   ├── duplicates.py            #   4-stage duplicate finder
│   ├── similarity.py            #   Similarity metrics (Python + Rust paths)
│   ├── lint.py                  #   Ruff linter integration
│   ├── security.py              #   Bandit security scanner
│   ├── rust_advisor.py          #   Rust porting candidate scorer
│   ├── transpiler.py            #   AST Python→Rust transpiler (2,259 lines)
│   ├── llm_transpiler.py        #   LLM fallback transpiler (426 lines)
│   ├── auto_rustify.py          #   End-to-end pipeline (1,657 lines)
│   ├── ui_compat.py             #   UI API compatibility checker (497 lines)
│   ├── reporting.py             #   ASCII + JSON + grading
│   ├── library_advisor.py       #   Shared library suggestions
│   ├── smart_graph.py           #   Interactive HTML graph
│   ├── semantic_fuzzer.py       #   Semantic fuzz testing
│   └── ...
│
├── Core/                        # Infrastructure
│   ├── types.py                 #   FunctionRecord, ClassRecord, SmellIssue, Severity
│   ├── config.py                #   Thresholds, version, constants
│   ├── i18n.py                  #   Internationalization (5 languages)
│   ├── scan_phases.py           #   Shared scan phase runners
│   ├── inference.py             #   Local LLM helper
│   ├── llm_manager.py           #   LLM settings persistence
│   ├── cli_args.py              #   Argument parsing
│   └── x_ray_core/              #   Rust source (PyO3 + Rayon)
│       ├── Cargo.toml
│       └── src/lib.rs
│
├── Lang/                        # Language support
│   ├── python_ast.py            #   Python AST parser + parallel scanner
│   └── tokenizer.py             #   Token-level similarity
│
├── tests/                       # 882 tests
│   ├── test_analysis_*.py       #   Per-analyzer tests
│   ├── test_ui_compat.py        #   UI compat tests (51)
│   ├── test_transpiler.py       #   Transpiler tests
│   ├── test_xray_*.py           #   End-to-end + integration
│   ├── verify_parity.py         #   Python ↔ Rust parity
│   ├── harness_*.py             #   Test harness infrastructure
│   └── ...
│
├── scan_all_rustify.py          # Multi-project scan + transpile
├── verify_rust_compilation.py   # Cargo-check verification harness
├── CHANGELOG.md                 # Version history
└── docs/
    ├── USAGE.md                 # Detailed usage guide
    ├── FUTURE_PLAN.md           # Roadmap
    └── how_to_download_rust.md  # Rust installation guide
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│           x_ray_flet.py  /  x_ray_claude.py                    │
│              (GUI)             (CLI)                             │
└────────┬─────────────────────────┬──────────────────────────────┘
         │                         │
    ┌────▼─────────────────────────▼────┐
    │       Core/scan_phases.py         │
    │     Phase orchestrator + ETA      │
    └──┬───┬───┬───┬───┬───┬───────────┘
       │   │   │   │   │   │
    ┌──▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼──────────┐
    │ S ││ D ││ L ││ B ││ R ││ UI Compat │
    │ m ││ u ││ i ││ a ││ u ││           │
    │ e ││ p ││ n ││ n ││ s ││ Validates │
    │ l ││ l ││ t ││ d ││ t ││ UI kwargs │
    │ l ││ s ││   ││ i ││ i ││ vs. live  │
    │ s ││   ││   ││ t ││ f ││ signatures│
    │   ││   ││   ││   ││ y ││           │
    └───┘└───┘└───┘└───┘└───┘└───────────┘
       │         │                │
    ┌──▼─────────▼────────────────▼────┐
    │       Lang/ (AST + Tokenizer)    │
    └──────────────┬───────────────────┘
                   │
    ┌──────────────▼───────────────────┐
    │  Analysis/transpiler.py          │
    │  Python → Rust (AST-based)       │
    │      ↓ fallback ↓               │
    │  Analysis/llm_transpiler.py      │
    │  LLM fills todo!() stubs         │
    └──────────────┬───────────────────┘
                   │
    ┌──────────────▼───────────────────┐
    │  x_ray_core.pyd (optional)       │
    │  PyO3 + Rayon · 10–50× speedup   │
    └──────────────────────────────────┘
                   │
    ┌──────────────▼───────────────────┐
    │  Unified Grade (A+ → F)          │
    │  JSON / Markdown / HTML export   │
    └──────────────────────────────────┘
```

---

## Environment Variables

| Variable | Effect |
|---|---|
| `X_RAY_DISABLE_RUST=1` | Force pure-Python mode (skip Rust core) |
| `X_RAY_LLM_URL` | Override local LLM endpoint (default: `http://localhost:8080/v1`) |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run the test suite: `python -m pytest tests/ -q --tb=short`
4. Ensure zero Ruff warnings: `ruff check .`
5. Submit a pull request

---

*Scan it · Grade it · Rustify it*
