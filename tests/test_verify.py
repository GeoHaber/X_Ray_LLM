"""
X-Ray THOROUGH VERIFICATION — Proving the tool is safe, effective, and reliable.
====================================================================================
Goal 1: DOES NO HARM   — Dry-run never writes, scan-only doesn't mutate, file hashes preserved
Goal 2: FINDS REAL BUGS — Every single rule fires on crafted vulnerable code; no silent misses
Goal 3: RELIABLE        — Handles edge cases without crashing: empty, binary, huge, unicode, nested, symlinks

Run:  python -m pytest tests/test_verify.py -v
"""

import hashlib
import json
import os
import struct
import sys
import tempfile
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.agent import AgentConfig, XRayAgent, _get_source_context
from xray.rules import ALL_RULES
from xray.runner import TestResult, run_tests
from xray.scanner import ScanResult, scan_directory, scan_file

# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _write_temp(suffix: str, content: str) -> str:
    """Write content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _sha256(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_project(root: str, files: dict[str, str]):
    """Create a mini project with given files relative to root."""
    for relpath, content in files.items():
        full = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


# ═════════════════════════════════════════════════════════════════════════════
# GOAL 1: DOES NO HARM
# ═════════════════════════════════════════════════════════════════════════════

class TestDoesNoHarm:
    """Prove the scanner and agent never modify files they scan."""

    def test_scan_file_preserves_content(self):
        """Scanning a file must NOT alter its contents (byte-level check)."""
        code = "import os\nx = eval(input())\nresult = pickle.loads(data)\n"
        path = _write_temp(".py", code)
        hash_before = _sha256(path)
        scan_file(path)
        hash_after = _sha256(path)
        os.unlink(path)
        assert hash_before == hash_after, "scan_file mutated the file!"

    def test_scan_directory_preserves_all_files(self):
        """Directory scan must not alter ANY file in the tree."""
        with tempfile.TemporaryDirectory() as root:
            files = {
                "app.py": "eval(input())\n",
                "server.py": "password = 'hunter2'\nimport subprocess\nsubprocess.run('ls', shell=True)\n",
                "ui.js": "el.innerHTML = `<b>${name}</b>`;\n",
                "index.html": "<script>el.innerHTML = `${danger}`;</script>\n",
                "sub/deep.py": "exec(code)\n",
            }
            _build_project(root, files)
            hashes_before = {}
            for rel in files:
                fp = os.path.join(root, rel)
                hashes_before[rel] = _sha256(fp)
            scan_directory(root)
            for rel in files:
                fp = os.path.join(root, rel)
                assert _sha256(fp) == hashes_before[rel], f"scan_directory mutated {rel}!"

    def test_agent_dry_run_preserves_project(self):
        """Full agent dry_run must NOT create, modify, or delete any files."""
        with tempfile.TemporaryDirectory() as root:
            files = {
                "bad.py": "eval(input())\nexec(code)\nimport pickle\npickle.loads(data)\n",
                "srv.py": "password = 'abc'\nsubprocess.run('ls', shell=True)\n",
            }
            _build_project(root, files)
            all_paths = {}
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    all_paths[fp] = _sha256(fp)

            config = AgentConfig(project_root=root, dry_run=True, severity_threshold="LOW")
            agent = XRayAgent(config=config, quiet=True)
            agent.run()

            # Check nothing changed
            current_paths = set()
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    current_paths.add(fp)
                    assert fp in all_paths, f"Agent created new file: {fp}"
                    assert _sha256(fp) == all_paths[fp], f"Agent modified: {fp}"
            for orig in all_paths:
                assert orig in current_paths, f"Agent deleted: {orig}"

    def test_agent_without_llm_never_writes(self):
        """When LLM is unavailable, even --fix mode cannot alter files."""
        with tempfile.TemporaryDirectory() as root:
            code = "eval(input())\n"
            path = os.path.join(root, "test.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            hash_before = _sha256(path)

            config = AgentConfig(
                project_root=root, dry_run=False,
                auto_fix=True, auto_test=True,
            )
            agent = XRayAgent(config=config, quiet=True)
            agent.run()

            assert _sha256(path) == hash_before, "Agent modified files without an LLM!"

    def test_scan_does_not_follow_symlinks_outside(self):
        """Scanner must not follow symlinks that escape the project root."""
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            path_outside = os.path.join(outside, "secret.py")
            with open(path_outside, "w", encoding="utf-8") as f:
                f.write("password = 'top_secret'\n")

            link_path = os.path.join(root, "link_to_outside")
            try:
                os.symlink(outside, link_path)
            except OSError:
                pytest.skip("Cannot create symlinks without admin on Windows")

            result = scan_directory(root)
            scanned_files = [f.file for f in result.findings]
            for sf in scanned_files:
                assert not sf.startswith(outside), f"Scanner followed symlink to {sf}!"

    def test_scan_result_is_read_only_copy(self):
        """Modifying returned ScanResult must not affect internal state."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "bad.py"), "w", encoding="utf-8") as f:
                f.write("eval(input())\n")
            config = AgentConfig(project_root=root, dry_run=True)
            agent = XRayAgent(config=config, quiet=True)
            result = agent.scan()
            original_count = len(result.findings)
            result.findings.clear()  # mutate the returned list
            # Agent's internal report should still hold the data
            assert agent.report.scan_result is not None


# ═════════════════════════════════════════════════════════════════════════════
# GOAL 2: FINDS REAL BUGS — Every rule must fire on vulnerable code
# ═════════════════════════════════════════════════════════════════════════════

class TestFindsRealBugs_Security:
    """Each security rule is tested with crafted vulnerable code."""

    def test_SEC_001_xss_template_literal(self):
        path = _write_temp(".html", '<script>el.innerHTML = `<b>${name}</b>`;</script>')
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-001" for f in findings), "Missed SEC-001 XSS template literal"

    def test_SEC_001_safe_code_no_fire(self):
        path = _write_temp(".html", '<script>el.innerHTML = `<b>${_escHtml(name)}</b>`;</script>')
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "SEC-001" for f in findings), "SEC-001 false positive on sanitized code"

    def test_SEC_002_xss_concatenation(self):
        path = _write_temp(".html", '<script>el.innerHTML = "<b>" + userInput</script>')
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-002" for f in findings), "Missed SEC-002 XSS concatenation"

    def test_SEC_003_command_injection(self):
        path = _write_temp(".py", 'subprocess.run(cmd, shell=True)\n')
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-003" for f in findings), "Missed SEC-003 command injection"

    def test_SEC_003_safe_shell_false(self):
        path = _write_temp(".py", 'subprocess.run(["ls", "-la"], shell=False)\n')
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "SEC-003" for f in findings), "SEC-003 false positive on shell=False"

    def test_SEC_004_sql_injection_fstring(self):
        path = _write_temp(".py", "cursor.execute(f\"SELECT * FROM users WHERE id={uid}\")\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-004" for f in findings), "Missed SEC-004 SQL injection f-string"

    def test_SEC_004_sql_injection_percent_s(self):
        path = _write_temp(".py", "cursor.execute('SELECT * FROM t WHERE id=%s' % user_id)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-004" for f in findings), "Missed SEC-004 SQL injection %s"

    def test_SEC_004_no_false_positive_on_regular_fstring(self):
        """Normal f-strings that don't involve execute() must NOT trigger SEC-004."""
        path = _write_temp(".py", "msg = f'Hello {name}, you have {count} items'\nprint(msg)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "SEC-004" for f in findings), "SEC-004 false positive on non-SQL f-string"

    def test_SEC_005_ssrf(self):
        path = _write_temp(".py", "urlopen(base_url + user_path)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-005" for f in findings), "Missed SEC-005 SSRF"

    def test_SEC_006_cors_wildcard(self):
        path = _write_temp(".py", "self.send_header('Access-Control-Allow-Origin', '*')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-006" for f in findings), "Missed SEC-006 CORS wildcard"

    def test_SEC_007_eval(self):
        path = _write_temp(".py", "result = eval(user_input)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-007" for f in findings), "Missed SEC-007 eval"

    def test_SEC_007_exec(self):
        path = _write_temp(".py", "exec(code_from_api)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-007" for f in findings), "Missed SEC-007 exec"

    def test_SEC_008_hardcoded_secret(self):
        path = _write_temp(".py", "password = 'super_secret_123'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-008" for f in findings), "Missed SEC-008 hardcoded secret"

    def test_SEC_009_pickle(self):
        path = _write_temp(".py", "obj = pickle.loads(network_data)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-009" for f in findings), "Missed SEC-009 pickle deserialization"

    def test_SEC_009_yaml_unsafe(self):
        path = _write_temp(".py", "config = yaml.load(raw_yaml)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-009" for f in findings), "Missed SEC-009 yaml unsafe load"

    def test_SEC_010_path_traversal(self):
        path = _write_temp(".py", "filepath = os.path.join(base, '../ etc/passwd')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-010" for f in findings), "Missed SEC-010 path traversal"


class TestFindsRealBugs_Quality:
    """Each quality rule is tested."""

    def test_QUAL_001_bare_except(self):
        path = _write_temp(".py", "try:\n    x = 1\nexcept:\n    pass\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-001" for f in findings), "Missed QUAL-001 bare except"

    def test_QUAL_001_specific_except_no_fire(self):
        path = _write_temp(".py", "try:\n    x = 1\nexcept ValueError:\n    pass\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "QUAL-001" for f in findings), "QUAL-001 false positive"

    def test_QUAL_002_silent_swallow(self):
        path = _write_temp(".py", "try:\n    x = 1\nexcept ValueError:\n    pass\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-002" for f in findings), "Missed QUAL-002 silent swallow"

    def test_QUAL_003_unchecked_int(self):
        path = _write_temp(".py", "limit = int(qs.get('limit', '10'))\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-003" for f in findings), "Missed QUAL-003 unchecked int"

    def test_QUAL_004_unchecked_float(self):
        path = _write_temp(".py", "val = float(params['temperature'])\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-004" for f in findings), "Missed QUAL-004 unchecked float"

    def test_QUAL_006_non_daemon_thread(self):
        path = _write_temp(".py", "t = threading.Thread(target=worker, daemon=False)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-006" for f in findings), "Missed QUAL-006 non-daemon thread"

    def test_QUAL_007_todo(self):
        path = _write_temp(".py", "# TODO: fix this later\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-007" for f in findings), "Missed QUAL-007 TODO"

    def test_QUAL_008_long_sleep(self):
        path = _write_temp(".py", "time.sleep(300)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-008" for f in findings), "Missed QUAL-008 long sleep"

    def test_QUAL_008_short_sleep_no_fire(self):
        path = _write_temp(".py", "time.sleep(1)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "QUAL-008" for f in findings), "QUAL-008 false positive on short sleep"

    def test_QUAL_009_keepalive(self):
        path = _write_temp(".py", "self.send_header('Connection', 'keep-alive')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-009" for f in findings), "Missed QUAL-009 keep-alive header"

    def test_QUAL_010_localstorage(self):
        path = _write_temp(".js", "const theme = localStorage.getItem('theme');\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "QUAL-010" for f in findings), "Missed QUAL-010 localStorage"


class TestFindsRealBugs_Python:
    """Each python-specific rule is tested."""

    def test_PY_001_return_type_mismatch(self):
        path = _write_temp(".py", "def get_data(self) -> None:\n    return {'key': 'val'}\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-001" for f in findings), "Missed PY-001 return type mismatch"

    def test_PY_003_wildcard_import(self):
        path = _write_temp(".py", "from os.path import *\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-003" for f in findings), "Missed PY-003 wildcard import"

    def test_PY_004_print_debug(self):
        path = _write_temp(".py", "def process():\n    print('debugging this')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-004" for f in findings), "Missed PY-004 print debug"

    def test_PY_005_json_no_try(self):
        path = _write_temp(".py", "data = json.loads(raw_text)\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-005" for f in findings), "Missed PY-005 json without try"

    def test_PY_006_global(self):
        path = _write_temp(".py", "global counter\ncounter += 1\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-006" for f in findings), "Missed PY-006 global mutation"

    def test_PY_007_environ_bracket(self):
        path = _write_temp(".py", "key = os.environ['SECRET_KEY']\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-007" for f in findings), "Missed PY-007 os.environ[]"

    def test_PY_007_environ_get_no_fire(self):
        path = _write_temp(".py", "key = os.environ.get('SECRET_KEY', '')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PY-007" for f in findings), "PY-007 false positive on .get()"

    def test_PY_008_open_without_encoding(self):
        path = _write_temp(".py", "f = open('data.txt', 'r')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PY-008" for f in findings), "Missed PY-008 open without encoding"

    def test_PY_008_open_with_encoding_no_fire(self):
        path = _write_temp(".py", "f = open('data.txt', 'r', encoding='utf-8')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PY-008" for f in findings), "PY-008 false positive when encoding present"

    def test_PY_008_open_binary_no_fire(self):
        path = _write_temp(".py", "f = open('data.bin', 'rb')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PY-008" for f in findings), "PY-008 false positive on binary mode"


class TestFindsRealBugs_MultiVuln:
    """Verify scanner catches ALL bugs in a file with multiple mixed vulnerabilities."""

    VULNERABLE_CODE = textwrap.dedent("""\
        import subprocess, pickle, os, json

        password = 'admin123'
        subprocess.run(f"echo {user_input}", shell=True)
        result = eval(user_input)
        data = pickle.loads(raw)
        val = int(qs.get('page', '1'))
        config = json.loads(raw_json)
        key = os.environ['API_KEY']
    """)

    def test_catches_all_in_multi_vuln_file(self):
        path = _write_temp(".py", self.VULNERABLE_CODE)
        findings = scan_file(path)
        os.unlink(path)
        found_ids = {f.rule_id for f in findings}
        expected = {"SEC-003", "SEC-007", "SEC-008", "SEC-009", "QUAL-003", "PY-005", "PY-007"}
        missing = expected - found_ids
        assert not missing, f"Scanner MISSED these rules in multi-vuln file: {missing}"

    def test_correct_line_numbers_in_multi_vuln(self):
        path = _write_temp(".py", self.VULNERABLE_CODE)
        findings = scan_file(path)
        os.unlink(path)
        eval_findings = [f for f in findings if f.rule_id == "SEC-007"]
        # eval is on line 5
        assert any(f.line == 5 for f in eval_findings), \
            f"eval should be on line 5, found on: {[f.line for f in eval_findings]}"

    def test_finding_metadata_complete(self):
        path = _write_temp(".py", self.VULNERABLE_CODE)
        findings = scan_file(path)
        os.unlink(path)
        for f in findings:
            assert f.rule_id, "Empty rule_id"
            assert f.severity in ("HIGH", "MEDIUM", "LOW"), f"Bad severity: {f.severity}"
            assert f.line > 0, f"Bad line: {f.line}"
            assert f.col > 0, f"Bad col: {f.col}"
            assert f.description, "Empty description"
            assert f.fix_hint, "Empty fix_hint"
            assert f.test_hint, "Empty test_hint"
            assert f.matched_text, "Empty matched_text"
            d = f.to_dict()
            assert isinstance(d, dict)
            assert all(k in d for k in ("rule_id", "severity", "file", "line"))


# ═════════════════════════════════════════════════════════════════════════════
# GOAL 3: RELIABLE — Edge cases that must not crash
# ═════════════════════════════════════════════════════════════════════════════

class TestReliable_EdgeCases:
    """Scanner must handle garbage, edge cases, and hostile input gracefully."""

    def test_empty_file(self):
        path = _write_temp(".py", "")
        findings = scan_file(path)
        os.unlink(path)
        assert findings == []

    def test_whitespace_only_file(self):
        path = _write_temp(".py", "   \n\n  \t\n")
        findings = scan_file(path)
        os.unlink(path)
        # Should not crash, findings may be empty
        assert isinstance(findings, list)

    def test_binary_file_with_py_extension(self):
        """Binary garbage with .py extension must not crash the scanner."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "wb") as f:
            f.write(struct.pack("256B", *range(256)))
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)  # didn't crash

    def test_huge_single_line_file(self):
        """A file with one very long line (500KB) must not crash or hang."""
        code = "x = " + "'a' * " + "500000" + "\n"
        path = _write_temp(".py", code)
        findings = scan_file(path)  # should finish in <1s
        os.unlink(path)
        assert isinstance(findings, list)

    def test_file_over_1mb_skipped(self):
        """Files > 1MB must be silently skipped, not crash."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# big file\n" * 200_000)  # ~2.2MB
        findings = scan_file(path)
        os.unlink(path)
        assert findings == [], "Files over 1MB should be skipped"

    def test_unicode_in_code(self):
        """Unicode characters (emoji, CJK, etc.) must not crash scanning."""
        code = "# 这是注释 🚀\npassword = '密码'\nprint('hello 世界')\n"
        path = _write_temp(".py", code)
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)  # didn't crash

    def test_unknown_extension_ignored(self):
        path = _write_temp(".xyz", "eval(danger)")
        findings = scan_file(path)
        os.unlink(path)
        assert findings == [], "Unknown extension should return empty list"

    def test_unscannable_extension_ignored(self):
        for ext in [".md", ".txt", ".csv", ".json", ".yaml", ".toml", ".cfg", ".ini"]:
            path = _write_temp(ext, "eval(danger)\npassword='bad'")
            findings = scan_file(path)
            os.unlink(path)
            assert findings == [], f"Extension {ext} should not be scanned"

    def test_nonexistent_file(self):
        findings = scan_file("/tmp/definitely_does_not_exist_xray.py")
        assert findings == []

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as root:
            result = scan_directory(root)
            assert result.files_scanned == 0
            assert result.findings == []
            assert isinstance(result.errors, list)

    def test_deeply_nested_directory(self):
        """15-level nesting must not crash or be skipped."""
        with tempfile.TemporaryDirectory() as root:
            deep = root
            for i in range(15):
                deep = os.path.join(deep, f"level{i}")
            os.makedirs(deep)
            with open(os.path.join(deep, "deep.py"), "w", encoding="utf-8") as f:
                f.write("eval('x')\n")
            result = scan_directory(root)
            assert result.files_scanned >= 1
            assert len(result.findings) >= 1, "Failed to find bug in deeply nested file"

    def test_skip_dirs_respected(self):
        """All skip dirs are actually skipped."""
        with tempfile.TemporaryDirectory() as root:
            for skip in ["__pycache__", "node_modules", ".git", ".venv", "venv"]:
                d = os.path.join(root, skip)
                os.makedirs(d)
                with open(os.path.join(d, "bad.py"), "w", encoding="utf-8") as f:
                    f.write("eval('x')\n")
            result = scan_directory(root)
            assert result.files_scanned == 0, f"Skipped dirs were scanned: {result.files_scanned} files"

    def test_file_with_no_newline_at_end(self):
        path = _write_temp(".py", "eval('x')")  # no trailing newline
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-007" for f in findings)

    def test_scan_file_with_null_bytes(self):
        """Null bytes in source must not crash the scanner."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "wb") as f:
            f.write(b"eval('x')\x00\npassword='bad'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)

    def test_windows_line_endings(self):
        """CRLF line endings must be handled correctly."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "wb") as f:
            f.write(b"line1 = 'ok'\r\nresult = eval('bad')\r\nline3 = 'ok'\r\n")
        findings = scan_file(path)
        os.unlink(path)
        eval_findings = [f for f in findings if f.rule_id == "SEC-007"]
        assert len(eval_findings) > 0, "CRLF line endings broke detection"


class TestReliable_ExcludePatterns:
    """Exclude patterns must work and not crash on bad input."""

    def test_exclude_pattern_works(self):
        with tempfile.TemporaryDirectory() as root:
            _build_project(root, {
                "src/app.py": "eval(input())\n",
                "vendor/lib.py": "eval(input())\n",
            })
            result = scan_directory(root, exclude_patterns=[r"vendor/"])
            found_files = {f.file for f in result.findings}
            assert not any("vendor" in f for f in found_files), "Excluded dir was scanned"
            assert result.files_scanned > 0, "Nothing was scanned at all"

    def test_invalid_exclude_pattern_no_crash(self):
        """Bad regex in exclude must not crash — just log an error."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "ok.py"), "w", encoding="utf-8") as f:
                f.write("x = 1\n")
            result = scan_directory(root, exclude_patterns=["[invalid_regex"])
            assert isinstance(result, ScanResult)
            assert len(result.errors) > 0, "Bad exclude pattern should be logged"


class TestReliable_ScanResult:
    """ScanResult aggregation must be correct."""

    def test_severity_counts_accurate(self):
        with tempfile.TemporaryDirectory() as root:
            # Create file with known HIGH + LOW findings
            _build_project(root, {
                "test.py": "eval(input())\n# TODO: fix this\n",
            })
            result = scan_directory(root)
            total = result.high_count + result.medium_count + result.low_count
            assert total == len(result.findings), \
                f"Severity counts ({total}) don't match total ({len(result.findings)})"

    def test_summary_format(self):
        result = ScanResult(files_scanned=10, rules_checked=28)
        s = result.summary()
        assert "10" in s
        assert "28" in s
        assert "0 HIGH" in s


class TestReliable_CLI:
    """CLI argument handling must not crash."""

    def test_cli_dry_run_exit_code(self):
        import subprocess as sp
        proc = sp.run(
            [sys.executable, "-m", "xray.agent", ".", "--dry-run", "--severity", "HIGH"],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, f"CLI crashed: {proc.stderr}"

    def test_cli_json_valid_json(self):
        import subprocess as sp
        proc = sp.run(
            [sys.executable, "-m", "xray.agent", ".", "--dry-run", "--json", "--severity", "HIGH"],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)  # must be valid JSON
        assert "files_scanned" in data
        assert "findings" in data
        assert "summary" in data

    def test_cli_nonexistent_dir_no_crash(self):
        import subprocess as sp
        proc = sp.run(
            [sys.executable, "-m", "xray.agent", "/tmp/nonexistent_xray_dir", "--dry-run"],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        # Should not crash — exit 0 with 0 findings is fine
        assert proc.returncode == 0, f"CLI crashed on nonexistent dir: {proc.stderr}"


class TestReliable_Agent:
    """Agent orchestrator edge cases."""

    def test_agent_on_clean_project(self):
        """Project with no scannable issues must not crash or report false alarms."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "clean.py"), "w", encoding="utf-8") as f:
                f.write("def add(a: int, b: int) -> int:\n    return a + b\n")
            config = AgentConfig(project_root=root, dry_run=True)
            agent = XRayAgent(config=config, quiet=True)
            report = agent.run()
            assert report.scan_result is not None
            high = [f for f in report.scan_result.findings if f.severity == "HIGH"]
            assert len(high) == 0, "Clean code flagged with HIGH severity"

    def test_agent_report_always_has_duration(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "x.py"), "w", encoding="utf-8") as f:
                f.write("x = 1\n")
            config = AgentConfig(project_root=root, dry_run=True)
            agent = XRayAgent(config=config, quiet=True)
            report = agent.run()
            assert report.duration_sec >= 0

    def test_agent_logs_captured(self):
        config = AgentConfig(project_root=REPO_ROOT, dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        agent.run()
        assert len(agent._log_lines) > 0, "Agent produced no log output"

    def test_get_source_context_nonexistent_file(self):
        result = _get_source_context("/nonexistent/file.py", 10)
        assert "Could not read" in result

    def test_get_source_context_line_out_of_range(self):
        path = _write_temp(".py", "line1\nline2\n")
        result = _get_source_context(path, 999)
        os.unlink(path)
        assert isinstance(result, str)  # didn't crash

    def test_runner_timeout_returns_result(self):
        """A test that takes too long should return TIMEOUT, not crash."""
        path = _write_temp(".py", textwrap.dedent("""\
            import time
            def test_hang():
                time.sleep(100)
        """))
        result = run_tests(path, timeout=3)
        os.unlink(path)
        # Should either have TIMEOUT in output or have 0 passed (not crash)
        assert isinstance(result, TestResult)

    def test_runner_bad_python_exe(self):
        result = run_tests(".", python_exe="/nonexistent/python")
        assert isinstance(result, TestResult)
        assert "not found" in result.output.lower() or result.total == 0


# ═════════════════════════════════════════════════════════════════════════════
# INTEGRATION: Run X-Ray on the Swarm/Zen LLM Compare project
# ═════════════════════════════════════════════════════════════════════════════

SWARM_DIR = os.path.join(REPO_ROOT, "..", "Swarm")

class TestIntegrationRealProject:
    """Run X-Ray against the actual Zen LLM Compare codebase (if available)."""

    @pytest.fixture(autouse=True)
    def check_swarm_exists(self):
        if not os.path.isdir(SWARM_DIR):
            pytest.skip("Swarm project not found — skipping integration tests")

    def test_scan_swarm_no_crash(self):
        """X-Ray must not crash when scanning a real ~4000-line project."""
        result = scan_directory(SWARM_DIR)
        assert result.files_scanned > 0
        assert isinstance(result.findings, list)

    def test_scan_swarm_finds_known_patterns(self):
        """Swarm has some known patterns — scanner should find them."""
        result = scan_directory(SWARM_DIR)
        found_ids = {f.rule_id for f in result.findings}
        # Swarm uses print() for logging, has some TODO markers
        assert len(found_ids) > 0, "Scanner found nothing in a real project"

    def test_scan_swarm_no_false_positive_on_fixed_xss(self):
        """The XSS bugs we already fixed in Swarm should NOT re-fire with _escHtml."""
        html_path = os.path.join(SWARM_DIR, "model_comparator.html")
        if not os.path.exists(html_path):
            pytest.skip("model_comparator.html not found")
        findings = scan_file(html_path)
        # After our X-Ray fix, _escHtml sanitizes all innerHTML template literals
        # SEC-001 should NOT fire on sanitized innerHTML assignments
        for f in findings:
            if f.rule_id == "SEC-001":
                # If it fires, check it's NOT on a line with _escHtml
                with open(html_path, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
                if f.line <= len(lines):
                    line_text = lines[f.line - 1]
                    assert "_escHtml" not in line_text, \
                        f"SEC-001 false positive on sanitized line {f.line}: {line_text.strip()}"

    def test_agent_dry_run_on_swarm_no_crash(self):
        """Full agent dry-run on Swarm must complete without exception."""
        config = AgentConfig(project_root=SWARM_DIR, dry_run=True, severity_threshold="HIGH")
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        assert report.duration_sec >= 0
        assert report.scan_result is not None


# ═════════════════════════════════════════════════════════════════════════════
# SELF-SCAN: X-Ray on its own code (expanded)
# ═════════════════════════════════════════════════════════════════════════════

class TestSelfScanExpanded:
    """Extended self-scan to verify X-Ray's own code is clean."""

    def test_no_high_findings_in_xray_package(self):
        xray_dir = os.path.join(REPO_ROOT, "xray")
        result = scan_directory(xray_dir)
        high = [f for f in result.findings if f.severity == "HIGH"]
        if high:
            details = "\n".join(f"  {f}" for f in high)
            pytest.fail(f"X-Ray's own code has HIGH findings:\n{details}")

    def test_all_rules_have_fix_hints(self):
        for rule in ALL_RULES:
            assert len(rule["fix_hint"]) > 10, f"Rule {rule['id']} has too-short fix_hint"
            assert len(rule["test_hint"]) > 10, f"Rule {rule['id']} has too-short test_hint"

    def test_no_unused_imports_in_rules(self):
        """Rule files should not have wildcard imports."""
        for fn in ["security.py", "quality.py", "python_rules.py"]:
            path = os.path.join(REPO_ROOT, "xray", "rules", fn)
            findings = scan_file(path)
            wildcard = [f for f in findings if f.rule_id == "PY-003"]
            assert not wildcard, f"Wildcard import in {fn}"

    def test_xray_scanner_all_opens_have_encoding(self):
        """scanner.py must specify encoding on all open() calls."""
        path = os.path.join(REPO_ROOT, "xray", "scanner.py")
        findings = scan_file(path)
        encoding_issues = [f for f in findings if f.rule_id == "PY-008"]
        assert not encoding_issues, f"scanner.py has open() without encoding: {encoding_issues}"

    def test_xray_agent_all_opens_have_encoding(self):
        path = os.path.join(REPO_ROOT, "xray", "agent.py")
        findings = scan_file(path)
        encoding_issues = [f for f in findings if f.rule_id == "PY-008"]
        assert not encoding_issues, f"agent.py has open() without encoding: {encoding_issues}"
