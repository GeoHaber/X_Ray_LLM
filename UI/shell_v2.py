"""
UI/shell_v2.py — X-Ray v8.0 Redesigned Shell
==============================================

Replaces the old sidebar + 15-pill tab system with:
  - LEFT ICON RAIL (64px): 7 grouped sections, always visible
  - MAIN CONTENT (expands): one section at a time, no scroll hunting
  - HOME VIEW: just drop a path + one big Scan button
  - RESULTS VIEW: grade hero + section router

Section map (icon → grouped content):
  🏠  Home/Scan
  📊  Overview  ← grade card, meta, history sparkline, quality gate
  🐛  Issues   ← smells, duplicates, lint, security, typecheck, format, all-issues
  💸  Debt     ← SATD, hotspots, temporal coupling, AI debt
  🏗️  Architecture ← graph, heatmap, complexity, diagrams
  ⚡  Actions  ← auto-rustify, nexus, test gen, auto-fix
  ⚙️  Settings ← theme, language, scan modes, export buttons
"""

from __future__ import annotations
import flet as ft
from typing import Any, Callable, Dict, List, Optional

from UI.tabs.shared import TH, glass_card, metric_tile, section_title, SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_H3, SZ_H2, SZ_HERO, SZ_DISPLAY, MONO_FONT, GRADE_COLORS
from Core.i18n import t
from Core.config import __version__

# ── Rail section IDs ──────────────────────────────────────────────────────────
SEC_HOME   = "home"
SEC_OVERVIEW = "overview"
SEC_ISSUES   = "issues"
SEC_DEBT     = "debt"
SEC_ARCH     = "arch"
SEC_ACTIONS  = "actions"
SEC_SETTINGS = "settings"


# ── Icon rail entry definition ─────────────────────────────────────────────────
_RAIL_ENTRIES = [
    (SEC_HOME,     "🏠", "Home",         None),                # always active
    (SEC_OVERVIEW, "📊", "Overview",     None),                # needs results
    (SEC_ISSUES,   "🐛", "Issues",       None),
    (SEC_DEBT,     "💸", "Debt Center",  None),
    (SEC_ARCH,     "🏗️", "Architecture", None),
    (SEC_ACTIONS,  "⚡", "Actions",      None),
    (SEC_SETTINGS, "⚙️", "Settings",     None),
]


# ── Colour tokens ─────────────────────────────────────────────────────────────
_RAIL_W   = 64    # icon rail width
_RAIL_SEL = "#00d4ff"   # selected accent
_RAIL_DIM = "#4b5563"   # unselected icon colour


def _rail_icon(
    section_id: str,
    emoji: str,
    label: str,
    is_selected: bool,
    on_click: Callable,
    badge_count: int = 0,
) -> ft.Container:
    """Single icon-rail button with optional badge count."""

    def _on_click(e):
        on_click(section_id)

    badge = None
    if badge_count > 0:
        n = str(badge_count) if badge_count < 100 else "99+"
        badge = ft.Container(
            content=ft.Text(n, size=8, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER),
            bgcolor="#ef4444",
            border_radius=8,
            width=16, height=16,
            alignment=ft.Alignment(0, 0),
            right=4, top=4,
        )

    body = ft.Container(
        content=ft.Stack(
            [
                ft.Column(
                    [
                        ft.Text(emoji, size=20, text_align=ft.TextAlign.CENTER),
                        ft.Text(label, size=8, color=_RAIL_SEL if is_selected else _RAIL_DIM,
                                text_align=ft.TextAlign.CENTER, max_lines=1),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
                *(  [badge] if badge else [] ),
            ],
        ),
        width=_RAIL_W,
        height=58,
        bgcolor=ft.Colors.with_opacity(0.12, _RAIL_SEL) if is_selected else "transparent",
        border_radius=10,
        alignment=ft.Alignment(0, 0),
        on_click=_on_click,
        animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        tooltip=label,
    )
    return body


# ── Left rail ─────────────────────────────────────────────────────────────────

def build_left_rail(
    selected: str,
    navigate: Callable[[str], None],
    results: Optional[Dict[str, Any]] = None,
    theme_icon=None,
) -> ft.Container:
    """Build the 64px left icon rail."""

    def _badge(section_id: str) -> int:
        """Return badge count for a section based on result data."""
        if results is None:
            return 0
        if section_id == SEC_ISSUES:
            return (
                results.get("smells", {}).get("critical", 0)
                + results.get("security", {}).get("critical", 0)
            )
        if section_id == SEC_DEBT:
            return results.get("_satd", {}).get("total", 0)
        return 0

    icons = []
    for sec_id, emoji, label, _ in _RAIL_ENTRIES:
        # Dim sections that require results if none available
        if results is None and sec_id not in (SEC_HOME, SEC_SETTINGS):
            # Show dimmed / disabled
            icons.append(ft.Container(
                content=ft.Column(
                    [
                        ft.Text(emoji, size=20, text_align=ft.TextAlign.CENTER,
                                opacity=0.25),
                        ft.Text(label, size=8, color="#374151",
                                text_align=ft.TextAlign.CENTER, max_lines=1),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
                width=_RAIL_W, height=58,
                alignment=ft.Alignment(0, 0),
                tooltip=f"{label} — scan first",
            ))
            continue
        icons.append(
            _rail_icon(
                sec_id, emoji, label,
                is_selected=(sec_id == selected),
                on_click=navigate,
                badge_count=_badge(sec_id),
            )
        )

    # Separator before settings
    icons.insert(-1, ft.Container(height=1, bgcolor=TH.divider, margin=ft.margin.symmetric(horizontal=8, vertical=4)))

    # Theme toggle at top
    rail_top = [
        ft.Container(
            content=ft.Text("☢", size=22, text_align=ft.TextAlign.CENTER, color=_RAIL_SEL),
            width=_RAIL_W, height=48,
            alignment=ft.Alignment(0, 0),
            tooltip="X-RAY",
        ),
        ft.Container(height=1, bgcolor=TH.divider, margin=ft.margin.symmetric(horizontal=8, vertical=2)),
    ]

    return ft.Container(
        content=ft.Column(
            rail_top + icons,
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.HIDDEN,
        ),
        width=_RAIL_W,
        bgcolor=TH.surface,
        border=ft.border.only(right=ft.BorderSide(1, TH.divider)),
        padding=ft.padding.symmetric(vertical=8),
    )


# ── Home / Scan section ───────────────────────────────────────────────────────

def build_home_section(
    state: Dict[str, Any],
    on_scan: Callable,
    on_pick_dir: Callable,
    on_apply_path: Callable,
    results: Optional[Dict[str, Any]] = None,
) -> ft.Control:
    """The clean home/scan page — just what matters."""

    path_val = state.get("root_path", "")
    path_input = ft.TextField(
        id="home_path",
        value=path_val,
        hint_text="  Paste or type a project folder path…",
        border_color=TH.border,
        focused_border_color=_RAIL_SEL,
        color=TH.text,
        bgcolor=TH.card,
        border_radius=12,
        height=52,
        expand=True,
        text_size=SZ_BODY,
        on_submit=lambda e: (on_apply_path(e.control.value), None),
        on_blur=lambda e: on_apply_path(e.control.value),
    )

    scan_btn = ft.FilledButton(
        "  Scan",
        icon=ft.Icons.RADAR,
        on_click=on_scan,
        height=52,
        style=ft.ButtonStyle(
            bgcolor={"": _RAIL_SEL, "hovered": "#00b8e6"},
            color={"": "#0a0e1a"},
            shape=ft.RoundedRectangleBorder(radius=12),
            animation_duration=200,
        ),
    )

    browse_btn = ft.OutlinedButton(
        "",
        icon=ft.Icons.FOLDER_OPEN,
        on_click=on_pick_dir,
        height=52,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1, TH.border),
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
        tooltip="Browse for folder",
    )

    # Recent paths
    recent = state.get("recent_paths", [])
    recent_chips = []
    for p in recent[:5]:
        short = ("…" + p[-34:]) if len(p) > 36 else p
        chip = ft.Container(
            content=ft.Text(short, size=SZ_XS, color=TH.dim, no_wrap=True),
            bgcolor=TH.card,
            border=ft.border.all(1, TH.border),
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            on_click=lambda e, path=p: (on_apply_path(path), path_input.__setattr__("value", path)),
            tooltip=p,
        )
        recent_chips.append(chip)

    # Last scan summary if available
    last_scan = ft.Container()
    if results:
        grade = results.get("grade", {})
        meta  = results.get("meta", {})
        letter = grade.get("letter", "?")
        color  = GRADE_COLORS.get(letter, "#6b7280")
        score  = grade.get("score", 0)
        n_files = meta.get("files", 0)
        n_fns   = meta.get("functions", 0)
        dur     = meta.get("duration", 0)
        scan_path = results.get("_scan_path", "?")
        last_scan = glass_card(ft.Column([
            ft.Text("Last scan", size=SZ_XS, color=TH.muted),
            ft.Row([
                ft.Text(letter, size=40, weight=ft.FontWeight.BOLD, color=color,
                        font_family=MONO_FONT),
                ft.Column([
                    ft.Text(scan_path.split("\\")[-1] if "\\" in str(scan_path) else str(scan_path),
                            size=SZ_LG, weight=ft.FontWeight.W_600, color=TH.text),
                    ft.Text(f"Score {score:.0f}/100 · {n_files} files · {n_fns} functions · {dur:.1f}s",
                            size=SZ_SM, color=TH.dim),
                ], spacing=2, expand=True),
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text("Click 📊 Overview in the rail to see full results →",
                    size=SZ_XS, color=TH.muted),
        ], spacing=6), padding=16)

    hero = ft.Column([
        ft.Text("☢ X-RAY", size=SZ_HERO, weight=ft.FontWeight.BOLD,
                color=_RAIL_SEL, font_family=MONO_FONT,
                text_align=ft.TextAlign.CENTER),
        ft.Text("Code Quality Intelligence · Drop a project folder and hit Scan",
                size=SZ_BODY, color=TH.dim, text_align=ft.TextAlign.CENTER),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)

    input_row = ft.Row([browse_btn, path_input, scan_btn], spacing=8)

    recent_row = ft.Row(recent_chips, spacing=6,
                        scroll=ft.ScrollMode.AUTO) if recent_chips else ft.Container()

    features = ft.Row([
        _feature_chip("🐛 Smells"),
        _feature_chip("🔒 Security"),
        _feature_chip("🧬 Duplicates"),
        _feature_chip("🔥 Hotspots"),
        _feature_chip("💸 SATD Debt"),
        _feature_chip("🤖 AI Debt"),
        _feature_chip("🏗️ Diagrams"),
        _feature_chip("⚡ Rustify"),
    ], spacing=6, wrap=True)

    return ft.Container(
        content=ft.Column([
            ft.Container(expand=True),
            hero,
            ft.Container(height=24),
            input_row,
            ft.Container(height=8),
            recent_row,
            ft.Container(height=32),
            features,
            ft.Container(height=32),
            last_scan,
            ft.Container(expand=True),
        ], expand=True, spacing=0,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        expand=True,
        padding=ft.padding.symmetric(horizontal=80, vertical=20),
    )


def _feature_chip(label: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(label, size=SZ_XS, color=TH.dim),
        bgcolor=TH.card,
        border=ft.border.all(1, TH.border),
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=4),
    )


# ── Overview section ──────────────────────────────────────────────────────────

def build_overview_section(results: Dict[str, Any], page) -> ft.Control:
    """Grade card + key metrics + sparkline + quality gate."""
    from UI.tabs.shared import (
        build_dimension_cards, build_severity_bar,
        build_trend_indicator, build_sparkline, _build_grade_card,
        _build_penalty_chips,
    )

    grade = results.get("grade", {})
    meta  = results.get("meta", {})
    letter = grade.get("letter", "?")
    score  = grade.get("score", 0)
    color  = GRADE_COLORS.get(letter, "#6b7280")
    gate   = results.get("_gate", {})

    grade_card = _build_grade_card(grade, narrow=False)
    dimension_cards = build_dimension_cards(grade.get("breakdown", {}))
    severity_bar = build_severity_bar(results)

    stats = ft.Row([
        metric_tile("📄", meta.get("files", 0), "Files"),
        metric_tile("🔧", meta.get("functions", 0), "Functions"),
        metric_tile("🏛️", meta.get("classes", 0), "Classes"),
        metric_tile("⏱️", f"{meta.get('duration', 0):.1f}s", "Duration"),
    ], spacing=8, wrap=True)

    # Quality Gate banner
    gate_banner = ft.Container()
    if gate and not gate.get("error"):
        passed = gate.get("passed", True)
        g_badge = gate.get("badge", "")
        g_score = gate.get("score", 0)
        violations = gate.get("violations", [])
        gate_color = "#10b981" if passed else "#ef4444"
        gate_banner = ft.Container(
            content=ft.Row([
                ft.Text(g_badge, size=SZ_LG),
                ft.Column([
                    ft.Text("Quality Gate", size=SZ_XS, color=TH.muted),
                    ft.Text(f"Score {g_score:.0f} · "
                            f"{'PASSED — CI build can proceed' if passed else f'{len(violations)} violation(s)'}",
                            size=SZ_SM, color=gate_color),
                ], spacing=0, expand=True),
            ], spacing=12),
            bgcolor=ft.Colors.with_opacity(0.08, gate_color),
            border=ft.border.all(1, gate_color),
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
        )

    return ft.Column([
        section_title("📊 Overview", ""),
        ft.Row([grade_card, ft.Container(expand=True), stats], spacing=16,
               vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Divider(color=TH.divider, height=20),
        gate_banner,
        ft.Divider(color=TH.divider, height=8) if gate else ft.Container(),
        severity_bar,
        ft.Divider(color=TH.divider, height=20),
        section_title("Dimension Scores", ""),
        dimension_cards,
    ], spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)


# ── Issues section — unified smells + lint + security ─────────────────────────

def build_issues_section(results: Dict[str, Any], page) -> ft.Control:
    """Unified issues view: summary + All Issues list."""
    from UI.tabs.shared import _empty_result_box
    from UI.tabs.smells_tab import _build_smells_tab
    from UI.tabs.duplicates_tab import _build_duplicates_tab
    from UI.tabs.lint_tab import _build_lint_tab
    from UI.tabs.security_tab import _build_security_tab

    sel = [0]

    def _sub_nav(labels, panels, sel_ref):
        """Build mini horizontal sub-nav pills inside a section."""
        panel_container = ft.Column([panels[0]] if panels else [], expand=True, spacing=0)

        def _on_click(idx):
            def handler(e):
                sel_ref[0] = idx
                panel_container.controls = [panels[idx]]
                for i, pill in enumerate(pill_row.controls):
                    pill.bgcolor = _RAIL_SEL if i == idx else TH.card
                    pill.content.color = "#0a0e1a" if i == idx else TH.dim
                page.update()
            return handler

        pills = []
        for i, lbl in enumerate(labels):
            styles = dict(bgcolor=_RAIL_SEL if i == 0 else TH.card)
            pills.append(ft.Container(
                content=ft.Text(lbl, size=SZ_SM,
                                color="#0a0e1a" if i == 0 else TH.dim),
                **styles,
                border_radius=16,
                padding=ft.padding.symmetric(horizontal=12, vertical=5),
                on_click=_on_click(i),
            ))
        pill_row = ft.Row(pills, spacing=6, scroll=ft.ScrollMode.AUTO)
        return ft.Column([pill_row, ft.Container(height=12), panel_container],
                         spacing=0, expand=True)

    labels, panels = [], []
    all_issues = []
    from UI.tabs.shared import _collect_all_issues, _build_all_issues_tab

    all_issues = _collect_all_issues(results)
    if all_issues:
        labels.append(f"All Issues ({len(all_issues)})")
        panels.append(_build_all_issues_tab(all_issues, results, page))
    if results.get("smells"):
        labels.append("🐛 Smells")
        panels.append(_build_smells_tab(results))
    if results.get("duplicates"):
        labels.append("🧬 Duplicates")
        panels.append(_build_duplicates_tab(results))
    if results.get("lint"):
        labels.append("📋 Lint")
        panels.append(_build_lint_tab(results))
    if results.get("security"):
        labels.append("🔒 Security")
        panels.append(_build_security_tab(results))

    if not panels:
        return ft.Column([
            section_title("🐛 Issues", ""),
            _empty_result_box(),
        ], spacing=10)

    return ft.Column([
        section_title("🐛 Issues", ""),
        _sub_nav(labels, panels, sel),
    ], spacing=10, expand=True)


# ── Architecture section ───────────────────────────────────────────────────────

def build_arch_section(results: Dict[str, Any], page) -> ft.Control:
    """Graph + Heatmap + Complexity + Diagrams."""
    from UI.tabs.graph_tab import _build_graph_tab
    from UI.tabs.heatmap_tab import _build_heatmap_tab
    from UI.tabs.complexity_tab import _build_complexity_tab
    from UI.tabs.diagrams_tab import _build_diagrams_tab

    sel = [0]
    labels, panels = [], []
    if results.get("_functions"):
        labels.append("🗺️ Import Graph")
        panels.append(_build_graph_tab(results, page))
        labels.append("🔥 Heatmap")
        panels.append(_build_heatmap_tab(results))
        labels.append("📈 Complexity")
        panels.append(_build_complexity_tab(results))
    if results.get("_diagrams", {}).get("mermaid_flowchart"):
        labels.append("🏗️ C4 Diagrams")
        panels.append(_build_diagrams_tab(results, page))

    if not panels:
        return ft.Column([
            section_title("🏗️ Architecture", ""),
            ft.Container(
                content=ft.Column([
                    ft.Text("🏗️", size=48, text_align=ft.TextAlign.CENTER),
                    ft.Text("No architecture data yet — run a scan first.",
                            size=SZ_BODY, color=TH.dim, text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                padding=40,
            ),
        ], spacing=10)

    panel_container = ft.Column([panels[0]], expand=True, spacing=0)

    def _on_click(idx):
        def handler(e):
            sel[0] = idx
            panel_container.controls = [panels[idx]]
            for i, pill in enumerate(pill_row.controls):
                pill.bgcolor = _RAIL_SEL if i == idx else TH.card
                pill.content.color = "#0a0e1a" if i == idx else TH.dim
            page.update()
        return handler

    pills = [
        ft.Container(
            content=ft.Text(lbl, size=SZ_SM, color="#0a0e1a" if i == 0 else TH.dim),
            bgcolor=_RAIL_SEL if i == 0 else TH.card,
            border_radius=16,
            padding=ft.padding.symmetric(horizontal=12, vertical=5),
            on_click=_on_click(i),
        )
        for i, lbl in enumerate(labels)
    ]
    pill_row = ft.Row(pills, spacing=6, scroll=ft.ScrollMode.AUTO)

    return ft.Column([
        section_title("🏗️ Architecture", ""),
        pill_row,
        ft.Container(height=12),
        panel_container,
    ], spacing=8, expand=True)


# ── Actions section ───────────────────────────────────────────────────────────

def build_actions_section(results: Dict[str, Any], page) -> ft.Control:
    """Auto-Rustify, Test Gen, Nexus Mode."""
    from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab
    from UI.tabs.nexus_tab import _build_nexus_tab
    from UI.tabs.rustify_tab import _build_rustify_tab

    sel = [0]
    labels, panels = [], []
    if results.get("_functions"):
        labels.append("⚡ Auto-Rustify")
        panels.append(_build_auto_rustify_tab(results, page))
        labels.append("🌐 Nexus Mode")
        panels.append(_build_nexus_tab(results, page))
        labels.append("🦀 Rustify")
        panels.append(_build_rustify_tab(results, page))

    if not panels:
        return ft.Column([
            section_title("⚡ Actions", ""),
            ft.Container(
                content=ft.Text("Run a scan to unlock Rustify, Test Gen, and Nexus Mode.",
                                size=SZ_BODY, color=TH.dim),
                padding=40,
            ),
        ], spacing=10)

    panel_container = ft.Column([panels[0]], expand=True, spacing=0)

    def _on_click(idx):
        def handler(e):
            panel_container.controls = [panels[idx]]
            for i, pill in enumerate(pill_row.controls):
                pill.bgcolor = _RAIL_SEL if i == idx else TH.card
                pill.content.color = "#0a0e1a" if i == idx else TH.dim
            page.update()
        return handler

    pills = [
        ft.Container(
            content=ft.Text(lbl, size=SZ_SM, color="#0a0e1a" if i == 0 else TH.dim),
            bgcolor=_RAIL_SEL if i == 0 else TH.card,
            border_radius=16,
            padding=ft.padding.symmetric(horizontal=12, vertical=5),
            on_click=_on_click(i),
        )
        for i, lbl in enumerate(labels)
    ]
    pill_row = ft.Row(pills, spacing=6, scroll=ft.ScrollMode.AUTO)

    return ft.Column([
        section_title("⚡ Actions", ""),
        pill_row,
        ft.Container(height=12),
        panel_container,
    ], spacing=8, expand=True)


# ── Settings section ─────────────────────────────────────────────────────────

def build_settings_section(state: Dict[str, Any], page, results=None) -> ft.Control:
    """Theme, language, export buttons — clean and simple."""
    import json
    from pathlib import Path
    from UI.tabs.shared import _show_snack, build_html_report, _build_markdown_report

    def on_theme(e):
        from UI.tabs.shared import TH as _TH
        _TH.toggle()
        page.data["_onboarded"] = True
        page.controls.clear()
        from x_ray_flet import main as _main
        page.run_task(_main, page)

    def on_export_json(e):
        if not results:
            _show_snack(page, "Run a scan first.", bgcolor=ft.Colors.AMBER_400)
            return
        try:
            export = {k: v for k, v in results.items() if not k.startswith("_")}
            path = Path(state["root_path"]) / "xray_report.json"
            path.write_text(json.dumps(export, indent=2, default=str), encoding="utf-8")
            _show_snack(page, f"✓ Saved to {path}")
        except Exception as exc:
            _show_snack(page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    def on_export_md(e):
        if not results:
            _show_snack(page, "Run a scan first.", bgcolor=ft.Colors.AMBER_400)
            return
        try:
            md = _build_markdown_report(results)
            path = Path(state["root_path"]) / "xray_report.md"
            path.write_text(md, encoding="utf-8")
            _show_snack(page, f"✓ Saved to {path}")
        except Exception as exc:
            _show_snack(page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    def on_export_html(e):
        if not results:
            _show_snack(page, "Run a scan first.", bgcolor=ft.Colors.AMBER_400)
            return
        try:
            html = build_html_report(results)
            path = Path(state["root_path"]) / "xray_report.html"
            path.write_text(html, encoding="utf-8")
            _show_snack(page, f"✓ HTML report saved to {path}")
        except Exception as exc:
            _show_snack(page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    is_dark = TH.bg < "#888888"

    return ft.Column([
        section_title("⚙️ Settings", ""),
        glass_card(ft.Column([
            ft.Text("Appearance", size=SZ_SM, weight=ft.FontWeight.BOLD, color=TH.muted),
            ft.Row([
                ft.Text("Dark mode", size=SZ_BODY, color=TH.text, expand=True),
                ft.Switch(value=True, on_change=on_theme,
                          active_color=_RAIL_SEL, inactive_thumb_color=TH.dim),
            ]),
            ft.Divider(color=TH.divider, height=16),
            ft.Text("Export", size=SZ_SM, weight=ft.FontWeight.BOLD, color=TH.muted),
            ft.Row([
                ft.OutlinedButton("JSON", icon=ft.Icons.CODE, on_click=on_export_json),
                ft.OutlinedButton("Markdown", icon=ft.Icons.ARTICLE, on_click=on_export_md),
                ft.OutlinedButton("HTML Report", icon=ft.Icons.WEB, on_click=on_export_html),
            ], spacing=8, wrap=True),
            ft.Divider(color=TH.divider, height=16),
            ft.Text(f"X-Ray v{__version__}  ·  AST · Ruff · Bandit · Rust",
                    size=SZ_XS, color=TH.muted),
        ], spacing=8), padding=16),
    ], spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)


# ── Main shell builder ────────────────────────────────────────────────────────

def build_shell_v2(
    page: ft.Page,
    state: Dict[str, Any],
    on_scan: Callable,
    on_pick_dir: Callable,
    on_apply_path: Callable,
    results: Optional[Dict[str, Any]] = None,
) -> ft.Row:
    """
    Build the full v2 shell — returns a ft.Row(rail + content).

    The returned Row should be page.add()'d directly.
    The shell maintains its own selected-section state and re-builds
    the content area on each navigation click.
    """
    sel = [SEC_HOME if results is None else SEC_OVERVIEW]
    content_area = ft.Container(expand=True, bgcolor=TH.bg,
                                padding=ft.padding.symmetric(horizontal=30, vertical=20))

    from UI.tabs.debt_tab import _build_debt_tab

    def _render_section(section_id: str):
        """Render the right panel for the selected section."""
        if section_id == SEC_HOME:
            return build_home_section(state, on_scan, on_pick_dir, on_apply_path, results)
        elif section_id == SEC_OVERVIEW and results:
            return build_overview_section(results, page)
        elif section_id == SEC_ISSUES and results:
            return build_issues_section(results, page)
        elif section_id == SEC_DEBT and results:
            return _build_debt_tab(results)
        elif section_id == SEC_ARCH and results:
            return build_arch_section(results, page)
        elif section_id == SEC_ACTIONS and results:
            return build_actions_section(results, page)
        elif section_id == SEC_SETTINGS:
            return build_settings_section(state, page, results)
        else:
            return build_home_section(state, on_scan, on_pick_dir, on_apply_path, results)

    rail_ref = [None]

    def navigate(section_id: str):
        sel[0] = section_id
        # Re-render the rail to update selection highlight
        new_rail = build_left_rail(section_id, navigate, results)
        shell_row.controls[0] = new_rail
        # Re-render the content
        content_area.content = _render_section(section_id)
        page.update()

    # Initial render
    content_area.content = _render_section(sel[0])
    rail = build_left_rail(sel[0], navigate, results)

    shell_row = ft.Row(
        [rail, content_area],
        expand=True,
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return shell_row
