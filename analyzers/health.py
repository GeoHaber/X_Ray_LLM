"""
X-Ray LLM — Project health, remediation time, release readiness.
"""

import logging
import os
import re

from analyzers._shared import _walk_py
from xray.types import HealthResult, RemediationEstimate


def check_project_health(directory: str) -> HealthResult:
    """Check for essential project files and configuration."""
    checks = []

    def _check(name, patterns, description, severity="MEDIUM"):
        for pat in patterns:
            target = os.path.join(directory, pat)
            if os.path.exists(target):
                checks.append(
                    {"name": name, "status": "pass", "file": pat, "description": description, "severity": severity}
                )
                return
        checks.append(
            {"name": name, "status": "fail", "file": patterns[0], "description": description, "severity": severity}
        )

    _check("README", ["README.md", "README.rst", "README.txt", "README"], "Project documentation", "HIGH")
    _check("LICENSE", ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"], "License file", "MEDIUM")
    _check(".gitignore", [".gitignore"], "Git ignore rules", "MEDIUM")
    _check(
        "Requirements",
        ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"],
        "Dependency specification",
        "HIGH",
    )
    _check(
        "CI Config",
        [".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci", ".travis.yml", "azure-pipelines.yml"],
        "CI/CD configuration",
        "LOW",
    )
    _check("Tests", ["tests", "test", "tests.py", "test.py"], "Test directory or file", "HIGH")
    _check(
        "Type Hints",
        ["py.typed", "pyproject.toml", "mypy.ini", ".mypy.ini", "pyrightconfig.json"],
        "Type checking configuration",
        "LOW",
    )
    _check(
        "Linter Config",
        [".ruff.toml", "ruff.toml", "pyproject.toml", ".flake8", ".pylintrc", "tox.ini"],
        "Linter configuration",
        "LOW",
    )
    _check("Changelog", ["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"], "Change log", "LOW")
    _check("Editor Config", [".editorconfig"], "Editor configuration", "LOW")

    passed = sum(1 for c in checks if c["status"] == "pass")
    total = len(checks)
    score = round(passed / total * 100) if total else 0

    return {
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
    }


# Time estimates per rule pattern
_TIME_ESTIMATES = {
    "SEC-": {"label": "~15 min", "minutes": 15},
    "QUAL-": {"label": "~5 min", "minutes": 5},
    "PY-": {"label": "~10 min", "minutes": 10},
}


def estimate_remediation_time(findings: list) -> RemediationEstimate:
    """Estimate remediation time per finding based on rule category."""
    total_min = 0
    estimates = []
    for f in findings:
        rid = f.get("rule_id", "")
        est = {"label": "~10 min", "minutes": 10}  # default
        for prefix, val in _TIME_ESTIMATES.items():
            if rid.startswith(prefix):
                est = val
                break
        total_min += est["minutes"]
        estimates.append(est["label"])

    return {
        "total_minutes": total_min,
        "total_hours": round(total_min / 60, 1),
        "per_finding": estimates,
    }


def check_release_readiness(directory: str) -> dict:
    """Assess release readiness based on multiple criteria."""
    checks = []

    # Version in pyproject.toml
    pyproject = os.path.join(directory, "pyproject.toml")
    has_version = False
    if os.path.exists(pyproject):
        try:
            with open(pyproject, encoding="utf-8") as f:
                content = f.read()
            has_version = "version" in content.lower()
        except OSError as e:
            logging.debug("Skipped pyproject.toml version check: %s", e)
    checks.append({"name": "Version defined", "pass": has_version, "severity": "HIGH"})

    # CHANGELOG exists and is recent
    changelog_exists = any(
        os.path.exists(os.path.join(directory, f))
        for f in ["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"]
    )
    checks.append({"name": "Changelog exists", "pass": changelog_exists, "severity": "MEDIUM"})

    # No TODO/FIXME in critical paths
    critical_tods = 0
    for fpath, _ in _walk_py(directory):
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if re.search(r"\b(FIXME|XXX|BUG)\b", line, re.IGNORECASE):
                        critical_tods += 1
        except OSError as e:
            logging.debug("Skipped TODO scan for %s: %s", fpath, e)
    checks.append(
        {"name": f"No critical TODOs ({critical_tods} found)", "pass": critical_tods == 0, "severity": "HIGH"}
    )

    # Tests exist
    test_dir = any(os.path.isdir(os.path.join(directory, d)) for d in ["tests", "test"])
    checks.append({"name": "Tests exist", "pass": test_dir, "severity": "HIGH"})

    # README exists
    readme = any(os.path.exists(os.path.join(directory, f)) for f in ["README.md", "README.rst", "README"])
    checks.append({"name": "README exists", "pass": readme, "severity": "MEDIUM"})

    # No print() debug statements (rough check)
    debug_prints = 0
    for fpath, rel in _walk_py(directory):
        if "test" in rel.lower():
            continue
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("print(") and "debug" not in stripped.lower():
                        debug_prints += 1
        except OSError as e:
            logging.debug("Skipped debug-print scan for %s: %s", fpath, e)
    checks.append({"name": f"No debug prints ({debug_prints} found)", "pass": debug_prints < 5, "severity": "LOW"})

    # .env not committed
    env_file = os.path.join(directory, ".env")
    gitignore = os.path.join(directory, ".gitignore")
    env_safe = True
    if os.path.exists(env_file) and os.path.exists(gitignore):
        try:
            with open(gitignore, encoding="utf-8") as f:
                env_safe = ".env" in f.read()
        except OSError as e:
            logging.debug("Skipped .gitignore check: %s", e)
    checks.append({"name": ".env in .gitignore", "pass": env_safe, "severity": "HIGH"})

    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    score = round(passed / total * 100) if total else 0

    return {
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
        "ready": score >= 80,
    }
