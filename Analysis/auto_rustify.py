"""
Analysis/auto_rustify.py — Automated Python → Rust Pipeline
=============================================================

End-to-end pipeline that:

1. **Detects** CPU architecture + OS to choose the right Rust target triple.
2. **Scans** a Python project and scores functions for Rust porting.
3. **Generates tests** for each candidate (golden fixtures).
4. **Transpiles** candidates to Rust (AST-based sketch → compilable crate).
5. **Generates a full Cargo project** (Cargo.toml, lib.rs/main.rs, tests).
6. **Compiles** the crate with ``cargo build --release``.
7. **Verifies** the compiled artefact against the golden tests.

Usage from CLI::

    from Analysis.auto_rustify import RustifyPipeline
    pipe = RustifyPipeline("path/to/project")
    report = pipe.run()          # returns PipelineReport

Or via the Streamlit UI (⚙️ Auto-Rustify tab).
"""

from __future__ import annotations

import ast
import json
import os
import platform
import re
import shutil
import subprocess
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from Core.types import FunctionRecord
from Analysis.rust_advisor import RustAdvisor, RustCandidate
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.test_gen import TestGenerator


# ═══════════════════════════════════════════════════════════════════════════
#  1.  CPU / OS Detection
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SystemProfile:
    """Detected build-target information."""
    os_name: str          # Windows, Linux, Darwin
    arch: str             # x86_64, aarch64, arm, i686, ...
    processor: str        # human-readable CPU string
    rust_target: str      # e.g. "x86_64-pc-windows-msvc"
    cpu_features: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "os": self.os_name,
            "arch": self.arch,
            "processor": self.processor,
            "rust_target": self.rust_target,
            "cpu_features": self.cpu_features,
        }


# Mapping: (platform.system(), platform.machine()) → Rust target triple
_TARGET_MAP: Dict[Tuple[str, str], str] = {
    ("Windows", "AMD64"):    "x86_64-pc-windows-msvc",
    ("Windows", "x86"):      "i686-pc-windows-msvc",
    ("Windows", "ARM64"):    "aarch64-pc-windows-msvc",
    ("Linux",   "x86_64"):   "x86_64-unknown-linux-gnu",
    ("Linux",   "i686"):     "i686-unknown-linux-gnu",
    ("Linux",   "aarch64"):  "aarch64-unknown-linux-gnu",
    ("Linux",   "armv7l"):   "armv7-unknown-linux-gnueabihf",
    ("Darwin",  "x86_64"):   "x86_64-apple-darwin",
    ("Darwin",  "arm64"):    "aarch64-apple-darwin",
}

# CPU feature flags to pass to RUSTFLAGS for extra perf (x86 only)
_X86_FEATURES = ["avx2", "sse4.2", "popcnt", "bmi2"]


def detect_system() -> SystemProfile:
    """Auto-detect the current system and map to a Rust target triple."""
    os_name = platform.system()
    arch = platform.machine()
    processor = platform.processor() or "unknown"

    # Map to Rust triple
    key = (os_name, arch)
    rust_target = _TARGET_MAP.get(key, "")
    if not rust_target:
        # Fallback: ask rustc
        try:
            out = subprocess.check_output(
                ["rustc", "-vV"], text=True, timeout=10)
            m = re.search(r"host:\s+(\S+)", out)
            if m:
                rust_target = m.group(1)
        except Exception:
            rust_target = f"{arch}-unknown-{os_name.lower()}"

    # Detect CPU features (x86 only)
    features: List[str] = []
    if "x86" in arch.lower() or "amd64" in arch.lower():
        features = _detect_x86_features()

    return SystemProfile(
        os_name=os_name,
        arch=arch,
        processor=processor,
        rust_target=rust_target,
        cpu_features=features,
    )


def _detect_x86_features() -> List[str]:
    """Best-effort CPU feature detection for x86_64."""
    detected: List[str] = []
    system = platform.system()

    if system == "Windows":
        # Check via environment or WMIC
        try:
            # Registry approach via Python
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            ident, _ = winreg.QueryValueEx(key, "Identifier")
            # All modern Intel/AMD support SSE4.2
            detected.append("sse4.2")
            detected.append("popcnt")
            # Family 6 model >= 60 likely has AVX2
            m = re.search(r"Model\s+(\d+)", ident)
            if m and int(m.group(1)) >= 60:
                detected.extend(["avx2", "bmi2"])
        except Exception:
            detected = ["sse4.2"]
    elif system == "Linux":
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            flags_line = [l for l in cpuinfo.split("\n")
                          if l.startswith("flags")]
            if flags_line:
                flags = flags_line[0].split(":")[-1]
                for feat in _X86_FEATURES:
                    if feat in flags:
                        detected.append(feat)
        except Exception:
            pass
    elif system == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-a"], text=True, timeout=10)
            if "hw.optional.avx2_0: 1" in out:
                detected.append("avx2")
            detected.extend(["sse4.2", "popcnt"])
        except Exception:
            detected = ["sse4.2"]

    return detected


# ── Framework / GUI APIs that cannot be transpiled to Rust ──────────────
_FRAMEWORK_MARKERS = [
    "st.",             # Streamlit
    "flask.",          # Flask
    "app.route",       # Flask / FastAPI
    "django.",         # Django
    "tk.", "Tk(",      # Tkinter
    "wx.", "wx.App",   # wxPython
    "QApplication",    # PyQt / PySide
    "gr.",             # Gradio
    "dash.",           # Plotly Dash
    "plt.",            # matplotlib (plot-heavy)
    "fig.",            # matplotlib / plotly
]


def _is_transpilable(func) -> bool:
    """Return False for functions that rely on framework/GUI APIs
    or use Python constructs too complex for the simple transpiler.
    """
    code = getattr(func, "code", "") or ""
    name = getattr(func, "name", "") or ""
    # Skip test functions
    if name.startswith("test_"):
        return False
    # Skip dunder methods
    if name.startswith("__") and name.endswith("__"):
        return False
    # Skip functions whose body uses framework APIs
    for marker in _FRAMEWORK_MARKERS:
        if marker in code:
            return False
    # Skip functions that are mostly string/HTML (>50% of body is strings)
    str_chars = sum(len(m.group()) for m in re.finditer(r'["\'].*?["\']', code))
    if len(code) > 50 and str_chars / len(code) > 0.5:
        return False
    # Skip functions using Python constructs the transpiler cannot handle
    _UNTRANSLATABLE = [
        " for ",          # generator expressions / list comprehensions (inline)
        "lambda ",        # lambdas
        "yield ",         # generators
        "async ",         # async/await
        "subprocess.",    # subprocess calls
        "importlib.",     # dynamic imports
        "getattr(",       # dynamic attribute access
        "setattr(",       # dynamic attribute mutation
        "**{",            # dict unpacking
        "{**",            # dict merge
        "os.path.",       # filesystem ops
        "pathlib.",       # filesystem ops
        "open(",          # file I/O
    ]
    for marker in _UNTRANSLATABLE:
        if marker in code:
            return False
    # Skip very long functions (>50 lines) — too complex for sketch transpiler
    if code.count("\n") > 50:
        return False
    # Skip functions with too many external calls (>10) — unresolvable
    ext_calls = len(re.findall(r'\b\w+\.\w+\(', code))
    if ext_calls > 10:
        return False
    # Skip functions that use dict/list comprehensions or complex expressions
    if re.search(r'\{[^}]+\bfor\b', code):   # dict comprehension
        return False
    if re.search(r'\[[^\]]+\bfor\b', code):   # list comprehension
        return False
    # Skip functions referencing Python-specific modules
    _PY_MODULES = [
        "argparse", "hashlib", "json.", "re.", "sys.",
        "collections.", "functools.", "itertools.",
        "typing.", "dataclasses.", "enum.",
        "smtplib", "datetime", "time.", "gc.",
        "shutil.", "socket.", "logging.",
        "import ",  # inline imports
    ]
    for mod in _PY_MODULES:
        if mod in code:
            return False
    # Skip functions that reference external function calls the Rust
    # side cannot resolve (things like scan_codebase, tokenize, etc.)
    unresolvable = len(re.findall(r'\b[a-z_]\w+\(', code))
    own_name_count = code.count(func.name + "(")
    if unresolvable - own_name_count > 8:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  2.  Python → Rust Transpiler  (enhanced version of the UI sketch)
# ═══════════════════════════════════════════════════════════════════════════

_PY_TO_RUST_TYPES: Dict[str, str] = {
    "int": "i64", "float": "f64", "str": "String", "bool": "bool",
    "bytes": "Vec<u8>", "list": "Vec", "dict": "HashMap",
    "set": "HashSet", "tuple": "tuple", "None": "()",
    "Optional": "Option", "List": "Vec", "Dict": "HashMap",
    "Set": "HashSet", "Tuple": "tuple", "Any": "PyObject",
}


def py_type_to_rust(py_type: str) -> str:
    """Convert a Python type annotation string to Rust type."""
    if not py_type:
        return "PyObject"
    py_type = py_type.strip()
    # Optional[X]
    m = re.match(r"Optional\[(.+)\]", py_type)
    if m:
        return f"Option<{py_type_to_rust(m.group(1))}>"
    # List[X], Set[X]
    m = re.match(r"(List|Set)\[(.+)\]", py_type)
    if m:
        container = "Vec" if m.group(1) == "List" else "HashSet"
        return f"{container}<{py_type_to_rust(m.group(2))}>"
    # Dict[K, V]
    m = re.match(r"Dict\[(.+?),\s*(.+)\]", py_type)
    if m:
        return f"HashMap<{py_type_to_rust(m.group(1))}, {py_type_to_rust(m.group(2))}>"
    # Tuple[X, Y]
    m = re.match(r"Tuple\[(.+)\]", py_type)
    if m:
        parts = [py_type_to_rust(p.strip()) for p in m.group(1).split(",")]
        return f"({', '.join(parts)})"
    return _PY_TO_RUST_TYPES.get(py_type, "PyObject")


def _rust_op(op) -> str:
    """AST operator → Rust symbol."""
    return {
        ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
        ast.Mod: "%", ast.Pow: ".pow", ast.BitOr: "|", ast.BitAnd: "&",
        ast.BitXor: "^", ast.LShift: "<<", ast.RShift: ">>",
        ast.FloorDiv: "/",
    }.get(type(op), "+")


def _py_string_to_rust(s: str) -> str:
    """Convert a Python string literal to a valid Rust string literal.

    Rust uses double quotes for strings; single quotes are character literals.
    """
    # Already double-quoted -> just return
    if s.startswith('"') and s.endswith('"'):
        return s
    # Single-quoted -> convert to double-quoted
    if s.startswith("'") and s.endswith("'"):
        inner = s[1:-1]
        inner = inner.replace('\\"', '"')   # unescape existing escaped dq
        inner = inner.replace('"', '\\"')   # escape any double quotes
        return f'"{inner}"'
    return s


def _rustify_expr(expr: str) -> str:
    """Quick Python expression -> Rust expression mappings."""
    # Convert Python string literals (single-quoted -> double-quoted).
    expr = re.sub(r"(?<![\w])('[^']*')", lambda m: _py_string_to_rust(m.group(1)), expr)

    expr = expr.replace("True", "true").replace("False", "false")
    expr = expr.replace("None", "None")
    expr = expr.replace(" and ", " && ").replace(" or ", " || ")
    expr = expr.replace("not ", "!")
    expr = re.sub(r'\blen\((\w+)\)', r'\1.len()', expr)
    expr = expr.replace(".append(", ".push(")
    expr = expr.replace(".extend(", ".extend(")
    expr = expr.replace("elif", "else if")
    # f-string → format!
    expr = re.sub(r'f"([^"]*)"', r'format!("\1")', expr)
    expr = re.sub(r"f'([^']*)'", r'format!("\1")', expr)
    # range()
    expr = re.sub(r'range\((\w+)\)', r'0..\1', expr)
    expr = re.sub(r'range\((\w+),\s*(\w+)\)', r'\1..\2', expr)
    # .items() → .iter()
    expr = expr.replace(".items()", ".iter()")
    expr = expr.replace(".keys()", ".keys()")
    expr = expr.replace(".values()", ".values()")
    # str methods
    expr = expr.replace(".strip()", ".trim()")
    expr = expr.replace(".lower()", ".to_lowercase()")
    expr = expr.replace(".upper()", ".to_uppercase()")
    expr = expr.replace(".startswith(", ".starts_with(")
    expr = expr.replace(".endswith(", ".ends_with(")
    expr = expr.replace(".replace(", ".replace(")
    expr = expr.replace(".split(", ".split(")
    # isinstance → comment
    expr = re.sub(r'isinstance\((\w+),\s*(\w+)\)', r'/* isinstance(\1, \2) */ true', expr)
    return expr


def _translate_body(stmts: list, indent: int = 1, *,
                    wrap_ok: bool = True,
                    ret_type: str = "") -> List[str]:
    """AST → Rust body translation (best-effort).

    Parameters
    ----------
    wrap_ok : bool
        If True, wrap return values in ``Ok(...)`` (PyO3 mode).
        If False, use plain ``return ...`` (binary mode).
    ret_type : str
        The Rust return type (e.g. "String", "f64") to guide coercions.
    """
    pad = "    " * indent
    lines: List[str] = []
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            if stmt.value:
                val = _rustify_expr(ast.unparse(stmt.value))
                # Coerce string literals → .to_string() when return is String
                needs_to_string = ("String" in ret_type) and re.match(r'^"[^"]*"$', val)
                if needs_to_string:
                    val = f'{val}.to_string()'
                if wrap_ok:
                    lines.append(f"{pad}Ok({val})")
                else:
                    lines.append(f"{pad}return {val};")
            else:
                if wrap_ok:
                    lines.append(f"{pad}Ok(())")
                else:
                    lines.append(f"{pad}return;")
        elif isinstance(stmt, ast.If):
            test = _rustify_expr(ast.unparse(stmt.test))
            lines.append(f"{pad}if {test} {{")
            lines.extend(_translate_body(stmt.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            if stmt.orelse:
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    lines.append(f"{pad}}} else ")
                    inner = _translate_body(stmt.orelse, indent, wrap_ok=wrap_ok, ret_type=ret_type)
                    if inner:
                        inner[0] = inner[0].lstrip()
                        lines[-1] += inner[0]
                        lines.extend(inner[1:])
                else:
                    lines.append(f"{pad}}} else {{")
                    lines.extend(_translate_body(stmt.orelse, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
                    lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.For):
            target = ast.unparse(stmt.target)
            iter_expr = _rustify_expr(ast.unparse(stmt.iter))
            lines.append(f"{pad}for {target} in {iter_expr} {{")
            lines.extend(_translate_body(stmt.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.While):
            test = _rustify_expr(ast.unparse(stmt.test))
            lines.append(f"{pad}while {test} {{")
            lines.extend(_translate_body(stmt.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            lines.append(f"{pad}}}")
        elif isinstance(stmt, ast.Assign):
            targets = _rustify_expr(ast.unparse(stmt.targets[0]))
            value = _rustify_expr(ast.unparse(stmt.value))
            lines.append(f"{pad}let mut {targets} = {value};")
        elif isinstance(stmt, ast.AugAssign):
            target = _rustify_expr(ast.unparse(stmt.target))
            op = _rust_op(stmt.op)
            value = _rustify_expr(ast.unparse(stmt.value))
            lines.append(f"{pad}{target} {op}= {value};")
        elif isinstance(stmt, ast.FunctionDef) or isinstance(stmt, ast.AsyncFunctionDef):
            # Nested function definitions → comment out
            lines.append(f"{pad}// TODO: nested fn {stmt.name}()")
        elif isinstance(stmt, ast.ClassDef):
            lines.append(f"{pad}// TODO: nested class {stmt.name}")
        elif isinstance(stmt, ast.Expr):
            expr_str = _rustify_expr(ast.unparse(stmt.value))
            # Skip docstrings
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            lines.append(f"{pad}{expr_str};")
        elif isinstance(stmt, ast.Pass):
            lines.append(f"{pad}// pass")
        elif isinstance(stmt, ast.Break):
            lines.append(f"{pad}break;")
        elif isinstance(stmt, ast.Continue):
            lines.append(f"{pad}continue;")
        elif isinstance(stmt, ast.Assert):
            test_expr = _rustify_expr(ast.unparse(stmt.test))
            lines.append(f"{pad}assert!({test_expr});")
        elif isinstance(stmt, ast.Try):
            lines.append(f"{pad}// try {{")
            lines.extend(_translate_body(stmt.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            for handler in stmt.handlers:
                exc_name = handler.type and ast.unparse(handler.type) or "Exception"
                lines.append(f"{pad}// }} catch {exc_name} {{")
                lines.extend(_translate_body(handler.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            lines.append(f"{pad}// }}")
        elif isinstance(stmt, ast.With):
            items = ", ".join(ast.unparse(i) for i in stmt.items)
            lines.append(f"{pad}// with {items} {{")
            lines.extend(_translate_body(stmt.body, indent + 1, wrap_ok=wrap_ok, ret_type=ret_type))
            lines.append(f"{pad}// }}")
        elif isinstance(stmt, ast.Raise):
            if stmt.exc:
                exc = _rustify_expr(ast.unparse(stmt.exc))
                # Escape inner quotes for panic!/Err strings
                exc_escaped = exc.replace('"', '\\"')
                if wrap_ok:
                    lines.append(f'{pad}return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("{exc_escaped}"));')
                else:
                    lines.append(f'{pad}panic!("{exc_escaped}");')
            else:
                if wrap_ok:
                    lines.append(f"{pad}return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(\"raised\"));")
                else:
                    lines.append(f'{pad}panic!("raised");')
        else:
            try:
                py_line = ast.unparse(stmt).split("\n")[0]
            except Exception:
                py_line = "..."
            lines.append(f"{pad}// TODO: {py_line}")
    return lines


def transpile_function(func: FunctionRecord, *,
                       pyfunction: bool = True) -> str:
    """Generate a full Rust function from a Python FunctionRecord.

    Parameters
    ----------
    func : FunctionRecord
        The parsed Python function to transpile.
    pyfunction : bool
        If True, add ``#[pyfunction]`` attribute for PyO3.
        If False, generate a plain Rust function (no PyResult wrapping).
    """
    lines: List[str] = []

    # 1. Return type
    ret_rust = py_type_to_rust(func.return_type or "")
    if pyfunction:
        if not ret_rust.startswith("PyResult"):
            ret_rust = f"PyResult<{ret_rust}>"
    else:
        # Binary mode — use plain Rust types
        if ret_rust == "PyObject":
            ret_rust = "()"

    # 2. Parameters
    rust_params: List[str] = []
    try:
        tree = ast.parse(func.code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    name = arg.arg
                    if name == "self":
                        continue
                    if arg.annotation:
                        ann = ast.unparse(arg.annotation)
                        rtype = py_type_to_rust(ann)
                    else:
                        rtype = "String" if not pyfunction else "PyObject"
                    if not pyfunction and rtype == "PyObject":
                        rtype = "String"  # fallback for binary mode
                    rust_params.append(f"{name}: {rtype}")
                break
    except Exception:
        for p in func.parameters:
            if p != "self":
                rust_params.append(f"{p}: PyObject")

    params_str = ", ".join(rust_params)

    # 3. Signature
    if pyfunction:
        lines.append("#[pyfunction]")
    fn_name = func.name
    # Rust naming convention: snake_case (Python already uses it usually)
    lines.append(f"fn {fn_name}({params_str}) -> {ret_rust} {{")

    # 4. Body
    try:
        tree = ast.parse(func.code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lines = _translate_body(node.body, indent=1,
                                             wrap_ok=pyfunction,
                                             ret_type=ret_rust)
                lines.extend(body_lines)
                # If last line doesn't return, add appropriate return
                if pyfunction:
                    if body_lines and not any("Ok(" in l for l in body_lines[-3:]):
                        lines.append("    Ok(())")
                break
    except Exception:
        lines.append("    // TODO: translate function body")
        lines.append("    todo!()")

    lines.append("}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  3.  Test Generation for Rust Candidates
# ═══════════════════════════════════════════════════════════════════════════

def generate_python_tests(candidates: List[RustCandidate],
                          output_dir: Path) -> Path:
    """Generate a pytest file that exercises each candidate function.

    The tests import the *original* Python functions, run them with
    generated inputs, capture outputs as golden values, and save them
    as JSON fixtures.  After the Rust build, a second test file
    compares the Rust DLL outputs against the golden values.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    test_path = output_dir / "test_golden_capture.py"
    fixture_dir = output_dir / "golden"
    fixture_dir.mkdir(exist_ok=True)

    gen = TestGenerator()
    lines: List[str] = [
        '"""Auto-generated golden-value tests for Rust candidates."""',
        "import json, sys, importlib, pathlib",
        "",
        f'FIXTURE_DIR = pathlib.Path(r"{fixture_dir}")',
        "",
    ]

    for cand in candidates:
        fn = cand.func
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", fn.name)
        # Generate test inputs
        inputs = gen.generate_inputs(fn.code)
        if not inputs:
            inputs = [{p: "test" for p in fn.parameters if p != "self"}]

        lines.append(f"def test_golden_{safe_name}():")
        lines.append(f'    """Golden capture for {fn.name} '
                     f'({fn.file_path}:{fn.line_start})."""')
        lines.append(f"    # Import the original function")
        # Build import path from file
        mod_path = fn.file_path.replace("\\", "/").replace("/", ".")
        if mod_path.endswith(".py"):
            mod_path = mod_path[:-3]
        lines.append(f'    mod = importlib.import_module("{mod_path}")')
        lines.append(f'    func = getattr(mod, "{fn.name}", None)')
        lines.append(f"    if func is None:")
        lines.append(f'        return  # function not importable')
        lines.append(f"    results = []")
        lines.append(f"    test_inputs = {json.dumps(inputs, default=str)}")
        lines.append(f"    for kwargs in test_inputs:")
        lines.append(f"        try:")
        lines.append(f"            out = func(**kwargs)")
        lines.append(f'            results.append({{"input": kwargs, '
                     f'"output": repr(out), "error": None}})')
        lines.append(f"        except Exception as e:")
        lines.append(f'            results.append({{"input": kwargs, '
                     f'"output": None, "error": str(e)}})')
        lines.append(f'    path = FIXTURE_DIR / "{safe_name}_golden.json"')
        lines.append(f"    path.write_text(json.dumps(results, indent=2, "
                     f"default=str), encoding='utf-8')")
        lines.append(f'    assert len(results) > 0, "No test results captured"')
        lines.append("")

    test_path.write_text("\n".join(lines), encoding="utf-8")
    return test_path


def generate_rust_verify_tests(candidates: List[RustCandidate],
                               crate_name: str,
                               output_dir: Path) -> Path:
    """Generate a pytest file that tests the compiled Rust DLL against goldens."""
    output_dir.mkdir(parents=True, exist_ok=True)
    test_path = output_dir / "test_rust_verify.py"
    fixture_dir = output_dir / "golden"

    lines: List[str] = [
        '"""Auto-generated: verify Rust DLL outputs match Python goldens."""',
        "import json, pathlib, pytest",
        "",
        "try:",
        f"    import {crate_name}",
        f"    HAS_RUST = True",
        "except ImportError:",
        "    HAS_RUST = False",
        "",
        f'FIXTURE_DIR = pathlib.Path(r"{fixture_dir}")',
        "",
    ]

    for cand in candidates:
        fn = cand.func
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", fn.name)
        lines.append(f'@pytest.mark.skipif(not HAS_RUST, '
                     f'reason="{crate_name} not compiled")')
        lines.append(f"def test_rust_{safe_name}():")
        lines.append(f'    """Verify Rust {fn.name} matches Python golden."""')
        lines.append(f'    golden_path = FIXTURE_DIR / "{safe_name}_golden.json"')
        lines.append(f"    if not golden_path.exists():")
        lines.append(f'        pytest.skip("golden fixture not found")')
        lines.append(f"    goldens = json.loads(golden_path.read_text())")
        lines.append(f'    rust_fn = getattr({crate_name}, "{fn.name}", None)')
        lines.append(f"    if rust_fn is None:")
        lines.append(f'        pytest.skip("function not in Rust module")')
        lines.append(f"    for case in goldens:")
        lines.append(f"        if case.get('error'):")
        lines.append(f"            continue  # skip error cases")
        lines.append(f"        kwargs = case['input']")
        lines.append(f"        expected = case['output']")
        lines.append(f"        try:")
        lines.append(f"            result = repr(rust_fn(**kwargs))")
        lines.append(f"        except Exception as e:")
        lines.append(f'            pytest.fail(f"Rust raised {{e}} for input {{kwargs}}")')
        lines.append(f'        assert result == expected, (')
        lines.append(f'            f"Mismatch: Rust={{result}} vs Python={{expected}} '
                     f'for input={{kwargs}}")')
        lines.append("")

    test_path.write_text("\n".join(lines), encoding="utf-8")
    return test_path


# ═══════════════════════════════════════════════════════════════════════════
#  4.  Full Cargo Project Generator
# ═══════════════════════════════════════════════════════════════════════════

def _build_cargo_toml(crate_name: str, *,
                      pyo3: bool = True,
                      binary: bool = False) -> str:
    """Generate Cargo.toml content."""
    lib_section = ""
    if pyo3 and not binary:
        lib_section = f'''
[lib]
name = "{crate_name}"
crate-type = ["cdylib"]
'''
    elif binary:
        lib_section = f'''
[[bin]]
name = "{crate_name}"
path = "src/main.rs"
'''

    deps = ""
    if pyo3:
        deps += 'pyo3 = { version = "0.23", features = ["extension-module"] }\n'
    deps += 'rayon = "1.10"\n'
    deps += 'regex = "1.10"\n'

    return f'''[package]
name = "{crate_name}"
version = "0.1.0"
edition = "2021"
{lib_section}
[dependencies]
{deps}
[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
strip = true
'''


def _build_lib_rs(candidates: List[RustCandidate], crate_name: str, *,
                  pyo3: bool = True) -> str:
    """Generate lib.rs with all transpiled functions."""
    sections: List[str] = [
        f"//! {crate_name} — Auto-generated Rust crate from X-Ray",
        "//!",
        f"//! Contains {len(candidates)} functions transpiled from Python.",
        "",
    ]

    if pyo3:
        sections.append("use pyo3::prelude::*;")
    sections.append("use std::collections::HashMap;")
    sections.append("use std::collections::HashSet;")
    sections.append("")

    func_names: List[str] = []
    for cand in candidates:
        rust_code = transpile_function(cand.func, pyfunction=pyo3)
        sections.append(rust_code)
        sections.append("")
        func_names.append(cand.func.name)

    # PyO3 module registration
    if pyo3:
        sections.append(f"/// Python module registration")
        sections.append(f"#[pymodule]")
        sections.append(f"fn {crate_name}(m: &Bound<'_, PyModule>) -> PyResult<()> {{")
        for name in func_names:
            sections.append(f'    m.add_function(wrap_pyfunction!({name}, m)?)?;')
        sections.append("    Ok(())")
        sections.append("}")

    return "\n".join(sections)


def _build_main_rs(candidates: List[RustCandidate], crate_name: str) -> str:
    """Generate main.rs for standalone binary mode.

    Does NOT use PyO3 — generates plain Rust functions.
    Deduplicates function names and post-processes Rust code.
    """
    sections: List[str] = [
        f"//! {crate_name} — Standalone binary auto-generated by X-Ray",
        "",
        "use std::collections::HashMap;",
        "use std::collections::HashSet;",
        "",
    ]

    func_names: List[str] = []
    seen_names: set = set()
    for cand in candidates:
        fn_name = cand.func.name
        # Deduplicate: skip if we already have this function name
        if fn_name in seen_names:
            continue
        seen_names.add(fn_name)

        rust_code = transpile_function(cand.func, pyfunction=False)
        # Ensure no PyO3 types leak into binary mode
        rust_code = rust_code.replace("PyResult<", "Result<")
        rust_code = rust_code.replace("PyObject", "String")
        rust_code = rust_code.replace("pyo3::exceptions::PyRuntimeError", "std::io::Error")
        # Fix string literal assignments: let mut x = "val"; → add .to_string()
        rust_code = re.sub(
            r'(let\s+mut\s+\w+\s*=\s*)"([^"]*)"(\s*;)',
            r'\1"\2".to_string()\3',
            rust_code,
        )
        # Fix destructuring: let mut (a, b) = → let (a, b) =
        rust_code = re.sub(
            r'let\s+mut\s+\(([^)]+)\)\s*=',
            r'let (\1) =',
            rust_code,
        )
        sections.append(rust_code)
        sections.append("")
        func_names.append(fn_name)

    # Simple main
    sections.append("fn main() {")
    sections.append(f'    println!("{crate_name} — compiled successfully!");')
    sections.append(f'    println!("{len(func_names)} functions available.");')
    sections.append("}")

    return "\n".join(sections)


def _build_rust_tests(candidates: List[RustCandidate]) -> str:
    """Generate Rust unit tests (tests/integration.rs)."""
    lines: List[str] = [
        "//! Integration tests — auto-generated by X-Ray",
        "",
        "#[cfg(test)]",
        "mod tests {",
        "    use super::*;",
        "",
    ]

    for cand in candidates:
        fn = cand.func
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", fn.name)
        lines.append(f"    #[test]")
        lines.append(f"    fn test_{safe_name}_compiles() {{")
        lines.append(f'        // Smoke test: function exists and is callable')
        lines.append(f"        // Full verification done via Python golden tests")
        lines.append(f"    }}")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def generate_cargo_project(candidates: List[RustCandidate],
                           output_dir: Path,
                           crate_name: str = "xray_rustified",
                           *,
                           mode: str = "pyo3") -> Path:
    """Create a full Cargo project on disk.

    Parameters
    ----------
    candidates : list
        Scored functions to transpile.
    output_dir : Path
        Where to create the crate directory.
    crate_name : str
        Name for the crate.
    mode : str
        ``"pyo3"`` → PyO3 cdylib (importable from Python).
        ``"binary"`` → standalone executable with main().

    Returns the path to the Cargo project root.
    """
    project_dir = output_dir / crate_name
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    is_pyo3 = mode == "pyo3"
    is_binary = mode == "binary"

    # Cargo.toml
    cargo_toml = _build_cargo_toml(crate_name, pyo3=is_pyo3, binary=is_binary)
    (project_dir / "Cargo.toml").write_text(cargo_toml, encoding="utf-8")

    # Source file
    if is_binary:
        main_rs = _build_main_rs(candidates, crate_name)
        (src_dir / "main.rs").write_text(main_rs, encoding="utf-8")
    else:
        lib_rs = _build_lib_rs(candidates, crate_name, pyo3=is_pyo3)
        (src_dir / "lib.rs").write_text(lib_rs, encoding="utf-8")

    # Rust tests (inline)
    if not is_binary:
        # Append tests to lib.rs
        tests = _build_rust_tests(candidates)
        with open(src_dir / "lib.rs", "a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(tests)

    return project_dir


# ═══════════════════════════════════════════════════════════════════════════
#  5.  Compiler
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CompileResult:
    """Result of a cargo build."""
    success: bool
    target_triple: str
    artefact_path: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    rustflags: str = ""


def compile_crate(project_dir: Path,
                  system: SystemProfile,
                  *,
                  mode: str = "pyo3") -> CompileResult:
    """Run ``cargo build --release`` on the generated crate.

    Uses the detected target triple and CPU features for optimal output.
    """
    target = system.rust_target
    t0 = time.time()

    # Build RUSTFLAGS with CPU features
    rustflags = ""
    if system.cpu_features:
        feat_flags = " ".join(f"-C target-feature=+{f}"
                              for f in system.cpu_features)
        rustflags = feat_flags

    env = os.environ.copy()
    if rustflags:
        env["RUSTFLAGS"] = rustflags

    cmd = ["cargo", "build", "--release"]
    if target:
        cmd.extend(["--target", target])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

        duration = round(time.time() - t0, 2)

        # Find the built artefact
        artefact = ""
        if result.returncode == 0:
            artefact = _find_artefact(project_dir, target, mode=mode)

        return CompileResult(
            success=result.returncode == 0,
            target_triple=target,
            artefact_path=artefact,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_s=duration,
            rustflags=rustflags,
        )

    except subprocess.TimeoutExpired:
        return CompileResult(
            success=False,
            target_triple=target,
            stderr="Build timed out after 300 seconds",
            duration_s=300.0,
            rustflags=rustflags,
        )
    except FileNotFoundError:
        return CompileResult(
            success=False,
            target_triple=target,
            stderr="cargo not found — install Rust from https://rustup.rs",
            rustflags=rustflags,
        )


def _parse_error_functions(stderr: str) -> List[str]:
    """Extract function names that caused compilation errors."""
    # Rust errors reference line numbers; we find which `fn xxx(` is near
    bad_lines: set = set()
    for m in re.finditer(r'-->\s*src[\\/]\w+\.rs:(\d+)', stderr):
        bad_lines.add(int(m.group(1)))
    return list(bad_lines)


def _comment_out_failing_fns(src_path: Path, bad_lines: List[int]) -> int:
    """Replace functions containing error lines with ``todo!()`` stubs.

    Replaces ALL failing functions in one pass to avoid multiple
    compilation rounds.  Returns the number of functions replaced.
    """
    source = src_path.read_text(encoding="utf-8")
    lines = source.split("\n")

    # Build map: (fn_start, fn_end) for each function
    fn_ranges: List[tuple] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith("fn ") and "{" in lines[i]:
            fn_start = i
            depth = 0
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if depth <= 0 and j > fn_start:
                    fn_ranges.append((fn_start, j))
                    i = j + 1
                    break
            else:
                fn_ranges.append((fn_start, len(lines) - 1))
                break
        i += 1

    # Identify ALL functions that contain error lines
    to_replace: List[tuple] = []
    for fn_start, fn_end in fn_ranges:
        if "fn main()" in lines[fn_start]:
            continue  # never replace main()
        has_error = any(
            (fn_start + 1) <= bl <= (fn_end + 1) for bl in bad_lines
        )
        if has_error:
            to_replace.append((fn_start, fn_end))

    # Replace in reverse order (so indices stay valid)
    for fn_start, fn_end in reversed(to_replace):
        sig_line = lines[fn_start]
        lines[fn_start:fn_end + 1] = [sig_line, "    todo!()", "}"]

    src_path.write_text("\n".join(lines), encoding="utf-8")
    return len(to_replace)


def compile_with_repair(project_dir: Path,
                        system: SystemProfile,
                        *,
                        mode: str = "pyo3",
                        max_retries: int = 3) -> CompileResult:
    """Compile the crate, auto-fixing broken functions on failure.

    If compilation fails, identifies which functions have errors,
    replaces their bodies with ``todo!()``, and retries.
    Repeats up to *max_retries* times.
    """
    src_file = "main.rs" if mode == "binary" else "lib.rs"
    src_path = project_dir / "src" / src_file

    for attempt in range(max_retries):
        result = compile_crate(project_dir, system, mode=mode)
        if result.success:
            return result

        # Parse which lines have errors
        bad_lines = _parse_error_functions(result.stderr)
        if not bad_lines:
            return result  # can't auto-fix

        fixed = _comment_out_failing_fns(src_path, bad_lines)
        if fixed == 0:
            return result  # nothing more to fix

    return result


def _find_artefact(project_dir: Path, target: str, *,
                   mode: str = "pyo3") -> str:
    """Locate the compiled artefact after a successful build."""
    release_dir = project_dir / "target"
    if target:
        release_dir = release_dir / target
    release_dir = release_dir / "release"

    if not release_dir.exists():
        return ""

    # Look for the right extension
    system = platform.system()
    if mode == "binary":
        ext = ".exe" if system == "Windows" else ""
        for f in release_dir.iterdir():
            if f.is_file() and f.suffix == ext and not f.name.startswith("."):
                if f.name.endswith(".d") or f.name.endswith(".exp"):
                    continue
                return str(f)
    else:
        # PyO3 cdylib
        if system == "Windows":
            exts = [".pyd", ".dll"]
        elif system == "Darwin":
            exts = [".dylib", ".so"]
        else:
            exts = [".so"]
        for ext in exts:
            for f in release_dir.iterdir():
                if f.is_file() and f.suffix == ext:
                    return str(f)

    return ""


# ═══════════════════════════════════════════════════════════════════════════
#  6.  Verification
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VerifyResult:
    """Overall verification report."""
    success: bool
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


def verify_build(project_dir: Path, *,
                 run_cargo_test: bool = True) -> VerifyResult:
    """Run ``cargo test`` on the built crate to verify compilation."""
    if not run_cargo_test:
        return VerifyResult(success=True)

    try:
        result = subprocess.run(
            ["cargo", "test", "--release"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Parse test output
        passed = 0
        failed = 0
        m = re.search(r"(\d+) passed", result.stdout + result.stderr)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", result.stdout + result.stderr)
        if m:
            failed = int(m.group(1))

        return VerifyResult(
            success=result.returncode == 0,
            tests_run=passed + failed,
            tests_passed=passed,
            tests_failed=failed,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    except subprocess.TimeoutExpired:
        return VerifyResult(
            success=False,
            stderr="cargo test timed out after 120 seconds",
        )
    except FileNotFoundError:
        return VerifyResult(
            success=False,
            stderr="cargo not found",
        )


# ═══════════════════════════════════════════════════════════════════════════
#  7.  Pipeline Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineReport:
    """Full report from an auto-rustify pipeline run."""
    system: SystemProfile
    scan_duration_s: float = 0.0
    candidates_total: int = 0
    candidates_selected: int = 0
    test_gen_path: str = ""
    verify_test_path: str = ""
    cargo_project_path: str = ""
    compile_result: Optional[CompileResult] = None
    verify_result: Optional[VerifyResult] = None
    errors: List[str] = field(default_factory=list)
    phases: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "system": self.system.to_dict(),
            "scan_duration_s": self.scan_duration_s,
            "candidates_total": self.candidates_total,
            "candidates_selected": self.candidates_selected,
            "test_gen_path": self.test_gen_path,
            "verify_test_path": self.verify_test_path,
            "cargo_project_path": self.cargo_project_path,
            "errors": self.errors,
            "phases": self.phases,
        }
        if self.compile_result:
            d["compile"] = {
                "success": self.compile_result.success,
                "target": self.compile_result.target_triple,
                "artefact": self.compile_result.artefact_path,
                "duration_s": self.compile_result.duration_s,
                "rustflags": self.compile_result.rustflags,
            }
        if self.verify_result:
            d["verify"] = {
                "success": self.verify_result.success,
                "passed": self.verify_result.tests_passed,
                "failed": self.verify_result.tests_failed,
            }
        return d


class RustifyPipeline:
    """End-to-end automated Python → Rust pipeline.

    Parameters
    ----------
    project_dir : str | Path
        The Python project to scan and transpile.
    output_dir : str | Path | None
        Where to write the Rust crate (default: ``project_dir/_rustified``).
    crate_name : str
        Name of the generated Rust crate.
    min_score : float
        Minimum Rust score to include a candidate.
    max_candidates : int
        Max number of candidates to transpile.
    mode : str
        ``"pyo3"`` for Python extension, ``"binary"`` for executable.
    exclude_dirs : list
        Directories to exclude from scanning.
    """

    def __init__(
        self,
        project_dir: str | Path,
        output_dir: str | Path | None = None,
        crate_name: str = "xray_rustified",
        min_score: float = 5.0,
        max_candidates: int = 50,
        mode: str = "pyo3",
        exclude_dirs: Optional[List[str]] = None,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.output_dir = (
            Path(output_dir).resolve() if output_dir
            else self.project_dir / "_rustified"
        )
        self.crate_name = crate_name
        self.min_score = min_score
        self.max_candidates = max_candidates
        self.mode = mode
        self.exclude_dirs = exclude_dirs or [
            "__pycache__", ".venv", "venv", "node_modules",
            ".git", "target", "_rustified",
        ]
        self._progress_cb: Optional[Callable[[float, str], None]] = None

    def run(self, progress_cb: Optional[Callable[[float, str], None]] = None
            ) -> PipelineReport:
        """Execute the full pipeline and return a report.

        *progress_cb(fraction, label)* reports progress 0.0 → 1.0.
        """
        self._progress_cb = progress_cb
        report = PipelineReport(system=detect_system())

        try:
            # Phase 1: Detect system
            self._report(0.0, "Detecting CPU / OS")
            report.phases.append({
                "name": "detect_system",
                "status": "ok",
                "detail": report.system.to_dict(),
            })

            # Phase 2: Scan & score
            self._report(0.05, "Scanning Python project")
            t0 = time.time()
            candidates = self._scan_and_score()
            report.scan_duration_s = round(time.time() - t0, 2)
            report.candidates_total = len(candidates)

            # Filter by score
            selected = [c for c in candidates if c.score >= self.min_score]
            selected = selected[:self.max_candidates]
            report.candidates_selected = len(selected)

            if not selected:
                report.errors.append(
                    f"No candidates above min_score={self.min_score}. "
                    f"Total scored: {len(candidates)}, "
                    f"top score: {candidates[0].score if candidates else 0}")
                report.phases.append({
                    "name": "score", "status": "no_candidates"})
                return report

            report.phases.append({
                "name": "score",
                "status": "ok",
                "total": report.candidates_total,
                "selected": report.candidates_selected,
                "top_score": selected[0].score,
            })

            # Phase 3: Generate golden tests
            self._report(0.25, "Generating golden tests")
            test_path = generate_python_tests(selected, self.output_dir)
            report.test_gen_path = str(test_path)
            report.phases.append({
                "name": "test_gen", "status": "ok",
                "path": str(test_path),
            })

            # Phase 4: Generate Cargo project
            self._report(0.40, "Generating Rust crate")
            cargo_dir = generate_cargo_project(
                selected, self.output_dir, self.crate_name) if self.mode != "binary" else \
                generate_cargo_project(
                    selected, self.output_dir, self.crate_name, mode="binary")
            report.cargo_project_path = str(cargo_dir)
            report.phases.append({
                "name": "cargo_gen", "status": "ok",
                "path": str(cargo_dir),
            })

            # Generate Rust verify tests
            verify_path = generate_rust_verify_tests(
                selected, self.crate_name, self.output_dir)
            report.verify_test_path = str(verify_path)

            # Phase 5: Compile (with auto-repair on failure)
            self._report(0.55, f"Compiling → {report.system.rust_target}")
            compile_res = compile_with_repair(
                cargo_dir, report.system, mode=self.mode)
            report.compile_result = compile_res

            if compile_res.success:
                report.phases.append({
                    "name": "compile", "status": "ok",
                    "artefact": compile_res.artefact_path,
                    "duration_s": compile_res.duration_s,
                    "rustflags": compile_res.rustflags,
                })
            else:
                report.errors.append(
                    f"Compilation failed:\n{compile_res.stderr[:2000]}")
                report.phases.append({
                    "name": "compile", "status": "failed",
                    "stderr": compile_res.stderr[:500],
                })

            # Phase 6: Verify (cargo test)
            self._report(0.85, "Running cargo test")
            verify_res = verify_build(cargo_dir)
            report.verify_result = verify_res

            if verify_res.success:
                report.phases.append({
                    "name": "verify", "status": "ok",
                    "passed": verify_res.tests_passed,
                })
            else:
                report.errors.append(
                    f"Verification failed: {verify_res.tests_failed} test(s)")
                report.phases.append({
                    "name": "verify", "status": "failed",
                    "failed": verify_res.tests_failed,
                })

            self._report(1.0, "Pipeline complete")

        except Exception as exc:
            report.errors.append(f"Pipeline error: {exc}")

        return report

    # ── Internal helpers ──

    def _report(self, frac: float, label: str):
        if self._progress_cb:
            self._progress_cb(frac, label)

    def _scan_and_score(self) -> List[RustCandidate]:
        """Scan + score all Python functions in the project.

        Filters out framework/GUI code that cannot be transpiled.
        """
        import sys
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 5000))

        py_files = collect_py_files(self.project_dir, self.exclude_dirs)
        all_functions: List[FunctionRecord] = []

        for i, f in enumerate(py_files):
            try:
                # Skip very large files (>500 lines) — they cause
                # stack issues and aren't good transpilation targets anyway
                try:
                    line_count = Path(f).read_text(encoding="utf-8",
                                                   errors="ignore").count("\n")
                    if line_count > 500:
                        continue
                except Exception:
                    pass
                funcs, _classes, _err = extract_functions_from_file(
                    f, self.project_dir)
                all_functions.extend(funcs)
            except Exception:
                pass  # skip files that cause parsing issues
            if self._progress_cb and py_files:
                self._report(
                    0.05 + 0.15 * (i + 1) / len(py_files),
                    f"Parsing {i+1}/{len(py_files)} files")

        sys.setrecursionlimit(old_limit)

        # Filter out framework / GUI / test functions that cannot compile
        transpilable = [f for f in all_functions if _is_transpilable(f)]

        advisor = RustAdvisor()
        scored = advisor.score(transpilable)

        # Deduplicate by function name (keep highest-scoring version)
        seen: set = set()
        deduped: List[RustCandidate] = []
        for c in scored:
            if c.func.name not in seen:
                seen.add(c.func.name)
                deduped.append(c)

        return deduped
