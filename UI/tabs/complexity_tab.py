import flet as ft
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_SM,
    SZ_MD,
    SZ_LG,
    TH,
    metric_tile,
    section_title,
    bar_chart,
    _CC_BUCKETS,
    _CC_LIMITS,
    _CC_COLORS,
    _SZ_BUCKETS,
    _SZ_LIMITS,
    _SZ_COLORS,
    _bucket_values,
)
from Core.i18n import t


def _build_fn_tile(fn, code_map):
    """Build one expansion tile for a function in the complexity tab."""
    cc_color = (
        "#d50000"
        if fn.complexity >= 15
        else "#ff6d00"
        if fn.complexity >= 8
        else "#ffd600"
    )
    code = code_map.get(f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, ""))
    return ft.ExpansionTile(
        title=ft.Text(f"CC {fn.complexity} · {fn.name}", size=SZ_MD),
        subtitle=ft.Text(
            f"{fn.file_path}:{fn.line_start} ({fn.size_lines} lines)",
            size=SZ_SM,
            color=TH.muted,
        ),
        leading=ft.Container(
            content=ft.Text(
                str(fn.complexity),
                size=SZ_LG,
                weight=ft.FontWeight.BOLD,
                color=cc_color,
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.15, cc_color),
            border_radius=8,
            width=36,
            height=36,
            alignment=ft.Alignment(0, 0),
        ),
        controls=[
            ft.Container(
                content=ft.Text(
                    code[:500] if code else "N/A",
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
        ]
        if code
        else [],
    )

    def _build_complexity_tab(results: Dict[str, Any]) -> ft.Control:
        """Render the Complexity analysis tab."""
        functions: list = results.get("_functions", [])
        if not functions:
            return ft.Text(
                "No functions available. Enable Smells or Duplicates.",
                color=TH.dim,
                size=SZ_LG,
            )

            complexities = [f.complexity for f in functions]
            sizes = [f.size_lines for f in functions]
            avg_cc = sum(complexities) / len(complexities)
            max_cc = max(complexities)
            med_cc = sorted(complexities)[len(complexities) // 2]

            metrics = ft.Row(
                [
                    metric_tile("", f"{avg_cc:.1f}", t("avg_complexity")),
                    metric_tile("", max_cc, t("max_complexity"), ft.Colors.RED_400),
                    metric_tile("", med_cc, "Median CC"),
                    metric_tile("", f"{sum(sizes) / len(sizes):.0f}", "Avg Size"),
                ],
                spacing=8,
            )

            cc_buckets = _bucket_values(complexities, _CC_BUCKETS, _CC_LIMITS)
            cc_chart = ft.Column(
                [
                    section_title(t("cc_distribution"), ""),
                    bar_chart([(k, v, _CC_COLORS[k]) for k, v in cc_buckets.items()]),
                ],
                spacing=8,
            )

            sz_buckets = _bucket_values(sizes, _SZ_BUCKETS, _SZ_LIMITS)
            sz_chart = ft.Column(
                [
                    section_title(t("size_distribution"), ""),
                    bar_chart(
                        [
                            (f"{k} lines", v, _SZ_COLORS[k])
                            for k, v in sz_buckets.items()
                        ]
                    ),
                ],
                spacing=8,
            )

            code_map = results.get("_code_map", {})
            top_fns = sorted(functions, key=lambda f: f.complexity, reverse=True)[:15]
            fn_tiles = [_build_fn_tile(fn, code_map) for fn in top_fns]

            return ft.Column(
                [
                    metrics,
                    ft.Divider(color=TH.divider, height=20),
                    cc_chart,
                    ft.Divider(color=TH.divider, height=20),
                    sz_chart,
                    ft.Divider(color=TH.divider, height=20),
                    section_title(t("most_complex"), ""),
                    ft.ListView(
                        controls=fn_tiles, expand=True, spacing=4, auto_scroll=False
                    ),
                ],
                spacing=10,
                expand=True,
            )
