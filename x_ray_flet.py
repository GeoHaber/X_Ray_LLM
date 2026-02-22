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
import logging
import subprocess
import sys
import textwrap
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import flet as ft

# ── Ensure project root is importable ────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.types import FunctionRecord  # noqa: E402
from Core.config import __version__, SMELL_THRESHOLDS  # noqa: E402
from Core.i18n import t, set_locale, get_locale, LOCALES  # noqa: E402
from Analysis.ast_utils import extract_functions_from_file, collect_py_files  # noqa: E402
from Analysis.smells import CodeSmellDetector  # noqa: E402
from Analysis.duplicates import DuplicateFinder  # noqa: E402
from Analysis.reporting import compute_grade  # noqa: E402
from Analysis.rust_advisor import RustAdvisor  # noqa: E402

import ast  # noqa: E402
import concurrent.futures  # noqa: E402

logger = logging.getLogger(__name__)

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

# ── Consistent sizing constants ──────────────────────────────────────────────
SZ_XS      = 11   # version numbers, copyright, tiny meta
SZ_SM      = 12   # captions, file paths, code blocks, subtitles
SZ_BODY    = 13   # secondary body, descriptions, meta info
SZ_MD      = 14   # list-item titles, expansion-tile titles, body
SZ_LG      = 15   # card titles, emphasized body
SZ_SECTION = 17   # section headings
SZ_H3      = 18   # panel titles, sub-headings
SZ_H2      = 22   # dialog titles, major headings
SZ_SIDEBAR = 24   # sidebar logo
SZ_HERO    = 34   # landing-page hero title
SZ_DISPLAY = 40   # grade letter, decorative emoji

BTN_H_SM   = 36   # secondary / export buttons
BTN_H_MD   = 40   # normal action buttons
BTN_RADIUS = 10   # consistent border-radius for all buttons

# ── Responsive breakpoints ───────────────────────────────────────────────────
BP_NARROW  = 900   # below this → single-column / drawer sidebar


def _page_width(page: ft.Page) -> int:
    """Return page width, defaulting to narrow-safe value."""
    w = page.width
    return int(w) if w and w > 0 else BP_NARROW - 1  # default → narrow


def is_narrow(page: ft.Page) -> bool:
    """True when viewport is phone-portrait width."""
    return _page_width(page) < BP_NARROW


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


class _THMeta(type):
    """Metaclass: lets TH.accent return a colour string directly (no parens)."""
    _KEYS = frozenset({
        "accent", "accent2", "bg", "card", "surface", "border", "text",
        "dim", "muted", "code_bg", "sidebar", "shadow", "divider",
        "bar_bg", "chip",
    })

    def __getattr__(cls, name: str) -> str:
        if name in cls._KEYS:
            p = cls._DARK if cls._dark else cls._LIGHT
            return p[name]
        raise AttributeError(name)


class TH(metaclass=_THMeta):
    """Dynamic theme — access colours as TH.accent, TH.bg, etc."""

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
    def is_dark(cls) -> bool: return cls._dark
    @classmethod
    def toggle(cls): cls._dark = not cls._dark


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

def _show_snack(page, text: str, bgcolor=None):
    """Show a SnackBar, removing any previous ones to prevent overlay leak."""
    page.overlay[:] = [
        c for c in page.overlay if not isinstance(c, ft.SnackBar)]
    sb = ft.SnackBar(content=ft.Text(text), open=True)
    if bgcolor:
        sb.bgcolor = bgcolor
    page.overlay.append(sb)
    page.update()


def glass_card(content, padding=20, expand=False, **kw):
    return ft.Container(
        content=content, bgcolor=TH.card,
        border=ft.Border.all(1, TH.border), border_radius=16,
        padding=padding, expand=expand,
        shadow=ft.BoxShadow(blur_radius=8, color=TH.shadow), **kw)


def metric_tile(icon: str, value, label: str, color=None):
    color = color or TH.accent
    return ft.Container(
        content=ft.Column([
            ft.Text(icon, size=SZ_H3, text_align=ft.TextAlign.CENTER),
            ft.Text(str(value), size=SZ_SECTION, weight=ft.FontWeight.BOLD,
                    color=color, font_family=MONO_FONT,
                    text_align=ft.TextAlign.CENTER),
            ft.Text(label, size=SZ_BODY, color=TH.dim,
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        bgcolor=TH.card, border=ft.Border.all(1, TH.border),
        border_radius=14,
        padding=ft.Padding.symmetric(vertical=14, horizontal=10),
        expand=True, width=140,
        shadow=ft.BoxShadow(blur_radius=6, color=TH.shadow))


def section_title(text: str, icon: str = ""):
    return ft.Text(f"{icon}  {text}" if icon else text,
                   size=SZ_SECTION, weight=ft.FontWeight.BOLD,
                   color=TH.accent, font_family=MONO_FONT)


# ═══════════════════════════════════════════════════════════════════════════════
#  BAR CHART (pure Flet — no Plotly needed)
# ═══════════════════════════════════════════════════════════════════════════════


def _make_proportional_bar(pct: float, color: str):
    """A bar that fills *pct* of its parent via a Row trick."""
    return ft.Container(
        content=ft.Row([
            ft.Container(bgcolor=color, border_radius=4,
                         expand=round(max(pct, 0.01) * 100),
                         height=14),
            ft.Container(expand=round((1 - pct) * 100), height=14)
            if pct < 1.0 else ft.Container(width=0),
        ], spacing=0),
        bgcolor=TH.bar_bg, border_radius=4, expand=True, height=14,
        clip_behavior=ft.ClipBehavior.HARD_EDGE)


def bar_row_flex(label: str, count: int, max_count: int, color: str):
    """Fully flexible bar row — works at any width."""
    pct = count / max(max_count, 1)
    return ft.Row([
        ft.Text(label, size=SZ_BODY, width=140, font_family=MONO_FONT,
                color=TH.dim, no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS),
        _make_proportional_bar(pct, color),
        ft.Text(str(count), size=SZ_BODY, weight=ft.FontWeight.BOLD,
                font_family=MONO_FONT, width=44, color=TH.text),
    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def bar_chart(items: list):
    """items = list of (label, count, color)"""
    if not items:
        return ft.Container()
    mx = max(c for _, c, _ in items) if items else 1
    return ft.Column([bar_row_flex(lbl, c, mx, col)
                      for lbl, c, col in items],
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


# ── Individual scan phase helpers (keep _run_scan lean) ──────────────────────

def _phase_smells(functions, classes, thresholds, results):
    det = CodeSmellDetector(thresholds=thresholds)
    smells = det.detect(functions, classes)
    results["smells"] = det.summary()
    results["_smell_issues"] = smells


def _phase_duplicates(functions, results):
    finder = DuplicateFinder()
    finder.find(functions)
    results["duplicates"] = finder.summary()
    results["_dup_groups"] = finder.groups


def _phase_lint(root, exclude, results):
    try:
        from Core.scan_phases import run_lint_phase
        linter, lint_issues = run_lint_phase(root, exclude=exclude or None)
        if linter:
            results["lint"] = linter.summary(lint_issues)
            results["_lint_issues"] = lint_issues
        else:
            results["lint"] = {"error": "Ruff not installed"}
    except Exception as exc:
        results["lint"] = {"error": str(exc)}


def _phase_security(root, exclude, results):
    try:
        from Core.scan_phases import run_security_phase
        sec, sec_issues = run_security_phase(root, exclude=exclude or None)
        if sec:
            results["security"] = sec.summary(sec_issues)
            results["_sec_issues"] = sec_issues
        else:
            results["security"] = {"error": "Bandit not installed"}
    except Exception as exc:
        results["security"] = {"error": str(exc)}


def _phase_rustify(functions, results):
    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    results["rustify"] = {
        "total_scored": len(candidates),
        "pure_count": sum(1 for c in candidates if c.is_pure),
        "top_score": candidates[0].score if candidates else 0,
    }
    results["_rust_candidates"] = candidates


def _phase_ui_compat(root, exclude, results):
    try:
        from Analysis.ui_compat import UICompatAnalyzer
        analyzer = UICompatAnalyzer()
        raw_issues = analyzer.analyze(root, exclude=exclude or None)
        smell_issues = [i.to_smell() for i in raw_issues]
        results["ui_compat"] = analyzer.summary(raw=raw_issues)
        results["_ui_compat_issues"] = smell_issues
        results["_ui_compat_raw"] = raw_issues
    except Exception as exc:
        results["ui_compat"] = {"error": str(exc)}


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

    # Dispatch table: (mode_key, progress_label, runner_callable)
    _phases = [
        ("smells", "Detecting code smells…",
         lambda: _phase_smells(functions, classes, thresholds, results)),
        ("duplicates", "Finding duplicates…",
         lambda: _phase_duplicates(functions, results)),
        ("lint", "Running Ruff lint…",
         lambda: _phase_lint(root, exclude, results)),
        ("security", "Running Bandit security…",
         lambda: _phase_security(root, exclude, results)),
        ("rustify", "Scoring Rust candidates…",
         lambda: _phase_rustify(functions, results)),
        ("ui_compat", "Checking UI API compatibility…",
         lambda: _phase_ui_compat(root, exclude, results)),
    ]
    for mode_key, label, runner in _phases:
        if not modes.get(mode_key):
            continue
        step += 1
        if progress_cb:
            progress_cb(_phase_frac(), label, 0, 0, -1)
        runner()

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
                            color=ft.Colors.GREEN_400, size=SZ_LG),
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
                    weight=ft.FontWeight.BOLD, size=SZ_MD),
        ]
        if s.suggestion:
            tile_controls.append(
                ft.Text(f"{t('fix')}: {s.suggestion}",
                        color=ft.Colors.BLUE_200, size=SZ_BODY))
        if code:
            tile_controls.append(ft.Container(
                content=ft.Text(code[:500], font_family=MONO_FONT, size=SZ_SM,
                                color=TH.dim, selectable=True,
                                no_wrap=False),
                bgcolor=TH.code_bg, border_radius=8, padding=10,
                margin=ft.Margin.only(top=6)))
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"{icon} [{s.category}] {s.name}", size=SZ_MD),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM,
                             italic=True, color=TH.muted),
            controls=[ft.Container(
                content=ft.Column(tile_controls), padding=15,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8)],
            expanded=False))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider, height=30),
        cat_chart,
        ft.Divider(color=TH.divider, height=20),
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
                            color=ft.Colors.GREEN_400, size=SZ_LG),
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
                content=ft.Text(f"💡 {g.merge_suggestion}", size=SZ_BODY,
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
                        size=SZ_BODY, font_family=MONO_FONT,
                        color=TH.accent),
                ft.Container(
                    content=ft.Text(code[:400] if code else "N/A",
                                    font_family=MONO_FONT, size=SZ_SM,
                                    selectable=True, color=TH.dim,
                                    no_wrap=False),
                    bgcolor=TH.code_bg, border_radius=8,
                    padding=10) if code else ft.Container(),
            ], spacing=4))
        group_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"Group {g.group_id} — {g.similarity_type}"
                          f" ({sim_pct})", size=SZ_MD),
            subtitle=ft.Text(func_names, size=SZ_SM, color=TH.muted),
            controls=[ft.Container(
                content=ft.Column(controls, spacing=8), padding=12)]))

    return ft.Column([
        metrics,
        metric_tile("🔗", summary.get("total_functions_involved", 0),
                    t("involved")),
        ft.Divider(color=TH.divider, height=20),
        ft.ListView(controls=group_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_lint_tab(results: Dict[str, Any],
                    page: ft.Page) -> ft.Control:
    summary = results.get("lint", {})
    issues = results.get("_lint_issues", [])

    if summary.get("error"):
        return ft.Text(f"⚠️ {summary['error']}",
                       color=ft.Colors.AMBER_400, size=SZ_LG)
    if not issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=SZ_LG),
            padding=20)

    metrics = ft.Row([
        metric_tile("📊", summary.get("total", 0), t("total")),
        metric_tile("🔴", summary.get("critical", 0), t("critical"),
                    ft.Colors.RED_400),
        metric_tile("🟡", summary.get("warning", 0), t("warning"),
                    ft.Colors.AMBER_400),
        metric_tile("🔧", summary.get("fixable", 0), t("auto_fixable"),
                    TH.accent2),
    ], spacing=8)

    fix_result = ft.Text("", size=SZ_BODY)

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
                on_click=on_auto_fix, bgcolor=TH.accent2,
                color=ft.Colors.WHITE, height=BTN_H_MD,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS))),
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
                f"{s.message[:80]}{fix_tag}", size=SZ_MD),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM,
                             color=TH.muted),
            controls=[ft.Container(
                content=ft.Column([
                    ft.Text(f"{t('issue')}: {s.message}",
                            weight=ft.FontWeight.BOLD, size=SZ_MD),
                    ft.Text(f"{t('fix')}: {s.suggestion}", size=SZ_BODY,
                            color=ft.Colors.BLUE_200)
                    if s.suggestion else ft.Container(),
                ]), padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8)]))

    return ft.Column([
        metrics, fix_btn,
        ft.Divider(color=TH.divider, height=20),
        rule_chart,
        ft.Divider(color=TH.divider, height=20),
        section_title(t("all_issues"), "📋"),
        ft.ListView(controls=issue_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_security_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("security", {})
    issues = results.get("_sec_issues", [])

    if summary.get("error"):
        return ft.Text(f"⚠️ {summary['error']}",
                       color=ft.Colors.AMBER_400, size=SZ_LG)
    if not issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')}",
                            color=ft.Colors.GREEN_400, size=SZ_LG),
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
                         weight=ft.FontWeight.BOLD, size=SZ_MD)]
        if s.suggestion:
            ctrls.append(ft.Text(f"{t('fix')}: {s.suggestion}", size=SZ_BODY,
                                 color=ft.Colors.BLUE_200))
        if getattr(s, "confidence", ""):
            ctrls.append(ft.Text(f"Confidence: {s.confidence}", size=SZ_SM,
                                 color=TH.muted))
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(
                f"{icon} [{getattr(s, 'rule_code', '?')}] "
                f"{s.message[:70]}", size=SZ_MD),
            subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM,
                             color=TH.muted),
            leading=ft.Icon(
                ft.Icons.SECURITY,
                color=SEV_COLORS.get(sev, ft.Colors.GREY_400)),
            controls=[ft.Container(
                content=ft.Column(ctrls), padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8)]))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider, height=20),
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
                       color=TH.dim, size=SZ_LG)

    metrics = ft.Row([
        metric_tile("🦀", summary.get("total_scored", 0), t("scored")),
        metric_tile("✅", summary.get("pure_count", 0), t("pure"),
                    ft.Colors.GREEN_400),
        metric_tile("🏆", summary.get("top_score", 0), t("top_score"),
                    TH.accent),
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
                        color=TH.accent, size=SZ_MD),
                ft.Text(f"| {purity}", size=SZ_BODY),
                ft.Text(f"| CC={fn.complexity}", size=SZ_BODY,
                        color=TH.dim),
                ft.Text(f"| {fn.size_lines} lines", size=SZ_BODY,
                        color=TH.dim),
            ], spacing=8),
            ft.Text(f"📄 {fn.file_path}:{fn.line_start}", size=SZ_SM,
                    color=TH.muted),
        ]
        if cand.reason:
            ctrls.append(ft.Text(f"💡 {cand.reason}", size=SZ_SM,
                                 italic=True,
                                 color=ft.Colors.AMBER_200))

        if code:
            ctrls.append(ft.Row([
                ft.Column([
                    ft.Text("🐍 Python", size=SZ_SM,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.AMBER_300),
                    ft.Container(
                        content=ft.Text(code[:600],
                                        font_family=MONO_FONT,
                                        size=SZ_SM, selectable=True,
                                        color=TH.dim,
                                        no_wrap=False),
                        bgcolor=TH.code_bg, border_radius=8,
                        padding=10, expand=True),
                ], expand=True, spacing=4),
                ft.Column([
                    ft.Text("🦀 Rust", size=SZ_SM,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.CYAN_200),
                    ft.Container(
                        content=ft.Text(rust_code[:600],
                                        font_family=MONO_FONT,
                                        size=SZ_SM, selectable=True,
                                        color=TH.dim,
                                        no_wrap=False),
                        bgcolor=TH.code_bg, border_radius=8,
                        padding=10, expand=True),
                ], expand=True, spacing=4),
            ], spacing=12, expand=True))

        cand_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"#{rank}  {fn.name}", size=SZ_MD,
                          weight=ft.FontWeight.BOLD),
            subtitle=ft.Text(
                f"Score: {cand.score} | {purity} | CC={fn.complexity}",
                size=SZ_SM),
            leading=ft.Icon(
                ft.Icons.BOLT,
                color=(ft.Colors.GREEN_400 if cand.score > 20
                       else TH.accent)),
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
        ft.Divider(color=TH.divider, height=20),
        section_title(
            f"🏆 Top Rust Candidates ({min(30, len(candidates))})",
            ""),
        ft.ListView(controls=cand_tiles, expand=True, spacing=4,
                    auto_scroll=False),
        ft.Divider(color=TH.divider, height=20),
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
                       color=ft.Colors.GREEN_400, size=SZ_LG)

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
                ft.Text(f"🔥 {display}", size=SZ_BODY,
                        font_family=MONO_FONT,
                        color=TH.dim, expand=True,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Container(
                    content=ft.Container(bgcolor=color,
                                         border_radius=3,
                                         width=max(4, pct * 200),
                                         height=12),
                    bgcolor=TH.bar_bg, border_radius=3, width=200,
                    height=12,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE),
                ft.Text(str(total), size=SZ_MD,
                        weight=ft.FontWeight.BOLD,
                        font_family=MONO_FONT, width=40, color=color),
            ], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(6, 10),
            border=ft.Border.only(left=ft.BorderSide(3, color)),
            bgcolor=TH.card, border_radius=8,
            margin=ft.Margin.only(bottom=4)))

    total_issues = sum(file_issues.values())
    return ft.Column([
        section_title(t("worst_files"), "🔥"),
        ft.Text(f"{total_issues} {t('issues_across')} "
                f"{len(file_issues)} {t('files')}",
                size=SZ_BODY, color=TH.muted),
        ft.ListView(controls=tiles, expand=True, spacing=2,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_complexity_tab(results: Dict[str, Any]) -> ft.Control:
    functions: list = results.get("_functions", [])
    if not functions:
        return ft.Text("No functions available. "
                       "Enable Smells or Duplicates.",
                       color=TH.dim, size=SZ_LG)

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
                          size=SZ_MD),
            subtitle=ft.Text(
                f"{fn.file_path}:{fn.line_start} "
                f"({fn.size_lines} lines)",
                size=SZ_SM, color=TH.muted),
            leading=ft.Container(
                content=ft.Text(str(fn.complexity), size=SZ_LG,
                                weight=ft.FontWeight.BOLD,
                                color=cc_color,
                                text_align=ft.TextAlign.CENTER),
                bgcolor=ft.Colors.with_opacity(0.15, cc_color),
                border_radius=8, width=36, height=36,
                alignment=ft.Alignment(0, 0)),
            controls=[ft.Container(
                content=ft.Text(code[:500] if code else "N/A",
                                font_family=MONO_FONT, size=SZ_SM,
                                selectable=True,
                                color=TH.dim,
                                no_wrap=False),
                bgcolor=TH.code_bg, border_radius=8,
                padding=10)] if code else []))

    return ft.Column([
        metrics,
        ft.Divider(color=TH.divider, height=20),
        cc_chart,
        ft.Divider(color=TH.divider, height=20),
        sz_chart,
        ft.Divider(color=TH.divider, height=20),
        section_title(t("most_complex"), "🔥"),
        ft.ListView(controls=fn_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


def _build_auto_rustify_tab(results: Dict[str, Any],
                            page: ft.Page) -> ft.Control:
    if not HAS_AUTO_RUSTIFY:
        return ft.Text("auto_rustify module not available.",
                       color=ft.Colors.AMBER_400, size=SZ_LG)

    sys_profile = detect_system()
    sys_row = ft.Row([
        metric_tile("🖥️", sys_profile.os_name, "OS"),
        metric_tile("🏗️", sys_profile.arch, "Arch"),
        metric_tile("🎯", sys_profile.rust_target.split('-')[0],
                    "Target"),
    ], spacing=8)

    status_text = ft.Text("", size=SZ_MD, color=TH.dim)
    progress = ft.ProgressBar(width=500, color=TH.accent,
                              bgcolor=TH.card,
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
            ft.Text(f"⚙️ {t('tab_auto_rustify')} Pipeline", size=SZ_H3,
                    weight=ft.FontWeight.BOLD, font_family=MONO_FONT,
                    color=TH.accent),
            ft.Text("End-to-end: Scan → Score → Transpile → "
                    "Compile → Verify",
                    size=SZ_BODY, color=TH.muted),
        ])),
        sys_row,
        ft.Divider(color=TH.divider, height=20),
        ft.Row([
            ft.Button(f"🚀 {t('run_pipeline')}", on_click=on_run,
                      bgcolor=TH.accent2,
                      color=ft.Colors.WHITE, height=BTN_H_MD,
                      style=ft.ButtonStyle(
                          shape=ft.RoundedRectangleBorder(
                              radius=BTN_RADIUS))),
            status_text,
        ], spacing=12),
        progress,
    ], spacing=10)


def _build_ui_compat_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("ui_compat", {})
    raw_issues = results.get("_ui_compat_raw", [])
    smell_issues = results.get("_ui_compat_issues", [])

    if summary.get("error"):
        return ft.Text(f"⚠️ {summary['error']}",
                       color=ft.Colors.AMBER_400, size=SZ_LG)
    if not raw_issues:
        return ft.Container(
            content=ft.Text(f"✅ {t('no_issues')} — all UI calls compatible",
                            color=ft.Colors.GREEN_400, size=SZ_LG),
            padding=20)

    metrics = ft.Row([
        metric_tile("🖥️", summary.get("total", 0), t("total")),
        metric_tile("🔴", summary.get("critical", 0), t("critical"),
                    ft.Colors.RED_400),
        metric_tile("🧩", len(summary.get("by_widget", {})), "Widgets"),
        metric_tile("📁", len(summary.get("by_file", {})), "Files"),
    ], spacing=8)

    # Bar chart of bad kwargs
    bad_kw = summary.get("bad_kwargs", {})
    kw_chart = ft.Container()
    if bad_kw:
        kw_data = sorted(bad_kw.items(), key=lambda x: -x[1])
        kw_chart = ft.Column([
            section_title("Bad kwargs", "🏷️"),
            bar_chart([(k, n, "#ff6b6b") for k, n in kw_data[:12]])
        ], spacing=8)

    # Bar chart by widget
    by_widget = summary.get("by_widget", {})
    widget_chart = ft.Container()
    if by_widget:
        w_data = sorted(by_widget.items(), key=lambda x: -x[1])
        widget_chart = ft.Column([
            section_title("By widget", "🧩"),
            bar_chart([(w, n, "#ffa502") for w, n in w_data[:12]])
        ], spacing=8)

    issue_tiles = []
    for r in raw_issues[:100]:
        s = r.to_smell() if hasattr(r, "to_smell") else None
        icon = SEV_ICONS.get("critical", "🔴")
        ctrls = [
            ft.Text(f"{t('issue')}: '{r.bad_kwarg}' is not valid for "
                    f"{r.call.resolved_name}()",
                    weight=ft.FontWeight.BOLD, size=SZ_MD),
        ]
        if r.suggestion:
            ctrls.append(ft.Text(f"{t('fix')}: {r.suggestion}", size=SZ_BODY,
                                 color=ft.Colors.BLUE_200))
        if r.accepted:
            top = sorted(r.accepted - {"self"})[:15]
            ctrls.append(ft.Text(
                f"Accepted: {', '.join(top)}"
                + (" …" if len(r.accepted) > 15 else ""),
                size=SZ_SM, color=TH.dim, font_family=MONO_FONT))
        if r.call.source_snippet:
            ctrls.append(ft.Container(
                content=ft.Text(r.call.source_snippet[:400],
                                font_family=MONO_FONT, size=SZ_SM,
                                color=TH.dim, selectable=True,
                                no_wrap=False),
                bgcolor=TH.code_bg, border_radius=8, padding=10,
                margin=ft.Margin.only(top=6)))
        issue_tiles.append(ft.ExpansionTile(
            title=ft.Text(f"{icon} {r.call.resolved_name}.{r.bad_kwarg}",
                          size=SZ_MD),
            subtitle=ft.Text(f"{r.call.file_path}:{r.call.line}",
                             size=SZ_SM, color=TH.muted),
            leading=ft.Icon(ft.Icons.MONITOR,
                            color=ft.Colors.RED_400),
            controls=[ft.Container(
                content=ft.Column(ctrls), padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8)],
            expanded=False))

    return ft.Column([
        glass_card(ft.Column([
            ft.Text(f"🖥️ {t('tab_ui_compat')}", size=SZ_H3,
                    weight=ft.FontWeight.BOLD, font_family=MONO_FONT,
                    color=TH.accent),
            ft.Text("Validates UI framework kwargs against live API signatures",
                    size=SZ_BODY, color=TH.muted),
        ])),
        metrics,
        ft.Divider(color=TH.divider, height=20),
        kw_chart,
        widget_chart,
        ft.Divider(color=TH.divider, height=20),
        section_title(t("all_issues"), "🖥️"),
        ft.ListView(controls=issue_tiles, expand=True, spacing=4,
                    auto_scroll=False),
    ], spacing=10, expand=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  ONBOARDING DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

def _show_onboarding(page: ft.Page):
    steps = [
        (t("onboard_step1_title"), t("onboard_step1_desc"),
         "📂"),
        (t("onboard_step2_title"), t("onboard_step2_desc"),
         "🔍"),
        (t("onboard_step3_title"), t("onboard_step3_desc"),
         "⚡"),
        (t("onboard_step4_title"), t("onboard_step4_desc"),
         "🦀"),
        (t("onboard_step5_title"), t("onboard_step5_desc"),
         "🚀"),
    ]
    n = len(steps)
    step_idx = [0]

    # ── Widgets ──────────────────────────────────────────────────────────
    icon_ctrl = ft.Text(steps[0][2], size=SZ_H2,
                        text_align=ft.TextAlign.CENTER)
    title_text = ft.Text(steps[0][0], size=SZ_LG,
                         weight=ft.FontWeight.W_600,
                         color=TH.accent)
    desc_text = ft.Text(steps[0][1], size=SZ_BODY, color=TH.dim,
                        no_wrap=False)

    # Step dots: ● for current, ○ for others
    def _make_dots(idx):
        dots = []
        for i in range(n):
            dots.append(ft.Text(
                "●" if i == idx else "○",
                size=SZ_SM if i == idx else SZ_XS,
                color=TH.accent if i == idx else TH.muted))
        return ft.Row(dots, spacing=6,
                      alignment=ft.MainAxisAlignment.CENTER)

    dots_row = _make_dots(0)
    step_label = ft.Text(f"1 / {n}", size=SZ_XS, color=TH.muted)

    # ── Button row — always: [Skip/Back]  [spacer]  [Next/Finish] ────
    back_btn = ft.TextButton(t("onboard_skip"), on_click=lambda e: page.pop_dialog(),
                             style=ft.ButtonStyle(color=TH.muted))
    next_btn = ft.Button(t("onboard_next"), on_click=lambda e: _on_next(e),
                         bgcolor=TH.accent,
                         color=ft.Colors.WHITE, height=BTN_H_SM,
                         style=ft.ButtonStyle(
                             shape=ft.RoundedRectangleBorder(
                                 radius=BTN_RADIUS)))

    def _update():
        i = step_idx[0]
        icon_ctrl.value = steps[i][2]
        title_text.value = steps[i][0]
        desc_text.value = steps[i][1]
        step_label.value = f"{i + 1} / {n}"
        # Update dots
        new_dots = _make_dots(i)
        dots_row.controls = new_dots.controls
        # Back becomes "← Back" after step 0, else "Skip"
        if i > 0:
            back_btn.text = t("onboard_back")
            back_btn.on_click = _on_back
        else:
            back_btn.text = t("onboard_skip")
            back_btn.on_click = lambda e: page.pop_dialog()
        # Next becomes "Got it!" on last step
        next_btn.text = (t("onboard_got_it") if i == n - 1
                         else t("onboard_next"))
        page.update()

    def _on_next(e):
        if step_idx[0] >= n - 1:
            page.pop_dialog()
            return
        step_idx[0] += 1
        _update()

    def _on_back(e):
        if step_idx[0] > 0:
            step_idx[0] -= 1
            _update()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Text("🔬", size=SZ_H3),
            ft.Text(t("onboard_title"), size=SZ_H3,
                    weight=ft.FontWeight.BOLD, color=TH.accent),
        ], spacing=8),
        content=ft.Container(
            content=ft.Column([
                # Icon + title row
                ft.Row([icon_ctrl, title_text], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                desc_text,
                ft.Container(height=8),
                dots_row,
                step_label,
                ft.Container(height=4),
                # Buttons inline at bottom of content
                ft.Row([
                    back_btn,
                    next_btn,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=6,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               tight=True),
            width=400, padding=ft.Padding.symmetric(horizontal=8, vertical=4)),
        actions=[],
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    page.show_dialog(dlg)


# ═══════════════════════════════════════════════════════════════════════════════
#  EXTRACTED HELPERS FOR main()
# ═══════════════════════════════════════════════════════════════════════════════

def _build_main_dashboard(page, state, main_content, results):
    """Build the full results dashboard (grade card + tabs + export bar)."""
    narrow = is_narrow(page)
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    letter = grade.get("letter", "?")
    score = grade.get("score", 0)
    color = GRADE_COLORS.get(letter, "#888")

    # Grade card
    grade_card = ft.Container(
        content=ft.Column([
            ft.Text(letter, size=SZ_DISPLAY, weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                    font_family=MONO_FONT),
            ft.Text(f"{score} / 100", size=SZ_SECTION,
                    color=ft.Colors.with_opacity(0.8, color),
                    text_align=ft.TextAlign.CENTER),
            ft.Text(t("quality_score").upper(), size=SZ_SM,
                    color=TH.muted,
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           spacing=2),
        bgcolor=ft.Colors.with_opacity(0.1, color),
        border=ft.Border.all(
            1, ft.Colors.with_opacity(0.4, color)),
        border_radius=16, padding=20,
        width=None if narrow else 190,
        expand=narrow,
        shadow=ft.BoxShadow(
            blur_radius=20,
            color=ft.Colors.with_opacity(0.15, color)),
        animate=ft.Animation(500, ft.AnimationCurve.EASE_OUT))

    # Stats row – wrap on narrow screens
    stats = ft.Row([
        metric_tile("📄", meta.get("files", 0), t("files")),
        metric_tile("⚡", meta.get("functions", 0),
                    t("functions")),
        metric_tile("📦", meta.get("classes", 0), t("classes")),
        metric_tile("⏱️", f"{meta.get('duration', 0):.1f}s",
                    t("duration")),
    ], spacing=8, expand=True, wrap=True)

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
                    size=SZ_SM, color=TH.text),
                bgcolor=TH.chip))

    # Responsive header: vertical on narrow, horizontal on wide
    if narrow:
        header = ft.Column([
            grade_card,
            stats,
            (ft.Row(penalty_chips, spacing=6, wrap=True)
             if penalty_chips else ft.Container()),
        ], spacing=12,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    else:
        header = ft.Row([
            grade_card,
            ft.Column([
                stats,
                (ft.Row(penalty_chips, spacing=6)
                 if penalty_chips else ft.Container()),
            ], expand=True, spacing=10),
        ], spacing=20,
           vertical_alignment=ft.CrossAxisAlignment.START)

    # ── Tabs ─────────────────────────────────────────────────────────
    tab_labels = []
    tab_panels = []
    if (results.get("smells")
            and not results["smells"].get("error")):
        tab_labels.append(ft.Tab(label=f"🔍 {t('tab_smells')}"))
        tab_panels.append(_build_smells_tab(results))
    if (results.get("duplicates")
            and not results.get("duplicates", {}).get("error")):
        tab_labels.append(ft.Tab(label=f"📋 {t('tab_duplicates')}"))
        tab_panels.append(_build_duplicates_tab(results))
    if (results.get("lint")
            and not results.get("lint", {}).get("error")):
        tab_labels.append(ft.Tab(label=f"🧹 {t('tab_lint')}"))
        tab_panels.append(_build_lint_tab(results, page))
    if (results.get("security")
            and not results.get("security", {}).get("error")):
        tab_labels.append(ft.Tab(label=f"🔒 {t('tab_security')}"))
        tab_panels.append(_build_security_tab(results))
    if results.get("rustify"):
        tab_labels.append(ft.Tab(label=f"🦀 {t('tab_rustify')}"))
        tab_panels.append(_build_rustify_tab(results))
    if (results.get("ui_compat")
            and not results.get("ui_compat", {}).get("error")):
        tab_labels.append(ft.Tab(label=f"🖥️ {t('tab_ui_compat')}"))
        tab_panels.append(_build_ui_compat_tab(results))

    has_issues = (results.get("_smell_issues")
                  or results.get("_lint_issues")
                  or results.get("_sec_issues"))
    if has_issues:
        tab_labels.append(ft.Tab(label=f"🔥 {t('tab_heatmap')}"))
        tab_panels.append(_build_heatmap_tab(results))
    if results.get("_functions"):
        tab_labels.append(ft.Tab(label=f"📊 {t('tab_complexity')}"))
        tab_panels.append(_build_complexity_tab(results))
        tab_labels.append(ft.Tab(label=f"⚙️ {t('tab_auto_rustify')}"))
        tab_panels.append(_build_auto_rustify_tab(results, page))

    # Panel container — shows the active tab's content
    panel_container = ft.Column(
        [tab_panels[0]] if tab_panels else [],
        expand=True, spacing=0)

    def _on_tab_change(e):
        idx = e.control.selected_index
        if 0 <= idx < len(tab_panels):
            panel_container.controls = [tab_panels[idx]]
            page.update()

    result_tabs = ft.Column([
        ft.Tabs(
            content=ft.Row(tab_labels),
            length=len(tab_labels),
            selected_index=0,
            animation_duration=300,
            on_change=_on_tab_change,
        ),
        panel_container,
    ], expand=True, spacing=0) if tab_labels else ft.Container()

    # ── Export bar ────────────────────────────────────────────────────
    def on_export_json(e):
        try:
            export = {k: v for k, v in results.items()
                      if not k.startswith("_")}
            path = Path(state["root_path"]) / "xray_report.json"
            path.write_text(
                json.dumps(export, indent=2, default=str),
                encoding="utf-8")
            _show_snack(page, f"📥 Saved to {path}")
        except Exception as exc:
            _show_snack(page, f"❌ Export failed: {exc}",
                        bgcolor=ft.Colors.RED_400)

    def on_export_md(e):
        try:
            md = _build_markdown_report(results)
            path = Path(state["root_path"]) / "xray_report.md"
            path.write_text(md, encoding="utf-8")
            _show_snack(page, f"📥 Saved to {path}")
        except Exception as exc:
            _show_snack(page, f"❌ Export failed: {exc}",
                        bgcolor=ft.Colors.RED_400)

    export_bar = ft.Row([
        ft.Button(f"📥 {t('export_json')}",
                  on_click=on_export_json,
                  bgcolor=TH.card,
                  color=TH.text, height=BTN_H_SM,
                  style=ft.ButtonStyle(
                      shape=ft.RoundedRectangleBorder(
                          radius=BTN_RADIUS))),
        ft.Button(f"📥 {t('export_markdown')}",
                  on_click=on_export_md,
                  bgcolor=TH.card,
                  color=TH.text, height=BTN_H_SM,
                  style=ft.ButtonStyle(
                      shape=ft.RoundedRectangleBorder(
                          radius=BTN_RADIUS))),
    ], spacing=12)

    main_content.controls = [
        ft.Container(
            content=ft.Column([
                header,
                ft.Divider(color=TH.divider, height=30),
                result_tabs,
                ft.Divider(color=TH.divider, height=20),
                export_bar,
            ], spacing=10, expand=True),
            padding=30, expand=True, bgcolor=TH.bg)
    ]
    page.update()


def _build_main_landing(page, main_content):
    """Build the welcome / landing page."""
    narrow = is_narrow(page)

    # 3-step instruction cards — fixed width so they work in any layout
    _card_w = 200 if narrow else 240

    def _landing_card(icon, icon_color, step, title, desc):
        return glass_card(ft.Column([
            ft.Container(
                content=ft.Icon(icon, color=icon_color, size=28),
                bgcolor=ft.Colors.with_opacity(0.08, icon_color),
                border_radius=12, width=56, height=56,
                alignment=ft.Alignment(0, 0)),
            ft.Text(f"{step}. {title}", weight=ft.FontWeight.BOLD,
                    size=SZ_LG, color=TH.text),
            ft.Text(desc, size=SZ_BODY, color=TH.muted,
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           spacing=8), padding=24, width=_card_w)

    card1 = _landing_card(
        ft.Icons.FOLDER_OPEN, TH.accent, 1, "Configure",
        "Set path & analyzers\nin the sidebar")
    card2 = _landing_card(
        ft.Icons.PLAY_ARROW_ROUNDED, TH.accent2, 2, "Scan",
        f"Press '{t('scan_start')}'\nto analyze code")
    card3 = _landing_card(
        ft.Icons.INSIGHTS, "#00c853", 3, "Explore",
        "Browse results in\ninteractive tabs")

    # Stack vertical on narrow, horizontal row on wide
    if narrow:
        cards_layout = ft.Column(
            [card1, card2, card3], spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    else:
        cards_layout = ft.Row(
            [card1, card2, card3], spacing=16,
            alignment=ft.MainAxisAlignment.CENTER)

    main_content.controls = [
        ft.Container(
            content=ft.Column([
                ft.Container(height=30 if narrow else 50),
                # Logo area
                ft.Container(
                    content=ft.Column([
                        ft.Text("🔬", size=SZ_DISPLAY,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text("X-RAY", size=SZ_HERO,
                                weight=ft.FontWeight.BOLD,
                                color=TH.accent,
                                font_family=MONO_FONT,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text(t("app_subtitle"), size=SZ_LG,
                                color=TH.muted,
                                text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER),
                       spacing=4),
                    animate=ft.Animation(
                        600, ft.AnimationCurve.EASE_OUT)),
                ft.Container(height=20 if narrow else 30),
                cards_layout,
                ft.Container(height=20 if narrow else 30),
                ft.Text("AST Smells · Ruff Lint · Bandit Security"
                        " · Duplicates · Rust Advisor",
                        size=SZ_BODY, color=TH.muted,
                        text_align=ft.TextAlign.CENTER),
                ft.TextButton(
                    "📖 Show Tutorial",
                    on_click=lambda _: _show_onboarding(page)),
                ft.Container(height=30),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=8),
            padding=ft.Padding.symmetric(horizontal=20, vertical=0),
            bgcolor=TH.bg,
            alignment=ft.Alignment(0, -1))
    ]


async def _start_scan_handler(page, state, progress, main_content,
                              build_dashboard_fn):
    """Run scan with rich progress, then show dashboard."""
    progress_bar = progress["bar"]
    progress_ring = progress["ring"]
    progress_label = progress["label"]
    progress_detail = progress["detail"]
    progress_eta = progress["eta"]

    if not state["root_path"]:
        _show_snack(page, t("select_dir_first"), bgcolor=ft.Colors.RED_400)
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
                ft.Text("🔬", size=SZ_HERO,
                        text_align=ft.TextAlign.CENTER),
                ft.Text(t("scanning").upper(), size=SZ_H2,
                        weight=ft.FontWeight.BOLD,
                        color=TH.accent,
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
                # Progress bar with percentage – responsive width
                ft.Container(
                    content=progress_bar,
                    padding=ft.Padding.symmetric(horizontal=40),
                    alignment=ft.Alignment(0, 0)),
                ft.Container(height=30),
                ft.Text("Analyzing Python source code\u2026",
                        size=SZ_SM, color=TH.muted, italic=True,
                        text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=6),
            padding=ft.Padding.symmetric(horizontal=20, vertical=0),
            bgcolor=TH.bg,
            alignment=ft.Alignment(0, -1))
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

    try:
        results = await loop.run_in_executor(
            None,
            lambda: _run_scan(
                Path(state["root_path"]), state["modes"],
                state["exclude"], state["thresholds"],
                progress_cb=progress_cb))
    except Exception as exc:
        # Reset progress UI
        progress_bar.visible = False
        progress_ring.visible = False
        progress_label.value = ""
        progress_detail.value = ""
        progress_eta.value = ""
        # Show error screen
        main_content.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Container(height=80),
                    ft.Text("❌", size=SZ_HERO,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text("Scan Failed", size=SZ_H2,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.RED_400,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(str(exc)[:300], size=SZ_BODY, color=TH.dim,
                            text_align=ft.TextAlign.CENTER,
                            no_wrap=False),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=8),
                padding=30, bgcolor=TH.bg,
                alignment=ft.Alignment(0, -1))
        ]
        page.update()
        return

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
                ft.Text("✅", size=SZ_HERO,
                        text_align=ft.TextAlign.CENTER),
                ft.Text(t("scan_complete"), size=SZ_H2,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREEN_400,
                        text_align=ft.TextAlign.CENTER),
                ft.Text(
                    f"{n_files} {t('files')} \u00b7 "
                    f"{n_funcs} {t('functions')} \u00b7 "
                    f"{dur:.1f}s",
                    size=SZ_SECTION, color=TH.dim,
                    text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=8),
            padding=ft.Padding.symmetric(horizontal=20, vertical=0),
            bgcolor=TH.bg,
            alignment=ft.Alignment(0, -1),
            animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT))
    ]
    page.update()

    # Short pause then show dashboard
    await asyncio.sleep(0.8)
    build_dashboard_fn(results)


def _build_app_sidebar(pick_directory, path_text, mode_checks, start_scan,
                       theme_icon, lang_dd, progress):
    """Build the left sidebar Container."""
    progress_ring = progress["ring"]
    progress_label = progress["label"]
    progress_detail = progress["detail"]
    progress_eta = progress["eta"]
    return ft.Container(
        content=ft.Column([
            # Logo
            ft.Container(
                content=ft.Column([
                    ft.Text("X-RAY", size=SZ_SIDEBAR,
                            weight=ft.FontWeight.BOLD,
                            color=TH.accent,
                            font_family=MONO_FONT,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(t("app_subtitle").upper(), size=SZ_XS,
                            color=TH.muted,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(f"v{__version__}", size=SZ_XS,
                            color=TH.muted,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=2),
                padding=ft.Padding.only(top=16, bottom=4)),

            # Theme + Language row
            ft.Row([
                theme_icon,
                ft.Icon(ft.Icons.LANGUAGE, size=SZ_LG,
                        color=TH.muted),
                lang_dd,
            ], spacing=4,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(color=TH.divider, height=16),

            # Directory
            ft.Text(t("project_scope").upper(), size=SZ_SM,
                    weight=ft.FontWeight.BOLD, color=TH.muted),
            ft.Button(
                t("select_directory"), icon=ft.Icons.FOLDER_OPEN,
                on_click=pick_directory,
                width=260, color=TH.accent, bgcolor=TH.card),
            path_text,
            ft.Divider(color=TH.divider, height=12),

            # Modes
            ft.Text(t("scan_modes").upper(), size=SZ_SM,
                    weight=ft.FontWeight.BOLD, color=TH.muted),
            mode_checks,
            ft.Divider(color=TH.divider, height=12),

            # Scan button
            ft.Button(
                f"⚡ {t('scan_start')}",
                width=260, height=48,
                color=ft.Colors.WHITE,
                bgcolor=TH.accent2,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=start_scan),

            ft.Container(height=4),
            ft.Row([progress_ring, progress_label], spacing=6),
            progress_detail,
            progress_eta,

            # Footer
            ft.Container(expand=True),
            ft.Divider(color=TH.divider),
            ft.Text("AST \u00b7 Ruff \u00b7 Bandit \u00b7 Rust \u00b7 UI", size=SZ_XS,
                    color=TH.muted,
                    text_align=ft.TextAlign.CENTER),
            ft.TextButton(
                "github.com/GeoHaber/X_Ray",
                url="https://github.com/GeoHaber/X_Ray",
                style=ft.ButtonStyle(color=TH.muted)),
        ], scroll=ft.ScrollMode.AUTO, spacing=6),
        width=280, bgcolor=TH.surface,
        border=ft.Border.only(right=ft.BorderSide(1, TH.border)),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8))


def _build_mode_checks(state):
    """Build the mode-toggle checkboxes column."""
    def on_mode(e):
        state["modes"][e.control.data] = e.control.value

    _m = state["modes"]
    return ft.Column([
        ft.Checkbox(label=t("smells"), value=_m["smells"],
                    on_change=on_mode, data="smells",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("duplicates"), value=_m["duplicates"],
                    on_change=on_mode, data="duplicates",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("lint"), value=_m["lint"],
                    on_change=on_mode, data="lint",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("security"), value=_m["security"],
                    on_change=on_mode, data="security",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("rustify"), value=_m["rustify"],
                    on_change=on_mode, data="rustify",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
        ft.Checkbox(label=t("ui_compat"), value=_m.get("ui_compat", True),
                    on_change=on_mode, data="ui_compat",
                    fill_color=TH.accent, check_color=ft.Colors.WHITE),
    ], spacing=0)


def _build_theme_lang_controls(page, main_fn):
    """Build theme toggle icon and language dropdown."""
    theme_icon = ft.IconButton(
        icon=(ft.Icons.LIGHT_MODE if TH.is_dark()
              else ft.Icons.DARK_MODE),
        icon_color=TH.accent,
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
        page.run_task(main_fn, page)

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
        page.run_task(main_fn, page)

    lang_dd = ft.Dropdown(
        value=get_locale(), width=120, dense=True,
        border_color=TH.border, color=TH.text,
        options=[ft.dropdown.Option(key=k, text=f"{v}")
                 for k, v in LOCALES.items()],
        on_select=on_lang_change)
    return theme_icon, lang_dd


def _build_progress_widgets():
    """Create the progress bar, ring, label, detail, and ETA widgets."""
    return {
        "bar": ft.ProgressBar(color=TH.accent,
                              bgcolor=TH.card,
                              value=0, visible=False),
        "ring": ft.ProgressRing(width=20, height=20,
                                stroke_width=2.5,
                                color=TH.accent,
                                visible=False),
        "label": ft.Text("", size=SZ_LG, color=TH.dim,
                         weight=ft.FontWeight.W_600),
        "detail": ft.Text("", size=SZ_MD, color=TH.muted,
                          font_family=MONO_FONT),
        "eta": ft.Text("", size=SZ_MD, color=TH.muted,
                       italic=True),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def main(page: ft.Page):
    # ── Page setup ───────────────────────────────────────────────────────
    def on_error(e):
        import traceback
        logger.error("Flet page error: %s", e.data)

    page.on_error = on_error
    page.title = t("app_title")
    page.theme_mode = (ft.ThemeMode.DARK if TH.is_dark()
                       else ft.ThemeMode.LIGHT)
    page.bgcolor = TH.bg
    page.window.width = 1360
    page.window.height = 880
    page.padding = 0
    page.spacing = 0
    page.fonts = {"mono": "Cascadia Code"}

    # Material 3 seed-color themes
    page.theme = ft.Theme(
        color_scheme_seed=TH.accent,
        font_family="Segoe UI, Roboto, Helvetica, Arial, sans-serif")
    page.dark_theme = ft.Theme(
        color_scheme_seed=TH.accent,
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
                "security": True, "rustify": True, "ui_compat": True,
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
        color=TH.accent if _prev_path else TH.muted,
        size=SZ_BODY, italic=not bool(_prev_path), max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS)

    async def pick_directory(e):
        result = await file_picker.get_directory_path(
            dialog_title=t("select_directory"))
        if result:
            state["root_path"] = result
            path_text.value = result
            path_text.color = TH.accent
            page.update()

    # ── Mode checkboxes ──────────────────────────────────────────────────
    mode_checks = _build_mode_checks(state)

    # ── Theme & language pickers ─────────────────────────────────────────
    theme_icon, lang_dd = _build_theme_lang_controls(page, main)

    # ── Progress UI (rich, with ETA) ─────────────────────────────────────
    progress = _build_progress_widgets()

    # ── Main content area ────────────────────────────────────────────────
    main_content = ft.Column([], expand=True, scroll=ft.ScrollMode.AUTO)

    def build_dashboard(results):
        _build_main_dashboard(page, state, main_content, results)

    def build_landing():
        _build_main_landing(page, main_content)

    # ── Scan handler ─────────────────────────────────────────────────────
    async def start_scan(e):
        await _start_scan_handler(page, state, progress, main_content,
                                  build_dashboard)

    # ── Sidebar ──────────────────────────────────────────────────────────
    sidebar = _build_app_sidebar(
        pick_directory, path_text, mode_checks, start_scan,
        theme_icon, lang_dd, progress)

    # ── Responsive layout helper ─────────────────────────────────────────
    narrow = is_narrow(page)

    if narrow:
        # Put sidebar content inside a NavigationDrawer
        drawer = ft.NavigationDrawer(
            controls=[sidebar],
            bgcolor=TH.surface)
        page.drawer = drawer

        def open_drawer(e):
            page.show_drawer(drawer)

        hamburger = ft.IconButton(
            icon=ft.Icons.MENU, icon_color=TH.accent,
            icon_size=28, tooltip="Menu",
            on_click=open_drawer)

        top_bar = ft.Container(
            content=ft.Row([
                hamburger,
                ft.Text("X-RAY", size=SZ_H3,
                        weight=ft.FontWeight.BOLD,
                        color=TH.accent, font_family=MONO_FONT),
                ft.Container(expand=True),
                theme_icon,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=TH.surface,
            border=ft.Border.only(
                bottom=ft.BorderSide(1, TH.border)),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4))

        main_area = ft.Container(
            content=main_content, bgcolor=TH.bg, expand=True)
        layout = ft.Column(
            [top_bar, main_area], expand=True, spacing=0)
    else:
        main_area = ft.Container(
            content=main_content, bgcolor=TH.bg, expand=True)
        layout = ft.Row(
            [sidebar, main_area], expand=True, spacing=0)

    # ── Layout ───────────────────────────────────────────────────────────
    # If we already have scan results (e.g. after theme/lang toggle), show dashboard
    if state.get("results"):
        build_dashboard(state["results"])
    else:
        build_landing()

    page.add(layout)

    # ── Responsive resize handler ────────────────────────────────────────
    _resize_guard = {"busy": False}

    def on_resize(e):
        """Rebuild layout when viewport crosses a breakpoint."""
        if _resize_guard["busy"]:
            return
        try:
            new_narrow = is_narrow(page)
            old_narrow = page.data.get("_was_narrow")
            if old_narrow is not None and new_narrow != old_narrow:
                _resize_guard["busy"] = True
                page.data["_onboarded"] = True  # don't re-show tutorial
                page.data["_was_narrow"] = new_narrow
                page.controls.clear()
                page.run_task(main, page)
                return  # new main() will set its own handler
            page.data["_was_narrow"] = new_narrow
        except Exception:
            pass
        finally:
            _resize_guard["busy"] = False

    page.data["_was_narrow"] = narrow
    page.on_resized = on_resize

    # ── First-run onboarding (only once) ─────────────────────────────────
    if not page.data.get("_onboarded"):
        page.data["_onboarded"] = True
        _show_onboarding(page)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ft.run(main)
