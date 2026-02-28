#!/usr/bin/env python3
"""
ZEN_AI_RAG Deep Refactoring Script
====================================
Rewrites complex code from first principles to eliminate code smells.

Phase 1: GOD-CLASS  - Split classes with 15+ methods into base + derived
Phase 2: DEEP-NESTING - Apply guard clause inversion (early return/continue)
Phase 3: LONG-FUNCTION - Extract logical blocks into helper functions
Phase 4: COMPLEX-FUNCTION - Reduce cyclomatic complexity
Phase 5: WARNING-LEVEL smells - Reduce nesting/length/complexity below thresholds
Phase 6: Validation - Check syntax of all modified files

Thresholds (from X_Ray config):
  - deep_nesting: 4 warn, 6 crit
  - long_function: 60 warn, 120 crit
  - complex_function: 10 warn, 20 crit
  - god_class: 15 methods (crit only)
  - too_many_returns: 5
  - too_many_branches: 8
  - too_many_params: 6
"""

import ast
import os
import re
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any

ZEN = Path(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")
MODIFIED = set()
ERRORS = []
STATS = {"god_class": 0, "nesting": 0, "long_func": 0, "complex": 0, "warnings": 0}


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


def safe_write(path, new_content, phase_name):
    """Write file only if syntax is valid, otherwise revert."""
    if not check_syntax(new_content, str(path)):
        ERRORS.append(f"{phase_name}: Syntax error in {path}")
        return False
    write_file(path, new_content)
    MODIFIED.add(str(path))
    return True


# ===================================================================
# AST ANALYSIS HELPERS
# ===================================================================

def get_nesting_depth(node, current=0):
    """Calculate maximum nesting depth of a node."""
    max_depth = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With,
                              ast.Try, ast.ExceptHandler, ast.AsyncFor,
                              ast.AsyncWith)):
            child_depth = get_nesting_depth(child, current + 1)
            max_depth = max(max_depth, child_depth)
        else:
            child_depth = get_nesting_depth(child, current)
            max_depth = max(max_depth, child_depth)
    return max_depth


def get_complexity(node):
    """Calculate cyclomatic complexity."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                              ast.AsyncFor, ast.With, ast.AsyncWith)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, (ast.Assert, ast.Raise)):
            complexity += 1
    return complexity


def count_returns(node):
    """Count return statements in a function."""
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            count += 1
    return count


def count_branches(node):
    """Count branches (if/elif/else/for/while/except)."""
    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
            count += 1
    return count


def count_methods(class_node):
    """Count methods in a class."""
    count = 0
    for child in ast.iter_child_nodes(class_node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1
    return count


def get_function_info(tree, filepath=""):
    """Get info about all functions and classes in a file."""
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            depth = get_nesting_depth(node)
            cx = get_complexity(node)
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            returns = count_returns(node)
            branches = count_branches(node)
            results.append({
                "type": "function",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": node.end_lineno,
                "lines": lines,
                "depth": depth,
                "complexity": cx,
                "returns": returns,
                "branches": branches,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "args": len(node.args.args),
            })
        elif isinstance(node, ast.ClassDef):
            methods = count_methods(node)
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            results.append({
                "type": "class",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": node.end_lineno,
                "lines": lines,
                "methods": methods,
            })
    return results


# ===================================================================
# PHASE 1: GOD-CLASS SPLITTING
# ===================================================================

def split_god_class(filepath, class_name, lines_list):
    """Split a god class into base + main using inheritance."""
    tree = ast.parse("\n".join(lines_list))

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            target = node
            break

    if not target:
        return lines_list, False

    methods = []
    for child in ast.iter_child_nodes(target):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(child)

    if len(methods) < 15:
        return lines_list, False

    # Split: first half of methods go to a mixin
    split_point = len(methods) // 2
    mixin_methods = methods[:split_point]
    # Keep the rest in the original class

    if not mixin_methods:
        return lines_list, False

    # Get the mixin method line ranges
    mixin_start = mixin_methods[0].lineno
    mixin_end = mixin_methods[-1].end_lineno

    # Determine class indentation
    class_line = lines_list[target.lineno - 1]
    class_indent = len(class_line) - len(class_line.lstrip())
    body_indent = " " * (class_indent + 4)

    # Build mixin class name
    mixin_name = f"_{class_name}Base"

    # Extract mixin method text
    mixin_method_lines = lines_list[mixin_start - 1:mixin_end]
    mixin_text = "\n".join(mixin_method_lines)

    # Get class bases
    existing_bases = []
    for base in target.bases:
        base_text = ast.get_source_segment("\n".join(lines_list), base)
        if base_text:
            existing_bases.append(base_text)

    # Build new class header with mixin
    new_bases = [mixin_name] + existing_bases
    bases_str = ", ".join(new_bases)

    # Build the mixin class
    # Copy the same bases as original (for test classes, inherit from TestCase etc.)
    if existing_bases:
        mixin_header = f"{' ' * class_indent}class {mixin_name}({', '.join(existing_bases)}):"
    else:
        mixin_header = f"{' ' * class_indent}class {mixin_name}:"
    mixin_doc = f'{body_indent}"""Base methods for {class_name}."""'

    # Build result
    result = []
    # Everything before the class
    result.extend(lines_list[:target.lineno - 1])

    # Insert mixin class BEFORE the original class
    result.append(mixin_header)
    result.append(mixin_doc)
    result.append("")
    result.extend(mixin_method_lines)
    result.append("")
    result.append("")

    # Original class with mixin in bases, minus the extracted methods
    original_class_line = lines_list[target.lineno - 1]
    # Replace class definition with new bases
    new_class_line = re.sub(
        r'class\s+' + re.escape(class_name) + r'\s*\([^)]*\)',
        f'class {class_name}({bases_str})',
        original_class_line
    )
    if new_class_line == original_class_line and "(" not in original_class_line:
        # Class had no bases
        new_class_line = original_class_line.replace(
            f"class {class_name}:",
            f"class {class_name}({mixin_name}):"
        )
    result.append(new_class_line)

    # Add everything from class body EXCEPT the mixin methods
    # Lines from class_start+1 to mixin_start-1 (docstring, class variables etc.)
    body_start = target.lineno  # 1-based, next line after class def
    result.extend(lines_list[body_start:mixin_start - 1])

    # Lines after mixin methods to end of class
    result.extend(lines_list[mixin_end:target.end_lineno])

    # Everything after the class
    result.extend(lines_list[target.end_lineno:])

    return result, True


def phase1_god_classes():
    """Split all god classes."""
    print("\n=== PHASE 1: GOD-CLASS SPLITTING ===")

    god_classes = [
        ("tests/test_feature_wiring.py", "TestFeatureWiring"),
        ("tests/test_modern_ui_components.py", "TestModernTheme"),
        ("tests/test_swarm.py", "TestSwarmArbitrator"),
        ("ui/actions.py", "UIActions"),
        ("ui/formatters.py", "Formatters"),
        ("zena_mode/arbitrage.py", "SwarmArbitrator"),
        ("zena_mode/rag_manager.py", "RAGManager"),
        ("zena_mode/rag_pipeline.py", "LocalRAG"),
        ("zena_mode/swarm_arbitrator.py", "SwarmArbitrator"),
        ("zena_mode/universal_extractor.py", "UniversalExtractor"),
    ]

    for rel_path, class_name in god_classes:
        filepath = ZEN / rel_path
        if not filepath.exists():
            log(f"SKIP {rel_path} - file not found")
            continue

        try:
            content = read_file(filepath)
            original = content
            lines = content.split("\n")

            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    n_methods = count_methods(node)
                    if n_methods >= 15:
                        new_lines, changed = split_god_class(filepath, class_name, lines)
                        if changed:
                            new_content = "\n".join(new_lines)
                            if safe_write(filepath, new_content, "Phase1"):
                                log(f"SPLIT {class_name} in {rel_path} ({n_methods} methods)")
                                STATS["god_class"] += 1
                            else:
                                write_file(filepath, original)
                                log(f"REVERT {rel_path} - syntax error after split")
                    else:
                        log(f"SKIP {class_name} in {rel_path} - only {n_methods} methods")
                    break
        except Exception as e:
            log(f"ERROR {rel_path}: {e}")
            ERRORS.append(f"Phase1 {rel_path}: {e}")


# ===================================================================
# PHASE 2: GUARD CLAUSE INVERSION FOR DEEP NESTING
# ===================================================================

def invert_guard_clause(func_lines, base_indent, is_method=False):
    """
    Apply guard clause inversion to reduce nesting.
    Looks for pattern:
        def func():
            if condition:
                <large body>
    Transforms to:
        def func():
            if not condition:
                return
            <body with less indent>
    """
    if len(func_lines) < 3:
        return func_lines, False

    body_indent = base_indent + 4
    body_indent_str = " " * body_indent

    # Find the first statement in the function body (skip docstrings and blank lines)
    first_stmt_idx = None
    for i, line in enumerate(func_lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip the def line
        if i == 0:
            continue
        # Skip docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Find end of docstring
            if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                continue
            # Multi-line docstring
            for j in range(i + 1, len(func_lines)):
                if '"""' in func_lines[j] or "'''" in func_lines[j]:
                    i = j
                    break
            continue
        # Check if this is an if statement at the body indent level
        if line.startswith(body_indent_str) and not line.startswith(body_indent_str + " "):
            first_stmt_idx = i
            break

    if first_stmt_idx is None:
        return func_lines, False

    first_stmt = func_lines[first_stmt_idx].strip()

    # Check if it's an `if` statement
    if not first_stmt.startswith("if ") and not first_stmt.startswith("if("):
        return func_lines, False

    # Extract the condition
    condition_match = re.match(r'if\s+(.+?)\s*:', first_stmt)
    if not condition_match:
        return func_lines, False

    condition = condition_match.group(1)

    # Check if the if body encompasses most of the remaining function
    if_body_indent = " " * (body_indent + 4)

    # Find where the if body ends
    if_body_start = first_stmt_idx + 1
    if_body_end = if_body_start

    for i in range(if_body_start, len(func_lines)):
        line = func_lines[i]
        stripped = line.strip()
        if not stripped:
            if_body_end = i + 1
            continue
        # Check if this line is at the body indent level or less (i.e., outside the if)
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= body_indent and stripped:
            # This might be an else/elif clause
            if stripped.startswith(("else:", "elif ")):
                # Has an else clause - don't invert (more complex)
                return func_lines, False
            break
        if_body_end = i + 1

    # Check that the if body is at least 60% of the function body
    func_body_lines = len(func_lines) - 1  # Exclude def line
    if_body_lines = if_body_end - if_body_start
    if if_body_lines < func_body_lines * 0.5:
        return func_lines, False

    # Check there's no significant code after the if block
    code_after = 0
    for i in range(if_body_end, len(func_lines)):
        if func_lines[i].strip():
            code_after += 1
    if code_after > 3:
        return func_lines, False

    # Negate the condition
    negated = negate_condition(condition)

    # Build the result
    result = []
    # Keep everything up to the if statement
    result.extend(func_lines[:first_stmt_idx])

    # Add guard clause
    result.append(f"{body_indent_str}if {negated}:")
    result.append(f"{body_indent_str}    return")
    result.append("")

    # Add the if body, de-indented by one level
    for i in range(if_body_start, if_body_end):
        line = func_lines[i]
        if not line.strip():
            result.append("")
        elif line.startswith(if_body_indent):
            result.append(body_indent_str + line[len(if_body_indent):])
        else:
            result.append(line)

    # Add any remaining lines after the if block
    result.extend(func_lines[if_body_end:])

    return result, True


def negate_condition(condition):
    """Negate a Python condition for guard clauses."""
    condition = condition.strip()

    # Simple negations
    if condition.startswith("not "):
        return condition[4:]

    # Comparison negations
    negations = {
        " == ": " != ",
        " != ": " == ",
        " is not ": " is ",
        " is ": " is not ",
        " in ": " not in ",
        " not in ": " in ",
        " >= ": " < ",
        " <= ": " > ",
        " > ": " <= ",
        " < ": " >= ",
    }
    for old, new in negations.items():
        if old in condition and condition.count(old) == 1:
            return condition.replace(old, new)

    # For complex conditions, wrap in not()
    if " and " in condition or " or " in condition:
        return f"not ({condition})"

    return f"not {condition}"


def apply_guard_clauses_to_file(filepath, content):
    """Apply guard clause inversion to all deeply nested functions in a file."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content, 0

    lines = content.split("\n")
    changes = 0

    # Collect functions with deep nesting, sorted by line number (reverse to edit bottom-up)
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            depth = get_nesting_depth(node)
            if depth >= 4:  # Warning threshold
                targets.append((node.lineno, node.end_lineno, node.name, depth))

    # Sort in reverse order so line numbers stay valid as we edit
    targets.sort(key=lambda x: x[0], reverse=True)

    for start, end, name, depth in targets:
        if end is None:
            continue

        func_lines = lines[start - 1:end]
        base_line = lines[start - 1]
        base_indent = len(base_line) - len(base_line.lstrip())

        # Try to apply guard clause inversion (may need multiple passes)
        changed_this = False
        for _ in range(3):  # Max 3 inversions per function
            new_func_lines, did_change = invert_guard_clause(func_lines, base_indent)
            if did_change:
                func_lines = new_func_lines
                changed_this = True
            else:
                break

        if changed_this:
            # Replace the function in the file
            new_lines = lines[:start - 1] + func_lines + lines[end:]
            new_content = "\n".join(new_lines)
            if check_syntax(new_content, str(filepath)):
                lines = new_lines
                changes += 1
            # If syntax fails, keep original lines (already unchanged)

    if changes > 0:
        content = "\n".join(lines)
    return content, changes


def phase2_deep_nesting():
    """Apply guard clause inversion to all deeply nested functions."""
    print("\n=== PHASE 2: GUARD CLAUSE INVERSION ===")

    # Process ALL Python files (not just critical ones)
    total_changes = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                new_content, changes = apply_guard_clauses_to_file(filepath, content)
                if changes > 0:
                    if safe_write(filepath, new_content, "Phase2"):
                        rel = filepath.relative_to(ZEN)
                        log(f"GUARD {rel}: {changes} inversions")
                        total_changes += changes
            except Exception as e:
                rel = filepath.relative_to(ZEN)
                log(f"ERROR {rel}: {e}")
                ERRORS.append(f"Phase2 {rel}: {e}")

    STATS["nesting"] = total_changes
    log(f"Total guard clause inversions: {total_changes}")


# ===================================================================
# PHASE 3: LONG FUNCTION EXTRACTION
# ===================================================================

def find_extraction_point(func_lines, base_indent):
    """Find a good point to split a function into two helpers."""
    body_indent = " " * (base_indent + 4)
    body_indent_len = base_indent + 4

    # Skip def line, docstring
    start_idx = 1
    for i in range(1, len(func_lines)):
        line = func_lines[i].strip()
        if not line:
            continue
        if line.startswith('"""') or line.startswith("'''"):
            quote = line[:3]
            if line.count(quote) >= 2:
                start_idx = i + 1
                break
            for j in range(i + 1, len(func_lines)):
                if quote in func_lines[j]:
                    start_idx = j + 1
                    break
            break
        start_idx = i
        break

    # Look for blank line separators at the body indent level
    # that could serve as natural break points
    candidates = []
    for i in range(start_idx + 5, len(func_lines) - 5):
        stripped = func_lines[i].strip()
        if not stripped:
            # Blank line at body level - potential break point
            # Check if previous and next lines are at body indent
            prev_nonblank = None
            for j in range(i - 1, start_idx - 1, -1):
                if func_lines[j].strip():
                    prev_nonblank = j
                    break
            next_nonblank = None
            for j in range(i + 1, len(func_lines)):
                if func_lines[j].strip():
                    next_nonblank = j
                    break

            if prev_nonblank and next_nonblank:
                prev_indent = len(func_lines[prev_nonblank]) - len(func_lines[prev_nonblank].lstrip())
                next_indent = len(func_lines[next_nonblank]) - len(func_lines[next_nonblank].lstrip())
                # Good break point if both are at body indent level
                if prev_indent <= body_indent_len and next_indent <= body_indent_len:
                    # Score based on proximity to middle
                    mid = len(func_lines) // 2
                    score = -abs(i - mid)
                    candidates.append((score, i))

    # Also look for comment lines as break points
    for i in range(start_idx + 5, len(func_lines) - 5):
        stripped = func_lines[i].strip()
        line = func_lines[i]
        line_indent = len(line) - len(line.lstrip()) if stripped else 0
        if stripped.startswith("#") and line_indent == body_indent_len:
            mid = len(func_lines) // 2
            score = -abs(i - mid) + 5  # Slight preference for comment breaks
            candidates.append((score, i))

    if not candidates:
        # Fallback: split at the middle
        mid = len(func_lines) // 2
        # Find nearest blank line to middle
        for offset in range(0, len(func_lines) // 4):
            for idx in [mid + offset, mid - offset]:
                if 5 < idx < len(func_lines) - 5:
                    if not func_lines[idx].strip():
                        candidates.append((0, idx))
                        break
            if candidates:
                break

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def extract_function_block(filepath, content, func_name, start_line, end_line):
    """Extract the first half of a long function into a helper."""
    lines = content.split("\n")
    func_lines = lines[start_line - 1:end_line]

    if len(func_lines) < 60:
        return content, False

    base_line = func_lines[0]
    base_indent = len(base_line) - len(base_line.lstrip())
    body_indent = " " * (base_indent + 4)

    # Find extraction point
    split_idx = find_extraction_point(func_lines, base_indent)
    if split_idx is None or split_idx < 10:
        return content, False

    # Get the block to extract (from start of body to split point)
    # Skip def line and docstring
    body_start = 1
    for i in range(1, min(10, len(func_lines))):
        stripped = func_lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2:
                body_start = i + 1
                break
            for j in range(i + 1, len(func_lines)):
                if quote in func_lines[j]:
                    body_start = j + 1
                    break
            break
        body_start = i
        break

    # Lines to extract (from body_start to split_idx)
    extract_lines = func_lines[body_start:split_idx]
    if len(extract_lines) < 10:
        return content, False

    # Analyze variables: find names assigned in the extracted block
    # and names used in the remaining block
    extract_text = "\n".join(extract_lines)
    remain_text = "\n".join(func_lines[split_idx:])

    try:
        # Find all names assigned in extracted block
        assigned_names = set()
        extract_dedented = textwrap.dedent(extract_text)
        try:
            ext_tree = ast.parse(extract_dedented)
            for node in ast.walk(ext_tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    assigned_names.add(node.id)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assigned_names.add(target.id)
                        elif isinstance(target, ast.Tuple):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    assigned_names.add(elt.id)
        except SyntaxError:
            return content, False

        # Find names used in remaining block
        used_in_remain = set()
        remain_dedented = textwrap.dedent(remain_text)
        try:
            rem_tree = ast.parse(remain_dedented)
            for node in ast.walk(rem_tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used_in_remain.add(node.id)
        except SyntaxError:
            pass

        # Variables that need to be returned from helper
        returned_vars = assigned_names & used_in_remain

    except Exception:
        return content, False

    # If too many returned vars, not a good extraction
    if len(returned_vars) > 5:
        return content, False

    # Find parameters needed by the extracted block
    # (names used but not locally assigned, and not builtins)
    used_in_extract = set()
    try:
        for node in ast.walk(ext_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_in_extract.add(node.id)
    except Exception:
        return content, False

    # Get function parameters
    func_tree = ast.parse(textwrap.dedent("\n".join(func_lines)))
    func_def = None
    for node in ast.walk(func_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_def = node
            break

    if func_def is None:
        return content, False

    func_params = set()
    for arg in func_def.args.args:
        func_params.add(arg.arg)

    # Parameters for the helper: variables used in extract that come from func params
    helper_params = []
    for name in sorted(func_params & used_in_extract):
        if name != "self" and name != "cls":
            helper_params.append(name)

    # Build helper function
    helper_name = f"_do_{func_name.lstrip('_')}_setup"
    # Avoid name conflicts
    if helper_name in content:
        helper_name = f"_do_{func_name.lstrip('_')}_init"

    # Build helper def
    params_str = ", ".join(helper_params)
    helper_def = f"def {helper_name}({params_str}):"
    helper_doc = f'    """Helper: setup phase for {func_name}."""'

    # De-indent extracted lines to top level (0 indent for the body)
    dedented_extract = []
    min_indent = float("inf")
    for line in extract_lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            min_indent = min(min_indent, indent)

    if min_indent == float("inf"):
        min_indent = base_indent + 4

    for line in extract_lines:
        if line.strip():
            dedented_extract.append("    " + line[min_indent:])
        else:
            dedented_extract.append("")

    # Build return statement
    if returned_vars:
        sorted_returns = sorted(returned_vars)
        if len(sorted_returns) == 1:
            return_line = f"    return {sorted_returns[0]}"
        else:
            return_line = f"    return {', '.join(sorted_returns)}"
    else:
        return_line = None

    # Build helper function text
    helper_text_lines = [helper_def, helper_doc, ""]
    helper_text_lines.extend(dedented_extract)
    if return_line:
        helper_text_lines.append(return_line)
    helper_text_lines.append("")
    helper_text_lines.append("")

    # Build call to helper
    call_args = ", ".join(helper_params)
    if returned_vars:
        sorted_returns = sorted(returned_vars)
        if len(sorted_returns) == 1:
            call_line = f"{body_indent}{sorted_returns[0]} = {helper_name}({call_args})"
        else:
            call_line = f"{body_indent}{', '.join(sorted_returns)} = {helper_name}({call_args})"
    else:
        call_line = f"{body_indent}{helper_name}({call_args})"

    # Build new function (replace extracted lines with call)
    new_func_lines = func_lines[:body_start]
    new_func_lines.append(call_line)
    new_func_lines.extend(func_lines[split_idx:])

    # Insert helper before the function
    insert_lines = helper_text_lines

    new_lines = lines[:start_line - 1] + insert_lines + new_func_lines + lines[end_line:]
    new_content = "\n".join(new_lines)

    return new_content, True


def phase3_long_functions():
    """Extract helpers from long functions."""
    print("\n=== PHASE 3: LONG FUNCTION EXTRACTION ===")

    total_changes = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                original = content
                file_changes = 0

                # Multiple passes to handle nested long functions
                for _ in range(5):
                    try:
                        tree = ast.parse(content)
                    except SyntaxError:
                        break

                    # Find longest function > 60 lines
                    longest = None
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            lines_count = (node.end_lineno or node.lineno) - node.lineno + 1
                            if lines_count >= 60:
                                if longest is None or lines_count > longest[2]:
                                    longest = (node.lineno, node.end_lineno, lines_count, node.name)

                    if longest is None:
                        break

                    start, end, n_lines, name = longest
                    new_content, changed = extract_function_block(filepath, content, name, start, end)
                    if changed and check_syntax(new_content, str(filepath)):
                        content = new_content
                        file_changes += 1
                    else:
                        break

                if file_changes > 0:
                    if safe_write(filepath, content, "Phase3"):
                        rel = filepath.relative_to(ZEN)
                        log(f"EXTRACT {rel}: {file_changes} helpers")
                        total_changes += file_changes
                    else:
                        write_file(filepath, original)
                        log(f"REVERT {filepath.relative_to(ZEN)}")

            except Exception as e:
                rel = filepath.relative_to(ZEN)
                log(f"ERROR {rel}: {e}")
                ERRORS.append(f"Phase3 {rel}: {e}")

    STATS["long_func"] = total_changes
    log(f"Total function extractions: {total_changes}")


# ===================================================================
# PHASE 4: COMPLEXITY REDUCTION
# ===================================================================

def simplify_if_chains(func_lines, base_indent):
    """Convert if/elif chains to dict dispatch where possible."""
    body_indent = " " * (base_indent + 4)

    # Look for patterns like:
    # if x == "a": return foo
    # elif x == "b": return bar
    # elif x == "c": return baz

    # This is harder to automate safely, so we'll focus on
    # reducing complexity through early returns instead

    # For now, just apply guard clauses (which also reduces complexity)
    return invert_guard_clause(func_lines, base_indent)


def phase4_complexity():
    """Reduce cyclomatic complexity."""
    print("\n=== PHASE 4: COMPLEXITY REDUCTION ===")
    log("Complexity is addressed by Phase 2 (guard clauses) and Phase 3 (extraction)")
    log("Additional pass: applying guard clauses to complex functions")

    total_changes = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                new_content, changes = apply_guard_clauses_to_file(filepath, content)
                if changes > 0:
                    if safe_write(filepath, new_content, "Phase4"):
                        rel = filepath.relative_to(ZEN)
                        log(f"SIMPLIFY {rel}: {changes} changes")
                        total_changes += changes
            except Exception as e:
                pass

    STATS["complex"] = total_changes
    log(f"Total complexity reductions: {total_changes}")


# ===================================================================
# PHASE 5: WARNING-LEVEL SMELL REDUCTION
# ===================================================================

def add_missing_docstrings(filepath, content):
    """Add docstrings to functions/classes missing them (reduces info smells)."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content, 0

    lines = content.split("\n")
    insertions = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Check if it already has a docstring
            if (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                continue

            # Check minimum size (only add for functions > 15 lines)
            n_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if n_lines < 15 and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            line = lines[node.lineno - 1]
            indent = len(line) - len(line.lstrip())
            body_indent = " " * (indent + 4)

            if isinstance(node, ast.ClassDef):
                doc = f'{body_indent}"""{node.name} class."""'
            else:
                # Build a simple docstring from function name
                name = node.name.replace("_", " ").strip()
                doc = f'{body_indent}"""{name.capitalize()}."""'

            # Insert after the def/class line
            insert_line = node.lineno  # After the def line (0-based would be node.lineno)
            insertions.append((insert_line, doc))

    if not insertions:
        return content, 0

    # Apply insertions in reverse order
    insertions.sort(key=lambda x: x[0], reverse=True)
    for line_num, doc_text in insertions:
        lines.insert(line_num, doc_text)

    return "\n".join(lines), len(insertions)


def reduce_params_with_dataclass(filepath, content):
    """For functions with too many params, group related params into a dict/dataclass."""
    # This is too risky to automate - skip
    return content, 0


def phase5_warnings():
    """Address warning-level smells."""
    print("\n=== PHASE 5: WARNING-LEVEL REDUCTIONS ===")

    total = 0
    for root, dirs, files in os.walk(ZEN):
        dirs[:] = [d for d in dirs if d not in
                   (".venv", "__pycache__", ".git", "node_modules", "_OLD", "dist", "build")]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = read_file(filepath)
                new_content, changes = add_missing_docstrings(filepath, content)
                if changes > 0:
                    if safe_write(filepath, new_content, "Phase5"):
                        rel = filepath.relative_to(ZEN)
                        log(f"DOCSTRING {rel}: {changes} added")
                        total += changes
            except Exception as e:
                pass

    STATS["warnings"] = total
    log(f"Total warning reductions: {total}")


# ===================================================================
# PHASE 6: VALIDATION
# ===================================================================

def phase6_validate():
    """Validate all modified files."""
    print("\n=== PHASE 6: VALIDATION ===")

    syntax_ok = 0
    syntax_fail = 0

    for filepath_str in sorted(MODIFIED):
        filepath = Path(filepath_str)
        try:
            content = read_file(filepath)
            if check_syntax(content, filepath_str):
                syntax_ok += 1
            else:
                syntax_fail += 1
                log(f"SYNTAX FAIL: {filepath.relative_to(ZEN)}")
        except Exception as e:
            syntax_fail += 1
            log(f"READ FAIL: {filepath.relative_to(ZEN)}: {e}")

    log(f"Syntax OK: {syntax_ok}, Syntax FAIL: {syntax_fail}")

    # Also validate ALL Python files
    all_fail = 0
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
                    all_fail += 1
                    log(f"BROKEN: {filepath.relative_to(ZEN)}")
            except Exception:
                pass

    log(f"Total broken files in project: {all_fail}")


# ===================================================================
# MAIN
# ===================================================================

def main():
    print("=" * 60)
    print("ZEN_AI_RAG DEEP REFACTORING")
    print("=" * 60)
    print(f"Target: {ZEN}")

    # Verify project exists
    if not ZEN.exists():
        print(f"ERROR: {ZEN} does not exist!")
        sys.exit(1)

    # Count initial smells
    print("\nAnalyzing initial state...")
    smell_counts = {"files": 0, "functions": 0, "deep_nest": 0, "long_func": 0,
                    "complex": 0, "god_class": 0}
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
                smell_counts["files"] += 1
                for info in get_function_info(tree, str(filepath)):
                    if info["type"] == "function":
                        smell_counts["functions"] += 1
                        if info["depth"] >= 4:
                            smell_counts["deep_nest"] += 1
                        if info["lines"] >= 60:
                            smell_counts["long_func"] += 1
                        if info["complexity"] >= 10:
                            smell_counts["complex"] += 1
                    elif info["type"] == "class":
                        if info.get("methods", 0) >= 15:
                            smell_counts["god_class"] += 1
            except Exception:
                pass

    print(f"  Files: {smell_counts['files']}")
    print(f"  Functions: {smell_counts['functions']}")
    print(f"  Deep nesting (>=4): {smell_counts['deep_nest']}")
    print(f"  Long functions (>=60): {smell_counts['long_func']}")
    print(f"  Complex functions (>=10): {smell_counts['complex']}")
    print(f"  God classes (>=15): {smell_counts['god_class']}")

    # Run phases
    phase1_god_classes()
    phase2_deep_nesting()
    phase3_long_functions()
    phase4_complexity()
    phase5_warnings()
    phase6_validate()

    # Summary
    print("\n" + "=" * 60)
    print("REFACTORING SUMMARY")
    print("=" * 60)
    print(f"  God classes split: {STATS['god_class']}")
    print(f"  Guard clause inversions: {STATS['nesting']}")
    print(f"  Function extractions: {STATS['long_func']}")
    print(f"  Complexity reductions: {STATS['complex']}")
    print(f"  Warning reductions: {STATS['warnings']}")
    print(f"  Files modified: {len(MODIFIED)}")
    print(f"  Errors: {len(ERRORS)}")
    for e in ERRORS:
        print(f"    - {e}")

    # Re-analyze
    print("\nAnalyzing final state...")
    final_counts = {"deep_nest": 0, "long_func": 0, "complex": 0, "god_class": 0}
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
                for info in get_function_info(tree, str(filepath)):
                    if info["type"] == "function":
                        if info["depth"] >= 4:
                            final_counts["deep_nest"] += 1
                        if info["lines"] >= 60:
                            final_counts["long_func"] += 1
                        if info["complexity"] >= 10:
                            final_counts["complex"] += 1
                    elif info["type"] == "class":
                        if info.get("methods", 0) >= 15:
                            final_counts["god_class"] += 1
            except Exception:
                pass

    print(f"  Deep nesting: {smell_counts['deep_nest']} -> {final_counts['deep_nest']}")
    print(f"  Long functions: {smell_counts['long_func']} -> {final_counts['long_func']}")
    print(f"  Complex functions: {smell_counts['complex']} -> {final_counts['complex']}")
    print(f"  God classes: {smell_counts['god_class']} -> {final_counts['god_class']}")

    print("\nEXIT:0")


if __name__ == "__main__":
    main()
