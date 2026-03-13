"""
tests/test_analysis_diagram_export.py — Unit tests for Analysis/diagram_export.py
"""
from Analysis.diagram_export import DiagramExporter, _node_id, _short_label, _detect_layer


class TestHelpers:
    def test_node_id_removes_special_chars(self):
        nid = _node_id("Analysis/smells.py")
        assert "/" not in nid
        assert "." not in nid

    def test_node_id_max_length(self):
        long = "very/long/path/" * 10 + "file.py"
        assert len(_node_id(long)) <= 40

    def test_short_label_strips_extension(self):
        assert _short_label("Analysis/smells.py") == "smells"

    def test_short_label_max_length(self):
        assert len(_short_label("a" * 100)) <= 30

    def test_detect_layer_core(self):
        assert _detect_layer("Core/utils.py") == "Core"

    def test_detect_layer_analysis(self):
        assert _detect_layer("Analysis/smells.py") == "Analysis"

    def test_detect_layer_ui(self):
        assert _detect_layer("UI/tabs/graph_tab.py") == "UI"

    def test_detect_layer_tests(self):
        assert _detect_layer("tests/test_smells.py") == "Tests"

    def test_detect_layer_unknown(self):
        assert _detect_layer("random/module.py") == "Other"


class TestDiagramExporter:
    EDGES = [
        ("Core/utils.py", "Analysis/smells.py"),
        ("Analysis/smells.py", "UI/tabs/smells_tab.py"),
        ("Core/config.py", "Analysis/smells.py"),
    ]

    def test_export_returns_result(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert result.node_count > 0
        assert result.edge_count > 0

    def test_mermaid_flowchart_contains_mermaid_marker(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert "```mermaid" in result.mermaid_flowchart
        assert "flowchart TD" in result.mermaid_flowchart

    def test_mermaid_contains_subgraphs(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert "subgraph" in result.mermaid_flowchart

    def test_mermaid_contains_arrow(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert "-->" in result.mermaid_flowchart

    def test_c4_context_generated(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert "C4Context" in result.c4_context or len(result.c4_context) > 0

    def test_c4_component_generated(self):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        assert len(result.c4_component) > 0

    def test_empty_edges(self):
        e = DiagramExporter()
        result = e.export([])
        assert result.node_count == 0
        assert result.edge_count == 0

    def test_max_nodes_respected(self):
        large_edges = [(f"file_{i}.py", f"file_{i+1}.py") for i in range(200)]
        e = DiagramExporter()
        result = e.export(large_edges, max_nodes=50)
        assert result.node_count <= 50

    def test_duplicate_edges_deduplicated(self):
        duped = self.EDGES * 5
        e = DiagramExporter()
        r1 = e.export(self.EDGES)
        r2 = e.export(duped)
        assert r1.edge_count == r2.edge_count

    def test_save_writes_file(self, tmp_path):
        e = DiagramExporter()
        result = e.export(self.EDGES)
        out = tmp_path / "arch.mmd"
        e.save(result.mermaid_flowchart, out)
        assert out.exists()
        assert len(out.read_text()) > 0
