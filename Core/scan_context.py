"""
Core/scan_context.py — Shared scan logic for all X-Ray UI frontends
===================================================================

UI-framework-agnostic helpers used by both x_ray_ui.py (Streamlit) and
x_ray_flet.py (Flet desktop). Contains:
  - _scan_codebase()         — parallel AST parse
  - ScanContext              — named-tuple bundling scan inputs
  - _run_phase_*             — per-phase analysis runners
  - _run_scan()              — orchestrates all phases, returns results dict
  - Rust sketch helpers      — _parse_sketch_params, _translate_sketch_body,
                               _generate_rust_sketch
  - Duplicate merge helpers  — _extract_params_from_code, _extract_func_codes,
                               _unified_func_name, _merge_param_lists,
                               _get_first_docstring, _collect_docstrings,
                               _build_unified_header, _build_unified_docstring,
                               _unparse_func_node, _generate_unified_function
"""

from __future__ import annotations

import ast
import concurrent.futures
import textwrap
import time
from collections import namedtuple
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Core.types import FunctionRecord, ClassRecord
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import compute_grade
from Analysis.rust_advisor import RustAdvisor
from Analysis.auto_rustify import (
    py_type_to_rust as _py_type_to_rust,
    _translate_body,
)


# ── Rust sketch helpers ──────────────────────────────────────────────────────

def _parse_sketch_params(func: "FunctionRecord") -> List[str]:
    """Parse Python parameters into Rust parameter strings."""
    try:
        tree = ast.parse(func.code)
        func_node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
            None,
        )
        if func_node is None:
            raise ValueError("No function node")
        params = []
        for arg in func_node.args.args:
            if arg.arg == "self":
                continue
            rust_type = (_py_type_to_rust(ast.unparse(arg.annotation))
                         if arg.annotation else "PyObject")
            params.append(f"{arg.arg}: {rust_type}")
        return params
    except Exception:  # nosec B110
        return [f"{p}: PyObject" for p in func.parameters if p != "self"]


def _translate_sketch_body(func: "FunctionRecord") -> List[str]:
    """Translate function body to Rust sketch lines."""
    try:
        tree = ast.parse(func.code)
        func_node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
            None,
        )
        if func_node is not None:
            return _translate_body(func_node.body, indent=1)
    except Exception:  # nosec B110
        pass
    return ["    // TODO: translate function body", "    todo!()"]


def _generate_rust_sketch(func: "FunctionRecord") -> str:
    """Generate a Rust function sketch from a Python FunctionRecord."""
    ret_rust = _py_type_to_rust(func.return_type or "")
    if not ret_rust.startswith("PyResult"):
        ret_rust = f"PyResult<{ret_rust}>"

    params_str = ", ".join(_parse_sketch_params(func))
    body_lines = _translate_sketch_body(func)

    lines = [
        "use pyo3::prelude::*;",
        "",
        "#[pyfunction]",
        f"fn {func.name}({params_str}) -> {ret_rust} {{",
        *body_lines,
        "}",
    ]
    return "\n".join(lines)


# ── Duplicate merge / unify helpers ─────────────────────────────────────────

def _extract_params_from_code(code: str) -> Optional[List[str]]:
    """Parse code and extract parameter list from the first function."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except Exception:  # nosec B110
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [
                f"{a.arg}{': ' + ast.unparse(a.annotation) if a.annotation else ''}"
                for a in node.args.args
            ]
    return None


def _extract_func_codes(
    funcs_data: List[Dict[str, Any]],
    code_map: Dict[str, str],
) -> tuple[List[str], List[str], List[List[str]]]:
    """Extract source code, names, and parameter sets from function data."""
    codes: List[str] = []
    names: List[str] = []
    params_sets: List[List[str]] = []
    for f in funcs_data:
        loc  = f"{f.get('file', '?')}:{f.get('line', '?')}"
        code = code_map.get(loc, code_map.get(f.get('key', ''), ''))
        if not code:
            continue
        codes.append(code)
        names.append(f.get('name', 'unknown'))
        params = _extract_params_from_code(code)
        if params is not None:
            params_sets.append(params)
    return codes, names, params_sets


def _unified_func_name(names: List[str]) -> str:
    """Derive a unified name from a common prefix of *names*."""
    prefix = names[0]
    for n in names[1:]:
        while not n.startswith(prefix) and prefix:
            prefix = prefix[:-1]
    return prefix.rstrip("_") if len(prefix) >= 3 else names[0]


def _merge_param_lists(params_sets: List[List[str]]) -> List[str]:
    """Union of all parameter sets, preserving order."""
    merged: List[str] = []
    seen: set = set()
    for pset in params_sets:
        for p in pset:
            name = p.split(":")[0].strip()
            if name not in seen:
                seen.add(name)
                merged.append(p)
    return merged


def _get_first_docstring(code: str) -> Optional[str]:
    """Get docstring from the first function/async function in code."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except Exception:  # nosec B110
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_docstring(node)
    return None


def _collect_docstrings(codes: List[str]) -> List[str]:
    """Gather unique docstrings from every code variant."""
    parts: List[str] = []
    for c in codes:
        ds = _get_first_docstring(c)
        if ds and ds not in parts:
            parts.append(ds)
    return parts


def _build_unified_header(
    funcs_data: List[Dict[str, Any]],
    names: List[str],
) -> List[str]:
    """Build the comment header for a unified function."""
    lines = [
        "# ══════════════════════════════════════════════════════",
        f"# UNIFIED from: {', '.join(names)}",
        "# Original locations:",
    ]
    for f in funcs_data:
        lines.append(f"#   - {f.get('file', '?')}:{f.get('line', '?')}")
    lines.extend(["# ══════════════════════════════════════════════════════", ""])
    return lines


def _build_unified_docstring(names: List[str], doc_parts: List[str]) -> List[str]:
    """Build the docstring block for a unified function."""
    if not doc_parts:
        return [f'    """Unified from {len(names)} duplicate functions."""']
    lines = ['    """', f"    Unified from {len(names)} duplicates.", ""]
    for dp in doc_parts:
        lines.extend(f"    {dl}" for dl in dp.strip().split("\n"))
    lines.append('    """')
    return lines


def _unparse_func_node(
    node: ast.FunctionDef,
    unified_name: str,
    all_params: List[str],
    names: List[str],
    doc_parts: List[str],
) -> List[str]:
    """Unparse a function AST node into unified source lines."""
    lines = []
    for d in node.decorator_list:
        lines.append(f"@{ast.unparse(d)}")
    kw  = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    lines.append(f"{kw} {unified_name}({', '.join(all_params)}){ret}:")
    lines.extend(_build_unified_docstring(names, doc_parts))
    body = node.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, (ast.Constant, ast.Str))):
        body = body[1:]
    for b_node in body:
        lines.extend(f"    {bl}" for bl in ast.unparse(b_node).split("\n"))
    return lines


def _generate_unified_function(
    funcs_data: List[Dict[str, Any]],
    code_map: Dict[str, str],
) -> str:
    """Generate a unified function from a group of duplicates."""
    codes, names, params_sets = _extract_func_codes(funcs_data, code_map)
    if not codes:
        return "# No source code available for merging"

    base_idx     = max(range(len(codes)), key=lambda i: len(codes[i]))
    base_code    = codes[base_idx]
    base_name    = names[base_idx]
    unified_name = _unified_func_name(names)
    all_params   = _merge_param_lists(params_sets)
    doc_parts    = _collect_docstrings(codes)

    lines = _build_unified_header(funcs_data, names)

    try:
        tree = ast.parse(textwrap.dedent(base_code))
        func_node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
            None,
        )
        if func_node is None:
            raise ValueError("No function node")
        lines.extend(
            _unparse_func_node(func_node, unified_name, all_params, names, doc_parts))
    except Exception:  # nosec B110
        lines.append(base_code.replace(base_name, unified_name, 1))

    return "\n".join(lines)


# ── Scan helpers ─────────────────────────────────────────────────────────────

def scan_codebase(
    root: Path,
    exclude: List[str],
    on_file: Optional[Callable] = None,
) -> tuple[List[FunctionRecord], List[ClassRecord], List[str], int]:
    """Parallel-scan the codebase, returning functions, classes, errors, count."""
    py_files = collect_py_files(root, exclude or None)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    done = 0
    total = len(py_files)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if on_file and total:
                on_file(done, total, str(futures[future]))

    return all_functions, all_classes, errors, len(py_files)


# Keep old name for backward compat
_scan_codebase = scan_codebase

# ── Scan context ─────────────────────────────────────────────────────────────

ScanContext = namedtuple("ScanContext", "root exclude thresholds functions classes")


# ── Phase runners ────────────────────────────────────────────────────────────

def run_phase_smells(ctx: ScanContext, results: Dict[str, Any]) -> None:
    """Run code-smell detection phase."""
    detector = CodeSmellDetector(thresholds=ctx.thresholds)
    smells = detector.detect(ctx.functions, ctx.classes)
    results["smells"]        = detector.summary()
    results["_smell_issues"] = smells


def run_phase_duplicates(ctx: ScanContext, results: Dict[str, Any]) -> None:
    """Run duplicate-detection phase."""
    finder = DuplicateFinder()
    finder.find(ctx.functions)
    results["duplicates"]  = finder.summary()
    results["_dup_groups"] = finder.groups


def run_phase_lint(ctx: ScanContext, results: Dict[str, Any]) -> None:
    """Run Ruff lint phase."""
    from Core.scan_phases import run_lint_phase
    linter, lint_issues = run_lint_phase(ctx.root, exclude=ctx.exclude or None)
    if linter is not None:
        results["lint"]         = linter.summary(lint_issues)
        results["_lint_issues"] = lint_issues
    else:
        results["lint"] = {"error": "Ruff not installed (pip install ruff)"}


def run_phase_security(ctx: ScanContext, results: Dict[str, Any]) -> None:
    """Run Bandit security phase."""
    from Core.scan_phases import run_security_phase
    sec, sec_issues = run_security_phase(ctx.root, exclude=ctx.exclude or None)
    if sec is not None:
        results["security"]    = sec.summary(sec_issues)
        results["_sec_issues"] = sec_issues
    else:
        results["security"] = {"error": "Bandit not installed (pip install bandit)"}


def run_phase_rustify(ctx: ScanContext, results: Dict[str, Any]) -> None:
    """Score functions for Rust transpilation."""
    advisor    = RustAdvisor()
    candidates = advisor.score(ctx.functions)
    results["rustify"] = {
        "total_scored": len(candidates),
        "pure_count":   sum(1 for c in candidates if c.is_pure),
        "top_score":    candidates[0].score if candidates else 0,
    }
    results["_rust_candidates"] = candidates


# Keep old names for backward compat (drop-in aliases)
_run_phase_smells     = run_phase_smells
_run_phase_duplicates = run_phase_duplicates
_run_phase_lint       = run_phase_lint
_run_phase_security   = run_phase_security
_run_phase_rustify    = run_phase_rustify


PHASE_RUNNERS: Dict[str, tuple[str, Callable]] = {
    "smells":     ("Detecting code smells",   run_phase_smells),
    "duplicates": ("Finding duplicates",       run_phase_duplicates),
    "lint":       ("Running Ruff lint",        run_phase_lint),
    "security":   ("Running Bandit security",  run_phase_security),
    "rustify":    ("Scoring Rust candidates",  run_phase_rustify),
}

# Backward-compat alias
_PHASE_RUNNERS = PHASE_RUNNERS


def run_scan(
    root: Path,
    modes: Dict[str, bool],
    exclude: List[str],
    thresholds: Dict[str, int],
    progress_cb: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Run selected scan phases and return results dict.

    *progress_cb(fraction, phase_label)* is called to report 0.0-1.0
    progress and the name of the current phase.

    v6.0.0: Lint and Security phases are run in a ThreadPoolExecutor
    concurrently with the AST-based analyses so their subprocess time does
    not add to the critical path.
    """
    results: Dict[str, Any] = {"meta": {}}
    t0 = time.time()

    need_ast = modes.get("smells") or modes.get("duplicates") or modes.get("rustify")
    io_phases  = [k for k in ("lint", "security") if modes.get(k)]  # subprocess-based
    ast_phases = [k for k in ("smells", "duplicates", "rustify") if modes.get(k)]
    active = io_phases + ast_phases
    n_phases = (1 if need_ast else 0) + len(active) + 1
    pw = 1.0 / max(n_phases, 1)
    pi = 0

    def _prog(label: str, sub: float = 1.0) -> None:
        if progress_cb:
            progress_cb(min((pi + sub) * pw, 1.0), label)

    functions: List[FunctionRecord] = []
    classes:   List[ClassRecord]    = []
    errors:    List[str]            = []
    file_count = 0

    if need_ast:
        _prog("Parsing source files", 0.0)
        functions, classes, errors, file_count = scan_codebase(
            root, exclude,
            on_file=lambda d, t, _p: _prog(f"Parsing {d}/{t}", d / t))
        _prog("AST parse complete")
        pi += 1

    results["meta"].update(
        files=file_count, functions=len(functions),
        classes=len(classes), errors=len(errors),
        error_list=errors[:20],
    )

    if need_ast:
        code_map: Dict[str, str] = {}
        for fn in functions:
            code_map[f"{fn.file_path}:{fn.line_start}"] = fn.code
            code_map[fn.key]                            = fn.code
        results["_code_map"]  = code_map
        results["_functions"] = functions

    ctx = ScanContext(root, exclude, thresholds, functions, classes)

    # ── parallel IO-bound phases (lint + security) ────────────────────────
    io_futures: Dict[str, concurrent.futures.Future] = {}
    if io_phases:
        _prog("Starting lint/security (parallel)", 0.0)
        _io_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(io_phases), 2))
        for key in io_phases:
            _label, runner = PHASE_RUNNERS[key]
            # We pass a local results dict per phase; merge after join
            _r: Dict[str, Any] = {}
            io_futures[key] = _io_executor.submit(runner, ctx, _r)
            # Keep a reference to the per-phase dict via the future
            io_futures[key]._phase_results = _r  # type: ignore[attr-defined]

    # ── AST-based phases (run while IO phases run) ────────────────────────
    for key in ast_phases:
        label, runner = PHASE_RUNNERS[key]
        _prog(label, 0.0)
        runner(ctx, results)
        _prog(f"{key.title()} done")
        pi += 1

    # ── join IO phases ────────────────────────────────────────────────────
    if io_futures:
        for key, fut in io_futures.items():
            try:
                fut.result(timeout=360)      # propagate exceptions
            except Exception:
                pass
            results.update(fut._phase_results)  # type: ignore[attr-defined]
            pi += 1
        _io_executor.shutdown(wait=False)

    results["grade"]          = compute_grade(results)
    results["meta"]["duration"] = round(time.time() - t0, 2)

    # ── flush the parse cache to disk (best effort) ───────────────────────
    try:
        from Analysis.scan_cache import get_cache
        get_cache().save()
    except Exception:
        pass

    return results


# Backward-compat alias used by x_ray_ui.py
_run_scan = run_scan
