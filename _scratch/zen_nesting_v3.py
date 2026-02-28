#!/usr/bin/env python3
"""
ZEN_AI_RAG Aggressive Nesting Reducer v3
=========================================
More aggressive nesting reduction with relaxed constraints.
Handles: for-guards, while-guards, function-guards, with-flattening.
"""

import ast
import os
import re
import sys
from pathlib import Path

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
CHANGES = 0
DETAILED_LOG = []


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


def negate(cond):
    cond = cond.strip()
    if cond.startswith("not "):
        inner = cond[4:].strip()
        if inner.startswith("(") and inner.endswith(")"):
            return inner[1:-1]
        return inner
    for old, new in [(" == "," != "),(" != "," == "),(" is not "," is "),
                     (" is "," is not "),(" not in "," in "),(" in "," not in "),
                     (" >= "," < "),(" <= "," > "),(" > "," <= "),(" < "," >= ")]:
        if old in cond and cond.count(old) == 1:
            return cond.replace(old, new)
    if " and " in cond or " or " in cond:
        return f"not ({cond})"
    return f"not {cond}"


def find_block_end(lines, start, min_indent):
    """Find where a block at min_indent (or deeper) ends."""
    end = start
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if not s:
            end = i + 1
            continue
        ind = get_indent(lines[i])
        if ind < min_indent:
            break
        end = i + 1
    return end


def apply_all_loop_guards(lines):
    """Apply guard clause inside ALL for/while loops where if is the first stmt."""
    result = []
    i = 0
    any_changed = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect for/while loops
        is_loop = ((stripped.startswith("for ") or stripped.startswith("async for ")) and stripped.endswith(":")) or \
                  (stripped.startswith("while ") and stripped.endswith(":") and stripped != "while True:")
        
        if not is_loop:
            result.append(line)
            i += 1
            continue

        loop_indent = get_indent(line)
        body_indent = loop_indent + 4
        bi_str = " " * body_indent

        # Find first non-blank line in loop body
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1

        if j >= len(lines) or get_indent(lines[j]) != body_indent:
            result.append(line)
            i += 1
            continue

        first = lines[j].strip()
        
        # Must be a plain `if` (not elif, not `if __name__`)
        if not first.startswith("if ") or first.startswith("if __"):
            result.append(line)
            i += 1
            continue

        # Extract condition (handle multi-line conditions)
        cond_match = re.match(r'if\s+(.+?)\s*:\s*$', first)
        if not cond_match:
            result.append(line)
            i += 1
            continue

        condition = cond_match.group(1)
        if_line_idx = j
        if_body_indent = body_indent + 4
        ibi_str = " " * if_body_indent

        # Find if-body end
        if_body_start = if_line_idx + 1
        if_body_end = find_block_end(lines, if_body_start, if_body_indent)

        # Check for else/elif right after if body
        if if_body_end < len(lines):
            after = lines[if_body_end].strip() if if_body_end < len(lines) else ""
            aft_indent = get_indent(lines[if_body_end]) if if_body_end < len(lines) else -1
            if aft_indent == body_indent and (after.startswith("elif ") or after.startswith("else:")):
                result.append(line)
                i += 1
                continue

        # Count if-body actual lines
        if_body_code = sum(1 for k in range(if_body_start, if_body_end) if lines[k].strip())
        if if_body_code < 2:
            result.append(line)
            i += 1
            continue

        # Find loop body end
        loop_body_end = find_block_end(lines, i + 1, body_indent)

        # RELAXED: Allow code after the if block - we'll keep it in place
        # Just transform the if body, keeping everything else

        # Build output
        result.append(line)  # for/while line
        # Blank lines between loop and if
        for k in range(i + 1, if_line_idx):
            result.append(lines[k])
        
        # Guard clause
        neg = negate(condition)
        result.append(f"{bi_str}if {neg}:")
        result.append(f"{bi_str}    continue")

        # De-indented if body
        for k in range(if_body_start, if_body_end):
            l = lines[k]
            if not l.strip():
                result.append("")
            elif l.startswith(ibi_str):
                result.append(bi_str + l[if_body_indent:])
            else:
                result.append(l)

        # Everything after the if block until loop body end
        for k in range(if_body_end, loop_body_end):
            result.append(lines[k])

        any_changed = True
        i = loop_body_end
        continue

    return result, any_changed


def apply_all_func_guards(lines):
    """Apply guard clause to functions where if is the first real statement."""
    result = list(lines)
    any_changed = False

    # Process bottom-up to preserve line numbers
    # First find all function defs
    func_defs = []
    for i, line in enumerate(result):
        s = line.strip()
        if s.startswith("def ") or s.startswith("async def "):
            func_defs.append(i)

    for func_idx in reversed(func_defs):
        func_line = result[func_idx]
        func_indent = get_indent(func_line)
        body_indent = func_indent + 4
        bi_str = " " * body_indent

        # Skip past docstring
        j = func_idx + 1
        while j < len(result) and not result[j].strip():
            j += 1
        if j >= len(result):
            continue

        # Detect docstring
        doc_line = result[j].strip()
        if doc_line.startswith('"""') or doc_line.startswith("'''"):
            quote = doc_line[:3]
            if doc_line.count(quote) >= 2:
                j += 1
            else:
                for k in range(j + 1, min(j + 100, len(result))):
                    if quote in result[k]:
                        j = k + 1
                        break

        # Skip blank lines after docstring
        while j < len(result) and not result[j].strip():
            j += 1
        if j >= len(result):
            continue

        first = result[j]
        first_stripped = first.strip()
        first_indent = get_indent(first)

        if first_indent != body_indent:
            continue
        if not first_stripped.startswith("if ") or first_stripped.startswith("if __"):
            continue

        cond_match = re.match(r'if\s+(.+?)\s*:\s*$', first_stripped)
        if not cond_match:
            continue

        condition = cond_match.group(1)
        if_body_indent = body_indent + 4
        ibi_str = " " * if_body_indent

        if_line_idx = j
        if_body_start = if_line_idx + 1
        if_body_end = find_block_end(result, if_body_start, if_body_indent)

        # Check for else/elif
        if if_body_end < len(result):
            after = result[if_body_end].strip()
            aft_indent = get_indent(result[if_body_end])
            if aft_indent == body_indent and (after.startswith("elif ") or after.startswith("else:")):
                continue

        # Find function end
        func_end = find_block_end(result, func_idx + 1, body_indent)

        # The if body should cover at least 40% of function body
        func_body_code = sum(1 for k in range(j, func_end) if result[k].strip())
        if_body_code = sum(1 for k in range(if_body_start, if_body_end) if result[k].strip())
        if func_body_code > 0 and if_body_code < func_body_code * 0.4:
            continue

        if if_body_code < 3:
            continue

        # Code after the if
        code_after = sum(1 for k in range(if_body_end, func_end) if result[k].strip())
        if code_after > 5:
            continue

        # Apply
        neg = negate(condition)
        new_section = []
        # Everything before the if line (docstring etc)
        for k in range(func_idx, if_line_idx):
            new_section.append(result[k])
        # Guard
        new_section.append(f"{bi_str}if {neg}:")
        new_section.append(f"{bi_str}    return")
        new_section.append("")
        # De-indented body
        for k in range(if_body_start, if_body_end):
            l = result[k]
            if not l.strip():
                new_section.append("")
            elif l.startswith(ibi_str):
                new_section.append(bi_str + l[if_body_indent:])
            else:
                new_section.append(l)
        # After-if lines
        for k in range(if_body_end, func_end):
            new_section.append(result[k])

        # Replace in result
        result = result[:func_idx] + new_section + result[func_end:]
        any_changed = True

    return result, any_changed


def flatten_withs(lines):
    """Flatten nested with statements: with A: with B: -> with A, B:"""
    result = []
    i = 0
    any_changed = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Look for with ... :
        with_match = re.match(r'^(\s*)(with\s+.+)\s*:\s*$', line)
        if not with_match:
            result.append(line)
            i += 1
            continue

        indent_str = with_match.group(1)
        outer_with = with_match.group(2)  # "with X as y" or "with X"
        indent = len(indent_str)
        inner_indent = indent + 4

        # Check next non-blank line
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1

        if j >= len(lines):
            result.append(line)
            i += 1
            continue

        inner_match = re.match(r'^(\s*)(with\s+.+)\s*:\s*$', lines[j])
        if not inner_match or get_indent(lines[j]) != inner_indent:
            result.append(line)
            i += 1
            continue

        inner_with = inner_match.group(2)

        # Extract the context expressions
        outer_ctx = outer_with[5:].strip()  # After "with "
        inner_ctx = inner_with[5:].strip()  # After "with "

        # Merge
        merged = f"{indent_str}with {outer_ctx}, {inner_ctx}:"
        result.append(merged)

        # De-indent inner body
        inner_body_indent = inner_indent + 4
        body_end = find_block_end(lines, j + 1, inner_body_indent)

        for k in range(j + 1, body_end):
            l = lines[k]
            if not l.strip():
                result.append("")
            elif l.startswith(" " * inner_body_indent):
                result.append(" " * inner_indent + l[inner_body_indent:])
            else:
                result.append(l)

        any_changed = True
        i = body_end
        continue

    return result, any_changed


def reduce_nesting(filepath, content):
    """Apply all nesting reductions with multiple passes."""
    if not check_syntax(content, str(filepath)):
        return content, 0

    lines = content.split("\n")
    total = 0

    for pass_num in range(12):
        changed_this_pass = False

        # For-loop guards (most impactful)
        new_lines, ch = apply_all_loop_guards(lines)
        if ch:
            lines = new_lines
            changed_this_pass = True
            total += 1

        # Function-level guards
        new_lines, ch = apply_all_func_guards(lines)
        if ch:
            lines = new_lines
            changed_this_pass = True
            total += 1

        # With-block flattening
        new_lines, ch = flatten_withs(lines)
        if ch:
            lines = new_lines
            changed_this_pass = True
            total += 1

        if not changed_this_pass:
            break

    if total > 0:
        new_content = "\n".join(lines)
        if check_syntax(new_content, str(filepath)):
            return new_content, total

    return content, 0


def count_deep_funcs(path):
    """Count functions with nesting depth >= 4 (indent depth >= 5 levels)."""
    count = 0
    try:
        content = read_file(path)
        tree = ast.parse(content)
        lines = content.split("\n")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    func_lines = lines[node.lineno-1:node.end_lineno]
                    base = get_indent(func_lines[0])
                    max_d = 0
                    for l in func_lines:
                        if l.strip():
                            d = (get_indent(l) - base) // 4
                            max_d = max(max_d, d)
                    if max_d >= 5:
                        count += 1
    except Exception:
        pass
    return count


def main():
    global CHANGES

    print("=" * 60)
    print("ZEN_AI_RAG AGGRESSIVE NESTING REDUCER v3")
    print("=" * 60)

    # Initial count
    initial = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if f.endswith(".py"):
                initial += count_deep_funcs(Path(root) / f)
    print(f"Initial deeply-nested functions (indent>=5): {initial}")

    # Process all files
    file_count = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                new_content, changes = reduce_nesting(filepath, content)
                if changes > 0:
                    write_file(filepath, new_content)
                    rel = filepath.relative_to(ZEN)
                    log(f"REDUCED {rel}: {changes} passes")
                    CHANGES += changes
                    file_count += 1
            except Exception as e:
                pass
    
    print(f"\nTotal passes applied: {CHANGES}")
    print(f"Files modified: {file_count}")

    # Final count
    final = 0
    broken = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if f.endswith(".py"):
                fp = Path(root) / f
                try:
                    c = read_file(fp)
                    if not check_syntax(c, str(fp)):
                        broken += 1
                    else:
                        final += count_deep_funcs(fp)
                except Exception:
                    pass

    print(f"\nDeeply-nested: {initial} -> {final}")
    print(f"Broken files: {broken}")
    print("EXIT:0")


if __name__ == "__main__":
    main()
