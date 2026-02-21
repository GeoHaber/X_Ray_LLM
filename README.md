# X-Ray — Smart AI-Powered Code Analyzer & Rustifier

**Version:** 5.0.0  
**License:** MIT  
**Python:** 3.10+  
**Rust:** Optional (for acceleration)

---

## What Is X-Ray?

X-Ray is a **two-phase code quality platform** that first *diagnoses* problems in
any Python codebase, then helps you *cure* them — including automatically
converting performance-critical paths to Rust.

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

# Basic scan (smells only)
python x_ray_claude.py --path /your/project

# Full 4-tool scan with unified grade
python x_ray_claude.py --full-scan --path /your/project

# Save JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project

# Generate interactive graph
python x_ray_claude.py --full-scan --graph --path /your/project
```

### Self-Scan Example

```bash
# X-Ray scanning itself
python x_ray_claude.py --path . --full-scan --report self_scan.json

# Output:
#   Score: 90.3/100  Grade: A-
#   Tools: X-Ray Smells, X-Ray Duplicates, Ruff Lint, Bandit Security
```

---

## Phase 2: Rustifying Your Code

X-Ray helps you accelerate hot paths with Rust. The workflow:

### Step 1: Identify Targets

Run X-Ray on your project and look for:
- **Complex functions** (CC ≥ 10) that do heavy computation
- **Hot-path duplicates** that appear in performance-critical loops
- **CPU-bound code** (tokenization, hashing, similarity matrices)

```bash
python x_ray_claude.py --full-scan --report analysis.json --path /your/project
# Review the JSON for functions with severity=CRITICAL or WARNING
```

### Step 2: Build the Rust Core Module

The `Core/x_ray_core/` directory contains the Rust source. Build it with
[maturin](https://github.com/PyO3/maturin):

```bash
cd Core/x_ray_core
pip install maturin
maturin develop --release    # Builds and installs x_ray_core.pyd into your venv
```

Or using cargo directly:

```bash
cargo build --release
# Copy target/release/x_ray_core.dll → x_ray_core.pyd into the project root
```

### Step 3: Verify Parity

Golden-file tests ensure Rust output exactly matches Python:

```bash
# Generate golden files from Python reference implementation
python tests/rust_harness/generate_golden.py

# Verify Rust matches Python
python tests/rust_harness/verify_rust.py

# Run parity test suite
python -m pytest tests/verify_parity.py -v
```

### Step 4: Benchmark

```bash
# Compare Python vs Rust performance
python run_benchmark.py

# Typical output:
#   Pure Python: 2.34s  →  Hybrid Rust: 0.16s  (14.6× faster)
```

### Step 5: Transparent Integration

No code changes needed. X-Ray automatically detects the Rust module:

```python
# In Analysis/similarity.py — automatic Rust detection
try:
    import x_ray_core as _rust_core
    _HAS_RUST = True      # Rust hot-paths used automatically
except ImportError:
    _HAS_RUST = False      # Falls back to pure Python
```

To force Python-only mode (useful for debugging):
```bash
set X_RAY_DISABLE_RUST=1   # Windows
export X_RAY_DISABLE_RUST=1 # Linux/macOS
```

---

## Rustifying Your Own Project

X-Ray's Rustification approach applies to any Python project:

1. **Scan** — `python x_ray_claude.py --full-scan --path /your/project`
2. **Prioritize** — Focus on functions flagged as complex + CPU-hot
3. **Port** — Rewrite in Rust with PyO3 (`#[pyfunction]`)
4. **Verify** — Generate golden files, run parity tests
5. **Benchmark** — Measure actual speedup
6. **Integrate** — `try: import rust_module` with Python fallback

### What Makes a Good Rust Candidate?

| ✅ Good Candidate | ❌ Poor Candidate |
|---|---|
| Tight loops over large data | I/O-bound code (HTTP, file reads) |
| String/token processing | Code with many Python library dependencies |
| Hash computation, similarity matrices | Simple glue code or config parsing |
| Batch operations on arrays | Code that changes frequently |
| CPU-bound with no GIL release | Small functions called rarely |

---

## Running Tests

```bash
pip install pytest

# Full test suite (500+ tests)
python -m pytest tests/ -v

# Quick run
python -m pytest tests/ -q --tb=short

# Rust-specific tests
python -m pytest tests/test_rust_smoke.py tests/verify_parity.py -v

# Benchmark Rust vs Python
python run_benchmark.py
```

---

## Project Structure

```
X_Ray/
├── x_ray_claude.py              # Main CLI — unified scanner + grading
├── x_ray_core.pyd               # Compiled Rust module (auto-detected)
├── README.md                    # This file
├── requirements.txt             # Dependencies
│
├── Analysis/                    # Analysis engines
│   ├── smells.py                #   Code smell detector (12+ categories)
│   ├── duplicates.py            #   4-stage duplicate finder
│   ├── similarity.py            #   Similarity metrics (Python + Rust paths)
│   ├── lint.py                  #   Ruff linter integration
│   ├── security.py              #   Bandit security scanner
│   ├── reporting.py             #   ASCII + JSON reporting + grading
│   ├── library_advisor.py       #   Shared library suggestions
│   ├── smart_graph.py           #   Interactive HTML graph
│   ├── ast_utils.py             #   AST extraction helpers
│   └── test_gen.py              #   Test input generator
│
├── Core/                        # Core infrastructure
│   ├── types.py                 #   Data types (FunctionRecord, SmellIssue, etc.)
│   ├── config.py                #   Thresholds, version, constants
│   ├── inference.py             #   LLM helper (optional)
│   ├── utils.py                 #   Logging, Rust environment check
│   └── x_ray_core/              #   Rust source (PyO3 + Rayon)
│       ├── Cargo.toml
│       └── src/lib.rs           #   861 lines of Rust (tokenizer, similarity, batch)
│
├── Lang/                        # Language support
│   ├── python_ast.py            #   Python AST parser + parallel scanner
│   └── tokenizer.py             #   Token-level similarity
│
├── tests/                       # 497 tests
│   ├── test_xray_claude.py      #   End-to-end + unit tests
│   ├── test_analysis_*.py       #   Per-module tests (smells, duplicates, lint, security)
│   ├── test_lang_*.py           #   AST + tokenizer tests
│   ├── test_core_*.py           #   Types + inference tests
│   ├── verify_parity.py         #   Python ↔ Rust parity verification
│   ├── test_rust_smoke.py       #   Rust module smoke tests
│   └── rust_harness/            #   Rust verification infrastructure
│       ├── generate_golden.py   #     Generate reference outputs
│       ├── verify_rust.py       #     Verify Rust matches Python
│       ├── benchmark.py         #     Performance comparison
│       ├── calibrate_fixtures.py#     Fixture calibration
│       └── fixtures/            #     Test fixture files
│
└── docs/
    ├── USAGE.md                 # Detailed usage guide
    └── FUTURE_PLAN.md           # Roadmap
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     CLI / main()                             │
│  --smell  --duplicates  --full-scan  --graph  --report       │
└──────┬──────────┬──────────┬─────────────┬───────────────────┘
       │          │          │             │
 ┌─────▼───┐ ┌───▼────┐ ┌───▼──────┐ ┌───▼──────┐
 │  Smell  │ │Duplicate│ │  Ruff    │ │ Bandit   │
 │Detector │ │ Finder  │ │ Lint     │ │ Security │
 └─────┬───┘ └───┬────┘ └───┬──────┘ └───┬──────┘
       │          │          │             │
 ┌─────▼──────────▼──────────▼─────────────▼──────────┐
 │         scan_codebase() — AST Engine                │
 │  ThreadPoolExecutor + ast.parse per file            │
 └──────────────────────┬──────────────────────────────┘
                        │
              ┌─────────▼─────────────┐
              │  similarity.py        │
              │  Python ←→ Rust paths │
              └─────────┬─────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  x_ray_core (Rust / PyO3)   │
         │  Rayon parallel batching    │
         │  10–50× acceleration        │
         └─────────────────────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  Unified Grading (A+ → F)   │
         │  JSON Report + Smart Graph  │
         └─────────────────────────────┘
```

---

## Grading Formula

The unified score is `100 − penalties`, where penalties come from all 4 tools:

| Tool | Weights | Cap |
|---|---|---|
| **Smells** | critical × 0.25 + warning × 0.05 + info × 0.01 | 30 |
| **Duplicates** | groups × 0.1 | 15 |
| **Lint** | critical × 0.3 + warning × 0.05 + info × 0.005 | 25 |
| **Security** | critical × 1.5 + warning × 0.3 + info × 0.005 | 30 |

| Grade | Score Range |
|---|---|
| A+ | ≥ 97 |
| A | ≥ 93 |
| A− | ≥ 90 |
| B+ | ≥ 87 |
| B | ≥ 83 |
| ... | ... |
| F | < 60 |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Install dev deps: `pip install -r requirements-dev.txt`
4. Run security audit: `pip-audit -r requirements.txt -r requirements-dev.txt`
5. Run type check: `pyright .`
6. Run the test suite: `python -m pytest tests/ -q --tb=short`
7. Submit a pull request

See [SECURITY.md](SECURITY.md) for dependency and code security practices.

---

## Documentation

| Doc | Description |
|-----|--------------|
| [docs/USAGE.md](docs/USAGE.md) | CLI options, smell categories, duplicate detection, programmatic API |
| [CI_CD_SETUP.md](CI_CD_SETUP.md) | GitHub Actions, pre-commit, quality gates |
| [docs/FUTURE_PLAN.md](docs/FUTURE_PLAN.md) | Roadmap and design philosophy |

---

*Built with AST heuristics + Rust acceleration + optional AI enrichment.  
Works on any Python codebase. Scan it, grade it, Rustify it.*
