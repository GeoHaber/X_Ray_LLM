import flet as ft
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    SZ_H3,
    SEV_ICONS,
    TH,
    glass_card,
    metric_tile,
    section_title,
    bar_chart,
    _code_snippet_container,
    _empty_result_box,
)
from Core.i18n import t


def _build_ui_compat_issue_tile(r):
    """Build one expansion tile for a UI-compat issue."""
    icon = SEV_ICONS.get("critical", "[!]")
    ctrls = [
        ft.Text(
            f"{t('issue')}: '{r.bad_kwarg}' is not valid for {r.call.resolved_name}()",
            weight=ft.FontWeight.BOLD,
            size=SZ_MD,
        ),
    ]
    if r.suggestion:
        ctrls.append(
            ft.Text(
                f"{t('fix')}: {r.suggestion}", size=SZ_BODY, color=ft.Colors.BLUE_200
            )
        )
        if r.accepted:
            top = sorted(r.accepted - {"self"})[:15]
            ctrls.append(
                ft.Text(
                    f"Accepted: {', '.join(top)}"
                    + (" …" if len(r.accepted) > 15 else ""),
                    size=SZ_SM,
                    color=TH.dim,
                    font_family=MONO_FONT,
                )
            )
            if r.call.source_snippet:
                ctrls.append(_code_snippet_container(r.call.source_snippet, limit=400))
                return ft.ExpansionTile(
                    title=ft.Text(
                        f"{icon} {r.call.resolved_name}.{r.bad_kwarg}", size=SZ_MD
                    ),
                    subtitle=ft.Text(
                        f"{r.call.file_path}:{r.call.line}", size=SZ_SM, color=TH.muted
                    ),
                    leading=ft.Icon(ft.Icons.MONITOR, color=ft.Colors.RED_400),
                    controls=[
                        ft.Container(
                            content=ft.Column(ctrls),
                            padding=12,
                            bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                            border_radius=8,
                        )
                    ],
                    expanded=False,
                )

                def _build_sorted_chart(data_dict, title, icon, color):
                    """Build a sorted bar chart section from a dict."""
                    if not data_dict:
                        return ft.Container()
                        items = sorted(data_dict.items(), key=lambda x: -x[1])
                        return ft.Column(
                            [
                                section_title(title, icon),
                                bar_chart([(k, n, color) for k, n in items[:12]]),
                            ],
                            spacing=8,
                        )

                        def _build_ui_compat_tab(results: Dict[str, Any]) -> ft.Control:
                            """Render the UI compatibility analysis tab."""
                            summary = results.get("ui_compat", {})
                            raw_issues = results.get("_ui_compat_raw", [])

                            if summary.get("error"):
                                return ft.Text(
                                    f"[!] {summary['error']}",
                                    color=ft.Colors.AMBER_400,
                                    size=SZ_LG,
                                )
                                if not raw_issues:
                                    return _empty_result_box("all UI calls compatible")

                                    metrics = ft.Row(
                                        [
                                            metric_tile(
                                                "", summary.get("total", 0), t("total")
                                            ),
                                            metric_tile(
                                                "[!]",
                                                summary.get("critical", 0),
                                                t("critical"),
                                                ft.Colors.RED_400,
                                            ),
                                            metric_tile(
                                                "",
                                                len(summary.get("by_widget", {})),
                                                "Widgets",
                                            ),
                                            metric_tile(
                                                "",
                                                len(summary.get("by_file", {})),
                                                "Files",
                                            ),
                                        ],
                                        spacing=8,
                                    )

                                    kw_chart = _build_sorted_chart(
                                        summary.get("bad_kwargs", {}),
                                        "Bad kwargs",
                                        "",
                                        "#ff6b6b",
                                    )
                                    widget_chart = _build_sorted_chart(
                                        summary.get("by_widget", {}),
                                        "By widget",
                                        "",
                                        "#ffa502",
                                    )
                                    issue_tiles = [
                                        _build_ui_compat_issue_tile(r)
                                        for r in raw_issues[:100]
                                    ]

                                    return ft.Column(
                                        [
                                            glass_card(
                                                ft.Column(
                                                    [
                                                        ft.Text(
                                                            f" {t('tab_ui_compat')}",
                                                            size=SZ_H3,
                                                            weight=ft.FontWeight.BOLD,
                                                            font_family=MONO_FONT,
                                                            color=TH.accent,
                                                        ),
                                                        ft.Text(
                                                            "Validates UI framework kwargs against live API signatures",
                                                            size=SZ_BODY,
                                                            color=TH.muted,
                                                        ),
                                                    ]
                                                )
                                            ),
                                            metrics,
                                            ft.Divider(color=TH.divider, height=20),
                                            kw_chart,
                                            widget_chart,
                                            ft.Divider(color=TH.divider, height=20),
                                            section_title(t("all_issues"), ""),
                                            ft.ListView(
                                                controls=issue_tiles,
                                                expand=True,
                                                spacing=4,
                                                auto_scroll=False,
                                            ),
                                        ],
                                        spacing=10,
                                        expand=True,
                                    )
