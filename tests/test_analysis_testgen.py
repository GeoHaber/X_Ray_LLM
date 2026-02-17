"""
Tests for Analysis/test_gen.py — TestReferenceGenerator.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock
from Analysis.test_gen import TestReferenceGenerator


# ── sample functions ─────────────────────────────────────────────────

def sample_add(a: int, b: int) -> int:
    return a + b

def sample_divide(a: float, b: float) -> float:
    return a / b

def sample_concat(*args: str) -> str:
    return " ".join(args)


# ════════════════════════════════════════════════════════════════════
#  __init__
# ════════════════════════════════════════════════════════════════════

class TestInit:

    def test_stores_function(self):
        gen = TestReferenceGenerator(sample_add)
        assert gen.func is sample_add
        assert gen.func_name == "sample_add"

    def test_captures_signature(self):
        gen = TestReferenceGenerator(sample_add)
        sig = str(gen.signature)
        assert "a" in sig
        assert "b" in sig


# ════════════════════════════════════════════════════════════════════
#  capture_ground_truth
# ════════════════════════════════════════════════════════════════════

class TestCaptureGroundTruth:

    def test_successful_execution(self):
        gen = TestReferenceGenerator(sample_add)
        inputs = [{"args": [2, 3], "kwargs": {}}]
        results = gen.capture_ground_truth(inputs)
        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["output"] == 5

    def test_exception_recorded(self):
        gen = TestReferenceGenerator(sample_divide)
        inputs = [{"args": [1.0, 0.0], "kwargs": {}}]
        results = gen.capture_ground_truth(inputs)
        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "error" in results[0]

    def test_empty_inputs(self):
        gen = TestReferenceGenerator(sample_add)
        results = gen.capture_ground_truth([])
        assert results == []

    def test_multiple_cases(self):
        gen = TestReferenceGenerator(sample_add)
        inputs = [
            {"args": [1, 2], "kwargs": {}},
            {"args": [0, 0], "kwargs": {}},
            {"args": [-1, 1], "kwargs": {}},
        ]
        results = gen.capture_ground_truth(inputs)
        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)
        assert results[0]["output"] == 3
        assert results[1]["output"] == 0
        assert results[2]["output"] == 0

    def test_kwargs_support(self):
        def kw_func(a, b=10):
            return a + b
        gen = TestReferenceGenerator(kw_func)
        inputs = [{"args": [5], "kwargs": {"b": 20}}]
        results = gen.capture_ground_truth(inputs)
        assert results[0]["output"] == 25

    def test_missing_args_key_defaults_to_empty(self):
        gen = TestReferenceGenerator(sample_concat)
        inputs = [{"kwargs": {}}]  # no "args" key
        results = gen.capture_ground_truth(inputs)
        assert results[0]["status"] == "success"
        assert results[0]["output"] == ""


# ════════════════════════════════════════════════════════════════════
#  save_fixture
# ════════════════════════════════════════════════════════════════════

class TestSaveFixture:

    def test_creates_file(self, tmp_path):
        gen = TestReferenceGenerator(sample_add)
        results = [{"input": {"args": [1, 2]}, "output": 3, "status": "success"}]
        path = gen.save_fixture(results, output_dir=str(tmp_path))
        assert Path(path).exists()
        assert Path(path).name == "sample_add_verification.json"

    def test_valid_json_content(self, tmp_path):
        gen = TestReferenceGenerator(sample_add)
        results = [{"input": {"args": [1, 2]}, "output": 3, "status": "success"}]
        path = gen.save_fixture(results, output_dir=str(tmp_path))
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["function"] == "sample_add"
        assert len(data["cases"]) == 1

    def test_creates_directory_if_missing(self, tmp_path):
        out = tmp_path / "sub" / "dir"
        gen = TestReferenceGenerator(sample_add)
        gen.save_fixture([], output_dir=str(out))
        assert out.exists()

    def test_empty_results(self, tmp_path):
        gen = TestReferenceGenerator(sample_add)
        path = gen.save_fixture([], output_dir=str(tmp_path))
        with open(path, "r") as f:
            data = json.load(f)
        assert data["cases"] == []


# ════════════════════════════════════════════════════════════════════
#  generate_llm_vectors
# ════════════════════════════════════════════════════════════════════

class TestGenerateLLMVectors:

    def test_returns_list(self):
        gen = TestReferenceGenerator(sample_add)
        gen.llm = MagicMock()
        gen.llm.generate_json.return_value = [
            {"args": [1, 2], "kwargs": {}},
            {"args": [0, 0], "kwargs": {}},
        ]
        vectors = gen.generate_llm_vectors(count=2)
        assert isinstance(vectors, list)
        assert len(vectors) == 2

    def test_non_list_response_returns_empty(self):
        gen = TestReferenceGenerator(sample_add)
        gen.llm = MagicMock()
        gen.llm.generate_json.return_value = "not a list"
        vectors = gen.generate_llm_vectors()
        assert vectors == []

    def test_none_response_returns_empty(self):
        gen = TestReferenceGenerator(sample_add)
        gen.llm = MagicMock()
        gen.llm.generate_json.return_value = None
        vectors = gen.generate_llm_vectors()
        assert vectors == []
