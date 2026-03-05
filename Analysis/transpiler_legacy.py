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
from typing import Callable, Dict, List, Tuple

logger = logging.getLogger("X_RAY_Claude")


# ═══════════════════════════════════════════════════════════════════════════
#  Type Mapping
# ═══════════════════════════════════════════════════════════════════════════

_PY_TO_RUST: Dict[str, str] = {
    "int": "i64",
    "float": "f64",
    "str": "String",
    "bool": "bool",
    "bytes": "Vec<u8>",
    "None": "()",
    "NoneType": "()",
    "list": "Vec<String>",
    "dict": "HashMap<String, String>",
    "set": "HashSet<String>",
    "tuple": "()",
    "Any": "String",
    "object": "String",
    "Path": "String",
    "pathlib.Path": "String",
}

# Regex patterns for generic Python types → Rust types
_GENERIC_TYPE_PATTERNS = [
    (r"Optional\[(.+)\]", lambda m: f"Option<{py_type_to_rust(m.group(1))}>"),
    (r"(?:List|list)\[(.+)\]", lambda m: f"Vec<{py_type_to_rust(m.group(1))}>"),
    (r"(?:Set|set)\[(.+)\]", lambda m: f"HashSet<{py_type_to_rust(m.group(1))}>"),
    (
        r"(?:Dict|dict)\[(.+?),\s*(.+)\]",
        lambda m: (
            f"HashMap<{py_type_to_rust(m.group(1))}, {py_type_to_rust(m.group(2))}>"
        ),
    ),
    (
        r"(?:Tuple|tuple)\[(.+)\]",
        lambda m: (
            f"({', '.join(py_type_to_rust(p.strip()) for p in m.group(1).split(','))})"
        ),
    ),
    (r"Union\[(.+)\]", lambda m: py_type_to_rust(m.group(1).split(",")[0].strip())),
]


def py_type_to_rust(py_type: str, default: str = "String") -> str:
    """Convert a Python type annotation string to a Rust type string.

    *default* is returned for types not in _PY_TO_RUST (e.g. \"String\" for
    pure Rust, \"PyObject\" for PyO3 bindings).
    """
    if not py_type or py_type.strip() == "":
        return default
    py_type = py_type.strip()
    for pattern, converter in _GENERIC_TYPE_PATTERNS:
        m = re.match(pattern, py_type)
        if m:
            return converter(m)
    return _PY_TO_RUST.get(py_type, default)


# ═══════════════════════════════════════════════════════════════════════════
#  AST Operator Mapping
# ═══════════════════════════════════════════════════════════════════════════

_OP_MAP = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
    ast.Pow: "pow",
    ast.BitOr: "|",
    ast.BitAnd: "&",
    ast.BitXor: "^",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.FloorDiv: "/",
}

_CMP_MAP = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "==",
    ast.IsNot: "!=",
    ast.In: ".contains",
    ast.NotIn: ".contains",
}

_UNARY_MAP = {
    ast.UAdd: "+",
    ast.USub: "-",
    ast.Not: "!",
    ast.Invert: "~",
}

# Rust reserved words needing r# prefix or renaming
_RUST_RESERVED = {
    "type",
    "match",
    "ref",
    "mod",
    "fn",
    "use",
    "impl",
    "struct",
    "enum",
    "trait",
    "pub",
    "crate",
    "move",
    "mut",
    "loop",
    "where",
    "async",
    "await",
    "dyn",
    "abstract",
    "become",
    "box",
    "do",
    "final",
    "macro",
    "override",
    "priv",
    "typeof",
    "unsized",
    "virtual",
    "yield",
    "union",
    "static",
    "extern",
    "const",
    "let",
}

# Words that cannot use r# prefix at all — must be renamed
_RUST_SPECIAL_RENAME = {
    "self": "this",
    "cls": "this",
    "Self": "This",
    "super": "super_",
    "_": "tr_",
}


def _safe_name(name: str) -> str:
    """Make a Python identifier safe for Rust."""
    if name in _RUST_SPECIAL_RENAME:
        return _RUST_SPECIAL_RENAME[name]
    if name in _RUST_RESERVED:
        return f"r#{name}"
    return name


# ═══════════════════════════════════════════════════════════════════════════
#  Expression Handlers  (each handles one AST node type)
# ═══════════════════════════════════════════════════════════════════════════

# Module-level context: set of parameter names known to be float-typed
_FLOAT_PARAMS: set = set()


def _expr_constant(node: ast.expr) -> str:
    """Literal values: int, float, str, bool, bytes, None."""
    v = node.value
    _CONST_TYPE_MAP = {
        bool: lambda x: "true" if x else "false",
        int: lambda x: str(x),
        float: lambda x: (
            repr(x) if ("." in repr(x) or "e" in repr(x).lower()) else repr(x) + ".0"
        ),
        str: _escape_string_literal,
        bytes: lambda x: _escape_bytes_literal(x),
    }
    handler = _CONST_TYPE_MAP.get(type(v))
    if handler:
        return handler(v)
    return "None" if v is None else repr(v)


# Character escape table for Rust string literals
_RUST_ESCAPE_MAP: Dict[str, str] = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "",
    "\t": "\\t",
    "\0": "\\0",
}
_RUST_BRACE_MAP: Dict[str, str] = {"{": "{{", "}": "}}"}


def _escape_for_rust(v: str, wrap_braces: bool = True) -> str:
    """Escape a Python string value for embedding in Rust source code.

    Uses table-driven lookup instead of per-character branching.
    If *wrap_braces* is True, also escapes ``{`` → ``{{`` and ``}`` → ``}}``.
    """
    table = {**_RUST_ESCAPE_MAP, **(_RUST_BRACE_MAP if wrap_braces else {})}
    return "".join(
        table.get(ch, ch) for ch in v if ch != "\r" or "\r" not in _RUST_ESCAPE_MAP
    )


def _escape_string_literal(v: str) -> str:
    """Escape a Python string for Rust string literal."""
    return f'"{_escape_for_rust(v, wrap_braces=True)}"'


def _escape_bytes_literal(v: bytes) -> str:
    """Escape Python bytes for Rust byte string literal."""
    decoded = v.decode("utf-8", errors="replace")
    escaped = decoded.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    # Remove non-ASCII chars that are invalid in Rust byte strings
    escaped = re.sub(r"[^\x00-\x7e]", "?", escaped)
    return f'b"{escaped}"'


_NAME_LITERALS = {"True": "true", "False": "false", "None": "None"}


def _expr_name(node: ast.expr) -> str:
    """Variable references: True/False/None or safe-named identifiers."""
    return _NAME_LITERALS.get(node.id, _safe_name(node.id))


_ATTR_RENAMES: Dict[str, str] = {
    "append": "push",
    "strip": "trim",
    "lstrip": "trim_start",
    "rstrip": "trim_end",
    "lower": "to_lowercase",
    "upper": "to_uppercase",
    "startswith": "starts_with",
    "endswith": "ends_with",
    "items": "iter",
    "keys": "keys",
    "values": "values",
    "extend": "extend",
    "replace": "replace",
    "split": "split",
    "join": "join",
    "format": "format",
    "count": "matches",
    "find": "find",
    "index": "find",
    "isdigit": "chars().all(|c| c.is_ascii_digit())",
    "isalpha": "chars().all(|c| c.is_alphabetic())",
}

# Module-level constants accessed as attributes (e.g. math.pi)
_MODULE_CONSTANTS: Dict[str, Dict[str, str]] = {
    "math": {
        "pi": "std::f64::consts::PI",
        "e": "std::f64::consts::E",
        "inf": "f64::INFINITY",
        "nan": "f64::NAN",
        "tau": "std::f64::consts::TAU",
    },
    "sys": {
        "maxsize": "i64::MAX",
        "maxunicode": "0x10FFFF_i64",
        "platform": "std::env::consts::OS",
        "argv": "std::env::args().collect::<Vec<String>>()",
        "stdin": "std::io::stdin()",
        "stdout": "std::io::stdout()",
        "stderr": "std::io::stderr()",
        "path": "Vec::<String>::new()",
        "version_info": "(0, 0, 0)",
    },
    "os": {
        "sep": "std::path::MAIN_SEPARATOR.to_string()",
        "linesep": r'"\\n".to_string()',
        "name": '"posix"',
        "environ": "std::env::vars().collect::<std::collections::HashMap<String, String>>()",
        "devnull": r'"NUL"',
        "curdir": r'"."',
        "pardir": r'".."',
    },
    "time": {},  # time module constants are rare
    "datetime": {},
    "logging": {
        "DEBUG": "log::Level::Debug",
        "INFO": "log::Level::Info",
        "WARNING": "log::Level::Warn",
        "ERROR": "log::Level::Error",
        "CRITICAL": "log::Level::Error",
    },
    "subprocess": {
        "PIPE": "std::process::Stdio::piped()",
        "DEVNULL": "std::process::Stdio::null()",
        "STDOUT": "std::process::Stdio::inherit()",
    },
}


def _try_module_constant(node: ast.expr) -> str:
    """Check if node is a known module constant (math.pi, sys.maxsize, etc.)."""
    if isinstance(node.value, ast.Name):
        mod_consts = _MODULE_CONSTANTS.get(node.value.id)
        if mod_consts:
            rust_val = mod_consts.get(node.attr)
            if rust_val:
                return rust_val
    return ""


def _is_comment_expr(obj: str) -> bool:
    """Check if obj is a comment/todo fallback expression."""
    stripped = obj.strip()
    return stripped.startswith("/*") and (
        stripped.endswith("*/") or stripped.endswith("todo!()")
    )


def _expr_attribute(node: ast.expr) -> str:
    """Attribute access: obj.attr with Python→Rust renames and module constants."""
    obj = _expr(node.value)
    # Check for known module constants: math.pi, sys.maxsize, etc.
    result = _try_module_constant(node)
    if result:
        return result
    # If obj is a comment/todo fallback, wrap entire chain as comment+todo
    if _is_comment_expr(obj):
        return _todo_comment(node)
    # Rename or escape the attribute name
    attr = _ATTR_RENAMES.get(node.attr, node.attr)
    if attr in _RUST_RESERVED:
        attr = f"r#{attr}"
    return f"{obj}.{attr}"


def _expr_binop(node: ast.expr) -> str:
    """Binary operators: +, -, *, /, **, //, %."""
    left, right = _expr(node.left), _expr(node.right)
    if isinstance(node.op, ast.Pow):
        return f"{left}.pow({right} as u32)"
    if isinstance(node.op, ast.FloorDiv):
        return f"({left} / {right})"
    # Python str % args → Rust format!()
    if isinstance(node.op, ast.Mod):
        if isinstance(node.left, (ast.Constant, ast.JoinedStr)):
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                return _format_percent_string(node.left.value, node.right)
        # Non-string mod → regular %
    return f"({left} {_OP_MAP.get(type(node.op), '+')} {right})"


def _format_percent_string(template: str, args_node) -> str:
    """Convert Python 'template' % args to Rust format!()."""
    # First, protect %% (literal percent) by replacing with a sentinel
    rust_fmt = template.replace("%%", "\x00PERCENT\x00")
    # Escape for Rust string
    rust_fmt = rust_fmt.replace("\\", "\\\\").replace('"', '\\"')
    rust_fmt = rust_fmt.replace("\n", "\\n").replace("\r", "").replace("\t", "\\t")
    rust_fmt = rust_fmt.replace("{", "{{").replace("}", "}}")
    # Convert %s, %d, %f, %r, etc. to {}
    rust_fmt = re.sub(r"%-?\d*\.?\d*[sdrfeEgGboxXi]", "{}", rust_fmt)
    # Restore literal percent
    rust_fmt = rust_fmt.replace("\x00PERCENT\x00", "%")
    # Build args list
    if isinstance(args_node, ast.Tuple):
        args_str = ", ".join(_expr(e) for e in args_node.elts)
    else:
        args_str = _expr(args_node)
    placeholder_count = rust_fmt.count("{}")
    if placeholder_count == 0:
        return f'"{rust_fmt}".to_string()'
    return f'format!("{rust_fmt}", {args_str})'


def _expr_unaryop(node: ast.expr) -> str:
    """Unary operators: +, -, not, ~."""
    return f"{_UNARY_MAP.get(type(node.op), '!')}{_expr(node.operand)}"


def _expr_boolop(node: ast.expr) -> str:
    """Boolean operators: and / or."""
    op = " && " if isinstance(node.op, ast.And) else " || "
    return f"({op.join(_expr(v) for v in node.values)})"


# ── Compare helpers ───────────────────────────────────────────────────


def _coerce_float_literal(left_node, comp_node, left_str, right_str):
    """Coerce int literals to float when comparing with float values/params."""
    if _is_plain_int(comp_node) and _is_float_context(left_node):
        right_str = f"{comp_node.value}.0"
    if _is_plain_int(left_node) and _is_float_context(comp_node):
        left_str = f"{left_node.value}.0"
    return left_str, right_str


def _is_plain_int(node) -> bool:
    """Check if node is an int constant (not bool)."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _is_float_context(node) -> bool:
    """Check if node represents a float value or known float parameter."""
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return True
    return isinstance(node, ast.Name) and node.id in _FLOAT_PARAMS


def _compare_contains(left: str, comp_node, negated: bool = False) -> str:
    """Handle 'in' / 'not in' operators."""
    right = _expr(comp_node)
    prefix = "!" if negated else ""
    if isinstance(comp_node, (ast.List, ast.Set, ast.Tuple)):
        has_str = any(
            isinstance(e, ast.Constant) and isinstance(e.value, str)
            for e in comp_node.elts
        )
        ref = f"&{left}.as_str()" if has_str else f"&{left}"
        return f"{prefix}{right}.contains({ref})"
    return f"{prefix}{right}.contains({left})"


def _compare_identity(left: str, comp_node, negated: bool = False) -> str:
    """Handle 'is' / 'is not' operators."""
    if isinstance(comp_node, ast.Constant) and comp_node.value is None:
        return f"{left}.is_some()" if negated else f"{left}.is_none()"
    right = _expr(comp_node)
    return f"{left} {'!=' if negated else '=='} {right}"


_CMP_OP_HANDLERS: Dict[type, Callable] = {
    ast.In: lambda left, cmp: _compare_contains(left, cmp),
    ast.NotIn: lambda left, cmp: _compare_contains(left, cmp, negated=True),
    ast.Is: lambda left, cmp: _compare_identity(left, cmp),
    ast.IsNot: lambda left, cmp: _compare_identity(left, cmp, negated=True),
}


def _expr_compare(node: ast.expr) -> str:
    """Comparison chains: a < b < c → a < b && b < c."""
    parts = []
    left_str, left_node = _expr(node.left), node.left
    for op, comparator in zip(node.ops, node.comparators):
        right_str = _expr(comparator)
        left_str, right_str = _coerce_float_literal(
            left_node, comparator, left_str, right_str
        )
        handler = _CMP_OP_HANDLERS.get(type(op))
        if handler:
            parts.append(handler(left_str, comparator))
        else:
            sym = _CMP_MAP.get(type(op), "==")
            parts.append(f"{left_str} {sym} {right_str}")
        left_str, left_node = right_str, comparator
    return " && ".join(parts) if len(parts) > 1 else parts[0]


def _expr_subscript(node: ast.expr) -> str:
    """Subscript/indexing: a[b], a[1:2], a[-1].

    Phase 3: Auto-clone HashMap/Vec values to avoid borrow checker errors.
    """
    obj = _expr(node.value)
    sl = node.slice
    if isinstance(sl, ast.Slice):
        lower = _resolve_slice_bound(sl.lower, obj) if sl.lower else "0"
        upper = _resolve_slice_bound(sl.upper, obj) if sl.upper else ""
        return f"&{obj}[{lower}..{upper}]" if upper else f"&{obj}[{lower}..]"
    # Handle negative indexing: arr[-1] → arr[arr.len() - 1]
    neg = _negative_index_value(sl)
    if neg is not None:
        return f"{obj}[{obj}.len() - {neg}]"
    # Phase 3: For HashMap access via dict[key], clone the result to avoid
    # borrow checker issues when the value is used across multiple statements
    idx_expr = _expr(sl)
    result = f"{obj}[{idx_expr}]"
    # Heuristic: if obj looks like a HashMap (common var names), add .clone()
    if any(
        hint in obj.lower() for hint in ("map", "dict", "config", "options", "settings")
    ):
        result = f"{result}.clone()"
    return result


def _negative_index_value(node) -> int | None:
    """Return the positive offset N if node represents -N, else None."""
    # ast.UnaryOp(op=USub, operand=Constant(int))
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and node.operand.value > 0
    ):
        return node.operand.value
    # ast.Constant with negative int (Python may fold -1 to Constant(-1))
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and node.value < 0
    ):
        return -node.value
    return None


def _resolve_slice_bound(node, obj: str) -> str:
    """Resolve a slice bound, handling negative values."""
    neg = _negative_index_value(node)
    if neg is not None:
        return f"{obj}.len() - {neg}"
    return _expr(node)


def _expr_ifexp(node: ast.expr) -> str:
    """Ternary: a if cond else b → if cond { a } else { b }."""
    return (
        f"if {_expr(node.test)} "
        f"{{ {_expr(node.body)} }} else {{ {_expr(node.orelse)} }}"
    )


def _expr_list(node: ast.expr) -> str:
    """List literal → vec![]."""
    if not node.elts:
        return "vec![]"
    return f"vec![{', '.join(_expr(e) for e in node.elts)}]"


def _expr_tuple(node: ast.expr) -> str:
    """Tuple literal → (a, b) or vec![] for large tuples."""
    elts = ", ".join(_expr(e) for e in node.elts)
    if len(node.elts) > 2:
        return f"vec![{elts}]"
    if len(node.elts) == 1:
        return f"({elts},)"
    return f"({elts})"


def _expr_dict(node: ast.expr) -> str:
    """Dict literal → HashMap::from([...])."""
    if not node.keys:
        return "HashMap::new()"
    pairs = []
    comments = []
    for k, v in zip(node.keys, node.values):
        if k is None:
            # dict unpacking (**expr) can't be represented in Rust HashMap::from;
            # emit as comment OUTSIDE the brackets to avoid dangling commas
            comments.append(f"/* **{_expr(v)} */")
        else:
            pairs.append(f"({_expr(k)}, {_expr(v)})")
    inner = ", ".join(pairs) if pairs else ""
    prefix = " ".join(comments) + " " if comments else ""
    if not pairs:
        return f"{prefix}HashMap::new()"
    return f"{prefix}HashMap::from([{inner}])"


def _expr_set(node: ast.expr) -> str:
    """Set literal → HashSet::from([...])."""
    return f"HashSet::from([{', '.join(_expr(e) for e in node.elts)}])"


def _convert_fstring_spec(format_spec) -> str:
    """Convert Python f-string format spec to Rust format spec."""
    if not format_spec:
        return ""
    spec_parts = []
    for sv in format_spec.values:
        if isinstance(sv, ast.Constant):
            spec_parts.append(str(sv.value))
    raw_spec = "".join(spec_parts)
    # Datetime format specs (%H, %M, %S, etc.) → not valid in Rust format!
    if "%" in raw_spec:
        return ""
    # Python: ":.1f" → Rust: ":.1" | ":25s" → ":<25" | ":s"/":d" → ""
    rust_spec = re.sub(r"([0-9.])[fsdeEgGbBoxXn%]$", r"\1", raw_spec)
    rust_spec = re.sub(r"^[fsdeEgGbBoxXn]$", "", rust_spec)
    rust_spec = re.sub(r"^(\d+)$", r"<\1", rust_spec)
    return ":" + rust_spec if rust_spec else ""


def _expr_joinedstr(node: ast.expr) -> str:
    """f-string → format!("...", args)."""
    parts_fmt, parts_args = [], []
    for val in node.values:
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            # Escape the literal part using shared char-by-char escaper
            parts_fmt.append(_escape_for_rust(val.value, wrap_braces=True))
        elif isinstance(val, ast.FormattedValue):
            parts_fmt.append(f"{{{_convert_fstring_spec(val.format_spec)}}}")
            parts_args.append(_expr(val.value))
        else:
            parts_fmt.append("{}")
            parts_args.append(_expr(val))
    fmt_str = "".join(parts_fmt)
    if parts_args:
        return f'format!("{fmt_str}", {", ".join(parts_args)})'
    return f'"{fmt_str}".to_string()'


def _expr_lambda(node: ast.expr) -> str:
    """Lambda → Rust closure."""
    params = [arg.arg for arg in node.args.args]
    return f"|{', '.join(params)}| {_expr(node.body)}"


# ── Comprehension handlers ───────────────────────────────────────────


def _transpile_comprehension(node) -> str:
    """[expr for x in iter if cond] → iter.filter().map().collect()"""
    if not node.generators:
        return "vec![]"
    gen = node.generators[0]
    target = _expr(gen.target)
    chain = f"{_expr(gen.iter)}.iter()"
    for cond in gen.ifs:
        chain += f".filter(|{target}| {_expr(cond)})"
    elt = _expr(node.elt)
    if elt != target:
        chain += f".map(|{target}| {elt})"
    if isinstance(node, ast.SetComp):
        chain += ".collect::<HashSet<_>>()"
    else:
        chain += ".collect::<Vec<_>>()"
    if len(node.generators) > 1:
        chain += " /* TODO: nested comprehension */"
    return chain


def _transpile_dict_comprehension(node: ast.DictComp) -> str:
    """{k: v for x in iter if cond} → iter.map(|x| (k,v)).collect()"""
    if not node.generators:
        return "HashMap::new()"
    gen = node.generators[0]
    target = _expr(gen.target)
    chain = f"{_expr(gen.iter)}.iter()"
    for cond in gen.ifs:
        chain += f".filter(|{target}| {_expr(cond)})"
    chain += f".map(|{target}| ({_expr(node.key)}, {_expr(node.value)}))"
    chain += ".collect::<HashMap<_, _>>()"
    return chain


# ═══════════════════════════════════════════════════════════════════════════
#  Expression Dispatcher
# ═══════════════════════════════════════════════════════════════════════════

_EXPR_DISPATCH: Dict[type, Callable] = {
    ast.Constant: _expr_constant,
    ast.Name: _expr_name,
    ast.Attribute: _expr_attribute,
    ast.BinOp: _expr_binop,
    ast.UnaryOp: _expr_unaryop,
    ast.BoolOp: _expr_boolop,
    ast.Compare: _expr_compare,
    ast.Call: lambda n: _transpile_call(n),  # forward ref — resolved at call time
    ast.Subscript: _expr_subscript,
    ast.Starred: lambda n: f"/* *{_expr(n.value)} */",
    ast.IfExp: _expr_ifexp,
    ast.List: _expr_list,
    ast.Tuple: _expr_tuple,
    ast.Dict: _expr_dict,
    ast.Set: _expr_set,
    ast.ListComp: _transpile_comprehension,
    ast.SetComp: _transpile_comprehension,
    ast.GeneratorExp: _transpile_comprehension,
    ast.DictComp: _transpile_dict_comprehension,
    ast.JoinedStr: _expr_joinedstr,
    ast.Lambda: _expr_lambda,
    ast.Await: lambda n: f"{_expr(n.value)}.await",
}


def _todo_comment(node) -> str:
    """Produce a /* ... */ todo!() comment for an unhandled node."""
    try:
        return f"/* {ast.unparse(node)} */ todo!()"
    except Exception:
        return "/* ??? */ todo!()"


def _expr(node: ast.expr) -> str:
    """Recursively convert a Python AST expression to a Rust expression string."""
    if node is None:
        return "()"
    handler = _EXPR_DISPATCH.get(type(node))
    if handler is not None:
        result = handler(node)
        # Ensure expressions used as values have actual Rust expression, not just comment
        stripped = result.strip()
        if stripped.startswith("/*") and stripped.endswith("*/"):
            return f"{stripped} todo!()"
        return result
    return _todo_comment(node)


def _ensure_expr(value: str) -> str:
    """Ensure value is a real Rust expression, not just a comment."""
    stripped = value.strip()
    # Already has todo!() or is a real expression → fine
    if stripped.endswith("todo!()"):
        return value
    if stripped.startswith("/*") and stripped.endswith("*/"):
        return f"{stripped} todo!()"
    return value


# ═══════════════════════════════════════════════════════════════════════════
#  Call Handlers  (builtin functions + method calls → Rust)
# ═══════════════════════════════════════════════════════════════════════════


def _try_unwrap_format(expr: str):
    """Try unwrapping format!(...) into its inner literal. Returns inner or None."""
    if not expr.startswith("format!("):
        return None
    if not expr.rstrip().endswith(")"):
        return None
    inner = expr.rstrip()[len("format!(") : -1]
    if inner.lstrip().startswith('"'):
        return inner
    return None


def _format_println_arg(a: str) -> str:
    """Format a single argument for println!()."""
    inner = _try_unwrap_format(a)
    if inner is not None:
        return f"println!({inner})"
    if a.startswith('"') and a.endswith('"'):
        return f"println!({a})"
    return f'println!("{{}}", {a})'


def _call_print(args, _kw):
    """print(...) → println!(...)."""
    if not args:
        return "println!()"
    if len(args) == 1:
        return _format_println_arg(args[0])
    fmt = " ".join("{}" for _ in args)
    return f'println!("{fmt}", {", ".join(args)})'


def _call_range(args, _kw):
    """range(...) → Rust range expressions."""
    if len(args) == 1:
        return f"0..{args[0]}"
    if len(args) == 2:
        return f"{args[0]}..{args[1]}"
    if len(args) == 3:
        return f"({args[0]}..{args[1]}).step_by({args[2]} as usize)"
    return "0..0"


def _call_sorted(args, kwargs):
    """sorted(...) → Rust sort + optional reverse."""
    base = args[0] if args else "vec![]"
    rev = kwargs.get("reverse", "false")
    if rev == "true":
        return f"{{ let mut v = {base}.clone(); v.sort(); v.reverse(); v }}"
    return f"{{ let mut v = {base}.clone(); v.sort(); v }}"


def _call_round(args, _kw):
    """round(...) → Rust round equivalents."""
    if not args:
        return "0"
    if len(args) >= 2:
        return (
            f"(({args[0]} * 10f64.powi({args[1]} as i32)).round()"
            f" / 10f64.powi({args[1]} as i32))"
        )
    return f"({args[0]} as f64).round() as i64"


def _call_min_max(name, args, _kw):
    """min/max → Rust equivalents."""
    if len(args) == 2:
        return f"{args[0]}.{name}({args[1]})"
    all_args = ", ".join(args)
    return f"[{all_args}].iter().copied().{name}().unwrap()"


# Simple builtin rewrites: name → lambda(args, kwargs) → Rust string
_BUILTIN_SIMPLE: Dict[str, Callable] = {
    "len": lambda a, _: f"{a[0]}.len()" if a else "0",
    "str": lambda a, _: f"{a[0]}.to_string()" if a else '"".to_string()',
    "int": lambda a, _: f"({a[0]} as i64)" if a else "0",
    "float": lambda a, _: f"({a[0]} as f64)" if a else "0.0",
    "bool": lambda a, _: f"({a[0]} != 0)" if a else "false",
    "abs": lambda a, _: f"{a[0]}.abs()" if a else "0",
    "sum": lambda a, _: f"{a[0]}.iter().sum::<i64>()" if a else "0",
    "reversed": lambda a, _: f"{a[0]}.iter().rev()" if a else "vec![].iter().rev()",
    "enumerate": lambda a, _: (
        f"{a[0]}.iter().enumerate()" if a else "vec![].iter().enumerate()"
    ),
    "isinstance": lambda a, _: f"/* isinstance({', '.join(a)}) */ true",
    "hasattr": lambda a, _: f"/* hasattr({', '.join(a)}) */ true",
    "type": lambda a, _: f'/* type({", ".join(a)}) */ "unknown"',
    "dict": lambda _a, _: "HashMap::new()",
    "set": lambda a, _: (
        f"{a[0]}.into_iter().collect::<HashSet<_>>()" if a else "HashSet::new()"
    ),
    "list": lambda a, _: (
        f"{a[0]}.into_iter().collect::<Vec<_>>()" if a else "Vec::new()"
    ),
    "tuple": lambda a, _: f"/* tuple({', '.join(a)}) */",
    "open": lambda a, _: (
        f"std::fs::read_to_string({a[0]}).unwrap_or_default()"
        if a
        else 'std::fs::read_to_string("").unwrap_or_default()'
    ),
    "any": lambda a, _: f"{a[0]}.iter().any(|x| *x)" if a else "false",
    "all": lambda a, _: f"{a[0]}.iter().all(|x| *x)" if a else "true",
    "ord": lambda a, _: f"{a[0]}.chars().next().unwrap() as u32" if a else "0",
    "chr": lambda a, _: f"char::from_u32({a[0]} as u32).unwrap()" if a else "' '",
    "print": _call_print,
    "range": _call_range,
    "round": _call_round,
    "sorted": _call_sorted,
    "min": lambda a, k: _call_min_max("min", a, k),
    "max": lambda a, k: _call_min_max("max", a, k),
}


def _builtin_zip(args, all_args):
    if len(args) == 2:
        return f"{args[0]}.iter().zip({args[1]}.iter())"
    return f"/* zip({all_args}) */"


def _builtin_map(args, all_args):
    return f"{args[1]}.iter().map({args[0]})" if len(args) >= 2 else None


def _builtin_filter(args, all_args):
    return f"{args[1]}.iter().filter({args[0]})" if len(args) >= 2 else None


def _builtin_getattr(args, all_args):
    if len(args) >= 3:
        return f"/* getattr */ {args[2]}"
    return f"/* getattr({all_args}) */"


def _builtin_format(args, all_args):
    if args and args[0].startswith('"'):
        return f"format!({all_args})"
    if args:
        return f'format!("{{}}", {args[0]})'
    return '"".to_string()'


_BUILTIN_COMPLEX_DISPATCH = {
    "zip": _builtin_zip,
    "map": _builtin_map,
    "filter": _builtin_filter,
    "getattr": _builtin_getattr,
    "format": _builtin_format,
}


def _call_builtin_complex(name, args, kwargs):
    """Handle remaining builtins: zip, map, filter, getattr, format."""
    all_args = ", ".join(args)
    handler = _BUILTIN_COMPLEX_DISPATCH.get(name)
    if handler:
        return handler(args, all_args)
    return None  # not handled


# ── Module-specific call handlers ─────────────────────────────────────


def _python_fmt_to_rust(s: str) -> str:
    """Convert Python %-style format specifiers in a Rust string literal to {} placeholders.
    E.g. '"msg: %s val: %d"' → '"msg: {} val: {}"'
    Handles %% → literal % (which in Rust format strings is %% anyway, but
    we keep it as-is since {{ }} escaping is already done).
    """
    if not s.startswith('"'):
        return s
    inner = s[1:-1]  # strip outer quotes
    # Sentinel for %%
    inner = inner.replace("%%", "\x00PCT\x00")
    inner = re.sub(r"%-?\d*\.?\d*[sdfegrioxXcba]", "{}", inner)
    inner = inner.replace("\x00PCT\x00", "%")
    return f'"{inner}"'


def _unwrap_single_format(expr: str) -> str:
    """Unwrap a single format!(...) argument into its inner content."""
    inner = expr[len("format!(") : -1]
    if inner.lstrip().startswith('"'):
        return inner
    return f'"{{}}",  {expr}'


def _ensure_placeholders(fmt_str: str, extra_args) -> str:
    """Ensure fmt_str has enough {} placeholders for extra_args."""
    fmt_str = _python_fmt_to_rust(fmt_str)
    placeholder_count = fmt_str.count("{}")
    if placeholder_count < len(extra_args):
        missing = len(extra_args) - placeholder_count
        inner = fmt_str[1:-1] + " {}" * missing
        fmt_str = f'"{inner}"'
    return fmt_str


def _format_literal_args(fmt_str: str, extra_args) -> str:
    """Format a string-literal first arg with optional extra arguments."""
    if not extra_args:
        return fmt_str
    return f"{_ensure_placeholders(fmt_str, extra_args)}, {', '.join(extra_args)}"


def _unwrap_format_args(args):
    """Unwrap format!(...) from macro arguments so println!/eprintln!/log::*! get a literal."""
    if not args:
        return '""'
    if len(args) == 1 and args[0].startswith("format!("):
        return _unwrap_single_format(args[0])
    a0 = args[0]
    if a0.startswith('"'):
        return _format_literal_args(a0, args[1:])
    fmt = " ".join("{}" for _ in args)
    return f'"{fmt}", {", ".join(args)}'


def _call_logger(method, args, all_args):
    """logger.xxx() → eprintln!()."""
    _LOG_METHODS = {
        "info",
        "debug",
        "warning",
        "error",
        "critical",
        "exception",
        "warn",
    }
    if method in _LOG_METHODS:
        return f"eprintln!({_unwrap_format_args(args)})" if args else "eprintln!()"
    return f"/* logger.{method}({all_args}) */"


_PLATFORM_MAP = {
    "system": "std::env::consts::OS.to_string()",
    "machine": "std::env::consts::ARCH.to_string()",
}


def _call_shutil(method, args, all_args):
    """shutil.xxx() → Rust fs equivalents."""
    if method == "which" and args:
        return (
            f'std::process::Command::new("which")'
            f".arg({args[0]}).output()"
            f".ok().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())"
        )
    if method in ("rmtree", "remove") and args:
        return f"std::fs::remove_dir_all({args[0]}).ok()"
    if method in ("copy2", "copy", "copyfile") and len(args) >= 2:
        return f"std::fs::copy({args[0]}, {args[1]}).ok()"
    return f"/* shutil.{method}({all_args}) */"


_SYS_DISPATCH = {
    "getrecursionlimit": lambda _a: "1000i64",
    "exit": lambda a: (
        f"std::process::exit({a[0]} as i32)" if a else "std::process::exit(0)"
    ),
    "argv": lambda _a: "std::env::args().collect::<Vec<String>>()",
    "getsizeof": lambda a: f"std::mem::size_of_val(&{a[0]}) as i64" if a else None,
    "getdefaultencoding": lambda _a: '"utf-8".to_string()',
    "getfilesystemencoding": lambda _a: '"utf-8".to_string()',
    "version": lambda _a: '"Rust".to_string()',
    "executable": lambda _a: (
        "std::env::current_exe().unwrap().to_string_lossy().to_string()"
    ),
    "modules": lambda _a: "std::collections::HashMap::<String, String>::new()",
}


def _call_sys_method(method, args, all_args):
    """sys.xxx() → Rust equivalents."""
    handler = _SYS_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* sys.{method}({all_args}) */"


_RE_DISPATCH = {
    "compile": lambda a: f"Regex::new({a[0]}).unwrap()" if a else None,
    "search": lambda a: (
        f"Regex::new({a[0]}).unwrap().find(&{a[1]})" if len(a) >= 2 else None
    ),
    "match": lambda a: (
        f'Regex::new(&format!("^{{}}", {a[0]})).unwrap().find(&{a[1]})'
        if len(a) >= 2
        else None
    ),
    "fullmatch": lambda a: (
        f'Regex::new(&format!("^{{}}$", {a[0]})).unwrap().is_match(&{a[1]})'
        if len(a) >= 2
        else None
    ),
    "sub": lambda a: (
        f"Regex::new({a[0]}).unwrap().replace_all(&{a[2]}, {a[1]}).to_string()"
        if len(a) >= 3
        else None
    ),
    "subn": lambda a: (
        f"Regex::new({a[0]}).unwrap().replace_all(&{a[2]}, {a[1]}).to_string()"
        if len(a) >= 3
        else None
    ),
    "findall": lambda a: (
        (
            f"Regex::new({a[0]}).unwrap().find_iter(&{a[1]})"
            f".map(|m| m.as_str().to_string()).collect::<Vec<String>>()"
        )
        if len(a) >= 2
        else None
    ),
    "finditer": lambda a: (
        f"Regex::new({a[0]}).unwrap().find_iter(&{a[1]})" if len(a) >= 2 else None
    ),
    "split": lambda a: (
        (
            f"Regex::new({a[0]}).unwrap().split(&{a[1]})"
            f".map(|s| s.to_string()).collect::<Vec<String>>()"
        )
        if len(a) >= 2
        else None
    ),
    "escape": lambda a: f"regex::escape(&{a[0]})" if a else None,
}


def _call_re(method, args, all_args):
    """re.xxx() → Rust regex crate equivalents."""
    handler = _RE_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* re.{method}({all_args}) */"


_JSON_DISPATCH = {
    "dumps": lambda a, _aa: (
        f"serde_json::to_string(&{a[0]}).unwrap_or_default()" if a else None
    ),
    "loads": lambda a, _aa: (
        f"serde_json::from_str::<serde_json::Value>(&{a[0]}).unwrap()" if a else None
    ),
    "dump": lambda a, _aa: (
        f"serde_json::to_writer(&{a[1]}, &{a[0]}).unwrap()" if len(a) >= 2 else None
    ),
    "load": lambda a, _aa: (
        f"serde_json::from_reader::<_, serde_json::Value>(&{a[0]}).unwrap()"
        if a
        else None
    ),
}


def _call_json(method, args, all_args):
    """json.xxx() → Rust serde_json equivalents."""
    handler = _JSON_DISPATCH.get(method)
    if handler is not None:
        result = handler(args, all_args)
        if result is not None:
            return result
    return f"/* json.{method}({all_args}) */"


def _call_os_path(method, args, all_args):
    """os.path.xxx() → Rust std::path equivalents."""
    _OS_PATH_MAP = {
        "exists": lambda a: f"std::path::Path::new(&{a[0]}).exists()" if a else "false",
        "isfile": lambda a: (
            f"std::path::Path::new(&{a[0]}).is_file()" if a else "false"
        ),
        "isdir": lambda a: f"std::path::Path::new(&{a[0]}).is_dir()" if a else "false",
        "join": lambda a: (
            (
                f"std::path::Path::new(&{a[0]})"
                + "".join(f".join(&{x})" for x in a[1:])
                + ".to_string_lossy().to_string()"
            )
            if a
            else '"".to_string()'
        ),
        "basename": lambda a: (
            (
                f"std::path::Path::new(&{a[0]}).file_name()"
                f".unwrap_or_default().to_string_lossy().to_string()"
            )
            if a
            else '"".to_string()'
        ),
        "dirname": lambda a: (
            (
                f"std::path::Path::new(&{a[0]}).parent()"
                f".map(|p| p.to_string_lossy().to_string())"
                f".unwrap_or_default()"
            )
            if a
            else '"".to_string()'
        ),
        "splitext": lambda a: (
            (
                f"(std::path::Path::new(&{a[0]}).file_stem()"
                f".unwrap_or_default().to_string_lossy().to_string(), "
                f"std::path::Path::new(&{a[0]}).extension()"
                f'.map(|e| format!(".{{}}", e.to_string_lossy()))'
                f".unwrap_or_default())"
            )
            if a
            else '("".to_string(), "".to_string())'
        ),
        "abspath": lambda a: (
            (
                f"std::fs::canonicalize(&{a[0]})"
                f".unwrap_or_default().to_string_lossy().to_string()"
            )
            if a
            else '"".to_string()'
        ),
        "expanduser": lambda a: (
            f"/* os.path.expanduser */ {a[0]}.to_string()" if a else '"".to_string()'
        ),
        "getsize": lambda a: (
            (f"std::fs::metadata(&{a[0]}).map(|m| m.len() as i64).unwrap_or(0)")
            if a
            else "0i64"
        ),
    }
    handler = _OS_PATH_MAP.get(method)
    if handler and args:
        return handler(args)
    return f"/* os.path.{method}({all_args}) */"


def _call_math(method, args, all_args):
    """math.xxx() → Rust f64 / std equivalents."""
    _MATH_CONST = {
        "pi": "std::f64::consts::PI",
        "e": "std::f64::consts::E",
        "inf": "f64::INFINITY",
        "nan": "f64::NAN",
    }
    # Handle math.pi etc. as constants (accessed as attributes, not calls)
    if not args and method in _MATH_CONST:
        return _MATH_CONST[method]
    _MATH_FN_MAP = {
        "sqrt": lambda a: f"({a[0]} as f64).sqrt()",
        "ceil": lambda a: f"({a[0]} as f64).ceil() as i64",
        "floor": lambda a: f"({a[0]} as f64).floor() as i64",
        "log": lambda a: (
            f"({a[0]} as f64).log({a[1]} as f64)"
            if len(a) >= 2
            else f"({a[0]} as f64).ln()"
        ),
        "log2": lambda a: f"({a[0]} as f64).log2()",
        "log10": lambda a: f"({a[0]} as f64).log10()",
        "pow": lambda a: (
            f"({a[0]} as f64).powf({a[1]} as f64)" if len(a) >= 2 else "1.0"
        ),
        "exp": lambda a: f"({a[0]} as f64).exp()",
        "sin": lambda a: f"({a[0]} as f64).sin()",
        "cos": lambda a: f"({a[0]} as f64).cos()",
        "tan": lambda a: f"({a[0]} as f64).tan()",
        "asin": lambda a: f"({a[0]} as f64).asin()",
        "acos": lambda a: f"({a[0]} as f64).acos()",
        "atan": lambda a: f"({a[0]} as f64).atan()",
        "atan2": lambda a: (
            f"({a[0]} as f64).atan2({a[1]} as f64)" if len(a) >= 2 else "0.0"
        ),
        "fabs": lambda a: f"({a[0]} as f64).abs()",
        "isnan": lambda a: f"({a[0]} as f64).is_nan()",
        "isinf": lambda a: f"({a[0]} as f64).is_infinite()",
        "isfinite": lambda a: f"({a[0]} as f64).is_finite()",
        "gcd": lambda a: f"/* math.gcd */ gcd({a[0]}, {a[1]})" if len(a) >= 2 else "0",
        "factorial": lambda a: f"(1..={a[0]} as u64).product::<u64>() as i64",
        "copysign": lambda a: (
            f"({a[0]} as f64).copysign({a[1]} as f64)" if len(a) >= 2 else "0.0"
        ),
        "trunc": lambda a: f"({a[0]} as f64).trunc() as i64",
        "hypot": lambda a: (
            f"({a[0]} as f64).hypot({a[1]} as f64)" if len(a) >= 2 else "0.0"
        ),
    }
    handler = _MATH_FN_MAP.get(method)
    if handler and args:
        return handler(args)
    return f"/* math.{method}({all_args}) */"


_OS_DISPATCH = {
    "getcwd": lambda _a: (
        "std::env::current_dir().unwrap().to_string_lossy().to_string()"
    ),
    "getenv": lambda a: f"std::env::var({a[0]}).unwrap_or_default()" if a else None,
    "environ": lambda a: f"std::env::var({a[0]}).unwrap_or_default()" if a else None,
    "listdir": lambda a: (
        (
            f"std::fs::read_dir({a[0]}).unwrap()"
            f".filter_map(|e| e.ok().map(|e| e.file_name().to_string_lossy().to_string()))"
            f".collect::<Vec<String>>()"
        )
        if a
        else None
    ),
    "makedirs": lambda a: f"std::fs::create_dir_all({a[0]}).ok()" if a else None,
    "remove": lambda a: f"std::fs::remove_file({a[0]}).ok()" if a else None,
    "rename": lambda a: (
        f"std::fs::rename({a[0]}, {a[1]}).ok()" if len(a) >= 2 else None
    ),
}


def _call_os(method, args, all_args):
    """os.xxx() → Rust std equivalents."""
    handler = _OS_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* os.{method}({all_args}) */"


_TIME_DISPATCH = {
    "time": lambda _a: (
        "std::time::SystemTime::now()"
        ".duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64()"
    ),
    "sleep": lambda a: (
        f"std::thread::sleep(std::time::Duration::from_secs_f64({a[0]} as f64))"
        if a
        else None
    ),
    "perf_counter": lambda _a: "std::time::Instant::now().elapsed().as_secs_f64()",
    "monotonic": lambda _a: "std::time::Instant::now().elapsed().as_secs_f64()",
    "strftime": lambda a: (
        f"chrono::Local::now().format({a[0]}).to_string()" if a else None
    ),
    "gmtime": lambda _a: "chrono::Utc::now()",
    "localtime": lambda _a: "chrono::Local::now()",
    "mktime": lambda a: "/* time.mktime */ 0i64" if a else None,
    "process_time": lambda _a: "std::time::Instant::now().elapsed().as_secs_f64()",
    "thread_time": lambda _a: "std::time::Instant::now().elapsed().as_secs_f64()",
}


def _call_time(method, args, all_args):
    """time.xxx() → Rust std::time / chrono equivalents."""
    handler = _TIME_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* time.{method}({all_args}) */"


_DATETIME_DISPATCH = {
    "now": lambda _a: "chrono::Local::now()",
    "utcnow": lambda _a: "chrono::Utc::now()",
    "today": lambda _a: "chrono::Local::now().date_naive()",
    "fromtimestamp": lambda a: (
        (f"chrono::DateTime::from_timestamp({a[0]} as i64, 0).unwrap_or_default()")
        if a
        else None
    ),
    "strftime": lambda a: f"self.format({a[0]}).to_string()" if a else None,
    "strptime": lambda a: (
        (f"chrono::NaiveDateTime::parse_from_str({a[0]}, {a[1]}).unwrap()")
        if len(a) >= 2
        else None
    ),
    "isoformat": lambda _a: "self.to_rfc3339()",
    "timestamp": lambda _a: "self.timestamp()",
    "date": lambda _a: "self.date_naive()",
    "combine": lambda a: (
        f"chrono::NaiveDateTime::new({a[0]}, {a[1]})" if len(a) >= 2 else None
    ),
}


def _call_datetime(method, args, all_args):
    """datetime.xxx() → Rust chrono crate equivalents."""
    if method == "replace":
        return f"/* datetime.replace({all_args}) */ self.clone()"
    handler = _DATETIME_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* datetime.{method}({all_args}) */"


def _call_timedelta(method, args, all_args):
    """datetime.timedelta() → chrono::Duration."""
    # timedelta is typically constructed, not called as method
    return f"/* timedelta.{method}({all_args}) */"


def _subprocess_cmd(args, suffix):
    """Build a std::process::Command chain."""
    base = f"std::process::Command::new({args[0]})"
    if len(args) > 1:
        base += f".args(&[{', '.join(args[1:])}])"
    return base + suffix


_SUBPROCESS_DISPATCH = {
    "run": lambda a: _subprocess_cmd(a, ".status().ok()") if a else None,
    "check_output": lambda a: (
        _subprocess_cmd(
            a,
            ".output().map(|o| String::from_utf8_lossy(&o.stdout).to_string()).unwrap_or_default()",
        )
        if a
        else None
    ),
    "check_call": lambda a: _subprocess_cmd(a, ".status().unwrap()") if a else None,
    "call": lambda a: (
        _subprocess_cmd(a, ".status().map(|s| s.code().unwrap_or(-1)).unwrap_or(-1)")
        if a
        else None
    ),
    "Popen": lambda a: _subprocess_cmd(a, ".spawn().ok()") if a else None,
    "PIPE": lambda _a: "std::process::Stdio::piped()",
    "DEVNULL": lambda _a: "std::process::Stdio::null()",
}


def _call_subprocess(method, args, all_args):
    """subprocess.xxx() → Rust std::process::Command equivalents."""
    handler = _SUBPROCESS_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* subprocess.{method}({all_args}) */"


_HASH_MAP = {
    "sha256": "Sha256",
    "sha1": "Sha1",
    "sha512": "Sha512",
    "sha384": "Sha384",
    "md5": "Md5",
    "blake2b": "Blake2b512",
    "blake2s": "Blake2s256",
}

_HASHLIB_SPECIAL = {
    "new": lambda a, aa: f"/* hashlib.new({aa}) */ Vec::new()" if a else None,
    "hexdigest": lambda _a, _aa: 'format!("{:x}", self.finalize())',
    "digest": lambda _a, _aa: 'format!("{:x}", self.finalize())',
    "update": lambda a, _aa: f"self.update({a[0]})" if a else None,
}


def _call_hashlib(method, args, all_args):
    """hashlib.xxx() → Rust sha2/md5 crate equivalents."""
    rust_type = _HASH_MAP.get(method)
    if rust_type:
        return f"{rust_type}::digest({args[0]})" if args else f"{rust_type}::new()"
    handler = _HASHLIB_SPECIAL.get(method)
    if handler is not None:
        result = handler(args, all_args)
        if result is not None:
            return result
    return f"/* hashlib.{method}({all_args}) */"


_ARGPARSE_DISPATCH = {
    "ArgumentParser": lambda a, _aa: (
        f'clap::Command::new("app").about({a[0] if a else chr(34) + chr(34)})'
    ),
    "add_argument": lambda a, _aa: (
        (f".arg(clap::Arg::new({a[0]}).required(true))") if a else None
    ),
    "parse_args": lambda _a, _aa: ".get_matches()",
    "parse_known_args": lambda _a, _aa: ".try_get_matches()",
}


def _call_argparse(method, args, all_args):
    """argparse.xxx() → Rust clap crate equivalents."""
    handler = _ARGPARSE_DISPATCH.get(method)
    if handler is not None:
        result = handler(args, all_args)
        if result is not None:
            return result
    return f"/* argparse.{method}({all_args}) */"


_COLLECTIONS_DISPATCH = {
    "Counter": lambda a: (
        f"{a[0]}.iter().fold(std::collections::HashMap::new(), "
        f"|mut map, item| {{ *map.entry(item).or_insert(0) += 1; map }})"
        if a
        else "std::collections::HashMap::<String, usize>::new()"
    ),
    "defaultdict": lambda _a: "std::collections::HashMap::new()",
    "deque": lambda a: (
        f"std::collections::VecDeque::from({a[0]})"
        if a
        else "std::collections::VecDeque::new()"
    ),
    "OrderedDict": lambda _a: "std::collections::BTreeMap::new()",
    "namedtuple": lambda _a: None,  # fallback to comment
    "ChainMap": lambda _a: None,  # fallback to comment
}


def _call_collections(method, args, all_args):
    """collections.xxx() → Rust std equivalents."""
    handler = _COLLECTIONS_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* collections.{method}({all_args}) */"


_FUNCTOOLS_DISPATCH = {
    "reduce": lambda a, _aa: (
        f"{a[1]}.iter().fold(Default::default(), {a[0]})" if len(a) >= 2 else None
    ),
    "partial": lambda a, _aa: (
        f"/* functools.partial */ move |args| {a[0]}"
        f"({', '.join(a[1:]) if len(a) > 1 else ''}, args)"
        if a
        else None
    ),
    "lru_cache": lambda _a, _aa: "/* #[cached] */",
    "wraps": lambda a, _aa: f"/* functools.wraps({a[0]}) */" if a else None,
    "total_ordering": lambda _a, _aa: "/* #[derive(Ord, PartialOrd)] */",
}


def _call_functools(method, args, all_args):
    """functools.xxx() → Rust equivalents."""
    handler = _FUNCTOOLS_DISPATCH.get(method)
    if handler is not None:
        result = handler(args, all_args)
        if result is not None:
            return result
    return f"/* functools.{method}({all_args}) */"


def _itertools_chain(args):
    """itertools.chain() → Rust .chain() calls."""
    if not args:
        return None
    result = args[0]
    for a in args[1:]:
        result = f"{result}.chain({a})"
    return result


_ITERTOOLS_DISPATCH = {
    "chain": lambda a: _itertools_chain(a),
    "product": lambda a: (
        (
            f"itertools::iproduct!({', '.join(f'{x}.iter()' for x in a)})"
            f".collect::<Vec<_>>()"
        )
        if len(a) >= 2
        else None
    ),
    "permutations": lambda a: (
        (
            f"{a[0]}.iter().permutations("
            f"{a[1] if len(a) > 1 else f'{a[0]}.len()'}).collect::<Vec<_>>()"
        )
        if a
        else None
    ),
    "combinations": lambda a: (
        f"{a[0]}.iter().combinations({a[1]}).collect::<Vec<_>>()"
        if len(a) >= 2
        else None
    ),
    "zip_longest": lambda a: f"itertools::izip!({', '.join(a)})" if a else None,
    "izip": lambda a: f"itertools::izip!({', '.join(a)})" if a else None,
    "groupby": lambda a: f"{a[0]}.iter().group_by(|item| /* key */)" if a else None,
    "count": lambda a: f"({a[0] if a else '0'}..)",
    "repeat": lambda a: f"std::iter::repeat({a[0]})" if a else None,
    "cycle": lambda a: f"{a[0]}.iter().cycle()" if a else None,
    "starmap": lambda a: (
        f"{a[1]}.iter().map(|item| {a[0]}(item))" if len(a) >= 2 else None
    ),
    "islice": lambda a: f"{a[0]}.iter().skip(0).take({a[1]})" if len(a) >= 2 else None,
    "accumulate": lambda a: (
        (
            f"/* itertools.accumulate */ {a[0]}.iter().scan(0, |acc, x| "
            f"{{ *acc += x; Some(*acc) }}).collect::<Vec<_>>()"
        )
        if a
        else None
    ),
}


def _call_itertools(method, args, all_args):
    """itertools.xxx() → Rust itertools crate equivalents."""
    handler = _ITERTOOLS_DISPATCH.get(method)
    if handler:
        result = handler(args)
        if result is not None:
            return result
    return f"/* itertools.{method}({all_args}) */"


_LOG_LEVEL_MAP = {
    "debug": "log::debug!",
    "info": "log::info!",
    "warning": "log::warn!",
    "warn": "log::warn!",
    "error": "log::error!",
    "critical": "log::error!",
    "exception": "log::error!",
}

_LOG_COMMENT_METHODS = {
    "getLogger",
    "basicConfig",
    "setLevel",
    "addHandler",
    "FileHandler",
    "StreamHandler",
    "Formatter",
}


def _call_logging(method, args, all_args):
    """logging.xxx() → Rust log crate macros."""
    macro = _LOG_LEVEL_MAP.get(method)
    if macro:
        return f"{macro}({_unwrap_format_args(args)})" if args else f"{macro}()"
    if method == "basicConfig":
        return "env_logger::init()"
    if method in _LOG_COMMENT_METHODS:
        return f"/* logging.{method}({all_args}) */"
    return f"/* logging.{method}({all_args}) */"


_MODULE_CALL_DISPATCH = {
    "logger": _call_logger,
    "log": _call_logger,
    "platform": lambda m, a, aa: _PLATFORM_MAP.get(
        m, f"/* platform.{m}({aa}) */ String::new()"
    ),
    "shutil": _call_shutil,
    "sys": _call_sys_method,
    "re": _call_re,
    "json": _call_json,
    "math": _call_math,
    "os": _call_os,
    "time": _call_time,
    "datetime": _call_datetime,
    "timedelta": _call_timedelta,
    "subprocess": _call_subprocess,
    "hashlib": _call_hashlib,
    "argparse": _call_argparse,
    "collections": _call_collections,
    "functools": _call_functools,
    "itertools": _call_itertools,
    "logging": _call_logging,
}


# ── Method-on-object handlers ────────────────────────────────────────

# Phase 2: Comprehensive stdlib method mapping for Python -> Rust translations
# Maps Python method names to their Rust equivalents across different types
_METHOD_RENAMES = {
    # String methods
    "append": "push",
    "strip": "trim",
    "lstrip": "trim_start",
    "rstrip": "trim_end",
    "lower": "to_lowercase",
    "capitalize": "to_uppercase",
    "upper": "to_uppercase",
    "startswith": "starts_with",
    "title": "to_uppercase",
    "endswith": "ends_with",
    "items": "iter",
    "isdigit": "chars",
    "isalpha": "chars",
    "isalnum": "chars",
    "isspace": "chars",
    "find": "find",
    "rfind": "rfind",
    "index": "find",
    "rindex": "rfind",
    "count": "matches",
    "replace": "replace",
    "expandtabs": "replace",
    "splitlines": "lines",
    "partition": "split",
    "rpartition": "rsplit",
    "swapcase": "chars",
    "casefold": "to_lowercase",
    "center": "pad_center",
    "ljust": "pad_start",
    "rjust": "pad_end",
    # List/Vec methods
    "extend": "extend",
    "remove": "remove",
    "insert": "insert",
    "reverse": "reverse",
    "sort": "sort",
    "copy": "clone",
    # Dict/HashMap methods
    "get": "get",
    "keys": "keys",
    "values": "values",
    "update": "extend",
    "pop": "remove",
    "popitem": "remove",
    "clear": "clear",
    "setdefault": "entry",
    # Type conversion helpers (context-dependent but useful defaults)
    "isempty": "is_empty",
    "len": "len",
}


def _method_join(obj, args, all_args):
    return f"{args[0]}.join({obj})" if args else f"Vec::<String>::new().join({obj})"


def _method_format(obj, args, all_args):
    # Convert Python positional placeholders {0}, {1} to Rust {}
    if obj.startswith('"'):
        fmt = re.sub(r"\{(\d+)\}", "{}", obj)
        return f"format!({fmt}, {all_args})"
    # Non-literal .format() base: can't use as format! template
    # Fall back to runtime string replacement
    if not all_args:
        return f'format!("{{}}", {obj})'
    # Non-literal with args: generate safe format with all arguments
    # (avoid trailing block comments that break when wrapped in println!)
    placeholders = " ".join("{}" for _ in args)
    return f'format!("{placeholders}", {all_args})'


def _method_split(obj, args, all_args):
    sep = args[0] if args else None
    collect = ".collect::<Vec<&str>>()"
    return (
        f"{obj}.split({sep}){collect}" if sep else f"{obj}.split_whitespace(){collect}"
    )


def _method_rsplit(obj, args, all_args):
    sep = args[0] if args else None
    collect = ".collect::<Vec<&str>>()"
    return (
        f"{obj}.rsplit({sep}){collect}"
        if sep
        else f"{obj}.rsplit_whitespace(){collect}"
    )


def _method_get(obj, args, all_args):
    """Phase 3: dict.get() with auto-clone for borrowed values."""
    if len(args) >= 2:
        # dict.get(key, default) → dict.get(&key).cloned().unwrap_or(default)
        return f"{obj}.get(&{args[0]}).cloned().unwrap_or({args[1]})"
    # dict.get(key) → dict.get(&key).cloned()
    return f"{obj}.get(&{args[0]}).cloned()"


def _method_pop(obj, args, all_args):
    return f"{obj}.remove(&{args[0]})" if args else f"{obj}.pop()"


def _method_update(obj, args, all_args):
    return f"{obj}.extend({all_args})"


_METHOD_SPECIAL_DISPATCH = {
    "join": _method_join,
    "format": _method_format,
    "split": _method_split,
    "rsplit": _method_rsplit,
    "get": _method_get,
    "pop": _method_pop,
    "update": _method_update,
}


def _call_method_special(obj, method, args, all_args):
    """Handle method calls that need custom Rust translation."""
    handler = _METHOD_SPECIAL_DISPATCH.get(method)
    if handler:
        return handler(obj, args, all_args)
    return None


# File/path method handlers
_PATH_METHOD_MAP = {
    "read_text": lambda o, a: f"std::fs::read_to_string(&{o}).unwrap_or_default()",
    "read": lambda o, a: f"std::fs::read_to_string(&{o}).unwrap_or_default()",
    "write_text": lambda o, a: f"std::fs::write(&{o}, {a[0] if a else ''}).ok()",
    "exists": lambda o, a: f"std::path::Path::new(&{o}).exists()",
    "is_file": lambda o, a: f"std::path::Path::new(&{o}).is_file()",
    "is_dir": lambda o, a: f"std::path::Path::new(&{o}).is_dir()",
    "mkdir": lambda o, a: f"std::fs::create_dir_all(&{o}).ok()",
    "iterdir": lambda o, a: f"std::fs::read_dir(&{o}).unwrap()",
    "keys": lambda o, a: f"{o}.keys()",
    "values": lambda o, a: f"{o}.values()",
    "count": lambda o, a: (
        f"({o}.matches({a[0]}).count() as i64)" if a else f"({o}.len() as i64)"
    ),
}


# ── Main call dispatcher ─────────────────────────────────────────────


def _transpile_call(node: ast.Call) -> str:
    """Handle Python function calls → Rust equivalents."""
    args = [_expr(a) for a in node.args]
    kwargs = {kw.arg: _expr(kw.value) for kw in node.keywords if kw.arg}

    # Named function call: func(args)
    if isinstance(node.func, ast.Name):
        return _dispatch_named_call(node.func.id, args, kwargs)

    # Method call: obj.method(args)
    if isinstance(node.func, ast.Attribute):
        return _dispatch_method_call(node, args, kwargs)

    # Complex callable (subscript, nested call, etc.)
    func_expr = _expr(node.func)
    return f"{func_expr}({', '.join(args)})"


def _dispatch_named_call(name, args, kwargs):
    """Dispatch a named function call to the appropriate handler."""
    # Check simple builtins first
    handler = _BUILTIN_SIMPLE.get(name)
    if handler is not None:
        return handler(args, kwargs)
    # Check complex builtins
    result = _call_builtin_complex(name, args, kwargs)
    if result is not None:
        return result
    # Default: call as-is
    return f"{_safe_name(name)}({', '.join(args)})"


_CHAIN_MODULE_DISPATCH = {
    "os.path": _call_os_path,
}


def _try_module_dispatch(node, method, args, all_args):
    """Try dispatching via module or chained-module handlers."""
    if isinstance(node.func.value, ast.Name):
        handler = _MODULE_CALL_DISPATCH.get(node.func.value.id)
        if handler is not None:
            return handler(method, args, all_args)
    if isinstance(node.func.value, ast.Attribute) and isinstance(
        node.func.value.value, ast.Name
    ):
        chain = f"{node.func.value.value.id}.{node.func.value.attr}"
        handler = _CHAIN_MODULE_DISPATCH.get(chain)
        if handler is not None:
            return handler(method, args, all_args)
    return None


def _dispatch_method_call(node, args, kwargs):
    """Dispatch a method call (obj.method) to the appropriate handler."""
    obj = _expr(node.func.value)
    method = node.func.attr
    all_args = ", ".join(args)

    mod_result = _try_module_dispatch(node, method, args, all_args)
    if mod_result is not None:
        return mod_result

    # Special method handlers (join, format, split, get, pop, etc.)
    result = _call_method_special(obj, method, args, all_args)
    if result is not None:
        return result

    # File/path methods
    path_handler = _PATH_METHOD_MAP.get(method)
    if path_handler is not None:
        return path_handler(obj, args)

    # Default: rename method and call, escaping reserved words
    rust_method = _METHOD_RENAMES.get(method, method)
    if rust_method in _RUST_RESERVED:
        rust_method = f"r#{rust_method}"
    return f"{obj}.{rust_method}({all_args})"


# ═══════════════════════════════════════════════════════════════════════════
#  Statement Handlers  (each handles one AST statement type)
# ═══════════════════════════════════════════════════════════════════════════


def _stmt_return(stmt, pad, indent, ret_type):
    """Handle return statements."""
    if stmt.value is None:
        return [f"{pad}return;"]
    val = _ensure_expr(_expr(stmt.value))
    if "String" in ret_type and val.startswith('"') and val.endswith('"'):
        val = f"{val}.to_string()"
    return [f"{pad}return {val};"]


def _stmt_if(stmt, pad, indent, ret_type):
    """Handle if / elif / else chains."""
    lines = [f"{pad}if {_ensure_expr(_expr(stmt.test))} {{"]
    lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
    if not stmt.orelse:
        lines.append(f"{pad}}}")
        return lines
    # elif chain
    if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        lines.extend(_build_elif_chain(stmt.orelse[0], pad, indent, ret_type))
    else:
        lines.append(f"{pad}}} else {{")
        lines.extend(_body(stmt.orelse, indent + 1, ret_type=ret_type))
    lines.append(f"{pad}}}")
    return lines


def _build_elif_chain(node, pad, indent, ret_type):
    """Recursively build elif / else blocks."""
    lines = [f"{pad}}} else if {_ensure_expr(_expr(node.test))} {{"]
    lines.extend(_body(node.body, indent + 1, ret_type=ret_type))
    rest = node.orelse
    while rest:
        if len(rest) == 1 and isinstance(rest[0], ast.If):
            lines.append(f"{pad}}} else if {_ensure_expr(_expr(rest[0].test))} {{")
            lines.extend(_body(rest[0].body, indent + 1, ret_type=ret_type))
            rest = rest[0].orelse
        else:
            lines.append(f"{pad}}} else {{")
            lines.extend(_body(rest, indent + 1, ret_type=ret_type))
            rest = None
    return lines


def _stmt_for(stmt, pad, indent, ret_type):
    """Handle for loops."""
    target = _expr(stmt.target)
    iter_expr = _expr(stmt.iter)
    # Ensure comment-only iterator gets a placeholder
    iter_expr = _ensure_expr(iter_expr)
    if isinstance(stmt.iter, ast.Constant) and isinstance(stmt.iter.value, str):
        iter_expr = f"{iter_expr}.chars()"
    elif isinstance(stmt.iter, (ast.List, ast.Set, ast.Tuple)):
        iter_expr = f"{iter_expr}.iter()"
    # Fix: vec![...] is not a valid pattern in `for` — convert to slice pattern
    if target.startswith("vec![") and target.endswith("]"):
        inner = target[5:-1]
        target = f"[{inner}]"
    lines = [f"{pad}for {target} in {iter_expr} {{"]
    lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
    lines.append(f"{pad}}}")
    return lines


def _stmt_while(stmt, pad, indent, ret_type):
    """Handle while loops."""
    lines = [f"{pad}while {_ensure_expr(_expr(stmt.test))} {{"]
    lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
    lines.append(f"{pad}}}")
    return lines


def _stmt_assign_tuple(tgt, value: str, pad: str) -> List[str]:
    """Handle tuple-target assignment: (a, b) = value."""
    has_complex = any(isinstance(e, (ast.Attribute, ast.Subscript)) for e in tgt.elts)
    if has_complex:
        lines = [f"{pad}let _destructured = {value};"]
        for i, e in enumerate(tgt.elts):
            lines.append(f"{pad}{_expr(e)} = _destructured.{i};")
        return lines
    parts = ", ".join(
        _expr(e) if _expr(e) == "_" else f"mut {_expr(e)}" for e in tgt.elts
    )
    return [f"{pad}let ({parts}) = {value};"]


def _stmt_assign(stmt, pad, _indent, _ret_type):
    """Handle assignment statements."""
    tgt = stmt.targets[0]
    value = _ensure_expr(_expr(stmt.value))
    if isinstance(tgt, ast.Tuple):
        return _stmt_assign_tuple(tgt, value, pad)
    if isinstance(tgt, (ast.Subscript, ast.Attribute)):
        return [f"{pad}{_expr(tgt)} = {value};"]
    return [f"{pad}let mut {_expr(tgt)} = {value};"]


def _stmt_ann_assign(stmt, pad, _indent, _ret_type):
    """Handle annotated assignment (x: int = 5)."""
    target = _expr(stmt.target)
    ann = py_type_to_rust(ast.unparse(stmt.annotation)) if stmt.annotation else "String"
    # self.field: Type = value  → field assignment, not let binding
    if isinstance(stmt.target, ast.Attribute):
        if stmt.value:
            return [f"{pad}{target} = {_ensure_expr(_expr(stmt.value))};"]
        return [f"{pad}// {target}: {ann};"]
    if stmt.value:
        return [f"{pad}let mut {target}: {ann} = {_ensure_expr(_expr(stmt.value))};"]
    return [f"{pad}let mut {target}: {ann};"]


def _stmt_aug_assign(stmt, pad, _indent, _ret_type):
    """Handle augmented assignment (+=, -=, etc.)."""
    op = _OP_MAP.get(type(stmt.op), "+")
    return [f"{pad}{_expr(stmt.target)} {op}= {_expr(stmt.value)};"]


def _stmt_expr(stmt, pad, _indent, _ret_type):
    """Handle expression statements (calls, etc.). Skip docstrings."""
    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
        return []  # skip docstring
    return [f"{pad}{_expr(stmt.value)};"]


def _stmt_assert(stmt, pad, _indent, _ret_type):
    """Handle assert statements."""
    test_expr = _expr(stmt.test)
    if stmt.msg:
        return [f"{pad}assert!({test_expr}, {_expr(stmt.msg)});"]
    return [f"{pad}assert!({test_expr});"]


def _stmt_raise(stmt, pad, _indent, _ret_type):
    """Handle raise statements."""
    if stmt.exc:
        exc = _expr(stmt.exc).replace("{", "{{").replace("}", "}}").replace('"', '\\"')
        return [f'{pad}panic!("{exc}");']
    return [f'{pad}panic!("raised");']


def _stmt_try(stmt, pad, indent, ret_type):
    """Handle try / except / finally → Rust Result + match pattern.

    Translates to:
        match (|| -> Result<(), Box<dyn std::error::Error>> {
            // try body
            Ok(())
        })() {
            Ok(_) => {}
            Err(e) => { // except body }
        }
        // finally body (unconditional)
    """
    inner_pad = "    " * (indent + 2)
    lines = [f"{pad}match (|| -> Result<(), Box<dyn std::error::Error>> {{"]
    lines.extend(_body(stmt.body, indent + 2, ret_type="()"))
    lines.append(f"{inner_pad}Ok(())")
    lines.append(f"{pad}    }})() {{")

    if stmt.handlers:
        for i, handler in enumerate(stmt.handlers):
            exc_type = ast.unparse(handler.type) if handler.type else "Exception"
            err_var = handler.name if handler.name else "_e"
            if i == 0:
                lines.append(f"{pad}    Err({err_var}) => {{ // catch {exc_type}")
            else:
                lines.append(f"{pad}    // also catch {exc_type}")
            lines.extend(_body(handler.body, indent + 2, ret_type=ret_type))
            if i == len(stmt.handlers) - 1:
                lines.append(f"{pad}    }}")
        lines.append(f"{pad}    Ok(_) => {{}}")
    else:
        lines.append(f"{pad}    Ok(_) => {{}}")
        lines.append(f"{pad}    Err(_) => {{}}")

    lines.append(f"{pad}}}")

    # finally → runs unconditionally after match
    if stmt.finalbody:
        lines.append(f"{pad}// finally:")
        lines.extend(_body(stmt.finalbody, indent, ret_type=ret_type))

    # orelse → runs if no exception (else clause)
    if hasattr(stmt, "orelse") and stmt.orelse:
        lines.append(f"{pad}// else (no exception):")
        lines.extend(_body(stmt.orelse, indent, ret_type=ret_type))

    return lines


def _stmt_with(stmt, pad, indent, ret_type):
    """Handle with statements."""
    lines = [f"{pad}{{ // with"]
    for item in stmt.items:
        ctx = _expr(item.context_expr)
        if item.optional_vars:
            lines.append(f"{pad}    let {_expr(item.optional_vars)} = {ctx};")
        else:
            lines.append(f"{pad}    {ctx};")
    lines.extend(_body(stmt.body, indent + 1, ret_type=ret_type))
    lines.append(f"{pad}}}")
    return lines


def _stmt_delete(stmt, pad, _indent, _ret_type):
    """Handle del statements."""
    return [f"{pad}// del {_expr(t)}" for t in stmt.targets]


def _stmt_import(stmt, pad, _indent, _ret_type):
    """Handle import / from...import statements."""
    return [f"{pad}// {ast.unparse(stmt)}"]


# ── Match/case handler (Python 3.10+) ────────────────────────────────


def _match_singleton(pattern):
    """Translate MatchSingleton (True/False/None) to Rust."""
    if pattern.value is True:
        return "true"
    if pattern.value is False:
        return "false"
    return "None"


def _match_as(pattern):
    """Translate MatchAs to Rust pattern binding."""
    if pattern.pattern is None:
        return _safe_name(pattern.name) if pattern.name else "_"
    inner = _match_pattern(pattern.pattern)
    if pattern.name:
        return f"{inner} @ {_safe_name(pattern.name)}"
    return inner


def _match_class(pattern):
    """Translate MatchClass to Rust constructor pattern."""
    cls = _expr(pattern.cls)
    parts = [_match_pattern(p) for p in pattern.patterns]
    for kw, pat in zip(pattern.kwd_attrs, pattern.kwd_patterns):
        parts.append(f"{kw}: {_match_pattern(pat)}")
    return f"{cls}({', '.join(parts)})"


_MATCH_PATTERN_DISPATCH = {
    ast.MatchValue: lambda p: _expr(p.value),
    ast.MatchSingleton: _match_singleton,
    ast.MatchSequence: lambda p: (
        f"[{', '.join(_match_pattern(pp) for pp in p.patterns)}]"
    ),
    ast.MatchMapping: lambda p: (
        f"/* {{{', '.join(f'{_expr(k)}: {_match_pattern(v)}' for k, v in zip(p.keys, p.patterns))}}} */"
    ),
    ast.MatchStar: lambda p: f"{p.name} @ .." if p.name else "..",
    ast.MatchAs: _match_as,
    ast.MatchOr: lambda p: " | ".join(_match_pattern(pp) for pp in p.patterns),
    ast.MatchClass: _match_class,
}


def _match_pattern(pattern) -> str:
    """Translate a Python match pattern to a Rust match arm pattern."""
    handler = _MATCH_PATTERN_DISPATCH.get(type(pattern))
    if handler:
        return handler(pattern)
    try:
        return f"/* {ast.unparse(pattern)} */"
    except Exception:
        return "_"


def _stmt_match(stmt, pad, indent, ret_type):
    """Handle match/case (Python 3.10+) → Rust match.

    Python:
        match command:
            case "quit":
                exit()
            case "hello":
                greet()
            case _:
                unknown()

    Rust:
        match command {
            "quit" => { exit(); }
            "hello" => { greet(); }
            _ => { unknown(); }
        }
    """
    lines = [f"{pad}match {_expr(stmt.subject)} {{"]
    for case in stmt.cases:
        arm_pattern = _match_pattern(case.pattern)
        guard = ""
        if case.guard:
            guard = f" if {_expr(case.guard)}"
        lines.append(f"{pad}    {arm_pattern}{guard} => {{")
        lines.extend(_body(case.body, indent + 2, ret_type=ret_type))
        lines.append(f"{pad}    }}")
    lines.append(f"{pad}}}")
    return lines


# ── Statement dispatch table ─────────────────────────────────────────

_STMT_DISPATCH: Dict[type, Callable] = {
    ast.Return: _stmt_return,
    ast.If: _stmt_if,
    ast.For: _stmt_for,
    ast.While: _stmt_while,
    ast.Assign: _stmt_assign,
    ast.AnnAssign: _stmt_ann_assign,
    ast.AugAssign: _stmt_aug_assign,
    ast.Expr: _stmt_expr,
    ast.Assert: _stmt_assert,
    ast.Raise: _stmt_raise,
    ast.Try: _stmt_try,
    ast.With: _stmt_with,
    ast.Delete: _stmt_delete,
    ast.Import: _stmt_import,
    ast.ImportFrom: _stmt_import,
}

# Python 3.10+ match/case support
if hasattr(ast, "Match"):
    _STMT_DISPATCH[ast.Match] = _stmt_match

# Simple one-liner statements
_STMT_SIMPLE = {
    ast.Pass: lambda _s, pad, _i, _r: [f"{pad}// pass"],
    ast.Break: lambda _s, pad, _i, _r: [f"{pad}break;"],
    ast.Continue: lambda _s, pad, _i, _r: [f"{pad}continue;"],
}


def _stmt_nested_function(stmt, pad: str, indent: int, ret_type: str) -> List[str]:
    """Translate nested function def → Rust closure.

    Python:
        def helper(x, y):
            return x + y

    Rust:
        let helper = |x: String, y: String| -> String {
            return (x + y);
        };
    """
    func_name = _safe_name(stmt.name)
    # Build closure params
    params = []
    for arg in stmt.args.args:
        if arg.arg == "self":
            continue
        atype = (
            py_type_to_rust(ast.unparse(arg.annotation)) if arg.annotation else "String"
        )
        params.append(f"{_safe_name(arg.arg)}: {atype}")
    params_str = ", ".join(params)

    # Return type
    if stmt.returns:
        rtype = py_type_to_rust(ast.unparse(stmt.returns))
    else:
        rtype = "()"

    lines = [f"{pad}let {func_name} = |{params_str}| -> {rtype} {{"]
    lines.extend(_body(stmt.body, indent + 1, ret_type=rtype))
    lines.append(f"{pad}}};")
    return lines


def _infer_field_type(value_node: ast.expr) -> str:
    """Infer a Rust type from a Python assignment value node."""
    if isinstance(value_node, ast.Constant):
        _CONST_FIELD_TYPES = {bool: "bool", int: "i64", float: "f64", str: "String"}
        return _CONST_FIELD_TYPES.get(type(value_node.value), "String")
    if isinstance(value_node, ast.List):
        return "Vec<String>"
    if isinstance(value_node, ast.Dict):
        return "HashMap<String, String>"
    return "String"


def _extract_init_fields(init_func) -> Dict[str, str]:
    """Extract self.x = ... assignments from __init__ as {name: rust_type}."""
    fields: Dict[str, str] = {}
    for sub in ast.walk(init_func):
        if not isinstance(sub, ast.Assign) or not sub.targets:
            continue
        tgt = sub.targets[0]
        if not isinstance(tgt, ast.Attribute):
            continue
        if not isinstance(tgt.value, ast.Name) or tgt.value.id != "self":
            continue
        fields[tgt.attr] = _infer_field_type(sub.value)
    return fields


def _extract_class_fields(body: List) -> Tuple[Dict[str, str], List]:
    """Extract fields and methods from a class body for Rust struct generation."""
    fields: Dict[str, str] = {}
    methods: List[ast.FunctionDef] = []

    for item in body:
        if isinstance(item, ast.FunctionDef):
            if item.name == "__init__":
                fields.update(_extract_init_fields(item))
            else:
                methods.append(item)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            ftype = (
                py_type_to_rust(ast.unparse(item.annotation))
                if item.annotation
                else "String"
            )
            fields[item.target.id] = ftype

    return fields, methods


def _emit_ctor(class_name: str, fields: dict, pad: str) -> List[str]:
    """Emit a Rust constructor for a struct."""
    ctor_params = ", ".join(f"{fn}: {ft}" for fn, ft in fields.items())
    lines = [f"{pad}    fn new({ctor_params}) -> Self {{"]
    lines.append(f"{pad}        {class_name} {{")
    for fn in fields:
        lines.append(f"{pad}            {fn},")
    lines.append(f"{pad}        }}")
    lines.append(f"{pad}    }}")
    return lines


def _emit_method(meth, pad: str, indent: int) -> List[str]:
    """Emit a single Rust impl method from a Python method AST node."""
    mparams = ["&self"]
    for arg in meth.args.args:
        if arg.arg == "self":
            continue
        atype = (
            py_type_to_rust(ast.unparse(arg.annotation)) if arg.annotation else "String"
        )
        mparams.append(f"{_safe_name(arg.arg)}: {atype}")
    mrtype = py_type_to_rust(ast.unparse(meth.returns)) if meth.returns else "()"
    lines = [
        f"{pad}    fn {_safe_name(meth.name)}({', '.join(mparams)}) -> {mrtype} {{"
    ]
    lines.extend(_body(meth.body, indent + 2, ret_type=mrtype))
    lines.append(f"{pad}    }}")
    return lines


def _stmt_nested_class(stmt, pad: str, indent: int, _ret_type: str) -> List[str]:
    """Translate nested class def → Rust struct + impl block."""
    class_name = stmt.name
    fields, methods = _extract_class_fields(stmt.body)

    lines = [f"{pad}struct {class_name} {{"]
    for fname, ftype in fields.items():
        lines.append(f"{pad}    {fname}: {ftype},")
    lines.append(f"{pad}}}")
    lines.append("")

    if methods or fields:
        lines.append(f"{pad}impl {class_name} {{")
        if fields:
            lines.extend(_emit_ctor(class_name, fields, pad))
        for meth in methods:
            lines.extend(_emit_method(meth, pad, indent))
        lines.append(f"{pad}}}")

    return lines


def _stmt_fallback(stmt, pad: str) -> List[str]:
    """Handle statement types not in dispatch tables."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Delegate to nested function handler (produces closure)
        indent = len(pad) // 4
        return _stmt_nested_function(stmt, pad, indent, "()")
    if isinstance(stmt, ast.ClassDef):
        # Delegate to nested class handler (produces struct + impl)
        indent = len(pad) // 4
        return _stmt_nested_class(stmt, pad, indent, "()")
    if isinstance(stmt, (ast.Global, ast.Nonlocal)):
        keyword = "global" if isinstance(stmt, ast.Global) else "nonlocal"
        return [f"{pad}// {keyword} {', '.join(stmt.names)}"]
    try:
        comment = f"// TODO: {ast.unparse(stmt).split(chr(10))[0]}"
    except Exception:
        comment = "// TODO: unsupported statement"
    return [f"{pad}{comment}"]


def _body(stmts: list, indent: int = 1, *, ret_type: str = "()") -> List[str]:
    """Translate a list of Python AST statements to Rust source lines."""
    pad = "    " * indent
    lines: List[str] = []
    for stmt in stmts:
        handler = _STMT_DISPATCH.get(type(stmt))
        if handler is not None:
            lines.extend(handler(stmt, pad, indent, ret_type))
            continue
        simple = _STMT_SIMPLE.get(type(stmt))
        if simple is not None:
            lines.extend(simple(stmt, pad, indent, ret_type))
            continue
        lines.extend(_stmt_fallback(stmt, pad))
    return lines


# ═══════════════════════════════════════════════════════════════════════════
#  Top-level: Transpile One Function
# ═══════════════════════════════════════════════════════════════════════════


def transpile_function_code(
    code: str, *, name_hint: str = "", source_info: str = ""
) -> str:
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
    code = textwrap.dedent(code)
    tree = _parse_or_stub(code, name_hint or "unknown", source_info)
    if isinstance(tree, str):
        return tree  # parse error stub

    func_node = _find_func_node(tree)
    if func_node is None:
        fn_name = name_hint or "unknown"
        return (
            f"// No function found: {source_info}\n"
            f'fn {fn_name}() {{\n    todo!("no function in source")\n}}'
        )

    fn_name = _safe_name(name_hint) if name_hint else _safe_name(func_node.name)
    params_str = _build_params(func_node)
    ret_type = _resolve_return_type(func_node)
    return _assemble_function(fn_name, params_str, ret_type, func_node, source_info)


def _parse_or_stub(code, fn_name, source_info):
    """Parse code or return a stub string on SyntaxError."""
    try:
        return ast.parse(code)
    except SyntaxError:
        return (
            f"// Could not parse: {source_info}\n"
            f'fn {fn_name}() {{\n    todo!("parse error")\n}}'
        )


def _find_func_node(tree):
    """Find the first function definition in an AST tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _build_params(func_node) -> str:
    """Build the Rust parameter string from AST function arguments."""
    _FLOAT_PARAMS.clear()
    params = []
    for arg in func_node.args.args:
        if arg.arg in ("self", "cls"):
            continue
        pname = _safe_name(arg.arg)
        ptype = (
            py_type_to_rust(ast.unparse(arg.annotation))
            if arg.annotation
            else _infer_type_from_name(arg.arg)
        )
        if ptype == "f64":
            _FLOAT_PARAMS.add(arg.arg)
        params.append(f"{pname}: {ptype}")
    if func_node.args.vararg:
        params.append(f"{_safe_name(func_node.args.vararg.arg)}: Vec<String>")
    if func_node.args.kwarg:
        params.append(
            f"{_safe_name(func_node.args.kwarg.arg)}: HashMap<String, String>"
        )
    return ", ".join(params)


def _resolve_return_type(func_node) -> str:
    """Determine the Rust return type from annotation or inference."""
    if func_node.returns:
        return py_type_to_rust(ast.unparse(func_node.returns))
    return _infer_return_type(func_node)


def _assemble_function(fn_name, params_str, ret_type, func_node, source_info):
    """Assemble the final Rust function string."""
    lines = []
    if source_info:
        lines.append(f"/// Transpiled from {source_info}")
    is_async = isinstance(func_node, ast.AsyncFunctionDef)
    fn_kw = "async fn" if is_async else "fn"
    lines.append(f"{fn_kw} {fn_name}({params_str}) -> {ret_type} {{")
    body_lines = _body(func_node.body, indent=1, ret_type=ret_type)
    lines.extend(body_lines)
    if ret_type != "()" and body_lines:
        has_return = any(
            "return " in ln or "return;" in ln
            for ln in body_lines
            if ln.strip() and not ln.strip().startswith("//")
        )
        if not has_return:
            lines.append(f'    todo!("return {ret_type}")')
    lines.append("}")
    return "\n".join(lines)


# ── Type inference helpers ────────────────────────────────────────────

_NAME_TYPE_RULES = [
    (("path", "file", "dir", "folder"), "&str"),
    (
        (
            "name",
            "text",
            "msg",
            "code",
            "source",
            "line",
            "pattern",
            "prefix",
            "suffix",
            "key",
            "label",
        ),
        "&str",
    ),
    (
        (
            "count",
            "size",
            "num",
            "index",
            "depth",
            "width",
            "height",
            "limit",
            "max",
            "min",
        ),
        "usize",
    ),
    (("flag", "enable", "disable", "verbose", "force", "recursive", "debug"), "bool"),
    (
        (
            "items",
            "list",
            "values",
            "args",
            "params",
            "names",
            "files",
            "lines",
            "results",
        ),
        "&[String]",
    ),
    (("dict", "map", "config", "options", "settings"), "&HashMap<String, String>"),
]

_SINGLE_LETTER_USIZE = frozenset("nijkxyz")


def _infer_type_from_name(name: str) -> str:
    """Guess a Rust type from a Python parameter name."""
    low = name.lower()
    if low in _SINGLE_LETTER_USIZE:
        return "usize"
    for keywords, rust_type in _NAME_TYPE_RULES:
        if any(k in low for k in keywords):
            return rust_type
    return "&str"


_RETURN_CONST_MAP = {bool: "bool", int: "i64", float: "f64", str: "String"}
_RETURN_NODE_MAP = {
    ast.List: "Vec<String>",
    ast.Dict: "HashMap<String, String>",
}


def _classify_return_value(val) -> str:
    """Determine Rust return type from a single return-value AST node."""
    if isinstance(val, ast.Constant) and type(val.value) in _RETURN_CONST_MAP:
        return _RETURN_CONST_MAP[type(val.value)]
    result = _RETURN_NODE_MAP.get(type(val))
    if not result and isinstance(val, ast.Tuple):
        result = f"({', '.join(['String'] * len(val.elts))})"
    if not result and isinstance(val, (ast.BoolOp, ast.Compare)):
        result = "bool"
    if (
        not result
        and isinstance(val, ast.BinOp)
        and isinstance(val.op, (ast.Add, ast.Sub, ast.Mult))
    ):
        result = "i64"
    return result or "String"


def _infer_return_type(func_node) -> str:
    """Try to infer return type from the function body."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        return _classify_return_value(node.value)
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


# ═══════════════════════════════════════════════════════════════════════════
#  Sanitizer — reject generated Rust that still references Python-only APIs
# ═══════════════════════════════════════════════════════════════════════════

_PYTHON_ONLY_SYMBOLS = {
    "ast",
    "os",
    "re",
    "json",
    "logging",
    "pathlib",
    "concurrent",
    "threading",
    "subprocess",
    "argparse",
    "io",
    "importlib",
    "inspect",
    "traceback",
    "pyo3",
    "typing",
    "collections",
    "functools",
    "itertools",
}

_UNTRANSPILABLE_PATTERNS = [
    r"\bthis\.",
    r"\btuple\(",
    r"\bsuper\(\)",
    r"\bcompile_crate\(",
    r"\btokenize\(",
    r"\b_[A-Z][A-Z_]{2,}\b",
    r'\["[^"]*"\]',
    r'extern\s+"C"',
    r"&\w+\[[^\]]*\]\s*=",
]

_SAFE_RUST_METHODS = {
    "len",
    "push",
    "pop",
    "contains",
    "is_empty",
    "to_string",
    "clone",
    "iter",
    "into_iter",
    "map",
    "filter",
    "collect",
    "any",
    "all",
    "unwrap",
    "unwrap_or",
    "expect",
    "ok",
    "err",
    "is_some",
    "is_none",
    "as_str",
    "trim",
    "split",
    "join",
    "replace",
    "starts_with",
    "ends_with",
    "to_lowercase",
    "to_uppercase",
    "chars",
    "bytes",
    "lines",
    "insert",
    "remove",
    "get",
    "entry",
    "or_insert",
    "extend",
    "sort",
    "sort_by",
    "reverse",
    "dedup",
    "retain",
    "pow",
    "abs",
    "min",
    "max",
    "round",
    "ceil",
    "floor",
    "keys",
    "values",
    "items",
    "find",
    "matches",
    "strip_prefix",
    "strip_suffix",
    "parse",
    "as_ref",
    "display",
    "write",
    "read",
    "flush",
    "result",
    "and_then",
    "or_else",
    "map_err",
    "format",
    "with_capacity",
    "capacity",
    "reserve",
    "as_bytes",
    "as_slice",
    "as_mut_slice",
    "checked_add",
    "checked_sub",
    "checked_mul",
    "to_owned",
    "into",
    "from",
    "default",
    "first",
    "last",
    "skip",
    "take",
    "enumerate",
    "zip",
    "flat_map",
    "fold",
    "reduce",
    "sum",
    "count",
    "step_by",
    "chain",
    "peekable",
    "is_ascii_digit",
    "is_alphabetic",
    "is_ascii",
    "new",
    "with",
    "build",
    "from_utf8",
}


def _sanitize_generated(rust_code: str) -> str:
    """If generated Rust references Python-only symbols, wrap body in todo!()."""
    lines = rust_code.split("\n")
    sig_line, sig_idx = _find_signature(lines)
    if sig_idx < 0:
        return rust_code

    body = "\n".join(lines[sig_idx + 1 :])
    reason = (
        _check_python_symbols(body)
        or _check_patterns(body)
        or _check_field_access(body)
    )
    if not reason:
        return rust_code

    comment_lines = lines[:sig_idx]
    sig = sig_line.rstrip()
    if not sig.endswith("{"):
        sig += " {"
    return "\n".join(comment_lines + [sig, f'    todo!("{reason}")', "}"])


def _find_signature(lines):
    """Find the function signature line and its index."""
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("fn ") or stripped.startswith("pub fn "):
            return line, i
    return "", -1


def _check_python_symbols(body: str):
    """Check for Python-only module symbols in body."""
    stripped = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stripped)
    for sym in _PYTHON_ONLY_SYMBOLS:
        if re.search(rf"\b{sym}\b", stripped):
            return f"Python-only: {sym}"
    return None


def _check_patterns(body: str):
    """Check for untranspilable code patterns."""
    for pat in _UNTRANSPILABLE_PATTERNS:
        if re.search(pat, body):
            return "uses Python class/module pattern"
    if re.search(r'"[^"]*"\s*\*\s*\d+', body) or re.search(r'"[^"]*"\s*\*\s*\w+', body):
        return "uses Python string repetition"
    return None


def _check_field_access(body: str):
    """Check for Python object field access patterns."""
    field_accesses = re.findall(r"\.([a-z_][a-z_0-9]*)\b", body)
    unknown = [f for f in field_accesses if f not in _SAFE_RUST_METHODS]
    if unknown and len(unknown) > max(2, len(field_accesses) * 0.3):
        return "uses Python object fields"
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Batch JSON Transpilation (called by X_Ray.exe)
# ═══════════════════════════════════════════════════════════════════════════


def transpile_batch_json(json_input: str) -> str:
    """Transpile a JSON array of {name, code, file_path, line_start}.

    Interface called by X_Ray.exe via subprocess.
    """
    candidates = json.loads(json_input)
    parts = _batch_preamble()
    from Analysis.llm_transpiler import get_cached_llm_transpiler

    llm_engine = get_cached_llm_transpiler()
    llm_available = llm_engine is not None
    name_counts: Dict[str, int] = {}

    for cand in candidates:
        rust = _transpile_candidate(cand, name_counts, llm_engine, llm_available)
        parts.append(rust)
        parts.append("")

    real_fns = _collect_real_functions(candidates, parts, name_counts)
    _build_main(parts, candidates, real_fns, llm_engine)
    result = "\n".join(parts)
    result = _postprocess_format_specs(result)
    _log_llm_stats(llm_engine)
    return result


def _batch_preamble():
    """Standard Rust preamble for batch output."""
    return [
        "// Auto-generated by X-Ray Hybrid Transpiler (AST + LLM)",
        "#![allow(unused_variables, unused_mut, dead_code, unused_imports)]",
        "#![allow(unreachable_code, unused_assignments)]",
        "",
        "use std::collections::{HashMap, HashSet};",
        "",
    ]


def _transpile_candidate(cand, name_counts, llm_engine, llm_available):
    """Transpile one candidate dict → Rust function string."""
    code = cand.get("code", "")
    name = cand.get("name", "unknown")
    fpath = cand.get("file_path", "")
    line = cand.get("line_start", 0)
    source_info = f"{fpath}:{line}" if fpath else ""
    unique_name = _deduplicate_name(name, fpath, name_counts)

    # AST transpile + sanitize
    rust = transpile_function_code(code, name_hint=unique_name, source_info=source_info)
    rust = _sanitize_generated(rust)

    # LLM fallback if AST produced todo!()
    if "todo!" in rust and llm_available and llm_engine is not None:
        logger.info(f"  AST produced todo!() for {unique_name} — trying LLM...")
        llm_result = llm_engine.transpile(
            code, name_hint=unique_name, source_info=source_info
        )
        if llm_result is not None:
            rust = llm_result
    return rust


def _deduplicate_name(name, fpath, name_counts):
    """Generate a unique Rust function name, de-duplicating repeats."""
    if name in name_counts:
        name_counts[name] += 1
        stem = Path(fpath).stem if fpath else f"mod{name_counts[name]}"
        safe_stem = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
        return f"{safe_stem}__{name}"
    name_counts[name] = 1
    return name


def _collect_real_functions(candidates, parts, name_counts):
    """Identify transpiled functions that compiled to real Rust (no todo!)."""
    real_fns = []
    for cand in candidates:
        name = cand.get("name", "unknown")
        rust_name = name
        if name_counts.get(name, 0) > 1:
            stem = (
                Path(cand.get("file_path", "")).stem if cand.get("file_path") else "mod"
            )
            safe_stem = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
            rust_name = f"{safe_stem}__{name}"
        fn_code = next(
            (
                p
                for p in parts
                if f"fn {rust_name}(" in p or f"fn {_safe_name(rust_name)}(" in p
            ),
            "",
        )
        if fn_code and "todo!" not in fn_code:
            real_fns.append((rust_name, fn_code))
    return real_fns


def _build_main(parts, candidates, real_fns, llm_engine):
    """Build the main() function that exercises transpiled code."""
    n = len(candidates)
    llm_count = sum(1 for p in parts if "LLM-assisted" in p)
    ast_real = sum(1 for _, c in real_fns if "LLM-assisted" not in c)

    parts.append("fn main() {")
    parts.append(
        '    println!("╔══════════════════════════════════════════════════╗");'
    )
    parts.append('    println!("║  X-Ray Rustified Executable (Hybrid)            ║");')
    parts.append(
        f'    println!("║  {n} functions transpiled, {{}} real Rust         ║", {len(real_fns)});'
    )
    if llm_count > 0:
        parts.append(
            f'    println!("║    AST engine: {ast_real}  |  LLM engine: {llm_count}             ║");'
        )
    parts.append(
        '    println!("╚══════════════════════════════════════════════════╝");'
    )
    parts.append("    println!();")

    for fn_name, fn_code in real_fns:
        _add_demo_call(parts, fn_name, fn_code)

    parts.append("    println!();")
    if llm_count > 0:
        parts.append(
            f'    println!("  Done. {{}} of {n} functions are real Rust code ({ast_real} AST + {llm_count} LLM).", {len(real_fns)});'
        )
    else:
        parts.append(
            f'    println!("  Done. {{}} of {n} functions are real Rust code.", {len(real_fns)});'
        )
    parts.append("}")


def _demo_call_for_params(safe: str, params_raw: str) -> List[str]:
    """Generate demo call lines based on parameter signature."""
    if not params_raw:
        return [f'    println!("  ▸ {safe}() = {{:?}}", {safe}());']
    _SINGLE_PARAM_MAP = {
        "Vec<String>": lambda s: [
            f'    println!("  ▸ {s}() = {{:?}}", {s}(vec!["parse_config".to_string(), "load_data".to_string()]));'
        ],
        "String": lambda s: [
            f'    println!("  ▸ {s}(\\"file_path\\") = {{:?}}", {s}("file_path".to_string()));'
        ],
        "f64": lambda s: [
            f'    println!("  ▸ {s}(0.03) = {{:?}}", {s}(0.03));',
            f'    println!("  ▸ {s}(-0.10) = {{:?}}", {s}(-0.10));',
            f'    println!("  ▸ {s}(0.20) = {{:?}}", {s}(0.20));',
        ],
    }
    if params_raw.count(",") == 0:
        for type_key, template in _SINGLE_PARAM_MAP.items():
            if type_key in params_raw:
                return template(safe)
    return [f"    // {safe}({params_raw}) — complex signature, skipped"]


def _add_demo_call(parts, fn_name, fn_code):
    """Add a demo invocation of a transpiled function to main()."""
    safe = _safe_name(fn_name)
    if any(s in safe for s in ("mock_", "test_", "reproduce")):
        parts.append(f'    println!("  ▸ {safe}() — skipped (test/mock function)");')
        return
    sig_match = re.search(r"fn\s+" + re.escape(safe) + r"\(([^)]*)\)", fn_code)
    if not sig_match:
        return
    parts.extend(_demo_call_for_params(safe, sig_match.group(1).strip()))


def _postprocess_format_specs(result: str) -> str:
    """Fix remaining Python format specs in Rust macros."""
    result = re.sub(r"\{([:<>.^0-9+-]*\d+\.?\d*)[fsdeEgGn]\}", r"{\1}", result)
    result = re.sub(r"\{:[fsdeEgGn]\}", "{}", result)
    return result


def _log_llm_stats(llm_engine):
    """Log LLM usage statistics if engine was used."""
    if llm_engine is not None and llm_engine.stats["attempted"] > 0:
        s = llm_engine.stats
        logger.info(
            f"Hybrid transpiler stats: {s['attempted']} LLM attempts, "
            f"{s['success']} succeeded, {s['compile_fail']} compile fails, "
            f"{s['llm_fail']} LLM errors"
        )


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
    parser.add_argument(
        "--stdin-json", action="store_true", help="Read JSON candidates from stdin"
    )
    parser.add_argument("--out", help="Output file (default: stdout)")
    args = parser.parse_args()

    result = ""
    if args.file:
        result = transpile_module_file(args.file)
    elif args.code:
        result = transpile_function_code(args.code)
    elif args.json or args.stdin_json:
        json_text = (
            Path(args.json).read_text(encoding="utf-8")
            if args.json
            else sys.stdin.read()
        )
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
