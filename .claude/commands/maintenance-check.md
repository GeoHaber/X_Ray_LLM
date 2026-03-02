# Maintenance Check

Run periodic maintenance on the codebase. **Primary target: X-Ray (Python).**

**Reference:** [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/)

## For X-Ray (this project) — default

1. **Dependencies:** `pip-audit -r requirements.txt -r requirements-dev.txt`; `pip list --outdated`
2. **Lint/format:** `ruff check .` and `ruff format --check .`
3. **Tests:** `python -m pytest tests/ -v --tb=short`
4. **Self-scan:** `python x_ray_claude.py --full-scan --path . --report x_ray_report.json`
5. **Quality gate:** `python .github/scripts/check_quality.py x_ray_report.json`
6. **Backlog:** Review docs/FUTURE_PLAN.md and docs/backlog.md (if present)
7. **Tech debt:** Grep for TODO/FIXME; list and prioritize

## For other Python projects
- Same pattern: pip-audit, Ruff, pytest, then project-specific checks (e.g. Bandit, coverage).
- For web projects optionally add: Lighthouse, bundle size.

## OUTPUT: docs/maintenance-report.md
- **Dependency health** — vulnerabilities (pip-audit), outdated packages
- **Test health** — pytest result, any regressions
- **Quality gate** — X-Ray self-scan and gate result (for this repo)
- **Tech debt** — TODOs/FIXMEs, recommended actions by risk

Suggest a cadence: weekly or before every release.
