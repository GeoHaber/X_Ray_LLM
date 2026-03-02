# .claude — Agents & Commands for X-Ray and Python Projects

**Validated for:** X-Ray (Python code quality scanner for Python codebases: diagnose = smells, duplicates, Ruff lint/format, Bandit security; cure = Rust advisor/transpiler) and for **Python projects** scanned or improved by X-Ray.

This folder contains **agent definitions** and **commands** aligned with the [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/) article.

---

## Code review (X-Ray and Python projects)

For **project/code review** of X-Ray or any Python codebase, use only:

| What | Purpose |
|------|---------|
| **reviewer** agent | Checklist: tests, Ruff, Bandit, docs, quality gate → docs/review-report.md |
| **security-auditor** agent | Bandit, pip-audit, secure patterns → docs/security-audit.md |
| **xray-quality** command | Pre-PR: Ruff + pytest + full-scan + quality gate (one-shot validation) |

All other agents and commands are for **implementation**, **CI**, **backlog**, or the **optional new-product pipeline** (not for X-Ray code review).

---

## Relevance to X-Ray

| Category | Purpose |
|----------|---------|
| **X-Ray development** | Contributing to X-Ray: analyzers (Analysis/), Core/, Lang/, tests, Ruff, Bandit, pytest, quality gate |
| **Python projects** | Scanning or improving any Python codebase with X-Ray; security/lint/format/review for Python |
| **Optional: new product** | Building a *separate* product (e.g. web app); not for X-Ray code review or development |

---

## Directory layout

| Path | Purpose |
|------|---------|
| **agents/** | Role definitions (Python/X-Ray–focused where applicable) |
| **commands/** | Orchestrator and utility commands, including X-Ray–specific quality check |

---

## Agents — X-Ray / Python (use for this repo)

| Agent | Use for |
|-------|--------|
| **backend-dev** | Implementing Python code in X-Ray: Analysis/, Core/, Lang/. New analyzers, phases, fixes. Ruff, pytest, conventional commits. |
| **reviewer** | Code review for X-Ray or scanned Python projects. Checklist: tests, Ruff, Bandit, docs. Output: docs/review-report.md. |
| **security-auditor** | Security audit for Python (Bandit, pip-audit). X-Ray and scanned projects. Output: docs/security-audit.md. |
| **test-engineer** | Tests for Python/X-Ray: pytest, tests/, fixtures. Integration and quality gates. |
| **devops** | CI/CD for X-Ray: .github/workflows/quality.yml, branch strategy, Ruff + pytest + Bandit. |
| **feedback-triage** | Triage feedback and issues; update docs/backlog.md or docs/FUTURE_PLAN.md for X-Ray. |
| **architect** | Technical design for X-Ray (new analyzer, major refactor) or for a new product. ADRs, docs/architecture.md. |

---

## Agents — Optional (new product pipeline only)

**Not for X-Ray code review or development.** Use only when building a *new product* (e.g. web app) with the full SDLC pipeline.

| Agent | Use for |
|-------|--------|
| product-strategist | Discovery & stakeholder validation → docs/validated-idea.md |
| spec-writer | Requirements & user stories → docs/requirements.md, docs/user-stories.md |
| ux-designer | Wireframes & UX flows → docs/ux-wireframes.md |
| frontend-dev | Client-side implementation (e.g. React) against api-contract |

---

## Commands

| Command | Relevance | When to use |
|---------|------------|-------------|
| **xray-quality** | **X-Ray** | Before every PR: Ruff check + format, pytest, full-scan, quality gate. Validates the X-Ray codebase. |
| **maintenance-check** | **X-Ray** | Weekly or pre-release: pip-audit, Ruff, pytest, X-Ray full-scan, quality gate, backlog review. |
| **process-feedback** | **X-Ray / any** | Triage user feedback; update docs/backlog.md or docs/FUTURE_PLAN.md; optional P0 hotfix flow. |
| **build-product** | **Optional** | Building a *new product* from an idea (Phases 1–8). Not for X-Ray code review or development. |

---

## X-Ray stack (Python)

- **Language:** Python 3.10+
- **Lint/format:** Ruff (check + format), config in pyproject.toml
- **Security:** Bandit, pip-audit; [tool.bandit] in pyproject.toml
- **Tests:** pytest in tests/
- **Structure:** Analysis/ (analyzers), Core/ (types, scan phases), Lang/ (AST), docs/

See root [CLAUDE.md](../CLAUDE.md) and [docs/DEVELOPMENT_WORKFLOW.md](../docs/DEVELOPMENT_WORKFLOW.md) for contribution workflow.

---

## Validation (X-Ray purpose)

| Check | Status |
|-------|--------|
| **Code review** uses only reviewer, security-auditor, xray-quality (no specs/wireframes) | ✓ |
| Primary agents reference X-Ray and Python; optional agents marked "not for X-Ray code review" | ✓ |
| Commands xray-quality and maintenance-check target X-Ray (Ruff, pytest, full-scan, quality gate) | ✓ |
| build-product and "For feature requests" pipeline scoped to new-product only | ✓ |
| Stack: Python 3.10+, Ruff, Bandit, pytest, Analysis/, Core/, Lang/ | ✓ |
