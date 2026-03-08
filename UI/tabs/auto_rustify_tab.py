import flet as ft
import asyncio
from pathlib import Path
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    SZ_H3,
    BTN_H_MD,
    BTN_RADIUS,
    TH,
    glass_card,
    metric_tile,
)
from Core.i18n import t

try:
    from Analysis.auto_rustify import RustifyPipeline, detect_system

    HAS_AUTO_RUSTIFY = True
except ImportError:
    HAS_AUTO_RUSTIFY = False
    RustifyPipeline = None  # type: ignore[assignment,misc]
    detect_system = None  # type: ignore[assignment]


def _run_rustify_pipeline(results, page, status_text, progress_bar, error_log=None):
    """Execute the auto-rustify pipeline, updating UI widgets."""
    scan_path = results.get("_scan_path", "")
    if not scan_path:
        status_text.value = t("select_dir_first")
        page.update()
        return
    if RustifyPipeline is None:
        return
    progress_bar.visible = True
    status_text.value = "Running pipeline..."
    if error_log is not None:
        error_log.value = ""
        error_log.visible = False
    page.update()
    try:

        def cb(frac, label):
            progress_bar.value = min(frac, 1.0)
            status_text.value = label
            page.update()

        output_dir = Path(scan_path) / "_rustified"
        pipeline = RustifyPipeline(
            project_dir=scan_path,
            output_dir=str(output_dir),
            crate_name="xray_rustified",
            min_score=5.0,
            max_candidates=30,
            mode="pyo3",
        )
        report = pipeline.run(progress_cb=cb)
        ok = report.compile_result and report.compile_result.success
        status_text.value = (
            "[ok] Pipeline complete -- compiled!"
            if ok
            else "[!] Pipeline finished with issues"
        )
        status_text.color = ft.Colors.GREEN_400 if ok else ft.Colors.AMBER_400
        if not ok and error_log is not None:
            stderr = ""
            if report.compile_result and hasattr(report.compile_result, "stderr"):
                stderr = report.compile_result.stderr or ""
            elif report.errors:
                stderr = "\n".join(report.errors)
            if stderr:
                error_log.value = stderr
                error_log.visible = True
    except Exception as ex:
        status_text.value = f"[x] Error: {ex}"
        status_text.color = ft.Colors.RED_400
        if error_log is not None:
            import traceback

            error_log.value = traceback.format_exc()
            error_log.visible = True
    progress_bar.visible = False
    page.update()


def _build_sys_row(sys_profile) -> ft.Row:
    """Build the system-profile metrics row (OS, arch, Rust target)."""
    return ft.Row(
        [
            metric_tile("", sys_profile.os_name, "OS"),
            metric_tile("", sys_profile.arch, "Arch"),
            metric_tile("", sys_profile.rust_target.split("-")[0], "Target"),
        ],
        spacing=8,
    )


def _build_cargo_error_log() -> ft.TextField:
    """Build the hidden Cargo error log field (shown only on compile failure)."""
    return ft.TextField(
        value="",
        multiline=True,
        read_only=True,
        visible=False,
        min_lines=6,
        max_lines=20,
        text_style=ft.TextStyle(font_family=MONO_FONT),
        text_size=SZ_SM,
        bgcolor=TH.code_bg,
        border_color=ft.Colors.RED_400,
        color=ft.Colors.RED_200,
        label="Cargo compile errors",
        expand=True,
    )


def _build_auto_rustify_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Render the Auto-Rustify pipeline tab."""
    if not HAS_AUTO_RUSTIFY:
        return ft.Text(
            "auto_rustify module not available.", color=ft.Colors.AMBER_400, size=SZ_LG
        )

    assert detect_system is not None  # guarded by HAS_AUTO_RUSTIFY above

    status_text = ft.Text("", size=SZ_MD, color=TH.dim)
    prog_bar = ft.ProgressBar(
        width=500, color=TH.accent, bgcolor=TH.card, value=0, visible=False
    )
    error_log = _build_cargo_error_log()

    async def _on_rustify_click(e):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _run_rustify_pipeline(
                results, page, status_text, prog_bar, error_log
            ),
        )

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            f" {t('tab_auto_rustify')} Pipeline",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Text(
                            "End-to-end: Scan -> Score -> Transpile -> "
                            "Compile -> Verify",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            _build_sys_row(detect_system()),
            ft.Divider(color=TH.divider, height=20),
            ft.Row(
                [
                    ft.Button(
                        f" {t('run_pipeline')}",
                        on_click=_on_rustify_click,
                        bgcolor=TH.accent2,
                        color=ft.Colors.WHITE,
                        height=BTN_H_MD,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                        ),
                    ),
                    status_text,
                ],
                spacing=12,
            ),
            prog_bar,
            error_log,
        ],
        spacing=10,
    )
