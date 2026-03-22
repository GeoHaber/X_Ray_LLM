"""
Git Analyzer — hotspot analysis and import graph parsing.

Extracted from ui_server.py.
"""

import logging
import os
import subprocess

from xray.constants import SKIP_DIRS as _SATD_SKIP_DIRS

logger = logging.getLogger(__name__)


def analyze_git_hotspots(directory: str, days: int = 90) -> dict:
    """Analyze git log to find frequently-changed files (hotspots)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days}.days", "--name-only",
             "--pretty=format:", "--diff-filter=ACMR"],
            capture_output=True, text=True, cwd=directory,
            timeout=30, encoding="utf-8", errors="ignore",
        )
    except FileNotFoundError:
        logger.debug("git not found for hotspot analysis")
        return {"error": "git not found. Install git to use hotspot analysis."}
    except subprocess.TimeoutExpired:
        logger.debug("git log timed out for hotspot analysis")
        return {"error": "git log timed out."}

    if result.returncode != 0:
        return {"error": f"git error: {result.stderr.strip()[:200]}"}

    skip_patterns = {
        "__pycache__", ".min.js", ".min.css",
        "package-lock.json", "uv.lock", "Cargo.lock", ".pyc",
    }
    churn: dict[str, int] = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(s in line for s in skip_patterns):
            continue
        churn[line] = churn.get(line, 0) + 1

    hotspots = []
    for path, count in sorted(churn.items(), key=lambda x: -x[1]):
        hotspots.append({"path": path, "churn": count, "priority": float(count)})

    return {"hotspots": hotspots[:100], "days": days}


def parse_imports(directory: str) -> dict:
    """Parse Python imports to build dependency graph."""
    nodes: dict[str, dict] = {}
    edges = []
    seen_edges: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SATD_SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, directory).replace("\\", "/")
            module = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
            if module not in nodes:
                nodes[module] = {
                    "id": module, "label": module.split(".")[-1],
                    "external": False, "imports_count": 0,
                }

            try:
                with open(fpath, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("import ") or line.startswith("from "):
                            parts = line.split()
                            if parts[0] == "import":
                                target = parts[1].split(".")[0]
                            elif parts[0] == "from" and len(parts) >= 2:
                                target = parts[1].split(".")[0]
                                if target == ".":
                                    continue
                            else:
                                continue
                            if not target or target.startswith("."):
                                continue
                            if target not in nodes:
                                nodes[target] = {
                                    "id": target, "label": target,
                                    "external": True, "imports_count": 0,
                                }
                            nodes[module]["imports_count"] += 1
                            edge_key = f"{module}->{target}"
                            if edge_key not in seen_edges:
                                seen_edges.add(edge_key)
                                edges.append({"from": module, "to": target})
            except (OSError, UnicodeDecodeError):
                continue

    return {"nodes": list(nodes.values()), "edges": edges}


def run_ruff(directory: str) -> dict:
    """Run ruff check --fix on the directory."""
    try:
        result = subprocess.run(
            ["ruff", "check", "--fix", directory],
            capture_output=True, text=True,
            timeout=60, encoding="utf-8", errors="ignore",
        )
    except FileNotFoundError:
        logger.debug("ruff not found for autofix")
        return {"error": "ruff not found. Install: pip install ruff"}
    except subprocess.TimeoutExpired:
        logger.debug("ruff timed out during autofix")
        return {"error": "ruff timed out."}
    except Exception as e:
        logger.debug("ruff autofix failed: %s", e)
        return {"error": f"ruff failed: {e!s}"}

    stdout = result.stdout or ""
    fixed = stdout.count("Fixed") + stdout.count("fixed")
    remaining = stdout.count("[")
    return {"fixed": fixed, "remaining": remaining, "output": stdout[:2000]}
