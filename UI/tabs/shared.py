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


def build_html_report(results: dict) -> str:
    """Generate a self-contained, professional HTML report."""
    from Core.config import __version__
    import datetime

    grade = results.get("grade", {})
    meta = results.get("meta", {})
    breakdown = grade.get("breakdown", {})
    score = grade.get("score", 0)
    letter = grade.get("letter", "?")
    color = GRADE_COLORS.get(letter, "#888")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build severity aggregates
    totals = _aggregate_severities(results)

    # Build breakdown rows
    breakdown_rows = ""
    for k, d in breakdown.items():
        p = d.get("penalty", 0)
        if p > 0:
            breakdown_rows += f"""
            <tr>
                <td>{k.replace('_', ' ').title()}</td>
                <td style="color: {'#ff6d00' if p > 5 else '#ffd600' if p > 2 else '#00c853'}">
                    -{p:.1f}
                </td>
            </tr>"""

    # Build dimension ratings
    dim_html = ""
    for dim_name, dim_info in _DIMENSION_MAP.items():
        dim_letter = _dimension_letter(breakdown, dim_info["keys"])
        dim_color = GRADE_COLORS.get(dim_letter, "#888")
        dim_html += f"""
        <div style="text-align:center;padding:12px 16px;border-radius:12px;
                    background:rgba({_hex_to_rgb(dim_color)},0.08);
                    border:1px solid rgba({_hex_to_rgb(dim_color)},0.25);min-width:80px;">
            <div style="font-size:24px;font-weight:bold;color:{dim_color};font-family:monospace;">
                {dim_letter}
            </div>
            <div style="font-size:11px;color:#8b949e;margin-top:2px;">{dim_name}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>X-Ray Code Quality Report</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
         background:#0a0e14; color:#e6edf3; padding:40px; }}
  .container {{ max-width:900px; margin:0 auto; }}
  .header {{ text-align:center; margin-bottom:32px; }}
  .header h1 {{ font-family:monospace; color:#00d4ff; font-size:32px;
                letter-spacing:2px; }}
  .header .subtitle {{ color:#8b949e; font-size:14px; margin-top:4px; }}
  .grade-ring {{ width:120px; height:120px; border-radius:60px; margin:24px auto;
                 border:4px solid {color}; display:flex; align-items:center;
                 justify-content:center; background:rgba({_hex_to_rgb(color)},0.06);
                 box-shadow:0 0 24px rgba({_hex_to_rgb(color)},0.15); }}
  .grade-letter {{ font-size:48px; font-weight:bold; color:{color};
                   font-family:monospace; }}
  .score-text {{ text-align:center; font-size:18px;
                 color:rgba({_hex_to_rgb(color)},0.8); margin-top:8px; }}
  .dimensions {{ display:flex; gap:12px; justify-content:center;
                 flex-wrap:wrap; margin:24px 0; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
            gap:12px; margin:24px 0; }}
  .stat-card {{ background:#141820; border:1px solid rgba(255,255,255,0.07);
                border-radius:12px; padding:16px; text-align:center; }}
  .stat-card .value {{ font-size:22px; font-weight:bold; color:#00d4ff;
                       font-family:monospace; }}
  .stat-card .label {{ font-size:12px; color:#8b949e; margin-top:4px; }}
  .severity-bar {{ display:flex; gap:12px; justify-content:center;
                   flex-wrap:wrap; margin:16px 0; }}
  .sev-badge {{ display:flex; align-items:center; gap:6px; padding:4px 12px;
                border-radius:12px; font-size:13px; font-weight:600; }}
  .sev-critical {{ background:rgba(239,83,80,0.1); color:#ef5350; }}
  .sev-warning {{ background:rgba(255,183,77,0.1); color:#ffb74d; }}
  .sev-info {{ background:rgba(102,187,106,0.1); color:#66bb6a; }}
  table {{ width:100%; border-collapse:collapse; margin:16px 0; }}
  th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #ffffff0a; }}
  th {{ color:#00d4ff; font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
  td {{ font-size:13px; }}
  .section {{ margin:32px 0; }}
  .section h2 {{ color:#00d4ff; font-size:18px; font-family:monospace;
                 border-bottom:1px solid #ffffff12; padding-bottom:8px;
                 margin-bottom:12px; }}
  .footer {{ text-align:center; color:#484f58; font-size:12px; margin-top:48px;
             padding-top:16px; border-top:1px solid #ffffff0a; }}
  @media print {{ body {{ background:white; color:#1f2328; }}
    .stat-card {{ border-color:#d0d7de; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>X-RAY</h1>
    <div class="subtitle">Code Quality Report &mdash; {timestamp}</div>
  </div>

  <div class="grade-ring">
    <span class="grade-letter">{letter}</span>
  </div>
  <div class="score-text">{score:.1f} / 100</div>

  <div class="dimensions">{dim_html}</div>

  <div class="severity-bar">
    <span class="sev-badge sev-critical">&#9679; {totals['critical']} critical</span>
    <span class="sev-badge sev-warning">&#9679; {totals['warning']} warning</span>
    <span class="sev-badge sev-info">&#9679; {totals['info']} info</span>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="value">{meta.get('files', 0)}</div>
        <div class="label">Files</div></div>
    <div class="stat-card"><div class="value">{meta.get('functions', 0)}</div>
        <div class="label">Functions</div></div>
    <div class="stat-card"><div class="value">{meta.get('classes', 0)}</div>
        <div class="label">Classes</div></div>
    <div class="stat-card"><div class="value">{meta.get('duration', 0):.1f}s</div>
        <div class="label">Duration</div></div>
  </div>

  <div class="section">
    <h2>Penalty Breakdown</h2>
    <table>
      <tr><th>Category</th><th>Penalty</th></tr>
      {breakdown_rows}
    </table>
  </div>

  <div class="footer">
    Generated by X-Ray v{__version__} &mdash; {timestamp}
  </div>
</div>
</body>
</html>"""


def _hex_to_rgb(hex_color: str) -> str:
    """Convert '#rrggbb' to 'r,g,b' string for CSS rgba()."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
    return "136,136,136"


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


# ── Dimension Rating Cards (SonarQube-style) ──────────────────────────────

# Map dimension → (abbrev, keys_contributing, weight_map)
_DIMENSION_MAP = {
    "Reliability": {
        "icon": ft.Icons.VERIFIED_USER,
        "color": "#00c853",
        "keys": ["smells", "typecheck"],
    },
    "Security": {
        "icon": ft.Icons.SHIELD,
        "color": "#ff6d00",
        "keys": ["security"],
    },
    "Maintainability": {
        "icon": ft.Icons.BUILD_CIRCLE,
        "color": "#00d4ff",
        "keys": ["lint", "format", "imports", "health"],
    },
    "Duplication": {
        "icon": ft.Icons.CONTENT_COPY,
        "color": "#7c4dff",
        "keys": ["duplicates"],
    },
}


def _dimension_letter(breakdown: dict, keys: list) -> str:
    """Derive a letter grade for a dimension from its contributing penalties."""
    total_penalty = 0.0
    for k in keys:
        v = breakdown.get(k, 0)
        if isinstance(v, dict):
            total_penalty += v.get("penalty", 0)
        elif isinstance(v, (int, float)):
            total_penalty += v
        # else ignore strings or other junk
    # Map penalty → letter (lower penalty = better grade)
    if total_penalty <= 0.5:
        return "A"
    elif total_penalty <= 3:
        return "B"
    elif total_penalty <= 8:
        return "C"
    elif total_penalty <= 15:
        return "D"
    return "F"


def build_dimension_cards(breakdown: dict) -> ft.Row:
    """Build SonarQube-style dimension rating cards."""
    cards = []
    for dim_name, dim_info in _DIMENSION_MAP.items():
        letter = _dimension_letter(breakdown, dim_info["keys"])
        color = GRADE_COLORS.get(letter, "#888")
        cards.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(dim_info["icon"], size=20, color=dim_info["color"]),
                        ft.Text(
                            letter,
                            size=SZ_H2,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                            font_family=MONO_FONT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            dim_name,
                            size=SZ_XS,
                            color=TH.dim,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=2,
                ),
                bgcolor=ft.Colors.with_opacity(0.06, color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.25, color)),
                border_radius=14,
                padding=ft.Padding.symmetric(vertical=10, horizontal=14),
                width=100,
                animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
            )
        )
    return ft.Row(cards, spacing=8, scroll=ft.ScrollMode.AUTO)


# ── Severity Summary Bar ───────────────────────────────────────────────────


def _aggregate_severities(results: dict) -> dict:
    """Aggregate critical/warning/info counts across all scan phases."""
    totals = {"critical": 0, "warning": 0, "info": 0}
    for key in ("smells", "lint", "security", "typecheck", "format",
                "imports", "ui_compat", "ui_health", "release_readiness"):
        data = results.get(key, {})
        if isinstance(data, dict) and not data.get("error"):
            for sev in totals:
                totals[sev] += data.get(sev, 0)
    return totals


def build_severity_bar(results: dict) -> ft.Container:
    """Build a horizontal bar showing total issues by severity."""
    totals = _aggregate_severities(results)
    total_all = sum(totals.values())

    badges = []
    for sev, count in totals.items():
        if count == 0 and sev != "info":
            continue
        color = SEV_COLORS.get(sev, TH.dim)
        badges.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            width=8, height=8, border_radius=4, bgcolor=color,
                        ),
                        ft.Text(
                            f"{count} {sev}",
                            size=SZ_SM,
                            color=TH.text,
                            weight=ft.FontWeight.BOLD if count > 0 else ft.FontWeight.NORMAL,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=ft.Colors.with_opacity(0.08, color),
                border_radius=12,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            )
        )
    # Add total
    badges.append(
        ft.Container(
            content=ft.Text(
                f"{total_all} total",
                size=SZ_SM,
                color=TH.muted,
            ),
            padding=ft.Padding.only(left=8),
        )
    )
    return ft.Container(
        content=ft.Row(badges, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(vertical=4),
    )


# ── Scan History Sparkline ─────────────────────────────────────────────────


def build_trend_indicator(current_score: float, prev_score: float | None) -> ft.Row:
    """Build a delta indicator showing score change vs previous scan."""
    if prev_score is None:
        return ft.Row([], spacing=0)
    delta = current_score - prev_score
    if abs(delta) < 0.1:
        icon = ft.Icon(ft.Icons.REMOVE, size=14, color=TH.muted)
        text = "No change"
        color = TH.muted
    elif delta > 0:
        icon = ft.Icon(ft.Icons.ARROW_UPWARD, size=14, color=ft.Colors.GREEN_400)
        text = f"+{delta:.1f}"
        color = ft.Colors.GREEN_400
    else:
        icon = ft.Icon(ft.Icons.ARROW_DOWNWARD, size=14, color=ft.Colors.RED_400)
        text = f"{delta:.1f}"
        color = ft.Colors.RED_400
    return ft.Row(
        [
            icon,
            ft.Text(text, size=SZ_SM, color=color, weight=ft.FontWeight.BOLD),
            ft.Text("vs last scan", size=SZ_XS, color=TH.muted),
        ],
        spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def build_sparkline(scores: list, width: int = 160, height: int = 32) -> ft.Container:
    """Build a mini sparkline chart from a list of scores (0-100)."""
    if len(scores) < 2:
        return ft.Container()
    # Normalize scores to height
    min_s = max(min(scores) - 5, 0)
    max_s = min(max(scores) + 5, 100)
    rng = max(max_s - min_s, 1)
    step_x = width / max(len(scores) - 1, 1)

    dots = []
    for i, s in enumerate(scores):
        x = i * step_x
        y = height - ((s - min_s) / rng) * height
        color = GRADE_COLORS.get(
            "A" if s >= 90 else "B" if s >= 75 else "C" if s >= 60 else "D" if s >= 40 else "F",
            "#888",
        )
        dots.append(
            ft.Container(
                width=6, height=6, border_radius=3, bgcolor=color,
                left=x - 3, top=y - 3,
            )
        )
        # Connect dots with a line segment (thin container)
        if i > 0:
            prev_x = (i - 1) * step_x
            prev_y = height - ((scores[i - 1] - min_s) / rng) * height
            dots.append(
                ft.Container(
                    width=step_x + 2, height=2,
                    bgcolor=ft.Colors.with_opacity(0.3, color),
                    left=prev_x, top=(prev_y + y) / 2 - 1,
                )
            )

    return ft.Container(
        content=ft.Stack(dots, width=width, height=height),
        width=width,
        height=height,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


# Module-level API for test compatibility
def is_dark(*args, **kwargs):
    """Wrapper for TH.is_dark()."""
    return TH.is_dark(*args, **kwargs)

def toggle(*args, **kwargs):
    """Wrapper for TH.toggle()."""
    return TH.toggle(*args, **kwargs)

