"""
Analysis/diagram_export.py — Mermaid / C4 Architecture Diagram Export (v8.0)
=============================================================================

Converts the X-Ray import graph into architecture diagrams in two formats:

* **Mermaid flowchart** — paste directly into GitHub READMEs, Notion, or
  any Markdown renderer that supports Mermaid (now default on GitHub).
* **C4 Context + Component** — simplified C4 Model representations showing
  how the major layers relate to each other.

Usage::

    from pathlib import Path
    from Analysis.diagram_export import DiagramExporter

    exporter = DiagramExporter(root=Path("/my/project"))
    mmd = exporter.build_mermaid(import_edges)
    exporter.save(mmd, Path("xray_architecture.mmd"))
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Edges: list of (source_module, target_module) strings
Edge = Tuple[str, str]

# Layer detection keywords (used in C4 grouping)
_LAYER_PATTERNS = {
    "Core": re.compile(r"(^|/)core/", re.IGNORECASE),
    "Analysis": re.compile(r"(^|/)analysis/", re.IGNORECASE),
    "UI": re.compile(r"(^|/)(ui|tabs|frontend|views?)/", re.IGNORECASE),
    "Tests": re.compile(r"(^|/)tests?/", re.IGNORECASE),
    "Lang": re.compile(r"(^|/)lang/", re.IGNORECASE),
    "Config": re.compile(r"(setup|config|settings)", re.IGNORECASE),
}

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _node_id(path: str) -> str:
    """Convert a file path to a safe Mermaid node ID."""
    return _SANITIZE_RE.sub("_", path).strip("_")[:40]


def _short_label(path: str) -> str:
    """Human-readable short label for a node."""
    return Path(path).stem[:30]


def _detect_layer(path: str) -> str:
    for layer, pattern in _LAYER_PATTERNS.items():
        if pattern.search(path):
            return layer
    return "Other"


@dataclass
class DiagramResult:
    """Generated diagram content."""

    mermaid_flowchart: str = ""
    c4_context: str = ""
    c4_component: str = ""
    node_count: int = 0
    edge_count: int = 0


class DiagramExporter:
    """Build Mermaid and C4 diagrams from import graph data."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(
        self,
        edges: List[Edge],
        max_nodes: int = 80,
    ) -> DiagramResult:
        """
        Generate all diagram formats from *edges*.

        Args:
            edges: List of (source, target) pairs from the import graph.
            max_nodes: Cap node count to keep diagrams readable.
        """
        result = DiagramResult()

        # Deduplicate and collect nodes
        unique_edges = list(dict.fromkeys(edges))
        nodes = _collect_nodes(unique_edges, max_nodes)
        filtered = [(s, t) for s, t in unique_edges if s in nodes and t in nodes]

        result.node_count = len(nodes)
        result.edge_count = len(filtered)
        result.mermaid_flowchart = self._mermaid_flowchart(nodes, filtered)
        result.c4_context = self._c4_context(nodes, filtered)
        result.c4_component = self._c4_component(nodes, filtered)

        return result

    def save(self, content: str, path: Path) -> None:
        """Write diagram content to *path*."""
        path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Mermaid Flowchart
    # ------------------------------------------------------------------

    def _mermaid_flowchart(self, nodes: set, edges: List[Edge]) -> str:
        lines = ["```mermaid", "flowchart TD"]

        # Subgraphs by layer
        by_layer: dict[str, list[str]] = {}
        for node in nodes:
            layer = _detect_layer(node)
            by_layer.setdefault(layer, []).append(node)

        for layer, layer_nodes in sorted(by_layer.items()):
            lines.append(f"    subgraph {layer}")
            for n in sorted(layer_nodes):
                nid = _node_id(n)
                label = _short_label(n)
                lines.append(f'        {nid}["{label}"]')
            lines.append("    end")

        lines.append("")
        for src, tgt in edges:
            lines.append(f"    {_node_id(src)} --> {_node_id(tgt)}")

        lines.append("```")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # C4 Context Diagram
    # ------------------------------------------------------------------

    def _c4_context(self, nodes: set, edges: List[Edge]) -> str:
        layers = sorted({_detect_layer(n) for n in nodes})
        lines = [
            "```mermaid",
            "C4Context",
            '    title System Context Diagram — X-Ray Project',
            "",
        ]

        for layer in layers:
            lines.append(f'    System("{layer}", "{layer} Layer", "Python package")')

        lines.append("")
        # Inter-layer edges
        seen: set = set()
        for src, tgt in edges:
            sl = _detect_layer(src)
            tl = _detect_layer(tgt)
            if sl != tl:
                key = (sl, tl)
                if key not in seen:
                    seen.add(key)
                    lines.append(f'    Rel("{sl}", "{tl}", "imports")')

        lines.append("```")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # C4 Component Diagram
    # ------------------------------------------------------------------

    def _c4_component(self, nodes: set, edges: List[Edge]) -> str:
        lines = [
            "```mermaid",
            "C4Component",
            '    title Component Diagram — Major Modules',
            "",
        ]

        # Only include up to 30 most-referenced nodes
        ref_count: dict[str, int] = {}
        for _, tgt in edges:
            ref_count[tgt] = ref_count.get(tgt, 0) + 1

        top_nodes = sorted(nodes, key=lambda n: ref_count.get(n, 0), reverse=True)[:30]

        for node in top_nodes:
            nid = _node_id(node)
            label = _short_label(node)
            layer = _detect_layer(node)
            lines.append(f'    Component({nid}, "{label}", "{layer}")')

        lines.append("")
        for src, tgt in edges:
            if src in top_nodes and tgt in top_nodes:
                lines.append(f"    Rel({_node_id(src)}, {_node_id(tgt)}, \"imports\")")

        lines.append("```")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _collect_nodes(edges: List[Edge], max_nodes: int) -> set:
    """Collect unique node paths, capped at *max_nodes*."""
    nodes: set = set()
    for src, tgt in edges:
        nodes.add(src)
        nodes.add(tgt)
        if len(nodes) >= max_nodes:
            break
    return nodes
