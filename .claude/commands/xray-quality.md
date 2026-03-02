# X-Ray Quality Check (Pre-PR Validation)

Run the same checks as CI to validate the **X-Ray** codebase (Python code quality scanner for Python projects) before opening or merging a PR. Use this command before every contribution.

## SCOPE: X-Ray only
This command is for the X-Ray repo. It runs lint (Ruff), format (Ruff), tests (pytest), self-scan (all analyzers), and quality gate.

## PROCESS
1. **Ruff check** — `ruff check .`
2. **Ruff format** — `ruff format --check .`
3. **Tests** — `python -m pytest tests/ -v --tb=short`
4. **Full self-scan** — `python x_ray_claude.py --full-scan --path . --report x_ray_report.json`
5. **Quality gate** — `python .github/scripts/check_quality.py x_ray_report.json`

Run in the repo root. If any step fails, fix before submitting the PR.

## ONE-LINER (from repo root)
```bash
ruff check . && ruff format --check . && python -m pytest tests/ -v --tb=short && python x_ray_claude.py --full-scan --path . --report x_ray_report.json && python .github/scripts/check_quality.py x_ray_report.json
```

## OUTPUT
- Ruff: pass or list of violations
- Pytest: pass/fail and summary
- Quality gate: PASS or FAIL (and quality-check.log content if failed)

## CONSTRAINTS
- Requires Python 3.10+, ruff, pytest; for full-scan also bandit (see requirements.txt)
- Optional: add `--exclude` to full-scan if needed (e.g. exclude X_Ray_Rust_Full)
