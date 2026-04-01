"""
Dual-server exhaustive comparison test.

Starts both the Python server (port 8077) and the Rust server (port 8078),
runs every API endpoint against both, and reports:
  - PASS  : both return 2xx with structurally identical top-level keys
  - WARN  : both return 2xx but key sets differ
  - FAIL  : Rust returns non-2xx or raises (Python is the reference)
  - SKIP  : endpoint legitimately skipped (e.g. needs external tool)

Usage:
    python -m pytest tests/test_dual_server.py -v -s
  or:
    python tests/test_dual_server.py

Set the environment variable XRAY_TEST_DIR to the project to scan (default: the repo itself).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import requests

# ─── Configuration ────────────────────────────────────────────────────────────

PYTHON_PORT = 8077
RUST_PORT = 8078
PYTHON_BASE = f"http://127.0.0.1:{PYTHON_PORT}"
RUST_BASE = f"http://127.0.0.1:{RUST_PORT}"
REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = str(Path(os.environ.get("XRAY_TEST_DIR", str(REPO_ROOT))).resolve())

# Timeout for each request (seconds)
REQUEST_TIMEOUT = 30
# How long to wait for servers to start
SERVER_START_WAIT = 6

# Endpoints that are genuinely expected to fail when tool not installed
TOOL_DEPENDENT = {"/api/ruff", "/api/bandit", "/api/typecheck", "/api/typecheck-pyright"}

# ─── Server fixtures ─────────────────────────────────────────────────────────


def _wait_for_server(base_url: str, timeout: float = SERVER_START_WAIT) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            r = requests.get(f"{base_url}/api/info", timeout=2)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _is_server_running(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/api/info", timeout=2)
        return r.status_code < 500
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def ensure_servers():
    """Ensure both servers are running (start them if not)."""
    procs = []

    if not _is_server_running(PYTHON_BASE):
        print(f"\nStarting Python server on port {PYTHON_PORT}…")
        p = subprocess.Popen(
            [sys.executable, "ui_server.py", "--port", str(PYTHON_PORT)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(p)
        assert _wait_for_server(PYTHON_BASE, 12), "Python server failed to start"

    rust_exe = REPO_ROOT / "xray-scanner.exe"
    if not rust_exe.exists():
        rust_exe = REPO_ROOT / "scanner" / "target" / "x86_64-pc-windows-msvc" / "release" / "xray-scanner.exe"
    if not _is_server_running(RUST_BASE):
        print(f"\nStarting Rust server on port {RUST_PORT}…")
        p = subprocess.Popen(
            [str(rust_exe), "--serve", "--port", str(RUST_PORT)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(p)
        assert _wait_for_server(RUST_BASE, 12), "Rust server failed to start"

    yield

    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def post(base: str, path: str, body: dict, timeout: int = REQUEST_TIMEOUT):
    return requests.post(f"{base}{path}", json=body, timeout=timeout)


def get(base: str, path: str, params: dict | None = None, timeout: int = REQUEST_TIMEOUT):
    return requests.get(f"{base}{path}", params=params or {}, timeout=timeout)


def top_keys(data: Any) -> set[str]:
    if isinstance(data, dict):
        return set(data.keys())
    return set()


def _cmp(endpoint: str, py_r, rs_r, body: dict) -> dict:
    """Compare a Python and Rust response, return a result dict."""
    result = {
        "endpoint": endpoint,
        "py_status": py_r.status_code,
        "rs_status": rs_r.status_code if rs_r else None,
        "status": "PASS",
        "notes": [],
    }

    # Python failed → not our problem
    if py_r.status_code >= 400:
        result["status"] = "SKIP"
        result["notes"].append(f"Python returned {py_r.status_code}")
        return result

    try:
        py_data = py_r.json()
    except Exception:
        result["status"] = "SKIP"
        result["notes"].append("Python returned non-JSON")
        return result

    if rs_r is None:
        result["status"] = "FAIL"
        result["notes"].append("Rust request raised exception")
        return result

    if rs_r.status_code >= 400:
        result["status"] = "FAIL"
        result["notes"].append(f"Rust returned HTTP {rs_r.status_code}")
        try:
            result["rs_body"] = rs_r.json()
        except Exception:
            result["rs_body"] = rs_r.text[:300]
        return result

    try:
        rs_data = rs_r.json()
    except Exception:
        result["status"] = "FAIL"
        result["notes"].append("Rust returned non-JSON")
        result["rs_body"] = rs_r.text[:300]
        return result

    py_keys = top_keys(py_data)
    rs_keys = top_keys(rs_data)

    missing = py_keys - rs_keys
    extra = rs_keys - py_keys

    if missing:
        result["status"] = "WARN"
        result["notes"].append(f"Rust missing keys: {sorted(missing)}")
    if extra:
        if result["status"] == "PASS":
            result["status"] = "WARN"
        result["notes"].append(f"Rust extra keys: {sorted(extra)}")

    # Check for error markers in Rust response that Python didn't have
    if "error" in rs_data and "error" not in py_data:
        result["status"] = "FAIL"
        result["notes"].append(f"Rust has error key: {rs_data['error']!r}")

    result["py_keys"] = sorted(py_keys)
    result["rs_keys"] = sorted(rs_keys)
    return result


# ─── Endpoint definitions ────────────────────────────────────────────────────

DIR_BODY = {"directory": TEST_DIR}


def _scan_and_get_findings(base: str) -> dict:
    """Run a full scan and return the result."""
    post(base, "/api/scan", DIR_BODY, timeout=60)
    # poll until done
    for _ in range(60):
        time.sleep(1)
        try:
            r = get(base, "/api/scan-result")
            if r.status_code == 200:
                data = r.json()
                if "findings" in data:
                    return data
        except Exception:
            pass
    return {}


@pytest.fixture(scope="session")
def scan_results(ensure_servers):
    """Run scans on both servers and cache results."""
    print(f"\nScanning {TEST_DIR} on Python server…")
    py_result = _scan_and_get_findings(PYTHON_BASE)
    print(f"Python scan: {len(py_result.get('findings', []))} findings")

    print(f"Scanning {TEST_DIR} on Rust server…")
    rs_result = _scan_and_get_findings(RUST_BASE)
    print(f"Rust scan: {len(rs_result.get('findings', []))} findings")

    return py_result, rs_result


# ─── GET endpoint tests ───────────────────────────────────────────────────────

class TestGetEndpoints:
    def _compare(self, path: str, params: dict | None = None):
        py_r = get(PYTHON_BASE, path, params)
        try:
            rs_r = get(RUST_BASE, path, params)
        except Exception as e:
            pytest.fail(f"{path}: Rust request failed: {e}")
        result = _cmp(path, py_r, rs_r, {})
        _print_result(result)
        assert result["status"] != "FAIL", f"{path} FAILED: {result['notes']}"

    def test_info(self):
        self._compare("/api/info")

    def test_browse_root(self):
        self._compare("/api/browse")

    def test_browse_dir(self):
        self._compare("/api/browse", {"path": TEST_DIR})

    def test_scan_result(self, scan_results):
        self._compare("/api/scan-result")

    def test_scan_progress(self):
        self._compare("/api/scan-progress")


# ─── Analysis POST endpoint tests ────────────────────────────────────────────

class TestAnalysisEndpoints:
    def _compare_post(self, path: str, body: dict | None = None):
        b = body if body is not None else DIR_BODY
        py_r = post(PYTHON_BASE, path, b)
        try:
            rs_r = post(RUST_BASE, path, b)
        except Exception as e:
            pytest.fail(f"{path}: Rust request failed: {e}")
        result = _cmp(path, py_r, rs_r, b)
        _print_result(result)
        # FAIL is always a test failure; WARN passes with a message
        assert result["status"] != "FAIL", f"{path} FAILED: {result['notes']}"

    def test_health(self):
        self._compare_post("/api/health")

    def test_smells(self):
        self._compare_post("/api/smells")

    def test_dead_code(self):
        self._compare_post("/api/dead-code")

    def test_duplicates(self):
        self._compare_post("/api/duplicates")

    def test_format(self):
        self._compare_post("/api/format")

    def test_typecheck(self):
        # May fail if 'ty' not installed — that's ok
        self._compare_post("/api/typecheck")

    def test_connection_test(self):
        self._compare_post("/api/connection-test")

    def test_release_readiness(self):
        self._compare_post("/api/release-readiness")

    def test_remediation_time(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])[:20]
        self._compare_post("/api/remediation-time", {"findings": findings})

    def test_satd(self):
        self._compare_post("/api/satd")

    def test_git_hotspots(self):
        self._compare_post("/api/git-hotspots", {**DIR_BODY, "days": 30})

    def test_imports(self):
        self._compare_post("/api/imports")

    def test_ruff(self):
        self._compare_post("/api/ruff")

    def test_bandit(self):
        self._compare_post("/api/bandit")

    def test_temporal_coupling(self):
        self._compare_post("/api/temporal-coupling", {**DIR_BODY, "days": 30})

    def test_ai_detect(self):
        self._compare_post("/api/ai-detect")

    def test_web_smells(self):
        self._compare_post("/api/web-smells")

    def test_test_gen(self):
        self._compare_post("/api/test-gen")

    def test_typecheck_pyright(self):
        self._compare_post("/api/typecheck-pyright")

    def test_typecheck_pyright_deprecated_field(self):
        """Both Python and Rust must return 'deprecated': true for pyright."""
        b = DIR_BODY
        py_r = post(PYTHON_BASE, "/api/typecheck-pyright", b).json()
        rs_r = post(RUST_BASE, "/api/typecheck-pyright", b).json()
        assert py_r.get("deprecated") is True, "Python missing deprecated flag"
        assert rs_r.get("deprecated") is True, "Rust missing deprecated flag"
        assert "deprecation_note" in py_r, "Python missing deprecation_note"
        assert "deprecation_note" in rs_r, "Rust missing deprecation_note"


# ─── PM Dashboard POST endpoint tests ────────────────────────────────────────

class TestDashboardEndpoints:
    def _compare_post(self, path: str, body: dict | None = None):
        b = body if body is not None else DIR_BODY
        py_r = post(PYTHON_BASE, path, b)
        try:
            rs_r = post(RUST_BASE, path, b)
        except Exception as e:
            pytest.fail(f"{path}: Rust request failed: {e}")
        result = _cmp(path, py_r, rs_r, b)
        _print_result(result)
        assert result["status"] != "FAIL", f"{path} FAILED: {result['notes']}"

    def test_risk_heatmap(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])
        self._compare_post("/api/risk-heatmap", {**DIR_BODY, "findings": findings})

    def test_module_cards(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])
        self._compare_post("/api/module-cards", {**DIR_BODY, "findings": findings})

    def test_confidence(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])
        self._compare_post("/api/confidence", {**DIR_BODY, "findings": findings})

    def test_sprint_batches(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])
        self._compare_post("/api/sprint-batches", {"findings": findings, "smells": []})

    def test_architecture(self):
        self._compare_post("/api/architecture")

    def test_call_graph(self):
        self._compare_post("/api/call-graph")

    def test_project_review(self, scan_results):
        py_result, _ = scan_results
        findings = py_result.get("findings", [])
        self._compare_post("/api/project-review", {
            **DIR_BODY,
            "findings": findings,
            "files_scanned": py_result.get("files_scanned", 0),
            "smells": [],
            "dead_functions": [],
        })

    def test_circular_calls(self):
        self._compare_post("/api/circular-calls")

    def test_coupling(self):
        self._compare_post("/api/coupling")

    def test_unused_imports(self):
        self._compare_post("/api/unused-imports")


# ─── Fix endpoint tests ───────────────────────────────────────────────────────

class TestFixEndpoints:
    def _compare_post(self, path: str, body: dict):
        py_r = post(PYTHON_BASE, path, body)
        try:
            rs_r = post(RUST_BASE, path, body)
        except Exception as e:
            pytest.fail(f"{path}: Rust request failed: {e}")
        result = _cmp(path, py_r, rs_r, body)
        _print_result(result)
        assert result["status"] != "FAIL", f"{path} FAILED: {result['notes']}"

    def test_preview_fix(self):
        body = {"file": str(REPO_ROOT / "xray" / "scanner.py"), "line": 1, "rule_id": "QUAL-001"}
        self._compare_post("/api/preview-fix", body)

    def test_apply_fix_dry(self):
        # Use a non-existent file so neither server actually modifies anything
        body = {"file": "/nonexistent/file.py", "line": 1, "rule_id": "QUAL-001"}
        self._compare_post("/api/apply-fix", body)


# ─── Reporter ─────────────────────────────────────────────────────────────────

_results: list[dict] = []


def _print_result(r: dict) -> None:
    status = r["status"]
    ep = r["endpoint"]
    notes = "; ".join(r.get("notes", []))
    symbol = {"PASS": "✓", "WARN": "~", "FAIL": "✗", "SKIP": "-"}.get(status, "?")
    line = f"  {symbol} [{status:4s}] {ep}"
    if notes:
        line += f"  →  {notes}"
    print(line)
    _results.append(r)


# ─── Summary session-finish hook ─────────────────────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    print("\n" + "=" * 70)
    print("DUAL-SERVER COMPARISON SUMMARY")
    print("=" * 70)
    by_status: dict[str, list[str]] = {"PASS": [], "WARN": [], "FAIL": [], "SKIP": []}
    for r in _results:
        by_status.setdefault(r["status"], []).append(r["endpoint"])
    for status in ("PASS", "WARN", "FAIL", "SKIP"):
        items = by_status.get(status, [])
        if items:
            print(f"\n{status} ({len(items)}):")
            for ep in items:
                print(f"    {ep}")
    total = len(_results)
    passed = len(by_status["PASS"])
    warned = len(by_status["WARN"])
    failed = len(by_status["FAIL"])
    skipped = len(by_status["SKIP"])
    print(f"\nTotal: {total}  PASS={passed}  WARN={warned}  FAIL={failed}  SKIP={skipped}")
    print("=" * 70)


# ─── Standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", "--tb=short"] + sys.argv[1:]))
