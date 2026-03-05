import math
import flet as ft
from collections import Counter
from pathlib import Path
from typing import Dict, Any
from Analysis.smart_graph import SmartGraph
from UI.tabs.shared import (
    MONO_FONT,
    SZ_BODY,
    SZ_LG,
    SZ_H3,
    BTN_H_SM,
    BTN_RADIUS,
    TH,
    glass_card,
    metric_tile,
    section_title,
    bar_chart,
)

ROOT = Path(__file__).parent.parent


def _layout_nodes_concentric(nodes: list):
    """Position nodes in concentric rings by health: critical->inner, healthy->outer."""
    groups = {"healthy": [], "warning": [], "critical": []}
    for i, node in enumerate(nodes):
        groups.get(node.get("health", "healthy"), groups["healthy"]).append(i)
    n = len(nodes)
    x, y = [0.0] * n, [0.0] * n
    for health, radius in [
        ("critical", 0.15),
        ("warning", 0.40),
        ("healthy", 0.75),
    ]:
        indices = groups.get(health, [])
        count = len(indices)
        for j, idx in enumerate(indices):
            angle = 2 * math.pi * j / max(count, 1) + (hash(health) % 100) * 0.01
            x[idx] = 0.5 + radius * 0.45 * math.cos(angle)
            y[idx] = 0.5 + radius * 0.45 * math.sin(angle)
    return x, y, groups


def _generate_graph_css(
    bg: str, legend_bg: str, border_color: str, text_color: str
) -> str:
    """Return the CSS rules for the interactive graph HTML page."""
    return f"""* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:{bg}; font-family:'Segoe UI',sans-serif; overflow:hidden; }}
#graph {{ width:100vw; height:100vh; }}
#legend {{
position:fixed; top:12px; right:12px; padding:12px 16px;
background:{legend_bg}; border:1px solid {border_color};
border-radius:10px; font-size:12px; color:{text_color};
backdrop-filter:blur(8px); z-index:10;
}}
#legend h4 {{ margin:0 0 6px; font-size:13px; opacity:0.7; }}
.dot {{ display:inline-block; width:10px; height:10px;
border-radius:50%; margin-right:6px; vertical-align:middle; }}
#controls {{
position:fixed; bottom:12px; left:12px; display:flex; gap:6px; z-index:10;
}}
#controls button {{
background:{legend_bg}; border:1px solid {border_color};
border-radius:6px; padding:6px 12px; cursor:pointer;
font-size:12px; color:{text_color};
}}
#controls button:hover {{ border-color:#00d4ff; }}
#info {{
position:fixed; top:12px; left:12px; padding:8px 12px;
background:{legend_bg}; border:1px solid {border_color};
border-radius:8px; font-size:11px; color:{text_color};
opacity:0.7; z-index:10;
}}"""


def _generate_graph_html(graph: SmartGraph) -> str:
    """Generate a self-contained HTML page with vis-network force graph."""
    import json as _json

    nodes_json = _json.dumps(graph.nodes)
    edges_json = _json.dumps(graph.edges)
    is_dark = TH.is_dark()
    bg = "#0a0e14" if is_dark else "#f6f8fa"
    text_color = "#e6edf3" if is_dark else "#1f2328"
    border_color = "rgba(255,255,255,0.12)" if is_dark else "#d0d7de"
    legend_bg = "rgba(20,24,32,0.85)" if is_dark else "rgba(255,255,255,0.9)"

    css = _generate_graph_css(bg, legend_bg, border_color, text_color)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
{css}
</style>
</head>
<body>
<div id="graph"></div>
<div id="legend">
<h4>Health</h4>
<div><span class="dot" style="background:#2ecc71"></span> Healthy</div>
<div><span class="dot" style="background:#f39c12"></span> Warning</div>
<div><span class="dot" style="background:#e74c3c"></span> Critical</div>
<div style="margin-top:6px; opacity:0.6; font-size:11px;">
Lines = duplicate pairs<br>Node size = function lines
</div>
</div>
<div id="info">Scroll to zoom · Drag to pan · Click node to focus</div>
<div id="controls">
<button onclick="network.fit()">Fit All</button>
<button onclick="network.stabilize(100)">Stabilize</button>
</div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});
var container = document.getElementById('graph');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
nodes: {{
shape:'dot', font:{{ size:12, color:'{text_color}', face:'Segoe UI' }},
borderWidth:1, borderWidthSelected:3,
shadow:{{ enabled:true, size:8, color:'rgba(0,0,0,0.3)' }},
scaling:{{ min:8, max:40, label:{{ enabled:true, min:10, max:18 }} }}
}},
edges: {{
color:{{ color:'rgba(0,212,255,0.25)', highlight:'#00d4ff', hover:'#00d4ff' }},
smooth:{{ type:'continuous' }}, width:1.5, hoverWidth:3,
selectionWidth:3
}},
physics: {{
stabilization:{{ enabled:true, iterations:200 }},
barnesHut:{{
gravitationalConstant:-15000,
centralGravity:0.4,
springLength:180,
springConstant:0.02,
damping:0.12,
avoidOverlap:0.3
}}
}},
interaction: {{
hover:true, tooltipDelay:150, zoomView:true,
dragView:true, navigationButtons:false
}},
groups: {{
healthy: {{ color:{{ background:'#2ecc71', border:'#27ae60' }} }},
warning: {{ color:{{ background:'#f39c12', border:'#e67e22' }} }},
critical: {{ color:{{ background:'#e74c3c', border:'#c0392b' }} }}
}}
}};
// Map health to group for vis-network
nodes.forEach(function(n) {{
n.group = n.health || 'healthy';
n.value = n.size || 10;
}});
nodes.update(nodes.get());
var network = new vis.Network(container, data, options);
network.once('stabilizationIterationsDone', function() {{
network.setOptions({{ physics:{{ stabilization:false }} }});
}});
</script>
</body>
</html>"""


def _build_graph_canvas(graph: SmartGraph) -> ft.Control:
    """Build an in-app Canvas preview of the codebase health graph."""
    import flet.canvas as cv

    node_x, node_y, _groups = _layout_nodes_concentric(graph.nodes)
    id_to_idx = {node["id"]: i for i, node in enumerate(graph.nodes)}

    health_colors = {
        "healthy": "#2ecc71",
        "warning": "#f39c12",
        "critical": "#e74c3c",
    }

    def _paint(canvas: cv.Canvas, event: cv.CanvasResizeEvent):
        w, h = event.width, event.height

        # Draw edges first (underneath)
        for edge in graph.edges:
            src, dst = (
                id_to_idx.get(edge.get("from")),
                id_to_idx.get(edge.get("to")),
            )
            if src is not None and dst is not None:
                canvas.shapes.append(
                    cv.Line(
                        node_x[src] * w,
                        node_y[src] * h,
                        node_x[dst] * w,
                        node_y[dst] * h,
                        paint=ft.Paint(
                            color="rgba(0,212,255,0.15)",
                            stroke_width=1,
                            style=ft.PaintingStyle.STROKE,
                        ),
                    )
                )

        # Draw nodes
        for i, node in enumerate(graph.nodes):
            color = health_colors.get(node.get("health", "healthy"), "#2ecc71")
            size = max(3, min(14, node.get("size", 10) / 5))
            cx, cy = node_x[i] * w, node_y[i] * h

            # Glow
            canvas.shapes.append(
                cv.Circle(
                    cx,
                    cy,
                    size + 3,
                    paint=ft.Paint(
                        color=f"{color}30",
                        style=ft.PaintingStyle.FILL,
                    ),
                )
            )
            # Dot
            canvas.shapes.append(
                cv.Circle(
                    cx,
                    cy,
                    size,
                    paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL),
                )
            )

            # Label for larger nodes
            if size >= 5 and len(graph.nodes) < 200:
                canvas.shapes.append(
                    cv.Text(
                        cx + size + 3,
                        cy - 5,
                        node.get("label", ""),
                        style=ft.TextStyle(size=8, color=TH.dim),
                    )
                )

        canvas.update()

    return cv.Canvas(on_resize=_paint, expand=True)


def _build_graph_metrics(graph) -> ft.Row:
    """Build the top metrics row for the graph tab."""
    healthy = sum(1 for n in graph.nodes if n.get("health") == "healthy")
    warning = sum(1 for n in graph.nodes if n.get("health") == "warning")
    critical = sum(1 for n in graph.nodes if n.get("health") == "critical")

    return ft.Row(
        [
            metric_tile(
                "[i]",
                healthy,
                "Healthy",
                ft.Colors.GREEN_400,
            ),
            metric_tile(
                "[~]",
                warning,
                "Warning",
                ft.Colors.AMBER_400,
            ),
            metric_tile(
                "[!]",
                critical,
                "Critical",
                ft.Colors.RED_400,
            ),
            metric_tile(
                "",
                len(graph.edges),
                "Dup Links",
                TH.accent,
            ),
        ],
        spacing=8,
    )


def _build_graph_group_chart(graph) -> ft.Control:
    """Build the 'per-group breakdown' bar chart for the graph tab."""
    group_counts = Counter(
        str(Path(n.get("group", ".")).name) or "root" for n in graph.nodes
    )
    top_groups = group_counts.most_common(10)
    if not top_groups:
        return ft.Container()
    return bar_chart([(g, c, TH.accent) for g, c in top_groups])


def _build_graph_header(
    on_open_graph,
) -> ft.Control:
    """Build the branded glass-card header for the graph tab."""
    return glass_card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            " Codebase Health Graph",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Container(expand=True),
                        ft.Button(
                            " Open Interactive Graph",
                            on_click=on_open_graph,
                            bgcolor=TH.accent2,
                            color=ft.Colors.WHITE,
                            height=BTN_H_SM,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                            ),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Nodes = functions (green/orange/red) \u00b7 "
                    "Edges = duplicate links \u00b7 "
                    "Size = function lines",
                    size=SZ_BODY,
                    color=TH.muted,
                ),
            ]
        )
    )


def _build_graph_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Build the codebase health graph tab with interactive HTML viewer."""
    functions = results.get("_functions", [])
    smells = results.get("_smell_issues", [])
    dup_groups = results.get("_dup_groups", [])

    if not functions:
        return ft.Text(
            "No functions available. Enable Smells or Duplicates.",
            color=TH.dim,
            size=SZ_LG,
        )

    graph = SmartGraph()
    graph.build(
        functions,
        smells,
        dup_groups or [],
        Path("."),
    )

    # Write full interactive HTML graph and capture URI for the button
    html_content = _generate_graph_html(graph)
    graph_dir = ROOT / "_scratch"
    graph_dir.mkdir(exist_ok=True)
    graph_file = graph_dir / "_graph_view.html"
    graph_file.write_text(html_content, encoding="utf-8")

    async def _open_graph(_e):
        await page.launch_url(graph_file.as_uri())

    canvas_preview = ft.Container(
        content=_build_graph_canvas(graph),
        height=400,
        expand=True,
        bgcolor=TH.code_bg,
        border=ft.Border.all(1, TH.border),
        border_radius=12,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    return ft.Column(
        [
            _build_graph_header(_open_graph),
            _build_graph_metrics(graph),
            ft.Divider(
                color=TH.divider,
                height=12,
            ),
            canvas_preview,
            ft.Divider(
                color=TH.divider,
                height=12,
            ),
            section_title("Components", ""),
            _build_graph_group_chart(graph),
        ],
        spacing=10,
        expand=True,
        scroll=ft.ScrollMode.ADAPTIVE,
    )
