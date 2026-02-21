import unittest
import ctypes
from Analysis.test_gen import TestGenerator
from tests.harness_common import mock_transpile_to_rust_v2, compile_rust


class GenerativeTranspilationHarness(unittest.TestCase):
    """Generative transpilation test harness."""

    def setUp(self):
        self.generator = TestGenerator()

    def verify_function(self, py_source: str, func_name: str, py_func: callable):
        """Verify transpiled Rust code compiles and produces correct output."""
        print(f"\n[Generative] Testing '{func_name}'...")

        # 1. Generate Inputs
        inputs = self.generator.generate_inputs(py_source)
        print(f"  Generated {len(inputs)} test cases: {inputs}")

        # 2. Baseline Run (Python)
        py_results = self.generator.execute_and_capture(py_func, inputs)

        # 3. Transpile & Compile
        rust_src = mock_transpile_to_rust_v2(py_source)
        lib_path = compile_rust(rust_src)
        rust_lib = ctypes.CDLL(lib_path)

        # Configure ctypes (assuming i32 for this prototype)
        c_func = getattr(rust_lib, func_name)
        c_func.argtypes = [ctypes.c_int32] * 2  # Mock assumes 2 args
        c_func.restype = ctypes.c_int32

        # 4. Parity Run (Rust)
        for i, case in enumerate(py_results):
            args = case["input"]
            expected = case["output"]

            # Unpack args assuming order matches (a, b) / (x, y)
            # In a real system, we'd map arg names to positions
            arg_values = list(args.values())

            actual = c_func(*arg_values)

            print(f"  Case {i + 1}: Input={args} | Python={expected} | Rust={actual}")

            # 5. Verify
            self.assertEqual(expected, actual, f"Mismatch on input {args}")

    def test_generative_add(self):
        code = "def add(a, b): return a + b"

        def add(a, b):
            return a + b

        self.verify_function(code, "add", add)

    def test_generative_multiply(self):
        code = "def multiply(x, y): return x * y"

        def multiply(x, y):
            return x * y

        self.verify_function(code, "multiply", multiply)


if __name__ == "__main__":
    unittest.main()
