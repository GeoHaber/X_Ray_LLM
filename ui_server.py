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
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
SCANNER_DIR = ROOT / "scanner"

# ── Helpers ──────────────────────────────────────────────────────────────

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

    start = time.perf_counter()
    result = scan_directory(directory, rules=rules, exclude_patterns=excludes or None)
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


def scan_with_rust(directory: str, severity: str, excludes: list[str]) -> dict:
    """Run scan using Rust binary."""
    binary = get_rust_binary()
    if not binary:
        return {"error": "Rust binary not found. Run: python build.py"}

    cmd = [binary, directory, "--severity", severity.upper(), "--json"]
    for exc in excludes:
        cmd.extend(["--exclude", exc])

    start = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    if proc.returncode != 0:
        return {"error": f"Rust scanner failed: {proc.stderr[:500]}"}

    data = json.loads(proc.stdout)
    data["engine"] = "rust"
    data["elapsed_ms"] = elapsed_ms
    return data


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
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                })
        except PermissionError:
            return {"error": f"Permission denied: {path}"}

        parent = str(p.parent) if p.parent != p else None
        return {
            "current": str(p),
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
            drive = f"{letter}:\\"
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

        elif path == "/api/browse":
            params = parse_qs(parsed.query)
            dir_path = params.get("path", [""])[0]
            if not dir_path:
                self._send_json({"drives": get_drives()})
            else:
                self._send_json(browse_directory(dir_path))

        elif path == "/api/info":
            rust_bin = get_rust_binary()
            self._send_json({
                "platform": f"{platform.system()} {platform.machine()}",
                "python": platform.python_version(),
                "rust_available": rust_bin is not None,
                "rust_binary": rust_bin,
                "rules_count": 28,
                "home": str(Path.home()),
            })

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

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

    server = HTTPServer((args.host, args.port), XRayHandler)
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
