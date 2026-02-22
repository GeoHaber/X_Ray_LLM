# X-Ray — AI-Powered Code Quality Scanner & Rust Accelerator

**Version 5.1.0** · Python 3.10+ · MIT License

X-Ray *diagnoses* problems in Python codebases, then helps you *cure* them — including transpiling performance-critical functions to Rust.

---

## What It Does

| Phase | Tools |
|-------|-------|
| **Diagnose** | Code smells · Duplicates · Ruff lint · Bandit security · Ruff format · Library advisor · Smart graph |
| **Cure** | Rust advisor · AST transpiler · Optional Rust core (10–50× speedup) |

**Output:** Single grade (A+ → F) + JSON report + interactive graph.

**Entry points:**
- **CLI** — `x_ray_claude.py` (default)
- **Desktop** — `x_ray_flet.py` (Flet GUI)
- **Web** — `x_ray_web.py` (Streamlit)

---

## Quick Start

```bash
git clone https://github.com/GeoHaber/X_Ray.git
cd X_Ray
pip install -r requirements.txt   # optional; core works with stdlib only

# Scan a project
python x_ray_claude.py --path /your/project

# Full scan + JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project

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
| [docs/USAGE.md](docs/USAGE.md) | CLI options, smell categories, programmatic API |
| [CI_CD_SETUP.md](CI_CD_SETUP.md) | GitHub Actions, quality gates |
| [SECURITY.md](SECURITY.md) | Dependency and code security |

**Contributing:** Fork → run `ruff check .` and `pytest tests/ -q` → PR

---

*Scan it · Grade it · Rustify it*
