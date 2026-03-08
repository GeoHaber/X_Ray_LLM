"""Analysis/imports.py — File-level import health analyzer.

Detects:
  - wildcard-import    : from X import *  (pollutes namespace, disables F821)
  - deep-relative-import: from ....module import x  (level >= 3)
  - missing-__all__    : modules with public names but no explicit API declaration
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from Core.types import Severity, SmellIssue
from Core.utils import logger

_MIN_PUBLIC_NAMES_FOR_ALL = 3


class ImportAnalyzer:
    """Analyze Python files for import-related code smells."""

    def analyze(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[SmellIssue]:
        """Scan all .py files under root and return import smell issues."""
        from Analysis.ast_utils import collect_py_files

        files = collect_py_files(root, exclude)
        issues: List[SmellIssue] = []
        for fpath in files:
            issues.extend(self._analyze_file(fpath, root))
        issues.sort(
            key=lambda s: (
                0
                if s.severity == Severity.CRITICAL
                else 1
                if s.severity == Severity.WARNING
                else 2,
                s.file_path,
                s.line,
            )
        )
        logger.info(f"ImportAnalyzer: {len(issues)} import issues found.")
        return issues

    def _analyze_file(self, fpath: Path, root: Path) -> List[SmellIssue]:
        try:
            source = fpath.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(fpath))
        except Exception:
            return []
        try:
            rel_path = str(fpath.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel_path = str(fpath).replace("\\", "/")
        issues: List[SmellIssue] = []
        issues.extend(_check_wildcard_import(tree, rel_path))
        issues.extend(_check_relative_import_depth(tree, rel_path))
        issues.extend(_check_missing_all(tree, rel_path))
        return issues

    def summary(self, issues: List[SmellIssue]) -> Dict[str, Any]:
        """Return a summary dict of all import issues."""
        by_severity = Counter(s.severity for s in issues)
        by_category = Counter(s.category for s in issues)
        return {
            "total": len(issues),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "by_category": dict(by_category),
            "source": "xray-imports",
        }

    def build_graph(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """Build a module-level dependency graph (source_file -> target_file)."""
        from Analysis.ast_utils import collect_py_files

        files = collect_py_files(root, exclude)
        # Map: "package.module" -> "package/module.py"
        all_internal = {}
        for f in files:
            try:
                rel = str(f.relative_to(root)).replace("\\", "/")
                mod = rel.replace(".py", "").replace("/", ".")
                # Handle cases like __init__.py which represent the package itself
                if mod.endswith(".__init__"):
                    all_internal[mod.replace(".__init__", "")] = rel
                all_internal[mod] = rel
            except ValueError:
                continue

        edges = []
        seen_edges = set()

        for fpath in files:
            try:
                source = str(fpath.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue

            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"))
                for node in ast.walk(tree):
                    targets = []
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            targets.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module or ""
                        targets.append(base)
                        for alias in node.names:
                            targets.append(
                                f"{base}.{alias.name}" if base else alias.name
                            )

                    for t_mod in targets:
                        if t_mod in all_internal:
                            target_file = all_internal[t_mod]
                            if source != target_file:
                                edge = (source, target_file)
                                if edge not in seen_edges:
                                    edges.append({"from": source, "to": target_file})
                                    seen_edges.add(edge)
            except Exception:
                continue

        return edges


def _check_wildcard_import(tree: ast.Module, rel_path: str) -> List[SmellIssue]:
    """Flag 'from X import *' — pollutes namespace and disables F821 checking."""
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name != "*":
                continue
            module = node.module or "?"
            issues.append(
                SmellIssue(
                    file_path=rel_path,
                    line=node.lineno,
                    end_line=node.lineno,
                    category="wildcard-import",
                    severity=Severity.WARNING,
                    name=module,
                    metric_value=0,
                    message=f"Wildcard import 'from {module} import *' pollutes the namespace",
                    suggestion=(
                        "List specific names: 'from module import Name1, Name2'. "
                        "Wildcard imports prevent tools from detecting undefined names."
                    ),
                    source="xray-imports",
                )
            )
    return issues


def _check_relative_import_depth(tree: ast.Module, rel_path: str) -> List[SmellIssue]:
    """Flag deeply nested relative imports (level >= 3: from ...X import y)."""
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        level = node.level or 0
        if level < 3:
            continue
        module = node.module or ""
        dots = "." * level
        severity = Severity.CRITICAL if level >= 4 else Severity.WARNING
        issues.append(
            SmellIssue(
                file_path=rel_path,
                line=node.lineno,
                end_line=node.lineno,
                category="deep-relative-import",
                severity=severity,
                name=f"{dots}{module}",
                metric_value=level,
                message=(
                    f"Deep relative import (depth={level}): "
                    f"'from {dots}{module} import ...'"
                ),
                suggestion=(
                    "Flatten package hierarchy or use absolute imports. "
                    "Relative imports deeper than 2 levels indicate structural problems."
                ),
                source="xray-imports",
            )
        )
    return issues


def _has_dunder_all(tree: ast.Module) -> bool:
    """Return True if the module already defines __all__."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                return True
    return False


def _count_public_names(tree: ast.Module) -> tuple:
    """Return (public_funcs, public_classes) counts from top-level definitions."""
    public_funcs = sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )
    public_classes = sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    )
    return public_funcs, public_classes


def _check_missing_all(tree: ast.Module, rel_path: str) -> List[SmellIssue]:
    """Flag library modules with public names but no __all__ declaration."""
    filename = rel_path.split("/")[-1]
    # Skip non-library files
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename == "__init__.py"
        or filename == "conftest.py"
    ):
        return []
    if _has_dunder_all(tree):
        return []
    public_funcs, public_classes = _count_public_names(tree)
    total_public = public_funcs + public_classes
    if total_public < _MIN_PUBLIC_NAMES_FOR_ALL:
        return []
    # Skip apparent scripts (main guard but no classes)
    has_main_guard = any(
        isinstance(node, ast.If)
        and isinstance(getattr(node.test, "left", None), ast.Name)
        and getattr(node.test, "left", None) is not None
        and node.test.left.id == "__name__"
        for node in tree.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
    )
    if has_main_guard and public_classes == 0:
        return []
    module_name = filename.replace(".py", "")
    return [
        SmellIssue(
            file_path=rel_path,
            line=1,
            end_line=1,
            category="missing-__all__",
            severity=Severity.INFO,
            name=module_name,
            metric_value=total_public,
            message=(
                f"Module '{module_name}' has {total_public} public name(s) "
                f"but no __all__ — public API is undefined"
            ),
            suggestion=(
                "Add __all__ = ['ClassName', 'func_name', ...] to declare the module's "
                "public API. This controls 'from module import *' behavior."
            ),
            source="xray-imports",
        )
    ]
