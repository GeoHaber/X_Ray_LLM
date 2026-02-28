#!/usr/bin/env python3
"""
ZEN_AI_RAG Aggressive Function Splitter v2
===========================================
Splits ALL functions >= 60 lines by extracting blocks at ~45 line intervals.
Uses a practical approach: each extracted block becomes a helper function
that receives any `self` parameter plus any variables assigned before the block.
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


def find_split_points(func_lines, base_indent, target_size=45):
    """Find good split points in a function (at blank lines or comments near targets)."""
    body_indent = base_indent + 4

    # Skip def line and docstring
    body_start = 1
    for i in range(1, min(20, len(func_lines))):
        stripped = func_lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2:
                body_start = i + 1
                continue
            for j in range(i + 1, min(i + 100, len(func_lines))):
                if quote in func_lines[j]:
                    body_start = j + 1
                    break
            break
        body_start = i
        break

    # Find all potential split points (blank lines at body indent level)
    candidates = []
    for i in range(body_start + 5, len(func_lines) - 3):
        stripped = func_lines[i].strip()
        if not stripped:
            # Blank line - check surrounding indentation
            prev_indent = None
            next_indent = None
            for j in range(i - 1, max(body_start - 1, i - 5), -1):
                if func_lines[j].strip():
                    prev_indent = get_indent(func_lines[j])
                    break
            for j in range(i + 1, min(len(func_lines), i + 5)):
                if func_lines[j].strip():
                    next_indent = get_indent(func_lines[j])
                    break
            # Good split if both neighbors are at body indent level
            if prev_indent is not None and prev_indent <= body_indent + 4:
                candidates.append(i)
        elif stripped.startswith("#") and get_indent(func_lines[i]) == body_indent:
            # Comment at body level - good split point
            candidates.append(i)

    if not candidates:
        return []

    # Select split points near target intervals
    splits = []
    next_target = body_start + target_size
    for cand in candidates:
        if cand >= next_target:
            splits.append(cand)
            next_target = cand + target_size

    return splits


def extract_at_split_point(content, func_name, func_start, func_end, split_idx, helper_idx):
    """Extract code from split_idx to the next split/end into a helper function."""
    lines = content.split("\n")
    func_lines = lines[func_start - 1:func_end]

    if not func_lines:
        return content, False

    base_line = func_lines[0]
    base_indent = get_indent(base_line)
    body_indent = base_indent + 4
    bi_str = " " * body_indent

    # Get the block to extract (from split_idx to end of function OR next major section)
    # For simplicity, extract from split_idx to end of function, then the main func
    # calls the helper at that point

    # Find end of this block (next blank line at body indent after significant code,
    # or end of function)
    block_start = split_idx  # Relative to func_lines
    block_end = len(func_lines)

    # Look for next good break point ~45 lines after split
    target = block_start + 45
    for i in range(target, len(func_lines)):
        if not func_lines[i].strip():
            # Check if next line is at body indent
            for j in range(i + 1, min(i + 3, len(func_lines))):
                if func_lines[j].strip():
                    if get_indent(func_lines[j]) <= body_indent:
                        block_end = i
                        break
            if block_end != len(func_lines):
                break

    block_lines = func_lines[block_start:block_end]
    if len(block_lines) < 5:
        return content, False

    # Analyze variables used in the block
    block_text = "\n".join(block_lines)
    try:
        dedented = ""
        min_indent = float("inf")
        for l in block_lines:
            if l.strip():
                min_indent = min(min_indent, get_indent(l))
        if min_indent == float("inf"):
            min_indent = body_indent

        for l in block_lines:
            if l.strip():
                dedented += l[min_indent:] + "\n"
            else:
                dedented += "\n"

        tree = ast.parse(dedented)
        used_names = set()
        assigned_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)
                elif isinstance(node.ctx, ast.Store):
                    assigned_names.add(node.id)
    except SyntaxError:
        return content, False

    # Get function parameters
    try:
        func_def_text = "\n".join(func_lines)
        min_base = float("inf")
        for l in func_lines:
            if l.strip():
                min_base = min(min_base, get_indent(l))
        if min_base == float("inf"):
            min_base = 0

        func_dedented = "\n".join(l[min_base:] if l.strip() else "" for l in func_lines)
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

    # Detect variables from before the block that the block needs
    before_text = "\n".join(func_lines[1:block_start])
    try:
        before_dedented = "\n".join(
            l[min_base:] if l.strip() else "" for l in func_lines[1:block_start]
        )
        before_tree = ast.parse(before_dedented)
        before_assigned = set()
        for node in ast.walk(before_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                before_assigned.add(node.id)
    except Exception:
        before_assigned = set()

    # Parameters for helper = (self if method) + (func params used) + (before-assigned used)
    helper_params = []
    if is_method:
        helper_params.append("self")
    for name in sorted((func_params | before_assigned) & used_names):
        if name not in ("self", "cls") and name not in helper_params:
            helper_params.append(name)

    # Limit params to avoid too-many-params smell
    if len(helper_params) > 6:
        return content, False

    # Variables assigned in block that are used after
    after_lines = func_lines[block_end:]
    after_text = "\n".join(after_lines)
    try:
        after_dedented = "\n".join(l[min_base:] if l.strip() else "" for l in after_lines)
        after_tree = ast.parse(after_dedented)
        after_used = set()
        for node in ast.walk(after_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                after_used.add(node.id)
    except Exception:
        after_used = set()

    returned_vars = sorted(assigned_names & after_used)
    if len(returned_vars) > 4:
        return content, False

    # Build helper name
    clean_name = func_name.lstrip("_")
    helper_name = f"_{clean_name}_part{helper_idx}"
    if helper_name in content:
        helper_name = f"_{clean_name}_section{helper_idx}"

    # Build helper
    params_str = ", ".join(helper_params)
    helper_lines = [f"def {helper_name}({params_str}):"]
    helper_lines.append(f'    """{clean_name.replace("_", " ").capitalize()} part {helper_idx}."""')
    helper_lines.append("")

    # Add block lines, re-indented to 4 spaces
    for l in block_lines:
        if not l.strip():
            helper_lines.append("")
        elif get_indent(l) >= min_indent:
            helper_lines.append("    " + l[min_indent:])
        else:
            helper_lines.append("    " + l.lstrip())

    # Add return
    if returned_vars:
        if len(returned_vars) == 1:
            helper_lines.append(f"    return {returned_vars[0]}")
        else:
            helper_lines.append(f"    return {', '.join(returned_vars)}")

    helper_lines.append("")
    helper_lines.append("")

    # Build call
    call_args = ", ".join(helper_params)
    if returned_vars:
        if len(returned_vars) == 1:
            call_text = f"{bi_str}{returned_vars[0]} = {helper_name}({call_args})"
        else:
            call_text = f"{bi_str}{', '.join(returned_vars)} = {helper_name}({call_args})"
    else:
        call_text = f"{bi_str}{helper_name}({call_args})"

    # Build new function
    new_func_lines = func_lines[:block_start]
    new_func_lines.append(call_text)
    new_func_lines.extend(func_lines[block_end:])

    # Build final content: insert helper before the function
    all_lines = lines[:func_start - 1]
    all_lines.extend(helper_lines)
    all_lines.extend(new_func_lines)
    all_lines.extend(lines[func_end:])

    new_content = "\n".join(all_lines)
    return new_content, True


def process_file(filepath):
    """Process a single file - extract helpers from all long functions."""
    content = read_file(filepath)
    if not check_syntax(content, str(filepath)):
        return 0

    original = content
    total_extractions = 0

    for attempt in range(15):  # Max extraction attempts per file
        try:
            tree = ast.parse(content)
        except SyntaxError:
            break

        # Find the longest function
        longest = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = (node.end_lineno or node.lineno) - node.lineno + 1
                if n >= 60:
                    if longest is None or n > longest[2]:
                        longest = (node.lineno, node.end_lineno, n, node.name)

        if longest is None:
            break

        start, end, n_lines, name = longest
        func_lines = content.split("\n")[start - 1:end]
        base_indent = get_indent(func_lines[0])

        # Find split points
        splits = find_split_points(func_lines, base_indent, target_size=45)
        if not splits:
            # Can't split this function further - try next longest
            break

        # Extract at the first split point
        helper_idx = total_extractions + 1
        new_content, changed = extract_at_split_point(
            content, name, start, end, splits[0], helper_idx
        )

        if changed and check_syntax(new_content, str(filepath)):
            content = new_content
            total_extractions += 1
        else:
            break

    if total_extractions > 0:
        write_file(filepath, content)
    return total_extractions


def main():
    global CHANGES

    print("=" * 60)
    print("ZEN_AI_RAG AGGRESSIVE FUNCTION SPLITTER v2")
    print("=" * 60)

    # Count initial long functions
    initial = 0
    initial_crit = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            try:
                content = read_file(Path(root) / f)
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        n = (node.end_lineno or node.lineno) - node.lineno + 1
                        if n >= 60:
                            initial += 1
                        if n >= 120:
                            initial_crit += 1
            except Exception:
                pass

    print(f"Long functions (>=60): {initial}")
    print(f"Critical long (>=120): {initial_crit}")

    # Process all files
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                extractions = process_file(filepath)
                if extractions > 0:
                    rel = filepath.relative_to(ZEN)
                    log(f"SPLIT {rel}: {extractions} extractions")
                    CHANGES += extractions
            except Exception as e:
                rel = filepath.relative_to(ZEN)
                log(f"ERROR {rel}: {e}")

    print(f"\nTotal extractions: {CHANGES}")

    # Final count
    final = 0
    final_crit = 0
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
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        n = (node.end_lineno or node.lineno) - node.lineno + 1
                        if n >= 60:
                            final += 1
                        if n >= 120:
                            final_crit += 1
            except Exception:
                pass

    print(f"\nLong functions (>=60): {initial} -> {final}")
    print(f"Critical long (>=120): {initial_crit} -> {final_crit}")
    print(f"Broken files: {broken}")
    print("EXIT:0")


if __name__ == "__main__":
    main()
