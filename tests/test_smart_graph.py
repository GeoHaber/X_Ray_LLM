from pathlib import Path
from Core.types import FunctionRecord, SmellIssue, DuplicateGroup, Severity
from Analysis.smart_graph import SmartGraph


def test_smart_graph_complete_mode():
    root = Path("/fake/project")
    f1 = FunctionRecord(
        name="funcA",
        file_path="/fake/project/src/a.py",
        line_start=1,
        line_end=10,
        size_lines=10,
        parameters=[],
        return_type=None,
        decorators=[],
        docstring="",
        calls_to=["funcB"],
        complexity=2,
        nesting_depth=1,
        code_hash="hashA",
        structure_hash="structA",
        code="def funcA(): pass",
    )
    f2 = FunctionRecord(
        name="funcB",
        file_path="/fake/project/src/b.py",
        line_start=1,
        line_end=5,
        size_lines=5,
        parameters=[],
        return_type=None,
        decorators=[],
        docstring="",
        calls_to=[],
        complexity=1,
        nesting_depth=1,
        code_hash="hashB",
        structure_hash="structB",
        code="def funcB(): pass",
    )

    smell = SmellIssue(
        file_path="/fake/project/src/a.py",
        line=1,
        end_line=10,
        category="complexity",
        severity=Severity.CRITICAL,
        name="funcA",
        metric_value=20,
        message="Too complex",
        suggestion="Refactor",
        source="linter",
    )

    dup = DuplicateGroup(
        group_id=1,
        functions=[{"key": f1.key}, {"key": f2.key}],
        avg_similarity=0.9,
        similarity_type="exact",
    )

    sg = SmartGraph()
    sg.build([f1, f2], [smell], [dup], root, mode="complete")

    assert len(sg.nodes) == 2
    assert len(sg.edges) == 1

    # Check node metadata
    nodeA = next((n for n in sg.nodes if n["id"] == f1.key), None)
    assert nodeA is not None
    assert nodeA["health"] == "critical"
    assert nodeA["color"] == "#ff4d4f"
    assert nodeA["group"] == str(Path("/fake/project/src"))
    assert len(nodeA["issues"]) == 1


def test_smart_graph_calls_mode():
    root = Path("/fake/project")
    f1 = FunctionRecord(
        name="funcA",
        file_path="/fake/project/src/a.py",
        line_start=1,
        line_end=10,
        size_lines=10,
        parameters=["x"],
        return_type=None,
        decorators=[],
        docstring="",
        calls_to=["funcB"],
        complexity=1,
        nesting_depth=1,
        code_hash="hashA",
        structure_hash="structA",
        code="",
    )
    f2 = FunctionRecord(
        name="funcB",
        file_path="/fake/project/src/b.py",
        line_start=1,
        line_end=5,
        size_lines=5,
        parameters=[],
        return_type=None,
        decorators=[],
        docstring="",
        calls_to=[],
        complexity=1,
        nesting_depth=1,
        code_hash="hashB",
        structure_hash="structB",
        code="",
    )

    sg = SmartGraph()
    sg.build([f1, f2], [], [], root, mode="calls")

    assert len(sg.nodes) == 2
    assert len(sg.edges) == 1
    assert sg.edges[0]["from"] == f1.key
    assert sg.edges[0]["to"] == f2.key
    assert sg.edges[0]["arrows"] == "to"


def test_smart_graph_hierarchy_mode():
    root = Path("root")
    f1 = FunctionRecord(
        name="funcA",
        file_path="root/src/a.py",
        line_start=1,
        line_end=10,
        size_lines=10,
        parameters=[],
        return_type=None,
        decorators=[],
        docstring="",
        calls_to=[],
        complexity=1,
        nesting_depth=1,
        code_hash="hashA",
        structure_hash="structA",
        code="",
    )

    sg = SmartGraph()
    sg.build([f1], [], [], root, mode="hierarchy")

    # Nodes should be: root module, "root", "src", "a.py", and funcA
    # Edges should connect them.
    assert len(sg.nodes) > 1

    # Root node should exist
    root_node = next((n for n in sg.nodes if n["id"] == "root"), None)
    assert root_node is not None

    # file node should exist
    file_node_id = "path:root/src/a.py"
    file_node = next((n for n in sg.nodes if n["id"] == file_node_id), None)
    assert file_node is not None

    # Edge from path -> funcA should exist
    edge = next(
        (e for e in sg.edges if e["from"] == file_node_id and e["to"] == f1.key), None
    )
    assert edge is not None
