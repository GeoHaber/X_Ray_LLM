
import unittest
import ctypes
import tempfile
import subprocess
import sys
from pathlib import Path
from Analysis.test_gen import TestGenerator

# Re-use the mock transpiler from Phase 5 (in a real scenario, we'd import it)
def mock_transpile_to_rust_v2(python_code: str) -> str:
    """Generate mock Rust code from a Python function for transpilation testing."""
    # Slightly more advanced mock that handles 'add' and 'multiply'
    if "def add(a, b):" in python_code:
        return r"""
        #[no_mangle]
        pub extern "C" def add(a: i32, b: i32) -> i32 {
            a + b
        }
        """
    if "def multiply(x, y):" in python_code:
        return r"""
        #[no_mangle]
        pub extern "C" def multiply(x: i32, y: i32) -> i32 {
            x * y
        }
        """
    raise NotImplementedError("Transpiler only supports 'add' and 'multiply'.")

class GenerativeTranspilationHarness(unittest.TestCase):
    """Generative transpilation test harness."""

    def setUp(self):
        self.generator = TestGenerator()

    def compile_rust(self, rust_code: str) -> str:
        # duplicated logic for standalone harness
        tmp_dir = Path(tempfile.mkdtemp())
        src_file = tmp_dir / "gen.rs"
        clean_code = rust_code.replace("def ", "fn ")
        src_file.write_text(clean_code, encoding="utf-8")
        
        lib_name = "gen.dll" if sys.platform == "win32" else "libgen.so"
        out_file = tmp_dir / lib_name
        
        cmd = ["rustc", "--crate-type", "cdylib", "-O", str(src_file), "-o", str(out_file)]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(out_file)

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
        lib_path = self.compile_rust(rust_src)
        rust_lib = ctypes.CDLL(lib_path)
        
        # Configure ctypes (assuming i32 for this prototype)
        c_func = getattr(rust_lib, func_name)
        c_func.argtypes = [ctypes.c_int32] * 2 # Mock assumes 2 args
        c_func.restype = ctypes.c_int32
        
        # 4. Parity Run (Rust)
        for i, case in enumerate(py_results):
            args = case["input"]
            expected = case["output"]
            
            # Unpack args assuming order matches (a, b) / (x, y)
            # In a real system, we'd map arg names to positions
            arg_values = list(args.values())
            
            actual = c_func(*arg_values)
            
            print(f"  Case {i+1}: Input={args} | Python={expected} | Rust={actual}")
            
            # 5. Verify
            self.assertEqual(expected, actual, f"Mismatch on input {args}")

    def test_generative_add(self):
        code = "def add(a, b): return a + b"
        def add(a, b): return a + b
        self.verify_function(code, "add", add)

    def test_generative_multiply(self):
        code = "def multiply(x, y): return x * y"
        def multiply(x, y): return x * y
        self.verify_function(code, "multiply", multiply)

if __name__ == "__main__":
    unittest.main()
