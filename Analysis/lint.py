"""
Analysis/lint.py — Ruff Linter Integration for X-Ray
=====================================================

Wraps `ruff check` as a subprocess, parses JSON output,
and converts findings into X-Ray SmellIssue objects for
unified reporting.

Requires: ruff (pip install ruff)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Analysis._analyzer_base import BaseStaticAnalyzer, _merged_excludes


# Ruff rule code → X-Ray severity mapping
_SEVERITY_MAP: Dict[str, str] = {
    # Fatal / likely bugs → CRITICAL
    "F811": Severity.CRITICAL,  # redefined-while-unused
    "E999": Severity.CRITICAL,  # syntax-error
    "F821": Severity.CRITICAL,  # undefined-name
    # Hygiene issues → WARNING
    "F401": Severity.WARNING,  # unused-import
    "F841": Severity.WARNING,  # unused-variable
    "E722": Severity.WARNING,  # bare-except
    "E741": Severity.WARNING,  # ambiguous-variable-name
    "E402": Severity.WARNING,  # module-import-not-at-top
    "F541": Severity.INFO,  # f-string-missing-placeholders
    "E701": Severity.INFO,  # multiple-statements-on-one-line
}


class LintAnalyzer(BaseStaticAnalyzer):
    """
    Runs Ruff linter and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = LintAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"))
    """

    TOOL_NAME = "ruff"
    TOOL_TIMEOUT = 120
    TOOL_LOG_NAME = "Ruff"

    # -- overrides ---------------------------------------------------------

    def _build_command(self, root: Path, exclude: Optional[List[str]]) -> List[str]:
        """Assemble the ruff CLI command list."""
        cmd = [
            self._tool_path,
            "check",
            str(root),
            "--output-format=json",
            "--no-fix",
        ]
        all_exclude = _merged_excludes(exclude)
        for pat in all_exclude:
            cmd.extend(["--exclude", pat])
        cmd.extend(self.extra_args)
        return cmd

    def _to_smell_issue(self, item: Dict[str, Any], root: Path) -> Optional[SmellIssue]:
        """Convert a single Ruff JSON object to SmellIssue."""
        code = item.get("code", "")
        message = item.get("message", "")
        filename = item.get("filename", "")
        location = item.get("location", {})
        end_location = item.get("end_location", {})
        fix = item.get("fix")

        # Make path relative to root
        try:
            rel_path = str(Path(filename).relative_to(root))
        except ValueError:
            rel_path = filename

        line = location.get("row", 0)
        end_line = end_location.get("row", line)

        severity = self._map_severity(code)

        # Category is the rule family (e.g., F401 → "unused-import")
        category = self._rule_to_category(code)

        # Build suggestion from fix info
        suggestion = ""
        fixable = False
        if fix:
            fixable = fix.get("applicability", "") in ("safe", "unsafe")
            suggestion = fix.get("message", "")
            if fixable and not suggestion:
                suggestion = "Auto-fixable with `ruff check --fix`"

        return SmellIssue(
            file_path=rel_path,
            line=line,
            end_line=end_line,
            category=category,
            severity=severity,
            message=f"[{code}] {message}",
            suggestion=suggestion,
            name="",  # Ruff doesn't provide function/class name context
            metric_value=0,
            source="ruff",
            rule_code=code,
            fixable=fixable,
        )

    # -- auto-fix ----------------------------------------------------------

    def fix(self, root: Path, exclude: Optional[List[str]] = None) -> int:
        """Run ``ruff check --fix`` and return the number of issues auto-fixed.

        Returns 0 if ruff is not available or the command fails.
        """
        if not self.available:
            return 0
        import subprocess

        cmd = [self._tool_path, "check", "--fix", str(root)]
        for pat in _merged_excludes(exclude):
            cmd.extend(["--exclude", pat])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TOOL_TIMEOUT,
            )
            # ruff prints "Fixed N errors." on stderr when --fix applied changes
            import re

            match = re.search(r"Fixed (\d+) error", result.stderr + result.stdout)
            return int(match.group(1)) if match else 0
        except Exception:
            return 0

    # -- static helpers (ruff-specific) ------------------------------------

    _PREFIX_SEVERITY = {"F": Severity.WARNING, "E": Severity.INFO, "W": Severity.INFO}

    @staticmethod
    def _map_severity(code: str) -> str:
        """Map Ruff rule code to X-Ray severity."""
        if code in _SEVERITY_MAP:
            return _SEVERITY_MAP[code]
        # Fallback by prefix
        prefix = code[0] if code else ""
        return LintAnalyzer._PREFIX_SEVERITY.get(prefix, Severity.INFO)

    @staticmethod
    def _rule_to_category(code: str) -> str:
        """Map Ruff rule code to a human-readable category string."""
        categories = {
            "F401": "unused-import",
            "F811": "redefined-unused",
            "F841": "unused-variable",
            "F541": "f-string-no-placeholder",
            "F821": "undefined-name",
            "E722": "bare-except",
            "E741": "ambiguous-name",
            "E402": "import-not-at-top",
            "E701": "multiple-statements",
            "E999": "syntax-error",
        }
        return categories.get(code, f"lint-{code}")


# ── Module-level API ────────────────────────────────────────────────────────


# Global analyzer instance
_default_lint_analyzer = LintAnalyzer()


def fix(root: Path, exclude: Optional[List[str]] = None) -> int:
    """Run ruff check --fix to auto-fix linting issues."""
    if root is None:
        raise ValueError("root path cannot be None")
    return _default_lint_analyzer.fix(root, exclude)
