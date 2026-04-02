"""
X-Ray Transpiler -- Python-to-Rust transpilation engine.

Analyses arbitrary Python codebases using the ``ast`` module, maps types and
constructs to idiomatic Rust equivalents, and generates a complete Cargo
project.  Complex constructs that cannot be pattern-translated are delegated
to an LLM backend (reusing the existing :mod:`xray.llm` infrastructure).

Pipeline integration::

    scan -> fix -> verify (clean) -> transpile to Rust -> compile
"""

from __future__ import annotations

import ast
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from xray.llm import LLMBackend, create_backend
from xray.scanner import scan_directory

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Type & crate mappings
# ═══════════════════════════════════════════════════════════════════════════

TYPE_MAP: dict[str, str] = {
    "str": "String",
    "int": "i64",
    "float": "f64",
    "bool": "bool",
    "None": "()",
    "bytes": "Vec<u8>",
    "list": "Vec",
    "dict": "HashMap",
    "set": "HashSet",
    "tuple": "tuple",
    "Optional": "Option",
    "List": "Vec",
    "Dict": "HashMap",
    "Set": "HashSet",
    "Tuple": "tuple",
    "Any": "Box<dyn std::any::Any>",
    "Callable": "Box<dyn Fn>",
    "Path": "PathBuf",
    "pathlib.Path": "PathBuf",
    "re.Pattern": "Regex",
    "io.TextIOWrapper": "File",
}

CRATE_MAP: dict[str, str] = {
    "requests": "reqwest",
    "flask": "axum",
    "fastapi": "axum",
    "django": "actix-web",
    "sqlalchemy": "diesel",
    "asyncio": "tokio",
    "json": "serde_json",
    "re": "regex",
    "os": "std::fs / std::env",
    "pathlib": "std::path",
    "hashlib": "sha2",
    "logging": "tracing",
    "subprocess": "std::process",
    "collections": "std::collections",
    "typing": "(built-in)",
    "dataclasses": "(derive macros)",
    "pytest": "(#[cfg(test)])",
    "argparse": "clap",
    "yaml": "serde_yaml",
    "toml": "toml",
    "csv": "csv",
    "datetime": "chrono",
}

# Standard-library modules that don't need a crate dependency.
_STDLIB_MODULES: set[str] = {
    "os", "sys", "pathlib", "collections", "typing", "dataclasses",
    "subprocess", "io", "math", "functools", "itertools", "copy",
    "abc", "contextlib", "enum", "inspect", "textwrap", "string",
    "struct", "threading", "multiprocessing", "unittest", "logging",
    "warnings", "traceback", "time", "shutil", "tempfile", "glob",
    "fnmatch", "stat", "errno", "signal", "socket", "http", "urllib",
    "email", "html", "xml", "base64", "binascii", "hashlib", "hmac",
    "secrets", "uuid", "pprint", "dis", "importlib", "pkgutil",
    "builtins", "__future__",
}

# Crates that require specific Cargo.toml features.
_CRATE_VERSIONS: dict[str, str] = {
    "serde": '{ version = "1", features = ["derive"] }',
    "serde_json": '"1"',
    "tokio": '{ version = "1", features = ["full"] }',
    "reqwest": '{ version = "0.11", features = ["json"] }',
    "axum": '"0.7"',
    "actix-web": '"4"',
    "diesel": '{ version = "2", features = ["sqlite"] }',
    "regex": '"1"',
    "sha2": '"0.10"',
    "tracing": '"0.1"',
    "tracing-subscriber": '"0.3"',
    "clap": '{ version = "4", features = ["derive"] }',
    "serde_yaml": '"0.9"',
    "toml": '"0.8"',
    "csv": '"1"',
    "chrono": '{ version = "0.4", features = ["serde"] }',
    "anyhow": '"1"',
    "thiserror": '"1"',
}


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TranspileConfig:
    """Configuration knobs for the transpilation run."""

    output_dir: str = "rust_output"
    crate_name: str = "transpiled"
    use_llm: bool = True
    llm_backend: str = "auto"
    generate_tests: bool = True
    generate_cargo_toml: bool = True
    preserve_comments: bool = True
    type_inference: bool = True
    error_strategy: str = "anyhow"       # "anyhow" | "thiserror" | "std"
    async_runtime: str = "tokio"         # "tokio" | "async-std" | "none"
    string_type: str = "String"          # "String" | "&str"
    max_llm_calls: int = 100


# ═══════════════════════════════════════════════════════════════════════════
# Parsed-representation dataclasses
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ImportInfo:
    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None


@dataclass
class GlobalInfo:
    name: str
    type_hint: str
    value: str


@dataclass
class FunctionInfo:
    name: str
    args: list[tuple[str, str]]   # [(name, rust_type), ...]
    return_type: str
    body_source: str              # raw Python source of the body
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)
    docstring: str = ""
    ast_body: list | None = None  # list[ast.stmt] — AST nodes for the body


@dataclass
class ClassInfo:
    name: str
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionInfo] = field(default_factory=list)
    fields: list[tuple[str, str]] = field(default_factory=list)  # (name, rust_type)
    docstring: str = ""
    is_dataclass: bool = False


@dataclass
class PythonModule:
    path: str
    module_name: str
    imports: list[ImportInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    globals: list[GlobalInfo] = field(default_factory=list)
    docstring: str = ""
    dependencies: set[str] = field(default_factory=set)


# ═══════════════════════════════════════════════════════════════════════════
# Result
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TranspileResult:
    modules_transpiled: int = 0
    files_written: dict[str, str] = field(default_factory=dict)
    cargo_toml: str = ""
    compile_success: bool = False
    compile_errors: list[str] = field(default_factory=list)
    llm_calls_made: int = 0
    warnings: list[str] = field(default_factory=list)
    dependency_map: dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Python Analyzer — AST-based extraction
# ═══════════════════════════════════════════════════════════════════════════

class PythonAnalyzer:
    """Parse Python source files and extract structured representations."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_file(self, filepath: str) -> PythonModule:
        """Analyze a single Python file and return a *PythonModule*."""
        source = Path(filepath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=filepath)
        module_name = Path(filepath).stem

        imports = self._extract_imports(tree)
        classes = self._extract_classes(tree, source)
        functions = self._extract_functions(tree, source)
        globals_ = self._extract_globals(tree)
        docstring = ast.get_docstring(tree) or ""
        dependencies = self._detect_dependencies(imports)

        return PythonModule(
            path=filepath,
            module_name=module_name,
            imports=imports,
            classes=classes,
            functions=functions,
            globals=globals_,
            docstring=docstring,
            dependencies=dependencies,
        )

    def analyze_directory(self, root: str) -> list[PythonModule]:
        """Recursively analyze all ``*.py`` files under *root*."""
        modules: list[PythonModule] = []
        root_path = Path(root)
        skip_dirs = {"__pycache__", ".git", "node_modules", ".venv", "venv",
                     ".tox", ".mypy_cache", ".pytest_cache", "dist", "build"}
        for py_file in sorted(root_path.rglob("*.py")):
            if any(part in skip_dirs for part in py_file.parts):
                continue
            try:
                modules.append(self.analyze_file(str(py_file)))
            except SyntaxError as exc:
                log.warning("Skipping %s — syntax error: %s", py_file, exc)
            except Exception as exc:
                log.warning("Skipping %s — %s", py_file, exc)
        return modules

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def _extract_imports(self, tree: ast.Module) -> list[ImportInfo]:
        result: list[ImportInfo] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.append(ImportInfo(
                        module=alias.name,
                        names=[],
                        alias=alias.asname,
                    ))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = [a.name for a in (node.names or [])]
                result.append(ImportInfo(module=mod, names=names))
        return result

    # ------------------------------------------------------------------
    # Class extraction
    # ------------------------------------------------------------------

    def _extract_classes(self, tree: ast.Module, source: str) -> list[ClassInfo]:
        result: list[ClassInfo] = []
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [self._name_of(b) for b in node.bases]
            docstring = ast.get_docstring(node) or ""
            is_dc = any(
                self._name_of(d if isinstance(d, ast.Name) else d) == "dataclass"
                for d in node.decorator_list
            )

            fields: list[tuple[str, str]] = []
            methods: list[FunctionInfo] = []

            for child in node.body:
                # Annotated assignments -> fields
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    rust_ty = self._infer_type(child.annotation)
                    fields.append((child.target.id, rust_ty))
                # Methods
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(self._function_from_node(child, source, is_method=True))

            # If it's not a dataclass, try to extract fields from __init__
            if not is_dc and not fields:
                fields = self._extract_init_fields(node)

            result.append(ClassInfo(
                name=node.name,
                bases=bases,
                methods=methods,
                fields=fields,
                docstring=docstring,
                is_dataclass=is_dc,
            ))
        return result

    def _extract_init_fields(self, cls_node: ast.ClassDef) -> list[tuple[str, str]]:
        """Extract ``self.x = ...`` assignments from ``__init__``."""
        fields: list[tuple[str, str]] = []
        seen: set[str] = set()
        for child in cls_node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
                for stmt in ast.walk(child):
                    if (isinstance(stmt, ast.Assign)
                            and len(stmt.targets) == 1
                            and isinstance(stmt.targets[0], ast.Attribute)
                            and isinstance(stmt.targets[0].value, ast.Name)
                            and stmt.targets[0].value.id == "self"):
                        attr = stmt.targets[0].attr
                        if attr not in seen:
                            seen.add(attr)
                            # Try to infer type from the assigned value
                            ty = self._infer_type_from_value(stmt.value)
                            fields.append((attr, ty))
                    elif (isinstance(stmt, ast.AnnAssign)
                            and isinstance(stmt.target, ast.Attribute)
                            and isinstance(stmt.target.value, ast.Name)
                            and stmt.target.value.id == "self"):
                        attr = stmt.target.attr
                        if attr not in seen:
                            seen.add(attr)
                            ty = self._infer_type(stmt.annotation)
                            fields.append((attr, ty))
        return fields

    # ------------------------------------------------------------------
    # Function / method extraction
    # ------------------------------------------------------------------

    def _extract_functions(self, tree: ast.Module, source: str) -> list[FunctionInfo]:
        result: list[FunctionInfo] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append(self._function_from_node(node, source, is_method=False))
        return result

    def _function_from_node(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        source: str,
        *,
        is_method: bool = False,
    ) -> FunctionInfo:
        args: list[tuple[str, str]] = []
        for arg in node.args.args:
            if is_method and arg.arg == "self":
                continue
            rust_ty = self._infer_type(arg.annotation)
            args.append((arg.arg, rust_ty))

        # Defaults for *args, **kwargs
        if node.args.vararg:
            args.append((f"*{node.args.vararg.arg}", "Vec<Box<dyn std::any::Any>>"))
        if node.args.kwarg:
            args.append((f"**{node.args.kwarg.arg}", "HashMap<String, Box<dyn std::any::Any>>"))

        return_type = self._infer_type(node.returns)
        decorators = [self._name_of(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node) or ""

        # Extract body source via line numbers
        body_source = self._extract_body_source(node, source)

        return FunctionInfo(
            name=node.name,
            args=args,
            return_type=return_type,
            body_source=body_source,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            decorators=decorators,
            docstring=docstring,
            ast_body=node.body,
        )

    def _extract_body_source(self, node: ast.AST, source: str) -> str:
        """Return the raw source text of a function/class body."""
        lines = source.splitlines(keepends=True)
        start = node.lineno  # 1-indexed; body starts after the def line
        end = getattr(node, "end_lineno", None)
        if end is None:
            end = start + 20  # fallback
        # Include everything from the first line of the body to the end
        body_lines = lines[start:end]  # skip def line itself
        return "".join(body_lines)

    # ------------------------------------------------------------------
    # Global variable extraction
    # ------------------------------------------------------------------

    def _extract_globals(self, tree: ast.Module) -> list[GlobalInfo]:
        seen: dict[str, int] = {}  # name -> index in result
        result: list[GlobalInfo] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                ty = self._infer_type(node.annotation)
                val = ast.unparse(node.value) if node.value else ""
                name = node.target.id
                if name in seen:
                    result[seen[name]] = GlobalInfo(name=name, type_hint=ty, value=val)
                else:
                    seen[name] = len(result)
                    result.append(GlobalInfo(name=name, type_hint=ty, value=val))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        ty = self._infer_type_from_value(node.value)
                        val = ast.unparse(node.value) if node.value else ""
                        name = target.id
                        if name in seen:
                            result[seen[name]] = GlobalInfo(name=name, type_hint=ty, value=val)
                        else:
                            seen[name] = len(result)
                            result.append(GlobalInfo(name=name, type_hint=ty, value=val))
        return result

    # ------------------------------------------------------------------
    # Type inference helpers
    # ------------------------------------------------------------------

    def _infer_type(self, annotation: ast.expr | None) -> str:
        """Map a Python type annotation AST node to a Rust type string."""
        if annotation is None:
            return "/* unknown */"

        # Simple name: str, int, bool, ...
        if isinstance(annotation, ast.Name):
            rust_type = TYPE_MAP.get(annotation.id, annotation.id)
            # Bare generic containers — keep simple form.
            # The Subscript handler adds <T> when subscripted.
            # For bare (unsubscripted) use, _safe_type will fill in defaults.
            return rust_type

        # Attribute: pathlib.Path, io.TextIOWrapper, ...
        if isinstance(annotation, ast.Attribute):
            full = self._name_of(annotation)
            if full in TYPE_MAP:
                return TYPE_MAP[full]
            return full.replace(".", "::")

        # Constant None
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return "()"

        # Subscript: list[int], dict[str, int], Optional[str], ...
        if isinstance(annotation, ast.Subscript):
            base = self._infer_type(annotation.value)
            slice_node = annotation.slice

            # Optional[X] -> Option<X>
            if base == "Option":
                inner = self._infer_type(slice_node)
                return f"Option<{inner}>"

            # Tuple — maps to (T1, T2, ...)
            if base == "tuple":
                if isinstance(slice_node, ast.Tuple):
                    inner = ", ".join(self._infer_type(e) for e in slice_node.elts)
                    return f"({inner})"
                inner = self._infer_type(slice_node)
                return f"({inner},)"

            # dict/Dict -> HashMap<K, V>
            if base == "HashMap":
                if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 2:
                    k = self._infer_type(slice_node.elts[0])
                    v = self._infer_type(slice_node.elts[1])
                    return f"HashMap<{k}, {v}>"
                return "HashMap<String, Box<dyn std::any::Any>>"

            # Generic single-param containers: Vec<T>, HashSet<T>
            inner = self._infer_type(slice_node)
            return f"{base}<{inner}>"

        # Union via `X | Y` (Python 3.10+)
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            left = self._infer_type(annotation.left)
            right = self._infer_type(annotation.right)
            if right == "()" or right == "None":
                return f"Option<{left}>"
            if left == "()" or left == "None":
                return f"Option<{right}>"
            # General union — use enum or Box<dyn Any>
            return f"/* Union({left}, {right}) */ Box<dyn std::any::Any>"

        return "/* unknown */"

    def _infer_type_from_value(self, value: ast.expr | None) -> str:
        """Best-effort type inference from a value expression (no annotation)."""
        if value is None:
            return "/* unknown */"
        if isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                return "String"
            if isinstance(value.value, bool):
                return "bool"
            if isinstance(value.value, int):
                return "i64"
            if isinstance(value.value, float):
                return "f64"
            if isinstance(value.value, bytes):
                return "Vec<u8>"
            if value.value is None:
                return "Option</* unknown */>"
        if isinstance(value, ast.List):
            if value.elts:
                inner = self._infer_type_from_value(value.elts[0])
                return f"Vec<{inner}>"
            return "Vec</* unknown */>"
        if isinstance(value, ast.Dict):
            return "HashMap<String, /* unknown */>"
        if isinstance(value, ast.Set):
            return "HashSet</* unknown */>"
        if isinstance(value, ast.Call):
            name = self._name_of(value.func)
            if name in TYPE_MAP:
                return TYPE_MAP[name]
            return name
        return "/* unknown */"

    # ------------------------------------------------------------------
    # Dependency detection
    # ------------------------------------------------------------------

    def _detect_dependencies(self, imports: list[ImportInfo]) -> set[str]:
        deps: set[str] = set()
        for imp in imports:
            top = imp.module.split(".")[0] if imp.module else ""
            if top and top not in _STDLIB_MODULES:
                deps.add(top)
        return deps

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _name_of(node: ast.expr) -> str:
        """Reconstruct a dotted name from an AST node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = PythonAnalyzer._name_of(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        if isinstance(node, ast.Call):
            return PythonAnalyzer._name_of(node.func)
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# Rust Code Generator
# ═══════════════════════════════════════════════════════════════════════════

class RustCodegen:
    """Emit idiomatic Rust source from analysed Python modules."""

    def __init__(self, config: TranspileConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Module-level generation
    # ------------------------------------------------------------------

    def generate_module(self, module: PythonModule, all_module_names: set[str] | None = None) -> str:
        """Generate the complete Rust source file for one Python module."""
        sections: list[str] = []

        # Module docstring
        if module.docstring:
            sections.append(self._rust_doc_comment(module.docstring))

        # Use statements
        uses = self._generate_uses(module, all_module_names)
        if uses:
            sections.append(uses)

        # Global constants / statics
        # Collect names imported from other modules (to skip re-definitions)
        imported_names: set[str] = set()
        for imp in module.imports:
            imported_names.update(imp.names)  # from X import a, b, c

        for g in module.globals:
            if g.name in imported_names:
                continue  # Skip — already imported from another module
            sections.append(self._generate_global(g))

        # Structs + impl blocks
        for cls in module.classes:
            sections.append(self.generate_struct(cls))
            sections.append(self.generate_impl_block(cls))

        # Free functions
        for func in module.functions:
            sections.append(self.generate_function(func))

        return "\n\n".join(s for s in sections if s) + "\n"

    # ------------------------------------------------------------------
    # Use / import generation
    # ------------------------------------------------------------------

    def _generate_uses(self, module: PythonModule, all_module_names: set[str] | None = None) -> str:
        uses: set[str] = set()
        if all_module_names is None:
            all_module_names = set()

        # Always needed for HashMap / HashSet if referenced
        src = "\n".join(
            self.generate_struct(c) + self.generate_impl_block(c)
            for c in module.classes
        ) + "\n".join(self.generate_function(f) for f in module.functions)

        if "HashMap" in src:
            uses.add("use std::collections::HashMap;")
        if "HashSet" in src:
            uses.add("use std::collections::HashSet;")
        if "PathBuf" in src:
            uses.add("use std::path::PathBuf;")
        if "File" in src:
            uses.add("use std::fs::File;")
            uses.add("use std::io::{self, Read, Write};")
        if "Regex" in src:
            uses.add("use regex::Regex;")

        # Error handling
        if self.config.error_strategy == "anyhow":
            uses.add("use anyhow::{Result, Context};")
        elif self.config.error_strategy == "thiserror":
            uses.add("use thiserror::Error;")

        # Async
        if self.config.async_runtime == "tokio" and "async " in src:
            uses.add("use tokio;")

        # Serde for dataclass structs
        for cls in module.classes:
            if cls.is_dataclass:
                uses.add("use serde::{Serialize, Deserialize};")
                break

        # Cross-module imports: translate Python imports to Rust `use crate::`
        for imp in module.imports:
            mod_name = imp.module.split(".")[-1] if imp.module else ""
            # Skip Python stdlib / third-party modules
            python_stdlib = {
                "os", "sys", "json", "re", "time", "datetime", "math",
                "collections", "itertools", "functools", "typing",
                "pathlib", "subprocess", "threading", "multiprocessing",
                "unittest", "pytest", "logging", "io", "abc", "enum",
                "dataclasses", "copy", "shutil", "tempfile", "glob",
                "hashlib", "base64", "uuid", "socket", "http", "urllib",
                "sqlite3", "contextlib", "traceback", "inspect", "signal",
                "argparse", "textwrap", "string", "struct", "pickle",
                "csv", "configparser", "importlib", "warnings", "platform",
                "random", "secrets", "getpass", "pprint", "operator",
            }
            if mod_name in python_stdlib or imp.module in python_stdlib:
                continue
            # If this module name matches another module in the project, add use
            sanitized = self._sanitize_ident(mod_name)
            if sanitized in all_module_names:
                alias = imp.alias
                if alias:
                    alias_s = self._sanitize_ident(alias)
                    uses.add(f"use crate::{sanitized} as {alias_s};")
                elif imp.names:
                    names = ", ".join(self._sanitize_ident(n) for n in imp.names)
                    uses.add(f"use crate::{sanitized}::{{{names}}};")
                else:
                    uses.add(f"use crate::{sanitized}::*;")

        sorted_uses = sorted(uses)
        return "\n".join(sorted_uses)

    # ------------------------------------------------------------------
    # Global constants
    # ------------------------------------------------------------------

    def _generate_global(self, g: GlobalInfo) -> str:
        """Generate a Rust constant/static from a Python module-level variable."""
        ty = self._safe_type(g.type_hint)
        name = g.name.upper()  # Rust constants are SCREAMING_SNAKE_CASE

        # Try to translate the Python value to Rust
        rust_val = self._translate_global_value(g.value, ty)

        if ty in ("i64", "i32", "f64", "f32", "bool", "usize", "isize"):
            return f"pub const {name}: {ty} = {rust_val};"
        if ty == "String" or ty == "&str":
            # Use &str for string constants
            return f'pub const {name}: &str = {rust_val};'
        # Complex types — use std::sync::LazyLock for runtime-initialized statics
        # Keep original name casing for non-UPPER_CASE Python globals
        orig_name = self._sanitize_ident(g.name)
        return (
            f"pub static {name}: std::sync::LazyLock<{ty}> = "
            f"std::sync::LazyLock::new(|| {rust_val});"
        )

    def _translate_global_value(self, val: str, ty: str) -> str:
        """Translate a Python value literal to Rust."""
        if not val:
            return self._rust_default_for_type(ty)
        val = val.strip()
        # Numeric
        if ty in ("i64", "i32", "usize", "isize"):
            try:
                return str(int(ast.literal_eval(val)))
            except Exception:
                return "0"
        if ty in ("f64", "f32"):
            try:
                return str(float(ast.literal_eval(val)))
            except Exception:
                return "0.0"
        if ty == "bool":
            if val in ("True", "true"):
                return "true"
            if val in ("False", "false"):
                return "false"
            return "false"
        # String
        if ty in ("String", "&str"):
            # Strip Python quotes and re-quote for Rust
            s = val.strip("'\"")
            s = s.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{s}"'
        return self._rust_default_for_type(ty)

    # ------------------------------------------------------------------
    # Struct generation
    # ------------------------------------------------------------------

    def generate_struct(self, cls: ClassInfo) -> str:
        lines: list[str] = []
        if cls.docstring:
            lines.append(self._rust_doc_comment(cls.docstring))

        # Derive macros
        derives = ["Debug", "Clone"]
        if cls.is_dataclass:
            derives.extend(["Serialize", "Deserialize"])
        lines.append(f"#[derive({', '.join(derives)})]")
        lines.append(f"pub struct {cls.name} {{")

        for fname, ftype in cls.fields:
            rust_ty = self._safe_type(ftype)
            lines.append(f"    pub {self._sanitize_ident(fname)}: {rust_ty},")

        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Impl block generation
    # ------------------------------------------------------------------

    def generate_impl_block(self, cls: ClassInfo) -> str:
        if not cls.methods:
            return ""
        lines: list[str] = [f"impl {cls.name} {{"]

        for method in cls.methods:
            # __init__ -> new()
            if method.name == "__init__":
                lines.append(self._generate_constructor(cls, method))
            elif "property" in method.decorators:
                lines.append(self._generate_getter(method))
            elif "staticmethod" in method.decorators:
                lines.append(self._generate_static_method(method))
            elif "classmethod" in method.decorators:
                lines.append(self._generate_class_method(cls, method))
            else:
                lines.append(self._generate_method(method))

        lines.append("}")
        return "\n".join(lines)

    def _generate_constructor(self, cls: ClassInfo, method: FunctionInfo) -> str:
        """Translate ``__init__`` to ``fn new(...) -> Self``."""
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {self._safe_type(ty)}"
            for name, ty in method.args
        )
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        lines.append(f"    pub fn new({params}) -> Self {{")

        # Try to extract self.field = expr assignments from __init__ AST
        field_inits: dict[str, str] = {}
        if method.ast_body:
            import ast as _ast
            for stmt in method.ast_body:
                if isinstance(stmt, _ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if (isinstance(tgt, _ast.Attribute)
                            and isinstance(tgt.value, _ast.Name)
                            and tgt.value.id == "self"):
                        fname = tgt.attr
                        try:
                            val = self._translate_ast_expr(stmt.value)
                            field_inits[fname] = val
                        except Exception:
                            pass

        # Build param name set for shorthand usage
        param_names = {self._sanitize_ident(n) for n, _ in method.args}

        lines.append("        Self {")
        for fname, ftype in cls.fields:
            safe_name = self._sanitize_ident(fname)
            if fname in field_inits:
                val = field_inits[fname]
                # If the init value is just the param name, use shorthand
                if val == safe_name and safe_name in param_names:
                    lines.append(f"            {safe_name},")
                else:
                    lines.append(f"            {safe_name}: {val},")
            elif safe_name in param_names:
                lines.append(f"            {safe_name},")
            else:
                lines.append(f"            {safe_name}: {self._rust_default_for_type(ftype)},")
        lines.append("        }")
        lines.append("    }")
        return "\n".join(lines)

    def _generate_getter(self, method: FunctionInfo) -> str:
        """Translate ``@property`` to a getter method."""
        ret = method.return_type if method.return_type != "/* unknown */" else "String"
        borrow = "&" if ret == "String" else ""
        ret_ty = f"&{ret}" if ret == "String" else ret
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        lines.append(f"    pub fn {self._sanitize_ident(method.name)}(&self) -> {ret_ty} {{")
        # Translate body or provide a placeholder
        body_lines = self.translate_body(method, indent=8)
        for bl in body_lines:
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    def _generate_static_method(self, method: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {self._safe_type(ty)}"
            for name, ty in method.args
        )
        ret = self._return_sig(method)
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        async_kw = "async " if method.is_async else ""
        lines.append(f"    pub {async_kw}fn {self._sanitize_ident(method.name)}({params}) -> {ret} {{")
        for bl in self.translate_body(method, indent=8):
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    def _generate_class_method(self, cls: ClassInfo, method: FunctionInfo) -> str:
        # Filter out 'cls' parameter
        args = [(n, t) for n, t in method.args if n != "cls"]
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {ty}"
            for name, ty in args
        )
        ret = self._return_sig(method)
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        async_kw = "async " if method.is_async else ""
        lines.append(f"    pub {async_kw}fn {self._sanitize_ident(method.name)}({params}) -> {ret} {{")
        for bl in self.translate_body(method, indent=8):
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    def _generate_method(self, method: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {self._safe_type(ty)}"
            for name, ty in method.args
        )
        self_param = "&mut self" if self._mutates_self(method) else "&self"
        if params:
            params = f"{self_param}, {params}"
        else:
            params = self_param
        ret = self._return_sig(method)
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        async_kw = "async " if method.is_async else ""
        lines.append(f"    pub {async_kw}fn {self._sanitize_ident(method.name)}({params}) -> {ret} {{")
        for bl in self.translate_body(method, indent=8):
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Free function generation
    # ------------------------------------------------------------------

    @staticmethod
    @staticmethod
    def _rust_default_for_type(ty: str) -> str:
        """Return a sensible Rust default-value literal for a given type."""
        ty = ty.strip()
        if ty in ("i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8", "isize", "usize"):
            return "0"
        if ty in ("f64", "f32"):
            return "0.0"
        if ty == "bool":
            return "false"
        if ty == "String" or ty == "&str":
            return "String::new()"
        if ty == "char":
            return "'\\0'"
        if ty.startswith("Vec<"):
            return "Vec::new()"
        if ty.startswith("HashMap<"):
            return "HashMap::new()"
        if ty.startswith("HashSet<"):
            return "HashSet::new()"
        if ty.startswith("Option<"):
            return "None"
        if ty.startswith("Box<"):
            return "Box::new(Default::default())"
        if "Mutex<" in ty:
            inner = ty.split("Mutex<", 1)[1].rstrip(">")
            if inner == "()" or not inner:
                return "std::sync::Mutex::new(())"
            return "std::sync::Mutex::new(Default::default())"
        # Fallback — use Default trait
        return "Default::default()"

    @staticmethod
    def _safe_type(ty: str) -> str:
        """Replace placeholder types with compilable defaults."""
        if ty == "/* unknown */" or not ty or ty.isspace():
            return "String"
        # Bare generic containers without type params
        if ty == "HashMap":
            return "HashMap<String, serde_json::Value>"
        if ty == "Vec":
            return "Vec<serde_json::Value>"
        if ty == "HashSet":
            return "HashSet<String>"
        # Python types with no direct Rust equivalent → generic fallback
        non_rust = {
            "threading.Lock": "std::sync::Mutex<()>",
            "threading.RLock": "std::sync::Mutex<()>",
            "threading.Thread": "std::thread::JoinHandle<()>",
            "threading.Event": "std::sync::Condvar",
            "socket.socket": "std::net::TcpStream",
            "sqlite3.Connection": "/* sqlite */ String",
            "logging.Logger": "/* logger */ String",
        }
        if ty in non_rust:
            return non_rust[ty]
        # Replace embedded /* unknown */ with serde_json::Value
        ty = ty.replace("/* unknown */", "serde_json::Value")
        # Replace Python dotted module paths that aren't valid Rust
        if "." in ty and "::" not in ty and "<" not in ty:
            ty = f"String /* {ty} */"
        return ty

    def generate_function(self, func: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {self._safe_type(ty)}"
            for name, ty in func.args
        )
        ret = self._return_sig(func)
        lines: list[str] = []
        if func.docstring:
            lines.append(self._rust_doc_comment(func.docstring))
        async_kw = "async " if func.is_async else ""
        lines.append(f"pub {async_kw}fn {self._sanitize_ident(func.name)}({params}) -> {ret} {{")
        for bl in self.translate_body(func, indent=4):
            lines.append(bl)
        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Cargo.toml generation
    # ------------------------------------------------------------------

    def generate_cargo_toml(self, modules: list[PythonModule]) -> str:
        all_deps: set[str] = set()
        for m in modules:
            all_deps |= m.dependencies

        # Map Python deps to Rust crates
        crate_deps: dict[str, str] = {}

        # Always include serde for derive macros
        crate_deps["serde"] = _CRATE_VERSIONS.get("serde", '"1"')

        if self.config.error_strategy == "anyhow":
            crate_deps["anyhow"] = _CRATE_VERSIONS.get("anyhow", '"1"')
        elif self.config.error_strategy == "thiserror":
            crate_deps["thiserror"] = _CRATE_VERSIONS.get("thiserror", '"1"')

        for py_dep in all_deps:
            rust_crate = CRATE_MAP.get(py_dep)
            if rust_crate and not rust_crate.startswith("std::") and not rust_crate.startswith("("):
                version = _CRATE_VERSIONS.get(rust_crate, '"0.1"')
                crate_deps[rust_crate] = version

        # Check module contents for additional needs
        all_src = ""
        for m in modules:
            for c in m.classes:
                if c.is_dataclass:
                    crate_deps["serde_json"] = _CRATE_VERSIONS.get("serde_json", '"1"')
                    break

        has_async = any(
            f.is_async
            for m in modules
            for f in m.functions + [meth for c in m.classes for meth in c.methods]
        )
        if has_async and self.config.async_runtime == "tokio":
            crate_deps["tokio"] = _CRATE_VERSIONS.get("tokio", '{ version = "1", features = ["full"] }')

        dep_lines = "\n".join(
            f'{name} = {ver}'
            for name, ver in sorted(crate_deps.items())
        )

        return (
            f'[package]\n'
            f'name = "{self.config.crate_name}"\n'
            f'version = "0.1.0"\n'
            f'edition = "2021"\n'
            f'\n'
            f'[dependencies]\n'
            f'{dep_lines}\n'
        )

    # ------------------------------------------------------------------
    # mod.rs / lib.rs generation
    # ------------------------------------------------------------------

    def generate_mod_rs(self, modules: list[PythonModule]) -> str:
        lines: list[str] = []
        for m in modules:
            mod_name = self._sanitize_ident(m.module_name)
            if mod_name == "mod" or mod_name == "__init__":
                continue
            lines.append(f"pub mod {mod_name};")
        return "\n".join(sorted(lines)) + "\n"

    # ------------------------------------------------------------------
    # Body translation — AST-based (preferred)
    # ------------------------------------------------------------------

    def translate_body(self, func: FunctionInfo, indent: int = 4) -> list[str]:
        """Route to AST-based or line-based translation."""
        if func.ast_body is not None:
            try:
                return self._translate_body_ast(func.ast_body, indent)
            except Exception as exc:
                log.debug("AST codegen failed for %s: %s; falling back to line-based", func.name, exc)
        return self._translate_body(func.body_source, indent)  # line-based fallback only

    def _translate_body_ast(self, stmts: list, indent: int = 4) -> list[str]:
        """Translate a list of ast.stmt nodes to Rust lines."""
        lines: list[str] = []
        for stmt in stmts:
            lines.extend(self._translate_stmt(stmt, indent))
        return lines

    def _translate_stmt(self, node: ast.AST, indent: int) -> list[str]:
        """Translate a single AST statement to Rust lines."""
        pad = " " * indent

        # ── Docstrings (string-only expression statements) ──
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            # Docstring or standalone string expression → comment
            for line in node.value.value.strip().splitlines():
                return [f"{pad}// {line.strip()}" for line in node.value.value.strip().splitlines()]

        # ── Expression statement (function call, etc.) ──
        if isinstance(node, ast.Expr):
            expr_rust = self._translate_ast_expr(node.value)
            return [f"{pad}{expr_rust};"]

        # ── Return ──
        if isinstance(node, ast.Return):
            if node.value is None:
                return [f"{pad}return;"]
            val = self._translate_ast_expr(node.value)
            return [f"{pad}{val}"]

        # ── Assignment: x = expr ──
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target_node = node.targets[0]
            value = self._translate_ast_expr(node.value)
            # Attribute/subscript targets: no `let`, just reassign
            if isinstance(target_node, (ast.Attribute, ast.Subscript)):
                target = self._translate_ast_target(target_node)
                return [f"{pad}{target} = {value};"]
            # Tuple unpacking: (a, b) = ... → let (mut a, mut b) = ...
            if isinstance(target_node, ast.Tuple):
                parts = []
                for e in target_node.elts:
                    t = self._translate_ast_target(e)
                    # Don't add mut to _ (wildcard) or attribute/subscript targets
                    if t == "_" or "." in t or "[" in t:
                        parts.append(t)
                    else:
                        parts.append(f"mut {t}")
                return [f"{pad}let ({', '.join(parts)}) = {value};"]
            # Simple name target: let mut x = ...
            target = self._translate_ast_target(target_node)
            return [f"{pad}let mut {target} = {value};"]

        # ── Annotated assignment: x: int = expr ──
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target = self._translate_ast_target(node.target)
            value = self._translate_ast_expr(node.value)
            return [f"{pad}let mut {target} = {value};"]

        # ── Augmented assignment: x += 1 ──
        if isinstance(node, ast.AugAssign):
            target = self._translate_ast_target(node.target)
            op = self._translate_ast_binop(node.op)
            value = self._translate_ast_expr(node.value)
            return [f"{pad}{target} {op}= {value};"]

        # ── If / elif / else ──
        if isinstance(node, ast.If):
            return self._translate_if(node, indent)

        # ── For loop ──
        if isinstance(node, ast.For):
            target = self._translate_ast_target(node.target)
            iter_expr = self._translate_ast_expr(node.iter)
            lines = [f"{pad}for {target} in {iter_expr}.iter() {{"]
            for stmt in node.body:
                lines.extend(self._translate_stmt(stmt, indent + 4))
            lines.append(f"{pad}}}")
            return lines

        # ── While loop ──
        if isinstance(node, ast.While):
            cond = self._translate_ast_expr(node.test)
            lines = [f"{pad}while {cond} {{"]
            for stmt in node.body:
                lines.extend(self._translate_stmt(stmt, indent + 4))
            lines.append(f"{pad}}}")
            return lines

        # ── Try/Except ──
        if isinstance(node, ast.Try):
            return self._translate_try(node, indent)

        # ── With statement ──
        if isinstance(node, ast.With):
            return self._translate_with(node, indent)

        # ── Pass ──
        if isinstance(node, ast.Pass):
            return [f"{pad}// pass"]

        # ── Break / Continue ──
        if isinstance(node, ast.Break):
            return [f"{pad}break;"]
        if isinstance(node, ast.Continue):
            return [f"{pad}continue;"]

        # ── Assert ──
        if isinstance(node, ast.Assert):
            test = self._translate_ast_expr(node.test)
            if node.msg:
                msg = self._translate_ast_expr(node.msg)
                # assert! takes a format string directly, not format!()
                msg = msg.replace('.to_string()', '')
                if msg.startswith('format!('):
                    # Unwrap format!("...", args) → "...", args
                    msg = msg[8:-1]
                return [f"{pad}assert!({test}, {msg});"]
            return [f"{pad}assert!({test});"]

        # ── Raise ──
        if isinstance(node, ast.Raise):
            if node.exc:
                # Get a safe string representation for the error
                try:
                    exc_str = ast.unparse(node.exc)
                except Exception:
                    exc_str = "error"
                # Escape for embedding in a string literal
                exc_str = exc_str.replace("\\", "\\\\").replace('"', '\\"')
                if self.config.error_strategy == "anyhow":
                    return [f'{pad}return Err(anyhow::anyhow!("{exc_str}"));']
                return [f'{pad}return Err("{exc_str}".into());']
            return [f"{pad}return Err(anyhow::anyhow!(\"re-raised error\"));"]

        # ── Delete ──
        if isinstance(node, ast.Delete):
            targets = [self._translate_ast_target(t) for t in node.targets]
            return [f"{pad}drop({t});" for t in targets]

        # ── Global / Nonlocal (no-op in Rust) ──
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            names = ", ".join(node.names)
            return [f"{pad}// global/nonlocal {names}"]

        # ── Async for / Async with ──
        if isinstance(node, ast.AsyncFor):
            target = self._translate_ast_target(node.target)
            iter_expr = self._translate_ast_expr(node.iter)
            lines = [f"{pad}// async for"]
            lines.append(f"{pad}while let Some({target}) = {iter_expr}.next().await {{")
            for stmt in node.body:
                lines.extend(self._translate_stmt(stmt, indent + 4))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(node, ast.AsyncWith):
            return self._translate_with(node, indent, is_async=True)

        # ── Class definition (nested) ──
        if isinstance(node, ast.ClassDef):
            return [f"{pad}// TODO: nested class {node.name}"]

        # ── Function definition (nested / inner function) ──
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._translate_inner_function(node, indent)

        # ── Fallback: use ast.unparse to get the original Python ──
        try:
            py_src = ast.unparse(node)
            return [f"{pad}// TODO: {py_src}"]
        except Exception:
            return [f"{pad}// TODO: <unparseable statement>"]

    # ── Compound statement helpers ──

    def _translate_if(self, node: ast.If, indent: int) -> list[str]:
        pad = " " * indent
        cond = self._translate_ast_expr(node.test)
        lines = [f"{pad}if {cond} {{"]
        for stmt in node.body:
            lines.extend(self._translate_stmt(stmt, indent + 4))
        # Handle elif chain and else
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                # elif
                elif_node = orelse[0]
                cond = self._translate_ast_expr(elif_node.test)
                lines.append(f"{pad}}} else if {cond} {{")
                for stmt in elif_node.body:
                    lines.extend(self._translate_stmt(stmt, indent + 4))
                orelse = elif_node.orelse
            else:
                # else
                lines.append(f"{pad}}} else {{")
                for stmt in orelse:
                    lines.extend(self._translate_stmt(stmt, indent + 4))
                orelse = None
        lines.append(f"{pad}}}")
        return lines

    def _translate_try(self, node: ast.Try, indent: int) -> list[str]:
        pad = " " * indent
        lines = [f"{pad}// try:"]
        lines.append(f"{pad}{{")
        for stmt in node.body:
            lines.extend(self._translate_stmt(stmt, indent + 4))
        lines.append(f"{pad}}}")
        for handler in node.handlers:
            exc_type = ""
            if handler.type:
                exc_type = self._translate_ast_expr(handler.type)
            exc_name = handler.name or "_e"
            lines.append(f"{pad}// except {exc_type} as {exc_name}:")
        # orelse (else clause)
        if node.orelse:
            lines.append(f"{pad}// else:")
            for stmt in node.orelse:
                lines.extend(self._translate_stmt(stmt, indent + 4))
        # finalbody
        if node.finalbody:
            lines.append(f"{pad}// finally:")
            for stmt in node.finalbody:
                lines.extend(self._translate_stmt(stmt, indent + 4))
        return lines

    def _translate_with(self, node, indent: int, *, is_async: bool = False) -> list[str]:
        pad = " " * indent
        lines = []
        for item in node.items:
            ctx = self._translate_ast_expr(item.context_expr)
            if item.optional_vars:
                var = self._translate_ast_target(item.optional_vars)
                lines.append(f"{pad}let mut {var} = {ctx};")
            else:
                lines.append(f"{pad}let _ctx = {ctx};")
        lines.append(f"{pad}{{")
        for stmt in node.body:
            lines.extend(self._translate_stmt(stmt, indent + 4))
        lines.append(f"{pad}}}")
        return lines

    def _translate_inner_function(self, node, indent: int) -> list[str]:
        pad = " " * indent
        name = RustCodegen._sanitize_ident(node.name)
        args = []
        for arg in node.args.args:
            if arg.arg == "self":
                continue
            args.append(f"{RustCodegen._sanitize_ident(arg.arg)}: /* TODO */")
        sig = f"fn {name}({', '.join(args)})"
        lines = [f"{pad}let {name} = |{', '.join(a.arg for a in node.args.args if a.arg != 'self')}| {{"]
        for stmt in node.body:
            lines.extend(self._translate_stmt(stmt, indent + 4))
        lines.append(f"{pad}}};")
        return lines

    # ------------------------------------------------------------------
    # AST expression translator
    # ------------------------------------------------------------------

    def _translate_ast_expr(self, node: ast.expr) -> str:
        """Translate a Python AST expression node to a Rust expression string."""
        if node is None:
            return "/* None */"

        # ── Constants (strings, numbers, booleans, None) ──
        if isinstance(node, ast.Constant):
            return self._translate_ast_constant(node)

        # ── Name (variable reference) ──
        if isinstance(node, ast.Name):
            name = node.id
            if name == "None":
                return "None"
            if name == "True":
                return "true"
            if name == "False":
                return "false"
            if name == "self":
                return "self"
            return RustCodegen._sanitize_ident(name)

        # ── Attribute access: obj.attr ──
        if isinstance(node, ast.Attribute):
            obj = self._translate_ast_expr(node.value)
            attr = node.attr
            # Common Python→Rust method renames
            renames = {
                "append": "push", "strip": "trim", "lstrip": "trim_start",
                "rstrip": "trim_end", "startswith": "starts_with",
                "endswith": "ends_with", "lower": "to_lowercase",
                "upper": "to_uppercase",
            }
            attr = renames.get(attr, attr)
            return f"{obj}.{attr}"

        # ── Function/method call ──
        if isinstance(node, ast.Call):
            return self._translate_ast_call(node)

        # ── Binary operation ──
        if isinstance(node, ast.BinOp):
            left = self._translate_ast_expr(node.left)
            right = self._translate_ast_expr(node.right)
            # Power operator: x ** y → x.pow(y)
            if isinstance(node.op, ast.Pow):
                return f"({left}).pow({right} as u32)"
            op = self._translate_ast_binop(node.op)
            return f"({left} {op} {right})"

        # ── Unary operation ──
        if isinstance(node, ast.UnaryOp):
            operand = self._translate_ast_expr(node.operand)
            if isinstance(node.op, ast.Not):
                return f"!{operand}"
            if isinstance(node.op, ast.USub):
                return f"-{operand}"
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.Invert):
                return f"!{operand}"
            return f"/* unary */ {operand}"

        # ── Boolean operation (and/or) ──
        if isinstance(node, ast.BoolOp):
            op = " && " if isinstance(node.op, ast.And) else " || "
            parts = [self._translate_ast_expr(v) for v in node.values]
            return f"({op.join(parts)})"

        # ── Comparison ──
        if isinstance(node, ast.Compare):
            return self._translate_ast_compare(node)

        # ── Subscript: x[key] ──
        if isinstance(node, ast.Subscript):
            obj = self._translate_ast_expr(node.value)
            sl = self._translate_ast_expr(node.slice)
            # HashMap indexing requires a reference; add & for non-literal keys
            if isinstance(node.slice, (ast.Name, ast.Attribute, ast.Call)):
                return f"{obj}[&{sl}]"
            return f"{obj}[{sl}]"

        # ── Slice ──
        if isinstance(node, ast.Slice):
            lower = self._translate_ast_expr(node.lower) if node.lower else ""
            upper = self._translate_ast_expr(node.upper) if node.upper else ""
            return f"{lower}..{upper}"

        # ── List literal ──
        if isinstance(node, ast.List):
            if not node.elts:
                return "vec![]"
            # Check for starred elements (*x) — need special handling
            has_starred = any(isinstance(e, ast.Starred) for e in node.elts)
            if has_starred:
                parts = []
                for e in node.elts:
                    if isinstance(e, ast.Starred):
                        val = self._translate_ast_expr(e.value)
                        parts.append(f"..{val}")
                    else:
                        parts.append(self._translate_ast_expr(e))
                # Build using chain: [a, *b, c] → { let mut v = vec![a]; v.extend(b); v.push(c); v }
                stmts = ["let mut _v = Vec::new()"]
                for e in node.elts:
                    if isinstance(e, ast.Starred):
                        val = self._translate_ast_expr(e.value)
                        stmts.append(f"_v.extend({val})")
                    else:
                        val = self._translate_ast_expr(e)
                        stmts.append(f"_v.push({val})")
                stmts.append("_v")
                return "{ " + "; ".join(stmts) + " }"
            elts = ", ".join(self._translate_ast_expr(e) for e in node.elts)
            return f"vec![{elts}]"

        # ── Tuple literal ──
        if isinstance(node, ast.Tuple):
            elts = ", ".join(self._translate_ast_expr(e) for e in node.elts)
            return f"({elts})"

        # ── Dict literal ──
        if isinstance(node, ast.Dict):
            if not node.keys:
                return "HashMap::new()"
            pairs = []
            for k, v in zip(node.keys, node.values):
                if k is None:
                    continue  # **splat
                pairs.append(f"({self._translate_ast_expr(k)}, {self._translate_ast_expr(v)})")
            if not pairs:
                return "HashMap::new()"
            return f"HashMap::from([{', '.join(pairs)}])"

        # ── Set literal ──
        if isinstance(node, ast.Set):
            elts = ", ".join(self._translate_ast_expr(e) for e in node.elts)
            return f"HashSet::from([{elts}])"

        # ── f-string (JoinedStr) ──
        if isinstance(node, ast.JoinedStr):
            return self._translate_ast_fstring(node)

        # ── List comprehension ──
        if isinstance(node, ast.ListComp):
            return self._translate_ast_listcomp(node)

        # ── Set comprehension ──
        if isinstance(node, ast.SetComp):
            gen = node.generators[0] if node.generators else None
            if gen:
                target = self._translate_ast_target(gen.target)
                iter_expr = self._translate_ast_expr(gen.iter)
                elt = self._translate_ast_expr(node.elt)
                chain = f"{iter_expr}.iter()"
                for cond in gen.ifs:
                    chain += f".filter(|{target}| {self._translate_ast_expr(cond)})"
                chain += f".map(|{target}| {elt}).collect::<HashSet<_>>()"
                return chain
            return "HashSet::new()"

        # ── Dict comprehension ──
        if isinstance(node, ast.DictComp):
            return self._translate_ast_dictcomp(node)

        # ── Generator expression ──
        if isinstance(node, ast.GeneratorExp):
            return self._translate_ast_listcomp(node)  # same pattern

        # ── Ternary: x if cond else y ──
        if isinstance(node, ast.IfExp):
            cond = self._translate_ast_expr(node.test)
            body = self._translate_ast_expr(node.body)
            orelse = self._translate_ast_expr(node.orelse)
            return f"if {cond} {{ {body} }} else {{ {orelse} }}"

        # ── Lambda ──
        if isinstance(node, ast.Lambda):
            args = ", ".join(a.arg for a in node.args.args)
            body = self._translate_ast_expr(node.body)
            return f"|{args}| {body}"

        # ── Await ──
        if isinstance(node, ast.Await):
            val = self._translate_ast_expr(node.value)
            return f"{val}.await"

        # ── Starred (*x) ──
        if isinstance(node, ast.Starred):
            val = self._translate_ast_expr(node.value)
            return f"/* *{val} */"

        # ── Yield / YieldFrom ──
        if isinstance(node, ast.Yield):
            if node.value:
                val = self._translate_ast_expr(node.value)
                return f"/* yield {val} */"
            return "/* yield */"
        if isinstance(node, ast.YieldFrom):
            val = self._translate_ast_expr(node.value)
            return f"/* yield from */ {val}"

        # ── Fallback ──
        try:
            return ast.unparse(node)
        except Exception:
            return "/* TODO */"

    # ── AST expression helpers ──

    def _translate_ast_constant(self, node: ast.Constant) -> str:
        """Translate a constant (string, number, bool, None)."""
        val = node.value
        if val is None:
            return "None"
        if val is True:
            return "true"
        if val is False:
            return "false"
        if isinstance(val, str):
            # Escape for Rust string literal — always use double quotes
            escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            return f'"{escaped}".to_string()'
        if isinstance(val, bytes):
            return f'b"{val.decode("ascii", errors="replace")}"'
        if isinstance(val, int):
            return str(val)
        if isinstance(val, float):
            s = repr(val)
            if "." not in s and "e" not in s and "E" not in s:
                s += ".0"
            return f"{s}_f64"
        return repr(val)

    def _translate_ast_fstring(self, node: ast.JoinedStr) -> str:
        """Translate an f-string (JoinedStr) to format!()."""
        fmt_parts = []
        args = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                # Literal text portion — escape { and } for format!
                text = value.value.replace("\\", "\\\\").replace("{", "{{").replace("}", "}}")
                text = text.replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
                fmt_parts.append(text)
            elif isinstance(value, ast.FormattedValue):
                expr = self._translate_ast_expr(value.value)
                if value.format_spec:
                    # format_spec is itself a JoinedStr
                    spec = ""
                    if isinstance(value.format_spec, ast.JoinedStr):
                        for part in value.format_spec.values:
                            if isinstance(part, ast.Constant):
                                spec += part.value
                    rust_spec = self._python_fmt_to_rust(spec)
                    fmt_parts.append("{" + rust_spec + "}")
                else:
                    fmt_parts.append("{}")
                args.append(expr)
            else:
                fmt_parts.append("{}")
                args.append(self._translate_ast_expr(value))
        fmt_str = "".join(fmt_parts)
        if args:
            return f'format!("{fmt_str}", {", ".join(args)})'
        return f'format!("{fmt_str}")'

    def _translate_ast_call(self, node: ast.Call) -> str:
        """Translate a function/method call."""
        func_name = self._translate_ast_expr(node.func)

        # Translate args (skip keyword-only like flush=True)
        pos_args = [self._translate_ast_expr(a) for a in node.args]
        kw_args = []
        skip_kw = {"flush", "file", "end"}  # print() kwargs to skip
        for kw in node.keywords:
            if kw.arg in skip_kw:
                continue
            if kw.arg:
                kw_args.append(f"/* {kw.arg}= */ {self._translate_ast_expr(kw.value)}")
            else:
                kw_args.append(f"/* ** */ {self._translate_ast_expr(kw.value)}")

        all_args = pos_args + kw_args

        # Special function translations
        # print(...) → println!(...)
        if func_name == "print":
            if not all_args:
                return 'println!()'
            if len(all_args) == 1:
                # If it's already a format! call, unwrap it
                arg = all_args[0]
                if arg.startswith('format!('):
                    inner = arg[8:-1]  # strip format!( and )
                    return f"println!({inner})"
                return f'println!("{{}}", {arg})'
            return f'println!("{{}}", {", ".join(all_args)})'

        # len(x) → x.len()
        if func_name == "len" and len(all_args) == 1:
            return f"{all_args[0]}.len()"

        # str(x) → x.to_string() or format!("{}", x)
        if func_name == "str" and len(all_args) == 1:
            return f'{all_args[0]}.to_string()'

        # int(x) → x.parse::<i64>().unwrap_or(0)
        if func_name == "int" and len(all_args) == 1:
            return f'{all_args[0]}.to_string().parse::<i64>().unwrap_or(0)'

        # float(x) → x.parse::<f64>().unwrap_or(0.0)
        if func_name == "float" and len(all_args) == 1:
            return f'{all_args[0]}.to_string().parse::<f64>().unwrap_or(0.0)'

        # isinstance(x, T) → placeholder
        if func_name == "isinstance" and len(all_args) == 2:
            return f'/* isinstance({all_args[0]}, {all_args[1]}) */ true'

        # range(n) → 0..n
        if func_name == "range":
            if len(all_args) == 1:
                return f"0..{all_args[0]}"
            if len(all_args) == 2:
                return f"{all_args[0]}..{all_args[1]}"
            if len(all_args) == 3:
                return f"({all_args[0]}..{all_args[1]}).step_by({all_args[2]} as usize)"

        # enumerate(x) → x.iter().enumerate()
        if func_name == "enumerate" and len(all_args) >= 1:
            return f"{all_args[0]}.iter().enumerate()"

        # zip(a, b) → a.iter().zip(b.iter())
        if func_name == "zip" and len(all_args) == 2:
            return f"{all_args[0]}.iter().zip({all_args[1]}.iter())"

        # sorted(x) → { let mut v = x.clone(); v.sort(); v }
        if func_name == "sorted" and len(all_args) >= 1:
            return f"{{ let mut v = {all_args[0]}.clone(); v.sort(); v }}"

        # reversed(x) → x.iter().rev()
        if func_name == "reversed" and len(all_args) == 1:
            return f"{all_args[0]}.iter().rev()"

        # any/all
        if func_name in ("any", "all") and len(all_args) == 1:
            return f"{all_args[0]}.iter().{func_name}(|v| *v)"

        # sum
        if func_name == "sum" and len(all_args) >= 1:
            return f"{all_args[0]}.iter().sum::<i64>()"

        # min/max
        if func_name in ("min", "max") and len(all_args) == 1:
            return f"{all_args[0]}.iter().{func_name}().unwrap()"
        if func_name in ("min", "max") and len(all_args) == 2:
            return f"{all_args[0]}.{func_name}({all_args[1]})"

        # open(path) → File::open(path)?
        if func_name == "open":
            path = all_args[0] if all_args else '"?"'
            mode = all_args[1] if len(all_args) > 1 else '"r".to_string()'
            if '"w"' in mode or '"a"' in mode:
                return f'File::create({path})?'
            return f'File::open({path})?'

        # os.path.join → PathBuf::from(...).join(...)
        if func_name == "os.path.join" and len(all_args) >= 2:
            base = all_args[0]
            rest = all_args[1:]
            chain = f"PathBuf::from({base})"
            for r in rest:
                chain += f".join({r})"
            return chain

        # json.dumps / json.loads
        if func_name == "json.dumps" and len(all_args) >= 1:
            return f"serde_json::to_string(&{all_args[0]}).unwrap()"
        if func_name == "json.loads" and len(all_args) >= 1:
            return f"serde_json::from_str(&{all_args[0]}).unwrap()"

        # re.match(pattern, string) → Regex::new(pattern).unwrap().is_match(string)
        if func_name in ("re.match", "re.search") and len(all_args) >= 2:
            return f"regex::Regex::new(&{all_args[0]}).unwrap().is_match(&{all_args[1]})"
        if func_name == "re.compile" and len(all_args) >= 1:
            return f"regex::Regex::new(&{all_args[0]}).unwrap()"
        if func_name == "re.sub" and len(all_args) >= 3:
            return f"regex::Regex::new(&{all_args[0]}).unwrap().replace_all(&{all_args[1]}, {all_args[2]}).to_string()"

        # time.time() → std::time::SystemTime::now()
        if func_name == "time.time" and not all_args:
            return "std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64()"

        # ── Method call translations (obj.method(args)) ──
        if isinstance(node.func, ast.Attribute):
            obj = self._translate_ast_expr(node.func.value)
            method = node.func.attr

            # dict.get(key, default) → map.get(&key).cloned().unwrap_or(default)
            if method == "get" and len(all_args) >= 1:
                key = all_args[0]
                if len(all_args) >= 2:
                    return f"{obj}.get(&{key}).cloned().unwrap_or({all_args[1]})"
                return f"{obj}.get(&{key}).cloned()"

            # dict.pop(key, default) → map.remove(&key).unwrap_or(default)
            if method == "pop":
                if len(all_args) >= 2:
                    return f"{obj}.remove(&{all_args[0]}).unwrap_or({all_args[1]})"
                if len(all_args) == 1:
                    # Could be list.pop(index) or dict.pop(key)
                    arg = all_args[0]
                    return f"{obj}.remove(&{arg})"
                # list.pop() with no args → vec.pop().unwrap()
                return f"{obj}.pop().unwrap()"

            # dict.update(other) → map.extend(other)
            if method == "update" and len(all_args) == 1:
                return f"{obj}.extend({all_args[0]})"

            # dict.items() → map.iter()
            if method == "items" and not all_args:
                return f"{obj}.iter()"
            if method == "keys" and not all_args:
                return f"{obj}.keys()"
            if method == "values" and not all_args:
                return f"{obj}.values()"
            if method == "setdefault" and len(all_args) >= 2:
                return f"{obj}.entry({all_args[0]}).or_insert({all_args[1]})"

            # list.append(x) → vec.push(x)
            if method == "append" and len(all_args) == 1:
                return f"{obj}.push({all_args[0]})"

            # list.extend(x) → vec.extend(x)
            if method == "extend" and len(all_args) == 1:
                return f"{obj}.extend({all_args[0]})"

            # list.insert(i, x) → vec.insert(i, x)
            if method == "insert" and len(all_args) == 2:
                return f"{obj}.insert({all_args[0]}, {all_args[1]})"

            # list.index(x) → vec.iter().position(|v| *v == x).unwrap()
            if method == "index" and len(all_args) == 1:
                return f"{obj}.iter().position(|v| *v == {all_args[0]}).unwrap()"

            # list.count(x) → vec.iter().filter(|v| **v == x).count()
            if method == "count" and len(all_args) == 1:
                return f"{obj}.iter().filter(|v| **v == {all_args[0]}).count()"

            # str.startswith / endswith
            if method == "startswith" and len(all_args) == 1:
                return f"{obj}.starts_with(&*{all_args[0]})"
            if method == "endswith" and len(all_args) == 1:
                return f"{obj}.ends_with(&*{all_args[0]})"

            # str.strip/lstrip/rstrip
            if method == "strip":
                if not all_args:
                    return f"{obj}.trim().to_string()"
                # strip("chars") → trim_matches(|c| "chars".contains(c))
                return f'{obj}.trim_matches(|c: char| {all_args[0]}.contains(c)).to_string()'
            if method == "lstrip":
                if not all_args:
                    return f"{obj}.trim_start().to_string()"
                return f'{obj}.trim_start_matches(|c: char| {all_args[0]}.contains(c)).to_string()'
            if method == "rstrip":
                if not all_args:
                    return f"{obj}.trim_end().to_string()"
                return f'{obj}.trim_end_matches(|c: char| {all_args[0]}.contains(c)).to_string()'

            # str.removeprefix / removesuffix (Python 3.9+)
            if method == "removeprefix" and len(all_args) == 1:
                return f'{obj}.strip_prefix({all_args[0]}).unwrap_or(&{obj}).to_string()'
            if method == "removesuffix" and len(all_args) == 1:
                return f'{obj}.strip_suffix({all_args[0]}).unwrap_or(&{obj}).to_string()'

            # str.split(sep) → str.split(sep).collect::<Vec<_>>()
            if method == "split" and len(all_args) <= 1:
                if not all_args:
                    # s.split() → s.split_whitespace() (splits on any whitespace, removes empty)
                    return f'{obj}.split_whitespace().map(|s| s.to_string()).collect::<Vec<String>>()'
                return f'{obj}.split({all_args[0]}).map(|s| s.to_string()).collect::<Vec<String>>()'
            if method == "rsplit" and len(all_args) == 1:
                return f'{obj}.rsplit({all_args[0]}).map(|s| s.to_string()).collect::<Vec<String>>()'
            if method == "splitlines" and not all_args:
                return f'{obj}.lines().map(|s| s.to_string()).collect::<Vec<String>>()'

            # str.join(iterable) → iterable.join(sep)
            if method == "join" and len(all_args) == 1:
                return f"{all_args[0]}.join(&{obj})"

            # str.replace(old, new)
            if method == "replace" and len(all_args) >= 2:
                return f"{obj}.replace(&*{all_args[0]}, &*{all_args[1]})"

            # str.lower/upper
            if method == "lower" and not all_args:
                return f"{obj}.to_lowercase()"
            if method == "upper" and not all_args:
                return f"{obj}.to_uppercase()"
            if method == "title" and not all_args:
                return f"/* title */ {obj}.to_string()"
            if method == "capitalize" and not all_args:
                return f"/* capitalize */ {obj}.to_string()"

            # str.format(*args) → format!(str, args)
            if method == "format":
                args_str = ", ".join(all_args)
                return f"format!({obj}, {args_str})" if all_args else f"format!({obj})"

            # str.encode()/decode()
            if method == "encode" and not all_args:
                return f"{obj}.as_bytes().to_vec()"
            if method == "decode" and not all_args:
                return f"String::from_utf8_lossy(&{obj}).to_string()"

            # str.isdigit/isalpha/isalnum
            if method == "isdigit" and not all_args:
                return f"{obj}.chars().all(|c| c.is_ascii_digit())"
            if method == "isalpha" and not all_args:
                return f"{obj}.chars().all(|c| c.is_alphabetic())"
            if method == "isalnum" and not all_args:
                return f"{obj}.chars().all(|c| c.is_alphanumeric())"

            # str.find(sub) → str.find(sub)  (returns Option<usize> in Rust)
            if method == "find" and len(all_args) == 1:
                return f"{obj}.find(&*{all_args[0]}).map(|i| i as i64).unwrap_or(-1)"
            if method == "rfind" and len(all_args) == 1:
                return f"{obj}.rfind(&*{all_args[0]}).map(|i| i as i64).unwrap_or(-1)"

            # set.add(x) → set.insert(x)
            if method == "add" and len(all_args) == 1:
                return f"{obj}.insert({all_args[0]})"
            # set.discard(x) → set.remove(&x)
            if method == "discard" and len(all_args) == 1:
                return f"{obj}.remove(&{all_args[0]})"

            # dict.contains_key / list.contains
            if method == "has_key" and len(all_args) == 1:
                return f"{obj}.contains_key(&{all_args[0]})"

            # .copy() → .clone()
            if method == "copy" and not all_args:
                return f"{obj}.clone()"

            # .sort() / .reverse()
            if method == "sort" and not all_args:
                return f"{obj}.sort()"
            if method == "reverse" and not all_args:
                return f"{obj}.reverse()"

        # ── Additional Python builtins ──
        if func_name == "round":
            if len(all_args) == 1:
                return f"({all_args[0]} as f64).round()"
            if len(all_args) == 2:
                return f"(({all_args[0]} as f64) * 10f64.powi({all_args[1]})).round() / 10f64.powi({all_args[1]})"

        if func_name == "abs" and len(all_args) == 1:
            return f"({all_args[0]}).abs()"

        if func_name == "hasattr":
            return f"/* hasattr({', '.join(all_args)}) */ true"
        if func_name == "getattr":
            if len(all_args) >= 3:
                return f"/* getattr */ {all_args[2]}"
            return f"/* getattr({', '.join(all_args)}) */ Default::default()"
        if func_name == "setattr":
            return f"/* setattr({', '.join(all_args)}) */"
        if func_name == "delattr":
            return f"/* delattr({', '.join(all_args)}) */"

        if func_name == "dict":
            if not all_args:
                return "HashMap::new()"
            return f"/* dict({', '.join(all_args)}) */ HashMap::new()"
        if func_name == "list":
            if not all_args:
                return "Vec::new()"
            return f"{all_args[0]}.into_iter().collect::<Vec<_>>()"
        if func_name == "set":
            if not all_args:
                return "HashSet::new()"
            return f"{all_args[0]}.into_iter().collect::<HashSet<_>>()"
        if func_name == "tuple":
            if not all_args:
                return "()"
            return f"/* tuple */ ({', '.join(all_args)})"

        if func_name == "type" and len(all_args) == 1:
            return f'/* type */ "{all_args[0]}"'

        if func_name == "id" and len(all_args) == 1:
            return f"(&{all_args[0]} as *const _ as usize)"

        if func_name == "hex" and len(all_args) == 1:
            return f'format!("0x{{:x}}", {all_args[0]})'
        if func_name == "oct" and len(all_args) == 1:
            return f'format!("0o{{:o}}", {all_args[0]})'
        if func_name == "bin" and len(all_args) == 1:
            return f'format!("0b{{:b}}", {all_args[0]})'

        if func_name == "chr" and len(all_args) == 1:
            return f"char::from({all_args[0]} as u8).to_string()"
        if func_name == "ord" and len(all_args) == 1:
            return f"({all_args[0]}.chars().next().unwrap() as i64)"

        if func_name == "bool" and len(all_args) == 1:
            return f"({all_args[0]} != 0)"

        if func_name == "map" and len(all_args) == 2:
            return f"{all_args[1]}.iter().map({all_args[0]}).collect::<Vec<_>>()"
        if func_name == "filter" and len(all_args) == 2:
            return f"{all_args[1]}.iter().filter(|x| {all_args[0]}(x)).collect::<Vec<_>>()"

        if func_name == "urlparse" and len(all_args) >= 1:
            return f"/* urlparse */ {all_args[0]}"

        if func_name == "Path" and len(all_args) >= 1:
            return f"PathBuf::from({all_args[0]})"

        # Default: func(args)
        args_str = ", ".join(all_args)
        return f"{func_name}({args_str})"

    def _translate_ast_compare(self, node: ast.Compare) -> str:
        """Translate comparison operations. Handles chained comparisons."""
        left = self._translate_ast_expr(node.left)

        # Single comparator — simple case
        if len(node.ops) == 1:
            op = node.ops[0]
            right = self._translate_ast_expr(node.comparators[0])
            return self._single_compare(left, op, right, node.comparators[0])

        # Chained: a < b < c → (a < b) && (b < c)
        parts = []
        prev = left
        for op, comp_node in zip(node.ops, node.comparators):
            right = self._translate_ast_expr(comp_node)
            parts.append(f"({self._single_compare(prev, op, right, comp_node)})")
            prev = right
        return " && ".join(parts)

    def _single_compare(self, left: str, op, right: str, comp_node=None) -> str:
        """Translate a single comparison."""
        op_map = {
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=",
        }
        if isinstance(op, ast.Is):
            if comp_node and isinstance(comp_node, ast.Constant) and comp_node.value is None:
                return f"{left}.is_none()"
            return f"{left} == {right}"
        if isinstance(op, ast.IsNot):
            if comp_node and isinstance(comp_node, ast.Constant) and comp_node.value is None:
                return f"{left}.is_some()"
            return f"{left} != {right}"
        if isinstance(op, ast.In):
            return f"{right}.contains(&{left})"
        if isinstance(op, ast.NotIn):
            return f"!{right}.contains(&{left})"
        rust_op = op_map.get(type(op), "/* cmp */")
        return f"{left} {rust_op} {right}"

    def _translate_ast_target(self, node: ast.AST) -> str:
        """Translate an assignment target."""
        if isinstance(node, ast.Name):
            return RustCodegen._sanitize_ident(node.id)
        if isinstance(node, ast.Attribute):
            obj = self._translate_ast_expr(node.value)
            return f"{obj}.{node.attr}"
        if isinstance(node, ast.Subscript):
            obj = self._translate_ast_expr(node.value)
            sl = self._translate_ast_expr(node.slice)
            return f"{obj}[{sl}]"
        if isinstance(node, ast.Tuple):
            elts = ", ".join(self._translate_ast_target(e) for e in node.elts)
            return f"({elts})"
        if isinstance(node, ast.Starred):
            name = self._translate_ast_target(node.value)
            if name == "_":
                return ".."  # *_ → .. (rest pattern)
            return f"/* *{name} */ .."
        try:
            return ast.unparse(node)
        except Exception:
            return "/* target */"

    @staticmethod
    def _translate_ast_binop(op: ast.operator) -> str:
        """Translate a binary operator."""
        ops = {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
            ast.FloorDiv: "/", ast.Mod: "%",
            ast.LShift: "<<", ast.RShift: ">>", ast.BitOr: "|",
            ast.BitXor: "^", ast.BitAnd: "&",
        }
        return ops.get(type(op), "/* op */")

    def _translate_ast_listcomp(self, node) -> str:
        """Translate list/generator comprehension to iterator chain."""
        elt = self._translate_ast_expr(node.elt if hasattr(node, 'elt') else node.key)
        # Typically one generator: [expr for x in iter if cond]
        gen = node.generators[0] if node.generators else None
        if not gen:
            return "vec![]"
        target = self._translate_ast_target(gen.target)
        iter_expr = self._translate_ast_expr(gen.iter)
        chain = f"{iter_expr}.iter()"
        for cond in gen.ifs:
            cond_r = self._translate_ast_expr(cond)
            chain += f".filter(|{target}| {cond_r})"
        chain += f".map(|{target}| {elt}).collect::<Vec<_>>()"
        return chain

    def _translate_ast_dictcomp(self, node: ast.DictComp) -> str:
        """Translate dict comprehension."""
        key = self._translate_ast_expr(node.key)
        val = self._translate_ast_expr(node.value)
        gen = node.generators[0] if node.generators else None
        if not gen:
            return "HashMap::new()"
        target = self._translate_ast_target(gen.target)
        iter_expr = self._translate_ast_expr(gen.iter)
        chain = f"{iter_expr}.iter()"
        for cond in gen.ifs:
            cond_r = self._translate_ast_expr(cond)
            chain += f".filter(|{target}| {cond_r})"
        chain += f".map(|{target}| ({key}, {val})).collect::<HashMap<_, _>>()"
        return chain

    # ------------------------------------------------------------------
    # Body translation — pattern-based line-by-line (fallback)
    # ------------------------------------------------------------------

    def _translate_body(self, body_source: str, indent: int = 4) -> list[str]:
        """Translate Python body source to Rust line by line.

        Handles the most common patterns; complex constructs get a
        ``// TODO: translate manually`` comment.  Uses indentation
        tracking to emit closing braces for blocks.
        """
        if not body_source or not body_source.strip():
            return [" " * indent + "todo!(\"implement\")"]

        py_lines = self._join_continued_lines(body_source.splitlines())
        rust_lines: list[str] = []
        pad = " " * indent

        # Track indentation levels that opened a brace so we know when to close.
        # Each entry is the Python indentation width at which a ``{`` was opened.
        brace_stack: list[int] = []

        # Determine the base indentation of the body (first non-blank line).
        base_indent = 0
        for pl in py_lines:
            if pl.strip():
                base_indent = len(pl) - len(pl.lstrip())
                break

        i = 0
        while i < len(py_lines):
            line = py_lines[i]
            stripped = line.strip()

            # Skip blank lines and docstrings
            if not stripped or stripped.startswith('"""') or stripped.startswith("'''"):
                i += 1
                continue

            # Current Python indentation
            py_indent = len(line) - len(line.lstrip())

            # Close any blocks whose indentation is now finished.
            # For elif/else lines, the closing brace is part of `} else if`
            # emitted by _translate_if_else, so we pop the stack but only
            # emit `}` for blocks NOT continued by elif/else.
            is_continuation = (
                stripped.startswith("elif ")
                or stripped == "else:"
                or stripped.startswith("else:")
            )
            while brace_stack and py_indent <= brace_stack[-1]:
                brace_stack.pop()
                if not is_continuation:
                    extra = " " * (indent + len(brace_stack) * 4)
                    rust_lines.append(f"{extra}}}")
                else:
                    # Only skip the first close — subsequent pops are real closes
                    is_continuation = False

            # Effective Rust extra indent for nested blocks
            extra_indent = " " * (len(brace_stack) * 4)
            cur_pad = pad + extra_indent

            # Skip comments but preserve them
            if stripped.startswith("#"):
                if self.config.preserve_comments:
                    rust_lines.append(f"{cur_pad}// {stripped[1:].strip()}")
                i += 1
                continue

            # --- Pattern translations ---
            translated = self._try_translate_line(stripped, cur_pad)
            if translated is not None:
                rust_lines.append(translated)
                # If the translated line opens a brace, push indent level
                if translated.rstrip().endswith("{"):
                    brace_stack.append(py_indent)
                i += 1
                continue

            # try/except blocks
            if stripped == "try:":
                block, consumed = self._translate_try_except(py_lines[i:])
                rust_lines.extend(f"{cur_pad}{bl}" for bl in block)
                i += consumed
                continue

            # Fallback: emit as a comment
            rust_lines.append(f"{cur_pad}// TODO: {stripped}")
            i += 1

        # Close any remaining open blocks
        while brace_stack:
            brace_stack.pop()
            extra = " " * (indent + len(brace_stack) * 4)
            rust_lines.append(f"{extra}}}")

        if not rust_lines:
            rust_lines.append(f"{pad}todo!(\"implement\")")

        return rust_lines

    def _try_translate_line(self, stripped: str, pad: str) -> str | None:
        """Attempt to translate a single Python line to Rust. Returns None on failure."""
        # print(...)
        r = self._translate_print(stripped)
        if r is not None:
            return f"{pad}{r}"

        # return ...
        r = self._translate_return(stripped)
        if r is not None:
            return f"{pad}{r}"

        # assert ...
        r = self._translate_assert(stripped)
        if r is not None:
            return f"{pad}{r}"

        # raise ...
        r = self._translate_raise(stripped)
        if r is not None:
            return f"{pad}{r}"

        # if / elif / else
        r = self._translate_if_else(stripped)
        if r is not None:
            return f"{pad}{r}"

        # for ... in ...
        r = self._translate_for_loop(stripped)
        if r is not None:
            return f"{pad}{r}"

        # while
        r = self._translate_while(stripped)
        if r is not None:
            return f"{pad}{r}"

        # with open(...)
        r = self._translate_with_statement(stripped)
        if r is not None:
            return f"{pad}{r}"

        # Assignment
        r = self._translate_assignment(stripped)
        if r is not None:
            return f"{pad}{r}"

        # pass
        if stripped == "pass":
            return f"{pad}// pass"

        # break / continue
        if stripped == "break":
            return f"{pad}break;"
        if stripped == "continue":
            return f"{pad}continue;"

        return None

    # ------------------------------------------------------------------
    # Individual pattern translators
    # ------------------------------------------------------------------

    def _translate_print(self, line: str) -> str | None:
        """``print(...)`` -> ``println!(...)``."""
        m = re.match(r'^print\((.*)?\)$', line)
        if not m:
            return None
        args = m.group(1) or ""
        # Strip Python keyword args: flush=True, end="...", file=sys.stderr
        args = re.sub(r',\s*flush\s*=\s*\w+', '', args)
        args = re.sub(r',\s*end\s*=\s*["\'][^"\']*["\']', '', args)
        args = re.sub(r',\s*file\s*=\s*[\w.]+', '', args)
        args = args.strip().rstrip(',').strip()
        args = self._translate_string_format(args)
        return f'println!({args});'

    def _translate_return(self, line: str) -> str | None:
        """``return X`` -> ``return X;`` or ``X`` (trailing expression)."""
        m = re.match(r'^return\s+(.+)$', line)
        if m:
            expr = self._translate_expr(m.group(1).strip())
            return f"{expr}"
        if line == "return":
            return "return;"
        if line == "return None":
            return "None"
        return None

    def _translate_assert(self, line: str) -> str | None:
        """``assert X`` -> ``assert!(X);``."""
        m = re.match(r'^assert\s+(.+)$', line)
        if not m:
            return None
        expr = m.group(1).strip()
        # assert X, "msg"
        parts = expr.split(",", 1)
        if len(parts) == 2:
            cond = self._translate_expr(parts[0].strip())
            msg = parts[1].strip()
            return f'assert!({cond}, {msg});'
        cond = self._translate_expr(expr)
        return f"assert!({cond});"

    def _translate_raise(self, line: str) -> str | None:
        """``raise X`` -> ``return Err(...)``."""
        m = re.match(r'^raise\s+(.+)$', line)
        if not m:
            return None
        exc = m.group(1).strip()
        if self.config.error_strategy == "anyhow":
            return f'return Err(anyhow::anyhow!("{exc}"));'
        return f'return Err("{exc}".into());'

    def _translate_if_else(self, line: str) -> str | None:
        """``if X:`` -> ``if X {``, ``elif`` -> ``} else if``, ``else:`` -> ``} else {``."""
        m = re.match(r'^if\s+(.+):$', line)
        if m:
            cond = self._translate_condition(m.group(1).strip())
            return f"if {cond} {{"

        m = re.match(r'^elif\s+(.+):$', line)
        if m:
            cond = self._translate_condition(m.group(1).strip())
            return f"}} else if {cond} {{"

        if line == "else:":
            return "} else {"

        return None

    def _translate_for_loop(self, line: str) -> str | None:
        """``for X in Y:`` -> ``for X in Y.iter() {``."""
        m = re.match(r'^for\s+(\w+)\s+in\s+(.+):$', line)
        if not m:
            # Tuple unpacking: for k, v in ...
            m = re.match(r'^for\s+(\w+)\s*,\s*(\w+)\s+in\s+(.+):$', line)
            if m:
                k, v, iterable = m.group(1), m.group(2), m.group(3).strip()
                iterable = self._translate_expr(iterable)
                return f"for ({k}, {v}) in {iterable}.iter() {{"
            return None
        var = m.group(1)
        iterable = m.group(2).strip()
        # range(n) -> 0..n
        rm = re.match(r'^range\((.+)\)$', iterable)
        if rm:
            range_args = [a.strip() for a in rm.group(1).split(",")]
            if len(range_args) == 1:
                return f"for {var} in 0..{range_args[0]} {{"
            elif len(range_args) == 2:
                return f"for {var} in {range_args[0]}..{range_args[1]} {{"
            elif len(range_args) == 3:
                return f"for {var} in ({range_args[0]}..{range_args[1]}).step_by({range_args[2]} as usize) {{"
        iterable = self._translate_expr(iterable)
        return f"for {var} in {iterable}.iter() {{"

    def _translate_while(self, line: str) -> str | None:
        """``while X:`` -> ``while X {``."""
        m = re.match(r'^while\s+(.+):$', line)
        if not m:
            return None
        cond = m.group(1).strip()
        if cond == "True":
            return "loop {"
        cond = self._translate_condition(cond)
        return f"while {cond} {{"

    def _translate_with_statement(self, line: str) -> str | None:
        """``with open(path, mode) as f:`` -> Rust file I/O."""
        m = re.match(r'^with\s+open\((.+?)\)\s+as\s+(\w+)\s*:', line)
        if not m:
            return None
        args_str = m.group(1)
        var = m.group(2)
        parts = [p.strip().strip("'\"") for p in args_str.split(",")]
        path = parts[0]
        mode = parts[1] if len(parts) > 1 else "r"

        if "w" in mode:
            return (f'let mut {var} = File::create({self._translate_expr(path)})'
                    f'.context("Failed to create file")?; {{')
        return (f'let mut {var} = File::open({self._translate_expr(path)})'
                f'.context("Failed to open file")?; {{')

    def _translate_assignment(self, line: str) -> str | None:
        """``x = expr`` -> ``let mut x = expr;``."""
        # Skip lines that are function calls without assignment
        if re.match(r'^[a-zA-Z_]\w*\(', line) and "=" not in line.split("(")[0]:
            # Bare function call
            expr = self._translate_expr(line)
            return f"{expr};"

        # Augmented assignment: +=, -=, *=, /=
        m = re.match(r'^(\w+)\s*([+\-*/])=\s*(.+)$', line)
        if m:
            var = m.group(1)
            op = m.group(2)
            val = self._translate_expr(m.group(3).strip())
            return f"{self._sanitize_ident(var)} {op}= {val};"

        # Type-annotated assignment: x: int = 5
        m = re.match(r'^(\w+)\s*:\s*\w[\w\[\], ]*\s*=\s*(.+)$', line)
        if m:
            var = m.group(1)
            val = self._translate_expr(m.group(2).strip())
            return f"let mut {self._sanitize_ident(var)} = {val};"

        # Simple assignment: x = expr
        m = re.match(r'^(\w+)\s*=\s*(.+)$', line)
        if m:
            var = m.group(1)
            val = self._translate_expr(m.group(2).strip())
            return f"let mut {self._sanitize_ident(var)} = {val};"

        # self.x = expr (in method body context)
        m = re.match(r'^self\.(\w+)\s*=\s*(.+)$', line)
        if m:
            attr = m.group(1)
            val = self._translate_expr(m.group(2).strip())
            return f"self.{self._sanitize_ident(attr)} = {val};"

        return None

    def _translate_try_except(self, lines: list[str]) -> tuple[list[str], int]:
        """Translate a try/except block into a Rust match on Result."""
        rust: list[str] = []
        consumed = 0
        consumed += 1  # skip 'try:'
        i = 1

        # Collect the try body
        try_body: list[str] = []
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("except") or stripped == "finally:":
                break
            if stripped:
                try_body.append(stripped)
            i += 1
            consumed += 1

        # Translate the try body — each line inside a block
        rust.append("// try:")
        rust.append("{")
        for tb in try_body:
            t = self._try_translate_line(tb, "    ")
            rust.append(t if t else f"    // TODO: {tb}")
        rust.append("}")

        # Except clause(s)
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("except"):
                m = re.match(r'^except\s*(\w+)?\s*(?:as\s+(\w+))?\s*:', stripped)
                exc_type = m.group(1) if m and m.group(1) else "Exception"
                exc_var = m.group(2) if m and m.group(2) else "_e"
                rust.append(f"// except {exc_type} as {exc_var}:")
                consumed += 1
                i += 1
                # Collect except body
                except_body: list[str] = []
                while i < len(lines):
                    s2 = lines[i].strip()
                    if not s2 or s2.startswith("except") or s2 == "finally:" or s2 == "else:":
                        break
                    except_body.append(s2)
                    i += 1
                    consumed += 1
                # If except body is non-trivial, emit it
                if except_body:
                    rust.append("// {")
                    for eb in except_body:
                        t = self._try_translate_line(eb, "//     ")
                        rust.append(t if t else f"//     // TODO: {eb}")
                    rust.append("// }")
            elif stripped == "finally:":
                consumed += 1
                i += 1
                rust.append("// finally:")
                while i < len(lines):
                    s2 = lines[i].strip()
                    if not s2:
                        break
                    t = self._try_translate_line(s2, "")
                    rust.append(t if t else f"// TODO: {s2}")
                    i += 1
                    consumed += 1
                return rust, consumed
            else:
                break

        return rust, consumed

    def _translate_list_comprehension(self, expr: str) -> str:
        """``[f(x) for x in xs if cond]`` -> ``.iter().filter().map().collect()``."""
        m = re.match(r'^\[(.+?)\s+for\s+(\w+)\s+in\s+(.+?)(?:\s+if\s+(.+))?\]$', expr)
        if not m:
            return expr
        map_expr = self._translate_expr(m.group(1).strip())
        var = m.group(2)
        iterable = self._translate_expr(m.group(3).strip())
        cond = m.group(4)
        chain = f"{iterable}.iter()"
        if cond:
            cond_rust = self._translate_condition(cond.strip())
            chain += f".filter(|{var}| {cond_rust})"
        chain += f".map(|{var}| {map_expr}).collect::<Vec<_>>()"
        return chain

    def _translate_dict_comprehension(self, expr: str) -> str:
        """``{k: v for k, v in items}`` -> ``.iter().map().collect::<HashMap<_,_>>()``."""
        m = re.match(r'^\{(.+?):\s*(.+?)\s+for\s+(.+?)\s+in\s+(.+?)(?:\s+if\s+(.+))?\}$', expr)
        if not m:
            return expr
        key_expr = self._translate_expr(m.group(1).strip())
        val_expr = self._translate_expr(m.group(2).strip())
        vars_str = m.group(3).strip()
        iterable = self._translate_expr(m.group(4).strip())
        cond = m.group(5)
        chain = f"{iterable}.iter()"
        if cond:
            chain += f".filter(|{vars_str}| {self._translate_condition(cond.strip())})"
        chain += f".map(|{vars_str}| ({key_expr}, {val_expr})).collect::<HashMap<_, _>>()"
        return chain

    @staticmethod
    def _python_fmt_to_rust(spec: str) -> str:
        """Convert a Python format spec to Rust: ``.2f`` -> ``:.2``, ``d`` -> empty."""
        if not spec:
            return ""
        # .Nf -> :.N  (Rust uses :.N for float precision, no 'f' suffix)
        m = re.match(r'^\.(\d+)f$', spec)
        if m:
            return f":.{m.group(1)}"
        # d -> nothing (integers are default)
        if spec == "d":
            return ""
        # >N, <N, ^N alignment
        m = re.match(r'^([<>^])(\d+)$', spec)
        if m:
            return f":{m.group(1)}{m.group(2)}"
        # 0Nd -> :0N (zero-padded integer, strip 'd')
        m = re.match(r'^0(\d+)[df]?$', spec)
        if m:
            return f":0{m.group(1)}"
        # Nf -> :.N (just N with f suffix)
        m = re.match(r'^(\d+)f$', spec)
        if m:
            return f":.{m.group(1)}"
        # ,  -> comma separator (not in Rust, skip)
        if spec == ",":
            return ""
        # >N.Mf, <N.Mf alignment with float precision
        m = re.match(r'^([<>^]?)(\d+)\.(\d+)f$', spec)
        if m:
            align = m.group(1) or ""
            width = m.group(2)
            prec = m.group(3)
            return f":{align}{width}.{prec}"
        # Nd (integer with width) → :N
        m = re.match(r'^(\d+)d$', spec)
        if m:
            return f":{m.group(1)}"
        # Strip trailing 'f' from any format spec (Rust doesn't use 'f')
        if spec.endswith('f') and not spec.endswith('xf'):
            return f":{spec[:-1]}"
        # Pass through anything else as-is with a :
        return f":{spec}"

    @staticmethod
    def _extract_fstring_parts(inner: str) -> list[tuple[str, str]]:
        """Extract (expr, format_spec) pairs from an f-string body.

        Handles nested braces properly, e.g. ``{json.dumps({'k': v})}``
        Returns list of (literal_before, expr_text) tuples.  The final
        trailing literal is returned as (literal, "").
        """
        parts: list[tuple[str, str]] = []
        i = 0
        literal = ""
        while i < len(inner):
            ch = inner[i]
            if ch == "{":
                if i + 1 < len(inner) and inner[i + 1] == "{":
                    literal += "{{"  # escaped brace
                    i += 2
                    continue
                # Start of expression — find matching closing brace
                depth = 1
                j = i + 1
                while j < len(inner) and depth > 0:
                    if inner[j] == "{":
                        depth += 1
                    elif inner[j] == "}":
                        depth -= 1
                    elif inner[j] in ('"', "'"):
                        # skip string literal inside expression
                        quote = inner[j]
                        j += 1
                        while j < len(inner) and inner[j] != quote:
                            if inner[j] == "\\":
                                j += 1  # skip escaped char
                            j += 1
                    j += 1
                expr_text = inner[i + 1 : j - 1] if depth == 0 else inner[i + 1:]
                parts.append((literal, expr_text))
                literal = ""
                i = j
            elif ch == "}" and i + 1 < len(inner) and inner[i + 1] == "}":
                literal += "}}"
                i += 2
            else:
                literal += ch
                i += 1
        if literal:
            parts.append((literal, ""))
        return parts

    def _translate_string_format(self, expr: str) -> str:
        """Translate Python f-strings and .format() to Rust format! arguments."""
        # f"..." -> format!("...")
        expr = expr.strip()
        if expr.startswith('f"') or expr.startswith("f'"):
            inner = expr[2:-1]
            fparts = self._extract_fstring_parts(inner)
            fmt = ""
            args: list[str] = []
            for literal, expr_text in fparts:
                fmt += literal
                if not expr_text:
                    continue
                # Split on : for format spec (but only top-level colon)
                colon_pos = -1
                depth = 0
                for ci, cc in enumerate(expr_text):
                    if cc in "({[":
                        depth += 1
                    elif cc in ")}]":
                        depth -= 1
                    elif cc == ":" and depth == 0:
                        colon_pos = ci
                        break
                if colon_pos >= 0:
                    var_part = expr_text[:colon_pos]
                    spec_part = expr_text[colon_pos + 1:]
                    rust_spec = self._python_fmt_to_rust(spec_part)
                    fmt += "{" + rust_spec + "}"
                else:
                    var_part = expr_text
                    fmt += "{}"
                args.append(self._translate_expr(var_part.strip()))
            if args:
                return f'"{fmt}", {", ".join(args)}'
            return f'"{fmt}"'

        # "...".format(args)
        m_fmt = re.match(r'^["\'](.+?)["\']\s*\.format\((.+)\)$', expr)
        if m_fmt:
            template = m_fmt.group(1)
            args = m_fmt.group(2)
            # Replace {0}, {name}, {} with {}
            template = re.sub(r'\{\w*\}', '{}', template)
            return f'"{template}", {args}'

        return expr

    # ------------------------------------------------------------------
    # Expression-level translation helpers
    # ------------------------------------------------------------------

    def _translate_expr(self, expr: str) -> str:
        """Best-effort translation of a Python expression to Rust."""
        expr = expr.strip()

        # None -> None (Rust Option::None)
        if expr == "None":
            return "None"
        # True / False
        if expr == "True":
            return "true"
        if expr == "False":
            return "false"

        # f-string — delegate to _translate_string_format and wrap with format!()
        if expr.startswith('f"') or expr.startswith("f'"):
            translated = self._translate_string_format(expr)
            return f'format!({translated})'

        # Raw string literals: r"..." or r'...'
        if (expr.startswith('r"') or expr.startswith("r'")) and len(expr) > 3:
            inner = expr[2:-1]
            return f'r#"{inner}"#.to_string()'

        # String literals
        if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
            inner = expr[1:-1]
            return f'"{inner}".to_string()'

        # List comprehension
        if expr.startswith("[") and " for " in expr:
            return self._translate_list_comprehension(expr)

        # Dict comprehension
        if expr.startswith("{") and " for " in expr:
            return self._translate_dict_comprehension(expr)

        # List literal
        if expr.startswith("[") and expr.endswith("]"):
            inner = expr[1:-1].strip()
            if not inner:
                return "vec![]"
            items = self._split_args(inner)
            translated = ", ".join(self._translate_expr(it) for it in items)
            return f"vec![{translated}]"

        # Empty dict/set literal
        if expr == "{}":
            return "HashMap::new()"

        # Dict literal
        if expr.startswith("{") and expr.endswith("}") and ":" in expr:
            return self._translate_dict_literal(expr)

        # isinstance(x, Y) -> matches! or type check
        m = re.match(r'^isinstance\((\w+),\s*(\w+)\)$', expr)
        if m:
            return f'/* isinstance({m.group(1)}, {m.group(2)}) */'

        # len(x) — use balanced paren matching
        if expr.startswith("len("):
            # Find the matching closing paren
            depth = 0
            for ci, cc in enumerate(expr):
                if cc == "(":
                    depth += 1
                elif cc == ")":
                    depth -= 1
                    if depth == 0:
                        inner_expr = expr[4:ci]
                        rest = expr[ci + 1:].strip()
                        inner_t = self._translate_expr(inner_expr)
                        if not rest:
                            return f"{inner_t}.len()"
                        # Something after len(), e.g. len(X) - len(Y)
                        return f"{inner_t}.len(){rest}"
                        break

        # x.append(y)
        m = re.match(r'^(\w+)\.append\((.+)\)$', expr)
        if m:
            return f"{m.group(1)}.push({self._translate_expr(m.group(2))})"

        # x.extend(y)
        m = re.match(r'^(\w+)\.extend\((.+)\)$', expr)
        if m:
            return f"{m.group(1)}.extend({self._translate_expr(m.group(2))})"

        # x.items()
        m = re.match(r'^(\w+)\.items\(\)$', expr)
        if m:
            return f"{m.group(1)}.iter()"

        # x.keys()
        m = re.match(r'^(\w+)\.keys\(\)$', expr)
        if m:
            return f"{m.group(1)}.keys()"

        # x.values()
        m = re.match(r'^(\w+)\.values\(\)$', expr)
        if m:
            return f"{m.group(1)}.values()"

        # x.get(key, default)
        m = re.match(r'^(\w+)\.get\((.+?),\s*(.+)\)$', expr)
        if m:
            return (f"{m.group(1)}.get({self._translate_expr(m.group(2))})"
                    f".unwrap_or(&{self._translate_expr(m.group(3))})")

        # x.strip() / x.lower() / x.upper()
        for py_method, rs_method in [("strip", "trim"), ("lstrip", "trim_start"),
                                      ("rstrip", "trim_end"), ("lower", "to_lowercase"),
                                      ("upper", "to_uppercase"), ("split", "split"),
                                      ("join", "join"), ("replace", "replace"),
                                      ("startswith", "starts_with"),
                                      ("endswith", "ends_with")]:
            pat = re.compile(rf'^(.+)\.{py_method}\(([^)]*)\)$')
            mm = pat.match(expr)
            if mm:
                obj = self._translate_expr(mm.group(1))
                args = mm.group(2).strip()
                if args:
                    args = self._translate_expr(args)
                    return f"{obj}.{rs_method}({args})"
                return f"{obj}.{rs_method}()"

        # not X -> !X
        m = re.match(r'^not\s+(.+)$', expr)
        if m:
            return f"!{self._translate_expr(m.group(1))}"

        # x in y -> y.contains(&x)
        m = re.match(r'^(.+?)\s+in\s+(.+)$', expr)
        if m:
            item = self._translate_expr(m.group(1))
            container = self._translate_expr(m.group(2))
            return f"{container}.contains(&{item})"

        # x not in y -> !y.contains(&x)
        m = re.match(r'^(.+?)\s+not\s+in\s+(.+)$', expr)
        if m:
            item = self._translate_expr(m.group(1))
            container = self._translate_expr(m.group(2))
            return f"!{container}.contains(&{item})"

        # x is None -> x.is_none()
        if expr.endswith(" is None"):
            var = expr[:-8].strip()
            return f"{self._translate_expr(var)}.is_none()"

        # x is not None -> x.is_some()
        if expr.endswith(" is not None"):
            var = expr[:-12].strip()
            return f"{self._translate_expr(var)}.is_some()"

        # Convert remaining single-quoted strings to double-quoted (Rust uses " for strings)
        expr = re.sub(r"'([^']*)'", r'"\1"', expr)

        # Numeric / identifier — pass through
        return expr

    def _translate_condition(self, cond: str) -> str:
        """Translate a Python boolean condition to Rust."""
        # and / or
        cond = cond.replace(" and ", " && ").replace(" or ", " || ")
        # not X in Y -> !Y.contains(&X)
        cond = re.sub(
            r'!(\S+)\s+in\s+(.+)',
            lambda m: f'!{m.group(2).strip()}.contains(&{m.group(1)})',
            cond,
        )
        # X in Y  (membership test) -> Y.contains(&X)
        cond = re.sub(
            r'(\S+)\s+in\s+(.+)',
            lambda m: f'{m.group(2).strip()}.contains(&{m.group(1)})',
            cond,
        )
        # not
        cond = re.sub(r'\bnot\s+', "!", cond)
        # is None / is not None
        cond = re.sub(r'(\w+)\s+is\s+None', r'\1.is_none()', cond)
        cond = re.sub(r'(\w+)\s+is\s+not\s+None', r'\1.is_some()', cond)
        # True / False
        cond = cond.replace("True", "true").replace("False", "false")
        # == None -> .is_none()
        cond = re.sub(r'(\w+)\s*==\s*None', r'\1.is_none()', cond)
        cond = re.sub(r'(\w+)\s*!=\s*None', r'\1.is_some()', cond)
        # isinstance(X, Y) -> X.is::<Y>() (simplified)
        cond = re.sub(r'isinstance\((\w+),\s*(\w+)\)', r'/* \1 is \2 */ true', cond)
        return cond

    def _translate_dict_literal(self, expr: str) -> str:
        """Translate ``{k: v, ...}`` to a HashMap construction."""
        inner = expr[1:-1].strip()
        if not inner:
            return "HashMap::new()"
        # Simple key: value pairs
        pairs: list[str] = []
        for part in self._split_args(inner):
            kv = part.split(":", 1)
            if len(kv) == 2:
                k = self._translate_expr(kv[0].strip())
                v = self._translate_expr(kv[1].strip())
                pairs.append(f"({k}, {v})")
        if not pairs:
            return "HashMap::new()"
        items = ", ".join(pairs)
        return f"HashMap::from([{items}])"

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _return_sig(self, func: FunctionInfo) -> str:
        """Build the return type signature, wrapping in Result if needed."""
        rt = func.return_type
        if rt == "/* unknown */":
            rt = "()"

        # Only wrap in Result if the function actually uses error patterns
        needs_result = self._func_needs_result(func)

        if needs_result and self.config.error_strategy == "anyhow":
            return f"Result<{rt}>"
        if needs_result and self.config.error_strategy == "thiserror":
            return f"Result<{rt}, AppError>"
        return rt

    def _func_needs_result(self, func: FunctionInfo) -> bool:
        """Heuristic: does this function need a Result return type?"""
        # Check AST body for try/except, raise, or error-prone calls
        if func.ast_body:
            for node in ast.walk(ast.Module(body=func.ast_body, type_ignores=[])):
                if isinstance(node, (ast.Try, ast.Raise)):
                    return True
                # Check for calls that produce Results: open(), File::open(), etc.
                if isinstance(node, ast.Call):
                    name = ""
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in ("open", "connect", "read", "write"):
                        return True
        # Fallback: check source text for error patterns
        src = func.body_source
        if "raise " in src or "try:" in src or "except " in src:
            return True
        if "open(" in src or ".read(" in src or ".write(" in src:
            return True
        return False

    @staticmethod
    def _mutates_self(method: FunctionInfo) -> bool:
        """Heuristic: does the method body assign to self.*?"""
        return "self." in method.body_source and "=" in method.body_source

    @staticmethod
    def _rust_doc_comment(text: str, indent: int = 0) -> str:
        pad = " " * indent
        lines = text.strip().splitlines()
        return "\n".join(f"{pad}/// {line.strip()}" for line in lines)

    @staticmethod
    def _join_continued_lines(lines: list[str]) -> list[str]:
        """Join Python lines that are continuations (unclosed parens/brackets/braces).

        Merges multi-line function calls into single lines.  Limits joining
        to 500 chars to avoid creating monster lines from large tuple/list
        literals that the line-by-line translator cannot handle.
        """
        result: list[str] = []
        current = ""
        depth = 0  # paren/bracket/brace nesting depth
        in_string = False
        string_char = ""

        for line in lines:
            stripped = line.rstrip()

            # Track string state (simplified)
            for ch in stripped:
                if in_string:
                    if ch == string_char:
                        in_string = False
                elif ch in ('"', "'"):
                    in_string = True
                    string_char = ch
                elif ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth = max(0, depth - 1)

            if current:
                candidate = current + " " + stripped.strip()
                # Safety: if the joined line is too long, give up joining
                if len(candidate) > 500:
                    result.append(current)
                    current = stripped
                    depth = 0  # reset since we broke the join
                else:
                    current = candidate
            else:
                current = stripped

            # Explicit continuation with backslash
            if current.endswith("\\"):
                current = current[:-1]
                continue

            if depth == 0:
                result.append(current)
                current = ""

        if current:
            result.append(current)

        return result

    @staticmethod
    def _sanitize_ident(name: str) -> str:
        """Make a Python identifier safe as a Rust identifier."""
        # Rust reserved words
        reserved = {
            "as", "break", "const", "continue", "crate", "else", "enum",
            "extern", "fn", "for", "if", "impl", "in", "let", "loop",
            "match", "mod", "move", "mut", "pub", "ref", "return", "self",
            "Self", "static", "struct", "super", "trait", "true", "false",
            "type", "unsafe", "use", "where", "while", "async", "await",
            "dyn", "abstract", "become", "box", "do", "final", "macro",
            "override", "priv", "typeof", "unsized", "virtual", "yield",
        }
        # Strip leading * or ** from vararg/kwarg names
        clean = name.lstrip("*")
        if clean in reserved:
            return f"r#{clean}"
        return clean

    @staticmethod
    def _split_args(s: str) -> list[str]:
        """Split a comma-separated string respecting nesting of brackets."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in s:
            if ch in "([{":
                depth += 1
                current.append(ch)
            elif ch in ")]}":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current).strip())
        return [p for p in parts if p]


# ═══════════════════════════════════════════════════════════════════════════
# LLM Transpile Helper
# ═══════════════════════════════════════════════════════════════════════════

class LLMTranspileHelper:
    """Delegate complex constructs to an LLM backend for transpilation."""

    def __init__(self, backend: LLMBackend) -> None:
        self.backend = backend
        self.calls_made = 0

    def transpile_complex_function(self, python_source: str, context: str) -> str:
        """Ask the LLM to transpile a Python function that is too complex for
        pattern-based translation."""
        prompt = (
            "You are a Python-to-Rust transpiler. Convert the following Python function "
            "to idiomatic, safe Rust code. Use proper error handling with Result/Option. "
            "Do not use unsafe blocks. Only return the Rust code, no explanations.\n\n"
            f"Context:\n{context}\n\n"
            f"Python source:\n```python\n{python_source}\n```\n\n"
            "Rust equivalent:"
        )
        self.calls_made += 1
        return self.backend.generate(prompt, max_tokens=2048)

    def resolve_type_ambiguity(self, python_expr: str, context: str) -> str:
        """Ask the LLM to determine the correct Rust type for an ambiguous expression."""
        prompt = (
            "Given the following Python expression and surrounding context, "
            "determine the most appropriate Rust type. Reply with ONLY the Rust type "
            "(e.g., 'Vec<String>', 'HashMap<String, i64>', 'Option<bool>').\n\n"
            f"Context:\n{context}\n\n"
            f"Expression: {python_expr}\n\n"
            "Rust type:"
        )
        self.calls_made += 1
        result = self.backend.generate(prompt, max_tokens=128)
        # Clean up the response — take the first line, strip backticks
        return result.strip().splitlines()[0].strip("`").strip()

    def translate_decorator(self, decorator: str, function: str) -> str:
        """Ask the LLM how to translate a Python decorator to Rust."""
        prompt = (
            "Translate the following Python decorated function to idiomatic Rust. "
            "Only return the Rust code, no explanations.\n\n"
            f"```python\n@{decorator}\n{function}\n```\n\n"
            "Rust equivalent:"
        )
        self.calls_made += 1
        return self.backend.generate(prompt, max_tokens=2048)

    def translate_metaclass(self, class_source: str) -> str:
        """Ask the LLM to translate a Python metaclass to Rust trait/macro patterns."""
        prompt = (
            "Translate the following Python class with metaclass to idiomatic Rust "
            "using traits and/or macros. Only return the Rust code, no explanations.\n\n"
            f"```python\n{class_source}\n```\n\n"
            "Rust equivalent:"
        )
        self.calls_made += 1
        return self.backend.generate(prompt, max_tokens=2048)

    def suggest_crate_dependency(self, python_import: str) -> str | None:
        """Ask the LLM to suggest a Rust crate equivalent for a Python package."""
        if python_import in CRATE_MAP:
            return CRATE_MAP[python_import]
        prompt = (
            f"What is the best Rust crate equivalent of the Python package '{python_import}'? "
            "Reply with ONLY the crate name (e.g., 'reqwest', 'serde_json'). "
            "If there is no good equivalent, reply with 'none'."
        )
        self.calls_made += 1
        result = self.backend.generate(prompt, max_tokens=64).strip().lower()
        if result == "none" or not result:
            return None
        return result.splitlines()[0].strip()


# ═══════════════════════════════════════════════════════════════════════════
# Main Transpiler Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

class Transpiler:
    """Orchestrates the full Python-to-Rust transpilation process."""

    def __init__(self, config: TranspileConfig | None = None) -> None:
        self.config = config or TranspileConfig()
        self.analyzer = PythonAnalyzer()
        self.codegen = RustCodegen(self.config)
        self._llm_helper: LLMTranspileHelper | None = None
        self._llm_calls = 0

    @property
    def llm_helper(self) -> LLMTranspileHelper | None:
        """Lazily initialize the LLM helper when first needed."""
        if self._llm_helper is not None:
            return self._llm_helper
        if not self.config.use_llm:
            return None
        try:
            backend = create_backend(self.config.llm_backend)
            if backend.is_available:
                self._llm_helper = LLMTranspileHelper(backend)
                log.info("LLM backend initialized: %s", backend.backend_name)
                return self._llm_helper
            log.warning("LLM backend not available; complex constructs will be skipped")
        except Exception as exc:
            log.warning("Failed to initialize LLM backend: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transpile_file(self, filepath: str) -> TranspileResult:
        """Transpile a single Python file to Rust."""
        module = self.analyzer.analyze_file(filepath)
        rust_src = self._generate_with_llm_fallback(module)
        result = TranspileResult(
            modules_transpiled=1,
            files_written={self._rust_filename(module): rust_src},
            dependency_map={d: CRATE_MAP.get(d, "?") for d in module.dependencies},
        )
        if self.config.generate_cargo_toml:
            result.cargo_toml = self.codegen.generate_cargo_toml([module])
        if self._llm_helper:
            result.llm_calls_made = self._llm_helper.calls_made
        self._write_output([module], result.files_written, result.cargo_toml)
        return result

    def transpile_directory(self, root: str) -> TranspileResult:
        """Transpile an entire Python directory to a Rust crate."""
        modules = self.analyzer.analyze_directory(root)
        if not modules:
            return TranspileResult(warnings=["No Python files found"])

        rust_sources: dict[str, str] = {}
        all_deps: set[str] = set()
        all_module_names = {m.module_name for m in modules}

        for module in modules:
            rust_src = self._generate_with_llm_fallback(module, all_module_names)
            rust_sources[self._rust_filename(module)] = rust_src
            all_deps |= module.dependencies

        # Post-generation rewriter pass
        rust_sources = self._post_rewrite_pass(rust_sources, all_module_names, modules)

        result = TranspileResult(
            modules_transpiled=len(modules),
            files_written=rust_sources,
            dependency_map={d: CRATE_MAP.get(d, "?") for d in all_deps},
        )

        if self.config.generate_cargo_toml:
            result.cargo_toml = self.codegen.generate_cargo_toml(modules)

        # Generate lib.rs
        lib_rs = self.codegen.generate_mod_rs(modules)
        result.files_written["src/lib.rs"] = lib_rs

        if self._llm_helper:
            result.llm_calls_made = self._llm_helper.calls_made

        self._write_output(modules, result.files_written, result.cargo_toml)

        # Attempt compilation
        result.compile_success, result.compile_errors = self._try_compile()

        # If compilation fails and LLM is available, attempt fixes
        if not result.compile_success and self.llm_helper:
            result = self._llm_fix_compile_errors(result, modules)

        return result

    def full_pipeline(self, root: str) -> TranspileResult:
        """Complete pipeline: scan -> fix -> verify -> transpile -> compile.

        1. Scan with X-Ray
        2. Auto-fix findings
        3. Verify fixes (re-scan)
        4. Transpile clean code
        5. Generate Cargo.toml
        6. Attempt cargo check
        7. If compile errors and LLM available, fix and retry
        """
        from xray.fixer import apply_fixes_bulk

        result = TranspileResult()

        # Step 1: Scan
        log.info("Step 1/7: Scanning %s with X-Ray...", root)
        scan_result = scan_directory(root)
        findings_count = len(scan_result.findings)
        log.info("  Found %d issues in %d files", findings_count, scan_result.files_scanned)

        # Step 2: Auto-fix
        if scan_result.findings:
            log.info("Step 2/7: Auto-fixing %d findings...", findings_count)
            fixable = [
                {
                    "rule_id": f.rule_id,
                    "file": f.file,
                    "line": f.line,
                    "matched_text": f.matched_text,
                    "severity": f.severity,
                }
                for f in scan_result.findings
            ]
            fix_result = apply_fixes_bulk(fixable)
            fixed_count = fix_result.get("fixed", 0)
            log.info("  Fixed %d/%d issues", fixed_count, findings_count)
        else:
            log.info("Step 2/7: No issues to fix")

        # Step 3: Verify
        log.info("Step 3/7: Re-scanning to verify fixes...")
        verify_result = scan_directory(root)
        remaining = len(verify_result.findings)
        if remaining > 0:
            result.warnings.append(
                f"{remaining} issues remain after auto-fix (non-blocking)"
            )
            log.warning("  %d issues remain after auto-fix", remaining)
        else:
            log.info("  Clean scan: 0 issues remaining")

        # Steps 4-7: Transpile
        log.info("Step 4/7: Transpiling to Rust...")
        transpile_result = self.transpile_directory(root)

        # Merge results
        result.modules_transpiled = transpile_result.modules_transpiled
        result.files_written = transpile_result.files_written
        result.cargo_toml = transpile_result.cargo_toml
        result.compile_success = transpile_result.compile_success
        result.compile_errors = transpile_result.compile_errors
        result.llm_calls_made = transpile_result.llm_calls_made
        result.dependency_map = transpile_result.dependency_map
        result.warnings.extend(transpile_result.warnings)

        status = "SUCCESS" if result.compile_success else "COMPILE ERRORS"
        log.info(
            "Pipeline complete: %d modules, %d files written, %s",
            result.modules_transpiled,
            len(result.files_written),
            status,
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_with_llm_fallback(self, module: PythonModule, all_module_names: set[str] | None = None) -> str:
        """Generate Rust source, using LLM for TODO-marked complex sections."""
        rust_src = self.codegen.generate_module(module, all_module_names)

        # Count remaining TODOs — if many, consider LLM pass
        todo_count = rust_src.count("// TODO:")
        if todo_count > 5 and self.llm_helper and self._llm_calls < self.config.max_llm_calls:
            log.info(
                "Module %s has %d TODOs; attempting LLM refinement...",
                module.module_name, todo_count,
            )
            rust_src = self._llm_refine_module(module, rust_src)

        return rust_src

    def _llm_refine_module(self, module: PythonModule, rust_src: str) -> str:
        """Use the LLM to refine sections that couldn't be pattern-translated."""
        if not self.llm_helper:
            return rust_src
        helper = self.llm_helper

        # Extract functions with TODO markers and retranslate them
        for func in module.functions:
            if self._llm_calls >= self.config.max_llm_calls:
                break
            func_rust = self.codegen.generate_function(func)
            if "// TODO:" in func_rust:
                try:
                    better = helper.transpile_complex_function(
                        func.body_source,
                        context=f"Module: {module.module_name}, Function: {func.name}",
                    )
                    self._llm_calls += 1
                    # Extract just the function body from LLM response
                    better = self._extract_code_block(better)
                    if better and "fn " in better:
                        rust_src = rust_src.replace(func_rust, better)
                except Exception as exc:
                    log.debug("LLM refinement failed for %s: %s", func.name, exc)

        for cls in module.classes:
            for method in cls.methods:
                if self._llm_calls >= self.config.max_llm_calls:
                    break
                # Check if this specific method has TODOs
                method_rust = self.codegen.generate_function(method)
                if "// TODO:" not in method_rust:
                    continue
                try:
                    better = helper.transpile_complex_function(
                        method.body_source,
                        context=f"Module: {module.module_name}, Class: {cls.name}, Method: {method.name}",
                    )
                    self._llm_calls += 1
                    better = self._extract_code_block(better)
                    if better:
                        # Replace just the body lines
                        rust_src = rust_src.replace(method_rust, better)
                except Exception as exc:
                    log.debug("LLM refinement failed for %s.%s: %s", cls.name, method.name, exc)

        return rust_src

    def _try_compile(self) -> tuple[bool, list[str]]:
        """Attempt ``cargo check`` in the output directory."""
        output_dir = Path(self.config.output_dir)
        if not (output_dir / "Cargo.toml").exists():
            return False, ["Cargo.toml not found"]
        try:
            proc = subprocess.run(
                ["cargo", "check"],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            if proc.returncode == 0:
                log.info("cargo check succeeded")
                return True, []
            errors = (proc.stderr or "").splitlines()
            log.warning("cargo check failed with %d error lines", len(errors))
            return False, errors
        except FileNotFoundError:
            return False, ["cargo not found in PATH"]
        except subprocess.TimeoutExpired:
            return False, ["cargo check timed out (120s)"]

    def _llm_fix_compile_errors(
        self, result: TranspileResult, modules: list[PythonModule],
    ) -> TranspileResult:
        """Use the LLM to fix compilation errors, up to 3 retries."""
        if not self.llm_helper:
            return result
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self._llm_calls >= self.config.max_llm_calls:
                result.warnings.append("LLM call budget exhausted during compile-fix")
                break

            log.info("LLM compile-fix attempt %d/%d", attempt, max_retries)
            errors_text = "\n".join(result.compile_errors[:50])

            prompt = (
                "The following Rust code has compilation errors. Fix the errors and "
                "return the corrected Rust source. Only return the code, no explanations.\n\n"
                f"Errors:\n```\n{errors_text}\n```\n\n"
            )

            # Find the file with the most errors and fix it
            error_files: dict[str, int] = {}
            for err_line in result.compile_errors:
                m = re.search(r'--> src/(\w+\.rs)', err_line)
                if m:
                    error_files[m.group(1)] = error_files.get(m.group(1), 0) + 1

            if not error_files:
                break

            worst_file = max(error_files, key=error_files.get)
            src_path = f"src/{worst_file}"
            if src_path not in result.files_written:
                break

            full_prompt = prompt + f"Source ({worst_file}):\n```rust\n{result.files_written[src_path]}\n```"
            try:
                fixed = self.llm_helper.transpile_complex_function(
                    result.files_written[src_path],
                    context=f"Fixing compile errors in {worst_file}: {errors_text[:500]}",
                )
                self._llm_calls += 1
                fixed = self._extract_code_block(fixed)
                if fixed:
                    result.files_written[src_path] = fixed
                    # Write and re-check
                    output_path = Path(self.config.output_dir) / src_path
                    output_path.write_text(fixed, encoding="utf-8")
                    success, errors = self._try_compile()
                    result.compile_success = success
                    result.compile_errors = errors
                    if success:
                        log.info("Compile fix succeeded on attempt %d", attempt)
                        break
            except Exception as exc:
                log.debug("LLM compile-fix failed: %s", exc)
                break

        if self._llm_helper:
            result.llm_calls_made = self._llm_helper.calls_made
        return result

    def _post_rewrite_pass(
        self, sources: dict[str, str], module_names: set[str],
        modules: list[PythonModule] | None = None,
    ) -> dict[str, str]:
        """Post-generation Rust linter/rewriter.

        Applies systematic pattern-based fixes to generated Rust code.
        This catches issues the AST translator misses, using simple
        regex/string replacement rules.
        """
        import re as _re

        # Build alias→module map from all sources (check for `use crate::X as Y;`)
        alias_to_mod: dict[str, str] = {}
        for src in sources.values():
            for m in _re.finditer(r'use crate::(\w+) as (\w+);', src):
                alias_to_mod[m.group(2)] = m.group(1)

        # Build per-file Python import alias map
        # e.g. "import subprocess as sp" → {"sp": "subprocess"}
        file_aliases: dict[str, dict[str, str]] = {}
        if modules:
            for mod in modules:
                rust_path = f"src/{RustCodegen._sanitize_ident(mod.module_name)}.rs"
                aliases: dict[str, str] = {}
                for imp in mod.imports:
                    if imp.alias:
                        aliases[imp.alias] = imp.module
                file_aliases[rust_path] = aliases

        # All identifiers that should use :: instead of .
        mod_idents = module_names | set(alias_to_mod.keys())

        result = {}
        for path, src in sources.items():
            # Rule 0: Resolve Python import aliases for stdlib/third-party modules
            # e.g. sp.run(...) → subprocess.run(...) → subprocess::run(...)
            # Skip aliases for project-internal modules (handled by crate::imports)
            py_aliases = file_aliases.get(path, {})
            for alias, full_name in py_aliases.items():
                mod_base = full_name.split(".")[-1]
                # Skip if this is a project-internal module
                if mod_base in module_names:
                    continue
                # Replace alias.method with full_name.method
                src = _re.sub(
                    rf'\b{_re.escape(alias)}\.(\w+)',
                    rf'{full_name}.\1',
                    src,
                )
            # Rule 1: module.func() → module::func() or just func()
            # If the file has `use crate::module::*;`, remove the module prefix
            # If it has `use crate::module as alias;`, use alias::
            glob_imported = set()
            for mod_id in mod_idents:
                actual_mod = alias_to_mod.get(mod_id, mod_id)
                if f'use crate::{actual_mod}::*;' in src:
                    glob_imported.add(mod_id)

            for mod_id in mod_idents:
                if mod_id in glob_imported:
                    # Glob imported: remove the module prefix entirely
                    src = _re.sub(
                        rf'\b{_re.escape(mod_id)}\.(\w+)',
                        r'\1',
                        src,
                    )
                else:
                    # Module path: use :: syntax
                    src = _re.sub(
                        rf'\b{_re.escape(mod_id)}\.(\w+)',
                        rf'{mod_id}::\1',
                        src,
                    )

            # Rule 1b: Convert Python stdlib module.func to module::func
            # so all subsequent rules can match with :: syntax
            _py_stdlib_mods = [
                'os', 'sys', 'json', 're', 'time', 'datetime', 'math',
                'shutil', 'tempfile', 'subprocess', 'threading',
                'inspect', 'sqlite3', 'urllib', 'uuid', 'pathlib',
                'socket', 'http', 'logging', 'copy', 'hashlib', 'base64',
                'signal', 'struct', 'pickle', 'csv', 'glob',
                'collections', 'itertools', 'functools',
            ]
            for mod in _py_stdlib_mods:
                src = _re.sub(
                    rf'\b{_re.escape(mod)}\.(\w+)',
                    rf'{mod}::\1',
                    src,
                )

            # Rule 2: Python-ism cleanup
            # .pop(0) on Vec → .remove(0)
            src = _re.sub(r'\.pop\(0\)', '.remove(0)', src)

            # Rule 3: threading → Rust std::thread/sync
            def _rewrite_threading(src_text):
                for marker in ('threading::Thread(', 'std::thread::JoinHandle<()>('):
                    while marker in src_text:
                        idx = src_text.index(marker)
                        start = idx + len(marker)
                        depth, end = 1, start
                        while end < len(src_text) and depth > 0:
                            if src_text[end] == '(':
                                depth += 1
                            elif src_text[end] == ')':
                                depth -= 1
                            end += 1
                        # Check if followed by .start()
                        rest = src_text[end:].lstrip()
                        if rest.startswith('.start()'):
                            end += src_text[end:].index('.start()') + len('.start()')
                        src_text = src_text[:idx] + 'std::thread::spawn(|| {})' + src_text[end:]
                return src_text
            src = _rewrite_threading(src)
            src = src.replace('threading::Lock()', 'std::sync::Mutex::new(())')
            src = src.replace('threading::RLock()', 'std::sync::Mutex::new(())')
            src = src.replace('threading::Event()', '/* Event */ ()')

            # Rule 4: os.environ → std::env::var
            # Use a function to handle balanced parens
            def _rewrite_environ(src_text):
                marker = 'os::environ.get('
                while marker in src_text:
                    idx = src_text.index(marker)
                    start = idx + len(marker)
                    depth, end = 1, start
                    while end < len(src_text) and depth > 0:
                        if src_text[end] == '(':
                            depth += 1
                        elif src_text[end] == ')':
                            depth -= 1
                        end += 1
                    inner = src_text[start:end - 1]
                    # Split on top-level comma
                    parts, d, cur = [], 0, []
                    for ch in inner:
                        if ch == '(' or ch == '[':
                            d += 1
                        elif ch == ')' or ch == ']':
                            d -= 1
                        if ch == ',' and d == 0:
                            parts.append(''.join(cur).strip())
                            cur = []
                        else:
                            cur.append(ch)
                    parts.append(''.join(cur).strip())
                    key = parts[0]
                    if len(parts) > 1:
                        default = parts[1]
                        replacement = f'std::env::var({key}).unwrap_or({default}.to_string())'
                    else:
                        replacement = f'std::env::var({key}).unwrap_or_default()'
                    src_text = src_text[:idx] + replacement + src_text[end:]
                return src_text
            src = _rewrite_environ(src)
            src = _re.sub(
                r'os::environ\[([^\]]+)\]',
                r'std::env::var(\1).unwrap()',
                src,
            )
            src = _re.sub(r'os::path::join\(', 'PathBuf::from(', src)
            src = _re.sub(r'os::path::exists\(([^)]+)\)', r'std::path::Path::new(\1).exists()', src)
            src = _re.sub(r'os::path::isfile\(([^)]+)\)', r'std::path::Path::new(\1).is_file()', src)
            src = _re.sub(r'os::path::isdir\(([^)]+)\)', r'std::path::Path::new(\1).is_dir()', src)
            src = _re.sub(r'os::path::basename\(([^)]+)\)', r'std::path::Path::new(\1).file_name().unwrap().to_str().unwrap()', src)
            src = _re.sub(r'os::path::dirname\(([^)]+)\)', r'std::path::Path::new(\1).parent().unwrap().to_str().unwrap()', src)
            src = _re.sub(r'os::makedirs\(([^,]+),\s*exist_ok\s*=\s*true\)', r'std::fs::create_dir_all(\1).ok()', src)
            src = _re.sub(r'os::makedirs\(([^)]+)\)', r'std::fs::create_dir_all(\1).unwrap()', src)
            src = _re.sub(r'os::listdir\(([^)]+)\)', r'std::fs::read_dir(\1).unwrap().map(|e| e.unwrap().path()).collect::<Vec<_>>()', src)
            src = _re.sub(r'os::getcwd\(\)', r'std::env::current_dir().unwrap().to_str().unwrap().to_string()', src)
            src = _re.sub(r'os::remove\(([^)]+)\)', r'std::fs::remove_file(\1).ok()', src)

            # Rule 5: sys module
            src = _re.sub(r'sys::exit\(([^)]+)\)', r'std::process::exit(\1)', src)
            src = _re.sub(r'sys::argv', 'std::env::args().collect::<Vec<String>>()', src)

            # Rule 6: subprocess
            src = _re.sub(
                r'subprocess::run\(([^)]+)\)',
                r'std::process::Command::new("sh").arg("-c").arg(\1).output().unwrap()',
                src,
            )

            # Rule 7: tempfile
            src = _re.sub(r'tempfile::mkdtemp\(\)', 'std::env::temp_dir().join("tmp")', src)
            src = _re.sub(r'tempfile::gettempdir\(\)', 'std::env::temp_dir()', src)

            # Rule 8: uuid
            src = _re.sub(r'uuid::uuid4\(\)', '/* uuid */ "00000000-0000-0000-0000-000000000000".to_string()', src)

            # Rule 9: json module (when used as module::)
            src = _re.sub(r'json::dumps\(([^)]+)\)', r'serde_json::to_string(&\1).unwrap()', src)
            src = _re.sub(r'json::loads\(([^)]+)\)', r'serde_json::from_str(&\1).unwrap()', src)

            # Rule 10: time module
            src = _re.sub(r'time::sleep\(([^)]+)\)', r'std::thread::sleep(std::time::Duration::from_secs_f64(\1))', src)
            src = _re.sub(r'time::time\(\)', 'std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64()', src)

            # Rule 11: shutil
            src = _re.sub(r'shutil::rmtree\(([^)]+)\)', r'std::fs::remove_dir_all(\1).ok()', src)
            src = _re.sub(r'shutil::copy2?\(([^,]+),\s*([^)]+)\)', r'std::fs::copy(\1, \2).unwrap()', src)
            src = _re.sub(r'shutil::r#move\(([^,]+),\s*([^)]+)\)', r'std::fs::rename(\1, \2).unwrap()', src)
            src = _re.sub(r'shutil::move\b', 'std::fs::rename', src)

            # Rule 12: inspect module
            src = _re.sub(r'inspect::getmembers\(([^)]+)\)', r'/* inspect::getmembers */ vec![]', src)
            src = _re.sub(r'inspect::isfunction\(([^)]+)\)', r'/* inspect::isfunction */ true', src)
            src = _re.sub(r'inspect::isclass\(([^)]+)\)', r'/* inspect::isclass */ true', src)

            # Rule 13: sqlite3
            src = _re.sub(r'sqlite3::connect\(([^)]+)\)', r'/* sqlite3 */ \1', src)

            # Rule 14: urllib
            src = _re.sub(r'urllib::request::urlopen\(([^)]+)\)', r'/* urlopen */ \1', src)
            src = _re.sub(r'urllib::parse::urlencode\(([^)]+)\)', r'/* urlencode */ \1.to_string()', src)

            # Rule 15: Python __dunder__ → Rust equivalents
            src = src.replace('__file__', 'file!()')
            src = src.replace('__name__', 'module_path!()')

            # Rule 16: None → None (Rust Option)
            src = _re.sub(r'\bNone\b', 'None', src)

            # Rule 17: True/False cleanup
            src = _re.sub(r'\bTrue\b', 'true', src)
            src = _re.sub(r'\bFalse\b', 'false', src)

            # Rule 18: Python format specs in Rust format strings
            # {:02d} → {:02}, {:.2f} → {:.2}, {:d} → {}
            src = _re.sub(r'\{([^}]*):(\d+)d\}', r'{\1:\2}', src)
            src = _re.sub(r'\{([^}]*):0(\d+)d\}', r'{\1:0\2}', src)
            src = _re.sub(r'\{([^}]*)d\}', r'{\1}', src)
            # Strip trailing 'f' from format specs: {:>5.1f} → {:>5.1}
            src = _re.sub(r'\{([^}]*\.\d+)f\}', r'{\1}', src)
            src = _re.sub(r'\{([^}]*\d)f\}', r'{\1}', src)
            # {:s} → {} (no 's' trait in Rust)
            src = _re.sub(r'\{([^}]*)s\}', r'{\1}', src)

            # Rule 19: Fix _re.match / _re.search (local regex alias)
            # _re.match(pattern, string) → regex::Regex::new(&pattern).unwrap().is_match(&string)
            src = _re.sub(
                r'_re\.match\(([^,]+),\s*([^)]+)\)',
                r'regex::Regex::new(&\1).unwrap().is_match(&\2)',
                src,
            )
            src = _re.sub(
                r'_re\.search\(([^,]+),\s*([^)]+)\)',
                r'regex::Regex::new(&\1).unwrap().is_match(&\2)',
                src,
            )
            src = _re.sub(
                r'_re\.sub\(([^,]+),\s*([^,]+),\s*([^)]+)\)',
                r'regex::Regex::new(&\1).unwrap().replace_all(&\3, \2).to_string()',
                src,
            )
            src = _re.sub(
                r'_re\.compile\(([^)]+)\)',
                r'regex::Regex::new(&\1).unwrap()',
                src,
            )

            # Rule 20: Callable type syntax fix
            # Box<dyn Fn><args> → Box<dyn Fn(args)>
            src = _re.sub(
                r'Box<dyn Fn><([^>]+)>',
                r'Box<dyn Fn(\1)>',
                src,
            )

            result[path] = src

        return result

    def _write_output(
        self,
        modules: list[PythonModule],
        rust_sources: dict[str, str],
        cargo_toml: str,
    ) -> None:
        """Write all generated Rust files to the output directory."""
        out = Path(self.config.output_dir)
        src_dir = out / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        # Cargo.toml
        if cargo_toml:
            (out / "Cargo.toml").write_text(cargo_toml, encoding="utf-8")

        # Source files
        for relpath, content in rust_sources.items():
            filepath = out / relpath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            log.info("Wrote %s", filepath)

    def _rust_filename(self, module: PythonModule) -> str:
        """Determine the output Rust filename for a Python module."""
        name = module.module_name
        if name == "__init__":
            return "src/mod.rs"
        if name == "__main__":
            return "src/main.rs"
        return f"src/{RustCodegen._sanitize_ident(name)}.rs"

    @staticmethod
    def _extract_code_block(text: str) -> str:
        """Extract a ```rust ... ``` code block from LLM output, or return the
        text as-is if no block is found."""
        m = re.search(r'```(?:rust)?\s*\n(.*?)```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # No code block — strip leading/trailing whitespace
        return text.strip()
