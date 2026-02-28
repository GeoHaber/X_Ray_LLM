import ast
import textwrap
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# --- RUST RESERVED KEYWORDS ---
RUST_RESERVED = {
    "as", "break", "const", "continue", "crate", "else", "enum", "extern",
    "false", "fn", "for", "if", "impl", "in", "let", "loop", "match", "mod",
    "move", "mut", "pub", "ref", "return", "self", "Self", "static", "struct",
    "super", "trait", "true", "type", "unsafe", "use", "where", "while",
    "async", "await", "dyn", "abstract", "become", "box", "do", "final",
    "macro", "override", "priv", "typeof", "unsized", "virtual", "yield",
    "try", "gen"  # gen is reserved in 2024 edition
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
        raise NotImplementedError(f"{self.__class__.__name__}.generate() string builder missing")

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
        emitter.emit(f"")
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
        
    def generate(self, emitter: 'RustEmitter'):
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
    
    def generate(self, emitter: "RustEmitter"):
        if self.docstring:
            for line in self.docstring.splitlines():
                emitter.emit(f"/// {line}")
                
        pub_str = 'pub ' if self.is_pub else ''
        async_str = 'async ' if self.is_async else ''
        params_str = ", ".join(self.params)
        
        emitter.emit(f"{pub_str}{async_str}fn {self.name}({params_str}) -> {self.return_type} {{")
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
        self.emit_newline() # flush any remaining
        final_code = []
        for imp in sorted(list(self.imports)):
            final_code.append(f"use {imp};")
        if self.imports:
            final_code.append("")
            
        final_code.extend(self._output)
        return "\n".join(final_code)


# --- AST VISITOR PIPELINE ---

class IRBuilder(ast.NodeVisitor):
    def __init__(self, emitter: RustEmitter):
        self.emitter = emitter
        
    def _parse_expr(self, node: "ast.expr") -> str:
        """Dispatch an AST expression node to its focused handler.

        Adding support for a new node type is a one-liner in _EXPR_DISPATCH.
        """
        if isinstance(node, ast.Call):
            return (self._expr_call_attr(node)
                    if isinstance(node.func, ast.Attribute)
                    else self._expr_call_builtin(node))

        handler = self._EXPR_DISPATCH.get(type(node))
        if handler:
            return handler(self, node)

        code_str = ast.unparse(node).replace('"', '\\"')
        return f'todo!("Unmapped Python Expression: {{}}", "{code_str}")'

    # ── literal primitives ──────────────────────────────────────────────────

    def _expr_name_const(self, node) -> str:
        if isinstance(node, ast.Name):
            return safe_name(node.id)
        v = node.value
        if isinstance(v, str):
            esc = v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
            return f'"{esc}".to_string()'
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "None"
        return str(v)

    # ── operators ───────────────────────────────────────────────────────────

    _BINOP_MAP: Dict[type, str] = {
        ast.Add: "+",  ast.Sub: "-",  ast.Mult: "*",  ast.Div: "/",
        ast.Mod: "%",  ast.FloorDiv: "/",
        ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
        ast.LShift: "<<", ast.RShift: ">>",
    }

    def _expr_binop(self, node: ast.BinOp) -> str:
        left  = self._parse_expr(node.left)
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
        if isinstance(node.op, (ast.Not, ast.Invert)): return f"!{operand}"
        if isinstance(node.op, ast.USub):              return f"-{operand}"
        if isinstance(node.op, ast.UAdd):              return f"+{operand}"
        return f"/* TODO: unary */ {operand}"

    # ── comparisons ─────────────────────────────────────────────────────────

    _CMP_MAP: Dict[type, str] = {
        ast.Eq: "==", ast.NotEq: "!=",
        ast.Lt: "<",  ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
    }

    def _expr_compare(self, node: ast.Compare) -> str:
        left = self._parse_expr(node.left)
        if len(node.ops) != 1:
            return f"({left} /* TODO: complex compare */)"
        op_node   = node.ops[0]
        right_raw = node.comparators[0]
        if isinstance(op_node, (ast.In, ast.NotIn)) and isinstance(right_raw, ast.Tuple):
            items = [self._parse_expr(e) for e in right_raw.elts]
            right = f"[{', '.join(items)}]"
        else:
            right = self._parse_expr(right_raw)
        if op_sym := self._CMP_MAP.get(type(op_node)):
            return f"({left} {op_sym} {right})"
        if isinstance(op_node, ast.In):    return f"{right}.contains(&{left})"
        if isinstance(op_node, ast.NotIn): return f"!{right}.contains(&{left})"
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
                fmt += (part.value
                        .replace('\\', '\\\\').replace('"', '\\"')
                        .replace("{", "{{").replace("}", "}}"))
            elif isinstance(part, ast.FormattedValue):
                fmt += "{}"
                args.append(self._parse_expr(part.value))
        args_str = ", ".join(args)
        return f'format!("{fmt}", {args_str})' if args else f'"{fmt}".to_string()'

    # ── attribute method calls ───────────────────────────────────────────────

    _ATTR_MAP: Dict[tuple, str] = {
        # str / list methods
        ("append",       None): "{val}.push({arg0})",
        ("extend",       None): "{val}.extend({arg0})",
        ("join",         None): "{arg0}.join(&{val})",
        ("splitlines",   None): "{val}.lines()",
        ("strip",        None): "{val}.trim()",
        ("lstrip",       None): "{val}.trim_start()",
        ("rstrip",       None): "{val}.trim_end()",
        ("lower",        None): "{val}.to_lowercase()",
        ("upper",        None): "{val}.to_uppercase()",
        ("startswith",   None): "{val}.starts_with({arg0})",
        ("endswith",     None): "{val}.ends_with({arg0})",
        ("split",        None): "{val}.split({arg0}).map(|s| s.to_string()).collect::<Vec<_>>()",
        ("replace",      None): "{val}.replace({arg0}, {arg1})",
        ("count",        None): "{val}.matches({arg0}).count()",
        ("format",       None): "format!({val}, {args})",
        # logging
        ("info",     "logger"):  'log::info!("{{}}", {arg0})',
        ("error",    "logger"):  'log::error!("{{}}", {arg0})',
        ("warning",  "logger"):  'log::warn!("{{}}", {arg0})',
        ("debug",    "logger"):  'log::debug!("{{}}", {arg0})',
        ("critical", "logger"):  'log::error!("{{}}", {arg0})',
        ("info",     "logging"): 'log::info!("{{}}", {arg0})',
        ("error",    "logging"): 'log::error!("{{}}", {arg0})',
        ("warning",  "logging"): 'log::warn!("{{}}", {arg0})',
        ("debug",    "logging"): 'log::debug!("{{}}", {arg0})',
        ("basicConfig", "logging"): "env_logger::init()",
        # time
        ("time",         "time"): "SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()",
        ("sleep",        "time"): "std::thread::sleep(Duration::from_secs_f64({arg0}))",
        ("perf_counter", "time"): "Instant::now().elapsed().as_secs_f64()",
        # datetime
        ("now",          "datetime"): "chrono::Local::now()",
        ("utcnow",       "datetime"): "chrono::Utc::now()",
        ("strptime",     "datetime"): "NaiveDateTime::parse_from_str({args})",
        ("fromtimestamp","datetime"): "chrono::NaiveDateTime::from_timestamp({arg0}, 0)",
        # subprocess
        ("run",          "subprocess"): "std::process::Command::new({arg0}).status()",
        ("check_output", "subprocess"): 'Command::new({arg0}).output().expect("cmd failed").stdout',
        ("Popen",        "subprocess"): "Command::new({arg0}).spawn()",
        # hashlib
        ("sha256", "hashlib"): "Sha256::digest({arg0})",
        ("md5",    "hashlib"): "Md5::digest({arg0})",
        # collections
        ("deque",       "collections"): "VecDeque::new()",
        ("defaultdict", "collections"): "HashMap::new()",
        # argparse / functools / itertools
        ("ArgumentParser", "argparse"):  "clap::Command::new({arg0})",
        ("reduce",         "functools"): "{arg1}.into_iter().fold(Default::default(), {arg0})",
        ("product",        "itertools"): "iproduct!({args})",
        # sys
        ("exit",               "sys"): "std::process::exit({arg0})",
        ("getsizeof",          "sys"): "std::mem::size_of_val(&{arg0})",
        ("getrecursionlimit",  "sys"): "1000",
        # shutil
        ("rmtree", "shutil"): "std::fs::remove_dir_all({arg0}).ok()",
        ("copy",   "shutil"): "std::fs::copy({arg0}, {arg1}).ok()",
        ("which",  "shutil"): "Some({arg0}.to_string())",
        # os / platform
        ("machine", "platform"): '"x86_64".to_string()',
        ("getcwd",  "os"):       "std::env::current_dir().unwrap().to_str().unwrap().to_string()",
    }

    def _expr_call_attr(self, node: ast.Call) -> str:
        val  = self._parse_expr(node.func.value)
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
            return (f"{arg0}.into_iter().fold(HashMap::new(), "
                    f"|mut acc, x| {{ *acc.entry(x).or_insert(0) += 1; acc }})")
        if attr in ("deque", "defaultdict") and val == "collections":
            self.emitter.require_import("std::collections::HashMap")

        # os.path.join (nested attribute receiver)
        if attr == "join" and val == "os.path":
            return (f"std::path::Path::new(&{arg0}).join({arg1})"
                    f".to_str().unwrap().to_string()")

        # Lookup: prefer specific receiver, then wildcard
        tmpl = self._ATTR_MAP.get((attr, val)) or self._ATTR_MAP.get((attr, None))
        if tmpl:
            return tmpl.format(val=val, arg0=arg0, arg1=arg1,
                               args=", ".join(args))

        return f"{val}.{attr}({', '.join(args)})"

    # ── builtin function calls ───────────────────────────────────────────────

    _BUILTIN_MAP: Dict[str, str] = {
        "str":       "{arg0}.to_string()",
        "int":       "({arg0} as i64)",
        "float":     "({arg0} as f64)",
        "bool":      "({arg0} != 0)",
        "abs":       "{arg0}.abs()",
        "round":     "{arg0}.round()",
        "len":       "{arg0}.len()",
        "sum":       "{arg0}.into_iter().sum()",
        "any":       "{arg0}.into_iter().any(|x| x)",
        "all":       "{arg0}.into_iter().all(|x| x)",
        "enumerate": "{arg0}.into_iter().enumerate()",
        "open":      'std::fs::read_to_string({arg0}).expect("Failed to read file")',
    }

    def _expr_call_builtin(self, node: ast.Call) -> str:
        func_name = self._parse_expr(node.func)
        args      = [self._parse_expr(a) for a in node.args]
        arg0      = args[0] if args else ""
        arg1      = args[1] if len(args) > 1 else ""

        if tmpl := self._BUILTIN_MAP.get(func_name):
            return tmpl.format(arg0=arg0, arg1=arg1, args=", ".join(args))

        if func_name == "min": return f"{arg0}.min({arg1})"
        if func_name == "max": return f"{arg0}.max({arg1})"
        if func_name == "zip": return f"{arg0}.into_iter().zip({arg1}.into_iter())"

        if func_name == "print":
            placeholders = ", ".join(['"{}"'] * len(args))
            return f'println!("{placeholders}", {", ".join(args)})'

        if func_name == "range":
            if len(args) == 1: return f"(0..{arg0})"
            if len(args) == 2: return f"({arg0}..{arg1})"
            return f"({arg0}..{arg1}).step_by({args[2]} as usize)"

        if func_name == "sorted":
            self.emitter.emit(f"/* TODO: proper sorted({arg0}) */")
            return f"{{ let mut temp = {arg0}; temp.sort(); temp }}" if arg0 else "vec![]"

        if func_name == "list":
            return "Vec::new()" if not args else f"{arg0}.into_iter().collect::<Vec<_>>()"
        if func_name == "dict":
            self.emitter.require_import("std::collections::HashMap")
            return "HashMap::new()"
        if func_name == "set":
            self.emitter.require_import("std::collections::HashSet")
            return "HashSet::new()" if not args else f"{arg0}.into_iter().collect::<HashSet<_>>()"

        if func_name == "isinstance" and len(args) == 2:
            typ = args[1].replace("ast.", "")
            return "true" if typ == "int" else f"matches!({arg0}, RustNode::{typ}(_))"

        if func_name == "getattr":
            default = args[2] if len(args) == 3 else "None"
            return f"{arg0}.get_{arg1.replace(chr(34), '')}().unwrap_or({default})"

        if func_name == "Path":
            return "PathBuf::new()" if not args else f"PathBuf::from({arg0})"

        return f"{func_name}({', '.join(args)})"

    # ── attribute constants (sys.argv, logging.INFO, …) ─────────────────────

    _ATTR_CONST: Dict[tuple, str] = {
        ("sys",        "argv"):     "std::env::args().collect::<Vec<String>>()",
        ("sys",        "platform"): "std::env::consts::OS.to_string()",
        ("sys",        "stdout"):   "std::io::stdout()",
        ("subprocess", "PIPE"):     "Stdio::piped()",
        ("logging",    "DEBUG"):    "log::Level::Debug",
        ("logging",    "INFO"):     "log::Level::Info",
        ("logging",    "WARNING"):  "log::Level::Warn",
        ("logging",    "ERROR"):    "log::Level::Error",
    }

    def _expr_attribute(self, node: ast.Attribute) -> str:
        val  = self._parse_expr(node.value)
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
        pairs = [f"({self._parse_expr(k)}, {self._parse_expr(v)})"
                 for k, v in zip(node.keys, node.values) if k is not None]
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
        body  = self._parse_expr(node.elt)
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
        val      = self._parse_expr(node.value)
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
        step  = self._parse_expr(s.step)  if s.step  else None
        if step:
            lo = lower or "0"
            hi = upper or f"{val}.len()"
            return (f"({lo}..{hi}).step_by({step} as usize)"
                    f".map(|i| {val}[i].clone()).collect::<Vec<_>>()")
        if lower and upper: return f"{val}[{lower}..{upper}]"
        if upper:           return f"{val}[..{upper}]"
        if lower:           return f"{val}[{lower}..]"
        return f"{val}[..]"

    # ── structural / misc ────────────────────────────────────────────────────

    def _expr_ifexp(self, node: ast.IfExp) -> str:
        cond, body, orelse = (self._parse_expr(n)
                              for n in (node.test, node.body, node.orelse))
        return f"if {cond} {{ {body} }} else {{ {orelse} }}"

    def _expr_lambda(self, node: ast.Lambda) -> str:
        args = [safe_name(a.arg) for a in node.args.args]
        return f"|{', '.join(args)}| {self._parse_expr(node.body)}"

    def _expr_namedexpr(self, node: ast.NamedExpr) -> str:
        name = safe_name(node.target.id)
        val  = self._parse_expr(node.value)
        return f"{{ let {name} = {val}; {name} }}"

    def _expr_await(self, node: ast.Await) -> str:
        return f"{self._parse_expr(node.value)}.await"

    def _expr_yield(self, node: ast.Yield) -> str:
        return f"/* yield */ {self._parse_expr(node.value)}" if node.value else "/* yield */"

    def _expr_yieldfrom(self, node: ast.YieldFrom) -> str:
        return f"/* yield from */ {self._parse_expr(node.value)}"

    def _expr_starred(self, node: ast.Starred) -> str:
        return self._parse_expr(node.value)

    # ── dispatch table ───────────────────────────────────────────────────────
    # Maps AST node type → handler. To support a new node type: one line here.

    _EXPR_DISPATCH: Dict[type, Any] = {
        ast.Name:         _expr_name_const,
        ast.Constant:     _expr_name_const,
        ast.BinOp:        _expr_binop,
        ast.BoolOp:       _expr_boolop,
        ast.UnaryOp:      _expr_unaryop,
        ast.Compare:      _expr_compare,
        ast.JoinedStr:    _expr_fstring,
        ast.Attribute:    _expr_attribute,
        ast.List:         _expr_list,
        ast.Set:          _expr_set,
        ast.Dict:         _expr_dict,
        ast.Tuple:        _expr_tuple,
        ast.ListComp:     _expr_listcomp,
        ast.SetComp:      _expr_setcomp,
        ast.DictComp:     _expr_dictcomp,
        ast.GeneratorExp: _expr_generatorexp,
        ast.Subscript:    _expr_subscript,
        ast.IfExp:        _expr_ifexp,
        ast.Lambda:       _expr_lambda,
        ast.NamedExpr:    _expr_namedexpr,
        ast.Await:        _expr_await,
        ast.Yield:        _expr_yield,
        ast.YieldFrom:    _expr_yieldfrom,
        ast.Starred:      _expr_starred,
    }

    def parse_body(self, stmts: List[ast.stmt]) -> List[RustNode]:
        nodes = []
        for stmt in stmts:
            if isinstance(stmt, ast.Assign):
                # Simple assignments
                if stmt.targets and isinstance(stmt.targets[0], ast.Name):
                    name = safe_name(stmt.targets[0].id)
                    val = self._parse_expr(stmt.value)
                    nodes.append(RustLet(name=name, value=val))
                elif stmt.targets and isinstance(stmt.targets[0], ast.Tuple):
                    names = []
                    for elt in stmt.targets[0].elts:
                        if isinstance(elt, ast.Starred):
                            names.append(f"mut {safe_name(elt.value.id)}")
                        elif isinstance(elt, ast.Name):
                            names.append(f"mut {safe_name(elt.id)}")
                        else:
                            names.append("_")
                    name = f"({', '.join(names)})"
                    val = self._parse_expr(stmt.value)
                    nodes.append(RustLet(name=name, value=val))
                elif stmt.targets and isinstance(stmt.targets[0], ast.Attribute):
                    # self.attr = val
                    target = self._parse_expr(stmt.targets[0])
                    val = self._parse_expr(stmt.value)
                    nodes.append(RustStatement(expr=RustExpr(f"{target} = {val}")))
                else:
                    code_unparsed = ast.unparse(stmt).replace('"', '\\"')
                    nodes.append(RustMacro("todo", [f'"{code_unparsed}"']))
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name):
                    name = safe_name(stmt.target.id)
                    val = self._parse_expr(stmt.value) if stmt.value else 'todo!("uninitialized")'
                    nodes.append(RustLet(name=name, value=val))
                else:
                    code_unparsed = ast.unparse(stmt).replace('"', '\\"')
                    nodes.append(RustMacro("todo", [f'"{code_unparsed}"']))
            elif isinstance(stmt, ast.Return):
                val = self._parse_expr(stmt.value) if stmt.value else None
                nodes.append(RustReturn(value=val))
            elif isinstance(stmt, ast.Raise):
                if stmt.exc:
                    nodes.append(RustStatement(expr=RustExpr(f'panic!("{{:?}}", {self._parse_expr(stmt.exc)})')))
                else:
                    nodes.append(RustStatement(expr=RustExpr('panic!()')))
            elif isinstance(stmt, ast.Pass):
                nodes.append(RustStatement(expr=RustExpr('// pass')))
            elif isinstance(stmt, ast.Break):
                nodes.append(RustStatement(expr=RustExpr('break')))
            elif isinstance(stmt, ast.Continue):
                nodes.append(RustStatement(expr=RustExpr('continue')))
            elif isinstance(stmt, ast.Expr):
                # Ignore docstrings and bare constants to prevent cargo syntax errors at module level
                if isinstance(stmt.value, ast.Constant):
                    continue
                nodes.append(RustStatement(expr=RustExpr(self._parse_expr(stmt.value))))
            elif isinstance(stmt, ast.If):
                cond = self._parse_expr(stmt.test)
                body = self.parse_body(stmt.body)
                orelse = self.parse_body(stmt.orelse)
                nodes.append(RustIf(cond, body, orelse))
            elif isinstance(stmt, ast.For):
                target = self._parse_expr(stmt.target)
                if isinstance(stmt.iter, ast.Tuple):
                    items = [self._parse_expr(e) for e in stmt.iter.elts]
                    iter_str = f"[{', '.join(items)}]"
                else:
                    iter_str = self._parse_expr(stmt.iter)
                body = self.parse_body(stmt.body)
                nodes.append(RustFor(target, iter_str, body))
            elif isinstance(stmt, ast.Import):
                # Inline import → comment
                names = ", ".join(alias.name for alias in stmt.names)
                nodes.append(RustStatement(expr=RustExpr(f"// import {names}")))
            elif isinstance(stmt, ast.ImportFrom):
                # Inline from-import → comment
                module = stmt.module or ""
                names = ", ".join(alias.name for alias in stmt.names)
                nodes.append(RustStatement(expr=RustExpr(f"// from {module} import {names}")))
            elif isinstance(stmt, ast.While):
                cond = self._parse_expr(stmt.test)
                body = self.parse_body(stmt.body)
                nodes.append(RustBlock(header=f"while {cond} {{", body=body))
            elif isinstance(stmt, ast.AugAssign):
                # x += 1 -> x += 1;
                target = self._parse_expr(stmt.target)
                val = self._parse_expr(stmt.value)
                op = "+"
                if isinstance(stmt.op, ast.Sub): op = "-"
                elif isinstance(stmt.op, ast.Mult): op = "*"
                elif isinstance(stmt.op, ast.Div): op = "/"
                elif isinstance(stmt.op, ast.Mod): op = "%"
                elif isinstance(stmt.op, ast.BitAnd): op = "&"
                elif isinstance(stmt.op, ast.BitOr): op = "|"
                elif isinstance(stmt.op, ast.BitXor): op = "^"
                elif isinstance(stmt.op, ast.LShift): op = "<<"
                elif isinstance(stmt.op, ast.RShift): op = ">>"
                nodes.append(RustStatement(expr=RustExpr(f"{target} {op}= {val}")))
            elif isinstance(stmt, ast.Try):
                # try/except -> match ... { Ok(val) => ..., Err(e) => ... }
                try_body = self.parse_body(stmt.body)
                # try/except -> match on closure returning Result
                # Wrap try body in a match Ok/Err pattern
                ok_body = try_body
                err_handlers = []
                for handler in stmt.handlers:
                    err_name = handler.name or "_e"
                    err_body = self.parse_body(handler.body)
                    err_handlers.append((err_name, err_body))
                
                # Emit as: match (|| -> Result<_, Box<dyn std::error::Error>> { ... })() { Ok(val) => val, Err(e) => ... }
                # Simplified: just emit the try body, then catch as if-let pattern
                nodes.append(RustStatement(expr=RustExpr("match (|| -> Result<_, Box<dyn std::error::Error>> {")))
                nodes.extend(ok_body)
                nodes.append(RustStatement(expr=RustExpr("})() {")))
                nodes.append(RustStatement(expr=RustExpr("    Ok(val) => val,")))
                for err_name, err_body in err_handlers:
                    nodes.append(RustStatement(expr=RustExpr(f"    Err({err_name}) => {{")))
                    nodes.extend(err_body)
                    nodes.append(RustStatement(expr=RustExpr("    }")))
                nodes.append(RustStatement(expr=RustExpr("}")))
                if stmt.finalbody:
                    # finally block always runs after
                    nodes.extend(self.parse_body(stmt.finalbody))
            elif isinstance(stmt, ast.With):
                # with open(x) as f -> let f = ...
                for item in stmt.items:
                    ctx = self._parse_expr(item.context_expr)
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        name = safe_name(item.optional_vars.id)
                        nodes.append(RustLet(name=name, value=ctx))
                    else:
                        nodes.append(RustStatement(expr=RustExpr(f"let _guard = {ctx}")))
                nodes.extend(self.parse_body(stmt.body))
            elif isinstance(stmt, ast.Assert):
                test_str = self._parse_expr(stmt.test)
                if stmt.msg:
                    msg = self._parse_expr(stmt.msg)
                    nodes.append(RustStatement(expr=RustExpr(f'assert!({test_str}, "{{}}", {msg})')))
                else:
                    nodes.append(RustStatement(expr=RustExpr(f'assert!({test_str})')))
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    if isinstance(target, ast.Subscript):
                        val = self._parse_expr(target.value)
                        key = self._parse_expr(target.slice)
                        nodes.append(RustStatement(expr=RustExpr(f"{val}.remove({key})")))
                    else:
                        expr = self._parse_expr(target)
                        nodes.append(RustStatement(expr=RustExpr(f"drop({expr})")))
            elif isinstance(stmt, ast.Global):
                for name in stmt.names:
                    nodes.append(RustStatement(expr=RustExpr(f"// global {name}")))
            elif isinstance(stmt, ast.Nonlocal):
                for name in stmt.names:
                    nodes.append(RustStatement(expr=RustExpr(f"// nonlocal {name}")))
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Nested function definition -> closure
                nested_fn = self.build_function(stmt, "nested")
                nested_params = []
                for p in nested_fn.params:
                    parts = p.split(": ")
                    if len(parts) == 2:
                        nested_params.append(f"{parts[0]}: {parts[1]}")
                    else:
                        nested_params.append(p)
                params_str = ", ".join(nested_params)
                header = f"let {safe_name(stmt.name)} = |{params_str}| -> {nested_fn.return_type} {{"
                nodes.append(RustBlock(header=header, body=nested_fn.body))
            elif isinstance(stmt, ast.Match):
                # match/case
                subject = self._parse_expr(stmt.subject)
                match_body = []
                for case in stmt.cases:
                    pattern = ast.unparse(case.pattern)
                    case_body = self.parse_body(case.body)
                    match_body.append(RustBlock(header=f"{pattern} => {{", body=case_body, footer="}"))
                nodes.append(RustBlock(header=f"match {subject} {{", body=match_body))
            else:
                code_str = ast.unparse(stmt).replace('"', '\\"')
                nodes.append(RustMacro("todo", [f'"Unmapped Statement: {{}}"', f'"{code_str}"']))
        return nodes

    def _wrap_returns_in_some(self, nodes: List[RustNode]):
        """Recursively wrap return values in Some() for Option<T> return types."""
        for i, stmt in enumerate(nodes):
            if isinstance(stmt, RustReturn) and stmt.value is not None and stmt.value != "None":
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
            # Simplistic type inference mapping
            rtype = "String"
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    py_t = arg.annotation.id
                    if py_t == "int": rtype = "i64"
                    elif py_t == "float": rtype = "f64"
                    elif py_t == "bool": rtype = "bool"
                    elif py_t == "str": rtype = "String"
                    elif py_t == "list": rtype = "Vec<String>"
                    elif py_t == "dict": 
                        rtype = "HashMap<String, String>"
                        self.emitter.require_import("std::collections::HashMap")
                    else: rtype = py_t # Custom class pass-through
                elif isinstance(arg.annotation, ast.Constant) and isinstance(arg.annotation.value, str):
                    rtype = arg.annotation.value # Handle string forward refs like "RustEmitter"
                elif isinstance(arg.annotation, ast.Subscript):
                    # Basic List[...] mapping
                    if getattr(arg.annotation.value, "id", "") in ("List", "list"):
                        inner = getattr(arg.annotation.slice, "id", "String")
                        if inner == "int": inner = "i64"
                        elif inner == "float": inner = "f64"
                        elif inner == "bool": inner = "bool"
                        elif inner == "str": inner = "String"
                        rtype = f"Vec<{inner}>"
                    elif getattr(arg.annotation.value, "id", "") in ("Dict", "dict"):
                        self.emitter.require_import("std::collections::HashMap")
                        if isinstance(arg.annotation.slice, ast.Tuple) and len(arg.annotation.slice.elts) == 2:
                            k_id = getattr(arg.annotation.slice.elts[0], "id", "String")
                            v_id = getattr(arg.annotation.slice.elts[1], "id", "String")
                            map_t = lambda t: {"int": "i64", "float": "f64", "bool": "bool", "str": "String"}.get(t, t)
                            rtype = f"HashMap<{map_t(k_id)}, {map_t(v_id)}>"
                        else:
                            rtype = "HashMap<String, String>"
            else:
                # Name-based heuristic type inference for untyped parameters
                raw = arg.arg
                if raw in ("i", "j", "k", "n", "m"):
                    rtype = "i64"
                elif raw in ("x", "y", "z"):
                    rtype = "f64"
                elif raw in ("count", "num", "index", "size", "length", "offset", "depth", "width", "height"):
                    rtype = "i64"
                elif raw in ("timeout", "delay", "rate", "ratio", "weight", "score", "threshold"):
                    rtype = "f64"
                elif raw in ("items", "elements", "values", "results", "entries", "records", "rows"):
                    rtype = "Vec<String>"
                elif raw in ("config", "settings", "options", "kwargs", "params", "metadata"):
                    self.emitter.require_import("std::collections::HashMap")
                    rtype = "HashMap<String, String>"
            params.append(f"{name}: {rtype}")
            
        if node.args.vararg:
            params.append(f"{safe_name(node.args.vararg.arg)}: Vec<String>")
        if node.args.kwarg:
            self.emitter.require_import("std::collections::HashMap")
            params.append(f"{safe_name(node.args.kwarg.arg)}: HashMap<String, String>")
            
        ret_type = "String"
        if getattr(node, "returns", None):
            if isinstance(node.returns, ast.Name):
                py_t = node.returns.id
                if py_t == "int": ret_type = "i64"
                elif py_t == "float": ret_type = "f64"
                elif py_t == "bool": ret_type = "bool"
                elif py_t == "str": ret_type = "String"
                elif py_t == "list": ret_type = "Vec<String>"
                elif py_t == "dict": 
                    ret_type = "HashMap<String, String>"
                    self.emitter.require_import("std::collections::HashMap")
                elif py_t == "None": ret_type = "()"
                else: ret_type = py_t
            elif isinstance(node.returns, ast.Constant) and isinstance(node.returns.value, str):
                ret_type = node.returns.value
            elif isinstance(node.returns, ast.Subscript):
                sub_name = getattr(node.returns.value, "id", "")
                if sub_name in ("List", "list"):
                    inner = getattr(node.returns.slice, "id", "String")
                    if inner == "int": inner = "i64"
                    elif inner == "float": inner = "f64"
                    elif inner == "bool": inner = "bool"
                    elif inner == "str": inner = "String"
                    ret_type = f"Vec<{inner}>"
                elif sub_name in ("Dict", "dict"):
                    self.emitter.require_import("std::collections::HashMap")
                    if isinstance(node.returns.slice, ast.Tuple) and len(node.returns.slice.elts) == 2:
                        k_id = getattr(node.returns.slice.elts[0], "id", "String")
                        v_id = getattr(node.returns.slice.elts[1], "id", "String")
                        map_t = lambda t: {"int": "i64", "float": "f64", "bool": "bool", "str": "String"}.get(t, t)
                        ret_type = f"HashMap<{map_t(k_id)}, {map_t(v_id)}>"
                    else:
                        ret_type = "HashMap<String, String>"
                elif sub_name == "Optional":
                    inner_t = "String"
                    if isinstance(node.returns.slice, ast.Name):
                        py_inner = node.returns.slice.id
                        if py_inner == "int": inner_t = "i64"
                        elif py_inner == "float": inner_t = "f64"
                        elif py_inner == "bool": inner_t = "bool"
                        elif py_inner == "str": inner_t = "String"
                        else: inner_t = py_inner
                    ret_type = f"Option<{inner_t}>"
        
        # Infer return type from param types when no annotation given
        if ret_type == "String" and not getattr(node, "returns", None):
            param_types = [p.split(": ")[1] if ": " in p else "" for p in params]
            param_types = [t for t in param_types if t]  # filter empty
            if param_types:
                if all(t == "f64" for t in param_types):
                    ret_type = "f64"
                elif all(t == "i64" for t in param_types):
                    ret_type = "i64"
                elif all(t == "bool" for t in param_types):
                    ret_type = "bool"
        
        body = self.parse_body(node.body)
        
        # Detect void functions: no return statements with values -> ()
        def _has_return_value(nodes):
            for n in nodes:
                if isinstance(n, RustReturn) and n.value is not None:
                    return True
                if isinstance(n, RustIf):
                    if _has_return_value(n.body) or _has_return_value(n.orelse):
                        return True
                if isinstance(n, RustFor):
                    if _has_return_value(n.body):
                        return True
                if isinstance(n, RustBlock):
                    if _has_return_value(n.body):
                        return True
            return False
        
        if not getattr(node, "returns", None) and not _has_return_value(body):
            ret_type = "()"
        
        is_async = isinstance(node, ast.AsyncFunctionDef)
        
        # Post-process: wrap return values in Some() for Option<T> return types
        if ret_type.startswith("Option<"):
            self._wrap_returns_in_some(body)
        
        return RustFunction(
            name=safe_name(node.name),
            params=params,
            return_type=ret_type,
            body=body,
            is_async=is_async,
            docstring=f"Transpiled from {source_info}" if source_info else None
        )

# --- PUBLIC API EXPORTS ---

def transpile_function_code(code: str, *, name_hint: str = "", source_info: str = "") -> str:
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
    func_node = next((node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    
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
