"""
Analysis/ui_compat.py — UI API Compatibility Analyzer for X-Ray
================================================================

AST-scans Python source files for UI framework constructor/method calls
(Flet, tkinter, PyQt, etc.) and validates keyword arguments against the
live installed API signatures.  Catches renamed, removed, or misspelled
kwargs *before* runtime — exactly the class of bug that causes
``TypeError: __init__() got an unexpected keyword argument '...'``.

Usage::

    from Analysis.ui_compat import UICompatAnalyzer

    analyzer = UICompatAnalyzer()
    issues = analyzer.analyze(Path("my_app.py"))          # single file
    issues = analyzer.analyze_tree(Path("src/"))           # whole tree
    analyzer.print_report(issues)

Integrates with the X-Ray scan pipeline: returns ``SmellIssue`` objects
with ``source="ui-compat"`` so they appear alongside lint/smell results.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Optional,
    Set,
    Tuple,
)

from Core.types import SmellIssue, Severity
from Core.utils import logger
from Core.ui_bridge import get_bridge


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class UICallSite:
    """A single UI constructor / method call found in source code."""

    file_path: str
    line: int
    end_line: int
    module_alias: str  # e.g. "ft"
    full_qual: str  # e.g. "ft.TabBar"
    resolved_name: str  # e.g. "flet.TabBar"
    kwargs_used: List[str]  # keyword arg names passed
    positional_count: int  # number of positional args
    is_method: bool  # True if ft.Class.method() pattern
    source_snippet: str = ""  # the call as written


@dataclass
class UICompatIssue:
    """One incompatibility finding (wraps into SmellIssue for reporting)."""

    call: UICallSite
    bad_kwarg: str  # the offending keyword name
    accepted: FrozenSet[str]  # what the constructor actually accepts
    has_var_keyword: bool  # True if ctor has **kwargs
    suggestion: str = ""

    def to_smell(self) -> SmellIssue:
        """Convert to X-Ray SmellIssue for unified reporting."""
        return SmellIssue(
            file_path=self.call.file_path,
            line=self.call.line,
            end_line=self.call.end_line,
            category="ui-compat",
            severity=Severity.CRITICAL,
            name=self.call.resolved_name,
            metric_value=0,
            message=(
                f"'{self.bad_kwarg}' is not a valid keyword argument for "
                f"{self.call.resolved_name}()"
            ),
            suggestion=self.suggestion or self._auto_suggest(),
            source="ui-compat",
            rule_code="UC001",
            fixable=False,
        )

    def _auto_suggest(self) -> str:
        """Best-effort suggestion via edit-distance matching."""
        if not self.accepted:
            return "Check the API docs for valid parameters."
        # Simple Levenshtein-ish closest match
        best, best_dist = "", 999
        for candidate in sorted(self.accepted):
            if candidate.startswith("_"):
                continue
            d = _edit_distance(self.bad_kwarg, candidate)
            if d < best_dist:
                best, best_dist = candidate, d
        if best_dist <= 3:
            return f"Did you mean '{best}'?  Valid params: {_top_params(self.accepted)}"
        return f"Valid params: {_top_params(self.accepted)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _edit_distance(a: str, b: str) -> int:
    """Minimal Levenshtein distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(
                min(
                    prev[j + 1] + 1,
                    curr[j] + 1,
                    prev[j] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    return prev[-1]


def _top_params(params: FrozenSet[str], n: int = 10) -> str:
    """Return a compact string of the top-n public parameter names."""
    public = sorted(p for p in params if not p.startswith("_") and p != "self")
    shown = public[:n]
    suffix = f" … (+{len(public) - n} more)" if len(public) > n else ""
    return ", ".join(shown) + suffix


def _resolve_attr(module: Any, attr_chain: List[str]) -> Optional[Any]:
    """Walk module.A.B.C safely, returning None on failure."""
    obj = module
    for attr in attr_chain:
        obj = getattr(obj, attr, None)
        if obj is None:
            return None
    return obj


def _get_accepted_params(callable_obj: Any) -> Tuple[FrozenSet[str], bool]:
    """
    Return (set_of_param_names, has_var_keyword) for a callable.

    ``has_var_keyword`` is True when the signature contains **kwargs,
    meaning ANY keyword is accepted and we cannot flag mismatches.
    """
    try:
        sig = inspect.signature(callable_obj)
    except (ValueError, TypeError):
        return frozenset(), True  # can't inspect → assume ok

    names: Set[str] = set()
    has_var_kw = False
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_var_kw = True
        elif name != "self":
            names.add(name)
    return frozenset(names), has_var_kw


# ---------------------------------------------------------------------------
# AST visitor — extract UI calls
# ---------------------------------------------------------------------------


class _UICallVisitor(ast.NodeVisitor):
    """
    Walk an AST looking for ``alias.Widget(...)`` constructor calls.

    Handles patterns:
        ft.Text("hello", size=14)          → constructor call
        ft.Padding.symmetric(vertical=10)  → classmethod / staticmethod
        ft.Colors.with_opacity(0.1, "red") → classmethod / staticmethod
    """

    def __init__(self, aliases: Dict[str, str], file_path: str):
        """
        Parameters
        ----------
        aliases : dict
            Mapping of local alias → real module name.
            e.g. {"ft": "flet", "tk": "tkinter"}
        file_path : str
            Relative or absolute path (for reporting).
        """
        self.aliases = aliases
        self.file_path = file_path
        self.calls: List[UICallSite] = []

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _unpack_attr(node: ast.expr) -> Optional[List[str]]:
        """
        Unpack a chain of attribute accesses into a list of names.

        ``ft.TabBar``  → ["ft", "TabBar"]
        ``ft.Padding.symmetric`` → ["ft", "Padding", "symmetric"]
        """
        parts: List[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            parts.reverse()
            return parts
        return None

    # -- visitor -----------------------------------------------------------

    def visit_Call(self, node: ast.Call):  # noqa: N802
        parts = self._unpack_attr(node.func)
        if not parts or len(parts) < 2:
            self.generic_visit(node)
            return

        alias = parts[0]
        module_name = self.aliases.get(alias)
        if module_name is None:
            self.generic_visit(node)
            return

        kwargs_used = [kw.arg for kw in node.keywords if kw.arg is not None]
        full_qual = ".".join(parts)
        resolved = module_name + "." + ".".join(parts[1:])

        self.calls.append(
            UICallSite(
                file_path=self.file_path,
                line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                module_alias=alias,
                full_qual=full_qual,
                resolved_name=resolved,
                kwargs_used=kwargs_used,
                positional_count=len(node.args),
                is_method=len(parts) > 2,
                source_snippet=ast.dump(node)[:200],
            )
        )
        self.generic_visit(node)


def _extract_import_aliases(node: ast.Import, aliases: dict):
    """Extract aliases from a plain import statement."""
    for a in node.names:
        aliases[a.asname or a.name] = a.name


def _extract_from_aliases(node: ast.ImportFrom, aliases: dict):
    """Extract aliases from a from-import statement."""
    if not node.module or not node.names:
        return
    for a in node.names:
        if a.name != "*":
            aliases.setdefault(a.asname or a.name, a.asname or a.name)


def _extract_aliases(tree: ast.Module) -> Dict[str, str]:
    """
    Scan top-level imports for ``import X as Y`` and ``import X``.

    Returns mapping: local_alias → real_module_name.
    """
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _extract_import_aliases(node, aliases)
        elif isinstance(node, ast.ImportFrom):
            _extract_from_aliases(node, aliases)
    return aliases


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

_SIG_CACHE: Dict[str, Tuple[FrozenSet[str], bool]] = {}


class UICompatAnalyzer:
    """
    Scan Python files for UI framework API mismatches.

    1. AST-parse each file to find ``alias.Widget(kwarg=...)`` calls
    2. Import the module and ``inspect.signature()`` the constructor
    3. Compare used kwargs vs accepted kwargs
    4. Return mismatches as ``UICompatIssue`` / ``SmellIssue``
    """

    # Modules that are safe to import for signature inspection
    SAFE_MODULES: Set[str] = {
        "flet",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "customtkinter",
        "kivy",
        "dearpygui",
        "wx",
    }

    def __init__(self, *, extra_modules: Optional[Set[str]] = None):
        self.extra_modules = extra_modules or set()
        self._mod_cache: Dict[str, Any] = {}

    # -- public API --------------------------------------------------------

    def analyze(
        self, path: Path, exclude: Optional[List[str]] = None
    ) -> List[UICompatIssue]:
        """
        Analyze a single file or directory tree.

        Returns a list of ``UICompatIssue`` — call ``.to_smell()`` on each
        for X-Ray SmellIssue integration.
        """
        if path.is_file():
            return self._analyze_file(path)
        return self.analyze_tree(path, exclude=exclude)

    def analyze_tree(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[UICompatIssue]:
        """Recursively scan a directory for .py files."""
        exclude_set = set(
            exclude
            or [
                ".venv",
                "venv",
                "__pycache__",
                ".git",
                "node_modules",
                "target",
                "dist",
                "build",
                ".eggs",
            ]
        )
        issues: List[UICompatIssue] = []
        for py in sorted(root.rglob("*.py")):
            # Skip excluded dirs
            if any(part in exclude_set for part in py.parts):
                continue
            try:
                issues.extend(self._analyze_file(py, root=root))
            except Exception as exc:
                logger.debug(f"ui_compat: skipping {py}: {exc}")
        return issues

    def analyze_to_smells(
        self, path: Path, exclude: Optional[List[str]] = None
    ) -> List[SmellIssue]:
        """Convenience: analyze and convert straight to SmellIssue list."""
        return [issue.to_smell() for issue in self.analyze(path, exclude)]

    def summary(
        self,
        issues: Optional[List[SmellIssue]] = None,
        raw: Optional[List[UICompatIssue]] = None,
    ) -> Dict[str, Any]:
        """Build summary dict compatible with X-Ray reporting."""
        if raw is not None:
            smells = [i.to_smell() for i in raw]
        else:
            smells = issues or []
        total = len(smells)
        by_widget: Dict[str, int] = {}
        by_file: Dict[str, int] = {}
        bad_kwargs: Dict[str, int] = {}
        for s in smells:
            by_widget[s.name] = by_widget.get(s.name, 0) + 1
            by_file[s.file_path] = by_file.get(s.file_path, 0) + 1
        if raw:
            for r in raw:
                bad_kwargs[r.bad_kwarg] = bad_kwargs.get(r.bad_kwarg, 0) + 1
        return {
            "total": total,
            "critical": total,  # all UI compat issues are critical
            "warning": 0,
            "info": 0,
            "by_widget": dict(sorted(by_widget.items(), key=lambda x: -x[1])),
            "by_file": dict(sorted(by_file.items(), key=lambda x: -x[1])),
            "bad_kwargs": dict(sorted(bad_kwargs.items(), key=lambda x: -x[1])),
        }

    def print_report(self, issues: List[UICompatIssue]) -> None:
        """Pretty-print findings via the active UI bridge."""
        bridge = get_bridge()
        sep = "=" * 70
        bridge.log(f"\n{sep}")
        bridge.log("UI API COMPATIBILITY REPORT (X-Ray)")
        bridge.log(f"{sep}")
        if not issues:
            bridge.log("  \u2705 All UI constructor calls are compatible!")
            return
        bridge.log(f"  Found {len(issues)} incompatible UI call(s):\n")
        for i, issue in enumerate(issues, 1):
            c = issue.call
            bridge.log(
                f"  {i}. {c.resolved_name}() \u2014 line {c.line} in {c.file_path}"
            )
            bridge.log(f"     \u274c Bad kwarg: '{issue.bad_kwarg}'")
            if issue.suggestion:
                bridge.log(f"     \U0001f4a1 {issue.suggestion}")
            bridge.log("")
        bridge.log(sep)

    # -- internals ---------------------------------------------------------

    def _analyze_file(
        self, path: Path, root: Optional[Path] = None
    ) -> List[UICompatIssue]:
        """Parse one file, extract UI calls, validate kwargs."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return []

        aliases = _extract_aliases(tree)
        if not aliases:
            return []

        # Filter to modules we can safely import
        allowed = self.SAFE_MODULES | self.extra_modules
        ui_aliases = {
            k: v
            for k, v in aliases.items()
            if v in allowed or v.split(".")[0] in allowed
        }
        if not ui_aliases:
            return []

        rel_path = str(path.relative_to(root)) if root else str(path)

        visitor = _UICallVisitor(ui_aliases, rel_path)
        visitor.visit(tree)

        issues: List[UICompatIssue] = []
        for call in visitor.calls:
            issues.extend(self._validate_call(call))
        return issues

    def _resolve_call_target(self, call: UICallSite):
        """Resolve a call site to its callable target, or None if unresolvable."""
        module_name = call.resolved_name.split(".")[0]
        attr_chain = call.resolved_name.split(".")[1:]
        mod = self._import_module(module_name)
        if mod is None:
            return None
        return _resolve_attr(mod, attr_chain)

    def _validate_call(self, call: UICallSite) -> List[UICompatIssue]:
        """Check a single call's kwargs against the real signature."""
        if not call.kwargs_used:
            return []  # nothing to validate (positional-only or no args)

        target = self._resolve_call_target(call)
        if target is None:
            return []

        # For classes, validate __init__
        callable_obj = target.__init__ if isinstance(target, type) else target

        # Get accepted params (with caching)
        cache_key = call.resolved_name
        if cache_key not in _SIG_CACHE:
            _SIG_CACHE[cache_key] = _get_accepted_params(callable_obj)
        accepted, has_var_kw = _SIG_CACHE[cache_key]

        if has_var_kw:
            return []  # accepts **kwargs → anything goes

        return [
            UICompatIssue(
                call=call,
                bad_kwarg=kwarg,
                accepted=accepted,
                has_var_keyword=has_var_kw,
            )
            for kwarg in call.kwargs_used
            if kwarg not in accepted
        ]

    def _import_module(self, name: str) -> Optional[Any]:
        """Import a module, caching the result. Returns None on failure."""
        if name in self._mod_cache:
            return self._mod_cache[name]
        try:
            mod = importlib.import_module(name)
            self._mod_cache[name] = mod
            return mod
        except Exception as exc:
            logger.debug(f"ui_compat: cannot import '{name}': {exc}")
            self._mod_cache[name] = None
            return None


# ---------------------------------------------------------------------------
# Standalone CLI entry point
# ---------------------------------------------------------------------------


def main():
    """Quick CLI: ``python -m Analysis.ui_compat path/to/file_or_dir``."""
    import argparse

    parser = argparse.ArgumentParser(description="X-Ray UI API Compatibility Checker")
    parser.add_argument("path", help="File or directory to scan")
    parser.add_argument(
        "--extra-module",
        "-m",
        action="append",
        default=[],
        help="Additional module names to inspect (repeatable)",
    )
    args = parser.parse_args()

    analyzer = UICompatAnalyzer(extra_modules=set(args.extra_module))
    issues = analyzer.analyze(Path(args.path))
    analyzer.print_report(issues)

    if issues:
        sys.exit(1)


if __name__ == "__main__":
    main()


# Module-level API for test compatibility
_default_analyzer = UICallSite()

def analyze(source_code: str, project_root: str = None):
    """Wrapper for UICallSite.analyze()."""
    if source_code is None:
        raise ValueError("source_code cannot be None")
    return _default_analyzer.analyze(source_code)

def analyze_to_smells(source_code: str, project_root: str = None):
    """Wrapper for UICallSite.analyze_to_smells()."""
    if source_code is None:
        raise ValueError("source_code cannot be None")
    return _default_analyzer.analyze_to_smells(source_code)

def analyze_tree(source_code: str, project_root: str = None):
    """Wrapper for UICallSite.analyze_tree()."""
    if source_code is None:
        raise ValueError("source_code cannot be None")
    return _default_analyzer.analyze_tree(source_code)

def print_report(*args, **kwargs):
    """Wrapper for UICallSite.print_report()."""
    return _default_analyzer.print_report(*args, **kwargs)

def summary(issues: List):
    """Wrapper for UICallSite.summary()."""
    if issues is None:
        raise ValueError("issues cannot be None")
    return _default_analyzer.summary(issues)

def to_smell(*args, **kwargs):
    """Wrapper for UICallSite.to_smell()."""
    return _default_analyzer.to_smell(*args, **kwargs)

def visit_Call(*args, **kwargs):
    """Wrapper for UICallSite.visit_Call()."""
    return _default_analyzer.visit_Call(*args, **kwargs)

