#!/usr/bin/env python3
"""
x_ray_flet.py — Flet Desktop/Web GUI for X-Ray Code Quality Scanner
======================================================================

Launch with::

    python x_ray_flet.py                  # native desktop window
    flet run x_ray_flet.py                # same, via flet CLI
    flet run --web x_ray_flet.py          # opens in browser

Features:
  - Native Material 3 desktop app (Flutter engine)
  - Light / Dark mode toggle
  - Multi-language support (EN, RO, ES, FR, DE)
  - First-run onboarding stepper
  - Animated progress screen with file counter & ETA
  - All scan tabs: Smells, Duplicates, Lint, Security, Rustify
  - Heatmap, Complexity, Auto-Rustify Pipeline tabs
  - JSON + Markdown export
  - One-click Ruff auto-fix
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import textwrap
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import flet as ft

# ── Ensure project root is importable ────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.types import FunctionRecord, ClassRecord, SmellIssue
from Core.config import __version__, SMELL_THRESHOLDS
from Core.i18n import t, set_locale, get_locale, LOCALES
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import compute_grade
from Analysis.rust_advisor import RustAdvisor
from Analysis.smart_graph import SmartGraph

import ast
import concurrent.futures

# ── Conditional imports for auto-rustify ─────────────────────────────────────
try:
    from Analysis.auto_rustify import (
        RustifyPipeline, detect_system,
        py_type_to_rust as _py_type_to_rust,
        _translate_body,
    )
    HAS_AUTO_RUSTIFY = True
except ImportError:
    HAS_AUTO_RUSTIFY = False


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME ENGINE  —  Dynamic Light / Dark
# ═══════════════════════════════════════════════════════════════════════════════

MONO_FONT = "Cascadia Code, Consolas, SF Mono, monospace"

GRADE_COLORS = {
    "A+": "#00c853", "A": "#00c853", "A-": "#00e676",
    "B+": "#64dd17", "B": "#aeea00", "B-": "#ffd600",
    "C+": "#ffab00", "C": "#ff6d00", "C-": "#ff3d00",
    "D+": "#dd2c00", "D": "#d50000", "D-": "#b71c1c",
    "F": "#880e4f",
}

SEV_ICONS  = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
SEV_COLORS = {"critical": ft.Colors.RED_400, "warning": ft.Colors.AMBER_400,
              "info": ft.Colors.GREEN_400}


class TH:
    """Dynamic theme — call TH.x() to get current palette value."""

    _dark = True

    _DARK = dict(
        accent="#00d4ff", accent2="#7c4dff",
        bg="#0a0e14", card="#141820", surface="#0f1319",
        border="#ffffff12", text="#e6edf3", dim="#8b949e",
        muted="#484f58", code_bg="#0d1117", sidebar="#0f1319",
        shadow="#00000040", divider="#ffffff0a",
        bar_bg="#ffffff08", chip="#141820",
    )
    _LIGHT = dict(
        accent="#0078d4", accent2="#5b2fb0",
        bg="#f6f8fa", card="#ffffff", surface="#f0f2f5",
        border="#d0d7de", text="#1f2328", dim="#656d76",
        muted="#8b949e", code_bg="#f6f8fa", sidebar="#ffffff",
        shadow="#0000001a", divider="#d8dee4",
        bar_bg="#0000000a", chip="#f0f2f5",
    )

    @classmethod
    def _p(cls): return cls._DARK if cls._dark else cls._LIGHT

    @classmethod
    def is_dark(cls): return cls._dark
    @classmethod
    def toggle(cls): cls._dark = not cls._dark
    @classmethod
    def set_dark(cls, v: bool): cls._dark = v

    # colour accessors ────────────────────────────────────────────────────
    @classmethod
    def accent(cls):   return cls._p()["accent"]
    @classmethod
    def accent2(cls):  return cls._p()["accent2"]
    @classmethod
    def bg(cls):       return cls._p()["bg"]
    @classmethod
    def card(cls):     return cls._p()["card"]
    @classmethod
    def surface(cls):  return cls._p()["surface"]
    @classmethod
    def border(cls):   return cls._p()["border"]
    @classmethod
    def text(cls):     return cls._p()["text"]
    @classmethod
    def dim(cls):      return cls._p()["dim"]
    @classmethod
    def muted(cls):    return cls._p()["muted"]
    @classmethod
    def code_bg(cls):  return cls._p()["code_bg"]
    @classmethod
    def sidebar(cls):  return cls._p()["sidebar"]
    @classmethod
    def shadow(cls):   return cls._p()["shadow"]
    @classmethod
    def divider(cls):  return cls._p()["divider"]
    @classmethod
    def bar_bg(cls):   return cls._p()["bar_bg"]
    @classmethod
    def chip(cls):     return cls._p()["chip"]


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

def glass_card(content, padding=20, expand=False, **kw):
    return ft.Container(
        content=content, bgcolor=TH.card(),
        border=ft.Border.all(1, TH.border()), border_radius=16,
        padding=padding, expand=expand,
        shadow=ft.BoxShadow(blur_radius=8, color=TH.shadow()), **kw)


def metric_tile(icon: str, value, label: str, color=None):
    color = color or TH.accent()
    return ft.Container(
        content=ft.Column([
            ft.Text(icon, size=24, text_align=ft.TextAlign.CENTER),
            ft.Text(str(value), size=20, weight=ft.FontWeight.BOLD,
                    color=color, font_family=MONO_FONT,
                    text_align=ft.TextAlign.CENTER),
            ft.Text(label, size=10, color=TH.dim(),
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        bgcolor=TH.card(), border=ft.Border.all(1, TH.border()),
        border_radius=14,
        padding=ft.Padding.symmetric(vertical=14, horizontal=10),
        expand=True,
        shadow=ft.BoxShadow(blur_radius=6, color=TH.shadow()))


def section_title(text: str, icon: str = ""):
    return ft.Text(f"{icon}  {text}" if icon else text,
                   size=15, weight=ft.FontWeight.BOLD,
                   color=TH.accent(), font_family=MONO_FONT)


def sev_badge(severity: str):
    icon = SEV_ICONS.get(severity, "❓")
    color = SEV_COLORS.get(severity, ft.Colors.GREY_400)
    return ft.Container(
        content=ft.Text(icon, size=14),
        bgcolor=ft.Colors.with_opacity(0.15, color),
        border_radius=6, padding=ft.Padding.symmetric(4, 6))


# ═══════════════════════════════════════════════════════════════════════════════
#  BAR CHART (pure Flet — no Plotly needed)
# ═══════════════════════════════════════════════════════════════════════════════

def bar_row(label: str, count: int, max_count: int, color: str):
    pct = count / max(max_count, 1)
    return ft.Row([
        ft.Text(label, size=12, width=160, font_family=MONO_FONT,
                color=TH.dim(), no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS),
        ft.Container(
            content=ft.Container(bgcolor=color, border_radius=4,
                                 width=max(4, pct * 400), height=14),
            bgcolor=TH.bar_bg(), border_radius=4, width=400, height=14,
            clip_behavior=ft.ClipBehavior.HARD_EDGE),
        ft.Text(str(count), size=12, weight=ft.FontWeight.BOLD,
                font_family=MONO_FONT, width=50, color=TH.text()),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def bar_chart(items: list, label_width=160):
    """items = list of (label, count, color)"""
    if not items:
        return ft.Container()
    mx = max(c for _, c, _ in items) if items else 1
    return ft.Column([bar_row(l, c, mx, col) for l, c, col in items],
                     spacing=4)


# ═══════════════════════════════════════════════════════════════════════════════
#  SCAN ENGINE  (reused from x_ray_ui.py logic)
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_codebase(root: Path, exclude: List[str], progress_cb=None):
    """Parse all .py files. Returns (funcs, classes, errors, file_count).
    progress_cb(files_done, total_files, current_file) is called per file."""
    py_files = collect_py_files(root, exclude or None)
    total = len(py_files)
    funcs, classes, errors = [], [], []
    done = [0]

    def _parse_one(f):
        fn, cl, err = extract_functions_from_file(f, root)
        done[0] += 1
        if progress_cb:
            progress_cb(done[0], total, str(f))
        return fn, cl, err, f

    with concurrent.futures.ThreadPoolExecutor() as pool:
        futs = [pool.submit(_parse_one, f) for f in py_files]
        for fut in concurrent.futures.as_completed(futs):
            fn, cl, err, fpath = fut.result()
            funcs.extend(fn)
            classes.extend(cl)
            if err:
                errors.append(f"{fpath}: {err}")
    return funcs, classes, errors, total


def _run_scan(root: Path, modes: Dict[str, bool],
              exclude: List[str], thresholds: Dict[str, int],
              progress_cb=None) -> Dict[str, Any]:
    """Run the full scan pipeline.
    progress_cb(frac, label, files_done, total_files, eta_secs)"""
    results: Dict[str, Any] = {"meta": {}}
    t0 = time.time()

    need_ast = (modes.get("smells") or modes.get("duplicates")
                or modes.get("rustify"))
    functions, classes, errors, file_count = [], [], [], 0

    if need_ast:
        parse_t0 = time.time()

        def _parse_progress(done, total, current_file):
            elapsed = time.time() - parse_t0
            rate = done / max(elapsed, 0.01)
            remaining = total - done
            eta = remaining / rate if rate > 0 else 0
            frac = 0.05 + (done / max(total, 1)) * 0.35
            short = (current_file if len(current_file) <= 50
                     else "…" + current_file[-47:])
            if progress_cb:
                progress_cb(frac, f"Parsing {short}",
                            done, total, eta)

        functions, classes, errors, file_count = _scan_codebase(
            root, exclude, progress_cb=_parse_progress)

    results["meta"].update(files=file_count, functions=len(functions),
                           classes=len(classes), errors=len(errors),
                           error_list=errors[:20])

    if need_ast:
        code_map = {}
        for fn in functions:
            code_map[f"{fn.file_path}:{fn.line_start}"] = fn.code
            code_map[fn.key] = fn.code
        results["_code_map"] = code_map
        results["_functions"] = functions

    step, total_steps = 0, sum(1 for v in modes.values() if v)

    def _phase_frac():
        return 0.4 + (step / max(total_steps, 1)) * 0.55

    if modes.get("smells"):
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), "Detecting code smells…",
                        0, 0, -1)
        det = CodeSmellDetector(thresholds=thresholds)
        smells = det.detect(functions, classes)
        results["smells"] = det.summary()
        results["_smell_issues"] = smells

    if modes.get("duplicates"):
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), "Finding duplicates…", 0, 0, -1)
        finder = DuplicateFinder()
        finder.find(functions)
        results["duplicates"] = finder.summary()
        results["_dup_groups"] = finder.groups

    if modes.get("lint"):
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), "Running Ruff lint…", 0, 0, -1)
        try:
            from Core.scan_phases import run_lint_phase
            linter, lint_issues = run_lint_phase(root,
                                                 exclude=exclude or None)
            if linter:
                results["lint"] = linter.summary(lint_issues)
                results["_lint_issues"] = lint_issues
            else:
                results["lint"] = {"error": "Ruff not installed"}
        except Exception as e:
            results["lint"] = {"error": str(e)}

    if modes.get("security"):
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), "Running Bandit security…",
                        0, 0, -1)
        try:
            from Core.scan_phases import run_security_phase
            sec, sec_issues = run_security_phase(root,
                                                 exclude=exclude or None)
            if sec:
                results["security"] = sec.summary(sec_issues)
                results["_sec_issues"] = sec_issues
            else:
                results["security"] = {"error": "Bandit not installed"}
        except Exception as e:
            results["security"] = {"error": str(e)}

    if modes.get("rustify"):
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), "Scoring Rust candidates…",
                        0, 0, -1)
        advisor = RustAdvisor()
        candidates = advisor.score(functions)
        results["rustify"] = {
            "total_scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "top_score": candidates[0].score if candidates else 0,
        }
        results["_rust_candidates"] = candidates

    results["grade"] = compute_grade(results)
    results["meta"]["duration"] = round(time.time() - t0, 2)
    if progress_cb:
        progress_cb(1.0, "Done!", 0, 0, 0)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  RUST SKETCH GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_rust_sketch(func: FunctionRecord) -> str:
    if not HAS_AUTO_RUSTIFY:
        return f"// auto_rustify not available\nfn {func.name}() {{ todo!() }}"
    try:
        tree = ast.parse(textwrap.dedent(func.code))
        fn_node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
            None)
        if fn_node is None:
            return f"// Could not parse {func.name}"
        params = []
        for arg in fn_node.args.args:
            if arg.arg == "self":
                continue
            rtype = (_py_type_to_rust(ast.unparse(arg.annotation))
                     if arg.annotation else "PyObject")
            params.append(f"{arg.arg}: {rtype}")
        ret = ""
        if fn_node.returns:
            ret = f" -> {_py_type_to_rust(ast.unparse(fn_node.returns))}"
        body = _translate_body(fn_node, "    ")
        kw = "async " if isinstance(fn_node, ast.AsyncFunctionDef) else ""
        sig = f"{kw}fn {func.name}({', '.join(params)}){ret}"
        return f"pub {sig} {{\n{body}\n}}"
    except Exception:
        return f"// Transpiler error for {func.name}\ntodo!()"


# ═══════════════════════════════════════════════════════════════════════════════
#  MARKDOWN REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_markdown_report(results: Dict[str, Any]) -> str:
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    lines = [
        "# X-Ray Code Quality Report", "",
        f"**Score:** {grade.get('score', '?')}/100  "
        f"**Grade:** {grade.get('letter', '?')}", "",
        "| Metric | Value |", "|--------|-------|",
        f"| Files | {meta.get('files', 0)} |",
        f"| Functions | {meta.get('functions', 0)} |",
        f"| Classes | {meta.get('classes', 0)} |",
        f"| Duration | {meta.get('duration', 0):.1f}s |", "",
    ]
    for key, title in [("smells", "Code Smells"), ("lint", "Lint"),
                        ("security", "Security"),
                        ("duplicates", "Duplicates")]:
        data = results.get(key, {})
        if data and not data.get("error"):
            lines.append(f"## {title}")
            for k, v in data.items():
                if not k.startswith("_") and k not in ("error",):
                    lines.append(f"- {k}: {v}")
            lines.append("")
    lines.append(f"---\n*Generated by X-Ray v{__version__}*")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB RENDERERS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_smells_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("smells", {})
    issues: list = results.get("_smell_issues", [])
    code_map = results.get("_code_map", {})

    if not issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=16),
            padding=20)

    metrics = ft.Row([
        metric_tile("📊", summary.get("total", 0), t("total")),
        metric_tile("🔴", summary.get("critical", 0), t("critical"),
                    ft.Colors.RED_400),
        metric_tile("🟡", summary.get("warning", 0), t("warning"),
                    ft.Colors.AMBER_400),
        metric_tile("🟢", summary.get("info", 0), t("info"),
                    ft.Colors.GREEN_400),
    ], spacing=8)

    by_cat = summary.get("by_category", {})
    cat_chart = ft.Container()
    if by_cat:
        cat_data = sorted(by_cat.items(), key=lambda x: -x[1])
        cat_chart = ft.Column([
            section_title(t("by_category"), "📂"),
            bar_chart([(c, n, "#ff6b6b") for c, n in cat_data[:12]])
        ], spacing=8)

    issue_tiles = []
    for s in sorted(issues,
                    key=lambda x: (0 if x.severity == "critical" else
                                   1 if x.severity == "warning" else 2)
                    )[:80]:
        icon = SEV_ICONS.get(s.severity, "❓")
        code = code_map.get(f"{s.file_path}:{s.line}", "")
        tile_controls = [
            ft.Text(f"{t('issue')}: {s.message}",
                    weight=ft.FontWeight.BOLD, size=13),
        ]
        if s.suggestion:
            tile_controls.append(
                ft.Text(f"{t('fix')}: {s.suggestion}",
                        color=ft.Colors.BLUE_200, size=12))
        if code:
            tile_controls.append(ft.Container(
                content=ft.Text(code[:500], font_family=MONO_FONT, size=11,
                                color=TH.dim(), selectable=True,
                                no_wrap=False),
                bgcolor=TH.code_bg(), border_radius=8, padding=10,
                margin=ft.Margin.only(top=6)))
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"{icon} [{s.category}] {s.name}", size=13),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=11,
                             italic=True, color=TH.muted()),
            controls=[ft.Container(
                content=ft.Column(tile_controls), padding=15,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text()),
                border_radius=8)],
            initially_expanded=False))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider(), height=30),
        cat_chart,
        ft.Divider(color=TH.divider(), height=20),
        section_title(t("all_issues"), "📋"),
        ft.ListView(controls=issue_tiles, expand=True, spacing=4,
                    padding=5, auto_scroll=False),
    ], spacing=10, expand=True)


def _build_duplicates_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("duplicates", {})
    groups = results.get("_dup_groups", [])
    code_map = results.get("_code_map", {})

    if not groups:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=16),
            padding=20)

    metrics = ft.Row([
        metric_tile("📋", summary.get("total_groups", 0), t("groups")),
        metric_tile("🎯", summary.get("exact_duplicates", 0), t("exact")),
        metric_tile("≈", summary.get("near_duplicates", 0), t("near")),
        metric_tile("🧠", summary.get("semantic_duplicates", 0),
                    t("semantic")),
    ], spacing=8)

    group_tiles = []
    for g in groups[:50]:
        sim_pct = f"{g.avg_similarity:.0%}"
        func_names = ", ".join(f.get("name", "?")
                               for f in g.functions[:3])
        controls = []
        if g.merge_suggestion:
            controls.append(ft.Container(
                content=ft.Text(f"💡 {g.merge_suggestion}", size=12,
                                italic=True),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_200),
                padding=10, border_radius=6))
        for f in g.functions:
            loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
            code = code_map.get(
                loc, code_map.get(f.get("key", ""), ""))
            controls.append(ft.Column([
                ft.Text(f"📄 {loc} — {f.get('name', '?')} "
                        f"({f.get('size', '?')} lines)",
                        size=12, font_family=MONO_FONT,
                        color=TH.accent()),
                ft.Container(
                    content=ft.Text(code[:400] if code else "N/A",
                                    font_family=MONO_FONT, size=11,
                                    selectable=True, color=TH.dim(),
                                    no_wrap=False),
                    bgcolor=TH.code_bg(), border_radius=8,
                    padding=10) if code else ft.Container(),
            ], spacing=4))
        group_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"Group {g.group_id} — {g.similarity_type}"
                          f" ({sim_pct})", size=13),
            subtitle=ft.Text(func_names, size=11, color=TH.muted()),
            controls=[ft.Container(
                content=ft.Column(controls, spacing=8), padding=12)]))

    return ft.Column([
        metrics,
        metric_tile("🔗", summary.get("total_functions_involved", 0),
                    t("involved")),
        ft.Divider(color=TH.divider(), height=20),
        ft.ListView(controls=group_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_lint_tab(results: Dict[str, Any],
                    page: ft.Page) -> ft.Control:
    summary = results.get("lint", {})
    issues = results.get("_lint_issues", [])

    if summary.get("error"):
        return ft.Text(f"⚠️ {summary['error']}",
                       color=ft.Colors.AMBER_400)
    if not issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=16),
            padding=20)

    metrics = ft.Row([
        metric_tile("📊", summary.get("total", 0), t("total")),
        metric_tile("🔴", summary.get("critical", 0), t("critical"),
                    ft.Colors.RED_400),
        metric_tile("🟡", summary.get("warning", 0), t("warning"),
                    ft.Colors.AMBER_400),
        metric_tile("🔧", summary.get("fixable", 0), t("auto_fixable"),
                    TH.accent2()),
    ], spacing=8)

    fix_result = ft.Text("", size=12)

    def on_auto_fix(e):
        scan_path = results.get("_scan_path", "")
        if not scan_path:
            fix_result.value = "No scan path available"
            page.update()
            return
        try:
            r = subprocess.run(["ruff", "check", "--fix", scan_path],
                               capture_output=True, text=True, timeout=60)
            fix_result.value = f"✅ Auto-fix done! {r.stdout.strip()}"
            fix_result.color = ft.Colors.GREEN_400
        except FileNotFoundError:
            fix_result.value = "❌ Ruff not found"
            fix_result.color = ft.Colors.RED_400
        except subprocess.TimeoutExpired:
            fix_result.value = "❌ Timed out"
            fix_result.color = ft.Colors.RED_400
        page.update()

    fix_btn = ft.Container()
    if summary.get("fixable", 0) > 0:
        fix_btn = ft.Row([
            ft.Button(
                f"🔧 {t('auto_fix')} ({summary['fixable']})",
                on_click=on_auto_fix, bgcolor=TH.accent2(),
                color=ft.Colors.WHITE),
            fix_result,
        ], spacing=12)

    by_rule = summary.get("by_rule", {})
    rule_chart = ft.Container()
    if by_rule:
        top_rules = sorted(by_rule.items(), key=lambda x: -x[1])[:10]
        rule_chart = ft.Column([
            section_title("Top Rules", "📊"),
            bar_chart([(r, c, "#ff9800") for r, c in top_rules])
        ], spacing=8)

    issue_tiles = []
    for s in issues[:100]:
        icon = SEV_ICONS.get(s.severity, "❓")
        fix_tag = " 🔧" if getattr(s, "fixable", False) else ""
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(
                f"{icon} [{getattr(s, 'rule_code', 'LINT')}] "
                f"{s.message[:80]}{fix_tag}", size=12),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=11,
                             color=TH.muted()),
            controls=[ft.Container(
                content=ft.Column([
                    ft.Text(f"{t('issue')}: {s.message}",
                            weight=ft.FontWeight.BOLD, size=12),
                    ft.Text(f"{t('fix')}: {s.suggestion}", size=12,
                            color=ft.Colors.BLUE_200)
                    if s.suggestion else ft.Container(),
                ]), padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text()),
                border_radius=8)]))

    return ft.Column([
        metrics, fix_btn,
        ft.Divider(color=TH.divider(), height=20),
        rule_chart,
        ft.Divider(color=TH.divider(), height=20),
        section_title(t("all_issues"), "📋"),
        ft.ListView(controls=issue_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_security_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("security", {})
    issues = results.get("_sec_issues", [])

    if summary.get("error"):
        return ft.Text(f"⚠️ {summary['error']}",
                       color=ft.Colors.AMBER_400)
    if not issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=16),
            padding=20)

    metrics = ft.Row([
        metric_tile("🛡️", summary.get("total", 0), t("total")),
        metric_tile("🔴", summary.get("critical", 0), "High",
                    ft.Colors.RED_400),
        metric_tile("🟡", summary.get("warning", 0), "Medium",
                    ft.Colors.AMBER_400),
    ], spacing=8)

    issue_tiles = []
    for s in issues[:100]:
        sev = s.severity
        icon = SEV_ICONS.get(sev, "❓")
        ctrls = [ft.Text(f"{t('issue')}: {s.message}",
                         weight=ft.FontWeight.BOLD, size=12)]
        if s.suggestion:
            ctrls.append(ft.Text(f"{t('fix')}: {s.suggestion}", size=12,
                                 color=ft.Colors.BLUE_200))
        if getattr(s, "confidence", ""):
            ctrls.append(ft.Text(f"Confidence: {s.confidence}", size=11,
                                 color=TH.muted()))
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(
                f"{icon} [{getattr(s, 'rule_code', '?')}] "
                f"{s.message[:70]}", size=12),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=11,
                             color=TH.muted()),
            leading=ft.Icon(
                ft.Icons.SECURITY,
                color=SEV_COLORS.get(sev, ft.Colors.GREY_400)),
            controls=[ft.Container(
                content=ft.Column(ctrls), padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text()),
                border_radius=8)]))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider(), height=20),
        section_title(t("all_issues"), "🔒"),
        ft.ListView(controls=issue_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_rustify_tab(results: Dict[str, Any]) -> ft.Control:
    candidates = results.get("_rust_candidates", [])
    summary = results.get("rustify", {})
    code_map = results.get("_code_map", {})

    if not candidates:
        return ft.Text("No Rustify candidates. "
                       "Need functions with 5+ lines.",
                       color=TH.dim())

    metrics = ft.Row([
        metric_tile("🦀", summary.get("total_scored", 0), t("scored")),
        metric_tile("✅", summary.get("pure_count", 0), t("pure"),
                    ft.Colors.GREEN_400),
        metric_tile("🏆", summary.get("top_score", 0), t("top_score"),
                    TH.accent()),
        metric_tile("⚠️",
                    summary.get("total_scored", 0) -
                    summary.get("pure_count", 0),
                    t("impure"), ft.Colors.RED_400),
    ], spacing=8)

    cand_tiles = []
    for rank, cand in enumerate(candidates[:30], 1):
        fn = cand.func
        purity = "🟢 Pure" if cand.is_pure else "🔴 Impure"
        code = code_map.get(f"{fn.file_path}:{fn.line_start}",
                            code_map.get(fn.key, ""))
        rust_code = _generate_rust_sketch(fn) if code else "// No source"

        ctrls = [
            ft.Row([
                ft.Text(f"Score: {cand.score}",
                        weight=ft.FontWeight.BOLD,
                        color=TH.accent()),
                ft.Text(f"| {purity}", size=12),
                ft.Text(f"| CC={fn.complexity}", size=12,
                        color=TH.dim()),
                ft.Text(f"| {fn.size_lines} lines", size=12,
                        color=TH.dim()),
            ], spacing=8),
            ft.Text(f"📄 {fn.file_path}:{fn.line_start}", size=11,
                    color=TH.muted()),
        ]
        if cand.reason:
            ctrls.append(ft.Text(f"💡 {cand.reason}", size=11,
                                 italic=True,
                                 color=ft.Colors.AMBER_200))

        if code:
            ctrls.append(ft.Row([
                ft.Column([
                    ft.Text("🐍 Python", size=11,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.AMBER_300),
                    ft.Container(
                        content=ft.Text(code[:600],
                                        font_family=MONO_FONT,
                                        size=10, selectable=True,
                                        color=TH.dim(),
                                        no_wrap=False),
                        bgcolor=TH.code_bg(), border_radius=8,
                        padding=10, expand=True),
                ], expand=True, spacing=4),
                ft.Column([
                    ft.Text("🦀 Rust", size=11,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.CYAN_200),
                    ft.Container(
                        content=ft.Text(rust_code[:600],
                                        font_family=MONO_FONT,
                                        size=10, selectable=True,
                                        color=TH.dim(),
                                        no_wrap=False),
                        bgcolor=TH.code_bg(), border_radius=8,
                        padding=10, expand=True),
                ], expand=True, spacing=4),
            ], spacing=12, expand=True))

        cand_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"#{rank}  {fn.name}", size=13,
                          weight=ft.FontWeight.BOLD),
            subtitle=ft.Text(
                f"Score: {cand.score} | {purity} | CC={fn.complexity}",
                size=11),
            leading=ft.Icon(
                ft.Icons.BOLT,
                color=(ft.Colors.GREEN_400 if cand.score > 20
                       else TH.accent())),
            controls=[ft.Container(
                content=ft.Column(ctrls, spacing=6), padding=12)]))

    # Score distribution
    buckets = {"0-5": 0, "5-10": 0, "10-15": 0,
               "15-20": 0, "20-25": 0, "25+": 0}
    bucket_colors = {"0-5": "#ff5722", "5-10": "#ff5722",
                     "10-15": "#ffd600", "15-20": "#ffd600",
                     "20-25": "#00c853", "25+": "#00c853"}
    for c in candidates:
        s = c.score
        bk = ("25+" if s >= 25 else "20-25" if s >= 20
              else "15-20" if s >= 15 else "10-15" if s >= 10
              else "5-10" if s >= 5 else "0-5")
        buckets[bk] += 1

    dist = ft.Column([
        section_title("Score Distribution", "📊"),
        bar_chart([(k, v, bucket_colors[k])
                   for k, v in buckets.items()])
    ], spacing=8)

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider(), height=20),
        section_title(
            f"🏆 Top Rust Candidates ({min(30, len(candidates))})",
            ""),
        ft.ListView(controls=cand_tiles, expand=True, spacing=4,
                    auto_scroll=False),
        ft.Divider(color=TH.divider(), height=20),
        dist,
    ], spacing=10, expand=True)


def _build_heatmap_tab(results: Dict[str, Any]) -> ft.Control:
    file_issues: Counter = Counter()
    sources = [("_smell_issues", "smells"), ("_lint_issues", "lint"),
               ("_sec_issues", "security")]
    for key, cat in sources:
        for s in results.get(key, []):
            file_issues[s.file_path] += 1

    if not file_issues:
        return ft.Text(f"✅ {t('no_issues')}",
                       color=ft.Colors.GREEN_400, size=16)

    ranked = file_issues.most_common(30)
    mx = ranked[0][1] if ranked else 1

    tiles = []
    for fpath, total in ranked:
        pct = total / mx
        color = ("#d50000" if pct > 0.75 else "#ff6d00" if pct > 0.5
                 else "#ffab00" if pct > 0.25 else "#00c853")
        display = fpath if len(fpath) <= 55 else "…" + fpath[-52:]
        tiles.append(ft.Container(
            content=ft.Row([
                ft.Text(f"🔥 {display}", size=12,
                        font_family=MONO_FONT,
                        color=TH.dim(), expand=True,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Container(
                    content=ft.Container(bgcolor=color,
                                         border_radius=3,
                                         width=max(4, pct * 200),
                                         height=12),
                    bgcolor=TH.bar_bg(), border_radius=3, width=200,
                    height=12,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE),
                ft.Text(str(total), size=12,
                        weight=ft.FontWeight.BOLD,
                        font_family=MONO_FONT, width=40, color=color),
            ], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(6, 10),
            border=ft.Border.only(left=ft.BorderSide(3, color)),
            bgcolor=TH.card(), border_radius=8,
            margin=ft.Margin.only(bottom=4)))

    total_issues = sum(file_issues.values())
    return ft.Column([
        section_title(t("worst_files"), "🔥"),
        ft.Text(f"{total_issues} {t('issues_across')} "
                f"{len(file_issues)} {t('files')}",
                size=12, color=TH.muted()),
        ft.ListView(controls=tiles, expand=True, spacing=2,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_complexity_tab(results: Dict[str, Any]) -> ft.Control:
    functions: list = results.get("_functions", [])
    if not functions:
        return ft.Text("No functions available. "
                       "Enable Smells or Duplicates.",
                       color=TH.dim())

    complexities = [f.complexity for f in functions]
    sizes = [f.size_lines for f in functions]
    avg_cc = sum(complexities) / len(complexities) if complexities else 0
    max_cc = max(complexities) if complexities else 0
    med_cc = (sorted(complexities)[len(complexities) // 2]
              if complexities else 0)
    avg_sz = sum(sizes) / len(sizes) if sizes else 0

    metrics = ft.Row([
        metric_tile("📊", f"{avg_cc:.1f}", t("avg_complexity")),
        metric_tile("🔥", max_cc, t("max_complexity"),
                    ft.Colors.RED_400),
        metric_tile("📐", med_cc, "Median CC"),
        metric_tile("📏", f"{avg_sz:.0f}", "Avg Size"),
    ], spacing=8)

    cc_buckets = {"1-3": 0, "4-7": 0, "8-14": 0,
                  "15-24": 0, "25+": 0}
    cc_colors = {"1-3": "#00c853", "4-7": "#64dd17", "8-14": "#ffd600",
                 "15-24": "#ff6d00", "25+": "#d50000"}
    for cc in complexities:
        b = ("25+" if cc >= 25 else "15-24" if cc >= 15
             else "8-14" if cc >= 8 else "4-7" if cc >= 4 else "1-3")
        cc_buckets[b] += 1
    cc_chart = ft.Column([
        section_title(t("cc_distribution"), "📊"),
        bar_chart([(k, v, cc_colors[k]) for k, v in cc_buckets.items()])
    ], spacing=8)

    sz_buckets = {"1-10": 0, "11-25": 0, "26-50": 0,
                  "51-100": 0, "100+": 0}
    sz_colors = {"1-10": "#00c853", "11-25": "#64dd17",
                 "26-50": "#ffd600", "51-100": "#ff6d00",
                 "100+": "#d50000"}
    for s in sizes:
        b = ("100+" if s > 100 else "51-100" if s > 50
             else "26-50" if s > 25 else "11-25" if s > 10 else "1-10")
        sz_buckets[b] += 1
    sz_chart = ft.Column([
        section_title(t("size_distribution"), "📏"),
        bar_chart([(f"{k} lines", v, sz_colors[k])
                   for k, v in sz_buckets.items()])
    ], spacing=8)

    code_map = results.get("_code_map", {})
    top_fns = sorted(functions,
                     key=lambda f: f.complexity, reverse=True)[:15]
    fn_tiles = []
    for fn in top_fns:
        cc_color = ("#d50000" if fn.complexity >= 15
                    else "#ff6d00" if fn.complexity >= 8 else "#ffd600")
        code = code_map.get(f"{fn.file_path}:{fn.line_start}",
                            code_map.get(fn.key, ""))
        fn_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"CC {fn.complexity}  ·  {fn.name}",
                          size=13),
            subtitle=ft.Text(
                f"{fn.file_path}:{fn.line_start} "
                f"({fn.size_lines} lines)",
                size=11, color=TH.muted()),
            leading=ft.Container(
                content=ft.Text(str(fn.complexity), size=14,
                                weight=ft.FontWeight.BOLD,
                                color=cc_color,
                                text_align=ft.TextAlign.CENTER),
                bgcolor=ft.Colors.with_opacity(0.15, cc_color),
                border_radius=8, width=36, height=36,
                alignment=ft.Alignment(0, 0)),
            controls=[ft.Container(
                content=ft.Text(code[:500] if code else "N/A",
                                font_family=MONO_FONT, size=11,
                                selectable=True,
                                color=TH.dim(),
                                no_wrap=False),
                bgcolor=TH.code_bg(), border_radius=8,
                padding=10)] if code else []))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider(), height=20),
        cc_chart,
        ft.Divider(color=TH.divider(), height=20),
        sz_chart,
        ft.Divider(color=TH.divider(), height=20),
        section_title(t("most_complex"), "🔥"),
        ft.ListView(controls=fn_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_auto_rustify_tab(results: Dict[str, Any],
                            page: ft.Page) -> ft.Control:
    if not HAS_AUTO_RUSTIFY:
        return ft.Text("auto_rustify module not available.",
                       color=ft.Colors.AMBER_400)

    sys_profile = detect_system()
    sys_row = ft.Row([
        metric_tile("🖥️", sys_profile.os_name, "OS"),
        metric_tile("🏗️", sys_profile.arch, "Arch"),
        metric_tile("🎯", sys_profile.rust_target.split('-')[0],
                    "Target"),
    ], spacing=8)

    status_text = ft.Text("", size=12, color=TH.dim())
    progress = ft.ProgressBar(width=500, color=TH.accent(),
                              bgcolor=TH.card(),
                              value=0, visible=False)

    def on_run(e):
        scan_path = results.get("_scan_path", "")
        if not scan_path:
            status_text.value = t("select_dir_first")
            page.update()
            return
        progress.visible = True
        status_text.value = "Running pipeline…"
        page.update()
        try:
            def cb(frac, label):
                progress.value = min(frac, 1.0)
                status_text.value = label
                page.update()

            output_dir = Path(scan_path) / "_rustified"
            pipeline = RustifyPipeline(
                project_dir=scan_path,
                output_dir=str(output_dir),
                crate_name="xray_rustified", min_score=5.0,
                max_candidates=30, mode="pyo3")
            report = pipeline.run(progress_cb=cb)
            success = (report.compile_result and
                       report.compile_result.success)
            status_text.value = (
                "✅ Pipeline complete — compiled!" if success
                else "⚠️ Pipeline finished with issues")
            status_text.color = (ft.Colors.GREEN_400 if success
                                 else ft.Colors.AMBER_400)
        except Exception as ex:
            status_text.value = f"❌ Error: {ex}"
            status_text.color = ft.Colors.RED_400
        progress.visible = False
        page.update()

    return ft.Column([
        glass_card(ft.Column([
            ft.Text(f"⚙️ {t('tab_auto_rustify')} Pipeline", size=16,
                    weight=ft.FontWeight.BOLD, font_family=MONO_FONT,
                    color=TH.accent()),
            ft.Text("End-to-end: Scan → Score → Transpile → "
                    "Compile → Verify",
                    size=12, color=TH.muted()),
        ])),
        sys_row,
        ft.Divider(color=TH.divider(), height=20),
        ft.Row([
            ft.Button(f"🚀 {t('run_pipeline')}", on_click=on_run,
                      bgcolor=TH.accent2(),
                      color=ft.Colors.WHITE, height=44),
            status_text,
        ], spacing=12),
        progress,
    ], spacing=10)


# ═══════════════════════════════════════════════════════════════════════════════
#  ONBOARDING DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

def _show_onboarding(page: ft.Page):
    steps = [
        (t("onboard_step1_title"), t("onboard_step1_desc"),
         ft.Icons.FOLDER_OPEN),
        (t("onboard_step2_title"), t("onboard_step2_desc"),
         ft.Icons.CHECKLIST),
        (t("onboard_step3_title"), t("onboard_step3_desc"),
         ft.Icons.PLAY_ARROW_ROUNDED),
    ]
    step_idx = [0]

    title_text = ft.Text(steps[0][0], size=20,
                         weight=ft.FontWeight.BOLD,
                         color=TH.accent())
    desc_text = ft.Text(steps[0][1], size=14, color=TH.dim())
    icon_ctrl = ft.Icon(steps[0][2], size=48, color=TH.accent())
    step_indicator = ft.Text(f"1 / {len(steps)}", size=12,
                             color=TH.muted())

    def _update():
        i = step_idx[0]
        title_text.value = steps[i][0]
        desc_text.value = steps[i][1]
        icon_ctrl.name = steps[i][2]
        step_indicator.value = f"{i + 1} / {len(steps)}"
        back_btn.visible = i > 0
        next_btn.text = (t("onboard_got_it") if i == len(steps) - 1
                         else t("onboard_next"))
        page.update()

    def on_next(e):
        if step_idx[0] >= len(steps) - 1:
            page.pop_dialog()
            return
        step_idx[0] += 1
        _update()

    def on_back(e):
        if step_idx[0] > 0:
            step_idx[0] -= 1
            _update()

    back_btn = ft.TextButton(t("onboard_back"), on_click=on_back,
                             visible=False)
    next_btn = ft.Button(t("onboard_next"), on_click=on_next,
                         bgcolor=TH.accent(),
                         color=ft.Colors.WHITE)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Text(t("onboard_title"), size=22,
                    weight=ft.FontWeight.BOLD, color=TH.accent()),
        ]),
        content=ft.Container(
            content=ft.Column([
                ft.Row([icon_ctrl],
                       alignment=ft.MainAxisAlignment.CENTER),
                title_text, desc_text, step_indicator,
            ], spacing=12,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=420, height=220),
        actions=[back_btn, next_btn],
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    page.show_dialog(dlg)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def main(page: ft.Page):
    # ── Page setup ───────────────────────────────────────────────────────
    page.title = t("app_title")
    page.theme_mode = (ft.ThemeMode.DARK if TH.is_dark()
                       else ft.ThemeMode.LIGHT)
    page.bgcolor = TH.bg()
    page.window.width = 1360
    page.window.height = 880
    page.padding = 0
    page.spacing = 0
    page.fonts = {"mono": "Cascadia Code"}

    # Material 3 seed-color themes
    page.theme = ft.Theme(
        color_scheme_seed=TH.accent(),
        font_family="Segoe UI, Roboto, Helvetica, Arial, sans-serif")
    page.dark_theme = ft.Theme(
        color_scheme_seed=TH.accent(),
        font_family="Segoe UI, Roboto, Helvetica, Arial, sans-serif")

    # ── State (persisted in page.data so theme / lang rebuilds keep it) ──
    page.data = page.data or {}
    if "_state" not in page.data:
        page.data["_state"] = {
            "root_path": "",
            "results": None,
            "exclude": [
                ".venv", "venv", "__pycache__", ".git", "_OLD",
                "node_modules", "target", "build_exe", "build_web",
                "build_desktop", "X_Ray_Desktop", "X_Ray_Standalone",
            ],
            "modes": {
                "smells": True, "duplicates": True, "lint": True,
                "security": True, "rustify": True,
            },
            "thresholds": SMELL_THRESHOLDS.copy(),
        }
    state = page.data["_state"]

    # ── File picker (Service, not overlay) ───────────────────────────────
    file_picker = ft.FilePicker()
    # Avoid appending duplicate services on rebuild
    if not any(isinstance(s, ft.FilePicker) for s in page.services):
        page.services.append(file_picker)

    # Show previously-selected path if we're rebuilding after theme/lang change
    _prev_path = state.get("root_path", "")
    path_text = ft.Text(
        _prev_path if _prev_path else t("no_dir_selected"),
        color=TH.accent() if _prev_path else TH.muted(),
        size=12, italic=not bool(_prev_path), max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS)

    async def pick_directory(e):
        result = await file_picker.get_directory_path(
            dialog_title=t("select_directory"))
        if result:
            state["root_path"] = result
            path_text.value = result
            path_text.color = TH.accent()
            page.update()

    # ── Mode checkboxes ──────────────────────────────────────────────────
    def on_mode(e):
        state["modes"][e.control.data] = e.control.value

    _m = state["modes"]
    mode_checks = ft.Column([
        ft.Checkbox(label=t("smells"), value=_m["smells"],
                    on_change=on_mode, data="smells",
                    fill_color=TH.accent(), check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("duplicates"), value=_m["duplicates"],
                    on_change=on_mode, data="duplicates",
                    fill_color=TH.accent(), check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("lint"), value=_m["lint"],
                    on_change=on_mode, data="lint",
                    fill_color=TH.accent(), check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("security"), value=_m["security"],
                    on_change=on_mode, data="security",
                    fill_color=TH.accent(), check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("rustify"), value=_m["rustify"],
                    on_change=on_mode, data="rustify",
                    fill_color=TH.accent(), check_color=ft.Colors.WHITE),
    ], spacing=0)

    # ── Theme & language pickers ─────────────────────────────────────────
    theme_icon = ft.IconButton(
        icon=(ft.Icons.LIGHT_MODE if TH.is_dark()
              else ft.Icons.DARK_MODE),
        icon_color=TH.accent(),
        tooltip="Toggle Light / Dark",
        icon_size=20)

    def on_theme_toggle(e):
        TH.toggle()
        page.data["_onboarded"] = True
        try:
            page.pop_dialog()
        except Exception:
            pass
        page.controls.clear()
        page.run_task(main, page)

    theme_icon.on_click = on_theme_toggle

    def on_lang_change(e):
        set_locale(e.control.value)
        page.data = page.data or {}
        page.data["_onboarded"] = True
        try:
            page.pop_dialog()
        except Exception:
            pass
        page.controls.clear()
        page.run_task(main, page)

    lang_dd = ft.Dropdown(
        value=get_locale(), width=120, dense=True,
        border_color=TH.border(), color=TH.text(),
        options=[ft.dropdown.Option(key=k, text=f"{v}")
                 for k, v in LOCALES.items()],
        on_select=on_lang_change)

    # ── Progress UI (rich, with ETA) ─────────────────────────────────────
    progress_bar = ft.ProgressBar(width=240, color=TH.accent(),
                                  bgcolor=TH.card(),
                                  value=0, visible=False)
    # Animated spinner
    progress_ring = ft.ProgressRing(width=20, height=20,
                                    stroke_width=2.5,
                                    color=TH.accent(),
                                    visible=False)
    progress_label = ft.Text("", size=12, color=TH.dim(),
                             weight=ft.FontWeight.W_500)
    progress_detail = ft.Text("", size=10, color=TH.muted(),
                              font_family=MONO_FONT)
    progress_eta = ft.Text("", size=10, color=TH.muted(),
                           italic=True)

    # ── Main content area ────────────────────────────────────────────────
    main_content = ft.Column([], expand=True, scroll=ft.ScrollMode.AUTO)

    # ── Build dashboard from scan results ────────────────────────────────
    def build_dashboard(results: Dict[str, Any]):
        grade = results.get("grade", {})
        meta = results.get("meta", {})
        letter = grade.get("letter", "?")
        score = grade.get("score", 0)
        color = GRADE_COLORS.get(letter, "#888")

        # Grade card
        grade_card = ft.Container(
            content=ft.Column([
                ft.Text(letter, size=56, weight=ft.FontWeight.BOLD,
                        color=color,
                        text_align=ft.TextAlign.CENTER,
                        font_family=MONO_FONT),
                ft.Text(f"{score} / 100", size=18,
                        color=ft.Colors.with_opacity(0.8, color),
                        text_align=ft.TextAlign.CENTER),
                ft.Text(t("quality_score").upper(), size=10,
                        color=TH.muted(),
                        text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=2),
            bgcolor=ft.Colors.with_opacity(0.1, color),
            border=ft.Border.all(
                1, ft.Colors.with_opacity(0.4, color)),
            border_radius=16, padding=20, width=190,
            shadow=ft.BoxShadow(
                blur_radius=20,
                color=ft.Colors.with_opacity(0.15, color)),
            animate=ft.Animation(500, ft.AnimationCurve.EASE_OUT))

        # Stats row
        stats = ft.Row([
            metric_tile("📄", meta.get("files", 0), t("files")),
            metric_tile("⚡", meta.get("functions", 0),
                        t("functions")),
            metric_tile("📦", meta.get("classes", 0), t("classes")),
            metric_tile("⏱️", f"{meta.get('duration', 0):.1f}s",
                        t("duration")),
        ], spacing=8, expand=True)

        # Penalty summary
        breakdown = grade.get("breakdown", {})
        penalty_chips = []
        labels_map = {"smells": "🔍 Smells", "duplicates": "📋 Dups",
                      "lint": "🧹 Lint", "security": "🔒 Sec"}
        for k, d in breakdown.items():
            p = d.get("penalty", 0)
            if p > 0:
                penalty_chips.append(ft.Chip(
                    label=ft.Text(
                        f"{labels_map.get(k, k)} -{p:.0f}",
                        size=11, color=TH.text()),
                    bgcolor=TH.chip()))

        header = ft.Row([
            grade_card,
            ft.Column([
                stats,
                (ft.Row(penalty_chips, spacing=6)
                 if penalty_chips else ft.Container()),
            ], expand=True, spacing=10),
        ], spacing=20,
           vertical_alignment=ft.CrossAxisAlignment.START)

        # ── Tabs ─────────────────────────────────────────────────────
        tabs_list = []
        if (results.get("smells")
                and not results["smells"].get("error")):
            tabs_list.append(ft.Tab(
                text=f"🔍 {t('tab_smells')}",
                content=_build_smells_tab(results)))
        if (results.get("duplicates")
                and not results.get("duplicates", {}).get("error")):
            tabs_list.append(ft.Tab(
                text=f"📋 {t('tab_duplicates')}",
                content=_build_duplicates_tab(results)))
        if (results.get("lint")
                and not results.get("lint", {}).get("error")):
            tabs_list.append(ft.Tab(
                text=f"🧹 {t('tab_lint')}",
                content=_build_lint_tab(results, page)))
        if (results.get("security")
                and not results.get("security", {}).get("error")):
            tabs_list.append(ft.Tab(
                text=f"🔒 {t('tab_security')}",
                content=_build_security_tab(results)))
        if results.get("rustify"):
            tabs_list.append(ft.Tab(
                text=f"🦀 {t('tab_rustify')}",
                content=_build_rustify_tab(results)))

        has_issues = (results.get("_smell_issues")
                      or results.get("_lint_issues")
                      or results.get("_sec_issues"))
        if has_issues:
            tabs_list.append(ft.Tab(
                text=f"🔥 {t('tab_heatmap')}",
                content=_build_heatmap_tab(results)))
        if results.get("_functions"):
            tabs_list.append(ft.Tab(
                text=f"📊 {t('tab_complexity')}",
                content=_build_complexity_tab(results)))
            tabs_list.append(ft.Tab(
                text=f"⚙️ {t('tab_auto_rustify')}",
                content=_build_auto_rustify_tab(results, page)))

        result_tabs = ft.Tabs(
            tabs=tabs_list, selected_index=0,
            animation_duration=300, expand=True,
            label_color=TH.accent(),
            unselected_label_color=TH.muted(),
            indicator_color=TH.accent(),
            divider_color=TH.divider())

        # ── Export bar ───────────────────────────────────────────────
        def on_export_json(e):
            export = {k: v for k, v in results.items()
                      if not k.startswith("_")}
            path = Path(state["root_path"]) / "xray_report.json"
            path.write_text(
                json.dumps(export, indent=2, default=str),
                encoding="utf-8")
            sb = ft.SnackBar(
                content=ft.Text(f"📥 Saved to {path}"), open=True)
            page.overlay.append(sb)
            page.update()

        def on_export_md(e):
            md = _build_markdown_report(results)
            path = Path(state["root_path"]) / "xray_report.md"
            path.write_text(md, encoding="utf-8")
            sb = ft.SnackBar(
                content=ft.Text(f"📥 Saved to {path}"), open=True)
            page.overlay.append(sb)
            page.update()

        export_bar = ft.Row([
            ft.Button(f"📥 {t('export_json')}",
                      on_click=on_export_json,
                      bgcolor=TH.card(),
                      color=TH.text()),
            ft.Button(f"📥 {t('export_markdown')}",
                      on_click=on_export_md,
                      bgcolor=TH.card(),
                      color=TH.text()),
        ], spacing=12)

        main_content.controls = [
            ft.Container(
                content=ft.Column([
                    header,
                    ft.Divider(color=TH.divider(), height=30),
                    result_tabs,
                    ft.Divider(color=TH.divider(), height=20),
                    export_bar,
                ], spacing=10, expand=True),
                padding=30, expand=True)
        ]
        page.update()

    # ── Landing page ─────────────────────────────────────────────────────
    def build_landing():
        main_content.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Container(height=50),
                    # Logo area
                    ft.Container(
                        content=ft.Column([
                            ft.Text("🔬", size=56,
                                    text_align=ft.TextAlign.CENTER),
                            ft.Text("X-RAY", size=40,
                                    weight=ft.FontWeight.BOLD,
                                    color=TH.accent(),
                                    font_family=MONO_FONT,
                                    text_align=ft.TextAlign.CENTER),
                            ft.Text(t("app_subtitle"), size=14,
                                    color=TH.muted(),
                                    text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER),
                           spacing=4),
                        animate=ft.Animation(
                            600, ft.AnimationCurve.EASE_OUT)),
                    ft.Container(height=30),
                    # 3-step instruction cards
                    ft.Row([
                        glass_card(ft.Column([
                            ft.Container(
                                content=ft.Icon(ft.Icons.FOLDER_OPEN,
                                                color=TH.accent(),
                                                size=30),
                                bgcolor=ft.Colors.with_opacity(
                                    0.08, TH.accent()),
                                border_radius=12, width=56, height=56,
                                alignment=ft.Alignment(0, 0)),
                            ft.Text("1. Configure",
                                    weight=ft.FontWeight.BOLD,
                                    size=14, color=TH.text()),
                            ft.Text("Set path & analyzers\n"
                                    "in the sidebar", size=11,
                                    color=TH.muted(),
                                    text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER), spacing=8),
                            padding=24, expand=True),
                        glass_card(ft.Column([
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.PLAY_ARROW_ROUNDED,
                                    color=TH.accent2(), size=30),
                                bgcolor=ft.Colors.with_opacity(
                                    0.08, TH.accent2()),
                                border_radius=12, width=56, height=56,
                                alignment=ft.Alignment(0, 0)),
                            ft.Text("2. Scan",
                                    weight=ft.FontWeight.BOLD,
                                    size=14, color=TH.text()),
                            ft.Text(f"Press '{t('scan_start')}'\n"
                                    "to analyze code", size=11,
                                    color=TH.muted(),
                                    text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER), spacing=8),
                            padding=24, expand=True),
                        glass_card(ft.Column([
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.INSIGHTS,
                                    color="#00c853", size=30),
                                bgcolor=ft.Colors.with_opacity(
                                    0.08, "#00c853"),
                                border_radius=12, width=56, height=56,
                                alignment=ft.Alignment(0, 0)),
                            ft.Text("3. Explore",
                                    weight=ft.FontWeight.BOLD,
                                    size=14, color=TH.text()),
                            ft.Text("Browse results in\n"
                                    "interactive tabs", size=11,
                                    color=TH.muted(),
                                    text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=(
                            ft.CrossAxisAlignment.CENTER), spacing=8),
                            padding=24, expand=True),
                    ], spacing=16,
                       alignment=ft.MainAxisAlignment.CENTER),
                    ft.Container(height=30),
                    ft.Text("AST Smells · Ruff Lint · Bandit Security"
                            " · Duplicates · Rust Advisor",
                            size=12, color=TH.muted(),
                            text_align=ft.TextAlign.CENTER),
                    ft.TextButton(
                        "📖 Show Tutorial",
                        on_click=lambda _: _show_onboarding(page)),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=8),
                expand=True, alignment=ft.Alignment(0, 0))
        ]

    # ── Scan handler (with rich progress) ────────────────────────────────
    async def start_scan(e):
        if not state["root_path"]:
            sb = ft.SnackBar(
                content=ft.Text(t("select_dir_first")),
                bgcolor=ft.Colors.RED_400, open=True)
            page.overlay.append(sb)
            page.update()
            return

        # Show rich progress screen
        progress_bar.visible = True
        progress_bar.value = 0
        progress_ring.visible = True
        progress_label.value = t("scanning")
        progress_detail.value = ""
        progress_eta.value = ""

        # Build progress panel in main content
        main_content.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Container(height=80),
                    ft.Text("🔬", size=48,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(t("scanning").upper(), size=22,
                            weight=ft.FontWeight.BOLD,
                            color=TH.accent(),
                            font_family=MONO_FONT,
                            text_align=ft.TextAlign.CENTER),
                    ft.Container(height=20),
                    # Progress ring + label row
                    ft.Row([
                        progress_ring,
                        progress_label,
                    ], spacing=10,
                       alignment=ft.MainAxisAlignment.CENTER),
                    ft.Container(height=8),
                    # File counter
                    progress_detail,
                    # ETA
                    progress_eta,
                    ft.Container(height=12),
                    # Progress bar with percentage
                    ft.Container(
                        content=progress_bar,
                        width=400,
                        alignment=ft.Alignment(0, 0)),
                    ft.Container(height=30),
                    ft.Text("Analyzing Python source code…",
                            size=12, color=TH.muted(), italic=True,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=6),
                expand=True, alignment=ft.Alignment(0, 0))
        ]
        page.update()

        loop = asyncio.get_event_loop()
        scan_t0 = time.time()

        def progress_cb(frac, label, files_done=0, total_files=0,
                        eta_secs=-1):
            progress_bar.value = min(frac, 1.0)
            progress_label.value = label

            if total_files > 0:
                progress_detail.value = (
                    f"📄  {files_done} / {total_files} files")
            else:
                elapsed = time.time() - scan_t0
                progress_detail.value = (
                    f"⏱️  {elapsed:.0f}s elapsed")

            if eta_secs > 0:
                mins = int(eta_secs) // 60
                secs = int(eta_secs) % 60
                if mins > 0:
                    progress_eta.value = (
                        f"⏳  ETA: ~{mins}m {secs:02d}s remaining")
                else:
                    progress_eta.value = (
                        f"⏳  ETA: ~{secs}s remaining")
            elif eta_secs == 0:
                progress_eta.value = ""
            # eta_secs == -1 means unknown, keep current text

            try:
                page.update()
            except Exception:
                pass

        results = await loop.run_in_executor(
            None,
            lambda: _run_scan(
                Path(state["root_path"]), state["modes"],
                state["exclude"], state["thresholds"],
                progress_cb=progress_cb))

        results["_scan_path"] = state["root_path"]
        state["results"] = results

        # Clean up progress
        progress_bar.visible = False
        progress_ring.visible = False
        progress_label.value = ""
        progress_detail.value = ""
        progress_eta.value = ""

        # Show completion summary briefly
        dur = results["meta"].get("duration", 0)
        n_files = results["meta"].get("files", 0)
        n_funcs = results["meta"].get("functions", 0)
        main_content.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Container(height=80),
                    ft.Text("✅", size=56,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(t("scan_complete"), size=22,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREEN_400,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        f"{n_files} {t('files')} · "
                        f"{n_funcs} {t('functions')} · "
                        f"{dur:.1f}s",
                        size=14, color=TH.dim(),
                        text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=8),
                expand=True, alignment=ft.Alignment(0, 0),
                animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT))
        ]
        page.update()

        # Short pause then show dashboard
        await asyncio.sleep(0.8)
        build_dashboard(results)

    # ── Sidebar ──────────────────────────────────────────────────────────
    sidebar = ft.Container(
        content=ft.Column([
            # Logo
            ft.Container(
                content=ft.Column([
                    ft.Text("X-RAY", size=26,
                            weight=ft.FontWeight.BOLD,
                            color=TH.accent(),
                            font_family=MONO_FONT,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(t("app_subtitle").upper(), size=9,
                            color=TH.muted(),
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(f"v{__version__}", size=10,
                            color=TH.muted(),
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=2),
                padding=ft.Padding.only(top=16, bottom=4)),

            # Theme + Language row
            ft.Row([
                theme_icon,
                ft.Icon(ft.Icons.LANGUAGE, size=16,
                        color=TH.muted()),
                lang_dd,
            ], spacing=4,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(color=TH.divider(), height=16),

            # Directory
            ft.Text(t("project_scope").upper(), size=10,
                    weight=ft.FontWeight.BOLD, color=TH.muted()),
            ft.Button(
                t("select_directory"), icon=ft.Icons.FOLDER_OPEN,
                on_click=pick_directory,
                width=260, color=TH.accent(), bgcolor=TH.card()),
            path_text,
            ft.Divider(color=TH.divider(), height=12),

            # Modes
            ft.Text(t("scan_modes").upper(), size=10,
                    weight=ft.FontWeight.BOLD, color=TH.muted()),
            mode_checks,
            ft.Divider(color=TH.divider(), height=12),

            # Scan button
            ft.Button(
                f"⚡ {t('scan_start')}",
                width=260, height=48,
                color=ft.Colors.WHITE,
                bgcolor=TH.accent2(),
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=start_scan),

            ft.Container(height=4),
            ft.Row([progress_ring, progress_label], spacing=6),
            progress_detail,
            progress_eta,

            # Footer
            ft.Container(expand=True),
            ft.Divider(color=TH.divider()),
            ft.Text("AST · Ruff · Bandit · Rust", size=9,
                    color=TH.muted(),
                    text_align=ft.TextAlign.CENTER),
            ft.TextButton(
                "github.com/GeoHaber/X_Ray",
                url="https://github.com/GeoHaber/X_Ray",
                style=ft.ButtonStyle(color=TH.muted())),
        ], scroll=ft.ScrollMode.AUTO, spacing=6),
        width=280, bgcolor=TH.surface(),
        border=ft.Border.only(right=ft.BorderSide(1, TH.border())),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8))

    # ── Layout ───────────────────────────────────────────────────────────
    # If we already have scan results (e.g. after theme/lang toggle), show dashboard
    if state.get("results"):
        build_dashboard(state["results"])
    else:
        build_landing()

    page.add(ft.Row([sidebar, main_content], expand=True, spacing=0))

    # ── First-run onboarding (only once) ─────────────────────────────────
    if not page.data.get("_onboarded"):
        page.data["_onboarded"] = True
        _show_onboarding(page)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ft.run(main)
