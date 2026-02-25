
import unittest
import subprocess
import time
import ctypes

from tests.harness_common import compile_rust as _compile_rust_common

# -----------------------------------------------------------------------------
# Mock Transpiler (Placeholder until we have the real AI/Rule-based engine)
# -----------------------------------------------------------------------------
def mock_transpile_to_rust(python_code: str) -> str:
    """
    Simulates converting a Python function to Rust.
    For the prototype, we just detect strict patterns and return hardcoded Rust.
    """
    if "def fib(n):" in python_code:
        return r"""
        #[no_mangle]
        pub extern "C" def fib(n: i32) -> i32 {
            if n <= 1 { return n; }
            fib(n - 1) + fib(n - 2)
        }
        """
    if "def add(a, b):" in python_code:
        return r"""
        #[no_mangle]
        pub extern "C" def add(a: i32, b: i32) -> i32 {
            a + b
        }
        """
    raise NotImplementedError("Transpiler only supports 'fib' and 'add' for now.")

class RustTranspilationHarness(unittest.TestCase):
    """
    Verifies that Python functions can be rewritten in Rust, compiled, 
    and produce identical results.
    """
    
    def compile_rust(self, rust_code: str, func_name: str) -> str:
        """
        Compiles Rust code to a shared library (.dll/.so) using rustc.
        Returns path to the compiled library.
        """
        try:
            return _compile_rust_common(rust_code)
        except subprocess.CalledProcessError as e:
            self.fail(f"Rust compilation failed: {e}")
        except FileNotFoundError:
            self.skipTest("rustc not found in PATH. Install Rust to run this test.")

    def load_rust_lib(self, lib_path: str):
        """Loads the compiled shared library."""
        return ctypes.CDLL(lib_path)

    def test_fibonacci_correctness(self):
        """Golden Test: Verify Fibonacci(10) correctness."""
        
        # 1. Define Source
        py_code = """
        def fib(n):
            if n <= 1: return n
            return fib(n-1) + fib(n-2)
        """
        
        # 2. Transpile
        rust_source = mock_transpile_to_rust(py_code)
        
        # 3. Compile
        lib_path = self.compile_rust(rust_source, "fib")
        
        # 4. Load & Execute
        rust_lib = self.load_rust_lib(lib_path)
        
        # Verify specific case
        # Rust: fib(10) -> 55
        # Define argument types for ctypes
        rust_lib.fib.argtypes = [ctypes.c_int32]
        rust_lib.fib.restype = ctypes.c_int32
        
        result_rust = rust_lib.fib(10)
        
        # 5. Assert against Python baseline
        def py_fib(n):
            if n <= 1:
                return n
            return py_fib(n-1) + py_fib(n-2)
            
        result_py = py_fib(10)
        
        print(f"\n[Golden] Fib(10): Python={result_py}, Rust={result_rust}")
        self.assertEqual(result_rust, result_py)

    def test_performance_gain(self):
        """Performance Test: Rust should be faster."""
        # Setup as above
        py_code = "def fib(n): ..." 
        rust_source = mock_transpile_to_rust(py_code)
        lib_path = self.compile_rust(rust_source, "fib")
        rust_lib = self.load_rust_lib(lib_path)
        rust_lib.fib.argtypes = [ctypes.c_int32]
        rust_lib.fib.restype = ctypes.c_int32
        
        # Benchmark Python
        def py_fib(n):
            if n <= 1:
                return n
            return py_fib(n-1) + py_fib(n-2)
            
        n = 30 # High enough to take time
        
        start = time.time()
        py_fib(n)
        py_time = time.time() - start
        
        start = time.time()
        rust_lib.fib(n)
        rust_time = time.time() - start
        
        print(f"\n[Bench] Fib({n}): Python={py_time:.4f}s, Rust={rust_time:.4f}s")
        print(f"Speedup: {py_time / rust_time:.1f}x")
        
        self.assertLess(rust_time, py_time * 0.5, "Rust was not 2x faster!")

if __name__ == "__main__":
    unittest.main()
