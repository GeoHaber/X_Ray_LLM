import ast
import json
import random
import inspect
from pathlib import Path
from typing import List, Any, Dict, Callable, Optional


class TestGenerator:
    """
    Analyzes function signatures and generates test inputs.
    """

    def generate_inputs(self, func_code: str) -> List[Dict[str, Any]]:
        """
        Parses function code and generates a list of argument dictionaries.
        """
        try:
            tree = ast.parse(func_code)
            func_node = next(
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            )
        except Exception:
            return []  # Can't parse

        args = [a.arg for a in func_node.args.args if a.arg != "self"]
        str_args = [a for a in args if a in ("text", "code", "name", "s")]
        num_args = [a for a in args if a not in str_args]

        if str_args:
            return self._generate_string_cases(str_args, num_args)
        return self._generate_numeric_cases(args)

    # -- helpers for generate_inputs ----------------------------------------

    @staticmethod
    def _generate_string_cases(str_args: list, num_args: list) -> List[Dict[str, Any]]:
        """Generate test cases for string-like arguments."""
        return [
            {**{a: "basic_test" for a in str_args}, **{a: 10 for a in num_args}},
            {**{a: "" for a in str_args}, **{a: 0 for a in num_args}},
            {**{a: "CamelCase" for a in str_args}, **{a: 1 for a in num_args}},
        ]

    @staticmethod
    def _generate_numeric_cases(args: list) -> List[Dict[str, Any]]:
        """Generate test cases for numeric arguments."""
        return [
            {arg: 0 for arg in args},
            {arg: random.randint(1, 100) for arg in args},  # nosec B311
            {arg: random.randint(-100, -1) for arg in args},  # nosec B311
            {arg: 1 for arg in args},
        ]

    def execute_and_capture(
        self, func: Callable, inputs: List[Dict[str, Any]]
    ) -> List[Any]:
        """
        Runs the function with inputs and captures results.
        """
        results = []
        for kwargs in inputs:
            try:
                res = func(**kwargs)
                results.append({"input": kwargs, "output": res, "error": None})
            except Exception as e:
                results.append({"input": kwargs, "output": None, "error": str(e)})
        return results


class TestReferenceGenerator:
    """
    Higher-level test reference generator that wraps a callable,
    captures ground-truth execution results, and saves fixtures.
    """

    __test__ = False  # Not a pytest test class

    def __init__(self, func: Callable):
        self.func = func
        self.func_name = func.__name__
        self.signature = inspect.signature(func)
        self.llm: Optional[Any] = None

    def capture_ground_truth(
        self, inputs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute *func* with each input spec and record outputs.

        Each item in *inputs* should have ``args`` (list) and/or
        ``kwargs`` (dict).  Returns a list of result dicts with keys
        ``input``, ``output``, ``status``, and optionally ``error``.
        """
        results: List[Dict[str, Any]] = []
        for spec in inputs:
            args = spec.get("args", [])
            kwargs = spec.get("kwargs", {})
            try:
                output = self.func(*args, **kwargs)
                results.append({"input": spec, "output": output, "status": "success"})
            except Exception as exc:
                results.append(
                    {
                        "input": spec,
                        "output": None,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return results

    def save_fixture(self, results: List[Dict[str, Any]], *, output_dir: str) -> str:
        """
        Persist *results* as a JSON fixture file under *output_dir*.

        Returns the path to the written file.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{self.func_name}_verification.json"
        payload = {
            "function": self.func_name,
            "signature": str(self.signature),
            "cases": results,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)

    def generate_llm_vectors(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        Ask the attached LLM to propose *count* diverse input vectors.

        Returns ``[]`` when the LLM is unavailable or returns a
        non-list response.
        """
        if self.llm is None:
            return []
        try:
            response = self.llm.generate_json(
                f"Generate {count} diverse test-input dicts (keys: args, kwargs) "
                f"for the function: {self.func_name}{self.signature}"
            )
            if isinstance(response, list):
                return response
            return []
        except Exception:
            return []
