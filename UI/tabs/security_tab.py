import flet as ft
from typing import Dict, Any
from UI.tabs.shared import (
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    SEV_ICONS,
    SEV_COLORS,
    TH,
    metric_tile,
    section_title,
)
from Core.i18n import t


def _build_security_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("security", {})
    issues = results.get("_sec_issues", [])

    if summary.get("error"):
        return ft.Text(f"[!] {summary['error']}", color=ft.Colors.AMBER_400, size=SZ_LG)
    if not issues:
        return ft.Container(
            content=ft.Text(
                f"[ok] {t('no_issues')}", color=ft.Colors.GREEN_400, size=SZ_LG
            ),
            padding=20,
        )

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile("[!]", summary.get("critical", 0), "High", ft.Colors.RED_400),
            metric_tile(
                "[~]", summary.get("warning", 0), "Medium", ft.Colors.AMBER_400
            ),
        ],
        spacing=8,
    )

    issue_tiles = []
    for s in issues[:100]:
        sev = s.severity
        icon = SEV_ICONS.get(sev, "[?]")
        ctrls = [
            ft.Text(
                f"{t('issue')}: {s.message}",
                weight=ft.FontWeight.BOLD,
                size=SZ_MD,
            )
        ]
        if s.suggestion:
            ctrls.append(
                ft.Text(
                    f"{t('fix')}: {s.suggestion}",
                    size=SZ_BODY,
                    color=ft.Colors.BLUE_200,
                )
            )
        if getattr(s, "confidence", ""):
            ctrls.append(
                ft.Text(
                    f"Confidence: {s.confidence}",
                    size=SZ_SM,
                    color=TH.muted,
                )
            )
        issue_tiles.append(
            ft.ExpansionTile(
                title=ft.Text(
                    f"{icon} [{getattr(s, 'rule_code', '?')}] {s.message[:70]}",
                    size=SZ_MD,
                ),
                subtitle=ft.Text(
                    f"{s.file_path}:{s.line}",
                    size=SZ_SM,
                    color=TH.muted,
                ),
                leading=ft.Icon(
                    ft.Icons.SECURITY,
                    color=SEV_COLORS.get(sev, ft.Colors.GREY_400),
                ),
                controls=[
                    ft.Container(
                        content=ft.Column(ctrls),
                        padding=12,
                        bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                        border_radius=8,
                    )
                ],
            )
        )

    return ft.Column(
        [
            metrics,
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
