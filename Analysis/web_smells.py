"""Analysis/web_smells.py — Web-specific code smell detector for JS/TS/React.

Detects common web development anti-patterns and code smells in
JavaScript, TypeScript, and React (JSX/TSX) files.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.config import _ALWAYS_SKIP
from Lang.js_ts_analyzer import (
    WEB_EXTENSIONS,
    analyze_js_file,
    JSFileAnalysis,
    JSFunction,
    categorize_imports,
)

logger = logging.getLogger("X_RAY_WEB")

# ── Thresholds ──────────────────────────────────────────────────────────

WEB_THRESHOLDS = {
    "long_function": 50,           # lines
    "very_long_function": 100,     # lines → critical
    "deep_nesting": 4,             # brace depth
    "very_deep_nesting": 6,        # → critical
    "high_complexity": 10,         # cyclomatic
    "very_high_complexity": 20,    # → critical
    "too_many_params": 5,          # parameters
    "large_file": 300,             # lines
    "very_large_file": 600,        # → critical
    "large_component": 200,        # lines for React component
    "too_many_imports": 20,        # imports in one file
    "console_log_threshold": 3,    # flag if > N console.logs
}


# ── Web smell factory ───────────────────────────────────────────────────

_WEB_SOURCE = "xray-web"


def _make_web_smell(
    loc: tuple,
    spec: tuple,
) -> "SmellIssue":
    """Create a SmellIssue from a (file, line, end_line) + (cat, sev, msg, sug, name[, metric]) tuple."""
    file_path, line, end_line = loc
    category, severity, message, suggestion, name = spec[:5]
    metric = spec[5] if len(spec) > 5 else 0
    return SmellIssue(
        file_path=file_path,
        line=line,
        end_line=end_line,
        category=category,
        severity=severity,
        message=message,
        suggestion=suggestion,
        name=name,
        metric_value=metric,
        source=_WEB_SOURCE,
    )


# ── Web smell detection ─────────────────────────────────────────────────

class WebSmellDetector:
    """Detects code smells in JS/TS/React files.

    Runs 12+ heuristic checks per file covering:
      - Function size and complexity
      - Console.log pollution
      - Large components
      - Deep callback nesting
      - Missing error handling in async
      - Any type abuse (TypeScript)
      - Inline styles in JSX
      - Large files
      - Import sprawl
    """

    def __init__(self, thresholds: Optional[Dict[str, int]] = None):
        self.thresholds = {**WEB_THRESHOLDS, **(thresholds or {})}
        self.smells: List[SmellIssue] = []
        self._analyses: List[JSFileAnalysis] = []

    def detect(self, root: Path,
               exclude: Optional[List[str]] = None) -> List[SmellIssue]:
        """Scan all JS/TS files under *root* and return detected smells."""
        self.smells = []
        self._analyses = []

        web_files = _collect_web_files(root, exclude)
        logger.info(f"Scanning {len(web_files)} JS/TS files...")

        for fpath in web_files:
            analysis = analyze_js_file(fpath, root)
            self._analyses.append(analysis)
            self._check_file(analysis)

        self.smells.sort(
            key=lambda s: (0 if s.severity == Severity.CRITICAL else 1,
                           s.file_path, s.line)
        )
        return self.smells

    # ── Per-file checks ─────────────────────────────────────────────────

    def _check_file(self, analysis: JSFileAnalysis) -> None:
        """Run all smell checks on one file analysis."""
        fp = analysis.file_path

        # 1. Large file
        self._check_large_file(analysis)

        # 2. Console.log pollution
        self._check_console_logs(analysis)

        # 3. Too many imports
        self._check_import_sprawl(analysis)

        # 4. Per-function checks
        for func in analysis.functions:
            self._check_function_size(func)
            self._check_function_complexity(func)
            self._check_deep_nesting(func)
            self._check_too_many_params(func)
            self._check_async_no_catch(func)

        # 5. React-specific checks
        if analysis.has_jsx:
            for func in analysis.functions:
                if func.is_react_component:
                    self._check_large_component(func)
                    self._check_inline_styles(func)

        # 6. TypeScript-specific
        if analysis.language in ("typescript", "react-typescript"):
            self._check_any_abuse(analysis)

    def _check_large_file(self, analysis: JSFileAnalysis) -> None:
        """Flag files that are too large."""
        t = self.thresholds
        loc = (analysis.file_path, 1, analysis.total_lines)
        if analysis.total_lines >= t["very_large_file"]:
            self.smells.append(_make_web_smell(
                loc, ("large-file", Severity.CRITICAL,
                       f"File is {analysis.total_lines} lines (threshold: {t['very_large_file']})",
                       "Split into multiple modules or extract helper files",
                       analysis.file_path, analysis.total_lines)))
        elif analysis.total_lines >= t["large_file"]:
            self.smells.append(_make_web_smell(
                loc, ("large-file", Severity.WARNING,
                       f"File is {analysis.total_lines} lines (threshold: {t['large_file']})",
                       "Consider splitting into smaller modules",
                       analysis.file_path, analysis.total_lines)))

    def _check_console_logs(self, analysis: JSFileAnalysis) -> None:
        """Flag excessive console.log usage."""
        count = len(analysis.console_logs)
        if count > self.thresholds["console_log_threshold"]:
            first_line = analysis.console_logs[0] if analysis.console_logs else 1
            severity = Severity.WARNING if count < 10 else Severity.CRITICAL
            self.smells.append(_make_web_smell(
                (analysis.file_path, first_line, first_line),
                ("console-log-pollution", severity,
                 f"{count} console.log/warn/error calls found",
                 "Remove or replace with a proper logging library",
                 analysis.file_path, count)))

    def _check_import_sprawl(self, analysis: JSFileAnalysis) -> None:
        """Flag files with too many imports."""
        count = len(analysis.imports)
        if count > self.thresholds["too_many_imports"]:
            self.smells.append(_make_web_smell(
                (analysis.file_path, 1, 1),
                ("import-sprawl", Severity.WARNING,
                 f"{count} imports — file may have too many dependencies",
                 "Consider splitting into focused modules or using barrel exports",
                 analysis.file_path, count)))

    def _check_function_size(self, func: JSFunction) -> None:
        """Flag long functions."""
        t = self.thresholds
        loc = (func.file_path, func.line_start, func.line_end)
        if func.size_lines >= t["very_long_function"]:
            self.smells.append(_make_web_smell(
                loc, ("long-function", Severity.CRITICAL,
                       f"'{func.name}' is {func.size_lines} lines (threshold: {t['very_long_function']})",
                       "Extract helper functions to reduce size",
                       func.name, func.size_lines)))
        elif func.size_lines >= t["long_function"]:
            self.smells.append(_make_web_smell(
                loc, ("long-function", Severity.WARNING,
                       f"'{func.name}' is {func.size_lines} lines (threshold: {t['long_function']})",
                       "Consider extracting helper functions",
                       func.name, func.size_lines)))

    def _check_function_complexity(self, func: JSFunction) -> None:
        """Flag complex functions."""
        t = self.thresholds
        loc = (func.file_path, func.line_start, func.line_end)
        if func.complexity >= t["very_high_complexity"]:
            self.smells.append(_make_web_smell(
                loc, ("complex-function", Severity.CRITICAL,
                       f"'{func.name}' has cyclomatic complexity {func.complexity} (threshold: {t['very_high_complexity']})",
                       "Decompose into smaller, focused functions",
                       func.name, func.complexity)))
        elif func.complexity >= t["high_complexity"]:
            self.smells.append(_make_web_smell(
                loc, ("complex-function", Severity.WARNING,
                       f"'{func.name}' has cyclomatic complexity {func.complexity} (threshold: {t['high_complexity']})",
                       "Consider reducing branching/nesting",
                       func.name, func.complexity)))

    def _check_deep_nesting(self, func: JSFunction) -> None:
        """Flag deeply nested functions."""
        t = self.thresholds
        loc = (func.file_path, func.line_start, func.line_end)
        if func.nesting_depth >= t["very_deep_nesting"]:
            self.smells.append(_make_web_smell(
                loc, ("deep-nesting", Severity.CRITICAL,
                       f"'{func.name}' has nesting depth {func.nesting_depth} (threshold: {t['very_deep_nesting']})",
                       "Use early returns, extract helpers, or flatten logic",
                       func.name, func.nesting_depth)))
        elif func.nesting_depth >= t["deep_nesting"]:
            self.smells.append(_make_web_smell(
                loc, ("deep-nesting", Severity.WARNING,
                       f"'{func.name}' has nesting depth {func.nesting_depth} (threshold: {t['deep_nesting']})",
                       "Consider early returns or guard clauses",
                       func.name, func.nesting_depth)))

    def _check_too_many_params(self, func: JSFunction) -> None:
        """Flag functions with too many parameters."""
        t = self.thresholds
        if len(func.parameters) >= t["too_many_params"]:
            self.smells.append(_make_web_smell(
                (func.file_path, func.line_start, func.line_end),
                ("too-many-params", Severity.WARNING,
                 f"'{func.name}' has {len(func.parameters)} parameters (threshold: {t['too_many_params']})",
                 "Use an options/config object instead of positional args",
                 func.name, len(func.parameters))))

    def _check_async_no_catch(self, func: JSFunction) -> None:
        """Flag async functions that lack try/catch or .catch()."""
        if not func.is_async:
            return
        code = func.code
        has_try = "try" in code and "catch" in code
        has_dot_catch = ".catch(" in code
        if not has_try and not has_dot_catch and func.size_lines > 5:
            self.smells.append(_make_web_smell(
                (func.file_path, func.line_start, func.line_end),
                ("async-no-error-handling", Severity.WARNING,
                 f"Async function '{func.name}' has no try/catch or .catch()",
                 "Wrap async logic in try/catch for proper error handling",
                 func.name)))

    def _check_large_component(self, func: JSFunction) -> None:
        """Flag React components that are too large."""
        t = self.thresholds
        if func.size_lines >= t["large_component"]:
            self.smells.append(_make_web_smell(
                (func.file_path, func.line_start, func.line_end),
                ("large-component", Severity.WARNING,
                 f"React component '{func.name}' is {func.size_lines} lines (threshold: {t['large_component']})",
                 "Extract sub-components or custom hooks",
                 func.name, func.size_lines)))

    def _check_inline_styles(self, func: JSFunction) -> None:
        """Flag excessive inline styles in JSX components."""
        style_count = len(re.findall(r'style\s*=\s*\{\{', func.code))
        if style_count >= 3:
            self.smells.append(_make_web_smell(
                (func.file_path, func.line_start, func.line_end),
                ("inline-styles", Severity.INFO,
                 f"Component '{func.name}' has {style_count} inline style objects",
                 "Use CSS modules, styled-components, or a utility CSS framework",
                 func.name, style_count)))

    def _check_any_abuse(self, analysis: JSFileAnalysis) -> None:
        """Flag excessive use of 'any' type in TypeScript files."""
        try:
            code_blocks = [f.code for f in analysis.functions]
            full_code = "\n".join(code_blocks)
            any_count = len(re.findall(r':\s*any\b', full_code))
            any_count += len(re.findall(r'as\s+any\b', full_code))
            if any_count >= 5:
                self.smells.append(_make_web_smell(
                    (analysis.file_path, 1, 1),
                    ("any-type-abuse", Severity.WARNING,
                     f"{any_count} uses of 'any' type — defeats TypeScript benefits",
                     "Replace 'any' with proper types, generics, or 'unknown'",
                     analysis.file_path, any_count)))
        except Exception:
            pass

    # ── Helpers ──────────────────────────────────────────────────────────
    # _add removed — use module-level _make_web_smell() instead

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of all web smells."""
        by_severity = Counter(s.severity for s in self.smells)
        by_category = Counter(s.category for s in self.smells)
        by_file = Counter(s.file_path for s in self.smells)

        # Import categories across all files
        all_imports = []
        for a in self._analyses:
            all_imports.extend(a.imports)
        import_cats = categorize_imports(all_imports)

        total_console = sum(len(a.console_logs) for a in self._analyses)
        total_funcs = sum(len(a.functions) for a in self._analyses)
        total_files = len(self._analyses)
        react_components = sum(
            1 for a in self._analyses
            for f in a.functions if f.is_react_component
        )

        return {
            "total": len(self.smells),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "by_category": dict(by_category),
            "worst_files": dict(by_file.most_common(10)),
            "files_scanned": total_files,
            "total_functions": total_funcs,
            "react_components": react_components,
            "console_logs_total": total_console,
            "package_categories": {k: len(v) for k, v in import_cats.items()},
        }


# ── File collection ─────────────────────────────────────────────────────

def _should_prune_web_dir(dirname: str, rel_dir: str,
                          exclude: Optional[List[str]]) -> bool:
    """Return True if *dirname* should be skipped during web file walk."""
    if dirname in _ALWAYS_SKIP or dirname.endswith(".egg-info"):
        return True
    # Also skip common JS build/output dirs
    if dirname in ("dist", "build", ".next", ".nuxt", "coverage",
                    ".cache", ".parcel-cache", "out", ".turbo"):
        return True
    if exclude:
        qualified = os.path.join(rel_dir, dirname) if rel_dir != "." else dirname
        return any(qualified.startswith(p) for p in exclude)
    return False


def _collect_web_files(root: Path,
                       exclude: Optional[List[str]] = None) -> List[Path]:
    """Walk root and return JS/TS/JSX/TSX files."""
    exclude = exclude or []
    results: List[Path] = []
    try:
        walker = os.walk(root)
    except PermissionError:
        return results

    for dirpath, dirnames, filenames in walker:
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [d for d in dirnames
                       if not _should_prune_web_dir(d, rel_dir, exclude)]
        for fn in filenames:
            if Path(fn).suffix.lower() in WEB_EXTENSIONS:
                results.append(Path(dirpath) / fn)
    return results
