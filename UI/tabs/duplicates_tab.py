import flet as ft
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    TH,
    metric_tile,
    _empty_result_box,
)
from Core.i18n import t


def _build_dup_group_tile(g, code_map):
    """Build one expansion tile for a duplicate group."""
    sim_pct = f"{g.avg_similarity:.0%}"
    func_names = ", ".join(f.get("name", "?") for f in g.functions[:3])
    controls = []
    if g.merge_suggestion:
        controls.append(
            ft.Container(
                content=ft.Text(f" {g.merge_suggestion}", size=SZ_BODY, italic=True),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_200),
                padding=10,
                border_radius=6,
            )
        )
        for f in g.functions:
            loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
            code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
            controls.append(
                ft.Column(
                    [
                        ft.Text(
                            f" {loc} - {f.get('name', '?')} ({f.get('size', '?')} lines)",
                            size=SZ_BODY,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Container(
                            content=ft.Text(
                                code[:400] if code else "N/A",
                                font_family=MONO_FONT,
                                size=SZ_SM,
                                selectable=True,
                                color=TH.dim,
                                no_wrap=False,
                            ),
                            bgcolor=TH.code_bg,
                            border_radius=8,
                            padding=10,
                        )
                        if code
                        else ft.Container(),
                    ],
                    spacing=4,
                )
            )
            return ft.ExpansionTile(
                title=ft.Text(
                    f"Group {g.group_id} - {g.similarity_type} ({sim_pct})", size=SZ_MD
                ),
                subtitle=ft.Text(func_names, size=SZ_SM, color=TH.muted),
                controls=[
                    ft.Container(content=ft.Column(controls, spacing=8), padding=12)
                ],
            )

            def _build_duplicates_tab(results: Dict[str, Any]) -> ft.Control:
                """Render the Duplicates analysis tab."""
                summary = results.get("duplicates", {})
                groups = results.get("_dup_groups", [])
                code_map = results.get("_code_map", {})

                if not groups:
                    return _empty_result_box()

                    metrics = ft.Row(
                        [
                            metric_tile(
                                "", summary.get("total_groups", 0), t("groups")
                            ),
                            metric_tile(
                                "", summary.get("exact_duplicates", 0), t("exact")
                            ),
                            metric_tile(
                                "", summary.get("near_duplicates", 0), t("near")
                            ),
                            metric_tile(
                                "", summary.get("semantic_duplicates", 0), t("semantic")
                            ),
                        ],
                        spacing=8,
                    )
                    group_tiles = [
                        _build_dup_group_tile(g, code_map) for g in groups[:50]
                    ]

                    return ft.Column(
                        [
                            metrics,
                            metric_tile(
                                "-",
                                summary.get("total_functions_involved", 0),
                                t("involved"),
                            ),
                            ft.Divider(color=TH.divider, height=20),
                            ft.ListView(
                                controls=group_tiles,
                                expand=True,
                                spacing=4,
                                auto_scroll=False,
                            ),
                        ],
                        spacing=10,
                        expand=True,
                    )
