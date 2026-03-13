import math
import flet as ft
from collections import Counter
from pathlib import Path
from typing import Dict, Any
from Analysis.smart_graph import SmartGraph
from Analysis.design_oracle import _default_oracle
from UI.tabs.shared import (
    MONO_FONT,
    SZ_SM,
    SZ_BODY,
    SZ_LG,
    SZ_H3,
    SZ_XS,
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


def _generate_graph_html(graph_complete: SmartGraph, graph_calls: SmartGraph, graph_hier: SmartGraph) -> str:
    """Generate a self-contained premium HTML page with vis-network."""
    import json as _json

    data_json = _json.dumps({
        "complete": {"nodes": graph_complete.nodes, "edges": graph_complete.edges},
        "calls": {"nodes": graph_calls.nodes, "edges": graph_calls.edges},
        "hierarchy": {"nodes": graph_hier.nodes, "edges": graph_hier.edges}
    })

    template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>X-RAY Code Graph Explorer</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        body {
            margin: 0; padding: 0;
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: 'Outfit', sans-serif;
            overflow: hidden;
            display: flex;
            height: 100vh;
        }
        #header {
            position: absolute;
            top: 15px; left: 15px; right: 15px;
            height: 60px;
            background: rgba(22, 27, 34, 0.75);
            backdrop-filter: blur(12px);
            border-radius: 12px;
            border: 1px solid #30363d;
            display: flex;
            align-items: center;
            padding: 0 25px;
            z-index: 100;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        }
        h2 { margin: 0; font-size: 22px; color: #58a6ff; font-weight: 600; letter-spacing: -0.5px; }
        .search-box {
            margin-left: 30px;
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid #30363d;
            background: #0d1117;
            color: #c9d1d9;
            font-family: inherit;
            font-size: 14px;
            width: 300px;
            outline: none;
            transition: all 0.2s;
        }
        .search-box:focus { border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88,166,255,0.25); }
        .controls {
            margin-left: auto;
            display: flex;
            gap: 15px;
        }
        select, button {
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid #30363d;
            background: #161b22;
            color: #c9d1d9;
            font-family: inherit;
            font-size: 14px;
            font-weight: 500;
            outline: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        select:hover, button:hover { border-color: #8b949e; background: #1c2128; }
        #mynetwork { flex: 1; height: 100%; outline: none; }
        
        #sidebar {
            width: 400px;
            background: rgba(22, 27, 34, 0.9);
            backdrop-filter: blur(16px);
            border-left: 1px solid #30363d;
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
            position: absolute;
            right: 0; top: 0; bottom: 0;
            z-index: 90;
            box-shadow: -8px 0 24px rgba(0,0,0,0.6);
            padding: 25px;
            padding-top: 90px;
            overflow-y: auto;
        }
        #sidebar.open { transform: translateX(0); }
        .node-title { font-size: 24px; font-weight: 600; color: #ffffff; margin-bottom: 8px; word-break: break-all; line-height: 1.2; }
        .node-meta { font-size: 14px; color: #8b949e; margin-bottom: 20px; }
        .badge {
            display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-right: 8px; border: 1px solid;
        }
        .badge-healthy { color: #52c41a; border-color: rgba(82,196,26,0.3); background: rgba(82,196,26,0.1); }
        .badge-warning { color: #faad14; border-color: rgba(250,173,20,0.3); background: rgba(250,173,20,0.1); }
        .badge-critical { color: #ff4d4f; border-color: rgba(255,77,79,0.3); background: rgba(255,77,79,0.1); }
        
        .section-title { font-size: 12px; font-weight: 600; color: #58a6ff; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
        .node-code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px; line-height: 1.5;
            background: #0d1117;
            padding: 16px;
            border-radius: 8px;
            border: 1px solid #30363d;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
            color: #e6edf3;
            margin-bottom: 20px;
        }
        .issue-card {
            background: rgba(48, 54, 61, 0.5);
            border-left: 4px solid;
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 6px;
            border-top: 1px solid #30363d;
            border-right: 1px solid #30363d;
            border-bottom: 1px solid #30363d;
        }
        .issue-CRITICAL { border-left-color: #ff4d4f; }
        .issue-WARNING { border-left-color: #faad14; }
        .issue-INFO { border-left-color: #52c41a; }
        .issue-msg { font-size: 14px; color: #c9d1d9; margin-top: 6px; line-height: 1.4; }
        .close-btn { position: absolute; left: 25px; top: 90px; cursor: pointer; color: #8b949e; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: rgba(255,255,255,0.05); transition: background 0.2s; }
        .close-btn:hover { color: #ffffff; background: rgba(255,255,255,0.15); }
    </style>
</head>
<body>
    <div id="header">
        <h2>X-RAY Explorer</h2>
        <input type="text" class="search-box" id="searchInput" placeholder="Search functions or files...">
        <div class="controls">
            <select id="modeSelect">
                <option value="complete">Complete Code Graph</option>
                <option value="calls">Function Calls</option>
                <option value="hierarchy">Project Hierarchy</option>
            </select>
            <select id="layoutSelect">
                <option value="force">Force Directed</option>
                <option value="hierarchical">Tree Layout</option>
            </select>
            <button onclick="network.fit()">Fit Screen</button>
        </div>
    </div>
    
    <div id="mynetwork"></div>
    
    <div id="sidebar">
        <div class="close-btn" id="closeSidebar">✕</div>
        <div id="sb-content" style="margin-top: 40px;">
            <div class="node-title" id="sb-title">Node Selected</div>
            <div id="sb-badges" style="margin-bottom: 10px;"></div>
            <div class="node-meta" id="sb-meta">Select a node to view details</div>
            <div id="sb-details" style="display:none;">
                <div class="section-title">Signature</div>
                <div class="node-code" id="sb-sig"></div>
                <div class="section-title">Source Code</div>
                <div class="node-code" id="sb-code"></div>
                <div class="section-title" id="sb-issues-title" style="color: #ff4d4f; margin-top: 25px;">Detected Issues</div>
                <div id="sb-issues"></div>
            </div>
        </div>
    </div>

    <script type="text/javascript">
        var allDatasets = DATA_JSON_PLACEHOLDER;
        
        var nodes = new vis.DataSet(allDatasets.complete.nodes);
        var edges = new vis.DataSet(allDatasets.complete.edges);
        
        var container = document.getElementById('mynetwork');
        var data = { nodes: nodes, edges: edges };
        var baseOptions = {
            nodes: {
                font: { size: 14, color: '#c9d1d9', face: 'Outfit' },
                borderWidth: 2,
                color: { border: '#30363d', background: '#161b22', highlight: { border: '#58a6ff', background: '#1f2428' } }
            },
            edges: {
                color: { color: '#8b949e', opacity: 0.5, highlight: '#58a6ff' },
                smooth: { type: 'continuous' }
            },
            interaction: { hover: true, tooltipDelay: 200 },
        };
        
        var forcePhysics = {
            stabilization: false,
            barnesHut: { gravitationalConstant: -30000, springConstant: 0.005, springLength: 150 }
        };
        var hierarchicalOptions = { enabled: true, sortMethod: 'directed', nodeSpacing: 150, treeSpacing: 250, direction: 'DU' };
        
        var network = new vis.Network(container, data, {...baseOptions, physics: forcePhysics});
        
        // Mode Toggle
        document.getElementById('modeSelect').addEventListener('change', function(e) {
            var mode = e.target.value;
            nodes.clear();
            edges.clear();
            nodes.add(allDatasets[mode].nodes);
            edges.add(allDatasets[mode].edges);
            if (mode === 'hierarchy' && document.getElementById('layoutSelect').value !== 'hierarchical') {
                document.getElementById('layoutSelect').value = 'hierarchical';
                network.setOptions({ layout: { hierarchical: hierarchicalOptions }, physics: false });
            } else if (mode === 'complete' && document.getElementById('layoutSelect').value === 'hierarchical') {
                document.getElementById('layoutSelect').value = 'force';
                network.setOptions({ layout: { hierarchical: false }, physics: forcePhysics });
            }
            document.getElementById('searchInput').value = '';
            sidebar.classList.remove('open');
        });

        // Setup Search
        document.getElementById('searchInput').addEventListener('input', function(e) {
            var term = e.target.value.toLowerCase();
            if (!term) {
                nodes.forEach(n => nodes.update({id: n.id, hidden: false}));
                edges.forEach(e => edges.update({id: e.id, hidden: false}));
                return;
            }
            var matched = new Set();
            nodes.forEach(n => {
                var match = (n.label && n.label.toLowerCase().includes(term)) || (n.file && n.file.toLowerCase().includes(term));
                if (match) matched.add(n.id);
            });
            nodes.forEach(n => nodes.update({id: n.id, hidden: !matched.has(n.id)}));
            edges.forEach(e => edges.update({id: e.id, hidden: !matched.has(e.from) || !matched.has(e.to)}));
        });
        
        // Layout Toggle
        document.getElementById('layoutSelect').addEventListener('change', function(e) {
            if (e.target.value === 'hierarchical') {
                network.setOptions({ layout: { hierarchical: hierarchicalOptions }, physics: false });
            } else {
                network.setOptions({ layout: { hierarchical: false }, physics: forcePhysics });
            }
        });
        
        // Sidebar logic
        var sidebar = document.getElementById('sidebar');
        document.getElementById('closeSidebar').onclick = () => sidebar.classList.remove('open');
        
        network.on("selectNode", function (params) {
            var nodeId = params.nodes[0];
            var node = nodes.get(nodeId);
            if (!node || node.id === 'root' || node.id.startsWith('path:')) return;
            
            sidebar.classList.add('open');
            document.getElementById('sb-title').textContent = node.label;
            
            var badges = document.getElementById('sb-badges');
            badges.innerHTML = '';
            if (node.health) {
                badges.innerHTML += `<span class="badge badge-${node.health}">${node.health.toUpperCase()}</span>`;
            }
            if (node.complexity) {
                badges.innerHTML += `<span class="badge" style="color:#8b949e; border-color:#30363d; background:transparent;">Cx: ${node.complexity}</span>`;
            }

            var metaText = node.file ? `${node.file} | Line ${node.line}` : 'No file info';
            document.getElementById('sb-meta').textContent = metaText;
            document.getElementById('sb-details').style.display = 'block';
            document.getElementById('sb-sig').textContent = node.signature || node.label;
            document.getElementById('sb-code').textContent = node.code || '// Source unavailable';
            
            var issuesDiv = document.getElementById('sb-issues');
            issuesDiv.innerHTML = '';
            var issuesTitle = document.getElementById('sb-issues-title');
            if (node.issues && node.issues.length > 0) {
                issuesTitle.style.display = 'block';
                node.issues.forEach(iss => {
                    var d = document.createElement('div');
                    d.className = `issue-card issue-${iss.severity}`;
                    d.innerHTML = `<strong style="color:#c9d1d9;font-size:12px;letter-spacing:0.5px;">${iss.severity}</strong><div class="issue-msg">${iss.category}: ${iss.message}</div>`;
                    issuesDiv.appendChild(d);
                });
            } else {
                issuesTitle.style.display = 'none';
            }
        });
        network.on("deselectNode", function () {
            sidebar.classList.remove('open');
        });
    </script>
</body>
</html>"""
    return template.replace("DATA_JSON_PLACEHOLDER", data_json)


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

    def _paint(event: cv.CanvasResizeEvent):
        canvas = event.control
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
    on_open_graph, mode_selector: ft.Control, layout_selector: ft.Control, on_run_oracle
) -> ft.Control:
    """Build the branded glass-card header for the graph tab."""
    return glass_card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, color=TH.accent, size=24),
                        ft.Text(
                            " Codebase Explorer",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Container(expand=True),
                        ft.ElevatedButton(
                            " Open Fullscreen Graph",
                            icon=ft.Icons.OPEN_IN_NEW,
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
                ft.Row(
                    [
                        ft.Text("View Mode:", size=SZ_SM, color=TH.dim, weight=ft.FontWeight.BOLD),
                        mode_selector,
                        ft.Container(width=10),
                        ft.Text("Layout:", size=SZ_SM, color=TH.dim, weight=ft.FontWeight.BOLD),
                        layout_selector,
                        ft.Container(expand=True),
                        ft.ElevatedButton(
                            " Analyze Architecture (AI)",
                            icon=ft.Icons.AUTO_AWESOME,
                            on_click=on_run_oracle,
                            bgcolor="#673ab7",
                            color=ft.Colors.WHITE,
                            height=BTN_H_SM,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                            ),
                        ),
                    ],
                    spacing=10,
                ),
                ft.Text(
                    "Nodes = functions \u00b7 "
                    "Edges = relationships \u00b7 "
                    "Colors = health (green=ok, red=issue)",
                    size=SZ_XS,
                    color=TH.muted,
                    italic=True,
                ),
            ],
            spacing=12,
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

    graph_complete = SmartGraph()
    graph_complete.build(
        functions,
        smells,
        dup_groups or [],
        Path("."),
        mode="complete"
    )
    
    graph_calls = SmartGraph()
    graph_calls.build(
        functions,
        smells,
        dup_groups or [],
        Path("."),
        mode="calls"
    )

    graph_hier = SmartGraph()
    graph_hier.build(
        functions,
        smells,
        dup_groups or [],
        Path("."),
        mode="hierarchy"
    )

    # Write full interactive HTML graph and capture URI for the button
    html_content = _generate_graph_html(graph_complete, graph_calls, graph_hier)
    graph_dir = ROOT / "_scratch"
    graph_dir.mkdir(exist_ok=True)
    graph_file = graph_dir / "_graph_view.html"
    graph_file.write_text(html_content, encoding="utf-8")

    async def _open_graph(_e):
        await page.launch_url(graph_file.as_uri())

    graphs_map = {
        "complete": graph_complete,
        "calls": graph_calls,
        "hierarchy": graph_hier
    }

    content_area = ft.Column(
        [
            _build_graph_metrics(graph_complete),
            ft.Divider(color=TH.divider, height=12),
            ft.Container(
                content=_build_graph_canvas(graph_complete),
                height=400,
                expand=True,
                bgcolor=TH.code_bg,
                border=ft.Border.all(1, TH.border),
                border_radius=12,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
            ft.Divider(color=TH.divider, height=12),
            section_title("Components", ""),
            _build_graph_group_chart(graph_complete),
        ],
        spacing=10,
        expand=True,
    )

    oracle_container = ft.Container(
        content=ft.Column(
            [
                ft.Text("Architectural Design Review", size=SZ_H3, weight=ft.FontWeight.BOLD, color=TH.accent),
                ft.Markdown("", selectable=True, extension_set="gitHubWeb", code_theme="atom-one-dark"),
            ],
            spacing=10,
        ),
        visible=False,
        padding=20,
        expand=True,
    )

    def on_run_oracle(e):
        e.control.disabled = True
        e.control.text = " Analyzing..."
        page.update()
        result = _default_oracle.analyze(functions, len(results.get("meta", {}).get("files", [])) or 1)
        if "error" in result:
             oracle_container.content.controls[1].value = f"**Error**: {result['error']}"
        else:
             oracle_container.content.controls[1].value = result.get("markdown", "")
        oracle_container.visible = True
        e.control.text = " Analyze Architecture (AI)"
        e.control.disabled = False
        page.update()
    
    def on_mode_change(e):
        g = graphs_map[e.control.value]
        content_area.controls[0] = _build_graph_metrics(g)
        content_area.controls[2].content = _build_graph_canvas(g)
        content_area.controls[5] = _build_graph_group_chart(g)
        content_area.update()

    mode_selector = ft.Dropdown(
        options=[
            ft.dropdown.Option("complete", "Complete Code Graph"),
            ft.dropdown.Option("calls", "Function Calls"),
            ft.dropdown.Option("hierarchy", "Project Hierarchy"),
        ],
        value="complete",
        width=220,
        height=40,
        bgcolor=TH.code_bg,
        border_color=TH.border,
        color=TH.text,
        text_size=SZ_BODY,
        on_select=on_mode_change,
    )

    layout_selector = ft.Dropdown(
        options=[
            ft.dropdown.Option("force", "Force Directed"),
            ft.dropdown.Option("hierarchical", "Hierarchical Tree"),
        ],
        value="force",
        width=200,
        height=40,
        bgcolor=TH.code_bg,
        border_color=TH.border,
        color=TH.text,
        text_size=SZ_BODY,
        tooltip="Select layout for the Fullscreen Graph explorer",
    )

    return ft.Column(
        [
            _build_graph_header(_open_graph, mode_selector, layout_selector, on_run_oracle),
            ft.Row([content_area, oracle_container], expand=True, spacing=10, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START)
        ],
        spacing=10,
        expand=True,
    )
