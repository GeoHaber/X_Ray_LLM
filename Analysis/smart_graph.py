import json
from pathlib import Path
from typing import List, Dict, Any
from Core.types import FunctionRecord, SmellIssue, DuplicateGroup, Severity


class SmartGraph:
    """Generates a visualization of the codebase health and relationships."""

    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []

    def build(
        self,
        functions: List[FunctionRecord],
        smells: List[SmellIssue],
        duplicates: List[DuplicateGroup],
        root: Path,
    ):
        """Build the graph nodes and edges."""
        self.nodes = []
        self.edges = []
        smell_map = self._build_smell_map(smells)
        self.nodes = [self._make_node(f, smell_map.get(f.key, [])) for f in functions]
        self.edges = self._make_edges(duplicates)

    # -- private helpers (extracted from build) ------------------------------

    @staticmethod
    def _build_smell_map(smells: List[SmellIssue]) -> Dict[str, List[SmellIssue]]:
        """Map ``file::name`` keys to their associated SmellIssue lists."""
        smell_map: Dict[str, List[SmellIssue]] = {}
        for s in smells:
            if not s.name:
                continue
            p = Path(s.file_path)
            parent = str(p.parent).replace("\\", "/")
            stem = p.stem
            k = f"{stem}::{s.name}" if parent == "." else f"{parent}/{stem}::{s.name}"
            smell_map.setdefault(k, []).append(s)
        return smell_map

    @staticmethod
    def _make_node(f: FunctionRecord, f_smells: List[SmellIssue]) -> Dict[str, Any]:
        """Create a single graph node dict for *f*."""
        critical_count = sum(1 for s in f_smells if s.severity == Severity.CRITICAL)
        warning_count = sum(1 for s in f_smells if s.severity == Severity.WARNING)

        if critical_count > 0:
            color, health = "#e74c3c", "critical"
        elif warning_count > 0:
            color, health = "#f39c12", "warning"
        else:
            color, health = "#2ecc71", "healthy"

        tooltip = f"<b>{f.name}</b><br>{f.file_path}:{f.line_start}<br>"
        if f_smells:
            tooltip += "<br><b>Issues:</b><br>"
            for s in f_smells:
                icon = Severity.icon(s.severity)
                tooltip += f"{icon} {s.category}: {s.message}<br>"

        return {
            "id": f.key,
            "label": f.name,
            "title": tooltip,
            "color": color,
            "health": health,
            "size": f.size_lines,
            "group": str(Path(f.file_path).parent),
        }

    @staticmethod
    def _make_edges(duplicates: List[DuplicateGroup]) -> List[Dict[str, Any]]:
        """Generate pairwise edge dicts from DuplicateGroups."""
        edges: List[Dict[str, Any]] = []
        for group in duplicates:
            funcs = group.functions
            if len(funcs) < 2:
                continue
            for i in range(len(funcs)):
                for j in range(i + 1, len(funcs)):
                    edges.append(
                        {
                            "from": funcs[i]["key"],
                            "to": funcs[j]["key"],
                            "value": group.avg_similarity,
                            "title": f"{group.similarity_type} duplicate ({group.avg_similarity:.2f})",
                        }
                    )
        return edges

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


# Module-level API for test compatibility
_default_analyzer = SmartGraph()

def build(*args, **kwargs):
    """Wrapper for SmartGraph.build()."""
    return _default_analyzer.build(*args, **kwargs)

def write_html(*args, **kwargs):
    """Wrapper for SmartGraph.write_html()."""
    return _default_analyzer.write_html(*args, **kwargs)

