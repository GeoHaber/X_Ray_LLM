
import unittest
import ctypes
import json
import sys
from pathlib import Path
from typing import List

# Import X-Ray components
from Analysis.test_gen import TestGenerator
from Analysis.similarity import tokenize as py_tokenize

class DogfoodHarness(unittest.TestCase):
    """Self-scan dogfood test harness."""

    @classmethod
    def setUpClass(cls):
        """Compile the Rust project once."""
        cls.project_root = Path(__file__).parent.parent / "X_Ray_Rust"
        if not cls.project_root.exists():
            raise FileNotFoundError(f"Rust project not found at {cls.project_root}")
            
        # print(f"\n[Build] Compiling X_Ray_Rust in {cls.project_root}...")
        # try:
        #     subprocess.check_call(
        #         ["cargo", "build", "--release"], 
        #         cwd=str(cls.project_root),
        #         stdout=subprocess.DEVNULL,
        #         stderr=subprocess.DEVNULL
        #     )
        # except subprocess.CalledProcessError:
        #     raise RuntimeError("Cargo build failed!")

        # Locate the artifact
        target_dir = cls.project_root / "target" / "release"
        if sys.platform == "win32":
            cls.lib_path = target_dir / "x_ray_rust.dll"
        else:
            cls.lib_path = target_dir / "libx_ray_rust.so"
            
        if not cls.lib_path.exists():
            raise FileNotFoundError(f"Compiled library not found at {cls.lib_path}")
            
        print(f"[Link] Loading library: {cls.lib_path}")
        cls.rust_lib = ctypes.CDLL(str(cls.lib_path))
        
        # Setup FFI
        cls.rust_lib.tokenize.argtypes = [ctypes.c_char_p]
        cls.rust_lib.tokenize.restype = ctypes.c_void_p # Returns pointer to string
        
        cls.rust_lib.free_string.argtypes = [ctypes.c_void_p]
        cls.rust_lib.free_string.restype = None

    def call_rust_tokenize(self, text: str) -> List[str]:
        """Wrapper to call Rust FFI and parse JSON result."""
        b_text = text.encode("utf-8")
        ptr = self.rust_lib.tokenize(b_text)
        
        if not ptr:
            return []
            
        # Read C-string
        try:
            c_str = ctypes.cast(ptr, ctypes.c_char_p)
            json_str = c_str.value.decode("utf-8")
        finally:
            # Free memory allocated by Rust
            self.rust_lib.free_string(ptr)
            
        return json.loads(json_str)

    def test_tokenize_parity(self):
        """Generative verification of tokenize()."""
        generator = TestGenerator()
        
        # 1. Generate Inputs
        # Since TestGenerator uses heuristics, let's also manually add some Tricky Cases
        inputs = generator.generate_inputs("def tokenize(text): pass")
        
        # Add tricky strings relevant for tokenization
        inputs.append({"text": "CamelCaseIdentifier"})
        inputs.append({"text": "snake_case_vars"})
        inputs.append({"text": "HTMLParser"})
        inputs.append({"text": "def __init__(self):"})
        inputs.append({"text": ""})  # Empty
        inputs.append({"text": "   "}) # Whitespace
        
        print(f"\n[Dogfood] Testing 'tokenize' with {len(inputs)} inputs...")
        
        for i, case in enumerate(inputs):
            text = case.get("text")
            if not isinstance(text, str): 
                continue # Skip non-string garbage from generator
                
            # 2. Run Python
            py_res = py_tokenize(text)
            
            # 3. Run Rust
            rust_res = self.call_rust_tokenize(text)
            
            print(f"  Case {i}: '{text}'")
            print(f"     Py: {py_res}")
            print(f"     Rs: {rust_res}")
            
            # 4. Verify
            # Note: Order might differ slightly depending on regex engine differences,
            # so we might verify sets if lists fail, but strict parity expects list match.
            self.assertEqual(py_res, rust_res, f"Mismatch for input: {repr(text)}")

if __name__ == "__main__":
    unittest.main()
