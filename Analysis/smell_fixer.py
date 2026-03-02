"""Analysis/smell_fixer.py — Auto-fix engine for code smells.

Implements the ``--fix-smells`` feature: automatically repairs common
code quality issues beyond what Ruff can fix, including:

  - Commenting out leftover console.log debug statements (JS/TS)
  - Commenting out leftover print() debug statements (Python)
  - Auto-creating missing project files (.gitignore, LICENSE, etc.)
  - Adding missing Python docstrings (stub)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from Core.types import SmellIssue, Severity
from Core.config import _ALWAYS_SKIP
from Lang.js_ts_analyzer import WEB_EXTENSIONS

logger = logging.getLogger("X_RAY_FIX")


class SmellFixResult:
    """Result of an auto-fix session."""

    def __init__(self):
        self.files_modified: List[str] = []
        self.fixes_applied: int = 0
        self.console_logs_commented: int = 0
        self.prints_commented: int = 0
        self.docstrings_added: int = 0
        self.project_files_created: List[str] = []
        self.errors: List[str] = []

    def to_dict(self) -> Dict:
        """Serialize to dict."""
        return {
            "files_modified": self.files_modified,
            "fixes_applied": self.fixes_applied,
            "console_logs_commented": self.console_logs_commented,
            "prints_commented": self.prints_commented,
            "docstrings_added": self.docstrings_added,
            "project_files_created": self.project_files_created,
            "errors": self.errors,
        }


class SmellFixer:
    """Auto-fix engine for common code smells.

    Call ``fix_all()`` on a project root to automatically repair
    common issues. The fixer is conservative — it only comments out
    debug statements rather than deleting them, and it only creates
    files that are clearly missing.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.result = SmellFixResult()

    def fix_all(self, root: Path,
                exclude: Optional[List[str]] = None,
                fix_console: bool = True,
                fix_prints: bool = True,
                fix_project: bool = True) -> SmellFixResult:
        """Run all auto-fix passes on the project.

        Parameters
        ----------
        root : Path
            Project root directory.
        exclude : list, optional
            Directory names to skip.
        fix_console : bool
            Comment out console.log/debug/warn statements in JS/TS files.
        fix_prints : bool
            Comment out bare ``print()`` debug statements in Python files.
        fix_project : bool
            Create missing structural files (.gitignore, LICENSE, etc.).
        """
        self.result = SmellFixResult()

        if fix_console:
            self._fix_console_logs(root, exclude)

        if fix_prints:
            self._fix_debug_prints(root, exclude)

        if fix_project:
            self._fix_project_structure(root)

        return self.result

    # ── Console.log commenting (JS/TS) ──────────────────────────────────

    _RE_CONSOLE_LINE = re.compile(
        r"^(\s*)(console\.(log|debug|info|warn|error|trace)\s*\(.*)",
        re.MULTILINE,
    )

    def _fix_console_logs(self, root: Path,
                          exclude: Optional[List[str]]) -> None:
        """Comment out console.log and friends in JS/TS files."""
        for fpath in self._walk_files(root, WEB_EXTENSIONS, exclude):
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            new_content, count = self._comment_console_lines(content)
            if count > 0:
                rel = str(fpath.relative_to(root)).replace("\\", "/")
                if not self.dry_run:
                    fpath.write_text(new_content, encoding="utf-8")
                self.result.console_logs_commented += count
                self.result.fixes_applied += count
                self.result.files_modified.append(rel)
                logger.info(f"Commented {count} console.log(s) in {rel}")

    @staticmethod
    def _comment_console_lines(content: str) -> Tuple[str, int]:
        """Comment out console.log lines, returning (new_content, count)."""
        count = 0

        def _replacer(m):
            nonlocal count
            indent = m.group(1)
            statement = m.group(2)
            # Skip if already commented
            if statement.lstrip().startswith("//"):
                return m.group(0)
            count += 1
            return f"{indent}// [X-Ray auto-fix] {statement}"

        new = SmellFixer._RE_CONSOLE_LINE.sub(_replacer, content)
        return new, count

    # ── Debug print() commenting (Python) ───────────────────────────────

    _RE_DEBUG_PRINT = re.compile(
        r'^(\s*)(print\s*\(.+\))\s*$',
        re.MULTILINE,
    )

    # Patterns that indicate a print is functional, not debug
    _FUNCTIONAL_PRINT_HINTS = frozenset({
        "usage", "help", "version", "error:", "warning:",
        "banner", "header", "report",
    })

    def _fix_debug_prints(self, root: Path,
                          exclude: Optional[List[str]]) -> None:
        """Comment out likely debug print() statements in Python files."""
        py_ext = frozenset({".py"})
        for fpath in self._walk_files(root, py_ext, exclude):
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            new_content, count = self._comment_debug_prints(content)
            if count > 0:
                rel = str(fpath.relative_to(root)).replace("\\", "/")
                if not self.dry_run:
                    fpath.write_text(new_content, encoding="utf-8")
                self.result.prints_commented += count
                self.result.fixes_applied += count
                self.result.files_modified.append(rel)
                logger.info(f"Commented {count} debug print(s) in {rel}")

    def _comment_debug_prints(self, content: str) -> Tuple[str, int]:
        """Comment out bare debug print() calls.

        Only comments prints that look like debugging output (e.g.
        ``print(f"DEBUG: {value}")`` or ``print(some_var)``).
        Skips functional prints that contain usage/help/error keywords.
        """
        count = 0

        def _replacer(m):
            nonlocal count
            indent = m.group(1)
            statement = m.group(2)
            lower = statement.lower()

            # Skip if already commented
            stripped = content[:m.start()].rsplit("\n", 1)[-1] if m.start() > 0 else ""
            if "#" in stripped:
                return m.group(0)

            # Skip functional prints
            if any(hint in lower for hint in self._FUNCTIONAL_PRINT_HINTS):
                return m.group(0)

            # Only comment obvious debug prints
            is_debug = any(kw in lower for kw in (
                "debug", "todo", "fixme", "hack", "xxx",
                "print(f\"", "print(f'", "print(f\"{",
            ))
            # Also flag bare variable prints: print(variable_name)
            inner_match = re.match(r'print\s*\(\s*(\w+)\s*\)', statement)
            if inner_match and not is_debug:
                var = inner_match.group(1)
                if var not in ("help", "usage", "version"):
                    is_debug = True

            if not is_debug:
                return m.group(0)

            count += 1
            return f"{indent}# [X-Ray auto-fix] {statement}"

        new = self._RE_DEBUG_PRINT.sub(_replacer, content)
        return new, count

    # ── Project structure auto-fix ──────────────────────────────────────

    def _fix_project_structure(self, root: Path) -> None:
        """Create missing project boilerplate files."""
        from Analysis.project_health import ProjectHealthAnalyzer

        analyzer = ProjectHealthAnalyzer()
        report = analyzer.analyze(root, auto_fix=not self.dry_run)
        self.result.project_files_created.extend(report.files_created)
        self.result.fixes_applied += len(report.files_created)

    # ── File walking utility ────────────────────────────────────────────

    @staticmethod
    def _walk_files(root: Path, extensions: frozenset,
                    exclude: Optional[List[str]] = None):
        """Yield files matching *extensions* under *root*, respecting excludes."""
        exclude = exclude or []
        skip = _ALWAYS_SKIP | {"node_modules", "dist", "build", ".next"}
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            dirnames[:] = [
                d for d in dirnames
                if d not in skip
                and not d.endswith(".egg-info")
                and not any(
                    (os.path.join(rel, d) if rel != "." else d).startswith(p)
                    for p in exclude
                )
            ]
            for fn in filenames:
                if Path(fn).suffix.lower() in extensions:
                    yield Path(dirpath) / fn
