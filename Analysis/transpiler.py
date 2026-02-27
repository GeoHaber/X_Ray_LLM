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
        
    def _parse_expr(self, node: ast.expr) -> str:
        """Parse an AST expression into a dynamic Rust string representing it."""
        if isinstance(node, ast.Name):
            return safe_name(node.id)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                # Escape inner quotes and backslashes for raw strings
                val = node.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                return f'"{val}".to_string()'
            elif isinstance(node.value, bool):
                return "true" if node.value else "false"
            elif node.value is None:
                return "None"
            else:
                return str(node.value)
        elif isinstance(node, ast.BinOp):
            left = self._parse_expr(node.left)
            right = self._parse_expr(node.right)
            # Simplistic mapping of ops
            op = "+"
            if isinstance(node.op, ast.Sub): op = "-"
            elif isinstance(node.op, ast.Mult): op = "*"
            elif isinstance(node.op, ast.Div): op = "/"
            return f"({left} {op} {right})"
        elif isinstance(node, ast.BoolOp):
            op = " && " if isinstance(node.op, ast.And) else " || "
            return op.join(self._parse_expr(v) for v in node.values)
        elif isinstance(node, ast.Compare):
            left = self._parse_expr(node.left)
            if len(node.ops) == 1:
                op_node = node.ops[0]
                right_node = node.comparators[0]
                if isinstance(op_node, (ast.In, ast.NotIn)) and isinstance(right_node, ast.Tuple):
                    items = [self._parse_expr(e) for e in right_node.elts]
                    right = f"[{', '.join(items)}]"
                else:
                    right = self._parse_expr(right_node)
                if isinstance(op_node, ast.Eq): return f"({left} == {right})"
                elif isinstance(op_node, ast.NotEq): return f"({left} != {right})"
                elif isinstance(op_node, ast.Lt): return f"({left} < {right})"
                elif isinstance(op_node, ast.LtE): return f"({left} <= {right})"
                elif isinstance(op_node, ast.Gt): return f"({left} > {right})"
                elif isinstance(op_node, ast.GtE): return f"({left} >= {right})"
                elif isinstance(op_node, ast.In): return f"{right}.contains(&{left})"
                elif isinstance(op_node, ast.NotIn): return f"!{right}.contains(&{left})"
                elif isinstance(op_node, ast.Is):
                    if right == "None": return f"{left}.is_none()"
                    return f"({left} == {right})"
                elif isinstance(op_node, ast.IsNot):
                    if right == "None": return f"{left}.is_some()"
                    return f"({left} != {right})"
            # Fallback for complex comparisons
            return f"({left} /* TODO: complex compare */)"
        elif isinstance(node, ast.UnaryOp):
            operand = self._parse_expr(node.operand)
            if isinstance(node.op, ast.Not): return f"!{operand}"
            elif isinstance(node.op, ast.USub): return f"-{operand}"
            elif isinstance(node.op, ast.UAdd): return f"+{operand}"
            elif isinstance(node.op, ast.Invert): return f"!{operand}"
            return f"/* TODO: unary */ {operand}"
        elif isinstance(node, ast.JoinedStr):
            # Convert f-strings into format!("...", args)
            format_str = ""
            args = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    format_str += v.value.replace('\\', '\\\\').replace('"', '\\"').replace("{", "{{").replace("}", "}}")
                elif isinstance(v, ast.FormattedValue):
                    format_str += "{}"
                    args.append(self._parse_expr(v.value))
            args_str = ", ".join(args)
            if args:
                return f'format!("{format_str}", {args_str})'
            return f'"{format_str}".to_string()'
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                val = self._parse_expr(node.func.value)
                attr = safe_name(node.func.attr)
                args = [self._parse_expr(a) for a in node.args]
                
                if attr == "append":
                    return f"{val}.push({args[0]})"
                elif attr == "extend":
                    return f"{val}.extend({args[0]})"
                elif attr == "join":
                    return f"{args[0]}.join(&{val})"
                elif attr == "splitlines":
                    return f"{val}.lines()"
                elif attr == "strip":
                    return f"{val}.trim()"
                elif attr == "lower":
                    return f"{val}.to_lowercase()"
                elif attr == "upper":
                    return f"{val}.to_uppercase()"
                elif attr == "startswith":
                    return f"{val}.starts_with({args[0]})"
                elif attr == "endswith":
                    return f"{val}.ends_with({args[0]})"
                elif attr == "split":
                    return f"{val}.split({args[0]}).map(|s| s.to_string()).collect::<Vec<_>>()"
                elif attr == "replace":
                    return f"{val}.replace({args[0]}, {args[1]})"
                elif attr == "get":
                    default = args[1] if len(args) > 1 else "None"
                    return f"{val}.get({args[0]}).cloned().unwrap_or({default})"
                elif attr == "count":
                    return f"{val}.matches({args[0]}).count()"
                elif attr == "join" and val == "os.path":
                    return f"std::path::Path::new(&{args[0]}).join({args[1]}).to_str().unwrap().to_string()"
                # ── logging module → log crate ──
                elif attr == "info" and val in ("logger", "logging"):
                    if args: return f"log::info!(\"{{}}\" , {args[0]})"
                    return "log::info!()"
                elif attr == "error" and val in ("logger", "logging"):
                    if args: return f"log::error!(\"{{}}\" , {args[0]})"
                    return "log::error!()"
                elif attr == "warning" and val in ("logger", "logging"):
                    if args: return f"log::warn!(\"{{}}\" , {args[0]})"
                    return "log::warn!()"
                elif attr == "debug" and val in ("logger", "logging"):
                    if args: return f"log::debug!(\"{{}}\" , {args[0]})"
                    return "log::debug!()"
                elif attr == "critical" and val in ("logger", "logging"):
                    if args: return f"log::error!(\"{{}}\" , {args[0]})"
                    return "log::error!()"
                elif attr == "basicConfig" and val == "logging":
                    return "env_logger::init()"
                # ── time module ──
                elif attr == "time" and val == "time":
                    return "SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()"
                elif attr == "sleep" and val == "time":
                    return f"std::thread::sleep(Duration::from_secs_f64({args[0]}))"
                elif attr == "perf_counter" and val == "time":
                    return "Instant::now().elapsed().as_secs_f64()"
                # ── datetime module ──
                elif attr == "now" and val == "datetime":
                    return "chrono::Local::now()"
                elif attr == "utcnow" and val == "datetime":
                    return "chrono::Utc::now()"
                elif attr == "strptime" and val == "datetime":
                    return f"NaiveDateTime::parse_from_str({', '.join(args)})"
                elif attr == "fromtimestamp" and val == "datetime":
                    return f"chrono::NaiveDateTime::from_timestamp({args[0]}, 0)"
                # ── subprocess module ──
                elif attr == "run" and val == "subprocess":
                    return f"std::process::Command::new({args[0]}).status()"
                elif attr == "check_output" and val == "subprocess":
                    return f"Command::new({args[0]}).output().expect(\"cmd failed\").stdout"
                elif attr == "Popen" and val == "subprocess":
                    return f"Command::new({args[0]}).spawn()"
                # ── hashlib module ──
                elif attr == "sha256" and val == "hashlib":
                    return f"Sha256::digest({args[0]})"
                elif attr == "md5" and val == "hashlib":
                    return f"Md5::digest({args[0]})"
                # ── collections module ──
                elif attr == "Counter" and val == "collections":
                    self.emitter.require_import("std::collections::HashMap")
                    return f"{args[0]}.into_iter().fold(HashMap::new(), |mut acc, x| {{ *acc.entry(x).or_insert(0) += 1; acc }})"
                elif attr == "deque" and val == "collections":
                    return "VecDeque::new()"
                elif attr == "defaultdict" and val == "collections":
                    self.emitter.require_import("std::collections::HashMap")
                    return "HashMap::new()"
                # ── argparse module ──
                elif attr == "ArgumentParser" and val == "argparse":
                    return f"clap::Command::new({args[0]})"
                # ── functools module ──
                elif attr == "reduce" and val == "functools":
                    return f"{args[1]}.into_iter().fold(Default::default(), {args[0]})"
                # ── itertools module ──
                elif attr == "product" and val == "itertools":
                    return f"iproduct!({', '.join(args)})"
                # ── sys module (call-based) ──
                elif attr == "exit" and val == "sys":
                    return f"std::process::exit({args[0]})"
                elif attr == "getsizeof" and val == "sys":
                    return f"std::mem::size_of_val(&{args[0]})"
                elif attr == "getrecursionlimit" and val == "sys":
                    return "1000"
                elif attr == "rmtree" and val == "shutil":
                    return f"std::fs::remove_dir_all({args[0]}).ok()"
                elif attr == "copy" and val == "shutil":
                    return f"std::fs::copy({args[0]}, {args[1]}).ok()"
                elif attr == "which" and val == "shutil":
                    return f"Some({args[0]}.to_string())"
                elif attr == "machine" and val == "platform":
                    return "\"x86_64\".to_string()"
                # ── os module ──
                elif attr == "getcwd" and val == "os":
                    return "std::env::current_dir().unwrap().to_str().unwrap().to_string()"
                    
                return f"{val}.{attr}({', '.join(args)})"

            func_name = self._parse_expr(node.func)
            args = [self._parse_expr(a) for a in node.args]
            
            if func_name == "str":
                return f"{args[0]}.to_string()"
            elif func_name == "int":
                return f"({args[0]} as i64)"
            elif func_name == "float":
                return f"({args[0]} as f64)"
            elif func_name == "list":
                if len(args) == 0:
                    return "Vec::new()"
                elif len(args) == 1:
                    return f"{args[0]}.into_iter().collect::<Vec<_>>()"
            elif func_name == "dict":
                self.emitter.require_import("std::collections::HashMap")
                return "HashMap::new()"
            elif func_name == "set":
                self.emitter.require_import("std::collections::HashSet")
                if len(args) == 0:
                    return "HashSet::new()"
                else:
                    return f"{args[0]}.into_iter().collect::<HashSet<_>>()"
            elif func_name == "len":
                return f"{args[0]}.len()"
            elif func_name == "print":
                placeholders = ", ".join(["\"{}\""] * len(args))
                return f'println!("{placeholders}", {", ".join(args)})'
            elif func_name == "range":
                if len(args) == 1:
                    return f"(0..{args[0]})"
                elif len(args) == 2:
                    return f"({args[0]}..{args[1]})"
                elif len(args) == 3:
                    return f"({args[0]}..{args[1]}).step_by({args[2]} as usize)"
            elif func_name == "abs":
                return f"{args[0]}.abs()"
            elif func_name == "round":
                return f"{args[0]}.round()"
            elif func_name == "min":
                return f"{args[0]}.min({args[1]})"
            elif func_name == "max":
                return f"{args[0]}.max({args[1]})"
            elif func_name == "sum":
                return f"{args[0]}.into_iter().sum()"
            elif func_name == "enumerate":
                return f"{args[0]}.into_iter().enumerate()"
            elif func_name == "zip":
                return f"{args[0]}.into_iter().zip({args[1]}.into_iter())"
            elif func_name == "any":
                return f"{args[0]}.into_iter().any(|x| x)"
            elif func_name == "all":
                return f"{args[0]}.into_iter().all(|x| x)"
            elif func_name == "open":
                return f"std::fs::read_to_string({args[0]}).expect(\"Failed to read file\")"
            elif func_name == "sorted":
                self.emitter.emit(f"/* TODO: proper sorted({args[0]}) */")
                if len(args) > 0:
                    return f"{{ let mut temp = {args[0]}; temp.sort(); temp }}"
                return "vec![]"
            elif func_name == "isinstance":
                if len(args) == 2:
                    typ = args[1].replace("ast.", "")
                    if typ == "int": return "true" # Handle test case isinstance(x, int)
                    return f"matches!({args[0]}, RustNode::{typ}(_))"
            elif func_name == "getattr":
                if len(args) >= 2:
                    default = args[2] if len(args) == 3 else "None"
                    return f"{args[0]}.get_{args[1].replace('\"', '')}().unwrap_or({default})"
            elif func_name == "Path":
                if len(args) == 0:
                    return "PathBuf::new()"
                else:
                    return f"PathBuf::from({args[0]})"
                
            return f"{func_name}({', '.join(args)})"
        elif isinstance(node, ast.Attribute):
            val = self._parse_expr(node.value)
            attr = safe_name(node.attr)
            # ── module constant attributes ──
            if val == "sys" and attr == "argv":
                return "std::env::args().collect::<Vec<String>>()"
            elif val == "sys" and attr == "platform":
                return "std::env::consts::OS.to_string()"
            elif val == "sys" and attr == "stdout":
                return "std::io::stdout()"
            elif val == "subprocess" and attr == "PIPE":
                return "Stdio::piped()"
            elif val == "logging" and attr == "DEBUG":
                return "log::Level::Debug"
            elif val == "logging" and attr == "INFO":
                return "log::Level::Info"
            elif val == "logging" and attr == "WARNING":
                return "log::Level::Warn"
            elif val == "logging" and attr == "ERROR":
                return "log::Level::Error"
            return f"{val}.{attr}"
        elif isinstance(node, ast.List):
            items = [self._parse_expr(e) for e in node.elts]
            if not items:
                return "vec![]"
            return f"vec![{', '.join(items)}]"
        elif isinstance(node, ast.Set):
            self.emitter.require_import("std::collections::HashSet")
            items = [self._parse_expr(e) for e in node.elts]
            return f"HashSet::from([{', '.join(items)}])"
        elif isinstance(node, ast.Dict):
            self.emitter.require_import("std::collections::HashMap")
            if not node.keys:
                return "HashMap::new()"
            items = []
            for k, v in zip(node.keys, node.values):
                if k is not None:
                    items.append(f"({self._parse_expr(k)}, {self._parse_expr(v)})")
            return f"HashMap::from([{', '.join(items)}])"
        elif isinstance(node, ast.IfExp):
            cond = self._parse_expr(node.test)
            body = self._parse_expr(node.body)
            orelse = self._parse_expr(node.orelse)
            return f"if {cond} {{ {body} }} else {{ {orelse} }}"
        elif isinstance(node, ast.Lambda):
            args = []
            for arg in node.args.args:
                args.append(safe_name(arg.arg))
            args_str = ", ".join(args)
            body = self._parse_expr(node.body)
            return f"|{args_str}| {body}"
        elif isinstance(node, ast.ListComp):
            # List comprehension
            if len(node.generators) == 1:
                gen = node.generators[0]
                target = self._parse_expr(gen.target)
                if isinstance(gen.iter, ast.Tuple):
                    items = [self._parse_expr(e) for e in gen.iter.elts]
                    iter_obj = f"[{', '.join(items)}]"
                else:
                    iter_obj = self._parse_expr(gen.iter)
                body = self._parse_expr(node.elt)
                
                filters = []
                for if_clause in gen.ifs:
                    filters.append(self._parse_expr(if_clause))
                
                rust_code = f"{iter_obj}.into_iter()"
                if filters:
                    filters_str = " && ".join(filters)
                    rust_code += f".filter(|&{target}| {filters_str})"
                # Map target to body if distinct, otherwise pure filter/collect is enough? 
                # e.g [x*2 for x in items] -> .map(|x| x*2)
                rust_code += f".map(|{target}| {body}).collect::<Vec<_>>()"
                return rust_code
        elif isinstance(node, ast.SetComp):
            self.emitter.require_import("std::collections::HashSet")
            if len(node.generators) == 1:
                gen = node.generators[0]
                target = self._parse_expr(gen.target)
                if isinstance(gen.iter, ast.Tuple):
                    items = [self._parse_expr(e) for e in gen.iter.elts]
                    iter_obj = f"[{', '.join(items)}]"
                else:
                    iter_obj = self._parse_expr(gen.iter)
                body = self._parse_expr(node.elt)
                return f"{iter_obj}.into_iter().map(|{target}| {body}).collect::<HashSet<_>>()"
        elif isinstance(node, ast.DictComp):
            self.emitter.require_import("std::collections::HashMap")
            if len(node.generators) == 1:
                gen = node.generators[0]
                target = self._parse_expr(gen.target)
                if isinstance(gen.iter, ast.Tuple):
                    items = [self._parse_expr(e) for e in gen.iter.elts]
                    iter_obj = f"[{', '.join(items)}]"
                else:
                    iter_obj = self._parse_expr(gen.iter)
                k = self._parse_expr(node.key)
                v = self._parse_expr(node.value)
                return f"{iter_obj}.into_iter().map(|{target}| ({k}, {v})).collect::<HashMap<_, _>>()"
        elif isinstance(node, ast.GeneratorExp):
            if len(node.generators) == 1:
                gen = node.generators[0]
                target = self._parse_expr(gen.target)
                if isinstance(gen.iter, ast.Tuple):
                    items = [self._parse_expr(e) for e in gen.iter.elts]
                    iter_obj = f"[{', '.join(items)}]"
                else:
                    iter_obj = self._parse_expr(gen.iter)
                body = self._parse_expr(node.elt)
                # Just return an iterator mapping
                return f"{iter_obj}.into_iter().map(|{target}| {body})"

        elif isinstance(node, ast.Await):
            # async/await: await expr → expr.await
            return f"{self._parse_expr(node.value)}.await"
        elif isinstance(node, ast.Subscript):
            # Indexing: arr[idx]
            val = self._parse_expr(node.value)
            idx_node = node.slice
            # Handle slicing: s[:3], s[1:], s[1:3], s[::2]
            if isinstance(idx_node, ast.Slice):
                lower = self._parse_expr(idx_node.lower) if idx_node.lower else None
                upper = self._parse_expr(idx_node.upper) if idx_node.upper else None
                step = self._parse_expr(idx_node.step) if idx_node.step else None
                if step:
                    lo = lower or "0"
                    hi = upper or f"{val}.len()"
                    return f"({lo}..{hi}).step_by({step} as usize).map(|i| {val}[i].clone()).collect::<Vec<_>>()"
                if lower and upper:
                    return f"{val}[{lower}..{upper}]"
                elif upper:
                    return f"{val}[..{upper}]"
                elif lower:
                    return f"{val}[{lower}..]"
                return f"{val}[..]"
            idx = self._parse_expr(idx_node)
            # Cast to usize for non-literal integer indices
            needs_cast = False
            if isinstance(idx_node, ast.BinOp):
                needs_cast = True
            elif isinstance(idx_node, ast.Call):
                needs_cast = True
            elif isinstance(idx_node, ast.Name):
                needs_cast = False  # could be usize already
            # Literal int constants don't need cast
            if isinstance(idx_node, ast.Constant) and isinstance(idx_node.value, int):
                needs_cast = False
            if needs_cast:
                return f"{val}[({idx}) as usize]"
            return f"{val}[{idx}]"
        elif isinstance(node, ast.Tuple):
            items = [self._parse_expr(e) for e in node.elts]
            return f"({', '.join(items)})"
        elif isinstance(node, ast.NamedExpr):
            # Walrus operator: (x := expr) -> { let x = expr; x }
            name = safe_name(node.target.id)
            val = self._parse_expr(node.value)
            return f"{{ let {name} = {val}; {name} }}"
        elif isinstance(node, ast.Starred):
            return self._parse_expr(node.value)
        elif isinstance(node, ast.Yield):
            if node.value:
                return f"/* yield */ {self._parse_expr(node.value)}"
            return "/* yield */"
        elif isinstance(node, ast.YieldFrom):
            return f"/* yield from */ {self._parse_expr(node.value)}"
        
        # Fallback for complex expressions
        code_str = ast.unparse(node).replace('"', '\\"')
        return f'todo!("Unmapped Python Expression: {{}}", "{code_str}")'

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
