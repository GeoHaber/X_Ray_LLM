
import unittest
import ctypes
import tempfile
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Any, Dict
from Analysis.test_gen import TestGenerator

# -----------------------------------------------------------------------------
# Phase 1: The "Scan & Capture" Simulation
# -----------------------------------------------------------------------------
@dataclass
class CapturedTestProfile:
    func_name: str
    source_code: str
    test_cases: List[Dict[str, Any]] # List of {input: {...}, output: ...}

class ScanPhaseSimulator:
    def __init__(self):
        self.generator = TestGenerator()

    def analyze_and_capture(self, func_name: str, source_code: str, func_impl: callable) -> CapturedTestProfile:
        """
        Simulates X-Ray analyzing a function and generating tests FOR LATER USE.
        """
        print(f"[Scan] Analyzing '{func_name}'...")
        
        # 1. Generate Inputs
        inputs = self.generator.generate_inputs(source_code)
        print(f"       Generated {len(inputs)} input vectors.")
        
        # 2. Capture Ground Truth (Python Execution)
        # We store the inputs AND the actual Python output.
        results = self.generator.execute_and_capture(func_impl, inputs)
        
        valid_cases = [r for r in results if r["error"] is None]
        print(f"       Captured {len(valid_cases)} valid behavior traces.")
        
        return CapturedTestProfile(
            func_name=func_name,
            source_code=source_code,
            test_cases=valid_cases
        )

# -----------------------------------------------------------------------------
# Phase 2: The "Rewrite &Verify" Simulation
# -----------------------------------------------------------------------------
def mock_transpile_to_rust_v2(python_code: str) -> str:
    """Generate mock Rust code from a Python function for parity testing."""
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

class GenerativeParityHarness(unittest.TestCase):
    """Generative parity test harness."""

    def compile_rust(self, rust_code: str) -> str:
        tmp_dir = Path(tempfile.mkdtemp())
        src_file = tmp_dir / "gen.rs"
        clean_code = rust_code.replace("def ", "fn ")
        src_file.write_text(clean_code, encoding="utf-8")
        
        lib_name = "gen.dll" if sys.platform == "win32" else "libgen.so"
        out_file = tmp_dir / lib_name
        
        cmd = ["rustc", "--crate-type", "cdylib", "-O", str(src_file), "-o", str(out_file)]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(out_file)

    def test_end_to_end_flow(self):
        """
        Demonstrates the User's Workflow:
        1. Scan/Analyze -> Generate Tests -> Store Profile
        2. Transpile -> Load Profile -> Verify
        """
        
        # --- SETUP: Define Python Functions ---
        code_add = "def add(a, b): return a + b"
        def py_add(a, b): return a + b
        
        # --- STEP 1: SCAN PHASE (Generate "Golden" Data) ---
        scanner = ScanPhaseSimulator()
        
        # We "scan" the function and produce a profile.
        # This profile contains the code AND the verified I/O pairs.
        profile_add = scanner.analyze_and_capture("add", code_add, py_add)
        
        # In a real app, this `profile_add` would be saved to disk/DB.
        print(f"\n[Storage] Saved profile for '{profile_add.func_name}' with {len(profile_add.test_cases)} tests.")

        # --- STEP 2: REWRITE PHASE (Verify against Golden Data) ---
        print("\n[Rewrite] User requested conversion to Rust...")
        
        # 1. Transpile
        rust_src = mock_transpile_to_rust_v2(profile_add.source_code)
        
        # 2. Compile
        lib_path = self.compile_rust(rust_src)
        rust_lib = ctypes.CDLL(lib_path)
        
        # 3. Verify against the *Stored Profile*
        c_func = getattr(rust_lib, "add")
        c_func.argtypes = [ctypes.c_int32] * 2
        c_func.restype = ctypes.c_int32
        
        print(f"[Verify] checking Rust implementation of '{profile_add.func_name}'...")
        
        for case in profile_add.test_cases:
            inputs = case["input"]
            expected_output = case["output"]
            
            # Execute Rust
            # (Assuming order match for prototype)
            actual_output = c_func(*inputs.values())
            
            # Assert Parity
            self.assertEqual(actual_output, expected_output, 
                             f"Rust divergence! Input: {inputs}")
            
        print(f"[Success] Rust implementation matches Python behavior on all {len(profile_add.test_cases)} generated cases.")

if __name__ == "__main__":
    unittest.main()
