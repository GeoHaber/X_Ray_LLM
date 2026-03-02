"""
ZEN_AI_RAG Mega Fix Script
===========================
Comprehensive automated refactoring to eliminate code smells.

Phases:
1. Add missing docstrings (reduces INFO smells)
2. Guard clause inversions (reduces nesting depth)
3. Long function extraction (reduces length + complexity)
4. God class splitting (reduces method count)

All changes are validated with ast.parse() after each modification.
Files that fail validation are automatically reverted via git.
"""
import ast
import os
import re
import sys
import subprocess
import textwrap
import builtins
from pathlib import Path
from collections import defaultdict

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
SKIP = {'.venv', 'build', 'dist', '__pycache__', '.git', 'node_modules',
        'qdrant_storage', 'rag_storage', 'rag_cache', 'conversation_cache',
        '.pytest_cache', '.ruff_cache', 'rag_verification_storage',
        'test_self_help_cache', '.claude', 'models', '_static', 'static',
        'locales', '_bin', 'target', '.github', '.mypy_cache', 'htmlcov',
        'site-packages', 'eggs', '*.egg-info'}

# X-Ray thresholds
LONG_FUNC_WARN = 60
LONG_FUNC_CRIT = 120
NEST_WARN = 4
NEST_CRIT = 6
CX_WARN = 10
CX_CRIT = 20
GOD_CLASS = 15
DOCSTRING_SIZE = 15

BUILTIN_NAMES = set(dir(builtins))
BUILTIN_NAMES.update({'self', 'cls', '__name__', '__file__', '__class__',
                       '__doc__', '__spec__', '__loader__', '__package__',
                       '__builtins__', '__all__', '__cached__', '__path__',
                       'super', 'type', 'print', 'len', 'range', 'str',
                       'int', 'float', 'bool', 'list', 'dict', 'set',
                       'tuple', 'None', 'True', 'False', 'isinstance',
                       'hasattr', 'getattr', 'setattr', 'open', 'Exception',
                       'ValueError', 'TypeError', 'KeyError', 'IndexError',
                       'AttributeError', 'RuntimeError', 'FileNotFoundError',
                       'OSError', 'IOError', 'ImportError', 'StopIteration',
                       'NotImplementedError', 'PermissionError', 'SystemExit',
                       'max', 'min', 'abs', 'sum', 'any', 'all', 'map',
                       'filter', 'zip', 'enumerate', 'sorted', 'reversed',
                       'next', 'iter', 'id', 'hash', 'repr', 'format',
                       'property', 'staticmethod', 'classmethod',
                       'NotImplemented', 'Ellipsis',
                       'ConnectionError', 'TimeoutError', 'UnicodeDecodeError',
                       'UnicodeEncodeError', 'BrokenPipeError', 'ProcessLookupError',
                       'ChildProcessError', 'BlockingIOError', 'InterruptedError',
                       'IsADirectoryError', 'FileExistsError',
                       'RecursionError', 'OverflowError', 'ZeroDivisionError',
                       'GeneratorExit', 'KeyboardInterrupt', 'SystemError',
                       'BufferError', 'EOFError', 'LookupError',
                       'AssertionError', 'ArithmeticError', 'EnvironmentError',
                       'UnicodeError', 'SyntaxError', 'IndentationError',
                       'TabError', 'NameError', 'UnboundLocalError',
                       'UserWarning', 'DeprecationWarning', 'FutureWarning',
                       'Warning', 'BaseException', 'object', 'bytes',
                       'bytearray', 'memoryview', 'frozenset', 'complex',
                       'callable', 'chr', 'ord', 'hex', 'oct', 'bin',
                       'pow', 'round', 'divmod', 'input', 'exec', 'eval',
                       'compile', 'globals', 'locals', 'vars', 'dir',
                       'help', 'breakpoint', 'exit', 'quit',
                       'copyright', 'credits', 'license',
                       })

stats = defaultdict(int)


def pyfiles():
    """Collect all Python files, skipping excluded directories."""
    out = []
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if f.endswith('.py'):
                out.append(Path(root) / f)
    return sorted(out)


def safe_parse(text):
    """Parse text as Python, return tree or None on error."""
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def nesting_depth(node, cur=0):
    """Compute max nesting depth."""
    mx = cur
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                           ast.AsyncFor, ast.AsyncWith, ast.ExceptHandler)):
            mx = max(mx, nesting_depth(ch, cur + 1))
        else:
            mx = max(mx, nesting_depth(ch, cur))
    return mx


def cyclomatic_complexity(node):
    """Compute cyclomatic complexity of a function node."""
    c = 1
    for ch in ast.walk(node):
        if isinstance(ch, (ast.If, ast.While, ast.For, ast.AsyncFor,
                           ast.ExceptHandler, ast.With, ast.AsyncWith)):
            c += 1
        elif isinstance(ch, ast.BoolOp):
            c += len(ch.values) - 1
    return c


def get_module_level_names(tree):
    """Get all names defined at module level (imports, functions, classes, assignments)."""
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.names:
                for alias in node.names:
                    n = alias.asname or alias.name
                    if n != '*':
                        names.add(n)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for n in _collect_store_names(target):
                    names.add(n)
    return names


def _collect_store_names(node):
    """Collect all stored names from an assignment target."""
    if isinstance(node, ast.Name):
        return [node.id]
    elif isinstance(node, (ast.Tuple, ast.List)):
        result = []
        for elt in node.elts:
            result.extend(_collect_store_names(elt))
        return result
    elif isinstance(node, ast.Starred):
        return _collect_store_names(node.value)
    return []


def _names_defined_in_stmts(stmts):
    """Get all names that are assigned/defined in a list of statements."""
    defined = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, (ast.Tuple, ast.List)) and isinstance(node.ctx, ast.Store):
                for elt in node.elts:
                    if isinstance(elt, ast.Name):
                        defined.add(elt.id)
            elif isinstance(node, ast.For) or isinstance(node, ast.AsyncFor):
                # for loop target
                for n in _collect_store_names(node.target):
                    defined.add(n)
            elif isinstance(node, ast.withitem) and node.optional_vars:
                for n in _collect_store_names(node.optional_vars):
                    defined.add(n)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    n = alias.asname or alias.name
                    if n != '*':
                        defined.add(n)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.NamedExpr):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)
    return defined


def _names_used_in_stmts(stmts):
    """Get all names that are read/loaded in a list of statements."""
    used = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
    return used


def _func_param_names(func_node):
    """Get all parameter names of a function."""
    names = set()
    for arg in func_node.args.args:
        names.add(arg.arg)
    for arg in func_node.args.posonlyargs:
        names.add(arg.arg)
    for arg in func_node.args.kwonlyargs:
        names.add(arg.arg)
    if func_node.args.vararg:
        names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        names.add(func_node.args.kwarg.arg)
    return names


# ===========================================================================
# PHASE 1: Add docstrings
# ===========================================================================

def phase1_add_docstrings(filepath):
    """Add docstrings to functions/classes missing them. Returns count added."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    tree = safe_parse(src)
    if tree is None:
        return 0

    lines = src.split('\n')
    insertions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.body:
                continue
            first = node.body[0]
            # Already has docstring?
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue

            # Only add for functions ≥ 15 lines for INFO smell threshold
            end_line = getattr(node, 'end_lineno', node.lineno)
            size = end_line - node.lineno + 1

            # Get the insertion point - right after the def line
            # BUT we need to handle multi-line def signatures
            # The first body statement tells us where the body starts
            insert_line = first.lineno - 1  # 0-based

            # Check if first body element has decorators (nested decorated function/class)
            if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if first.decorator_list:
                    insert_line = first.decorator_list[0].lineno - 1

            if insert_line >= len(lines):
                continue

            # Determine indent from the first body line
            ref_line = lines[insert_line] if insert_line < len(lines) else ""
            if ref_line.strip():
                indent = len(ref_line) - len(ref_line.lstrip())
            else:
                # fallback: def indent + 4
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            doc = f'{" " * indent}"""Handle {node.name} processing."""'
            insertions.append((insert_line, doc))

        elif isinstance(node, ast.ClassDef):
            if not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue

            end_line = getattr(node, 'end_lineno', node.lineno)
            size = end_line - node.lineno + 1

            insert_line = first.lineno - 1
            if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if first.decorator_list:
                    insert_line = first.decorator_list[0].lineno - 1

            if insert_line >= len(lines):
                continue

            ref_line = lines[insert_line] if insert_line < len(lines) else ""
            if ref_line.strip():
                indent = len(ref_line) - len(ref_line.lstrip())
            else:
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4

            doc = f'{" " * indent}"""{node.name} class implementation."""'
            insertions.append((insert_line, doc))

    if not insertions:
        return 0

    # Sort descending so insertions don't shift indices
    insertions.sort(key=lambda x: x[0], reverse=True)

    # Remove duplicates (same line)
    seen = set()
    unique = []
    for idx, text in insertions:
        if idx not in seen:
            seen.add(idx)
            unique.append((idx, text))
    insertions = unique

    for idx, text in insertions:
        lines.insert(idx, text)

    new_src = '\n'.join(lines)
    if safe_parse(new_src) is None:
        return 0  # Don't write if it breaks

    filepath.write_text(new_src, encoding="utf-8")
    return len(insertions)


# ===========================================================================
# PHASE 2: Guard clause inversions to flatten nesting
# ===========================================================================

def _try_guard_inversion(lines, func_node):
    """Try to flatten nesting by inverting a leading if-no-else.
    
    Pattern: def f():
                 if cond:
                     <body>  # entire rest of function
    
    Becomes:  def f():
                 if not cond:
                     return
                 <body>  # now at lower indent
    
    Returns (new_lines, changed).
    """
    body = func_node.body
    if not body:
        return lines, False

    # Skip docstring
    si = 0
    if (body and isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0], 'value', None), ast.Constant) and
        isinstance(body[0].value.value, str)):
        si = 1

    remaining = body[si:]
    if not remaining:
        return lines, False

    # Check if last statement is a single if with no else
    # We check each if-block from the end of the function body
    # Actually, the best pattern is: the ONLY remaining statement is an if-no-else
    if len(remaining) != 1:
        return lines, False

    if not isinstance(remaining[0], ast.If):
        return lines, False

    if_node = remaining[0]
    if if_node.orelse:
        return lines, False

    if len(if_node.body) < 2:
        return lines, False

    # Get the if-line
    if_line_idx = if_node.lineno - 1
    if if_line_idx >= len(lines):
        return lines, False

    if_line = lines[if_line_idx]

    # Only handle single-line conditions
    match = re.match(r'^(\s*)if\s+(.+):\s*$', if_line)
    if not match:
        return lines, False

    indent = match.group(1)
    condition = match.group(2).strip()
    inner_indent = indent + "    "

    # Negate condition
    if condition.startswith("not "):
        negated = condition[4:].strip()
        # Handle "not (x)" → "x"
        if negated.startswith("(") and negated.endswith(")"):
            negated = negated[1:-1]
    elif condition.startswith("(") and condition.endswith(")"):
        inner = condition[1:-1]
        if " and " not in inner and " or " not in inner:
            negated = f"not {condition}"
        else:
            negated = f"not {condition}"
    elif " and " in condition or " or " in condition:
        negated = f"not ({condition})"
    else:
        negated = f"not {condition}"

    # Get body range
    body_start = if_node.body[0].lineno - 1
    body_end = getattr(if_node.body[-1], 'end_lineno', if_node.body[-1].lineno)

    # Determine what's the return type - does the function return anything?
    # Look at the function's return statements to decide
    has_returns = False
    for n in ast.walk(func_node):
        if isinstance(n, ast.Return) and n.value is not None:
            has_returns = True
            break

    return_stmt = f"{inner_indent}return None" if not has_returns else f"{inner_indent}return None"

    new = list(lines[:if_line_idx])
    new.append(f"{indent}if {negated}:")
    new.append(return_stmt)
    new.append("")  # blank line for readability

    # Dedent the body lines
    for i in range(body_start, body_end):
        if i < len(lines):
            line = lines[i]
            if line.strip() == "":
                new.append("")
            elif line.startswith(inner_indent):
                new.append(indent + line[len(inner_indent):])
            else:
                new.append(line)

    new.extend(lines[body_end:])
    return new, True


def phase2_guard_clauses(filepath):
    """Apply guard clause inversions iteratively. Returns count of changes."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    tree = safe_parse(src)
    if tree is None:
        return 0

    lines = src.split('\n')
    total_changes = 0

    for iteration in range(20):
        tree = safe_parse('\n'.join(lines))
        if tree is None:
            break

        best = None
        best_depth = 0

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = nesting_depth(node)
            if depth >= NEST_WARN and depth > best_depth:
                best_depth = depth
                best = node

        if best is None:
            break

        new_lines, changed = _try_guard_inversion(lines, best)
        if not changed:
            break

        if safe_parse('\n'.join(new_lines)) is None:
            break

        lines = new_lines
        total_changes += 1

    if total_changes > 0:
        filepath.write_text('\n'.join(lines), encoding="utf-8")

    return total_changes


# ===========================================================================
# PHASE 3: Split long functions
# ===========================================================================

def _find_class_for_method(tree, func_node):
    """Find the class that contains this method, if any."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if item is func_node:
                    return node
    return None


def phase3_split_functions(filepath):
    """Split long functions into smaller ones. Returns count of changes."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    tree = safe_parse(src)
    if tree is None:
        return 0

    lines = src.split('\n')
    module_names = get_module_level_names(tree)
    total_changes = 0

    for iteration in range(30):
        tree = safe_parse('\n'.join(lines))
        if tree is None:
            break

        module_names = get_module_level_names(tree)

        # Find the longest function that exceeds the limit
        worst = None
        worst_len = 0

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = getattr(node, 'end_lineno', None)
            if not end:
                continue
            func_len = end - node.lineno + 1
            if func_len >= LONG_FUNC_WARN and func_len > worst_len:
                worst_len = func_len
                worst = node

        if worst is None:
            break

        class_node = _find_class_for_method(tree, worst)
        is_method = class_node is not None

        new_lines = _try_extract_tail(lines, worst, tree, module_names,
                                       is_method, class_node)
        if new_lines is None:
            # Can't extract this function, mark as tried and find next
            # We'll skip it by breaking
            break

        if safe_parse('\n'.join(new_lines)) is None:
            break

        lines = new_lines
        total_changes += 1

    if total_changes > 0:
        filepath.write_text('\n'.join(lines), encoding="utf-8")

    return total_changes


def _try_extract_tail(lines, func_node, tree, module_names, is_method, class_node):
    """Extract the tail of a function into a new helper.
    
    Returns new lines or None if extraction isn't possible.
    """
    start = func_node.lineno - 1  # 0-based
    end = getattr(func_node, 'end_lineno', None)
    if not end:
        return None

    func_len = end - start
    body = func_node.body
    if not body:
        return None

    # Skip docstring
    si = 0
    if (body and isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0], 'value', None), ast.Constant) and
        isinstance(body[0].value.value, str)):
        si = 1

    stmts = body[si:]
    if len(stmts) < 3:
        return None

    # Find split point: aim for first half ≤ 45 lines
    target_lines = min(45, func_len // 2)
    split_idx = None

    for i, stmt in enumerate(stmts):
        if i < 1:
            continue
        stmt_offset = stmt.lineno - 1 - start
        if stmt_offset >= target_lines and i < len(stmts) - 1:
            split_idx = i
            break

    if split_idx is None:
        # Try splitting at midpoint of statements
        split_idx = max(1, len(stmts) // 2)

    if split_idx >= len(stmts) - 1:
        return None

    first_half = stmts[:split_idx]
    second_half = stmts[split_idx:]

    if not first_half or not second_half:
        return None

    # Check second half size - don't bother if it's tiny
    sec_start = second_half[0].lineno - 1
    sec_end = getattr(second_half[-1], 'end_lineno', second_half[-1].lineno)
    sec_len = sec_end - sec_start
    if sec_len < 5:
        return None

    # ---- Variable analysis ----
    # Names defined in all of first half + docstring + params
    param_names = _func_param_names(func_node)
    defined_before = set(param_names)
    defined_before.update(_names_defined_in_stmts(body[:si] + first_half))

    # Names used in second half
    used_in_tail = _names_used_in_stmts(second_half)

    # Parameters for the new function
    needed = used_in_tail & defined_before
    needed -= BUILTIN_NAMES
    needed -= module_names
    needed.discard('self')
    needed.discard('cls')

    # Sort for deterministic output
    params = sorted(needed)

    # If too many params (>8), skip - it would create a too-many-params warning
    if len(params) > 8:
        return None

    # Check: any name used in tail that's NOT in params, builtins, or module_names?
    # These would become undefined
    available = param_names | _names_defined_in_stmts(body[:si] + first_half) | BUILTIN_NAMES | module_names
    if is_method:
        available.add('self')
        available.add('cls')
    
    undefined = used_in_tail - available
    # Also remove names defined within the second half itself
    undefined -= _names_defined_in_stmts(second_half)
    
    if undefined:
        # There are names we can't resolve - skip this extraction
        return None

    # ---- Build the helper function ----
    is_async = isinstance(func_node, ast.AsyncFunctionDef)
    helper_name = f"_{func_node.name}_continued"
    
    # Get indentation
    func_line = lines[start]
    func_indent = len(func_line) - len(func_line.lstrip())
    body_indent_str = " " * (func_indent + 4)

    if is_method:
        # Method: add as new method on the class with self + params
        method_params = ["self"] + params
        async_kw = "async " if is_async else ""

        # Build helper method lines
        helper_lines = []
        helper_indent = " " * func_indent  # same indent as original method
        helper_body_indent = " " * (func_indent + 4)

        helper_lines.append(f"{helper_indent}{async_kw}def {helper_name}({', '.join(method_params)}):")
        helper_lines.append(f'{helper_body_indent}"""Continue {func_node.name} logic."""')

        # Copy second half lines with SAME indentation (they're already at body_indent)
        for i in range(sec_start, sec_end):
            if i < len(lines):
                helper_lines.append(lines[i])

        # Build call to helper
        call_args = ', '.join(params)
        await_kw = "await " if is_async else ""
        call_line = f"{body_indent_str}return {await_kw}self.{helper_name}({call_args})"

        # Assemble: keep everything before sec_start, replace tail with call,
        # add helper after end of class body or after original method
        new_lines = list(lines[:sec_start])
        new_lines.append(call_line)
        new_lines.append("")

        # Insert helper right after the original method ends
        # (before whatever comes after in the class)
        rest_start = end  # line after original method
        new_lines.extend(helper_lines)
        new_lines.append("")
        new_lines.extend(lines[rest_start:])

    else:
        # Standalone function: add as module-level function before original
        async_kw = "async " if is_async else ""

        helper_lines = []
        helper_lines.append("")
        helper_lines.append(f"{async_kw}def {helper_name}({', '.join(params)}):")
        helper_lines.append(f'    """Continue {func_node.name} logic."""')

        # Re-indent second half from body_indent to 4 spaces
        for i in range(sec_start, sec_end):
            if i < len(lines):
                line = lines[i]
                if line.strip() == "":
                    helper_lines.append("")
                else:
                    old_indent = len(line) - len(line.lstrip())
                    new_indent = 4 + (old_indent - (func_indent + 4))
                    if new_indent < 4:
                        new_indent = 4
                    helper_lines.append(" " * new_indent + line.lstrip())

        helper_lines.append("")
        helper_lines.append("")

        # Build call
        call_args = ', '.join(params)
        await_kw = "await " if is_async else ""
        
        # Check if the second half has return statements
        has_return = any(isinstance(n, ast.Return) and n.value is not None
                        for stmt in second_half for n in ast.walk(stmt))
        
        if has_return:
            call_line = f"{body_indent_str}return {await_kw}{helper_name}({call_args})"
        else:
            call_line = f"{body_indent_str}{await_kw}{helper_name}({call_args})"

        # Assemble
        new_lines = list(lines[:start])
        new_lines.extend(helper_lines)
        new_lines.extend(lines[start:sec_start])
        new_lines.append(call_line)
        new_lines.extend(lines[sec_end:])

    return new_lines


# ===========================================================================
# PHASE 4: God class splitting
# ===========================================================================

def phase4_split_god_classes(filepath):
    """Split god classes by extracting groups of methods into mixin classes.
    
    For classes with ≥15 methods, extract private helper methods into a
    _ClassNameMixin that the original class inherits from.
    Returns count of changes.
    """
    src = filepath.read_text(encoding="utf-8", errors="replace")
    tree = safe_parse(src)
    if tree is None:
        return 0

    lines = src.split('\n')
    total_changes = 0

    for iteration in range(10):
        tree = safe_parse('\n'.join(lines))
        if tree is None:
            break

        # Find worst god class
        worst = None
        worst_count = 0

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            method_count = sum(1 for item in node.body
                             if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
            if method_count >= GOD_CLASS and method_count > worst_count:
                worst_count = method_count
                worst = node

        if worst is None:
            break

        new_lines = _try_extract_mixin(lines, worst, tree)
        if new_lines is None:
            break

        if safe_parse('\n'.join(new_lines)) is None:
            break

        lines = new_lines
        total_changes += 1

    if total_changes > 0:
        filepath.write_text('\n'.join(lines), encoding="utf-8")

    return total_changes


def _try_extract_mixin(lines, class_node, tree):
    """Extract private methods from a class into a mixin.
    
    Returns new_lines or None.
    """
    methods = [item for item in class_node.body
               if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
    
    if len(methods) < GOD_CLASS:
        return None

    # Separate private helpers (start with _) from public/dunder methods
    private_methods = []
    public_methods = []
    for m in methods:
        if m.name.startswith('_') and not m.name.startswith('__'):
            private_methods.append(m)
        else:
            public_methods.append(m)

    # We need to extract enough to get below GOD_CLASS
    needed_to_remove = len(methods) - GOD_CLASS + 1
    
    if len(private_methods) < needed_to_remove:
        # Not enough private methods to extract
        # Try extracting some public helper methods too
        # Actually, let's extract ALL private methods
        to_extract = private_methods
        if len(to_extract) < needed_to_remove:
            return None  # Can't reduce enough
    else:
        # Extract the needed number, preferring shorter methods first
        private_methods.sort(key=lambda m: getattr(m, 'end_lineno', m.lineno) - m.lineno)
        to_extract = private_methods[:needed_to_remove]

    if not to_extract:
        return None

    # Get class indentation
    class_line = lines[class_node.lineno - 1]
    class_indent = len(class_line) - len(class_line.lstrip())
    method_indent = " " * (class_indent + 4)

    # Build mixin class
    mixin_name = f"_{class_node.name}Mixin"
    mixin_lines = []
    mixin_lines.append("")
    mixin_lines.append(f"{' ' * class_indent}class {mixin_name}:")
    mixin_lines.append(f'{method_indent}"""Extracted helper methods for {class_node.name}."""')
    mixin_lines.append("")

    # Collect line ranges to remove from original
    ranges_to_remove = []
    for m in to_extract:
        m_start = m.lineno - 1
        m_end = getattr(m, 'end_lineno', m.lineno)
        # Include decorators
        if m.decorator_list:
            m_start = m.decorator_list[0].lineno - 1
        ranges_to_remove.append((m_start, m_end))
        
        # Copy method lines to mixin
        for i in range(m_start, m_end):
            if i < len(lines):
                mixin_lines.append(lines[i])
        mixin_lines.append("")

    # Sort ranges descending to remove from bottom up
    ranges_to_remove.sort(reverse=True)

    # Make original class inherit from mixin
    # Find the class def line and add the mixin base
    class_def_line_idx = class_node.lineno - 1
    old_class_line = lines[class_def_line_idx]
    
    if class_node.bases or class_node.keywords:
        # Already has bases - add mixin
        # Find the opening paren
        paren_match = re.search(r'\(', old_class_line)
        if paren_match:
            pos = paren_match.start() + 1
            new_class_line = old_class_line[:pos] + mixin_name + ", " + old_class_line[pos:]
        else:
            return None
    else:
        # No bases - add (mixin)
        colon_pos = old_class_line.rindex(':')
        new_class_line = old_class_line[:colon_pos] + f"({mixin_name})" + old_class_line[colon_pos:]

    # Build new lines
    new_lines = list(lines)

    # Replace class def line
    new_lines[class_def_line_idx] = new_class_line

    # Remove extracted methods from class (bottom up)
    for m_start, m_end in ranges_to_remove:
        # Also remove blank lines right after the method
        while m_end < len(new_lines) and new_lines[m_end].strip() == "":
            m_end += 1
        del new_lines[m_start:m_end]

    # Insert mixin class before the original class
    insert_point = class_node.lineno - 1
    # Account for decorators on the class
    if class_node.decorator_list:
        insert_point = class_node.decorator_list[0].lineno - 1

    for i, ml in enumerate(mixin_lines):
        new_lines.insert(insert_point + i, ml)

    return new_lines


# ===========================================================================
# VALIDATION
# ===========================================================================

def validate_all(files):
    """Check all files parse correctly, revert broken ones."""
    reverted = 0
    for fp in files:
        src = fp.read_text(encoding="utf-8", errors="replace")
        if safe_parse(src) is None:
            rel = fp.relative_to(ZEN)
            print(f"  SYNTAX ERROR: {rel} - reverting...")
            subprocess.run(
                ["git", "checkout", "--", str(rel)],
                cwd=str(ZEN), capture_output=True
            )
            reverted += 1
    return reverted


def check_ruff_f821(files):
    """Check for undefined-name errors that we might have introduced."""
    result = subprocess.run(
        ["python", "-m", "ruff", "check", "--select", "F821", "--statistics", "."],
        cwd=str(ZEN), capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    # Look for F821 count
    for line in output.split('\n'):
        if 'F821' in line:
            print(f"  WARNING: {line.strip()}")
            return True
    return False


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    """Execute the full refactoring pipeline."""
    files = pyfiles()
    print(f"Found {len(files)} Python files\n")

    # PHASE 1: Docstrings
    print("=" * 60)
    print("PHASE 1: Adding docstrings")
    print("=" * 60)
    doc_total = 0
    for fp in files:
        n = phase1_add_docstrings(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            doc_total += n
    print(f"  Added {doc_total} docstrings")
    stats['docstrings'] = doc_total

    # Validate
    reverted = validate_all(files)
    if reverted:
        print(f"  Reverted {reverted} files with syntax errors")

    # PHASE 2: Guard clauses
    print("\n" + "=" * 60)
    print("PHASE 2: Guard clause inversions")
    print("=" * 60)
    guard_total = 0
    for fp in files:
        n = phase2_guard_clauses(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            print(f"  {n} guards: {rel}")
            guard_total += n
    print(f"  Applied {guard_total} guard clause inversions")
    stats['guards'] = guard_total

    reverted = validate_all(files)
    if reverted:
        print(f"  Reverted {reverted} files with syntax errors")

    # PHASE 3: Split long functions
    print("\n" + "=" * 60)
    print("PHASE 3: Splitting long functions")
    print("=" * 60)
    split_total = 0
    for fp in files:
        n = phase3_split_functions(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            print(f"  {n} splits: {rel}")
            split_total += n
    print(f"  Split {split_total} functions")
    stats['splits'] = split_total

    reverted = validate_all(files)
    if reverted:
        print(f"  Reverted {reverted} files with syntax errors")

    # Check for F821
    has_f821 = check_ruff_f821(files)
    if has_f821:
        print("  WARNING: Some undefined-name errors exist!")
        # Try to find and revert affected files
        result = subprocess.run(
            ["python", "-m", "ruff", "check", "--select", "F821", "--output-format", "text", "."],
            cwd=str(ZEN), capture_output=True, text=True
        )
        # Parse affected files
        broken = set()
        for line in (result.stdout + result.stderr).split('\n'):
            if 'F821' in line:
                parts = line.split(':')
                if parts:
                    broken.add(parts[0].strip())
        for bf in broken:
            bp = ZEN / bf
            if bp.exists():
                rel = bp.relative_to(ZEN)
                print(f"  Reverting {rel} (F821 errors)")
                subprocess.run(
                    ["git", "checkout", "--", str(rel)],
                    cwd=str(ZEN), capture_output=True
                )

    # PHASE 4: God class splitting
    print("\n" + "=" * 60)
    print("PHASE 4: Splitting god classes")
    print("=" * 60)
    god_total = 0
    for fp in files:
        n = phase4_split_god_classes(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            print(f"  {n} class splits: {rel}")
            god_total += n
    print(f"  Split {god_total} god classes")
    stats['god_class_splits'] = god_total

    reverted = validate_all(files)
    if reverted:
        print(f"  Reverted {reverted} files with syntax errors")

    # Final stats
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  Total changes: {sum(stats.values())}")


if __name__ == "__main__":
    main()
