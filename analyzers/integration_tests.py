"""
Integration Test Generator — Generates API integration tests, round-trip tests,
wire health tests, and cross-module dependency tests.
"""

from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

from analyzers._shared import _SKIP_DIRS


def _discover_endpoints(directory: str) -> list[dict]:
    """Discover all API endpoints with their methods, params, and handler info."""
    endpoints = []
    route_rx = [
        re.compile(r"""@\w+\.\s*(route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
        re.compile(r"""(?:app|router)\.\s*(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
    ]
    body_rx = re.compile(r"""(?:request\.(?:json|get_json|form|data)|req\.body|body\s*=)""")

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".ts")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    lines = content.splitlines()
            except OSError:
                continue

            for i, line in enumerate(lines, 1):
                for rx in route_rx:
                    for m in rx.finditer(line):
                        method = m.group(1).upper()
                        if method == "ROUTE":
                            method = "GET"
                        url = m.group(2)
                        # Check nearby lines for request body usage
                        context = "\n".join(lines[max(0, i - 1):min(len(lines), i + 20)])
                        accepts_body = bool(body_rx.search(context))
                        endpoints.append({
                            "method": method,
                            "url": url,
                            "file": os.path.relpath(fp, directory),
                            "line": i,
                            "accepts_body": accepts_body,
                        })
    return endpoints


def _discover_modules(directory: str) -> dict[str, list[str]]:
    """Discover Python modules and their exports (functions/classes)."""
    modules: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, directory)
            try:
                import ast
                with open(fp, encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fp)
                exports = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_"):
                            exports.append(node.name)
                    elif isinstance(node, ast.ClassDef):
                        if not node.name.startswith("_"):
                            exports.append(node.name)
                if exports:
                    modules[rel] = exports
            except (OSError, SyntaxError):
                continue
    return modules


def _discover_cross_imports(directory: str) -> list[dict]:
    """Find cross-module imports (module A imports from module B)."""
    imports = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, directory)
            try:
                import ast
                with open(fp, encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fp)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        names = [a.name for a in node.names if a.name != "*"]
                        if names:
                            imports.append({
                                "from_file": rel,
                                "imports_module": node.module,
                                "names": names,
                            })
            except (OSError, SyntaxError):
                continue
    return imports


def generate_integration_tests(directory: str, base_url: str = "http://localhost:8077") -> dict:
    """
    Generate integration tests for the project:
    1. API endpoint tests (call each discovered endpoint)
    2. Wire health tests (pytest fixtures for wire-connector)
    3. Cross-module dependency tests
    """
    root = str(Path(directory).resolve())
    endpoints = _discover_endpoints(root)
    modules = _discover_modules(root)
    cross_imports = _discover_cross_imports(root)

    tests: list[dict] = []
    code_blocks: list[str] = []

    # ── Header ────────────────────────────────────────────────────────
    header = textwrap.dedent(f'''\
        """
        Auto-generated integration tests by X-Ray LLM.
        Target: {os.path.basename(root)}
        Base URL: {base_url}
        """

        import pytest
        import requests
        import json


        BASE_URL = "{base_url}"


        @pytest.fixture(scope="session")
        def api():
            """Session-scoped API client."""
            session = requests.Session()
            session.headers["Content-Type"] = "application/json"
            yield session
            session.close()

    ''')
    code_blocks.append(header)

    # ── API Endpoint Tests ────────────────────────────────────────────
    for ep in endpoints:
        method = ep["method"]
        url = ep["url"]
        fn_name = f"test_{method.lower()}_{url.replace('/', '_').replace('-', '_').strip('_')}"
        # De-duplicate
        if any(t.get("name") == fn_name for t in tests):
            continue

        if ep["accepts_body"] or method in ("POST", "PUT", "PATCH"):
            body_hint = '{"directory": "."}'  # sensible default
            test_code = textwrap.dedent(f'''\
                def {fn_name}(api):
                    """Integration test: {method} {url}"""
                    resp = api.{method.lower()}(f"{{BASE_URL}}{url}", json={body_hint})
                    assert resp.status_code in (200, 201, 400), f"Unexpected {{resp.status_code}}: {{resp.text[:200]}}"
                    if resp.status_code == 200:
                        data = resp.json()
                        assert isinstance(data, (dict, list)), f"Expected JSON object/array, got {{type(data).__name__}}"

            ''')
        else:
            test_code = textwrap.dedent(f'''\
                def {fn_name}(api):
                    """Integration test: {method} {url}"""
                    resp = api.{method.lower()}(f"{{BASE_URL}}{url}")
                    assert resp.status_code in (200, 204, 400), f"Unexpected {{resp.status_code}}: {{resp.text[:200]}}"

            ''')

        code_blocks.append(test_code)
        tests.append({
            "name": fn_name,
            "type": "api_endpoint",
            "method": method,
            "url": url,
            "source_file": ep["file"],
        })

    # ── Wire Health Tests ─────────────────────────────────────────────
    wire_test = textwrap.dedent(f'''\
        class TestWireHealth:
            """Wire connectivity health checks — verifies all discovered endpoints respond."""

            def test_wire_test_starts(self, api):
                """Verify wire-test endpoint can be triggered."""
                resp = api.post(f"{{BASE_URL}}/api/wire-test", json={{"directory": "."}})
                assert resp.status_code == 200
                data = resp.json()
                assert data.get("status") == "started"

            def test_wire_progress_responds(self, api):
                """Verify wire-progress returns valid status."""
                resp = api.get(f"{{BASE_URL}}/api/wire-progress")
                assert resp.status_code == 200
                data = resp.json()
                assert "status" in data

            def test_connection_analysis(self, api):
                """Verify connection-test returns orphan analysis."""
                resp = api.post(f"{{BASE_URL}}/api/connection-test", json={{"directory": "."}})
                assert resp.status_code == 200
                data = resp.json()
                assert "wired" in data or "summary" in data

    ''')
    code_blocks.append(wire_test)
    tests.append({"name": "TestWireHealth", "type": "wire_health"})

    # ── Cross-Module Dependency Tests ─────────────────────────────────
    if cross_imports:
        dep_header = textwrap.dedent('''\
            class TestCrossModuleDeps:
                """Cross-module import contract tests — verify imported symbols exist."""

        ''')
        code_blocks.append(dep_header)

        seen = set()
        for imp in cross_imports[:20]:  # Cap at 20 to avoid huge files
            mod = imp["imports_module"]
            for name in imp["names"][:5]:
                key = f"{mod}.{name}"
                if key in seen:
                    continue
                seen.add(key)
                safe_mod = mod.replace(".", "_")
                fn_name = f"    def test_import_{safe_mod}_{name}(self):\n"
                test = fn_name + textwrap.dedent(f'''\
                            """Verify {mod}.{name} is importable."""
                            try:
                                mod = __import__("{mod}", fromlist=["{name}"])
                                assert hasattr(mod, "{name}"), "{mod} has no attribute {name}"
                            except ImportError:
                                pytest.skip("{mod} not installed")

                ''')
                code_blocks.append(test)
        tests.append({"name": "TestCrossModuleDeps", "type": "cross_module"})

    full_code = "\n".join(code_blocks)

    return {
        "test_code": full_code,
        "tests_generated": len(tests),
        "tests": tests,
        "endpoints_found": len(endpoints),
        "modules_found": len(modules),
        "cross_imports_found": len(cross_imports),
        "output_suggestion": os.path.join(root, "tests", "test_integration_xray.py"),
    }
