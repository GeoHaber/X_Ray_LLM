"""
ZEN_AI_RAG Docstring-Only Fix Script
=====================================
Only adds docstrings. No function extraction. No class splitting.
Thoroughly validates syntax after changes.
"""
import ast
import os
import subprocess
from pathlib import Path

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
SKIP = {'.venv', 'build', 'dist', '__pycache__', '.git', 'node_modules',
        'qdrant_storage', 'rag_storage', 'rag_cache', 'conversation_cache',
        '.pytest_cache', '.ruff_cache', 'rag_verification_storage',
        'test_self_help_cache', '.claude', 'models', '_static', 'static',
        'locales', '_bin', 'target', '.github', '.mypy_cache', 'htmlcov',
        'site-packages'}


def pyfiles():
    """Collect all Python files."""
    out = []
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if f.endswith('.py'):
                out.append(Path(root) / f)
    return sorted(out)


def add_docstrings(filepath):
    """Add docstrings to functions/classes missing them.
    
    Very conservative: validates syntax before and after.
    Returns count added.
    """
    src = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0

    lines = src.split('\n')
    insertions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.body:
                continue
            first = node.body[0]
            # Skip if already has docstring
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue

            # Get body start line
            insert_line = first.lineno - 1

            # CRITICAL: Check if first body element is decorated
            # If so, we must insert BEFORE the decorators, not between decorator and def
            if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if first.decorator_list:
                    insert_line = first.decorator_list[0].lineno - 1

            if insert_line >= len(lines):
                continue

            # Get indentation from the reference line
            ref = lines[insert_line]
            if ref.strip():
                indent = len(ref) - len(ref.lstrip())
            else:
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            # Generate a meaningful docstring based on name
            name = node.name
            if name.startswith('test_'):
                doc = f'{" " * indent}"""Test {name[5:].replace("_", " ")}."""'
            elif name.startswith('_'):
                doc = f'{" " * indent}"""Handle {name[1:].replace("_", " ")} internally."""'
            elif name.startswith('get_'):
                doc = f'{" " * indent}"""Get {name[4:].replace("_", " ")}."""'
            elif name.startswith('set_'):
                doc = f'{" " * indent}"""Set {name[4:].replace("_", " ")}."""'
            elif name.startswith('is_') or name.startswith('has_'):
                doc = f'{" " * indent}"""Check if {name[3:].replace("_", " ")}."""'
            elif name.startswith('create_') or name.startswith('build_'):
                prefix_len = 7 if name.startswith('create_') else 6
                doc = f'{" " * indent}"""Create {name[prefix_len:].replace("_", " ")}."""'
            elif name.startswith('setup_') or name.startswith('init_'):
                prefix_len = 6 if name.startswith('setup_') else 5
                doc = f'{" " * indent}"""Initialize {name[prefix_len:].replace("_", " ")}."""'
            elif name.startswith('on_'):
                doc = f'{" " * indent}"""Handle {name[3:].replace("_", " ")} event."""'
            elif name == '__init__':
                doc = f'{" " * indent}"""Initialize the instance."""'
            else:
                doc = f'{" " * indent}"""Handle {name.replace("_", " ")} logic."""'

            insertions.append((insert_line, doc))

        elif isinstance(node, ast.ClassDef):
            if not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue

            insert_line = first.lineno - 1
            if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if first.decorator_list:
                    insert_line = first.decorator_list[0].lineno - 1

            if insert_line >= len(lines):
                continue

            ref = lines[insert_line]
            if ref.strip():
                indent = len(ref) - len(ref.lstrip())
            else:
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            doc = f'{" " * indent}"""{node.name} implementation."""'
            insertions.append((insert_line, doc))

    if not insertions:
        return 0

    # Sort descending + deduplicate
    insertions.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    unique = []
    for idx, text in insertions:
        if idx not in seen:
            seen.add(idx)
            unique.append((idx, text))

    for idx, text in unique:
        lines.insert(idx, text)

    new_src = '\n'.join(lines)
    try:
        ast.parse(new_src)
    except SyntaxError:
        return 0  # Don't write broken files

    filepath.write_text(new_src, encoding="utf-8")
    return len(unique)


def main():
    """Run docstring addition across all files."""
    files = pyfiles()
    print(f"Processing {len(files)} Python files...")

    total = 0
    errors = 0
    for fp in files:
        n = add_docstrings(fp)
        if n > 0:
            total += n
        # Double check
        src = fp.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(src)
        except SyntaxError:
            rel = fp.relative_to(ZEN)
            print(f"  SYNTAX ERROR in {rel} - reverting!")
            subprocess.run(
                ["git", "checkout", "--", str(rel)],
                cwd=str(ZEN), capture_output=True
            )
            errors += 1

    print(f"\nAdded {total} docstrings")
    if errors:
        print(f"Reverted {errors} files with syntax errors")


if __name__ == "__main__":
    main()
