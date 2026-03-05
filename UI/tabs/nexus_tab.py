import flet as ft
from pathlib import Path
from typing import Dict, Any
from UI.tabs.shared import (
    MONO_FONT,
    SZ_BODY,
    SZ_MD,
    SZ_H3,
    BTN_H_MD,
    BTN_RADIUS,
    TH,
    glass_card,
)
from Analysis.NexusMode.orchestrator import NexusOrchestrator


def _run_nexus_pipeline(results, page, status_text, progress_bar, trans_results_col):
    """Execute the Nexus Mode orchestration pipeline."""
    scan_path = results.get("_scan_path", "")
    if not scan_path:
        status_text.value = "Select directory first"
        page.update()
        return
    progress_bar.visible = True
    status_text.value = "Starting Nexus Orchestrator..."
    status_text.color = TH.dim
    trans_results_col.controls.clear()
    page.update()

    try:

        def cb(num, total):
            progress_bar.value = num / max(1, total)
            page.update()

        orchestrator = NexusOrchestrator(Path(scan_path))

        status_text.value = "Building Graph..."
        page.update()

        transpiler_path = Path(scan_path) / "Analysis" / "transpiler.py"
        files_to_scan = (
            [transpiler_path]
            if transpiler_path.exists()
            else list(Path(scan_path).rglob("*.py"))[:10]
        )
        orchestrator.build_context_graph(files_to_scan, progress_cb=cb)

        status_text.value = f"Transpiling {len(orchestrator.graph_index.get('bottlenecks', []))} bottlenecks..."
        progress_bar.value = 0
        page.update()
        res = orchestrator.run_transpilation_pipeline("x-ray", progress_cb=cb)

        status_text.value = "Verifying Generated Rust with Cargo..."
        progress_bar.value = 0
        page.update()
        verified = orchestrator.verify_and_build(res, progress_cb=cb)

        status_text.value = f"[ok] Nexus Pipeline complete! {len(verified)}/{len(res)} passed Cargo Check."
        status_text.color = ft.Colors.GREEN_400

        for r in res:
            color = (
                ft.Colors.GREEN_400
                if r.get("status") == "success"
                else ft.Colors.RED_400
            )
            trans_results_col.controls.append(
                ft.Text(f"{r.get('function')}: {r.get('status')}", color=color)
            )

    except Exception as ex:
        status_text.value = f"[x] Error: {ex}"
        status_text.color = ft.Colors.RED_400

    progress_bar.visible = False
    page.update()


def _build_nexus_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    status_text = ft.Text("", size=SZ_MD, color=TH.dim)
    prog_bar = ft.ProgressBar(
        width=500, color=TH.accent, bgcolor=TH.card, value=0, visible=False
    )
    trans_results_col = ft.Column(scroll=ft.ScrollMode.ADAPTIVE, height=300)

    btn = ft.Button(
        " Run Nexus Mode Orchestrator",
        on_click=lambda e: _run_nexus_pipeline(
            results, page, status_text, prog_bar, trans_results_col
        ),
        bgcolor=TH.accent2,
        color=ft.Colors.WHITE,
        height=BTN_H_MD,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)),
    )

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            " Nexus Mode Orchestrator",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Text(
                            "Knowledge graph-based transpilation and autonomous verification.",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            ft.Divider(color=TH.divider, height=20),
            ft.Row([btn, status_text], spacing=12),
            prog_bar,
            ft.Container(
                content=trans_results_col,
                padding=10,
                bgcolor=TH.bg,
                border=ft.Border.all(1, TH.border),
                border_radius=8,
                expand=True,
            ),
        ],
        spacing=10,
        expand=True,
    )
