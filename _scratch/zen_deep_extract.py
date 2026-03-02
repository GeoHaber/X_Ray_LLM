#!/usr/bin/env python3
"""
ZEN_AI_RAG Deep Block Extractor
================================
For each function with nesting >= 6, finds the DEEPEST code block
and extracts it into a helper function to reduce nesting depth.
"""

import ast
import os
import re
import sys
from pathlib import Path

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
CHANGES = 0


def log(msg):
    print(f"  {msg}", flush=True)


def read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def check_syntax(code, fn="<string>"):
    try:
        compile(code, fn, "exec")
        return True
    except SyntaxError:
        return False


def get_indent(line):
    if not line.strip():
        return -1
    return len(line) - len(line.lstrip())


def find_deepest_block(func_lines, base_indent, min_block_size=5):
    """
    Find the deepest block of code in a function.
    Returns (block_start, block_end, block_indent) or None.
    The block_start/block_end are relative to func_lines.
    """
    # Find the deepest indentation level that has enough code
    # Count consecutive lines at each indent level
    indent_runs = {}  # indent -> list of (start, end)

    i = 0
    while i < len(func_lines):
        line = func_lines[i]
        if not line.strip():
            i += 1
            continue
        ind = get_indent(line)
        if ind <= base_indent:
            i += 1
            continue

        # Start of a run at this indent level
        run_start = i
        run_end = i + 1
        for j in range(i + 1, len(func_lines)):
            l = func_lines[j]
            if not l.strip():
                run_end = j + 1
                continue
            jind = get_indent(l)
            if jind >= ind:
                run_end = j + 1
            else:
                break

        # Count actual code lines in this run
        code_lines = sum(1 for k in range(run_start, run_end) if func_lines[k].strip())
        if code_lines >= min_block_size:
            if ind not in indent_runs:
                indent_runs[ind] = []
            indent_runs[ind].append((run_start, run_end, code_lines))

        i = run_end

    if not indent_runs:
        return None

    # Find the deepest indent level with a good block
    max_indent = max(indent_runs.keys())

    # We want to extract at a level that will actually reduce nesting
    # Target: extract at indent level base+20 or deeper (nesting 5+)
    target_indent = base_indent + 20  # 5 levels deep

    best = None
    for ind in sorted(indent_runs.keys(), reverse=True):
        if ind < target_indent:
            break
        for start, end, code in indent_runs[ind]:
            if code >= min_block_size:
                if best is None or code > best[2]:
                    best = (start, end, code, ind)

    if best is None:
        # Try deeper blocks even if they're smaller
        for ind in sorted(indent_runs.keys(), reverse=True):
            if ind >= base_indent + 16:  # At least 4 levels deep
                for start, end, code in indent_runs[ind]:
                    if code >= 3:
                        if best is None or ind > best[3] or (ind == best[3] and code > best[2]):
                            best = (start, end, code, ind)
                if best:
                    break

    if best is None:
        return None

    return best[0], best[1], best[3]


def extract_deep_block(content, filepath, func_name, func_start, func_end, helper_suffix):
    """Extract the deepest block from a function into a helper."""
    lines = content.split("\n")
    func_lines = lines[func_start - 1:func_end]

    if not func_lines:
        return content, False

    base_indent = get_indent(func_lines[0])
    result = find_deepest_block(func_lines, base_indent, min_block_size=4)

    if result is None:
        return content, False

    block_start, block_end, block_indent = result
    block_lines = func_lines[block_start:block_end]

    if len(block_lines) < 4:
        return content, False

    # Find the parent line (the line before the block that establishes the indent)
    # This is typically a for/if/with/try statement
    parent_idx = None
    for i in range(block_start - 1, -1, -1):
        l = func_lines[i]
        if l.strip() and get_indent(l) == block_indent - 4:
            parent_idx = i
            break

    # Determine helper indent (extract to one level above where it's called)
    # The helper will be at the same indent level as the function
    helper_indent = base_indent
    hi_str = " " * helper_indent

    # Analyze variables
    block_text = "\n".join(block_lines)
    min_block_indent = min(
        (get_indent(l) for l in block_lines if l.strip()),
        default=block_indent
    )

    # Dedent block to create helper body
    helper_body_lines = []
    for l in block_lines:
        if not l.strip():
            helper_body_lines.append("")
        else:
            ind = get_indent(l)
            new_indent = ind - min_block_indent + 4
            helper_body_lines.append(" " * new_indent + l.lstrip())

    # Find used variable names in the block
    try:
        dedented_block = "\n".join(
            l[min_block_indent:] if l.strip() else "" for l in block_lines
        )
        block_tree = ast.parse(dedented_block)
        used = set()
        assigned = set()
        for node in ast.walk(block_tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used.add(node.id)
                elif isinstance(node.ctx, ast.Store):
                    assigned.add(node.id)
    except SyntaxError:
        return content, False

    # Find function parameters
    try:
        func_text = "\n".join(func_lines)
        func_dedented = "\n".join(
            l[base_indent:] if l.strip() else "" for l in func_lines
        )
        func_tree = ast.parse(func_dedented)
        func_params = set()
        is_method = False
        for node in ast.walk(func_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    func_params.add(arg.arg)
                    if arg.arg == "self":
                        is_method = True
                break
    except Exception:
        func_params = set()
        is_method = False

    # Find variables assigned before the block
    before_lines = func_lines[1:block_start]
    try:
        before_dedented = "\n".join(
            l[base_indent:] if l.strip() else "" for l in before_lines
        )
        before_tree = ast.parse(before_dedented)
        before_assigned = set()
        for node in ast.walk(before_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                before_assigned.add(node.id)
    except Exception:
        before_assigned = set()

    # Helper params: self + params and pre-assigned vars that the block uses
    helper_params = []
    if is_method:
        helper_params.append("self")
    for name in sorted((func_params | before_assigned) & used):
        if name not in ("self", "cls") and name not in helper_params:
            helper_params.append(name)

    if len(helper_params) > 7:
        # Too many params - not a good extraction
        return content, False

    # Find variables the block assigns that are used after
    after_lines = func_lines[block_end:]
    after_text = "\n".join(after_lines)
    try:
        after_dedented = "\n".join(
            l[base_indent:] if l.strip() else "" for l in after_lines
        )
        after_tree = ast.parse(after_dedented)
        after_used = set()
        for node in ast.walk(after_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                after_used.add(node.id)
    except Exception:
        after_used = set()

    returned = sorted(assigned & after_used)
    if len(returned) > 4:
        return content, False

    # Build helper name
    clean = func_name.lstrip("_")
    helper_name = f"_{clean}_inner{helper_suffix}"
    attempts = 0
    while helper_name in content and attempts < 10:
        helper_suffix += 1
        helper_name = f"_{clean}_inner{helper_suffix}"
        attempts += 1

    # Build helper function
    params_str = ", ".join(helper_params)
    helper_lines_out = []
    helper_lines_out.append(f"{hi_str}def {helper_name}({params_str}):")
    helper_lines_out.append(f"{hi_str}    \"\"\"{clean.replace('_', ' ').capitalize()} inner logic.\"\"\"\n")
    helper_lines_out.extend(f"{hi_str}{l}" if l.strip() else "" for l in helper_body_lines)
    if returned:
        if len(returned) == 1:
            helper_lines_out.append(f"{hi_str}    return {returned[0]}")
        else:
            helper_lines_out.append(f"{hi_str}    return {', '.join(returned)}")
    helper_lines_out.append("")
    helper_lines_out.append("")

    # Build call
    call_indent = " " * block_indent
    call_args = ", ".join(helper_params)
    if returned:
        if len(returned) == 1:
            call = f"{call_indent}{returned[0]} = {helper_name}({call_args})"
        else:
            call = f"{call_indent}{', '.join(returned)} = {helper_name}({call_args})"
    else:
        call = f"{call_indent}{helper_name}({call_args})"

    # Build new function with the block replaced by a call
    new_func_lines = func_lines[:block_start]
    new_func_lines.append(call)
    new_func_lines.extend(func_lines[block_end:])

    # Assemble final content
    new_lines = lines[:func_start - 1]
    new_lines.extend(helper_lines_out)
    new_lines.extend(new_func_lines)
    new_lines.extend(lines[func_end:])

    new_content = "\n".join(new_lines)
    return new_content, True


def process_file(filepath):
    """Extract deep blocks from all deeply-nested functions."""
    content = read_file(filepath)
    if not check_syntax(content, str(filepath)):
        return 0

    original = content
    total = 0

    for attempt in range(20):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            break

        lines = content.split("\n")

        # Find the function with the deepest nesting
        worst = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.end_lineno:
                    continue
                func_lines = lines[node.lineno - 1:node.end_lineno]
                base = get_indent(func_lines[0])
                max_depth = 0
                for l in func_lines:
                    if l.strip():
                        d = (get_indent(l) - base) // 4
                        max_depth = max(max_depth, d)
                if max_depth >= 6:  # Critical nesting (indent depth 6 = ~nesting 5-6)
                    if worst is None or max_depth > worst[4]:
                        worst = (node.lineno, node.end_lineno, node.name, len(func_lines), max_depth)

        if worst is None:
            break

        start, end, name, n_lines, depth = worst
        new_content, changed = extract_deep_block(content, filepath, name, start, end, total + 1)

        if changed and check_syntax(new_content, str(filepath)):
            content = new_content
            total += 1
        else:
            break

    if total > 0:
        write_file(filepath, content)
    elif content != original:
        write_file(filepath, original)  # Revert

    return total


def main():
    global CHANGES

    print("=" * 60)
    print("ZEN_AI_RAG DEEP BLOCK EXTRACTOR")
    print("=" * 60)

    # Initial count
    initial_deep = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            try:
                content = read_file(Path(root) / f)
                tree = ast.parse(content)
                lines = content.split("\n")
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.end_lineno:
                            continue
                        func_lines = lines[node.lineno - 1:node.end_lineno]
                        base = get_indent(func_lines[0])
                        max_d = max((get_indent(l) - base) // 4 for l in func_lines if l.strip())
                        if max_d >= 6:
                            initial_deep += 1
            except Exception:
                pass

    print(f"Functions with indent-depth >= 6: {initial_deep}")

    # Process
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                n = process_file(filepath)
                if n > 0:
                    rel = filepath.relative_to(ZEN)
                    log(f"EXTRACT {rel}: {n} deep blocks")
                    CHANGES += n
            except Exception as e:
                pass

    print(f"\nTotal deep block extractions: {CHANGES}")

    # Final count
    final_deep = 0
    broken = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            try:
                content = read_file(Path(root) / f)
                if not check_syntax(content, str(Path(root) / f)):
                    broken += 1
                    continue
                tree = ast.parse(content)
                lines = content.split("\n")
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.end_lineno:
                            continue
                        func_lines = lines[node.lineno - 1:node.end_lineno]
                        base = get_indent(func_lines[0])
                        max_d = max((get_indent(l) - base) // 4 for l in func_lines if l.strip())
                        if max_d >= 6:
                            final_deep += 1
            except Exception:
                pass

    print(f"Deep functions: {initial_deep} -> {final_deep}")
    print(f"Broken files: {broken}")
    print("EXIT:0")


if __name__ == "__main__":
    main()
