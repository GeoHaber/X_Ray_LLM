"""
X-Ray LLM — Code smells, dead function detection, duplicate detection.
"""

import ast
import hashlib
import logging
from collections import defaultdict

from analyzers._shared import _fwd, _safe_parse, _walk_py
from xray.types import DeadFunctionResult, SmellResult


def detect_dead_functions(directory: str) -> DeadFunctionResult:
    """Detect potentially dead (uncalled) functions across a Python project."""
    defined = {}  # name -> {file, line, lines_count}
    called = set()
    _EXEMPT = {
        "main",
        "setUp",
        "tearDown",
        "setUpClass",
        "tearDownClass",
        "setUpModule",
        "tearDownModule",
        "__init__",
        "__enter__",
        "__exit__",
        "__str__",
        "__repr__",
        "__len__",
        "__iter__",
        "__next__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__contains__",
        "__eq__",
        "__hash__",
        "__lt__",
        "__le__",
        "__gt__",
        "__ge__",
        "__add__",
        "__sub__",
        "__bool__",
    }
    _EXEMPT_PREFIXES = ("test_", "on_", "handle_", "do_", "setup_", "teardown_", "_")

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            # Collect defined functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in _EXEMPT or name.startswith(_EXEMPT_PREFIXES):
                    continue
                line_count = (node.end_lineno or node.lineno) - node.lineno + 1
                if line_count < 5:
                    continue  # skip tiny functions
                key = name
                if key not in defined:
                    defined[key] = {"name": name, "file": _fwd(rel), "line": node.lineno, "lines": line_count}

            # Collect calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

    dead = []
    for name, info in defined.items():
        if name not in called:
            dead.append(info)

    dead.sort(key=lambda x: -x["lines"])

    return {
        "dead_functions": dead,
        "total_defined": len(defined),
        "total_dead": len(dead),
        "total_called": len(called),
    }


def detect_code_smells(directory: str) -> SmellResult:
    """AST-based code smell detection (long functions, complexity, nesting, etc.)."""
    smells = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            fname = node.name
            line_count = (node.end_lineno or node.lineno) - node.lineno + 1

            # Long function (>50 lines)
            if line_count > 50:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "MEDIUM",
                        "smell": "long_function",
                        "description": f"Function '{fname}' is {line_count} lines (max: 50)",
                        "metric": line_count,
                    }
                )

            # Too many parameters (>5)
            args = node.args
            param_count = len(args.args) + len(args.kwonlyargs)
            if args.vararg:
                param_count += 1
            if args.kwarg:
                param_count += 1
            # Subtract 'self'/'cls'
            if args.args and args.args[0].arg in ("self", "cls"):
                param_count -= 1
            if param_count > 5:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "MEDIUM",
                        "smell": "too_many_params",
                        "description": f"Function '{fname}' has {param_count} parameters (max: 5)",
                        "metric": param_count,
                    }
                )

            # Cyclomatic complexity (count branches)
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.With, ast.Assert)):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
                    complexity += len(child.values) - 1
            if complexity > 10:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "HIGH",
                        "smell": "high_complexity",
                        "description": f"Function '{fname}' has cyclomatic complexity {complexity} (max: 10)",
                        "metric": complexity,
                    }
                )

            # Deep nesting
            max_depth = _max_nesting(node)
            if max_depth > 4:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "MEDIUM",
                        "smell": "deep_nesting",
                        "description": f"Function '{fname}' has nesting depth {max_depth} (max: 4)",
                        "metric": max_depth,
                    }
                )

            # Mutable default arguments
            for default in args.defaults + args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set, ast.Call)):
                    smells.append(
                        {
                            "file": _fwd(rel),
                            "line": node.lineno,
                            "severity": "HIGH",
                            "smell": "mutable_default",
                            "description": f"Function '{fname}' has mutable default argument",
                            "metric": 1,
                        }
                    )
                    break

            # Too many return statements (>5)
            returns = sum(1 for n in ast.walk(node) if isinstance(n, ast.Return))
            if returns > 5:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "LOW",
                        "smell": "too_many_returns",
                        "description": f"Function '{fname}' has {returns} return statements (max: 5)",
                        "metric": returns,
                    }
                )

        # God class detection (>300 lines or >20 methods)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_lines = (node.end_lineno or node.lineno) - node.lineno + 1
                method_count = sum(1 for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
                if class_lines > 300:
                    smells.append(
                        {
                            "file": _fwd(rel),
                            "line": node.lineno,
                            "severity": "MEDIUM",
                            "smell": "god_class",
                            "description": f"Class '{node.name}' is {class_lines} lines (max: 300)",
                            "metric": class_lines,
                        }
                    )
                if method_count > 20:
                    smells.append(
                        {
                            "file": _fwd(rel),
                            "line": node.lineno,
                            "severity": "MEDIUM",
                            "smell": "god_class",
                            "description": f"Class '{node.name}' has {method_count} methods (max: 20)",
                            "metric": method_count,
                        }
                    )

        # Bare except
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                smells.append(
                    {
                        "file": _fwd(rel),
                        "line": node.lineno,
                        "severity": "MEDIUM",
                        "smell": "bare_except",
                        "description": "Bare 'except' clause catches all exceptions including SystemExit, KeyboardInterrupt",
                        "metric": 1,
                    }
                )

        # Magic numbers in function bodies
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):  # noqa: SIM102
                        if child.value not in (0, 1, -1, 2, 0.0, 1.0, 100, True, False, None) and hasattr(
                            child, "lineno"
                        ):
                            smells.append(
                                {
                                    "file": _fwd(rel),
                                    "line": child.lineno,
                                    "severity": "LOW",
                                    "smell": "magic_number",
                                    "description": f"Magic number {child.value} — extract to named constant",
                                    "metric": child.value,
                                }
                            )

    # Deduplicate magic numbers (keep max 50 per file)
    seen = set()
    deduped = []
    for s in smells:
        if s["smell"] == "magic_number":
            key = (s["file"], s["line"], s["metric"])
            if key in seen:
                continue
            seen.add(key)
        deduped.append(s)

    # Cap magic numbers at 100 total
    magic_count = 0
    final = []
    for s in deduped:
        if s["smell"] == "magic_number":
            magic_count += 1
            if magic_count > 100:
                continue
        final.append(s)

    # Group by smell type for summary
    by_smell = defaultdict(int)
    for s in final:
        by_smell[s["smell"]] += 1

    return {
        "smells": final,
        "total": len(final),
        "by_type": dict(by_smell),
    }


def _max_nesting(node, depth=0):
    """Calculate max nesting depth in a function body."""
    max_d = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
            max_d = max(max_d, _max_nesting(child, depth + 1))
        else:
            max_d = max(max_d, _max_nesting(child, depth))
    return max_d


def detect_duplicates(directory: str) -> dict:
    """Detect duplicate code blocks (exact + structural)."""
    # Phase 1: Exact duplicates (by line hash)
    chunk_size = 6  # minimum consecutive lines to consider a duplicate
    chunks = defaultdict(list)  # hash -> [(file, start_line)]

    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError as e:
            logging.debug("Skipped duplicate check for %s: %s", fpath, e)
            continue

        # Normalize lines
        normalized = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                normalized.append((stripped, len(normalized) + 1))  # (content, original_lineno)

        # Slide a window
        for i in range(len(normalized) - chunk_size + 1):
            block = "\n".join(n[0] for n in normalized[i : i + chunk_size])
            h = hashlib.sha256(block.encode()).hexdigest()
            start_line = normalized[i][1]
            chunks[h].append({"file": _fwd(rel), "line": start_line})

    # Filter to actual duplicates (>1 occurrence)
    duplicates = []
    for h, locations in chunks.items():
        if len(locations) < 2:
            continue
        # Skip if all in same file same area (overlapping window)
        files = set(loc["file"] for loc in locations)
        if len(files) == 1:
            lines = [loc["line"] for loc in locations]
            if max(lines) - min(lines) < chunk_size:
                continue
        duplicates.append(
            {
                "hash": h,
                "occurrences": len(locations),
                "locations": locations[:10],  # cap per group
                "lines": chunk_size,
            }
        )

    duplicates.sort(key=lambda x: -x["occurrences"])

    return {
        "duplicate_groups": duplicates[:200],
        "total_groups": len(duplicates),
        "total_duplicated_blocks": sum(d["occurrences"] for d in duplicates),
    }
