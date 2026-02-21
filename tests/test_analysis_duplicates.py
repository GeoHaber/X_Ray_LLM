"""
Tests for Analysis/duplicates.py — DuplicateFinder.
"""
import pytest
from Analysis.duplicates import DuplicateFinder, _func_to_dict, _is_valid_group
from tests.conftest import make_func as _func


# ════════════════════════════════════════════════════════════════════
#  Exact duplicates
# ════════════════════════════════════════════════════════════════════

class TestExactDuplicates:
    """Tests for exact duplicate detection."""

    def test_exact_cross_file(self):
        funcs = [
            _func(name="foo", file_path="a.py", code_hash="AAA"),
            _func(name="foo", file_path="b.py", code_hash="AAA"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs, cross_file_only=True)
        assert len(groups) == 1
        assert groups[0].similarity_type == "exact"
        assert groups[0].avg_similarity == 1.0

    def test_exact_same_file_cross_only(self):
        """Same file duplicates are ignored when cross_file_only=True."""
        funcs = [
            _func(name="a", file_path="x.py", code_hash="AAA"),
            _func(name="b", file_path="x.py", code_hash="AAA"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs, cross_file_only=True)
        assert len(groups) == 0

    def test_exact_same_file_allowed(self):
        """Same file duplicates ARE found when cross_file_only=False."""
        funcs = [
            _func(name="a", file_path="x.py", code_hash="AAA"),
            _func(name="b", file_path="x.py", code_hash="AAA"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs, cross_file_only=False)
        assert len(groups) == 1

    def test_no_duplicates(self):
        funcs = [
            _func(name="a", file_path="a.py", code_hash="H1", structure_hash="S1", code="x=1"),
            _func(name="b", file_path="b.py", code_hash="H2", structure_hash="S2", code="y=2"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        assert len(groups) == 0


# ════════════════════════════════════════════════════════════════════
#  Structural duplicates
# ════════════════════════════════════════════════════════════════════

class TestStructuralDuplicates:

    def test_structural_match(self):
        funcs = [
            _func(name="a", file_path="a.py", code_hash="H1", structure_hash="SAME", size_lines=10),
            _func(name="b", file_path="b.py", code_hash="H2", structure_hash="SAME", size_lines=10),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        structural = [g for g in groups if g.similarity_type == "structural"]
        assert len(structural) == 1

    def test_structural_skip_small_functions(self):
        """Functions < 4 lines are excluded from structural check."""
        funcs = [
            _func(name="a", file_path="a.py", code_hash="H1", structure_hash="SAME", size_lines=2),
            _func(name="b", file_path="b.py", code_hash="H2", structure_hash="SAME", size_lines=2),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        assert len(groups) == 0

    def test_structural_empty_hash_skipped(self):
        funcs = [
            _func(name="a", file_path="a.py", code_hash="H1", structure_hash="", size_lines=10, code="x=1"),
            _func(name="b", file_path="b.py", code_hash="H2", structure_hash="", size_lines=10, code="y=2"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        assert len(groups) == 0


# ════════════════════════════════════════════════════════════════════
#  Boilerplate skipping
# ════════════════════════════════════════════════════════════════════

class TestBoilerplateSkipping:

    @pytest.mark.parametrize("name", [
        "__init__", "__repr__", "__str__", "__eq__", "__hash__",
        "__len__", "__iter__", "__next__", "__enter__", "__exit__",
    ])
    def test_boilerplate_excluded(self, name):
        funcs = [
            _func(name=name, file_path="a.py", code_hash="SAME"),
            _func(name=name, file_path="b.py", code_hash="SAME"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        assert len(groups) == 0


# ════════════════════════════════════════════════════════════════════
#  _is_valid_group / _func_to_dict
# ════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_single_function_not_valid(self):
        assert _is_valid_group([_func()], cross_file=True) is False

    def test_func_to_dict_keys(self):
        d = _func_to_dict(_func(name="bar", file_path="x.py", line_start=5))
        assert "key" in d
        assert "name" in d
        assert d["name"] == "bar"
        assert "file" in d
        assert "line" in d


# ════════════════════════════════════════════════════════════════════
#  Edge cases
# ════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Tests for edge cases in duplicate detection."""

    def test_empty_input(self):
        finder = DuplicateFinder()
        groups = finder.find([])
        assert groups == []

    def test_single_function(self):
        finder = DuplicateFinder()
        groups = finder.find([_func()])
        assert groups == []

    def test_three_way_duplicate(self):
        funcs = [
            _func(name="a", file_path="a.py", code_hash="SAME"),
            _func(name="b", file_path="b.py", code_hash="SAME"),
            _func(name="c", file_path="c.py", code_hash="SAME"),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs)
        assert len(groups) == 1
        assert len(groups[0].functions) == 3

    def test_groups_get_incrementing_ids(self):
        funcs = [
            _func(name="a", file_path="a.py", code_hash="H1", structure_hash="S1", size_lines=10),
            _func(name="b", file_path="b.py", code_hash="H1", structure_hash="S1", size_lines=10),
            _func(name="c", file_path="c.py", code_hash="H2", structure_hash="S2", size_lines=10),
            _func(name="d", file_path="d.py", code_hash="H3", structure_hash="S2", size_lines=10),
        ]
        finder = DuplicateFinder()
        groups = finder.find(funcs, cross_file_only=True)
        ids = [g.group_id for g in groups]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)  # all unique
