from Analysis.design_oracle import DesignOracle
from Core.types import FunctionRecord


def test_design_oracle_initialization():
    oracle = DesignOracle()
    assert oracle is not None
    assert "Design Oracle" in oracle.system_prompt


def test_design_oracle_empty_functions():
    oracle = DesignOracle()
    result = oracle.analyze([], 0)
    assert "error" in result
    assert (
        result["error"]
        == "No functions found. Could not perform architectural analysis."
    )


def test_design_oracle_mock_analysis():
    oracle = DesignOracle()
    fake_func = FunctionRecord(
        name="test_func",
        file_path="test.py",
        line_start=1,
        line_end=10,
        complexity=2,
        nesting_depth=1,
        parameters=[],
        docstring=None,
        code="pass",
        size_lines=10,
        return_type=None,
        decorators=[],
        calls_to=set(),
        code_hash="demo",
        structure_hash="demo",
    )
    result = oracle.analyze([fake_func], 1)

    assert "status" in result
    assert result["status"] == "success"
    assert "markdown" in result
    assert "Architectural Summary" in result["markdown"]
    assert result["target_files"] == 1


def test_design_oracle_summary():
    oracle = DesignOracle()
    # Test error sumary
    err_res = oracle.summary({"error": "Failed to analyze"})
    assert "error" in err_res

    # Test success summary
    succ_res = oracle.summary({"status": "success", "markdown": "Some text"})
    assert "insight_generated" in succ_res
    assert succ_res["insight_generated"] is True
    assert succ_res["characters"] == 9
