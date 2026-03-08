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

        # Heuristic: Generate basic types
        # Real implementation would use type hints or LLM inference

        test_cases = []

        # Heuristic: Check for string-like arguments
        # In a real scanner, we'd check type hints. Here we act on variable names or defaults.

        # Strategy A: Generate Strings for likely string args
        str_args = [a for a in args if a in ("text", "code", "name", "s")]
        num_args = [a for a in args if a not in str_args]

        if str_args:
            # Case 1: Base Strings
            test_cases.append(
                {**{a: "basic_test" for a in str_args}, **{a: 10 for a in num_args}}
            )
            # Case 2: Empty Strings
            test_cases.append({**{a: "" for a in str_args}, **{a: 0 for a in num_args}})
            # Case 3: Mixed Case
            test_cases.append(
                {**{a: "CamelCase" for a in str_args}, **{a: 1 for a in num_args}}
            )
        else:
            # Fallback to Integers (original logic)
            # Case 1: All Zeros/Empty
            test_cases.append({arg: 0 for arg in args})

            # Case 2: Positive Integers
            test_cases.append({arg: random.randint(1, 100) for arg in args})

            # Case 3: Negative Integers
            test_cases.append({arg: random.randint(-100, -1) for arg in args})

            # Case 4: Edge boundaries (simulating limits)
            test_cases.append({arg: 1 for arg in args})

        return test_cases

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
