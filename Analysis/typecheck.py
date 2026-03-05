"""
Analysis/typecheck.py — Pyright Type Checker Integration for X-Ray
===================================================================

Wraps ``pyright --outputjson`` as a subprocess, parses JSON output,
and converts diagnostics into X-Ray SmellIssue objects for unified
reporting.

Catches argument mismatches, missing attributes, wrong types, and
other bugs that only surface at runtime — complementing Ruff (lint)
and Bandit (security).

Requires: pyright (pip install pyright)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from Core.types import SmellIssue, Severity
from Analysis._analyzer_base import BaseStaticAnalyzer


# Pyright severity → X-Ray severity mapping
_SEVERITY_MAP: Dict[str, str] = {
    "error": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "information": Severity.INFO,
}


class TypecheckAnalyzer(BaseStaticAnalyzer):
    """
    Runs Pyright type checker and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = TypecheckAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"))
    """

    TOOL_NAME = "pyright"
    TOOL_TIMEOUT = 180
    TOOL_LOG_NAME = "Pyright"

    # -- overrides ---------------------------------------------------------

    def _build_command(self, root: Path, exclude: Optional[List[str]]) -> List[str]:
        """Assemble the pyright CLI command list."""
        cmd = [
            self._tool_path,
            "--outputjson",
            str(root),
        ]
        # Pyright doesn't have --exclude flags like Ruff; it uses
        # pyrightconfig.json or pyproject.toml [tool.pyright] for excludes.
        # We pass extra args if configured.
        cmd.extend(self.extra_args)
        return cmd

    def _extract_items(self, data: Any) -> list:
        """Pyright wraps diagnostics in a top-level object."""
        if isinstance(data, dict):
            return data.get("generalDiagnostics", [])
        return []

    def _to_smell_issue(self, item: Dict[str, Any], root: Path) -> Optional[SmellIssue]:
        """Convert a single Pyright diagnostic to SmellIssue."""
        file_path = item.get("file", "")
        severity_str = item.get("severity", "information")
        message = item.get("message", "")
        rule = item.get("rule", "")
        rng = item.get("range", {})

        # Make path relative to root
        try:
            rel_path = str(Path(file_path).relative_to(root))
        except ValueError:
            rel_path = file_path

        # Pyright lines are 0-based; X-Ray expects 1-based
        start = rng.get("start", {})
        end = rng.get("end", {})
        line = start.get("line", 0) + 1
        end_line = end.get("line", line - 1) + 1

        severity = _SEVERITY_MAP.get(severity_str, Severity.INFO)

        # Category is the rule family (e.g. reportCallIssue → "call-issue")
        category = self._rule_to_category(rule)

        return SmellIssue(
            file_path=rel_path,
            line=line,
            end_line=end_line,
            category=category,
            severity=severity,
            message=f"[{rule}] {message}" if rule else message,
            suggestion="Fix the type error indicated by Pyright.",
            name="",
            metric_value=0,
            source="pyright",
            rule_code=rule,
            fixable=False,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _rule_to_category(rule: str) -> str:
        """Convert a pyright rule name to a kebab-case category slug.

        ``reportCallIssue`` → ``call-issue``
        ``reportArgumentType`` → ``argument-type``
        """
        if not rule:
            return "type-error"
        # Strip 'report' prefix
        name = rule
        if name.startswith("report"):
            name = name[6:]
        # Convert camelCase to kebab-case
        parts: list = []
        current: list = []
        for ch in name:
            if ch.isupper() and current:
                parts.append("".join(current).lower())
                current = [ch]
            else:
                current.append(ch)
        if current:
            parts.append("".join(current).lower())
        return "-".join(parts) or "type-error"
