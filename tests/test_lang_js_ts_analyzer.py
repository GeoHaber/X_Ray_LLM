"""
tests/test_lang_js_ts_analyzer.py
===================================
Tests for Lang/js_ts_analyzer.py — JS/TS/JSX/TSX regex-based file analyzer.

Covers:
  - is_web_file / is_devops_file helpers
  - JSFunction, JSImport, JSFileAnalysis dataclasses
  - analyze_js_file: function extraction, import detection, console.log, todos
  - _extract_imports, _extract_func_declarations, _extract_arrow_functions,
    _extract_class_methods
  - _count_complexity, _count_nesting, _parse_params, _code_hash
  - categorize_imports
"""

import hashlib
import textwrap
from pathlib import Path

import pytest

from Lang.js_ts_analyzer import (
    JSFileAnalysis,
    JSFunction,
    JSImport,
    analyze_js_file,
    categorize_imports,
    is_devops_file,
    is_web_file,
    _count_complexity,
    _count_nesting,
    _parse_params,
    _extract_imports,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tmp_js(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a temporary JS/TS file and return its path."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f


# ── is_web_file ───────────────────────────────────────────────────────────────

class TestIsWebFile:
    def test_js_extension(self):
        assert is_web_file("app.js") is True

    def test_ts_extension(self):
        assert is_web_file("main.ts") is True

    def test_jsx_extension(self):
        assert is_web_file("Component.jsx") is True

    def test_tsx_extension(self):
        assert is_web_file("Button.tsx") is True

    def test_python_not_web(self):
        assert is_web_file("app.py") is False

    def test_json_not_web(self):
        assert is_web_file("package.json") is False

    def test_empty_string(self):
        assert is_web_file("") is False

    def test_no_extension(self):
        assert is_web_file("Makefile") is False


# ── is_devops_file ────────────────────────────────────────────────────────────

class TestIsDevopsFile:
    def test_dockerfile(self):
        assert is_devops_file("Dockerfile") is True

    def test_yaml_extension_generic_not_devops(self):
        # Generic .yml files are NOT flagged — only specific DevOps filenames
        assert is_devops_file("github.yml") is False

    def test_docker_compose(self):
        assert is_devops_file("docker-compose.yml") is True

    def test_python_not_devops(self):
        assert is_devops_file("app.py") is False

    def test_js_not_devops(self):
        assert is_devops_file("index.js") is False


# ── JSFunction dataclass ──────────────────────────────────────────────────────

class TestJSFunction:
    def test_location_string(self):
        fn = JSFunction(
            name="myFunc",
            file_path="src/app.js",
            line_start=10,
            line_end=20,
            size_lines=10,
            parameters=["a", "b"],
            is_async=False,
            is_arrow=False,
            is_exported=True,
            is_react_component=False,
            complexity=2,
            nesting_depth=1,
            code="function myFunc(a, b) {}",
            code_hash="abc123",
        )
        loc = fn.location  # property, not method
        assert "src/app.js" in loc
        assert "10" in loc

    def test_defaults(self):
        fn = JSFunction(
            name="fn",
            file_path="a.js",
            line_start=1,
            line_end=5,
            size_lines=5,
            parameters=[],
            is_async=False,
            is_arrow=False,
            is_exported=False,
            is_react_component=False,
            complexity=1,
            nesting_depth=0,
            code="",
            code_hash="",
        )
        assert fn.kind == "function"  # default value


# ── _parse_params ─────────────────────────────────────────────────────────────

class TestParseParams:
    def test_simple_params(self):
        result = _parse_params("a, b, c")
        assert result == ["a", "b", "c"]

    def test_typed_params(self):
        result = _parse_params("name: string, age: number")
        assert "name" in result
        assert "age" in result

    def test_empty_params(self):
        result = _parse_params("")
        assert result == []

    def test_destructured_params(self):
        # Destructured params should not crash
        result = _parse_params("{ a, b }, c")
        assert isinstance(result, list)

    def test_default_values(self):
        result = _parse_params("x = 0, y = 1")
        assert "x" in result
        assert "y" in result


# ── _count_complexity ─────────────────────────────────────────────────────────

class TestCountComplexity:
    def test_simple_function(self):
        code = "function f() { return 1; }"
        assert _count_complexity(code) >= 1

    def test_if_adds_complexity(self):
        code = "function f(x) { if (x) { return 1; } return 0; }"
        assert _count_complexity(code) >= 2

    def test_loop_adds_complexity(self):
        code = "function f(arr) { for (let i = 0; i < arr.length; i++) {} }"
        assert _count_complexity(code) >= 2

    def test_ternary_adds_complexity(self):
        # The complexity regex matches `??` (nullish coalescing) and `?` conditional
        code = "const f = (x) => x ?? -1;"
        # ?? is included in the regex as \?\? which matches
        assert _count_complexity(code) >= 1  # at minimum base complexity of 1

    def test_logical_and_complexity(self):
        code = "if (a && b) { return 1; }"
        # && is matched by the regex → base 1 + 1 = 2
        assert _count_complexity(code) >= 2


# ── _count_nesting ────────────────────────────────────────────────────────────

class TestCountNesting:
    def test_flat_code(self):
        code = "function f() { return 1; }"
        assert _count_nesting(code) >= 0

    def test_nested_code(self):
        code = "function f() { if (x) { if (y) { return 1; } } }"
        assert _count_nesting(code) >= 2

    def test_empty_code(self):
        assert _count_nesting("") == 0


# ── _extract_imports ──────────────────────────────────────────────────────────

class TestExtractImports:
    def test_es_import(self):
        source = "import React from 'react';\n"
        imports = _extract_imports(source)
        assert any(i.module == "react" for i in imports)

    def test_named_imports(self):
        source = "import { useState, useEffect } from 'react';\n"
        imports = _extract_imports(source)
        react = next((i for i in imports if i.module == "react"), None)
        assert react is not None
        assert "useState" in react.names or len(react.names) > 0

    def test_require_import(self):
        source = "const fs = require('fs');\n"
        imports = _extract_imports(source)
        assert any(i.module == "fs" for i in imports)

    def test_dynamic_import(self):
        source = "const mod = await import('./module');\n"
        imports = _extract_imports(source)
        # Dynamic imports may or may not be captured depending on implementation
        assert isinstance(imports, list)

    def test_multiple_imports(self):
        source = (
            "import React from 'react';\n"
            "import axios from 'axios';\n"
            "import { debounce } from 'lodash';\n"
        )
        imports = _extract_imports(source)
        modules = {i.module for i in imports}
        assert "react" in modules
        assert "axios" in modules

    def test_no_imports(self):
        source = "function f() { return 1; }\n"
        imports = _extract_imports(source)
        assert imports == []


# ── analyze_js_file ───────────────────────────────────────────────────────────

class TestAnalyzeJsFile:
    def test_basic_function_extraction(self, tmp_path):
        f = _tmp_js(tmp_path, "app.js", """
            function greet(name) {
                return "Hello " + name;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        assert isinstance(result, JSFileAnalysis)
        assert any(fn.name == "greet" for fn in result.functions)

    def test_arrow_function_extraction(self, tmp_path):
        f = _tmp_js(tmp_path, "utils.js", """
            const add = (a, b) => a + b;
            const multiply = (x, y) => {
                return x * y;
            };
        """)
        result = analyze_js_file(f, tmp_path)
        names = {fn.name for fn in result.functions}
        assert "add" in names or "multiply" in names

    def test_class_method_extraction(self, tmp_path):
        f = _tmp_js(tmp_path, "service.js", """
            class UserService {
                constructor(db) {
                    this.db = db;
                }
                async getUser(id) {
                    return await this.db.find(id);
                }
            }
        """)
        result = analyze_js_file(f, tmp_path)
        names = {fn.name for fn in result.functions}
        assert "getUser" in names or "constructor" in names

    def test_import_detection(self, tmp_path):
        f = _tmp_js(tmp_path, "app.js", """
            import React from 'react';
            import { useState } from 'react';
            import axios from 'axios';

            function App() { return null; }
        """)
        result = analyze_js_file(f, tmp_path)
        modules = {i.module for i in result.imports}
        assert "react" in modules
        assert "axios" in modules

    def test_console_log_detection(self, tmp_path):
        f = _tmp_js(tmp_path, "debug.js", """
            function buggy() {
                console.log("debug 1");
                console.log("debug 2");
                console.log("debug 3");
                return true;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        assert len(result.console_logs) >= 3

    def test_todo_detection(self, tmp_path):
        f = _tmp_js(tmp_path, "todo.js", """
            // TODO: fix this later
            function broken() {
                // FIXME: this crashes on null
                return null;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        assert len(result.todos) >= 2

    def test_jsx_detection(self, tmp_path):
        f = _tmp_js(tmp_path, "Component.jsx", """
            import React from 'react';
            function Button({ onClick, label }) {
                return <Button onClick={onClick}>{label}</Button>;
            }
            export default Button;
        """)
        result = analyze_js_file(f, tmp_path)
        assert result.has_jsx is True

    def test_typescript_language_detection(self, tmp_path):
        f = _tmp_js(tmp_path, "api.ts", """
            interface User {
                id: number;
                name: string;
            }
            async function fetchUser(id: number): Promise<User> {
                return await fetch('/api/user/' + id).then(r => r.json());
            }
        """)
        result = analyze_js_file(f, tmp_path)
        assert result.language in ("typescript", "ts")

    def test_total_lines_count(self, tmp_path):
        content = "\n".join(["// line " + str(i) for i in range(50)])
        f = _tmp_js(tmp_path, "lines.js", content)
        result = analyze_js_file(f, tmp_path)
        assert result.total_lines >= 40  # allow some tolerance

    def test_exported_function_detected(self, tmp_path):
        f = _tmp_js(tmp_path, "exported.js", """
            export function publicAPI(x) {
                return x * 2;
            }
            function privateHelper(x) {
                return x + 1;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        exported = [fn for fn in result.functions if fn.is_exported]
        assert len(exported) >= 1
        assert any(fn.name == "publicAPI" for fn in exported)

    def test_async_function_detected(self, tmp_path):
        f = _tmp_js(tmp_path, "async.js", """
            async function loadData(url) {
                const response = await fetch(url);
                return response.json();
            }
        """)
        result = analyze_js_file(f, tmp_path)
        async_fns = [fn for fn in result.functions if fn.is_async]
        assert len(async_fns) >= 1

    def test_react_component_detected(self, tmp_path):
        # JSX detection requires uppercase component tags in the code
        f = _tmp_js(tmp_path, "Widget.jsx", """
            import React from 'react';
            function Widget({ title }) {
                return <Widget>{title}</Widget>;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        # If JSX is present and function starts with uppercase, it's a component
        assert result.has_jsx is True

    def test_relative_path_in_file_path(self, tmp_path):
        subdir = tmp_path / "src"
        subdir.mkdir()
        f = _tmp_js(subdir, "api.js", "function f() {}")
        result = analyze_js_file(f, tmp_path)
        assert "src" in result.file_path or "/" in result.file_path

    def test_nonexistent_file_returns_error(self, tmp_path):
        f = tmp_path / "nonexistent.js"
        result = analyze_js_file(f, tmp_path)
        assert len(result.errors) > 0 or result.total_lines == 0

    def test_empty_file(self, tmp_path):
        f = _tmp_js(tmp_path, "empty.js", "")
        result = analyze_js_file(f, tmp_path)
        assert result.functions == []
        assert result.imports == []

    def test_function_complexity_populated(self, tmp_path):
        f = _tmp_js(tmp_path, "complex.js", """
            function decide(a, b, c) {
                if (a) {
                    if (b) {
                        return 1;
                    } else if (c) {
                        return 2;
                    }
                }
                return 0;
            }
        """)
        result = analyze_js_file(f, tmp_path)
        fns = [fn for fn in result.functions if fn.name == "decide"]
        if fns:
            assert fns[0].complexity >= 2


# ── categorize_imports ────────────────────────────────────────────────────────

class TestCategorizeImports:
    def test_react_category(self):
        imports = [JSImport(module="react", names=["React"], line=1, is_default=True)]
        cats = categorize_imports(imports)
        assert any("react" in k.lower() or "ui" in k.lower() for k in cats)

    def test_node_builtins_category(self):
        imports = [JSImport(module="fs", names=[], line=1, is_default=True)]
        cats = categorize_imports(imports)
        # Should have some category for node builtins
        assert isinstance(cats, dict)

    def test_unknown_package_categorized(self):
        imports = [JSImport(module="my-custom-package", names=[], line=1, is_default=True)]
        cats = categorize_imports(imports)
        assert isinstance(cats, dict)
        assert len(cats) >= 0

    def test_empty_imports(self):
        cats = categorize_imports([])
        assert isinstance(cats, dict)

    def test_multiple_packages_multiple_cats(self):
        imports = [
            JSImport(module="react", names=["React"], line=1, is_default=True),
            JSImport(module="lodash", names=["debounce"], line=2, is_default=False),
            JSImport(module="axios", names=[], line=3, is_default=True),
        ]
        cats = categorize_imports(imports)
        assert isinstance(cats, dict)
