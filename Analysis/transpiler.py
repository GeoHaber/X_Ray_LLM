"""
Analysis/transpiler.py — AST-Based Python → Rust Transpiler
=============================================================

A proper transpiler using Python's ``ast`` module for perfect parsing.
No regex guessing — every node is structurally understood.

Architecture
------------
X_Ray.exe (Rust)                    transpiler.py (Python)
  ├─ scans codebase                   ├─ receives function code via stdin/args
  ├─ scores candidates                ├─ ast.parse() → perfect AST
  ├─ calls transpiler.py ────────────►├─ walks AST nodes
  ├─ collects .rs output  ◄──────────├─ emits clean Rust
  └─ cargo build                      └─ guaranteed balanced braces

Usage
-----
CLI::

    python -m Analysis.transpiler --file some_module.py
    python -m Analysis.transpiler --code "def add(a: int, b: int) -> int: return a + b"
    python -m Analysis.transpiler --json candidates.json --out _rustified_exe/src/main.rs

As library::

    from Analysis.transpiler import transpile_function_code, transpile_module
    rust_code = transpile_function_code("def add(a, b): return a + b")
"""

from __future__ import annotations

import ast
import json
import logging
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("X_RAY_Claude")


# ═══════════════════════════════════════════════════════════════════════════
#  Type Mapping
# ═══════════════════════════════════════════════════════════════════════════

_PY_TO_RUST: Dict[str, str] = {
    "int": "i64", "float": "f64", "str": "String", "bool": "bool",
    "bytes": "Vec<u8>", "None": "()", "NoneType": "()",
    "list": "Vec<String>", "dict": "HashMap<String, String>",
    "set": "HashSet<String>", "tuple": "()",
    "Any": "String", "object": "String",
    "Path": "String", "pathlib.Path": "String",
}


def py_type_to_rust(py_type: str) -> str:
    """Convert a Python type annotation string to a Rust type string."""
    if not py_type or py_type.strip() == "":
        return "String"
    py_type = py_type.strip()

    # Optional[X]
    m = re.match(r"Optional\[(.+)\]", py_type)
    if m:
        inner = py_type_to_rust(m.group(1))
        return f"Option<{inner}>"

    # List[X]
    m = re.match(r"(?:List|list)\[(.+)\]", py_type)
    if m:
        return f"Vec<{py_type_to_rust(m.group(1))}>"

    # Set[X]
    m = re.match(r"(?:Set|set)\[(.+)\]", py_type)
    if m:
        return f"HashSet<{py_type_to_rust(m.group(1))}>"

    # Dict[K, V]
    m = re.match(r"(?:Dict|dict)\[(.+?),\s*(.+)\]", py_type)
    if m:
        k = py_type_to_rust(m.group(1))
        v = py_type_to_rust(m.group(2))
        return f"HashMap<{k}, {v}>"

    # Tuple[X, Y, ...]
    m = re.match(r"(?:Tuple|tuple)\[(.+)\]", py_type)
    if m:
        parts = [py_type_to_rust(p.strip()) for p in m.group(1).split(",")]
        return f"({', '.join(parts)})"

    # Union[X, Y] — just use the first type
    m = re.match(r"Union\[(.+)\]", py_type)
    if m:
        first = m.group(1).split(",")[0].strip()
        return py_type_to_rust(first)

    return _PY_TO_RUST.get(py_type, "String")


# ═══════════════════════════════════════════════════════════════════════════
#  AST Operator Mapping
# ═══════════════════════════════════════════════════════════════════════════

_OP_MAP = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.Mod: "%", ast.Pow: "pow", ast.BitOr: "|", ast.BitAnd: "&",
    ast.BitXor: "^", ast.LShift: "<<", ast.RShift: ">>",
    ast.FloorDiv: "/",
}

_CMP_MAP = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=", ast.Is: "==", ast.IsNot: "!=",
    ast.In: ".contains", ast.NotIn: ".contains",
}

_UNARY_MAP = {
    ast.UAdd: "+", ast.USub: "-", ast.Not: "!", ast.Invert: "~",
}

# Rust reserved words needing r# prefix or renaming
_RUST_RESERVED = {
    "type", "match", "ref", "mod", "fn", "use", "impl", "struct",
    "enum", "trait", "pub", "crate", "super", "move", "mut",
    "loop", "where", "async", "await", "dyn", "abstract", "become",
    "box", "do", "final", "macro", "override", "priv", "typeof",
    "unsized", "virtual", "yield",
}

# Words that cannot use r# prefix at all — must be renamed
_RUST_SPECIAL_RENAME = {
    "self": "this",
    "cls": "this",
    "Self": "This",
}


def _safe_name(name: str) -> str:
    """Make a Python identifier safe for Rust."""
    if name in _RUST_SPECIAL_RENAME:
        return _RUST_SPECIAL_RENAME[name]
    if name in _RUST_RESERVED:
        return f"r#{name}"
    return name


# ═══════════════════════════════════════════════════════════════════════════
#  Expression Transpilation  (ast node → Rust string)
# ═══════════════════════════════════════════════════════════════════════════

# Module-level context: set of parameter names known to be float-typed
_FLOAT_PARAMS: set = set()

def _expr(node: ast.expr) -> str:
    """Recursively convert a Python AST expression to a Rust expression string."""

    if node is None:
        return "()".strip()

    # ── Literals ──────────────────────────────────────────────────────
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            s = repr(v)
            if "." not in s and "e" not in s and "E" not in s:
                s += ".0"
            return s
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            # Protect bare { } from Rust format macro interpretation
            escaped = escaped.replace("{", "{{").replace("}", "}}")
            # Convert Python %-style format specifiers to Rust {} placeholders
            escaped = re.sub(r"%[sd]", "{}", escaped)
            escaped = re.sub(r"%-?\d*\.?\d*[sfde]", "{}", escaped)
            return f'"{escaped}"'
        if isinstance(v, bytes):
            return f'b"{v.decode("utf-8", errors="replace")}"'
        if v is None:
            return "None"
        return repr(v)

    # ── Name ──────────────────────────────────────────────────────────
    if isinstance(node, ast.Name):
        name = node.id
        if name == "True":
            return "true"
        if name == "False":
            return "false"
        if name == "None":
            return "None"
        return _safe_name(name)

    # ── Attribute  (obj.attr) ─────────────────────────────────────────
    if isinstance(node, ast.Attribute):
        obj = _expr(node.value)
        attr = node.attr
        # Python → Rust method renames
        renames = {
            "append": "push", "strip": "trim",
            "lstrip": "trim_start", "rstrip": "trim_end",
            "lower": "to_lowercase", "upper": "to_uppercase",
            "startswith": "starts_with", "endswith": "ends_with",
            "items": "iter", "keys": "keys", "values": "values",
            "extend": "extend", "replace": "replace", "split": "split",
            "join": "join", "format": "format", "count": "matches",
            "find": "find", "index": "find",
            "isdigit": "chars().all(|c| c.is_ascii_digit())",
            "isalpha": "chars().all(|c| c.is_alphabetic())",
        }
        rust_attr = renames.get(attr, attr)
        # self.x → self.x (keep for struct methods)
        return f"{obj}.{rust_attr}"

    # ── BinOp ─────────────────────────────────────────────────────────
    if isinstance(node, ast.BinOp):
        left = _expr(node.left)
        right = _expr(node.right)
        if isinstance(node.op, ast.Pow):
            return f"{left}.pow({right} as u32)"
        if isinstance(node.op, ast.FloorDiv):
            return f"({left} / {right})"
        op = _OP_MAP.get(type(node.op), "+")
        return f"({left} {op} {right})"

    # ── UnaryOp ───────────────────────────────────────────────────────
    if isinstance(node, ast.UnaryOp):
        operand = _expr(node.operand)
        op = _UNARY_MAP.get(type(node.op), "!")
        return f"{op}{operand}"

    # ── BoolOp (and / or) ────────────────────────────────────────────
    if isinstance(node, ast.BoolOp):
        op = " && " if isinstance(node.op, ast.And) else " || "
        parts = [_expr(v) for v in node.values]
        return f"({op.join(parts)})"

    # ── Compare  (a < b < c → a < b && b < c) ───────────────────────
    if isinstance(node, ast.Compare):
        parts = []
        left = _expr(node.left)
        left_node = node.left
        for op, comparator in zip(node.ops, node.comparators):
            right = _expr(comparator)
            # Fix int vs float comparisons: if one side is a known float param
            # and the other is an integer constant, add .0
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, int) and not isinstance(comparator.value, bool):
                left_is_float = (isinstance(left_node, ast.Constant) and isinstance(left_node.value, float))
                left_is_float_name = (isinstance(left_node, ast.Name) and left_node.id in _FLOAT_PARAMS)
                if left_is_float or left_is_float_name:
                    right = f"{comparator.value}.0"
            if isinstance(left_node, ast.Constant) and isinstance(left_node.value, int) and not isinstance(left_node.value, bool):
                right_is_float = (isinstance(comparator, ast.Constant) and isinstance(comparator.value, float))
                right_is_float_name = (isinstance(comparator, ast.Name) and comparator.id in _FLOAT_PARAMS)
                if right_is_float or right_is_float_name:
                    left = f"{left_node.value}.0"
            if isinstance(op, ast.In):
                # Check if comparator is a collection (list/set/tuple) vs string
                if isinstance(comparator, (ast.List, ast.Set, ast.Tuple)):
                    # If list elements are string constants, left may be String → .as_str()
                    has_str_elts = any(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                       for e in comparator.elts)
                    ref = f"&{left}.as_str()" if has_str_elts else f"&{left}"
                    parts.append(f"{right}.contains({ref})")
                else:
                    # Assume string contains
                    parts.append(f"{right}.contains({left})")
            elif isinstance(op, ast.NotIn):
                if isinstance(comparator, (ast.List, ast.Set, ast.Tuple)):
                    has_str_elts = any(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                       for e in comparator.elts)
                    ref = f"&{left}.as_str()" if has_str_elts else f"&{left}"
                    parts.append(f"!{right}.contains({ref})")
                else:
                    parts.append(f"!{right}.contains({left})")
            elif isinstance(op, ast.Is):
                if isinstance(comparator, ast.Constant) and comparator.value is None:
                    parts.append(f"{left}.is_none()")
                else:
                    parts.append(f"{left} == {right}")
            elif isinstance(op, ast.IsNot):
                if isinstance(comparator, ast.Constant) and comparator.value is None:
                    parts.append(f"{left}.is_some()")
                else:
                    parts.append(f"{left} != {right}")
            else:
                sym = _CMP_MAP.get(type(op), "==")
                parts.append(f"{left} {sym} {right}")
            left = right
        return " && ".join(parts) if len(parts) > 1 else parts[0]

    # ── Call ──────────────────────────────────────────────────────────
    if isinstance(node, ast.Call):
        return _transpile_call(node)

    # ── Subscript  (a[b]) ────────────────────────────────────────────
    if isinstance(node, ast.Subscript):
        obj = _expr(node.value)
        sl = node.slice
        if isinstance(sl, ast.Slice):
            lower = _expr(sl.lower) if sl.lower else "0"
            upper = _expr(sl.upper) if sl.upper else ""
            if upper:
                return f"&{obj}[{lower}..{upper}]"
            else:
                return f"&{obj}[{lower}..]"
        else:
            idx = _expr(sl)
            return f"{obj}[{idx}]"

    # ── Starred (*args) ──────────────────────────────────────────────
    if isinstance(node, ast.Starred):
        return f"/* *{_expr(node.value)} */"

    # ── IfExp  (a if cond else b) ────────────────────────────────────
    if isinstance(node, ast.IfExp):
        cond = _expr(node.test)
        body = _expr(node.body)
        orelse = _expr(node.orelse)
        return f"if {cond} {{ {body} }} else {{ {orelse} }}"

    # ── List literal ─────────────────────────────────────────────────
    if isinstance(node, ast.List):
        if not node.elts:
            return "vec![]"
        elts = ", ".join(_expr(e) for e in node.elts)
        return f"vec![{elts}]"

    # ── Tuple literal ────────────────────────────────────────────────
    if isinstance(node, ast.Tuple):
        elts = ", ".join(_expr(e) for e in node.elts)
        # Tuples with >2 elements are often used for iteration in Python
        # → use vec![] for Rust compatibility (tuples can't .iter())
        if len(node.elts) > 2:
            return f"vec![{elts}]"
        if len(node.elts) == 1:
            return f"({elts},)"
        return f"({elts})"

    # ── Dict literal ─────────────────────────────────────────────────
    if isinstance(node, ast.Dict):
        if not node.keys:
            return "HashMap::new()"
        pairs = []
        for k, v in zip(node.keys, node.values):
            if k is None:
                pairs.append(f"/* **{_expr(v)} */")
            else:
                pairs.append(f"({_expr(k)}, {_expr(v)})")
        return f"HashMap::from([{', '.join(pairs)}])"

    # ── Set literal ──────────────────────────────────────────────────
    if isinstance(node, ast.Set):
        elts = ", ".join(_expr(e) for e in node.elts)
        return f"HashSet::from([{elts}])"

    # ── ListComp / SetComp / DictComp / GeneratorExp ─────────────────
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return _transpile_comprehension(node)

    if isinstance(node, ast.DictComp):
        return _transpile_dict_comprehension(node)

    # ── f-string (JoinedStr) ─────────────────────────────────────────
    if isinstance(node, ast.JoinedStr):
        parts_fmt = []
        parts_args = []
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts_fmt.append(val.value.replace("{", "{{").replace("}", "}}"))
            elif isinstance(val, ast.FormattedValue):
                fmt_spec = ""
                if val.format_spec:
                    # format_spec is a JoinedStr itself
                    spec_parts = []
                    for sv in val.format_spec.values:
                        if isinstance(sv, ast.Constant):
                            spec_parts.append(str(sv.value))
                    raw_spec = "".join(spec_parts)
                    # Convert Python format spec to Rust:
                    # Remove trailing type char: f, s, d, e, g, b, o, x, X, n, %
                    # Python: ":.1f" → Rust: ":.1"
                    # Python: ":25s" → Rust: ":<25"
                    # Python: ":>10.1f" → Rust: ":>10.1"
                    rust_spec = re.sub(r"([0-9.])[fsdeEgGbBoxXn%]$", r"\1", raw_spec)
                    # Handle standalone type char: ":s" → ":"   ":d" → ":"
                    rust_spec = re.sub(r"^[fsdeEgGbBoxXn]$", "", rust_spec)
                    # ":25s" → ":<25"  (Python implicit left-align for strings)
                    rust_spec = re.sub(r"^(\d+)$", r"<\1", rust_spec)
                    fmt_spec = ":" + rust_spec if rust_spec else ""
                parts_fmt.append(f"{{{fmt_spec}}}")
                parts_args.append(_expr(val.value))
            else:
                parts_fmt.append("{}")
                parts_args.append(_expr(val))
        fmt_str = "".join(parts_fmt).replace('"', '\\"')
        if parts_args:
            args = ", ".join(parts_args)
            return f'format!("{fmt_str}", {args})'
        return f'"{fmt_str}".to_string()'

    # ── Lambda ───────────────────────────────────────────────────────
    if isinstance(node, ast.Lambda):
        params = []
        for arg in node.args.args:
            params.append(arg.arg)
        body = _expr(node.body)
        return f"|{', '.join(params)}| {body}"

    # ── Await ────────────────────────────────────────────────────────
    if isinstance(node, ast.Await):
        return f"{_expr(node.value)}.await"

    # Fallback: use ast.unparse wrapped in a comment
    try:
        raw = ast.unparse(node)
        return f"/* {raw} */"
    except Exception:
        return "/* ??? */"


def _transpile_call(node: ast.Call) -> str:
    """Handle Python function calls → Rust equivalents."""
    args = [_expr(a) for a in node.args]
    kwargs = {kw.arg: _expr(kw.value) for kw in node.keywords if kw.arg}

    # Identify the function being called
    if isinstance(node.func, ast.Name):
        name = node.func.id
        all_args = ", ".join(args)

        # Built-in rewrites
        if name == "len":
            return f"{args[0]}.len()" if args else "0"
        if name == "print":
            if not args:
                return 'println!()'
            # If single arg is a format!() call, unwrap it into println!
            if len(args) == 1 and args[0].startswith("format!("):
                inner = args[0][len("format!("):-1]  # strip format!( and )
                return f'println!({inner})'
            # If single arg is a string literal, use it directly
            if len(args) == 1 and args[0].startswith('"'):
                return f'println!({args[0]})'
            # Multiple args or non-literal: use display format
            fmt_str = " ".join("{}" for _ in args)
            return f'println!("{fmt_str}", {", ".join(args)})'
        if name == "range":
            if len(args) == 1:
                return f"0..{args[0]}"
            if len(args) == 2:
                return f"{args[0]}..{args[1]}"
            if len(args) == 3:
                return f"({args[0]}..{args[1]}).step_by({args[2]} as usize)"
        if name == "str":
            return f"{args[0]}.to_string()" if args else '"".to_string()'
        if name == "int":
            return f"{args[0]} as i64" if args else "0"
        if name == "float":
            return f"{args[0]} as f64" if args else "0.0"
        if name == "bool":
            return f"({args[0]} != 0)" if args else "false"
        if name == "abs":
            return f"{args[0]}.abs()" if args else "0"
        if name == "round":
            if len(args) >= 2:
                return f"(({args[0]} * 10f64.powi({args[1]} as i32)).round() / 10f64.powi({args[1]} as i32))"
            return f"({args[0]} as f64).round() as i64" if args else "0"
        if name == "min":
            if len(args) == 2:
                return f"{args[0]}.min({args[1]})"
            return f"[{all_args}].iter().copied().min().unwrap()"
        if name == "max":
            if len(args) == 2:
                return f"{args[0]}.max({args[1]})"
            return f"[{all_args}].iter().copied().max().unwrap()"
        if name == "sum":
            return f"{args[0]}.iter().sum::<i64>()" if args else "0"
        if name == "sorted":
            base = args[0] if args else "vec![]"
            rev = kwargs.get("reverse", "false")
            if rev == "true":
                return f"{{ let mut v = {base}.clone(); v.sort(); v.reverse(); v }}"
            return f"{{ let mut v = {base}.clone(); v.sort(); v }}"
        if name == "reversed":
            return f"{args[0]}.iter().rev()" if args else "vec![].iter().rev()"
        if name == "enumerate":
            return f"{args[0]}.iter().enumerate()" if args else "vec![].iter().enumerate()"
        if name == "zip":
            if len(args) == 2:
                return f"{args[0]}.iter().zip({args[1]}.iter())"
            return f"/* zip({all_args}) */"
        if name == "map":
            if len(args) >= 2:
                return f"{args[1]}.iter().map({args[0]})"
            return f"/* map({all_args}) */"
        if name == "filter":
            if len(args) >= 2:
                return f"{args[1]}.iter().filter({args[0]})"
            return f"/* filter({all_args}) */"
        if name == "isinstance":
            return f"/* isinstance({all_args}) */ true"
        if name == "hasattr":
            return f"/* hasattr({all_args}) */ true"
        if name == "getattr":
            if len(args) >= 3:
                return f"/* getattr */ {args[2]}"
            return f"/* getattr({all_args}) */"
        if name == "type":
            return f'/* type({all_args}) */ "unknown"'
        if name == "dict":
            return "HashMap::new()"
        if name == "list":
            if args:
                return f"{args[0]}.into_iter().collect::<Vec<_>>()"
            return "Vec::new()"
        if name == "set":
            if args:
                return f"{args[0]}.into_iter().collect::<HashSet<_>>()"
            return "HashSet::new()"
        if name == "tuple":
            return f"/* tuple({all_args}) */"
        if name == "open":
            path_arg = args[0] if args else '""'
            return f'std::fs::read_to_string({path_arg}).unwrap_or_default()'
        if name == "any":
            return f"{args[0]}.iter().any(|x| *x)" if args else "false"
        if name == "all":
            return f"{args[0]}.iter().all(|x| *x)" if args else "true"
        if name == "ord":
            return f"{args[0]}.chars().next().unwrap() as u32" if args else "0"
        if name == "chr":
            return f"char::from_u32({args[0]} as u32).unwrap()" if args else "' '"
        if name == "format":
            if args and args[0].startswith('"'):
                return f'format!({all_args})'
            # If first arg isn't a literal, use display format
            if args:
                return f'format!("{{}}", {args[0]})'
            return '"".to_string()'

        # Default: just call as-is
        return f"{_safe_name(name)}({all_args})"

    # Method call: obj.method(args)
    if isinstance(node.func, ast.Attribute):
        obj = _expr(node.func.value)
        method = node.func.attr
        all_args = ", ".join(args)

        # ── Logger calls → eprintln! ─────────────────────────────────
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "logger":
            if method in ("info", "debug", "warning", "error", "critical",
                          "exception", "warn"):
                if args:
                    return f'eprintln!({", ".join(args)})'
                return 'eprintln!()'
            # logger.setLevel etc. → no-op comment
            return f'/* logger.{method}({all_args}) */'

        # ── platform module calls ─────────────────────────────────────
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "platform":
            if method == "system":
                return 'std::env::consts::OS.to_string()'
            if method == "machine":
                return 'std::env::consts::ARCH.to_string()'
            return f'/* platform.{method}({all_args}) */ String::new()'

        # ── shutil module calls ───────────────────────────────────────
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "shutil":
            if method == "which":
                if args:
                    return (f'std::process::Command::new("which")'
                            f'.arg({args[0]}).output()'
                            f'.ok().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())')
                return 'None::<String>'
            if method in ("rmtree", "remove"):
                if args:
                    return f'std::fs::remove_dir_all({args[0]}).ok()'
                return '()'
            if method in ("copy2", "copy", "copyfile"):
                if len(args) >= 2:
                    return f'std::fs::copy({args[0]}, {args[1]}).ok()'
            return f'/* shutil.{method}({all_args}) */'

        # ── sys module calls ──────────────────────────────────────────
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "sys":
            if method == "getrecursionlimit":
                return '1000i64'
            if method == "exit":
                if args:
                    return f'std::process::exit({args[0]} as i32)'
                return 'std::process::exit(0)'
            return f'/* sys.{method}({all_args}) */'

        # String method rewrites
        method_map = {
            "append": "push", "strip": "trim", "lstrip": "trim_start",
            "rstrip": "trim_end", "lower": "to_lowercase",
            "upper": "to_uppercase", "startswith": "starts_with",
            "endswith": "ends_with", "items": "iter",
        }
        rust_method = method_map.get(method, method)

        # Special cases
        if method == "join":
            # Python: ", ".join(lst) → Rust: lst.join(", ")
            # In Python, the obj is the separator and arg is the iterable
            if args:
                return f"{args[0]}.join({obj})"
            return f"Vec::<String>::new().join({obj})"
        if method == "format":
            return f"format!({obj}, {all_args})"
        if method == "split":
            # Python split returns a list, Rust split returns an iterator
            # → collect to Vec for list-like usage
            if args:
                return f"{obj}.split({args[0]}).collect::<Vec<&str>>()"
            return f"{obj}.split_whitespace().collect::<Vec<&str>>()"
        if method == "rsplit":
            if args:
                return f"{obj}.rsplit({args[0]}).collect::<Vec<&str>>()"
            return f"{obj}.rsplit_whitespace().collect::<Vec<&str>>()"
        if method == "get":
            # dict.get(key, default) → dict.get(key).unwrap_or(default)
            if len(args) >= 2:
                return f"{obj}.get(&{args[0]}).cloned().unwrap_or({args[1]})"
            return f"{obj}.get(&{args[0]})"
        if method == "pop":
            if args:
                return f"{obj}.remove(&{args[0]})"
            return f"{obj}.pop()"
        if method == "update":
            return f"{obj}.extend({all_args})"
        if method == "keys":
            return f"{obj}.keys()"
        if method == "values":
            return f"{obj}.values()"
        if method in ("read_text", "read"):
            return f"std::fs::read_to_string(&{obj}).unwrap_or_default()"
        if method == "write_text":
            if args:
                return f"std::fs::write(&{obj}, {args[0]}).ok()"
            return f"std::fs::write(&{obj}, \"\").ok()"
        if method == "exists":
            return f"std::path::Path::new(&{obj}).exists()"
        if method == "is_file":
            return f"std::path::Path::new(&{obj}).is_file()"
        if method == "is_dir":
            return f"std::path::Path::new(&{obj}).is_dir()"
        if method == "mkdir":
            return f"std::fs::create_dir_all(&{obj}).ok()"
        if method == "iterdir":
            return f"std::fs::read_dir(&{obj}).unwrap()"
        if method == "count":
            # Python str.count("x") → Rust .matches("x").count() as i64
            if args:
                return f"{obj}.matches({args[0]}).count() as i64"
            return f"{obj}.len() as i64"

        return f"{obj}.{rust_method}({all_args})"

    # Complex callable (subscript, nested call, etc.)
    func_expr = _expr(node.func)
    all_args = ", ".join(args)
    return f"{func_expr}({all_args})"


def _transpile_comprehension(node) -> str:
    """[expr for x in iter if cond] → iter.filter().map().collect()"""
    # We handle the first generator; nested ones get a comment
    if not node.generators:
        return "vec![]"

    gen = node.generators[0]
    target = _expr(gen.target)
    iter_expr = _expr(gen.iter)
    elt = _expr(node.elt)

    chain = f"{iter_expr}.iter()"

    # Conditions
    for cond in gen.ifs:
        cond_expr = _expr(cond)
        chain += f".filter(|{target}| {cond_expr})"

    # Map
    if elt != target:
        chain += f".map(|{target}| {elt})"

    # Collect
    if isinstance(node, ast.SetComp):
        chain += ".collect::<HashSet<_>>()"
    elif isinstance(node, ast.GeneratorExp):
        chain += ".collect::<Vec<_>>()"
    else:
        chain += ".collect::<Vec<_>>()"

    # Nested generators → comment
    if len(node.generators) > 1:
        chain += " /* TODO: nested comprehension */"

    return chain


def _transpile_dict_comprehension(node: ast.DictComp) -> str:
    """{k: v for x in iter if cond} → iter.map(|x| (k,v)).collect()"""
    if not node.generators:
        return "HashMap::new()"

    gen = node.generators[0]
    target = _expr(gen.target)
    iter_expr = _expr(gen.iter)
    key = _expr(node.key)
    val = _expr(node.value)

    chain = f"{iter_expr}.iter()"
    for cond in gen.ifs:
        cond_expr = _expr(cond)
        chain += f".filter(|{target}| {cond_expr})"

    chain += f".map(|{target}| ({key}, {val}))"
    chain += ".collect::<HashMap<_, _>>()"

    return chain


# ═══════════════════════════════════════════════════════════════════════════
#  Statement Transpilation  (ast.stmt → Rust lines)
# ═══════════════════════════════════════════════════════════════════════════

def _body(stmts: list, indent: int = 1, *, ret_type: str = "()") -> List[str]:
    """Translate a list of Python AST statements to Rust source lines."""
    pad = "    " * indent
    lines: List[str] = []

    for stmt in stmts:
        # ── return ────────────────────────────────────────────────────
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                val = _expr(stmt.value)
                # Add .to_string() for string literals when return type is String
                if "String" in ret_type and val.startswith('"') and val.endswith('"'):
                    val = f"{val}.to_string()"
                lines.append(f"{pad}return {val};")
            else:
                lines.append(f"{pad}return;")

        # ── if / elif / else ─────────────────────────────────────────
        elif isinstance(stmt, ast.If):
            test = _expr(stmt.test)
            lines.append(f"{pad}if {test} {{")
            lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
            if stmt.orelse:
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    # elif chain
                    elif_test = _expr(stmt.orelse[0].test)
                    lines.append(f"{pad}}} else if {elif_test} {{")
                    lines.extend(_body(stmt.orelse[0].body, indent + 1, ret_type=ret_type))
                    # recursively handle the rest of the elif chain
                    rest = stmt.orelse[0].orelse
                    while rest:
                        if len(rest) == 1 and isinstance(rest[0], ast.If):
                            elif_t = _expr(rest[0].test)
                            lines.append(f"{pad}}} else if {elif_t} {{")
                            lines.extend(_body(rest[0].body, indent + 1, ret_type=ret_type))
                            rest = rest[0].orelse
                        else:
                            lines.append(f"{pad}}} else {{")
                            lines.extend(_body(rest, indent + 1, ret_type=ret_type))
                            rest = None
                    lines.append(f"{pad}}}")
                else:
                    lines.append(f"{pad}}} else {{")
                    lines.extend(_body(stmt.orelse, indent + 1, ret_type=ret_type))
                    lines.append(f"{pad}}}")
            else:
                lines.append(f"{pad}}}")

        # ── for ──────────────────────────────────────────────────────
        elif isinstance(stmt, ast.For):
            target = _expr(stmt.target)
            iter_expr = _expr(stmt.iter)
            # String constants need .chars() to iterate
            if isinstance(stmt.iter, ast.Constant) and isinstance(stmt.iter.value, str):
                iter_expr = f"{iter_expr}.chars()"
            # .iter() for list/set/tuple literals so we get references
            elif isinstance(stmt.iter, (ast.List, ast.Set, ast.Tuple)):
                iter_expr = f"{iter_expr}.iter()"
            lines.append(f"{pad}for {target} in {iter_expr} {{")
            lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
            lines.append(f"{pad}}}")

        # ── while ────────────────────────────────────────────────────
        elif isinstance(stmt, ast.While):
            test = _expr(stmt.test)
            lines.append(f"{pad}while {test} {{")
            lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
            lines.append(f"{pad}}}")

        # ── assignment ───────────────────────────────────────────────
        elif isinstance(stmt, ast.Assign):
            tgt_node = stmt.targets[0]
            value = _expr(stmt.value)

            # Tuple unpacking: (a, b) = expr → let (mut a, mut b) = expr
            if isinstance(tgt_node, ast.Tuple):
                parts = ", ".join(f"mut {_expr(e)}" for e in tgt_node.elts)
                lines.append(f"{pad}let ({parts}) = {value};")

            # Subscript/slice assignment: x[i] = val → x[i] = val  (no let)
            elif isinstance(tgt_node, ast.Subscript):
                target = _expr(tgt_node)
                lines.append(f"{pad}{target} = {value};")

            # Attribute assignment: self.x = val → this.x = val  (no let)
            elif isinstance(tgt_node, ast.Attribute):
                target = _expr(tgt_node)
                lines.append(f"{pad}{target} = {value};")

            # Simple name binding
            else:
                target = _expr(tgt_node)
                lines.append(f"{pad}let mut {target} = {value};")

        # ── annotated assignment ──────────────────────────────────────
        elif isinstance(stmt, ast.AnnAssign):
            target = _expr(stmt.target)
            ann = py_type_to_rust(ast.unparse(stmt.annotation)) if stmt.annotation else "String"
            if stmt.value:
                value = _expr(stmt.value)
                lines.append(f"{pad}let mut {target}: {ann} = {value};")
            else:
                lines.append(f"{pad}let mut {target}: {ann};")

        # ── augmented assignment (+=, -=, etc.) ──────────────────────
        elif isinstance(stmt, ast.AugAssign):
            target = _expr(stmt.target)
            op = _OP_MAP.get(type(stmt.op), "+")
            value = _expr(stmt.value)
            lines.append(f"{pad}{target} {op}= {value};")

        # ── expression statement (function calls, etc.) ──────────────
        elif isinstance(stmt, ast.Expr):
            # Skip docstrings
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            expr_str = _expr(stmt.value)
            lines.append(f"{pad}{expr_str};")

        # ── pass ─────────────────────────────────────────────────────
        elif isinstance(stmt, ast.Pass):
            lines.append(f"{pad}// pass")

        # ── break / continue ─────────────────────────────────────────
        elif isinstance(stmt, ast.Break):
            lines.append(f"{pad}break;")
        elif isinstance(stmt, ast.Continue):
            lines.append(f"{pad}continue;")

        # ── assert ───────────────────────────────────────────────────
        elif isinstance(stmt, ast.Assert):
            test_expr = _expr(stmt.test)
            if stmt.msg:
                msg = _expr(stmt.msg)
                lines.append(f'{pad}assert!({test_expr}, {msg});')
            else:
                lines.append(f"{pad}assert!({test_expr});")

        # ── raise ────────────────────────────────────────────────────
        elif isinstance(stmt, ast.Raise):
            if stmt.exc:
                exc = _expr(stmt.exc)
                # Escape { and } so panic! doesn't try to format them
                exc_safe = exc.replace("{", "{{").replace("}", "}}")
                exc_safe = exc_safe.replace('"', '\\"')
                lines.append(f'{pad}panic!("{exc_safe}");')
            else:
                lines.append(f'{pad}panic!("raised");')

        # ── try / except / finally ───────────────────────────────────
        elif isinstance(stmt, ast.Try):
            lines.append(f"{pad}// try {{")
            lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
            for handler in stmt.handlers:
                exc_name = ast.unparse(handler.type) if handler.type else "Exception"
                as_name = f" as {handler.name}" if handler.name else ""
                lines.append(f"{pad}// }} catch {exc_name}{as_name} {{")
                lines.extend(_body(handler.body, indent + 1, ret_type=ret_type))
            if stmt.finalbody:
                lines.append(f"{pad}// }} finally {{")
                lines.extend(_body(stmt.finalbody, indent + 1, ret_type=ret_type))
            lines.append(f"{pad}// }}")

        # ── with ─────────────────────────────────────────────────────
        elif isinstance(stmt, ast.With):
            items = []
            for item in stmt.items:
                ctx = _expr(item.context_expr)
                if item.optional_vars:
                    alias = _expr(item.optional_vars)
                    items.append(f"let {alias} = {ctx}")
                else:
                    items.append(ctx)
            lines.append(f"{pad}{{ // with")
            for item_str in items:
                lines.append(f"{pad}    {item_str};")
            lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
            lines.append(f"{pad}}}")

        # ── nested function def ──────────────────────────────────────
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(f"{pad}// TODO: nested fn {stmt.name}()")

        # ── nested class def ─────────────────────────────────────────
        elif isinstance(stmt, ast.ClassDef):
            lines.append(f"{pad}// TODO: nested class {stmt.name}")

        # ── delete ───────────────────────────────────────────────────
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                lines.append(f"{pad}// del {_expr(target)}")

        # ── global / nonlocal ────────────────────────────────────────
        elif isinstance(stmt, (ast.Global, ast.Nonlocal)):
            names = ", ".join(stmt.names)
            keyword = "global" if isinstance(stmt, ast.Global) else "nonlocal"
            lines.append(f"{pad}// {keyword} {names}")

        # ── import ───────────────────────────────────────────────────
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            lines.append(f"{pad}// {ast.unparse(stmt)}")

        # ── fallback ─────────────────────────────────────────────────
        else:
            try:
                py_line = ast.unparse(stmt).split("\n")[0]
                lines.append(f"{pad}// TODO: {py_line}")
            except Exception:
                lines.append(f"{pad}// TODO: unsupported statement")

    return lines


# ═══════════════════════════════════════════════════════════════════════════
#  Top-level: Transpile One Function
# ═══════════════════════════════════════════════════════════════════════════

def transpile_function_code(code: str, *, name_hint: str = "",
                            source_info: str = "") -> str:
    """Transpile a Python function's source code to Rust.

    Parameters
    ----------
    code : str
        The raw Python source of a single function (def line + body).
    name_hint : str
        Function name (used if the def can't be parsed).
    source_info : str
        e.g. "module.py:42" — added as a doc comment.

    Returns
    -------
    str
        A complete Rust function definition.
    """
    # Dedent to handle functions extracted with leading whitespace
    code = textwrap.dedent(code)

    try:
        tree = ast.parse(code)
    except SyntaxError:
        fn_name = name_hint or "unknown"
        return (f"// Could not parse: {source_info}\n"
                f"fn {fn_name}() {{\n    todo!(\"parse error\")\n}}")

    # Find the function def node
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_node = node
            break

    if func_node is None:
        fn_name = name_hint or "unknown"
        return (f"// No function found: {source_info}\n"
                f"fn {fn_name}() {{\n    todo!(\"no function in source\")\n}}")

    fn_name = _safe_name(name_hint) if name_hint else _safe_name(func_node.name)

    # ── Parameters ────────────────────────────────────────────────────
    _FLOAT_PARAMS.clear()
    params = []
    for arg in func_node.args.args:
        if arg.arg == "self" or arg.arg == "cls":
            continue
        pname = _safe_name(arg.arg)
        if arg.annotation:
            ptype = py_type_to_rust(ast.unparse(arg.annotation))
        else:
            ptype = _infer_type_from_name(arg.arg)
        if ptype == "f64":
            _FLOAT_PARAMS.add(arg.arg)
        params.append(f"{pname}: {ptype}")

    # Handle *args and **kwargs
    if func_node.args.vararg:
        vname = _safe_name(func_node.args.vararg.arg)
        params.append(f"{vname}: Vec<String>")
    if func_node.args.kwarg:
        kname = _safe_name(func_node.args.kwarg.arg)
        params.append(f"{kname}: HashMap<String, String>")

    params_str = ", ".join(params)

    # ── Return type ───────────────────────────────────────────────────
    if func_node.returns:
        ret_type = py_type_to_rust(ast.unparse(func_node.returns))
    else:
        ret_type = _infer_return_type(func_node)

    # ── Build function ────────────────────────────────────────────────
    lines = []
    if source_info:
        lines.append(f"/// Transpiled from {source_info}")
    lines.append(f"fn {fn_name}({params_str}) -> {ret_type} {{")

    body_lines = _body(func_node.body, indent=1, ret_type=ret_type)
    lines.extend(body_lines)

    # Ensure there's a return if needed
    if ret_type != "()" and body_lines:
        # Check if any line in the body has a return statement
        has_any_return = any("return " in l or "return;" in l
                            for l in body_lines if l.strip() and not l.strip().startswith("//"))
        if not has_any_return:
            lines.append(f"    todo!(\"return {ret_type}\")")

    lines.append("}")
    return "\n".join(lines)


def _infer_type_from_name(name: str) -> str:
    """Guess a Rust type from a Python parameter name."""
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


def _infer_return_type(func_node) -> str:
    """Try to infer return type from the function body."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value is not None:
            val = node.value
            if isinstance(val, ast.Constant):
                if isinstance(val.value, bool):
                    return "bool"
                if isinstance(val.value, int):
                    return "i64"
                if isinstance(val.value, float):
                    return "f64"
                if isinstance(val.value, str):
                    return "String"
            if isinstance(val, ast.List):
                return "Vec<String>"
            if isinstance(val, ast.Dict):
                return "HashMap<String, String>"
            if isinstance(val, ast.Tuple):
                n = len(val.elts)
                return f"({', '.join(['String'] * n)})"
            if isinstance(val, (ast.BoolOp, ast.Compare)):
                return "bool"
            if isinstance(val, ast.BinOp):
                if isinstance(val.op, (ast.Add, ast.Sub, ast.Mult)):
                    return "i64"
            # Default: String is safe
            return "String"
    return "()"


# ═══════════════════════════════════════════════════════════════════════════
#  Top-level: Transpile Entire Module / Batch
# ═══════════════════════════════════════════════════════════════════════════

def transpile_module_file(filepath: str) -> str:
    """Read a .py file and transpile all top-level functions to Rust."""
    code = Path(filepath).read_text(encoding="utf-8")
    return transpile_module_code(code, source=filepath)


def transpile_module_code(code: str, *, source: str = "") -> str:
    """Transpile all functions in a Python source string to Rust."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return f"// Parse error in {source}"

    parts = ["// Auto-generated by X-Ray AST Transpiler", ""]

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = f"{source}:{node.lineno}" if source else ""
            fn_code = ast.get_source_segment(code, node) or ""
            if fn_code:
                parts.append(transpile_function_code(fn_code, source_info=info))
                parts.append("")

    return "\n".join(parts)


# Python-only identifiers that cannot exist in standalone Rust
# NOTE: logger, platform, shutil, sys are handled by call rewrites
# in _transpile_call — they're removed here so the rewritten output passes.
_PYTHON_ONLY_SYMBOLS = {
    "ast", "os", "re", "json", "logging", "pathlib",
    "concurrent", "threading", "subprocess", "argparse",
    "io", "importlib", "inspect", "traceback", "pyo3",
    "typing", "collections", "functools", "itertools",
}

# Patterns in the *generated Rust body* that indicate untranspilable code
_UNTRANSPILABLE_PATTERNS = [
    r"\bthis\.",           # class method using self → this
    r"\btuple\(",          # Python tuple()
    r"\bsuper\(\)",        # Python super()
    r"\bcompile_crate\(",  # cross-module function call
    r"\btokenize\(",       # cross-module function call
    r"\b_[A-Z][A-Z_]{2,}\b",  # Module-level constants like _PENALTY_RULES
    r'\["[^"]*"\]',        # dict-style string subscript like conflict["key"]
    r'extern\s+"C"',       # FFI extern blocks
    r'&\w+\[[^\]]*\]\s*=',  # Slice assignment (invalid Rust lhs)
]

# Known safe Rust methods that don't indicate Python object access
_SAFE_RUST_METHODS = {
    "len", "push", "pop", "contains", "is_empty", "to_string", "clone",
    "iter", "into_iter", "map", "filter", "collect", "any", "all",
    "unwrap", "unwrap_or", "expect", "ok", "err", "is_some", "is_none",
    "as_str", "trim", "split", "join", "replace", "starts_with", "ends_with",
    "to_lowercase", "to_uppercase", "chars", "bytes", "lines",
    "insert", "remove", "get", "entry", "or_insert", "extend",
    "sort", "sort_by", "reverse", "dedup", "retain",
    "pow", "abs", "min", "max", "round", "ceil", "floor",
    "keys", "values", "items", "find", "matches",
    "strip_prefix", "strip_suffix", "parse", "as_ref",
    "display", "write", "read", "flush",
    "result", "and_then", "or_else", "map_err",
    "format", "with_capacity", "capacity", "reserve",
    "as_bytes", "as_slice", "as_mut_slice",
    "checked_add", "checked_sub", "checked_mul",
    "to_owned", "into", "from", "default",
    "first", "last", "skip", "take", "enumerate", "zip",
    "flat_map", "fold", "reduce", "sum", "count",
    "step_by", "chain", "peekable",
    "is_ascii_digit", "is_alphabetic", "is_ascii",
    "new", "with", "build", "from_utf8",
}


def _sanitize_generated(rust_code: str) -> str:
    """If the generated Rust code references Python-only symbols,
    replace the body with todo!() to ensure compilation succeeds."""
    # Extract the signature (first line with fn)
    lines = rust_code.split("\n")
    sig_line = ""
    sig_idx = -1
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("fn ") or stripped.startswith("pub fn "):
            sig_line = line
            sig_idx = i
            break

    if sig_idx < 0:
        return rust_code

    # Check the body for Python-only references
    body = "\n".join(lines[sig_idx + 1:])
    reason = ""

    # Strip comments and string literal contents so that e.g. `// import json`
    # or `"-f", "json"` don't cause false positives.
    body_stripped = re.sub(r'//.*$', '', body, flags=re.MULTILINE)
    body_stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body_stripped)

    # Check for Python-only module symbols (against stripped body)
    for sym in _PYTHON_ONLY_SYMBOLS:
        if re.search(rf"\b{sym}\b", body_stripped):
            reason = f"Python-only: {sym}"
            break

    # Check for untranspilable patterns (against raw body — these patterns
    # deliberately match structural code, not identifiers in strings)
    if not reason:
        for pat in _UNTRANSPILABLE_PATTERNS:
            if re.search(pat, body):
                # Use a cleaned description, not the raw regex
                reason = "uses Python class/module pattern"
                break

    # Check for Python object field access (foo.bar where bar is not a known Rust method)
    if not reason:
        field_accesses = re.findall(r"\.([a-z_][a-z_0-9]*)\b", body)
        unknown_fields = [f for f in field_accesses if f not in _SAFE_RUST_METHODS]
        # If >30% of field accesses are unknown, it's operating on Python objects
        if unknown_fields and len(unknown_fields) > max(2, len(field_accesses) * 0.3):
            reason = "uses Python object fields"

    # Check for Python string repetition (str * int)
    if not reason:
        if re.search(r'"[^"]*"\s*\*\s*\d+', body) or re.search(r'"[^"]*"\s*\*\s*\w+', body):
            reason = "uses Python string repetition"

    if reason:
        # Wrap body in todo!()
        comment_lines = [l for l in lines[:sig_idx]]
        sig = sig_line.rstrip()
        if not sig.endswith("{"):
            sig += " {"
        return "\n".join(comment_lines + [
            sig,
            f'    todo!("{reason}")',
            "}"
        ])

    return rust_code


def transpile_batch_json(json_input: str) -> str:
    """Transpile a JSON array of {name, code, file_path, line_start}.

    This is the interface called by X_Ray.exe via subprocess:

        X_Ray.exe → writes candidates to temp.json
                  → calls: python -m Analysis.transpiler --json temp.json
                  → reads stdout as the generated Rust source
    """
    candidates = json.loads(json_input)
    parts = [
        "// Auto-generated by X-Ray Hybrid Transpiler (AST + LLM)",
        "#![allow(unused_variables, unused_mut, dead_code, unused_imports)]",
        "#![allow(unreachable_code, unused_assignments)]",
        "",
        "use std::collections::{HashMap, HashSet};",
        "",
    ]

    # ── LLM fallback engine (lazy — only initialised if needed) ───────
    llm_engine = None
    llm_available = False
    try:
        from Analysis.llm_transpiler import get_llm_transpiler
        llm_engine = get_llm_transpiler()
        llm_available = llm_engine.available
        if llm_available:
            logger.info("Hybrid transpiler: LLM backend detected — "
                        "complex functions will use LLM fallback")
    except Exception:
        pass  # LLM not configured — pure AST mode

    # Track used names to deduplicate
    name_counts: Dict[str, int] = {}

    for cand in candidates:
        code = cand.get("code", "")
        name = cand.get("name", "unknown")
        fpath = cand.get("file_path", "")
        line = cand.get("line_start", 0)
        source_info = f"{fpath}:{line}" if fpath else ""

        # Deduplicate: if name already seen, prefix with module name
        if name in name_counts:
            name_counts[name] += 1
            stem = Path(fpath).stem if fpath else f"mod{name_counts[name]}"
            # Clean module name to be a valid Rust identifier
            safe_stem = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
            unique_name = f"{safe_stem}__{name}"
        else:
            name_counts[name] = 1
            unique_name = name

        # Step 1: AST transpiler (fast, deterministic)
        rust = transpile_function_code(code, name_hint=unique_name, source_info=source_info)

        # Sanitize: if the generated Rust references Python-only symbols,
        # wrap the body in todo!() to prevent compilation errors
        rust = _sanitize_generated(rust)

        # Step 2: LLM fallback — if AST produced todo!(), ask the LLM
        if "todo!" in rust and llm_available and llm_engine is not None:
            logger.info(f"  AST produced todo!() for {unique_name} — trying LLM...")
            llm_result = llm_engine.transpile(
                code, name_hint=unique_name, source_info=source_info
            )
            if llm_result is not None:
                rust = llm_result

        parts.append(rust)
        parts.append("")

    # Add main() that exercises real transpiled functions
    n = len(candidates)

    # Count LLM-assisted functions
    llm_count = sum(1 for p in parts if "LLM-assisted" in p)
    ast_real = 0

    real_fns = []
    for cand in candidates:
        name = cand.get("name", "unknown")
        # Find the actual Rust name used (may be deduplicated)
        rust_name = name
        if name_counts.get(name, 0) > 1:
            stem = Path(cand.get("file_path", "")).stem if cand.get("file_path") else "mod"
            safe_stem = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
            rust_name = f"{safe_stem}__{name}"
        # Check if this function was sanitized (has todo! in its generated code)
        fn_code = next((p for p in parts if f"fn {rust_name}(" in p
                        or f"fn {_safe_name(rust_name)}(" in p), "")
        if fn_code and "todo!" not in fn_code:
            real_fns.append((rust_name, fn_code))
            if "LLM-assisted" not in fn_code:
                ast_real += 1

    parts.append("fn main() {")
    parts.append(f'    println!("╔══════════════════════════════════════════════════╗");')
    parts.append(f'    println!("║  X-Ray Rustified Executable (Hybrid)            ║");')
    parts.append(f'    println!("║  {n} functions transpiled, {{}} real Rust         ║", {len(real_fns)});')
    if llm_count > 0:
        parts.append(f'    println!("║    AST engine: {ast_real}  |  LLM engine: {llm_count}             ║");')
    parts.append(f'    println!("╚══════════════════════════════════════════════════╝");')
    parts.append(f'    println!();')

    # Exercise each real function with demo calls
    # Skip mock/test functions that may panic with arbitrary input
    for fn_name, fn_code in real_fns:
        safe = _safe_name(fn_name)
        if any(s in safe for s in ("mock_", "test_", "reproduce")):
            parts.append(f'    println!("  ▸ {safe}() — skipped (test/mock function)");')
            continue
        # Parse signature to determine call args
        sig_match = re.search(r"fn\s+" + re.escape(safe) + r"\(([^)]*)\)", fn_code)
        if not sig_match:
            continue
        params_raw = sig_match.group(1).strip()
        if not params_raw:
            # No-arg function
            parts.append(f'    println!("  ▸ {safe}() = {{:?}}", {safe}());')
        elif "Vec<String>" in params_raw and params_raw.count(",") == 0:
            # Single Vec<String> param
            parts.append(f'    println!("  ▸ {safe}() = {{:?}}", {safe}(vec!["parse_config".to_string(), "load_data".to_string()]));')
        elif "String" in params_raw and params_raw.count(",") == 0:
            # Single String param
            parts.append(f'    println!("  ▸ {safe}(\\\"file_path\\\") = {{:?}}", {safe}("file_path".to_string()));')
        elif "f64" in params_raw and params_raw.count(",") == 0:
            # Single f64 param
            parts.append(f'    println!("  ▸ {safe}(0.03) = {{:?}}", {safe}(0.03));')
            parts.append(f'    println!("  ▸ {safe}(-0.10) = {{:?}}", {safe}(-0.10));')
            parts.append(f'    println!("  ▸ {safe}(0.20) = {{:?}}", {safe}(0.20));')
        else:
            parts.append(f'    // {safe}({params_raw}) — complex signature, skipped')

    parts.append(f'    println!();')
    if llm_count > 0:
        parts.append(f'    println!("  Done. {{}} of {n} functions are real Rust code ({ast_real} AST + {llm_count} LLM).", {len(real_fns)});')
    else:
        parts.append(f'    println!("  Done. {{}} of {n} functions are real Rust code.", {len(real_fns)});')
    parts.append("}")

    result = "\n".join(parts)

    # Final post-process: fix any remaining Python format specs in Rust macros
    # {:25s} → {:<25}    {:.1f} → {:.1}    {:>10.1f} → {:>10.1}
    result = re.sub(r"\{([:<>.^0-9+-]*\d+\.?\d*)[fsdeEgGn]\}", r"{\1}", result)
    # {:s} → {}   {:d} → {}
    result = re.sub(r"\{:[fsdeEgGn]\}", "{}", result)

    # Log LLM stats if engine was used
    if llm_engine is not None and llm_engine.stats["attempted"] > 0:
        s = llm_engine.stats
        logger.info(
            f"Hybrid transpiler stats: {s['attempted']} LLM attempts, "
            f"{s['success']} succeeded, {s['compile_fail']} compile fails, "
            f"{s['llm_fail']} LLM errors"
        )

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """CLI: python -m Analysis.transpiler [options]"""
    import argparse
    parser = argparse.ArgumentParser(description="X-Ray AST Transpiler: Python → Rust")
    parser.add_argument("--file", help="Transpile all functions in a .py file")
    parser.add_argument("--code", help="Transpile a single function from a code string")
    parser.add_argument("--json", help="Path to JSON file with candidate list")
    parser.add_argument("--stdin-json", action="store_true",
                        help="Read JSON candidates from stdin")
    parser.add_argument("--out", help="Output file (default: stdout)")
    args = parser.parse_args()

    result = ""

    if args.file:
        result = transpile_module_file(args.file)
    elif args.code:
        result = transpile_function_code(args.code)
    elif args.json:
        json_text = Path(args.json).read_text(encoding="utf-8")
        result = transpile_batch_json(json_text)
    elif args.stdin_json:
        json_text = sys.stdin.read()
        result = transpile_batch_json(json_text)
    else:
        parser.print_help()
        return

    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print(f"Written to {args.out}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
