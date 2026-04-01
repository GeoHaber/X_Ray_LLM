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
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
            except Exception as exc:  # noqa: BLE001
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
        result: list[GlobalInfo] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                ty = self._infer_type(node.annotation)
                val = ast.dump(node.value) if node.value else ""
                result.append(GlobalInfo(name=node.target.id, type_hint=ty, value=val))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        ty = self._infer_type_from_value(node.value)
                        val = ast.dump(node.value) if node.value else ""
                        result.append(GlobalInfo(name=target.id, type_hint=ty, value=val))
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
            return TYPE_MAP.get(annotation.id, annotation.id)

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

    def generate_module(self, module: PythonModule) -> str:
        """Generate the complete Rust source file for one Python module."""
        sections: list[str] = []

        # Module docstring
        if module.docstring:
            sections.append(self._rust_doc_comment(module.docstring))

        # Use statements
        uses = self._generate_uses(module)
        if uses:
            sections.append(uses)

        # Global constants / statics
        for g in module.globals:
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

    def _generate_uses(self, module: PythonModule) -> str:
        uses: set[str] = set()
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

        sorted_uses = sorted(uses)
        return "\n".join(sorted_uses)

    # ------------------------------------------------------------------
    # Global constants
    # ------------------------------------------------------------------

    def _generate_global(self, g: GlobalInfo) -> str:
        ty = g.type_hint if g.type_hint != "/* unknown */" else "/* TODO */"
        # Try to emit as const; fall back to lazy_static pattern comment
        return f"// TODO: static/const {g.name}: {ty};"

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
            rust_ty = ftype if ftype != "/* unknown */" else "String /* TODO: infer type */"
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
            f"{self._sanitize_ident(name)}: {ty}"
            for name, ty in method.args
        )
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        lines.append(f"    pub fn new({params}) -> Self {{")
        lines.append(f"        Self {{")
        for fname, _ in cls.fields:
            lines.append(f"            {self._sanitize_ident(fname)},")
        lines.append(f"        }}")
        lines.append(f"    }}")
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
        body_lines = self._translate_body(method.body_source, indent=8)
        for bl in body_lines:
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    def _generate_static_method(self, method: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {ty}"
            for name, ty in method.args
        )
        ret = self._return_sig(method)
        lines: list[str] = []
        if method.docstring:
            lines.append(self._rust_doc_comment(method.docstring, indent=4))
        async_kw = "async " if method.is_async else ""
        lines.append(f"    pub {async_kw}fn {self._sanitize_ident(method.name)}({params}) -> {ret} {{")
        for bl in self._translate_body(method.body_source, indent=8):
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
        for bl in self._translate_body(method.body_source, indent=8):
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    def _generate_method(self, method: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {ty}"
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
        for bl in self._translate_body(method.body_source, indent=8):
            lines.append(bl)
        lines.append("    }")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Free function generation
    # ------------------------------------------------------------------

    def generate_function(self, func: FunctionInfo) -> str:
        params = ", ".join(
            f"{self._sanitize_ident(name)}: {ty}"
            for name, ty in func.args
        )
        ret = self._return_sig(func)
        lines: list[str] = []
        if func.docstring:
            lines.append(self._rust_doc_comment(func.docstring))
        async_kw = "async " if func.is_async else ""
        lines.append(f"pub {async_kw}fn {self._sanitize_ident(func.name)}({params}) -> {ret} {{")
        for bl in self._translate_body(func.body_source, indent=4):
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
    # Body translation — pattern-based line-by-line
    # ------------------------------------------------------------------

    def _translate_body(self, body_source: str, indent: int = 4) -> list[str]:
        """Translate Python body source to Rust line by line.

        Handles the most common patterns; complex constructs get a
        ``// TODO: translate manually`` comment.  Uses indentation
        tracking to emit closing braces for blocks.
        """
        if not body_source or not body_source.strip():
            return [" " * indent + "todo!(\"implement\")"]

        py_lines = body_source.splitlines()
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

            # Close any blocks whose indentation is now finished
            while brace_stack and py_indent <= brace_stack[-1]:
                brace_stack.pop()
                extra = " " * (indent + len(brace_stack) * 4)
                rust_lines.append(f"{extra}}}")

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
        # Collect the try body
        rust.append("// try {")
        consumed += 1  # skip 'try:'
        i = 1
        try_body: list[str] = []
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("except") or stripped == "finally:":
                break
            try_body.append(stripped)
            i += 1
            consumed += 1

        rust.append("match (|| -> Result<(), Box<dyn std::error::Error>> {")
        for tb in try_body:
            t = self._try_translate_line(tb, "    ")
            rust.append(t if t else f"    // TODO: {tb}")
        rust.append("    Ok(())")
        rust.append("})() {")
        rust.append("    Ok(()) => {},")

        # Except clause(s)
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("except"):
                m = re.match(r'^except\s*(\w+)?\s*(?:as\s+(\w+))?\s*:', stripped)
                exc_type = m.group(1) if m and m.group(1) else "_"
                exc_var = m.group(2) if m and m.group(2) else "e"
                rust.append(f"    Err({exc_var}) => {{")
                consumed += 1
                i += 1
                # Collect except body
                while i < len(lines):
                    s2 = lines[i].strip()
                    if not s2 or s2.startswith("except") or s2 == "finally:" or s2 == "else:":
                        break
                    t = self._try_translate_line(s2, "        ")
                    rust.append(t if t else f"        // TODO: {s2}")
                    i += 1
                    consumed += 1
                rust.append("    }")
            elif stripped == "finally:":
                consumed += 1
                i += 1
                rust.append("} // finally:")
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

        rust.append("}")
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

    def _translate_string_format(self, expr: str) -> str:
        """Translate Python f-strings and .format() to Rust format! arguments."""
        # f"..." -> format!("...")
        expr = expr.strip()
        if expr.startswith('f"') or expr.startswith("f'"):
            inner = expr[2:-1]
            # Replace {var} with {} and collect the variables
            parts: list[str] = []
            fmt = ""
            last = 0
            for m in re.finditer(r'\{([^}]+)\}', inner):
                fmt += inner[last:m.start()] + "{}"
                parts.append(self._translate_expr(m.group(1)))
                last = m.end()
            fmt += inner[last:]
            if parts:
                args = ", ".join(parts)
                return f'"{fmt}", {args}'
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

        # f-string
        if expr.startswith('f"') or expr.startswith("f'"):
            inner = expr[2:-1]
            parts: list[str] = []
            fmt = ""
            last = 0
            for m in re.finditer(r'\{([^}]+)\}', inner):
                fmt += inner[last:m.start()] + "{}"
                parts.append(self._translate_expr(m.group(1)))
                last = m.end()
            fmt += inner[last:]
            if parts:
                args = ", ".join(parts)
                return f'format!("{fmt}", {args})'
            return f'format!("{fmt}")'

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

        # Dict literal
        if expr.startswith("{") and expr.endswith("}") and ":" in expr:
            return self._translate_dict_literal(expr)

        # isinstance(x, Y) -> matches! or type check
        m = re.match(r'^isinstance\((\w+),\s*(\w+)\)$', expr)
        if m:
            return f'/* isinstance({m.group(1)}, {m.group(2)}) */'

        # len(x)
        m = re.match(r'^len\((.+)\)$', expr)
        if m:
            inner = self._translate_expr(m.group(1))
            return f"{inner}.len()"

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

        # Numeric / identifier — pass through
        return expr

    def _translate_condition(self, cond: str) -> str:
        """Translate a Python boolean condition to Rust."""
        # and / or
        cond = cond.replace(" and ", " && ").replace(" or ", " || ")
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
        if self.config.error_strategy == "anyhow":
            return f"Result<{rt}>"
        if self.config.error_strategy == "thiserror":
            return f"Result<{rt}, AppError>"
        return rt

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
        except Exception as exc:  # noqa: BLE001
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

        for module in modules:
            rust_src = self._generate_with_llm_fallback(module)
            rust_sources[self._rust_filename(module)] = rust_src
            all_deps |= module.dependencies

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

    def _generate_with_llm_fallback(self, module: PythonModule) -> str:
        """Generate Rust source, using LLM for TODO-marked complex sections."""
        rust_src = self.codegen.generate_module(module)

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
                except Exception as exc:  # noqa: BLE001
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
                except Exception as exc:  # noqa: BLE001
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
                timeout=120,
            )
            if proc.returncode == 0:
                log.info("cargo check succeeded")
                return True, []
            errors = proc.stderr.splitlines()
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
            except Exception as exc:  # noqa: BLE001
                log.debug("LLM compile-fix failed: %s", exc)
                break

        if self._llm_helper:
            result.llm_calls_made = self._llm_helper.calls_made
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
