import flet as ft
from UI.tabs.shared import (
    SZ_SM,
    SZ_MD,
    SEV_ICONS,
    SEV_COLORS,
    TH,
    _empty_state,
)


def _build_ui_health_tile(issue) -> ft.Container:
    """Render one UI Health issue as a severity-coloured bordered card."""
    icon_color = SEV_COLORS.get(issue.severity, TH.muted)
    icon_name = SEV_ICONS.get(issue.severity, ft.Icons.ERROR)
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(icon_name, color=icon_color, size=20),
                        ft.Text(
                            f"{issue.name} -- {issue.rule_code}",
                            color=TH.text,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Container(expand=True),
                        ft.Text(
                            f"{issue.file_path}:{issue.line}",
                            color=TH.dim,
                            size=SZ_SM,
                        ),
                    ]
                ),
                ft.Text(issue.message, color=TH.muted, size=SZ_MD),
                (
                    ft.Text(
                        f" {issue.suggestion}",
                        color=TH.accent,
                        size=SZ_SM,
                        italic=True,
                    )
                    if issue.suggestion
                    else ft.Container()
                ),
            ],
            spacing=4,
        ),
        bgcolor=TH.surface,
        border_radius=8,
        padding=12,
        border=ft.border.only(left=ft.BorderSide(4, icon_color)),
    )

    def _build_ui_health_tab(results):
        """Render the UI Health tab (Analyzer #10)."""
        health = results.get("ui_health")
        issues = results.get("_ui_health_issues", [])

        if not health or isinstance(health, dict) and health.get("error"):
            return _empty_state("", "UI Health Analysis Failed or Skipped")

            if not issues:
                return _empty_state(
                    "",
                    "No UI Health Issues Found",
                    "All tested UI components are structurally sound and well-connected.",
                )

                list_view = ft.ListView(expand=True, spacing=8, padding=16)

                # Info banner
                list_view.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.INFO_OUTLINE, color=TH.accent),
                                ft.Text(
                                    f"Found {len(issues)} structural/behavioral UI issue(s).",
                                    color=TH.text,
                                    weight=ft.FontWeight.W_500,
                                ),
                            ]
                        ),
                        bgcolor=ft.Colors.with_opacity(0.1, TH.accent),
                        border_radius=8,
                        padding=16,
                        margin=ft.margin.only(bottom=8),
                    )
                )

                for issue in issues:
                    list_view.controls.append(_build_ui_health_tile(issue))

                    return list_view
