"""Shared utilities for generative transpilation test harnesses.

Eliminates duplicate mock_transpile_to_rust_v2 and compile_rust between
harness_generative.py and harness_generative_parity.py.
"""

import subprocess
import sys
import tempfile
from pathlib import Path


def mock_transpile_to_rust_v2(python_code: str) -> str:
    """Generate mock Rust code from a Python function for transpilation testing."""
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


def compile_rust(rust_code: str) -> str:
    """Compile Rust code to a shared library and return the output path."""
    tmp_dir = Path(tempfile.mkdtemp())
    src_file = tmp_dir / "gen.rs"
    clean_code = rust_code.replace("def ", "fn ")
    src_file.write_text(clean_code, encoding="utf-8")

    lib_name = "gen.dll" if sys.platform == "win32" else "libgen.so"
    out_file = tmp_dir / lib_name

    cmd = ["rustc", "--crate-type", "cdylib", "-O", str(src_file), "-o", str(out_file)]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(out_file)
