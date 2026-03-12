# X-Ray — Code Quality Scanner & Rust Accelerator

> **Scan it · Grade it · Fix it · Rustify it**

X-Ray is a desktop-first, native **code quality platform** that *diagnoses* problems in Python, JavaScript, TypeScript, and React codebases — then helps you *cure* them. It detects code smells, finds duplicates, runs lint and security audits, and can automatically transpile performance-critical Python functions into Rust.

**One command. One score. A+ or fix it.**

---

## What X-Ray Does

```
Your Code  →  X-Ray  →  Grade A–F  →  Actionable Issues  →  One-Click Fixes
                                                          →  Auto-Generated Tests
                                                          →  Rust Transpiled Functions
```

| Phase | What Happens |
|---|---|
| 🔍 **Diagnose** | Detects 15+ code smells, finds duplicate logic, flags lint violations, spots security vulnerabilities, checks UI framework compatibility |
| 📊 **Grade** | Combines all findings into a single **A+ → F score** (0–100 scale) with a breakdown of what's hurting you |
| 🧠 **Oracle** | Generates an AI-powered top-down architectural design review of the codebase |
| 🛠️ **Fix** | One-click Ruff auto-fix for lint, auto-generates a pytest test suite, suggests library consolidations |
| ✅ **Verify** | Heuristic functional verification — testability scoring, UI stress-test robustness, per-project grade |
| 🦀 **Rustify** | Scores every function for Rust portability, transpiles pure-Python logic to Rust, compiles with Cargo, builds a `.exe` |

---

## Launch the Desktop GUI

```bash
git clone https://github.com/GeoHaber/X_Ray.git
cd X_Ray
pip install -r requirements.txt

python x_ray_flet.py          # native desktop window  (Flutter engine)
flet run --web x_ray_flet.py  # same UI, opens in browser
```

> **Note:** X-Ray requires **Flet >= 0.80.0**. If an older version is detected
> at startup, the app will auto-upgrade via `pip` and ask you to restart.

The GUI opens a modern dark-mode dashboard with:

- **Sidebar** — folder picker, recent-paths history, analyzer toggles, ⚡ Scan button
- **Dashboard tabs** — Smells · Duplicates · Lint · Security · Rustify · Heatmap · Complexity · Graph · Auto-Rustify · UI Compat · Verification · Release Readiness
- **Export bar** — 📥 JSON report · 📥 Markdown report · 🧪 Generate Tests
- **Theme toggle** — Dark / Light  |  **5 languages** — EN · RO · ES · FR · DE

---

## CLI Usage

```bash
# Quick scan (smells + lint + security)
python x_ray_claude.py --path /your/project

# Full scan — all 10 analyzers, grade, report
python x_ray_claude.py --full-scan --path /your/project

# Save a JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project

# Auto-generate a pytest test suite from scan data
python x_ray_claude.py --full-scan --gen-tests --path /your/project

# Score functions for Rust and show candidates
python x_ray_claude.py --rustify --path /your/project

# Full Rust pipeline: scan → transpile → compile → .exe
python x_ray_claude.py --rustify-exe --path /your/project

# Interactive HTML dependency graph
python x_ray_claude.py --graph --path /your/project
```

<details>
<summary>All CLI flags</summary>

| Flag | Description |
|---|---|
| `--path PATH` | Directory to scan (required) |
| `--full-scan` | Enable all analyzers |
| `--smell` | Code smells only |
| `--duplicates` | Find similar functions |
| `--lint` | Ruff linter |
| `--security` | Bandit security audit |
| `--rustify` | Score functions for Rust |
| `--rustify-exe` | Full pipeline to compiled `.exe` |
| `--gen-tests` | Auto-generate pytest test files |
| `--graph` | Interactive HTML call graph |
| `--report FILE` | Save results to JSON |
| `--compare FILE` | Diff against a previous report |
| `--fail-on GRADE` | Exit non-zero if grade is below threshold (CI use) |

</details>

---

## The Grading Formula

Score = **100 − penalties** (capped per analyzer):

| Analyzer | Penalty per Issue | Max Penalty |
|---|---|---|
| Code Smells | critical ×0.25 · warning ×0.05 · info ×0.01 | 30 pts |
| Duplicates | per group ×0.1 | 15 pts |
| Lint | critical ×0.3 · warning ×0.05 · info ×0.005 | 25 pts |
| Security | critical ×1.5 · warning ×0.3 · info ×0.005 | 30 pts |

| Grade | Score Range |
|---|---|
| **A+** | 97–100 |
| **A** | 93–96 |
| **A−** | 90–92 |
| **B+** | 87–89 |
| **B** | 83–86 |
| **B−** | 80–82 |
| **C** | 70–79 |
| **D** | 60–69 |
| **F** | < 60 |

---

## The 11 Analyzers

| # | Analyzer | Finds |
|---|---|---|
| 1 | **Code Smells** | God functions, boolean blindness, magic numbers, too-many-params, deep nesting, missing type hints |
| 2 | **Duplicates** | Near-identical logic across files (AST + token fingerprinting) |
| 3 | **Ruff Lint** | 800+ Python lint rules, with one-click auto-fix |
| 4 | **Bandit Security** | Hardcoded secrets, unsafe subprocess calls, SQL injection patterns |
| 5 | **Rust Advisor** | Scores every function 0–30 for Rust portability (pure, no I/O, type-safe) |
| 6 | **Heatmap** | Files ranked by total issue density — shows your worst files at a glance |
| 7 | **Complexity** | Cyclomatic complexity and function-size distribution charts |
| 8 | **UI Compat** | Detects invalid Flet API usage — wrong kwargs, deprecated patterns |
| 9 | **Test Generator** | Emits pytest smoke, callable, regression, and structure tests from AST data |
| 10 | **Verification** | Heuristic functional verification — testability scoring, UI stress-test robustness, per-project grade |
| 11 | **Release Readiness** | Weighted release-readiness scoring across 7 categories (tests, lint, security, docs, deps, CI, code quality) with auto-generated checklist |

**JS/TS/React support:** Full analysis of `.js`, `.ts`, `.jsx`, `.tsx` files — imports, functions, React components, 142 npm package mappings in 15 categories.

---

## Import Dependency Graph

X-Ray can generate an interactive HTML dependency graph showing all module-level imports in your project:

```bash
python x_ray_claude.py --graph --path /your/project
```

The graph uses **vis-network.js** for interactive visualization with color-coded modules:
- **Analysis** — cyan · **Core** — orange · **UI** — green · **tests** — red · **Lang** — purple

Nodes are draggable, zoomable, and hoverable. The generated `import_graph.html` opens in any browser.

---

## Rust Acceleration

X-Ray has two Rust integration points:

### 1. Auto-Rustify Pipeline (`--rustify-exe`)
```
Your Python  →  Score  →  Transpile (AST)  →  Cargo compile  →  x_ray_rustified.exe
```
- Scans all functions, scores each for portability
- Selects top 30 candidates (score ≥ 3.0)
- Generates Rust source with full type inference
- Compiles with `cargo build --release`  
- LLM fills `todo!()` stubs where transpiler needs help

### 2. Rust Core (`Core/x_ray_core/`)
An optional compiled Rust extension (`x_ray_core.pyd`) that speeds up the duplicate-detection hot-path by **10–50×** using Minhash, n-gram fingerprints, and parallel Rayon processing.

```bash
# Build and install the Rust core extension
cd Core/x_ray_core
maturin build --release --out dist
pip install dist/x_ray_core-*.whl
```

> Rust is always **optional** — pure-Python fallbacks are always available.

---

## Project Layout

```
X_Ray/
├── x_ray_claude.py        ← Main CLI entry point
├── x_ray_flet.py          ← Desktop GUI (Flet / Flutter engine)
├── x_ray_flet.spec        ← PyInstaller spec for building .exe
├── Core/
│   ├── types.py           ← Shared data classes (FunctionRecord, etc.)
│   ├── config.py          ← Thresholds, version, settings
│   ├── scan_phases.py     ← Phase orchestration
│   ├── ui_bridge.py       ← Swappable output layer (Flet / tqdm / tests)
│   ├── i18n.py            ← 5-language strings
│   └── x_ray_core/        ← Optional Rust extension (Cargo project)
├── Analysis/
│   ├── smells.py          ← Code smell detector
│   ├── duplicates.py      ← Duplicate finder
│   ├── rust_advisor.py    ← Rust portability scorer
│   ├── auto_rustify.py    ← Full Rust transpile + compile pipeline
│   ├── smart_graph.py     ← Call graph builder
│   ├── imports.py         ← Import analyzer + dependency graph builder
│   ├── verification.py    ← Heuristic functional verification engine
│   ├── release_readiness.py ← Release-readiness scoring & checklist
│   ├── ui_compat.py       ← UI framework compatibility checker
│   └── NexusMode/         ← LLM orchestration agents
├── Lang/
│   └── transpiler/        ← Python → Rust AST transpiler
├── UI/
│   └── tabs/              ← Per-tab Flet UI modules (incl. verification, release readiness)
└── tests/                 ← 4,900+ test cases
    └── xray_generated/    ← Auto-generated tests (from --gen-tests)
```

---

## Running the Tests

```bash
pytest tests/ -q                  # full suite (~50 s)
pytest tests/ -q -x               # stop on first failure
pytest tests/test_xray_claude.py  # core unit tests only
```

**Current status:** 4,880 passing · 14 skipped · 0 failing

---

## Building the Standalone `.exe`

X-Ray ships as a portable Windows executable — no Python install required.

```bash
pip install pyinstaller
python -m PyInstaller x_ray.spec --noconfirm
# Output: dist/x_ray/x_ray.exe
```

The `.exe` includes a **hardware-locked trial** (10 free runs per machine):
- Machine fingerprint → AES-256-GCM encrypted counter → HMAC-SHA256 integrity
- All crypto runs inside `x_ray_core.pyd` (compiled Rust) — no Python-side secrets

---

## Environment Variables

| Variable | Effect |
|---|---|
| `X_RAY_DISABLE_RUST=1` | Skip Rust core, use pure-Python fallbacks |
| `X_RAY_LLM_URL` | Override the local LLM endpoint URL |

---

## Reference Docs

| Doc | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Project context for AI assistants and developers |
| [CHANGELOG.md](CHANGELOG.md) | Full version history |
| [FEATURES.md](FEATURES.md) | Feature-to-test registry |
| [SECURITY.md](SECURITY.md) | Security policy and known exceptions |
| [docs/USAGE.md](docs/USAGE.md) | Full CLI reference and smell catalog |

---

*Built with Python · Flet · Rust · ❤️*
