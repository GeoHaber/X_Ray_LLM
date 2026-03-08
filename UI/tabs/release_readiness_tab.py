"""UI/tabs/release_readiness_tab.py — Release Readiness dashboard tab."""

import flet as ft
from typing import Dict, Any

from UI.tabs.shared import (
    TH,
    SZ_XS,
    SZ_SM,
    SZ_BODY,
    SZ_LG,
    SZ_H2,
    MONO_FONT,
    GRADE_COLORS,
    glass_card,
    metric_tile,
    section_title,
)


def _verdict_banner(checklist, go):
    """Render the GO / NO-GO banner."""
    blockers = checklist.get("blockers", 0)
    warnings = checklist.get("warnings", 0)
    verdict_color = "#00c853" if go else "#ff1744"
    verdict_text = "GO" if go else "NO-GO"
    verdict_icon = ft.Icons.CHECK_CIRCLE if go else ft.Icons.CANCEL

    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(verdict_icon, size=36, color=verdict_color),
                ft.Column(
                    [
                        ft.Text(
                            f"Release Verdict: {verdict_text}",
                            size=SZ_H2,
                            weight=ft.FontWeight.BOLD,
                            color=verdict_color,
                        ),
                        ft.Text(
                            f"{blockers} blocker(s), {warnings} warning(s)"
                            if blockers or warnings
                            else "All checks passed",
                            size=SZ_BODY,
                            color=TH.dim,
                        ),
                    ],
                    spacing=2,
                ),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=TH.card,
        border=ft.Border.all(2, verdict_color),
        border_radius=16,
        padding=20,
    )


def _grade_and_metrics(release, grade, color, score):
    """Grade card + summary metric tiles row."""
    grade_card = ft.Container(
        content=ft.Column(
            [
                ft.Text("Readiness Score", size=SZ_BODY, color=TH.dim),
                ft.Text(grade, size=48, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(f"{score:.1f} / 100", size=SZ_LG, color=TH.text),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=TH.card,
        border=ft.Border.all(2, color),
        border_radius=20,
        padding=30,
        width=200,
        alignment=ft.Alignment(0, 0),
    )

    doc_pct = release.get("docstring_coverage_pct", 0)
    metrics_row = ft.Row(
        [
            metric_tile(ft.Icons.COMMENT, f"{doc_pct:.0f}%", "Docstrings"),
            metric_tile(ft.Icons.FLAG, str(release.get("markers", 0)), "Markers"),
            metric_tile(
                ft.Icons.BUG_REPORT, str(release.get("vulnerabilities", 0)), "CVEs"
            ),
            metric_tile(
                ft.Icons.DELETE_OUTLINE,
                str(release.get("orphan_modules", 0)),
                "Orphans",
            ),
            metric_tile(
                ft.Icons.LINK_OFF, str(release.get("unpinned_deps", 0)), "Unpinned"
            ),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
    )

    return ft.Row(
        [grade_card, ft.Column([metrics_row], expand=True, spacing=10)],
        spacing=20,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def _checklist_card(checklist):
    """Render checklist items as a glass card."""
    widgets = []
    for item in checklist.get("items", []):
        passed = item.get("passed", False)
        sev = item.get("severity", "")
        if passed:
            icon, icon_color = ft.Icons.CHECK_CIRCLE, "#00c853"
        elif sev == "blocker":
            icon, icon_color = ft.Icons.CANCEL, "#ff1744"
        elif sev == "warning":
            icon, icon_color = ft.Icons.WARNING, "#ffab00"
        else:
            icon, icon_color = ft.Icons.INFO_OUTLINE, TH.dim

        detail = item.get("detail", "")
        widgets.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=20, color=icon_color),
                        ft.Text(
                            item.get("label", ""),
                            size=SZ_BODY,
                            color=TH.text,
                            expand=True,
                        ),
                        ft.Text(detail, size=SZ_SM, color=TH.dim, italic=True)
                        if detail
                        else ft.Container(width=0),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            )
        )

    if widgets:
        return glass_card(ft.Column(widgets, spacing=2), padding=14)
    return ft.Container()


def _markers_section(release, results):
    """Marker kind chips + optional detail rows."""
    markers_by_kind = release.get("markers_by_kind", {})
    marker_detail = results.get("_release_markers_detail", [])
    controls: list = []

    if markers_by_kind:
        chips = []
        for kind, count in sorted(markers_by_kind.items()):
            chip_color = (
                "#ff1744"
                if kind == "NOCOMMIT"
                else "#ffab00"
                if kind in ("FIXME", "HACK", "XXX")
                else TH.dim
            )
            chips.append(
                ft.Container(
                    content=ft.Text(f"{kind}: {count}", size=SZ_SM, color=chip_color),
                    bgcolor=TH.chip,
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                )
            )
        controls.append(ft.Row(chips, spacing=8, wrap=True))

    if marker_detail:
        rows = []
        for m in marker_detail[:50]:
            sev_color = (
                "#ff1744"
                if m.get("severity") == "critical"
                else "#ffab00"
                if m.get("severity") == "warning"
                else TH.dim
            )
            rows.append(
                ft.Row(
                    [
                        ft.Text(
                            m.get("kind", ""), size=SZ_XS, color=sev_color, width=80
                        ),
                        ft.Text(
                            f"{m.get('file_path', '')}:{m.get('line', '')}",
                            size=SZ_XS,
                            color=TH.dim,
                            width=260,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            m.get("text", ""),
                            size=SZ_XS,
                            color=TH.text,
                            font_family=MONO_FONT,
                            expand=True,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=8,
                )
            )
        controls.append(glass_card(ft.Column(rows, spacing=2), padding=10))

    return controls


def _docstring_section(release):
    """Docstring coverage progress bar."""
    doc_pct = release.get("docstring_coverage_pct", 0)
    doc_total = release.get("docstring_total", 0)
    doc_documented = release.get("docstring_documented", 0)
    bar_color = (
        "#00c853" if doc_pct >= 60 else "#ffab00" if doc_pct >= 30 else "#ff1744"
    )
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(
                        f"{doc_documented}/{doc_total} public symbols documented",
                        size=SZ_BODY,
                        color=TH.text,
                    ),
                    ft.Text(
                        f"{doc_pct:.1f}%",
                        size=SZ_LG,
                        weight=ft.FontWeight.BOLD,
                        color=TH.text,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.ProgressBar(
                value=doc_pct / 100 if doc_total else 1.0,
                color=bar_color,
                bgcolor=TH.bar_bg,
                height=12,
                border_radius=6,
            ),
        ],
        spacing=6,
    )


def _version_section(release):
    """Version consistency chips (or empty list)."""
    versions_ok = release.get("versions_consistent", True)
    vsources = release.get("version_sources", [])
    if not vsources:
        return []
    v_icon = ft.Icons.CHECK_CIRCLE if versions_ok else ft.Icons.WARNING
    v_color = "#00c853" if versions_ok else "#ffab00"
    v_chips = [
        ft.Container(
            content=ft.Text(
                f"{vs.get('source', '?')}: {vs.get('version', '?')}",
                size=SZ_SM,
                color=TH.text,
            ),
            bgcolor=TH.chip,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        )
        for vs in vsources
    ]
    return [
        ft.Row(
            [
                ft.Icon(v_icon, size=18, color=v_color),
                ft.Text(
                    "Consistent" if versions_ok else "Mismatch detected",
                    size=SZ_BODY,
                    color=v_color,
                ),
            ],
            spacing=8,
        ),
        ft.Row(v_chips, spacing=8, wrap=True),
    ]


def _build_release_readiness_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Render the Release Readiness tab with checklist + sub-check details."""
    release = results.get("release_readiness", {})
    checklist = results.get("release_checklist", {})

    if not release:
        return ft.Container(
            content=ft.Text(
                "No release readiness data. Enable 'Release Ready' and run a scan.",
                color=TH.dim,
            ),
            padding=40,
        )

    score = release.get("score", 0)
    grade = release.get("grade", "F")
    color = GRADE_COLORS.get(grade, ft.Colors.RED_400)
    go = checklist.get("go", True) if checklist else True

    children = [
        ft.Container(height=16),
        _verdict_banner(checklist, go),
        ft.Container(height=12),
        _grade_and_metrics(release, grade, color, score),
        ft.Container(height=20),
        section_title("Release Checklist", ft.Icons.CHECKLIST),
        ft.Container(height=6),
        _checklist_card(checklist),
    ]

    markers_ctrls = _markers_section(release, results)
    if markers_ctrls:
        children.extend(
            [
                ft.Container(height=20),
                section_title("Code Markers", ft.Icons.FLAG),
                ft.Container(height=6),
                *markers_ctrls,
            ]
        )

    children.extend(
        [
            ft.Container(height=20),
            section_title("Docstring Coverage", ft.Icons.DESCRIPTION),
            ft.Container(height=6),
            _docstring_section(release),
        ]
    )

    ver_ctrls = _version_section(release)
    if ver_ctrls:
        children.extend(
            [
                ft.Container(height=20),
                section_title("Version Consistency", ft.Icons.NUMBERS),
                ft.Container(height=6),
                *ver_ctrls,
            ]
        )

    return ft.ListView(children, expand=True, spacing=6, padding=12)
