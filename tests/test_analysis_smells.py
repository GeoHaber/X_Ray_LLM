"""
Tests for Analysis/smells.py — CodeSmellDetector.
"""

from unittest.mock import MagicMock
from Core.types import Severity
from Core.config import SMELL_THRESHOLDS
from Analysis.smells import CodeSmellDetector
from tests.conftest import make_func as _func, make_cls as _cls


# ════════════════════════════════════════════════════════════════════
#  Long function
# ════════════════════════════════════════════════════════════════════


class TestLongFunction:
    def test_no_smell_under_threshold(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=30)], [])
        assert len(det.smells) == 0

    def test_warning_at_threshold(self):
        t = SMELL_THRESHOLDS["long_function"]
        det = CodeSmellDetector()
        det.check([_func(size_lines=t)], [])
        long = [s for s in det.smells if s.category == "long-function"]
        assert len(long) == 1
        assert long[0].severity == Severity.WARNING

    def test_critical_at_very_long(self):
        t = SMELL_THRESHOLDS["very_long_function"]
        det = CodeSmellDetector()
        det.check([_func(size_lines=t)], [])
        long = [s for s in det.smells if s.category == "long-function"]
        assert len(long) == 1
        assert long[0].severity == Severity.CRITICAL


# ════════════════════════════════════════════════════════════════════
#  Deep nesting
# ════════════════════════════════════════════════════════════════════


class TestDeepNesting:
    def test_no_smell(self):
        det = CodeSmellDetector()
        det.check([_func(nesting_depth=2)], [])
        assert len([s for s in det.smells if s.category == "deep-nesting"]) == 0

    def test_warning(self):
        t = SMELL_THRESHOLDS["deep_nesting"]
        det = CodeSmellDetector()
        det.check([_func(nesting_depth=t)], [])
        nesting = [s for s in det.smells if s.category == "deep-nesting"]
        assert len(nesting) == 1
        assert nesting[0].severity == Severity.WARNING

    def test_critical(self):
        t = SMELL_THRESHOLDS["very_deep_nesting"]
        det = CodeSmellDetector()
        det.check([_func(nesting_depth=t)], [])
        nesting = [s for s in det.smells if s.category == "deep-nesting"]
        assert len(nesting) == 1
        assert nesting[0].severity == Severity.CRITICAL


# ════════════════════════════════════════════════════════════════════
#  High complexity
# ════════════════════════════════════════════════════════════════════


class TestHighComplexity:
    def test_no_smell(self):
        det = CodeSmellDetector()
        det.check([_func(complexity=3)], [])
        assert len([s for s in det.smells if s.category == "complex-function"]) == 0

    def test_warning(self):
        t = SMELL_THRESHOLDS["high_complexity"]
        det = CodeSmellDetector()
        det.check([_func(complexity=t)], [])
        cx = [s for s in det.smells if s.category == "complex-function"]
        assert len(cx) == 1
        assert cx[0].severity == Severity.WARNING

    def test_critical(self):
        t = SMELL_THRESHOLDS["very_high_complexity"]
        det = CodeSmellDetector()
        det.check([_func(complexity=t)], [])
        cx = [s for s in det.smells if s.category == "complex-function"]
        assert len(cx) == 1
        assert cx[0].severity == Severity.CRITICAL


# ════════════════════════════════════════════════════════════════════
#  Too many params
# ════════════════════════════════════════════════════════════════════


class TestTooManyParams:
    def test_no_smell(self):
        det = CodeSmellDetector()
        det.check([_func(parameters=["a", "b"])], [])
        assert len([s for s in det.smells if s.category == "too-many-params"]) == 0

    def test_warning(self):
        t = SMELL_THRESHOLDS["too_many_params"]
        params = [f"p{i}" for i in range(t)]
        det = CodeSmellDetector()
        det.check([_func(parameters=params)], [])
        tp = [s for s in det.smells if s.category == "too-many-params"]
        assert len(tp) == 1
        assert tp[0].severity == Severity.WARNING


# ════════════════════════════════════════════════════════════════════
#  Class smells
# ════════════════════════════════════════════════════════════════════


class TestClassSmells:
    def test_god_class(self):
        t = SMELL_THRESHOLDS["god_class"]
        det = CodeSmellDetector()
        det.check([], [_cls(method_count=t)])
        gc = [s for s in det.smells if s.category == "god-class"]
        assert len(gc) == 1
        assert gc[0].severity == Severity.CRITICAL

    def test_large_class(self):
        t = SMELL_THRESHOLDS["large_class"]
        det = CodeSmellDetector()
        det.check([], [_cls(size_lines=t)])
        lc = [s for s in det.smells if s.category == "large-class"]
        assert len(lc) == 1
        assert lc[0].severity == Severity.WARNING

    def test_clean_class(self):
        det = CodeSmellDetector()
        det.check([], [_cls(method_count=3, size_lines=50)])
        assert len(det.smells) == 0


# ════════════════════════════════════════════════════════════════════
#  Multiple smells at once
# ════════════════════════════════════════════════════════════════════


class TestMultipleSmells:
    def test_function_triggers_multiple(self):
        """A function can trigger long + complex + deep nesting simultaneously."""
        det = CodeSmellDetector()
        det.check(
            [
                _func(
                    size_lines=200,
                    nesting_depth=8,
                    complexity=25,
                    parameters=[f"p{i}" for i in range(10)],
                )
            ],
            [],
        )
        cats = {s.category for s in det.smells}
        assert "long-function" in cats
        assert "deep-nesting" in cats
        assert "complex-function" in cats
        assert "too-many-params" in cats

    def test_check_resets_smells(self):
        """Calling check() again resets the smells list."""
        det = CodeSmellDetector()
        det.check([_func(size_lines=200)], [])
        assert len(det.smells) > 0
        det.check([], [])
        assert len(det.smells) == 0


# ════════════════════════════════════════════════════════════════════
#  SmellIssue fields
# ════════════════════════════════════════════════════════════════════


class TestSmellIssueFields:
    def test_metric_value_correct(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=100)], [])
        assert det.smells[0].metric_value == 100

    def test_name_populated(self):
        det = CodeSmellDetector()
        det.check([_func(name="my_big_fn", size_lines=100)], [])
        assert det.smells[0].name == "my_big_fn"

    def test_message_contains_function_name(self):
        det = CodeSmellDetector()
        det.check([_func(name="process", size_lines=100)], [])
        assert "process" in det.smells[0].message

    def test_suggestion_nonempty(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=100)], [])
        assert len(det.smells[0].suggestion) > 0


# ════════════════════════════════════════════════════════════════════
#  enrich_with_llm
# ════════════════════════════════════════════════════════════════════


class TestEnrichWithLLM:
    """Tests for LLM enrichment of code smells."""

    def test_enriches_critical_smells(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=200)], [])
        mock_llm = MagicMock()
        mock_llm.query_sync.return_value = "Use extract-method refactoring."
        det.enrich_with_llm(mock_llm, max_calls=5)
        assert det.smells[0].llm_analysis == "Use extract-method refactoring."

    def test_respects_max_calls(self):
        det = CodeSmellDetector()
        funcs = [_func(name=f"f{i}", size_lines=100) for i in range(10)]
        det.check(funcs, [])
        mock_llm = MagicMock()
        mock_llm.query_sync.return_value = "fix it"
        det.enrich_with_llm(mock_llm, max_calls=3)
        assert mock_llm.query_sync.call_count == 3

    def test_handles_llm_exception(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=200)], [])
        mock_llm = MagicMock()
        mock_llm.query_sync.side_effect = RuntimeError("LLM down")
        det.enrich_with_llm(mock_llm, max_calls=5)
        # Should not crash, llm_analysis remains empty
        assert det.smells[0].llm_analysis == ""

    def test_no_critical_smells_skips_llm(self):
        det = CodeSmellDetector()
        det.check([], [])  # no smells
        mock_llm = MagicMock()
        det.enrich_with_llm(mock_llm)
        mock_llm.query_sync.assert_not_called()


# ════════════════════════════════════════════════════════════════════
#  Missing docstring
# ════════════════════════════════════════════════════════════════════


class TestMissingDocstring:
    def test_flagged_for_large_public_function(self):
        det = CodeSmellDetector()
        det.check([_func(name="process", size_lines=20, docstring=None)], [])
        cats = [s.category for s in det.smells]
        assert "missing-docstring" in cats

    def test_not_flagged_for_private_function(self):
        det = CodeSmellDetector()
        det.check([_func(name="_helper", size_lines=20, docstring=None)], [])
        cats = [s.category for s in det.smells]
        assert "missing-docstring" not in cats

    def test_not_flagged_for_small_function(self):
        det = CodeSmellDetector()
        det.check([_func(name="small", size_lines=5, docstring=None)], [])
        cats = [s.category for s in det.smells]
        assert "missing-docstring" not in cats


# ════════════════════════════════════════════════════════════════════
#  Boolean blindness
# ════════════════════════════════════════════════════════════════════


class TestBooleanBlindness:
    def test_flagged_without_prefix(self):
        det = CodeSmellDetector()
        det.check([_func(name="process", return_type="bool")], [])
        cats = [s.category for s in det.smells]
        assert "boolean-blindness" in cats

    def test_not_flagged_with_is_prefix(self):
        det = CodeSmellDetector()
        det.check([_func(name="is_valid", return_type="bool")], [])
        cats = [s.category for s in det.smells]
        assert "boolean-blindness" not in cats

    def test_not_flagged_with_has_prefix(self):
        det = CodeSmellDetector()
        det.check([_func(name="has_items", return_type="bool")], [])
        cats = [s.category for s in det.smells]
        assert "boolean-blindness" not in cats


# ════════════════════════════════════════════════════════════════════
#  Too many returns / branches & class smells
# ════════════════════════════════════════════════════════════════════


class TestReturnsBranches:
    def test_too_many_returns(self):
        t = SMELL_THRESHOLDS["too_many_returns"]
        det = CodeSmellDetector()
        det.check([_func(return_count=t)], [])
        cats = [s.category for s in det.smells]
        assert "too-many-returns" in cats

    def test_too_many_branches(self):
        t = SMELL_THRESHOLDS["too_many_branches"]
        det = CodeSmellDetector()
        det.check([_func(branch_count=t)], [])
        cats = [s.category for s in det.smells]
        assert "too-many-branches" in cats


class TestClassSmellsExtended:
    def test_dataclass_candidate(self):
        det = CodeSmellDetector()
        det.check([], [_cls(method_count=2, base_classes=[], has_init=True)])
        cats = [s.category for s in det.smells]
        assert "dataclass-candidate" in cats

    def test_dataclass_not_flagged_with_base(self):
        det = CodeSmellDetector()
        det.check([], [_cls(method_count=2, base_classes=["BaseModel"], has_init=True)])
        cats = [s.category for s in det.smells]
        assert "dataclass-candidate" not in cats

    def test_missing_class_docstring(self):
        det = CodeSmellDetector()
        det.check([], [_cls(size_lines=50, docstring=None)])
        cats = [s.category for s in det.smells]
        assert "missing-class-docstring" in cats

    def test_missing_class_docstring_not_flagged_small(self):
        det = CodeSmellDetector()
        det.check([], [_cls(size_lines=20, docstring=None)])
        cats = [s.category for s in det.smells]
        assert "missing-class-docstring" not in cats


# ════════════════════════════════════════════════════════════════════
#  Summary
# ════════════════════════════════════════════════════════════════════


class TestSmellSummary:
    def test_summary_structure(self):
        det = CodeSmellDetector()
        det.check([_func(size_lines=200)], [])
        s = det.summary()
        assert "total" in s
        assert "critical" in s
        assert "by_category" in s
        assert "worst_files" in s
        assert s["total"] > 0

    def test_summary_empty(self):
        det = CodeSmellDetector()
        det.check([], [])
        s = det.summary()
        assert s["total"] == 0
