"""Auto-generated smell regression tests by X-Ray v7.0.

These tests verify that known code smells are acknowledged.
If a smell disappears (fixed), the test should be updated.
"""

import ast
from pathlib import Path


def _count_lines(filepath, func_name):
    """Count lines of a function by name using AST."""
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node.end_lineno - node.lineno + 1
    return 0



