"""Auto-generated smell regression tests by X-Ray v7.0.

These tests verify that known code smells are acknowledged.
If a smell disappears (fixed), the test should be updated.
"""

import ast
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parent.parent.parent


def _count_lines(filepath, func_name):
    """Count lines of a function by name using AST."""
    source = (ROOT / filepath).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node.end_lineno - node.lineno + 1
    return 0

def test_smell_regression_generate_checklist_long_function():
    """Regression: generate_checklist in Analysis/release_checklist.py is 187 lines (limit ~60)."""
    size = _count_lines(str(ROOT / "Analysis/release_checklist.py"), "generate_checklist")
    # Originally 187 lines — track if it grows or gets refactored
    assert size > 0, "Function generate_checklist should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"generate_checklist is {size} lines — refactor needed"

def test_smell_regression__build_release_readiness_tab_long_function():
    """Regression: _build_release_readiness_tab in UI/tabs/release_readiness_tab.py is 325 lines (limit ~60)."""
    size = _count_lines(str(ROOT / "UI/tabs/release_readiness_tab.py"), "_build_release_readiness_tab")
    # Originally 325 lines — track if it grows or gets refactored
    assert size > 0, "Function _build_release_readiness_tab should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"_build_release_readiness_tab is {size} lines — refactor needed"
