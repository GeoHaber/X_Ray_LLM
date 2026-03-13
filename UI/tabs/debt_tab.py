"""
UI/tabs/debt_tab.py — Debt Center Tab (v8.0)
============================================

Renders the consolidated "Debt Center" view combining:
  - Self-Admitted Technical Debt (SATD) items & hours estimate
  - Git Hotspot ranked file list (🔥 churn × complexity)
  - Temporal coupling pairs (files that change together)
  - AI-Generated Code Detector findings
"""

import flet as ft
from typing import Any, Dict, List
from UI.tabs.shared import (
    TH,
    metric_tile,
    section_title,
    bar_chart,
    _empty_result_box,
    glass_card,
    SZ_XS,
    SZ_SM,
)


# ── Colour constants ──────────────────────────────────────────────────────────

_FLAME = "#ff6b35"
_DEBT_BLUE = "#00d4ff"
_COUPLE_PURP = "#a855f7"
_AI_TEAL = "#10b981"
_WARN_AMBER = "#f59e0b"
_CRIT_RED = "#ef4444"
_MUTED = "#6b7280"


def _chip(label: str, color: str = "#374151") -> ft.Container:
    return ft.Container(
        content=ft.Text(label, size=SZ_XS, color=ft.Colors.WHITE),
        bgcolor=color,
        border_radius=4,
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
    )


def _badge_text(badge: str) -> ft.Text:
    return ft.Text(badge, size=14, no_wrap=True)


def _row_divider() -> ft.Divider:
    return ft.Divider(color=TH.divider, height=1, thickness=1)


# ── SATD Section ──────────────────────────────────────────────────────────────


def _build_satd_section(satd: Dict[str, Any]) -> ft.Control:
    """Render SATD summary + item list."""
    if not satd:
        return ft.Container()

    total = satd.get("total", 0)
    total_hours = satd.get("total_hours", 0)
    by_cat = satd.get("by_category", {})
    items = satd.get("items", [])
    top_files = satd.get("top_files", [])

    cat_color = {
        "defect": _CRIT_RED,
        "design": _DEBT_BLUE,
        "debt": _WARN_AMBER,
        "test": _AI_TEAL,
        "documentation": _MUTED,
    }

    # Metrics row
    metrics = ft.Row(
        [
            metric_tile("📝", total, "SATD items", _DEBT_BLUE),
            metric_tile("⏱️", f"{total_hours:.0f}h", "Est. Debt Hours", _WARN_AMBER),
            metric_tile("🔴", by_cat.get("defect", 0), "Defects", _CRIT_RED),
            metric_tile("🔵", by_cat.get("design", 0), "Design", _DEBT_BLUE),
            metric_tile("🟡", by_cat.get("debt", 0), "Tech Debt", _WARN_AMBER),
        ],
        spacing=8,
        wrap=True,
    )

    # Category bar chart
    cat_data = [
        (cat, count, cat_color.get(cat, "#6b7280"))
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1])
    ]
    cat_bar = bar_chart(cat_data) if cat_data else ft.Container()

    # Top files
    file_tiles = []
    for f in top_files[:8]:
        fname = f.get("file", "?")
        count = f.get("count", 0)
        hours = f.get("hours", 0)
        file_tiles.append(
            ft.ListTile(
                leading=ft.Text("📄", size=16),
                title=ft.Text(fname, size=SZ_SM, overflow=ft.TextOverflow.ELLIPSIS),
                trailing=ft.Row(
                    [
                        _chip(f"{count} items", _DEBT_BLUE),
                        _chip(f"{hours:.0f}h", _WARN_AMBER),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )
        )

    # SATD item list (first 30)
    item_tiles = []
    for item in items[:30]:
        cat = item.get("category", "?")
        text = item.get("text", "")
        fpath = item.get("file", "?")
        lno = item.get("line", 0)
        hrs = item.get("hours", 0)
        color = cat_color.get(cat, _MUTED)
        item_tiles.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                _chip(item.get("marker", cat).upper(), color),
                                ft.Text(
                                    f"{fpath}:{lno}",
                                    size=SZ_XS,
                                    color=TH.dim,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                                ft.Text(f"{hrs:.1f}h", size=SZ_XS, color=_WARN_AMBER),
                            ],
                            spacing=6,
                        ),
                        ft.Text(
                            text,
                            size=SZ_XS,
                            color=TH.muted,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=2,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border=ft.border.only(bottom=ft.BorderSide(1, TH.divider)),
            )
        )

    return ft.Column(
        [
            section_title("📝 Self-Admitted Technical Debt", ""),
            metrics,
            ft.Divider(color=TH.divider, height=20),
            section_title("By Category", ""),
            cat_bar,
            ft.Divider(color=TH.divider, height=20),
            section_title("Top Debt Files", ""),
            ft.Column(file_tiles, spacing=0) if file_tiles else ft.Container(),
            ft.Divider(color=TH.divider, height=20),
            section_title("SATD Items", ""),
            ft.Column(item_tiles, spacing=0, scroll=ft.ScrollMode.AUTO)
            if item_tiles
            else ft.Container(),
        ],
        spacing=10,
    )


# ── Hotspot Section ───────────────────────────────────────────────────────────


def _build_hotspot_section(hotspots: Dict[str, Any]) -> ft.Control:
    """Render git hotspot ranked file list."""
    if not hotspots:
        return ft.Container()

    top = hotspots.get("top_hotspots", [])
    if not top:
        return ft.Container(
            content=ft.Text(
                "No git history found or no hotspots detected.",
                color=TH.dim,
                size=SZ_SM,
            ),
            padding=20,
        )

    tiles = []
    for i, h in enumerate(top[:15]):
        badge = h.get("badge", "📄")
        path = h.get("path", "?")
        churn = h.get("churn", 0)
        cx = h.get("complexity", 0)
        pri = h.get("priority", 0)
        tiles.append(
            ft.ListTile(
                leading=ft.Text(badge, size=18),
                title=ft.Text(path, size=SZ_SM, overflow=ft.TextOverflow.ELLIPSIS),
                subtitle=ft.Text(f"complexity: {cx:.1f}", size=SZ_XS, color=TH.dim),
                trailing=ft.Row(
                    [
                        _chip(f"churn {churn}", _FLAME),
                        _chip(f"pri {pri:.0f}", "#7c3aed"),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )
        )

    total_commits = hotspots.get("total_commits", 0)
    days = hotspots.get("analysis_days", 90)

    return ft.Column(
        [
            section_title("🔥 Git Hotspots", ""),
            ft.Text(
                f"Based on {total_commits} commits in last {days} days",
                size=SZ_XS,
                color=TH.dim,
            ),
            ft.Divider(color=TH.divider, height=12),
            ft.Column(tiles, spacing=0),
        ],
        spacing=8,
    )


# ── Temporal Coupling Section ─────────────────────────────────────────────────


def _build_coupling_section(coupling: Dict[str, Any]) -> ft.Control:
    """Render temporal coupling pairs table."""
    if not coupling:
        return ft.Container()

    top_pairs = coupling.get("top_pairs", [])
    if not top_pairs:
        return ft.Container(
            content=ft.Text(
                "No significant temporal coupling detected.", color=TH.dim, size=SZ_SM
            ),
            padding=20,
        )

    rows = [
        ft.Row(
            [
                ft.Text("Strength", size=SZ_XS, color=TH.dim, width=60),
                ft.Text("File A", size=SZ_XS, color=TH.dim, expand=2),
                ft.Text("File B", size=SZ_XS, color=TH.dim, expand=2),
                ft.Text("Coupling%", size=SZ_XS, color=TH.dim, width=70),
                ft.Text("Co-changes", size=SZ_XS, color=TH.dim, width=80),
            ],
            spacing=8,
        ),
        ft.Divider(color=TH.divider, height=1),
    ]

    for p in top_pairs[:15]:
        badge = p.get("badge", "🟢")
        fa = p.get("file_a", "?")
        fb = p.get("file_b", "?")
        pct = p.get("coupling_pct", 0)
        cnt = p.get("cochange_count", 0)
        rows.append(
            ft.Row(
                [
                    ft.Text(badge, size=14, width=60),
                    ft.Text(
                        fa, size=SZ_XS, overflow=ft.TextOverflow.ELLIPSIS, expand=2
                    ),
                    ft.Text(
                        fb, size=SZ_XS, overflow=ft.TextOverflow.ELLIPSIS, expand=2
                    ),
                    ft.Text(f"{pct:.0f}%", size=SZ_SM, color=_COUPLE_PURP, width=70),
                    ft.Text(str(cnt), size=SZ_SM, width=80),
                ],
                spacing=8,
            )
        )
        rows.append(ft.Divider(color=TH.divider, height=1))

    total_pairs = coupling.get("total_pairs", 0)
    strong_pairs = coupling.get("strong_pairs", 0)
    days = coupling.get("analysis_days", 180)

    return ft.Column(
        [
            section_title("🔗 Temporal Coupling", ""),
            ft.Row(
                [
                    metric_tile("🔴", strong_pairs, "Strong couples", _CRIT_RED),
                    metric_tile("🔗", total_pairs, "Total pairs", _COUPLE_PURP),
                ],
                spacing=8,
            ),
            ft.Text(f"Based on last {days} days of commits", size=SZ_XS, color=TH.dim),
            ft.Divider(color=TH.divider, height=12),
            ft.Column(rows, spacing=2),
        ],
        spacing=8,
    )


# ── AI Debt Section ───────────────────────────────────────────────────────────


def _build_ai_debt_section(ai_data: Dict[str, Any]) -> ft.Control:
    """Render AI-Generated Code Detector results."""
    if not ai_data:
        return ft.Container()

    total = ai_data.get("total_findings", 0)
    score = ai_data.get("ai_debt_score", 0)
    by_pattern = ai_data.get("by_pattern", {})
    items = ai_data.get("items", [])

    pattern_labels = {
        "over_documented": "Over-documented",
        "gpt_naming": "GPT Naming",
        "wrapper_function": "Wrapper Fns",
        "blanket_except": "Blanket Except",
        "high_comment_ratio": "Comment Ratio",
    }

    pat_tiles = [
        ft.Row(
            [
                ft.Text(pattern_labels.get(k, k), size=SZ_SM, expand=True),
                _chip(str(v), _AI_TEAL),
            ],
            spacing=8,
        )
        for k, v in sorted(by_pattern.items(), key=lambda x: -x[1])
    ]

    item_tiles = []
    for item in items[:20]:
        sev = item.get("severity", "info")
        patt = pattern_labels.get(item.get("pattern", ""), item.get("pattern", ""))
        desc = item.get("description", "")
        fpath = item.get("file", "?")
        lno = item.get("line", 0)
        col = _CRIT_RED if sev == "warning" else _AI_TEAL
        item_tiles.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                _chip(patt, col),
                                ft.Text(
                                    f"{fpath}:{lno}",
                                    size=SZ_XS,
                                    color=TH.dim,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Text(
                            desc,
                            size=SZ_XS,
                            color=TH.muted,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=2,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border=ft.border.only(bottom=ft.BorderSide(1, TH.divider)),
            )
        )

    return ft.Column(
        [
            section_title("🤖 AI-Generated Code Detector", ""),
            ft.Row(
                [
                    metric_tile("🤖", total, "AI Findings", _AI_TEAL),
                    metric_tile("📊", f"{score:.0f}", "AI Debt Score", _WARN_AMBER),
                ],
                spacing=8,
            ),
            ft.Divider(color=TH.divider, height=12),
            ft.Column(pat_tiles, spacing=6),
            ft.Divider(color=TH.divider, height=12),
            section_title("Findings", ""),
            ft.Column(item_tiles, spacing=0)
            if item_tiles
            else ft.Text("No AI patterns detected.", color=TH.dim, size=SZ_SM),
        ],
        spacing=8,
    )


# ── Main entry point ──────────────────────────────────────────────────────────


def _build_debt_tab(results: Dict[str, Any]) -> ft.Control:
    """
    Render the full Debt Center tab.

    Expected keys in results:
      - _satd:     SATDSummary.as_dict()
      - _hotspots: HotspotReport.as_dict()
      - _coupling: TemporalCouplingReport.as_dict()
      - _ai_debt:  AICodeReport.as_dict()
    """
    satd = results.get("_satd", {})
    hotspots = results.get("_hotspots", {})
    coupling = results.get("_coupling", {})
    ai_debt = results.get("_ai_debt", {})

    if not any([satd, hotspots, coupling, ai_debt]):
        return _empty_result_box()

    sections: List[ft.Control] = []

    if satd:
        sections.append(glass_card(_build_satd_section(satd)))
        sections.append(ft.Divider(color=TH.divider, height=30))

    if hotspots:
        sections.append(glass_card(_build_hotspot_section(hotspots)))
        sections.append(ft.Divider(color=TH.divider, height=30))

    if coupling:
        sections.append(glass_card(_build_coupling_section(coupling)))
        sections.append(ft.Divider(color=TH.divider, height=30))

    if ai_debt:
        sections.append(glass_card(_build_ai_debt_section(ai_debt)))

    return ft.Column(
        sections,
        spacing=0,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
