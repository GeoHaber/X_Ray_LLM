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
from collections import Counter, namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# ── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="X-Ray Code Scanner",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports from X-Ray core ─────────────────────────────────────────────────
from Core.types import FunctionRecord, ClassRecord, SmellIssue  # noqa: E402
from Core.config import __version__, SMELL_THRESHOLDS  # noqa: E402
from Analysis.ast_utils import extract_functions_from_file, collect_py_files  # noqa: E402
from Analysis.smells import CodeSmellDetector  # noqa: E402
from Analysis.duplicates import DuplicateFinder  # noqa: E402
from Analysis.reporting import compute_grade  # noqa: E402
from Analysis.rust_advisor import RustAdvisor  # noqa: E402
from Analysis.smart_graph import SmartGraph  # noqa: E402
from Analysis.auto_rustify import (  # noqa: E402
    RustifyPipeline,
    detect_system,
    transpile_function,
)

import concurrent.futures  # noqa: E402
import ast  # noqa: E402
import textwrap  # noqa: E402


def _generate_rust_sketch(func: "FunctionRecord") -> str:
    """Generate a Rust function sketch from a Python FunctionRecord."""
    rust_fn = transpile_function(func, pyfunction=True)
    return "use pyo3::prelude::*;\n\n" + rust_fn


# ── Duplicate merge / unify helper ───────────────────────────────────────────


def _extract_params_from_code(code: str):
    """Parse code and extract parameter list from the first function."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [
                f"{a.arg}{': ' + ast.unparse(a.annotation) if a.annotation else ''}"
                for a in node.args.args
            ]
    return None


def _extract_func_codes(funcs_data: List[Dict[str, Any]], code_map: Dict[str, str]):
    """Extract source code, names, and parameter sets from function data."""
    codes, names, params_sets = [], [], []
    for f in funcs_data:
        loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
        code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
        if not code:
            continue
        codes.append(code)
        names.append(f.get("name", "unknown"))
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


def _get_first_docstring(code: str):
    """Get docstring from the first function/async function in code."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except Exception:
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
    funcs_data: List[Dict[str, Any]], names: List[str]
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
    node,
    unified_name: str,
    all_params: List[str],
    names: List[str],
    doc_parts: List[str],
) -> List[str]:
    """Unparse a function AST node into unified source lines."""
    lines = []
    for d in node.decorator_list:
        lines.append(f"@{ast.unparse(d)}")
    kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    lines.append(f"{kw} {unified_name}({', '.join(all_params)}){ret}:")
    lines.extend(_build_unified_docstring(names, doc_parts))
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, (ast.Constant, ast.Str))
    ):
        body = body[1:]
    for b_node in body:
        lines.extend(f"    {bl}" for bl in ast.unparse(b_node).split("\n"))
    return lines


def _generate_unified_function(
    funcs_data: List[Dict[str, Any]], code_map: Dict[str, str]
) -> str:
    """Generate a unified function from a group of duplicates."""
    codes, names, params_sets = _extract_func_codes(funcs_data, code_map)
    if not codes:
        return "# No source code available for merging"

    base_idx = max(range(len(codes)), key=lambda i: len(codes[i]))
    base_code, base_name = codes[base_idx], names[base_idx]
    unified_name = _unified_func_name(names)
    all_params = _merge_param_lists(params_sets)
    doc_parts = _collect_docstrings(codes)

    lines = _build_unified_header(funcs_data, names)

    try:
        tree = ast.parse(textwrap.dedent(base_code))
        func_node = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if func_node is None:
            raise ValueError("No function node")
        lines.extend(
            _unparse_func_node(func_node, unified_name, all_params, names, doc_parts)
        )
    except Exception:
        lines.append(base_code.replace(base_name, unified_name, 1))

    return "\n".join(lines)


# ── Modern CSS injection ────────────────────────────────────────────────────

_CUSTOM_CSS = """
<style>
/* ── Global overrides ─────────────────────────────── */

:root {
    --accent:  #00d4ff;
    --accent2: #7c4dff;
    --bg-card: rgba(17, 25, 40, 0.75);
    --border:  rgba(255,255,255,0.08);
    --font-body: 'Segoe UI', -apple-system, system-ui, 'Helvetica Neue', Arial, sans-serif;
    --font-mono: 'Cascadia Code', 'Consolas', 'SF Mono', 'Fira Code', monospace;
}

/* Main container */
.stApp {
    font-family: var(--font-body);
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
    font-family: var(--font-mono);
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
    font-family: var(--font-mono);
    font-size: 0.85rem;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #00d4ff22, #7c4dff22) !important;
    border: 1px solid var(--accent) !important;
}

/* Expander styling */
.streamlit-expanderHeader {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    border-radius: 8px;
}

/* Code blocks */
code, .stCode {
    font-family: var(--font-mono) !important;
}

/* Buttons */
.stButton > button {
    border-radius: 8px;
    font-family: var(--font-mono);
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
    font-family: var(--font-mono);
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
    "A+": "#00c853",
    "A": "#00c853",
    "A-": "#00e676",
    "B+": "#64dd17",
    "B": "#aeea00",
    "B-": "#ffd600",
    "C+": "#ffab00",
    "C": "#ff6d00",
    "C-": "#ff3d00",
    "D+": "#dd2c00",
    "D": "#d50000",
    "D-": "#b71c1c",
    "F": "#880e4f",
}

_SEV_ICONS = {"critical": "🔴", "warning": "🟡", "info": "🟢"}


# ── Reusable UI helpers ──────────────────────────────────────────────────────


def _html_bar(
    label: str, count: int, max_count: int, color: str, label_width: str = "120px"
) -> str:
    """Return one styled horizontal bar as raw HTML."""
    pct = int(count / max(max_count, 1) * 100)
    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0;">'
        f'<span style="min-width:{label_width};font-family:var(--font-mono);'
        f'font-size:0.8rem;">{label}</span>'
        f'<div style="flex:1;background:rgba(255,255,255,0.06);'
        f'border-radius:4px;height:20px;overflow:hidden;">'
        f'<div style="width:{pct}%;height:100%;background:{color};'
        f'border-radius:4px;transition:width 0.3s;"></div></div>'
        f'<span style="font-family:var(--font-mono);font-weight:700;'
        f'min-width:30px;">{count}</span></div>'
    )


def _render_bars(items: list, label_width: str = "120px"):
    """Render a list of ``(label, count, color)`` tuples as bars."""
    if not items:
        return
    max_count = max(c for _, c, _ in items) if items else 1
    html = "\n".join(
        _html_bar(lbl, cnt, max_count, col, label_width) for lbl, cnt, col in items
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_file_preview(file_path: str, max_chars: int = 8000):
    """Show a file code-block, truncated when necessary."""
    try:
        src = Path(file_path).read_text(encoding="utf-8", errors="replace")
        st.code(src[:max_chars], language="python")
        if len(src) > max_chars:
            st.caption(f"... truncated (file > {max_chars:,} chars)")
    except Exception as exc:
        st.warning(f"Cannot read file: {exc}")


def _render_worst_files(worst: Dict[str, int], limit: int = 10):
    """Show expandable worst-files list with source preview."""
    if not worst:
        return
    st.subheader("Worst Files")
    for fpath, count in sorted(worst.items(), key=lambda x: -x[1])[:limit]:
        with st.expander(f"📄 `{fpath}` — {count} issues"):
            _render_file_preview(fpath)


def _mono_status(text: str, color: str = "") -> str:
    """Return an inline monospace status paragraph (HTML)."""
    style = "font-family:'Cascadia Code','Consolas',monospace;font-size:0.82rem;"
    if color:
        style += f"color:{color};"
    else:
        style += "opacity:0.7;"
    return f"<p style='{style}'>{text}</p>"


# ── Scan helpers ─────────────────────────────────────────────────────────────


def _scan_codebase(root: Path, exclude: List[str], on_file=None) -> tuple:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude or None)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    done = 0
    total = len(py_files)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f for f in py_files
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


# ── Scan context bundling ────────────────────────────────────────────────
ScanContext = namedtuple("ScanContext", "root exclude thresholds functions classes")


def _run_phase_smells(ctx, results):
    """Run code-smell detection phase."""
    detector = CodeSmellDetector(thresholds=ctx.thresholds)
    smells = detector.detect(ctx.functions, ctx.classes)
    results["smells"] = detector.summary()
    results["_smell_issues"] = smells


def _run_phase_duplicates(ctx, results):
    """Run duplicate-detection phase."""
    finder = DuplicateFinder()
    finder.find(ctx.functions)
    results["duplicates"] = finder.summary()
    results["_dup_groups"] = finder.groups


def _run_phase_lint(ctx, results):
    """Run Ruff lint phase — delegates to Core.scan_phases."""
    from Core.scan_phases import run_lint_phase

    linter, lint_issues = run_lint_phase(ctx.root, exclude=ctx.exclude or None)
    if linter is not None:
        results["lint"] = linter.summary(lint_issues)
        results["_lint_issues"] = lint_issues
    else:
        results["lint"] = {"error": "Ruff not installed (pip install ruff)"}


def _run_phase_security(ctx, results):
    """Run Bandit security phase — delegates to Core.scan_phases."""
    from Core.scan_phases import run_security_phase

    sec, sec_issues = run_security_phase(ctx.root, exclude=ctx.exclude or None)
    if sec is not None:
        results["security"] = sec.summary(sec_issues)
        results["_sec_issues"] = sec_issues
    else:
        results["security"] = {"error": "Bandit not installed (pip install bandit)"}


def _run_phase_rustify(ctx, results):
    """Score functions for Rust transpilation."""
    advisor = RustAdvisor()
    candidates = advisor.score(ctx.functions)
    results["rustify"] = {
        "total_scored": len(candidates),
        "pure_count": sum(1 for c in candidates if c.is_pure),
        "top_score": candidates[0].score if candidates else 0,
    }
    results["_rust_candidates"] = candidates


_PHASE_RUNNERS = {
    "smells": ("Detecting code smells", _run_phase_smells),
    "duplicates": ("Finding duplicates", _run_phase_duplicates),
    "lint": ("Running Ruff lint", _run_phase_lint),
    "security": ("Running Bandit security", _run_phase_security),
    "rustify": ("Scoring Rust candidates", _run_phase_rustify),
}


def _run_scan(
    root: Path,
    modes: Dict[str, bool],
    exclude: List[str],
    thresholds: Dict[str, int],
    progress_cb=None,
) -> Dict[str, Any]:
    """Run selected scan phases and return results dict.

    *progress_cb(fraction, phase_label)* is called to report 0.0-1.0
    progress and the name of the current phase.
    """
    results: Dict[str, Any] = {"meta": {}}
    t0 = time.time()

    # ── Build phase list so we can distribute the progress bar evenly ──
    need_ast = modes.get("smells") or modes.get("duplicates") or modes.get("rustify")
    active = [k for k in _PHASE_RUNNERS if modes.get(k)]
    n_phases = (1 if need_ast else 0) + len(active) + 1  # +1 for grade
    pw = 1.0 / max(n_phases, 1)
    pi = 0

    def _prog(label: str, sub: float = 1.0):
        if progress_cb:
            progress_cb(min((pi + sub) * pw, 1.0), label)

    # ── AST parse ──
    functions, classes, errors, file_count = [], [], [], 0
    if need_ast:
        _prog("Parsing source files", 0.0)
        functions, classes, errors, file_count = _scan_codebase(
            root, exclude, on_file=lambda d, t, _p: _prog(f"Parsing {d}/{t}", d / t)
        )
        _prog("AST parse complete")
        pi += 1

    results["meta"].update(
        files=file_count,
        functions=len(functions),
        classes=len(classes),
        errors=len(errors),
        error_list=errors[:20],
    )

    if need_ast:
        code_map: Dict[str, str] = {}
        for fn in functions:
            code_map[f"{fn.file_path}:{fn.line_start}"] = fn.code
            code_map[fn.key] = fn.code
        results["_code_map"] = code_map
        results["_functions"] = functions

    # ── Run analysis phases via dispatch table ──
    ctx = ScanContext(root, exclude, thresholds, functions, classes)
    for key in active:
        label, runner = _PHASE_RUNNERS[key]
        _prog(label, 0.0)
        runner(ctx, results)
        _prog(f"{key.title()} done")
        pi += 1

    # ── Grade ──
    results["grade"] = compute_grade(results)
    results["meta"]["duration"] = round(time.time() - t0, 2)
    return results


# ── UI Components ────────────────────────────────────────────────────────────


def _render_grade_card(grade: Dict[str, Any]):
    """Render the big grade card at the top with a modern glassmorphism look."""
    score = grade["score"]
    letter = grade["letter"]
    color = _GRADE_COLORS.get(letter, "#888")
    glow_size = max(10, int(score / 3))

    st.markdown(
        f"""
    <div style="
        text-align: center;
        padding: 1.2rem 1rem;
        border-radius: 16px;
        background: linear-gradient(135deg, {color}15, {color}30);
        border: 1px solid {color}66;
        box-shadow: 0 0 {glow_size}px {color}33;
        backdrop-filter: blur(12px);
    ">
        <p style="
            font-size: 3.5rem; font-weight: 700;
            margin: 0; color: {color};
            text-shadow: 0 0 30px {color}66;
        ">{letter}</p>
        <p style="
            font-size: 1.2rem; font-weight: 600;
            margin: 0.2rem 0; color: {color}cc;
        ">{score} / 100</p>
        <p style="
            margin: 0; opacity: 0.5; font-size: 0.7rem;
            text-transform: uppercase; letter-spacing: 2px;
        ">Quality Score</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


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
            st.markdown(
                f"""
            <div style="
                text-align: center; padding: 12px;
                border-radius: 12px;
                background: rgba(17,25,40,0.6);
                border: 1px solid rgba(255,255,255,0.06);
            ">
                <p style="font-size: 1.8rem; margin: 0;">{icon}</p>
                <p style="font-family:'Cascadia Code','Consolas',monospace;
                          font-size: 1.3rem; font-weight: 700;
                          margin: 0; color: #00d4ff;">{value}</p>
                <p style="font-size: 0.75rem; margin: 0; opacity: 0.5;
                          text-transform: uppercase; letter-spacing: 1px;">{label}</p>
            </div>
            """,
                unsafe_allow_html=True,
            )


def _render_penalty_bar(breakdown: Dict[str, Any]):
    """Render a horizontal breakdown of penalties with modern styling."""
    if not breakdown:
        return
    cols = st.columns(len(breakdown))
    labels = {
        "smells": "🔍 Smells",
        "duplicates": "📋 Duplicates",
        "lint": "🧹 Lint",
        "security": "🔒 Security",
    }
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
        _render_bars(
            [
                (cat, cnt, "linear-gradient(90deg,#ff6b6b,#ffa06b)")
                for cat, cnt in cat_data
            ],
            label_width="180px",
        )

    _render_worst_files(summary.get("worst_files", {}))
    _render_smell_issues(issues, results.get("_code_map", {}))


def _render_smell_issues(issues: list, code_map: dict):
    """Expandable issue list with severity filter."""
    st.subheader("All Issues")
    sev_filter = st.selectbox(
        "Filter by severity", ["all", "critical", "warning", "info"], key="smell_filter"
    )
    filtered = (
        issues
        if sev_filter == "all"
        else [i for i in issues if i.severity == sev_filter]
    )
    filtered.sort(
        key=lambda s: (
            0 if s.severity == "critical" else 1 if s.severity == "warning" else 2,
            s.file_path,
            s.line,
        )
    )

    for s in filtered[:100]:
        icon = _SEV_ICONS.get(s.severity, "❓")
        with st.expander(f"{icon} [{s.category}] {s.name} — {s.file_path}:{s.line}"):
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


def _render_func_column(col, f, code_map: dict):
    """Render one function's code inside a Streamlit column."""
    loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
    code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
    with col:
        st.caption(f"📄 {loc}")
        st.markdown(
            f"**{f.get('name', '?')}** "
            f"({f.get('size', '?')} lines, "
            f"sim: {f.get('similarity', 0):.0%})"
        )
        if code:
            st.code(code, language="python")
        else:
            st.warning("Source not available")


def _render_dup_group(g, code_map: dict):
    """Render one duplicate group inside an expander."""
    if g.merge_suggestion:
        st.info(f"**Merge suggestion:** {g.merge_suggestion}")

    funcs = g.functions
    st.markdown("##### 📄 Original Functions")

    if len(funcs) >= 2:
        cols = st.columns(min(len(funcs), 2))
        for i, f in enumerate(funcs[:2]):
            _render_func_column(cols[i], f, code_map)
        for f in funcs[2:]:
            loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
            code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
            st.caption(f"📄 {loc} — **{f.get('name', '?')}**")
            if code:
                st.code(code, language="python")
    else:
        for f in funcs:
            loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
            code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
            st.caption(f"📄 {loc} — **{f.get('name', '?')}**")
            if code:
                st.code(code, language="python")

    if len(funcs) >= 2:
        st.markdown("---")
        st.markdown("##### 🔗 Unified Function (auto-generated)")
        st.caption(
            "This is a suggested merged version. "
            "Review parameters, logic branches, and naming "
            "before applying."
        )
        unified = _generate_unified_function(funcs, code_map)
        st.code(unified, language="python")


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

    type_filter = st.selectbox(
        "Filter by type",
        ["all", "exact", "near", "structural", "semantic"],
        key="dup_filter",
    )
    filtered = (
        groups
        if type_filter == "all"
        else [g for g in groups if g.similarity_type == type_filter]
    )

    code_map = results.get("_code_map", {})

    for g in filtered[:50]:
        sim_pct = f"{g.avg_similarity:.0%}"
        func_names = ", ".join(f.get("name", "?") for f in g.functions)
        with st.expander(
            f"Group {g.group_id} — {g.similarity_type} ({sim_pct}) — {func_names}"
        ):
            _render_dup_group(g, code_map)

    if len(filtered) > 50:
        st.warning(f"Showing first 50 of {len(filtered)} groups.")


def _run_ruff_autofix(scan_path: str):
    """Execute ruff --fix and display results in Streamlit."""
    try:
        result = subprocess.run(
            ["ruff", "check", "--fix", str(scan_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            st.success("✅ Auto-fix complete! Re-run scan to see updated results.")
        else:
            st.success(f"✅ Fixes applied. {result.stdout.strip()}")
        if result.stderr.strip():
            with st.expander("Ruff output"):
                st.code(result.stderr)
    except FileNotFoundError:
        st.error("Ruff not found. Install with: `pip install ruff`")
    except subprocess.TimeoutExpired:
        st.error("Ruff timed out after 60 seconds.")


def _render_autofix_section(fixable_count: int):
    """Render the ruff --fix button and run it on click."""
    st.markdown("---")
    fix_col1, fix_col2 = st.columns([1, 3])
    with fix_col1:
        do_fix = st.button(
            "🔧 Auto-Fix All",
            type="primary",
            use_container_width=True,
            help=f"Run ruff --fix on {fixable_count} auto-fixable issues",
        )
    with fix_col2:
        st.caption(f"⚡ {fixable_count} issues can be automatically fixed by Ruff.")
        st.caption("⚠️ This modifies files in-place. Commit your work first!")

    if do_fix:
        scan_path = st.session_state.get("scan_path", "")
        if scan_path:
            with st.spinner("🔧 Running ruff --fix ..."):
                _run_ruff_autofix(scan_path)
    st.markdown("---")


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

    fixable_count = summary.get("fixable", 0)
    if fixable_count > 0:
        _render_autofix_section(fixable_count)

    # Top rules
    by_rule = summary.get("by_rule", {})
    if by_rule:
        st.subheader("Top Rules")
        top_rules = sorted(by_rule.items(), key=lambda x: -x[1])[:10]
        _render_bars(
            [
                (rule, cnt, "linear-gradient(90deg,#ff9800,#ff5722)")
                for rule, cnt in top_rules
            ],
            label_width="120px",
        )

    _render_worst_files(summary.get("worst_files", {}))

    # Issue list
    st.subheader("All Issues")
    for s in issues[:100]:
        icon = _SEV_ICONS.get(s.severity, "❓")
        fix_tag = " 🔧" if s.fixable else ""
        with st.expander(f"{icon} [{s.rule_code}] {s.file_path}:{s.line}{fix_tag}"):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")
    if len(issues) > 100:
        st.warning(f"Showing first 100 of {len(issues)} issues.")


def _render_security_summary(summary: Dict[str, Any]):
    """Render security summary metrics and breakdowns."""
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", summary.get("total", 0))
    c2.metric("🔴 High", summary.get("critical", 0))
    c3.metric("🟡 Medium", summary.get("warning", 0))

    by_rule = summary.get("by_rule", {})
    if by_rule:
        st.subheader("Issue Types")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
            st.write(f"**{rule}**: {count}")

    by_conf = summary.get("by_confidence", {})
    if by_conf:
        st.subheader("By Confidence")
        for conf, count in by_conf.items():
            st.write(f"**{conf}**: {count}")


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

    _render_security_summary(summary)

    st.subheader("All Issues")
    sev_filter = st.selectbox(
        "Filter by severity", ["all", "critical", "warning", "info"], key="sec_filter"
    )
    filtered = (
        issues
        if sev_filter == "all"
        else [i for i in issues if i.severity == sev_filter]
    )

    for s in filtered[:100]:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(s.severity, "❓")
        with st.expander(f"{icon} [{s.rule_code}] {s.file_path}:{s.line}"):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")
            if s.confidence:
                st.caption(f"Confidence: {s.confidence}")

    if len(filtered) > 100:
        st.warning(f"Showing first 100 of {len(filtered)} issues.")


def _render_candidate_card(rank: int, cand, code_map: dict):
    """Render one Rust candidate inside an expander."""
    fn = cand.func
    purity_badge = "🟢 Pure" if cand.is_pure else "🔴 Impure"
    score_color = (
        "#00c853" if cand.score >= 20 else "#ffd600" if cand.score >= 10 else "#ff5722"
    )

    info_cols = st.columns(5)
    info_cols[0].markdown("**Score**")
    info_cols[0].markdown(
        f"<span style='font-family:var(--font-mono); font-size:1.4rem; "
        f"color:{score_color}; font-weight:700;'>{cand.score}</span>",
        unsafe_allow_html=True,
    )
    info_cols[1].markdown(f"**Purity**\n\n{purity_badge}")
    info_cols[2].markdown(f"**Complexity**\n\n`CC = {fn.complexity}`")
    info_cols[3].markdown(f"**Size**\n\n`{fn.size_lines} lines`")
    info_cols[4].markdown(f"**Deps**\n\n`{cand.external_deps} external`")

    if cand.reason:
        st.caption(f"💡 Reason: {cand.reason}")
    st.markdown(f"📄 `{fn.file_path}:{fn.line_start}`")

    code = code_map.get(f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, ""))
    if code:
        py_col, rs_col = st.columns(2)
        with py_col:
            st.markdown("**🐍 Python (original)**")
            st.code(code, language="python")
        with rs_col:
            st.markdown("**🦀 Rust (auto-sketch)**")
            st.code(_generate_rust_sketch(fn), language="rust")
        st.caption("⚠️ Auto-generated sketch — review types and error handling.")


_SCORE_BUCKET_ORDER = ["0-5", "5-10", "10-15", "15-20", "20-25", "25+"]
_SCORE_BUCKET_THRESHOLDS = [5, 10, 15, 20, 25]
_SCORE_BUCKET_COLORS = {
    "25+": "#00c853",
    "20-25": "#00c853",
    "15-20": "#ffd600",
    "10-15": "#ffd600",
    "5-10": "#ff5722",
    "0-5": "#ff5722",
}


def _score_to_bucket(score: float) -> str:
    """Map a numeric score to its bucket label."""
    for threshold, label in zip(_SCORE_BUCKET_THRESHOLDS, _SCORE_BUCKET_ORDER):
        if score < threshold:
            return label
    return "25+"


def _render_score_distribution(candidates: list):
    """Score distribution bar chart."""
    st.subheader("📊 Score Distribution")
    buckets = {k: 0 for k in _SCORE_BUCKET_ORDER}
    for c in candidates:
        buckets[_score_to_bucket(c.score)] += 1

    items = [
        (label, count, _SCORE_BUCKET_COLORS[label]) for label, count in buckets.items()
    ]
    _render_bars(items, label_width="60px")


def _render_rustify_tab(results: Dict[str, Any]):
    """Render the Rustify analysis tab."""
    candidates = results.get("_rust_candidates", [])
    rustify_summary = results.get("rustify", {})
    code_map = results.get("_code_map", {})

    if not candidates:
        st.info("No functions scored. Need functions with 5+ lines.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🦀 Scored", rustify_summary.get("total_scored", 0))
    c2.metric("✅ Pure", rustify_summary.get("pure_count", 0))
    c3.metric("🏆 Top Score", rustify_summary.get("top_score", 0))
    c4.metric(
        "⚠️ Impure",
        rustify_summary.get("total_scored", 0) - rustify_summary.get("pure_count", 0),
    )

    st.markdown("---")
    st.subheader("🏆 Top Rust Candidates")
    show_n = st.slider(
        "Show top N",
        5,
        min(50, len(candidates)),
        min(15, len(candidates)),
        key="rustify_top_n",
    )

    for rank, cand in enumerate(candidates[:show_n], 1):
        fn = cand.func
        purity_badge = "🟢 Pure" if cand.is_pure else "🔴 Impure"
        with st.expander(
            f"#{rank}  ⟫  **{fn.name}**  —  Score: {cand.score}  |  "
            f"{purity_badge}  |  CC={fn.complexity}  |  {fn.size_lines} lines"
        ):
            _render_candidate_card(rank, cand, code_map)

    st.markdown("---")
    _render_score_distribution(candidates)


def _aggregate_file_issues(results: Dict[str, Any]):
    """Aggregate all issues by file path for the heatmap."""
    file_issues: Counter = Counter()
    file_detail: Dict[str, Counter] = {}

    sources = [
        ("_smell_issues", "smells"),
        ("_lint_issues", "lint"),
        ("_sec_issues", "security"),
    ]
    for key, cat in sources:
        for s in results.get(key, []):
            file_issues[s.file_path] += 1
            file_detail.setdefault(s.file_path, Counter())
            file_detail[s.file_path][cat] += 1

    return file_issues, file_detail


def _heatmap_bar_color(pct: int) -> str:
    """Return gradient colour string based on severity percentage."""
    if pct > 75:
        return "linear-gradient(90deg, #ff1744, #d50000)"
    if pct > 50:
        return "linear-gradient(90deg, #ff9100, #ff6d00)"
    if pct > 25:
        return "linear-gradient(90deg, #ffd600, #ffab00)"
    return "linear-gradient(90deg, #00e676, #00c853)"


def _render_heatmap_tab(results: Dict[str, Any]):
    """Render a file heatmap aggregating all issues across analyzers."""
    file_issues, file_detail = _aggregate_file_issues(results)

    if not file_issues:
        st.success("No issues to visualize! 🎉")
        return

    ranked = file_issues.most_common(30)
    max_issues = ranked[0][1] if ranked else 1

    st.subheader("🔥 Issue Heatmap — Worst Files")
    st.caption("Aggregated across all enabled analyzers.")

    cat_colors = {"smells": "#ff6b6b", "lint": "#ffa06b", "security": "#ff4081"}

    for file_path, total in ranked:
        pct = int(total / max(max_issues, 1) * 100)
        detail = file_detail.get(file_path, {})
        tags = " ".join(
            f"<span style='background:{cat_colors.get(cat, '#888')}33; "
            f"color:{cat_colors.get(cat, '#888')}; padding:1px 6px; "
            f"border-radius:4px; font-size:0.7rem; margin-left:4px;'>"
            f"{cat}:{cnt}</span>"
            for cat, cnt in sorted(detail.items(), key=lambda x: -x[1])
        )
        display = file_path if len(file_path) <= 50 else "..." + file_path[-47:]
        with st.expander(f"🔥 {display} — {total} issues"):
            st.markdown(
                f"""
            <div style="margin: 4px 0 8px 0;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-family:var(--font-mono);
                                 font-weight:700; color:#00d4ff;">
                        {total} issues</span> {tags}
                </div>
                <div style="background:rgba(255,255,255,0.04);
                            border-radius:4px; height:10px;
                            overflow:hidden; margin-top:4px;">
                    <div style="width:{pct}%; height:100%;
                                background:{_heatmap_bar_color(pct)};
                                border-radius:4px;"></div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )
            _render_file_preview(file_path)

    st.markdown("---")
    st.caption(
        f"📊 {sum(file_issues.values())} total issues across {len(file_issues)} files"
    )


_CC_THRESHOLDS = [
    (25, "25+ (untestable)"),
    (15, "15-24 (very complex)"),
    (8, "8-14 (complex)"),
    (4, "4-7 (moderate)"),
]


def _cc_bucket(cc: int) -> str:
    """Classify a cyclomatic complexity value into a bucket label."""
    return next((lbl for thr, lbl in _CC_THRESHOLDS if cc >= thr), "1-3 (simple)")


def _render_cc_histogram(complexities: list):
    """Cyclomatic complexity distribution bars."""
    st.subheader("📊 Cyclomatic Complexity Distribution")
    buckets = {
        "1-3 (simple)": 0,
        "4-7 (moderate)": 0,
        "8-14 (complex)": 0,
        "15-24 (very complex)": 0,
        "25+ (untestable)": 0,
    }
    bucket_colors = {
        "1-3 (simple)": "#00c853",
        "4-7 (moderate)": "#64dd17",
        "8-14 (complex)": "#ffd600",
        "15-24 (very complex)": "#ff6d00",
        "25+ (untestable)": "#d50000",
    }
    for cc in complexities:
        buckets[_cc_bucket(cc)] += 1

    _render_bars(
        [(lbl, cnt, bucket_colors[lbl]) for lbl, cnt in buckets.items()],
        label_width="170px",
    )


_SIZE_THRESHOLDS = [
    (100, "100+"),
    (50, "51-100"),
    (25, "26-50"),
    (10, "11-25"),
]


def _size_bucket(s: int) -> str:
    """Classify a function size into a bucket label."""
    return next((lbl for thr, lbl in _SIZE_THRESHOLDS if s > thr), "1-10")


def _render_size_distribution(sizes: list):
    """Function size distribution bars."""
    st.subheader("📏 Function Size Distribution")
    size_buckets = {"1-10": 0, "11-25": 0, "26-50": 0, "51-100": 0, "100+": 0}
    size_colors = {
        "1-10": "#00c853",
        "11-25": "#64dd17",
        "26-50": "#ffd600",
        "51-100": "#ff6d00",
        "100+": "#d50000",
    }
    for s in sizes:
        size_buckets[_size_bucket(s)] += 1

    _render_bars(
        [(f"{lbl} lines", cnt, size_colors[lbl]) for lbl, cnt in size_buckets.items()],
        label_width="80px",
    )


def _render_top_complex_fns(functions: list, code_map: dict):
    """Show the top-15 most complex functions with code preview."""
    st.subheader("🔥 Most Complex Functions")
    sorted_fns = sorted(functions, key=lambda f: f.complexity, reverse=True)[:15]
    for fn in sorted_fns:
        cc_color = (
            "#d50000"
            if fn.complexity >= 15
            else "#ff6d00"
            if fn.complexity >= 8
            else "#ffd600"
        )
        with st.expander(
            f"CC {fn.complexity}  ·  {fn.name}  ·  "
            f"{fn.file_path}:{fn.line_start} ({fn.size_lines} lines)"
        ):
            st.markdown(
                f"""
            <div style="display:flex; align-items:center; gap:12px;
                        padding:6px 10px; margin:2px 0; border-radius:8px;
                        background:rgba(255,255,255,0.03);
                        border-left: 3px solid {cc_color};">
                <span style="font-family:var(--font-mono);
                             font-size:1.1rem; font-weight:700;
                             color:{cc_color};">CC {fn.complexity}</span>
                <span style="font-family:var(--font-mono);
                             font-size:0.82rem; color:#00d4ff;">
                    {fn.name}</span>
                <span style="font-size:0.72rem; opacity:0.5;
                             margin-left:auto;">
                    {fn.size_lines} lines · params: {", ".join(fn.parameters) or "none"}</span>
            </div>
            """,
                unsafe_allow_html=True,
            )
            code = code_map.get(
                f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, "")
            )
            if code:
                st.code(code, language="python")
            else:
                _render_file_snippet(fn)


def _render_file_snippet(fn):
    """Fallback: load source from disk for a FunctionRecord."""
    try:
        src = Path(fn.file_path).read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        start = max(0, fn.line_start - 1)
        end = min(len(lines), start + fn.size_lines + 5)
        st.code("\n".join(lines[start:end]), language="python")
    except Exception:
        st.warning("Source code not available")


def _render_complexity_tab(results: Dict[str, Any]):
    """Render complexity distribution chart for all scanned functions."""
    functions: List[FunctionRecord] = results.get("_functions", [])
    if not functions:
        st.info(
            "No functions available. Enable Smells, Duplicates, or Rustify "
            "to scan the AST."
        )
        return

    complexities = [f.complexity for f in functions]
    sizes = [f.size_lines for f in functions]

    _render_cc_histogram(complexities)

    # Stats summary
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

    st.markdown("---")
    _render_size_distribution(sizes)

    st.markdown("---")
    _render_top_complex_fns(functions, results.get("_code_map", {}))


# ── Function Graph (Plotly) tab ──────────────────────────────────────────────


def _layout_graph_nodes(nodes: list):
    """Position nodes in concentric rings by health category."""
    import math

    groups = {"healthy": [], "warning": [], "critical": []}
    for i, node in enumerate(nodes):
        groups.get(node.get("health", "healthy"), groups["healthy"]).append(i)

    n = len(nodes)
    node_x, node_y = [0.0] * n, [0.0] * n
    for health, radius in [("critical", 1.0), ("warning", 2.5), ("healthy", 4.5)]:
        indices = groups.get(health, [])
        count = len(indices)
        for j, idx in enumerate(indices):
            angle = 2 * math.pi * j / max(count, 1) + (hash(health) % 100) * 0.01
            node_x[idx] = radius * math.cos(angle)
            node_y[idx] = radius * math.sin(angle)

    return node_x, node_y, groups


def _build_edge_trace(graph, node_x, node_y, go):
    """Build the edge line trace for the graph."""
    id_to_idx = {node["id"]: i for i, node in enumerate(graph.nodes)}
    edge_x, edge_y = [], []
    for edge in graph.edges:
        src, dst = id_to_idx.get(edge["from"]), id_to_idx.get(edge["to"])
        if src is not None and dst is not None:
            edge_x.extend([node_x[src], node_x[dst], None])
            edge_y.extend([node_y[src], node_y[dst], None])
    return go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=0.8, color="rgba(150,150,150,0.4)"),
        hoverinfo="none",
    )


class _GraphLayout:
    """Bundle of graph + node positions for trace building."""

    __slots__ = ("graph", "node_x", "node_y")

    def __init__(self, graph, node_x, node_y):
        self.graph = graph
        self.node_x = node_x
        self.node_y = node_y


def _build_node_trace(layout: _GraphLayout, indices, health, go):
    """Build a Plotly scatter trace for one health category."""
    graph, node_x, node_y = layout.graph, layout.node_x, layout.node_y
    color_map = {"healthy": "#2ecc71", "warning": "#f39c12", "critical": "#e74c3c"}
    label_map = {"healthy": "Healthy", "warning": "Warning", "critical": "Critical"}
    xs = [node_x[i] for i in indices]
    ys = [node_y[i] for i in indices]
    labels = [graph.nodes[i]["label"] for i in indices]
    sizes = [max(6, min(25, graph.nodes[i].get("size", 10) / 3)) for i in indices]
    hovers = [
        f"<b>{graph.nodes[i]['label']}</b><br>"
        f"Size: {graph.nodes[i].get('size', '?')} lines<br>"
        f"Group: {graph.nodes[i].get('group', '?')}"
        for i in indices
    ]
    return go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        name=f"{label_map[health]} ({len(indices)})",
        text=labels if len(indices) <= 40 else [""] * len(indices),
        textposition="top center",
        textfont=dict(size=8, color="#ccc"),
        marker=dict(
            size=sizes,
            color=color_map[health],
            line=dict(width=1, color="rgba(255,255,255,0.3)"),
            opacity=0.85,
        ),
        hovertext=hovers,
        hoverinfo="text",
    )


def _build_graph_traces(graph, node_x, node_y, groups):
    """Build Plotly scatter traces for edges and health-grouped nodes."""
    import plotly.graph_objects as go

    layout = _GraphLayout(graph, node_x, node_y)
    traces = [_build_edge_trace(graph, node_x, node_y, go)]

    for health in ["critical", "warning", "healthy"]:
        indices = groups.get(health, [])
        if not indices:
            continue
        traces.append(_build_node_trace(layout, indices, health, go))

    return traces


def _render_graph_tab(results: Dict[str, Any]):
    """Render interactive function-distribution graph using Plotly."""
    import plotly.graph_objects as go

    functions: List[FunctionRecord] = results.get("_functions", [])
    smells: List[SmellIssue] = results.get("_smell_issues", [])
    dup_groups = results.get("_dup_groups", [])

    if not functions:
        st.info("No functions available. Enable Smells or Duplicates.")
        return

    graph = SmartGraph()
    graph.build(functions, smells, dup_groups, Path("."))

    healthy = sum(1 for n in graph.nodes if n.get("health") == "healthy")
    warning = sum(1 for n in graph.nodes if n.get("health") == "warning")
    critical = sum(1 for n in graph.nodes if n.get("health") == "critical")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Healthy", healthy)
    c2.metric("Warning", warning)
    c3.metric("Critical", critical)
    c4.metric("Dup Links", len(graph.edges))
    st.caption(
        "Nodes = functions (green/orange/red). "
        "Edges = duplicate pairs. Hover for details."
    )

    if not graph.nodes:
        st.info("No function nodes to display.")
        return

    node_x, node_y, groups = _layout_graph_nodes(graph.nodes)
    traces = _build_graph_traces(graph, node_x, node_y, groups)

    fig = go.Figure(data=traces)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(14,17,23,0.8)",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=0, r=0, t=40, b=0),
        height=550,
        hovermode="closest",
    )

    st.plotly_chart(fig, use_container_width=True, key="graph_plotly")


# ── Auto-Rustify Pipeline tab ────────────────────────────────────────────────


def _render_pipeline_config() -> Dict[str, Any]:
    """Pipeline configuration widgets; return config dict."""
    st.markdown("##### Pipeline Configuration")
    cfg1, cfg2, cfg3 = st.columns(3)
    with cfg1:
        build_mode = st.selectbox(
            "Build mode",
            ["pyo3", "binary"],
            help="**pyo3** = Python extension, **binary** = standalone exe",
            key="ar_mode",
        )
    with cfg2:
        min_score = st.slider(
            "Min Rust score",
            1.0,
            30.0,
            5.0,
            0.5,
            help="Only transpile functions scoring above this",
            key="ar_min_score",
        )
    with cfg3:
        max_cands = st.slider(
            "Max candidates",
            5,
            100,
            30,
            help="Limit the number of functions to transpile",
            key="ar_max_cands",
        )

    crate_name = st.text_input(
        "Crate name",
        value="xray_rustified",
        help="Name for Cargo.toml and the output library/binary",
        key="ar_crate_name",
    )

    return {
        "mode": build_mode,
        "min_score": min_score,
        "max_cands": max_cands,
        "crate_name": crate_name,
    }


def _execute_rustify_pipeline(scan_path: str, output_dir: Path, cfg: Dict[str, Any]):
    """Run the auto-rustify pipeline with progress UI."""
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def _on_progress(frac: float, label: str):
        progress_bar.progress(min(frac, 1.0))
        status_text.markdown(_mono_status(f"⚙️ {label}"), unsafe_allow_html=True)

    pipeline = RustifyPipeline(
        project_dir=scan_path,
        output_dir=str(output_dir),
        crate_name=cfg["crate_name"],
        min_score=cfg["min_score"],
        max_candidates=cfg["max_cands"],
        mode=cfg["mode"],
    )
    report = pipeline.run(progress_cb=_on_progress)

    progress_bar.progress(1.0)
    success = report.compile_result and report.compile_result.success
    msg = (
        "✅ Pipeline complete — crate compiled successfully!"
        if success
        else "⚠️ Pipeline finished with issues — see details below"
    )
    color = "#00c853" if success else "#ff9800"
    status_text.markdown(_mono_status(msg, color=color), unsafe_allow_html=True)
    time.sleep(0.8)
    progress_bar.empty()

    return report.to_dict()


def _render_auto_rustify_tab(results: Dict[str, Any]):
    """Render the Auto-Rustify pipeline tab."""
    st.markdown(
        """
    <div style="padding:12px 16px; border-radius:12px;
                background:rgba(17,25,40,0.6);
                border:1px solid rgba(124,77,255,0.3); margin-bottom:1rem;">
        <p style="margin:0 0 6px 0; font-size:0.95rem;
                  font-family:var(--font-mono);">
            ⚙️ <b>Auto-Rustify Pipeline</b></p>
        <p style="font-size:0.78rem; opacity:0.6; margin:0;">
            End-to-end: Scan → Score → Generate tests → Transpile →
            Compile → Verify.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    sys_profile = detect_system()
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("🖥️ OS", sys_profile.os_name)
    s2.metric("🏗️ Arch", sys_profile.arch)
    s3.metric("🎯 Target", sys_profile.rust_target.split("-")[0])
    s4.metric("🚀 CPU Feats", ", ".join(sys_profile.cpu_features) or "baseline")
    st.divider()

    cfg = _render_pipeline_config()

    scan_path = st.session_state.get("scan_path", str(Path.cwd()))
    output_dir = Path(scan_path) / "_rustified"
    st.divider()

    run_col1, run_col2 = st.columns([1, 3])
    with run_col1:
        do_run = st.button("🚀 Run Pipeline", type="primary", use_container_width=True)
    with run_col2:
        st.caption(f"Output directory: `{output_dir}`")
        st.caption("⚠️  Requires Rust toolchain (`rustup`, `cargo`).")

    prev_report: Optional[Dict] = st.session_state.get("auto_rustify_report")

    if do_run:
        prev_report = _execute_rustify_pipeline(scan_path, output_dir, cfg)
        st.session_state["auto_rustify_report"] = prev_report

    if prev_report:
        _render_pipeline_report(prev_report)


def _render_phase_timeline(phases: list):
    """Render pipeline phase rows."""
    st.markdown("##### ⏱️ Phase Timeline")
    for phase in phases:
        name = phase.get("name", "?")
        status = phase.get("status", "?")
        icon = "✅" if status == "ok" else "⚠️" if status == "no_candidates" else "❌"
        parts = [
            f"{k}={v}"
            for k, v in phase.items()
            if k not in ("name", "status", "stderr")
        ]
        detail_str = " · ".join(parts) if parts else ""
        st.markdown(
            f"""
        <div style="display:flex; align-items:center; gap:10px;
                    padding:4px 10px; margin:2px 0; border-radius:6px;
                    background:rgba(255,255,255,0.02);">
            <span style="font-size:1.1rem;">{icon}</span>
            <span style="font-family:var(--font-mono);
                         font-size:0.82rem; min-width:140px;
                         color:#00d4ff;">{name}</span>
            <span style="font-size:0.75rem; opacity:0.6;">{detail_str}</span>
        </div>
        """,
            unsafe_allow_html=True,
        )


def _render_compile_details(compile_info: dict, phases: list):
    """Render compilation section of the pipeline report."""
    st.markdown("##### 🔨 Compilation")
    cc1, cc2, cc3 = st.columns(3)
    cc1.markdown(f"**Target:** `{compile_info.get('target', '?')}`")
    cc2.markdown(f"**Duration:** {compile_info.get('duration_s', 0):.1f}s")
    cc3.markdown(f"**RUSTFLAGS:** `{compile_info.get('rustflags', 'default')}`")
    artefact = compile_info.get("artefact", "")
    if artefact:
        st.success(f"🎯 Artefact: `{artefact}`")
    if not compile_info.get("success") and len(phases) > 1:
        stderr = phases[-2].get("stderr", "")
        if stderr:
            with st.expander("Compiler errors"):
                st.code(stderr, language="text")


def _render_pipeline_metrics(report: Dict[str, Any]):
    """Render system info and top-level metrics for the pipeline report."""
    sys_info = report.get("system", {})
    st.markdown(
        f"""
    <div style="padding:10px 14px; border-radius:8px;
                background:rgba(17,25,40,0.5);
                border:1px solid rgba(255,255,255,0.06);
                font-size:0.8rem; margin-bottom:12px;">
        🖥️ <b>{sys_info.get("os", "?")}</b> · {sys_info.get("arch", "?")} ·
        Target: <code>{sys_info.get("rust_target", "?")}</code>
    </div>
    """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📄 Scanned", f"{report.get('scan_duration_s', 0):.1f}s")
    m2.metric(
        "🦀 Candidates",
        f"{report.get('candidates_selected', 0)}/{report.get('candidates_total', 0)}",
    )
    compile_info = report.get("compile", {})
    m3.metric("⚙️ Compile", "✅ OK" if compile_info.get("success") else "❌ Failed")
    verify_info = report.get("verify", {})
    m4.metric("✔️ Verify", "✅ OK" if verify_info.get("success") else "❌ Failed")
    return compile_info, verify_info


def _render_pipeline_report(report: Dict[str, Any]):
    """Display a completed pipeline report."""
    st.divider()
    st.markdown("### 📋 Pipeline Report")

    compile_info, verify_info = _render_pipeline_metrics(report)

    phases = report.get("phases", [])
    if phases:
        _render_phase_timeline(phases)
    if compile_info:
        _render_compile_details(compile_info, phases)

    if verify_info:
        st.markdown("##### ✔️ Verification")
        if verify_info.get("success"):
            st.success(f"All {verify_info.get('passed', 0)} Rust tests passed!")
        else:
            st.error(f"{verify_info.get('failed', 0)} test(s) failed")

    st.markdown("##### 📁 Output Files")
    for label, p in [
        ("Cargo project", report.get("cargo_project_path", "")),
        ("Golden tests (Python)", report.get("test_gen_path", "")),
        ("Verify tests (Rust)", report.get("verify_test_path", "")),
    ]:
        if p:
            st.markdown(f"- **{label}:** `{p}`")

    for e in report.get("errors", []):
        st.error(e)

    st.divider()
    st.download_button(
        "⬇️ Download Pipeline Report (JSON)",
        data=json.dumps(report, indent=2, default=str),
        file_name="auto_rustify_report.json",
        mime="application/json",
        use_container_width=True,
    )


# ── Main app ─────────────────────────────────────────────────────────────────


def _sidebar_analyzers() -> Dict[str, bool]:
    """Render analyzer checkboxes + presets; return modes dict."""
    st.markdown("##### 🔍 Analyzers")
    col1, col2 = st.columns(2)
    with col1:
        do_smells = st.checkbox("Smells", value=True)
        do_lint = st.checkbox("Lint", value=True)
        do_rustify = st.checkbox(
            "🦀 Rustify", value=False, help="Score functions for Rust porting"
        )
    with col2:
        do_duplicates = st.checkbox(
            "Duplicates", value=False, help="Slower — finds similar functions"
        )
        do_security = st.checkbox("Security", value=True)

    preset = st.radio("Presets", ["Custom", "Quick", "Full"], horizontal=True, index=0)
    if preset == "Quick":
        do_smells, do_lint, do_security = True, True, True
        do_duplicates, do_rustify = False, False
    elif preset == "Full":
        do_smells = do_lint = do_security = True
        do_duplicates = do_rustify = True

    return {
        "smells": do_smells,
        "duplicates": do_duplicates,
        "lint": do_lint,
        "security": do_security,
        "rustify": do_rustify,
    }


def _sidebar_thresholds() -> Dict[str, int]:
    """Render threshold sliders; return custom thresholds dict."""
    st.markdown("##### ⚙️ Thresholds")
    with st.expander("Adjust sensitivity", expanded=False):
        th_long = st.slider(
            "Long function (lines)", 20, 200, SMELL_THRESHOLDS["long_function"]
        )
        th_complex = st.slider(
            "High complexity (CC)", 5, 40, SMELL_THRESHOLDS["high_complexity"]
        )
        th_nesting = st.slider(
            "Deep nesting (levels)", 2, 10, SMELL_THRESHOLDS["deep_nesting"]
        )
        th_params = st.slider(
            "Too many params", 3, 15, SMELL_THRESHOLDS["too_many_params"]
        )
        th_god = st.slider("God class (methods)", 8, 30, SMELL_THRESHOLDS["god_class"])
    return {
        **SMELL_THRESHOLDS,
        "long_function": th_long,
        "high_complexity": th_complex,
        "deep_nesting": th_nesting,
        "too_many_params": th_params,
        "god_class": th_god,
    }


def _render_sidebar() -> Dict[str, Any]:
    """Build the entire sidebar; return scan configuration dict."""
    with st.sidebar:
        st.markdown(
            """
        <div style="text-align:center; padding: 0.5rem 0 1rem 0;">
            <p style="font-family:'Cascadia Code','Consolas',monospace;
                      font-size:1.6rem; font-weight:700; margin:0;
                      background: linear-gradient(135deg, #00d4ff, #7c4dff);
                      -webkit-background-clip: text;
                      -webkit-text-fill-color: transparent;">X-RAY</p>
            <p style="font-size:0.7rem; opacity:0.5; margin:0;
                      letter-spacing:3px; text-transform:uppercase;">
                Code Scanner</p>
        </div>
        """,
            unsafe_allow_html=True,
        )
        st.caption(f"v{__version__}")
        st.divider()

        # Directory picker
        st.markdown("##### 📁 Target")
        scan_path = st.text_input(
            "Path to scan",
            value=str(Path.cwd()),
            help="Absolute path to the project root",
            label_visibility="collapsed",
        )
        exclude_str = st.text_input(
            "Exclude dirs (comma-sep)",
            value="",
            help="e.g. venv,node_modules,__pycache__",
            label_visibility="collapsed",
            placeholder="Exclude: venv, node_modules, ...",
        )
        exclude_dirs = [d.strip() for d in exclude_str.split(",") if d.strip()]
        st.divider()

        modes = _sidebar_analyzers()
        st.divider()

        thresholds = _sidebar_thresholds()
        st.divider()

        run_clicked = st.button(
            "⚡ Run X-Ray Scan", use_container_width=True, type="primary"
        )

        st.divider()
        st.markdown(
            """
        <div style="text-align:center; opacity:0.3; font-size:0.65rem;
                    font-family:'Cascadia Code','Consolas',monospace;">
            AST · Ruff · Bandit · Rust<br>
            github.com/GeoHaber/X_Ray
        </div>
        """,
            unsafe_allow_html=True,
        )

    return {
        "scan_path": scan_path,
        "exclude_dirs": exclude_dirs,
        "modes": modes,
        "thresholds": thresholds,
        "run": run_clicked,
    }


def _execute_scan_ui(
    root: Path,
    modes: Dict[str, bool],
    exclude_dirs: List[str],
    thresholds: Dict[str, int],
):
    """Run the scan with a live progress bar; store results in session."""
    if not any(modes.values()):
        st.warning("Please select at least one analyzer.")
        return

    progress_bar = st.progress(0.0)
    status_text = st.empty()
    status_text.markdown(_mono_status("⚡ Initialising scan…"), unsafe_allow_html=True)

    def _on_progress(frac: float, label: str):
        progress_bar.progress(min(frac, 1.0))
        status_text.markdown(_mono_status(f"⚡ {label}"), unsafe_allow_html=True)

    results = _run_scan(root, modes, exclude_dirs, thresholds, progress_cb=_on_progress)

    progress_bar.progress(1.0)
    meta = results["meta"]
    status_text.markdown(
        _mono_status(
            f"✅ Scan complete — {meta.get('files', 0)} files, "
            f"{meta.get('functions', 0)} functions "
            f"in {meta.get('duration', 0):.1f}s",
            color="#00c853",
        ),
        unsafe_allow_html=True,
    )
    time.sleep(0.6)
    progress_bar.empty()
    status_text.empty()

    st.session_state["results"] = results
    st.session_state["scan_path"] = str(root)


def _render_landing():
    """Display the landing page when no scan results exist yet."""
    st.markdown(
        """
    <div style="text-align:center; padding:2rem 1.5rem;
                border: 1px solid rgba(0,212,255,0.12);
                border-radius:16px; margin-top:1rem;
                background: linear-gradient(135deg, rgba(0,212,255,0.04), rgba(124,77,255,0.04));">
        <p style="font-size:2.8rem; margin:0;">🔬</p>
        <p style="font-size:1.1rem; margin:0.3rem 0;
                  background:linear-gradient(135deg,#00d4ff,#7c4dff);
                  -webkit-background-clip:text;
                  -webkit-text-fill-color:transparent;
                  font-weight:700;">X-Ray Code Quality Scanner</p>
        <p style="opacity:0.45; font-size:0.8rem; max-width:500px; margin:0.5rem auto 0;">
            AST Smells · Ruff Lint · Bandit Security · Duplicate Detection · Rust Advisor</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.write("")
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("**1. Configure** — Set path & analyzers in sidebar")
    with g2:
        st.markdown("**2. Scan** — Press **⚡ Run X-Ray Scan**")
    with g3:
        st.markdown("**3. Explore** — Browse results in interactive tabs")

    st.write("")
    st.caption(
        "Quality grades: A+ (97) · A (93) · B+ (87) · B (83) "
        "· C+ (77) · C (73) · D (63) · F (<60)"
    )


_TAB_RENDERERS = [
    ("🔍 Smells", "smells", lambda r: _render_smells_tab(r)),
    ("📋 Duplicates", "duplicates", lambda r: _render_duplicates_tab(r)),
    ("🧹 Lint", "lint", lambda r: _render_lint_tab(r)),
    ("🔒 Security", "security", lambda r: _render_security_tab(r)),
    ("🦀 Rustify", "rustify", lambda r: _render_rustify_tab(r)),
]


def _collect_extra_tabs(results: Dict[str, Any]) -> List[tuple]:
    """Collect extra tabs (heatmap, complexity, graph, auto-rustify)."""
    extras: List[tuple] = []
    has_issues = (
        results.get("_smell_issues")
        or results.get("_lint_issues")
        or results.get("_sec_issues")
    )
    if has_issues:
        extras.append(("🔥 Heatmap", lambda r: _render_heatmap_tab(r)))
    if results.get("_functions"):
        extras.append(("📊 Complexity", lambda r: _render_complexity_tab(r)))
        extras.append(("🕸️ Graph", lambda r: _render_graph_tab(r)))
    if "rustify" in results:
        extras.append(("⚙️ Auto-Rustify", lambda r: _render_auto_rustify_tab(r)))
    return extras


def _render_results_tabs(results: Dict[str, Any]):
    """Build dynamic tabs and dispatch to category renderers."""
    tab_entries: List[tuple] = []
    for label, key, renderer in _TAB_RENDERERS:
        data = results.get(key)
        if data and not (isinstance(data, dict) and data.get("error")):
            tab_entries.append((label, renderer))

    tab_entries.extend(_collect_extra_tabs(results))

    if not tab_entries:
        return

    tabs = st.tabs([label for label, _ in tab_entries])
    for tab, (_, renderer) in zip(tabs, tab_entries):
        with tab:
            renderer(results)


def _render_results_header(results: Dict[str, Any]):
    """Grade card + stats + penalty summary."""
    grade = results.get("grade", {})
    meta = results.get("meta", {})

    col_grade, col_stats = st.columns([1, 2])
    with col_grade:
        _render_grade_card(grade)
    with col_stats:
        _render_stats_bar(meta)
        breakdown = grade.get("breakdown", {})
        if breakdown:
            labels = {
                "smells": "Smells",
                "duplicates": "Duplicates",
                "lint": "Lint",
                "security": "Security",
            }
            parts = [
                f"{labels.get(k, k)} <b>-{d.get('penalty', 0):.0f}</b>"
                for k, d in breakdown.items()
                if d.get("penalty", 0) > 0
            ]
            if parts:
                st.markdown(
                    f"<p style='font-size:0.78rem; opacity:0.55; "
                    f"margin-top:8px;'>Penalties: {' · '.join(parts)}</p>",
                    unsafe_allow_html=True,
                )
    st.divider()


def _render_export(results: Dict[str, Any]):
    """Export section with JSON + Markdown download buttons."""
    st.divider()
    st.markdown("##### 📥 Export")

    export_data = {k: v for k, v in results.items() if not k.startswith("_")}
    export_data["scan_path"] = st.session_state.get("scan_path", "")

    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "⬇️ JSON Report",
            data=json.dumps(export_data, indent=2, default=str),
            file_name="xray_report.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_b:
        st.download_button(
            "⬇️ Markdown Report",
            data=_build_markdown_summary(results),
            file_name="xray_report.md",
            mime="text/markdown",
            use_container_width=True,
        )

    error_list = results.get("meta", {}).get("error_list", [])
    if error_list:
        with st.expander(f"⚠️ {len(error_list)} parse errors"):
            for e in error_list:
                st.code(e)


def main():
    """Main Streamlit application entry point."""
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

    config = _render_sidebar()

    if config["run"]:
        root = Path(config["scan_path"]).resolve()
        if not root.is_dir():
            st.error(f"❌ Not a valid directory: `{config['scan_path']}`")
            return
        _execute_scan_ui(
            root, config["modes"], config["exclude_dirs"], config["thresholds"]
        )

    if "results" not in st.session_state:
        _render_landing()
        return

    results = st.session_state["results"]
    _render_results_header(results)
    _render_results_tabs(results)
    _render_export(results)


def _md_header(results: Dict[str, Any]) -> List[str]:
    """Build the header section of the Markdown report."""
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    return [
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


def _md_breakdown(grade: dict) -> List[str]:
    """Build the penalty breakdown section."""
    breakdown = grade.get("breakdown", {})
    if not breakdown:
        return []
    lines = [
        "## Penalty Breakdown",
        "",
        "| Category | Penalty | Details |",
        "|----------|---------|---------|",
    ]
    for key, detail in breakdown.items():
        penalty = detail.get("penalty", 0)
        extras = {k: v for k, v in detail.items() if k != "penalty"}
        detail_str = ", ".join(f"{k}={v}" for k, v in extras.items())
        lines.append(f"| {key} | -{penalty:.1f} | {detail_str} |")
    lines.append("")
    return lines


def _md_section(
    results: Dict[str, Any], key: str, title: str, fields: List[tuple]
) -> List[str]:
    """Build a section with title and bullet-point fields."""
    data = results.get(key, {})
    if not data or isinstance(data, str) or data.get("error"):
        return []
    lines = [f"## {title}"]
    for label, field in fields:
        lines.append(f"- {label}: {data.get(field, 0)}")
    lines.append("")
    return lines


def _build_markdown_summary(results: Dict[str, Any]) -> str:
    """Build a Markdown summary of scan results."""
    lines = _md_header(results)
    lines.extend(_md_breakdown(results.get("grade", {})))
    lines.extend(
        _md_section(
            results,
            "smells",
            "Code Smells",
            [
                ("Total", "total"),
                ("Critical", "critical"),
                ("Warning", "warning"),
                ("Info", "info"),
            ],
        )
    )
    lines.extend(
        _md_section(
            results,
            "duplicates",
            "Duplicates",
            [
                ("Groups", "total_groups"),
                ("Functions involved", "total_functions_involved"),
            ],
        )
    )
    lines.extend(
        _md_section(
            results,
            "lint",
            "Lint (Ruff)",
            [("Total", "total"), ("Auto-fixable", "fixable")],
        )
    )
    lines.extend(
        _md_section(
            results,
            "security",
            "Security (Bandit)",
            [("Total", "total"), ("High", "critical"), ("Medium", "warning")],
        )
    )
    lines.extend(
        _md_section(
            results,
            "rustify",
            "Rustify Candidates",
            [
                ("Scored", "total_scored"),
                ("Pure", "pure_count"),
                ("Top score", "top_score"),
            ],
        )
    )
    lines.append("---")
    lines.append(f"*Generated by X-Ray v{__version__}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
