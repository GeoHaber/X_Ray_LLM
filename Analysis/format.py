"""
Analysis/format.py — Ruff Format Check Integration for X-Ray
=============================================================

Wraps `ruff format --check` as a subprocess, parses output,
and converts findings into X-Ray SmellIssue objects for
unified reporting when scanning any project.

Best practices enforced (via [tool.ruff.format] in pyproject.toml):
  - line-length 88 (Black default, PEP 8)
  - quote-style double
  - indent-style space (PEP 8)
  - skip-magic-trailing-comma false (respect trailing commas)
  - line-ending auto

Requires: ruff (pip install ruff)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from Core.types import SmellIssue, Severity
from Analysis._analyzer_base import AUTO_EXCLUDE, _find_tool


def _build_format_cmd(tool: str, root: Path, exclude: Optional[List[str]]) -> List[str]:
    """Build ruff format --check command with exclusions."""
    all_exclude = [*AUTO_EXCLUDE, *(exclude or [])]
    return [tool, "format", "--check", str(root)] + [
        arg for pat in all_exclude for arg in ("--exclude", pat)
    ]


def _parse_format_output(lines: List[str], root: Path) -> List[SmellIssue]:
    """Parse 'Would reformat: path' lines into SmellIssue list."""
    prefix = "Would reformat:"
    root_res = root.resolve()
    issues: List[SmellIssue] = []
    for line in lines:
        s = line.strip()
        if not s.startswith(prefix) or not s.endswith(".py"):
            continue
        raw_path = s[len(prefix) :].strip()
        try:
            rel_path = str((root / raw_path).resolve().relative_to(root_res)).replace(
                "\\", "/"
            )
        except ValueError:
            rel_path = raw_path.replace("\\", "/")
        issues.append(
            SmellIssue(
                file_path=rel_path,
                line=1,
                end_line=1,
                category="format",
                severity=Severity.WARNING,
                message="File is not formatted (ruff format)",
                suggestion=f"Run: ruff format {rel_path}",
                name="",
                metric_value=0,
                source="ruff-format",
                rule_code="RUF001",
                fixable=True,
            )
        )
    return sorted(issues, key=lambda s: s.file_path)


class FormatAnalyzer:
    """
    Runs `ruff format --check` and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = FormatAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"), exclude=[...])
    """

    TOOL_NAME = "ruff"
    TOOL_TIMEOUT = 120

    def __init__(self):
        self._tool_path = _find_tool("ruff")

    @property
    def available(self) -> bool:
        """Check if ruff is installed."""
        return self._tool_path is not None

    def analyze(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[SmellIssue]:
        """Run ruff format --check on root and return SmellIssue list."""
        if not self.available:
            return []
        cmd = _build_format_cmd(self._tool_path, root, exclude or [])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.TOOL_TIMEOUT,
                cwd=str(root),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        lines = (result.stdout or "").splitlines()
        return _parse_format_output(lines, root)

    def summary(self, issues: List[SmellIssue]) -> dict:
        """Build summary dict from format issues."""
        n = len(issues)
        return {
            "total": n,
            "critical": 0,
            "warning": n,
            "info": 0,
            "fixable": n,
            "source": "ruff-format",
        }


# ── Module-level API ────────────────────────────────────────────────────────


# Global analyzer instance
_default_analyzer = FormatAnalyzer()


def available() -> bool:
    """Check if ruff format is available."""
    return _default_analyzer.available


def analyze(
    root: Path, exclude: Optional[List[str]] = None
) -> List[SmellIssue]:
    """Analyze code formatting with ruff."""
    if root is None:
        raise ValueError("root path cannot be None")
    return _default_analyzer.analyze(root, exclude)


def summary(issues: List[SmellIssue]) -> dict:
    """Generate summary statistics for format issues."""
    return _default_analyzer.summary(issues)
