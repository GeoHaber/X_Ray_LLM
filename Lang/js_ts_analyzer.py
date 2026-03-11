"""Lang/js_ts_analyzer.py — Regex-based JS/TS/JSX/TSX file analyzer.

Provides function extraction, complexity calculation, and import
detection for JavaScript and TypeScript files (including React JSX/TSX).

Since X-Ray is a Python tool, we use regex heuristics rather than
requiring a JS AST parser like tree-sitter or babel.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple


# ── Scannable web extensions ────────────────────────────────────────────

WEB_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"})
DEVOPS_EXTENSIONS = frozenset({".yml", ".yaml"})
DEVOPS_FILENAMES = frozenset(
    {
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Jenkinsfile",
        "Makefile",
        ".dockerignore",
    }
)


def is_web_file(filename: str) -> bool:
    """Return True if *filename* is a scannable JS/TS/React file."""
    return Path(filename).suffix.lower() in WEB_EXTENSIONS


def is_devops_file(filename: str) -> bool:
    """Return True if *filename* is a DevOps config file."""
    name = Path(filename).name
    if name in DEVOPS_FILENAMES:
        return True
    suffix = Path(filename).suffix.lower()
    if suffix in DEVOPS_EXTENSIONS:
        # Only flag known DevOps filenames, not all YAML
        return name.startswith(("docker-compose", "Jenkinsfile"))
    return name in DEVOPS_FILENAMES


# ── JS/TS function record ──────────────────────────────────────────────


@dataclass
class JSFunction:
    """Extracted function metadata from a JS/TS file."""

    name: str
    file_path: str
    line_start: int
    line_end: int
    size_lines: int
    parameters: List[str]
    is_async: bool
    is_arrow: bool
    is_exported: bool
    is_react_component: bool
    complexity: int
    nesting_depth: int
    code: str
    code_hash: str
    kind: str = "function"  # "function" | "method" | "arrow" | "component"

    @property
    def location(self) -> str:
        """Human-readable location string."""
        return f"{self.file_path}:{self.line_start}"


@dataclass
class JSImport:
    """An import statement from a JS/TS file."""

    module: str
    names: List[str]
    line: int
    is_default: bool
    is_dynamic: bool = False


@dataclass
class JSFileAnalysis:
    """Full analysis result for one JS/TS file."""

    file_path: str
    total_lines: int
    functions: List[JSFunction] = field(default_factory=list)
    imports: List[JSImport] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    console_logs: List[int] = field(default_factory=list)  # line numbers
    todos: List[Tuple[int, str]] = field(default_factory=list)
    has_jsx: bool = False
    language: str = "javascript"  # "javascript" | "typescript" | "react"
    errors: List[str] = field(default_factory=list)


# ── Regex patterns ──────────────────────────────────────────────────────

# Function declarations: function name(params) { ... }
_RE_FUNC_DECL = re.compile(
    r"^(?P<export>export\s+)?(?P<default>default\s+)?"
    r"(?P<async>async\s+)?function\s*(?:\*\s*)?"
    r"(?P<name>\w+)?\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)

# Arrow functions: const name = (params) => { ... }
_RE_ARROW = re.compile(
    r"^(?P<export>export\s+)?(?:const|let|var)\s+"
    r"(?P<name>\w+)\s*"
    r"(?::\s*[^=]+?)?\s*=\s*"  # optional TS type annotation
    r"(?P<async>async\s+)?"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?::\s*[^=>{]+?)?\s*=>\s*",  # optional TS return type
    re.MULTILINE,
)

# Class methods: name(params) { or async name(params) {
_RE_METHOD = re.compile(
    r"^\s+(?P<static>static\s+)?(?P<async>async\s+)?"
    r"(?P<accessor>get\s+|set\s+)?"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*"
    r"(?::\s*[^{]+?)?\s*\{",
    re.MULTILINE,
)

# Class definition
_RE_CLASS = re.compile(
    r"^(?:export\s+)?(?:default\s+)?class\s+(?P<name>\w+)",
    re.MULTILINE,
)

# React component: const Name = (props) => ( ... JSX ... )
# or function Name(props) { return <div>...</div> }
_RE_REACT_COMPONENT = re.compile(
    r"(?:const|function)\s+(?P<name>[A-Z]\w+)",
    re.MULTILINE,
)

# Import patterns
_RE_IMPORT = re.compile(
    r"^import\s+(?:"
    r"(?P<default>\w+)"  # default import
    r"|(?:\{?\s*(?P<named>[^}]+?)\s*\}?)"  # named imports
    r"(?:\s*,\s*(?:\{?\s*(?P<named2>[^}]+?)\s*\}?))?"
    r")\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)

_RE_REQUIRE = re.compile(
    r"(?:const|let|var)\s+(?:\{?\s*(?P<names>[^}=]+?)\s*\}?)\s*="
    r"\s*require\s*\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)",
    re.MULTILINE,
)

_RE_DYNAMIC_IMPORT = re.compile(
    r"import\s*\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)",
)

# Console.log and friends
_RE_CONSOLE = re.compile(
    r"^\s*console\.(log|warn|error|debug|info|trace)\s*\(",
    re.MULTILINE,
)

# Marker comments (e.g. "// TODO:", "/* FIXME */")
_RE_TODO = re.compile(
    r"(?://|/\*)\s*(?:TODO|FIXME|HACK|XXX)\s*:?\s*(.*)",
    re.IGNORECASE,
)

# Complexity indicators
_RE_COMPLEXITY = re.compile(
    r"\b(?:if|else\s+if|for|while|do|switch|case|\?\?|catch|&&|\|\||\?)\b"
)

# JSX detection
_RE_JSX = re.compile(r"<[A-Z]\w+[\s/>]|<\/[A-Z]\w+>|<\w+\.[A-Z]")


# ── Core analysis functions ─────────────────────────────────────────────


def _find_matching_brace(lines: List[str], start_line: int) -> int:
    """Find the line number of the closing brace starting from *start_line*.

    Returns the line index (0-based) of the matching ``}``, or the last
    line if no match is found.
    """
    depth = 0
    in_string = False
    string_char = ""

    for i in range(start_line, len(lines)):
        line = lines[i]
        depth, in_string, string_char, matched = _scan_braces_in_line(
            line, depth, in_string, string_char
        )
        if matched:
            return i

    return min(start_line + 200, len(lines) - 1)  # fallback cap


def _scan_braces_in_line(
    line: str, depth: int, in_string: bool, string_char: str
) -> tuple:
    """Process one line, tracking string state and brace depth.

    Returns ``(depth, in_string, string_char, matched)`` where *matched*
    is True if a closing ``}`` brought depth back to zero.
    """
    j = 0
    while j < len(line):
        ch = line[j]
        if in_string:
            if ch == "\\" and j + 1 < len(line):
                j += 2
                continue
            if ch == string_char:
                in_string = False
        elif ch in ('"', "'", "`"):
            in_string = True
            string_char = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return depth, in_string, string_char, True
        j += 1
    return depth, in_string, string_char, False


def _count_nesting(code: str) -> int:
    """Estimate maximum nesting depth from brace/indent analysis."""
    max_depth = 0
    depth = 0
    in_string = False
    string_char = ""

    for ch in code:
        if in_string:
            if ch == string_char:
                in_string = False
            continue
        if ch in ('"', "'", "`"):
            in_string = True
            string_char = ch
        elif ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)

    return max_depth


def _count_complexity(code: str) -> int:
    """Estimate cyclomatic complexity from keyword counting."""
    # Remove strings and comments to avoid false positives
    cleaned = re.sub(r'(["\'])(?:(?!\1).)*\1', '""', code)
    cleaned = re.sub(r"//[^\n]*", "", cleaned)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

    matches = _RE_COMPLEXITY.findall(cleaned)
    # Base complexity of 1 + branch points
    return 1 + len(matches)


def _parse_params(param_str: str) -> List[str]:
    """Parse a JS/TS parameter string into a list of parameter names."""
    if not param_str or not param_str.strip():
        return []
    params = []
    for p in param_str.split(","):
        p = p.strip()
        if not p:
            continue
        # Remove TS type annotations: name: Type = default
        name = re.split(r"[:\s=?]", p)[0].strip()
        # Remove destructuring braces
        name = name.strip("{} ")
        if name and name != "...":
            # Handle rest params: ...args
            if name.startswith("..."):
                name = name[3:]
            params.append(name)
    return params


def _code_hash(code: str) -> str:
    """SHA-256 hash of code string."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def analyze_js_file(fpath: Path, root: Path) -> JSFileAnalysis:
    """Analyze a single JS/TS/JSX/TSX file and return structured results.

    This is the main entry point for JS/TS analysis. It extracts:
    - Function declarations, arrow functions, and class methods
    - Import/require statements
    - console.log locations
    - TODO/FIXME comments
    - JSX usage detection
    - Complexity and nesting metrics per function
    """
    try:
        source = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        rel = str(fpath.relative_to(root)).replace("\\", "/")
        return JSFileAnalysis(file_path=rel, total_lines=0, errors=[str(e)])

    rel_path = str(fpath.relative_to(root)).replace("\\", "/")
    lines = source.splitlines()
    suffix = fpath.suffix.lower()

    analysis = JSFileAnalysis(
        file_path=rel_path,
        total_lines=len(lines),
        has_jsx=bool(_RE_JSX.search(source)),
    )

    # Determine language
    if suffix in (".tsx",):
        analysis.language = "react-typescript"
    elif suffix in (".jsx",):
        analysis.language = "react"
    elif suffix in (".ts", ".mts", ".cts"):
        analysis.language = "typescript"
    else:
        analysis.language = "javascript"

    # ── Extract imports ─────────────────────────────────────────────────
    analysis.imports = _extract_imports(source)

    # ── Find console.log calls ──────────────────────────────────────────
    for m in _RE_CONSOLE.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        analysis.console_logs.append(lineno)

    # ── Find TODOs ──────────────────────────────────────────────────────
    for m in _RE_TODO.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        analysis.todos.append((lineno, m.group(1).strip()))

    # ── Extract functions ───────────────────────────────────────────────
    analysis.functions = _extract_functions(source, lines, rel_path, analysis.has_jsx)

    return analysis


def _extract_imports(source: str) -> List[JSImport]:
    """Extract all import/require statements from source."""
    imports: List[JSImport] = []

    for m in _RE_IMPORT.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        default_name = m.group("default")
        named = m.group("named") or ""
        named2 = m.group("named2") or ""
        module = m.group("module")

        names: List[str] = []
        if default_name:
            names.append(default_name)
        for n_str in (named, named2):
            if n_str:
                names.extend(
                    n.strip().split(" as ")[0].strip()
                    for n in n_str.split(",")
                    if n.strip()
                )

        imports.append(
            JSImport(
                module=module,
                names=names,
                line=lineno,
                is_default=bool(default_name),
            )
        )

    for m in _RE_REQUIRE.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        names_str = m.group("names") or ""
        module = m.group("module")
        names = [n.strip() for n in names_str.split(",") if n.strip()]
        imports.append(
            JSImport(module=module, names=names, line=lineno, is_default=True)
        )

    for m in _RE_DYNAMIC_IMPORT.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        imports.append(
            JSImport(
                module=m.group("module"),
                names=[],
                line=lineno,
                is_default=False,
                is_dynamic=True,
            )
        )

    return imports


def _extract_func_declarations(
    source: str, lines: List[str], rel_path: str, has_jsx: bool, seen_lines: set
) -> List[JSFunction]:
    functions = []
    for m in _RE_FUNC_DECL.finditer(source):
        lineno = source[: m.start()].count("\n")
        if lineno in seen_lines:
            continue
        seen_lines.add(lineno)

        name = m.group("name") or "<anonymous>"
        params = _parse_params(m.group("params"))
        is_exported = bool(m.group("export"))
        is_async = bool(m.group("async"))

        end_line = _find_matching_brace(lines, lineno)
        code = "\n".join(lines[lineno : end_line + 1])
        is_component = has_jsx and name[0:1].isupper() and bool(_RE_JSX.search(code))

        functions.append(
            JSFunction(
                name=name,
                file_path=rel_path,
                line_start=lineno + 1,
                line_end=end_line + 1,
                size_lines=end_line - lineno + 1,
                parameters=params,
                is_async=is_async,
                is_arrow=False,
                is_exported=is_exported,
                is_react_component=is_component,
                complexity=_count_complexity(code),
                nesting_depth=_count_nesting(code),
                code=code,
                code_hash=_code_hash(code),
                kind="component" if is_component else "function",
            )
        )
    return functions


def _extract_arrow_functions(
    source: str, lines: List[str], rel_path: str, has_jsx: bool, seen_lines: set
) -> List[JSFunction]:
    functions = []
    for m in _RE_ARROW.finditer(source):
        lineno = source[: m.start()].count("\n")
        if lineno in seen_lines:
            continue
        seen_lines.add(lineno)

        name = m.group("name")
        params = _parse_params(m.group("params"))
        is_exported = bool(m.group("export"))
        is_async = bool(m.group("async"))

        end_line = _find_matching_brace(lines, lineno)
        code = "\n".join(lines[lineno : end_line + 1])
        is_component = has_jsx and name[0:1].isupper() and bool(_RE_JSX.search(code))

        functions.append(
            JSFunction(
                name=name,
                file_path=rel_path,
                line_start=lineno + 1,
                line_end=end_line + 1,
                size_lines=end_line - lineno + 1,
                parameters=params,
                is_async=is_async,
                is_arrow=True,
                is_exported=is_exported,
                is_react_component=is_component,
                complexity=_count_complexity(code),
                nesting_depth=_count_nesting(code),
                code=code,
                code_hash=_code_hash(code),
                kind="component" if is_component else "arrow",
            )
        )
    return functions


def _extract_class_methods(
    source: str, lines: List[str], rel_path: str, seen_lines: set
) -> List[JSFunction]:
    functions = []
    for m in _RE_METHOD.finditer(source):
        lineno = source[: m.start()].count("\n")
        if lineno in seen_lines:
            continue
        seen_lines.add(lineno)

        name = m.group("name")
        if name in ("if", "for", "while", "switch", "catch", "else"):
            continue  # false positive — control flow keyword

        params = _parse_params(m.group("params"))
        is_async = bool(m.group("async"))

        end_line = _find_matching_brace(lines, lineno)
        code = "\n".join(lines[lineno : end_line + 1])

        functions.append(
            JSFunction(
                name=name,
                file_path=rel_path,
                line_start=lineno + 1,
                line_end=end_line + 1,
                size_lines=end_line - lineno + 1,
                parameters=params,
                is_async=is_async,
                is_arrow=False,
                is_exported=False,
                is_react_component=False,
                complexity=_count_complexity(code),
                nesting_depth=_count_nesting(code),
                code=code,
                code_hash=_code_hash(code),
                kind="method",
            )
        )
    return functions


def _extract_functions(
    source: str, lines: List[str], rel_path: str, has_jsx: bool
) -> List[JSFunction]:
    """Extract all function-like constructs from JS/TS source."""
    functions: List[JSFunction] = []
    seen_lines: set = set()

    functions.extend(
        _extract_func_declarations(source, lines, rel_path, has_jsx, seen_lines)
    )
    functions.extend(
        _extract_arrow_functions(source, lines, rel_path, has_jsx, seen_lines)
    )
    functions.extend(_extract_class_methods(source, lines, rel_path, seen_lines))

    return functions


# ── Package mapping (130+ common JS/TS packages) ───────────────────────

JS_PACKAGE_CATEGORIES: Dict[str, List[str]] = {
    "react-core": [
        "react",
        "react-dom",
        "react-router",
        "react-router-dom",
        "react-helmet",
        "react-hook-form",
        "react-query",
        "react-redux",
        "react-scripts",
        "react-select",
        "react-table",
        "react-transition-group",
        "react-spring",
        "react-i18next",
        "react-dropzone",
        "react-modal",
        "react-toastify",
        "react-icons",
        "react-datepicker",
    ],
    "next-js": [
        "next",
        "next-auth",
        "next-i18next",
        "next-seo",
        "next-themes",
        "next-mdx-remote",
    ],
    "state-management": [
        "redux",
        "redux-toolkit",
        "@reduxjs/toolkit",
        "zustand",
        "recoil",
        "jotai",
        "mobx",
        "mobx-react",
        "valtio",
        "xstate",
    ],
    "ui-framework": [
        "@mui/material",
        "@chakra-ui/react",
        "antd",
        "tailwindcss",
        "bootstrap",
        "react-bootstrap",
        "@headlessui/react",
        "styled-components",
        "@emotion/react",
        "@emotion/styled",
        "radix-ui",
        "@radix-ui/react-dialog",
        "shadcn-ui",
    ],
    "testing": [
        "jest",
        "@jest/globals",
        "vitest",
        "cypress",
        "playwright",
        "@testing-library/react",
        "@testing-library/jest-dom",
        "@testing-library/user-event",
        "mocha",
        "chai",
        "sinon",
        "supertest",
        "nock",
        "msw",
    ],
    "build-tools": [
        "webpack",
        "vite",
        "esbuild",
        "rollup",
        "parcel",
        "turbo",
        "babel",
        "@babel/core",
        "@babel/preset-env",
        "swc",
        "tsup",
        "unbuild",
    ],
    "http-client": [
        "axios",
        "node-fetch",
        "got",
        "ky",
        "superagent",
        "undici",
        "ofetch",
    ],
    "server-framework": [
        "express",
        "fastify",
        "koa",
        "hapi",
        "nestjs",
        "@nestjs/core",
        "hono",
        "h3",
    ],
    "database": [
        "prisma",
        "@prisma/client",
        "mongoose",
        "sequelize",
        "typeorm",
        "knex",
        "drizzle-orm",
        "pg",
        "mysql2",
        "better-sqlite3",
        "redis",
        "ioredis",
    ],
    "auth": [
        "jsonwebtoken",
        "passport",
        "bcrypt",
        "bcryptjs",
        "jose",
        "oauth4webapi",
    ],
    "validation": [
        "zod",
        "yup",
        "joi",
        "class-validator",
        "ajv",
        "superstruct",
    ],
    "utility": [
        "lodash",
        "ramda",
        "date-fns",
        "dayjs",
        "moment",
        "uuid",
        "nanoid",
        "chalk",
        "debug",
        "dotenv",
        "cross-env",
    ],
    "type-system": [
        "typescript",
        "ts-node",
        "@types/node",
        "@types/react",
        "@types/jest",
        "tsx",
    ],
    "linting": [
        "eslint",
        "prettier",
        "@typescript-eslint/parser",
        "@typescript-eslint/eslint-plugin",
        "eslint-config-next",
    ],
    "devops": [
        "docker-compose",
        "pm2",
        "nodemon",
        "concurrently",
        "husky",
        "lint-staged",
        "commitlint",
    ],
}

# Flat lookup: package_name → category
PACKAGE_TO_CATEGORY: Dict[str, str] = {}
for _cat, _pkgs in JS_PACKAGE_CATEGORIES.items():
    for _pkg in _pkgs:
        PACKAGE_TO_CATEGORY[_pkg] = _cat


def categorize_imports(imports: List[JSImport]) -> Dict[str, List[str]]:
    """Categorize imports by their package category.

    Returns a dict mapping category names to lists of imported package names.
    """
    result: Dict[str, List[str]] = {}
    for imp in imports:
        module = imp.module
        # Normalize scoped packages: @scope/pkg → @scope/pkg
        cat = PACKAGE_TO_CATEGORY.get(module)
        if not cat:
            # Try prefix match for scoped packages
            parts = module.split("/")
            if len(parts) >= 2 and parts[0].startswith("@"):
                cat = PACKAGE_TO_CATEGORY.get(f"{parts[0]}/{parts[1]}")
        if cat:
            result.setdefault(cat, []).append(module)
    return result


# Module-level API for test compatibility

def location(file_path: str, line_start: int) -> str:
    """Return a human-readable location string (standalone helper)."""
    return f"{file_path}:{line_start}"

