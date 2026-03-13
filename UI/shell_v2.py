"""
UI/shell_v2.py — X-Ray v8.0 Redesigned Shell
==============================================

Replaces the old sidebar + 15-pill tab system with:
  - LEFT ICON RAIL (64px): 7 grouped sections, always visible
  - MAIN CONTENT (expands): one section at a time
  - HOME VIEW: just drop a path + one big Scan button
  - RESULTS VIEW: grade hero + section router

Section map:
  🏠  Home    — path input + Scan button
  📊  Overview — grade, score, dimensions, quality gate
  🐛  Issues  — all issues, smells, duplicates, lint, security
  💸  Debt    — SATD, hotspots, temporal coupling, AI debt
  🏗️  Architecture — graph, heatmap, complexity, diagrams
  ⚡  Actions — auto-rustify, nexus, test gen
  ⚙️  Settings — theme, language, export
"""

from __future__ import annotations
import flet as ft
from typing import Any, Callable, Dict, List, Optional

from UI.tabs.shared import (
    TH,
    glass_card,
    metric_tile,
    section_title,
    SZ_XS,
    SZ_SM,
    SZ_BODY,
    SZ_LG,
    SZ_H3,
    SZ_HERO,
    SZ_DISPLAY,
    MONO_FONT,
    GRADE_COLORS,
    build_dimension_cards,
    build_severity_bar,
    build_html_report,
    _build_markdown_report,
    _show_snack,
)
from Core.config import __version__

# ── Rail section IDs ──────────────────────────────────────────────────────────
SEC_HOME = "home"
SEC_OVERVIEW = "overview"
SEC_ISSUES = "issues"
SEC_DEBT = "debt"
SEC_ARCH = "arch"
SEC_ACTIONS = "actions"
SEC_SETTINGS = "settings"

_RAIL_ENTRIES = [
    (SEC_HOME, "🏠", "Home"),
    (SEC_OVERVIEW, "📊", "Overview"),
    (SEC_ISSUES, "🐛", "Issues"),
    (SEC_DEBT, "💸", "Debt"),
    (SEC_ARCH, "🏗️", "Arch"),
    (SEC_ACTIONS, "⚡", "Actions"),
    (SEC_SETTINGS, "⚙️", "Settings"),
]

_RAIL_W = 64
_RAIL_SEL = "#00d4ff"
_RAIL_DIM = "#4b5563"


# ── Shared sub-nav helper ─────────────────────────────────────────────────────


def _make_sub_nav(
    labels: List[str], panels: List[ft.Control], sel_ref: List[int], page
) -> ft.Column:
    """Horizontal pill sub-navigation used inside every section."""
    panel_box = ft.Column([panels[0]] if panels else [], expand=True, spacing=0)

    def _on_click(idx):
        def handler(e):
            sel_ref[0] = idx
            panel_box.controls = [panels[idx]]
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
            padding=ft.Padding.symmetric(horizontal=12, vertical=5),
            on_click=_on_click(i),
        )
        for i, lbl in enumerate(labels)
    ]
    pill_row = ft.Row(pills, spacing=6, scroll=ft.ScrollMode.AUTO)
    return ft.Column(
        [pill_row, ft.Container(height=12), panel_box], spacing=0, expand=True
    )


# ── Left icon rail ────────────────────────────────────────────────────────────


def _rail_icon(
    section_id: str,
    emoji: str,
    label: str,
    is_selected: bool,
    on_click: Callable,
    badge: int = 0,
) -> ft.Container:
    """Single icon-rail button."""

    def _click(e):
        on_click(section_id)

    badge_ctrl = []
    if badge > 0:
        badge_ctrl = [
            ft.Container(
                content=ft.Text(
                    str(badge) if badge < 100 else "99+",
                    size=8,
                    color=ft.Colors.WHITE,
                    text_align=ft.TextAlign.CENTER,
                ),
                bgcolor="#ef4444",
                border_radius=8,
                width=16,
                height=16,
                alignment=ft.Alignment(0, 0),
                right=4,
                top=4,
            )
        ]

    return ft.Container(
        content=ft.Stack(
            [
                ft.Column(
                    [
                        ft.Text(emoji, size=20, text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            label,
                            size=8,
                            color=_RAIL_SEL if is_selected else _RAIL_DIM,
                            text_align=ft.TextAlign.CENTER,
                            max_lines=1,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                ),
                *badge_ctrl,
            ]
        ),
        width=_RAIL_W,
        height=58,
        bgcolor=ft.Colors.with_opacity(0.12, _RAIL_SEL)
        if is_selected
        else "transparent",
        border_radius=10,
        alignment=ft.Alignment(0, 0),
        on_click=_click,
        animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        tooltip=label,
    )


def build_left_rail(
    selected: str, navigate: Callable, results: Optional[Dict[str, Any]] = None
) -> ft.Container:
    """64px left icon rail."""

    def _badge(sec: str) -> int:
        if results is None:
            return 0
        if sec == SEC_ISSUES:
            return results.get("smells", {}).get("critical", 0) + results.get(
                "security", {}
            ).get("critical", 0)
        return 0

    icons: List[ft.Control] = [
        ft.Container(
            content=ft.Text(
                "☢", size=22, text_align=ft.TextAlign.CENTER, color=_RAIL_SEL
            ),
            width=_RAIL_W,
            height=48,
            alignment=ft.Alignment(0, 0),
            tooltip="X-RAY",
        ),
        ft.Divider(color=TH.divider, height=12),
    ]

    for i, (sec_id, emoji, label) in enumerate(_RAIL_ENTRIES):
        if results is None and sec_id not in (SEC_HOME, SEC_SETTINGS):
            icons.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                emoji,
                                size=20,
                                text_align=ft.TextAlign.CENTER,
                                opacity=0.25,
                            ),
                            ft.Text(
                                label,
                                size=8,
                                color="#374151",
                                text_align=ft.TextAlign.CENTER,
                                max_lines=1,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=0,
                    ),
                    width=_RAIL_W,
                    height=58,
                    alignment=ft.Alignment(0, 0),
                    tooltip=f"{label} — scan first",
                )
            )
        else:
            icons.append(
                _rail_icon(
                    sec_id,
                    emoji,
                    label,
                    is_selected=(sec_id == selected),
                    on_click=navigate,
                    badge=_badge(sec_id),
                )
            )
        # Separator before Settings
        if i == len(_RAIL_ENTRIES) - 2:
            icons.append(ft.Divider(color=TH.divider, height=8))

    return ft.Container(
        content=ft.Column(
            icons,
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.HIDDEN,
        ),
        width=_RAIL_W,
        bgcolor=TH.surface,
        border=ft.Border.only(right=ft.BorderSide(1, TH.divider)),
        padding=ft.Padding.symmetric(vertical=8),
    )


# ── Home section ──────────────────────────────────────────────────────────────


def _build_last_scan_card(results: Dict[str, Any]) -> ft.Control:
    """Build the last scan summary card shown on the home page."""
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    letter = grade.get("letter", "?")
    color = GRADE_COLORS.get(letter, "#6b7280")
    score = grade.get("score", 0)
    n_files = meta.get("files", 0)
    dur = meta.get("duration", 0)
    sp = results.get("_scan_path", "?")
    proj = str(sp).split("\\")[-1] if "\\" in str(sp) else str(sp)
    return glass_card(
        ft.Column(
            [
                ft.Text("Last scan", size=SZ_XS, color=TH.muted),
                ft.Row(
                    [
                        ft.Text(
                            letter,
                            size=40,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                            font_family=MONO_FONT,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    proj,
                                    size=SZ_LG,
                                    weight=ft.FontWeight.W_600,
                                    color=TH.text,
                                ),
                                ft.Text(
                                    f"Score {score:.0f}/100 · {n_files} files · {dur:.1f}s",
                                    size=SZ_SM,
                                    color=TH.dim,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Click 📊 Overview in the rail to see full results →",
                    size=SZ_XS,
                    color=TH.muted,
                ),
            ],
            spacing=6,
        ),
        padding=16,
    )


def build_home_section(
    state: Dict[str, Any],
    on_scan: Callable,
    on_pick_dir: Callable,
    on_apply_path: Callable,
    results: Optional[Dict[str, Any]] = None,
) -> ft.Control:
    """Clean landing: logo + path input + Scan button."""

    path_val = state.get("root_path", "")
    path_input = ft.TextField(
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
        on_submit=lambda e: on_apply_path(e.control.value),
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

    recent = state.get("recent_paths", [])
    recent_chips = []
    for p in recent[:5]:
        short = ("…" + p[-34:]) if len(p) > 36 else p
        recent_chips.append(
            ft.Container(
                content=ft.Text(short, size=SZ_XS, color=TH.dim, no_wrap=True),
                bgcolor=TH.card,
                border=ft.Border.all(1, TH.border),
                border_radius=20,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=lambda e, path=p: on_apply_path(path),
                tooltip=p,
            )
        )

    # Last scan summary card
    last_scan: ft.Control = ft.Container()
    if results:
        last_scan = _build_last_scan_card(results)

    feature_chips = ft.Row(
        [
            _chip("🐛 Smells"),
            _chip("🔒 Security"),
            _chip("🧬 Duplicates"),
            _chip("🔥 Hotspots"),
            _chip("💸 SATD Debt"),
            _chip("🤖 AI Debt"),
            _chip("🏗️ Diagrams"),
            _chip("⚡ Rustify"),
        ],
        spacing=6,
        wrap=True,
    )

    hero = ft.Column(
        [
            ft.Text(
                "☢  X-RAY",
                size=SZ_HERO,
                weight=ft.FontWeight.BOLD,
                color=_RAIL_SEL,
                font_family=MONO_FONT,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "Code Quality Intelligence · Drop a project folder and hit Scan",
                size=SZ_BODY,
                color=TH.dim,
                text_align=ft.TextAlign.CENTER,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=4,
    )

    input_row = ft.Row([browse_btn, path_input, scan_btn], spacing=8)
    recent_row = (
        ft.Row(recent_chips, spacing=6, scroll=ft.ScrollMode.AUTO)
        if recent_chips
        else ft.Container()
    )

    return ft.Container(
        content=ft.Column(
            [
                ft.Container(expand=True),
                hero,
                ft.Container(height=24),
                input_row,
                ft.Container(height=8),
                recent_row,
                ft.Container(height=32),
                feature_chips,
                ft.Container(height=32),
                last_scan,
                ft.Container(expand=True),
            ],
            expand=True,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        padding=ft.Padding.symmetric(horizontal=80, vertical=20),
    )


def _chip(label: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(label, size=SZ_XS, color=TH.dim),
        bgcolor=TH.card,
        border=ft.Border.all(1, TH.border),
        border_radius=20,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
    )


# ── Overview section ──────────────────────────────────────────────────────────


def build_overview_section(results: Dict[str, Any], page) -> ft.Control:
    """Grade + score + dimensions + quality gate."""
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    letter = grade.get("letter", "?")
    score = grade.get("score", 0)
    color = GRADE_COLORS.get(letter, "#6b7280")
    gate = results.get("_gate", {})

    grade_card = glass_card(
        ft.Row(
            [
                ft.Text(
                    letter,
                    size=SZ_DISPLAY,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    font_family=MONO_FONT,
                ),
                ft.Column(
                    [
                        ft.Text(
                            f"Score: {score:.0f} / 100",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            color=TH.text,
                        ),
                        ft.Text(grade.get("label", ""), size=SZ_BODY, color=TH.dim),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=20,
    )

    stats = ft.Row(
        [
            metric_tile("📄", meta.get("files", 0), "Files"),
            metric_tile("🔧", meta.get("functions", 0), "Functions"),
            metric_tile("🏛️", meta.get("classes", 0), "Classes"),
            metric_tile("⏱️", f"{meta.get('duration', 0):.1f}s", "Duration"),
        ],
        spacing=8,
        wrap=True,
    )

    # Quality Gate banner
    gate_banner: ft.Control = ft.Container()
    if gate and not gate.get("error"):
        passed = gate.get("passed", True)
        g_score = gate.get("score", 0)
        violations = gate.get("violations", [])
        gate_color = "#10b981" if passed else "#ef4444"
        gate_text = (
            "PASSED — CI build can proceed"
            if passed
            else f"{len(violations)} violation(s) — build blocked"
        )
        gate_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Text("✅" if passed else "❌", size=SZ_LG),
                    ft.Column(
                        [
                            ft.Text("Quality Gate", size=SZ_XS, color=TH.muted),
                            ft.Text(
                                f"Score {g_score:.0f}  ·  {gate_text}",
                                size=SZ_SM,
                                color=gate_color,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=12,
            ),
            bgcolor=ft.Colors.with_opacity(0.08, gate_color),
            border=ft.Border.all(1, gate_color),
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        )

    severity_bar = build_severity_bar(results)
    dimension_cards = build_dimension_cards(grade.get("breakdown", {}))

    return ft.Column(
        [
            section_title("📊 Overview", ""),
            ft.Row(
                [grade_card, ft.Container(expand=True), stats],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Divider(color=TH.divider, height=20),
            gate_banner,
            severity_bar,
            ft.Divider(color=TH.divider, height=20),
            section_title("Dimension Scores", ""),
            dimension_cards,
        ],
        spacing=10,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


# ── Issues section ────────────────────────────────────────────────────────────


def build_issues_section(results: Dict[str, Any], page) -> ft.Control:
    """All Issues + Smells + Duplicates + Lint + Security sub-tabs."""
    from UI.tabs.smells_tab import _build_smells_tab
    from UI.tabs.duplicates_tab import _build_duplicates_tab
    from UI.tabs.lint_tab import _build_lint_tab
    from UI.tabs.security_tab import _build_security_tab

    sel = [0]
    labels: List[str] = []
    panels: List[ft.Control] = []

    # Unified list — lazy import from x_ray_flet to avoid circular dependency
    try:
        import x_ray_flet as _xrf

        all_issues = _xrf._collect_all_issues(results)
        if all_issues:
            labels.append(f"All Issues ({len(all_issues)})")
            panels.append(_xrf._build_all_issues_tab(all_issues, results, page))
    except Exception:
        pass

    if results.get("smells") and not results["smells"].get("error"):
        labels.append("🐛 Smells")
        panels.append(_build_smells_tab(results))
    if results.get("duplicates") and not results["duplicates"].get("error"):
        labels.append("🧬 Duplicates")
        panels.append(_build_duplicates_tab(results))
    if results.get("lint") and not results["lint"].get("error"):
        labels.append("📋 Lint")
        panels.append(_build_lint_tab(results, page))
    if results.get("security") and not results["security"].get("error"):
        labels.append("🔒 Security")
        panels.append(_build_security_tab(results))

    if not panels:
        return ft.Column(
            [
                section_title("🐛 Issues", ""),
                ft.Container(
                    content=ft.Text(
                        "No issues found — great job! 🎉",
                        size=SZ_BODY,
                        color=TH.dim,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=40,
                ),
            ],
            spacing=10,
        )

    return ft.Column(
        [
            section_title("🐛 Issues", ""),
            _make_sub_nav(labels, panels, sel, page),
        ],
        spacing=10,
        expand=True,
    )


# ── Architecture section ──────────────────────────────────────────────────────


def build_arch_section(results: Dict[str, Any], page) -> ft.Control:
    """Graph + Heatmap + Complexity + Diagrams."""
    from UI.tabs.graph_tab import _build_graph_tab
    from UI.tabs.heatmap_tab import _build_heatmap_tab
    from UI.tabs.complexity_tab import _build_complexity_tab
    from UI.tabs.diagrams_tab import _build_diagrams_tab

    sel = [0]
    labels: List[str] = []
    panels: List[ft.Control] = []

    if results.get("_functions") or results.get("smells"):
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
        return ft.Column(
            [
                section_title("🏗️ Architecture", ""),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("🏗️", size=48, text_align=ft.TextAlign.CENTER),
                            ft.Text(
                                "Run a scan to see architecture diagrams.",
                                size=SZ_BODY,
                                color=TH.dim,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    padding=40,
                ),
            ],
            spacing=10,
        )

    return ft.Column(
        [
            section_title("🏗️ Architecture", ""),
            _make_sub_nav(labels, panels, sel, page),
        ],
        spacing=8,
        expand=True,
    )


# ── Actions section ───────────────────────────────────────────────────────────


def build_actions_section(results: Dict[str, Any], page) -> ft.Control:
    """Auto-Rustify, Nexus Mode, Rustify."""
    from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab
    from UI.tabs.nexus_tab import _build_nexus_tab
    from UI.tabs.rustify_tab import _build_rustify_tab

    sel = [0]
    labels: List[str] = []
    panels: List[ft.Control] = []

    if results.get("_functions") or results.get("rustify"):
        labels.append("⚡ Auto-Rustify")
        panels.append(_build_auto_rustify_tab(results, page))
        labels.append("🌐 Nexus Mode")
        panels.append(_build_nexus_tab(results, page))
        labels.append("🦀 Rustify")
        panels.append(_build_rustify_tab(results))

    if not panels:
        return ft.Column(
            [
                section_title("⚡ Actions", ""),
                ft.Container(
                    content=ft.Text(
                        "Run a scan to unlock Rustify, Test Gen, and Nexus Mode.",
                        size=SZ_BODY,
                        color=TH.dim,
                    ),
                    padding=40,
                ),
            ],
            spacing=10,
        )

    return ft.Column(
        [
            section_title("⚡ Actions", ""),
            _make_sub_nav(labels, panels, sel, page),
        ],
        spacing=8,
        expand=True,
    )


# ── Settings section ──────────────────────────────────────────────────────────


def build_settings_section(
    state: Dict[str, Any], page, results: Optional[Dict[str, Any]] = None
) -> ft.Control:
    """Theme, export, version info."""
    import json
    from pathlib import Path

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
            _show_snack(page, f"✓ HTML saved to {path}")
        except Exception as exc:
            _show_snack(page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    def on_theme(e):
        TH.toggle()
        page.data["_onboarded"] = True
        page.controls.clear()
        import x_ray_flet as _xrf

        page.run_task(_xrf.main, page)

    return ft.Column(
        [
            section_title("⚙️ Settings", ""),
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            "Appearance",
                            size=SZ_SM,
                            weight=ft.FontWeight.BOLD,
                            color=TH.muted,
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    "Dark mode",
                                    size=SZ_BODY,
                                    color=TH.text,
                                    expand=True,
                                ),
                                ft.Switch(
                                    value=True,
                                    on_change=on_theme,
                                    active_color=_RAIL_SEL,
                                    inactive_thumb_color=TH.dim,
                                ),
                            ]
                        ),
                        ft.Divider(color=TH.divider, height=16),
                        ft.Text(
                            "Export",
                            size=SZ_SM,
                            weight=ft.FontWeight.BOLD,
                            color=TH.muted,
                        ),
                        ft.Row(
                            [
                                ft.OutlinedButton(
                                    "JSON", icon=ft.Icons.CODE, on_click=on_export_json
                                ),
                                ft.OutlinedButton(
                                    "Markdown",
                                    icon=ft.Icons.ARTICLE,
                                    on_click=on_export_md,
                                ),
                                ft.OutlinedButton(
                                    "HTML", icon=ft.Icons.WEB, on_click=on_export_html
                                ),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        ft.Divider(color=TH.divider, height=16),
                        ft.Text(
                            f"X-Ray v{__version__}  ·  Ctrl+S Scan  ·  Ctrl+E JSON export",
                            size=SZ_XS,
                            color=TH.muted,
                        ),
                    ],
                    spacing=8,
                ),
                padding=16,
            ),
        ],
        spacing=10,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


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
    Caller should set page_container.content = build_shell_v2(...).
    """
    from UI.tabs.debt_tab import _build_debt_tab

    sel = [SEC_HOME if results is None else SEC_OVERVIEW]
    content_area = ft.Container(
        expand=True,
        bgcolor=TH.bg,
        padding=ft.Padding.symmetric(horizontal=30, vertical=20),
    )

    def _render(section_id: str) -> ft.Control:
        if section_id == SEC_HOME:
            return build_home_section(
                state, on_scan, on_pick_dir, on_apply_path, results
            )
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
            return build_home_section(
                state, on_scan, on_pick_dir, on_apply_path, results
            )

    def navigate(section_id: str):
        sel[0] = section_id
        shell_row.controls[0] = build_left_rail(section_id, navigate, results)
        content_area.content = _render(section_id)
        page.update()

    content_area.content = _render(sel[0])
    rail = build_left_rail(sel[0], navigate, results)

    shell_row = ft.Row(
        [rail, content_area],
        expand=True,
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return shell_row
