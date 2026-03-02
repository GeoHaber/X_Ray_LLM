# X-Ray — Development Workflow

Best practices for contributing to X-Ray, aligned with a structured SDLC (see [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/)).

---

## Branch Strategy

| Branch | Purpose | Protection |
|--------|---------|------------|
| `main` | Production / release; always shippable | PR + CI required; no force push |
| `develop` | Integration (optional) | PR from feature/fix branches; CI required |
| `feature/*` | New features (e.g. `feature/format-checks`) | Merge into `develop` or `main` |
| `fix/*` | Bug fixes | Merge into `develop` or `main` |
| `hotfix/*` | Urgent production fixes | Branch from `main`, PR to `main`, then sync to `develop` |

**Minimal setup:** Use `main` only; open PRs from short-lived `feature/` or `fix/` branches. CI runs on every PR to `main` and `develop` (see `.github/workflows/quality.yml`).

---

## Git Conventions

### Conventional Commits

Use a short prefix so history and release notes stay clear:

| Prefix | Use for |
|--------|--------|
| `feat:` | New feature or analyzer |
| `fix:` | Bug fix |
| `test:` | Adding or updating tests |
| `refactor:` | Code change that doesn’t fix a bug or add a feature |
| `chore:` | Build, tooling, config |
| `docs:` | Documentation only |

**Examples:**

```text
feat: add Ruff format check phase
fix: security analyzer exclude paths on Windows
refactor: format and security analyzers, add tool config
docs: add DEVELOPMENT_WORKFLOW and CLAUDE.md
```

### Pull Requests

- Target `main` (or `develop` if you use it).
- CI must pass: tests, Ruff (check + format), Bandit, quality gate.
- Keep PRs small and focused; link to issues if applicable.

---

## CI Pipeline

The pipeline (`.github/workflows/quality.yml`) runs on push/PR to `main` and `develop`:

1. **tests** — Pyright (optional), pip-audit, Bandit, pytest (matrix: 3.10, 3.11, 3.12).
2. **code-quality** — X-Ray full self-scan → JSON report → `check_quality.py`.
3. **quality-gate** — Fails if the report contains `CRITICAL:` in `quality-check.log`.

**Locally before pushing:**

```bash
ruff check . && ruff format --check .
python -m pytest tests/ -q --tb=short
python x_ray_claude.py --full-scan --path . --report x_ray_report.json
python .github/scripts/check_quality.py x_ray_report.json
```

---

## Code Standards

- **Language:** Python 3.10+.
- **Format:** Ruff format (Black-compatible). Config: `pyproject.toml` → `[tool.ruff]`, `[tool.ruff.format]`.
- **Lint:** Ruff check. Resolve all reported issues; avoid broad `except:` and unused imports.
- **Security:** Bandit. Config: `[tool.bandit]`. Use `# nosec` only for reviewed false positives; prefer fixing or narrowing the finding.
- **Tests:** Pytest in `tests/`. Add tests for new behavior; keep tests fast and deterministic.
- **Secrets:** Never commit secrets or API keys; use env vars and `.env` (in `.gitignore`).

---

## Review Checklist (Pre-Merge)

Use this before marking a PR ready or merging:

- [ ] All tests pass (`pytest tests/`).
- [ ] No Ruff violations (`ruff check .`, `ruff format --check .`).
- [ ] No new Bandit issues (or documented `# nosec` with a short reason).
- [ ] Quality gate passes when running `check_quality.py` on the latest report.
- [ ] Docs updated if you changed behavior, CLI, or config (`README.md`, `docs/USAGE.md`, or `docs/`).
- [ ] Commits use conventional prefixes (`feat:`, `fix:`, etc.).

---

## Documentation Layout

| Document | Purpose |
|----------|---------|
| `README.md` | Quick start, structure, grading, env vars |
| `CLAUDE.md` | Project context for AI assistants and developers |
| `docs/USAGE.md` | CLI options, smell categories, programmatic API |
| `docs/DEVELOPMENT_WORKFLOW.md` | This file — branch strategy, CI, standards |
| `docs/CI_CD_SETUP.md` | GitHub Actions, quality gates, pre-commit |
| `docs/FUTURE_PLAN.md` | Roadmap and backlog |

Keep design and architecture notes in `docs/`; update them when you change behavior or structure.

---

## Security & Quality Gates

- **Bandit** runs in CI (medium severity). Fix or suppress with `# nosec` and a comment.
- **Quality gate** (`.github/scripts/check_quality.py`) fails the build on CRITICAL thresholds (e.g. too many critical smells or total issues). Tune thresholds in that script if needed.
- **pip-audit** runs on dependencies; address reported CVEs before merging.

---

*For a one-page summary for AI and new contributors, see [CLAUDE.md](../CLAUDE.md) in the repo root.*
