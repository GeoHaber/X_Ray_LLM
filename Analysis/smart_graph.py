import json
from pathlib import Path
from typing import List, Dict, Any
from Core.types import FunctionRecord, SmellIssue, DuplicateGroup, Severity


class SmartGraph:
    """Generates a visualization of the codebase health and relationships (Premium Edition)."""

    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []

    def build(
        self,
        functions: List[FunctionRecord],
        smells: List[SmellIssue],
        duplicates: List[DuplicateGroup],
        root: Path,
        mode: str = "complete"  # 'complete', 'calls', 'hierarchy'
    ):
        """Build the graph nodes and edges."""
        self.nodes = []
        self.edges = []
        smell_map = self._build_smell_map(smells)

        if mode == "calls":
            self.nodes, self.edges = self._build_call_graph(functions, smell_map)
        elif mode == "hierarchy":
            self.nodes, self.edges = self._build_hierarchy_graph(functions, root)
        else:  # default complete graph
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
            color, health = "#ff4d4f", "critical"
        elif warning_count > 0:
            color, health = "#faad14", "warning"
        else:
            color, health = "#52c41a", "healthy"

        issues_data = [{"category": s.category, "severity": s.severity, "message": s.message} for s in f_smells]
        return {
            "id": f.key,
            "label": f.name,
            "title": f.name,
            "color": color,
            "health": health,
            "size": max(10, f.size_lines),
            "group": str(Path(f.file_path).parent),
            "signature": f.name + "(" + ", ".join(f.parameters) + ")",
            "file": f.file_path,
            "line": f.line_start,
            "code": f.code[:1000] + ("..." if len(f.code) > 1000 else ""),
            "issues": issues_data,
            "complexity": f.complexity,
            "shape": "dot"
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
                            "color": {"color": "#ffffff", "opacity": 0.3},
                            "dashes": True,
                        }
                    )
        return edges

    def _build_call_graph(self, functions: List[FunctionRecord], smell_map: Dict):
        nodes = []
        edges = []
        func_keys = {f.name: f.key for f in functions}
        for f in functions:
            nodes.append(self._make_node(f, smell_map.get(f.key, [])))
            for call in f.calls_to:
                if call in func_keys:
                    edges.append({
                        "from": f.key,
                        "to": func_keys[call],
                        "arrows": "to",
                        "color": {"color": "#a855f7", "opacity": 0.6},
                        "title": f"calls {call}"
                    })
        return nodes, edges

    def _build_hierarchy_graph(self, functions: List[FunctionRecord], root: Path):
        nodes = []
        edges = []
        dirs = set()
        files = set()

        nodes.append({"id": "root", "label": root.name, "color": "#1e293b", "size": 30, "shape": "box", "font": {"color": "white"}})

        for f in functions:
            nodes.append(self._make_node(f, []))
            p = Path(f.file_path)
            parts = list(p.parts)

            parent_id = "root"
            current_path = ""
            for i, part in enumerate(parts):
                current_path = current_path + "/" + part if current_path else part
                is_file = (i == len(parts) - 1)
                node_id = f"path:{current_path}"

                if current_path not in dirs and current_path not in files:
                    if is_file:
                        files.add(current_path)
                        nodes.append({"id": node_id, "label": part, "color": "#334155", "size": 20, "shape": "box", "font": {"color": "white"}})
                    else:
                        dirs.add(current_path)
                        nodes.append({"id": node_id, "label": part, "color": "#0f172a", "size": 25, "shape": "box", "font": {"color": "white"}})

                    edges.append({"from": parent_id, "to": node_id, "color": {"color": "#64748b", "opacity": 0.4}, "arrows": "to"})
                parent_id = node_id

            edges.append({"from": parent_id, "to": f.key, "color": {"color": "#94a3b8", "opacity": 0.4}})

        return nodes, edges

    def write_html(self, output_path: Path):
        """Not used by GUI, but keeping signature for CLI compatibility."""
        output_path.write_text("<html><body>Use GUI to view premium graph.</body></html>", encoding="utf-8")


# Module-level API for test compatibility
_default_analyzer = SmartGraph()

def build(*args, **kwargs):
    """Wrapper for SmartGraph.build()."""
    return _default_analyzer.build(*args, **kwargs)

def write_html(*args, **kwargs):
    """Wrapper for SmartGraph.write_html()."""
    return _default_analyzer.write_html(*args, **kwargs)

