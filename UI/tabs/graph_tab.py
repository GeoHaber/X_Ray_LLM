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


# Use unique placeholders to avoid scan collisions
_GRAPH_DATA_PLACEHOLDER = "___XRAY_GRAPH_INJECTION_POINT___"
_GRAPH_LIB_PLACEHOLDER = "___XRAY_FORCEGRAPH_LIB___"
_VENDOR_JS = ROOT / "_vendor_force_graph.min.js"

_GRAPH_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>X-RAY Code Graph Explorer</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script>___XRAY_FORCEGRAPH_LIB___</script>
    <style>
        body {
            margin: 0; padding: 0;
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: 'Outfit', sans-serif;
            overflow: hidden;
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
        #graph { width: 100vw; height: 100vh; }

        #sidebar {
            width: 400px;
            background: rgba(22, 27, 34, 0.95);
            backdrop-filter: blur(20px);
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
            color: #ffffff;
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
            white-space: pre;
            overflow: auto;
            max-height: 400px;
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
        #node-count { color: #8b949e; font-size: 13px; margin-left: 20px; white-space: nowrap; }
    </style>
</head>
<body>
    <div id="header">
        <h2>X-RAY Explorer</h2>
        <span id="node-count"></span>
        <input type="text" class="search-box" id="searchInput" placeholder="Search functions or files...">
        <div class="controls">
            <select id="modeSelect">
                <option value="hierarchy">Project Hierarchy</option>
                <option value="complete">Complete Code Graph</option>
                <option value="calls">Function Calls</option>
            </select>
            <select id="layoutSelect">
                <option value="tree">Tree Layout</option>
                <option value="force">Force Directed</option>
                <option value="radial">Radial</option>
            </select>
            <button id="fitBtn">Fit Screen</button>
        </div>
    </div>

    <div id="graph"></div>
    <div id="loading" style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;background:rgba(13,17,23,0.92);z-index:50;">
        <div style="text-align:center;">
            <div style="font-size:28px;color:#58a6ff;margin-bottom:12px;">Loading Graph...</div>
            <div id="loadStatus" style="color:#8b949e;font-size:14px;">Initializing</div>
        </div>
    </div>

    <div id="sidebar">
        <div class="close-btn" id="closeSidebar">&#10005;</div>
        <div id="sb-content" style="margin-top: 40px;">
            <div class="node-title" id="sb-title">Node Selected</div>
            <div id="sb-badges" style="margin-bottom: 10px;"></div>
            <div class="node-meta" id="sb-meta">Select a node to view details</div>
            <div id="sb-details" style="display:none;">
                <div class="section-title">Signature</div>
                <div class="node-code" id="sb-sig"></div>
                <div class="section-title" id="sb-issues-title" style="color: #ff4d4f; margin-top: 25px;">Detected Issues</div>
                <div id="sb-issues"></div>
            </div>
        </div>
    </div>

    <script type="application/json" id="xray-data">___XRAY_GRAPH_INJECTION_POINT___</script>

    <script type="text/javascript">
    try {
        var loadEl = document.getElementById('loadStatus');
        function setStatus(msg) { if (loadEl) loadEl.textContent = msg; }
        setStatus('Parsing graph data...');

        var allDatasets;
        try {
            allDatasets = JSON.parse(document.getElementById('xray-data').textContent);
            setStatus('Data parsed OK');
        } catch (err) {
            document.getElementById('loading').innerHTML =
                '<div style="text-align:center;"><div style="font-size:28px;color:#ff4d4f;margin-bottom:12px;">' +
                'Data Load Failed</div><pre style="color:#c9d1d9;">' + err + '</pre></div>';
            throw err;
        }

        /* ── Transform vis-network data to force-graph format ── */
        function transformDataset(ds) {
            var nodes = ds.nodes.map(function(n) {
                var c = '#888';
                if (n.color) {
                    if (typeof n.color === 'object' && n.color.background) c = n.color.background;
                    else if (typeof n.color === 'string') c = n.color;
                }
                return {
                    id: n.id, label: n.label || n.id, name: n.label || n.id,
                    val: n.size || 10, nodeColor: c, health: n.health,
                    file: n.file, line: n.line, signature: n.signature,
                    code: n.code, issues: n.issues, complexity: n.complexity,
                    group: n.group, shape: n.shape
                };
            });
            var links = (ds.edges || []).map(function(e) {
                var c = 'rgba(255,255,255,0.15)';
                if (e.color) {
                    if (typeof e.color === 'object' && e.color.color) c = e.color.color;
                    else if (typeof e.color === 'string') c = e.color;
                }
                return { source: e.from, target: e.to, linkColor: c, title: e.title };
            });
            /* Build neighbor index for hover-highlighting */
            var nodeById = {};
            nodes.forEach(function(n) { n.neighbors = []; n.links = []; nodeById[n.id] = n; });
            links.forEach(function(link) {
                var a = nodeById[link.source], b = nodeById[link.target];
                if (a && b) {
                    a.neighbors.push(b); b.neighbors.push(a);
                    a.links.push(link);  b.links.push(link);
                }
            });
            return { nodes: nodes, links: links };
        }

        /* ── State ── */
        var highlightNodes = new Set();
        var hoverNode = null;
        var searchTerm = '';

        /* ── Build force-graph ── */
        var container = document.getElementById('graph');
        var Graph = new ForceGraph(container)
            .backgroundColor('#0d1117')
            .nodeId('id')
            .nodeLabel(function(n) {
                var parts = [n.label || n.id];
                if (n.file) parts.push(n.file + ':' + n.line);
                if (n.health) parts.push(n.health.toUpperCase());
                return parts.join('\\n');
            })
            .nodeColor(function(n) {
                if (highlightNodes.size > 0) {
                    return highlightNodes.has(n) ? n.nodeColor : 'rgba(60,60,60,0.3)';
                }
                return n.nodeColor;
            })
            .nodeVal(function(n) { return Math.min(n.val || 4, 20); })
            .nodeRelSize(3)
            .nodeCanvasObjectMode(function() { return 'after'; })
            .nodeCanvasObject(function(node, ctx, globalScale) {
                var r = Math.sqrt(node.val || 10) * 5 + 2;
                /* Highlight ring for hovered/neighbor nodes */
                if (highlightNodes.has(node)) {
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI, false);
                    ctx.fillStyle = node === hoverNode
                        ? 'rgba(88,166,255,0.4)' : 'rgba(88,166,255,0.15)';
                    ctx.fill();
                }
                /* Draw label when zoomed in enough */
                var fontSize = 12 / globalScale;
                if (globalScale > 1.2 || highlightNodes.has(node)) {
                    var label = node.label || node.id || '';
                    ctx.font = fontSize + 'px Outfit, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'top';
                    ctx.fillStyle = 'rgba(255,255,255,0.9)';
                    ctx.fillText(label, node.x, node.y + r + 2);
                }
            })
            .nodeVisibility(function(n) {
                if (!searchTerm) return true;
                return (n.label && n.label.toLowerCase().indexOf(searchTerm) >= 0) ||
                       (n.file  && n.file.toLowerCase().indexOf(searchTerm) >= 0);
            })
            .linkColor(function(l) { return l.linkColor || 'rgba(255,255,255,0.15)'; })
            .linkWidth(1)
            .linkDirectionalArrowLength(4)
            .linkDirectionalArrowRelPos(1)
            .onNodeHover(function(node) {
                container.style.cursor = node ? 'pointer' : null;
                highlightNodes.clear();
                if (node) {
                    highlightNodes.add(node);
                    if (node.neighbors) node.neighbors.forEach(function(nb) { highlightNodes.add(nb); });
                }
                hoverNode = node || null;
            })
            .onNodeClick(function(node) {
                if (!node) return;
                var sid = String(node.id);
                if (sid === 'root' || sid.indexOf('path:') === 0) return;
                showSidebar(node);
            })
            .onBackgroundClick(function() {
                document.getElementById('sidebar').classList.remove('open');
            })
            .cooldownTime(4000)
            .warmupTicks(50)
            .dagMode('td')
            .dagLevelDistance(60);

        /* ── Load a mode ── */
        function loadMode(mode) {
            var data = transformDataset(allDatasets[mode]);
            var layout = document.getElementById('layoutSelect').value;
            if (layout === 'tree')        Graph.dagMode('td').dagLevelDistance(60);
            else if (layout === 'radial') Graph.dagMode('radialout').dagLevelDistance(60);
            else                          Graph.dagMode(null);
            Graph.graphData(data);
            document.getElementById('node-count').textContent =
                data.nodes.length + ' nodes \u00b7 ' + data.links.length + ' links';
        }

        function autoLayout(mode) {
            document.getElementById('layoutSelect').value = (mode === 'hierarchy') ? 'tree' : 'force';
        }

        /* ── Init ── */
        autoLayout('hierarchy');
        loadMode('hierarchy');
        setTimeout(function() {
            Graph.zoomToFit(400);
            document.getElementById('loading').style.display = 'none';
        }, 2000);

        /* ── Mode toggle ── */
        document.getElementById('modeSelect').addEventListener('change', function(e) {
            var mode = e.target.value;
            var overlay = document.getElementById('loading');
            if (overlay) { overlay.style.display = 'flex'; setStatus('Switching to ' + mode + '...'); }
            document.getElementById('sidebar').classList.remove('open');
            document.getElementById('searchInput').value = '';
            searchTerm = '';
            autoLayout(mode);
            setTimeout(function() {
                loadMode(mode);
                setTimeout(function() {
                    Graph.zoomToFit(400);
                    if (overlay) overlay.style.display = 'none';
                }, 2000);
            }, 50);
        });

        /* ── Layout toggle ── */
        document.getElementById('layoutSelect').addEventListener('change', function(e) {
            var val = e.target.value;
            if (val === 'tree')        Graph.dagMode('td').dagLevelDistance(60);
            else if (val === 'radial') Graph.dagMode('radialout').dagLevelDistance(60);
            else                       Graph.dagMode(null);
            Graph.d3ReheatSimulation();
            setTimeout(function() { Graph.zoomToFit(400); }, 2000);
        });

        /* ── Search ── */
        document.getElementById('searchInput').addEventListener('input', function(e) {
            searchTerm = e.target.value.toLowerCase();
            Graph.nodeVisibility(function(n) {
                if (!searchTerm) return true;
                return (n.label && n.label.toLowerCase().indexOf(searchTerm) >= 0) ||
                       (n.file  && n.file.toLowerCase().indexOf(searchTerm) >= 0);
            });
        });

        /* ── Fit ── */
        document.getElementById('fitBtn').addEventListener('click', function() {
            Graph.zoomToFit(400);
        });

        /* ── Sidebar ── */
        document.getElementById('closeSidebar').onclick = function() {
            document.getElementById('sidebar').classList.remove('open');
        };

        function showSidebar(node) {
            var sb = document.getElementById('sidebar');
            sb.classList.add('open');
            document.getElementById('sb-title').textContent = node.label || node.name || node.id;

            var badges = document.getElementById('sb-badges');
            badges.innerHTML = '';
            if (node.health) {
                badges.innerHTML += '<span class="badge badge-' + node.health + '">'
                    + node.health.toUpperCase() + '</span>';
            }
            if (node.complexity) {
                badges.innerHTML += '<span class="badge" style="color:#8b949e;border-color:#30363d;'
                    + 'background:transparent;">Cx: ' + node.complexity + '</span>';
            }

            document.getElementById('sb-meta').textContent =
                node.file ? node.file + ' | Line ' + node.line : '';
            document.getElementById('sb-details').style.display = 'block';
            document.getElementById('sb-sig').textContent = node.signature || node.label || node.id;

            var issuesDiv = document.getElementById('sb-issues');
            issuesDiv.innerHTML = '';
            var issuesTitle = document.getElementById('sb-issues-title');
            if (node.issues && node.issues.length > 0) {
                issuesTitle.style.display = 'block';
                node.issues.forEach(function(iss) {
                    var d = document.createElement('div');
                    d.className = 'issue-card issue-' + iss.severity;
                    d.innerHTML = '<strong style="color:#c9d1d9;font-size:12px;letter-spacing:0.5px;">'
                        + iss.severity + '</strong><div class="issue-msg">'
                        + iss.category + ': ' + iss.message + '</div>';
                    issuesDiv.appendChild(d);
                });
            } else {
                issuesTitle.style.display = 'none';
            }
        }

        setStatus('Graph ready.');
    } catch (globalErr) {
        var el = document.getElementById('loading');
        if (el) el.innerHTML = '<div style="text-align:center;"><div style="font-size:28px;'
            + 'color:#ff4d4f;margin-bottom:12px;">Error</div><pre style="color:#c9d1d9;'
            + 'max-width:600px;white-space:pre-wrap;">' + globalErr + '\\n'
            + (globalErr.stack||'') + '</pre></div>';
    }
    </script>
</body>
</html>"""


def _strip_code_for_html(nodes: list) -> list:
    """Return nodes with 'code' field truncated to keep HTML small."""
    out = []
    for n in nodes:
        n2 = dict(n)
        n2.pop("code", None)
        out.append(n2)
    return out


def _generate_graph_html(
    graph_complete: SmartGraph, graph_calls: SmartGraph, graph_hier: SmartGraph
) -> str:
    """Generate a self-contained HTML page with force-graph visualization."""
    import json as _json

    data_dict = {
        "complete": {
            "nodes": _strip_code_for_html(graph_complete.nodes),
            "edges": graph_complete.edges,
        },
        "calls": {
            "nodes": _strip_code_for_html(graph_calls.nodes),
            "edges": graph_calls.edges,
        },
        "hierarchy": {
            "nodes": _strip_code_for_html(graph_hier.nodes),
            "edges": graph_hier.edges,
        },
    }
    data_json = _json.dumps(data_dict).replace("</", "<\\/")
    # Inline the force-graph library so file:// pages work without CDN
    vendor_js = _VENDOR_JS.read_text(encoding="utf-8") if _VENDOR_JS.exists() else ""
    html = _GRAPH_HTML_TEMPLATE.replace(_GRAPH_LIB_PLACEHOLDER, vendor_js)
    return html.replace(_GRAPH_DATA_PLACEHOLDER, data_json)


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
                        ft.Icon(
                            ft.Icons.SUBDIRECTORY_ARROW_RIGHT, color=TH.accent, size=24
                        ),
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
                        ft.Text(
                            "View Mode:",
                            size=SZ_SM,
                            color=TH.dim,
                            weight=ft.FontWeight.BOLD,
                        ),
                        mode_selector,
                        ft.Container(width=10),
                        ft.Text(
                            "Layout:",
                            size=SZ_SM,
                            color=TH.dim,
                            weight=ft.FontWeight.BOLD,
                        ),
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


def _build_oracle_container():
    """Build the oracle results container and its run handler."""
    container = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Architectural Design Review",
                    size=SZ_H3,
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                ),
                ft.Markdown(
                    "",
                    selectable=True,
                    extension_set="gitHubWeb",
                    code_theme="atom-one-dark",
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
        visible=False,
        padding=20,
        expand=True,
    )
    return container


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
        functions, smells, dup_groups or [], Path("."), mode="complete"
    )

    graph_calls = SmartGraph()
    graph_calls.build(functions, smells, dup_groups or [], Path("."), mode="calls")

    graph_hier = SmartGraph()
    graph_hier.build(functions, smells, dup_groups or [], Path("."), mode="hierarchy")

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
        "hierarchy": graph_hier,
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
                on_click=_open_graph,
                tooltip="Click to open fullscreen interactive graph",
                ink=True,
            ),
            ft.Divider(color=TH.divider, height=12),
            section_title("Components", ""),
            _build_graph_group_chart(graph_complete),
        ],
        spacing=10,
        expand=True,
    )

    oracle_container = _build_oracle_container()

    def on_run_oracle(e):
        e.control.disabled = True
        e.control.text = " Analyzing..."
        page.update()
        file_count = results.get("meta", {}).get("files", 1) or 1
        result = _default_oracle.analyze(functions, file_count)
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
            _build_graph_header(
                _open_graph, mode_selector, layout_selector, on_run_oracle
            ),
            ft.Row(
                [content_area, oracle_container],
                expand=True,
                spacing=10,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ],
        spacing=10,
        expand=True,
    )
