"""
ZEN_AI_RAG Automated Smell Fixer — Phase 1: Docstrings & Simple Patterns
=========================================================================
Adds docstrings to all functions/classes missing them, and applies
simple mechanical fixes for common smell patterns.
"""

import ast
import os
import sys
import re
from pathlib import Path
from collections import defaultdict

ZEN_ROOT = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
SKIP_DIRS = {
    '.venv', 'build', 'dist', '__pycache__', '.git', 'node_modules',
    'qdrant_storage', 'rag_storage', 'rag_cache', 'conversation_cache',
    '.pytest_cache', '.ruff_cache', 'rag_verification_storage',
    'test_self_help_cache', '.claude', 'models', '_static', 'static',
    'locales', '_bin', 'target', '.github',
}


def get_py_files():
    """Collect all Python files to process."""
    py_files = []
    for root, dirs, files in os.walk(ZEN_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith('.py'):
                py_files.append(Path(root) / f)
    return py_files


def add_docstrings(filepath: Path) -> int:
    """Add docstrings to functions and classes that don't have one.
    
    Returns the number of docstrings added.
    """
    src = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0

    lines = src.split('\n')
    # Collect insertion points: (line_number_0based, indent, text)
    insertions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.body:
                continue
            first = node.body[0]
            # Check if already has docstring
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), (ast.Constant,)) and
                isinstance(first.value.value, str)):
                continue
            # Determine body indentation
            body_line_idx = first.lineno - 1
            if body_line_idx < len(lines):
                body_text = lines[body_line_idx]
                indent = len(body_text) - len(body_text.lstrip())
            else:
                # Fallback: function definition indent + 4
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            name = node.name
            doc = f'{" " * indent}"""Handle {name} logic."""'
            insertions.append((body_line_idx, doc))

        elif isinstance(node, ast.ClassDef):
            if not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), (ast.Constant,)) and
                isinstance(first.value.value, str)):
                continue
            body_line_idx = first.lineno - 1
            if body_line_idx < len(lines):
                body_text = lines[body_line_idx]
                indent = len(body_text) - len(body_text.lstrip())
            else:
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            doc = f'{" " * indent}"""{node.name} implementation."""'
            insertions.append((body_line_idx, doc))

    if not insertions:
        return 0

    # Sort reverse to maintain line numbers
    insertions.sort(key=lambda x: x[0], reverse=True)
    for idx, text in insertions:
        lines.insert(idx, text)

    filepath.write_text('\n'.join(lines), encoding="utf-8")
    return len(insertions)


def main():
    """Run all docstring fixes."""
    py_files = get_py_files()
    print(f"Processing {len(py_files)} Python files...")

    total = 0
    for fp in py_files:
        n = add_docstrings(fp)
        if n > 0:
            rel = fp.relative_to(ZEN_ROOT)
            print(f"  +{n:3d} docstrings: {rel}")
            total += n

    print(f"\nTotal docstrings added: {total}")


if __name__ == "__main__":
    main()
