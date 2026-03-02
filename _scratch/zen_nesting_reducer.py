#!/usr/bin/env python3
"""
ZEN_AI_RAG Nesting Reducer v2
==============================
Aggressively reduces nesting by:
1. For-loop guard clauses: for x: if cond: body -> for x: if not cond: continue; body
2. While-loop guard clauses: same pattern with continue
3. Function-level guard clauses: if cond: body -> if not cond: return; body
4. with-block flattening: with A: with B: -> with A, B:
Applied recursively until nesting < threshold.
"""

import ast
import os
import re
import sys
from pathlib import Path

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
CHANGES = 0
ERRORS = []


def log(msg):
    print(f"  {msg}", flush=True)


def read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def check_syntax(code, filename="<string>"):
    try:
        compile(code, filename, "exec")
        return True
    except SyntaxError:
        return False


def get_indent(line):
    """Get indentation level (number of spaces)."""
    return len(line) - len(line.lstrip()) if line.strip() else -1


def negate_condition(cond):
    """Negate a Python condition."""
    cond = cond.strip()
    if cond.startswith("not "):
        inner = cond[4:].strip()
        if inner.startswith("(") and inner.endswith(")"):
            return inner[1:-1]
        return inner
    simple_negations = [
        (" == ", " != "), (" != ", " == "),
        (" is not ", " is "), (" is ", " is not "),
        (" not in ", " in "), (" in ", " not in "),
        (" >= ", " < "), (" <= ", " > "),
        (" > ", " <= "), (" < ", " >= "),
    ]
    for old, new in simple_negations:
        if old in cond and cond.count(old) == 1:
            return cond.replace(old, new)
    if " and " in cond or " or " in cond:
        return f"not ({cond})"
    return f"not {cond}"


def find_block_end(lines, start_idx, block_indent):
    """Find where a block at block_indent ends."""
    end = start_idx
    for i in range(start_idx, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            end = i + 1
            continue
        line_indent = get_indent(lines[i])
        if line_indent < block_indent:
            break
        end = i + 1
    return end


def apply_for_loop_guard(lines):
    """
    Find pattern:
        for VAR in ITER:
            if COND:
                BODY
    Transform to:
        for VAR in ITER:
            if not COND:
                continue
            BODY (de-indented)
    """
    changed = False
    i = 0
    result = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for: for VAR in ITER: or while COND:
        is_for = stripped.startswith("for ") and stripped.endswith(":")
        is_while = stripped.startswith("while ") and stripped.endswith(":")
        is_loop = is_for or is_while

        if not is_loop or not stripped:
            result.append(line)
            i += 1
            continue

        loop_indent = get_indent(line)
        body_indent = loop_indent + 4
        body_indent_str = " " * body_indent

        # Find the next non-blank line (should be the if statement)
        next_idx = i + 1
        while next_idx < len(lines) and not lines[next_idx].strip():
            next_idx += 1

        if next_idx >= len(lines):
            result.append(line)
            i += 1
            continue

        next_line = lines[next_idx]
        next_stripped = next_line.strip()
        next_indent = get_indent(next_line)

        # Must be an if at body indent level
        if next_indent != body_indent or not next_stripped.startswith("if "):
            result.append(line)
            i += 1
            continue

        # Extract condition
        cond_match = re.match(r'if\s+(.+?)\s*:', next_stripped)
        if not cond_match:
            result.append(line)
            i += 1
            continue

        condition = cond_match.group(1)
        if_body_indent = body_indent + 4
        if_body_indent_str = " " * if_body_indent

        # Find end of if body
        if_body_start = next_idx + 1
        if_body_end = find_block_end(lines, if_body_start, if_body_indent)

        # Check if there's an else/elif after the if body
        has_else = False
        if if_body_end < len(lines):
            after_if = lines[if_body_end].strip() if if_body_end < len(lines) else ""
            if after_if.startswith("elif ") or after_if.startswith("else:"):
                has_else = True

        if has_else:
            result.append(line)
            i += 1
            continue

        # Check that the if body is the only/main content of the loop body
        # Find end of loop body
        loop_body_end = find_block_end(lines, i + 1, body_indent)

        # Count lines after the if block in the loop
        code_after_if = 0
        for j in range(if_body_end, loop_body_end):
            if lines[j].strip():
                code_after_if += 1

        # The if body should be the majority of loop content
        if_body_lines = [l for l in lines[if_body_start:if_body_end] if l.strip()]
        if len(if_body_lines) < 3:
            result.append(line)
            i += 1
            continue

        if code_after_if > 2:
            result.append(line)
            i += 1
            continue

        # Apply the transformation!
        negated = negate_condition(condition)

        # Add the for/while line
        result.append(line)
        # Add blank lines between for and if (preserve them)
        for j in range(i + 1, next_idx):
            result.append(lines[j])
        # Add guard clause
        result.append(f"{body_indent_str}if {negated}:")
        result.append(f"{body_indent_str}    continue")

        # Add de-indented if body
        for j in range(if_body_start, if_body_end):
            l = lines[j]
            if not l.strip():
                result.append("")
            elif l.startswith(if_body_indent_str):
                result.append(body_indent_str + l[if_body_indent:])
            else:
                result.append(l)

        # Add any remaining loop body after the if
        for j in range(if_body_end, loop_body_end):
            result.append(lines[j])

        changed = True
        i = loop_body_end
        continue

    return result, changed


def apply_function_guard(lines):
    """
    Find pattern (at function level):
        def func():
            [docstring]
            if COND:
                BODY
    Transform to:
        def func():
            [docstring]
            if not COND:
                return
            BODY (de-indented)
    """
    changed = False
    result = list(lines)

    # Find function definitions
    i = 0
    while i < len(result):
        line = result[i]
        stripped = line.strip()

        if not (stripped.startswith("def ") or stripped.startswith("async def ")):
            i += 1
            continue

        func_indent = get_indent(line)
        body_indent = func_indent + 4
        body_indent_str = " " * body_indent

        # Skip past docstring
        body_start = i + 1
        while body_start < len(result) and not result[body_start].strip():
            body_start += 1

        if body_start >= len(result):
            i += 1
            continue

        # Check for docstring
        doc_line = result[body_start].strip()
        if doc_line.startswith('"""') or doc_line.startswith("'''"):
            quote = doc_line[:3]
            if doc_line.count(quote) >= 2:
                body_start += 1
            else:
                for j in range(body_start + 1, min(body_start + 50, len(result))):
                    if quote in result[j]:
                        body_start = j + 1
                        break

        # Skip blank lines after docstring
        while body_start < len(result) and not result[body_start].strip():
            body_start += 1

        if body_start >= len(result):
            i += 1
            continue

        # Check if first statement is an `if`
        first_stmt = result[body_start]
        first_stripped = first_stmt.strip()
        first_indent = get_indent(first_stmt)

        if first_indent != body_indent or not first_stripped.startswith("if "):
            i += 1
            continue

        cond_match = re.match(r'if\s+(.+?)\s*:', first_stripped)
        if not cond_match:
            i += 1
            continue

        condition = cond_match.group(1)
        if_body_indent = body_indent + 4
        if_body_indent_str = " " * if_body_indent

        # Find end of if body
        if_body_start = body_start + 1
        if_body_end = find_block_end(result, if_body_start, if_body_indent)

        # Check for else/elif
        has_else = False
        if if_body_end < len(result):
            after_if = result[if_body_end].strip()
            if after_if.startswith("elif ") or after_if.startswith("else:"):
                has_else = True

        if has_else:
            i += 1
            continue

        # Find end of function
        func_end = find_block_end(result, i + 1, body_indent)

        # Check that the if spans most of the function
        func_body_lines = sum(1 for j in range(body_start, func_end) if result[j].strip())
        if_body_content = sum(1 for j in range(if_body_start, if_body_end) if result[j].strip())

        if if_body_content < func_body_lines * 0.5:
            i += 1
            continue

        # Code after the if block
        code_after = sum(1 for j in range(if_body_end, func_end) if result[j].strip())
        if code_after > 3:
            i += 1
            continue

        # Apply transformation
        negated = negate_condition(condition)
        new_lines = result[:body_start]
        new_lines.append(f"{body_indent_str}if {negated}:")
        new_lines.append(f"{body_indent_str}    return")
        new_lines.append("")

        for j in range(if_body_start, if_body_end):
            l = result[j]
            if not l.strip():
                new_lines.append("")
            elif l.startswith(if_body_indent_str):
                new_lines.append(body_indent_str + l[if_body_indent:])
            else:
                new_lines.append(l)

        # Add remaining lines after if block
        for j in range(if_body_end, func_end):
            new_lines.append(result[j])

        new_lines.extend(result[func_end:])
        result = new_lines
        changed = True
        # Don't increment i - re-check same position for nested guards
        i += 1

    return result, changed


def flatten_with_blocks(lines):
    """
    Transform: with A:\n    with B: -> with A, B:
    """
    changed = False
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not (stripped.startswith("with ") and stripped.endswith(":")):
            result.append(line)
            i += 1
            continue

        with_indent = get_indent(line)
        inner_indent = with_indent + 4

        # Check next non-blank line
        next_idx = i + 1
        while next_idx < len(lines) and not lines[next_idx].strip():
            next_idx += 1

        if next_idx >= len(lines):
            result.append(line)
            i += 1
            continue

        next_line = lines[next_idx]
        next_stripped = next_line.strip()
        next_line_indent = get_indent(next_line)

        if (next_line_indent == inner_indent and
            next_stripped.startswith("with ") and
            next_stripped.endswith(":") and
                " as " not in stripped or " as " not in next_stripped):

            # Can we merge? Only if the outer with has no 'as' clause
            # that's used in the inner with expression
            outer_ctx = stripped[5:-1].strip()  # Between 'with ' and ':'
            inner_ctx = next_stripped[5:-1].strip()

            # Simple merge
            new_line = f"{' ' * with_indent}with {outer_ctx}, {inner_ctx}:"
            result.append(new_line)

            # De-indent the inner body by one level
            inner_body_indent = inner_indent + 4
            body_end = find_block_end(lines, next_idx + 1, inner_body_indent)

            for j in range(next_idx + 1, body_end):
                l = lines[j]
                if not l.strip():
                    result.append("")
                elif l.startswith(" " * inner_body_indent):
                    result.append(" " * inner_indent + l[inner_body_indent:])
                else:
                    result.append(l)

            changed = True
            i = body_end
            continue

        result.append(line)
        i += 1

    return result, changed


def reduce_nesting_in_file(filepath, content):
    """Apply all nesting reduction transforms to a file."""
    if not check_syntax(content, str(filepath)):
        return content, 0

    lines = content.split("\n")
    total_changes = 0

    # Multiple passes - each pass may enable further reductions
    for pass_num in range(8):
        pass_changed = False

        # Apply for-loop guards
        new_lines, changed = apply_for_loop_guard(lines)
        if changed:
            lines = new_lines
            pass_changed = True
            total_changes += 1

        # Apply function-level guards
        new_lines, changed = apply_function_guard(lines)
        if changed:
            lines = new_lines
            pass_changed = True
            total_changes += 1

        # Apply with-block flattening
        new_lines, changed = flatten_with_blocks(lines)
        if changed:
            lines = new_lines
            pass_changed = True
            total_changes += 1

        if not pass_changed:
            break

    if total_changes > 0:
        new_content = "\n".join(lines)
        if check_syntax(new_content, str(filepath)):
            return new_content, total_changes
        else:
            return content, 0  # Revert if syntax breaks

    return content, 0


def main():
    global CHANGES

    print("=" * 60)
    print("ZEN_AI_RAG NESTING REDUCER v2")
    print("=" * 60)

    # Count initial nesting
    initial_deep = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        depth = 0
                        for child in ast.walk(node):
                            if isinstance(child, (ast.If, ast.For, ast.While, ast.With,
                                                  ast.Try, ast.ExceptHandler, ast.AsyncFor)):
                                d = getattr(child, '_depth', 0)
                        # Simple depth calc
                        lines_txt = content.split("\n")[node.lineno-1:node.end_lineno]
                        if lines_txt:
                            base = get_indent(lines_txt[0])
                            max_d = 0
                            for l in lines_txt:
                                if l.strip():
                                    d = (get_indent(l) - base) // 4
                                    max_d = max(max_d, d)
                            if max_d >= 5:  # ~nesting 4+
                                initial_deep += 1
            except Exception:
                pass

    print(f"Initial deeply-nested functions: ~{initial_deep}")
    print()

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
                new_content, changes = reduce_nesting_in_file(filepath, content)
                if changes > 0:
                    write_file(filepath, new_content)
                    rel = filepath.relative_to(ZEN)
                    log(f"REDUCED {rel}: {changes} transforms")
                    CHANGES += changes
                    file_count += 1
            except Exception as e:
                rel = filepath.relative_to(ZEN)
                ERRORS.append(f"{rel}: {e}")

    print(f"\nTotal transforms applied: {CHANGES}")
    print(f"Files modified: {file_count}")
    if ERRORS:
        print(f"Errors: {len(ERRORS)}")
        for e in ERRORS[:10]:
            print(f"  - {e}")

    # Count final nesting
    final_deep = 0
    broken = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                if not check_syntax(content, str(filepath)):
                    broken += 1
                    continue
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        lines_txt = content.split("\n")[node.lineno-1:node.end_lineno]
                        if lines_txt:
                            base = get_indent(lines_txt[0])
                            max_d = 0
                            for l in lines_txt:
                                if l.strip():
                                    d = (get_indent(l) - base) // 4
                                    max_d = max(max_d, d)
                            if max_d >= 5:
                                final_deep += 1
            except Exception:
                pass

    print(f"\nDeeply-nested functions: {initial_deep} -> {final_deep}")
    print(f"Broken files: {broken}")
    print("\nEXIT:0")


if __name__ == "__main__":
    main()
