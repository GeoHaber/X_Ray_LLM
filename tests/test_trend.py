"""
tests/test_trend.py — Tests for Analysis/trend.py (v6.0.0)
"""

import json
import pytest

from Analysis.trend import (
    compare_scans,
    format_grade_delta,
    load_prev_results,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def prev_scan():
    return {
        "grade": {"score": 85.0, "letter": "B"},
        "smells": {"total": 10, "critical": 2, "warning": 5, "info": 3},
        "duplicates": {"total_groups": 4, "total_functions_involved": 8},
        "lint": {"total": 20, "critical": 1, "warning": 10, "fixable": 5},
        "security": {"total": 3, "critical": 1, "warning": 2},
    }


@pytest.fixture()
def curr_scan():
    return {
        "grade": {"score": 88.5, "letter": "B+"},
        "smells": {"total": 7, "critical": 1, "warning": 4, "info": 2},
        "duplicates": {"total_groups": 3, "total_functions_involved": 6},
        "lint": {"total": 15, "critical": 0, "warning": 8, "fixable": 3},
        "security": {"total": 2, "critical": 0, "warning": 2},
    }


# ── compare_scans ──────────────────────────────────────────────────────────────


class TestCompareScans:
    def test_returns_empty_when_prev_none(self, curr_scan):
        assert compare_scans(None, curr_scan) == {}

    def test_returns_empty_when_prev_empty(self, curr_scan):
        assert compare_scans({}, curr_scan) == {}

    def test_grade_score_delta(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert delta["grade"]["score"] == pytest.approx(3.5, 0.01)

    def test_grade_letter_change(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert "letter" in delta["grade"]
        assert delta["grade"]["letter"] == "B→B+"

    def test_grade_no_letter_change_when_same(self, prev_scan):
        curr = dict(prev_scan)
        curr["grade"] = {"score": 85.0, "letter": "B"}
        delta = compare_scans(prev_scan, curr)
        assert "letter" not in delta.get("grade", {})

    def test_smells_delta_negative_means_improvement(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert delta["smells"]["total"] == -3  # 10 → 7
        assert delta["smells"]["critical"] == -1  # 2 → 1

    def test_duplicate_delta(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert delta["duplicates"]["total_groups"] == -1

    def test_lint_delta(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert delta["lint"]["total"] == -5
        assert delta["lint"]["critical"] == -1

    def test_security_delta(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        assert delta["security"]["critical"] == -1

    def test_missing_category_skipped(self, curr_scan):
        prev = {"grade": {"score": 80.0, "letter": "B-"}}
        delta = compare_scans(prev, curr_scan)
        assert "smells" not in delta  # prev has no smells key


# ── format_grade_delta ──────────────────────────────────────────────────────


class TestFormatGradeDelta:
    def test_positive_shows_up_arrow(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        line = format_grade_delta(delta)
        assert "▲" in line
        assert "+3.5" in line

    def test_negative_shows_down_arrow(self):
        prev = {"grade": {"score": 90.0, "letter": "A-"}}
        curr = {"grade": {"score": 87.5, "letter": "B+"}}
        delta = compare_scans(prev, curr)
        line = format_grade_delta(delta)
        assert "▼" in line
        assert "-2.5" in line

    def test_includes_letter_change(self, prev_scan, curr_scan):
        delta = compare_scans(prev_scan, curr_scan)
        line = format_grade_delta(delta)
        assert "B→B+" in line

    def test_empty_delta_returns_empty_string(self):
        assert format_grade_delta({}) == ""

    def test_delta_without_grade_returns_empty(self):
        assert format_grade_delta({"smells": {"total": -3}}) == ""


# ── load_prev_results ──────────────────────────────────────────────────────


class TestLoadPrevResults:
    def test_loads_valid_json(self, tmp_path, prev_scan):
        p = tmp_path / "prev.json"
        p.write_text(json.dumps(prev_scan), encoding="utf-8")
        loaded = load_prev_results(p)
        assert loaded == prev_scan

    def test_returns_none_for_missing_file(self, tmp_path):
        assert load_prev_results(tmp_path / "nonexistent.json") is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        assert load_prev_results(p) is None
