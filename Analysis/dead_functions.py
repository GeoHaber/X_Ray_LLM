"""Analysis/dead_functions.py — Cross-file dead function detector.

Detects public functions that are defined in the project but never called
from anywhere in the scanned codebase. Uses a simple static call-graph:
  - Defined names: {f.name for f in functions}
  - Called names:  all ast.Name/ast.Attribute ids found inside ast.Call nodes

LIMITATIONS:
  - False positives for framework callbacks (Flet event handlers, pytest fixtures,
    __dunder__ methods) and dynamically dispatched methods (obj.method()).
  - Only detects calls by name; alias-renamed calls are missed.
  - Public API entry points and test helpers are exempt.
"""

from __future__ import annotations

import ast
from typing import List, Set

from Core.types import FunctionRecord, Severity, SmellIssue

_EXEMPT_NAMES: Set[str] = {
    "main",
    "run",
    "app",
    "create_app",
    "setup",
    "teardown",
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setUpModule",
    "tearDownModule",
    "pytest_configure",
    "pytest_collect_file",
    "conftest",
}

# Flet / UI framework entry-point patterns (starts-with)
_FRAMEWORK_PREFIXES = ("on_", "build", "did_mount", "will_unmount")

_MIN_LINES = 10  # ignore tiny functions (often callbacks/lambdas)


class DeadFunctionDetector:
    """Detect public functions that appear to be never called in the project."""

    def detect(self, functions: List[FunctionRecord]) -> List[SmellIssue]:
        """Return SmellIssues for functions that are defined but never called."""
        if not functions:
            return []

        # Build set of all defined function names (public, non-trivial)
        candidates = [
            f
            for f in functions
            if not f.name.startswith("_")
            and not f.name.startswith("test_")
            and f.name not in _EXEMPT_NAMES
            and not any(f.name.startswith(p) for p in _FRAMEWORK_PREFIXES)
            and f.size_lines >= _MIN_LINES
        ]

        if not candidates:
            return []

        # Build set of all called names from every function's code
        called: Set[str] = set()
        for func in functions:
            try:
                tree = ast.parse(func.code)
            except Exception:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # Direct call: func_name(...)
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                # Method call: obj.method(...)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

        smells = []
        for func in sorted(candidates, key=lambda f: (f.file_path, f.line_start)):
            if func.name not in called:
                smells.append(
                    SmellIssue(
                        file_path=func.file_path,
                        line=func.line_start,
                        end_line=func.line_end,
                        category="dead-function",
                        severity=Severity.INFO,
                        name=func.name,
                        metric_value=func.size_lines,
                        message=(
                            f"Function '{func.name}' ({func.size_lines} lines) "
                            f"appears to be never called in the scanned codebase"
                        ),
                        suggestion=(
                            "Remove the function if it is unused, or add a comment "
                            "explaining its purpose (e.g. 'called dynamically', "
                            "'framework callback', 'exported API'). "
                            "Note: false positives are possible for dynamic dispatch."
                        ),
                        source="xray-dead",
                    )
                )
        return smells


# Module-level API for test compatibility
_default_analyzer = DeadFunctionDetector()


def detect(*args, **kwargs):
    """Wrapper for DeadFunctionDetector.detect()."""
    return _default_analyzer.detect(*args, **kwargs)
