import ast
import textwrap
import flet as ft
from typing import Dict, Any
from Core.types import FunctionRecord
from UI.tabs.shared import (
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_LG,
    TH,
    metric_tile,
    section_title,
    bar_chart,
    _code_panel,
)
from Core.i18n import t

try:
    from Analysis.auto_rustify import (
        py_type_to_rust as _py_type_to_rust,
        _translate_body,
    )

    _HAS_AUTO_RUSTIFY = True
except ImportError:
    _HAS_AUTO_RUSTIFY = False


def _generate_rust_sketch(func: FunctionRecord) -> str:
    """Generate a Rust sketch from a Python function record."""
    if not _HAS_AUTO_RUSTIFY:
        return f"// auto_rustify not available\nfn {func.name}() {{ todo!() }}"
    try:
        tree = ast.parse(textwrap.dedent(func.code))
        fn_node = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if fn_node is None:
            return f"// Could not parse {func.name}"
        params = []
        for arg in fn_node.args.args:
            if arg.arg == "self":
                continue
            rtype = (
                _py_type_to_rust(ast.unparse(arg.annotation))
                if arg.annotation
                else "PyObject"
            )
            params.append(f"{arg.arg}: {rtype}")
        ret = ""
        if fn_node.returns:
            ret = f" -> {_py_type_to_rust(ast.unparse(fn_node.returns))}"
        body = "\n".join(_translate_body(fn_node.body, 1))
        kw = "async " if isinstance(fn_node, ast.AsyncFunctionDef) else ""
        sig = f"{kw}fn {func.name}({', '.join(params)}){ret}"
        return f"pub {sig} {{\n{body}\n}}"
    except Exception:
        return f"// Transpiler error for {func.name}\ntodo!()"


def _build_rustify_candidate(rank, cand, code_map):
    """Build a single expansion tile for a Rust-portability candidate."""
    fn = cand.func
    purity = " Pure" if cand.is_pure else "[!] Impure"
    code = code_map.get(f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, ""))
    rust_code = _generate_rust_sketch(fn) if code else "// No source"

    ctrls = [
        ft.Row(
            [
                ft.Text(
                    f"Score: {cand.score}",
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                    size=SZ_MD,
                ),
                ft.Text(f"| {purity}", size=SZ_BODY),
                ft.Text(f"| CC={fn.complexity}", size=SZ_BODY, color=TH.dim),
                ft.Text(f"| {fn.size_lines} lines", size=SZ_BODY, color=TH.dim),
            ],
            spacing=8,
        ),
        ft.Text(f" {fn.file_path}:{fn.line_start}", size=SZ_SM, color=TH.muted),
    ]
    if cand.reason:
        ctrls.append(
            ft.Text(
                f" {cand.reason}",
                size=SZ_SM,
                italic=True,
                color=ft.Colors.AMBER_200,
            )
        )
    if code:
        ctrls.append(
            ft.Row(
                [
                    _code_panel("Python", "", code, ft.Colors.AMBER_300),
                    _code_panel("Rust", "", rust_code, ft.Colors.CYAN_200),
                ],
                spacing=12,
                expand=True,
            )
        )

    return ft.ExpansionTile(
        title=ft.Text(f"#{rank} {fn.name}", size=SZ_MD, weight=ft.FontWeight.BOLD),
        subtitle=ft.Text(
            f"Score: {cand.score} | {purity} | CC={fn.complexity}", size=SZ_SM
        ),
        leading=ft.Icon(
            ft.Icons.BOLT, color=(ft.Colors.GREEN_400 if cand.score > 20 else TH.accent)
        ),
        controls=[ft.Container(content=ft.Column(ctrls, spacing=6), padding=12)],
    )


def _build_score_distribution(candidates):
    """Build score distribution chart for Rustify tab."""
    buckets = {"0-5": 0, "5-10": 0, "10-15": 0, "15-20": 0, "20-25": 0, "25+": 0}
    bucket_colors = {
        "0-5": "#ff5722",
        "5-10": "#ff5722",
        "10-15": "#ffd600",
        "15-20": "#ffd600",
        "20-25": "#00c853",
        "25+": "#00c853",
    }
    for c in candidates:
        s = c.score
        bk = (
            "25+"
            if s >= 25
            else "20-25"
            if s >= 20
            else "15-20"
            if s >= 15
            else "10-15"
            if s >= 10
            else "5-10"
            if s >= 5
            else "0-5"
        )
        buckets[bk] += 1

    return ft.Column(
        [
            section_title("Score Distribution", ""),
            bar_chart([(k, v, bucket_colors[k]) for k, v in buckets.items()]),
        ],
        spacing=8,
    )


def _build_rustify_tab(results: Dict[str, Any]) -> ft.Control:
    """Build the Rust-portability candidate tab."""
    candidates = results.get("_rust_candidates", [])
    summary = results.get("rustify", {})
    code_map = results.get("_code_map", {})

    if not candidates:
        return ft.Text(
            "No Rustify candidates. Need functions with 5+ lines.",
            color=TH.dim,
            size=SZ_LG,
        )

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total_scored", 0), t("scored")),
            metric_tile(
                "[ok]", summary.get("pure_count", 0), t("pure"), ft.Colors.GREEN_400
            ),
            metric_tile("", summary.get("top_score", 0), t("top_score"), TH.accent),
            metric_tile(
                "[!]",
                summary.get("total_scored", 0) - summary.get("pure_count", 0),
                t("impure"),
                ft.Colors.RED_400,
            ),
        ],
        spacing=8,
    )

    cand_tiles = [
        _build_rustify_candidate(rank, cand, code_map)
        for rank, cand in enumerate(candidates[:30], 1)
    ]

    return ft.Column(
        [
            metrics,
            ft.Divider(color=TH.divider, height=20),
            section_title(f" Top Rust Candidates ({min(30, len(candidates))})", ""),
            ft.ListView(controls=cand_tiles, expand=True, spacing=4, auto_scroll=False),
            ft.Divider(color=TH.divider, height=20),
            _build_score_distribution(candidates),
        ],
        spacing=10,
        expand=True,
    )
