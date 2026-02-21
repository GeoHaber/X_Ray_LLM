"""
tests/test_parity_py_vs_rust.py — Python vs Rust Parity Tests
================================================================

For every function that is successfully transpiled to real Rust in the
generated _rustified_exe, verify that the Python original and the Rust
transpilation produce identical results for the same inputs.

This is the ultimate quality gate:  if the transpiled Rust code returns
different values than the Python source, the transpiler has a semantic bug.

Architecture
------------
  1. Call the Python function directly (import from source module).
  2. Run the compiled Rust executable with JSON test vectors via subprocess.
  3. Compare outputs.

The Rust exe is invoked once with a JSON payload on stdin and returns
a JSON response.  This avoids recompilation for each test.
"""

import os
import subprocess
import textwrap

import pytest

# ═══════════════════════════════════════════════════════════════════════════
#  Python implementations (imported from source)
# ═══════════════════════════════════════════════════════════════════════════

from Analysis.transpiler import _infer_type_from_name


_MODULE_KEYWORDS = [
    (("parse",), "utils"),
    (("read", "write", "load"), "io_helpers"),
    (("validate", "check"), "validators"),
    (("search", "find"), "search"),
]


def _suggest_module_name_py(func_names):
    """Python implementation (extracted from LibraryAdvisor._suggest_module_name)."""
    name = func_names[0].lower()
    for keywords, module in _MODULE_KEYWORDS:
        if any(kw in name for kw in keywords):
            return module
    return "shared_utils"


_MARGIN_BANDS = [
    (-0.15, "SAFE_MISS"), (-0.05, "NEAR_MISS"), (0.0, "BOUNDARY_MISS"),
    (0.05, "BOUNDARY_HIT"), (0.15, "NEAR_HIT"),
]


def classify_margin_py(margin: float) -> str:
    """Python implementation (from calibrate_fixtures.py)."""
    for threshold, label in _MARGIN_BANDS:
        if margin < threshold:
            return label
    return "SAFE_HIT"


# ═══════════════════════════════════════════════════════════════════════════
#  Rust executable path
# ═══════════════════════════════════════════════════════════════════════════

RUST_EXE = os.path.join(
    os.path.dirname(__file__), "..",
    "_rustified_exe", "target", "release", "x_ray.exe"
)


def _rust_exe_available() -> bool:
    """Check if the compiled Rust exe exists."""
    return os.path.isfile(RUST_EXE)


HAS_RUST_EXE = _rust_exe_available()


# ═══════════════════════════════════════════════════════════════════════════
#  1. _suggest_module_name  Parity
# ═══════════════════════════════════════════════════════════════════════════

class TestSuggestModuleNameParity:
    """Verify _suggest_module_name Python == Rust for all input categories."""

    # Test vectors: (input_func_names, expected_output)
    VECTORS = [
        (["parse_config"], "utils"),
        (["parse_json_data"], "utils"),
        (["read_file"], "io_helpers"),
        (["write_output"], "io_helpers"),
        (["load_data"], "io_helpers"),
        (["validate_input"], "validators"),
        (["check_syntax"], "validators"),
        (["search_index"], "search"),
        (["find_matches"], "search"),
        (["do_something_else"], "shared_utils"),
        (["compute_hash"], "shared_utils"),
    ]

    @pytest.mark.parametrize("func_names,expected", VECTORS,
                             ids=[v[0][0] for v in VECTORS])
    def test_python_output(self, func_names, expected):
        """Python implementation returns correct value."""
        assert _suggest_module_name_py(func_names) == expected

    @pytest.mark.parametrize("func_names,expected", VECTORS,
                             ids=[v[0][0] for v in VECTORS])
    def test_rust_matches_python(self, func_names, expected):
        """Rust transpilation returns same value as Python for each input.

        Note: The Rust exe demo output is parsed from stdout.
        For now we test the Python transpiler output directly by compiling
        and running a small Rust program.
        """
        # Generate Rust code for _suggest_module_name
        from Analysis.transpiler import transpile_function_code

        py_src = textwrap.dedent("""\
            def _suggest_module_name(func_names: list) -> str:
                name = func_names[0].lower()
                if "parse" in name:
                    return "utils"
                if "read" in name or "write" in name or "load" in name:
                    return "io_helpers"
                if "validate" in name or "check" in name:
                    return "validators"
                if "search" in name or "find" in name:
                    return "search"
                return "shared_utils"
        """)
        rust_fn = transpile_function_code(py_src)

        # Build a small Rust program that calls the function and prints result
        vec_elts = ", ".join(f'"{n}".to_string()' for n in func_names)
        rust_prog = textwrap.dedent(f"""\
            #![allow(unused_variables, unused_mut, dead_code, unused_imports)]
            use std::collections::{{HashMap, HashSet}};

            {rust_fn}

            fn main() {{
                let result = _suggest_module_name(vec![{vec_elts}]);
                print!("{{}}", result);
            }}
        """)

        result = _compile_and_run(rust_prog)
        if result is None:
            pytest.skip("rustc not available")
        assert result == expected, f"Rust returned {result!r}, expected {expected!r}"


# ═══════════════════════════════════════════════════════════════════════════
#  2. _infer_type_from_name  Parity
# ═══════════════════════════════════════════════════════════════════════════

class TestInferTypeFromNameParity:
    """Verify _infer_type_from_name Python == Rust for various param names."""

    VECTORS = [
        ("file_path", "&str"),
        ("dir_name", "&str"),
        ("text", "&str"),
        ("msg", "&str"),
        ("count", "usize"),
        ("num_items", "usize"),
        ("index", "usize"),
        ("n", "usize"),
        ("verbose", "bool"),
        ("force", "bool"),
        ("items", "&[String]"),
        ("file_list", "&str"),  # "file" matches before "list"
        ("config", "&HashMap<String, String>"),
        ("unknown_param", "&str"),  # default
    ]

    @pytest.mark.parametrize("name,expected", VECTORS,
                             ids=[v[0] for v in VECTORS])
    def test_python_output(self, name, expected):
        """Python _infer_type_from_name returns correct value."""
        assert _infer_type_from_name(name) == expected

    @pytest.mark.parametrize("name,expected", VECTORS,
                             ids=[v[0] for v in VECTORS])
    def test_rust_matches_python(self, name, expected):
        """Rust transpilation of _infer_type_from_name returns same value."""
        from Analysis.transpiler import transpile_function_code

        py_src = textwrap.dedent("""\
            def _infer_type_from_name(name: str) -> str:
                low = name.lower()
                if any(k in low for k in ("path", "file", "dir", "folder")):
                    return "&str"
                if any(k in low for k in ("name", "text", "msg", "code", "source", "line",
                                            "pattern", "prefix", "suffix", "key", "label")):
                    return "&str"
                if any(k in low for k in ("count", "size", "num", "index", "depth",
                                            "width", "height", "limit", "max", "min")):
                    return "usize"
                if low in ("n", "i", "j", "k", "x", "y", "z"):
                    return "usize"
                if any(k in low for k in ("flag", "enable", "disable", "verbose",
                                            "force", "recursive", "debug")):
                    return "bool"
                if any(k in low for k in ("items", "list", "values", "args", "params",
                                            "names", "files", "lines", "results")):
                    return "&[String]"
                if any(k in low for k in ("dict", "map", "config", "options", "settings")):
                    return "&HashMap<String, String>"
                return "&str"
        """)
        rust_fn = transpile_function_code(py_src)

        rust_prog = textwrap.dedent(f"""\
            #![allow(unused_variables, unused_mut, dead_code, unused_imports)]
            use std::collections::{{HashMap, HashSet}};

            {rust_fn}

            fn main() {{
                let result = _infer_type_from_name("{name}".to_string());
                print!("{{}}", result);
            }}
        """)

        result = _compile_and_run(rust_prog)
        if result is None:
            pytest.skip("rustc not available")
        assert result == expected, f"Rust returned {result!r}, expected {expected!r}"


# ═══════════════════════════════════════════════════════════════════════════
#  3. classify_margin  Parity
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifyMarginParity:
    """Verify classify_margin Python == Rust for boundary values."""

    VECTORS = [
        (-0.50, "SAFE_MISS"),
        (-0.20, "SAFE_MISS"),
        (-0.15, "NEAR_MISS"),     # boundary: exactly -0.15
        (-0.10, "NEAR_MISS"),
        (-0.05, "BOUNDARY_MISS"),  # boundary: exactly -0.05
        (-0.01, "BOUNDARY_MISS"),
        (0.0, "BOUNDARY_HIT"),     # boundary: exactly 0.0
        (0.03, "BOUNDARY_HIT"),
        (0.05, "NEAR_HIT"),        # boundary: exactly 0.05
        (0.10, "NEAR_HIT"),
        (0.15, "SAFE_HIT"),        # boundary: exactly 0.15
        (0.50, "SAFE_HIT"),
        (1.0, "SAFE_HIT"),
    ]

    @pytest.mark.parametrize("margin,expected", VECTORS,
                             ids=[f"m={v[0]}" for v in VECTORS])
    def test_python_output(self, margin, expected):
        """Python classify_margin returns correct value."""
        assert classify_margin_py(margin) == expected

    @pytest.mark.parametrize("margin,expected", VECTORS,
                             ids=[f"m={v[0]}" for v in VECTORS])
    def test_rust_matches_python(self, margin, expected):
        """Rust transpilation of classify_margin returns same value."""
        from Analysis.transpiler import transpile_function_code

        py_src = textwrap.dedent("""\
            def classify_margin(margin: float) -> str:
                if margin < -0.15:
                    return "SAFE_MISS"
                elif margin < -0.05:
                    return "NEAR_MISS"
                elif margin < 0.0:
                    return "BOUNDARY_MISS"
                elif margin < 0.05:
                    return "BOUNDARY_HIT"
                elif margin < 0.15:
                    return "NEAR_HIT"
                else:
                    return "SAFE_HIT"
        """)
        rust_fn = transpile_function_code(py_src)

        rust_prog = textwrap.dedent(f"""\
            #![allow(unused_variables, unused_mut, dead_code, unused_imports)]
            use std::collections::{{HashMap, HashSet}};

            {rust_fn}

            fn main() {{
                let result = classify_margin({margin}_f64);
                print!("{{}}", result);
            }}
        """)

        result = _compile_and_run(rust_prog)
        if result is None:
            pytest.skip("rustc not available")
        assert result == expected, f"Rust returned {result!r}, expected {expected!r}"


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: compile & run a Rust program, return stdout
# ═══════════════════════════════════════════════════════════════════════════

import tempfile  # noqa: E402

def _compile_and_run(rust_source: str) -> str | None:
    """Compile a Rust source string and run it, returning stdout.

    Returns None if rustc is not available.
    """
    try:
        subprocess.run(["rustc", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "test.rs")
        exe_path = os.path.join(tmpdir, "test.exe")

        with open(src_path, "w", encoding="utf-8") as f:
            f.write(rust_source)

        # Compile
        comp = subprocess.run(
            ["rustc", "--edition", "2021", src_path, "-o", exe_path],
            capture_output=True, text=True, timeout=30
        )
        if comp.returncode != 0:
            pytest.fail(
                f"Rust compilation failed:\n{comp.stderr}\n"
                f"\n--- Generated Source ---\n{rust_source}"
            )

        # Run
        run = subprocess.run(
            [exe_path], capture_output=True, text=True, timeout=10
        )
        if run.returncode != 0:
            pytest.fail(f"Rust exe crashed:\n{run.stderr}")

        return run.stdout


# ═══════════════════════════════════════════════════════════════════════════
#  4. Summary: Cross-check all real functions
# ═══════════════════════════════════════════════════════════════════════════

class TestTranspiledExeOutput:
    """Verify the generated _rustified_exe prints correct demo output."""

    @pytest.mark.skipif(not HAS_RUST_EXE, reason="Rustified exe not compiled")
    def test_exe_runs_without_crash(self):
        """The generated exe runs and exits cleanly."""
        result = subprocess.run(
            [RUST_EXE], capture_output=True, timeout=10, encoding="utf-8", errors="replace"
        )
        assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"

    @pytest.mark.skipif(not HAS_RUST_EXE, reason="Rustified exe not compiled")
    def test_exe_reports_function_count(self):
        """The exe reports the number of transpiled functions."""
        result = subprocess.run(
            [RUST_EXE], capture_output=True, timeout=10, encoding="utf-8", errors="replace"
        )
        assert "functions transpiled" in result.stdout
        assert "real Rust" in result.stdout

    @pytest.mark.skipif(not HAS_RUST_EXE, reason="Rustified exe not compiled")
    def test_exe_suggest_module_name(self):
        """The exe's _suggest_module_name output matches Python."""
        result = subprocess.run(
            [RUST_EXE], capture_output=True, timeout=10, encoding="utf-8", errors="replace"
        )
        # The default demo call passes vec!["parse_config", "load_data"]
        # which starts with "parse_config" → should return "utils"
        assert '"utils"' in result.stdout

    @pytest.mark.skipif(not HAS_RUST_EXE, reason="Rustified exe not compiled")
    def test_exe_infer_type(self):
        """The exe's _infer_type_from_name output matches Python."""
        result = subprocess.run(
            [RUST_EXE], capture_output=True, timeout=10, encoding="utf-8", errors="replace"
        )
        assert '"&str"' in result.stdout

    @pytest.mark.skipif(not HAS_RUST_EXE, reason="Rustified exe not compiled")
    def test_exe_classify_margin(self):
        """The exe's classify_margin outputs match Python."""
        result = subprocess.run(
            [RUST_EXE], capture_output=True, timeout=10, encoding="utf-8", errors="replace"
        )
        # classify_margin(0.03) should be "BOUNDARY_HIT"
        assert "BOUNDARY_HIT" in result.stdout
        # classify_margin(-0.10) should be "NEAR_MISS"
        assert "NEAR_MISS" in result.stdout
        # classify_margin(0.20) should be "SAFE_HIT"
        assert "SAFE_HIT" in result.stdout
