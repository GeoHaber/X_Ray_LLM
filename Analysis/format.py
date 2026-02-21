"""
Analysis/format.py — Ruff Format Check Integration for X-Ray
=============================================================

Wraps `ruff format --check` as a subprocess, parses output,
and converts findings into X-Ray SmellIssue objects for
unified reporting when scanning any project.

Requires: ruff (pip install ruff)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from Core.types import SmellIssue, Severity


def _find_ruff() -> Optional[str]:
    """Locate ruff CLI, including in frozen PyInstaller bundles."""
    found = shutil.which("ruff")
    if found:
        return found
    if not getattr(sys, "frozen", False):
        return None
    meipass = Path(getattr(sys, "_MEIPASS", ""))
    exe_dir = Path(sys.executable).parent
    for base in (meipass, exe_dir, exe_dir / "tools"):
        for name in ("ruff.exe", "ruff"):
            p = base / name
            if p.is_file():
                return str(p)
    return None


def _build_format_cmd(tool: str, root: Path, exclude: list) -> List[str]:
    """Build ruff format --check command with exclusions."""
    auto_exclude = [
        ".venv",
        "venv",
        ".env",
        "__pycache__",
        "node_modules",
        ".git",
        "target",
        "dist",
        "build",
        "_scratch",
    ]
    all_exclude = list(auto_exclude)
    if exclude:
        all_exclude.extend(exclude)
    cmd = [tool, "format", "--check", str(root)]
    for pat in all_exclude:
        cmd.extend(["--exclude", pat])
    return cmd


def _parse_format_output(lines: List[str], root: Path) -> List[SmellIssue]:
    """Parse 'Would reformat: path' lines into SmellIssue list."""
    pattern = re.compile(r"Would reformat:\s*(.+\.py)\s*$")
    issues: List[SmellIssue] = []
    for line in lines:
        m = pattern.match(line.strip())
        if not m:
            continue
        raw_path = m.group(1).strip()
        try:
            abs_path = (root / raw_path).resolve()
            rel_path = str(abs_path.relative_to(root.resolve())).replace("\\", "/")
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
                suggestion="Run: ruff format " + rel_path,
                name="",
                metric_value=0,
                source="ruff-format",
                rule_code="RUF001",
                fixable=True,
            )
        )
    return sorted(issues, key=lambda s: (s.file_path, s.line))


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
        self._tool_path = _find_ruff()

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
        return {
            "total": len(issues),
            "critical": 0,
            "warning": len(issues),
            "info": 0,
            "fixable": len(issues),
            "source": "ruff-format",
        }
