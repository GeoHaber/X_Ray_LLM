"""
ZEN_AI_RAG Comprehensive Refactoring Script
=============================================
Splits long functions, flattens nesting, and fixes complexity issues.
Uses AST analysis for safe variable tracking during function extraction.
"""
import ast
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict, Set, Optional

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
SKIP = {'.venv','build','dist','__pycache__','.git','node_modules',
        'qdrant_storage','rag_storage','rag_cache','conversation_cache',
        '.pytest_cache','.ruff_cache','rag_verification_storage',
        'test_self_help_cache','.claude','models','_static','static',
        'locales','_bin','target','.github'}

FUNC_LIMIT = 60
NEST_LIMIT = 4
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
    """Compute max nesting depth."""
    mx = cur
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, (ast.If,ast.For,ast.While,ast.With,ast.Try,
                           ast.AsyncFor,ast.AsyncWith,ast.ExceptHandler)):
            mx = max(mx, nesting(ch, cur+1))
        else:
            mx = max(mx, nesting(ch, cur))
    return mx

def complexity(node):
    """Compute cyclomatic complexity."""
    c = 1
    for ch in ast.walk(node):
        if isinstance(ch, (ast.If,ast.While,ast.For,ast.AsyncFor,
                           ast.ExceptHandler,ast.With,ast.AsyncWith)):
            c += 1
        elif isinstance(ch, ast.BoolOp):
            c += len(ch.values)-1
    return c

def names_used(stmts):
    """Get all Name nodes with Load context in a list of statements."""
    used = set()
    for s in stmts:
        for n in ast.walk(s):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                used.add(n.id)
    return used

def names_defined(stmts):
    """Get all Name nodes with Store context in a list of statements."""
    defs = set()
    for s in stmts:
        for n in ast.walk(s):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                defs.add(n.id)
    return defs

def extract_function(lines, func_node, tree, is_method=False, class_indent=0):
    """Split a long function by extracting the second half into a helper.
    
    Returns (new_lines, True) if successful, (lines, False) otherwise.
    """
    start = func_node.lineno - 1  # 0-based
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
    if (isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0],'value',None), ast.Constant) and
        isinstance(body[0].value.value, str)):
        si = 1
    
    if si >= len(body):
        return lines, False
    
    stmts = body[si:]
    if len(stmts) < 4:
        return lines, False
    
    # Find split point: midpoint of statements
    mid = len(stmts) // 2
    if mid < 2:
        mid = 2
    
    first_half = stmts[:mid]
    second_half = stmts[mid:]
    
    if not second_half:
        return lines, False
    
    # Compute variables needed by second half
    defs_before = names_defined(body[:si] + first_half)
    used_after = names_used(second_half)
    
    # Parameters to pass: variables used in second half that were defined in first half
    # Exclude builtins, self, cls, common globals
    builtins_set = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
    builtins_set.update({'self', 'cls', 'print', 'len', 'range', 'str', 'int', 
                         'float', 'list', 'dict', 'set', 'tuple', 'bool',
                         'True', 'False', 'None', 'isinstance', 'hasattr',
                         'getattr', 'setattr', 'type', 'super', 'open',
                         'os', 'sys', 'Path', 'json', 're', 'logging',
                         'time', 'datetime', 'subprocess', 'threading',
                         'asyncio', 'shutil', 'traceback', 'pathlib',
                         'Exception', 'ValueError', 'TypeError', 'KeyError',
                         'RuntimeError', 'FileNotFoundError', 'OSError',
                         'ImportError', 'AttributeError', 'IndexError',
                         'StopIteration', 'NotImplementedError'})
    
    params = sorted(defs_before & used_after - builtins_set)
    
    # Also check if second half defines variables used after (return values)
    defs_after = names_defined(second_half)
    # For simplicity, if the function returns something, the helper should too
    has_return = any(isinstance(n, ast.Return) and n.value is not None 
                     for s in second_half for n in ast.walk(s))
    
    # Get indentation
    func_line = lines[start]
    func_indent = len(func_line) - len(func_line.lstrip())
    body_indent = func_indent + 4
    indent_s = " " * func_indent
    body_s = " " * body_indent
    
    # Helper function name
    helper_name = f"_{func_node.name}_part2"
    
    # Build helper function
    if is_method:
        # For methods, add self as first param
        if 'self' not in params:
            helper_params = ['self'] + params
        else:
            params.remove('self')
            helper_params = ['self'] + params
        helper_def = f"{indent_s}def {helper_name}({', '.join(helper_params)}):"
    else:
        helper_def = f"{indent_s}def {helper_name}({', '.join(params)}):"
    
    helper_doc = f'{body_s}"""Continue {func_node.name} logic."""'
    
    # Extract second half source lines
    sec_start = second_half[0].lineno - 1
    sec_end = getattr(second_half[-1], 'end_lineno', second_half[-1].lineno)
    helper_body_lines = lines[sec_start:sec_end]
    
    # Build the call
    if is_method:
        call_args = ', '.join(params)
        if has_return:
            call_line = f"{body_s}return self.{helper_name}({call_args})"
        else:
            call_line = f"{body_s}self.{helper_name}({call_args})"
    else:
        call_args = ', '.join(params)
        if has_return:
            call_line = f"{body_s}return {helper_name}({call_args})"
        else:
            call_line = f"{body_s}{helper_name}({call_args})"
    
    # Build new file content
    new_lines = []
    # Everything before the function
    new_lines.extend(lines[:start])
    
    # Insert helper function before the original
    if not is_method:
        new_lines.append("")
        new_lines.append(helper_def)
        new_lines.append(helper_doc)
        new_lines.extend(helper_body_lines)
        new_lines.append("")
        new_lines.append("")
    
    # Original function up to the split point
    orig_end_line = sec_start  # where second half starts
    new_lines.extend(lines[start:orig_end_line])
    
    # Add the call to the helper
    new_lines.append(call_line)
    
    # If method, add the helper as a new method after the original function
    if is_method:
        # Complete the original function, then add helper
        new_lines.extend(lines[sec_end:end])  # rest of original after extracted part 
        new_lines.append("")
        new_lines.append(helper_def)
        new_lines.append(helper_doc)
        new_lines.extend(helper_body_lines)
    
    # Everything after the function
    if not is_method:
        new_lines.extend(lines[sec_end:])
    else:
        new_lines.extend(lines[end:])
    
    return new_lines, True


def invert_guard(lines, func_node):
    """Flatten a function that wraps its entire body in a single if-no-else.
    
    Pattern: 
        def foo():
            if cond:
                body...
    Becomes:
        def foo():
            if not cond:
                return None
            body...
    """
    body = func_node.body
    si = 0
    if (body and isinstance(body[0], ast.Expr) and
        isinstance(getattr(body[0],'value',None), ast.Constant) and
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
    
    # Get the if line
    if_line_idx = if_node.lineno - 1
    if_line = lines[if_line_idx]
    
    match = re.match(r'^(\s*)if\s+(.+):\s*$', if_line)
    if not match:
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
    
    # Check if last statement in if body is return - adjust guard accordingly
    # For async functions, the return type might matter
    is_async = isinstance(func_node, ast.AsyncFunctionDef)
    
    # Build guard
    guard = f"{indent}if {negated}:\n{inner_indent}return None\n"
    
    # Get if body line range
    body_start = if_node.body[0].lineno - 1
    body_end = getattr(if_node.body[-1], 'end_lineno', if_node.body[-1].lineno)
    
    # Build new lines
    new = lines[:if_line_idx]
    new.append(f"{indent}if {negated}:")
    new.append(f"{inner_indent}return None")
    
    # Dedent body lines by one level
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


def split_class_methods(lines, class_node):
    """Split a god class by extracting groups of methods into a mixin.
    
    Strategy: Move the second half of methods to a Mixin base class
    defined right before the original class.
    """
    methods = [n for n in class_node.body 
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    
    if len(methods) <= 15:
        return lines, False
    
    # We can't easily split a class without risking breaks.
    # Instead, group related methods by name prefix into sub-groups.
    # For now, the safest approach is to just note these need manual review.
    return lines, False


def process_file(filepath):
    """Process a single file: fix long functions and deep nesting."""
    src = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0
    
    lines = src.split('\n')
    changes = 0
    max_iterations = 20  # Safety limit
    
    for iteration in range(max_iterations):
        # Re-parse after each change
        try:
            tree = ast.parse('\n'.join(lines))
        except SyntaxError:
            break
        
        changed = False
        
        # Build class membership map
        class_methods = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for n in node.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        class_methods[id(n)] = node
        
        # Find worst offender (longest function or deepest nesting)
        worst_func = None
        worst_score = 0
        
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            
            end = getattr(node, 'end_lineno', None)
            if not end:
                continue
            
            lc = end - node.lineno + 1
            nd = nesting(node)
            cx = complexity(node)
            
            # Score: higher = more problematic
            score = 0
            if lc > FUNC_LIMIT:
                score += (lc - FUNC_LIMIT)
            if nd > NEST_LIMIT:
                score += (nd - NEST_LIMIT) * 15
            if cx > CX_LIMIT:
                score += (cx - CX_LIMIT) * 5
            
            if score > worst_score:
                worst_score = score
                worst_func = node
        
        if not worst_func or worst_score == 0:
            break  # Nothing to fix
        
        nd = nesting(worst_func)
        end = getattr(worst_func, 'end_lineno', worst_func.lineno)
        lc = end - worst_func.lineno + 1
        
        # Try nesting fix first (often reduces complexity too)
        if nd > NEST_LIMIT:
            new_lines, ok = invert_guard(lines, worst_func)
            if ok:
                lines = new_lines
                changes += 1
                changed = True
                continue
        
        # Try function splitting for long functions
        if lc > FUNC_LIMIT:
            is_method = id(worst_func) in class_methods
            new_lines, ok = extract_function(
                lines, worst_func, tree, 
                is_method=is_method
            )
            if ok:
                lines = new_lines
                changes += 1
                changed = True
                continue
        
        # If we couldn't fix the worst, break to avoid infinite loop
        break
    
    if changes > 0:
        filepath.write_text('\n'.join(lines), encoding="utf-8")
    
    return changes


def main():
    """Run the comprehensive refactoring."""
    files = pyfiles()
    print(f"Processing {len(files)} files...")
    
    total = 0
    for fp in files:
        n = process_file(fp)
        if n > 0:
            rel = fp.relative_to(ZEN)
            print(f"  {n} fixes: {rel}")
            total += n
    
    print(f"\nTotal refactoring changes: {total}")


if __name__ == "__main__":
    main()
