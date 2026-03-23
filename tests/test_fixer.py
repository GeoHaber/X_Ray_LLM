"""
X-Ray Fixer Tests
=================
Tests for xray/fixer.py: preview_fix, apply_fix, apply_fixes_bulk,
and individual rule-based fixers.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.fixer import FIXABLE_RULES, apply_fix, apply_fixes_bulk, preview_fix

# Sample source snippets keyed by rule_id, used for parametrized tests.
_RULE_SAMPLES = {
    "PY-005": "import json\ndata = json.loads(text)\n",
    "PY-007": "import os\nval = os.environ['SECRET_KEY']\n",
    "QUAL-001": "try:\n    x = 1\nexcept:\n    pass\n",
    "QUAL-003": "age = int(input('Enter age: '))\n",
    "QUAL-004": "price = float(input('Enter price: '))\n",
    "SEC-003": "import subprocess\nsubprocess.run(['ls'], shell=True)\n",
    "SEC-009": "import yaml\ndata = yaml.load(open('f.yml'))\n",
}

# Matched text and target line for each sample.
_RULE_FINDING = {
    "PY-005": {"line": 2, "matched_text": "json.loads(text)"},
    "PY-007": {"line": 2, "matched_text": "os.environ['SECRET_KEY']"},
    "QUAL-001": {"line": 3, "matched_text": "except:"},
    "QUAL-003": {"line": 1, "matched_text": "int(input("},
    "QUAL-004": {"line": 1, "matched_text": "float(input("},
    "SEC-003": {"line": 2, "matched_text": "shell=True"},
    "SEC-009": {"line": 2, "matched_text": "yaml.load("},
}


class TestFixer:
    """Tests for the xray.fixer module."""

    # ------------------------------------------------------------------
    # 1. Preview bare except (QUAL-001)
    # ------------------------------------------------------------------
    def test_preview_fix_qual001_bare_except(self, tmp_path):
        fp = tmp_path / "bare_except.py"
        fp.write_text("try:\n    x = 1\nexcept:\n    pass\n", encoding="utf-8")

        result = preview_fix(
            {
                "rule_id": "QUAL-001",
                "file": str(fp),
                "line": 3,
                "matched_text": "except:",
            }
        )

        assert result["fixable"] is True
        assert "except Exception:" in result["diff"]

    # ------------------------------------------------------------------
    # 2. Preview json.loads wrap (PY-005)
    # ------------------------------------------------------------------
    def test_preview_fix_py005_json_parse(self, tmp_path):
        fp = tmp_path / "json_parse.py"
        fp.write_text("import json\ndata = json.loads(text)\n", encoding="utf-8")

        result = preview_fix(
            {
                "rule_id": "PY-005",
                "file": str(fp),
                "line": 2,
                "matched_text": "json.loads(text)",
            }
        )

        assert result["fixable"] is True
        assert "try" in result["diff"]

    # ------------------------------------------------------------------
    # 3. Preview shell=True fix (SEC-003)
    # ------------------------------------------------------------------
    def test_preview_fix_sec003_shell_true(self, tmp_path):
        fp = tmp_path / "shell_true.py"
        fp.write_text(
            "import subprocess\nsubprocess.run(['ls'], shell=True)\n",
            encoding="utf-8",
        )

        result = preview_fix(
            {
                "rule_id": "SEC-003",
                "file": str(fp),
                "line": 2,
                "matched_text": "shell=True",
            }
        )

        assert result["fixable"] is True
        assert "shell=False" in result["diff"]

    # ------------------------------------------------------------------
    # 4. apply_fix writes the patched file
    # ------------------------------------------------------------------
    def test_apply_fix_writes_file(self, tmp_path):
        fp = tmp_path / "apply_bare.py"
        fp.write_text("try:\n    x = 1\nexcept:\n    pass\n", encoding="utf-8")

        result = apply_fix(
            {
                "rule_id": "QUAL-001",
                "file": str(fp),
                "line": 3,
                "matched_text": "except:",
            }
        )

        assert result["ok"] is True
        content = fp.read_text(encoding="utf-8")
        assert "except Exception:" in content

    # ------------------------------------------------------------------
    # 5. apply_fixes_bulk counts
    # ------------------------------------------------------------------
    def test_apply_fixes_bulk_counts(self, tmp_path):
        fp = tmp_path / "multi_bare.py"
        fp.write_text(
            "try:\n    a = 1\nexcept:\n    pass\n\ntry:\n    b = 2\nexcept:\n    pass\n",
            encoding="utf-8",
        )

        findings = [
            {"rule_id": "QUAL-001", "file": str(fp), "line": 8, "matched_text": "except:"},
            {"rule_id": "QUAL-001", "file": str(fp), "line": 3, "matched_text": "except:"},
        ]

        result = apply_fixes_bulk(findings)
        assert result["applied"] >= 1

    # ------------------------------------------------------------------
    # 6. Unknown rule returns not fixable
    # ------------------------------------------------------------------
    def test_preview_unknown_rule(self):
        result = preview_fix(
            {
                "rule_id": "UNKNOWN-999",
                "file": "x.py",
                "line": 1,
                "matched_text": "",
            }
        )

        assert result["fixable"] is False
        assert "No auto-fixer" in result["error"]

    # ------------------------------------------------------------------
    # 7. Missing file returns not fixable
    # ------------------------------------------------------------------
    def test_preview_missing_file(self):
        result = preview_fix(
            {
                "rule_id": "QUAL-001",
                "file": "/nonexistent/file.py",
                "line": 1,
                "matched_text": "except:",
            }
        )

        assert result["fixable"] is False

    # ------------------------------------------------------------------
    # 8. All fixable rules can preview without crashing
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("rule_id", sorted(FIXABLE_RULES))
    def test_all_fixable_rules_have_preview(self, tmp_path, rule_id):
        source = _RULE_SAMPLES[rule_id]
        fp = tmp_path / f"sample_{rule_id.replace('-', '_')}.py"
        fp.write_text(source, encoding="utf-8")

        info = _RULE_FINDING[rule_id]
        result = preview_fix(
            {
                "rule_id": rule_id,
                "file": str(fp),
                "line": info["line"],
                "matched_text": info["matched_text"],
            }
        )

        # Must not crash; result is a dict with expected keys
        assert isinstance(result, dict)
        assert "fixable" in result
        assert "diff" in result
        assert "error" in result
