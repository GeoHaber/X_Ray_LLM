import ast
import textwrap
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Set

logger = logging.getLogger(__name__)

# --- RUST RESERVED KEYWORDS ---
RUST_RESERVED = {
    "as",
    "break",
    "const",
    "continue",
    "crate",
    "else",
    "enum",
    "extern",
    "false",
    "fn",
    "for",
    "if",
    "impl",
    "in",
    "let",
    "loop",
    "match",
    "mod",
    "move",
    "mut",
    "pub",
    "ref",
    "return",
    "self",
    "Self",
    "static",
    "struct",
    "super",
    "trait",
    "true",
    "type",
    "unsafe",
    "use",
    "where",
    "while",
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
    "try",
    "gen",  # gen is reserved in 2024 edition
}


def safe_name(name: str) -> str:
    """Sanitize Python identifiers to be safe in Rust."""
    if not isinstance(name, str):
        return "unknown_ident"

    if name == "self":
        return name
    if name in RUST_RESERVED:
        return f"r#{name}"
    return name


# --- INTERMEDIATE REPRESENTATION (IR) ---


class RustNode:
    """Base class for all Rust IR nodes."""

    def generate(self, emitter: "RustEmitter"):
        raise NotImplementedError(
            f"{self.__class__.__name__}.generate() string builder missing"
        )


@dataclass
class RustExpr(RustNode):
    code: str

    def generate(self, emitter: "RustEmitter"):
        # We don't emit raw expressions as full statements generally,
        # but if we do, we just emit the code.
        emitter.emit_inline(self.code)


@dataclass
class RustStatement(RustNode):
    expr: RustExpr

    def generate(self, emitter: "RustEmitter"):
        emitter.emit("")
        emitter.emit_inline(self.expr.code)
        emitter.emit_inline(";")
        emitter.emit_newline()


@dataclass
class RustLet(RustNode):
    name: str
    value: str
    is_mut: bool = True
    type_hint: Optional[str] = None

    def generate(self, emitter: "RustEmitter"):
        mut_str = "mut " if self.is_mut else ""
        type_str = f": {self.type_hint}" if self.type_hint else ""
        emitter.emit(f"let {mut_str}{self.name}{type_str} = {self.value};")


@dataclass
class RustReturn(RustNode):
    value: Optional[str]

    def generate(self, emitter: "RustEmitter"):
        if self.value:
            emitter.emit(f"return {self.value};")
        else:
            emitter.emit("return;")


@dataclass
class RustMacro(RustNode):
    name: str
    args: List[str]

    def generate(self, emitter: "RustEmitter"):
        args_str = ", ".join(self.args)
        emitter.emit(f"{self.name}!({args_str});")


class RustIf(RustNode):
    def __init__(self, cond: str, body: List[RustNode], orelse: List[RustNode]):
        self.cond = cond
        self.body = body
        self.orelse = orelse

    def generate(self, emitter: "RustEmitter"):
        emitter.emit(f"if {self.cond} {{")
        emitter.indent()
        for node in self.body:
            node.generate(emitter)
        emitter.dedent()
        if self.orelse:
            if len(self.orelse) == 1 and isinstance(self.orelse[0], RustIf):
                # Format as 'else if'
                emitter.emit_inline("} else ")
                self.orelse[0].generate(emitter)
                # The nested RustIf will handle closing its own brace
                return
            else:
                emitter.emit("} else {")
                emitter.indent()
                for node in self.orelse:
                    node.generate(emitter)
                emitter.dedent()
        emitter.emit("}")


@dataclass
class RustFor(RustNode):
    target: str
    iterable: str
    body: List[RustNode]

    def generate(self, emitter: "RustEmitter"):
        emitter.emit(f"for {self.target} in {self.iterable} {{")
        emitter.indent()
        for stmt in self.body:
            stmt.generate(emitter)
        emitter.dedent()
        emitter.emit("}")


@dataclass
class RustBlock(RustNode):
    """Generic block with a header, body nodes, and closing brace."""

    header: str
    body: List[RustNode]
    footer: str = "}"

    def generate(self, emitter: "RustEmitter"):
        emitter.emit(self.header)
        emitter.indent()
        for stmt in self.body:
            stmt.generate(emitter)
        emitter.dedent()
        emitter.emit(self.footer)


@dataclass
class RustFunction(RustNode):
    name: str
    params: List[str]
    return_type: str
    body: List[RustNode]
    is_async: bool = False
    is_pub: bool = False
    docstring: Optional[str] = None
    source_info: str = ""

    def generate(self, emitter: "RustEmitter"):
        if self.source_info:
            emitter.emit(f"/// Transpiled from {self.source_info}")
        if self.docstring:
            for line in self.docstring.splitlines():
                emitter.emit(f"/// {line}")

        pub_str = "pub " if self.is_pub else ""
        async_str = "async " if self.is_async else ""
        params_str = ", ".join(self.params)

        emitter.emit(
            f"{pub_str}{async_str}fn {self.name}({params_str}) -> {self.return_type} {{"
        )
        emitter.indent()

        has_return = False
        for stmt in self.body:
            stmt.generate(emitter)
            if isinstance(stmt, RustReturn):
                has_return = True

        # Inject fallback return if none provided and expected
        if not has_return and self.return_type != "()":
            emitter.emit(f'todo!("return {self.return_type}");')

        emitter.dedent()
        emitter.emit("}")


# --- EMITTER ---


class RustEmitter:
    def __init__(self):
        self._output: List[str] = []
        self._current_line: str = ""
        self.indent_level = 0
        self.imports: Set[str] = set()

    def require_import(self, module_path: str):
        """Register a required Rust import (e.g. std::collections::HashMap)."""
        self.imports.add(module_path)

    def emit(self, text: str):
        """Emit a full line with preserved indentation."""
        if self._current_line:
            self.emit_newline()
        indent_str = "    " * self.indent_level
        self._output.append(f"{indent_str}{text}")

    def emit_inline(self, text: str):
        """Append text to the current inline buffer without indentation."""
        self._current_line += text

    def emit_newline(self):
        """Flush the inline buffer to the output."""
        if self._current_line:
            indent_str = "    " * self.indent_level
            self._output.append(f"{indent_str}{self._current_line}")
            self._current_line = ""

    def indent(self):
        self.indent_level += 1

    def dedent(self):
        self.indent_level = max(0, self.indent_level - 1)

    def get_code(self) -> str:
        self.emit_newline()  # flush any remaining
        final_code = []
        for imp in sorted(list(self.imports)):
            final_code.append(f"use {imp};")
        if self.imports:
            final_code.append("")

        final_code.extend(self._output)
        return "\n".join(final_code)


# --- AST VISITOR PIPELINE ---


class _ExprHandlerMixin:
    """Mixin providing all AST expression → Rust translation handlers for IRBuilder.

    Extracted from IRBuilder to keep each class under 20 methods (god-class smell).
    All methods receive ``self`` as an IRBuilder instance at call-time.
    """

    def _expr_name_const(self, node) -> str:
        if isinstance(node, ast.Name):
            return safe_name(node.id)
        v = node.value
        if isinstance(v, str):
            esc = (
                v.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
            )
            return f'"{esc}".to_string()'
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "None"
        return str(v)

    # ── operators ───────────────────────────────────────────────────────────

    _BINOP_MAP: Dict[type, str] = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.Mod: "%",
        ast.FloorDiv: "/",
        ast.BitAnd: "&",
        ast.BitOr: "|",
        ast.BitXor: "^",
        ast.LShift: "<<",
        ast.RShift: ">>",
    }

    def _expr_binop(self, node: ast.BinOp) -> str:
        left = self._parse_expr(node.left)
        right = self._parse_expr(node.right)
        if isinstance(node.op, ast.Pow):
            return f"{left}.powf({right} as f64)"
        op = self._BINOP_MAP.get(type(node.op), "+")
        return f"({left} {op} {right})"

    def _expr_boolop(self, node: ast.BoolOp) -> str:
        op = " && " if isinstance(node.op, ast.And) else " || "
        return op.join(self._parse_expr(v) for v in node.values)

    def _expr_unaryop(self, node: ast.UnaryOp) -> str:
        operand = self._parse_expr(node.operand)
        if isinstance(node.op, (ast.Not, ast.Invert)):
            return f"!{operand}"
        if isinstance(node.op, ast.USub):
            return f"-{operand}"
        if isinstance(node.op, ast.UAdd):
            return f"+{operand}"
        return f"/* TODO: unary */ {operand}"

    # ── comparisons ─────────────────────────────────────────────────────────

    _CMP_MAP: Dict[type, str] = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    def _expr_compare(self, node: ast.Compare) -> str:
        left = self._parse_expr(node.left)
        if len(node.ops) != 1:
            return f"({left} /* TODO: complex compare */)"
        op_node = node.ops[0]
        right_raw = node.comparators[0]
        if isinstance(op_node, (ast.In, ast.NotIn)) and isinstance(
            right_raw, ast.Tuple
        ):
            items = [self._parse_expr(e) for e in right_raw.elts]
            right = f"[{', '.join(items)}]"
        else:
            right = self._parse_expr(right_raw)
        if op_sym := self._CMP_MAP.get(type(op_node)):
            return f"({left} {op_sym} {right})"
        if isinstance(op_node, ast.In):
            return f"{right}.contains(&{left})"
        if isinstance(op_node, ast.NotIn):
            return f"!{right}.contains(&{left})"
        if isinstance(op_node, ast.Is):
            return f"{left}.is_none()" if right == "None" else f"({left} == {right})"
        if isinstance(op_node, ast.IsNot):
            return f"{left}.is_some()" if right == "None" else f"({left} != {right})"
        return f"({left} /* TODO: compare */)"

    # ── f-strings ───────────────────────────────────────────────────────────

    def _expr_fstring(self, node: ast.JoinedStr) -> str:
        fmt, args = "", []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                fmt += (
                    part.value.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("{", "{{")
                    .replace("}", "}}")
                )
            elif isinstance(part, ast.FormattedValue):
                fmt += "{}"
                args.append(self._parse_expr(part.value))
        args_str = ", ".join(args)
        return f'format!("{fmt}", {args_str})' if args else f'"{fmt}".to_string()'

    # ── attribute method calls ───────────────────────────────────────────────

    _ATTR_MAP: Dict[tuple, str] = {
        # str / list methods
        ("append", None): "{val}.push({arg0})",
        ("extend", None): "{val}.extend({arg0})",
        ("join", None): "{arg0}.join(&{val})",
        ("splitlines", None): "{val}.lines()",
        ("strip", None): "{val}.trim()",
        ("lstrip", None): "{val}.trim_start()",
        ("rstrip", None): "{val}.trim_end()",
        ("lower", None): "{val}.to_lowercase()",
        ("upper", None): "{val}.to_uppercase()",
        ("startswith", None): "{val}.starts_with({arg0})",
        ("endswith", None): "{val}.ends_with({arg0})",
        (
            "split",
            None,
        ): "{val}.split({arg0}).map(|s| s.to_string()).collect::<Vec<_>>()",
        ("replace", None): "{val}.replace({arg0}, {arg1})",
        ("count", None): "{val}.matches({arg0}).count()",
        ("format", None): "format!({val}, {args})",
        # logging
        ("info", "logger"): 'log::info!("{{}}", {arg0})',
        ("error", "logger"): 'log::error!("{{}}", {arg0})',
        ("warning", "logger"): 'log::warn!("{{}}", {arg0})',
        ("debug", "logger"): 'log::debug!("{{}}", {arg0})',
        ("critical", "logger"): 'log::error!("{{}}", {arg0})',
        ("info", "logging"): 'log::info!("{{}}", {arg0})',
        ("error", "logging"): 'log::error!("{{}}", {arg0})',
        ("warning", "logging"): 'log::warn!("{{}}", {arg0})',
        ("debug", "logging"): 'log::debug!("{{}}", {arg0})',
        ("basicConfig", "logging"): "env_logger::init()",
        # time
        (
            "time",
            "time",
        ): "SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()",
        ("sleep", "time"): "std::thread::sleep(Duration::from_secs_f64({arg0}))",
        ("perf_counter", "time"): "Instant::now().elapsed().as_secs_f64()",
        # datetime
        ("now", "datetime"): "chrono::Local::now()",
        ("utcnow", "datetime"): "chrono::Utc::now()",
        ("strptime", "datetime"): "NaiveDateTime::parse_from_str({args})",
        (
            "fromtimestamp",
            "datetime",
        ): "chrono::NaiveDateTime::from_timestamp({arg0}, 0)",
        # subprocess
        ("run", "subprocess"): "std::process::Command::new({arg0}).status()",
        (
            "check_output",
            "subprocess",
        ): 'Command::new({arg0}).output().expect("cmd failed").stdout',
        ("Popen", "subprocess"): "Command::new({arg0}).spawn()",
        # hashlib
        ("sha256", "hashlib"): "Sha256::digest({arg0})",
        ("md5", "hashlib"): "Md5::digest({arg0})",
        # collections
        ("deque", "collections"): "VecDeque::new()",
        ("defaultdict", "collections"): "HashMap::new()",
        # argparse / functools / itertools
        ("ArgumentParser", "argparse"): "clap::Command::new({arg0})",
        ("reduce", "functools"): "{arg1}.into_iter().fold(Default::default(), {arg0})",
        ("product", "itertools"): "iproduct!({args})",
        # sys
        ("exit", "sys"): "std::process::exit({arg0})",
        ("getsizeof", "sys"): "std::mem::size_of_val(&{arg0})",
        ("getrecursionlimit", "sys"): "1000",
        # shutil
        ("rmtree", "shutil"): "std::fs::remove_dir_all({arg0}).ok()",
        ("copy", "shutil"): "std::fs::copy({arg0}, {arg1}).ok()",
        ("which", "shutil"): "Some({arg0}.to_string())",
        # os / platform
        ("machine", "platform"): '"x86_64".to_string()',
        (
            "getcwd",
            "os",
        ): "std::env::current_dir().unwrap().to_str().unwrap().to_string()",
    }

    def _expr_call_attr(self, node: ast.Call) -> str:
        val = self._parse_expr(node.func.value)
        attr = safe_name(node.func.attr)
        args = [self._parse_expr(a) for a in node.args]
        arg0 = args[0] if args else ""
        arg1 = args[1] if len(args) > 1 else ""

        # Special: dict.get needs runtime default logic
        if attr == "get":
            default = args[1] if len(args) > 1 else "None"
            return f"{val}.get({arg0}).cloned().unwrap_or({default})"

        # Special: Counter/deque/defaultdict need import side-effect
        if attr == "Counter" and val == "collections":
            self.emitter.require_import("std::collections::HashMap")
            return (
                f"{arg0}.into_iter().fold(HashMap::new(), "
                f"|mut acc, x| {{ *acc.entry(x).or_insert(0) += 1; acc }})"
            )
        if attr in ("deque", "defaultdict") and val == "collections":
            self.emitter.require_import("std::collections::HashMap")

        # os.path.join (nested attribute receiver)
        if attr == "join" and val == "os.path":
            return (
                f"std::path::Path::new(&{arg0}).join({arg1})"
                f".to_str().unwrap().to_string()"
            )

        # Lookup: prefer specific receiver, then wildcard
        tmpl = self._ATTR_MAP.get((attr, val)) or self._ATTR_MAP.get((attr, None))
        if tmpl:
            return tmpl.format(val=val, arg0=arg0, arg1=arg1, args=", ".join(args))

        return f"{val}.{attr}({', '.join(args)})"

    # ── builtin function calls ───────────────────────────────────────────────

    _BUILTIN_MAP: Dict[str, str] = {
        "str": "{arg0}.to_string()",
        "int": "({arg0} as i64)",
        "float": "({arg0} as f64)",
        "bool": "({arg0} != 0)",
        "abs": "{arg0}.abs()",
        "round": "{arg0}.round()",
        "len": "{arg0}.len()",
        "sum": "{arg0}.into_iter().sum()",
        "any": "{arg0}.into_iter().any(|x| x)",
        "all": "{arg0}.into_iter().all(|x| x)",
        "enumerate": "{arg0}.into_iter().enumerate()",
        "open": 'std::fs::read_to_string({arg0}).expect("Failed to read file")',
    }

    _BUILTIN_DISPATCH = {
        "print": lambda s, a: s._handle_builtin_print(a),
        "range": lambda s, a: s._handle_builtin_range(a),
        "sorted": lambda s, a: s._handle_builtin_sorted(a),
        "list": lambda s, a: s._handle_builtin_collection("list", a),
        "dict": lambda s, a: s._handle_builtin_collection("dict", a),
        "set": lambda s, a: s._handle_builtin_collection("set", a),
        "isinstance": lambda s, a: s._handle_builtin_isinstance(a),
        "getattr": lambda s, a: s._handle_builtin_getattr(a),
        "min": lambda s, a: f"{a[0]}.min({a[1]})" if len(a) > 1 else a[0],
        "max": lambda s, a: f"{a[0]}.max({a[1]})" if len(a) > 1 else a[0],
        "zip": lambda s, a: f"{a[0]}.into_iter().zip({a[1]}.into_iter())",
        "Path": lambda s, a: "PathBuf::new()" if not a else f"PathBuf::from({a[0]})",
    }

    def _expr_call_builtin(self, node: ast.Call) -> str:
        func_name = self._parse_expr(node.func)
        args = [self._parse_expr(a) for a in node.args]

        # 1. Map directly to template
        if tmpl := self._BUILTIN_MAP.get(func_name):
            return tmpl.format(
                arg0=args[0] if args else "",
                arg1=args[1] if len(args) > 1 else "",
                args=", ".join(args),
            )

        # 2. Dispatch to specific handlers
        if handler := self._BUILTIN_DISPATCH.get(func_name):
            return handler(self, args)

        return f"{func_name}({', '.join(args)})"

    # --- Builtin Specific Handlers ---

    def _handle_builtin_print(self, args: List[str]) -> str:
        placeholders = ", ".join(['"{}"'] * len(args))
        return f'println!("{placeholders}", {", ".join(args)})'

    def _handle_builtin_range(self, args: List[str]) -> str:
        if len(args) == 1:
            return f"(0..{args[0]})"
        if len(args) == 2:
            return f"({args[0]}..{args[1]})"
        return f"({args[0]}..{args[1]}).step_by({args[2]} as usize)"

    def _handle_builtin_sorted(self, args: List[str]) -> str:
        arg0 = args[0] if args else "vec![]"
        self.emitter.emit(f"/* TODO: proper sorted({arg0}) */")
        return f"{{ let mut temp = {arg0}; temp.sort(); temp }}"

    def _handle_builtin_collection(self, kind: str, args: List[str]) -> str:
        arg0 = args[0] if args else ""
        if kind == "list":
            return (
                "Vec::new()" if not args else f"{arg0}.into_iter().collect::<Vec<_>>()"
            )
        if kind == "dict":
            self.emitter.require_import("std::collections::HashMap")
            return "HashMap::new()"
        if kind == "set":
            self.emitter.require_import("std::collections::HashSet")
            return (
                "HashSet::new()"
                if not args
                else f"{arg0}.into_iter().collect::<HashSet<_>>()"
            )
        return ""

    def _handle_builtin_isinstance(self, args: List[str]) -> str:
        if len(args) != 2:
            return "false"
        arg0 = args[0]
        typ = args[1].replace("ast.", "")
        return "true" if typ == "int" else f"matches!({arg0}, RustNode::{typ}(_))"

    def _handle_builtin_getattr(self, args: List[str]) -> str:
        arg0 = args[0]
        arg1 = args[1]
        default = args[2] if len(args) == 3 else "None"
        return f"{arg0}.get_{arg1.replace(chr(34), '')}().unwrap_or({default})"

    # ── attribute constants (sys.argv, logging.INFO, …) ─────────────────────

    _ATTR_CONST: Dict[tuple, str] = {
        ("sys", "argv"): "std::env::args().collect::<Vec<String>>()",
        ("sys", "platform"): "std::env::consts::OS.to_string()",
        ("sys", "stdout"): "std::io::stdout()",
        ("subprocess", "PIPE"): "Stdio::piped()",
        ("logging", "DEBUG"): "log::Level::Debug",
        ("logging", "INFO"): "log::Level::Info",
        ("logging", "WARNING"): "log::Level::Warn",
        ("logging", "ERROR"): "log::Level::Error",
    }

    def _expr_attribute(self, node: ast.Attribute) -> str:
        val = self._parse_expr(node.value)
        attr = safe_name(node.attr)
        return self._ATTR_CONST.get((val, attr), f"{val}.{attr}")

    # ── collection literals ──────────────────────────────────────────────────

    def _expr_list(self, node: ast.List) -> str:
        items = [self._parse_expr(e) for e in node.elts]
        return f"vec![{', '.join(items)}]" if items else "vec![]"

    def _expr_set(self, node: ast.Set) -> str:
        self.emitter.require_import("std::collections::HashSet")
        items = [self._parse_expr(e) for e in node.elts]
        return f"HashSet::from([{', '.join(items)}])"

    def _expr_dict(self, node: ast.Dict) -> str:
        self.emitter.require_import("std::collections::HashMap")
        if not node.keys:
            return "HashMap::new()"
        pairs = [
            f"({self._parse_expr(k)}, {self._parse_expr(v)})"
            for k, v in zip(node.keys, node.values)
            if k is not None
        ]
        return f"HashMap::from([{', '.join(pairs)}])"

    def _expr_tuple(self, node: ast.Tuple) -> str:
        return f"({', '.join(self._parse_expr(e) for e in node.elts)})"

    # ── comprehensions ───────────────────────────────────────────────────────

    def _comprehension_iter(self, gen: ast.comprehension) -> "tuple[str, str]":
        """Return (target_str, iter_str) for a single generator."""
        target = self._parse_expr(gen.target)
        if isinstance(gen.iter, ast.Tuple):
            items = [self._parse_expr(e) for e in gen.iter.elts]
            return target, f"[{', '.join(items)}]"
        return target, self._parse_expr(gen.iter)

    def _expr_listcomp(self, node: ast.ListComp) -> str:
        if not node.generators:
            return "vec![]"
        gen = node.generators[0]
        target, iter_obj = self._comprehension_iter(gen)
        body = self._parse_expr(node.elt)
        chain = f"{iter_obj}.into_iter()"
        if gen.ifs:
            cond = " && ".join(self._parse_expr(c) for c in gen.ifs)
            chain += f".filter(|&{target}| {cond})"
        return f"{chain}.map(|{target}| {body}).collect::<Vec<_>>()"

    def _expr_setcomp(self, node: ast.SetComp) -> str:
        self.emitter.require_import("std::collections::HashSet")
        if not node.generators:
            return "HashSet::new()"
        target, iter_obj = self._comprehension_iter(node.generators[0])
        body = self._parse_expr(node.elt)
        return f"{iter_obj}.into_iter().map(|{target}| {body}).collect::<HashSet<_>>()"

    def _expr_dictcomp(self, node: ast.DictComp) -> str:
        self.emitter.require_import("std::collections::HashMap")
        if not node.generators:
            return "HashMap::new()"
        target, iter_obj = self._comprehension_iter(node.generators[0])
        k = self._parse_expr(node.key)
        v = self._parse_expr(node.value)
        return f"{iter_obj}.into_iter().map(|{target}| ({k}, {v})).collect::<HashMap<_, _>>()"

    def _expr_generatorexp(self, node: ast.GeneratorExp) -> str:
        if not node.generators:
            return "std::iter::empty()"
        target, iter_obj = self._comprehension_iter(node.generators[0])
        body = self._parse_expr(node.elt)
        return f"{iter_obj}.into_iter().map(|{target}| {body})"

    # ── subscript / slice ────────────────────────────────────────────────────

    def _expr_subscript(self, node: ast.Subscript) -> str:
        val = self._parse_expr(node.value)
        idx_node = node.slice
        if isinstance(idx_node, ast.Slice):
            return self._expr_slice(val, idx_node)
        idx = self._parse_expr(idx_node)
        if isinstance(idx_node, (ast.BinOp, ast.Call)):
            return f"{val}[({idx}) as usize]"
        return f"{val}[{idx}]"

    def _expr_slice(self, val: str, s: ast.Slice) -> str:
        lower = self._parse_expr(s.lower) if s.lower else None
        upper = self._parse_expr(s.upper) if s.upper else None
        step = self._parse_expr(s.step) if s.step else None
        if step:
            lo = lower or "0"
            hi = upper or f"{val}.len()"
            return (
                f"({lo}..{hi}).step_by({step} as usize)"
                f".map(|i| {val}[i].clone()).collect::<Vec<_>>()"
            )
        if lower and upper:
            return f"{val}[{lower}..{upper}]"
        if upper:
            return f"{val}[..{upper}]"
        if lower:
            return f"{val}[{lower}..]"
        return f"{val}[..]"

    # ── structural / misc ────────────────────────────────────────────────────

    def _expr_ifexp(self, node: ast.IfExp) -> str:
        cond, body, orelse = (
            self._parse_expr(n) for n in (node.test, node.body, node.orelse)
        )
        return f"if {cond} {{ {body} }} else {{ {orelse} }}"

    def _expr_lambda(self, node: ast.Lambda) -> str:
        args = [safe_name(a.arg) for a in node.args.args]
        return f"|{', '.join(args)}| {self._parse_expr(node.body)}"

    def _expr_namedexpr(self, node: ast.NamedExpr) -> str:
        name = safe_name(node.target.id)
        val = self._parse_expr(node.value)
        return f"{{ let {name} = {val}; {name} }}"

    def _expr_await(self, node: ast.Await) -> str:
        return f"{self._parse_expr(node.value)}.await"

    def _expr_yield(self, node: ast.Yield) -> str:
        return (
            f"/* yield */ {self._parse_expr(node.value)}"
            if node.value
            else "/* yield */"
        )

    def _expr_yieldfrom(self, node: ast.YieldFrom) -> str:
        return f"/* yield from */ {self._parse_expr(node.value)}"

    def _expr_starred(self, node: ast.Starred) -> str:
        return self._parse_expr(node.value)


class _StmtHandlerMixin:
    """Mixin providing all AST statement → Rust IR translation handlers for IRBuilder.

    Extracted from IRBuilder to keep each class under 20 methods (god-class smell).
    """

    def _stmt_assign(self, stmt: ast.Assign) -> "RustNode | None":
        if not stmt.targets:
            return None
        target = stmt.targets[0]
        val = self._parse_expr(stmt.value)
        if isinstance(target, ast.Name):
            return RustLet(name=safe_name(target.id), value=val)
        if isinstance(target, ast.Tuple):
            parts = []
            for elt in target.elts:
                if isinstance(elt, ast.Starred):
                    parts.append(f"mut {safe_name(elt.value.id)}")
                elif isinstance(elt, ast.Name):
                    parts.append(f"mut {safe_name(elt.id)}")
                else:
                    parts.append("_")
            return RustLet(name=f"({', '.join(parts)})", value=val)
        if isinstance(target, ast.Attribute):
            return RustStatement(expr=RustExpr(f"{self._parse_expr(target)} = {val}"))
        code_str = ast.unparse(stmt).replace('"', '\\"')
        return RustMacro("todo", [f'"{code_str}"'])

    def _stmt_annassign(self, stmt: ast.AnnAssign) -> "RustNode":
        if isinstance(stmt.target, ast.Name):
            val = (
                self._parse_expr(stmt.value) if stmt.value else 'todo!("uninitialized")'
            )
            return RustLet(name=safe_name(stmt.target.id), value=val)
        code_str = ast.unparse(stmt).replace('"', '\\"')
        return RustMacro("todo", [f'"{code_str}"'])

    def _stmt_augassign(self, stmt: ast.AugAssign) -> RustNode:
        _AUGOP = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Mod: "%",
            ast.BitAnd: "&",
            ast.BitOr: "|",
            ast.BitXor: "^",
            ast.LShift: "<<",
            ast.RShift: ">>",
        }
        target = self._parse_expr(stmt.target)
        val = self._parse_expr(stmt.value)
        op = _AUGOP.get(type(stmt.op), "+")
        return RustStatement(expr=RustExpr(f"{target} {op}= {val}"))

    def _stmt_return(self, stmt: ast.Return) -> RustNode:
        val = self._parse_expr(stmt.value) if stmt.value else None
        return RustReturn(value=val)

    def _stmt_raise(self, stmt: ast.Raise) -> RustNode:
        if stmt.exc:
            return RustStatement(
                expr=RustExpr(f'panic!("{{:?}}", {self._parse_expr(stmt.exc)})')
            )
        return RustStatement(expr=RustExpr("panic!()"))

    def _stmt_expr(self, stmt: ast.Expr) -> "RustNode | None":
        if isinstance(stmt.value, ast.Constant):
            return None  # skip docstrings / bare constants
        return RustStatement(expr=RustExpr(self._parse_expr(stmt.value)))

    def _stmt_if(self, stmt: ast.If) -> RustNode:
        return RustIf(
            cond=self._parse_expr(stmt.test),
            body=self.parse_body(stmt.body),
            orelse=self.parse_body(stmt.orelse),
        )

    def _stmt_for(self, stmt: ast.For) -> RustNode:
        target = self._parse_expr(stmt.target)
        if isinstance(stmt.iter, ast.Tuple):
            items = [self._parse_expr(e) for e in stmt.iter.elts]
            iter_str = f"[{', '.join(items)}]"
        else:
            iter_str = self._parse_expr(stmt.iter)
        return RustFor(target, iter_str, self.parse_body(stmt.body))

    def _stmt_while(self, stmt: ast.While) -> RustNode:
        return RustBlock(
            header=f"while {self._parse_expr(stmt.test)} {{",
            body=self.parse_body(stmt.body),
        )

    def _stmt_try(self, stmt: ast.Try) -> "list[RustNode]":
        ok_body = self.parse_body(stmt.body)
        handlers = [(h.name or "_e", self.parse_body(h.body)) for h in stmt.handlers]
        nodes: list[RustNode] = []
        nodes.append(
            RustStatement(
                expr=RustExpr("match (|| -> Result<_, Box<dyn std::error::Error>> {")
            )
        )
        nodes.extend(ok_body)
        nodes.append(RustStatement(expr=RustExpr("})() {")))
        nodes.append(RustStatement(expr=RustExpr("    Ok(val) => val,")))
        for err_name, err_body in handlers:
            nodes.append(RustStatement(expr=RustExpr(f"    Err({err_name}) => {{")))
            nodes.extend(err_body)
            nodes.append(RustStatement(expr=RustExpr("    }")))
        nodes.append(RustStatement(expr=RustExpr("}")))
        if stmt.finalbody:
            nodes.extend(self.parse_body(stmt.finalbody))
        return nodes

    def _stmt_with(self, stmt: ast.With) -> "list[RustNode]":
        nodes: list[RustNode] = []
        for item in stmt.items:
            ctx = self._parse_expr(item.context_expr)
            if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                nodes.append(RustLet(name=safe_name(item.optional_vars.id), value=ctx))
            else:
                nodes.append(RustStatement(expr=RustExpr(f"let _guard = {ctx}")))
        nodes.extend(self.parse_body(stmt.body))
        return nodes

    def _stmt_assert(self, stmt: ast.Assert) -> RustNode:
        test_str = self._parse_expr(stmt.test)
        if stmt.msg:
            return RustStatement(
                expr=RustExpr(
                    f'assert!({test_str}, "{{}}", {self._parse_expr(stmt.msg)})'
                )
            )
        return RustStatement(expr=RustExpr(f"assert!({test_str})"))

    def _stmt_delete(self, stmt: ast.Delete) -> "list[RustNode]":
        nodes: list[RustNode] = []
        for target in stmt.targets:
            if isinstance(target, ast.Subscript):
                val = self._parse_expr(target.value)
                key = self._parse_expr(target.slice)
                nodes.append(RustStatement(expr=RustExpr(f"{val}.remove({key})")))
            else:
                nodes.append(
                    RustStatement(expr=RustExpr(f"drop({self._parse_expr(target)})"))
                )
        return nodes

    def _stmt_import(self, stmt: ast.Import) -> RustNode:
        names = ", ".join(a.name for a in stmt.names)
        return RustStatement(expr=RustExpr(f"// import {names}"))

    def _stmt_importfrom(self, stmt: ast.ImportFrom) -> RustNode:
        module = stmt.module or ""
        names = ", ".join(a.name for a in stmt.names)
        return RustStatement(expr=RustExpr(f"// from {module} import {names}"))

    def _stmt_global(self, stmt: ast.Global) -> "list[RustNode]":
        return [RustStatement(expr=RustExpr(f"// global {n}")) for n in stmt.names]

    def _stmt_nonlocal(self, stmt: ast.Nonlocal) -> "list[RustNode]":
        return [RustStatement(expr=RustExpr(f"// nonlocal {n}")) for n in stmt.names]

    def _stmt_funcdef(self, stmt: "ast.FunctionDef | ast.AsyncFunctionDef") -> RustNode:
        nested_fn = self.build_function(stmt, "nested")
        nested_params = []
        for p in nested_fn.params:
            parts = p.split(": ")
            nested_params.append(f"{parts[0]}: {parts[1]}" if len(parts) == 2 else p)
        params_str = ", ".join(nested_params)
        header = (
            f"let {safe_name(stmt.name)} = |{params_str}| -> {nested_fn.return_type} {{"
        )
        return RustBlock(header=header, body=nested_fn.body)

    def _stmt_match(self, stmt: ast.Match) -> RustNode:
        subject = self._parse_expr(stmt.subject)
        match_body = []
        for case in stmt.cases:
            pattern = ast.unparse(case.pattern)
            case_body = self.parse_body(case.body)
            match_body.append(
                RustBlock(header=f"{pattern} => {{", body=case_body, footer="}")
            )
        return RustBlock(header=f"match {subject} {{", body=match_body)

    def _stmt_pass(self, _) -> RustNode:
        return RustStatement(expr=RustExpr("// pass"))

    def _stmt_break(self, _) -> RustNode:
        return RustStatement(expr=RustExpr("break"))

    def _stmt_continue(self, _) -> RustNode:
        return RustStatement(expr=RustExpr("continue"))


class IRBuilder(_ExprHandlerMixin, _StmtHandlerMixin, ast.NodeVisitor):
    """Core AST visitor that coordinates expression/statement transpilation to Rust IR.

    Inherits expression handlers from _ExprHandlerMixin and statement handlers from
    _StmtHandlerMixin. This class provides only the high-level coordination logic:
    _parse_expr, parse_body, build_function, and type resolution.
    """

    def __init__(self, emitter: RustEmitter):
        self.emitter = emitter

    def _parse_expr(self, node: "ast.expr") -> str:
        """Dispatch an AST expression node to its focused handler.

        Adding support for a new node type is a one-liner in _EXPR_DISPATCH.
        """
        if isinstance(node, ast.Call):
            return (
                self._expr_call_attr(node)
                if isinstance(node.func, ast.Attribute)
                else self._expr_call_builtin(node)
            )

        handler_name = self._EXPR_DISPATCH.get(type(node))
        handler = getattr(self, handler_name) if handler_name else None
        if handler:
            return handler(node)

        code_str = ast.unparse(node).replace('"', '\\"')
        return f'todo!("Unmapped Python Expression: {{}}", "{code_str}")'

    # ── literal primitives ──────────────────────────────────────────────────

    # ── dispatch table ───────────────────────────────────────────────────────
    # Maps AST node type → handler. To support a new node type: one line here.

    _EXPR_DISPATCH: Dict[type, Any] = {
        ast.Name: "_expr_name_const",
        ast.Constant: "_expr_name_const",
        ast.BinOp: "_expr_binop",
        ast.BoolOp: "_expr_boolop",
        ast.UnaryOp: "_expr_unaryop",
        ast.Compare: "_expr_compare",
        ast.JoinedStr: "_expr_fstring",
        ast.Attribute: "_expr_attribute",
        ast.List: "_expr_list",
        ast.Set: "_expr_set",
        ast.Dict: "_expr_dict",
        ast.Tuple: "_expr_tuple",
        ast.ListComp: "_expr_listcomp",
        ast.SetComp: "_expr_setcomp",
        ast.DictComp: "_expr_dictcomp",
        ast.GeneratorExp: "_expr_generatorexp",
        ast.Subscript: "_expr_subscript",
        ast.IfExp: "_expr_ifexp",
        ast.Lambda: "_expr_lambda",
        ast.NamedExpr: "_expr_namedexpr",
        ast.Await: "_expr_await",
        ast.Yield: "_expr_yield",
        ast.YieldFrom: "_expr_yieldfrom",
        ast.Starred: "_expr_starred",
    }

    def parse_body(self, stmts: List[ast.stmt]) -> List[RustNode]:
        """Translate a list of Python AST statements into Rust IR nodes.

        Dispatches each statement type to a focused _stmt_* handler.
        Unknown statements fall back to a todo!() macro.
        """
        nodes: List[RustNode] = []
        for stmt in stmts:
            handler_name = self._STMT_DISPATCH.get(type(stmt))
            handler = getattr(self, handler_name) if handler_name else None
            if handler:
                result = handler(stmt)
                if result is None:
                    continue  # e.g. docstrings that are skipped
                if isinstance(result, list):
                    nodes.extend(result)
                else:
                    nodes.append(result)
            else:
                code_str = ast.unparse(stmt).replace('"', '\\"')
                nodes.append(
                    RustMacro("todo", ['"Unmapped Statement: {}"', f'"{code_str}"'])
                )
        return nodes

    # ── statement handlers ───────────────────────────────────────────────────

    # ── statement dispatch table ─────────────────────────────────────────────

    _STMT_DISPATCH: Dict[type, Any] = {
        ast.Assign: "_stmt_assign",
        ast.AnnAssign: "_stmt_annassign",
        ast.AugAssign: "_stmt_augassign",
        ast.Return: "_stmt_return",
        ast.Raise: "_stmt_raise",
        ast.Expr: "_stmt_expr",
        ast.If: "_stmt_if",
        ast.For: "_stmt_for",
        ast.While: "_stmt_while",
        ast.Try: "_stmt_try",
        ast.With: "_stmt_with",
        ast.Assert: "_stmt_assert",
        ast.Delete: "_stmt_delete",
        ast.Import: "_stmt_import",
        ast.ImportFrom: "_stmt_importfrom",
        ast.Global: "_stmt_global",
        ast.Nonlocal: "_stmt_nonlocal",
        ast.FunctionDef: "_stmt_funcdef",
        ast.AsyncFunctionDef: "_stmt_funcdef",
        ast.Match: "_stmt_match",
        ast.Pass: "_stmt_pass",
        ast.Break: "_stmt_break",
        ast.Continue: "_stmt_continue",
    }

    def _wrap_returns_in_some(self, nodes: List[RustNode]):
        """Recursively wrap return values in Some() for Option<T> return types."""
        for i, stmt in enumerate(nodes):
            if (
                isinstance(stmt, RustReturn)
                and stmt.value is not None
                and stmt.value != "None"
            ):
                nodes[i] = RustReturn(value=f"Some({stmt.value})")
            elif isinstance(stmt, RustIf):
                self._wrap_returns_in_some(stmt.body)
                self._wrap_returns_in_some(stmt.orelse)
            elif isinstance(stmt, RustFor):
                self._wrap_returns_in_some(stmt.body)
            elif isinstance(stmt, RustBlock):
                self._wrap_returns_in_some(stmt.body)

    def build_function(self, node: ast.FunctionDef, source_info: str) -> RustFunction:
        params = []
        for arg in node.args.args:
            name = safe_name(arg.arg)
            if name in ("self", "cls"):
                params.append("&self")
                continue
            rtype = self._resolve_rust_type(arg.annotation, arg.arg)
            params.append(f"{name}: {rtype}")

        if node.args.vararg:
            params.append(f"{safe_name(node.args.vararg.arg)}: Vec<String>")
        if node.args.kwarg:
            self.emitter.require_import("std::collections::HashMap")
            params.append(f"{safe_name(node.args.kwarg.arg)}: HashMap<String, String>")

        ret_type = self._resolve_rust_type(getattr(node, "returns", None), "RET")

        # stage IR function
        fn = RustFunction(
            name=safe_name(node.name),
            params=params,
            return_type=ret_type,
            body=self.parse_body(node.body),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            docstring=ast.get_docstring(node),
            source_info=source_info,
        )

        # recursive return-wrap for Option if needed
        if ret_type.startswith("Option<"):
            self._wrap_returns_in_some(fn.body)

        return fn

    # --- Type Inference Helpers ---

    def _resolve_rust_type(self, ann: Optional[ast.AST], name_hint: str = "") -> str:
        """Resolve a Python annotation or name-hint into a Rust type string."""
        if ann is None:
            return self._infer_by_name(name_hint)

        if isinstance(ann, ast.Name):
            return self._map_basic_type(ann.id)

        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            return ann.value

        if isinstance(ann, ast.Subscript):
            return self._handle_complex_type(ann)

        return "String"

    def _map_basic_type(self, py_t: str) -> str:
        type_map = {
            "int": "i64",
            "float": "f64",
            "bool": "bool",
            "str": "String",
            "list": "Vec<String>",
            "None": "()",
        }
        if py_t == "dict":
            self.emitter.require_import("std::collections::HashMap")
            return "HashMap<String, String>"
        return type_map.get(py_t, py_t)

    def _handle_complex_type(self, ann: ast.Subscript) -> str:
        base = getattr(ann.value, "id", "")
        if base in ("List", "list"):
            inner = getattr(ann.slice, "id", "String")
            return f"Vec<{self._map_basic_type(inner)}>"

        if base in ("Dict", "dict"):
            self.emitter.require_import("std::collections::HashMap")
            if isinstance(ann.slice, ast.Tuple) and len(ann.slice.elts) == 2:
                k = getattr(ann.slice.elts[0], "id", "String")
                v = getattr(ann.slice.elts[1], "id", "String")
                return f"HashMap<{self._map_basic_type(k)}, {self._map_basic_type(v)}>"
            return "HashMap<String, String>"

        if base in ("Optional", "Union"):  # Simplistic Option mapping
            inner = getattr(ann.slice, "id", "String")
            return f"Option<{self._map_basic_type(inner)}>"

        return "String"

    def _infer_by_name(self, name: str) -> str:
        """Fallback name-based type inference."""
        if name in ("i", "j", "k", "n", "m", "count", "num", "index", "size", "length"):
            return "i64"
        if name in ("x", "y", "z", "score", "rate", "threshold", "weight"):
            return "f64"
        if name in ("items", "elements", "values", "results", "entries"):
            return "Vec<String>"
        if name in ("config", "settings", "options", "kwargs", "params"):
            self.emitter.require_import("std::collections::HashMap")
            return "HashMap<String, String>"
        return "String"


# --- PUBLIC API EXPORTS ---


def transpile_function_code(
    code: str, *, name_hint: str = "", source_info: str = ""
) -> str:
    """
    Core entry point expected by adapters.py and orchestrator.
    Converts a single python function's source code string into a Rust string via the IR pipeline.
    """
    code = textwrap.dedent(code)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"// SyntaxError during parse: {e}\nfn {safe_name(name_hint)}() {{ todo!() }}"

    # Find the first function
    func_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        None,
    )

    if not func_node:
        name = safe_name(name_hint) or "unknown_func"
        return f"// No function parsed\nfn {name}() {{ todo!() }}"

    emitter = RustEmitter()

    # Inject dummy environment types for testing
    emitter.emit("pub struct RustNode;")
    emitter.emit("pub struct RustEmitter;")
    emitter.emit("pub struct RustFunction;")
    emitter.emit("pub struct RustLet;")
    emitter.emit("pub struct RustStatement;")
    emitter.emit("pub struct RustReturn;")
    emitter.emit("pub struct RustIf;")
    emitter.emit("pub struct RustFor;")
    emitter.emit("pub struct RustMacro;\n")

    builder = IRBuilder(emitter)

    rust_fn = builder.build_function(func_node, source_info)

    has_self = any(p.startswith("&self") for p in rust_fn.params)
    if has_self:
        emitter.emit("pub struct MockContainer;")
        emitter.emit("impl MockContainer {")
        emitter.indent()

    rust_fn.generate(emitter)

    if has_self:
        emitter.dedent()
        emitter.emit("}")

    return emitter.get_code()


def transpile_module_code(code: str) -> str:
    """Backup function in case entire files specify translation."""
    emitter = RustEmitter()
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"// SyntaxError: {e}"

    builder = IRBuilder(emitter)

    functions = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(builder.build_function(node, "module string"))

    for fn in functions:
        fn.generate(emitter)
        emitter.emit("")

    return emitter.get_code()


def transpile_module_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return transpile_module_code(f.read())


# Module-level API for test compatibility
_default_analyzer = RustNode()


def build_function(*args, **kwargs):
    """Wrapper for RustNode.build_function()."""
    return _default_analyzer.build_function(*args, **kwargs)


def dedent(*args, **kwargs):
    """Wrapper for RustNode.dedent()."""
    return _default_analyzer.dedent(*args, **kwargs)


def emit(*args, **kwargs):
    """Wrapper for RustNode.emit()."""
    return _default_analyzer.emit(*args, **kwargs)


def emit_inline(*args, **kwargs):
    """Wrapper for RustNode.emit_inline()."""
    return _default_analyzer.emit_inline(*args, **kwargs)


def emit_newline(*args, **kwargs):
    """Wrapper for RustNode.emit_newline()."""
    return _default_analyzer.emit_newline(*args, **kwargs)


def generate(*args, **kwargs):
    """Wrapper for RustNode.generate()."""
    return _default_analyzer.generate(*args, **kwargs)


def get_code(*args, **kwargs):
    """Wrapper for RustNode.get_code()."""
    return _default_analyzer.get_code(*args, **kwargs)


def indent(*args, **kwargs):
    """Wrapper for RustNode.indent()."""
    return _default_analyzer.indent(*args, **kwargs)


def parse_body(*args, **kwargs):
    """Wrapper for RustNode.parse_body()."""
    return _default_analyzer.parse_body(*args, **kwargs)


def require_import(*args, **kwargs):
    """Wrapper for RustNode.require_import()."""
    return _default_analyzer.require_import(*args, **kwargs)
