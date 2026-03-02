# Security & Dependency Hygiene

## Overview

X-Ray follows Python security best practices for dependency management and code security. See [CI_CD_SETUP.md](CI_CD_SETUP.md) for automated checks.

## Dependency Security

### pip-audit (CVE Scanning)

We use [pip-audit](https://pypi.org/project/pip-audit/) to scan for known vulnerabilities:

```bash
pip-audit -r requirements.txt -r requirements-dev.txt
```

Runs automatically in CI. Fix vulnerabilities with `pip-audit --fix` or by updating affected packages.

### Dependabot

[GitHub Dependabot](https://docs.github.com/en/code-security/dependabot) opens pull requests for:

- **pip** — Weekly on Mondays
- **GitHub Actions** — Weekly on Mondays

Review and merge dependency update PRs regularly.

### Version Pinning

- `requirements.txt` and `requirements-dev.txt` use compatible release pinning (`>=x,<y`)
- Dependabot proposes updates; merge to stay current
- For full reproducibility, consider [pip-tools](https://pip-tools.readthedocs.io/) (`pip-compile`)

## Code Security

### Bandit

[Bandit](https://bandit.readthedocs.io/) scans Python source for common security issues:

```bash
bandit -r . -x ./venv,./.venv,./X_Ray_Rust_Full,tests/fixtures
```

Runs in CI; findings are non-blocking initially. Address HIGH/CRITICAL findings promptly.

### X-Ray Security Phase

When scanning other projects, X-Ray integrates Bandit (`--security` / `--full-scan`) to report vulnerabilities in target codebases.

## Reporting Vulnerabilities

If you discover a security vulnerability, please email the maintainers directly rather than opening a public issue.
