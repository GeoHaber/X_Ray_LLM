#!/usr/bin/env python3
"""
API Compatibility Test — Python vs Rust Server

Runs the same requests against both servers and compares response JSON shapes.
This catches transpilation drift: missing fields, wrong types, renamed keys.

Usage:
  # Start both servers first:
  #   python ui_server.py --port 8077          (Python)
  #   ./xray-scanner.exe --serve --port 8078   (Rust)
  # Then:
  pytest tests/test_api_compat.py -v

  # Or standalone:
  python tests/test_api_compat.py [--py-port 8077] [--rs-port 8078]

Can also be used as a post-transpile validation step.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Configuration ───────────────────────────────────────────────────────────

PY_PORT = 8077
RS_PORT = 8078

# A small, safe directory both servers can scan for comparison.
# Default: this project's own tests/ folder (small, deterministic)
SCAN_DIR = str(Path(__file__).resolve().parent)

# Maximum seconds to wait for a scan to finish when polling.
SCAN_TIMEOUT = 60

# ── HTTP helpers ────────────────────────────────────────────────────────────


def _get(port: int, path: str, params: dict | None = None) -> dict:
    """GET request returning parsed JSON."""
    url = f"http://127.0.0.1:{port}{path}"
    if params:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url += f"?{qs}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _post(port: int, path: str, body: dict | None = None) -> dict:
    """POST request returning parsed JSON."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def _trigger_scan(port: int, directory: str = SCAN_DIR, severity: str = "LOW") -> dict:
    """POST /api/scan, poll until done, GET /api/scan-result."""
    body = {"directory": directory, "engine": "rust" if port != PY_PORT else "python",
            "severity": severity, "excludes": []}
    start_resp = _post(port, "/api/scan", body)
    if "error" in start_resp:
        return start_resp

    deadline = time.monotonic() + SCAN_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(0.5)
        prog = _get(port, "/api/scan-progress")
        if prog.get("status") in ("done",):
            break
        # "idle" after enough polls means done (Rust pre-fix compat)
        if prog.get("status") == "idle" and (time.monotonic() - (deadline - SCAN_TIMEOUT)) > 3:
            break
    return _get(port, "/api/scan-result")


# ── Shape extraction ────────────────────────────────────────────────────────


def json_shape(obj: Any, path: str = "$") -> dict[str, str]:
    """
    Recursively extract {json_path: type_name} from a JSON value.

    Lists are sampled from element [0]. This gives a flat map of
    every key that appears in the response, e.g.:
        {"$.files_scanned": "int", "$.findings[0].rule_id": "str", ...}
    """
    result: dict[str, str] = {}
    if isinstance(obj, dict):
        result[path] = "object"
        for k, v in obj.items():
            result.update(json_shape(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        result[path] = "array"
        if obj:
            result.update(json_shape(obj[0], f"{path}[0]"))
    elif isinstance(obj, bool):
        result[path] = "bool"
    elif isinstance(obj, int):
        result[path] = "int"
    elif isinstance(obj, float):
        result[path] = "number"
    elif isinstance(obj, str):
        result[path] = "str"
    elif obj is None:
        result[path] = "null"
    else:
        result[path] = type(obj).__name__
    return result


# ── Comparison ──────────────────────────────────────────────────────────────


@dataclass
class Diff:
    endpoint: str
    missing_in_rust: list[str] = field(default_factory=list)
    missing_in_python: list[str] = field(default_factory=list)
    type_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Extra fields in Rust are backwards-compatible, not failures
        return not self.missing_in_rust and not self.type_mismatches


def compare_shapes(py_data: dict, rs_data: dict, endpoint: str) -> Diff:
    """Compare JSON shapes from both servers for one endpoint."""
    py_shape = json_shape(py_data)
    rs_shape = json_shape(rs_data)
    diff = Diff(endpoint=endpoint)

    # Detect array paths that are empty on one side (can't compare element shapes)
    py_arrays = {k for k, v in py_shape.items() if v == "array"}
    rs_arrays = {k for k, v in rs_shape.items() if v == "array"}
    empty_array_paths: set[str] = set()
    for arr_path in py_arrays | rs_arrays:
        elem_key = f"{arr_path}[0]"
        py_has_elem = any(k.startswith(elem_key) for k in py_shape)
        rs_has_elem = any(k.startswith(elem_key) for k in rs_shape)
        if py_has_elem != rs_has_elem:
            empty_array_paths.add(arr_path)

    # Detect dynamic dict paths (keys are data-dependent, e.g. filenames)
    # If both sides have the parent as "object" but different child keys, skip
    dynamic_paths: set[str] = set()
    for k in py_shape:
        parts = k.rsplit(".", 1)
        if len(parts) == 2:
            parent = parts[0]
            if py_shape.get(parent) == "object" and rs_shape.get(parent) == "object":
                # Count children under this parent in both
                py_children = [k2 for k2 in py_shape if k2.startswith(parent + ".") and k2.count(".") == parent.count(".") + 1]
                rs_children = [k2 for k2 in rs_shape if k2.startswith(parent + ".") and k2.count(".") == parent.count(".") + 1]
                if len(py_children) >= 3 and len(rs_children) >= 3:
                    # Both have multiple children — likely a dynamic dict
                    py_types = {py_shape[c] for c in py_children}
                    rs_types = {rs_shape[c] for c in rs_children}
                    if py_types == rs_types:
                        dynamic_paths.add(parent)

    for key, py_type in py_shape.items():
        # Skip element-level keys for empty arrays
        skip = False
        for arr in empty_array_paths:
            if key.startswith(f"{arr}[0]"):
                skip = True
                break
        # Skip dynamic dict children
        for dp in dynamic_paths:
            if key.startswith(dp + "."):
                skip = True
                break
        if skip:
            continue

        if key not in rs_shape:
            diff.missing_in_rust.append(f"{key} ({py_type})")
        elif rs_shape[key] != py_type:
            # Allow int/number mismatch (JSON doesn't distinguish)
            if {py_type, rs_shape[key]} <= {"int", "number"}:
                continue
            # Allow null vs specific type (optional field)
            if py_type == "null" or rs_shape[key] == "null":
                continue
            diff.type_mismatches.append(f"{key}: python={py_type}, rust={rs_shape[key]}")

    for key, rs_type in rs_shape.items():
        skip = False
        for arr in empty_array_paths:
            if key.startswith(f"{arr}[0]"):
                skip = True
                break
        for dp in dynamic_paths:
            if key.startswith(dp + "."):
                skip = True
                break
        if skip:
            continue
        if key not in py_shape:
            diff.missing_in_python.append(f"{key} ({rs_type})")

    return diff


# ── Endpoint test cases ─────────────────────────────────────────────────────

# Each test: (name, method, path, params_or_body)
# method: "GET" or "POST"
# For GET: params_or_body is query params dict
# For POST: params_or_body is JSON body dict


def get_test_cases(scan_dir: str) -> list[tuple[str, str, str, dict]]:
    """Return endpoint test cases. scan_dir is used for POST bodies."""
    return [
        # ── Core GET routes ───────────────────────────────────
        ("info", "GET", "/api/info", {}),
        ("browse_drives", "GET", "/api/browse", {}),
        ("browse_dir", "GET", "/api/browse", {"path": scan_dir}),
        ("scan_progress_idle", "GET", "/api/scan-progress", {}),

        # ── Scan workflow (triggered separately) ──────────────
        # scan-result is tested after trigger_scan()

        # ── POST analysis routes ──────────────────────────────
        ("health", "POST", "/api/health", {"directory": scan_dir}),
        ("smells", "POST", "/api/smells", {"directory": scan_dir}),
        ("dead_code", "POST", "/api/dead-code", {"directory": scan_dir}),
        ("duplicates", "POST", "/api/duplicates", {"directory": scan_dir}),
        ("format", "POST", "/api/format", {"directory": scan_dir}),
        ("typecheck", "POST", "/api/typecheck", {"directory": scan_dir}),
        ("connection_test", "POST", "/api/connection-test", {"directory": scan_dir}),
        ("release_readiness", "POST", "/api/release-readiness", {"directory": scan_dir}),
        ("remediation_time", "POST", "/api/remediation-time", {"findings": []}),

        # ── Graph / PM ────────────────────────────────────────
        ("circular_calls", "POST", "/api/circular-calls", {"directory": scan_dir}),
        ("coupling", "POST", "/api/coupling", {"directory": scan_dir}),
        ("unused_imports", "POST", "/api/unused-imports", {"directory": scan_dir}),
    ]


# ── Main runner ─────────────────────────────────────────────────────────────


def run_compat_tests(
    py_port: int = PY_PORT,
    rs_port: int = RS_PORT,
    scan_dir: str = SCAN_DIR,
    verbose: bool = True,
) -> list[Diff]:
    """Run all compatibility tests. Returns list of Diffs."""
    results: list[Diff] = []
    cases = get_test_cases(scan_dir)

    # ── 1. Test simple endpoints ──────────────────────────────────────
    for name, method, path, params_body in cases:
        if verbose:
            print(f"  Testing {name:25s} ({method} {path}) ... ", end="", flush=True)
        try:
            if method == "GET":
                py_resp = _get(py_port, path, params_body or None)
                rs_resp = _get(rs_port, path, params_body or None)
            else:
                py_resp = _post(py_port, path, params_body)
                rs_resp = _post(rs_port, path, params_body)

            diff = compare_shapes(py_resp, rs_resp, f"{method} {path}")
            results.append(diff)
            if verbose:
                print("OK" if diff.ok else "DIFF")
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")
            results.append(Diff(
                endpoint=f"{method} {path}",
                missing_in_rust=[f"Request failed: {e}"],
            ))

    # ── 2. Full scan + compare scan-result shapes ─────────────────────
    if verbose:
        print(f"  Testing {'scan_result':25s} (full scan workflow) ... ", end="", flush=True)
    try:
        py_result = _trigger_scan(py_port, scan_dir)
        rs_result = _trigger_scan(rs_port, scan_dir)
        diff = compare_shapes(py_result, rs_result, "GET /api/scan-result (after scan)")
        results.append(diff)
        if verbose:
            print("OK" if diff.ok else "DIFF")
    except Exception as e:
        if verbose:
            print(f"ERROR: {e}")
        results.append(Diff(
            endpoint="GET /api/scan-result (after scan)",
            missing_in_rust=[f"Scan failed: {e}"],
        ))

    # ── 3. Compare scan-progress when done ────────────────────────────
    if verbose:
        print(f"  Testing {'scan_progress_done':25s} (after scan) ... ", end="", flush=True)
    try:
        py_prog = _get(py_port, "/api/scan-progress")
        rs_prog = _get(rs_port, "/api/scan-progress")
        diff = compare_shapes(py_prog, rs_prog, "GET /api/scan-progress (done)")
        results.append(diff)
        if verbose:
            print("OK" if diff.ok else "DIFF")
    except Exception as e:
        if verbose:
            print(f"ERROR: {e}")
        results.append(Diff(
            endpoint="GET /api/scan-progress (done)",
            missing_in_rust=[f"Request failed: {e}"],
        ))

    return results


def print_report(diffs: list[Diff]) -> int:
    """Print a summary report and return exit code (0=pass, 1=fail)."""
    passed = sum(1 for d in diffs if d.ok)
    failed = [d for d in diffs if not d.ok]

    print(f"\n{'='*60}")
    print(f"  API Compatibility: {passed}/{len(diffs)} endpoints match")
    print(f"{'='*60}")

    if not failed:
        print("  All endpoints produce compatible JSON shapes!")
        return 0

    for d in failed:
        print(f"\n  FAIL: {d.endpoint}")
        for m in d.missing_in_rust:
            print(f"    [-rust]  {m}")
        for m in d.missing_in_python:
            print(f"    [-python] {m}")
        for m in d.type_mismatches:
            print(f"    [type]   {m}")

    print(f"\n  {len(failed)} endpoint(s) have incompatible shapes.")
    print("  Fix the Rust server to match the Python reference.\n")
    return 1


# ── Pytest integration ──────────────────────────────────────────────────────

def _servers_reachable() -> bool:
    """Check if both servers are running."""
    for port in (PY_PORT, RS_PORT):
        try:
            _get(port, "/api/info")
        except Exception:
            return False
    return True


try:
    import pytest

    @pytest.mark.skipif(not _servers_reachable(), reason="Both servers must be running (py=8077, rs=8078)")
    class TestAPICompat:
        """Pytest suite — runs when both servers are up."""

        def test_info_shape(self):
            py = _get(PY_PORT, "/api/info")
            rs = _get(RS_PORT, "/api/info")
            diff = compare_shapes(py, rs, "GET /api/info")
            assert diff.ok, _diff_msg(diff)

        def test_browse_drives_shape(self):
            py = _get(PY_PORT, "/api/browse")
            rs = _get(RS_PORT, "/api/browse")
            diff = compare_shapes(py, rs, "GET /api/browse (drives)")
            assert diff.ok, _diff_msg(diff)

        def test_browse_dir_shape(self):
            py = _get(PY_PORT, "/api/browse", {"path": SCAN_DIR})
            rs = _get(RS_PORT, "/api/browse", {"path": SCAN_DIR})
            diff = compare_shapes(py, rs, "GET /api/browse (dir)")
            assert diff.ok, _diff_msg(diff)

        def test_scan_progress_idle_shape(self):
            py = _get(PY_PORT, "/api/scan-progress")
            rs = _get(RS_PORT, "/api/scan-progress")
            diff = compare_shapes(py, rs, "GET /api/scan-progress (idle)")
            assert diff.ok, _diff_msg(diff)

        def test_scan_result_shape(self):
            """Full scan workflow: trigger scan on both, compare result shapes."""
            py = _trigger_scan(PY_PORT, SCAN_DIR)
            rs = _trigger_scan(RS_PORT, SCAN_DIR)
            diff = compare_shapes(py, rs, "GET /api/scan-result")
            assert diff.ok, _diff_msg(diff)

        def test_scan_progress_done_shape(self):
            """After scan, compare progress shapes."""
            # Ensure a scan completed on both
            _trigger_scan(PY_PORT, SCAN_DIR)
            _trigger_scan(RS_PORT, SCAN_DIR)
            py = _get(PY_PORT, "/api/scan-progress")
            rs = _get(RS_PORT, "/api/scan-progress")
            diff = compare_shapes(py, rs, "GET /api/scan-progress (done)")
            assert diff.ok, _diff_msg(diff)

        def test_health_shape(self):
            py = _post(PY_PORT, "/api/health", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/health", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/health")
            assert diff.ok, _diff_msg(diff)

        def test_smells_shape(self):
            py = _post(PY_PORT, "/api/smells", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/smells", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/smells")
            assert diff.ok, _diff_msg(diff)

        def test_dead_code_shape(self):
            py = _post(PY_PORT, "/api/dead-code", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/dead-code", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/dead-code")
            assert diff.ok, _diff_msg(diff)

        def test_duplicates_shape(self):
            py = _post(PY_PORT, "/api/duplicates", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/duplicates", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/duplicates")
            assert diff.ok, _diff_msg(diff)

        def test_format_shape(self):
            py = _post(PY_PORT, "/api/format", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/format", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/format")
            assert diff.ok, _diff_msg(diff)

        def test_remediation_time_shape(self):
            py = _post(PY_PORT, "/api/remediation-time", {"findings": []})
            rs = _post(RS_PORT, "/api/remediation-time", {"findings": []})
            diff = compare_shapes(py, rs, "POST /api/remediation-time")
            assert diff.ok, _diff_msg(diff)

        def test_circular_calls_shape(self):
            py = _post(PY_PORT, "/api/circular-calls", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/circular-calls", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/circular-calls")
            assert diff.ok, _diff_msg(diff)

        def test_coupling_shape(self):
            py = _post(PY_PORT, "/api/coupling", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/coupling", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/coupling")
            assert diff.ok, _diff_msg(diff)

        def test_unused_imports_shape(self):
            py = _post(PY_PORT, "/api/unused-imports", {"directory": SCAN_DIR})
            rs = _post(RS_PORT, "/api/unused-imports", {"directory": SCAN_DIR})
            diff = compare_shapes(py, rs, "POST /api/unused-imports")
            assert diff.ok, _diff_msg(diff)

    def _diff_msg(diff: Diff) -> str:
        parts = []
        for m in diff.missing_in_rust:
            parts.append(f"  missing in Rust: {m}")
        for m in diff.missing_in_python:
            parts.append(f"  extra in Rust: {m}")
        for m in diff.type_mismatches:
            parts.append(f"  type mismatch: {m}")
        return f"Shape mismatch for {diff.endpoint}:\n" + "\n".join(parts)

except ImportError:
    pass  # pytest not available — standalone mode only


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="API Compatibility Test — Python vs Rust Server")
    parser.add_argument("--py-port", type=int, default=PY_PORT, help="Python server port (default: 8077)")
    parser.add_argument("--rs-port", type=int, default=RS_PORT, help="Rust server port (default: 8078)")
    parser.add_argument("--scan-dir", type=str, default=SCAN_DIR, help="Directory to scan for comparison")
    args = parser.parse_args()

    print("API Compatibility Test")
    print(f"  Python server: http://127.0.0.1:{args.py_port}")
    print(f"  Rust server:   http://127.0.0.1:{args.rs_port}")
    print(f"  Scan target:   {args.scan_dir}")
    print()

    # Check servers are reachable
    for name, port in [("Python", args.py_port), ("Rust", args.rs_port)]:
        try:
            _get(port, "/api/info")
            print(f"  {name} server: OK")
        except Exception as e:
            print(f"  {name} server: UNREACHABLE ({e})")
            print("\nStart both servers first:")
            print(f"  python ui_server.py --port {args.py_port}")
            print(f"  ./xray-scanner.exe --serve --port {args.rs_port}")
            sys.exit(2)
    print()

    diffs = run_compat_tests(args.py_port, args.rs_port, args.scan_dir)
    code = print_report(diffs)
    sys.exit(code)
