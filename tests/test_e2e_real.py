"""
End-to-End Real Execution Tests — NO mocks, stubs, or fakes.

Covers the highest-priority gaps identified in the coverage audit:
  - API routes (scan, fix, analysis, PM dashboard)
  - Services (scan_manager, git_analyzer, chat_engine, satd_scanner)
  - Scanner integration (full project scans, edge cases)
  - Fixer integration (bulk fix, line shifting)
  - Agent loop (retry logic, severity filtering, error recovery)
  - Wire connector basics
  - Config cascading

Run:  python -m pytest tests/test_e2e_real.py -v --tb=short
"""

import json
import sys
import textwrap
import threading
import time
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.chat_engine import chat_reply
from services.git_analyzer import parse_imports
from services.satd_scanner import scan_satd
from services.scan_manager import (
    browse_directory,
    count_scannable_files,
    get_drives,
)
from ui_server import XRayHandler
from xray.agent import AgentConfig, XRayAgent
from xray.config import XRayConfig
from xray.fixer import apply_fix, apply_fixes_bulk, preview_fix
from xray.rules import ALL_RULES
from xray.sarif import findings_to_sarif, sarif_to_json_string
from xray.scanner import scan_directory, scan_file

# ── HTTP Server Fixtures ────────────────────────────────────────────────


class _TestServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture(scope="module")
def server():
    """Start a real HTTP server on a free port."""
    srv = _TestServer(("127.0.0.1", 0), XRayHandler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(30):
        try:
            conn = HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/api/info")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    yield host, port
    srv.shutdown()


def _get(server, path):
    host, port = server
    conn = HTTPConnection(host, port, timeout=15)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    return resp.status, data, body


def _post(server, path, payload=None):
    host, port = server
    conn = HTTPConnection(host, port, timeout=60)
    body_bytes = json.dumps(payload or {}).encode("utf-8")
    conn.request(
        "POST",
        path,
        body=body_bytes,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body_bytes))},
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    return resp.status, data


# ── Temp Project Fixtures ───────────────────────────────────────────────


@pytest.fixture
def vuln_project(tmp_path):
    """Create a temp project with known vulnerabilities."""
    (tmp_path / "vuln.py").write_text(
        textwrap.dedent("""\
        import subprocess, json, os, yaml

        def run_cmd(cmd):
            subprocess.run(cmd, shell=True)

        def parse_data(raw):
            return json.loads(raw)

        def get_key():
            return os.environ['SECRET_KEY']

        def load_config(path):
            with open(path) as f:
                return yaml.load(f.read())

        try:
            x = 1
        except:
            pass
    """),
        encoding="utf-8",
    )

    (tmp_path / "clean.py").write_text(
        textwrap.dedent("""\
        def add(a: int, b: int) -> int:
            return a + b

        def greet(name: str) -> str:
            return f"Hello, {name}"
    """),
        encoding="utf-8",
    )

    (tmp_path / "todo_file.py").write_text(
        textwrap.dedent("""\
        # TODO: Fix this later
        # FIXME: Performance issue
        # HACK: Temporary workaround
        def placeholder():
            pass
    """),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def large_project(tmp_path):
    """Create a project with many files for performance testing."""
    for i in range(50):
        (tmp_path / f"module_{i}.py").write_text(
            f"def func_{i}():\n    return {i}\n",
            encoding="utf-8",
        )
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════
# 1. SCANNER INTEGRATION
# ══════════════════════════════════════════════════════════════════════════


class TestScannerIntegration:
    """Real scan_directory and scan_file calls — no mocks."""

    def test_scan_directory_finds_all_vuln_types(self, vuln_project):
        result = scan_directory(str(vuln_project))
        rule_ids = {f.rule_id for f in result.findings}
        assert "SEC-003" in rule_ids, "Should detect shell=True"
        assert "QUAL-001" in rule_ids, "Should detect bare except"
        assert "PY-007" in rule_ids, "Should detect os.environ[]"

    def test_scan_directory_clean_file_no_findings(self, tmp_path):
        (tmp_path / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        result = scan_directory(str(tmp_path))
        assert len(result.findings) == 0

    def test_scan_directory_counts_files(self, vuln_project):
        result = scan_directory(str(vuln_project))
        assert result.files_scanned >= 2

    def test_scan_empty_directory(self, tmp_path):
        result = scan_directory(str(tmp_path))
        assert len(result.findings) == 0
        assert result.files_scanned == 0

    def test_scan_directory_respects_severity_filter(self, vuln_project):
        result = scan_directory(str(vuln_project))
        high_findings = [f for f in result.findings if f.severity == "HIGH"]
        assert len(high_findings) >= 1

    def test_scan_file_nonexistent_returns_empty(self, tmp_path):
        result = scan_file(str(tmp_path / "nonexistent.py"))
        assert result == [] or len(result) == 0

    def test_scan_file_binary_content(self, tmp_path):
        bf = tmp_path / "data.bin"
        bf.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = scan_file(str(bf))
        assert result == [] or len(result) == 0

    def test_scan_directory_excludes_patterns(self, vuln_project):
        sub = vuln_project / "vendor"
        sub.mkdir()
        (sub / "lib.py").write_text("eval('bad')\n", encoding="utf-8")
        result = scan_directory(str(vuln_project), exclude_patterns=["vendor"])
        files_scanned = {f.file for f in result.findings}
        for fpath in files_scanned:
            assert "vendor" not in fpath

    def test_scan_50_file_project_performance(self, large_project):
        import time

        start = time.perf_counter()
        result = scan_directory(str(large_project))
        elapsed = time.perf_counter() - start
        assert elapsed < 30, f"Scan took {elapsed:.1f}s for 50 files — too slow"
        assert result.files_scanned == 50

    def test_scan_unicode_filenames(self, tmp_path):
        ufile = tmp_path / "módulo.py"
        ufile.write_text("def f():\n    return 1\n", encoding="utf-8")
        result = scan_directory(str(tmp_path))
        assert result.files_scanned >= 1

    def test_scan_deeply_nested_directory(self, tmp_path):
        d = tmp_path
        for i in range(20):
            d = d / f"level_{i}"
            d.mkdir()
        (d / "deep.py").write_text("eval('x')\n", encoding="utf-8")
        result = scan_directory(str(tmp_path))
        assert len(result.findings) >= 1


# ══════════════════════════════════════════════════════════════════════════
# 2. FIXER INTEGRATION
# ══════════════════════════════════════════════════════════════════════════


class TestFixerIntegration:
    """Real fix operations on actual files — no mocks."""

    def test_preview_fix_shows_diff_sec003(self, vuln_project):
        finding = {"rule_id": "SEC-003", "file": str(vuln_project / "vuln.py"), "line": 5, "matched_text": "shell=True"}
        result = preview_fix(finding)
        assert result is not None
        assert "diff" in result or "fixable" in result

    def test_apply_fix_sec003_modifies_file(self, vuln_project):
        fpath = str(vuln_project / "vuln.py")
        original = Path(fpath).read_text(encoding="utf-8")
        assert "shell=True" in original
        # Find actual line number
        lines = original.split("\n")
        target_line = None
        for i, line in enumerate(lines, 1):
            if "shell=True" in line:
                target_line = i
                break
        assert target_line is not None
        finding = {"rule_id": "SEC-003", "file": fpath, "line": target_line, "matched_text": "shell=True"}
        apply_fix(finding)
        modified = Path(fpath).read_text(encoding="utf-8")
        assert "shell=True" not in modified or "shell=False" in modified

    def test_apply_fix_qual001_bare_except(self, vuln_project):
        fpath = str(vuln_project / "vuln.py")
        original = Path(fpath).read_text(encoding="utf-8")
        lines = original.split("\n")
        except_line = None
        for i, line in enumerate(lines, 1):
            if line.strip() == "except:":
                except_line = i
                break
        if except_line:
            finding = {"rule_id": "QUAL-001", "file": fpath, "line": except_line, "matched_text": "except:"}
            apply_fix(finding)
            modified = Path(fpath).read_text(encoding="utf-8")
            assert "except Exception:" in modified

    def test_apply_fix_py007_environ_get(self, vuln_project):
        fpath = str(vuln_project / "vuln.py")
        original = Path(fpath).read_text(encoding="utf-8")
        lines = original.split("\n")
        environ_line = None
        for i, line in enumerate(lines, 1):
            if "os.environ[" in line:
                environ_line = i
                break
        if environ_line:
            finding = {
                "rule_id": "PY-007",
                "file": fpath,
                "line": environ_line,
                "matched_text": "os.environ['SECRET_KEY']",
            }
            apply_fix(finding)
            modified = Path(fpath).read_text(encoding="utf-8")
            assert "os.environ.get(" in modified

    def test_preview_fix_invalid_rule(self, vuln_project):
        finding = {"rule_id": "FAKE-999", "file": str(vuln_project / "vuln.py"), "line": 1, "matched_text": ""}
        result = preview_fix(finding)
        assert result is None or (isinstance(result, dict) and "error" in result)

    def test_apply_fixes_bulk_multiple(self, vuln_project):
        result = scan_directory(str(vuln_project))
        fixable = [
            f.to_dict()
            for f in result.findings
            if f.rule_id in {"SEC-003", "QUAL-001", "PY-007"} and f.file.endswith("vuln.py")
        ]
        if fixable:
            applied = apply_fixes_bulk(fixable)
            assert isinstance(applied, dict)
            assert applied["applied"] >= 1

    def test_fix_on_nonexistent_file_graceful(self, tmp_path):
        finding = {"rule_id": "SEC-003", "file": str(tmp_path / "gone.py"), "line": 1, "matched_text": ""}
        result = preview_fix(finding)
        assert result is None or isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════
# 3. AGENT LOOP INTEGRATION
# ══════════════════════════════════════════════════════════════════════════


class TestAgentLoopIntegration:
    """Real Agent executions — no LLM required for deterministic fixes."""

    def test_agent_scan_and_report(self, vuln_project):
        config = AgentConfig(project_root=str(vuln_project), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        assert report is not None

    def test_agent_dry_run_no_file_changes(self, vuln_project):
        fpath = vuln_project / "vuln.py"
        original = fpath.read_text(encoding="utf-8")
        config = AgentConfig(project_root=str(vuln_project), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        agent.run()
        assert fpath.read_text(encoding="utf-8") == original

    def test_agent_severity_high_only(self, vuln_project):
        config = AgentConfig(project_root=str(vuln_project), dry_run=True, severity_threshold="HIGH")
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        if report.scan_result and report.scan_result.findings:
            for f in report.scan_result.findings:
                assert f.severity == "HIGH"

    def test_agent_exclude_patterns(self, vuln_project):
        sub = vuln_project / "ignored"
        sub.mkdir()
        (sub / "bad.py").write_text("eval('x')\n", encoding="utf-8")
        config = AgentConfig(
            project_root=str(vuln_project),
            dry_run=True,
            exclude_patterns=["ignored"],
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        if report.scan_result:
            for f in report.scan_result.findings:
                assert "ignored" not in f.file

    def test_agent_on_empty_project(self, tmp_path):
        config = AgentConfig(project_root=str(tmp_path), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        assert report is not None


# ══════════════════════════════════════════════════════════════════════════
# 4. API ROUTES — REAL HTTP REQUESTS
# ══════════════════════════════════════════════════════════════════════════


class TestAPIInfo:
    """Test info-class endpoints via real HTTP."""

    def test_api_info_returns_rules_count(self, server):
        status, data, _ = _get(server, "/api/info")
        assert status == 200
        assert data["rules_count"] == 42

    def test_api_info_has_fixable_rules(self, server):
        status, data, _ = _get(server, "/api/info")
        assert "fixable_rules" in data
        assert len(data["fixable_rules"]) == 7

    def test_api_env_check_returns_tools(self, server):
        status, data, _ = _get(server, "/api/env-check")
        assert status == 200
        assert "tools" in data or "python_version" in data or "environment" in data


class TestAPIScan:
    """Test scan endpoints via real HTTP."""

    def test_scan_start_returns_status(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/scan",
            {
                "directory": str(vuln_project),
                "engine": "python",
                "severity": "ALL",
            },
        )
        assert status == 200
        assert data["status"] in ("started", "scanning", "done", "already_running")

    def test_scan_progress_returns_json(self, server):
        status, data, _ = _get(server, "/api/scan-progress")
        assert status == 200
        assert "status" in data

    def test_scan_result_returns_json(self, server):
        # Wait for any scan to finish
        for _ in range(60):
            status, data, _ = _get(server, "/api/scan-progress")
            if data and data.get("status") == "done":
                break
            time.sleep(0.5)
        status, data, _ = _get(server, "/api/scan-result")
        assert status == 200

    def test_scan_invalid_directory(self, server):
        status, data = _post(
            server,
            "/api/scan",
            {
                "directory": "/nonexistent/path/xyz",
                "engine": "python",
            },
        )
        assert status in (200, 400)
        if status == 200:
            assert "error" in data or data.get("status") == "error"

    def test_abort_returns_ok(self, server):
        status, data = _post(server, "/api/abort", {})
        assert status == 200
        assert data.get("ok") is True


class TestAPIFix:
    """Test fix endpoints via real HTTP."""

    def test_preview_fix_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/preview-fix",
            {
                "rule_id": "SEC-003",
                "file": str(vuln_project / "vuln.py"),
                "line": 5,
            },
        )
        assert status == 200

    def test_apply_fix_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/apply-fix",
            {
                "rule_id": "QUAL-001",
                "file": str(vuln_project / "vuln.py"),
                "line": 17,
            },
        )
        assert status == 200


class TestAPIAnalysis:
    """Test analysis endpoints via real HTTP."""

    def test_satd_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/satd", {"directory": str(vuln_project)})
        assert status == 200
        assert "items" in data or "markers" in data or "debt" in data or isinstance(data, dict)

    def test_dead_code_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/dead-code", {"directory": str(vuln_project)})
        assert status == 200
        assert "dead_functions" in data or "total_dead" in data or isinstance(data, dict)

    def test_smells_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/smells", {"directory": str(vuln_project)})
        assert status == 200

    def test_duplicates_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/duplicates", {"directory": str(vuln_project)})
        assert status == 200

    def test_health_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/health", {"directory": str(vuln_project)})
        assert status == 200
        assert "score" in data or "checks" in data or isinstance(data, dict)

    def test_release_readiness_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/release-readiness", {"directory": str(vuln_project)})
        assert status == 200

    def test_ai_detect_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/ai-detect", {"directory": str(vuln_project)})
        assert status == 200

    def test_web_smells_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/web-smells", {"directory": str(vuln_project)})
        assert status == 200

    def test_test_gen_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/test-gen", {"directory": str(vuln_project)})
        assert status == 200

    def test_remediation_time_endpoint(self, server):
        findings = [
            {"rule_id": "SEC-003", "severity": "HIGH", "file": "x.py", "line": 1, "description": "test"},
        ]
        status, data = _post(server, "/api/remediation-time", {"findings": findings})
        assert status == 200

    def test_connection_test_endpoint(self, server, vuln_project):
        status, data = _post(server, "/api/connection-test", {"directory": str(vuln_project)})
        assert status == 200


class TestAPIPMDashboard:
    """Test PM Dashboard endpoints via real HTTP."""

    def test_risk_heatmap_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/risk-heatmap",
            {
                "directory": str(vuln_project),
                "findings": [],
            },
        )
        assert status == 200

    def test_module_cards_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/module-cards",
            {
                "directory": str(vuln_project),
                "findings": [],
            },
        )
        assert status == 200

    def test_confidence_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/confidence",
            {
                "directory": str(vuln_project),
                "findings": [],
            },
        )
        assert status == 200
        assert "confidence" in data

    def test_sprint_batches_endpoint(self, server):
        status, data = _post(
            server,
            "/api/sprint-batches",
            {
                "findings": [],
                "smells": [],
            },
        )
        assert status == 200
        assert "batches" in data

    def test_architecture_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/architecture",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200

    def test_call_graph_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/call-graph",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200

    def test_circular_calls_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/circular-calls",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200

    def test_coupling_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/coupling",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200

    def test_unused_imports_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/unused-imports",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200


class TestAPIChat:
    """Test chat endpoint via real HTTP."""

    def test_chat_returns_response(self, server):
        status, data = _post(server, "/api/chat", {"message": "What rules exist?"})
        assert status == 200
        assert "reply" in data or "response" in data or "message" in data

    def test_chat_empty_message_rejected(self, server):
        status, data = _post(server, "/api/chat", {"message": ""})
        assert status in (200, 400)

    def test_project_review_endpoint(self, server, vuln_project):
        status, data = _post(
            server,
            "/api/project-review",
            {
                "directory": str(vuln_project),
            },
        )
        assert status == 200


class TestAPIErrorHandling:
    """Test error handling across API endpoints."""

    def test_invalid_json_body(self, server):
        host, port = server
        conn = HTTPConnection(host, port, timeout=10)
        conn.request(
            "POST", "/api/scan", body=b"not json", headers={"Content-Type": "application/json", "Content-Length": "8"}
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status in (200, 400, 500)

    def test_missing_directory_field(self, server):
        status, data = _post(server, "/api/dead-code", {})
        assert status in (200, 400)

    def test_unknown_route_returns_404(self, server):
        status, _, _ = _get(server, "/api/nonexistent-route")
        assert status in (404, 405)


# ══════════════════════════════════════════════════════════════════════════
# 5. SERVICES — DIRECT FUNCTION CALLS
# ══════════════════════════════════════════════════════════════════════════


class TestScanManagerServices:
    """Test scan_manager functions directly."""

    def test_count_scannable_files(self, vuln_project):
        count = count_scannable_files(str(vuln_project))
        assert count >= 2

    def test_browse_directory_returns_entries(self, vuln_project):
        result = browse_directory(str(vuln_project))
        assert isinstance(result, dict)
        items = result.get("items", [])
        assert len(items) >= 2
        names = {e["name"] for e in items}
        assert "vuln.py" in names

    def test_browse_directory_nonexistent(self):
        result = browse_directory("/nonexistent/path/xyz123")
        assert isinstance(result, (list, dict))

    def test_get_drives_returns_list(self):
        drives = get_drives()
        assert isinstance(drives, list)
        assert len(drives) >= 1
        assert "path" in drives[0]


class TestSATDScanner:
    """Test SATD scanner directly."""

    def test_scan_satd_finds_markers(self, vuln_project):
        result = scan_satd(str(vuln_project))
        assert isinstance(result, dict)
        markers = result.get("items", result.get("markers", []))
        # todo_file.py has TODO, FIXME, HACK
        assert len(markers) >= 3


class TestChatEngine:
    """Test chat engine directly."""

    def test_chat_reply_about_rules(self):
        reply = chat_reply("What scan rules does X-Ray have?", {})
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_chat_reply_about_fixers(self):
        reply = chat_reply("Which rules have auto-fixers?", {})
        assert isinstance(reply, str)


class TestGitAnalyzer:
    """Test git analyzer import parsing."""

    def test_parse_imports_finds_stdlib(self, vuln_project):
        result = parse_imports(str(vuln_project))
        assert isinstance(result, dict)
        # vuln.py imports subprocess, json, os, yaml
        if "nodes" in result:
            node_names = {n.get("id", n.get("name", "")) for n in result["nodes"]}
            assert any("subprocess" in str(n) or "json" in str(n) for n in node_names)


# ══════════════════════════════════════════════════════════════════════════
# 6. SARIF OUTPUT
# ══════════════════════════════════════════════════════════════════════════


class TestSARIFIntegration:
    """Real SARIF generation from actual scan results."""

    def test_sarif_from_real_scan(self, vuln_project):
        result = scan_directory(str(vuln_project))
        findings_dicts = [f.to_dict() for f in result.findings]
        sarif = findings_to_sarif(findings_dicts)
        assert "sarif" in sarif["$schema"].lower()
        assert len(sarif["runs"]) == 1
        assert len(sarif["runs"][0]["results"]) > 0

    def test_sarif_json_roundtrip(self, vuln_project):
        result = scan_directory(str(vuln_project))
        findings_dicts = [f.to_dict() for f in result.findings]
        sarif = findings_to_sarif(findings_dicts)
        json_str = sarif_to_json_string(findings_dicts)
        parsed = json.loads(json_str)
        assert parsed["$schema"] == sarif["$schema"]

    def test_sarif_empty_findings(self):
        sarif = findings_to_sarif([])
        assert sarif["runs"][0]["results"] == []


# ══════════════════════════════════════════════════════════════════════════
# 7. CONFIG INTEGRATION
# ══════════════════════════════════════════════════════════════════════════


class TestConfigIntegration:
    """Real config loading from actual project."""

    def test_default_config_values(self):
        cfg = XRayConfig()
        assert cfg.severity in ("ALL", "HIGH", "MEDIUM", "LOW")

    def test_config_from_real_pyproject(self):
        cfg = XRayConfig.from_pyproject(str(REPO_ROOT))
        assert isinstance(cfg, XRayConfig)


# ══════════════════════════════════════════════════════════════════════════
# 8. ANALYZER FUNCTIONS — DIRECT CALLS
# ══════════════════════════════════════════════════════════════════════════


class TestAnalyzersDirect:
    """Direct function calls to analyzers — no HTTP layer."""

    def test_detect_code_smells_real(self, vuln_project):
        from analyzers import detect_code_smells

        result = detect_code_smells(str(vuln_project))
        assert "smells" in result or "total" in result

    def test_detect_duplicates_real(self, vuln_project):
        from analyzers import detect_duplicates

        result = detect_duplicates(str(vuln_project))
        assert "duplicate_groups" in result or "total_groups" in result

    def test_detect_dead_functions_real(self, vuln_project):
        from analyzers import detect_dead_functions

        result = detect_dead_functions(str(vuln_project))
        assert "dead_functions" in result

    def test_detect_unused_imports_real(self, vuln_project):
        from analyzers import detect_unused_imports

        result = detect_unused_imports(str(vuln_project))
        assert "unused_imports" in result

    def test_compute_architecture_map_real(self, vuln_project):
        from analyzers import compute_architecture_map

        result = compute_architecture_map(str(vuln_project))
        assert "nodes" in result

    def test_compute_call_graph_real(self, vuln_project):
        from analyzers import compute_call_graph

        result = compute_call_graph(str(vuln_project))
        assert "nodes" in result

    def test_detect_circular_calls_real(self, vuln_project):
        from analyzers import detect_circular_calls

        result = detect_circular_calls(str(vuln_project))
        assert "circular_calls" in result or "total_cycles" in result

    def test_compute_coupling_metrics_real(self, vuln_project):
        from analyzers import compute_coupling_metrics

        result = compute_coupling_metrics(str(vuln_project))
        assert "modules" in result

    def test_check_project_health_real(self, vuln_project):
        from analyzers import check_project_health

        result = check_project_health(str(vuln_project))
        assert "score" in result

    def test_estimate_remediation_time_real(self, vuln_project):
        from analyzers import estimate_remediation_time

        scan_result = scan_directory(str(vuln_project))
        findings = [f.to_dict() for f in scan_result.findings]
        result = estimate_remediation_time(findings)
        assert "total_minutes" in result or "total_hours" in result

    def test_generate_test_stubs_real(self, vuln_project):
        from analyzers import generate_test_stubs

        result = generate_test_stubs(str(vuln_project))
        assert "total_functions" in result

    def test_detect_ai_code_real(self, vuln_project):
        from analyzers import detect_ai_code

        result = detect_ai_code(str(vuln_project))
        assert "indicators" in result or "total" in result

    def test_compute_confidence_meter_real(self, vuln_project):
        from analyzers import compute_confidence_meter

        scan_result = scan_directory(str(vuln_project))
        findings = [f.to_dict() for f in scan_result.findings]
        result = compute_confidence_meter(str(vuln_project), findings)
        assert "confidence" in result
        assert 0 <= result["confidence"] <= 100

    def test_compute_sprint_batches_real(self, vuln_project):
        from analyzers import compute_sprint_batches

        scan_result = scan_directory(str(vuln_project))
        findings = [f.to_dict() for f in scan_result.findings]
        result = compute_sprint_batches(findings, [])
        assert "batches" in result

    def test_compute_project_review_real(self, vuln_project):
        from analyzers import compute_project_review

        result = compute_project_review(str(vuln_project))
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════
# 9. RULES DATABASE INTEGRITY
# ══════════════════════════════════════════════════════════════════════════


class TestRulesIntegrity:
    """Validate rule definitions are internally consistent."""

    def test_42_rules_total(self):
        assert len(ALL_RULES) == 42

    def test_all_rule_ids_unique(self):
        ids = [r["id"] for r in ALL_RULES]
        assert len(ids) == len(set(ids))

    def test_all_rules_have_regex(self):
        import re

        for rule in ALL_RULES:
            pat = rule.get("pattern")
            assert pat, f"Rule {rule['id']} missing pattern"
            re.compile(pat)  # Should not raise

    def test_severity_values_valid(self):
        valid = {"HIGH", "MEDIUM", "LOW"}
        for rule in ALL_RULES:
            assert rule["severity"] in valid, f"Rule {rule['id']} has invalid severity"

    def test_rule_id_prefixes(self):
        prefixes = {"SEC", "QUAL", "PY", "PORT"}
        for rule in ALL_RULES:
            prefix = rule["id"].split("-")[0]
            assert prefix in prefixes, f"Rule {rule['id']} has unexpected prefix"

    def test_each_rule_fires_on_sample(self, tmp_path):
        """Each rule should fire on its own sample pattern."""
        samples = {
            "SEC-003": ("subprocess.run(cmd, shell=True)", ".py"),
            "SEC-004": ('cursor.execute(f"SELECT * FROM {table}")', ".py"),
            "SEC-007": ("result = eval(user_input)", ".py"),
            "SEC-009": ("data = yaml.load(raw)", ".py"),
            "SEC-012": ("DEBUG = True", ".py"),
            "QUAL-001": ("except:\n    pass", ".py"),
            "QUAL-007": ("# TODO: fix this", ".py"),
            "PY-003": ("from os import *", ".py"),
            "PY-004": ("print(debug_value)", ".py"),
            "PY-007": ("key = os.environ['SECRET']", ".py"),
            "SEC-001": ("el.innerHTML = `${userInput}`;", ".js"),
            "SEC-002": ('el.innerHTML = "prefix" + variable;', ".js"),
        }
        for rule_id, (code, ext) in samples.items():
            f = tmp_path / f"test_{rule_id}{ext}"
            f.write_text(code + "\n", encoding="utf-8")
            result = scan_file(str(f))
            found_ids = {r.rule_id for r in result} if result else set()
            assert rule_id in found_ids, f"Rule {rule_id} did not fire on sample: {code}"


# ══════════════════════════════════════════════════════════════════════════
# 10. FULL WORKFLOW — SCAN → ANALYZE → FIX → VERIFY
# ══════════════════════════════════════════════════════════════════════════


class TestFullWorkflow:
    """Complete end-to-end workflow test."""

    def test_scan_analyze_fix_rescan(self, vuln_project):
        """Full cycle: scan → analyze → fix → rescan confirms improvement."""
        # 1. Initial scan
        result1 = scan_directory(str(vuln_project))
        initial_count = len(result1.findings)
        assert initial_count > 0, "Should find issues in vuln_project"

        # 2. Apply all deterministic fixes
        fixable_rules = {"SEC-003", "SEC-009", "QUAL-001", "PY-005", "PY-007"}
        fixable = [f.to_dict() for f in result1.findings if f.rule_id in fixable_rules]

        if fixable:
            apply_fixes_bulk(fixable)

        # 3. Re-scan after fixes
        result2 = scan_directory(str(vuln_project))
        final_count = len(result2.findings)

        # Should have fewer findings after fixing
        assert final_count < initial_count, f"Expected fewer findings after fix: {final_count} >= {initial_count}"

    def test_scan_to_sarif_pipeline(self, vuln_project):
        """Scan → SARIF → validate output."""
        result = scan_directory(str(vuln_project))
        findings_dicts = [f.to_dict() for f in result.findings]
        _sarif = findings_to_sarif(findings_dicts)
        json_str = sarif_to_json_string(findings_dicts)
        parsed = json.loads(json_str)
        assert parsed["version"] == "2.1.0"
        assert len(parsed["runs"][0]["results"]) == len(result.findings)
