"""
Scan Manager — scan orchestration, progress tracking, and file counting.

Extracted from ui_server.py.
"""

import json
import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from services.app_state import state
from xray.constants import fwd as _fwd
from xray.types import BrowseResult, DriveInfo

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# --- Browse allow-list ---------------------------------------------------
# Comma-separated base directories the file browser may access.
# Set XRAY_BROWSE_ROOTS env-var to override (empty string = unrestricted).
_BROWSE_ROOTS_RAW = os.environ.get("XRAY_BROWSE_ROOTS")


def _default_browse_roots() -> list[Path]:
    """Return safe default roots: user home + project root."""
    roots = [ROOT]
    home = Path.home()
    if home.exists():
        roots.append(home)
    return roots


def _browse_roots() -> list[Path] | None:
    """Parse the allow-list. Returns None if unrestricted."""
    if _BROWSE_ROOTS_RAW is None:
        return _default_browse_roots()
    if _BROWSE_ROOTS_RAW.strip() == "":
        return None  # explicitly unrestricted
    return [Path(r.strip()).resolve() for r in _BROWSE_ROOTS_RAW.split(",") if r.strip()]


def _is_path_allowed(target: Path) -> bool:
    """Check *target* is under one of the allowed browse roots."""
    roots = _browse_roots()
    if roots is None:
        return True
    resolved = target.resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


SCANNER_DIR = ROOT / "scanner"


class _ScanAbortedError(Exception):
    """Raised inside on_progress to abort a scan early."""


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


def count_scannable_files(directory: str, exclude_patterns: list[str] | None = None) -> int:
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
            try:
                rel = os.path.relpath(fp, directory).replace(os.sep, "/")
            except ValueError:
                logger.debug("Cannot compute relative path for %s", fp)
                continue
            if exclude_res and any(r.search(rel) for r in exclude_res):
                continue
            count += 1
    return count


def scan_with_python(directory: str, severity: str, excludes: list[str], sse_write=None, total_files: int = 0) -> dict:
    """Run scan using Python scanner."""
    sys.path.insert(0, str(ROOT))
    from xray.rules import ALL_RULES
    from xray.scanner import scan_directory

    sev_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    min_sev = sev_order.get(severity.upper(), 1)
    rules = [r for r in ALL_RULES if sev_order.get(r["severity"], 1) >= min_sev]

    scan_start = time.perf_counter()

    def on_progress(files_scanned, findings_count, current_file):
        if state.abort.is_set():
            raise _ScanAbortedError()
        if sse_write:
            elapsed_ms = round((time.perf_counter() - scan_start) * 1000, 1)
            fsize = 0
            fext = ""
            try:
                full = os.path.join(directory, current_file)
                fsize = os.path.getsize(full)
                fext = os.path.splitext(current_file)[1]
            except OSError:
                logger.debug("Could not stat file %s", current_file)
            if state.debug and files_scanned % 50 == 0:
                logger.debug(
                    "progress: %s/%s files, %s findings, %s", files_scanned, total_files, findings_count, current_file
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

    state.abort.clear()
    start = time.perf_counter()
    try:
        result = scan_directory(directory, rules=rules, exclude_patterns=excludes or None, on_progress=on_progress)
    except _ScanAbortedError:
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
    """Run scan using Rust binary."""
    binary = get_rust_binary()
    if not binary:
        return {"error": "Rust binary not found. Run: python build.py"}

    cmd = [binary, directory, "--severity", severity.upper(), "--json"]
    for exc in excludes:
        cmd.extend(["--exclude", exc])

    state.abort.clear()
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

    start = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    with state.rust_proc_lock:
        state.rust_proc = proc
    stdout, stderr = proc.communicate()
    with state.rust_proc_lock:
        state.rust_proc = None
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    if state.abort.is_set():
        return {"aborted": True, "engine": "rust"}

    if proc.returncode != 0:
        return {"error": f"Rust scanner failed: {stderr[:500]}"}

    data = json.loads(stdout)
    data["engine"] = "rust"
    data["elapsed_ms"] = elapsed_ms
    return data


def background_scan(directory: str, engine: str, severity: str, excludes: list[str], total_files: int):
    """Run scan in background thread, updating state.scan_progress."""
    scan_start = time.perf_counter()
    state.set_scan_result(None)  # type: ignore[arg-type]
    state.set_scan_progress(
        {
            "status": "scanning",
            "files_scanned": 0,
            "total_files": total_files,
            "findings_count": 0,
            "current_file": "Starting scan...",
            "file_size": 0,
            "file_type": "",
            "elapsed_ms": 0,
        }
    )

    def progress_writer(_event_type, data):
        if _event_type == "progress":
            state.set_scan_progress({**data, "status": "scanning"})

    try:
        if engine == "rust":
            result = scan_with_rust(directory, severity, excludes, sse_write=progress_writer, total_files=total_files)
        else:
            result = scan_with_python(directory, severity, excludes, sse_write=progress_writer, total_files=total_files)
    except Exception as exc:
        if state.debug:
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

    elapsed_ms = round((time.perf_counter() - scan_start) * 1000, 1)
    state.set_scan_result(result)
    state.set_scan_progress(
        {
            "status": "done",
            "files_scanned": result.get("files_scanned", 0),
            "total_files": total_files,
            "findings_count": result.get("summary", {}).get("total", 0),
            "elapsed_ms": result.get("elapsed_ms", elapsed_ms),
        }
    )

    if state.debug:
        logger.debug(
            "background scan done — %s files, %s findings, elapsed=%.0fms",
            result.get("files_scanned", "?"),
            result.get("summary", {}).get("total", "?"),
            elapsed_ms,
        )
    logger.info(
        "[scan] done — %s files, %s findings", result.get("files_scanned", 0), result.get("summary", {}).get("total", 0)
    )


def browse_directory(path: str) -> BrowseResult:
    """List directory contents for the file browser."""
    try:
        p = Path(path).resolve()
        if not _is_path_allowed(p):
            return {"error": f"Access denied — path outside allowed roots: {path}"}
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

        parent = _fwd(str(p.parent)) if p.parent != p and _is_path_allowed(p.parent) else None
        return {"current": _fwd(str(p)), "parent": parent, "items": items}
    except Exception as e:
        logger.debug("browse_directory error: %s", e)
        return {"error": str(e)}


def get_drives() -> list[DriveInfo]:
    """List available drives (Windows) or root (Unix)."""
    if platform.system() == "Windows":
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:/"
            if os.path.exists(drive):
                drives.append({"name": f"{letter}:", "path": drive, "is_dir": True})
        return drives
    return [{"name": "/", "path": "/", "is_dir": True}]


def execute_monkey_tests(base_url: str):
    """Run monkey tests in background thread."""
    proc_lines: list[str] = []
    repo_root = str(ROOT)
    test_file = str(Path(repo_root) / "tests" / "test_monkey.py")
    proc = None

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=repo_root,
            encoding="utf-8",
            errors="replace",
        )
        passed = 0
        failed = 0
        for line in proc.stdout:
            proc_lines.append(line.rstrip())
            if " PASSED" in line:
                passed += 1
            elif " FAILED" in line:
                failed += 1
            state.monkey_test_progress = {
                "status": "running",
                "passed": passed,
                "failed": failed,
                "line_count": len(proc_lines),
                "last_line": proc_lines[-1] if proc_lines else "",
            }
        proc.wait(timeout=300)
        state.monkey_test_results = {
            "status": "done",
            "exit_code": proc.returncode,
            "passed": passed,
            "failed": failed,
            "total": passed + failed,
            "output": "\n".join(proc_lines[-200:]),
        }
        state.monkey_test_progress = {"status": "done"}
    except subprocess.TimeoutExpired:
        logger.warning("Monkey tests timed out after 300s, killing process")
        if proc:
            proc.kill()
            proc.wait()
        state.monkey_test_results = {
            "status": "error",
            "error": "Monkey tests timed out after 300 seconds",
            "output": "\n".join(proc_lines[-100:]),
        }
        state.monkey_test_progress = {"status": "done"}
    except Exception as e:
        logger.debug("Monkey test error: %s", e)
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        state.monkey_test_results = {
            "status": "error",
            "error": str(e),
            "output": "\n".join(proc_lines[-100:]),
        }
        state.monkey_test_progress = {"status": "done"}


def execute_wire_test(directory: str, base_url: str):
    """Run wire connector tests in background thread."""
    from xray.wire_connector import WireConnector

    wc = WireConnector(base_url)

    def callback(p):
        state.wire_test_progress = p

    results = wc.run_tests(directory, callback)
    state.wire_test_results = results
    state.wire_test_progress = {"status": "done", "results": results}
