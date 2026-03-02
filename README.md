# X-Ray — AI-Powered Universal Code Quality Scanner & Rust Accelerator

**Version 7.0.0** · Python 3.10+ · 905+ tests · Python + JS/TS/React · 5 languages · MIT License

---

## What Is X-Ray?

X-Ray is a **universal code quality platform** that *diagnoses* problems in
**Python, JavaScript, TypeScript, and React** codebases, then helps you *cure*
them — including auto-fixing smells, generating test suites, and transpiling
performance-critical Python functions to Rust.

It ships with a **Flet desktop GUI** (Material 3), an **interactive CLI**, and
a full **AST-based Python → Rust transpiler** verified against 14 real projects.

### At a Glance

| Feature | Details |
|---|---|
| 9 Analyzers | Code Smells · Duplicates · Ruff Lint · Bandit Security · **Web Smells** · **Project Health** · Rust Advisor · UI Compat · **Test Generator** |
| **JS/TS/React** | Full analysis of `.js`, `.ts`, `.jsx`, `.tsx` files — imports, functions, React components, 142 package mappings in 15 categories |
| Unified Grade | Single A+ → F score (0–100) combining all tools |
| Desktop GUI | Flet (Flutter engine), light/dark mode, 9 dashboard tabs |
| 5 Languages | English · Română · Español · Français · Deutsch |
| **Test Generator** | Auto-generates pytest (Python) or Vitest/Jest (JS/TS) test suites from scan data — import smoke, function, class, smell regression, structure tests |
| **Auto-Fix** | `--fix-smells` removes console.log, debug prints, creates missing project files |
| Rust Transpiler | AST-based, 19 module handlers, 54.7 % coverage across 14 projects |
| LLM Fallback | Local LLM fills `todo!()` stubs, validates with `rustc --check` |
| **UIBridge** | Swappable output layer — Flet, tqdm, Streamlit, NiceGUI, tests all use one bridge |
| 905+ Tests | Smoke, unit, integration, parity, fuzz, transpilation, bridge |
| Zero Core Deps | Core analyzers use only Python stdlib |

---

## Quick Start

```bash
git clone https://github.com/GeoHaber/X_Ray.git
cd X_Ray
pip install -r requirements.txt   # pytest only — core has zero deps
```

### Desktop GUI (recommended)

```bash
pip install flet
python x_ray_flet.py
```

The app opens a native window with a sidebar to pick a directory, toggle
analyzers on/off, and view results across 9 dashboard tabs.

### Standalone EXE (share with friends)

X-Ray ships as a portable `.exe` — no Python install required.
Double-click to launch the interactive wizard:

1. **Folder picker** — native Windows dialog to choose the project to scan
2. **Scan mode menu** — 7 options from quick lint to full scan + rustify
3. **Report prompt** — save JSON, print summary, or both

Build it yourself:
```bash
pip install pyinstaller
python -m PyInstaller x_ray.spec --noconfirm
# Output: dist/x_ray/x_ray.exe (~64 MB, includes ruff, bandit, tkinter, Rust core)
```

The `.exe` includes a **hardware-locked trial system** (10 runs per machine):
- Machine fingerprint → AES-256-GCM encrypted counter → HMAC-SHA256 integrity
- All crypto runs in compiled Rust (`x_ray_core.pyd`) — no Python-side secrets
- Counter stored at `%APPDATA%\x_ray\.xrl` (84 bytes, binary)
- Each new machine gets a fresh 10 runs, no server needed

CLI mode also works: `x_ray.exe --path C:\project --full-scan`

### CLI

```bash
# Default scan (smells + lint + security)
python x_ray_claude.py --path /your/project

# Full scan with unified grade (includes web smells + health checks)
python x_ray_claude.py --full-scan --path /your/project

# Save JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project

# Scan a JS/TS/React project
python x_ray_claude.py --full-scan --path /your/react-app

# Auto-generate test suite from scan data
python x_ray_claude.py --full-scan --gen-tests --path /your/project

# Auto-fix code smells (console.log, debug prints, missing files)
python x_ray_claude.py --full-scan --fix-smells --path /your/project

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
| `--full-scan` | Run all analyzers (auto-enables `--web` + `--health`) |
| `--web` | Web smell detection for JS/TS/React files |
| `--health` | Project structural health checks |
| `--fix-smells` | Auto-fix code smells (console.log, debug prints, missing files) |
| `--gen-tests` | Auto-generate test suite from scan analysis data |
| `--rustify` | Score & rank functions for Rust porting |
| `--report FILE` | Save JSON report to file |
| `--graph` | Generate interactive HTML dependency graph |

</details>

---

## Analyzers

### Phase 1 — Diagnose

| Analyzer | What It Checks |
|---|---|
| **Code Smells** | 15+ categories — long functions, god classes, deep nesting, high cyclomatic complexity, missing docstrings, boolean blindness, magic numbers, mutable defaults, dead code, too many params/returns/branches |
| **Duplicate Finder** | 4-stage pipeline: exact hash → structural hash → token n-gram + AST histogram → semantic similarity |
| **Ruff Lint** | Fast Python linting (unused imports, undefined names, bare-excepts, style) |
| **Bandit Security** | Security audit (hardcoded passwords, SQL injection, unsafe eval, subprocess) |
| **Web Smells** | JS/TS/React analysis — console.log pollution, `any` abuse, huge React components, missing error boundaries, mixed imports, inline styles, prop drilling, magic strings, nested ternaries |
| **Project Health** | 10 structural checks — README, LICENSE, .gitignore, tests dir, CI config, lock file, type config, linter config, docs, changelog |
| **UI Compat** | AST-scans for UI framework calls (Flet, tkinter, PyQt, PySide, Kivy, wxPython, Dear PyGui), validates kwargs against live `inspect.signature()`, catches `TypeError` before runtime |

### Phase 2 — Cure (Rustify)

| Capability | Description |
|---|---|
| **Rust Advisor** | Scores every function for Rust-portability (purity, complexity, CPU intensity) |
| **AST Transpiler** | 2,259-line transpiler with 19 module handlers — `os`, `json`, `re`, `pathlib`, `time`, `datetime`, `subprocess`, `hashlib`, `argparse`, `collections`, `functools`, `itertools`, `logging`, `sys`, and more |
| **LLM Fallback** | When AST transpiler emits `todo!()` stubs, a local LLM completes them, then `rustc --check` validates |
| **Auto-Rustify Pipeline** | End-to-end: Scan → Score → Transpile → Cargo build → Verify |
| **Rust Core** | Optional `x_ray_core.pyd` (PyO3 + Rayon) replaces Python hot-paths with 10–50× speedup |
| **Trial License** | AES-256-GCM + HMAC-SHA256 hardware-locked trial gate, compiled in Rust |

### Phase 3 — Generate (`--gen-tests`)

| Capability | Description |
|---|---|
| **Test Generator** | Reads X-Ray analysis data and auto-creates a test suite your project can run |
| **Python Tests** | Generates `pytest` files: import smoke, per-module function tests, class instantiation, smell regression, project structure validation |
| **JS/TS Tests** | Generates `Vitest`/`Jest` files: import smoke, per-file function tests, React component render tests, structure checks |
| **5 Test Categories** | Import Smoke · Function/Class Tests · Smell Regression · Structure · React Components |
| **Smell Fixer** | `--fix-smells` auto-comments `console.log` / debug `print()`, creates missing `.gitignore`, `LICENSE`, `package.json` |

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
| `prefilter_parallel` | ~30× (Rayon O(N²) pre-filter) |
| `check_trial` | AES-256-GCM trial gate |
| `trial_max_runs` | Returns max run count |

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

# Full suite (905 tests)
python -m pytest tests/ -q --tb=short

# Specific modules
python -m pytest tests/test_ui_compat.py -v         # 51 UI compat tests
python -m pytest tests/test_ui_bridge.py -v          # 23 UIBridge tests
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
├── x_ray_exe.py                 # Standalone exe (interactive wizard + trial license)
│
├── Analysis/                    # Analyzers (25 modules)
│   ├── smells.py                #   Code smell detector (15+ categories)
│   ├── duplicates.py            #   4-stage duplicate finder
│   ├── similarity.py            #   Similarity metrics (Python + Rust paths)
│   ├── lint.py                  #   Ruff linter integration + auto-fix
│   ├── security.py              #   Bandit security scanner
│   ├── web_smells.py            #   JS/TS/React web smell detector (NEW v7.0)
│   ├── project_health.py        #   Structural health checker (NEW v7.0)
│   ├── smell_fixer.py           #   Auto-fix engine for --fix-smells (NEW v7.0)
│   ├── test_generator.py        #   Test suite auto-generator (NEW v7.0)
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
│   ├── ui_bridge.py             #   UIBridge Protocol + PrintBridge/NullBridge/TqdmBridge
│   ├── inference.py             #   Local LLM helper
│   ├── llm_manager.py           #   LLM settings persistence
│   ├── cli_args.py              #   Argument parsing
│   └── x_ray_core/              #   Rust source (PyO3 + Rayon)
│       ├── Cargo.toml
│       └── src/lib.rs
│
├── Lang/                        # Language support
│   ├── python_ast.py            #   Python AST parser + parallel scanner
│   ├── js_ts_analyzer.py        #   JS/TS/JSX/TSX regex analyzer (NEW v7.0)
│   └── tokenizer.py             #   Token-level similarity
│
├── tests/                       # 905 tests
│   ├── test_analysis_*.py       #   Per-analyzer tests
│   ├── test_ui_bridge.py        #   UIBridge swappability tests (23)
│   ├── test_ui_compat.py        #   UI compat tests (51)
│   ├── test_transpiler.py       #   Transpiler tests
│   ├── test_xray_*.py           #   End-to-end + integration
│   ├── verify_parity.py         #   Python ↔ Rust parity
│   ├── harness_*.py             #   Test harness infrastructure
│   └── ...
│
├── x_ray.spec                   # PyInstaller build spec (bundles ruff, bandit, Rust core, tkinter)
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
┌──────────────────────────────────────────────────────────────────────┐
│    x_ray_flet.py  /  x_ray_claude.py  /  x_ray_exe.py               │
│       (Flet GUI)          (CLI)             (Standalone)             │
└────────┬──────────────────────┬───────────────────────────────────── ┘
         │                      │
    ┌────▼──────────────────────▼───────────────────────────────────┐
    │               Core/ui_bridge.py                               │
    │  UIBridge Protocol — log() / status() / progress()            │
    │  ├── PrintBridge (default CLI)  ├── NullBridge (tests)        │
    │  ├── TqdmBridge (tqdm bars)     └── FletBridge / custom       │
    └───────────────────────────────────────────────────────────────┘
         │  set_bridge() ↑   get_bridge() ↓
    ┌────▼──────────────────────────────────┐
    │         Core/scan_phases.py           │
    │    Phase orchestrator + ETA           │
    └──┬───┬───┬───┬───┬───┬───┬───┬─────────┘
       │   │   │   │   │   │   │   │
    ┌──▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼┐┌─▼────────┐
    │ S ││ D ││ L ││ B ││ W ││ H ││ R ││ TestGen  │
    │ m ││ u ││ i ││ a ││ e ││ e ││ u ││ ──────── │
    │ e ││ p ││ n ││ n ││ b ││ a ││ s ││ Generates│
    │ l ││ l ││ t ││ d ││   ││ l ││ t ││ pytest / │
    │ l ││ s ││   ││ i ││ S ││ t ││ i ││ Vitest   │
    │ s ││   ││   ││ t ││ m ││ h ││ f ││ suites   │
    │   ││   ││   ││   ││ l ││   ││ y ││          │
    └───┘└───┘└───┘└───┘└───┘└───┘└───┘└──────────┘
       │         │                │
    ┌──▼─────────▼────────────────▼────┐
    │  Lang/ (AST + Tokenizer + JS/TS) │
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

## Lessons Learned

> Hard-won insights from building, shipping, and debugging X-Ray across 15 projects.

| Lesson | Context |
|---|---|
| **Rust → Python type boundaries need explicit resolution** | `prefilter_parallel` returns `(str, str, float)` key tuples, not Python objects. Always resolve keys back to domain objects at the boundary. |
| **Hash algorithm divergence is a silent landmine** | Rust uses FxHash (64-bit), Python uses SHA-256 truncated to 32-bit for n-gram fingerprints. Never mix fingerprint sets across the two runtimes. |
| **Double-call anti-pattern in comprehensions** | `code_similarity(a, b)` was called twice per pair (filter + value). Walrus operator `:=` eliminates the 2× cost. |
| **PyInstaller excludes can break features** | `tkinter` was in the excludes list — removing it was necessary for the folder picker to work in the `.exe`. |
| **Bundled tool binaries must be explicit** | Ruff was bundled but Bandit wasn't. Both must appear in `x_ray.spec`'s `binaries` list. |
| **Trial crypto belongs in compiled code** | Python-side secrets are trivially patchable. The AES-256-GCM gate lives entirely in the Rust `.pyd` — no keys in Python. |
| **Interactive mode is essential for .exe distribution** | Friends double-click `.exe` files; they don't open terminals. A 3-step wizard (folder → mode → report) makes the tool usable for non-developers. |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run the test suite: `python -m pytest tests/ -q --tb=short`
4. Ensure zero Ruff warnings: `ruff check .`
5. Submit a pull request

---

*Scan it · Grade it · Rustify it*
