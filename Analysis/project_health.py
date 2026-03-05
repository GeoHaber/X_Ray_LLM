"""Analysis/project_health.py — Project health & structural completeness checker.

Scores a project directory on structural completeness (essential config files,
CI/CD presence, documentation, etc.) and optionally auto-generates missing
boilerplate files.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

from Core.types import SmellIssue, Severity
from Analysis.reporting import (
    _score_to_letter as _score_to_grade,
)  # shared grade mapping

logger = logging.getLogger("X_RAY_HEALTH")


# ── Health check definitions ────────────────────────────────────────────


@dataclass
class HealthCheck:
    """One structural health check and its result."""

    name: str
    description: str
    weight: int  # points out of 100 total
    passed: bool = False
    auto_fixable: bool = False
    detail: str = ""


@dataclass
class HealthReport:
    """Full project health report."""

    root: str
    score: int  # 0-100
    grade: str  # A+ → F
    checks: List[HealthCheck] = field(default_factory=list)
    console_logs_found: int = 0
    console_logs_fixed: int = 0
    files_created: List[str] = field(default_factory=list)
    issues: List[SmellIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "root": self.root,
            "score": self.score,
            "grade": self.grade,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "weight": c.weight,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
            "console_logs_found": self.console_logs_found,
            "console_logs_fixed": self.console_logs_fixed,
            "files_created": self.files_created,
        }


# ── Auto-fix helpers (module-level to keep ProjectHealthAnalyzer lean) ──


def _create_gitignore_file(root: Path) -> None:
    """Create a sensible .gitignore."""
    content = """\
# ── Python ──
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/
*.egg
.eggs/

# ── Node.js ──
node_modules/
.next/
.nuxt/
dist/
coverage/

# ── IDE ──
.vscode/
.idea/
*.swp
*.swo
*~

# ── OS ──
.DS_Store
Thumbs.db

# ── Environment ──
.env
.env.local
.env.*.local

# ── Build ──
*.log
npm-debug.log*
yarn-debug.log*
"""
    (root / ".gitignore").write_text(content, encoding="utf-8")
    logger.info("Created .gitignore")


def _create_license_file(root: Path) -> None:
    """Create an MIT LICENSE file."""
    from datetime import datetime

    year = datetime.now().year
    content = f"""\
MIT License

Copyright (c) {year}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
    (root / "LICENSE").write_text(content, encoding="utf-8")
    logger.info("Created LICENSE (MIT)")


def _create_package_json_file(root: Path) -> None:
    """Create a minimal package.json for a JS/TS workspace."""
    name = root.name.lower().replace(" ", "-").replace("_", "-")
    content = {
        "name": name,
        "version": "1.0.0",
        "private": True,
        "description": "",
        "scripts": {
            "start": 'echo "No start script defined"',
            "test": 'echo "No test script defined"',
        },
    }
    (root / "package.json").write_text(
        json.dumps(content, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Created package.json")


# ── Health analyzer ─────────────────────────────────────────────────────


class ProjectHealthAnalyzer:
    """Analyze project structure and score overall health.

    Checks for:
      - .gitignore
      - README.md / README.rst
      - LICENSE / LICENCE
      - package.json (for JS/TS projects) or pyproject.toml / setup.py
      - docker-compose.yml (if Dockerfile exists)
      - CI/CD config (.github/workflows, .gitlab-ci.yml, etc.)
      - .env.example (if .env is present)
      - Tests directory
      - requirements.txt or equivalent
      - CHANGELOG / HISTORY
    """

    def __init__(self):
        self.report: Optional[HealthReport] = None

    def analyze(self, root: Path, auto_fix: bool = False) -> HealthReport:
        """Run all health checks on *root* and return a HealthReport."""
        checks: List[HealthCheck] = []
        files_created: List[str] = []

        # 1. .gitignore (15 pts)
        checks.append(self._check_gitignore(root, auto_fix, files_created))

        # 2. README (15 pts)
        checks.append(self._check_readme(root))

        # 3. LICENSE (10 pts)
        checks.append(self._check_license(root, auto_fix, files_created))

        # 4. Package manifest (10 pts)
        checks.append(self._check_manifest(root, auto_fix, files_created))

        # 5. Docker infrastructure (10 pts)
        checks.append(self._check_docker(root))

        # 6. CI/CD (10 pts)
        checks.append(self._check_ci(root))

        # 7. .env.example (5 pts)
        checks.append(self._check_env_example(root))

        # 8. Tests (15 pts)
        checks.append(self._check_tests(root))

        # 9. Dependencies lock (5 pts)
        checks.append(self._check_deps(root))

        # 10. CHANGELOG (5 pts)
        checks.append(self._check_changelog(root))

        # Calculate score
        earned = sum(c.weight for c in checks if c.passed)
        total = sum(c.weight for c in checks)
        score = round(earned / total * 100) if total else 0

        # Build issues for failed checks
        issues: List[SmellIssue] = []
        for c in checks:
            if not c.passed:
                severity = Severity.WARNING if c.weight >= 10 else Severity.INFO
                issues.append(
                    SmellIssue(
                        file_path="<project-root>",
                        line=0,
                        end_line=0,
                        category="project-health",
                        severity=severity,
                        message=f"Missing: {c.description}",
                        suggestion=c.detail or f"Add {c.name} to project root",
                        name=c.name,
                        source="xray-health",
                    )
                )

        self.report = HealthReport(
            root=str(root),
            score=score,
            grade=_score_to_grade(score),
            checks=checks,
            files_created=files_created,
            issues=issues,
        )
        return self.report

    # ── Individual checks ───────────────────────────────────────────────

    def _check_gitignore(
        self, root: Path, auto_fix: bool, created: List[str]
    ) -> HealthCheck:
        """Check for .gitignore."""
        path = root / ".gitignore"
        exists = path.is_file()
        check = HealthCheck(
            name=".gitignore",
            description=".gitignore file",
            weight=15,
            passed=exists,
            auto_fixable=True,
            detail="Prevents committing build artifacts and secrets",
        )
        if not exists and auto_fix:
            _create_gitignore_file(root)
            created.append(".gitignore")
            check.passed = True
            check.detail = "Auto-created .gitignore"
        return check

    def _check_readme(self, root: Path) -> HealthCheck:
        """Check for README."""
        found = any(
            (root / name).is_file()
            for name in ("README.md", "README.rst", "README.txt", "README")
        )
        return HealthCheck(
            name="README",
            description="README documentation",
            weight=15,
            passed=found,
            detail="Add a README.md describing project purpose and setup",
        )

    def _check_license(
        self, root: Path, auto_fix: bool, created: List[str]
    ) -> HealthCheck:
        """Check for LICENSE."""
        found = any(
            (root / name).is_file()
            for name in ("LICENSE", "LICENCE", "LICENSE.md", "LICENSE.txt")
        )
        check = HealthCheck(
            name="LICENSE",
            description="License file",
            weight=10,
            passed=found,
            auto_fixable=True,
            detail="Add a LICENSE file to clarify usage rights",
        )
        if not found and auto_fix:
            _create_license_file(root)
            created.append("LICENSE")
            check.passed = True
            check.detail = "Auto-created MIT LICENSE"
        return check

    def _check_manifest(
        self, root: Path, auto_fix: bool, created: List[str]
    ) -> HealthCheck:
        """Check for package manifest (package.json, pyproject.toml, etc.)."""
        js_manifest = (root / "package.json").is_file()
        py_manifests = any(
            (root / name).is_file()
            for name in ("pyproject.toml", "setup.py", "setup.cfg")
        )
        found = js_manifest or py_manifests

        # Detect project type
        has_js = (
            any(
                f.suffix.lower() in (".js", ".ts", ".jsx", ".tsx")
                for f in root.iterdir()
                if f.is_file()
            )
            or (root / "node_modules").is_dir()
        )

        check = HealthCheck(
            name="package-manifest",
            description="Package manifest (package.json / pyproject.toml)",
            weight=10,
            passed=found,
            auto_fixable=has_js,
            detail="Add package.json or pyproject.toml for dependency management",
        )

        if not found and auto_fix and has_js:
            _create_package_json_file(root)
            created.append("package.json")
            check.passed = True
            check.detail = "Auto-created package.json"

        return check

    def _check_docker(self, root: Path) -> HealthCheck:
        """Check docker-compose.yml if Dockerfile exists."""
        has_dockerfile = (root / "Dockerfile").is_file()
        if not has_dockerfile:
            # No Dockerfile, so docker-compose is not expected → pass
            return HealthCheck(
                name="docker-compose",
                description="Docker Compose config",
                weight=10,
                passed=True,
                detail="No Dockerfile found — docker-compose check skipped",
            )
        has_compose = any(
            (root / name).is_file()
            for name in (
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            )
        )
        return HealthCheck(
            name="docker-compose",
            description="Docker Compose config",
            weight=10,
            passed=has_compose,
            detail="Add docker-compose.yml for multi-service orchestration",
        )

    def _check_ci(self, root: Path) -> HealthCheck:
        """Check for CI/CD configuration."""
        ci_paths = [
            root / ".github" / "workflows",
            root / ".gitlab-ci.yml",
            root / "Jenkinsfile",
            root / ".circleci",
            root / ".travis.yml",
            root / "azure-pipelines.yml",
            root / "bitbucket-pipelines.yml",
        ]
        found = any(p.exists() for p in ci_paths)
        return HealthCheck(
            name="CI/CD",
            description="Continuous Integration config",
            weight=10,
            passed=found,
            detail="Add CI/CD config (e.g. .github/workflows/) for automation",
        )

    def _check_env_example(self, root: Path) -> HealthCheck:
        """Check for .env.example if .env exists."""
        has_env = (root / ".env").is_file()
        if not has_env:
            return HealthCheck(
                name=".env.example",
                description=".env.example template",
                weight=5,
                passed=True,
                detail="No .env found — .env.example check skipped",
            )
        has_example = any(
            (root / name).is_file()
            for name in (".env.example", ".env.sample", ".env.template")
        )
        return HealthCheck(
            name=".env.example",
            description=".env.example template",
            weight=5,
            passed=has_example,
            detail="Add .env.example so others know which env vars to set",
        )

    def _check_tests(self, root: Path) -> HealthCheck:
        """Check for a tests directory or test files."""
        test_dirs = ("tests", "test", "__tests__", "spec", "specs")
        has_test_dir = any((root / d).is_dir() for d in test_dirs)
        # Also check for test files at root
        has_test_files = any(
            f.name.startswith("test_")
            or f.name.endswith("_test.py")
            or f.name.endswith(".test.js")
            or f.name.endswith(".test.ts")
            or f.name.endswith(".spec.js")
            or f.name.endswith(".spec.ts")
            for f in root.iterdir()
            if f.is_file()
        )
        found = has_test_dir or has_test_files
        return HealthCheck(
            name="tests",
            description="Test suite",
            weight=15,
            passed=found,
            detail="Add a tests/ directory with unit and integration tests",
        )

    def _check_deps(self, root: Path) -> HealthCheck:
        """Check for dependency lock files."""
        lock_files = (
            "requirements.txt",
            "Pipfile.lock",
            "poetry.lock",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lockb",
        )
        found = any((root / f).is_file() for f in lock_files)
        return HealthCheck(
            name="dep-lock",
            description="Dependency lock file",
            weight=5,
            passed=found,
            detail="Add a lock file for reproducible builds",
        )

    def _check_changelog(self, root: Path) -> HealthCheck:
        """Check for CHANGELOG or HISTORY file."""
        names = (
            "CHANGELOG.md",
            "CHANGELOG",
            "CHANGELOG.txt",
            "HISTORY.md",
            "HISTORY",
            "CHANGES.md",
        )
        found = any((root / name).is_file() for name in names)
        return HealthCheck(
            name="CHANGELOG",
            description="Change log",
            weight=5,
            passed=found,
            detail="Add CHANGELOG.md to document version history",
        )

    # ── Auto-fix: create missing files — delegated to module-level helpers ──

    # ── Summary ─────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for unified grading integration."""
        if not self.report:
            return {"total": 0, "critical": 0, "warning": 0, "info": 0}

        by_sev = Counter(i.severity for i in self.report.issues)
        return {
            "total": len(self.report.issues),
            "critical": by_sev.get(Severity.CRITICAL, 0),
            "warning": by_sev.get(Severity.WARNING, 0),
            "info": by_sev.get(Severity.INFO, 0),
            "health_score": self.report.score,
            "health_grade": self.report.grade,
            "checks_passed": sum(1 for c in self.report.checks if c.passed),
            "checks_total": len(self.report.checks),
            "files_created": self.report.files_created,
        }
