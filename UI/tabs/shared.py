"""
UI/tabs/shared.py - Shared rendering helpers, layout constants, and themes for Flet.
"""

import flet as ft
from Core.i18n import t

MONO_FONT = "Cascadia Code, Consolas, SF Mono, monospace"

SZ_XS = 11
SZ_SM = 12
SZ_BODY = 13
SZ_MD = 14
SZ_LG = 15
SZ_SECTION = 17
SZ_H3 = 18
SZ_H2 = 22
SZ_SIDEBAR = 24
SZ_HERO = 34
SZ_DISPLAY = 40

BTN_H_SM = 36
BTN_H_MD = 40
BTN_RADIUS = 10

BP_NARROW = 900


def _page_width(page: ft.Page) -> int:
    w = page.width
    return int(w) if w and w > 0 else BP_NARROW - 1


def is_narrow(page: ft.Page) -> bool:
    return _page_width(page) < BP_NARROW


GRADE_COLORS = {
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

SEV_ICONS = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
SEV_COLORS = {
    "critical": ft.Colors.RED_400,
    "warning": ft.Colors.AMBER_400,
    "info": ft.Colors.GREEN_400,
}


class _THMeta(type):
    _KEYS = frozenset(
        {
            "accent",
            "accent2",
            "bg",
            "card",
            "surface",
            "border",
            "text",
            "dim",
            "muted",
            "code_bg",
            "sidebar",
            "shadow",
            "divider",
            "bar_bg",
            "chip",
        }
    )

    def __getattr__(cls, name: str) -> str:
        if name in cls._KEYS:
            p = cls._DARK if cls._dark else cls._LIGHT
            return p[name]
        raise AttributeError(name)


class TH(metaclass=_THMeta):
    """Centralised theme accessor. Use TH.accent, TH.bg, etc.

    Delegates attribute access to `_DARK` or `_LIGHT` via `_THMeta.__getattr__`.
    Toggle with `TH.toggle()`.
    """

    _dark = True
    _DARK = dict(
        accent="#00d4ff",
        accent2="#7c4dff",
        bg="#0a0e14",
        card="#141820",
        surface="#0f1319",
        border="#ffffff12",
        text="#e6edf3",
        dim="#8b949e",
        muted="#484f58",
        code_bg="#0d1117",
        sidebar="#0f1319",
        shadow="#00000040",
        divider="#ffffff0a",
        bar_bg="#ffffff08",
        chip="#141820",
    )
    _LIGHT = dict(
        accent="#0078d4",
        accent2="#5b2fb0",
        bg="#f6f8fa",
        card="#ffffff",
        surface="#f0f2f5",
        border="#d0d7de",
        text="#1f2328",
        dim="#656d76",
        muted="#8b949e",
        code_bg="#f6f8fa",
        sidebar="#ffffff",
        shadow="#0000001a",
        divider="#d8dee4",
        bar_bg="#0000000a",
        chip="#f0f2f5",
    )

    @classmethod
    def is_dark(cls) -> bool:
        return cls._dark

    @classmethod
    def toggle(cls):
        cls._dark = not cls._dark


def _show_snack(page, text: str, bgcolor=None):
    page.overlay[:] = [c for c in page.overlay if not isinstance(c, ft.SnackBar)]
    sb = ft.SnackBar(content=ft.Text(text), open=True)
    if bgcolor:
        sb.bgcolor = bgcolor
    page.overlay.append(sb)
    page.update()


def glass_card(content, padding=20, expand=False, **kw):
    return ft.Container(
        content=content,
        bgcolor=TH.card,
        border=ft.Border.all(1, TH.border),
        border_radius=16,
        padding=padding,
        expand=expand,
        shadow=ft.BoxShadow(blur_radius=8, color=TH.shadow),
        **kw,
    )


def metric_tile(icon, value, label: str, color=None):
    """Small metric card with icon, bold value, and label."""
    color = color or TH.accent
    if isinstance(icon, str):
        icon_widget = ft.Text(icon, size=SZ_H3, text_align=ft.TextAlign.CENTER)
    elif isinstance(icon, int):
        # ft.Icons.* enums are ints in Flet 0.80+ — wrap in ft.Icon widget
        icon_widget = ft.Icon(icon, size=SZ_H3, color=color)
    else:
        icon_widget = icon
    return ft.Container(
        content=ft.Column(
            [
                icon_widget,
                ft.Text(
                    str(value),
                    size=SZ_SECTION,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    font_family=MONO_FONT,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    label, size=SZ_BODY, color=TH.dim, text_align=ft.TextAlign.CENTER
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        bgcolor=TH.card,
        border=ft.Border.all(1, TH.border),
        border_radius=14,
        padding=ft.Padding.symmetric(vertical=14, horizontal=10),
        width=140,
        shadow=ft.BoxShadow(blur_radius=6, color=TH.shadow),
    )


def section_title(text: str, icon=""):
    if icon and not isinstance(icon, str):
        # ft.Icons.* enum values are ints — render as an actual icon widget
        return ft.Row(
            [
                ft.Icon(icon, color=TH.accent, size=SZ_SECTION + 4),
                ft.Text(
                    text,
                    size=SZ_SECTION,
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                    font_family=MONO_FONT,
                ),
            ],
            spacing=6,
        )
    return ft.Text(
        f"{icon} {text}" if icon else text,
        size=SZ_SECTION,
        weight=ft.FontWeight.BOLD,
        color=TH.accent,
        font_family=MONO_FONT,
    )


def _make_proportional_bar(pct: float, color: str):
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    bgcolor=color,
                    border_radius=4,
                    expand=round(max(pct, 0.01) * 100),
                    height=14,
                ),
                ft.Container(expand=round((1 - pct) * 100), height=14)
                if pct < 1.0
                else ft.Container(width=0),
            ],
            spacing=0,
        ),
        bgcolor=TH.bar_bg,
        border_radius=4,
        expand=True,
        height=14,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def bar_row_flex(label: str, count: int, max_count: int, color: str):
    """One labelled proportional bar row for use in bar charts.

    Args:
        label: Display name (truncated to fit).
        count: Absolute value for this row.
        max_count: Maximum value in the series (determines bar length).
        color: Hex or Flet color for the filled portion.
    """
    pct = count / max(max_count, 1)
    return ft.Row(
        [
            ft.Text(
                label,
                size=SZ_BODY,
                width=140,
                font_family=MONO_FONT,
                color=TH.dim,
                no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            _make_proportional_bar(pct, color),
            ft.Text(
                str(count),
                size=SZ_BODY,
                weight=ft.FontWeight.BOLD,
                font_family=MONO_FONT,
                width=44,
                color=TH.text,
            ),
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def bar_chart(items: list):
    if not items:
        return ft.Container()
    mx = max(c for _, c, _ in items) if items else 1
    return ft.Column(
        [bar_row_flex(lbl, c, mx, col) for lbl, c, col in items], spacing=4
    )


def _empty_result_box(label: str = "") -> ft.Container:
    text = label or f"[ok] {t('no_issues')}"
    return ft.Container(
        content=ft.Text(text, color=ft.Colors.GREEN_400, size=SZ_LG), padding=20
    )


def _empty_state(icon: str, title: str, subtitle: str = ""):
    return ft.Container(
        content=ft.Column(
            [
                ft.Text(icon, size=64),
                ft.Text(title, size=SZ_H3, weight=ft.FontWeight.BOLD, color=TH.text),
                ft.Text(subtitle, size=SZ_BODY, color=TH.dim)
                if subtitle
                else ft.Container(),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
    )


_CODE_SNIPPET_CHARS = 500  # max characters shown in inline code previews


def _code_snippet_container(
    snippet: str, limit: int = _CODE_SNIPPET_CHARS
) -> ft.Container:
    """Render a code snippet inside a styled dark container."""
    return ft.Container(
        content=ft.Text(
            snippet[:limit],
            font_family=MONO_FONT,
            size=SZ_SM,
            color=TH.dim,
            selectable=True,
            no_wrap=False,
        ),
        bgcolor=TH.code_bg,
        border_radius=8,
        padding=10,
        margin=ft.Margin.only(top=6),
    )


def _build_issue_tile(s, code_map: dict) -> ft.ExpansionTile:
    icon = SEV_ICONS.get(s.severity, "[?]")
    code = code_map.get(f"{s.file_path}:{s.line}", "")
    tile_controls = [
        ft.Text(f"{t('issue')}: {s.message}", weight=ft.FontWeight.BOLD, size=SZ_MD)
    ]
    if s.suggestion:
        tile_controls.append(
            ft.Text(
                f"{t('fix')}: {s.suggestion}", color=ft.Colors.BLUE_200, size=SZ_BODY
            )
        )
    if code:
        tile_controls.append(_code_snippet_container(code))
    return ft.ExpansionTile(
        title=ft.Text(f"{icon} [{s.category}] {s.name}", size=SZ_MD),
        subtitle=ft.Text(
            f"{s.file_path}:{s.line}", size=SZ_SM, italic=True, color=TH.muted
        ),
        controls=[
            ft.Container(
                content=ft.Column(tile_controls),
                padding=15,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8,
            )
        ],
        expanded=False,
    )


def _format_section(data: dict, title: str) -> list:
    if not data or data.get("error"):
        return []
    lines = [f"## {title}"]
    for k, v in data.items():
        if not k.startswith("_") and k != "error":
            lines.append(f"- {k}: {v}")
    lines.append("")
    return lines


def _build_markdown_report(results: dict) -> str:
    from Core.config import __version__

    grade = results.get("grade", {})
    meta = results.get("meta", {})
    lines = [
        "# X-Ray Code Quality Report",
        "",
        f"**Score:** {grade.get('score', '?')}/100 **Grade:** {grade.get('letter', '?')}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Files | {meta.get('files', 0)} |",
        f"| Functions | {meta.get('functions', 0)} |",
        f"| Classes | {meta.get('classes', 0)} |",
        f"| Duration | {meta.get('duration', 0):.1f}s |",
        "",
    ]
    for key, title in [
        ("smells", "Code Smells"),
        ("lint", "Lint"),
        ("security", "Security"),
        ("duplicates", "Duplicates"),
    ]:
        lines.extend(_format_section(results.get(key, {}), title))
    lines.append(f"---\\n*Generated by X-Ray v{__version__}*")
    return "\\n".join(lines)


# ── Complexity / Size chart constants (used by complexity_tab.py) ──────────

_CC_BUCKETS = ("1-3", "4-7", "8-14", "15-24", "25+")
_CC_LIMITS = (25, 15, 8, 4, 1)
_CC_COLORS = {
    "1-3": "#00c853",
    "4-7": "#64dd17",
    "8-14": "#ffd600",
    "15-24": "#ff6d00",
    "25+": "#d50000",
}
_SZ_BUCKETS = ("1-10", "11-25", "26-50", "51-100", "100+")
_SZ_LIMITS = (100, 50, 25, 10, 1)
_SZ_COLORS = {
    "1-10": "#00c853",
    "11-25": "#64dd17",
    "26-50": "#ffd600",
    "51-100": "#ff6d00",
    "100+": "#d50000",
}


def _bucket_values(values, bucket_names, limits):
    """Assign numeric values to named buckets using limit thresholds."""
    buckets = {b: 0 for b in bucket_names}
    for v in values:
        for lim, bname in zip(limits, bucket_names[::-1]):
            if v >= lim:
                buckets[bname] += 1
                break
    return buckets


# ── Code comparison panel (used by rustify_tab.py) ─────────────────────────


def _code_panel(label, emoji, code_text, color):
    """Build one side of the Python/Rust code comparison."""
    return ft.Column(
        [
            ft.Text(
                f"{emoji} {label}", size=SZ_SM, weight=ft.FontWeight.BOLD, color=color
            ),
            ft.Container(
                content=ft.Text(
                    code_text[:600],
                    font_family=MONO_FONT,
                    size=SZ_SM,
                    selectable=True,
                    color=TH.dim,
                    no_wrap=False,
                ),
                bgcolor=TH.code_bg,
                border_radius=8,
                padding=10,
                expand=True,
            ),
        ],
        expand=True,
        spacing=4,
    )


# Module-level API for test compatibility
_default_analyzer = _THMeta()

def is_dark(*args, **kwargs):
    """Wrapper for _THMeta.is_dark()."""
    return _default_analyzer.is_dark(*args, **kwargs)

def toggle(*args, **kwargs):
    """Wrapper for _THMeta.toggle()."""
    return _default_analyzer.toggle(*args, **kwargs)

