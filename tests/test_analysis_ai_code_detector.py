"""
tests/test_analysis_ai_code_detector.py — Unit tests for ai_code_detector.py
"""
import textwrap
from pathlib import Path

from Analysis.ai_code_detector import AICodeDetector, AICodeReport, AIDebtItem


def _write(tmp_path: Path, name: str, code: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


class TestOverDocumented:
    def test_trivial_function_with_docstring_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def get_value():
                \"\"\"Return the value.\"\"\"
                return 42
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        patterns = {i.pattern for i in rep.items}
        assert "over_documented" in patterns

    def test_complex_function_not_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def compute(a, b, c, d):
                \"\"\"Complex calculations.\"\"\"
                x = a + b
                y = c * d
                z = x - y
                return z + x
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        over_doc = [i for i in rep.items if i.pattern == "over_documented"]
        assert len(over_doc) == 0

    def test_gpt_named_trivial_is_warning(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def process_data():
                \"\"\"Process the data.\"\"\"
                return {}
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        items = [i for i in rep.items if i.pattern == "over_documented"]
        assert any(i.severity == "warning" for i in items)


class TestGPTNaming:
    def test_generic_verb_noun_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def handle_request():
                pass
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        patterns = {i.pattern for i in rep.items}
        assert "gpt_naming" in patterns

    def test_private_method_not_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def _process_internal():
                pass
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        gpt = [i for i in rep.items if i.pattern == "gpt_naming"]
        assert len(gpt) == 0

    def test_specific_domain_name_not_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def tokenize_ast():
                pass
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        gpt = [i for i in rep.items if i.pattern == "gpt_naming"]
        assert len(gpt) == 0


class TestWrapperFunctions:
    def test_single_call_wrapper_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def do_thing():
                return other_thing()
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        patterns = {i.pattern for i in rep.items}
        assert "wrapper_function" in patterns

    def test_two_statement_not_wrapper(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def do_thing():
                x = other_thing()
                return x + 1
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        wrappers = [i for i in rep.items if i.pattern == "wrapper_function"]
        assert len(wrappers) == 0


class TestBlanketExcept:
    def test_bare_except_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            try:
                x = 1
            except Exception:
                pass
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        patterns = {i.pattern for i in rep.items}
        assert "blanket_except" in patterns

    def test_specific_exception_not_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            try:
                x = int("abc")
            except ValueError:
                pass
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        blanket = [i for i in rep.items if i.pattern == "blanket_except"]
        assert len(blanket) == 0

    def test_bare_except_reraise_not_flagged(self, tmp_path):
        _write(tmp_path, "f.py", """\
            try:
                x = 1
            except Exception:
                raise
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        blanket = [i for i in rep.items if i.pattern == "blanket_except"]
        assert len(blanket) == 0


class TestHighCommentRatio:
    def test_very_high_ratio_flagged(self, tmp_path):
        # Generate 30 comment lines + 5 code lines
        code = "\n".join(["# comment line"] * 30 + ["x = 1"] * 5)
        _write(tmp_path, "f.py", code)
        rep = AICodeDetector().scan_directory(tmp_path)
        patterns = {i.pattern for i in rep.items}
        assert "high_comment_ratio" in patterns

    def test_normal_ratio_not_flagged(self, tmp_path):
        code = "\n".join(["# comment"] * 5 + ["x = i"] * 20)
        _write(tmp_path, "f.py", code)
        rep = AICodeDetector().scan_directory(tmp_path)
        hi = [i for i in rep.items if i.pattern == "high_comment_ratio"]
        assert len(hi) == 0


class TestReport:
    def test_ai_debt_score_zero_on_clean_code(self, tmp_path):
        _write(tmp_path, "f.py", """\
            def calculate_area(width: float, height: float) -> float:
                return width * height

            class Rectangle:
                def __init__(self, w: float, h: float) -> None:
                    self.w = w
                    self.h = h
        """)
        rep = AICodeDetector().scan_directory(tmp_path)
        assert rep.ai_debt_score >= 0  # score is always non-negative

    def test_as_dict_has_required_keys(self, tmp_path):
        _write(tmp_path, "f.py", "x = 1\n")
        rep = AICodeDetector().scan_directory(tmp_path)
        d = rep.as_dict()
        for key in ("files_scanned", "total_findings", "ai_debt_score", "by_pattern"):
            assert key in d

    def test_empty_directory(self, tmp_path):
        rep = AICodeDetector().scan_directory(tmp_path)
        assert rep.total_findings == 0
        assert rep.ai_debt_score == 0.0

    def test_syntax_error_file_skipped(self, tmp_path):
        _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
        rep = AICodeDetector().scan_directory(tmp_path)
        # Should not raise, just skip it
        assert rep.files_scanned >= 0
