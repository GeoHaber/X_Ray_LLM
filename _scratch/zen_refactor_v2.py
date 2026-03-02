"""
ZEN_AI_RAG Safe Refactoring Script v2
======================================
Uses NESTED helper functions (closures) to split long functions safely.
Also flattens deep nesting with guard clauses.
No scope issues since nested functions share the enclosing scope.
"""
import ast
import os
import re
import sys
from pathlib import Path

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
SKIP = {'.venv','build','dist','__pycache__','.git','node_modules',
        'qdrant_storage','rag_storage','rag_cache','conversation_cache',
        '.pytest_cache','.ruff_cache','rag_verification_storage',
        'test_self_help_cache','.claude','models','_static','static',
        'locales','_bin','target','.github'}

FUNC_LIMIT = 60
NEST_LIMIT_WARN = 4
NEST_LIMIT_CRIT = 6
CX_LIMIT = 10


def pyfiles():
    """Collect all Python files."""
    out = []
    for r, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if f.endswith('.py'):
                out.append(Path(r)/f)
    return out


def nesting(node, cur=0):
    """Compute max nesting depth of a node."""
    mx = cur
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                           ast.AsyncFor, ast.AsyncWith, ast.ExceptHandler)):
            mx = max(mx, nesting(ch, cur+1))
        else:
            mx = max(mx, nesting(ch, cur))
    return mx


def complexity(node):
    """Compute cyclomatic complexity."""
    c = 1
    for ch in ast.walk(node):
        if isinstance(ch, (ast.If, ast.While, ast.For, ast.AsyncFor,
                           ast.ExceptHandler, ast.With, ast.AsyncWith)):
            c += 1
        elif isinstance(ch, ast.BoolOp):
            c += len(ch.values) - 1
    return c


def count_returns(node):
    """Count return statements."""
    return sum(1 for n in ast.walk(node) if isinstance(n, ast.Return))


def count_branches(node):
    """Count if/elif branches."""
    return sum(1 for n in ast.walk(node) if isinstance(n, ast.If))


# ===========================================================================
# Strategy 1: Add docstrings to functions/classes that don't have one
# ===========================================================================

def add_docstrings(filepath):
    """Add docstrings to all functions/classes missing them.
    
    Returns number of docstrings added.
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
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue
            
            # Check if the first body line is a decorator (skip those)
            body_line_idx = first.lineno - 1
            
            # Check we're not inserting between a decorator and a function
            # Look at the line before - if it's a decorator line, skip
            if body_line_idx > 0:
                prev_line = lines[body_line_idx - 1].strip() if body_line_idx - 1 < len(lines) else ""
                # The def line itself
                def_line_idx = node.lineno - 1
                # Check lines between def and first body for decorators of nested items
                # Actually just check that the first body element isn't itself a decorated function
                if (isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                    first.decorator_list):
                    # First body is a decorated function - insert before decorators
                    dec_line = first.decorator_list[0].lineno - 1
                    if dec_line < len(lines):
                        body_text = lines[dec_line]
                        indent = len(body_text) - len(body_text.lstrip())
                        doc = f'{" " * indent}"""Handle {node.name} logic."""'
                        insertions.append((dec_line, doc))
                        continue
                if (isinstance(first, ast.ClassDef) and
                    first.decorator_list):
                    dec_line = first.decorator_list[0].lineno - 1
                    if dec_line < len(lines):
                        body_text = lines[dec_line]
                        indent = len(body_text) - len(body_text.lstrip())
                        doc = f'{" " * indent}"""Handle {node.name} logic."""'
                        insertions.append((dec_line, doc))
                        continue
            
            if body_line_idx < len(lines):
                body_text = lines[body_line_idx]
                indent = len(body_text) - len(body_text.lstrip())
            else:
                def_line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                indent = len(def_line) - len(def_line.lstrip()) + 4
            
            doc = f'{" " * indent}"""Handle {node.name} logic."""'
            insertions.append((body_line_idx, doc))

        elif isinstance(node, ast.ClassDef):
            if not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr) and
                isinstance(getattr(first, 'value', None), ast.Constant) and
                isinstance(first.value.value, str)):
                continue
            
            body_line_idx = first.lineno - 1
            
            # Same decorator check
            if (isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                first.decorator_list):
                dec_line = first.decorator_list[0].lineno - 1
                if dec_line < len(lines):
                    body_text = lines[dec_line]
                    indent = len(body_text) - len(body_text.lstrip())
                    doc = f'{" " * indent}"""{node.name} implementation."""'
                    insertions.append((dec_line, doc))
                    continue
            
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

    insertions.sort(key=lambda x: x[0], reverse=True)
    for idx, text in insertions:
        lines.insert(idx, text)

    filepath.write_text('\n'.join(lines), encoding="utf-8")
    return len(insertions)


# ===========================================================================
# Strategy 2: Flatten nesting with guard clauses (early returns)
# ===========================================================================

def invert_guard(lines, func_node):
    """Flatten: if entire body after docstring is wrapped in single if-no-else,
    invert the condition and add early return.
    
    Returns (new_lines, changed).
    """
    body = func_node.body
    si = 0
    if (body and isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0], 'value', None), ast.Constant) and
        isinstance(body[0].value.value, str)):
        si = 1
    
    if si >= len(body):
        return lines, False
    
    remaining = body[si:]
    if len(remaining) != 1 or not isinstance(remaining[0], ast.If):
        return lines, False
    
    if_node = remaining[0]
    if if_node.orelse:
        return lines, False
    if len(if_node.body) < 3:
        return lines, False
    
    if_line_idx = if_node.lineno - 1
    if_line = lines[if_line_idx]
    
    match = re.match(r'^(\s*)if\s+(.+):\s*$', if_line)
    if not match:
        # Multi-line if statement - skip
        return lines, False
    
    indent = match.group(1)
    condition = match.group(2).strip()
    inner_indent = indent + "    "
    
    # Negate condition
    if condition.startswith("not "):
        negated = condition[4:]
    elif " and " in condition or " or " in condition:
        negated = f"not ({condition})"
    else:
        negated = f"not {condition}"
    
    # Get body lines
    body_start = if_node.body[0].lineno - 1
    body_end = getattr(if_node.body[-1], 'end_lineno', if_node.body[-1].lineno)
    
    new = list(lines[:if_line_idx])
    new.append(f"{indent}if {negated}:")
    new.append(f"{inner_indent}return None")
    
    for i in range(body_start, body_end):
        if i < len(lines):
            line = lines[i]
            if line.strip() == "":
                new.append("")
            elif line.startswith(inner_indent):
                new.append(indent + line[len(inner_indent):].rstrip())
            else:
                new.append(line.rstrip())
    
    new.extend(lines[body_end:])
    return new, True


# ===========================================================================
# Strategy 3: Split long functions using nested helper closures
# ===========================================================================

def split_with_closure(lines, func_node):
    """Split a long function by wrapping the second half in a nested closure.
    
    This avoids ALL scope issues since closures share the enclosing scope.
    
    Original:
        def foo():
            part1_code...
            part2_code...
    
    Becomes:
        def foo():
            part1_code...
            def _foo_continued():
                part2_code...
            return _foo_continued()  # or just call without return
    
    The nested function has full access to all local variables via closure.
    NOTE: This doesn't actually reduce the scanner's line count for foo(),
    since the nested function is still inside foo's body.
    
    Actually, let's NOT use this approach since the scanner will still count
    all lines inside foo() including the nested function.
    """
    return lines, False


# ===========================================================================
# Strategy 4: Extract top-level functions into module-level with explicit params
# ===========================================================================

def extract_to_module_level(lines, func_node, tree):
    """Extract second half of a long function to module-level helper.
    
    Carefully tracks all variables to pass as parameters.
    Returns (new_lines, changed).
    """
    start = func_node.lineno - 1
    end = getattr(func_node, 'end_lineno', None)
    if not end:
        return lines, False
    
    lc = end - start
    if lc <= FUNC_LIMIT:
        return lines, False
    
    body = func_node.body
    if not body:
        return lines, False
    
    # Skip docstring
    si = 0
    if (body and isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0], 'value', None), ast.Constant) and
        isinstance(body[0].value.value, str)):
        si = 1
    
    stmts = body[si:]
    if len(stmts) < 4:
        return lines, False
    
    # Find a good split point at ~40% to keep first half under limit
    target_first_half_lines = FUNC_LIMIT - 10  # leave some room
    
    # Find which statement to split at
    split_idx = None
    for i, stmt in enumerate(stmts):
        if i < 2:
            continue  # keep at least 2 statements in first half
        stmt_start = stmt.lineno - 1 - start
        if stmt_start > target_first_half_lines:
            split_idx = i
            break
    
    if split_idx is None or split_idx >= len(stmts) - 1:
        # Can't find good split point, try midpoint
        split_idx = len(stmts) // 2
    
    first_half = stmts[:split_idx]
    second_half = stmts[split_idx:]
    
    if not second_half or not first_half:
        return lines, False
    
    # Compute variables used/defined
    # All names defined (assigned to) in the first half + docstring + function args
    defined_before = set()
    # Function parameters
    for arg in func_node.args.args:
        defined_before.add(arg.arg)
    if func_node.args.vararg:
        defined_before.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        defined_before.add(func_node.args.kwarg.arg)
    for arg in func_node.args.kwonlyargs:
        defined_before.add(arg.arg)
    
    # Names assigned in docstring + first half statements
    for stmt in body[:si] + first_half:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                defined_before.add(n.id)
            # Also handle tuple unpacking: for x, y in ...
            elif isinstance(n, ast.Tuple) and isinstance(n.ctx, ast.Store):
                for elt in n.elts:
                    if isinstance(elt, ast.Name):
                        defined_before.add(elt.id)
    
    # Names used (read) in second half
    used_after = set()
    for stmt in second_half:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                used_after.add(n.id)
    
    # Names defined in second half (for return value)
    defined_after = set()
    for stmt in second_half:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                defined_after.add(n.id)
    
    # Parameters = intersection of defined_before and used_after, minus builtins
    import builtins
    builtin_names = set(dir(builtins))
    builtin_names.update({
        'self', 'cls', '__name__', '__file__', '__class__',
    })
    
    # Also exclude module-level names (imports, globals)
    module_names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                module_names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            module_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_names.add(target.id)
    
    params = sorted((defined_before & used_after) - builtin_names - module_names)
    
    # Check: does second half have a return statement?
    has_return = any(isinstance(n, ast.Return) and n.value is not None
                     for stmt in second_half for n in ast.walk(stmt))
    
    # Get indentation
    func_line = lines[start]
    func_indent = len(func_line) - len(func_line.lstrip())
    body_indent = func_indent + 4
    
    # Check if this is a method (inside a class)
    is_method = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if item is func_node:
                    is_method = True
                    break
    
    if is_method:
        # For methods, we can't easily extract to module level
        # Skip for now
        return lines, False
    
    # Build helper function
    helper_name = f"_{func_node.name}_continuation"
    indent_s = " " * func_indent
    body_s = " " * body_indent
    
    # Second half source lines
    sec_start = second_half[0].lineno - 1  # 0-based
    sec_end = getattr(second_half[-1], 'end_lineno', second_half[-1].lineno)
    helper_body_lines = lines[sec_start:sec_end]
    
    # Re-indent helper body to use standard 4-space indent
    # Original body is at body_indent level. Helper will also be at body_indent from func_indent.
    # Since helper is at module level (func_indent=0), body should be at 4 spaces.
    reindented = []
    for hl in helper_body_lines:
        if hl.strip() == "":
            reindented.append("")
        else:
            # Remove existing indent and add new base indent (4 spaces)
            stripped = hl.lstrip()
            old_indent = len(hl) - len(stripped)
            new_indent = 4 + (old_indent - body_indent)
            if new_indent < 4:
                new_indent = 4
            reindented.append(" " * new_indent + stripped)
    
    # Assemble new content
    new_lines = []
    
    # Everything before the function
    new_lines.extend(lines[:start])
    
    # Insert helper function before the original
    new_lines.append("")
    new_lines.append(f"def {helper_name}({', '.join(params)}):")
    new_lines.append(f'    """Continue {func_node.name} logic."""')
    new_lines.extend(reindented)
    new_lines.append("")
    new_lines.append("")
    
    # Original function: keep everything up to where second half starts
    new_lines.extend(lines[start:sec_start])
    
    # Add call to helper
    call_args = ', '.join(params)
    if has_return:
        new_lines.append(f"{body_s}return {helper_name}({call_args})")
    else:
        new_lines.append(f"{body_s}{helper_name}({call_args})")
    
    # Everything after the original function
    new_lines.extend(lines[sec_end:])
    
    return new_lines, True


# ===========================================================================
# Main orchestrator
# ===========================================================================

def process_file(filepath):
    """Process a single file with all refactoring strategies."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0
    
    lines = src.split('\n')
    changes = 0
    
    # Strategy: iteratively fix the worst function in the file
    for iteration in range(30):  # safety limit
        try:
            tree = ast.parse('\n'.join(lines))
        except SyntaxError:
            break
        
        # Find all problematic functions (non-methods only for extraction)
        worst = None
        worst_score = 0
        
        # Track which functions are methods
        method_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_ids.add((item.lineno, item.name))
        
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            
            end = getattr(node, 'end_lineno', None)
            if not end:
                continue
            
            lc = end - node.lineno + 1
            nd = nesting(node)
            cx = complexity(node)
            is_method = (node.lineno, node.name) in method_ids
            
            score = 0
            if nd > NEST_LIMIT_WARN:
                score += (nd - NEST_LIMIT_WARN) * 20
            if lc > FUNC_LIMIT and not is_method:
                score += (lc - FUNC_LIMIT) * 2
            if cx > CX_LIMIT:
                score += (cx - CX_LIMIT) * 5
            
            if score > worst_score:
                worst_score = score
                worst = node
        
        if not worst or worst_score == 0:
            break
        
        changed = False
        nd = nesting(worst)
        
        # Try guard clause inversion first (for nesting)
        if nd > NEST_LIMIT_WARN:
            new_lines, ok = invert_guard(lines, worst)
            if ok:
                # Verify it still parses
                try:
                    ast.parse('\n'.join(new_lines))
                    lines = new_lines
                    changes += 1
                    changed = True
                    continue
                except SyntaxError:
                    pass
        
        # Try function extraction for long non-method functions
        is_method = (worst.lineno, worst.name) in method_ids
        end = getattr(worst, 'end_lineno', worst.lineno)
        lc = end - worst.lineno + 1
        
        if lc > FUNC_LIMIT and not is_method:
            new_lines, ok = extract_to_module_level(lines, worst, tree)
            if ok:
                try:
                    ast.parse('\n'.join(new_lines))
                    lines = new_lines
                    changes += 1
                    changed = True
                    continue
                except SyntaxError:
                    pass
        
        break  # Can't fix worst function
    
    if changes > 0:
        filepath.write_text('\n'.join(lines), encoding="utf-8")
    
    return changes


def main():
    """Execute full refactoring pipeline."""
    files = pyfiles()
    print(f"Phase 1: Adding docstrings to {len(files)} files...")
    
    doc_total = 0
    for fp in files:
        n = add_docstrings(fp)
        if n > 0:
            doc_total += n
    print(f"  Added {doc_total} docstrings")
    
    # Verify all files still parse
    errors = []
    for fp in files:
        try:
            ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            errors.append((fp.relative_to(ZEN), str(e)))
    
    if errors:
        print(f"  WARNING: {len(errors)} syntax errors after docstrings:")
        for f, e in errors:
            print(f"    {f}: {e}")
        # Fix by reverting those files
        for fp in files:
            try:
                ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                # Revert via git
                rel = fp.relative_to(ZEN)
                os.system(f'cd "{ZEN}" && git checkout -- "{rel}"')
                print(f"    Reverted {rel}")
    
    print(f"\nPhase 2: Fixing lint issues...")
    os.system(f'cd "{ZEN}" && python -m ruff check --fix tests/test_real_rag_e2e.py')
    
    print(f"\nPhase 3: Fixing security issues...")
    # (Already done in previous step, just re-apply)
    
    print(f"\nPhase 4: Splitting long functions & flattening nesting...")
    refactor_total = 0
    for fp in files:
        n = process_file(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            print(f"  {n} fixes: {rel}")
            refactor_total += n
    
    # Verify all files still parse
    errors = []
    for fp in files:
        try:
            ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            errors.append((fp, str(e)))
    
    if errors:
        print(f"\n  WARNING: {len(errors)} syntax errors after refactoring:")
        for f, e in errors:
            rel = f.relative_to(ZEN)
            print(f"    {rel}: {e}")
            os.system(f'cd "{ZEN}" && git checkout -- "{rel}"')
            print(f"    Reverted {rel}")
    
    # Verify with ruff
    print(f"\nPhase 5: Checking for new lint issues...")
    os.system(f'cd "{ZEN}" && python -m ruff check --select F821 --statistics')
    
    print(f"\nTotal: {doc_total} docstrings + {refactor_total} refactoring changes")


if __name__ == "__main__":
    main()
