import flet as ft
from typing import Dict, Any
from UI.tabs.shared import (
    TH,
    metric_tile,
    section_title,
    bar_chart,
    _empty_result_box,
    _build_issue_tile,
)
from Core.i18n import t


def _build_smells_tab(results: Dict[str, Any]) -> ft.Control:
    """Render the Smells analysis tab."""
    summary = results.get("smells", {})
    issues: list = results.get("_smell_issues", [])
    code_map = results.get("_code_map", {})
    if not issues:
        return _empty_result_box()

        metrics = ft.Row(
            [
                metric_tile("", summary.get("total", 0), t("total")),
                metric_tile(
                    "[!]", summary.get("critical", 0), t("critical"), ft.Colors.RED_400
                ),
                metric_tile(
                    "[~]", summary.get("warning", 0), t("warning"), ft.Colors.AMBER_400
                ),
                metric_tile("", summary.get("info", 0), t("info"), ft.Colors.GREEN_400),
            ],
            spacing=8,
        )

        by_cat = summary.get("by_category", {})
        cat_chart = ft.Container()
        if by_cat:
            cat_data = sorted(by_cat.items(), key=lambda x: -x[1])
            cat_chart = ft.Column(
                [
                    section_title(t("by_category"), ""),
                    bar_chart([(c, n, "#ff6b6b") for c, n in cat_data[:12]]),
                ],
                spacing=8,
            )

            sorted_issues = sorted(
                issues,
                key=lambda x: (
                    0
                    if x.severity == "critical"
                    else 1
                    if x.severity == "warning"
                    else 2
                ),
            )[:80]
            issue_tiles = [_build_issue_tile(s, code_map) for s in sorted_issues]

            return ft.Column(
                [
                    metrics,
                    ft.Divider(color=TH.divider, height=30),
                    cat_chart,
                    ft.Divider(color=TH.divider, height=20),
                    section_title(t("all_issues"), ""),
                    ft.ListView(
                        controls=issue_tiles,
                        expand=True,
                        spacing=4,
                        padding=5,
                        auto_scroll=False,
                    ),
                ],
                spacing=10,
                expand=True,
            )
