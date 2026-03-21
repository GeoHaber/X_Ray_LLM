#!/usr/bin/env python3
"""
X-Ray Scanner — Web UI Server

Lightweight HTTP server that provides:
  - Static file serving (ui.html)
  - REST API for scanning directories
  - Directory browsing API
  - Settings management

Usage:
  python ui_server.py              # starts on http://localhost:8077
  python ui_server.py --port 9000  # custom port
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
SCANNER_DIR = ROOT / "scanner"

# ── SATD Patterns (Self-Admitted Technical Debt) ─────────────────────────
import re as _re

_SATD_MARKERS = [
    # (regex_pattern, category, hours_estimate)
    (_re.compile(r"\b(FIXME)\b", _re.IGNORECASE), "defect", 1.0),
    (_re.compile(r"\b(BUG|BUGFIX)\b", _re.IGNORECASE), "defect", 1.0),
    (_re.compile(r"\b(XXX)\b", _re.IGNORECASE), "defect", 1.0),
    (_re.compile(r"\b(SECURITY)\b", _re.IGNORECASE), "defect", 1.0),
    (_re.compile(r"\b(HACK)\b", _re.IGNORECASE), "design", 2.0),
    (_re.compile(r"\b(WORKAROUND)\b", _re.IGNORECASE), "design", 2.0),
    (_re.compile(r"\b(KLUDGE)\b", _re.IGNORECASE), "design", 2.0),
    (_re.compile(r"\b(TODO)\b", _re.IGNORECASE), "design", 2.0),
    (_re.compile(r"\b(OPTIMIZE|PERF)\b", _re.IGNORECASE), "design", 2.0),
    (_re.compile(r"\b(TECH.?DEBT|DEBT)\b", _re.IGNORECASE), "debt", 3.0),
    (_re.compile(r"\b(NOQA|type:\s*ignore)\b", _re.IGNORECASE), "test", 0.5),
    (_re.compile(r"\b(DOCME|DOCUMENT|UNDOCUMENTED)\b", _re.IGNORECASE), "documentation", 0.25),
]

_SATD_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    "build",
    "dist",
    "_rustified",
    ".mypy_cache",
    ".pytest_cache",
    "target",
}

_COMMENT_RE = _re.compile(r"#\s*(.*)")

_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".go",
    ".rb",
    ".rs",
    ".sh",
    ".bat",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}


def scan_satd(directory: str) -> dict:
    """Scan for Self-Admitted Technical Debt markers (TODO, FIXME, HACK, etc.)."""
    items = []
    by_category = {}
    total_hours = 0.0

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SATD_SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _TEXT_EXTENSIONS:
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat, category, hours in _SATD_MARKERS:
                            m = pat.search(line)
                            if m:
                                text = line.strip()
                                # Try to extract just the comment part
                                cm = _COMMENT_RE.search(line)
                                if cm:
                                    text = cm.group(1).strip()
                                items.append(
                                    {
                                        "file": _fwd(fpath),
                                        "line": lineno,
                                        "category": category,
                                        "marker": m.group(1).upper(),
                                        "text": text[:200],
                                        "hours": hours,
                                    }
                                )
                                total_hours += hours
                                by_category.setdefault(category, []).append(items[-1])
                                break  # first match wins per line
            except (OSError, UnicodeDecodeError):
                continue

    return {
        "total_items": len(items),
        "total_hours": round(total_hours, 1),
        "items": items,
        "by_category": {k: v for k, v in by_category.items()},
    }


def analyze_git_hotspots(directory: str, days: int = 90) -> dict:
    """Analyze git log to find frequently-changed files (hotspots)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days}.days", "--name-only", "--pretty=format:", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            cwd=directory,
            timeout=30,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError:
        logger.debug("git not found for hotspot analysis")
        return {"error": "git not found. Install git to use hotspot analysis."}
    except subprocess.TimeoutExpired:
        logger.debug("git log timed out for hotspot analysis")
        return {"error": "git log timed out."}

    if result.returncode != 0:
        return {"error": f"git error: {result.stderr.strip()[:200]}"}

    skip_patterns = {"__pycache__", ".min.js", ".min.css", "package-lock.json", "uv.lock", "Cargo.lock", ".pyc"}
    churn = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(s in line for s in skip_patterns):
            continue
        churn[line] = churn.get(line, 0) + 1

    hotspots = []
    for path, count in sorted(churn.items(), key=lambda x: -x[1]):
        priority = float(count)  # simple churn-based priority
        hotspots.append({"path": path, "churn": count, "priority": priority})

    return {"hotspots": hotspots[:100], "days": days}


def parse_imports(directory: str) -> dict:
    """Parse Python imports to build dependency graph."""
    nodes = {}
    edges = []
    seen_edges = set()

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SATD_SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, directory).replace("\\", "/")
            module = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
            if module not in nodes:
                nodes[module] = {"id": module, "label": module.split(".")[-1], "external": False, "imports_count": 0}

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
                                nodes[target] = {"id": target, "label": target, "external": True, "imports_count": 0}
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
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="ignore",
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

    # Count fixes from output
    stdout = result.stdout or ""
    fixed = stdout.count("Fixed") + stdout.count("fixed")
    remaining = stdout.count("[")
    return {"fixed": fixed, "remaining": remaining, "output": stdout[:2000]}


# ── Scan Progress Tracking ───────────────────────────────────────────────

De_Bug = os.environ.get("XRAY_DEBUG", "").lower() in ("1", "true", "yes")

_abort = threading.Event()
_last_scan_result = None  # Stores full scan result for client to fetch separately
_scan_progress = None  # Initialised here to avoid NameError on early GET /api/scan-progress
# ── Wire Test Progress ──────────────────────────────────────────────────
_wire_test_results = None
_wire_test_progress = None
_wire_test_thread = None

# ── Monkey Test Progress ───────────────────────────────────────────────
_monkey_test_results = None
_monkey_test_progress = None
_monkey_test_thread = None


def _execute_monkey_tests(base_url: str):
    """Run monkey tests in background thread."""
    global _monkey_test_results, _monkey_test_progress
    import subprocess as _sp

    _monkey_test_progress = {"status": "running", "output": "", "line_count": 0}
    repo_root = str(Path(__file__).parent)
    test_file = str(Path(repo_root) / "tests" / "test_monkey.py")

    try:
        proc = _sp.Popen(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
            stdout=_sp.PIPE,
            stderr=_sp.STDOUT,
            text=True,
            cwd=repo_root,
            encoding="utf-8",
            errors="replace",
        )
        lines = []
        passed = 0
        failed = 0
        for line in proc.stdout:
            lines.append(line.rstrip())
            if " PASSED" in line:
                passed += 1
            elif " FAILED" in line:
                failed += 1
            _monkey_test_progress = {
                "status": "running",
                "passed": passed,
                "failed": failed,
                "line_count": len(lines),
                "last_line": lines[-1] if lines else "",
            }
        proc.wait(timeout=300)
        _monkey_test_results = {
            "status": "done",
            "exit_code": proc.returncode,
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "output": "\n".join(lines[-200:]),
        }
        _monkey_test_progress = {"status": "done"}
    except Exception as e:
        logger.debug("Monkey test error: %s", e)
        _monkey_test_results = {"status": "error", "error": str(e), "output": "\n".join(lines[-100:])}
        _monkey_test_progress = {"status": "done"}


def _execute_wire_test(directory: str, base_url: str):
    global _wire_test_results, _wire_test_progress
    from xray.wire_connector import WireConnector

    wc = WireConnector(base_url)

    def callback(p):
        global _wire_test_progress
        _wire_test_progress = p

    results = wc.run_tests(directory, callback)
    _wire_test_results = results
    _wire_test_progress = {"status": "done", "results": results}


def _background_scan(directory: str, engine: str, severity: str, excludes: list[str], total_files: int):
    """Run scan in background thread, updating _scan_progress as it goes."""
    global _last_scan_result, _scan_progress
    import time as _time

    _last_scan_result = None
    scan_start = _time.perf_counter()
    _scan_progress = {
        "status": "scanning",
        "files_scanned": 0,
        "total_files": total_files,
        "findings_count": 0,
        "current_file": "Starting scan...",
        "file_size": 0,
        "file_type": "",
        "elapsed_ms": 0,
    }

    def progress_writer(_event_type, data):
        """Called per-file; updates the global progress dict instead of SSE."""
        global _scan_progress
        if _event_type == "progress":
            _scan_progress = {**data, "status": "scanning"}

    try:
        if engine == "rust":
            result = scan_with_rust(directory, severity, excludes, sse_write=progress_writer, total_files=total_files)
        else:
            result = scan_with_python(directory, severity, excludes, sse_write=progress_writer, total_files=total_files)
    except Exception as exc:
        if De_Bug:
            logger.debug("SCAN CRASHED: %s: %s", type(exc).__name__, exc)
        result = {
            "error": f"Scan crashed: {type(exc).__name__}: {exc}",
            "engine": engine,
            "aborted": False,
            "files_scanned": 0,
            "findings": [],
            "errors": [],
            "summary": {"total": 0, "high": 0, "medium": 0, "low": 0},
        }

    elapsed_ms = round((_time.perf_counter() - scan_start) * 1000, 1)
    _last_scan_result = result

    _scan_progress = {
        "status": "done",
        "files_scanned": result.get("files_scanned", 0),
        "total_files": total_files,
        "findings_count": result.get("summary", {}).get("total", 0),
        "elapsed_ms": result.get("elapsed_ms", elapsed_ms),
    }

    if De_Bug:
        logger.debug(
            "background scan done — %s files, %s findings, elapsed=%.0fms",
            result.get("files_scanned", "?"),
            result.get("summary", {}).get("total", "?"),
            elapsed_ms,
        )
    logger.info(
        "[scan] done — %s files, %s findings", result.get("files_scanned", 0), result.get("summary", {}).get("total", 0)
    )


def _count_scannable_files(directory: str, exclude_patterns: list[str] | None = None) -> int:
    """Fast pre-count of scannable files (mirrors scanner's walk logic)."""
    import re as _re

    from xray.scanner import _EXT_LANG, _SKIP_DIRS

    skip_dirs = _SKIP_DIRS
    scan_exts = set(_EXT_LANG.keys())
    exclude_res = []
    if exclude_patterns:
        for pat in exclude_patterns:
            try:
                exclude_res.append(_re.compile(pat))
            except _re.error as exc:
                logger.debug("Invalid exclude pattern %r: %s", pat, exc)
    count = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in scan_exts:
                continue
            fp = os.path.join(dirpath, fn)
            # Match scan_directory: always check relpath (skips Windows reserved names)
            try:
                rel = os.path.relpath(fp, directory).replace(os.sep, "/")
            except ValueError:
                logger.debug("Cannot compute relative path for %s", fp)
                continue
            if exclude_res and any(r.search(rel) for r in exclude_res):
                continue
            count += 1
    return count


# ── Helpers ──────────────────────────────────────────────────────────────


class _ScanAborted(Exception):
    """Raised inside on_progress to abort a scan early."""


_rust_proc = None  # track running Rust subprocess for abort
_rust_proc_lock = threading.Lock()


def get_rust_binary() -> str | None:
    """Find the Rust binary for the current platform."""
    system = platform.system()
    machine = platform.machine()
    targets = {
        ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
        ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
        ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("Darwin", "x86_64"): "x86_64-apple-darwin",
        ("Darwin", "arm64"): "aarch64-apple-darwin",
    }
    target = targets.get((system, machine))
    if not target:
        return None
    name = "xray-scanner.exe" if system == "Windows" else "xray-scanner"
    path = SCANNER_DIR / "target" / target / "release" / name
    return str(path) if path.exists() else None


def scan_with_python(directory: str, severity: str, excludes: list[str], sse_write=None, total_files: int = 0) -> dict:
    """Run scan using Python scanner. If sse_write is provided, push per-file SSE events."""
    sys.path.insert(0, str(ROOT))
    from xray.rules import ALL_RULES
    from xray.scanner import scan_directory

    sev_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    min_sev = sev_order.get(severity.upper(), 1)
    rules = [r for r in ALL_RULES if sev_order.get(r["severity"], 1) >= min_sev]

    scan_start = time.perf_counter()

    def on_progress(files_scanned, findings_count, current_file):
        if _abort.is_set():
            raise _ScanAborted()
        if sse_write:
            elapsed_ms = round((time.perf_counter() - scan_start) * 1000, 1)
            # Get file info
            fsize = 0
            fext = ""
            try:
                full = os.path.join(directory, current_file)
                fsize = os.path.getsize(full)
                fext = os.path.splitext(current_file)[1]
            except OSError:
                logger.debug("Could not stat file %s", current_file)
            if De_Bug and files_scanned % 50 == 0:
                logger.debug(
                    "progress: %s/%s files, %s findings, %s",
                    files_scanned,
                    total_files,
                    findings_count,
                    current_file,
                )
            sse_write(
                "progress",
                {
                    "files_scanned": files_scanned,
                    "total_files": total_files,
                    "findings_count": findings_count,
                    "current_file": current_file,
                    "file_size": fsize,
                    "file_type": fext,
                    "elapsed_ms": elapsed_ms,
                },
            )

    _abort.clear()
    start = time.perf_counter()
    try:
        result = scan_directory(directory, rules=rules, exclude_patterns=excludes or None, on_progress=on_progress)
    except _ScanAborted:
        logger.debug("Scan aborted by user")
        return {"aborted": True, "engine": "python", "files_scanned": 0, "findings_count": 0}
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    return {
        "engine": "python",
        "elapsed_ms": elapsed_ms,
        "files_scanned": result.files_scanned,
        "summary": {
            "total": len(result.findings),
            "high": result.high_count,
            "medium": result.medium_count,
            "low": result.low_count,
        },
        "findings": [f.to_dict() for f in result.findings],
        "errors": result.errors,
    }


def scan_with_rust(directory: str, severity: str, excludes: list[str], sse_write=None, total_files: int = 0) -> dict:
    """Run scan using Rust binary. If sse_write provided, push SSE events."""
    binary = get_rust_binary()
    if not binary:
        return {"error": "Rust binary not found. Run: python build.py"}

    cmd = [binary, directory, "--severity", severity.upper(), "--json"]
    for exc in excludes:
        cmd.extend(["--exclude", exc])

    _abort.clear()
    if sse_write:
        sse_write(
            "progress",
            {
                "files_scanned": 0,
                "total_files": total_files,
                "findings_count": 0,
                "current_file": "(rust binary)",
                "file_size": 0,
                "file_type": "",
                "elapsed_ms": 0,
            },
        )

    global _rust_proc
    start = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore"
    )
    with _rust_proc_lock:
        _rust_proc = proc
    stdout, stderr = proc.communicate()
    with _rust_proc_lock:
        _rust_proc = None
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    if _abort.is_set():
        return {"aborted": True, "engine": "rust"}

    if proc.returncode != 0:
        return {"error": f"Rust scanner failed: {stderr[:500]}"}

    data = json.loads(stdout)
    data["engine"] = "rust"
    data["elapsed_ms"] = elapsed_ms
    return data


def _fwd(path: str) -> str:
    """Normalize path to forward slashes (works on all OSes, safe in JS strings)."""
    return path.replace("\\", "/")


def browse_directory(path: str) -> dict:
    """List directory contents for the file browser."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"error": f"Path not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}

        items = []
        try:
            for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                name = entry.name
                if name.startswith(".") and name not in (".env",):
                    continue
                items.append(
                    {
                        "name": name,
                        "path": _fwd(str(entry)),
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if entry.is_file() else None,
                    }
                )
        except PermissionError:
            logger.debug("Permission denied listing %s", path)
            return {"error": f"Permission denied: {path}"}

        parent = _fwd(str(p.parent)) if p.parent != p else None
        return {
            "current": _fwd(str(p)),
            "parent": parent,
            "items": items,
        }
    except Exception as e:
        logger.debug("browse_directory error: %s", e)
        return {"error": str(e)}


def get_drives() -> list[dict]:
    """List available drives (Windows) or root (Unix)."""
    if platform.system() == "Windows":
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:/"
            if os.path.exists(drive):
                drives.append({"name": f"{letter}:", "path": drive, "is_dir": True})
        return drives
    else:
        return [{"name": "/", "path": "/", "is_dir": True}]


# ── Chat Bot (knowledge-based) ──────────────────────────────────────────

_GUIDE_TEXT = ""


def _load_guide():
    """Load X_RAY_LLM_GUIDE.md once at startup for chat context."""
    global _GUIDE_TEXT
    guide_path = ROOT / "X_RAY_LLM_GUIDE.md"
    if guide_path.exists():
        _GUIDE_TEXT = guide_path.read_text(encoding="utf-8", errors="ignore")


# Rule knowledge base
_RULES = {
    # Security (14)
    "SEC-001": ("XSS: Template literal in innerHTML", "HIGH", False),
    "SEC-002": ("XSS: String concat to innerHTML", "HIGH", False),
    "SEC-003": ("Command injection: shell=True", "HIGH", True),
    "SEC-004": ("SQL injection: Query formatting", "HIGH", False),
    "SEC-005": ("SSRF: URL from user input", "MEDIUM", False),
    "SEC-006": ("CORS misconfiguration: wildcard", "MEDIUM", False),
    "SEC-007": ("Code injection: eval/exec", "HIGH", False),
    "SEC-008": ("Hardcoded secret", "MEDIUM", False),
    "SEC-009": ("Unsafe deserialization", "HIGH", True),
    "SEC-010": ("Path traversal", "MEDIUM", False),
    "SEC-011": ("Timing attack: == on secrets", "MEDIUM", False),
    "SEC-012": ("Debug mode enabled in production", "HIGH", False),
    "SEC-013": ("Weak hash algorithm: MD5/SHA1", "MEDIUM", False),
    "SEC-014": ("TLS verification disabled", "HIGH", False),
    # Quality (13)
    "QUAL-001": ("Bare except clause", "MEDIUM", True),
    "QUAL-002": ("Silent exception swallowing", "LOW", False),
    "QUAL-003": ("Unchecked int() on user input", "MEDIUM", True),
    "QUAL-004": ("Unchecked float() on user input", "MEDIUM", True),
    "QUAL-005": (".items() on possibly-None return", "LOW", False),
    "QUAL-006": ("Non-daemon threads", "MEDIUM", False),
    "QUAL-007": ("TODO/FIXME markers", "LOW", False),
    "QUAL-008": ("Long sleep (10+ seconds)", "MEDIUM", False),
    "QUAL-009": ("Keep-alive header in HTTP", "HIGH", False),
    "QUAL-010": ("localStorage without try/catch", "MEDIUM", False),
    "QUAL-011": ("Broad Exception catching", "MEDIUM", False),
    "QUAL-012": ("String concatenation in loop", "LOW", False),
    "QUAL-013": ("Line exceeds 200 characters", "LOW", False),
    # Python (11)
    "PY-001": ("Return type mismatch", "MEDIUM", False),
    "PY-002": (".items() on method returning None", "HIGH", False),
    "PY-003": ("Wildcard import", "MEDIUM", False),
    "PY-004": ("print() debug statement", "LOW", False),
    "PY-005": ("JSON without error handling", "HIGH", True),
    "PY-006": ("Global mutation", "MEDIUM", False),
    "PY-007": ("os.envir" + "on[] crashes on missing", "MEDIUM", True),
    "PY-008": ("open() without encoding", "MEDIUM", False),
    "PY-009": ("Captured but ignored exception", "MEDIUM", False),
    "PY-010": ("sys.exit() in library code", "MEDIUM", False),
    "PY-011": ("Long isinstance chain", "LOW", False),
}

_TOOLS_LIST = [
    "Dead Code",
    "Code Smells",
    "Duplicates",
    "Formatting (ruff)",
    "Type Check (pyright)",
    "Bandit (security)",
    "Ruff --fix",
    "Import Graph",
    "Git Hotspots",
    "Project Health",
    "SATD (tech debt)",
    "Release Readiness",
    "AI-Generated Code Detection",
    "Web Smells",
    "Test Stub Generator",
    "Remediation Time Estimate",
    "Circular Call Detection",
    "Module Coupling & Cohesion",
    "Unused Imports",
]

_PM_FEATURES = {
    "risk heatmap": "Color-coded grid of files by risk score — red = urgent, green = clean. Uses findings severity × density.",
    "module cards": "Per-directory grade cards (A+ through F) showing issue breakdown for each module.",
    "confidence meter": "Large percentage showing release confidence based on quality gate thresholds.",
    "sprint batches": "Groups findings into 4 work packages: Critical, Security, Quality, Cleanup — ready for sprint planning.",
    "architecture map": "Visualizes project layers (API, core, utils, tests) with dependency arrows.",
    "call graph": "Interactive vis.js graph of function call relationships — shows entry points, leaves, and call chains.",
    "circular calls": "Detects function-level circular call chains (macaroni code), recursive functions, and hub functions with high fan-in × fan-out.",
    "coupling": "Per-module afferent/efferent coupling, instability metric (I=Ce/(Ca+Ce)), cohesion estimate, and health classification (healthy/god/fragile/isolated).",
    "unused imports": "AST-based detection of imported names never referenced anywhere in the file — dead imports that clutter code.",
}


def _chat_reply(message: str, context: dict) -> str:
    """Generate a knowledge-based reply about X-Ray features."""
    lo = message.lower().strip()

    # Direct rule lookup: "SEC-003", "QUAL-001", etc.
    for rule_id, (name, severity, fixable) in _RULES.items():
        if rule_id.lower() in lo:
            fix_str = "✅ Auto-fixable" if fixable else "❌ No auto-fix (manual or LLM)"
            return f"<strong>{rule_id}: {name}</strong><br>Severity: <strong>{severity}</strong><br>Fix: {fix_str}"

    # PM Dashboard features
    for feature, desc in _PM_FEATURES.items():
        if feature in lo or feature.replace(" ", "") in lo.replace(" ", ""):
            return f"<strong>{feature.title()}</strong>: {desc}"

    # Category-based responses
    if _re.search(r"\brule|all rule|38 rule|28 rule|list rule", lo):
        sec = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("SEC")]
        qual = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("QUAL")]
        py = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("PY")]
        return (
            "<strong>38 Scan Rules:</strong><br><br>"
            "<strong>Security (14):</strong><br>"
            + "<br>".join(sec)
            + "<br><br><strong>Quality (13):</strong><br>"
            + "<br>".join(qual)
            + "<br><br><strong>Python (11):</strong><br>"
            + "<br>".join(py)
        )

    if _re.search(r"\bfix|auto.?fix|fixable|fixer", lo):
        fixable = [f"<strong>{k}</strong>: {v[0]}" for k, v in _RULES.items() if v[2]]
        return (
            "<strong>7 Auto-Fixable Rules</strong> (no LLM needed):<br>"
            + "<br>".join(fixable)
            + "<br><br>Click the 🔧 wrench icon on any finding, or use <code>/api/apply-fix</code>."
        )

    if _re.search(r"\bpm|dashboard|project.?manag", lo):
        items = [f"• <strong>{k.title()}</strong>: {v}" for k, v in _PM_FEATURES.items()]
        return "<strong>PM Dashboard — 9 Features:</strong><br><br>" + "<br>".join(items)

    if _re.search(r"\btool|analys|analyzer", lo):
        numbered = [f"{i + 1}. {t}" for i, t in enumerate(_TOOLS_LIST)]
        return "<strong>19 Analysis Tools:</strong><br>" + "<br>".join(numbered)

    if _re.search(r"\bscan|how.*start|begin|quick.?start", lo):
        return (
            "<strong>How to Scan:</strong><br>"
            "1. Browse to a directory in the left sidebar<br>"
            "2. Choose engine (Python or Rust) and severity filter<br>"
            "3. Click <strong>Scan Project</strong><br>"
            "4. Results appear on the right with severity badges<br><br>"
            "CLI: <code>python -m xray.agent /path --dry-run</code>"
        )

    if _re.search(r"\bgrade|score|letter|a\+|rating", lo):
        return (
            "<strong>Grading System:</strong><br>"
            "• A+ = 0 issues<br>• A = 1–3<br>• B = 4–7<br>• C = 8–12<br>"
            "• D = 13–20<br>• F = 21+<br><br>"
            "Weighted: High×3 + Medium×1 + Low×0.3<br>"
            "Quality Gate in sidebar sets pass/fail thresholds."
        )

    if _re.search(r"\bapi|endpoint|rest|http", lo):
        return (
            "<strong>34+ API Endpoints</strong> on <code>localhost:8077/api/</code>:<br><br>"
            "Core: <code>/api/scan</code> (SSE), <code>/api/browse</code>, <code>/api/info</code>, <code>/api/abort</code><br>"
            "Fix: <code>/api/preview-fix</code>, <code>/api/apply-fix</code>, <code>/api/apply-fixes-bulk</code><br>"
            "Analysis: <code>/api/dead-code</code>, <code>/api/smells</code>, <code>/api/duplicates</code>, "
            "<code>/api/format</code>, <code>/api/typecheck</code>, <code>/api/bandit</code>, <code>/api/ruff</code><br>"
            "PM: <code>/api/risk-heatmap</code>, <code>/api/module-cards</code>, <code>/api/confidence</code>, "
            "<code>/api/sprint-batches</code>, <code>/api/architecture</code>, <code>/api/call-graph</code><br>"
            "CGC: <code>/api/circular-calls</code>, <code>/api/coupling</code>, <code>/api/unused-imports</code><br>"
            "Utility: <code>/api/chat</code>, <code>/api/project-review</code>"
        )

    if _re.search(r"\brust|engine|fast|performance|speed", lo):
        return (
            "<strong>Dual Engines:</strong><br>"
            "• <strong>Python</strong>: Cross-platform, always available, full feature set<br>"
            "• <strong>Rust</strong>: ~10× faster, optional. Build: <code>python build.py</code><br><br>"
            "Switch in the sidebar Settings → Engine dropdown."
        )

    if _re.search(r"\bsecurity|vuln|xss|inject|sql|ssrf|cors|eval|pickle|secret|password", lo):
        sec = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){' ✅fix' if v[2] else ''}"
            for k, v in _RULES.items()
            if k.startswith("SEC")
        ]
        return "<strong>Security Rules (14):</strong><br>" + "<br>".join(sec)

    if _re.search(r"\bquality|smell|except|magic|dup|long func|param", lo):
        qual = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){' ✅fix' if v[2] else ''}"
            for k, v in _RULES.items()
            if k.startswith("QUAL")
        ]
        return "<strong>Quality Rules (13):</strong><br>" + "<br>".join(qual)

    if _re.search(r"\bpython rule|py rule|print|assert|wildcard|import\b", lo):
        py = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){' ✅fix' if v[2] else ''}"
            for k, v in _RULES.items()
            if k.startswith("PY")
        ]
        return "<strong>Python Rules (11):</strong><br>" + "<br>".join(py)

    if _re.search(r"\bhello|hi\b|hey|help|what can you", lo):
        return (
            "Hello! I'm the <strong>X-Ray Assistant</strong>. I can help with:<br><br>"
            "• <strong>rules</strong> — all 38 scan rules (14 security + 13 quality + 11 Python)<br>"
            "• <strong>auto-fix</strong> — which rules have automatic fixes<br>"
            "• <strong>tools</strong> — 19 analysis tools<br>"
            "• <strong>PM Dashboard</strong> — 9 project management features<br>"
            "• <strong>scanning</strong> — how to scan a project<br>"
            "• <strong>grading</strong> — score and letter grade system<br>"
            "• <strong>API</strong> — 34+ REST endpoints<br>"
            "• <strong>engines</strong> — Python vs Rust<br><br>"
            "Or ask about a specific rule like <code>SEC-003</code>!"
        )

    # Scan context
    has_results = context.get("has_results", False)
    findings = context.get("findings_count", 0)
    if has_results and _re.search(r"\bresult|finding|current|status|summary", lo):
        return (
            f"Current scan: <strong>{findings} findings</strong> in "
            f"<code>{context.get('directory', 'unknown')}</code>. "
            "Use the filter tabs above the results to sort by severity or rule."
        )

    # Default
    return (
        "I know about X-Ray's <strong>38 rules</strong>, <strong>7 auto-fixers</strong>, "
        "<strong>19 tools</strong>, <strong>9 PM Dashboard features</strong>, <strong>grading</strong>, "
        "and <strong>34+ API endpoints</strong>. "
        "Try asking about any of those, or a specific rule like <code>SEC-003</code>!"
    )


# ── HTTP Handler ─────────────────────────────────────────────────────────


class XRayHandler(BaseHTTPRequestHandler):
    """Handle API requests and serve the UI."""

    def log_message(self, format, *args):
        """Suppress default request logging noise."""
        pass

    def handle(self):
        """Silence connection reset/abort errors (normal browser behavior)."""
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            logger.debug("Client connection lost during request")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, filepath: Path):
        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            logger.debug("UI file not found: %s", self.path)
            self.send_error(404, "File not found")

    _MAX_BODY = 10 * 1024 * 1024  # 10 MB safety limit

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > self._MAX_BODY:
            self.send_error(413, "Request body too large")
            return {}
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/ui.html":
            self._send_html(ROOT / "ui.html")

        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()

        elif path == "/api/browse":
            params = parse_qs(parsed.query)
            dir_path = params.get("path", [""])[0]
            if not dir_path:
                self._send_json({"drives": get_drives()})
            else:
                self._send_json(browse_directory(dir_path))

        elif path == "/api/scan-result":
            if De_Bug:
                has = _last_scan_result is not None
                n = len(_last_scan_result.get("findings", [])) if has else 0
                logger.debug("GET /api/scan-result — has_result=%s, findings=%s", has, n)
            if _last_scan_result is not None:
                self._send_json(_last_scan_result)
            else:
                self._send_json({"error": "No scan results available"}, 404)

        elif path == "/api/scan-progress":
            if _scan_progress is not None:
                self._send_json(_scan_progress)
            else:
                self._send_json({"status": "idle"})

        elif path == "/api/info":
            rust_bin = get_rust_binary()
            from xray.fixer import FIXABLE_RULES

            self._send_json(
                {
                    "platform": f"{platform.system()} {platform.machine()}",
                    "python": platform.python_version(),
                    "rust_available": rust_bin is not None,
                    "rust_binary": rust_bin,
                    "rules_count": len(__import__("xray.rules", fromlist=["ALL_RULES"]).ALL_RULES),
                    "home": _fwd(str(Path.home())),
                    "fixable_rules": sorted(FIXABLE_RULES),
                }
            )

        elif path == "/api/env-check":
            from xray.compat import (
                check_environment, environment_summary,
                check_api_compatibility, api_compatibility_summary,
                DEPENDENCIES, MIN_PYTHON,
            )

            ok, problems = check_environment()
            api_results = check_api_compatibility()
            api_report = [
                {
                    "library": r.import_path,
                    "symbol": r.attr_chain,
                    "used_in": r.used_in,
                    "description": r.description,
                    "found": r.found,
                    "error": r.error,
                }
                for r in api_results
            ]
            self._send_json(
                {
                    "ok": ok,
                    "python_version": platform.python_version(),
                    "min_python": ".".join(str(v) for v in MIN_PYTHON),
                    "problems": problems,
                    "summary": environment_summary(),
                    "api_compatibility": api_report,
                    "api_summary": api_compatibility_summary(),
                }
            )

        elif path == "/api/dependency-check":
            from xray.compat import dependency_freshness_summary

            self._send_json(dependency_freshness_summary())

        elif path == "/api/wire-progress":
            if _wire_test_progress is not None:
                self._send_json(_wire_test_progress)
            elif _wire_test_results is not None:
                self._send_json({"status": "done", "results": _wire_test_results})
            else:
                self._send_json({"status": "idle"})

        elif path == "/api/monkey-progress":
            if _monkey_test_progress is not None and _monkey_test_progress.get("status") == "running":
                self._send_json(_monkey_test_progress)
            elif _monkey_test_results is not None:
                self._send_json(_monkey_test_results)
            else:
                self._send_json({"status": "idle"})

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/abort":
            _abort.set()
            with _rust_proc_lock:
                if _rust_proc and _rust_proc.poll() is None:
                    _rust_proc.kill()
            self._send_json({"ok": True})
            return

        if path == "/api/scan":
            body = self._read_body()
            directory = body.get("directory", "")
            engine = body.get("engine", "python")
            severity = body.get("severity", "LOW")
            excludes = body.get("excludes", [])

            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return

            # Resolve to absolute path
            directory = str(Path(directory).resolve())

            # Clear previous results
            global _last_scan_result, _scan_progress, _scan_thread
            _last_scan_result = None
            _scan_progress = None

            # Pre-count files
            total = _count_scannable_files(directory, excludes)
            if De_Bug:
                logger.debug("=== SCAN START (async) ===")
                logger.debug("directory: %s", directory)
                logger.debug("engine: %s, severity: %s", engine, severity)
                logger.debug("pre-count: %s scannable files", total)

            # Start scan in background thread — return immediately
            _abort.clear()
            _scan_thread = threading.Thread(
                target=_background_scan,
                args=(directory, engine, severity, excludes, total),
                daemon=True,
            )
            _scan_thread.start()

            self._send_json({"status": "started", "total_files": total})
            return

        elif path == "/api/preview-fix":
            from xray.fixer import preview_fix

            body = self._read_body()
            result = preview_fix(body)
            self._send_json(result)

        elif path == "/api/apply-fix":
            from xray.fixer import apply_fix

            body = self._read_body()
            result = apply_fix(body)
            self._send_json(result)

        elif path == "/api/apply-fixes-bulk":
            from xray.fixer import apply_fixes_bulk

            body = self._read_body()
            findings = body.get("findings", [])
            result = apply_fixes_bulk(findings)
            self._send_json(result)

        elif path == "/api/satd":
            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            result = scan_satd(str(Path(directory).resolve()))
            self._send_json(result)

        elif path == "/api/git-hotspots":
            body = self._read_body()
            directory = body.get("directory", "")
            days = body.get("days", 90)
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            result = analyze_git_hotspots(str(Path(directory).resolve()), days)
            self._send_json(result)

        elif path == "/api/imports":
            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            result = parse_imports(str(Path(directory).resolve()))
            self._send_json(result)

        elif path == "/api/ruff":
            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            result = run_ruff(str(Path(directory).resolve()))
            self._send_json(result)

        elif path == "/api/format":
            from analyzers import check_format

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(check_format(str(Path(directory).resolve())))

        elif path == "/api/typecheck":
            from analyzers import check_types

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(check_types(str(Path(directory).resolve())))

        elif path == "/api/health":
            from analyzers import check_project_health

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(check_project_health(str(Path(directory).resolve())))

        elif path == "/api/bandit":
            from analyzers import run_bandit

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(run_bandit(str(Path(directory).resolve())))

        elif path == "/api/dead-code":
            from analyzers import detect_dead_functions

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_dead_functions(str(Path(directory).resolve())))

        elif path == "/api/smells":
            from analyzers import detect_code_smells

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_code_smells(str(Path(directory).resolve())))

        elif path == "/api/duplicates":
            from analyzers import detect_duplicates

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_duplicates(str(Path(directory).resolve())))

        elif path == "/api/temporal-coupling":
            from analyzers import analyze_temporal_coupling

            body = self._read_body()
            directory = body.get("directory", "")
            days = body.get("days", 90)
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(analyze_temporal_coupling(str(Path(directory).resolve()), days))

        elif path == "/api/typecheck-pyright":
            from analyzers import run_typecheck

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(run_typecheck(str(Path(directory).resolve())))

        elif path == "/api/release-readiness":
            from analyzers import check_release_readiness

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(check_release_readiness(str(Path(directory).resolve())))

        elif path == "/api/ai-detect":
            from analyzers import detect_ai_code

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_ai_code(str(Path(directory).resolve())))

        elif path == "/api/web-smells":
            from analyzers import detect_web_smells

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_web_smells(str(Path(directory).resolve())))

        elif path == "/api/connection-test":
            from analyzers import analyze_connections

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(analyze_connections(str(Path(directory).resolve())))

        elif path == "/api/test-gen":
            from analyzers import generate_test_stubs

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(generate_test_stubs(str(Path(directory).resolve())))

        elif path == "/api/remediation-time":
            from analyzers import estimate_remediation_time

            body = self._read_body()
            findings = body.get("findings", [])
            self._send_json(estimate_remediation_time(findings))

        # ── PM Dashboard endpoints ──────────────────────────────
        elif path == "/api/risk-heatmap":
            from analyzers import compute_risk_heatmap

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_risk_heatmap(str(Path(directory).resolve()), body.get("findings")))

        elif path == "/api/module-cards":
            from analyzers import compute_module_cards

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_module_cards(str(Path(directory).resolve()), body.get("findings")))

        elif path == "/api/confidence":
            from analyzers import compute_confidence_meter

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_confidence_meter(str(Path(directory).resolve()), body.get("findings")))

        elif path == "/api/sprint-batches":
            from analyzers import compute_sprint_batches

            body = self._read_body()
            self._send_json(compute_sprint_batches(body.get("findings"), body.get("smells")))

        elif path == "/api/architecture":
            from analyzers import compute_architecture_map

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_architecture_map(str(Path(directory).resolve())))

        elif path == "/api/call-graph":
            from analyzers import compute_call_graph

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_call_graph(str(Path(directory).resolve())))

        elif path == "/api/chat":
            body = self._read_body()
            message = body.get("message", "").strip()
            if not message:
                self._send_json({"reply": "Please type a message."})
                return
            reply = _chat_reply(message, body)
            self._send_json({"reply": reply})

        elif path == "/api/project-review":
            from analyzers import compute_project_review

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(
                compute_project_review(
                    str(Path(directory).resolve()),
                    findings=body.get("findings"),
                    summary=body.get("summary"),
                    files_scanned=body.get("files_scanned", 0),
                    smells=body.get("smells"),
                    dead_functions=body.get("dead_functions"),
                    health=body.get("health"),
                    satd=body.get("satd"),
                    duplicates=body.get("duplicates"),
                )
            )

        elif path == "/api/circular-calls":
            from analyzers import detect_circular_calls

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_circular_calls(str(Path(directory).resolve())))

        elif path == "/api/coupling":
            from analyzers import compute_coupling_metrics

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(compute_coupling_metrics(str(Path(directory).resolve())))

        elif path == "/api/unused-imports":
            from analyzers import detect_unused_imports

            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return
            self._send_json(detect_unused_imports(str(Path(directory).resolve())))

        elif path == "/api/monkey-test":
            global _monkey_test_thread, _monkey_test_results, _monkey_test_progress
            if _monkey_test_thread and _monkey_test_thread.is_alive():
                self._send_json({"status": "already_running"})
                return
            _monkey_test_results = None
            _monkey_test_progress = {"status": "starting", "passed": 0, "failed": 0}

            host = self.server.server_address[0]
            port = self.server.server_address[1]
            base_url = f"http://{host}:{port}"

            _monkey_test_thread = threading.Thread(
                target=_execute_monkey_tests, args=(base_url,), daemon=True
            )
            _monkey_test_thread.start()
            self._send_json({"status": "started"})

        elif path == "/api/wire-test":
            body = self._read_body()
            directory = body.get("directory", "")
            if not directory or not os.path.isdir(directory):
                self._send_json({"error": f"Invalid directory: {directory}"}, 400)
                return

            global _wire_test_thread, _wire_test_results, _wire_test_progress
            _wire_test_results = None
            _wire_test_progress = {"status": "starting", "step": 0, "total": 0}

            host = self.server.server_address[0]
            port = self.server.server_address[1]
            base_url = f"http://{host}:{port}"

            _wire_test_thread = threading.Thread(
                target=_execute_wire_test, args=(str(Path(directory).resolve()), base_url), daemon=True
            )
            _wire_test_thread.start()
            self._send_json({"status": "started"})

        else:
            self.send_error(404)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="X-Ray Scanner Web UI")
    parser.add_argument("--port", "-p", type=int, default=8077, help="Port to listen on (default: 8077)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    # ── Environment verification ──────────────────────────────────────
    from xray.compat import check_environment, environment_summary

    ok, problems = check_environment()
    if problems:
        for p in problems:
            lvl = logging.ERROR if p.startswith("[REQUIRED]") else logging.WARNING
            logger.log(lvl, p)
    if not ok:
        raise SystemExit(1)
    logger.info("Environment OK:\n%s", environment_summary())

    _load_guide()  # Load knowledge base for chat bot

    ServerClass = type(
        "ThreadedHTTPServer",
        (ThreadingMixIn, HTTPServer),
        {
            "daemon_threads": True,
            "allow_reuse_address": True,
        },
    )
    try:
        server = ServerClass((args.host, args.port), XRayHandler)
    except OSError as e:
        logger.error("Cannot bind to %s:%s — %s", args.host, args.port, e)
        logger.error("Another instance is likely already running on that port.")
        logger.error("Kill it first or use: python ui_server.py --port %s", args.port + 1)
        raise SystemExit(1) from e

    rust_status = "available" if get_rust_binary() else "not built"
    logger.info("X-Ray Scanner UI: http://%s:%s", args.host, args.port)
    logger.info("  Python scanner: ready")
    logger.info("  Rust scanner:   %s", rust_status)
    logger.info("  Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
