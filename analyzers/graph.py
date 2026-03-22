"""
X-Ray LLM — Graph analysis: circular calls, coupling metrics, unused imports.
"""

import ast
import logging
from collections import defaultdict

from analyzers._shared import _fwd, _safe_parse, _walk_py


def detect_circular_calls(directory: str) -> dict:
    """Detect circular call chains at the FUNCTION level (macaroni code).
    Inspired by CodeGraphContext's call-chain analysis.
    A->B->C->A is a circular call chain that makes code hard to reason about."""
    # Build function-level call graph
    funcs = {}  # key -> {name, file, line, calls: [callee_name]}
    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = f"{_fwd(rel)}::{node.name}"
            callees = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        callees.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        callees.add(child.func.attr)
            callees.discard(node.name)  # exclude direct recursion (separate concern)
            funcs[key] = {"name": node.name, "file": _fwd(rel), "line": node.lineno, "calls": list(callees)}

    # Resolve name -> keys
    name_to_keys = defaultdict(list)
    for key, data in funcs.items():
        name_to_keys[data["name"]].append(key)

    # Build adjacency (key -> set of keys)
    adj = defaultdict(set)
    for key, data in funcs.items():
        for callee_name in data["calls"]:
            for ck in name_to_keys.get(callee_name, []):
                if ck != key:
                    adj[key].add(ck)

    # Detect direct recursion
    recursive = []
    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    cname = None
                    if isinstance(child.func, ast.Name):
                        cname = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        cname = child.func.attr
                    if cname == node.name:
                        recursive.append(
                            {
                                "function": node.name,
                                "file": _fwd(rel),
                                "line": node.lineno,
                            }
                        )
                        break

    # Find cycles using DFS (Johnson's simplified — cap at reasonable size)
    cycles = []
    visited_global = set()

    def _find_cycles(start, current, path, on_stack):
        if len(cycles) >= 50:
            return
        on_stack.add(current)
        path.append(current)
        for nb in adj.get(current, set()):
            if nb == start and len(path) >= 2:
                cycle = [funcs[k]["name"] for k in path] + [funcs[start]["name"]]
                files = list({funcs[k]["file"] for k in path})
                cycles.append(
                    {
                        "chain": cycle,
                        "length": len(cycle) - 1,
                        "files": files,
                        "functions": [
                            {
                                "name": funcs[k]["name"],
                                "file": funcs[k]["file"],
                                "line": funcs[k]["line"],
                            }
                            for k in path
                        ],
                    }
                )
            elif nb not in on_stack and nb not in visited_global:
                _find_cycles(start, nb, path, on_stack)
        path.pop()
        on_stack.discard(current)

    for key in list(funcs.keys()):
        if key not in visited_global:
            _find_cycles(key, key, [], set())
            visited_global.add(key)

    # Deduplicate cycles (same set of functions = same cycle)
    seen_sets = set()
    unique_cycles = []
    for c in cycles:
        fset = frozenset(c["chain"][:-1])
        if fset not in seen_sets:
            seen_sets.add(fset)
            unique_cycles.append(c)

    unique_cycles.sort(key=lambda x: (-x["length"], x["chain"][0]))

    # Hub functions: high fan-in AND fan-out (coordination smell / spaghetti centers)
    fan_in = defaultdict(int)
    fan_out = defaultdict(int)
    for key, nbs in adj.items():
        fan_out[key] = len(nbs)
        for nb in nbs:
            fan_in[nb] += 1

    hubs = []
    for key, data in funcs.items():
        fi = fan_in.get(key, 0)
        fo = fan_out.get(key, 0)
        if fi >= 3 and fo >= 3:
            hubs.append(
                {
                    "name": data["name"],
                    "file": data["file"],
                    "line": data["line"],
                    "fan_in": fi,
                    "fan_out": fo,
                    "score": fi * fo,
                }
            )
    hubs.sort(key=lambda x: -x["score"])

    return {
        "circular_calls": unique_cycles[:30],
        "total_cycles": len(unique_cycles),
        "recursive_functions": recursive[:20],
        "total_recursive": len(recursive),
        "hub_functions": hubs[:20],
        "total_hubs": len(hubs),
        "total_functions": len(funcs),
        "total_edges": sum(len(v) for v in adj.values()),
    }


def compute_coupling_metrics(directory: str) -> dict:
    """Compute coupling & cohesion metrics per module — inspired by CGC graph analysis.
    Afferent coupling (Ca) = how many modules depend on this one (fan-in).
    Efferent coupling (Ce) = how many modules this one depends on (fan-out).
    Instability (I) = Ce / (Ca + Ce) — 0 = stable, 1 = unstable.
    High Ca + high Ce = god module (tangled). High I + many dependents = fragile."""
    modules = {}  # mod_name -> {file, loc, imports: set, imported_by: set, funcs, classes}
    local_mods = set()

    for fpath, rel in _walk_py(directory):
        mod = _fwd(rel).replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        local_mods.add(mod)
        loc = 0
        func_count = 0
        class_count = 0
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                loc = sum(1 for ln in lines if ln.strip())
        except OSError as e:
            logging.debug("Skipped coupling metrics for %s: %s", fpath, e)
        tree = _safe_parse(fpath)
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_count += 1
                elif isinstance(node, ast.ClassDef):
                    class_count += 1
        modules[mod] = {
            "name": mod,
            "file": _fwd(rel),
            "loc": loc,
            "imports": set(),
            "imported_by": set(),
            "func_count": func_count,
            "class_count": class_count,
        }

    # Resolve imports
    for fpath, rel in _walk_py(directory):
        mod = _fwd(rel).replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not (line.startswith("import ") or line.startswith("from ")):
                        continue
                    parts = line.split()
                    target = None
                    if parts[0] == "import" or len(parts) >= 2:
                        target = parts[1].split(".")[0]
                    if target and target in local_mods and target != mod:
                        modules[mod]["imports"].add(target)
                        if target in modules:
                            modules[target]["imported_by"].add(mod)
        except (OSError, UnicodeDecodeError):
            continue

    # Compute metrics
    results = []
    for mod, data in modules.items():
        ca = len(data["imported_by"])  # afferent coupling
        ce = len(data["imports"])  # efferent coupling
        instability = round(ce / (ca + ce), 2) if (ca + ce) > 0 else 0.5

        # Cohesion estimate: ratio of internal function calls vs external dependencies
        # Low ratio = low cohesion (module does unrelated things)
        cohesion = "high" if ce <= 2 and data["func_count"] <= 8 else "medium" if ce <= 5 else "low"

        health = "healthy"
        if ca >= 5 and ce >= 5:
            health = "god_module"
        elif instability > 0.8 and ca >= 3:
            health = "fragile"
        elif ca == 0 and ce == 0 and data["loc"] > 20:
            health = "isolated"
        elif ce > 8:
            health = "dependent"

        results.append(
            {
                "module": mod,
                "file": data["file"],
                "loc": data["loc"],
                "afferent_coupling": ca,
                "efferent_coupling": ce,
                "instability": instability,
                "cohesion": cohesion,
                "health": health,
                "func_count": data["func_count"],
                "class_count": data["class_count"],
                "imports": sorted(data["imports"]),
                "imported_by": sorted(data["imported_by"]),
            }
        )

    results.sort(key=lambda x: -(x["afferent_coupling"] + x["efferent_coupling"]))

    # Summary
    health_counts = defaultdict(int)
    for r in results:
        health_counts[r["health"]] += 1

    avg_instability = round(sum(r["instability"] for r in results) / max(len(results), 1), 2)

    return {
        "modules": results,
        "total_modules": len(results),
        "health_summary": dict(health_counts),
        "avg_instability": avg_instability,
        "god_modules": [r for r in results if r["health"] == "god_module"][:10],
        "fragile_modules": [r for r in results if r["health"] == "fragile"][:10],
        "isolated_modules": [r for r in results if r["health"] == "isolated"][:10],
    }


def detect_unused_imports(directory: str) -> dict:
    """AST-based unused import detection — clean code starts with clean imports."""
    issues = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        # Collect all imported names and their line numbers
        imported = {}  # name -> line
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split(".")[0]
                    imported[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("__"):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname if alias.asname else alias.name
                    imported[name] = node.lineno

        if not imported:
            continue

        # Collect all Name references in the file (excluding import nodes)
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # For chained attrs like `os.path`, collect the root
                root = node
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    used_names.add(root.id)
            # Check string annotations (TYPE_CHECKING style)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for imp_name in imported:
                    if imp_name in node.value:
                        used_names.add(imp_name)

        # Determine unused
        for name, line in imported.items():
            if name not in used_names and name != "_":
                issues.append(
                    {
                        "file": _fwd(rel),
                        "line": line,
                        "import_name": name,
                        "severity": "LOW",
                    }
                )

    issues.sort(key=lambda x: (x["file"], x["line"]))

    # Group by file for summary
    by_file = defaultdict(int)
    for i in issues:
        by_file[i["file"]] += 1

    return {
        "unused_imports": issues,
        "total_unused": len(issues),
        "files_with_unused": len(by_file),
        "by_file": dict(sorted(by_file.items(), key=lambda x: -x[1])[:20]),
    }
