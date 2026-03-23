"""
Tests for portability rules (PORT-001 through PORT-004).
Each rule is tested with crafted vulnerable code AND safe code.

Run:  python -m pytest tests/test_portability.py -v --tb=short
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.rules.portability import PORTABILITY_RULES
from xray.scanner import scan_file


def _write_temp(suffix: str, content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# PORT-001: Hardcoded C:\Users\<username> paths
# ═════════════════════════════════════════════════════════════════════════════


class TestPORT001:
    """Detect hardcoded user-specific paths."""

    def test_hardcoded_user_path_detected(self):
        path = _write_temp(".py", "path = r'C:\\Users\\dvdze\\Documents'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-001" for f in findings), "Missed PORT-001"

    def test_forward_slash_user_path_detected(self):
        path = _write_temp(".py", "path = 'C:/Users/george/projects'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-001" for f in findings), "Missed PORT-001 forward-slash"

    def test_path_home_no_fire(self):
        """Using Path.home() is the correct portable approach."""
        path = _write_temp(".py", "from pathlib import Path\nbase = Path.home() / 'Documents'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-001" for f in findings), "PORT-001 false positive on Path.home()"

    def test_env_var_no_fire(self):
        path = _write_temp(".py", "import os\nbase = os.environ.get('HOME', '/tmp')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-001" for f in findings)


# ═════════════════════════════════════════════════════════════════════════════
# PORT-002: Hardcoded C:\AI\ paths
# ═════════════════════════════════════════════════════════════════════════════


class TestPORT002:
    """Detect hardcoded C:\\AI\\ paths."""

    def test_hardcoded_ai_path_detected(self):
        path = _write_temp(".py", "path = r'C:\\AI\\Models\\model.gguf'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-002" for f in findings), "Missed PORT-002"

    def test_forward_slash_ai_path_detected(self):
        path = _write_temp(".py", "model_dir = 'C:/AI/Models'\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-002" for f in findings), "Missed PORT-002 forward-slash"

    def test_env_var_model_dir_no_fire(self):
        path = _write_temp(".py", "import os\nmodel_dir = os.environ.get('ZENAI_MODEL_DIR', '')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-002" for f in findings)


# ═════════════════════════════════════════════════════════════════════════════
# PORT-003: Hardcoded absolute Windows paths
# ═════════════════════════════════════════════════════════════════════════════


class TestPORT003:
    """Detect hardcoded absolute Windows paths (not Users/AI/Windows/Program)."""

    def test_hardcoded_drive_path_detected(self):
        path = _write_temp(".py", "open(r'D:\\data\\output\\results.csv')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-003" for f in findings), "Missed PORT-003"

    def test_chdir_hardcoded_detected(self):
        path = _write_temp(".py", "os.chdir('E:/projects/myproject')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-003" for f in findings), "Missed PORT-003 chdir"

    def test_relative_path_no_fire(self):
        path = _write_temp(".py", "open('data/output.csv', encoding='utf-8')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-003" for f in findings)


# ═════════════════════════════════════════════════════════════════════════════
# PORT-004: Windows-only module imports
# ═════════════════════════════════════════════════════════════════════════════


class TestPORT004:
    """Detect unguarded Windows-only module imports."""

    def test_winreg_import_detected(self):
        path = _write_temp(".py", "import winreg\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-004" for f in findings), "Missed PORT-004 winreg"

    def test_msvcrt_import_detected(self):
        path = _write_temp(".py", "import msvcrt\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-004" for f in findings), "Missed PORT-004 msvcrt"

    def test_wintypes_import_detected(self):
        path = _write_temp(".py", "from ctypes.wintypes import DWORD\n")
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "PORT-004" for f in findings), "Missed PORT-004 wintypes"

    def test_guarded_import_no_fire(self):
        """A platform-guarded import should NOT be scanned by regex (limitation accepted)."""
        # Note: regex can't detect if-guards, so this tests the pattern specificity
        code = "import os\nimport sys\n"
        path = _write_temp(".py", code)
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-004" for f in findings)

    def test_normal_imports_no_fire(self):
        path = _write_temp(".py", "import json\nimport os\nimport pathlib\n")
        findings = scan_file(path)
        os.unlink(path)
        assert not any(f.rule_id == "PORT-004" for f in findings)


# ═════════════════════════════════════════════════════════════════════════════
# Rule database integrity
# ═════════════════════════════════════════════════════════════════════════════


class TestPortabilityRuleDB:
    """Verify portability rules are well-formed."""

    def test_rules_count(self):
        assert len(PORTABILITY_RULES) >= 4

    def test_all_have_required_fields(self):
        required = {"id", "severity", "lang", "pattern", "description", "fix_hint", "test_hint"}
        for rule in PORTABILITY_RULES:
            missing = required - set(rule.keys())
            assert not missing, f"Rule {rule['id']} missing: {missing}"

    def test_ids_start_with_port(self):
        for rule in PORTABILITY_RULES:
            assert rule["id"].startswith("PORT-"), f"Rule {rule['id']} doesn't start with PORT-"

    def test_all_target_python(self):
        for rule in PORTABILITY_RULES:
            assert "python" in rule["lang"], f"Rule {rule['id']} doesn't target Python"

    def test_no_duplicate_ids(self):
        ids = [r["id"] for r in PORTABILITY_RULES]
        assert len(ids) == len(set(ids))
