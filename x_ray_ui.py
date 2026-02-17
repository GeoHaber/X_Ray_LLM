#!/usr/bin/env python3
"""
x_ray_ui.py — Streamlit GUI for X-Ray Code Quality Scanner
============================================================

Launch with::

    python -m streamlit run x_ray_ui.py

Provides a visual interface to:
  - Select a project directory
  - Choose scan modes (Smells, Duplicates, Lint, Security)
  - Adjust detection thresholds
  - View results with grade card, category tabs, and details
"""

from __future__ import annotations

import json
import time
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

import concurrent.futures

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

    need_ast = modes.get("smells") or modes.get("duplicates")
    functions, classes, errors = [], [], []
    file_count = 0

    if need_ast:
        functions, classes, errors, file_count = _scan_codebase(root, exclude)

    results["meta"]["files"] = file_count
    results["meta"]["functions"] = len(functions)
    results["meta"]["classes"] = len(classes)
    results["meta"]["errors"] = len(errors)
    results["meta"]["error_list"] = errors[:20]

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
    grade_data = {"score": score, "letter": letter, "breakdown": breakdown, "tools_run": tools_run}
    results["grade"] = grade_data

    results["meta"]["duration"] = round(time.time() - t0, 2)
    return results


# ── UI Components ────────────────────────────────────────────────────────────

def _render_grade_card(grade: Dict[str, Any]):
    """Render the big grade card at the top."""
    score = grade["score"]
    letter = grade["letter"]
    color = _GRADE_COLORS.get(letter, "#888")

    st.markdown(f"""
    <div style="text-align: center; padding: 1.5rem; border-radius: 12px;
                background: linear-gradient(135deg, {color}22, {color}44);
                border: 2px solid {color};">
        <h1 style="font-size: 4rem; margin: 0; color: {color};">{letter}</h1>
        <h2 style="margin: 0.2rem 0; color: {color};">{score} / 100</h2>
        <p style="margin: 0; opacity: 0.7;">Combined Quality Score</p>
    </div>
    """, unsafe_allow_html=True)


def _render_penalty_bar(breakdown: Dict[str, Any]):
    """Render a horizontal breakdown of penalties."""
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

    # Category breakdown
    by_cat = summary.get("by_category", {})
    if by_cat:
        st.subheader("By Category")
        cat_data = sorted(by_cat.items(), key=lambda x: -x[1])
        for cat, count in cat_data:
            st.write(f"**{cat}**: {count}")

    # Worst files
    worst = summary.get("worst_files", {})
    if worst:
        st.subheader("Worst Files")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            st.write(f"`{f}` — {count} issues")

    # Issue list (expandable)
    st.subheader("All Issues")
    sev_filter = st.selectbox("Filter by severity", ["all", "critical", "warning", "info"],
                              key="smell_filter")
    filtered = issues if sev_filter == "all" else [i for i in issues if i.severity == sev_filter]
    filtered.sort(key=lambda s: (0 if s.severity == "critical" else 1 if s.severity == "warning" else 2,
                                 s.file_path, s.line))

    for s in filtered[:100]:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(s.severity, "❓")
        with st.expander(f"{icon} [{s.category}] {s.name} — {s.file_path}:{s.line}"):
            st.write(f"**Issue:** {s.message}")
            if s.suggestion:
                st.write(f"**Fix:** {s.suggestion}")
            if s.llm_analysis:
                st.info(f"**AI Tip:** {s.llm_analysis}")
            st.caption(f"Severity: {s.severity} | Metric: {s.metric_value}")

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
    type_filter = st.selectbox("Filter by type",
                               ["all", "exact", "near", "structural", "semantic"],
                               key="dup_filter")
    filtered = groups if type_filter == "all" else [
        g for g in groups if g.similarity_type == type_filter
    ]

    for g in filtered[:50]:
        sim_pct = f"{g.avg_similarity:.0%}"
        with st.expander(f"Group {g.group_id} — {g.similarity_type} ({sim_pct})"):
            for f in g.functions:
                st.write(f"📄 `{f.get('file', '?')}:{f.get('line', '?')}` — **{f.get('name', '?')}**")
            if g.merge_suggestion:
                st.info(f"**Merge suggestion:** {g.merge_suggestion}")

    if len(filtered) > 50:
        st.warning(f"Showing first 50 of {len(filtered)} groups.")


def _render_lint_tab(results: Dict[str, Any]):
    """Render the Lint tab."""
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

    # Top rules
    by_rule = summary.get("by_rule", {})
    if by_rule:
        st.subheader("Top Rules")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
            st.write(f"**{rule}**: {count}")

    # Worst files
    worst = summary.get("worst_files", {})
    if worst:
        st.subheader("Worst Files")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            st.write(f"`{f}` — {count} issues")

    # Issue list
    st.subheader("All Issues")
    for s in issues[:100]:
        icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(s.severity, "❓")
        fix_tag = " 🔧" if s.fixable else ""
        with st.expander(f"{icon} [{s.rule_code}] {s.file_path}:{s.line}{fix_tag}"):
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
    sev_filter = st.selectbox("Filter by severity",
                              ["all", "critical", "warning", "info"],
                              key="sec_filter")
    filtered = issues if sev_filter == "all" else [i for i in issues if i.severity == sev_filter]

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


# ── Main app ─────────────────────────────────────────────────────────────────

def main():
    """Main Streamlit application entry point."""

    # ── Sidebar ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/x-ray.png", width=64)
        st.title(f"X-Ray v{__version__}")
        st.caption("AI-Powered Code Quality Scanner")
        st.divider()

        # Directory picker
        st.subheader("📁 Target Directory")
        default_path = str(Path.cwd())
        scan_path = st.text_input("Path to scan", value=default_path,
                                  help="Absolute path to the project root")

        # Exclude directories
        exclude_str = st.text_input("Exclude directories",
                                    value="",
                                    help="Comma-separated list (e.g. 'venv,node_modules')")
        exclude_dirs = [d.strip() for d in exclude_str.split(",") if d.strip()]

        st.divider()

        # Scan modes
        st.subheader("🔍 Scan Modes")
        col1, col2 = st.columns(2)
        with col1:
            do_smells = st.checkbox("Smells", value=True)
            do_lint = st.checkbox("Lint", value=True)
        with col2:
            do_duplicates = st.checkbox("Duplicates", value=False,
                                        help="Slower — finds similar functions")
            do_security = st.checkbox("Security", value=True)

        # Presets
        preset = st.radio("Presets", ["Custom", "Quick Scan", "Full Scan"],
                          horizontal=True, index=0)
        if preset == "Quick Scan":
            do_smells, do_lint, do_security, do_duplicates = True, True, True, False
        elif preset == "Full Scan":
            do_smells, do_lint, do_security, do_duplicates = True, True, True, True

        st.divider()

        # Thresholds
        st.subheader("⚙️ Thresholds")
        with st.expander("Adjust detection sensitivity"):
            th_long = st.slider("Long function (lines)",
                                20, 200, SMELL_THRESHOLDS["long_function"])
            th_complex = st.slider("High complexity (CC)",
                                   5, 40, SMELL_THRESHOLDS["high_complexity"])
            th_nesting = st.slider("Deep nesting (levels)",
                                   2, 10, SMELL_THRESHOLDS["deep_nesting"])
            th_params = st.slider("Too many params",
                                  3, 15, SMELL_THRESHOLDS["too_many_params"])
            th_god = st.slider("God class (methods)",
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
        run_scan = st.button("🚀 Run X-Ray Scan", use_container_width=True,
                             type="primary")

    # ── Main area ────────────────────────────────────────────────────────
    st.title("🔬 X-Ray Code Quality Scanner")
    st.caption(f"v{__version__} — AST Smells + Ruff Lint + Bandit Security")

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
        }

        if not any(modes.values()):
            st.warning("Please select at least one scan mode.")
            return

        with st.spinner(f"🔬 Scanning `{root.name}`..."):
            results = _run_scan(root, modes, exclude_dirs, custom_thresholds)
            st.session_state["results"] = results
            st.session_state["scan_path"] = str(root)

    # ── Display results ──────────────────────────────────────────────────
    if "results" not in st.session_state:
        st.info("👈 Configure scan parameters in the sidebar and click **Run X-Ray Scan**.")
        return

    results = st.session_state["results"]
    grade = results.get("grade", {})
    meta = results.get("meta", {})

    # Grade card
    _render_grade_card(grade)

    # Quick stats
    st.write("")
    cols = st.columns(4)
    cols[0].metric("📄 Files", meta.get("files", 0))
    cols[1].metric("🔧 Functions", meta.get("functions", 0))
    cols[2].metric("📦 Classes", meta.get("classes", 0))
    cols[3].metric("⏱️ Duration", f"{meta.get('duration', 0):.1f}s")

    # Penalty breakdown
    breakdown = grade.get("breakdown", {})
    if breakdown:
        st.write("")
        _render_penalty_bar(breakdown)

    st.divider()

    # Tabbed results
    tab_names = []
    if "smells" in results and not isinstance(results["smells"], str):
        tab_names.append("🔍 Smells")
    if "duplicates" in results:
        tab_names.append("📋 Duplicates")
    if "lint" in results:
        tab_names.append("🧹 Lint")
    if "security" in results:
        tab_names.append("🔒 Security")

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

    # ── Export ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📥 Export Results")

    # Build export-safe dict (strip internal objects)
    export_data = {
        k: v for k, v in results.items()
        if not k.startswith("_")
    }
    export_data["scan_path"] = st.session_state.get("scan_path", "")

    col_a, col_b = st.columns(2)
    with col_a:
        json_str = json.dumps(export_data, indent=2, default=str)
        st.download_button(
            "⬇️ Download JSON Report",
            data=json_str,
            file_name="xray_report.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_b:
        # Markdown summary
        md = _build_markdown_summary(results)
        st.download_button(
            "⬇️ Download Markdown Summary",
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
        f"**Score:** {grade.get('score', '?')}/100  **Grade:** {grade.get('letter', '?')}",
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

    # Breakdown
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

    # Smells summary
    smells = results.get("smells", {})
    if smells and not isinstance(smells, str):
        lines.append("## Code Smells")
        lines.append(f"- Total: {smells.get('total', 0)}")
        lines.append(f"- Critical: {smells.get('critical', 0)}")
        lines.append(f"- Warning: {smells.get('warning', 0)}")
        lines.append(f"- Info: {smells.get('info', 0)}")
        lines.append("")

    # Duplicates summary
    dups = results.get("duplicates", {})
    if dups:
        lines.append("## Duplicates")
        lines.append(f"- Groups: {dups.get('total_groups', 0)}")
        lines.append(f"- Functions involved: {dups.get('total_functions_involved', 0)}")
        lines.append("")

    # Lint summary
    lint = results.get("lint", {})
    if lint and not lint.get("error"):
        lines.append("## Lint (Ruff)")
        lines.append(f"- Total: {lint.get('total', 0)}")
        lines.append(f"- Auto-fixable: {lint.get('fixable', 0)}")
        lines.append("")

    # Security summary
    sec = results.get("security", {})
    if sec and not sec.get("error"):
        lines.append("## Security (Bandit)")
        lines.append(f"- Total: {sec.get('total', 0)}")
        lines.append(f"- High: {sec.get('critical', 0)}")
        lines.append(f"- Medium: {sec.get('warning', 0)}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by X-Ray v{__version__}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
