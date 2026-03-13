"""
tests/test_analysis_quality_gate.py — Unit tests for Analysis/quality_gate.py
"""

import json

from Analysis.quality_gate import QualityGate


def _make_results(score=85, crit_smells=0, crit_sec=0, dup_groups=5):
    return {
        "grade": {"score": score, "letter": "B+"},
        "smells": {"critical": crit_smells, "warning": 3, "total": 10},
        "security": {"critical": crit_sec, "warning": 1},
        "duplicates": {"total_groups": dup_groups},
    }


def _gate(tmp_path, thresholds=None):
    settings = tmp_path / "xray_settings.json"
    base = {
        "gate": thresholds
        or {
            "min_score": 70,
            "max_critical_smells": 0,
            "max_critical_security": 0,
            "max_debt_hours": 80,
            "max_duplicate_groups": 20,
        }
    }
    settings.write_text(json.dumps(base), encoding="utf-8")
    return QualityGate(settings_path=settings)


class TestQualityGatePasses:
    def test_pass_all_green(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results())
        assert result.passed is True
        assert len(result.violations) == 0

    def test_pass_returns_correct_score(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(score=90))
        assert result.score == 90.0

    def test_pass_badge_checkmark(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results())
        assert "✅" in result.badge


class TestQualityGateFails:
    def test_fail_low_score(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(score=50))
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "min_score" in rules

    def test_fail_critical_smells(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(crit_smells=2))
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "max_critical_smells" in rules

    def test_fail_critical_security(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(crit_sec=1))
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "max_critical_security" in rules

    def test_fail_too_many_duplicates(self, tmp_path):
        gate = _gate(
            tmp_path,
            {
                "min_score": 0,
                "max_duplicate_groups": 3,
                "max_critical_smells": 99,
                "max_critical_security": 99,
            },
        )
        result = gate.evaluate(_make_results(dup_groups=10))
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "max_duplicate_groups" in rules

    def test_fail_badge_x(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(score=10))
        assert "❌" in result.badge

    def test_multiple_violations(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results(score=10, crit_smells=5, crit_sec=3))
        assert len(result.violations) >= 3


class TestQualityGateJSON:
    def test_write_json(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results())
        out = tmp_path / "gate.json"
        result.write_json(out)
        data = json.loads(out.read_text())
        assert "passed" in data
        assert "violations" in data
        assert "score" in data

    def test_as_dict_structure(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate.evaluate(_make_results())
        d = result.as_dict()
        for key in ("passed", "badge", "score", "grade", "violations", "thresholds"):
            assert key in d

    def test_default_thresholds_written_if_missing(self, tmp_path):
        settings = tmp_path / "xray_settings.json"
        settings.write_text("{}", encoding="utf-8")
        QualityGate(settings_path=settings)  # side-effect: writes defaults
        data = json.loads(settings.read_text())
        assert "gate" in data
        assert "min_score" in data["gate"]


class TestSATDGateRule:
    def test_fail_on_high_satd_hours(self, tmp_path):
        gate = _gate(
            tmp_path,
            {
                "min_score": 0,
                "max_debt_hours": 10,
                "max_critical_smells": 99,
                "max_critical_security": 99,
                "max_duplicate_groups": 99,
            },
        )

        class FakeSATD:
            total_hours = 50

        result = gate.evaluate(_make_results(), satd_summary=FakeSATD())
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "max_debt_hours" in rules

    def test_pass_on_acceptable_satd_hours(self, tmp_path):
        gate = _gate(tmp_path)

        class FakeSATD:
            total_hours = 10

        result = gate.evaluate(_make_results(), satd_summary=FakeSATD())
        assert result.passed is True
