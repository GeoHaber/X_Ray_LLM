"""
X-Ray LLM — PM Dashboard: Risk Heatmap, Module Cards, Confidence Meter,
Sprint Batches, Architecture Map, Call Graph, Project Review.
"""

import ast
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

from analyzers._shared import _fwd, _safe_parse, _walk_py
from analyzers.detection import generate_test_stubs
from analyzers.format_check import check_format
from analyzers.health import check_project_health, check_release_readiness
from analyzers.smells import detect_code_smells, detect_dead_functions, detect_duplicates


def compute_risk_heatmap(directory: str, findings: list | None = None) -> dict:
    """Composite risk score per file — combines scanner findings, smells, duplicates, git churn."""
    smells_result = detect_code_smells(directory)
    dups_result = detect_duplicates(directory)

    # Git churn (best-effort, skip if no git)
    churn_map = {}
    try:
        proc = subprocess.run(
            ["git", "log", "--since=90.days", "--name-only", "--pretty=format:"],
            capture_output=True,
            text=True,
            cwd=directory,
            timeout=15,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().split("\n"):
                line = line.strip()
                if line:
                    churn_map[line] = churn_map.get(line, 0) + 1
    except (subprocess.SubprocessError, OSError):
        pass

    # LOC per Python file
    loc_map = {}
    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                loc_map[rel] = sum(1 for ln in f if ln.strip())
        except OSError as e:
            logging.debug("Skipped LOC count for %s: %s", fpath, e)

    # Accumulate per-file signals
    risk = defaultdict(lambda: {"security": 0, "quality": 0, "smells": 0, "churn": 0, "duplicates": 0})

    for f in findings or []:
        rel = f.get("file", "")
        w = {"HIGH": 5, "MEDIUM": 2, "LOW": 0.5}.get(f.get("severity", ""), 1)
        if f.get("rule_id", "").startswith("SEC-"):
            risk[rel]["security"] += w
        else:
            risk[rel]["quality"] += w

    for s in smells_result.get("smells", []):
        risk[s["file"]]["smells"] += {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(s.get("severity", ""), 1)

    for g in dups_result.get("duplicate_groups", []):
        for loc in g.get("locations", []):
            risk[loc["file"]]["duplicates"] += 1

    for path, churn in churn_map.items():
        risk[_fwd(path)]["churn"] = churn

    # Composite score per file
    all_files = set(list(risk.keys()) + list(loc_map.keys()))
    files = []
    for rel in all_files:
        r = risk.get(rel, {"security": 0, "quality": 0, "smells": 0, "churn": 0, "duplicates": 0})
        score = r["security"] * 5 + r["quality"] * 2 + r["smells"] * 2 + r["churn"] * 3 + r["duplicates"] * 1
        loc = loc_map.get(rel, 0)
        if score > 0 or loc > 0:
            files.append({"file": rel, "risk_score": round(score, 1), "loc": loc, **r})

    files.sort(key=lambda x: -x["risk_score"])
    max_risk = max((f["risk_score"] for f in files), default=1) or 1

    return {
        "files": files[:300],
        "total_files": len(files),
        "max_risk": round(max_risk, 1),
        "high_risk": sum(1 for f in files if f["risk_score"] > max_risk * 0.6),
        "medium_risk": sum(1 for f in files if max_risk * 0.2 < f["risk_score"] <= max_risk * 0.6),
        "low_risk": sum(1 for f in files if f["risk_score"] <= max_risk * 0.2),
    }


def compute_module_cards(directory: str, findings: list | None = None) -> dict:
    """Per-directory grade cards — module-level quality breakdown."""
    smells_result = detect_code_smells(directory)
    test_result = generate_test_stubs(directory)

    dirs = defaultdict(
        lambda: {"high": 0, "medium": 0, "low": 0, "smells": 0, "files": set(), "loc": 0, "tested": 0, "untested": 0}
    )

    for f in findings or []:
        rel = f.get("file", "")
        d = rel.rsplit("/", 1)[0] if "/" in rel else "."
        dirs[d]["files"].add(rel)
        sev = f.get("severity", "LOW").lower()
        if sev in ("high", "medium", "low"):
            dirs[d][sev] += 1

    for s in smells_result.get("smells", []):
        d = s["file"].rsplit("/", 1)[0] if "/" in s["file"] else "."
        dirs[d]["smells"] += 1
        dirs[d]["files"].add(s["file"])

    for stub in test_result.get("stubs", []):
        d = stub["file"].rsplit("/", 1)[0] if "/" in stub["file"] else "."
        dirs[d]["untested"] += 1

    for fpath, rel in _walk_py(directory):
        d = rel.rsplit("/", 1)[0] if "/" in rel else "."
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                dirs[d]["loc"] += sum(1 for ln in f if ln.strip())
        except OSError as e:
            logging.debug("Skipped directory LOC for %s: %s", fpath, e)
        dirs[d]["files"].add(rel)

    def _grade(h, m, low, fc):
        if fc == 0:
            return "?", 0
        weighted = h * 5 + m * 2 + low * 0.5
        per100 = (weighted / max(fc, 1)) * 100
        if per100 <= 5:
            return "A", max(0, int(100 - per100))
        if per100 <= 15:
            return "B", max(0, int(100 - per100 * 0.8))
        if per100 <= 40:
            return "C", max(0, int(100 - per100 * 0.6))
        if per100 <= 80:
            return "D", max(20, int(100 - per100 * 0.5))
        return "F", max(5, int(100 - per100 * 0.4))

    modules = []
    for d, data in dirs.items():
        fc = len(data["files"])
        letter, score = _grade(data["high"], data["medium"], data["low"], fc)
        modules.append(
            {
                "module": d,
                "grade": letter,
                "score": score,
                "files": fc,
                "loc": data["loc"],
                "high": data["high"],
                "medium": data["medium"],
                "low": data["low"],
                "smells": data["smells"],
                "untested": data["untested"],
            }
        )

    modules.sort(key=lambda x: x["score"])
    return {"modules": modules, "total_modules": len(modules)}


def compute_architecture_map(directory: str) -> dict:
    """Enhanced import graph with layers, circular deps, god modules, clusters."""
    nodes = {}
    edges = []
    seen_edges = set()
    local_modules = set()

    for fpath, rel in _walk_py(directory):
        mod = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        local_modules.add(mod)
        top_dir = rel.split("/")[0] if "/" in rel else "."
        layer = "test" if "test" in rel.lower() else ("app" if top_dir == "." else "lib")
        loc = 0
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                loc = sum(1 for ln in f if ln.strip())
        except OSError as e:
            logging.debug("Skipped architecture LOC for %s: %s", fpath, e)
        nodes[mod] = {
            "id": mod,
            "label": mod.split(".")[-1],
            "file": rel,
            "external": False,
            "layer": layer,
            "imports_count": 0,
            "loc": loc,
            "dir": top_dir,
        }

    for fpath, rel in _walk_py(directory):
        mod = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
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
                    if not target or target.startswith(".") or target == ".":
                        continue
                    if target not in nodes:
                        nodes[target] = {
                            "id": target,
                            "label": target,
                            "external": True,
                            "layer": "external",
                            "imports_count": 0,
                            "loc": 0,
                            "dir": "external",
                        }
                    if mod in nodes:
                        nodes[mod]["imports_count"] += 1
                    ek = f"{mod}->{target}"
                    if ek not in seen_edges:
                        seen_edges.add(ek)
                        edges.append({"from": mod, "to": target})
        except (OSError, UnicodeDecodeError):
            continue

    # Circular dependency detection (DFS on local modules)
    adj = defaultdict(set)
    for e in edges:
        if e["from"] in local_modules and e["to"] in local_modules:
            adj[e["from"]].add(e["to"])

    circular_deps = []
    visited = set()

    def _dfs(node, path, on_stack):
        visited.add(node)
        on_stack.add(node)
        path.append(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                _dfs(nb, path, on_stack)
            elif nb in on_stack and nb in path:
                idx = path.index(nb)
                cycle = [*path[idx:], nb]
                if len(cycle) <= 10:
                    circular_deps.append(cycle)
        path.pop()
        on_stack.discard(node)

    for m in local_modules:
        if m not in visited:
            _dfs(m, [], set())

    # God modules (many inbound local deps)
    local_inbound = defaultdict(int)
    for e in edges:
        if e["from"] in local_modules and e["to"] in local_modules:
            local_inbound[e["to"]] += 1
    god_modules = sorted(
        [
            {"module": m, "dependents": c, "loc": nodes.get(m, {}).get("loc", 0)}
            for m, c in local_inbound.items()
            if c >= 5
        ],
        key=lambda x: -x["dependents"],
    )

    clusters = defaultdict(list)
    for n in nodes.values():
        clusters[n.get("dir", ".")].append(n["id"])

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "layers": {
            "test": [n["id"] for n in nodes.values() if n.get("layer") == "test"],
            "app": [n["id"] for n in nodes.values() if n.get("layer") == "app"],
            "lib": [n["id"] for n in nodes.values() if n.get("layer") == "lib"],
            "external": [n["id"] for n in nodes.values() if n.get("layer") == "external"],
        },
        "circular_deps": circular_deps[:20],
        "god_modules": god_modules[:10],
        "clusters": dict(clusters),
    }


def compute_call_graph(directory: str) -> dict:
    """AST-based call graph: who calls whom, entry points, leaf functions."""
    functions = {}
    calls = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fname = node.name
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            key = f"{_fwd(rel)}::{fname}"

            is_entry = fname == "main"
            for dec in node.decorator_list:
                dec_name = None
                if isinstance(dec, ast.Attribute):
                    dec_name = dec.attr
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    dec_name = dec.func.attr
                if dec_name in ("route", "get", "post", "put", "delete", "command", "task", "cli"):
                    is_entry = True

            fn_calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = None
                    if isinstance(child.func, ast.Name):
                        callee = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        callee = child.func.attr
                    if callee and callee != fname:
                        fn_calls.append(callee)
                        calls.append({"caller": key, "callee_name": callee})

            functions[key] = {
                "name": fname,
                "file": _fwd(rel),
                "line": node.lineno,
                "lines": lines,
                "is_entry": is_entry,
                "calls": fn_calls,
                "called_by": [],
            }

    # Resolve callee names to full keys
    name_to_keys = defaultdict(list)
    for key, data in functions.items():
        name_to_keys[data["name"]].append(key)

    resolved_edges = []
    for call in calls:
        for ck in name_to_keys.get(call["callee_name"], []):
            resolved_edges.append({"from": call["caller"], "to": ck})
            functions[ck]["called_by"].append(call["caller"])

    entries = [k for k, v in functions.items() if v["is_entry"] or not v["called_by"]]
    leaves = [
        k
        for k, v in functions.items()
        if not any(name_to_keys.get(c) for c in v["calls"]) and not v["name"].startswith("_")
    ]

    nodes = [
        {
            "id": k,
            "name": d["name"],
            "file": d["file"],
            "line": d["line"],
            "lines": d["lines"],
            "is_entry": d["is_entry"],
            "call_count": len(d["calls"]),
            "caller_count": len(d["called_by"]),
        }
        for k, d in (functions or {}).items()
    ]

    return {
        "nodes": nodes[:500],
        "edges": resolved_edges[:2000],
        "entries": entries[:50],
        "leaves": leaves[:50],
        "total_functions": len(functions),
        "total_edges": len(resolved_edges),
    }


def compute_confidence_meter(directory: str, findings: list | None = None) -> dict:
    """Release confidence synthesis — one number + narrative that synthesizes everything."""
    health = check_project_health(directory)
    release = check_release_readiness(directory)
    dead = detect_dead_functions(directory)
    test = generate_test_stubs(directory)
    smells = detect_code_smells(directory)
    arch = compute_architecture_map(directory)

    checks = []
    score = 0
    max_score = 0

    def add(name, passed, weight, detail=""):
        nonlocal score, max_score
        max_score += weight
        if passed:
            score += weight
        checks.append({"name": name, "passed": passed, "weight": weight, "detail": detail})

    high_sec = sum(
        1 for f in (findings or []) if f.get("severity") == "HIGH" and f.get("rule_id", "").startswith("SEC-")
    )
    add("No critical security issues", high_sec == 0, 20, f"{high_sec} HIGH security findings" if high_sec else "Clean")

    high_total = sum(1 for f in (findings or []) if f.get("severity") == "HIGH")
    add("No HIGH-severity findings", high_total == 0, 10, f"{high_total} HIGH findings" if high_total else "Clean")

    add("Project health >= 70%", health.get("score", 0) >= 70, 10, f"Health: {health.get('score', 0)}%")

    cov = test.get("coverage_pct", 0)
    add("Test coverage >= 50%", cov >= 50, 15, f"Coverage: {cov}%")

    dc = dead.get("total_dead", 0)
    add("Minimal dead code (< 5)", dc < 5, 5, f"{dc} dead functions")

    hs = sum(1 for s in smells.get("smells", []) if s.get("severity") == "HIGH")
    add("No HIGH code smells", hs == 0, 10, f"{hs} HIGH smells" if hs else "Clean")

    circ = arch.get("circular_deps", [])
    add("No circular dependencies", len(circ) == 0, 10, f"{len(circ)} circular deps" if circ else "Clean")

    gods = arch.get("god_modules", [])
    add("No god modules (>=5 dependents)", len(gods) == 0, 5, f"{len(gods)} god modules" if gods else "Clean")

    add("Release readiness >= 70%", release.get("score", 0) >= 70, 10, f"Readiness: {release.get('score', 0)}%")

    try:
        fmt = check_format(directory)
        add(
            "Code formatting passes",
            fmt.get("all_formatted", False),
            5,
            f"{fmt.get('needs_format', 0)} files need formatting" if not fmt.get("all_formatted") else "Clean",
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    confidence = round(score / max(max_score, 1) * 100)

    top_risks = sorted(
        [{"name": c["name"], "detail": c["detail"], "weight": c["weight"]} for c in checks if not c["passed"]],
        key=lambda x: -x["weight"],
    )

    if confidence >= 80:
        rec = "Good to ship. Minor items can be addressed post-release."
    elif confidence >= 60:
        rec = "Address top risks before release. Focus on highest-weight items first."
    elif confidence >= 40:
        rec = "Significant work needed. Prioritize security and test coverage."
    else:
        rec = "Not ready for release. Major structural issues need attention."

    return {
        "confidence": confidence,
        "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
        "top_risks": top_risks[:5],
        "recommendation": rec,
    }


def compute_sprint_batches(findings: list | None = None, smells: list | None = None) -> dict:
    """Group all issues into sprint-sized action batches sorted by ROI (impact/effort)."""
    items = []

    for f in findings or []:
        rid = f.get("rule_id", "")
        sev = f.get("severity", "LOW")
        mins = 15 if rid.startswith("SEC-") else 5 if rid.startswith("QUAL-") else 10
        impact = {"HIGH": 10, "MEDIUM": 4, "LOW": 1}.get(sev, 2)
        items.append(
            {
                "type": "finding",
                "id": rid,
                "file": f.get("file", ""),
                "line": f.get("line", 0),
                "severity": sev,
                "description": f.get("description", ""),
                "fix_hint": f.get("fix_hint", ""),
                "minutes": mins,
                "impact": impact,
                "roi": round(impact / max(mins, 1), 2),
            }
        )

    for s in smells or []:
        sev = s.get("severity", "LOW")
        impact = {"HIGH": 8, "MEDIUM": 3, "LOW": 1}.get(sev, 2)
        items.append(
            {
                "type": "smell",
                "id": s.get("smell", ""),
                "file": s.get("file", ""),
                "line": s.get("line", 0),
                "severity": sev,
                "description": s.get("description", ""),
                "fix_hint": "Refactor: " + s.get("smell", "").replace("_", " "),
                "minutes": 15,
                "impact": impact,
                "roi": round(impact / 15, 2),
            }
        )

    items.sort(key=lambda x: -x["roi"])

    batches = [
        {"name": "Quick Wins (< 4h)", "max_min": 240, "items": [], "total_min": 0},
        {"name": "Sprint 1 (4-8h)", "max_min": 480, "items": [], "total_min": 0},
        {"name": "Sprint 2 (8-16h)", "max_min": 960, "items": [], "total_min": 0},
        {"name": "Backlog (16h+)", "max_min": 999999, "items": [], "total_min": 0},
    ]

    running = 0
    for item in items:
        running += item["minutes"]
        idx = 0 if running <= 240 else 1 if running <= 480 else 2 if running <= 960 else 3
        batches[idx]["items"].append(item)
        batches[idx]["total_min"] += item["minutes"]

    cum = 0
    total = len(items)
    for b in batches:
        cum += len(b["items"])
        b["pct_resolved"] = round(cum / max(total, 1) * 100)
        b["total_hours"] = round(b["total_min"] / 60, 1)
        b["items"] = b["items"][:100]  # cap for transport
        del b["max_min"]

    return {
        "batches": batches,
        "total_items": total,
        "total_hours": round(sum(b["total_min"] for b in batches) / 60, 1),
    }


def compute_project_review(
    directory: str,
    findings: list | None = None,
    summary: dict | None = None,
    files_scanned: int = 0,
    smells: list | None = None,
    dead_functions: list | None = None,
    health: dict | None = None,
    satd: dict | None = None,
    duplicates: dict | None = None,
) -> dict:
    """Generate a comprehensive PM-style project review with grades, charts data, and recommendations."""
    findings = findings or []
    smells = smells or []
    dead_functions = dead_functions or []
    dir_path = Path(directory).resolve()

    # ── Severity breakdown ──
    sev_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        sev = f.get("severity", "LOW")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    total = sum(sev_counts.values())

    # ── Category breakdown ──
    cat_counts = {}
    for f in findings:
        rid = f.get("rule_id", "UNKNOWN")
        cat = rid.split("-")[0] if "-" in rid else rid
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # ── Score ──
    deductions = sev_counts["HIGH"] * 5 + sev_counts["MEDIUM"] * 2 + sev_counts["LOW"] * 0.5
    score = max(0, min(100, round(100 - deductions)))
    letter = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    # ── Top hotspot files ──
    file_issues = {}
    for f in findings:
        fp = f.get("file", "unknown")
        file_issues.setdefault(fp, {"high": 0, "medium": 0, "low": 0, "total": 0})
        sev = f.get("severity", "LOW").lower()
        file_issues[fp][sev] = file_issues[fp].get(sev, 0) + 1
        file_issues[fp]["total"] += 1
    hotspots = sorted(file_issues.items(), key=lambda x: (-x[1]["high"], -x[1]["total"]))[:15]

    # ── Recommendations ──
    must_do = []
    should_do = []
    nice_to_have = []

    if sev_counts["HIGH"] > 0:
        must_do.append(
            {
                "title": f"Fix {sev_counts['HIGH']} HIGH severity issues",
                "reason": "High severity findings indicate security vulnerabilities or critical reliability flaws that can lead to data breaches or system failures.",
                "effort": f"{sev_counts['HIGH'] * 15} min",
                "impact": "Critical",
            }
        )

    sec_count = sum(1 for f in findings if f.get("rule_id", "").startswith("SEC-"))
    if sec_count > 0:
        must_do.append(
            {
                "title": f"Address {sec_count} security findings",
                "reason": "Security issues must be resolved before any production release to prevent exploitation.",
                "effort": f"{sec_count * 20} min",
                "impact": "Critical",
            }
        )

    if sev_counts["MEDIUM"] > 5:
        should_do.append(
            {
                "title": f"Reduce {sev_counts['MEDIUM']} MEDIUM severity issues",
                "reason": "Medium issues degrade code quality and increase maintenance burden over time.",
                "effort": f"{sev_counts['MEDIUM'] * 10} min",
                "impact": "High",
            }
        )

    if len(smells) > 5:
        should_do.append(
            {
                "title": f"Refactor {len(smells)} code smells",
                "reason": "Code smells increase complexity, make debugging harder, and slow down new feature development.",
                "effort": f"{len(smells) * 15} min",
                "impact": "Medium",
            }
        )

    if len(dead_functions) > 3:
        should_do.append(
            {
                "title": f"Remove {len(dead_functions)} dead functions",
                "reason": "Dead code confuses developers and increases cognitive load without providing value.",
                "effort": f"{len(dead_functions) * 5} min",
                "impact": "Medium",
            }
        )

    if duplicates and duplicates.get("total_groups", 0) > 0:
        nice_to_have.append(
            {
                "title": f"Consolidate {duplicates.get('total_groups', 0)} duplicate code groups",
                "reason": "Duplicate code increases maintenance burden and risk of inconsistent bug fixes.",
                "effort": f"{duplicates.get('total_groups', 0) * 20} min",
                "impact": "Medium",
            }
        )

    if sev_counts["LOW"] > 10:
        nice_to_have.append(
            {
                "title": f"Clean up {sev_counts['LOW']} LOW severity items",
                "reason": "While individually minor, large numbers of low-severity issues signal declining code discipline.",
                "effort": f"{sev_counts['LOW'] * 5} min",
                "impact": "Low",
            }
        )

    # ── Health snapshot ──
    health_flags = {}
    if health:
        for k, v in health.items():
            if isinstance(v, bool):
                health_flags[k] = v

    # ── Debt summary ──
    debt_hours = satd.get("total_hours", 0) if satd else 0
    debt_items = satd.get("total_items", 0) if satd else 0

    # ── Release readiness ──
    blockers = sev_counts["HIGH"] + sec_count
    release_ready = blockers == 0 and score >= 60
    release_status = "GO" if release_ready else "NO-GO"

    # ── Estimated total fix time ──
    total_fix_min = (
        sev_counts["HIGH"] * 15
        + sev_counts["MEDIUM"] * 10
        + sev_counts["LOW"] * 5
        + len(smells) * 15
        + len(dead_functions) * 5
    )
    total_fix_hours = round(total_fix_min / 60, 1)

    return {
        "project_name": dir_path.name,
        "directory": str(dir_path),
        "files_scanned": files_scanned,
        "score": score,
        "letter": letter,
        "release_status": release_status,
        "release_ready": release_ready,
        "blockers": blockers,
        "severity": sev_counts,
        "total_findings": total,
        "categories": cat_counts,
        "hotspots": [{"file": h[0], **h[1]} for h in hotspots],
        "must_do": must_do,
        "should_do": should_do,
        "nice_to_have": nice_to_have,
        "health_flags": health_flags,
        "debt_hours": debt_hours,
        "debt_items": debt_items,
        "total_fix_hours": total_fix_hours,
        "smells_count": len(smells),
        "dead_count": len(dead_functions),
        "duplicates_count": duplicates.get("total_groups", 0) if duplicates else 0,
    }


def compute_impact_graph(directory: str, findings: list | None = None) -> dict:
    """Compute a blast-radius graph from risky files using architecture dependencies."""
    arch = compute_architecture_map(directory)
    nodes = arch.get("nodes", [])
    edges = arch.get("edges", [])
    findings = findings or []

    # Build quick lookups
    id_to_file = {n.get("id", ""): n.get("file", "") for n in nodes}
    file_to_ids = {}
    for nid, file_path in id_to_file.items():
        if not file_path:
            continue
        file_to_ids.setdefault(file_path, set()).add(nid)

    # Rank risk by file (HIGH weighted much more than LOW)
    file_risk = defaultdict(float)
    for f in findings:
        file_path = str(f.get("file", ""))
        if not file_path:
            continue
        weight = {"HIGH": 5.0, "MEDIUM": 2.0, "LOW": 0.5}.get(str(f.get("severity", "LOW")), 1.0)
        file_risk[file_path] += weight

    seed_ids = set()
    for file_path, _risk in sorted(file_risk.items(), key=lambda item: -item[1])[:8]:
        for nid in file_to_ids.get(file_path, set()):
            seed_ids.add(nid)

    # Fallback: if no findings, pick top local nodes by degree
    if not seed_ids:
        degree = defaultdict(int)
        for e in edges:
            degree[e.get("from", "")] += 1
            degree[e.get("to", "")] += 1
        for nid, _deg in sorted(degree.items(), key=lambda item: -item[1])[:5]:
            if nid:
                seed_ids.add(nid)

    # Build adjacency for a 2-hop blast radius
    out_adj = defaultdict(set)
    in_adj = defaultdict(set)
    for e in edges:
        src = e.get("from", "")
        dst = e.get("to", "")
        if not src or not dst:
            continue
        out_adj[src].add(dst)
        in_adj[dst].add(src)

    levels = {}
    frontier = list(seed_ids)
    for nid in frontier:
        levels[nid] = 0

    for depth in (1, 2):
        next_frontier = []
        for nid in frontier:
            neighbors = out_adj.get(nid, set()) | in_adj.get(nid, set())
            for nb in neighbors:
                if nb in levels:
                    continue
                levels[nb] = depth
                next_frontier.append(nb)
        frontier = next_frontier

    sub_nodes = []
    for n in nodes:
        nid = n.get("id", "")
        if nid not in levels:
            continue
        file_path = n.get("file", "")
        base_risk = file_risk.get(file_path, 0.0)
        in_deg = len(in_adj.get(nid, set()))
        out_deg = len(out_adj.get(nid, set()))
        impact = round(base_risk + (in_deg + out_deg) * (2.5 - min(levels[nid], 2)), 2)
        sub_nodes.append(
            {
                "id": nid,
                "label": n.get("label", nid),
                "file": file_path,
                "level": levels[nid],
                "is_seed": nid in seed_ids,
                "risk": round(base_risk, 2),
                "impact": impact,
                "external": bool(n.get("external", False)),
            }
        )

    sub_node_ids = {n["id"] for n in sub_nodes}
    sub_edges = [
        e
        for e in edges
        if e.get("from", "") in sub_node_ids and e.get("to", "") in sub_node_ids
    ]

    sub_nodes.sort(key=lambda n: (-n["impact"], n["id"]))

    return {
        "nodes": sub_nodes,
        "edges": sub_edges,
        "seed_count": len(seed_ids),
        "node_count": len(sub_nodes),
        "edge_count": len(sub_edges),
    }
