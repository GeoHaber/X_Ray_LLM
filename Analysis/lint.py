"""
Analysis/lint.py — Ruff Linter Integration for X-Ray
=====================================================

Wraps `ruff check` as a subprocess, parses JSON output,
and converts findings into X-Ray SmellIssue objects for
unified reporting.

Requires: ruff (pip install ruff)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.utils import logger


# Ruff rule code → X-Ray severity mapping
_SEVERITY_MAP: Dict[str, str] = {
    # Fatal / likely bugs → CRITICAL
    "F811": Severity.CRITICAL,   # redefined-while-unused
    "E999": Severity.CRITICAL,   # syntax-error
    "F821": Severity.CRITICAL,   # undefined-name
    # Hygiene issues → WARNING
    "F401": Severity.WARNING,    # unused-import
    "F841": Severity.WARNING,    # unused-variable
    "E722": Severity.WARNING,    # bare-except
    "E741": Severity.WARNING,    # ambiguous-variable-name
    "E402": Severity.WARNING,    # module-import-not-at-top
    "F541": Severity.INFO,       # f-string-missing-placeholders
    "E701": Severity.INFO,       # multiple-statements-on-one-line
}


class LintAnalyzer:
    """
    Runs Ruff linter and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = LintAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"))
    """

    def __init__(self, extra_args: Optional[List[str]] = None):
        self.extra_args = extra_args or []
        self._ruff_path = shutil.which("ruff")

    @property
    def available(self) -> bool:
        """Check if ruff is installed and executable."""
        return self._ruff_path is not None

    def analyze(self, root: Path, exclude: Optional[List[str]] = None) -> List[SmellIssue]:
        """
        Run ``ruff check`` on `root` and return SmellIssue list.

        Parameters
        ----------
        root : Path
            Directory to scan.
        exclude : list[str], optional
            Glob patterns to exclude (passed via --exclude).

        Returns
        -------
        list[SmellIssue]
            Issues found, mapped to X-Ray severity levels.
        """
        if not self.available:
            logger.warning("Ruff is not installed. Run: pip install ruff")
            return []

        cmd = self._build_ruff_command(root, exclude)
        raw = self._run_ruff_subprocess(cmd, root)
        if raw is None:
            return []
        return self._parse_ruff_results(raw, root)

    # -- private helpers (extracted from analyze) ----------------------------

    def _build_ruff_command(self, root: Path,
                            exclude: Optional[List[str]]) -> List[str]:
        """Assemble the ruff CLI command list."""
        cmd = [
            self._ruff_path, "check", str(root),
            "--output-format=json", "--no-fix",
        ]
        auto_exclude = [
            ".venv", "venv", ".env", "__pycache__", "node_modules",
            ".git", "target", ".mypy_cache", ".pytest_cache",
            "dist", "build", ".eggs", "*.egg-info",
            "_scratch", ".github",
        ]
        all_exclude = list(auto_exclude)
        if exclude:
            all_exclude.extend(exclude)
        for pat in all_exclude:
            cmd.extend(["--exclude", pat])
        cmd.extend(self.extra_args)
        return cmd

    def _run_ruff_subprocess(self, cmd: List[str],
                             root: Path) -> Optional[str]:
        """Execute ruff, return raw JSON string or *None* on failure."""
        logger.info(f"Running Ruff: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=120, cwd=str(root),
            )
        except FileNotFoundError:
            logger.error("Ruff executable not found despite which() succeeding.")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Ruff timed out after 120s.")
            return None

        raw = (result.stdout or "").strip()
        if not raw:
            logger.info("Ruff returned no output (clean or empty project).")
            return None
        return raw

    def _parse_ruff_results(self, raw: str,
                            root: Path) -> List[SmellIssue]:
        """Parse raw JSON string into sorted SmellIssue list."""
        try:
            ruff_issues = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ruff JSON output: {e}")
            logger.debug(f"Raw output (first 500 chars): {raw[:500]}")
            return []

        issues = [
            issue for item in ruff_issues
            if (issue := self._to_smell_issue(item, root)) is not None
        ]
        issues.sort(key=lambda s: (
            0 if s.severity == Severity.CRITICAL else
            1 if s.severity == Severity.WARNING else 2,
            s.file_path, s.line,
        ))
        logger.info(f"Ruff found {len(issues)} issues.")
        return issues

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

    @staticmethod
    def _map_severity(code: str) -> str:
        """Map Ruff rule code to X-Ray severity."""
        if code in _SEVERITY_MAP:
            return _SEVERITY_MAP[code]
        # Fallback by prefix
        prefix = code[0] if code else ""
        if prefix == "F":
            return Severity.WARNING      # F = pyflakes (likely bugs)
        if prefix == "E":
            return Severity.INFO         # E = pycodestyle (style)
        if prefix == "W":
            return Severity.INFO         # W = pycodestyle warnings
        return Severity.INFO

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

    def summary(self, issues: List[SmellIssue]) -> Dict[str, Any]:
        """Build a summary dict from lint issues."""
        from collections import Counter
        by_severity = Counter(s.severity for s in issues)
        by_rule = Counter(s.rule_code for s in issues)
        by_file = Counter(s.file_path for s in issues)
        fixable_count = sum(1 for s in issues if s.fixable)

        return {
            "total": len(issues),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "fixable": fixable_count,
            "by_rule": dict(by_rule.most_common(20)),
            "worst_files": dict(by_file.most_common(10)),
            "source": "ruff",
        }
