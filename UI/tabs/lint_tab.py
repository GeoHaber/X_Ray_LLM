import flet as ft
from typing import Dict, Any
import subprocess
from UI.tabs.shared import (
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    BTN_H_MD,
    BTN_RADIUS,
    SEV_ICONS,
    TH,
    metric_tile,
    section_title,
    bar_chart,
    _empty_result_box,
)
from Core.i18n import t


def _build_lint_fix_bar(results, summary, page):
    """Build the auto-fix button + result text for lint tab."""
    fix_result = ft.Text("", size=SZ_BODY)

    def on_auto_fix(_e):
        scan_path = results.get("_scan_path", "")
        if not scan_path:
            fix_result.value = "No scan path available"
            page.update()
            return
        try:
            r = subprocess.run(
                ["ruff", "check", "--fix", scan_path],  # nosec B607
                capture_output=True,
                text=True,
                timeout=60,
            )
            fix_result.value = f"[ok] Auto-fix done! {r.stdout.strip()}"
            fix_result.color = ft.Colors.GREEN_400
        except FileNotFoundError:
            fix_result.value = "[x] Ruff not found"
            fix_result.color = ft.Colors.RED_400
        except subprocess.TimeoutExpired:
            fix_result.value = "[x] Timed out"
            fix_result.color = ft.Colors.RED_400
        page.update()

    if summary.get("fixable", 0) > 0:
        return ft.Row(
            [
                ft.Button(
                    f" {t('auto_fix')} ({summary['fixable']})",
                    on_click=on_auto_fix,
                    bgcolor=TH.accent2,
                    color=ft.Colors.WHITE,
                    height=BTN_H_MD,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                    ),
                ),
                fix_result,
            ],
            spacing=12,
        )
    return ft.Container()


def _build_lint_issue_tile(s):
    """Build a single expansion tile for a lint issue."""
    icon = SEV_ICONS.get(s.severity, "[?]")
    fix_tag = " " if getattr(s, "fixable", False) else ""
    return ft.ExpansionTile(
        title=ft.Text(
            f"{icon} [{getattr(s, 'rule_code', 'LINT')}] {s.message[:80]}{fix_tag}",
            size=SZ_MD,
        ),
        subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM, color=TH.muted),
        controls=[
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            f"{t('issue')}: {s.message}",
                            weight=ft.FontWeight.BOLD,
                            size=SZ_MD,
                        ),
                        ft.Text(
                            f"{t('fix')}: {s.suggestion}",
                            size=SZ_BODY,
                            color=ft.Colors.BLUE_200,
                        )
                        if s.suggestion
                        else ft.Container(),
                    ]
                ),
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8,
            )
        ],
    )


def _build_lint_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Render the Lint analysis tab."""
    summary = results.get("lint", {})
    issues = results.get("_lint_issues", [])

    if summary.get("error"):
        return ft.Text(
            f"[!] {summary['error']}",
            color=ft.Colors.AMBER_400,
            size=SZ_LG,
        )
    if not issues:
        return _empty_result_box()

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile(
                "[!]",
                summary.get("critical", 0),
                t("critical"),
                ft.Colors.RED_400,
            ),
            metric_tile(
                "[~]",
                summary.get("warning", 0),
                t("warning"),
                ft.Colors.AMBER_400,
            ),
            metric_tile(
                "",
                summary.get("fixable", 0),
                t("auto_fixable"),
                TH.accent2,
            ),
        ],
        spacing=8,
    )

    fix_btn = _build_lint_fix_bar(results, summary, page)

    by_rule = summary.get("by_rule", {})
    rule_chart = ft.Container()
    if by_rule:
        top_rules = sorted(by_rule.items(), key=lambda x: -x[1])[:10]
        rule_chart = ft.Column(
            [
                section_title("Top Rules", ""),
                bar_chart([(r, c, "#ff9800") for r, c in top_rules]),
            ],
            spacing=8,
        )

    issue_tiles = [_build_lint_issue_tile(s) for s in issues[:100]]

    return ft.Column(
        [
            metrics,
            fix_btn,
            ft.Divider(color=TH.divider, height=20),
            rule_chart,
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
