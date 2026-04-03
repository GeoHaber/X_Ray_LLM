"""
Component Coverage Map — Maps which components/endpoints are tested and which aren't.
Overlays test coverage onto the connection graph.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from analyzers._shared import _SKIP_DIRS


def _discover_test_targets(directory: str) -> dict[str, set[str]]:
    """
    Discover what each test file tests.
    Returns: {test_file: {set of tested identifiers (URLs, functions, classes)}}
    """
    targets: dict[str, set[str]] = {}

    # Patterns for what tests target
    url_rx = re.compile(r"""['"](/api/[^'"]+)['"]""")
    func_call_rx = re.compile(r"""(\w+)\s*\(""")
    import_rx = re.compile(r"""from\s+(\S+)\s+import\s+(.+)""")

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            is_test = fn.startswith("test_") or fn.endswith("_test.py") or fn.endswith(".test.js")
            is_test = is_test or fn.endswith(".test.ts") or fn.endswith(".test.tsx")
            is_test = is_test or fn.endswith(".spec.js") or fn.endswith(".spec.ts")
            if not is_test:
                continue

            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, directory)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            found = set()
            # URLs tested
            for m in url_rx.finditer(content):
                found.add(m.group(1))

            # Imports from project modules
            for m in import_rx.finditer(content):
                module = m.group(1)
                names = [n.strip().split(" as ")[0].strip()
                         for n in m.group(2).split(",")]
                for name in names:
                    found.add(f"{module}.{name}")
                    found.add(name)

            if found:
                targets[rel] = found

    return targets


def _discover_api_endpoints(directory: str) -> list[dict]:
    """Discover all API endpoints."""
    endpoints = []
    rx = [
        re.compile(r"""@\w+\.\s*(?:route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
        re.compile(r"""(?:app|router)\.\s*(?:get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
    ]
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".ts")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        for pat in rx:
                            for m in pat.finditer(line):
                                endpoints.append({
                                    "url": m.group(1),
                                    "file": os.path.relpath(fp, directory),
                                    "line": i,
                                })
            except OSError:
                continue
    return endpoints


def _discover_functions(directory: str) -> list[dict]:
    """Discover public Python functions."""
    functions = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fp)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_"):
                            functions.append({
                                "name": node.name,
                                "file": os.path.relpath(fp, directory),
                                "line": node.lineno,
                            })
            except (OSError, SyntaxError):
                continue
    return functions


def _discover_components(directory: str) -> list[dict]:
    """Discover React/UI components."""
    components = []
    comp_rx = re.compile(
        r"""(?:export\s+(?:default\s+)?)?(?:function|const|class)\s+([A-Z]\w+)"""
    )
    fe_exts = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in fe_exts:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        m = comp_rx.match(line.strip())
                        if m:
                            components.append({
                                "name": m.group(1),
                                "file": os.path.relpath(fp, directory),
                                "line": i,
                            })
            except OSError:
                continue
    return components


def compute_coverage_map(directory: str) -> dict:
    """
    Build a component/endpoint coverage map showing what is tested and what isn't.

    Returns:
    - tested_endpoints: API endpoints that have test coverage
    - untested_endpoints: API endpoints with NO test coverage
    - tested_functions: functions referenced by tests
    - untested_functions: public functions with no test coverage
    - tested_components: UI components with test coverage
    - untested_components: UI components with no test coverage
    - coverage_score: overall coverage percentage
    """
    root = str(Path(directory).resolve())

    test_targets = _discover_test_targets(root)
    endpoints = _discover_api_endpoints(root)
    functions = _discover_functions(root)
    components = _discover_components(root)

    # Flatten all test targets
    all_tested: set[str] = set()
    for targets in test_targets.values():
        all_tested.update(targets)

    # ── Endpoint Coverage ─────────────────────────────────────────────
    tested_eps = []
    untested_eps = []
    for ep in endpoints:
        url = ep["url"]
        if url in all_tested or url.rstrip("/") in all_tested:
            tested_eps.append(ep)
        else:
            untested_eps.append(ep)

    # ── Function Coverage ─────────────────────────────────────────────
    tested_fns = []
    untested_fns = []
    for fn in functions:
        name = fn["name"]
        module = fn["file"].replace(os.sep, ".").replace(".py", "")
        if name in all_tested or f"{module}.{name}" in all_tested:
            tested_fns.append(fn)
        else:
            untested_fns.append(fn)

    # ── Component Coverage ────────────────────────────────────────────
    tested_comps = []
    untested_comps = []
    for comp in components:
        if comp["name"] in all_tested:
            tested_comps.append(comp)
        else:
            untested_comps.append(comp)

    # ── Coverage Score ────────────────────────────────────────────────
    total = len(endpoints) + len(functions) + len(components)
    covered = len(tested_eps) + len(tested_fns) + len(tested_comps)
    score = int(100 * covered / total) if total else 100

    return {
        "tested_endpoints": tested_eps,
        "untested_endpoints": untested_eps[:100],
        "tested_functions": tested_fns[:200],
        "untested_functions": untested_fns[:200],
        "tested_components": tested_comps,
        "untested_components": untested_comps[:100],
        "test_files": list(test_targets.keys()),
        "summary": {
            "total_endpoints": len(endpoints),
            "tested_endpoints": len(tested_eps),
            "untested_endpoints": len(untested_eps),
            "total_functions": len(functions),
            "tested_functions": len(tested_fns),
            "untested_functions": len(untested_fns),
            "total_components": len(components),
            "tested_components": len(tested_comps),
            "untested_components": len(untested_comps),
            "coverage_score": score,
            "test_file_count": len(test_targets),
        },
    }
