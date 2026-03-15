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
import os
import platform
import subprocess
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse, parse_qs

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

_SATD_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".tox",
                    "build", "dist", "_rustified", ".mypy_cache", ".pytest_cache", "target"}

_COMMENT_RE = _re.compile(r"#\s*(.*)")

_TEXT_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
                    ".cs", ".go", ".rb", ".rs", ".sh", ".bat", ".yaml", ".yml", ".toml", ".md"}


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
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat, category, hours in _SATD_MARKERS:
                            m = pat.search(line)
                            if m:
                                text = line.strip()
                                # Try to extract just the comment part
                                cm = _COMMENT_RE.search(line)
                                if cm:
                                    text = cm.group(1).strip()
                                items.append({
                                    "file": _fwd(fpath),
                                    "line": lineno,
                                    "category": category,
                                    "marker": m.group(1).upper(),
                                    "text": text[:200],
                                    "hours": hours,
                                })
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
            capture_output=True, text=True, cwd=directory, timeout=30,
        )
    except FileNotFoundError:
        return {"error": "git not found. Install git to use hotspot analysis."}
    except subprocess.TimeoutExpired:
        return {"error": "git log timed out."}

    if result.returncode != 0:
        return {"error": f"git error: {result.stderr.strip()[:200]}"}

    skip_patterns = {"__pycache__", ".min.js", ".min.css", "package-lock.json",
                     "uv.lock", "Cargo.lock", ".pyc"}
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
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
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
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return {"error": "ruff not found. Install: pip install ruff"}
    except subprocess.TimeoutExpired:
        return {"error": "ruff timed out."}

    # Count fixes from output
    fixed = result.stdout.count("Fixed") + result.stdout.count("fixed")
    remaining = result.stdout.count("[")
    return {"fixed": fixed, "remaining": remaining, "output": result.stdout[:2000]}

# ── Scan Progress Tracking ───────────────────────────────────────────────

_progress = {
    "active": False,
    "engine": "",
    "directory": "",
    "files_scanned": 0,
    "findings_count": 0,
    "current_file": "",
    "started_at": 0.0,
    "elapsed_ms": 0.0,
}
_progress_lock = threading.Lock()
_abort = threading.Event()

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


def scan_with_python(directory: str, severity: str, excludes: list[str]) -> dict:
    """Run scan using Python scanner."""
    sys.path.insert(0, str(ROOT))
    from xray.scanner import scan_directory
    from xray.rules import ALL_RULES

    sev_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    min_sev = sev_order.get(severity.upper(), 1)
    rules = [r for r in ALL_RULES if sev_order.get(r["severity"], 1) >= min_sev]

    def on_progress(files_scanned, findings_count, current_file):
        if _abort.is_set():
            raise _ScanAborted()
        with _progress_lock:
            _progress["files_scanned"] = files_scanned
            _progress["findings_count"] = findings_count
            _progress["current_file"] = current_file
            _progress["elapsed_ms"] = round((time.perf_counter() - _progress["started_at"]) * 1000, 1)

    _abort.clear()
    with _progress_lock:
        _progress.update(active=True, engine="python", directory=_fwd(directory),
                         files_scanned=0, findings_count=0, current_file="",
                         started_at=time.perf_counter(), elapsed_ms=0.0)

    start = time.perf_counter()
    try:
        result = scan_directory(directory, rules=rules, exclude_patterns=excludes or None,
                                on_progress=on_progress)
    except _ScanAborted:
        with _progress_lock:
            _progress["active"] = False
        return {"aborted": True, "engine": "python",
                "files_scanned": _progress["files_scanned"],
                "findings_count": _progress["findings_count"]}
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    with _progress_lock:
        _progress["active"] = False

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


def scan_with_rust(directory: str, severity: str, excludes: list[str]) -> dict:
    """Run scan using Rust binary."""
    binary = get_rust_binary()
    if not binary:
        return {"error": "Rust binary not found. Run: python build.py"}

    cmd = [binary, directory, "--severity", severity.upper(), "--json"]
    for exc in excludes:
        cmd.extend(["--exclude", exc])

    _abort.clear()
    with _progress_lock:
        _progress.update(active=True, engine="rust", directory=_fwd(directory),
                         files_scanned=0, findings_count=0, current_file="(rust binary)",
                         started_at=time.perf_counter(), elapsed_ms=0.0)

    global _rust_proc
    start = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with _rust_proc_lock:
        _rust_proc = proc
    stdout, stderr = proc.communicate()
    with _rust_proc_lock:
        _rust_proc = None
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    with _progress_lock:
        _progress["active"] = False

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
                items.append({
                    "name": name,
                    "path": _fwd(str(entry)),
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                })
        except PermissionError:
            return {"error": f"Permission denied: {path}"}

        parent = _fwd(str(p.parent)) if p.parent != p else None
        return {
            "current": _fwd(str(p)),
            "parent": parent,
            "items": items,
        }
    except Exception as e:
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
            pass

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, filepath: Path):
        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "File not found")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body)

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

        elif path == "/api/info":
            rust_bin = get_rust_binary()
            from xray.fixer import FIXABLE_RULES
            self._send_json({
                "platform": f"{platform.system()} {platform.machine()}",
                "python": platform.python_version(),
                "rust_available": rust_bin is not None,
                "rust_binary": rust_bin,
                "rules_count": 28,
                "home": _fwd(str(Path.home())),
                "fixable_rules": sorted(FIXABLE_RULES),
            })

        elif path == "/api/progress":
            with _progress_lock:
                self._send_json(dict(_progress))

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

            if engine == "rust":
                result = scan_with_rust(directory, severity, excludes)
            else:
                result = scan_with_python(directory, severity, excludes)

            self._send_json(result)

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

        elif path == "/api/typecheck":
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

        else:
            self.send_error(404)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="X-Ray Scanner Web UI")
    parser.add_argument("--port", "-p", type=int, default=8077,
                        help="Port to listen on (default: 8077)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    server = type('ThreadedHTTPServer', (ThreadingMixIn, HTTPServer), {'daemon_threads': True})(
        (args.host, args.port), XRayHandler
    )
    rust_status = "available" if get_rust_binary() else "not built"
    print(f"X-Ray Scanner UI: http://{args.host}:{args.port}")
    print(f"  Python scanner: ready")
    print(f"  Rust scanner:   {rust_status}")
    print(f"  Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
