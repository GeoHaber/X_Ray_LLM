#!/usr/bin/env python3
"""
x_ray_ui.py — Streamlit GUI for X-Ray Code Quality Scanner
============================================================

Launch with::

    python -m streamlit run x_ray_ui.py --server.port=8666

Provides a modern visual interface to:
  - Select a project directory
  - Choose scan modes (Smells, Duplicates, Lint, Security, Rustify)
  - Adjust detection thresholds
  - View results with grade card, category tabs, heatmap, and charts
  - Auto-fix lint issues with one click
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

# ── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="X-Ray Code Scanner",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports from X-Ray core ─────────────────────────────────────────────────
from Core.types import FunctionRecord, ClassRecord, SmellIssue
from Core.config import __version__, SMELL_THRESHOLDS
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.lint import LintAnalyzer
from Analysis.security import SecurityAnalyzer
from Analysis.reporting import _score_to_letter
from Analysis.rust_advisor import RustAdvisor

import concurrent.futures
import ast
import re
import textwrap


# ── Python → Rust transpiler (AST-based sketch) ─────────────────────────────

_PY_TO_RUST_TYPES = {
    "int": "i64", "float": "f64", "str": "String", "bool": "bool",
    "bytes": "Vec<u8>", "list": "Vec", "dict": "HashMap",
    "set": "HashSet", "tuple": "tuple", "None": "()",
    "Optional": "Option", "List": "Vec", "Dict": "HashMap",
    "Set": "HashSet", "Tuple": "tuple", "Any": "PyObject",
}


def _py_type_to_rust(py_type: str) -> str:
    """Best-effort Python type annotation → Rust type."""
    if not py_type:
        return "PyResult<PyObject>"
    py_type = py_type.strip()
    # Handle Optional[X]
    m = re.match(r"Optional\[(.+)\]", py_type)
    if m:
        inner = _py_type_to_rust(m.group(1))
        return f"Option<{inner}>"
    # Handle List[X], Set[X]
    m = re.match(r"(List|Set)\[(.+)\]", py_type)
    if m:
        container = "Vec" if m.group(1) == "List" else "HashSet"
        inner = _py_type_to_rust(m.group(2))
        return f"{container}<{inner}>"
    # Handle Dict[K, V]
    m = re.match(r"Dict\[(.+),\s*(.+)\]", py_type)
    if m:
        k = _py_type_to_rust(m.group(1))
        v = _py_type_to_rust(m.group(2))
        return f"HashMap<{k}, {v}>"
    # Handle Tuple[X, Y, ...]
    m = re.match(r"Tuple\[(.+)\]", py_type)
    if m:
        parts = [_py_type_to_rust(p.strip()) for p in m.group(1).split(",")]
        return f"({', '.join(parts)})"
    return _PY_TO_RUST_TYPES.get(py_type, "PyObject")


def _generate_rust_sketch(func: "FunctionRecord") -> str:
    """Generate a Rust function sketch from a Python FunctionRecord."""
    lines = []
    # Imports hint
    lines.append("use pyo3::prelude::*;")
    lines.append("")

    # Parse return type
    ret_rust = _py_type_to_rust(func.return_type or "")
    if not ret_rust.startswith("PyResult"):
        ret_rust = f"PyResult<{ret_rust}>"

    # Parse parameters
    rust_params = []
    try:
        tree = ast.parse(func.code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    name = arg.arg
                    if name == "self":
                        continue
                    if arg.annotation:
                        ann = ast.unparse(arg.annotation)
                        rust_type = _py_type_to_rust(ann)
                    else:
                        rust_type = "PyObject"
                    rust_params.append(f"{name}: {rust_type}")
                break
    except Exception:
        for p in func.parameters:
            if p != "self":
                rust_params.append(f"{p}: PyObject")

    params_str = ", ".join(rust_params)

    # Function signature
    lines.append("#[pyfunction]")
    lines.append(f"fn {func.name}({params_str}) -> {ret_rust} {{")

    # Body sketch — translate simple constructs
    try:
        tree = ast.parse(func.code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lines = _translate_body(node.body, indent=1)
                lines.extend(body_lines)
                break
    except Exception:
        lines.append("    // TODO: translate function body")
        lines.append("    todo!()")

    lines.append("}")
    return "\n".join(lines)


def _translate_body(stmts: list, indent: int = 1) -> List[str]:
    """Best-effort AST → Rust body translation."""
    pad = "    " * indent
    lines = []
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            if stmt.value:
                val = ast.unparse(stmt.value)
                val = _rustify_expr(val)
                lines.append(f"{pad}Ok({val})")
            else:
                lines.append(f"{pad}Ok(())")
        elif isinstance(stmt, ast.If):
            test = _rustify_expr(ast.unparse(stmt.test))
            lines.append(f"{pad}if {test} {{")
            lines.extend(_translate_body(stmt.body, indent + 1))
            if stmt.orelse:
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    lines.append(f"{pad}}} else ")
                    inner = _translate_body(stmt.orelse, indent)
                    if inner:
                        inner[0] = inner[0].lstrip()
                        lines[-1] += inner[0]
                        lines.extend(inner[1:])
                else:
                    lines.append(f"{pad}}} else {{")
                    lines.extend(_translate_body(stmt.orelse, indent + 1))
                    lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.For):
            target = ast.unparse(stmt.target)
            iter_expr = _rustify_expr(ast.unparse(stmt.iter))
            lines.append(f"{pad}for {target} in {iter_expr} {{")
            lines.extend(_translate_body(stmt.body, indent + 1))
            lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.While):
            test = _rustify_expr(ast.unparse(stmt.test))
            lines.append(f"{pad}while {test} {{")
            lines.extend(_translate_body(stmt.body, indent + 1))
            lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.Assign):
            targets = ast.unparse(stmt.targets[0])
            value = _rustify_expr(ast.unparse(stmt.value))
            lines.append(f"{pad}let mut {targets} = {value};")
        elif isinstance(stmt, ast.AugAssign):
            target = ast.unparse(stmt.target)
            op = _rust_op(stmt.op)
            value = _rustify_expr(ast.unparse(stmt.value))
            lines.append(f"{pad}{target} {op}= {value};")
        elif isinstance(stmt, ast.Expr):
            expr = _rustify_expr(ast.unparse(stmt.value))
            lines.append(f"{pad}{expr};")
        else:
            # Fallback: comment out the Python line
            try:
                py_line = ast.unparse(stmt).split("\n")[0]
            except Exception:
                py_line = "..."
            lines.append(f"{pad}// TODO: {py_line}")
    return lines


def _rustify_expr(expr: str) -> str:
    """Quick Python expression → Rust expression mappings."""
    expr = expr.replace("True", "true").replace("False", "false")
    expr = expr.replace("None", "None")
    expr = expr.replace(" and ", " && ").replace(" or ", " || ")
    expr = expr.replace("not ", "!")
    expr = expr.replace("len(", ".len(")
    expr = expr.replace(".append(", ".push(")
    expr = expr.replace("elif", "else if")
    expr = re.sub(r'f"([^"]+)"', r'format!("\1")', expr)
    expr = re.sub(r"f'([^']+)'", r'format!("\1")', expr)
    return expr


def _rust_op(op) -> str:
    """Map Python AST operator to Rust symbol."""
    return {
        ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
        ast.Mod: "%", ast.Pow: "**", ast.BitOr: "|", ast.BitAnd: "&",
        ast.BitXor: "^", ast.LShift: "<<", ast.RShift: ">>",
    }.get(type(op), "+")


# ── Duplicate merge / unify helper ───────────────────────────────────────────

def _generate_unified_function(funcs_data: List[Dict[str, Any]],
                               code_map: Dict[str, str]) -> str:
    """Generate a unified function from a group of duplicates."""
    codes = []
    names = []
    params_sets = []

    for f in funcs_data:
        loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
        code = code_map.get(loc, code_map.get(f.get('key', ''), ''))
        if code:
            codes.append(code)
            names.append(f.get('name', 'unknown'))
            # Extract parameters from the code
            try:
                tree = ast.parse(textwrap.dedent(code))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        params = []
                        for arg in node.args.args:
                            ann = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
                            params.append(f"{arg.arg}{ann}")
                        params_sets.append(params)
                        break
            except Exception:
                pass

    if not codes:
        return "# No source code available for merging"

    # Pick the longest version as the base (most complete)
    base_idx = max(range(len(codes)), key=lambda i: len(codes[i]))
    base_code = codes[base_idx]
    base_name = names[base_idx]

    # Build a unified name
    common_prefix = names[0]
    for n in names[1:]:
        while not n.startswith(common_prefix) and common_prefix:
            common_prefix = common_prefix[:-1]
    if len(common_prefix) >= 3:
        unified_name = common_prefix.rstrip("_")
    else:
        unified_name = base_name

    # Merge parameter lists (union of all params)
    all_params = []
    seen_params = set()
    for pset in params_sets:
        for p in pset:
            param_name = p.split(":")[0].strip()
            if param_name not in seen_params:
                seen_params.add(param_name)
                all_params.append(p)

    # Build the unified function
    lines = [
        f"# ══════════════════════════════════════════════════════",
        f"# UNIFIED from: {', '.join(names)}",
        f"# Original locations:",
    ]
    for f in funcs_data:
        lines.append(f"#   - {f.get('file', '?')}:{f.get('line', '?')}")
    lines.append(f"# ══════════════════════════════════════════════════════")
    lines.append("")

    # Re-parse the base to rebuild with unified name
    try:
        tree = ast.parse(textwrap.dedent(base_code))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Get decorators
                decos = []
                for d in node.decorator_list:
                    decos.append(f"@{ast.unparse(d)}")
                for d in decos:
                    lines.append(d)

                # Build signature
                is_async = isinstance(node, ast.AsyncFunctionDef)
                prefix = "async def" if is_async else "def"
                params_str = ", ".join(all_params)
                ret = ""
                if node.returns:
                    ret = f" -> {ast.unparse(node.returns)}"
                lines.append(f"{prefix} {unified_name}({params_str}){ret}:")

                # Docstring — combine all
                doc_parts = []
                for i, c in enumerate(codes):
                    try:
                        t = ast.parse(textwrap.dedent(c))
                        for n2 in ast.walk(t):
                            if isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                ds = ast.get_docstring(n2)
                                if ds and ds not in doc_parts:
                                    doc_parts.append(ds)
                                break
                    except Exception:
                        pass
                if doc_parts:
                    lines.append('    """')
                    lines.append(f"    Unified from {len(names)} duplicates.")
                    lines.append("")
                    for dp in doc_parts:
                        for dl in dp.strip().split("\n"):
                            lines.append(f"    {dl}")
                    lines.append('    """')
                else:
                    lines.append(f'    """Unified from {len(names)} duplicate functions."""')

                # Body from base (skip the original docstring)
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, (ast.Constant, ast.Str))):
                    body = body[1:]  # skip docstring node
                for b_node in body:
                    for bline in ast.unparse(b_node).split("\n"):
                        lines.append(f"    {bline}")
                break
    except Exception:
        # Fallback: just rename
        lines.append(base_code.replace(base_name, unified_name, 1))

    return "\n".join(lines)


# ── Modern CSS injection ────────────────────────────────────────────────────

_CUSTOM_CSS = """
<style>
/* ── Global overrides ─────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600;700&display=swap');

:root {
    --accent:  #00d4ff;
    --accent2: #7c4dff;
    --bg-card: rgba(17, 25, 40, 0.75);
    --border:  rgba(255,255,255,0.08);
}

/* Main container */
.stApp {
    font-family: 'Inter', sans-serif;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .stMarkdown h1,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3 {
    color: var(--accent) !important;
    font-family: 'JetBrains Mono', monospace;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: var(--bg-card);
    backdrop-filter: blur(16px);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 16px;
    transition: transform 0.2s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    border-color: var(--accent);
}

/* Tab styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--bg-card);
    border-radius: 12px;
    padding: 4px;
    border: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #00d4ff22, #7c4dff22) !important;
    border: 1px solid var(--accent) !important;
}

/* Expander styling */
.streamlit-expanderHeader {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    border-radius: 8px;
}

/* Code blocks */
code, .stCode {
    font-family: 'JetBrains Mono', monospace !important;
}

/* Buttons */
.stButton > button {
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 212, 255, 0.3);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #00d4ff, #7c4dff) !important;
    border: none !important;
    color: white !important;
}

/* Download buttons */
.stDownloadButton > button {
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
}

/* Progress bars and sliders */
.stSlider [data-baseweb="slider"] [role="slider"] {
    background: var(--accent) !important;
}

/* Dividers */
hr {
    border-color: var(--border) !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(0,212,255,0.3);
    border-radius: 3px;
}

/* Hide deploy button */
.stDeployButton, [data-testid="stToolbar"] { display: none !important; }
</style>
"""

# ── Grade colours ────────────────────────────────────────────────────────────

_GRADE_COLORS = {
    "A+": "#00c853", "A": "#00c853", "A-": "#00e676",
    "B+": "#64dd17", "B": "#aeea00", "B-": "#ffd600",
    "C+": "#ffab00", "C": "#ff6d00", "C-": "#ff3d00",
    "D+": "#dd2c00", "D": "#d50000", "D-": "#b71c1c",
    "F": "#880e4f",
}


# ── Scan helpers ─────────────────────────────────────────────────────────────

def _scan_codebase(root: Path, exclude: List[str]) -> tuple:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude or None)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []

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

    return all_functions, all_classes, errors, len(py_files)


def _run_scan(root: Path, modes: Dict[str, bool],
              exclude: List[str],
              thresholds: Dict[str, int]) -> Dict[str, Any]:
    """Run selected scan phases and return results dict."""
    results: Dict[str, Any] = {"meta": {}}
    t0 = time.time()

    need_ast = modes.get("smells") or modes.get("duplicates") or modes.get("rustify")
    functions, classes, errors = [], [], []
    file_count = 0

    if need_ast:
        functions, classes, errors, file_count = _scan_codebase(root, exclude)

    results["meta"]["files"] = file_count
    results["meta"]["functions"] = len(functions)
    results["meta"]["classes"] = len(classes)
    results["meta"]["errors"] = len(errors)
    results["meta"]["error_list"] = errors[:20]

    # Build code lookup once (shared by smells, duplicates, rustify)
    if need_ast:
        code_map: Dict[str, str] = {}
        for fn in functions:
            code_map[f"{fn.file_path}:{fn.line_start}"] = fn.code
            code_map[fn.key] = fn.code
        results["_code_map"] = code_map
        results["_functions"] = functions

    # ── Smells ──
    if modes.get("smells"):
        detector = CodeSmellDetector(thresholds=thresholds)
        smells = detector.detect(functions, classes)
        summary = detector.summary()
        results["smells"] = summary
        results["_smell_issues"] = smells

    # ── Duplicates ──
    if modes.get("duplicates"):
        finder = DuplicateFinder()
        finder.find(functions)
        summary = finder.summary()
        results["duplicates"] = summary
        results["_dup_groups"] = finder.groups

    # ── Lint ──
    if modes.get("lint"):
        linter = LintAnalyzer()
        if linter.available:
            lint_issues = linter.analyze(root, exclude=exclude or None)
            summary = linter.summary(lint_issues)
            results["lint"] = summary
            results["_lint_issues"] = lint_issues
        else:
            results["lint"] = {"error": "Ruff not installed (pip install ruff)"}

    # ── Security ──
    if modes.get("security"):
        sec = SecurityAnalyzer()
        if sec.available:
            sec_issues = sec.analyze(root, exclude=exclude or None)
            summary = sec.summary(sec_issues)
            results["security"] = summary
            results["_sec_issues"] = sec_issues
        else:
            results["security"] = {"error": "Bandit not installed (pip install bandit)"}

    # ── Rustify ──
    if modes.get("rustify"):
        advisor = RustAdvisor()
        candidates = advisor.score(functions)
        results["rustify"] = {
            "total_scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "top_score": candidates[0].score if candidates else 0,
        }
        results["_rust_candidates"] = candidates

    # ── Grade (reuse reporting logic) ──
    grade_data = {}
    score = 100.0
    from Analysis.reporting import _calc_category_penalty, _PENALTY_RULES
    tools_run = []
    breakdown = {}
    for key, tool_label, _w, _c, _e in _PENALTY_RULES:
        if key not in results:
            continue
        tools_run.append(tool_label)
        penalty, detail = _calc_category_penalty(results[key], key)
        if detail is not None:
            score -= penalty
            breakdown[key] = detail
    score = max(0, round(score, 1))
    letter = _score_to_letter(score)
    grade_data = {
        "score": score, "letter": letter,
        "breakdown": breakdown, "tools_run": tools_run,
    }
    results["grade"] = grade_data

    results["meta"]["duration"] = round(time.time() - t0, 2)
    return results


# ── UI Components ────────────────────────────────────────────────────────────

def _render_grade_card(grade: Dict[str, Any]):
    """Render the big grade card at the top with a modern glassmorphism look."""
    score = grade["score"]
    letter = grade["letter"]
    color = _GRADE_COLORS.get(letter, "#888")
    glow_size = max(10, int(score / 3))

    st.markdown(f"""
    <div style="
        text-align: center;
        padding: 2rem 1.5rem;
        border-radius: 16px;
        background: linear-gradient(135deg, {color}15, {color}30);
        border: 1px solid {color}66;
        box-shadow: 0 0 {glow_size}px {color}33, inset 0 1px 0 rgba(255,255,255,0.05);
        backdrop-filter: blur(12px);
        position: relative;
        overflow: hidden;
    ">
        <div style="
            position: absolute; top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: radial-gradient(circle at 50% 50%, {color}08, transparent 70%);
        "></div>
        <p style="
            font-family: 'JetBrains Mono', monospace;
            font-size: 5rem; font-weight: 700;
            margin: 0; color: {color};
            text-shadow: 0 0 40px {color}66;
            position: relative;
        ">{letter}</p>
        <p style="
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.6rem; font-weight: 600;
            margin: 0.2rem 0; color: {color}cc;
            position: relative;
        ">{score} / 100</p>
        <p style="
            margin: 0; opacity: 0.5; font-size: 0.8rem;
            text-transform: uppercase; letter-spacing: 2px;
            position: relative;
        ">Combined Quality Score</p>
    </div>
    """, unsafe_allow_html=True)


def _render_stats_bar(meta: Dict[str, Any]):
    """Render the quick stats row with techy styling."""
    items = [
        ("📄", "Files", meta.get("files", 0)),
        ("⚡", "Functions", meta.get("functions", 0)),
        ("📦", "Classes", meta.get("classes", 0)),
        ("⏱️", "Duration", f"{meta.get('duration', 0):.1f}s"),
    ]
    cols = st.columns(len(items))
    for col, (icon, label, value) in zip(cols, items):
        with col:
            st.markdown(f"""
            <div style="
                text-align: center; padding: 12px;
                border-radius: 12px;
                background: rgba(17,25,40,0.6);
                border: 1px solid rgba(255,255,255,0.06);
            ">
                <p style="font-size: 1.8rem; margin: 0;">{icon}</p>
                <p style="font-family: 'JetBrains Mono', monospace;
                          font-size: 1.3rem; font-weight: 700;
                          margin: 0; color: #00d4ff;">{value}</p>
                <p style="font-size: 0.75rem; margin: 0; opacity: 0.5;
                          text-transform: uppercase; letter-spacing: 1px;">{label}</p>
            </div>
            """, unsafe_allow_html=True)


def _render_penalty_bar(breakdown: Dict[str, Any]):
    """Render a horizontal breakdown of penalties with modern styling."""
    if not breakdown:
        return
    cols = st.columns(len(breakdown))
    labels = {"smells": "🔍 Smells", "duplicates": "📋 Duplicates",
              "lint": "🧹 Lint", "security": "🔒 Security"}
    for col, (key, detail) in zip(cols, breakdown.items()):
        penalty = detail.get("penalty", 0)
        with col:
            st.metric(labels.get(key, key), f"-{penalty:.1f} pts")
            extra = {k: v for k, v in detail.items() if k != "penalty"}
            st.caption(", ".join(f"{k}={v}" for k, v in extra.items()))


def _render_smells_tab(results: Dict[str, Any]):
    """Render the Smells tab."""
    summary = results.get("smells", {})
    issues: List[SmellIssue] = results.get("_smell_issues", [])

    if not issues:
        st.success("No code smells detected! 🎉")
        return

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", summary.get("total", 0))
    c2.metric("🔴 Critical", summary.get("critical", 0))
    c3.metric("🟡 Warning", summary.get("warning", 0))
    c4.metric("🟢 Info", summary.get("info", 0))

    # Category breakdown with visual bars
    by_cat = summary.get("by_category", {})
    if by_cat:
        st.subheader("By Category")
        cat_data = sorted(by_cat.items(), key=lambda x: -x[1])
        for cat, count in cat_data:
            max_count = cat_data[0][1] if cat_data else 1
            pct = int(count / max(max_count, 1) * 100)
            st.markdown(f"""
            <div style="display:flex; align-items:center; gap:10px; margin:4px 0;">
                <span style="min-width:180px; font-family:'JetBrains Mono',monospace;
                             font-size:0.8rem;">{cat}</span>
                <div style="flex:1; background:rgba(255,255,255,0.06);
                            border-radius:4px; height:20px; overflow:hidden;">
                    <div style="width:{pct}%; height:100%;
                                background:linear-gradient(90deg,#ff6b6b,#ffa06b);
                                border-radius:4px; transition:width 0.3s;"></div>
                </div>
                <span style="font-family:'JetBrains Mono',monospace;
                             font-weight:700; min-width:30px;">{count}</span>
            </div>
            """, unsafe_allow_html=True)

    # Worst files
    worst = summary.get("worst_files", {})
    if worst:
        st.subheader("Worst Files")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            st.write(f"`{f}` — {count} issues")

    # Issue list (expandable)
    st.subheader("All Issues")
    sev_filter = st.selectbox("Filter by severity",
                              ["all", "critical", "warning", "info"],
                              key="smell_filter")
    filtered = (issues if sev_filter == "all"
                else [i for i in issues if i.severity == sev_filter])
    filtered.sort(key=lambda s: (
        0 if s.severity == "critical" else 1 if s.severity == "warning" else 2,
        s.file_path, s.line))

    code_map = results.get("_code_map", {})

    for s in filtered[:100]:
        icon = {"critical": "🔴", "warning": "🟡",
                "info": "🟢"}.get(s.severity, "❓")
        with st.expander(
            f"{icon} [{s.category}] {s.name} — {s.file_path}:{s.line}"
        ):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")
            if s.llm_analysis:
                st.info(f"**AI Tip:** {s.llm_analysis}")
            st.caption(f"Severity: {s.severity} | Metric: {s.metric_value}")
            code = code_map.get(f"{s.file_path}:{s.line}", "")
            if code:
                st.code(code, language="python")

    if len(filtered) > 100:
        st.warning(f"Showing first 100 of {len(filtered)} issues.")


def _render_duplicates_tab(results: Dict[str, Any]):
    """Render the Duplicates tab."""
    summary = results.get("duplicates", {})
    groups = results.get("_dup_groups", [])

    if not groups:
        st.success("No significant duplication found! 🎉")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Groups", summary.get("total_groups", 0))
    c2.metric("Exact", summary.get("exact_duplicates", 0))
    c3.metric("Near", summary.get("near_duplicates", 0))
    c4.metric("Semantic", summary.get("semantic_duplicates", 0))

    st.metric("Functions Involved", summary.get("total_functions_involved", 0))

    # Type filter
    type_filter = st.selectbox(
        "Filter by type",
        ["all", "exact", "near", "structural", "semantic"],
        key="dup_filter",
    )
    filtered = (groups if type_filter == "all"
                else [g for g in groups if g.similarity_type == type_filter])

    code_map = results.get("_code_map", {})

    for g in filtered[:50]:
        sim_pct = f"{g.avg_similarity:.0%}"
        func_names = ", ".join(f.get("name", "?") for f in g.functions)
        with st.expander(
            f"Group {g.group_id} — {g.similarity_type} ({sim_pct}) — "
            f"{func_names}"
        ):
            if g.merge_suggestion:
                st.info(f"**Merge suggestion:** {g.merge_suggestion}")

            funcs = g.functions

            # ── Original code side-by-side ──
            st.markdown("##### 📄 Original Functions")
            if len(funcs) >= 2:
                cols = st.columns(min(len(funcs), 2))
                for i, f in enumerate(funcs[:2]):
                    loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
                    code = code_map.get(
                        loc, code_map.get(f.get('key', ''), ''))
                    with cols[i]:
                        st.caption(f"📄 {loc}")
                        st.markdown(
                            f"**{f.get('name', '?')}** "
                            f"({f.get('size', '?')} lines, "
                            f"sim: {f.get('similarity', 0):.0%})")
                        if code:
                            st.code(code, language="python")
                        else:
                            st.warning("Source not available")
                for f in funcs[2:]:
                    loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
                    code = code_map.get(
                        loc, code_map.get(f.get('key', ''), ''))
                    st.caption(f"📄 {loc} — **{f.get('name', '?')}**")
                    if code:
                        st.code(code, language="python")
            else:
                for f in funcs:
                    loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
                    code = code_map.get(
                        loc, code_map.get(f.get('key', ''), ''))
                    st.caption(f"📄 {loc} — **{f.get('name', '?')}**")
                    if code:
                        st.code(code, language="python")

            # ── Unified / merged function preview ──
            if len(funcs) >= 2:
                st.markdown("---")
                st.markdown("##### 🔗 Unified Function (auto-generated)")
                st.caption(
                    "This is a suggested merged version. "
                    "Review parameters, logic branches, and naming "
                    "before applying.")
                unified = _generate_unified_function(funcs, code_map)
                st.code(unified, language="python")

    if len(filtered) > 50:
        st.warning(f"Showing first 50 of {len(filtered)} groups.")


def _render_lint_tab(results: Dict[str, Any]):
    """Render the Lint tab with auto-fix button."""
    summary = results.get("lint", {})
    issues: List[SmellIssue] = results.get("_lint_issues", [])

    if summary.get("error"):
        st.error(summary["error"])
        return

    if not issues:
        st.success("No lint issues found! 🎉")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", summary.get("total", 0))
    c2.metric("🔴 Critical", summary.get("critical", 0))
    c3.metric("🟡 Warning", summary.get("warning", 0))
    c4.metric("🔧 Auto-fixable", summary.get("fixable", 0))

    # ── Auto-fix button ──
    fixable_count = summary.get("fixable", 0)
    if fixable_count > 0:
        st.markdown("---")
        fix_col1, fix_col2 = st.columns([1, 3])
        with fix_col1:
            do_fix = st.button(
                "🔧 Auto-Fix All", type="primary",
                use_container_width=True,
                help=f"Run ruff --fix on {fixable_count} auto-fixable issues")
        with fix_col2:
            st.caption(
                f"⚡ {fixable_count} issues can be automatically fixed by Ruff.")
            st.caption("⚠️ This modifies files in-place. Commit your work first!")

        if do_fix:
            scan_path = st.session_state.get("scan_path", "")
            if scan_path:
                with st.spinner("🔧 Running ruff --fix ..."):
                    try:
                        result = subprocess.run(
                            ["ruff", "check", "--fix", str(scan_path)],
                            capture_output=True, text=True, timeout=60,
                        )
                        if result.returncode == 0:
                            st.success(
                                "✅ Auto-fix complete! Re-run scan to see "
                                "updated results.")
                        else:
                            st.success(
                                f"✅ Fixes applied. {result.stdout.strip()}")
                        if result.stderr.strip():
                            with st.expander("Ruff output"):
                                st.code(result.stderr)
                    except FileNotFoundError:
                        st.error(
                            "Ruff not found. Install with: `pip install ruff`")
                    except subprocess.TimeoutExpired:
                        st.error("Ruff timed out after 60 seconds.")
        st.markdown("---")

    # Top rules with visual bars
    by_rule = summary.get("by_rule", {})
    if by_rule:
        st.subheader("Top Rules")
        top_rules = sorted(by_rule.items(), key=lambda x: -x[1])[:10]
        for rule, count in top_rules:
            max_count = top_rules[0][1] if top_rules else 1
            pct = int(count / max(max_count, 1) * 100)
            st.markdown(f"""
            <div style="display:flex; align-items:center; gap:10px; margin:4px 0;">
                <span style="min-width:120px; font-family:'JetBrains Mono',monospace;
                             font-size:0.82rem; color:#ffa06b;">{rule}</span>
                <div style="flex:1; background:rgba(255,255,255,0.06);
                            border-radius:4px; height:18px; overflow:hidden;">
                    <div style="width:{pct}%; height:100%;
                                background:linear-gradient(90deg,#ff9800,#ff5722);
                                border-radius:4px;"></div>
                </div>
                <span style="font-family:'JetBrains Mono',monospace;
                             font-weight:700; min-width:30px;">{count}</span>
            </div>
            """, unsafe_allow_html=True)

    # Worst files
    worst = summary.get("worst_files", {})
    if worst:
        st.subheader("Worst Files")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            st.write(f"`{f}` — {count} issues")

    # Issue list
    st.subheader("All Issues")
    for s in issues[:100]:
        icon = {"critical": "🔴", "warning": "🟡",
                "info": "🟢"}.get(s.severity, "❓")
        fix_tag = " 🔧" if s.fixable else ""
        with st.expander(
            f"{icon} [{s.rule_code}] {s.file_path}:{s.line}{fix_tag}"
        ):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")

    if len(issues) > 100:
        st.warning(f"Showing first 100 of {len(issues)} issues.")


def _render_security_tab(results: Dict[str, Any]):
    """Render the Security tab."""
    summary = results.get("security", {})
    issues: List[SmellIssue] = results.get("_sec_issues", [])

    if summary.get("error"):
        st.error(summary["error"])
        return

    if not issues:
        st.success("No security issues found! 🎉")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Total", summary.get("total", 0))
    c2.metric("🔴 High", summary.get("critical", 0))
    c3.metric("🟡 Medium", summary.get("warning", 0))

    # By rule
    by_rule = summary.get("by_rule", {})
    if by_rule:
        st.subheader("Issue Types")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
            st.write(f"**{rule}**: {count}")

    # Confidence
    by_conf = summary.get("by_confidence", {})
    if by_conf:
        st.subheader("By Confidence")
        for conf, count in by_conf.items():
            st.write(f"**{conf}**: {count}")

    # Issue list
    st.subheader("All Issues")
    sev_filter = st.selectbox(
        "Filter by severity", ["all", "critical", "warning", "info"],
        key="sec_filter")
    filtered = (issues if sev_filter == "all"
                else [i for i in issues if i.severity == sev_filter])

    for s in filtered[:100]:
        icon = {"critical": "🔴", "warning": "🟡",
                "info": "🟢"}.get(s.severity, "❓")
        with st.expander(
            f"{icon} [{s.rule_code}] {s.file_path}:{s.line}"
        ):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")
            if s.confidence:
                st.caption(f"Confidence: {s.confidence}")

    if len(filtered) > 100:
        st.warning(f"Showing first 100 of {len(filtered)} issues.")


def _render_rustify_tab(results: Dict[str, Any]):
    """Render the Rustify analysis tab — best Rust porting candidates."""
    candidates = results.get("_rust_candidates", [])
    rustify_summary = results.get("rustify", {})
    code_map = results.get("_code_map", {})

    if not candidates:
        st.info(
            "No functions scored. Make sure the codebase has functions "
            "with 5+ lines.")
        return

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🦀 Scored", rustify_summary.get("total_scored", 0))
    c2.metric("✅ Pure", rustify_summary.get("pure_count", 0))
    c3.metric("🏆 Top Score", rustify_summary.get("top_score", 0))
    impure = (rustify_summary.get("total_scored", 0)
              - rustify_summary.get("pure_count", 0))
    c4.metric("⚠️ Impure", impure)

    st.markdown("---")

    # Top candidates
    st.subheader("🏆 Top Rust Candidates")
    st.caption(
        "Higher score = better candidate for Rust porting. "
        "Pure functions with high complexity score best.")

    show_n = st.slider(
        "Show top N candidates", 5, min(50, len(candidates)),
        min(15, len(candidates)), key="rustify_top_n")

    for rank, cand in enumerate(candidates[:show_n], 1):
        fn = cand.func
        purity_badge = "🟢 Pure" if cand.is_pure else "🔴 Impure"
        score_color = ("#00c853" if cand.score >= 20
                       else "#ffd600" if cand.score >= 10 else "#ff5722")

        with st.expander(
            f"#{rank}  ⟫  **{fn.name}**  —  Score: {cand.score}  |  "
            f"{purity_badge}  |  CC={fn.complexity}  |  {fn.size_lines} lines"
        ):
            info_cols = st.columns(5)
            info_cols[0].markdown("**Score**")
            info_cols[0].markdown(
                f"<span style='font-family:JetBrains Mono,monospace; "
                f"font-size:1.4rem; color:{score_color}; "
                f"font-weight:700;'>{cand.score}</span>",
                unsafe_allow_html=True)
            info_cols[1].markdown(f"**Purity**\n\n{purity_badge}")
            info_cols[2].markdown(f"**Complexity**\n\n`CC = {fn.complexity}`")
            info_cols[3].markdown(f"**Size**\n\n`{fn.size_lines} lines`")
            info_cols[4].markdown(
                f"**Deps**\n\n`{cand.external_deps} external`")

            if cand.reason:
                st.caption(f"💡 Reason: {cand.reason}")
            st.markdown(f"📄 `{fn.file_path}:{fn.line_start}`")

            code = code_map.get(
                f"{fn.file_path}:{fn.line_start}",
                code_map.get(fn.key, ""))
            if code:
                # Side-by-side: Python original → Rust sketch
                py_col, rs_col = st.columns(2)
                with py_col:
                    st.markdown("**🐍 Python (original)**")
                    st.code(code, language="python")
                with rs_col:
                    st.markdown("**🦀 Rust (auto-sketch)**")
                    rust_code = _generate_rust_sketch(fn)
                    st.code(rust_code, language="rust")
                st.caption(
                    "⚠️ This is an auto-generated sketch — "
                    "review and adjust types, error handling, "
                    "and unsafe blocks before use.")

    # Score distribution
    st.markdown("---")
    st.subheader("📊 Score Distribution")
    buckets = {"0-5": 0, "5-10": 0, "10-15": 0,
               "15-20": 0, "20-25": 0, "25+": 0}
    for c in candidates:
        if c.score >= 25:
            buckets["25+"] += 1
        elif c.score >= 20:
            buckets["20-25"] += 1
        elif c.score >= 15:
            buckets["15-20"] += 1
        elif c.score >= 10:
            buckets["10-15"] += 1
        elif c.score >= 5:
            buckets["5-10"] += 1
        else:
            buckets["0-5"] += 1

    max_b = max(buckets.values()) if buckets.values() else 1
    for label, count in buckets.items():
        pct = int(count / max(max_b, 1) * 100)
        bar_color = ("#00c853" if "25" in label or "20" in label
                     else "#ffd600" if "15" in label or "10" in label
                     else "#ff5722")
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:10px; margin:3px 0;">
            <span style="min-width:60px; font-family:'JetBrains Mono',monospace;
                         font-size:0.8rem; color:#888;">{label}</span>
            <div style="flex:1; background:rgba(255,255,255,0.06);
                        border-radius:4px; height:20px; overflow:hidden;">
                <div style="width:{pct}%; height:100%; background:{bar_color};
                            border-radius:4px; transition:width 0.3s;"></div>
            </div>
            <span style="font-family:'JetBrains Mono',monospace;
                         font-weight:700; min-width:30px; font-size:0.85rem;">
                {count}</span>
        </div>
        """, unsafe_allow_html=True)


def _render_heatmap_tab(results: Dict[str, Any]):
    """Render a file heatmap aggregating all issues across analyzers."""
    file_issues: Counter = Counter()
    file_detail: Dict[str, Counter] = {}

    # Aggregate smells
    for s in results.get("_smell_issues", []):
        file_issues[s.file_path] += 1
        file_detail.setdefault(s.file_path, Counter())
        file_detail[s.file_path]["smells"] += 1

    # Aggregate lint
    for s in results.get("_lint_issues", []):
        file_issues[s.file_path] += 1
        file_detail.setdefault(s.file_path, Counter())
        file_detail[s.file_path]["lint"] += 1

    # Aggregate security
    for s in results.get("_sec_issues", []):
        file_issues[s.file_path] += 1
        file_detail.setdefault(s.file_path, Counter())
        file_detail[s.file_path]["security"] += 1

    if not file_issues:
        st.success("No issues to visualize! 🎉")
        return

    ranked = file_issues.most_common(30)
    max_issues = ranked[0][1] if ranked else 1

    st.subheader("🔥 Issue Heatmap — Worst Files")
    st.caption(
        "Aggregated across all enabled analyzers. "
        "Longer bar = more issues.")

    for file_path, total in ranked:
        pct = int(total / max(max_issues, 1) * 100)
        detail = file_detail.get(file_path, {})

        if pct > 75:
            bar_color = "linear-gradient(90deg, #ff1744, #d50000)"
        elif pct > 50:
            bar_color = "linear-gradient(90deg, #ff9100, #ff6d00)"
        elif pct > 25:
            bar_color = "linear-gradient(90deg, #ffd600, #ffab00)"
        else:
            bar_color = "linear-gradient(90deg, #00e676, #00c853)"

        tags = []
        cat_colors = {"smells": "#ff6b6b", "lint": "#ffa06b",
                      "security": "#ff4081"}
        for cat, count in sorted(detail.items(), key=lambda x: -x[1]):
            c = cat_colors.get(cat, "#888")
            tags.append(
                f"<span style='background:{c}33; color:{c}; "
                f"padding:1px 6px; border-radius:4px; font-size:0.7rem; "
                f"margin-left:4px;'>{cat}:{count}</span>")
        tag_html = " ".join(tags)

        display_path = (file_path if len(file_path) <= 50
                        else "..." + file_path[-47:])

        st.markdown(f"""
        <div style="margin: 5px 0;">
            <div style="display:flex; align-items:center; gap:8px;
                        margin-bottom:2px;">
                <span style="font-family:'JetBrains Mono',monospace;
                             font-size:0.78rem; min-width:300px;
                             overflow:hidden; text-overflow:ellipsis;
                             white-space:nowrap;"
                      title="{file_path}">{display_path}</span>
                <span style="font-family:'JetBrains Mono',monospace;
                             font-weight:700; font-size:0.9rem;
                             min-width:35px; color:#00d4ff;">{total}</span>
                {tag_html}
            </div>
            <div style="background:rgba(255,255,255,0.04); border-radius:4px;
                        height:14px; overflow:hidden;">
                <div style="width:{pct}%; height:100%; background:{bar_color};
                            border-radius:4px;
                            transition:width 0.5s ease;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    total_files = len(file_issues)
    total_issues_count = sum(file_issues.values())
    st.caption(
        f"📊 {total_issues_count} total issues across {total_files} files")


def _render_complexity_tab(results: Dict[str, Any]):
    """Render complexity distribution chart for all scanned functions."""
    functions: List[FunctionRecord] = results.get("_functions", [])
    if not functions:
        st.info(
            "No functions available. Enable Smells, Duplicates, or Rustify "
            "to scan the AST.")
        return

    complexities = [f.complexity for f in functions]
    sizes = [f.size_lines for f in functions]

    # ── Complexity histogram ──
    st.subheader("📊 Cyclomatic Complexity Distribution")
    buckets = {
        "1-3 (simple)": 0, "4-7 (moderate)": 0,
        "8-14 (complex)": 0, "15-24 (very complex)": 0,
        "25+ (untestable)": 0,
    }
    bucket_colors = {
        "1-3 (simple)": "#00c853", "4-7 (moderate)": "#64dd17",
        "8-14 (complex)": "#ffd600", "15-24 (very complex)": "#ff6d00",
        "25+ (untestable)": "#d50000",
    }
    for cc in complexities:
        if cc >= 25:
            buckets["25+ (untestable)"] += 1
        elif cc >= 15:
            buckets["15-24 (very complex)"] += 1
        elif cc >= 8:
            buckets["8-14 (complex)"] += 1
        elif cc >= 4:
            buckets["4-7 (moderate)"] += 1
        else:
            buckets["1-3 (simple)"] += 1

    max_bucket = max(buckets.values()) if buckets.values() else 1
    for label, count in buckets.items():
        pct = int(count / max(max_bucket, 1) * 100)
        color = bucket_colors.get(label, "#888")
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:10px; margin:4px 0;">
            <span style="min-width:170px; font-family:'JetBrains Mono',monospace;
                         font-size:0.8rem;">{label}</span>
            <div style="flex:1; background:rgba(255,255,255,0.06);
                        border-radius:4px; height:22px; overflow:hidden;">
                <div style="width:{pct}%; height:100%; background:{color};
                            border-radius:4px; transition:width 0.3s;"></div>
            </div>
            <span style="font-family:'JetBrains Mono',monospace;
                         font-weight:700; min-width:40px;
                         font-size:0.85rem;">{count}</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Stats summary ──
    st.markdown("---")
    avg_cc = sum(complexities) / len(complexities) if complexities else 0
    max_cc = max(complexities) if complexities else 0
    median_cc = sorted(complexities)[len(complexities) // 2] if complexities else 0
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Avg Complexity", f"{avg_cc:.1f}")
    sc2.metric("Max Complexity", max_cc)
    sc3.metric("Median Complexity", median_cc)
    sc4.metric("Avg Size (lines)", f"{avg_size:.0f}")

    # ── Size distribution ──
    st.markdown("---")
    st.subheader("📏 Function Size Distribution")
    size_buckets = {"1-10": 0, "11-25": 0, "26-50": 0,
                    "51-100": 0, "100+": 0}
    size_colors = {"1-10": "#00c853", "11-25": "#64dd17",
                   "26-50": "#ffd600", "51-100": "#ff6d00",
                   "100+": "#d50000"}
    for s in sizes:
        if s > 100:
            size_buckets["100+"] += 1
        elif s > 50:
            size_buckets["51-100"] += 1
        elif s > 25:
            size_buckets["26-50"] += 1
        elif s > 10:
            size_buckets["11-25"] += 1
        else:
            size_buckets["1-10"] += 1

    max_sb = max(size_buckets.values()) if size_buckets.values() else 1
    for label, count in size_buckets.items():
        pct = int(count / max(max_sb, 1) * 100)
        color = size_colors.get(label, "#888")
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:10px; margin:4px 0;">
            <span style="min-width:80px; font-family:'JetBrains Mono',monospace;
                         font-size:0.8rem;">{label} lines</span>
            <div style="flex:1; background:rgba(255,255,255,0.06);
                        border-radius:4px; height:22px; overflow:hidden;">
                <div style="width:{pct}%; height:100%; background:{color};
                            border-radius:4px; transition:width 0.3s;"></div>
            </div>
            <span style="font-family:'JetBrains Mono',monospace;
                         font-weight:700; min-width:40px;
                         font-size:0.85rem;">{count}</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Top complex functions ──
    st.markdown("---")
    st.subheader("🔥 Most Complex Functions")
    sorted_fns = sorted(
        functions, key=lambda f: f.complexity, reverse=True)[:15]
    for fn in sorted_fns:
        cc_color = ("#d50000" if fn.complexity >= 15
                    else "#ff6d00" if fn.complexity >= 8 else "#ffd600")
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px;
                    padding:6px 10px; margin:2px 0; border-radius:8px;
                    background:rgba(255,255,255,0.03);
                    border-left: 3px solid {cc_color};">
            <span style="font-family:'JetBrains Mono',monospace;
                         font-size:1.1rem; font-weight:700;
                         color:{cc_color}; min-width:35px;">
                CC {fn.complexity}</span>
            <span style="font-family:'JetBrains Mono',monospace;
                         font-size:0.82rem; color:#00d4ff;">
                {fn.name}</span>
            <span style="font-size:0.72rem; opacity:0.5; margin-left:auto;">
                {fn.file_path}:{fn.line_start} ({fn.size_lines} lines)</span>
        </div>
        """, unsafe_allow_html=True)


# ── Main app ─────────────────────────────────────────────────────────────────

def main():
    """Main Streamlit application entry point."""

    # Inject modern CSS
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

    # ── Sidebar ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center; padding: 0.5rem 0 1rem 0;">
            <p style="font-family:'JetBrains Mono',monospace;
                      font-size:1.6rem; font-weight:700; margin:0;
                      background: linear-gradient(135deg, #00d4ff, #7c4dff);
                      -webkit-background-clip: text;
                      -webkit-text-fill-color: transparent;">X-RAY</p>
            <p style="font-size:0.7rem; opacity:0.5; margin:0;
                      letter-spacing:3px; text-transform:uppercase;">
                Code Scanner</p>
        </div>
        """, unsafe_allow_html=True)
        st.caption(f"v{__version__}")
        st.divider()

        # Directory picker
        st.markdown("##### 📁 Target")
        default_path = str(Path.cwd())
        scan_path = st.text_input(
            "Path to scan", value=default_path,
            help="Absolute path to the project root",
            label_visibility="collapsed")

        exclude_str = st.text_input(
            "Exclude dirs (comma-sep)", value="",
            help="e.g. venv,node_modules,__pycache__",
            label_visibility="collapsed",
            placeholder="Exclude: venv, node_modules, ...")
        exclude_dirs = [d.strip() for d in exclude_str.split(",")
                        if d.strip()]

        st.divider()

        # Scan modes
        st.markdown("##### 🔍 Analyzers")
        col1, col2 = st.columns(2)
        with col1:
            do_smells = st.checkbox("Smells", value=True)
            do_lint = st.checkbox("Lint", value=True)
            do_rustify = st.checkbox(
                "🦀 Rustify", value=False,
                help="Score functions for Rust porting")
        with col2:
            do_duplicates = st.checkbox(
                "Duplicates", value=False,
                help="Slower — finds similar functions")
            do_security = st.checkbox("Security", value=True)

        # Presets
        preset = st.radio(
            "Presets", ["Custom", "Quick", "Full"],
            horizontal=True, index=0)
        if preset == "Quick":
            do_smells, do_lint, do_security = True, True, True
            do_duplicates, do_rustify = False, False
        elif preset == "Full":
            do_smells, do_lint, do_security = True, True, True
            do_duplicates, do_rustify = True, True

        st.divider()

        # Thresholds
        st.markdown("##### ⚙️ Thresholds")
        with st.expander("Adjust sensitivity", expanded=False):
            th_long = st.slider(
                "Long function (lines)",
                20, 200, SMELL_THRESHOLDS["long_function"])
            th_complex = st.slider(
                "High complexity (CC)",
                5, 40, SMELL_THRESHOLDS["high_complexity"])
            th_nesting = st.slider(
                "Deep nesting (levels)",
                2, 10, SMELL_THRESHOLDS["deep_nesting"])
            th_params = st.slider(
                "Too many params",
                3, 15, SMELL_THRESHOLDS["too_many_params"])
            th_god = st.slider(
                "God class (methods)",
                8, 30, SMELL_THRESHOLDS["god_class"])

        custom_thresholds = {
            **SMELL_THRESHOLDS,
            "long_function": th_long,
            "high_complexity": th_complex,
            "deep_nesting": th_nesting,
            "too_many_params": th_params,
            "god_class": th_god,
        }

        st.divider()

        # Run button
        run_scan = st.button(
            "⚡ Run X-Ray Scan", use_container_width=True, type="primary")

        # Footer
        st.divider()
        st.markdown("""
        <div style="text-align:center; opacity:0.3; font-size:0.65rem;
                    font-family:'JetBrains Mono',monospace;">
            AST · Ruff · Bandit · Rust<br>
            github.com/GeoHaber/X_Ray
        </div>
        """, unsafe_allow_html=True)

    # ── Main area ────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom: 1rem;">
        <h1 style="font-family:'JetBrains Mono',monospace; font-weight:700;
                   background: linear-gradient(135deg, #00d4ff, #7c4dff);
                   -webkit-background-clip: text;
                   -webkit-text-fill-color: transparent;
                   margin:0;">🔬 X-Ray</h1>
        <p style="opacity:0.5; font-size:0.85rem; margin:0;">
            AI-Powered Code Quality Scanner —
            AST Smells · Ruff Lint · Bandit Security · Rust Advisor</p>
    </div>
    """, unsafe_allow_html=True)

    # Run scan on button click
    if run_scan:
        root = Path(scan_path).resolve()
        if not root.is_dir():
            st.error(f"❌ Not a valid directory: `{scan_path}`")
            return

        modes = {
            "smells": do_smells,
            "duplicates": do_duplicates,
            "lint": do_lint,
            "security": do_security,
            "rustify": do_rustify,
        }

        if not any(modes.values()):
            st.warning("Please select at least one analyzer.")
            return

        with st.spinner(f"⚡ Scanning `{root.name}` ..."):
            results = _run_scan(root, modes, exclude_dirs, custom_thresholds)
            st.session_state["results"] = results
            st.session_state["scan_path"] = str(root)

    # ── Display results ──────────────────────────────────────────────────
    if "results" not in st.session_state:
        st.markdown("""
        <div style="text-align:center; padding:4rem 2rem;
                    border: 1px dashed rgba(255,255,255,0.1);
                    border-radius:16px; margin-top: 2rem;">
            <p style="font-size:3rem; margin:0;">🔬</p>
            <p style="font-family:'JetBrains Mono',monospace;
                      font-size:1.1rem; margin:0.5rem 0; opacity:0.7;">
                Ready to scan</p>
            <p style="opacity:0.4; font-size:0.85rem;">
                Configure analyzers in the sidebar and click
                <b>⚡ Run X-Ray Scan</b></p>
        </div>
        """, unsafe_allow_html=True)
        return

    results = st.session_state["results"]
    grade = results.get("grade", {})
    meta = results.get("meta", {})

    # Grade card
    _render_grade_card(grade)
    st.write("")

    # Quick stats
    _render_stats_bar(meta)

    # Penalty breakdown
    breakdown = grade.get("breakdown", {})
    if breakdown:
        st.write("")
        _render_penalty_bar(breakdown)

    st.divider()

    # ── Build tab list dynamically ──
    tab_names = []
    if "smells" in results and not isinstance(results["smells"], str):
        tab_names.append("🔍 Smells")
    if "duplicates" in results:
        tab_names.append("📋 Duplicates")
    if "lint" in results:
        tab_names.append("🧹 Lint")
    if "security" in results:
        tab_names.append("🔒 Security")
    if "rustify" in results:
        tab_names.append("🦀 Rustify")

    has_issues = (results.get("_smell_issues")
                  or results.get("_lint_issues")
                  or results.get("_sec_issues"))
    if has_issues:
        tab_names.append("🔥 Heatmap")

    has_functions = bool(results.get("_functions"))
    if has_functions:
        tab_names.append("📊 Complexity")

    if tab_names:
        tabs = st.tabs(tab_names)
        tab_idx = 0
        if "🔍 Smells" in tab_names:
            with tabs[tab_idx]:
                _render_smells_tab(results)
            tab_idx += 1
        if "📋 Duplicates" in tab_names:
            with tabs[tab_idx]:
                _render_duplicates_tab(results)
            tab_idx += 1
        if "🧹 Lint" in tab_names:
            with tabs[tab_idx]:
                _render_lint_tab(results)
            tab_idx += 1
        if "🔒 Security" in tab_names:
            with tabs[tab_idx]:
                _render_security_tab(results)
            tab_idx += 1
        if "🦀 Rustify" in tab_names:
            with tabs[tab_idx]:
                _render_rustify_tab(results)
            tab_idx += 1
        if "🔥 Heatmap" in tab_names:
            with tabs[tab_idx]:
                _render_heatmap_tab(results)
            tab_idx += 1
        if "📊 Complexity" in tab_names:
            with tabs[tab_idx]:
                _render_complexity_tab(results)
            tab_idx += 1

    # ── Export ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("##### 📥 Export")

    export_data = {
        k: v for k, v in results.items()
        if not k.startswith("_")
    }
    export_data["scan_path"] = st.session_state.get("scan_path", "")

    col_a, col_b = st.columns(2)
    with col_a:
        json_str = json.dumps(export_data, indent=2, default=str)
        st.download_button(
            "⬇️ JSON Report",
            data=json_str,
            file_name="xray_report.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_b:
        md = _build_markdown_summary(results)
        st.download_button(
            "⬇️ Markdown Report",
            data=md,
            file_name="xray_report.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # Show errors if any
    error_list = meta.get("error_list", [])
    if error_list:
        with st.expander(f"⚠️ {len(error_list)} parse errors"):
            for e in error_list:
                st.code(e)


def _build_markdown_summary(results: Dict[str, Any]) -> str:
    """Build a Markdown summary of scan results."""
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    lines = [
        "# X-Ray Code Quality Report",
        "",
        f"**Score:** {grade.get('score', '?')}/100  "
        f"**Grade:** {grade.get('letter', '?')}",
        "",
        f"**Path:** `{results.get('scan_path', '?')}`",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Files scanned | {meta.get('files', 0)} |",
        f"| Functions | {meta.get('functions', 0)} |",
        f"| Classes | {meta.get('classes', 0)} |",
        f"| Duration | {meta.get('duration', 0):.1f}s |",
        "",
    ]

    breakdown = grade.get("breakdown", {})
    if breakdown:
        lines.append("## Penalty Breakdown")
        lines.append("")
        lines.append("| Category | Penalty | Details |")
        lines.append("|----------|---------|---------|")
        for key, detail in breakdown.items():
            penalty = detail.get("penalty", 0)
            extras = {k: v for k, v in detail.items() if k != "penalty"}
            detail_str = ", ".join(f"{k}={v}" for k, v in extras.items())
            lines.append(f"| {key} | -{penalty:.1f} | {detail_str} |")
        lines.append("")

    smells = results.get("smells", {})
    if smells and not isinstance(smells, str):
        lines.append("## Code Smells")
        lines.append(f"- Total: {smells.get('total', 0)}")
        lines.append(f"- Critical: {smells.get('critical', 0)}")
        lines.append(f"- Warning: {smells.get('warning', 0)}")
        lines.append(f"- Info: {smells.get('info', 0)}")
        lines.append("")

    dups = results.get("duplicates", {})
    if dups:
        lines.append("## Duplicates")
        lines.append(f"- Groups: {dups.get('total_groups', 0)}")
        lines.append(
            f"- Functions involved: "
            f"{dups.get('total_functions_involved', 0)}")
        lines.append("")

    lint = results.get("lint", {})
    if lint and not lint.get("error"):
        lines.append("## Lint (Ruff)")
        lines.append(f"- Total: {lint.get('total', 0)}")
        lines.append(f"- Auto-fixable: {lint.get('fixable', 0)}")
        lines.append("")

    sec = results.get("security", {})
    if sec and not sec.get("error"):
        lines.append("## Security (Bandit)")
        lines.append(f"- Total: {sec.get('total', 0)}")
        lines.append(f"- High: {sec.get('critical', 0)}")
        lines.append(f"- Medium: {sec.get('warning', 0)}")
        lines.append("")

    rustify = results.get("rustify", {})
    if rustify:
        lines.append("## Rustify Candidates")
        lines.append(f"- Scored: {rustify.get('total_scored', 0)}")
        lines.append(f"- Pure: {rustify.get('pure_count', 0)}")
        lines.append(f"- Top score: {rustify.get('top_score', 0)}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by X-Ray v{__version__}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
