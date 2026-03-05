import flet as ft
from collections import Counter
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    TH,
    section_title,
)
from Core.i18n import t

_HEATMAP_COLORS = ("#d50000", "#ff6d00", "#ffab00", "#00c853")
_HEATMAP_THRESHOLDS = (0.75, 0.5, 0.25)
_MAX_PATH_CHARS = 55
_BAR_MAX_WIDTH = 200


def _heatmap_color(pct: float) -> str:
    """Return a red->green color string based on the issue-density percentage."""
    for threshold, color in zip(_HEATMAP_THRESHOLDS, _HEATMAP_COLORS):
        if pct > threshold:
            return color
            return _HEATMAP_COLORS[-1]

        def _heatmap_tile(fpath: str, total: int, max_count: int) -> ft.Container:
            """Build a single file row for the heatmap list."""
            pct = total / max(max_count, 1)
            color = _heatmap_color(pct)
            display = (
                fpath
                if len(fpath) <= _MAX_PATH_CHARS
                else "..." + fpath[-(_MAX_PATH_CHARS - 3) :]
            )
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Text(
                            f" {display}",
                            size=SZ_BODY,
                            font_family=MONO_FONT,
                            color=TH.dim,
                            expand=True,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Container(
                            content=ft.Container(
                                bgcolor=color,
                                border_radius=3,
                                width=max(4, pct * _BAR_MAX_WIDTH),
                                height=12,
                            ),
                            bgcolor=TH.bar_bg,
                            border_radius=3,
                            width=_BAR_MAX_WIDTH,
                            height=12,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Text(
                            str(total),
                            size=SZ_MD,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            width=40,
                            color=color,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(vertical=6, horizontal=10),
                border=ft.Border.only(left=ft.BorderSide(3, color)),
                bgcolor=TH.card,
                border_radius=8,
                margin=ft.Margin.only(bottom=4),
            )

            def _build_heatmap_tab(results: Dict[str, Any]) -> ft.Control:
                """Render the issue-density heatmap tab (worst files first)."""
                file_issues: Counter = Counter()
                for key in ("_smell_issues", "_lint_issues", "_sec_issues"):
                    for s in results.get(key, []):
                        file_issues[s.file_path] += 1

                        if not file_issues:
                            return ft.Text(
                                f"[ok] {t('no_issues')}",
                                color=ft.Colors.GREEN_400,
                                size=SZ_LG,
                            )

                            ranked = file_issues.most_common(30)
                            mx = ranked[0][1] if ranked else 1
                            tiles = [
                                _heatmap_tile(fpath, total, mx)
                                for fpath, total in ranked
                            ]

                            return ft.Column(
                                [
                                    section_title(t("worst_files"), ""),
                                    ft.Text(
                                        f"{sum(file_issues.values())} {t('issues_across')} "
                                        f"{len(file_issues)} {t('files')}",
                                        size=SZ_BODY,
                                        color=TH.muted,
                                    ),
                                    ft.ListView(
                                        controls=tiles,
                                        expand=True,
                                        spacing=2,
                                        auto_scroll=False,
                                    ),
                                ],
                                spacing=10,
                                expand=True,
                            )
