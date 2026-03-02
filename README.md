# X-Ray — AI-Powered Universal Code Quality Scanner & Rust Accelerator

**Version 7.0.0** · Python 3.10+ · 905+ tests · Python + JS/TS/React · 5 languages · MIT License

X-Ray *diagnoses* problems in Python codebases, then helps you *cure* them — including transpiling performance-critical functions to Rust.

---

X-Ray is a **universal code quality platform** that *diagnoses* problems in
**Python, JavaScript, TypeScript, and React** codebases, then helps you *cure*
them — including auto-fixing smells, generating test suites, and transpiling
performance-critical Python functions to Rust.

| Phase | Tools |
|-------|-------|
| **Diagnose** | Code smells · Duplicates · Ruff lint · Bandit security · Ruff format · Library advisor · Smart graph |
| **Cure** | Rust advisor · AST transpiler · Optional Rust core (10–50× speedup) |

**Output:** Single grade (A+ → F) + JSON report + interactive graph.

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
pip install -r requirements.txt   # optional; core works with stdlib only

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
<summary>CLI flags</summary>

| Flag | Description |
|------|-------------|
| `--path PATH` | Directory to scan |
| `--smell` | Code smells only |
| `--duplicates` | Find similar functions |
| `--lint` | Ruff linter only |
| `--security` | Bandit only |
| `--full-scan` | All analyzers |
| `--rustify` | Score for Rust porting |
| `--report FILE` | Save JSON |
| `--graph` | Interactive HTML graph |

</details>

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

## Rust Acceleration

**Transpiler** (`Analysis/transpiler.py`) — AST-based Python → Rust, 19 stdlib module handlers. Escape hatch: `todo!()` stubs filled by LLM.

**Optional Rust core** (`x_ray_core.pyd`) — 10–50× speedup on similarity/duplicate hot-paths. Build:
```bash
cd Core/x_ray_core && pip install maturin && maturin develop --release
```
Rust is optional — pure-Python fallbacks always available.

| Stage | Transpilable | Rate |
|---|---|---|
| Pre-Tier 3 | 4,322 / 14,044 | 30.8 % |
| Post-Tier 3 + Threshold Tuning | 7,485 / 14,064 | 53.2 % |
| Post-Round 2 Fixes | 7,694 (6,917 clean compile) | 54.7 % |

## Tests

```bash
pip install pytest
python -m pytest tests/ -q --tb=short
```

---

## Structure

| Path | Purpose |
|------|---------|
| `x_ray_claude.py` | Main CLI |
| `x_ray_flet.py` | Desktop GUI |
| `x_ray_web.py` | Streamlit web UI |
| `Analysis/` | Analyzers (smells, duplicates, lint, security, transpiler) |
| `Core/` | Types, config, scan phases, Rust core |
| `Lang/` | Python AST parser, tokenizer |
| `tests/` | Test suite |

---

## Env Vars

| Variable | Effect |
|----------|--------|
| `X_RAY_DISABLE_RUST=1` | Skip Rust core (pure-Python only) |
| `X_RAY_LLM_URL` | Override LLM endpoint |

---

## Docs

| Doc | Description |
|-----|-------------|
| [CLAUDE.md](CLAUDE.md) | Project context for AI assistants & developers |
| [docs/USAGE.md](docs/USAGE.md) | CLI options, smell categories, programmatic API |
| [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) | Branch strategy, CI, code standards, review checklist |
| [.claude/README.md](.claude/README.md) | SDLC agents & commands (from Full-SDLC Multi-Agent article) |
| [docs/CI_CD_SETUP.md](docs/CI_CD_SETUP.md) | GitHub Actions, quality gates |
| [SECURITY.md](SECURITY.md) | Dependency and code security |

**Contributing:** See [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md). Fork → `ruff check .` && `ruff format --check .` && `pytest tests/ -q` → PR.

---

*Scan it · Grade it · Rustify it*
