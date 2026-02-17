
import json
from pathlib import Path
from typing import List, Dict, Any
from Core.types import FunctionRecord, SmellIssue, DuplicateGroup, Severity

class SmartGraph:
    """Generates a visualization of the codebase health and relationships."""

    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []

    def build(self, functions: List[FunctionRecord], 
              smells: List[SmellIssue], 
              duplicates: List[DuplicateGroup], 
              root: Path):
        """Build the graph nodes and edges."""
        self.nodes = []
        self.edges = []

        # Map function key to smells
        smell_map: Dict[str, List[SmellIssue]] = {}
        for s in smells:
            # Since FunctionRecord.key format is "file::name", strictly we need to match that.
            # SmellIssue doesn't store the exact key, but has file_path and name.
            # Let's try to verify against function keys if possible, or build exact keys.
            if s.name:
                p = Path(s.file_path)
                parent = str(p.parent).replace("\\", "/")
                stem = p.stem
                if parent == ".":
                    k = f"{stem}::{s.name}"
                else:
                    k = f"{parent}/{stem}::{s.name}"
                
                if k not in smell_map:
                    smell_map[k] = []
                smell_map[k].append(s)

        # Create Nodes
        for f in functions:
            f_smells = smell_map.get(f.key, [])
            
            # Determine health color
            color = "#2ecc71" # Green (Healthy)
            health = "healthy"
            
            critical_count = sum(1 for s in f_smells if s.severity == Severity.CRITICAL)
            warning_count = sum(1 for s in f_smells if s.severity == Severity.WARNING)
            
            if critical_count > 0:
                color = "#e74c3c" # Red
                health = "critical"
            elif warning_count > 0:
                color = "#f39c12" # Orange/Yellow
                health = "warning"

            # Tooltip
            tooltip = f"<b>{f.name}</b><br>{f.file_path}:{f.line_start}<br>"
            if f_smells:
                tooltip += "<br><b>Issues:</b><br>"
                for s in f_smells:
                    icon = Severity.icon(s.severity)
                    tooltip += f"{icon} {s.category}: {s.message}<br>"

            self.nodes.append({
                "id": f.key,
                "label": f.name,
                "title": tooltip,
                "color": color,
                "health": health,
                "size": f.size_lines, # Visual size based on LOC
                "group": str(Path(f.file_path).parent) # Group by folder
            })

        # Create Edges (Duplicates)
        for group in duplicates:
            # Fully connected component for each group
            # Or simplified: Connect first to all others, or ring.
            # Let's do a chain or star to avoid clutter.
            # "test_duplicate_edges" expects 1 edge for 2 functions.
            funcs_in_group = group.functions
            if len(funcs_in_group) < 2:
                continue
                
            for i in range(len(funcs_in_group)):
                for j in range(i + 1, len(funcs_in_group)):
                    u = funcs_in_group[i]["key"]
                    v = funcs_in_group[j]["key"]
                    self.edges.append({
                        "from": u,
                        "to": v,
                        "value": group.avg_similarity, # Width
                        "title": f"{group.similarity_type} duplicate ({group.avg_similarity:.2f})"
                    })

    def write_html(self, output_path: Path):
        """Export the graph to an interactive HTML file using vis-network."""
        # Minimal template
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>X-RAY Codebase Visualization</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style type="text/css">
        #mynetwork {{
            width: 100%;
            height: 90vh;
            border: 1px solid lightgray;
        }}
    </style>
</head>
<body>
    <h2>X-RAY Claude — Codebase Health Graph</h2>
    <div id="mynetwork"></div>
    <script type="text/javascript">
        var nodes = new vis.DataSet({json.dumps(self.nodes)});
        var edges = new vis.DataSet({json.dumps(self.edges)});
        var container = document.getElementById('mynetwork');
        var data = {{ nodes: nodes, edges: edges }};
        var options = {{
            nodes: {{
                shape: 'dot',
                font: {{ size: 14, color: '#333' }}
            }},
            edges: {{
                color: 'gray',
                smooth: false
            }},
            physics: {{
                stabilization: false,
                barnesHut: {{
                    gravitationalConstant: -80000,
                    springConstant: 0.001,
                    springLength: 200
                }}
            }}
        }};
        var network = new vis.Network(container, data, options);
    </script>
</body>
</html>
"""
        output_path.write_text(html_content, encoding="utf-8")
