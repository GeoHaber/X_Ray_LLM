"""
Analysis/_analyzer_base.py — Shared base class for static analyzers
====================================================================

Provides ``BaseStaticAnalyzer`` with the common template-method
pattern used by both LintAnalyzer (ruff) and SecurityAnalyzer (bandit).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.utils import logger

# Shared auto-exclude patterns used by both lint and security analyzers.
AUTO_EXCLUDE: List[str] = [
    ".venv", "venv", ".env", "__pycache__", "node_modules",
    ".git", "target", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".eggs", "*.egg-info",
    "_scratch", ".github", "_OLD",
]


def _merged_excludes(extra: Optional[List[str]] = None) -> List[str]:
    """Return *AUTO_EXCLUDE* merged with any user-supplied *extra* patterns."""
    result = list(AUTO_EXCLUDE)
    if extra:
        result.extend(extra)
    return result


def _find_tool(tool_name: str) -> Optional[str]:
    """Locate a CLI tool by *tool_name*, including in frozen PyInstaller bundles."""
    # 1. Normal PATH lookup
    found = shutil.which(tool_name)
    if found:
        return found

    # 2. Frozen exe: check the bundle directory (onedir mode)
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        exe_dir = Path(sys.executable).parent
        candidates.extend([
            meipass / f"{tool_name}.exe",
            exe_dir / f"{tool_name}.exe",
            exe_dir / "tools" / f"{tool_name}.exe",
            meipass / tool_name,
            exe_dir / tool_name,
            exe_dir / "tools" / tool_name,
        ])
    else:
        # Dev mode: check .venv/Scripts
        project = Path(__file__).resolve().parent.parent
        candidates.append(project / ".venv" / "Scripts" / f"{tool_name}.exe")

    for p in candidates:
        if p.is_file():
            logger.info(f"Found {tool_name} at: {p}")
            return str(p)

    return None


class BaseStaticAnalyzer:
    """
    Template-method base for subprocess-based static analyzers.

    Subclasses must set class attributes ``TOOL_NAME``, ``TOOL_TIMEOUT``,
    ``TOOL_LOG_NAME`` and override ``_build_command`` and ``_to_smell_issue``.
    """

    TOOL_NAME: str = ""
    TOOL_TIMEOUT: int = 120
    TOOL_LOG_NAME: str = ""

    def __init__(self, extra_args: Optional[List[str]] = None):
        self.extra_args = extra_args or []
        self._tool_path = _find_tool(self.TOOL_NAME)

    @property
    def available(self) -> bool:
        """Check if the tool is installed and executable."""
        return self._tool_path is not None

    # -- template method ---------------------------------------------------

    def analyze(self, root: Path, exclude: Optional[List[str]] = None) -> List[SmellIssue]:
        """Run the tool on *root* and return a sorted SmellIssue list."""
        if not self.available:
            logger.warning(
                f"{self.TOOL_LOG_NAME} is not installed. "
                f"Run: pip install {self.TOOL_NAME}"
            )
            return []

        cmd = self._build_command(root, exclude)
        raw = self._run_subprocess(cmd, root)
        if raw is not None:
            raw = self._preprocess_output(raw)
        data = self._parse_raw_json(raw) if raw is not None else None
        if data is None:
            return []
        items = self._extract_items(data)
        return self._convert_items(items, root)

    # -- abstract methods (must override) ----------------------------------

    def _build_command(self, root: Path,
                       exclude: Optional[List[str]]) -> List[str]:
        """Assemble the CLI command list.  Must be overridden."""
        raise NotImplementedError

    def _to_smell_issue(self, item: Dict[str, Any],
                        root: Path) -> Optional[SmellIssue]:
        """Convert a single tool result item to SmellIssue.  Must be overridden."""
        raise NotImplementedError

    # -- hooks (override if needed) ----------------------------------------

    def _preprocess_output(self, raw: str) -> Optional[str]:
        """Transform raw stdout before JSON parsing.  Default: identity."""
        return raw

    def _extract_items(self, data: Any) -> list:
        """Extract the iterable of finding items from parsed JSON data.

        Default returns *data* itself (works for tools that emit a JSON array).
        """
        return data

    # -- shared helpers ----------------------------------------------------

    def _run_subprocess(self, cmd: List[str],
                        root: Path) -> Optional[str]:
        """Execute the tool, return raw stdout string or *None* on failure."""
        logger.info(f"Running {self.TOOL_LOG_NAME}: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.TOOL_TIMEOUT, cwd=str(root),
            )
        except FileNotFoundError:
            logger.error(f"{self.TOOL_LOG_NAME} executable not found.")
            return None
        except subprocess.TimeoutExpired:
            logger.error(
                f"{self.TOOL_LOG_NAME} timed out after {self.TOOL_TIMEOUT}s."
            )
            return None

        raw = (result.stdout or "").strip()
        if not raw:
            logger.info(
                f"{self.TOOL_LOG_NAME} returned no output "
                f"(clean or empty project)."
            )
            return None
        return raw

    def _parse_raw_json(self, raw: str) -> Any:
        """Parse a raw JSON string.  Returns parsed data or *None*."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse {self.TOOL_LOG_NAME} JSON output: {e}"
            )
            logger.debug(f"Raw output (first 500 chars): {raw[:500]}")
            return None

    def _convert_items(self, items: list, root: Path) -> List[SmellIssue]:
        """Convert raw items to SmellIssue list, sort, and log count."""
        issues = [
            issue for item in items
            if (issue := self._to_smell_issue(item, root)) is not None
        ]
        issues.sort(key=lambda s: (
            0 if s.severity == Severity.CRITICAL else
            1 if s.severity == Severity.WARNING else 2,
            s.file_path, s.line,
        ))
        logger.info(f"{self.TOOL_LOG_NAME} found {len(issues)} issues.")
        return issues

    def summary(self, issues: List[SmellIssue]) -> Dict[str, Any]:
        """Build a summary dict from issues."""
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
            "source": self.TOOL_NAME,
        }
