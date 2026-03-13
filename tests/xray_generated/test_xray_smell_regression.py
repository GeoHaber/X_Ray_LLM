"""Auto-generated smell regression tests by X-Ray v7.0.

These tests verify that known code smells are acknowledged.
If a smell disappears (fixed), the test should be updated.
"""

import ast
from pathlib import Path


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


def test_smell_regression__generate_graph_html_long_function():
    """Regression: _generate_graph_html in UI/tabs/graph_tab.py is 294 lines (limit ~60)."""
    size = _count_lines(str(ROOT / "UI/tabs/graph_tab.py"), "_generate_graph_html")
    # Originally 294 lines — track if it grows or gets refactored
    assert size > 0, "Function _generate_graph_html should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"_generate_graph_html is {size} lines — refactor needed"


def test_smell_regression__build_graph_tab_long_function():
    """Regression: _build_graph_tab in UI/tabs/graph_tab.py is 150 lines (limit ~60)."""
    size = _count_lines(str(ROOT / "UI/tabs/graph_tab.py"), "_build_graph_tab")
    # Originally 150 lines — track if it grows or gets refactored
    assert size > 0, "Function _build_graph_tab should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"_build_graph_tab is {size} lines — refactor needed"
