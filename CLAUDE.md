# X-Ray — Project Context for AI Assistants & Developers

*Adapted from [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/).*

## What This Project Is

**X-Ray** is an AI-powered Python code quality scanner and Rust accelerator. It diagnoses (smells, duplicates, lint, security, format) and helps cure (Rust transpilation, library suggestions). Entry points: CLI (`x_ray_claude.py`), Flet GUI (`x_ray_flet.py`), Streamlit (`x_ray_web.py`).

## Development Workflow

- **Default branch:** `main`. Use `develop` for integration if you adopt a two-branch flow.
- **Feature work:** Prefer short-lived branches, e.g. `feature/format-checks`, `fix/security-exclude`.
- **Commits:** Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`.
- **Before PR:** Run `ruff check .`, `ruff format --check .`, and `python -m pytest tests/ -q --tb=short`. CI runs the same plus Bandit and quality gates.

## Branch Strategy (Optional)

```
main (production / release)
  └── develop (integration)  ← optional
        ├── feature/*
        └── fix/*
```

- PRs target `main` or `develop`; CI must pass.
- Hotfixes: branch from `main`, fix, PR to `main`, then sync back to `develop` if used.

## Documentation

All project docs live in **`docs/`** and are the source of truth:

| Document | Purpose |
|----------|---------|
| `docs/USAGE.md` | CLI, options, programmatic API |
| `docs/DEVELOPMENT_WORKFLOW.md` | Branch strategy, CI, code standards, review checklist |
| `docs/CI_CD_SETUP.md` | GitHub Actions, quality gates |
| `docs/FUTURE_PLAN.md` | Roadmap / backlog |
| `README.md` | Quick start, structure, env vars |

## .claude folder (SDLC agents & commands)

The **`.claude/`** directory holds the multi-agent SDLC setup from [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/):

| Path | Purpose |
|------|---------|
| `.claude/agents/` | 11 role definitions (product-strategist, spec-writer, ux-designer, architect, devops, backend-dev, frontend-dev, test-engineer, reviewer, security-auditor, feedback-triage) |
| `.claude/commands/` | **xray-quality** (pre-PR), maintenance-check, process-feedback, build-product (optional) |
| `.claude/README.md` | Index; which agents/commands are for X-Ray vs new-product pipeline |
| `.claude/CLAUDE.md.template` | Template CLAUDE.md for new products using this pipeline |

For X-Ray PRs run **xray-quality** (or the steps under Commands to Run). Use build-product and product/spec/UX/frontend agents only when building a new product. Otherwise follow the “Development Workflow” and “Commands to Run” sections above.

## Code Standards

- **Python 3.10+.** Type hints encouraged; Pyright in CI (optional).
- **Formatting:** Ruff format (Black-compatible). Config in `pyproject.toml` under `[tool.ruff]` and `[tool.ruff.format]`.
- **Linting:** Ruff check. No broad `except:`; avoid unused imports (F401).
- **Security:** Bandit. Config in `[tool.bandit]`; use `# nosec` for reviewed false positives.
- **Tests:** Pytest in `tests/`. Co-locate test files with the area they cover where it makes sense; keep fixtures in `tests/` or `tests/fixtures`.
- **No secrets** in code or history; use env vars. `.env` in `.gitignore`.

## Commands to Run

```bash
# Lint + format check
ruff check . && ruff format --check .

# Tests
python -m pytest tests/ -v --tb=short

# Full self-scan (smells, duplicates, lint, security, format)
python x_ray_claude.py --full-scan --path . --report x_ray_report.json

# Quality gate (after report exists)
python .github/scripts/check_quality.py x_ray_report.json
```

## Structure (Where to Edit)

| Path | Purpose |
|------|---------|
| `Analysis/` | Analyzers: format, lint, security, smells, duplicates, transpiler |
| `Core/` | Types, config, scan phases, CLI args |
| `Lang/` | AST parser, tokenizer |
| `tests/` | Pytest suite |
| `docs/` | All written documentation |

When adding a new analyzer or phase: add the module under `Analysis/`, register the phase in `Core/scan_phases.py`, and add tests under `tests/`.

## Review Checklist (Pre-Merge)

- [ ] All tests pass.
- [ ] No Ruff lint/format issues.
- [ ] No new Bandit findings (or documented `# nosec` with reason).
- [ ] Docs updated if behavior or CLI changed.
- [ ] Conventional commit messages on the branch.

---

*This file gives AI assistants and new contributors a single place to understand how to work on X-Ray in line with SDLC best practices.*
